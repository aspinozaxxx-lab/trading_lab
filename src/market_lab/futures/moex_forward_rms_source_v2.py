"""Capture immutable forward MOEX RMS risk and anticipated-cashflow snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_forward_rms_risk_cashflow_source_v2.yaml"
CONFIG_SHA256: Final[str] = "48044ecf8928d68d1ff3a2f93ef6796db15970401e58546b32cc2933f67df926"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = PROJECT_ROOT / "data/forward/moex-rms-risk-cashflow-v2"
USER_AGENT: Final[str] = "market-lab-forward-rms/2.0 (research)"
TABLES: Final[tuple[str, ...]] = ("staticparams", "limits", "cashflow")
MOSCOW_TIMEZONE: Final[str] = "Europe/Moscow"


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
    return _sha_bytes(path.read_bytes())


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
        raise ValueError("MOEX RMS V2 config seal mismatch")
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent_path = PROJECT_ROOT / correction["parent_v1"]["protocol"]
    if correction["parent_v1"]["protocol_sha256"] != _sha_file(parent_path):
        raise ValueError("MOEX RMS V2 parent seal mismatch")
    parent = yaml.safe_load(parent_path.read_text(encoding="utf-8-sig"))
    if (
        correction.get("protocol_id") != "moex_forward_rms_risk_cashflow_source_v2"
        or correction.get("live_trading_allowed") is not False
        or correction["correction_scope"]["economic_hypothesis_changed"] is not False
        or correction["temporal_semantics_v2"]["cashflow_historical_backfill"]
        != "forbidden"
        or parent["objective"]["price_return_target_prediction_or_pnl_allowed"] is not False
    ):
        raise ValueError("MOEX RMS V2 invariants drifted")
    effective = dict(parent)
    for key in (
        "protocol_id",
        "protocol_version",
        "status",
        "declared_at_utc",
        "research_only",
        "live_trading_allowed",
        "parent_v1",
        "correction_scope",
        "temporal_semantics_v2",
        "source_quality_gates_v2",
        "output",
        "forbidden_columns",
    ):
        effective[key] = correction[key]
    return effective


def table_url(config: dict[str, Any], table: str, start: int) -> str:
    if table not in TABLES or start < 0:
        raise ValueError("invalid MOEX RMS table or cursor")
    endpoint = config["source"]["tables"][table]["endpoint"]
    query = urlencode({"iss.meta": "off", "start": start})
    return f"{config['source']['base_endpoint']}/{endpoint}?{query}"


def _block(payload: dict[str, Any], name: str) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        raise ValueError(f"missing MOEX RMS {name} block")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX RMS {name} rows")
    return pd.DataFrame(rows, columns=[str(value) for value in block["columns"]])


def parse_page(raw: bytes, table: str, config: dict[str, Any]) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    frame = _block(payload, table)
    required = config["source"]["tables"][table]["required_columns"]
    if set(required) - set(frame.columns):
        raise ValueError(f"MOEX RMS {table} schema drift")
    cursor = _block(payload, f"{table}.cursor")
    if len(cursor) != 1 or set(("INDEX", "TOTAL", "PAGESIZE")) - set(cursor.columns):
        raise ValueError(f"MOEX RMS {table} cursor drift")
    index = int(cursor.iloc[0]["INDEX"])
    total = int(cursor.iloc[0]["TOTAL"])
    if index < 0 or total < 0 or index + len(frame) > total:
        raise ValueError(f"MOEX RMS {table} cursor bounds invalid")
    return frame.loc[:, required], index, total


def normalize_table(
    frame: pd.DataFrame, table: str, retrieval: pd.Timestamp, config: dict[str, Any]
) -> pd.DataFrame:
    output = frame.copy()
    output["tradedate"] = pd.to_datetime(output["tradedate"], errors="raise").dt.normalize()
    updates = pd.to_datetime(output["updatetime"], errors="raise").dt.tz_localize(
        MOSCOW_TIMEZONE, ambiguous="raise", nonexistent="raise"
    ).dt.tz_convert("UTC")
    retrieval_utc = retrieval.tz_convert("UTC")
    if updates.gt(retrieval_utc).any():
        raise ValueError("MOEX RMS update time is after actual retrieval")
    output["source_table"] = table
    output["retrieved_at_utc"] = retrieval_utc
    output["available_at_utc"] = retrieval_utc
    risk_earliest = pd.Timestamp(config["temporal_semantics_v2"]["risk_source_date_earliest"])
    if table in {"staticparams", "limits"}:
        dates = output["tradedate"].drop_duplicates()
        if len(dates) != 1 or dates.iloc[0] < risk_earliest:
            raise ValueError("MOEX RMS risk source date escaped V2 forward boundary")
        if output["assetcode"].astype("string").duplicated().any():
            raise ValueError(f"duplicate MOEX RMS {table} assetcode")
    else:
        retrieval_date = retrieval_utc.tz_convert(MOSCOW_TIMEZONE).tz_localize(None).normalize()
        if output["tradedate"].gt(retrieval_date).any():
            raise ValueError("MOEX RMS cashflow date is in the future")
        if output.duplicated(["assetcode", "t"]).any():
            raise ValueError("duplicate MOEX RMS cashflow identity")
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("forbidden outcome column escaped into MOEX RMS source")
    return output.sort_values(
        ["assetcode"] + (["t"] if table == "cashflow" else []),
        kind="stable",
        ignore_index=True,
    )


def _fetch_table(
    client: SessionLike,
    table: str,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    start = 0
    frames: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    total: int | None = None
    while total is None or start < total:
        url = table_url(config, table, start)
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        raw = bytes(response.content)
        frame, index, page_total = parse_page(raw, table, config)
        if index != start or (total is not None and page_total != total):
            raise ValueError(f"MOEX RMS {table} pagination drift")
        total = page_total
        pages.append({"start": start, "url": url, "raw": raw, "rows": len(frame)})
        frames.append(frame)
        if len(frame) == 0 and start < total:
            raise ValueError(f"MOEX RMS {table} empty page before total")
        start += len(frame)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != total:
        raise ValueError(f"MOEX RMS {table} incomplete pagination")
    return combined, pages


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("MOEX RMS retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    if retrieval < pd.Timestamp(config["forward_boundary"]["earliest_allowed_retrieval_utc"]):
        raise ValueError("MOEX RMS retrieval escaped forward seal")
    client: SessionLike = session or requests.Session()
    normalized: dict[str, pd.DataFrame] = {}
    raw_pages: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:
        frame, pages = _fetch_table(client, table, config)
        normalized[table] = normalize_table(frame, table, retrieval, config)
        raw_pages[table] = pages
    risk_dates = {
        table: normalized[table]["tradedate"].dt.date.astype(str).unique().tolist()
        for table in ("staticparams", "limits")
    }
    if risk_dates["staticparams"] != risk_dates["limits"]:
        raise ValueError("MOEX RMS staticparams and limits dates differ")

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_manifest: list[dict[str, Any]] = []
        for table, pages in raw_pages.items():
            for page_number, page in enumerate(pages):
                path = temporary / f"raw_{table}_{page_number:04d}.json.gz"
                raw = page["raw"]
                path.write_bytes(gzip.compress(raw, mtime=0))
                raw_manifest.append(
                    {
                        "table": table,
                        "start": page["start"],
                        "url": page["url"],
                        "rows": page["rows"],
                        "path": path.name,
                        "response_bytes": len(raw),
                        "response_sha256": _sha_bytes(raw),
                        "stored_bytes": path.stat().st_size,
                        "stored_sha256": _sha_file(path),
                    }
                )
        processed: dict[str, Any] = {}
        for table, frame in normalized.items():
            path = temporary / f"{table}.parquet"
            frame.to_parquet(path, index=False)
            processed[table] = {
                "path": path.name,
                "rows": len(frame),
                "bytes": path.stat().st_size,
                "sha256": _sha_file(path),
            }
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "risk_source_date": risk_dates["staticparams"][0],
            "cashflow_source_dates": sorted(
                normalized["cashflow"]["tradedate"].dt.date.astype(str).unique().tolist()
            ),
            "forward_only": True,
            "contains_price_return_target_prediction_or_pnl": False,
            "raw_pages": raw_manifest,
            "processed": processed,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("MOEX RMS forward audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest["contains_price_return_target_prediction_or_pnl"] is False,
    }
    rebuilt_pages: dict[str, list[pd.DataFrame]] = {table: [] for table in TABLES}
    for index, item in enumerate(manifest["raw_pages"]):
        path = snapshot / item["path"]
        raw = gzip.decompress(path.read_bytes())
        checks[f"raw_stored_{index}"] = (
            path.stat().st_size == item["stored_bytes"]
            and _sha_file(path) == item["stored_sha256"]
        )
        checks[f"raw_response_{index}"] = (
            len(raw) == item["response_bytes"]
            and _sha_bytes(raw) == item["response_sha256"]
            and item["url"] == table_url(config, item["table"], int(item["start"]))
        )
        frame, page_start, _ = parse_page(raw, item["table"], config)
        checks[f"raw_cursor_{index}"] = page_start == int(item["start"])
        rebuilt_pages[item["table"]].append(frame)
    rebuilt: dict[str, pd.DataFrame] = {}
    for table in TABLES:
        combined = pd.concat(rebuilt_pages[table], ignore_index=True)
        rebuilt[table] = normalize_table(combined, table, retrieval, config)
        item = manifest["processed"][table]
        path = snapshot / item["path"]
        stored = pd.read_parquet(path)
        try:
            pd.testing.assert_frame_equal(stored, rebuilt[table], check_dtype=False)
            replay = True
        except AssertionError:
            replay = False
        checks[f"processed_{table}_exact"] = (
            path.stat().st_size == item["bytes"]
            and _sha_file(path) == item["sha256"]
            and len(stored) == item["rows"]
        )
        checks[f"raw_replay_{table}_exact"] = replay
    checks["risk_dates_equal"] = (
        rebuilt["staticparams"]["tradedate"].unique().tolist()
        == rebuilt["limits"]["tradedate"].unique().tolist()
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
