"""Adapter svechei MOEX ISS i ego polnostyu lokalnyi analog."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from market_lab.config import DataConfig
from market_lab.io_utils import TEXT_ENCODING

LOGGER = logging.getLogger(__name__)  # Logger adaptera MOEX.
MOEX_INTERVALS = {  # Sootvetstvie timeframe parametru ISS.
    "10m": 10,
    "1h": 60,
    "1d": 24,
}
REQUIRED_COLUMNS = {  # Obyazatelnye polya odnogo candles-otveta.
    "open",
    "close",
    "high",
    "low",
    "value",
    "volume",
    "begin",
    "end",
}


@dataclass(frozen=True)
class MarketDataBundle:
    """Hranit normalizovannye svechi, syrye stranicy i metadannye."""

    frame: pd.DataFrame
    raw_pages: list[dict[str, Any]]
    metadata: dict[str, Any]


def parse_moex_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """Preobrazuet odin JSON-otvet ISS v proverennuyu tablicu svechei."""
    candles = payload.get("candles")
    if not isinstance(candles, dict):
        raise ValueError("Otvet MOEX ne soderzhit obekt candles")
    columns = candles.get("columns")
    rows = candles.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("Otvet MOEX soderzhit nekorrektnuyu strukturu candles")
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise ValueError(f"V otvete MOEX net kolonok: {sorted(missing)}")
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume", "value"]
        ).set_index("timestamp")
    timestamp = pd.to_datetime(frame["begin"], errors="raise")
    if timestamp.dt.tz is None:
        timestamp = timestamp.dt.tz_localize("Europe/Moscow")
    timestamp = timestamp.dt.tz_convert("UTC")
    normalized = pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": pd.to_numeric(frame["open"], errors="raise"),
            "high": pd.to_numeric(frame["high"], errors="raise"),
            "low": pd.to_numeric(frame["low"], errors="raise"),
            "close": pd.to_numeric(frame["close"], errors="raise"),
            "volume": pd.to_numeric(frame["volume"], errors="raise"),
            "value": pd.to_numeric(frame["value"], errors="raise"),
        }
    ).set_index("timestamp")
    return validate_market_frame(normalized)


def validate_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet svechi i proveriaet bazovye rynochnye invarianty."""
    required = ["open", "high", "low", "close", "volume", "value"]
    if any(column not in frame.columns for column in required):
        raise ValueError("Normalizovannye dannye ne soderzhat vse OHLCV-kolonki")
    result = frame.loc[:, required].sort_index()
    result = result.loc[~result.index.duplicated(keep="last")]
    if result.empty:
        raise ValueError("Nabor rynochnyh dannyh pust")
    if result.index.tz is None:
        raise ValueError("Vremennoi indeks dolzhen byt timezone-aware")
    if result[required].isna().any().any():
        raise ValueError("Rynochnye dannye soderzhat propuski")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Ceny dolzhny byt polozhitelnymi")
    if (result[["volume", "value"]] < 0).any().any():
        raise ValueError("Obem i oborot ne mogut byt otricatelnymi")
    upper_bound = result[["open", "close", "low"]].max(axis=1)
    lower_bound = result[["open", "close", "high"]].min(axis=1)
    if (result["high"] < upper_bound).any() or (result["low"] > lower_bound).any():
        raise ValueError("Narushen OHLC-invariant high/low")
    if not result.index.is_monotonic_increasing:
        raise ValueError("Vremennoi indeks ne otsortirovan")
    return result


class MoexIssSource:
    """Zagruzhaet vse stranicy svechei iz MOEX ISS."""

    def __init__(self, config: DataConfig, session: requests.Session | None = None) -> None:
        """Sohranyaet konfiguraciyu i pozvolyaet vnedrit testovuyu sessiyu."""
        self.config = config
        self.session = session or requests.Session()

    @property
    def endpoint(self) -> str:
        """Formiruet board-specific HTTPS endpoint bez parametrov zaprosa."""
        base = "https://iss.moex.com/iss"
        return (
            f"{base}/engines/{self.config.engine}/markets/{self.config.market}"
            f"/boards/{self.config.board}/securities/{self.config.instrument}/candles.json"
        )

    def _request_page(self, start: int) -> dict[str, Any]:
        """Zaprashivaet odnu stranicu s ogranichennymi povtorami."""
        parameters = {
            "from": self.config.start.isoformat(),
            "till": self.config.end.isoformat(),
            "interval": MOEX_INTERVALS[self.config.timeframe],
            "start": start,
            "iss.meta": "off",
            "iss.only": "candles",
        }
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.get(
                    self.endpoint,
                    params=parameters,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("MOEX vernul ne JSON-obekt")
                return payload
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt >= self.config.max_retries:
                    break
                delay = min(2**attempt, 4)
                LOGGER.warning("Povtor zaprosa MOEX cherez %s s: %s", delay, error)
                time.sleep(delay)
        raise RuntimeError(f"Ne udalos zagruzit MOEX: {last_error}") from last_error

    def load(self) -> MarketDataBundle:
        """Zagruzhaet svechi postranichno i obedinyaet ih bez dublikatov."""
        pages: list[dict[str, Any]] = []
        frames: list[pd.DataFrame] = []
        start = 0
        while True:
            payload = self._request_page(start)
            pages.append(payload)
            candles = payload.get("candles", {})
            raw_rows = candles.get("data", []) if isinstance(candles, dict) else []
            if raw_rows:
                frames.append(parse_moex_payload(payload))
            if len(raw_rows) < self.config.page_size:
                break
            start += len(raw_rows)
        if not frames:
            raise ValueError("MOEX ne vernul svechi dlya zadannogo perioda")
        frame = validate_market_frame(pd.concat(frames))
        metadata = {
            "source": "moex",
            "endpoint": self.endpoint,
            "instrument": self.config.instrument,
            "board": self.config.board,
            "timeframe": self.config.timeframe,
            "start": self.config.start.isoformat(),
            "end": self.config.end.isoformat(),
            "pages": len(pages),
            "rows": len(frame),
        }
        return MarketDataBundle(frame=frame, raw_pages=pages, metadata=metadata)


class FixtureSource:
    """Chitaet lokalnyi fixture v tom zhe formate, chto i MOEX ISS."""

    def __init__(self, config: DataConfig) -> None:
        """Sohranyaet konfiguraciyu bez inicializacii setevyh obektov."""
        self.config = config

    def load(self) -> MarketDataBundle:
        """Chitaet odnu ili neskolko zafiksirovannyh stranic JSON."""
        with self.config.fixture_path.open("r", encoding=TEXT_ENCODING) as stream:
            document = json.load(stream)
        pages = document.get("pages") if isinstance(document, dict) else None
        if pages is None:
            pages = [document]
        if not isinstance(pages, list) or not pages:
            raise ValueError("Fixture ne soderzhit stranicy MOEX")
        frames = [parse_moex_payload(page) for page in pages]
        frame = validate_market_frame(pd.concat(frames))
        metadata = {
            "source": "fixture",
            "fixture": str(self.config.fixture_path),
            "instrument": self.config.instrument,
            "board": self.config.board,
            "timeframe": self.config.timeframe,
            "pages": len(pages),
            "rows": len(frame),
        }
        return MarketDataBundle(frame=frame, raw_pages=pages, metadata=metadata)
