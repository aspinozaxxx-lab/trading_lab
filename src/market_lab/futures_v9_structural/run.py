"""Official MOEX ISS downloader and executable V9 structural benchmark."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

from market_lab.futures_v9_structural.structural import (
    build_asset_panel,
    build_synchronized_panel,
    evaluate_strategy_family,
    truncate_contract_rows,
    validate_contract_rows,
)
from market_lab.io_utils import atomic_write_bytes, write_json

ISS_BASE = "https://iss.moex.com/iss"
SERIES_URL = f"{ISS_BASE}/statistics/engines/futures/markets/forts/series.json"
HISTORY_TEMPLATE = (
    f"{ISS_BASE}/history/engines/futures/markets/forts/boards/RFUD/securities/{{secid}}.json"
)
OUTRIGHT_PATTERN = re.compile(r"^[A-Za-z]+[FGHJKMNQUVXZ]\d(?:_\d{4})?$")
ARCHIVE_SUFFIX = re.compile(r"_\d{4}$")
USER_AGENT = "market-lab-v9-structural/1.0 (MOEX ISS research)"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
        raise ValueError(f"MOEX payload missing {name}")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"invalid MOEX table {name}")
    normalized = [str(column).lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"duplicate MOEX columns in {name}")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"malformed MOEX row in {name}")
    return pd.DataFrame(rows, columns=normalized)


def _request_json(url: str, *, attempts: int = 5) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX response is not an object")
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    raise RuntimeError(f"MOEX request failed: {url}: {last_error}") from last_error


def _with_query(url: str, values: Mapping[str, Any]) -> str:
    return f"{url}?{urlencode([(key, value) for key, value in values.items()])}"


def fetch_filtered_catalog(config: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch current metadata but retain only pre-2026 outright deliveries in scope."""
    url = _with_query(SERIES_URL, {"iss.meta": "off", "show_expired": 1})
    payload = _request_json(url)
    frame = _table(payload, "series")
    required = {
        "secid",
        "name",
        "start_date",
        "expiration_date",
        "asset_code",
        "underlying_asset",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"series table missing {sorted(missing)}")
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="coerce").dt.normalize()
    frame["expiration_date"] = pd.to_datetime(
        frame["expiration_date"], errors="coerce"
    ).dt.normalize()
    candidate_codes = {str(item["asset_code"]) for item in config["universe"]["candidates"]}
    source_start = pd.Timestamp(config["dates"]["source_start"])
    development_end = pd.Timestamp(config["dates"]["development_end"])
    keep = (
        frame["asset_code"].astype(str).isin(candidate_codes)
        & frame["secid"]
        .astype(str)
        .map(lambda value: OUTRIGHT_PATTERN.fullmatch(value) is not None)
        & frame["start_date"].le(development_end)
        & frame["expiration_date"].ge(source_start)
        & frame["expiration_date"].le(development_end)
    )
    frame = frame.loc[keep, sorted(required)].copy()
    if frame.empty:
        raise ValueError("filtered official series catalog is empty")
    frame["canonical_secid"] = (
        frame["secid"].astype(str).map(lambda value: ARCHIVE_SUFFIX.sub("", value))
    )
    frame["contract_id"] = (
        frame["asset_code"].astype(str)
        + ":"
        + frame["canonical_secid"]
        + ":"
        + frame["expiration_date"].dt.strftime("%Y-%m-%d")
    )
    frame = frame.sort_values(
        ["asset_code", "expiration_date", "contract_id", "secid"], ignore_index=True
    )
    normalized_source = {
        "request_url": url,
        "provider": "MOEX ISS",
        "note": "normalized catalog is filtered to expiration <= 2025-12-31 before persistence",
        "columns": frame.columns.tolist(),
        "data": frame.astype(object).where(frame.notna(), None).values.tolist(),
    }
    return frame, normalized_source


def paginate_history(
    fetch_page: Callable[[int], tuple[str, dict[str, Any]]],
    *,
    maximum_pages: int = 100,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Follow MOEX history.cursor exactly and reject truncation or overlap."""
    frames: list[pd.DataFrame] = []
    archived: list[dict[str, Any]] = []
    offset = 0
    expected_total: int | None = None
    seen_keys: set[tuple[str, str, str]] = set()
    for _ in range(maximum_pages):
        url, payload = fetch_page(offset)
        frame = _table(payload, "history")
        cursor = _table(payload, "history.cursor")
        if len(cursor) != 1 or not {"index", "total", "pagesize"}.issubset(cursor.columns):
            raise ValueError("invalid history.cursor")
        cursor_index = int(cursor.iloc[0]["index"])
        total = int(cursor.iloc[0]["total"])
        page_size = int(cursor.iloc[0]["pagesize"])
        if cursor_index != offset or page_size <= 0 or total < 0:
            raise ValueError("non-canonical MOEX cursor")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError("MOEX cursor total changed during pagination")
        expected_rows = min(page_size, max(total - offset, 0))
        if len(frame) != expected_rows:
            raise ValueError(f"truncated MOEX page at {offset}: {len(frame)} != {expected_rows}")
        if not frame.empty:
            if not {"tradedate", "secid", "boardid"}.issubset(frame.columns):
                raise ValueError("history page lacks identity columns")
            keys = list(
                zip(
                    frame["tradedate"].astype(str),
                    frame["secid"].astype(str),
                    frame["boardid"].astype(str),
                    strict=True,
                )
            )
            if any(key in seen_keys for key in keys) or len(keys) != len(set(keys)):
                raise ValueError("duplicate history row across MOEX pages")
            seen_keys.update(keys)
            frames.append(frame)
        archived.append({"request_url": url, "payload": payload})
        offset += len(frame)
        if offset == total:
            break
        if len(frame) == 0 or offset > total:
            raise ValueError("MOEX cursor did not progress")
    else:
        raise ValueError("MOEX history pagination exceeded maximum_pages")
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != (expected_total or 0):
        raise ValueError("incomplete MOEX history pagination")
    return combined, archived


def _fetch_contract_history(task: Mapping[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    secid = str(task["secid"])
    asset_code = str(task["asset_code"])
    contract_id = str(task["contract_id"])
    expiration = pd.Timestamp(task["expiration_date"])
    start_date = max(pd.Timestamp(task["start_date"]), pd.Timestamp(task["source_start"]))
    end_date = min(expiration, pd.Timestamp(task["development_end"]))
    base_url = HISTORY_TEMPLATE.format(secid=secid)

    def fetch(offset: int) -> tuple[str, dict[str, Any]]:
        url = _with_query(
            base_url,
            {
                "iss.meta": "off",
                "from": start_date.date().isoformat(),
                "till": end_date.date().isoformat(),
                "start": offset,
            },
        )
        return url, _request_json(url)

    frame, archive = paginate_history(fetch)
    if frame.empty:
        return frame, archive
    if not frame["secid"].astype(str).eq(secid).all():
        raise ValueError(f"MOEX returned another SECID for {secid}")
    dates = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    if dates.lt(start_date).any() or dates.gt(end_date).any():
        raise ValueError(f"MOEX history escaped requested bounds for {secid}")
    if dates.ge(pd.Timestamp("2026-01-01")).any():
        raise ValueError(f"protected 2026 row for {secid}")
    close = pd.to_numeric(frame.get("close"), errors="coerce")
    if "settleprice" in frame:
        close = close.fillna(pd.to_numeric(frame["settleprice"], errors="coerce"))
    output = pd.DataFrame(
        {
            "asset_code": asset_code,
            "contract_id": contract_id,
            "secid": secid,
            "trade_date": dates,
            "expiration_date": expiration,
            "close": close,
            "value": pd.to_numeric(frame.get("value"), errors="coerce").fillna(0.0),
            "volume": pd.to_numeric(frame.get("volume"), errors="coerce").fillna(0.0),
            "open_interest": pd.to_numeric(frame.get("openposition"), errors="coerce").fillna(0.0),
        }
    )
    output = output.loc[output["close"].notna()].reset_index(drop=True)
    return output, archive


def download_contract_history(
    config: Mapping[str, Any],
    output_root: Path,
    *,
    workers: int = 8,
) -> tuple[Path, Path, Path]:
    """Download every selected contract page and persist a content-addressed source bundle."""
    catalog, catalog_source = fetch_filtered_catalog(config)
    tasks = []
    for row in catalog.to_dict("records"):
        tasks.append(
            {
                **row,
                "source_start": config["dates"]["source_start"],
                "development_end": config["dates"]["development_end"],
            }
        )
    frames: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch_contract_history, task): task for task in tasks}
        for future in as_completed(futures):
            frame, archived = future.result()
            if not frame.empty:
                frames.append(frame)
            pages.extend(archived)
    if not frames:
        raise ValueError("MOEX returned no daily futures rows")
    combined = pd.concat(frames, ignore_index=True)
    combined = validate_contract_rows(combined, pd.Timestamp(config["dates"]["forbidden_from"]))
    combined = truncate_contract_rows(combined, pd.Timestamp(config["dates"]["development_end"]))
    output_root.mkdir(parents=True, exist_ok=True)
    history_path = output_root / "contract_daily_2017_2025.parquet"
    _atomic_parquet(history_path, combined)
    catalog_path = output_root / "official_series_catalog_through_2025.parquet"
    _atomic_parquet(catalog_path, catalog)
    archive_records = [catalog_source, *sorted(pages, key=lambda item: item["request_url"])]
    archive_body = b"\n".join(_canonical_json(record) for record in archive_records) + b"\n"
    archive_bytes = gzip.compress(archive_body, compresslevel=6, mtime=0)
    archive_path = output_root / "official_moex_iss_source.jsonl.gz"
    atomic_write_bytes(archive_path, archive_bytes)
    config_path = Path("configs/futures_v9_structural.yaml").resolve()
    manifest_payload = {
        "protocol_id": config["protocol_id"],
        "provider": "MOEX ISS",
        "official_source_urls": [SERIES_URL, HISTORY_TEMPLATE],
        "request_count": len(pages) + 1,
        "history_requests_all_till_lte": config["dates"]["development_end"],
        "protected_from": config["dates"]["forbidden_from"],
        "config": {
            "path": config_path.as_posix(),
            "sha256": _sha256_file(config_path),
        },
        "artifacts": {
            "contract_history": {
                "path": history_path.resolve().as_posix(),
                "bytes": history_path.stat().st_size,
                "sha256": _sha256_file(history_path),
                "rows": len(combined),
                "minimum_date": combined["trade_date"].min(),
                "maximum_date": combined["trade_date"].max(),
                "assets": int(combined["asset_code"].nunique()),
                "contracts": int(combined["contract_id"].nunique()),
            },
            "filtered_catalog": {
                "path": catalog_path.resolve().as_posix(),
                "bytes": catalog_path.stat().st_size,
                "sha256": _sha256_file(catalog_path),
                "rows": len(catalog),
                "maximum_expiration": catalog["expiration_date"].max(),
            },
            "raw_source_archive": {
                "path": archive_path.resolve().as_posix(),
                "bytes": archive_path.stat().st_size,
                "sha256": _sha256_file(archive_path),
                "records": len(archive_records),
            },
        },
    }
    identity = _sha256_bytes(_canonical_json(manifest_payload))
    manifest_path = output_root / f"manifest_{identity}.json"
    write_json(manifest_path, {**manifest_payload, "manifest_payload_sha256": identity})
    return history_path, catalog_path, manifest_path


def run_benchmark(
    config_path: Path,
    data_root: Path,
    runs_root: Path,
    *,
    download: bool,
    workers: int,
) -> Path:
    """Build data if requested and evaluate all sealed strategies."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("V9 config must be a mapping")
    if download:
        history_path, _, source_manifest = download_contract_history(
            config, data_root, workers=workers
        )
    else:
        history_path = data_root / "contract_daily_2017_2025.parquet"
        manifests = sorted(data_root.glob("manifest_*.json"))
        if not history_path.exists() or not manifests:
            raise FileNotFoundError("downloaded V9 data or source manifest is missing")
        source_manifest = manifests[-1]
    contract_rows = pd.read_parquet(history_path)
    contract_rows = truncate_contract_rows(
        contract_rows, pd.Timestamp(config["dates"]["development_end"])
    )
    panel = build_asset_panel(contract_rows, config)
    synchronized, synchronized_schema = build_synchronized_panel(panel)
    ledgers, summary = evaluate_strategy_family(panel, config)
    implementation_paths = [
        Path(__file__).resolve(),
        (Path(__file__).parent / "structural.py").resolve(),
    ]
    identity_payload = {
        "config_sha256": _sha256_file(config_path),
        "source_manifest_sha256": _sha256_file(source_manifest),
        "history_sha256": _sha256_file(history_path),
        "implementation_sha256": {path.name: _sha256_file(path) for path in implementation_paths},
    }
    run_id = _sha256_bytes(_canonical_json(identity_payload))[:16]
    run_dir = runs_root / f"structural_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    panel_path = run_dir / "causal_asset_panel.parquet"
    _atomic_parquet(panel_path, panel)
    synchronized_path = run_dir / "synchronized_market_state.parquet"
    _atomic_parquet(synchronized_path, synchronized)
    ledger_records = {}
    for strategy_id, ledger in ledgers.items():
        path = run_dir / f"ledger_{strategy_id}.parquet"
        _atomic_parquet(path, ledger.reset_index(names="trade_date"))
        ledger_records[strategy_id] = {
            "path": path.name,
            "sha256": _sha256_file(path),
            "rows": len(ledger),
        }
    result = {
        "research_only": True,
        "claim": "fast daily proxy; exact contract specifications and fills remain pending",
        "run_id": run_id,
        "identity": identity_payload,
        "source_manifest": source_manifest.resolve().as_posix(),
        "panel": {
            "path": panel_path.name,
            "sha256": _sha256_file(panel_path),
            "rows": len(panel),
            "assets": sorted(panel["asset_code"].unique().tolist()),
            "minimum_date": panel["trade_date"].min(),
            "maximum_date": panel["trade_date"].max(),
        },
        "synchronized_market_state": {
            "path": synchronized_path.name,
            "sha256": _sha256_file(synchronized_path),
            "rows": len(synchronized),
            "columns": len(synchronized.columns),
            "schema": synchronized_schema,
        },
        "ledgers": ledger_records,
        "results": summary,
    }
    write_json(run_dir / "results.json", result)
    write_json(run_dir / "run_identity.json", identity_payload)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/futures_v9_structural.yaml"))
    parser.add_argument(
        "--data-root", type=Path, default=Path("data/processed/futures_v9_structural")
    )
    parser.add_argument("--runs-root", type=Path, default=Path("runs/futures_v9_structural"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-download", action="store_true")
    arguments = parser.parse_args()
    output = run_benchmark(
        arguments.config.resolve(),
        arguments.data_root.resolve(),
        arguments.runs_root.resolve(),
        download=not arguments.no_download,
        workers=arguments.workers,
    )
    print(output)


if __name__ == "__main__":
    main()
