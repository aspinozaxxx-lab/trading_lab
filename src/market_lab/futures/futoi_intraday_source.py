"""Acquire full target-free pre-2026 MOEX FUTOI with truncation proofs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from market_lab.futures import futoi_source as daily_source
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SOURCE_START: pd.Timestamp = pd.Timestamp("2020-05-01")
SOURCE_END: pd.Timestamp = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
TICKERS: tuple[str, ...] = daily_source.TICKERS
MAX_RESPONSE_ROWS: Final[int] = 1_000
DEFAULT_MAX_WORKERS: Final[int] = 4
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/moex-futoi-intraday-dev-2020-2025-v1"
)
DEFAULT_STAGING: Final[Path] = DEFAULT_OUTPUT.with_name(f".{DEFAULT_OUTPUT.name}.staging")
USER_AGENT: Final[str] = "market-lab-futoi-intraday-source/1.0 (MOEX ISS research)"
COMPARISON_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "source_time",
    "ticker",
    "client_group",
    "sess_id",
    "seqnum",
    "net_position",
    "long_position",
    "short_position",
    "long_accounts",
    "short_accounts",
    "published_at_moscow",
)

_THREAD_LOCAL = threading.local()


@dataclass(frozen=True, slots=True)
class IntradayJob:
    """One provably bounded single-ticker, single-source-date request."""

    ticker: str
    source_date: pd.Timestamp

    @property
    def key(self) -> str:
        return f"{self.ticker}:{self.source_date.date().isoformat()}"


def _source_periods() -> tuple[tuple[pd.Timestamp, pd.Timestamp], ...]:
    periods: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for year in range(SOURCE_START.year, SOURCE_END.year + 1):
        start = max(SOURCE_START, pd.Timestamp(year=year, month=1, day=1))
        end = min(SOURCE_END, pd.Timestamp(year=year, month=12, day=31))
        periods.append((start, end))
    return tuple(periods)


def _intraday_request_url(ticker: str, source_date: pd.Timestamp) -> str:
    date = pd.Timestamp(source_date).normalize()
    if ticker not in TICKERS:
        raise ValueError(f"unsupported FUTOI intraday ticker: {ticker}")
    if date < SOURCE_START or date > SOURCE_END or date >= PROTECTED_FROM:
        raise ValueError("FUTOI intraday request escaped the sealed pre-2026 bounds")
    query = urlencode(
        {
            "from": date.date().isoformat(),
            "till": date.date().isoformat(),
            "iss.meta": "off",
            "iss.only": "futoi",
            "futoi.columns": ",".join(daily_source.ISS_COLUMNS),
        }
    )
    url = f"{daily_source.ISS_ROOT}/{ticker.lower()}.json?{query}"
    parsed = parse_qs(urlparse(url).query)
    if "latest" in parsed or "start" in parsed:
        raise ValueError("FUTOI intraday URL unexpectedly requests a sample or offset")
    if parsed["from"] != parsed["till"]:
        raise ValueError("FUTOI intraday request is not bounded to one source date")
    if pd.Timestamp(parsed["till"][0]) >= PROTECTED_FROM:
        raise ValueError("FUTOI intraday URL contains a protected till value")
    return url


def _worker_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_LOCAL.session = session
    return session


def _request_json(
    url: str,
    *,
    session: daily_source.SessionLike | None = None,
    attempts: int = 7,
) -> dict[str, Any]:
    network_session = session or _worker_session()
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = network_session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX FUTOI intraday response is not an object")
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.25 * (2**attempt)))
    raise RuntimeError(f"MOEX FUTOI intraday request failed: {url}: {last_error}") from last_error


def _raw_intraday_frame(payload: dict[str, Any]) -> pd.DataFrame:
    frame = daily_source._table(payload)
    if set(frame.columns) != set(daily_source.ISS_COLUMNS):
        raise ValueError("MOEX FUTOI intraday response escaped the closed schema")
    if len(frame) >= MAX_RESPONSE_ROWS:
        raise ValueError(
            "MOEX FUTOI intraday response reached the 1000-row cap and is unproved"
        )
    return frame


def fetch_intraday_day(
    ticker: str,
    source_date: pd.Timestamp,
    *,
    session: daily_source.SessionLike | None = None,
    request_delay_seconds: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch one date; fail closed instead of accepting a possibly truncated response."""
    date = pd.Timestamp(source_date).normalize()
    url = _intraday_request_url(ticker, date)
    payload = _request_json(url, session=session)
    frame = _raw_intraday_frame(payload)
    if frame.empty:
        raise ValueError(f"MOEX FUTOI intraday planned date returned no rows: {ticker} {date}")
    if request_delay_seconds > 0.0:
        time.sleep(request_delay_seconds)
    return frame, {
        "request_kind": "intraday_single_ticker_single_date",
        "ticker": ticker,
        "source_date": date.date().isoformat(),
        "request_url": url,
        "payload": payload,
    }


def verify_intraday_day(
    frame: pd.DataFrame,
    ticker: str,
    source_date: pd.Timestamp,
    *,
    daily_latest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Verify pair identity, exact date and equality to official daily-last proof."""
    date = pd.Timestamp(source_date).normalize()
    if len(frame) >= MAX_RESPONSE_ROWS:
        raise ValueError("FUTOI intraday day can be truncated at the response cap")
    normalized = daily_source.normalize_futoi_history(frame, ticker)
    if normalized.empty or not normalized["source_date"].eq(date).all():
        raise ValueError("FUTOI intraday response escaped its exact requested date")
    keys = ["source_date", "source_time", "ticker", "client_group"]
    if normalized.duplicated(keys).any():
        raise ValueError("FUTOI intraday day contains duplicate point/group keys")
    point_groups = normalized.groupby(
        ["source_date", "source_time", "ticker"], observed=True
    )["client_group"].nunique()
    if point_groups.ne(2).any():
        raise ValueError("FUTOI intraday point lacks an exact FIZ/YUR pair")
    if daily_latest is not None:
        proof = daily_latest.loc[
            daily_latest["source_date"].eq(date)
            & daily_latest["ticker"].astype("string").eq(ticker)
        ].copy()
        if len(proof) != 2:
            raise ValueError("FUTOI daily-last proof is missing the planned ticker/date pair")
        last_time = normalized["available_at"].max()
        last = normalized.loc[normalized["available_at"].eq(last_time)].copy()
        if len(last) != 2:
            raise ValueError("FUTOI intraday day has no unique final paired point")
        left = last.loc[:, COMPARISON_COLUMNS].sort_values(
            "client_group", kind="mergesort", ignore_index=True
        )
        right = proof.loc[:, COMPARISON_COLUMNS].sort_values(
            "client_group", kind="mergesort", ignore_index=True
        )
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_like=False)
    return normalized


def _discovery_url(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    if ticker not in TICKERS:
        raise ValueError(f"unsupported FUTOI discovery ticker: {ticker}")
    if start < SOURCE_START or end > SOURCE_END or end >= PROTECTED_FROM:
        raise ValueError("FUTOI discovery escaped sealed pre-2026 bounds")
    query = urlencode(
        {
            "from": start.date().isoformat(),
            "till": end.date().isoformat(),
            "latest": 1,
            "iss.meta": "off",
            "iss.only": "futoi",
            "futoi.columns": ",".join(daily_source.ISS_COLUMNS),
        }
    )
    return f"{daily_source.ISS_ROOT}/{ticker.lower()}.json?{query}"


def discover_daily_latest(
    *,
    session: daily_source.SessionLike | None = None,
    request_delay_seconds: float = 0.0,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Discover exact trading dates from bounded official latest-per-date requests."""
    chunks: list[pd.DataFrame] = []
    archive: list[dict[str, Any]] = []
    for ticker in TICKERS:
        for start, end in _source_periods():
            url = _discovery_url(ticker, start, end)
            payload = _request_json(url, session=session)
            raw = daily_source._table(payload)
            if set(raw.columns) != set(daily_source.ISS_COLUMNS):
                raise ValueError("FUTOI discovery response escaped the closed schema")
            maximum_rows = 2 * ((end - start).days + 1)
            if len(raw) > maximum_rows or len(raw) >= MAX_RESPONSE_ROWS:
                raise ValueError("FUTOI discovery response is unbounded or truncated")
            archive.append(
                {
                    "request_kind": "daily_latest_calendar_discovery",
                    "ticker": ticker,
                    "from": start.date().isoformat(),
                    "till": end.date().isoformat(),
                    "request_url": url,
                    "payload": payload,
                }
            )
            if not raw.empty:
                chunks.append(daily_source.normalize_futoi_history(raw, ticker))
            if request_delay_seconds > 0.0:
                time.sleep(request_delay_seconds)
    if not chunks:
        raise ValueError("MOEX FUTOI daily-last discovery returned no rows")
    latest = pd.concat(chunks, ignore_index=True).sort_values(
        ["source_date", "ticker", "client_group"],
        kind="mergesort",
        ignore_index=True,
    )
    keys = ["source_date", "ticker", "client_group"]
    if latest.duplicated(keys).any():
        raise ValueError("FUTOI daily-last discovery contains duplicate keys")
    grouped = latest.groupby(["source_date", "ticker"], observed=True)
    if grouped["client_group"].nunique().ne(2).any():
        raise ValueError("FUTOI daily-last discovery lacks a FIZ/YUR pair")
    return latest, archive


def _stage_path(staging: Path, job: IntradayJob) -> Path:
    return staging / "pages" / job.ticker / f"{job.source_date.date().isoformat()}.json.gz"


def _record_bytes(record: dict[str, Any]) -> bytes:
    return daily_source._canonical_json(record) + b"\n"


def _write_stage_record(path: Path, record: dict[str, Any]) -> None:
    atomic_write_bytes(path, gzip.compress(_record_bytes(record), compresslevel=6, mtime=0))


def _read_stage_record(path: Path) -> dict[str, Any]:
    value = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(value, dict):
        raise ValueError(f"invalid staged FUTOI record: {path}")
    return value


def _record_frame(record: dict[str, Any], job: IntradayJob) -> pd.DataFrame:
    if (
        record.get("request_kind") != "intraday_single_ticker_single_date"
        or record.get("ticker") != job.ticker
        or record.get("source_date") != job.source_date.date().isoformat()
        or record.get("request_url") != _intraday_request_url(job.ticker, job.source_date)
        or not isinstance(record.get("payload"), dict)
    ):
        raise ValueError(f"staged FUTOI record identity mismatch: {job.key}")
    return _raw_intraday_frame(record["payload"])


def _plan_core(
    jobs: list[IntradayJob],
    discovery_archive: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_id": "official-moex-futoi-intraday-current-vintage-2020-2025-v1",
        "source_start": SOURCE_START.date().isoformat(),
        "source_end": SOURCE_END.date().isoformat(),
        "protected_from": PROTECTED_FROM.date().isoformat(),
        "tickers": list(TICKERS),
        "jobs": [job.key for job in jobs],
        "discovery_archive_sha256": hashlib.sha256(
            daily_source._canonical_json(discovery_archive)
        ).hexdigest(),
    }


def _ensure_stage_plan(staging: Path, plan: dict[str, Any]) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / "plan.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8-sig"))
        if existing != plan:
            raise ValueError("FUTOI intraday staging plan identity changed")
    else:
        write_json(path, plan)


def _fetch_stage_job(
    job: IntradayJob,
    staging: Path,
    daily_latest: pd.DataFrame,
    *,
    session: daily_source.SessionLike | None,
    request_delay_seconds: float,
) -> bool:
    path = _stage_path(staging, job)
    proof = daily_latest.loc[
        daily_latest["source_date"].eq(job.source_date)
        & daily_latest["ticker"].astype("string").eq(job.ticker)
    ]
    if path.exists():
        record = _read_stage_record(path)
        raw = _record_frame(record, job)
        verify_intraday_day(raw, job.ticker, job.source_date, daily_latest=proof)
        return False
    raw, record = fetch_intraday_day(
        job.ticker,
        job.source_date,
        session=session,
        request_delay_seconds=request_delay_seconds,
    )
    verify_intraday_day(raw, job.ticker, job.source_date, daily_latest=proof)
    _write_stage_record(path, record)
    return True


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": daily_source.sha256_file(path),
    }
    if rows is not None:
        result["rows"] = rows
    return result


def _assemble_output(
    final: Path,
    staging: Path,
    jobs: list[IntradayJob],
    daily_latest: pd.DataFrame,
    discovery_archive: list[dict[str, Any]],
    *,
    fetched_at_utc: str,
    network_requests_this_run: int,
) -> Path:
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    raw_path = temporary / "official_moex_iss_pages.jsonl.gz"
    intraday_path = temporary / "futoi_intraday.parquet"
    coverage_path = temporary / "coverage.parquet"
    latest_path = temporary / "futoi_daily_latest_proof.parquet"
    writer: pq.ParquetWriter | None = None
    batch: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    rows_by_ticker = {ticker: 0 for ticker in TICKERS}
    point_count = 0
    total_rows = 0
    try:
        with raw_path.open("wb") as raw_file, gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_file, compresslevel=6, mtime=0
        ) as raw_stream:
            for record in discovery_archive:
                raw_stream.write(_record_bytes(record))
            for index, job in enumerate(jobs, start=1):
                record = _read_stage_record(_stage_path(staging, job))
                raw = _record_frame(record, job)
                proof = daily_latest.loc[
                    daily_latest["source_date"].eq(job.source_date)
                    & daily_latest["ticker"].astype("string").eq(job.ticker)
                ]
                normalized = verify_intraday_day(
                    raw,
                    job.ticker,
                    job.source_date,
                    daily_latest=proof,
                )
                raw_stream.write(_record_bytes(record))
                batch.append(normalized)
                rows_by_ticker[job.ticker] += len(normalized)
                total_rows += len(normalized)
                points = normalized[["source_date", "source_time", "ticker"]].drop_duplicates()
                point_count += len(points)
                coverage_rows.append(
                    {
                        "source_date": job.source_date,
                        "ticker": job.ticker,
                        "asset_code": daily_source.TICKER_TO_ASSET[job.ticker],
                        "rows": len(normalized),
                        "paired_points": len(points),
                        "minimum_observed_at": normalized["observed_at"].min(),
                        "maximum_observed_at": normalized["observed_at"].max(),
                        "maximum_available_at": normalized["available_at"].max(),
                        "response_below_1000_row_cap": len(normalized) < MAX_RESPONSE_ROWS,
                        "daily_latest_pair_matched": True,
                    }
                )
                if len(batch) >= 64 or index == len(jobs):
                    frame = pd.concat(batch, ignore_index=True)
                    table = pa.Table.from_pandas(frame, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            intraday_path,
                            table.schema,
                            compression="zstd",
                        )
                    elif table.schema != writer.schema:
                        table = table.cast(writer.schema)
                    writer.write_table(table, row_group_size=100_000)
                    batch.clear()
        if writer is None:
            raise ValueError("FUTOI intraday assembly produced no rows")
        writer.close()
        writer = None
        coverage = pd.DataFrame(coverage_rows).sort_values(
            ["source_date", "ticker"], kind="mergesort", ignore_index=True
        )
        if len(coverage) != len(jobs) or not coverage[
            "response_below_1000_row_cap"
        ].all():
            raise ValueError("FUTOI intraday coverage proof is incomplete")
        _atomic_parquet(coverage_path, coverage)
        _atomic_parquet(latest_path, daily_latest)
        parquet = pq.ParquetFile(intraday_path)
        if parquet.metadata.num_rows != total_rows:
            raise ValueError("FUTOI intraday Parquet row count drift")
        parquet_columns = parquet.schema_arrow.names
        parquet.close()
        raw_requests = len(discovery_archive) + len(jobs)
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-futoi-intraday-current-vintage-2020-2025-v1",
            "provider": "MOEX ISS FUTOI",
            "official_endpoint": daily_source.ISS_ROOT,
            "fetched_at_utc": fetched_at_utc,
            "request_count": raw_requests,
            "network_requests_this_run": network_requests_this_run,
            "discovery_request_count": len(discovery_archive),
            "single_date_intraday_request_count": len(jobs),
            "requested_tickers": list(TICKERS),
            "ticker_to_asset": daily_source.TICKER_TO_ASSET,
            "rows_by_ticker": rows_by_ticker,
            "paired_intraday_points": point_count,
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
                "closed_response_columns": list(daily_source.ISS_COLUMNS),
                "discovery_sampling_parameter": "latest=1",
                "intraday_sampling_parameter": None,
                "intraday_request_unit": "one_ticker_one_source_date",
                "maximum_rows_per_response": MAX_RESPONSE_ROWS,
                "response_equal_to_cap_policy": "fail_closed_as_possibly_truncated",
                "offset_pagination_used": False,
            },
            "temporal_semantics": {
                "source_timestamp": "tradedate plus tradetime in Europe/Moscow",
                "published_timestamp": "official systime in Europe/Moscow",
                "available_at": "official systime plus one minute, converted to UTC",
                "admissible_intraday_join": "available_at at or before decision timestamp",
                "current_vintage_snapshot": True,
                "historical_revision_archive_proved": False,
                "contains_prices_returns_targets_or_pnl": False,
                "full_intraday_history_downloaded": True,
                "daily_completeness_proof": (
                    "response below 1000-row cap and final pair equals official latest=1"
                ),
            },
            "artifacts": {
                "processed_intraday": {
                    **_artifact(intraday_path, rows=total_rows),
                    "minimum_source_date": coverage["source_date"]
                    .min()
                    .date()
                    .isoformat(),
                    "maximum_source_date": coverage["source_date"]
                    .max()
                    .date()
                    .isoformat(),
                    "columns": parquet_columns,
                },
                "daily_latest_proof": _artifact(latest_path, rows=len(daily_latest)),
                "coverage": _artifact(coverage_path, rows=len(coverage)),
                "raw_archive": {
                    **_artifact(raw_path),
                    "requests": raw_requests,
                    "format": "one canonical JSON request/payload record per gzip line",
                },
            },
        }
        manifest_identity = hashlib.sha256(
            daily_source._canonical_json(manifest_core)
        ).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": manifest_identity},
        )
        manifest_sha = daily_source.sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        if writer is not None:
            writer.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def download_futoi_intraday_source(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    staging_directory: Path | None = None,
    session: daily_source.SessionLike | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    request_delay_seconds: float = 0.05,
    fetched_at_utc: str | None = None,
) -> Path:
    """Build a resumable full intraday snapshot, then publish one immutable bundle."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"MOEX FUTOI intraday output already exists: {final}")
    if max_workers < 1 or max_workers > 16:
        raise ValueError("FUTOI intraday max_workers must be in 1..16")
    if session is not None and max_workers != 1:
        raise ValueError("an injected session requires max_workers=1")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = (staging_directory or final.with_name(f".{final.name}.staging")).resolve()
    if staging == final or staging.is_relative_to(final):
        raise ValueError("FUTOI intraday staging must be outside the immutable final path")

    daily_latest, discovery_archive = discover_daily_latest(
        session=session,
        request_delay_seconds=request_delay_seconds,
    )
    job_keys = daily_latest.loc[:, ["ticker", "source_date"]].drop_duplicates()
    jobs = [
        IntradayJob(str(row.ticker), pd.Timestamp(row.source_date).normalize())
        for row in job_keys.sort_values(
            ["ticker", "source_date"], kind="mergesort"
        ).itertuples(index=False)
    ]
    if not jobs or len({job.key for job in jobs}) != len(jobs):
        raise ValueError("FUTOI intraday discovery produced an invalid job plan")
    plan = _plan_core(jobs, discovery_archive)
    _ensure_stage_plan(staging, plan)

    def execute(job: IntradayJob) -> bool:
        return _fetch_stage_job(
            job,
            staging,
            daily_latest,
            session=session,
            request_delay_seconds=request_delay_seconds,
        )

    network_requests = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for fetched in executor.map(execute, jobs):
            network_requests += int(fetched)
            completed += 1
            if completed % 500 == 0 or completed == len(jobs):
                print(
                    json.dumps(
                        {
                            "milestone": "futoi_intraday_stage",
                            "completed": completed,
                            "total": len(jobs),
                            "network_requests_this_run": network_requests,
                        }
                    ),
                    flush=True,
                )
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _assemble_output(
        final,
        staging,
        jobs,
        daily_latest,
        discovery_archive,
        fetched_at_utc=fetched_at,
        network_requests_this_run=network_requests + len(discovery_archive),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--staging-directory", type=Path, default=None)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--request-delay-seconds", type=float, default=0.05)
    arguments = parser.parse_args()
    print(
        download_futoi_intraday_source(
            arguments.output_directory,
            staging_directory=arguments.staging_directory,
            max_workers=arguments.max_workers,
            request_delay_seconds=arguments.request_delay_seconds,
        )
    )


if __name__ == "__main__":
    main()
