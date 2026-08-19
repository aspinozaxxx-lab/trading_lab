"""Zagruzka besplatnogo rynochnogo konteksta iz oficial'nogo MOEX ISS."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

CONTEXT_INTERVAL_MINUTES = 10  # Chislovoi kod desyatiminutnoi svechi ISS.
CONTEXT_PAGE_SIZE = 500  # Bezopasnyi razmer odnoi stranicy ISS.
CONTEXT_USER_AGENT = "market-lab-research/0.4 (MOEX ISS)"  # Identifikator klienta.
CONTEXT_SIGNAL_MINUTE = 18 * 60 + 50  # Dostupnost' daily-context posle bara 18:40.
CONTEXT_INSTRUMENTS = (  # Zafiksirovannyi nabor obshcherynochnyh indikatorov.
    ("IMOEX", "stock", "index", "SNDX"),
    ("RVI", "stock", "index", "SNDX"),
    ("RGBI", "stock", "index", "SNDX"),
    ("CNYRUB_TOM", "currency", "selt", "CETS"),
)


@dataclass(frozen=True)
class ContextInstrument:
    """Opisyvaet odin instrument i ego marshrut v ISS."""

    ticker: str
    engine: str
    market: str
    board: str

    @property
    def endpoint(self) -> str:
        """Vozvrashchaet board-specific endpoint svechei."""
        return (
            "https://iss.moex.com/iss/engines/"
            f"{self.engine}/markets/{self.market}/boards/{self.board}/"
            f"securities/{self.ticker}/candles.json"
        )


DEFAULT_CONTEXT_SPECS = tuple(  # Tipizirovannye specifikacii konteksta.
    ContextInstrument(*values) for values in CONTEXT_INSTRUMENTS
)


@dataclass(frozen=True)
class ContextDownloadResult:
    """Hranit audit-metadannye zagruzhennogo kontekstnogo ryada."""

    ticker: str
    rows: int
    pages: int
    first_timestamp: str
    last_timestamp: str
    parquet_path: str
    raw_path: str
    sha256: str
    cached: bool


def parse_context_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """Normalizuet ISS candles i dopuskaet pustye volume/value u FX i indeksov."""
    candles = payload.get("candles")
    if not isinstance(candles, dict):
        raise ValueError("Otvet ISS ne soderzhit obekt candles")
    columns = candles.get("columns")
    rows = candles.get("data")
    required = {"open", "high", "low", "close", "begin"}
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("Otvet ISS soderzhit nekorrektnyi candles-blok")
    missing = required - set(columns)
    if missing:
        raise ValueError(f"V context candles net kolonok: {sorted(missing)}")
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "value"]
        ).rename_axis("timestamp")
    timestamp = pd.to_datetime(frame["begin"], errors="raise")
    if timestamp.dt.tz is None:
        timestamp = timestamp.dt.tz_localize("Europe/Moscow")
    timestamp = timestamp.dt.tz_convert("UTC")
    normalized = pd.DataFrame(index=pd.DatetimeIndex(timestamp, name="timestamp"))
    for column in ("open", "high", "low", "close"):
        normalized[column] = pd.to_numeric(frame[column], errors="raise").to_numpy()
    for column in ("volume", "value"):
        values = frame[column] if column in frame else pd.Series(0.0, index=frame.index)
        normalized[column] = pd.to_numeric(values, errors="coerce").fillna(0.0).to_numpy()
    normalized = normalized.sort_index().loc[
        lambda value: ~value.index.duplicated(keep="last")
    ]
    if normalized.empty or normalized[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("Context candles pusty ili soderzhat propuski cen")
    if (normalized[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise ValueError("Context candles soderzhat nepolozhitel'nye ceny")
    upper = normalized[["open", "close", "low"]].max(axis=1)
    lower = normalized[["open", "close", "high"]].min(axis=1)
    if (normalized["high"] < upper).any() or (normalized["low"] > lower).any():
        raise ValueError("Context candles narushayut OHLC-invariant")
    return normalized


def _context_paths(
    raw_root: Path,
    processed_root: Path,
    spec: ContextInstrument,
    start: date,
    end: date,
) -> tuple[Path, Path]:
    """Stroit stabil'nye puti syrogo i Parquet-kesha."""
    stem = f"{spec.ticker}_{spec.board}_10m_{start.isoformat()}_{end.isoformat()}"
    raw = raw_root / "sequence_context" / f"{stem}.jsonl.gz"
    parquet = processed_root / "sequence_context" / f"{stem}.parquet"
    return raw, parquet


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 faila potokovo."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet kontekstnyi Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _request_context_page(
    session: requests.Session,
    spec: ContextInstrument,
    start_date: date,
    end_date: date,
    offset: int,
    timeout_seconds: int,
    max_retries: int,
) -> dict[str, Any]:
    """Chitaet odnu ISS-stranicu s ogranichennym exponential backoff."""
    parameters = {
        "from": start_date.isoformat(),
        "till": end_date.isoformat(),
        "interval": CONTEXT_INTERVAL_MINUTES,
        "start": offset,
        "limit": CONTEXT_PAGE_SIZE,
        "iss.meta": "off",
        "iss.only": "candles",
    }
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = session.get(spec.endpoint, params=parameters, timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("ISS vernul ne JSON-obekt")
            parse_context_payload(payload)
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt == max_retries:
                break
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(
        f"Ne udalos zagruzit context {spec.ticker} start={offset}: {last_error}"
    ) from last_error


def download_context_instrument(
    raw_root: Path,
    processed_root: Path,
    spec: ContextInstrument,
    start_date: date,
    end_date: date,
    timeout_seconds: int = 30,
    max_retries: int = 4,
) -> ContextDownloadResult:
    """Zagruzhaet ili proveriaet odin kontekstnyi ryad bez global'nyh izmenenii."""
    raw_path, parquet_path = _context_paths(
        raw_root, processed_root, spec, start_date, end_date
    )
    if raw_path.exists() and parquet_path.exists():
        cached = pd.read_parquet(parquet_path)
        if cached.empty:
            raise ValueError(f"Pustoi context-kesh: {parquet_path}")
        return ContextDownloadResult(
            ticker=spec.ticker,
            rows=len(cached),
            pages=-1,
            first_timestamp=cached.index.min().isoformat(),
            last_timestamp=cached.index.max().isoformat(),
            parquet_path=str(parquet_path),
            raw_path=str(raw_path),
            sha256=_sha256_file(parquet_path),
            cached=True,
        )
    session = requests.Session()
    session.headers.update({"User-Agent": CONTEXT_USER_AGENT})
    pages: list[dict[str, Any]] = []
    frames: list[pd.DataFrame] = []
    offset = 0
    try:
        while True:
            payload = _request_context_page(
                session,
                spec,
                start_date,
                end_date,
                offset,
                timeout_seconds,
                max_retries,
            )
            rows = payload["candles"]["data"]
            if rows:
                pages.append(payload)
                frames.append(parse_context_payload(payload))
            if len(rows) < CONTEXT_PAGE_SIZE:
                break
            offset += len(rows)
            time.sleep(0.03)
    finally:
        session.close()
    if not frames:
        raise ValueError(f"ISS ne vernul context candles dlya {spec.ticker}")
    frame = pd.concat(frames).sort_index()
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    raw_lines = b"".join(
        json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for page in pages
    )
    atomic_write_bytes(raw_path, gzip.compress(raw_lines, compresslevel=6, mtime=0))
    _atomic_write_parquet(parquet_path, frame)
    return ContextDownloadResult(
        ticker=spec.ticker,
        rows=len(frame),
        pages=len(pages),
        first_timestamp=frame.index.min().isoformat(),
        last_timestamp=frame.index.max().isoformat(),
        parquet_path=str(parquet_path),
        raw_path=str(raw_path),
        sha256=_sha256_file(parquet_path),
        cached=False,
    )


def download_default_context(
    raw_root: Path,
    processed_root: Path,
    start_date: date,
    end_date: date,
) -> Path:
    """Zagruzhaet zafiksirovannyi context-nabor i sohranyaet manifest."""
    results = [
        download_context_instrument(
            raw_root,
            processed_root,
            spec,
            start_date,
            end_date,
        )
        for spec in DEFAULT_CONTEXT_SPECS
    ]
    manifest = processed_root / "sequence_context" / "manifest.json"
    write_json(
        manifest,
        {
            "source": "official anonymous MOEX ISS",
            "requested_period": [start_date.isoformat(), end_date.isoformat()],
            "results": [asdict(result) for result in results],
        },
    )
    return manifest


def load_daily_context(
    processed_root: Path,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Agregiruet zakeshirovannyi context do causal dnevnyh close-priznakov."""
    parts: list[pd.DataFrame] = []
    for spec in DEFAULT_CONTEXT_SPECS:
        _, path = _context_paths(
            processed_root.parent / "raw",
            processed_root,
            spec,
            start_date,
            end_date,
        )
        if not path.exists():
            raise FileNotFoundError(f"Net context-kesha dlya {spec.ticker}: {path}")
        frame = pd.read_parquet(path)
        local = frame.index.tz_convert("Europe/Moscow")
        main = frame.loc[(local.hour * 60 + local.minute) <= 18 * 60 + 40].copy()
        main["local_date"] = pd.to_datetime(main.index.tz_convert("Europe/Moscow").date)
        daily = main.groupby("local_date").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        close = daily["close"]
        context = pd.DataFrame(index=daily.index)
        for lag in (1, 5, 20, 60):
            context[f"ctx_{spec.ticker.lower()}_ret_{lag}"] = close.pct_change(lag)
        context[f"ctx_{spec.ticker.lower()}_vol_20"] = close.pct_change().rolling(20).std()
        available_at = (
            context.index.tz_localize("Europe/Moscow")
            + pd.Timedelta(minutes=CONTEXT_SIGNAL_MINUTE)
        ).tz_convert("UTC")
        context.index = available_at
        context.index.name = "available_at"
        parts.append(context)
    return pd.concat(parts, axis=1).sort_index()
