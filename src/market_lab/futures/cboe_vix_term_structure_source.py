"""Acquire bounded FRED-distributed Cboe VIX/VIX3M daily closes."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import math
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from io import StringIO
from pathlib import Path
from typing import Final, Protocol
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SOURCE_START: Final[date] = date(2018, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
CHICAGO: Final[ZoneInfo] = ZoneInfo("America/Chicago")
FRED_HOST: Final[str] = "fred.stlouisfed.org"
FRED_SERIES: Final[dict[str, str]] = {
    "VIXCLS": "vix_close",
    "VXVCLS": "vix3m_close",
}
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/"
    "fred-cboe-vix-term-structure-current-vintage-2018-2025-v2"
)
USER_AGENT: Final[str] = "curl/8.10.1"
MAX_CSV_BYTES: Final[int] = 2 * 1024 * 1024
_SAFE_SNAPSHOT_ID: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
)


class ResponseLike(Protocol):
    """Minimal requests-compatible response used by production and tests."""

    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    """Minimal requests-compatible session used by production and tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class _UrllibResponse:
    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None:
        return None


class _UrllibSession:
    """Small stdlib transport; FRED rejects requests' TLS fingerprint intermittently."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _UrllibResponse:
        request = Request(url, headers=dict(headers), method="GET")
        with urlopen(request, timeout=timeout) as response:
            content = response.read(MAX_CSV_BYTES + 1)
            response_headers = dict(response.headers.items())
        return _UrllibResponse(content, response_headers)


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """One bounded official response retained outside Git."""

    series_id: str
    url: str
    content: bytes
    headers: Mapping[str, str]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def series_url(series_id: str) -> str:
    """Return an exact server-bounded FRED CSV URL for one admitted series."""
    if series_id not in FRED_SERIES:
        raise ValueError(f"unsupported Cboe/FRED series: {series_id}")
    query = urlencode(
        {
            "id": series_id,
            "cosd": SOURCE_START.isoformat(),
            "coed": SOURCE_END.isoformat(),
        }
    )
    value = f"https://{FRED_HOST}/graph/fredgraph.csv?{query}"
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != FRED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path != "/graph/fredgraph.csv"
    ):
        raise ValueError("FRED URL escaped the official bounded endpoint")
    return value


def conservative_available_at(observation_date: date) -> pd.Timestamp:
    """Admit a Cboe close only after the end of its Chicago calendar day."""
    local = datetime.combine(observation_date, time(23, 59, 59), tzinfo=CHICAGO)
    return pd.Timestamp(local).tz_convert("UTC")


def parse_fred_csv(content: bytes, *, series_id: str) -> pd.DataFrame:
    """Parse one bounded FRED CSV while preserving missing values."""
    if series_id not in FRED_SERIES:
        raise ValueError(f"unsupported Cboe/FRED series: {series_id}")
    if not content or len(content) > MAX_CSV_BYTES:
        raise ValueError("bounded FRED CSV has an invalid size")
    try:
        text_value = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("bounded FRED CSV is not UTF-8") from error
    reader = csv.DictReader(StringIO(text_value))
    expected_header = ["observation_date", series_id]
    if reader.fieldnames != expected_header:
        raise ValueError(
            f"bounded FRED CSV header drifted: {reader.fieldnames} != {expected_header}"
        )
    rows: list[dict[str, object]] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            observation = date.fromisoformat(str(row["observation_date"]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid FRED date at line {line_number}") from error
        if not SOURCE_START <= observation <= SOURCE_END:
            raise ValueError(
                f"FRED server ignored the protected date bounds at line {line_number}"
            )
        raw_value = str(row[series_id] or "").strip()
        if raw_value in {"", "."}:
            value = float("nan")
        else:
            try:
                value = float(raw_value)
            except ValueError as error:
                raise ValueError(f"invalid FRED value at line {line_number}") from error
            if not math.isfinite(value) or value <= 0.0 or value > 500.0:
                raise ValueError(f"implausible FRED volatility value at line {line_number}")
        rows.append(
            {
                "observation_date": pd.Timestamp(observation),
                FRED_SERIES[series_id]: value,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("bounded FRED CSV has no observations")
    if (
        frame["observation_date"].duplicated().any()
        or not frame["observation_date"].is_monotonic_increasing
        or frame["observation_date"].max() >= pd.Timestamp("2026-01-01")
    ):
        raise ValueError("bounded FRED dates are duplicated, unordered, or protected")
    return frame


def build_term_structure(
    series_frames: Mapping[str, pd.DataFrame],
    *,
    retrieved_at_utc: str,
    minimum_rows: int = 1_900,
    minimum_complete_pairs: int = 1_800,
) -> pd.DataFrame:
    """Combine the exact shared date grid without filling either Cboe series."""
    if set(series_frames) != set(FRED_SERIES):
        raise ValueError("both exact Cboe/FRED series are required")
    retrieved = pd.Timestamp(retrieved_at_utc)
    if retrieved.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    parsed = {
        series_id: parse_fred_csv(
            _frame_to_csv_bytes(frame, series_id), series_id=series_id
        )
        for series_id, frame in series_frames.items()
    }
    vix = parsed["VIXCLS"]
    vix3m = parsed["VXVCLS"]
    if not vix["observation_date"].equals(vix3m["observation_date"]):
        raise ValueError("VIX and VIX3M bounded source grids differ")
    frame = vix.merge(
        vix3m,
        on="observation_date",
        how="inner",
        validate="one_to_one",
    )
    frame["available_at"] = pd.Series(
        [
            conservative_available_at(value.date())
            for value in frame["observation_date"]
        ],
        dtype="datetime64[ns, UTC]",
    )
    frame["complete_pair"] = frame[["vix_close", "vix3m_close"]].notna().all(axis=1)
    frame["vix_vix3m_ratio"] = np.where(
        frame["complete_pair"], frame["vix_close"] / frame["vix3m_close"], np.nan
    )
    frame["term_structure"] = np.select(
        [
            frame["complete_pair"] & frame["vix_vix3m_ratio"].gt(1.0),
            frame["complete_pair"] & frame["vix_vix3m_ratio"].lt(1.0),
            frame["complete_pair"] & frame["vix_vix3m_ratio"].eq(1.0),
        ],
        ["backwardation", "contango", "flat"],
        default="missing",
    )
    frame["retrieved_at_utc"] = pd.Series(
        [retrieved.tz_convert("UTC")] * len(frame),
        dtype="datetime64[ms, UTC]",
    )
    frame["source_current_vintage"] = True
    complete = frame.loc[frame["complete_pair"]]
    if (
        len(frame) < minimum_rows
        or len(complete) < minimum_complete_pairs
        or frame["observation_date"].min() < pd.Timestamp(SOURCE_START)
        or frame["observation_date"].max() > pd.Timestamp(SOURCE_END)
        or complete["vix_vix3m_ratio"].isna().any()
        or not np.isfinite(complete["vix_vix3m_ratio"].to_numpy()).all()
        or complete["vix_vix3m_ratio"].le(0.0).any()
        or not frame["source_current_vintage"].all()
    ):
        raise ValueError("Cboe VIX term-structure coverage or values are invalid")
    return frame


def _frame_to_csv_bytes(frame: pd.DataFrame, series_id: str) -> bytes:
    """Canonicalize an already parsed frame for shared validation logic."""
    value_column = FRED_SERIES[series_id]
    if set(frame.columns) != {"observation_date", value_column}:
        raise ValueError(f"parsed {series_id} frame schema drifted")
    lines = [f"observation_date,{series_id}"]
    for row in frame.sort_values("observation_date").itertuples(index=False):
        observation = pd.Timestamp(row.observation_date).date().isoformat()
        value = getattr(row, value_column)
        rendered = "." if pd.isna(value) else repr(float(value))
        lines.append(f"{observation},{rendered}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _fetch(series_id: str, *, session: SessionLike) -> RequestRecord:
    url = series_url(series_id)
    response: ResponseLike | None = None
    last_error: BaseException | None = None
    for _attempt in range(3):
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/csv,*/*;q=0.8",
                    "Connection": "close",
                },
                timeout=20.0,
            )
            break
        except (OSError, TimeoutError, URLError) as error:
            last_error = error
    if response is None:
        raise RuntimeError(f"FRED request failed three times for {series_id}") from last_error
    response.raise_for_status()
    if not response.content or len(response.content) > MAX_CSV_BYTES:
        raise ValueError(f"FRED response size is invalid for {series_id}")
    content_type = str(response.headers.get("Content-Type", "")).casefold()
    if content_type and "csv" not in content_type and "text/plain" not in content_type:
        raise ValueError(f"FRED content type is invalid for {series_id}: {content_type}")
    return RequestRecord(series_id, url, response.content, dict(response.headers))


def _raw_record(record: RequestRecord) -> bytes:
    selected_headers = {
        name: record.headers.get(name)
        for name in ("Last-Modified", "Content-Type", "ETag")
        if record.headers.get(name) is not None
    }
    return json.dumps(
        {
            "kind": "fred_csv",
            "identity": record.series_id,
            "url": record.url,
            "headers": selected_headers,
            "bytes": len(record.content),
            "sha256": sha256_bytes(record.content),
            "content_encoding": "base64",
            "content": base64.b64encode(record.content).decode("ascii"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def download_cboe_vix_term_structure(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
    minimum_rows: int = 1_900,
    minimum_complete_pairs: int = 1_800,
) -> Path:
    """Write one immutable target-free VIX/VIX3M source bundle."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"Cboe VIX term-structure output already exists: {final}")
    if not _SAFE_SNAPSHOT_ID.fullmatch(final.name):
        raise ValueError("unsafe Cboe VIX term-structure snapshot directory name")
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = session or _UrllibSession()
    records = [_fetch(series_id, session=client) for series_id in FRED_SERIES]
    series_frames = {
        record.series_id: parse_fred_csv(record.content, series_id=record.series_id)
        for record in records
    }
    frame = build_term_structure(
        series_frames,
        retrieved_at_utc=fetched_at,
        minimum_rows=minimum_rows,
        minimum_complete_pairs=minimum_complete_pairs,
    )
    complete = frame.loc[frame["complete_pair"]].copy()
    admissible = complete.loc[complete["available_at"].lt(PROTECTED_FROM)].copy()
    if admissible.empty or admissible["observation_date"].max() >= pd.Timestamp(
        "2026-01-01"
    ):
        raise ValueError("Cboe VIX term structure crossed the protected market boundary")
    record_by_id = {record.series_id: record for record in records}
    coverage = pd.DataFrame(
        [
            {
                "series_id": series_id,
                "value_column": FRED_SERIES[series_id],
                "url": record_by_id[series_id].url,
                "response_bytes": len(record_by_id[series_id].content),
                "response_sha256": sha256_bytes(record_by_id[series_id].content),
                "rows": len(series_frames[series_id]),
                "nonmissing_rows": int(
                    series_frames[series_id][FRED_SERIES[series_id]].notna().sum()
                ),
                "missing_rows": int(
                    series_frames[series_id][FRED_SERIES[series_id]].isna().sum()
                ),
                "minimum_observation_date": series_frames[series_id][
                    "observation_date"
                ].min(),
                "maximum_observation_date": series_frames[series_id][
                    "observation_date"
                ].max(),
            }
            for series_id in FRED_SERIES
        ]
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "cboe_vix_term_structure.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_fred_cboe_responses.jsonl.gz"
        frame.to_parquet(data_path, index=False, compression="zstd")
        coverage.to_parquet(coverage_path, index=False, compression="zstd")
        raw_lines = [_raw_record(record) for record in records]
        atomic_write_bytes(
            raw_path,
            gzip.compress(b"\n".join(raw_lines) + b"\n", compresslevel=6, mtime=0),
        )
        counts = complete["term_structure"].value_counts().to_dict()
        admissible_counts = admissible["term_structure"].value_counts().to_dict()
        gaps = complete["observation_date"].diff().dt.days
        manifest_core = {
            "schema_version": 1,
            "source_id": "fred-cboe-vix-term-structure-current-vintage-2018-2025-v2",
            "provider": "Cboe Global Markets via FRED, Federal Reserve Bank of St. Louis",
            "source_name": "Cboe VIX and Cboe S&P 500 3-Month Volatility Index daily closes",
            "source_urls": {series_id: series_url(series_id) for series_id in FRED_SERIES},
            "fetched_at_utc": fetched_at,
            "request_count": len(records),
            "request_bounds": {
                "observation_date_from": SOURCE_START.isoformat(),
                "observation_date_through": SOURCE_END.isoformat(),
                "server_side_bounded_query": True,
                "protected_from_utc": PROTECTED_FROM.isoformat(),
            },
            "coverage": {
                "grid_rows": len(frame),
                "complete_pairs": len(complete),
                "missing_pair_rows": int((~frame["complete_pair"]).sum()),
                "complete_pairs_by_year": {
                    str(key): int(value)
                    for key, value in complete["observation_date"]
                    .dt.year.value_counts().sort_index().items()
                },
                "minimum_observation_date": frame["observation_date"].min().date().isoformat(),
                "maximum_observation_date": frame["observation_date"].max().date().isoformat(),
                "minimum_available_at": frame["available_at"].min().isoformat(),
                "maximum_available_at": frame["available_at"].max().isoformat(),
                "complete_pairs_available_before_protected_boundary": len(admissible),
                "maximum_admissible_observation_date": admissible[
                    "observation_date"
                ].max().date().isoformat(),
                "maximum_admissible_available_at": admissible[
                    "available_at"
                ].max().isoformat(),
                "maximum_complete_pair_gap_calendar_days": int(gaps.max()),
                "term_structure_counts": {
                    "backwardation": int(counts.get("backwardation", 0)),
                    "contango": int(counts.get("contango", 0)),
                    "flat": int(counts.get("flat", 0)),
                },
                "admissible_term_structure_counts": {
                    "backwardation": int(admissible_counts.get("backwardation", 0)),
                    "contango": int(admissible_counts.get("contango", 0)),
                    "flat": int(admissible_counts.get("flat", 0)),
                },
            },
            "temporal_semantics": {
                "observation_date": "Cboe index close date distributed by FRED",
                "available_at": "23:59:59 America/Chicago on observation_date",
                "admissible_join": "available_at less than or equal to decision_at",
                "same_Moscow_calendar_day_US_close_forbidden": True,
                "date_bounded_raw_responses_contain_no_2026_observations": True,
                "current_vintage_retrieved_now": True,
                "original_historical_response_bytes_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_MOEX_prices_returns_targets_labels_or_pnl": False,
                "missing_values_are_not_zero": True,
            },
            "value_semantics": {
                "VIXCLS": "Cboe VIX 30-day implied-volatility index daily close",
                "VXVCLS": "Cboe S&P 500 3-month implied-volatility index daily close",
                "structural_boundary": (
                    "backwardation exactly when VIXCLS divided by VXVCLS "
                    "is greater than 1"
                ),
                "no_threshold_fit_or_outcome_labels": True,
            },
            "source_quality": {
                "both_series_share_exact_date_grid": True,
                "server_bounds_verified_from_every_observation": True,
                "raw_response_hashes_retained": True,
                "missing_rows_preserved": True,
                "maximum_complete_pair_gap_calendar_days": int(gaps.max()),
            },
            "rights": {
                "cboe_values_copyrighted": True,
                "citation_required": True,
                "redistribution_license_verified": False,
                "raw_stored_outside_git": True,
            },
            "artifacts": {
                "processed": {
                    "path": data_path.name,
                    "bytes": data_path.stat().st_size,
                    "sha256": sha256_file(data_path),
                    "rows": len(frame),
                    "columns": frame.columns.tolist(),
                },
                "coverage": {
                    "path": coverage_path.name,
                    "bytes": coverage_path.stat().st_size,
                    "sha256": sha256_file(coverage_path),
                    "rows": len(coverage),
                },
                "raw_responses": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "records": len(records),
                },
            },
        }
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {
                **manifest_core,
                "manifest_payload_sha256": sha256_bytes(_canonical_json(manifest_core)),
            },
        )
        manifest_sha = sha256_file(manifest_path)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{manifest_sha}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Immutable external source-bundle directory.",
    )
    arguments = parser.parse_args()
    print(download_cboe_vix_term_structure(arguments.output))


if __name__ == "__main__":
    main()
