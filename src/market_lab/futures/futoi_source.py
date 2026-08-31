"""Download target-free pre-2026 MOEX FUTOI with immutable raw provenance."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

import numpy as np
import pandas as pd
import requests

from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SOURCE_START: Final[pd.Timestamp] = pd.Timestamp("2020-05-01")
SOURCE_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
MOSCOW_TIMEZONE: Final[str] = "Europe/Moscow"
TICKERS: Final[tuple[str, ...]] = ("Si", "RI", "BR", "MX")
TICKER_TO_ASSET: Final[dict[str, str]] = {
    "Si": "SI",
    "RI": "RI",
    "BR": "BR",
    "MX": "MIX",
}
CLIENT_GROUPS: Final[frozenset[str]] = frozenset({"FIZ", "YUR"})
ISS_ROOT: Final[str] = (
    "https://iss.moex.com/iss/analyticalproducts/futoi/securities"
)
ISS_COLUMNS: Final[tuple[str, ...]] = (
    "sess_id",
    "seqnum",
    "tradedate",
    "tradetime",
    "ticker",
    "clgroup",
    "pos",
    "pos_long",
    "pos_short",
    "pos_long_num",
    "pos_short_num",
    "systime",
)
DELIVERY_BUFFER: Final[pd.Timedelta] = pd.Timedelta(minutes=1)
USER_AGENT: Final[str] = "market-lab-futoi-source/1.0 (MOEX ISS research)"
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT / "data/processed/info_radar/moex-futoi-dev-2020-2025-v1"
)


class ResponseLike(Protocol):
    """Minimal requests-compatible response for real and synthetic sessions."""

    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class SessionLike(Protocol):
    """Minimal requests-compatible session."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _table(payload: Mapping[str, Any]) -> pd.DataFrame:
    block = payload.get("futoi")
    if not isinstance(block, Mapping):
        raise ValueError("MOEX FUTOI payload lacks futoi")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("invalid MOEX FUTOI table")
    normalized = [str(column).lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate MOEX FUTOI columns")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("malformed MOEX FUTOI row")
    return pd.DataFrame(rows, columns=normalized)


def _source_periods() -> tuple[tuple[pd.Timestamp, pd.Timestamp], ...]:
    periods: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for year in range(SOURCE_START.year, SOURCE_END.year + 1):
        start = max(SOURCE_START, pd.Timestamp(year=year, month=1, day=1))
        end = min(SOURCE_END, pd.Timestamp(year=year, month=12, day=31))
        periods.append((start, end))
    return tuple(periods)


def _request_url(
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> str:
    if ticker not in TICKERS:
        raise ValueError(f"unsupported sealed FUTOI ticker: {ticker}")
    if end_date >= PROTECTED_FROM:
        raise ValueError("MOEX FUTOI request could cross the protected boundary")
    if start_date < SOURCE_START or end_date > SOURCE_END:
        raise ValueError("MOEX FUTOI request escaped sealed bounds")
    if start_date > end_date:
        raise ValueError("MOEX FUTOI request could cross the protected boundary")
    query = urlencode(
        {
            "from": start_date.date().isoformat(),
            "till": end_date.date().isoformat(),
            "latest": 1,
            "iss.meta": "off",
            "iss.only": "futoi",
            "futoi.columns": ",".join(ISS_COLUMNS),
        }
    )
    url = f"{ISS_ROOT}/{ticker.lower()}.json?{query}"
    parsed = parse_qs(urlparse(url).query)
    if pd.Timestamp(parsed["till"][0]) >= PROTECTED_FROM:
        raise ValueError("MOEX FUTOI URL contains a protected till value")
    return url


def _request_json(
    session: SessionLike,
    url: str,
    *,
    attempts: int = 5,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=60.0)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX FUTOI response is not an object")
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    raise RuntimeError(f"MOEX FUTOI request failed: {url}: {last_error}") from last_error


def fetch_futoi_period(
    session: SessionLike,
    ticker: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    *,
    request_delay_seconds: float = 0.0,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Read one bounded official latest-per-date response for one ticker-year."""
    url = _request_url(ticker, start_date, end_date)
    payload = _request_json(session, url)
    frame = _table(payload)
    if set(frame.columns) != set(ISS_COLUMNS):
        raise ValueError("MOEX FUTOI response escaped the requested closed schema")
    maximum_rows = 2 * ((end_date - start_date).days + 1)
    if len(frame) > maximum_rows or len(frame) > 1000:
        raise ValueError("MOEX FUTOI latest=1 response exceeds its provable period bound")
    key_columns = ["tradedate", "ticker", "clgroup"]
    if frame.duplicated(key_columns).any():
        raise ValueError("MOEX FUTOI latest=1 contains duplicate date/ticker/group rows")
    if request_delay_seconds > 0.0:
        time.sleep(request_delay_seconds)
    return frame, [{"request_url": url, "payload": payload}]


def _integer_series(values: pd.Series, label: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    if numeric.isna().any() or not np.isfinite(numeric).all():
        raise ValueError(f"MOEX FUTOI {label} must be finite")
    if not np.allclose(numeric, np.round(numeric), rtol=0.0, atol=0.0):
        raise ValueError(f"MOEX FUTOI {label} must be integer-valued")
    return numeric.astype("int64")


def normalize_futoi_history(frame: pd.DataFrame, expected_ticker: str) -> pd.DataFrame:
    """Validate paired client positioning and exact conservative availability."""
    required = set(ISS_COLUMNS)
    if missing := required - set(frame.columns):
        raise ValueError(f"MOEX FUTOI history lacks columns: {sorted(missing)}")
    output = frame.loc[:, list(ISS_COLUMNS)].copy()
    output = output.rename(
        columns={
            "tradedate": "source_date",
            "tradetime": "source_time",
            "clgroup": "client_group",
            "pos": "net_position",
            "pos_long": "long_position",
            "pos_short": "short_position",
            "pos_long_num": "long_accounts",
            "pos_short_num": "short_accounts",
            "systime": "published_at_moscow",
        }
    )
    output["source_date"] = pd.to_datetime(
        output["source_date"], errors="raise"
    ).dt.normalize()
    if output["source_date"].lt(SOURCE_START).any() or output["source_date"].gt(
        SOURCE_END
    ).any():
        raise ValueError("MOEX FUTOI history escaped the development interval")
    if output["source_date"].ge(PROTECTED_FROM).any():
        raise ValueError("MOEX FUTOI history contains a protected 2026+ source date")
    source_clock = output["source_time"].astype("string")
    observed = pd.to_datetime(
        output["source_date"].dt.strftime("%Y-%m-%d") + " " + source_clock,
        errors="raise",
    )
    published = pd.to_datetime(output["published_at_moscow"], errors="raise")
    if published.dt.tz is not None:
        raise ValueError("MOEX FUTOI systime unexpectedly contains a timezone")
    if published.ge(PROTECTED_FROM).any() or published.lt(observed).any():
        raise ValueError("MOEX FUTOI publication time is noncausal or protected")
    output["observed_at"] = observed.dt.tz_localize(MOSCOW_TIMEZONE).dt.tz_convert("UTC")
    output["published_at"] = published.dt.tz_localize(MOSCOW_TIMEZONE).dt.tz_convert(
        "UTC"
    )
    output["available_at"] = output["published_at"] + DELIVERY_BUFFER
    protected_utc = PROTECTED_FROM.tz_localize(MOSCOW_TIMEZONE).tz_convert("UTC")
    if output["available_at"].ge(protected_utc).any():
        raise ValueError("MOEX FUTOI conservative availability crosses 2026")
    if not output["ticker"].astype("string").eq(expected_ticker).all():
        raise ValueError("MOEX FUTOI endpoint returned another ticker")
    output["client_group"] = output["client_group"].astype("string").str.upper()
    if not set(output["client_group"].dropna().unique()) <= CLIENT_GROUPS:
        raise ValueError("MOEX FUTOI returned an unknown client group")
    for column in (
        "sess_id",
        "seqnum",
        "net_position",
        "long_position",
        "short_position",
        "long_accounts",
        "short_accounts",
    ):
        output[column] = _integer_series(output[column], column)
    if output[["sess_id", "seqnum", "long_accounts", "short_accounts"]].lt(0).any().any():
        raise ValueError("MOEX FUTOI identifiers and account counts must be nonnegative")
    if output["long_position"].lt(0).any() or output["short_position"].gt(0).any():
        raise ValueError("MOEX FUTOI long/short position signs are invalid")
    if not output["net_position"].eq(
        output["long_position"] + output["short_position"]
    ).all():
        raise ValueError("MOEX FUTOI net position identity failed")
    point_keys = ["ticker", "source_date", "source_time"]
    if output.duplicated(point_keys + ["client_group"]).any():
        raise ValueError("MOEX FUTOI contains duplicate ticker/time/group rows")
    grouped = output.groupby(point_keys, sort=False, observed=True)
    if grouped["client_group"].nunique().ne(2).any():
        raise ValueError("MOEX FUTOI point lacks the FIZ/YUR pair")
    if grouped["sess_id"].nunique().ne(1).any() or grouped["seqnum"].nunique().ne(1).any():
        raise ValueError("MOEX FUTOI paired rows disagree on session identity")
    output["reported_pair_net_imbalance"] = grouped["net_position"].transform("sum")
    reported_pair_gross = grouped["long_position"].transform("sum") + grouped[
        "short_position"
    ].transform("sum").abs()
    output["reported_pair_balance_ratio"] = (
        output["reported_pair_net_imbalance"].abs()
        / reported_pair_gross.where(reported_pair_gross.gt(0), 1)
    )
    output["reported_pair_balance_exact"] = output[
        "reported_pair_net_imbalance"
    ].eq(0)
    output["asset_code"] = output["ticker"].map(TICKER_TO_ASSET).astype("string")
    output["availability_rule"] = "official_systime_plus_one_minute_delivery_buffer"
    output["provider"] = "MOEX ISS FUTOI"
    output["contains_prices_returns_targets_or_pnl"] = False
    output["current_vintage_snapshot"] = True
    ordered_columns = (
        "source_date",
        "source_time",
        "observed_at",
        "published_at_moscow",
        "published_at",
        "available_at",
        "ticker",
        "asset_code",
        "client_group",
        "sess_id",
        "seqnum",
        "net_position",
        "long_position",
        "short_position",
        "long_accounts",
        "short_accounts",
        "reported_pair_net_imbalance",
        "reported_pair_balance_ratio",
        "reported_pair_balance_exact",
        "availability_rule",
        "provider",
        "contains_prices_returns_targets_or_pnl",
        "current_vintage_snapshot",
    )
    return output.loc[:, ordered_columns].sort_values(
        ["available_at", "ticker", "client_group"],
        kind="mergesort",
        ignore_index=True,
    )


def _write_raw_record(stream: gzip.GzipFile, record: dict[str, Any]) -> None:
    stream.write(_canonical_json(record) + b"\n")


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download_futoi_source(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
    request_delay_seconds: float = 0.02,
) -> Path:
    """Write a new immutable FUTOI snapshot and never overwrite an existing one."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"MOEX FUTOI output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    processed_rows = 0
    request_count = 0
    processed_chunks: list[pd.DataFrame] = []
    ticker_rows = {ticker: 0 for ticker in TICKERS}
    raw_path = temporary / "official_moex_iss_pages.jsonl.gz"
    try:
        network_session: SessionLike = session or requests.Session()
        with raw_path.open("wb") as raw_file, gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_file, compresslevel=6, mtime=0
        ) as raw_stream:
            for ticker in TICKERS:
                for start_date, end_date in _source_periods():
                    raw, archive = fetch_futoi_period(
                        network_session,
                        ticker,
                        start_date,
                        end_date,
                        request_delay_seconds=request_delay_seconds,
                    )
                    for record in archive:
                        _write_raw_record(raw_stream, record)
                    request_count += len(archive)
                    if raw.empty:
                        continue
                    normalized = normalize_futoi_history(raw, ticker)
                    processed_rows += len(normalized)
                    ticker_rows[ticker] += len(normalized)
                    processed_chunks.append(normalized)
        if processed_rows == 0 or any(rows == 0 for rows in ticker_rows.values()):
            raise ValueError("MOEX FUTOI did not cover every sealed ticker")
        daily = pd.concat(processed_chunks, ignore_index=True).sort_values(
            ["source_date", "ticker", "client_group"],
            kind="mergesort",
            ignore_index=True,
        )
        if daily.duplicated(["source_date", "ticker", "client_group"]).any():
            raise ValueError("MOEX FUTOI daily-last aggregation contains duplicates")
        daily_path = temporary / "futoi_daily_last.parquet"
        _atomic_parquet(daily_path, daily)
        fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-futoi-current-vintage-2020-2025-v1",
            "provider": "MOEX ISS FUTOI",
            "official_endpoint": ISS_ROOT,
            "fetched_at_utc": fetched_at,
            "request_count": request_count,
            "requested_tickers": list(TICKERS),
            "ticker_to_asset": TICKER_TO_ASSET,
            "rows_by_ticker": ticker_rows,
            "access_observation": {
                "authentication_used": False,
                "http_response": "successful_during_snapshot",
                "subscription_language_in_official_documentation": True,
                "redistribution_rights_assessed": False,
                "raw_redistribution_allowed": False,
            },
            "request_bounds": {
                "from": SOURCE_START.date().isoformat(),
                "till": SOURCE_END.date().isoformat(),
                "protected_from": PROTECTED_FROM.date().isoformat(),
                "all_request_till_values_before_protected_from": True,
                "closed_response_columns": list(ISS_COLUMNS),
                "official_sampling_parameter": "latest=1",
            },
            "temporal_semantics": {
                "source_timestamp": "tradedate plus tradetime in Europe/Moscow",
                "published_timestamp": "official systime in Europe/Moscow",
                "available_at": "official systime plus one minute, converted to UTC",
                "admissible_join": "available_at at or before decision timestamp",
                "current_vintage_snapshot": True,
                "historical_revision_archive_proved": False,
                "contains_prices_returns_targets_or_pnl": False,
                "full_intraday_history_downloaded": False,
                "reported_pair_balance": (
                    "source values preserved; no assumption that FIZ plus YUR net is zero"
                ),
            },
            "artifacts": {
                "processed_daily_last": {
                    "path": daily_path.name,
                    "bytes": daily_path.stat().st_size,
                    "sha256": sha256_file(daily_path),
                    "rows": len(daily),
                    "minimum_source_date": daily["source_date"].min().date().isoformat(),
                    "maximum_source_date": daily["source_date"].max().date().isoformat(),
                    "columns": daily.columns.tolist(),
                    "nonzero_reported_pair_dates": int(
                        daily.loc[
                            ~daily["reported_pair_balance_exact"],
                            ["source_date", "ticker"],
                        ].drop_duplicates().shape[0]
                    ),
                    "maximum_reported_pair_balance_ratio": float(
                        daily["reported_pair_balance_ratio"].max()
                    ),
                },
                "raw_archive": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "requests": request_count,
                    "format": "one canonical JSON request/payload record per gzip line",
                },
            },
        }
        manifest_identity = hashlib.sha256(_canonical_json(manifest_core)).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": manifest_identity},
        )
        manifest_sha = sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    print(download_futoi_source(arguments.output_directory))


if __name__ == "__main__":
    main()
