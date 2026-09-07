"""Source-only FO flow/depth sample with immutable inventory reconciliation."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
import yaml

from market_lab.futures import moex_algopack_fo_historical_inventory_v1 as transport
from market_lab.futures import moex_algopack_fo_historical_inventory_v2 as inventory

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = "moex_algopack_fo_flow_depth_sample_v1"
MODULE_RELATIVE = f"src/market_lab/futures/{PROTOCOL}.py"
CONFIG_RELATIVE = f"configs/{PROTOCOL}.yaml"
COMMON = ["tradedate", "tradetime", "secid", "asset_code", "SYSTIME"]
FIELDS = {
    "tradestats": ["trades", "trades_b", "trades_s", "vol", "vol_b", "vol_s",
                   "val", "val_b", "val_s", "disb"],
    "obstats": ["spread_l1", "spread_l10", "levels_b", "levels_s",
                "vol_b_l1", "vol_s_l1", "vol_b_l10", "vol_s_l10"],
}
COUNT_FIELDS = {"trades", "trades_b", "trades_s", "vol", "vol_b", "vol_s"}
SIGNED_FIELDS = {"disb", "spread_l1", "spread_l10"}
EXPECTED_CONFIG = {
    "protocol_id": PROTOCOL, "sample_date": "2024-10-15",
    "contracts": ["SiZ4", "RIZ4", "BRX4", "MXZ4"],
    "columns": {dataset: COMMON + fields for dataset, fields in FIELDS.items()},
    "max_pages_per_contract_dataset": 10, "request_interval_seconds": 0.5,
    "protected_holdout_start": "2026-01-01",
    "asset_code_missing_policy": "preserve_null_or_empty_and_flag",
    "source_only": True, "historical_model_eligible": False, "live_trading_allowed": False,
    "parent_inventory": {
        "path": "data/processed/algopack/moex_algopack_fo_historical_inventory_v2_1da8655bf03d",
        "seal_sha256": "1da8655bf03da09c5c6670951d3acb9acfc77536e48f9b0f9e38aae3439d09f4",
        "manifest_sha256": "89896f3a1647db6a7d1c794cc98745dec48123a4dbe6355baccfac2d8894f242",
    },
}
InventoryFailure = transport.InventoryFailure
sha = transport.sha
_json_bytes = transport._json_bytes
_identity = transport._identity
_fetch = transport._fetch


def verify_seal(seal_sha: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{64}", seal_sha) is None:
        raise ValueError("invalid sample seal identity")
    raw = (PROJECT_ROOT / f"configs/{PROTOCOL}.seal.json").read_bytes()
    if sha(raw) != seal_sha:
        raise ValueError("sample seal identity mismatch")
    seal = json.loads(raw.decode("utf-8-sig"))
    files = seal.get("files", {})
    required = {MODULE_RELATIVE, CONFIG_RELATIVE, transport.MODULE_RELATIVE,
                inventory.MODULE_RELATIVE, "src/market_lab/__init__.py",
                "src/market_lab/futures/__init__.py"}
    if seal.get("protocol_id") != PROTOCOL or not required.issubset(files):
        raise ValueError("sample closure is incomplete")
    for relative, digest in files.items():
        path = (PROJECT_ROOT / relative).resolve()
        if not path.is_relative_to(PROJECT_ROOT.resolve()) or sha(path.read_bytes()) != digest:
            raise ValueError("sample dependency hash mismatch")
    path = PROJECT_ROOT / CONFIG_RELATIVE
    raw_config = path.read_bytes()
    sidecar = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if (sidecar != sha(raw_config)
            or yaml.safe_load(raw_config.decode("utf-8-sig")) != EXPECTED_CONFIG):
        raise ValueError("sample configuration drift")
    return {"seal_sha256": seal_sha, "config_sha256": sha(raw_config), "files": files}


def load_parent(storage_root: Path) -> list[dict]:
    parent = EXPECTED_CONFIG["parent_inventory"]
    path = (storage_root / parent["path"]).resolve()
    if not path.is_relative_to(storage_root.resolve()):
        raise ValueError("parent inventory escaped storage root")
    inventory.audit(path, parent["seal_sha256"], parent["manifest_sha256"])
    return json.loads((path / "inventory.json").read_bytes())


def request_url(dataset: str, secid: str, start: int) -> str:
    if dataset not in FIELDS or secid not in EXPECTED_CONFIG["contracts"]:
        raise ValueError("sample request outside frozen contract set")
    if type(start) is not int or start < 0:
        raise ValueError("invalid sample cursor")
    query = urlencode({
        "from": EXPECTED_CONFIG["sample_date"], "till": EXPECTED_CONFIG["sample_date"],
        "latest": 0, "start": start, "iss.meta": "off", "iss.only": "data,data.cursor",
        "data.columns": ",".join(EXPECTED_CONFIG["columns"][dataset]),
    })
    return f"https://apim.moex.com/iss/datashop/algopack/fo/{dataset}/{secid}.json?{query}"


def parse_page(raw: bytes, dataset: str, secid: str, start: int) -> tuple[list[dict], dict]:
    request_url(dataset, secid, start)
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=transport._unique_pairs)
        if set(payload) != {"data", "data.cursor"} or set(payload["data"]) != {"columns", "data"}:
            raise ValueError("unexpected sample blocks")
        data = payload["data"]
        columns = EXPECTED_CONFIG["columns"][dataset]
        if data["columns"] != columns or not isinstance(data["data"], list):
            raise ValueError("sample column schema mismatch")
        if any(not isinstance(row, list) or len(row) != len(columns) for row in data["data"]):
            raise ValueError("sample row width mismatch")
        metadata = {"data": {"columns": COMMON, "data": [row[:5] for row in data["data"]]},
                    "data.cursor": payload["data.cursor"]}
        rows, cursor = inventory.parse_page(_json_bytes(metadata), dataset, start)
        for row, original in zip(rows, data["data"], strict=True):
            if row["secid"] != secid:
                raise ValueError("sample returned another contract")
            for field, value in zip(FIELDS[dataset], original[5:], strict=True):
                if value is not None:
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError("sample numeric value is invalid")
                    if field not in SIGNED_FIELDS and value < 0:
                        raise ValueError("sample unsigned value is negative")
                    if field in COUNT_FIELDS and value != math.trunc(value):
                        raise ValueError("sample count is not integral")
                row[field] = value
        return rows, cursor
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("invalid source-only sample response") from None


def _replay(directory: Path, pages: list[dict]) -> list[dict]:
    cases = [(dataset, secid) for dataset in FIELDS for secid in EXPECTED_CONFIG["contracts"]]
    if any((p["dataset"], p["secid"]) not in cases for p in pages):
        raise ValueError("unknown sample request case")
    paths = [(directory / p["path"]).resolve() for p in pages]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate sample raw path")
    output, seen = [], set()
    for dataset, secid in cases:
        selected = [p for p in pages if (p["dataset"], p["secid"]) == (dataset, secid)]
        if not selected or len(selected) > EXPECTED_CONFIG["max_pages_per_contract_dataset"]:
            raise ValueError("missing or excessive sample pages")
        start, total = 0, None
        for number, page in enumerate(selected):
            path = (directory / page["path"]).resolve()
            if not path.is_relative_to(directory.resolve()) or _identity(path) != {
                key: page[key] for key in ("path", "bytes", "sha256")
            }:
                raise ValueError("sample raw identity mismatch")
            rows, cursor = parse_page(path.read_bytes(), dataset, secid, start)
            url = request_url(dataset, secid, start)
            if (page["request_url"] != url or page["final_url"] != url
                    or page["http_status"] != 200 or page["bearer_sent"] is not True
                    or page["cursor"] != cursor):
                raise ValueError("sample transport identity mismatch")
            if total is not None and total != cursor["TOTAL"]:
                raise ValueError("sample cursor total changed")
            total = cursor["TOTAL"]
            if datetime.fromisoformat(page["retrieved_at_utc"]).tzinfo is None:
                raise ValueError("sample retrieval lacks timezone")
            for row in rows:
                key = (dataset, secid, row["tradedate"], row["tradetime"])
                if key in seen:
                    raise ValueError("duplicate sample observation")
                seen.add(key)
                output.append({**row, "retrieved_at_utc": page["retrieved_at_utc"],
                               "available_at": None, "original_version_verified": False,
                               "historical_model_eligible": False})
            start += len(rows)
            if start >= total and number != len(selected) - 1:
                raise ValueError("sample continued after terminal cursor")
        if start != total:
            raise ValueError("sample cursor did not finish")
    return output


def diagnostics(rows: list[dict], parent_rows: list[dict]) -> dict:
    result, coverage, joint = {}, {}, {}
    for dataset, fields in FIELDS.items():
        for secid in EXPECTED_CONFIG["contracts"]:
            case = f"{dataset}:{secid}"
            selected = [r for r in rows if r["dataset"] == dataset and r["secid"] == secid]
            expected = [r for r in parent_rows if r["dataset"] == dataset and r["secid"] == secid]
            def key(row: dict) -> tuple[str, str]:
                return row["tradedate"], row["tradetime"]
            actual_by_key, parent_by_key = ({key(r): r for r in group}
                                            for group in (selected, expected))
            common = actual_by_key.keys() & parent_by_key.keys()
            mismatch = sorted(k for k in common
                              if actual_by_key[k]["asset_code"] != parent_by_key[k]["asset_code"])
            revised = sorted(k for k in common
                             if actual_by_key[k]["SYSTIME"] != parent_by_key[k]["SYSTIME"])
            coverage[case] = {
                "sample_keys": len(actual_by_key), "inventory_keys": len(parent_by_key),
                "missing_keys": sorted(parent_by_key.keys() - actual_by_key.keys()),
                "extra_keys": sorted(actual_by_key.keys() - parent_by_key.keys()),
                "asset_metadata_mismatch_keys": mismatch, "system_timestamp_changed_keys": revised,
                "admitted": bool(parent_by_key) and actual_by_key.keys() == parent_by_key.keys()
                and not mismatch and not revised,
            }
            result[case] = {
                "rows": len(selected),
                "missing_asset_code_rows": sum(r["asset_code_missing"] for r in selected),
                "fields": {field: {
                    "null": sum(r[field] is None for r in selected),
                    "zero": sum(r[field] == 0 for r in selected),
                    "negative": sum(r[field] is not None and r[field] < 0 for r in selected),
                } for field in fields},
            }
    for secid in EXPECTED_CONFIG["contracts"]:
        sets = {dataset: {(r["tradedate"], r["tradetime"]) for r in rows
                          if r["dataset"] == dataset and r["secid"] == secid} for dataset in FIELDS}
        joint[secid] = {"both": len(sets["tradestats"] & sets["obstats"]),
                        "tradestats_only": len(sets["tradestats"] - sets["obstats"]),
                        "obstats_only": len(sets["obstats"] - sets["tradestats"])}
    return {"field_counts": result, "inventory_comparison": coverage, "joint_coverage": joint,
            "sample_coverage_admitted": all(case["admitted"] for case in coverage.values())}


def collect(storage_root: Path, seal_sha: str, *, session: object | None = None) -> Path:
    closure = verify_seal(seal_sha)
    parent_rows = load_parent(storage_root)
    token = os.environ.get(transport.TOKEN_ENV, "")
    if not token.strip():
        raise ValueError("MOEX_ALGOPACK_TOKEN is required")
    parent = storage_root.resolve() / "data/processed/algopack"
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / f"{PROTOCOL}_{seal_sha[:12]}"
    if final.exists():
        raise FileExistsError("immutable sample already exists")
    staging = Path(tempfile.mkdtemp(prefix=f".{PROTOCOL}_", dir=parent))
    network, pages = session or requests.Session(), []
    phase, dataset, secid, start, status = "setup", None, None, 0, None
    try:
        for dataset in FIELDS:
            for secid in EXPECTED_CONFIG["contracts"]:
                start, total = 0, None
                for number in range(EXPECTED_CONFIG["max_pages_per_contract_dataset"]):
                    if pages:
                        time.sleep(EXPECTED_CONFIG["request_interval_seconds"])
                    url = request_url(dataset, secid, start)
                    phase, status = "transport", None
                    raw, evidence = _fetch(network, url, token)
                    status, phase = evidence["http_status"], "parse_page"
                    rows, cursor = parse_page(raw, dataset, secid, start)
                    if total is not None and total != cursor["TOTAL"]:
                        raise ValueError("sample cursor total changed")
                    total = cursor["TOTAL"]
                    path = staging / f"raw_{dataset}_{secid}_{number:03d}.json"
                    path.write_bytes(raw)
                    pages.append({**_identity(path), **evidence, "dataset": dataset, "secid": secid,
                                  "request_url": url, "cursor": cursor,
                                  "retrieved_at_utc": datetime.now(UTC).isoformat()})
                    start += len(rows)
                    if start == total:
                        break
                else:
                    raise ValueError("sample page ceiling reached")
        phase = "raw_replay"
        rows = _replay(staging, pages)
        path = staging / "sample.json"
        path.write_bytes(_json_bytes(rows))
        manifest = {
            "protocol_id": PROTOCOL, "closure": closure,
            "parent_inventory": EXPECTED_CONFIG["parent_inventory"], "pages": pages,
            "sample": _identity(path), "diagnostics": diagnostics(rows, parent_rows),
            "source_only": True, "current_vintage": True, "historical_model_eligible": False,
            "live_trading_allowed": False, "status": "complete",
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(_json_bytes(manifest))
        phase = "audit"
        audit(staging, storage_root, seal_sha, sha(manifest_path.read_bytes()))
        staging.rename(final)
        return final
    except Exception as error:
        if isinstance(error, InventoryFailure):
            phase, status = error.phase, error.http_status
        diagnostic = staging / "failure.json"
        diagnostic.write_bytes(_json_bytes({
            "phase": phase, "dataset": dataset, "secid": secid, "start": start,
            "http_status": status, "failed_response_raw_saved": False,
            "validated_pages_saved": len(pages), "status": "failed_no_canonical_output",
        }))
        raise InventoryFailure(phase, status, str(diagnostic)) from None


def audit(directory: Path, storage_root: Path, seal_sha: str, manifest_sha: str) -> dict:
    closure, parent_rows = verify_seal(seal_sha), load_parent(storage_root)
    raw = (directory / "manifest.json").read_bytes()
    if sha(raw) != manifest_sha:
        raise ValueError("sample manifest identity mismatch")
    manifest = json.loads(raw)
    rows = _replay(directory, manifest["pages"])
    path = directory / "sample.json"
    # JSON round-trip makes the timestamp-key list representation exact.
    expected_diagnostics = json.loads(_json_bytes(diagnostics(rows, parent_rows)))
    checks = {
        "protocol_exact": manifest["protocol_id"] == PROTOCOL,
        "closure_exact": manifest["closure"] == closure,
        "parent_inventory_exact": manifest["parent_inventory"]
        == EXPECTED_CONFIG["parent_inventory"],
        "sample_identity": manifest["sample"] == _identity(path),
        "sample_raw_replay_exact": json.loads(path.read_bytes()) == rows,
        "diagnostics_raw_replay_exact": manifest["diagnostics"] == expected_diagnostics,
        "source_only": manifest["source_only"] is True,
        "current_vintage": manifest["current_vintage"] is True,
        "historical_ineligible": manifest["historical_model_eligible"] is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "complete": manifest["status"] == "complete",
    }
    if not all(checks.values()):
        raise ValueError("sample audit failed")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--manifest-sha")
    args = parser.parse_args()
    try:
        if args.audit:
            if not args.manifest_sha:
                raise ValueError("sample audit requires manifest SHA")
            checks = audit(args.audit, args.storage_root, args.seal_sha, args.manifest_sha)
            print(json.dumps(checks))
        else:
            output = collect(args.storage_root, args.seal_sha)
            print(json.dumps({"output": str(output),
                              "manifest_sha256": sha((output / "manifest.json").read_bytes())}))
    except InventoryFailure as error:
        print(json.dumps({"status": "failed", "phase": error.phase,
                          "http_status": error.http_status,
                          "diagnostic_path": error.diagnostic_path}))
        raise SystemExit(2) from None
    except Exception:
        raise SystemExit("Sample operation failed; sensitive error details suppressed") from None


if __name__ == "__main__":
    main()
