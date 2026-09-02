"""Collect the sealed pre-2026 point-in-time MOEX RMS archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_rms_historical_pit_source_v1.yaml"
CONFIG_SHA256: Final[str] = "33a57278f9466f1d1fd04fef06d1a1c73b87c22126f951f8670208ffbab7a699"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v1"
)
USER_AGENT: Final[str] = "market-lab-moex-rms-pit/1.0 (research)"
TABLES: Final[tuple[str, ...]] = ("limits", "staticparams", "cashflow")
MOSCOW_TIMEZONE: Final[str] = "Europe/Moscow"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".yaml.sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("MOEX RMS historical config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_rms_historical_pit_source_v1"
        or config.get("live_trading_allowed") is not False
        or config["objective"]["returns_targets_predictions_or_pnl_allowed"] is not False
        or str(config["temporal_boundary"]["protected_from"]) != "2026-01-01"
        or config["future_hypothesis_constraints"]["structural_margin_rule_threshold"]
        != "zero_change_only_not_percentile_fit"
    ):
        raise ValueError("MOEX RMS historical invariants drifted")
    return config


def table_url(config: dict[str, Any], table: str, query_date: date, start: int) -> str:
    if table not in TABLES or start < 0 or pd.Timestamp(query_date) >= PROTECTED_FROM:
        raise ValueError("invalid MOEX RMS historical request")
    endpoint = config["source"]["tables"][table]["endpoint"]
    query = urlencode({"iss.meta": "off", "date": query_date.isoformat(), "start": start})
    return f"{config['source']['base_endpoint']}/{endpoint}?{query}"


def _block(payload: dict[str, Any], name: str) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        raise ValueError(f"missing MOEX RMS historical {name} block")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX RMS historical {name} rows")
    return pd.DataFrame(rows, columns=[str(value) for value in block["columns"]])


def parse_page(
    raw: bytes, table: str, query_date: date, config: dict[str, Any]
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    frame = _block(payload, table)
    required = config["source"]["tables"][table]["required_columns"]
    if tuple(frame.columns) != tuple(required):
        raise ValueError(f"MOEX RMS historical {table} exact schema drift")
    cursor = _block(payload, f"{table}.cursor")
    if len(cursor) != 1 or set(("INDEX", "TOTAL", "PAGESIZE")) - set(cursor.columns):
        raise ValueError(f"MOEX RMS historical {table} cursor drift")
    index = int(cursor.iloc[0]["INDEX"])
    total = int(cursor.iloc[0]["TOTAL"])
    if index < 0 or total < 0 or index + len(frame) > total:
        raise ValueError(f"MOEX RMS historical {table} cursor invalid")
    if len(frame):
        dates = pd.to_datetime(frame["tradedate"], errors="raise").dt.date.unique()
        if len(dates) != 1 or dates[0] != query_date:
            raise ValueError(f"MOEX RMS historical {table} query/tradedate mismatch")
    return frame, index, total


def _get_with_retry(url: str, session: SessionLike | None) -> bytes:
    last_error: BaseException | None = None
    for attempt in range(3):
        try:
            client = session or requests
            response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
            response.raise_for_status()
            return bytes(response.content)
        except (requests.RequestException, TimeoutError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"MOEX RMS request failed after retries: {url}") from last_error


def fetch_date(
    table: str,
    query_date: date,
    config: dict[str, Any],
    session: SessionLike | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    start = 0
    total: int | None = None
    frames: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    while total is None or start < total:
        url = table_url(config, table, query_date, start)
        raw = _get_with_retry(url, session)
        frame, index, page_total = parse_page(raw, table, query_date, config)
        if index != start or (total is not None and page_total != total):
            raise ValueError(f"MOEX RMS historical {table} pagination drift")
        total = page_total
        frames.append(frame)
        pages.append(
            {
                "table": table,
                "query_date": query_date.isoformat(),
                "start": start,
                "url": url,
                "rows": len(frame),
                "raw": raw,
            }
        )
        if len(frame) == 0:
            if total != 0:
                raise ValueError(f"MOEX RMS historical {table} empty page before total")
            break
        start += len(frame)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != int(total or 0):
        raise ValueError(f"MOEX RMS historical {table} incomplete date")
    return combined, pages


def _date_grid(start: str, finish: str) -> list[date]:
    return [value.date() for value in pd.date_range(start=start, end=finish, freq="D")]


def canonical_date_ranges(config: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {
        table: (
            str(config["source"]["tables"][table]["requested_from"]),
            str(config["source"]["tables"][table]["requested_till"]),
        )
        for table in TABLES
    }


def normalize_table(
    frame: pd.DataFrame, table: str, retrieved_at: pd.Timestamp, config: dict[str, Any]
) -> pd.DataFrame:
    required = config["source"]["tables"][table]["required_columns"]
    if frame.empty:
        columns = list(required) + ["source_table", "available_at_utc", "retrieved_at_utc"]
        return pd.DataFrame(columns=columns)
    output = frame.loc[:, required].copy()
    output["tradedate"] = pd.to_datetime(output["tradedate"], errors="raise").dt.normalize()
    updates = pd.to_datetime(output["updatetime"], errors="raise").dt.tz_localize(
        MOSCOW_TIMEZONE, ambiguous="raise", nonexistent="raise"
    ).dt.tz_convert("UTC")
    if output["tradedate"].ge(PROTECTED_FROM).any():
        raise ValueError("MOEX RMS historical tradedate crossed 2026")
    if updates.ge(pd.Timestamp("2026-01-01T00:00:00Z")).any():
        raise ValueError("MOEX RMS historical updatetime crossed 2026")
    output["source_table"] = table
    output["available_at_utc"] = updates
    output["retrieved_at_utc"] = retrieved_at.tz_convert("UTC")
    key = config["source"]["tables"][table]["unique_key"]
    if output.duplicated(key).any():
        raise ValueError(f"duplicate MOEX RMS historical {table} key")
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("outcome column escaped into MOEX RMS historical source")
    return output.sort_values(key, kind="stable", ignore_index=True)


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    date_ranges: dict[str, tuple[str, str]] | None = None,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
    max_workers: int = 8,
) -> Path:
    config = load_config()
    ranges = date_ranges or canonical_date_ranges(config)
    canonical = ranges == canonical_date_ranges(config)
    if set(ranges) != set(TABLES):
        raise ValueError("MOEX RMS historical date ranges must cover exact tables")
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("MOEX RMS historical retrieval must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    jobs = [
        (table, query_date)
        for table in TABLES
        for query_date in _date_grid(*ranges[table])
    ]
    results: dict[tuple[str, date], tuple[pd.DataFrame, list[dict[str, Any]]]] = {}
    workers = 1 if session is not None else max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_date, table, query_date, config, session): (table, query_date)
            for table, query_date in jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            key = futures[future]
            results[key] = future.result()
            if canonical and completed % 250 == 0:
                print(f"MOEX RMS historical progress {completed}/{len(jobs)}", flush=True)
    table_frames: dict[str, pd.DataFrame] = {}
    raw_pages: list[dict[str, Any]] = []
    empty_dates: dict[str, int] = {}
    for table in TABLES:
        frames = []
        empty = 0
        for query_date in _date_grid(*ranges[table]):
            frame, pages = results[(table, query_date)]
            raw_pages.extend(pages)
            if frame.empty:
                empty += 1
            else:
                frames.append(frame)
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        table_frames[table] = normalize_table(combined, table, retrieval, config)
        empty_dates[table] = empty

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable MOEX RMS historical output exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        requests_log: list[dict[str, Any]] = []
        raw_zip = temporary / "raw_responses.zip"
        with zipfile.ZipFile(raw_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for page in sorted(
                raw_pages,
                key=lambda item: (item["table"], item["query_date"], int(item["start"])),
            ):
                member = (
                    f"raw/{page['table']}/{page['query_date']}/"
                    f"{int(page['start']):06d}.json"
                )
                raw = page["raw"]
                archive.writestr(member, raw)
                requests_log.append(
                    {
                        "table": page["table"],
                        "query_date": page["query_date"],
                        "start": page["start"],
                        "url": page["url"],
                        "rows": page["rows"],
                        "zip_member": member,
                        "response_bytes": len(raw),
                        "response_sha256": _sha_bytes(raw),
                    }
                )
        requests_path = temporary / "requests.json"
        _write_json(requests_path, requests_log)
        processed: dict[str, Any] = {}
        for table, frame in table_frames.items():
            path = temporary / f"{table}.parquet"
            frame.to_parquet(path, index=False)
            processed[table] = {
                "path": path.name,
                "rows": len(frame),
                "bytes": path.stat().st_size,
                "sha256": _sha_file(path),
                "minimum_tradedate": (
                    frame["tradedate"].min().date().isoformat() if len(frame) else None
                ),
                "maximum_tradedate": (
                    frame["tradedate"].max().date().isoformat() if len(frame) else None
                ),
            }
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "canonical_full_range": canonical,
            "date_ranges": ranges,
            "request_date_count": len(jobs),
            "raw_page_count": len(requests_log),
            "empty_request_dates": empty_dates,
            "contains_returns_targets_predictions_or_pnl": False,
            "raw_zip": {
                "path": raw_zip.name,
                "bytes": raw_zip.stat().st_size,
                "sha256": _sha_file(raw_zip),
                "members": len(requests_log),
            },
            "requests": {
                "path": requests_path.name,
                "bytes": requests_path.stat().st_size,
                "sha256": _sha_file(requests_path),
                "rows": len(requests_log),
            },
            "processed": processed,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(output_root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(output_root)
    _write_json(output_root / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("MOEX RMS historical audit failed")
    return output_root


def audit(output_root: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks: dict[str, bool] = {
        "protocol_exact": manifest["protocol_id"] == config["protocol_id"],
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "target_free": manifest["contains_returns_targets_predictions_or_pnl"] is False,
    }
    raw_zip = output_root / manifest["raw_zip"]["path"]
    requests_path = output_root / manifest["requests"]["path"]
    checks["raw_zip_exact"] = (
        raw_zip.stat().st_size == manifest["raw_zip"]["bytes"]
        and _sha_file(raw_zip) == manifest["raw_zip"]["sha256"]
    )
    checks["requests_exact"] = (
        requests_path.stat().st_size == manifest["requests"]["bytes"]
        and _sha_file(requests_path) == manifest["requests"]["sha256"]
    )
    request_log = json.loads(requests_path.read_text(encoding="utf-8-sig"))
    rebuilt: dict[str, list[pd.DataFrame]] = {table: [] for table in TABLES}
    raw_exact = True
    with zipfile.ZipFile(raw_zip) as archive:
        for item in request_log:
            raw = archive.read(item["zip_member"])
            raw_exact &= (
                len(raw) == int(item["response_bytes"])
                and _sha_bytes(raw) == item["response_sha256"]
                and item["url"]
                == table_url(
                    config,
                    item["table"],
                    date.fromisoformat(item["query_date"]),
                    int(item["start"]),
                )
            )
            frame, index, _ = parse_page(
                raw,
                item["table"],
                date.fromisoformat(item["query_date"]),
                config,
            )
            raw_exact &= index == int(item["start"])
            if len(frame):
                rebuilt[item["table"]].append(frame)
    checks["all_raw_pages_exact"] = raw_exact
    for table in TABLES:
        combined = (
            pd.concat(rebuilt[table], ignore_index=True)
            if rebuilt[table]
            else pd.DataFrame()
        )
        replay = normalize_table(combined, table, retrieval, config)
        item = manifest["processed"][table]
        path = output_root / item["path"]
        stored = pd.read_parquet(path)
        try:
            pd.testing.assert_frame_equal(stored, replay, check_dtype=False)
            frame_exact = True
        except AssertionError:
            frame_exact = False
        checks[f"processed_{table}_exact"] = (
            path.stat().st_size == item["bytes"]
            and _sha_file(path) == item["sha256"]
            and len(stored) == item["rows"]
            and frame_exact
        )
    if manifest["canonical_full_range"]:
        checks["canonical_ranges_exact"] = manifest["date_ranges"] == {
            key: list(value) for key, value in canonical_date_ranges(config).items()
        }
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()
    if args.audit_only:
        checks = audit(args.output_root)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root, max_workers=args.max_workers))


if __name__ == "__main__":
    main()
