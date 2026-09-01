"""Acquire bounded FRED STLFSI4 weekly financial-stress observations."""

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
from datetime import UTC, date, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from typing import Final, Protocol
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SERIES_ID: Final[str] = "STLFSI4"
SOURCE_START: Final[date] = date(2018, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
CHICAGO: Final[ZoneInfo] = ZoneInfo("America/Chicago")
FRED_HOST: Final[str] = "fred.stlouisfed.org"
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT / "data/processed/info_radar/fred-stlfsi4-current-vintage-2018-2025-v1"
)
USER_AGENT: Final[str] = "curl/8.10.1"
MAX_CSV_BYTES: Final[int] = 2 * 1024 * 1024
CONSERVATIVE_PUBLICATION_LAG_DAYS: Final[int] = 6
_SAFE_SNAPSHOT_ID: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ResponseLike(Protocol):
    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
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
    """Small stdlib transport matching the reproducible FRED collectors."""

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


def series_url() -> str:
    """Return the exact server-bounded official FRED graph CSV URL."""
    query = urlencode(
        {
            "id": SERIES_ID,
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
        raise ValueError("STLFSI4 URL escaped the official bounded endpoint")
    return value


def conservative_available_at(observation_date: date) -> pd.Timestamp:
    """Admit Friday-ending data only after the following Thursday in Chicago."""
    publication_buffer_date = observation_date + timedelta(days=CONSERVATIVE_PUBLICATION_LAG_DAYS)
    local = datetime.combine(publication_buffer_date, time(23, 59, 59), tzinfo=CHICAGO)
    return pd.Timestamp(local).tz_convert("UTC")


def parse_fred_csv(content: bytes) -> pd.DataFrame:
    """Parse a bounded STLFSI4 CSV without filling or coercing missing values."""
    if not content or len(content) > MAX_CSV_BYTES:
        raise ValueError("bounded STLFSI4 CSV has an invalid size")
    try:
        text_value = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("bounded STLFSI4 CSV is not UTF-8") from error
    reader = csv.DictReader(StringIO(text_value))
    expected_header = ["observation_date", SERIES_ID]
    if reader.fieldnames != expected_header:
        raise ValueError(
            f"bounded STLFSI4 CSV header drifted: {reader.fieldnames} != {expected_header}"
        )
    rows: list[dict[str, object]] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            observation = date.fromisoformat(str(row["observation_date"]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid STLFSI4 date at line {line_number}") from error
        if not SOURCE_START <= observation <= SOURCE_END:
            raise ValueError(f"FRED ignored the protected STLFSI4 bounds at line {line_number}")
        raw_value = str(row[SERIES_ID] or "").strip()
        if raw_value in {"", "."}:
            value = float("nan")
        else:
            try:
                value = float(raw_value)
            except ValueError as error:
                raise ValueError(f"invalid STLFSI4 value at line {line_number}") from error
            if not math.isfinite(value) or abs(value) > 25.0:
                raise ValueError(f"implausible STLFSI4 value at line {line_number}")
        rows.append(
            {
                "observation_date": pd.Timestamp(observation),
                "stress_index": value,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("bounded STLFSI4 CSV has no observations")
    if (
        frame["observation_date"].duplicated().any()
        or not frame["observation_date"].is_monotonic_increasing
        or frame["observation_date"].max() >= pd.Timestamp("2026-01-01")
        or not frame["observation_date"].dt.dayofweek.eq(4).all()
    ):
        raise ValueError("STLFSI4 dates are duplicate, unordered, protected or non-Friday")
    return frame


def build_stress_index(
    parsed: pd.DataFrame,
    *,
    retrieved_at_utc: str,
    minimum_rows: int = 400,
) -> pd.DataFrame:
    """Add conservative availability and the official structural zero state."""
    if set(parsed.columns) != {"observation_date", "stress_index"}:
        raise ValueError("parsed STLFSI4 frame schema drifted")
    canonical_lines = [f"observation_date,{SERIES_ID}"]
    for row in parsed.sort_values("observation_date").itertuples(index=False):
        rendered = "." if pd.isna(row.stress_index) else repr(float(row.stress_index))
        canonical_lines.append(
            f"{pd.Timestamp(row.observation_date).date().isoformat()},{rendered}"
        )
    source = parse_fred_csv(("\n".join(canonical_lines) + "\n").encode("utf-8"))
    retrieved = pd.Timestamp(retrieved_at_utc)
    if retrieved.tzinfo is None:
        raise ValueError("STLFSI4 retrieval timestamp must be timezone-aware")
    frame = source.copy()
    frame["available_at"] = pd.Series(
        [conservative_available_at(value.date()) for value in frame["observation_date"]],
        dtype="datetime64[ns, UTC]",
    )
    frame["complete"] = frame["stress_index"].notna()
    frame["stress_state"] = "missing"
    frame.loc[frame["complete"] & frame["stress_index"].gt(0.0), "stress_state"] = "above_average"
    frame.loc[frame["complete"] & frame["stress_index"].le(0.0), "stress_state"] = "normal_or_below"
    frame["retrieved_at_utc"] = pd.Series(
        [retrieved.tz_convert("UTC")] * len(frame), dtype="datetime64[ms, UTC]"
    )
    frame["source_current_vintage"] = True
    frame["methodology_version"] = SERIES_ID
    complete = frame.loc[frame["complete"]]
    if (
        len(frame) < minimum_rows
        or complete.empty
        or not frame["source_current_vintage"].all()
        or set(complete["stress_state"]) - {"above_average", "normal_or_below"}
    ):
        raise ValueError("STLFSI4 coverage, values or structural states are invalid")
    return frame


def _fetch(*, session: SessionLike) -> RequestRecord:
    url = series_url()
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
        raise RuntimeError("FRED request failed three times for STLFSI4") from last_error
    response.raise_for_status()
    if not response.content or len(response.content) > MAX_CSV_BYTES:
        raise ValueError("FRED response size is invalid for STLFSI4")
    content_type = str(response.headers.get("Content-Type", "")).casefold()
    if content_type and "csv" not in content_type and "text/plain" not in content_type:
        raise ValueError(f"FRED content type is invalid for STLFSI4: {content_type}")
    return RequestRecord(url, response.content, dict(response.headers))


def _raw_record(record: RequestRecord) -> bytes:
    selected_headers = {
        name: record.headers.get(name)
        for name in ("Last-Modified", "Content-Type", "ETag")
        if record.headers.get(name) is not None
    }
    return json.dumps(
        {
            "kind": "fred_csv",
            "identity": SERIES_ID,
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


def download_stlfsi(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
    minimum_rows: int = 400,
) -> Path:
    """Write one immutable target-free STLFSI4 source bundle outside Git."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"STLFSI4 output already exists: {final}")
    if not _SAFE_SNAPSHOT_ID.fullmatch(final.name):
        raise ValueError("unsafe STLFSI4 snapshot directory name")
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = _fetch(session=session or _UrllibSession())
    parsed = parse_fred_csv(record.content)
    frame = build_stress_index(parsed, retrieved_at_utc=fetched_at, minimum_rows=minimum_rows)
    complete = frame.loc[frame["complete"]]
    admissible = complete.loc[frame["available_at"].lt(PROTECTED_FROM)]
    if admissible.empty:
        raise ValueError("STLFSI4 has no values available before the protected boundary")
    coverage = pd.DataFrame(
        [
            {
                "series_id": SERIES_ID,
                "url": record.url,
                "response_bytes": len(record.content),
                "response_sha256": sha256_bytes(record.content),
                "rows": len(parsed),
                "nonmissing_rows": int(parsed["stress_index"].notna().sum()),
                "missing_rows": int(parsed["stress_index"].isna().sum()),
                "minimum_observation_date": parsed["observation_date"].min(),
                "maximum_observation_date": parsed["observation_date"].max(),
            }
        ]
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "stlfsi4.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_fred_stlfsi4_response.jsonl.gz"
        frame.to_parquet(data_path, index=False, compression="zstd")
        coverage.to_parquet(coverage_path, index=False, compression="zstd")
        atomic_write_bytes(
            raw_path,
            gzip.compress(_raw_record(record) + b"\n", compresslevel=6, mtime=0),
        )
        counts = complete["stress_state"].value_counts()
        admissible_counts = admissible["stress_state"].value_counts()
        gaps = complete["observation_date"].diff().dt.days
        manifest_core = {
            "schema_version": 1,
            "source_id": "fred-stlfsi4-current-vintage-2018-2025-v1",
            "provider": "Federal Reserve Bank of St. Louis via FRED",
            "source_name": "St. Louis Fed Financial Stress Index, Version 4.0",
            "series_id": SERIES_ID,
            "source_url": series_url(),
            "fetched_at_utc": fetched_at,
            "request_count": 1,
            "request_bounds": {
                "observation_date_from": SOURCE_START.isoformat(),
                "observation_date_through": SOURCE_END.isoformat(),
                "server_side_bounded_query": True,
                "protected_from_utc": PROTECTED_FROM.isoformat(),
            },
            "coverage": {
                "rows": len(frame),
                "complete_rows": len(complete),
                "missing_rows": int((~frame["complete"]).sum()),
                "minimum_observation_date": frame["observation_date"].min().date().isoformat(),
                "maximum_observation_date": frame["observation_date"].max().date().isoformat(),
                "minimum_available_at": frame["available_at"].min().isoformat(),
                "maximum_available_at": frame["available_at"].max().isoformat(),
                "complete_available_before_protected_boundary": len(admissible),
                "maximum_admissible_observation_date": admissible["observation_date"]
                .max()
                .date()
                .isoformat(),
                "maximum_admissible_available_at": admissible["available_at"].max().isoformat(),
                "maximum_complete_gap_calendar_days": int(gaps.max()),
                "stress_state_counts": {
                    "above_average": int(counts.get("above_average", 0)),
                    "normal_or_below": int(counts.get("normal_or_below", 0)),
                },
                "admissible_stress_state_counts": {
                    "above_average": int(admissible_counts.get("above_average", 0)),
                    "normal_or_below": int(admissible_counts.get("normal_or_below", 0)),
                },
                "complete_rows_by_year": {
                    str(key): int(value)
                    for key, value in complete["observation_date"]
                    .dt.year.value_counts()
                    .sort_index()
                    .items()
                },
                "above_average_rows_by_year": {
                    str(key): int(value)
                    for key, value in complete.loc[
                        complete["stress_state"].eq("above_average"), "observation_date"
                    ]
                    .dt.year.value_counts()
                    .sort_index()
                    .items()
                },
            },
            "temporal_semantics": {
                "observation_date": "weekly period ending Friday",
                "available_at": (
                    "23:59:59 America/Chicago on the Thursday six calendar days "
                    "after observation_date"
                ),
                "availability_basis": (
                    "FRED normally updates the Friday-ending series the following "
                    "Wednesday; Thursday end is a one-day conservative buffer"
                ),
                "admissible_join": "available_at less than or equal to decision_at",
                "current_vintage_retrieved_now": True,
                "original_historical_response_bytes_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "methodology_version_available_through_full_history": False,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_MOEX_prices_returns_targets_labels_or_pnl": False,
                "missing_values_are_not_zero": True,
            },
            "value_semantics": {
                "components": "18 weekly financial-market series",
                "structural_boundary": 0.0,
                "above_zero": "above-average financial market stress",
                "zero": "normal financial market conditions",
                "below_zero": "below-average financial market stress",
                "no_threshold_fit_or_outcome_labels": True,
            },
            "source_quality": {
                "server_bounds_verified_from_every_observation": True,
                "raw_response_hash_retained": True,
                "missing_rows_preserved": True,
                "weekly_ending_friday_exact": True,
                "maximum_complete_gap_calendar_days": int(gaps.max()),
            },
            "rights": {
                "values_copyrighted": True,
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
                "raw_response": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "records": 1,
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
        help="Immutable external STLFSI4 source-bundle directory.",
    )
    arguments = parser.parse_args()
    print(download_stlfsi(arguments.output))


if __name__ == "__main__":
    main()
