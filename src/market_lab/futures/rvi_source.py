"""Download a target-free, pre-2026 MOEX RVI history with immutable provenance."""

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

from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SOURCE_START: Final[pd.Timestamp] = pd.Timestamp("2018-01-01")
SOURCE_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
SECURITY_ID: Final[str] = "RVI"
ISS_URL: Final[str] = (
    "https://iss.moex.com/iss/history/engines/stock/markets/index/"
    "securities/RVI.json"
)
ISS_COLUMNS: Final[tuple[str, ...]] = (
    "TRADEDATE",
    "SECID",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
)
USER_AGENT: Final[str] = "market-lab-rvi-source/1.0 (MOEX ISS research)"
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/moex-rvi-dev-2018-2025-v1"
)


class ResponseLike(Protocol):
    """Minimal requests-compatible response used by the downloader and synthetic tests."""

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


def _table(payload: Mapping[str, Any], name: str) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, Mapping):
        raise ValueError(f"MOEX RVI payload lacks {name}")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"invalid MOEX RVI table {name}")
    normalized = [str(column).lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"duplicate columns in MOEX RVI table {name}")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"malformed row in MOEX RVI table {name}")
    return pd.DataFrame(rows, columns=normalized)


def _request_url(offset: int) -> str:
    if offset < 0:
        raise ValueError("MOEX RVI pagination offset cannot be negative")
    query = urlencode(
        {
            "from": SOURCE_START.date().isoformat(),
            "till": SOURCE_END.date().isoformat(),
            "start": offset,
            "iss.meta": "off",
            "iss.only": "history,history.cursor",
            "history.columns": ",".join(ISS_COLUMNS),
        }
    )
    url = f"{ISS_URL}?{query}"
    parsed = parse_qs(urlparse(url).query)
    if pd.Timestamp(parsed["till"][0]) >= PROTECTED_FROM:
        raise ValueError("MOEX RVI request could cross the protected boundary")
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
                raise ValueError("MOEX RVI response is not an object")
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    raise RuntimeError(f"MOEX RVI request failed: {url}: {last_error}") from last_error


def fetch_rvi_pages(
    session: SessionLike,
    *,
    maximum_pages: int = 100,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Follow the official cursor exactly and preserve every bounded raw response."""
    frames: list[pd.DataFrame] = []
    archive: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    expected_total: int | None = None
    offset = 0
    for _ in range(maximum_pages):
        url = _request_url(offset)
        payload = _request_json(session, url)
        history = _table(payload, "history")
        cursor = _table(payload, "history.cursor")
        if len(cursor) != 1 or not {"index", "total", "pagesize"} <= set(cursor.columns):
            raise ValueError("invalid MOEX RVI history.cursor")
        cursor_index = int(cursor.iloc[0]["index"])
        total = int(cursor.iloc[0]["total"])
        page_size = int(cursor.iloc[0]["pagesize"])
        if cursor_index != offset or total < 0 or page_size <= 0:
            raise ValueError("non-canonical MOEX RVI cursor")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError("MOEX RVI cursor total changed during pagination")
        expected_rows = min(page_size, max(total - offset, 0))
        if len(history) != expected_rows:
            raise ValueError(
                f"truncated MOEX RVI page at {offset}: {len(history)} != {expected_rows}"
            )
        if not set(column.lower() for column in ISS_COLUMNS) <= set(history.columns):
            raise ValueError("MOEX RVI history does not contain the requested closed schema")
        dates = history["tradedate"].astype(str).tolist()
        if len(dates) != len(set(dates)) or any(value in seen_dates for value in dates):
            raise ValueError("duplicate RVI date within or across MOEX pages")
        seen_dates.update(dates)
        if not history.empty:
            frames.append(history)
        archive.append({"request_url": url, "payload": payload})
        offset += len(history)
        if offset == total:
            break
        if history.empty or offset > total:
            raise ValueError("MOEX RVI cursor did not progress")
    else:
        raise ValueError("MOEX RVI pagination exceeded maximum_pages")
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != (expected_total or 0):
        raise ValueError("incomplete MOEX RVI history pagination")
    return combined, archive


def normalize_rvi_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate target-free daily OHLC and attach a conservative one-date availability lag."""
    required = {column.lower() for column in ISS_COLUMNS}
    if missing := required - set(frame.columns):
        raise ValueError(f"MOEX RVI history lacks columns: {sorted(missing)}")
    output = frame.loc[:, [column.lower() for column in ISS_COLUMNS]].copy()
    output = output.rename(columns={"tradedate": "source_date", "secid": "security_id"})
    output["source_date"] = pd.to_datetime(output["source_date"], errors="raise").dt.normalize()
    if output["source_date"].lt(SOURCE_START).any() or output["source_date"].gt(
        SOURCE_END
    ).any():
        raise ValueError("MOEX RVI history escaped the requested development interval")
    if output["source_date"].ge(PROTECTED_FROM).any():
        raise ValueError("MOEX RVI history contains a protected 2026+ row")
    if output.duplicated("source_date").any():
        raise ValueError("MOEX RVI history contains duplicate dates")
    if not output["security_id"].astype(str).eq(SECURITY_ID).all():
        raise ValueError("MOEX returned another security in the RVI endpoint")
    for column in ("open", "high", "low", "close"):
        values = pd.to_numeric(output[column], errors="coerce").astype(float)
        if values.isna().any() or not np.isfinite(values).all() or values.le(0.0).any():
            raise ValueError(f"MOEX RVI {column} must be finite and positive")
        output[column] = values
    invalid = (
        output["high"].lt(output[["open", "close"]].max(axis=1))
        | output["low"].gt(output[["open", "close"]].min(axis=1))
        | output["high"].lt(output["low"])
    )
    if invalid.any():
        raise ValueError("MOEX RVI history violates OHLC invariants")
    output["conservative_available_from_date"] = output["source_date"] + pd.Timedelta(days=1)
    output["availability_rule"] = "use_only_when_source_date_strictly_before_decision_date"
    output["provider"] = "MOEX ISS"
    output["current_vintage_snapshot"] = True
    return output.sort_values("source_date", kind="mergesort", ignore_index=True)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download_rvi_source(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
) -> Path:
    """Write a new immutable RVI source directory; never overwrite an existing snapshot."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"MOEX RVI output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        network_session: SessionLike = session or requests.Session()
        raw, pages = fetch_rvi_pages(network_session)
        normalized = normalize_rvi_history(raw)
        if normalized.empty:
            raise ValueError("MOEX RVI history is empty")

        data_path = temporary / "rvi_daily.parquet"
        _atomic_parquet(data_path, normalized)
        raw_body = json.dumps(
            {"requests": pages},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        raw_path = temporary / "official_moex_iss_pages.json.gz"
        atomic_write_bytes(raw_path, gzip.compress(raw_body, compresslevel=6, mtime=0))
        fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-rvi-current-vintage-2018-2025-v1",
            "provider": "MOEX ISS",
            "official_endpoint": ISS_URL,
            "fetched_at_utc": fetched_at,
            "request_count": len(pages),
            "request_bounds": {
                "from": SOURCE_START.date().isoformat(),
                "till": SOURCE_END.date().isoformat(),
                "protected_from": PROTECTED_FROM.date().isoformat(),
                "all_request_till_values_before_protected_from": True,
            },
            "temporal_semantics": {
                "source_date": "MOEX index trading date",
                "conservative_available_from_date": "source_date plus one calendar day",
                "admissible_join": "source_date strictly less than decision_date",
                "timezone": "Europe/Moscow",
                "current_vintage_snapshot": True,
                "historical_revision_archive_proved": False,
            },
            "artifacts": {
                "processed": {
                    "path": data_path.name,
                    "bytes": data_path.stat().st_size,
                    "sha256": sha256_file(data_path),
                    "rows": len(normalized),
                    "minimum_source_date": normalized["source_date"].min().date().isoformat(),
                    "maximum_source_date": normalized["source_date"].max().date().isoformat(),
                    "columns": normalized.columns.tolist(),
                },
                "raw_archive": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "requests": len(pages),
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
    print(download_rvi_source(arguments.output_directory))


if __name__ == "__main__":
    main()
