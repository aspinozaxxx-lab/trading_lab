"""V2 metadata-only FO inventory: preserve missing asset codes without inference."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

from market_lab.futures import moex_algopack_fo_historical_inventory_v1 as parent_source

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = "moex_algopack_fo_historical_inventory_v2"
PARENT_MODULE_RELATIVE = parent_source.MODULE_RELATIVE
MODULE_RELATIVE = f"src/market_lab/futures/{PROTOCOL}.py"
CONFIG_RELATIVE = f"configs/{PROTOCOL}.yaml"
TOKEN_ENV = "MOEX_ALGOPACK_TOKEN"
COLUMNS = ["tradedate", "tradetime", "secid", "asset_code", "SYSTIME"]
EXPECTED_CONFIG = {
    "protocol_id": PROTOCOL,
    "sample_date": "2024-10-15",
    "datasets": ["tradestats", "obstats"],
    "columns": COLUMNS,
    "max_pages_per_dataset": 200,
    "request_interval_seconds": 0.5,
    "protected_holdout_start": "2026-01-01",
    "source_only": True,
    "historical_model_eligible": False,
    "live_trading_allowed": False,
    "asset_code_missing_policy": "preserve_null_or_empty_and_flag",
}


InventoryFailure = parent_source.InventoryFailure
sha = parent_source.sha
_json_bytes = parent_source._json_bytes
request_url = parent_source.request_url
_unique_pairs = parent_source._unique_pairs
_fetch = parent_source._fetch
_identity = parent_source._identity


def verify_seal(seal_sha: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{64}", seal_sha) is None:
        raise ValueError("invalid seal identity")
    seal_path = PROJECT_ROOT / f"configs/{PROTOCOL}.seal.json"
    raw = seal_path.read_bytes()
    if sha(raw) != seal_sha:
        raise ValueError("seal identity mismatch")
    seal = json.loads(raw.decode("utf-8-sig"))
    files = seal.get("files", {})
    required = {
        MODULE_RELATIVE, CONFIG_RELATIVE, PARENT_MODULE_RELATIVE,
        "src/market_lab/__init__.py", "src/market_lab/futures/__init__.py",
    }
    if seal.get("protocol_id") != PROTOCOL or not required.issubset(files):
        raise ValueError("incomplete source closure")
    for relative, digest in files.items():
        path = (PROJECT_ROOT / relative).resolve()
        if not path.is_relative_to(PROJECT_ROOT.resolve()) or sha(path.read_bytes()) != digest:
            raise ValueError("source closure file mismatch")
    config_path = PROJECT_ROOT / CONFIG_RELATIVE
    config_raw = config_path.read_bytes()
    sidecar = config_path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(config_raw.decode("utf-8-sig"))
    if sidecar != sha(config_raw) or config != EXPECTED_CONFIG:
        raise ValueError("source configuration drift")
    return {"seal_sha256": seal_sha, "config_sha256": sha(config_raw), "files": files}


def parse_page(raw: bytes, dataset: str, expected_start: int) -> tuple[list[dict], dict]:
    request_url(dataset, expected_start)
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs)
        if set(payload) != {"data", "data.cursor"}:
            raise ValueError("unexpected inventory blocks")
        data, cursor = payload["data"], payload["data.cursor"]
        if set(data) != {"columns", "data"} or set(cursor) != {"columns", "data"}:
            raise ValueError("unexpected inventory block fields")
        if data["columns"] != COLUMNS or cursor["columns"] != ["INDEX", "TOTAL", "PAGESIZE"]:
            raise ValueError("inventory column schema mismatch")
        if len(cursor["data"]) != 1 or len(cursor["data"][0]) != 3:
            raise ValueError("invalid inventory cursor")
        index, total, page_size = cursor["data"][0]
        if any(type(value) is not int for value in (index, total, page_size)):
            raise ValueError("noninteger inventory cursor")
        if index != expected_start or total < index or page_size <= 0:
            raise ValueError("inventory cursor bounds mismatch")
        rows = data["data"]
        if not isinstance(rows, list) or len(rows) != min(page_size, total - index):
            raise ValueError("inventory page is incomplete")
        normalized, seen = [], set()
        for values in rows:
            if not isinstance(values, list) or len(values) != len(COLUMNS):
                raise ValueError("invalid inventory row width")
            if any(not isinstance(value, str) or not value
                   for index, value in enumerate(values) if index != 3):
                raise ValueError("invalid inventory metadata type")
            if values[3] is not None and not isinstance(values[3], str):
                raise ValueError("asset_code must be a string or null")
            asset_code_missing = values[3] is None or values[3] == ""
            row = dict(zip(COLUMNS, values, strict=True))
            if row["tradedate"] != EXPECTED_CONFIG["sample_date"]:
                raise ValueError("inventory row escaped sample date")
            parsed_time = datetime.strptime(row["tradetime"], "%H:%M:%S")
            if parsed_time.strftime("%H:%M:%S") != row["tradetime"]:
                raise ValueError("invalid observation time")
            system_time = datetime.fromisoformat(row["SYSTIME"])
            if system_time.tzinfo is not None or system_time < datetime.fromisoformat(
                row["tradedate"] + " " + row["tradetime"]
            ):
                raise ValueError("invalid source-system timestamp")
            if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", row[key]) is None
                   for key in ("secid", "asset_code")
                   if key != "asset_code" or not asset_code_missing):
                raise ValueError("invalid contract identity")
            key = (row["tradedate"], row["tradetime"], row["secid"])
            if key in seen:
                raise ValueError("duplicate inventory observation")
            seen.add(key)
            normalized.append({"dataset": dataset, **row,
                               "asset_code_missing": asset_code_missing})
        return normalized, {"INDEX": index, "TOTAL": total, "PAGESIZE": page_size}
    except (KeyError, TypeError, UnicodeError, ValueError, OverflowError):
        raise ValueError("invalid metadata-only inventory response") from None


def _replay(directory: Path, pages: list[dict]) -> list[dict]:
    output, seen = [], set()
    if any(page["dataset"] not in EXPECTED_CONFIG["datasets"] for page in pages):
        raise ValueError("unknown inventory dataset")
    paths = [(directory / page["path"]).resolve() for page in pages]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate inventory artifact path")
    for dataset in EXPECTED_CONFIG["datasets"]:
        selected = [page for page in pages if page["dataset"] == dataset]
        start, total = 0, None
        if not selected or len(selected) > EXPECTED_CONFIG["max_pages_per_dataset"]:
            raise ValueError("missing or excessive inventory pages")
        for number, page in enumerate(selected):
            path = (directory / page["path"]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("inventory artifact escaped output directory")
            raw = path.read_bytes()
            if len(raw) != page["bytes"] or sha(raw) != page["sha256"]:
                raise ValueError("inventory raw identity mismatch")
            rows, cursor = parse_page(raw, dataset, start)
            if page["request_url"] != request_url(dataset, start) or page["cursor"] != cursor:
                raise ValueError("inventory request or cursor identity mismatch")
            if (page["http_status"] != 200 or page["bearer_sent"] is not True
                    or page["final_url"] != page["request_url"]):
                raise ValueError("inventory authenticated transport evidence mismatch")
            if total is not None and cursor["TOTAL"] != total:
                raise ValueError("inventory cursor total changed")
            total = cursor["TOTAL"]
            retrieval = datetime.fromisoformat(page["retrieved_at_utc"])
            if retrieval.tzinfo is None:
                raise ValueError("inventory retrieval lacks timezone")
            for row in rows:
                key = (dataset, row["tradedate"], row["tradetime"], row["secid"])
                if key in seen:
                    raise ValueError("duplicate observation across inventory pages")
                seen.add(key)
                output.append({**row, "retrieved_at_utc": page["retrieved_at_utc"],
                               "available_at": None, "original_version_verified": False,
                               "historical_model_eligible": False})
            start += len(rows)
            if start >= total and number != len(selected) - 1:
                raise ValueError("inventory continued after terminal cursor")
        if start != total:
            raise ValueError("inventory pagination did not finish")
    return output


def collect(storage_root: Path, seal_sha: str, *, session: object | None = None) -> Path:
    closure = verify_seal(seal_sha)
    token = os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        raise ValueError("MOEX_ALGOPACK_TOKEN is required")
    parent = storage_root.resolve() / "data/processed/algopack"
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / f"{PROTOCOL}_{seal_sha[:12]}"
    if final.exists():
        raise FileExistsError("immutable inventory already exists")
    staging = Path(tempfile.mkdtemp(prefix=f".{PROTOCOL}_", dir=parent))
    pages, calls = [], 0
    network = session or requests.Session()
    phase, dataset, start, http_status = "setup", None, 0, None
    try:
        for dataset in EXPECTED_CONFIG["datasets"]:
            start, total = 0, None
            for number in range(EXPECTED_CONFIG["max_pages_per_dataset"]):
                if calls:
                    time.sleep(EXPECTED_CONFIG["request_interval_seconds"])
                url = request_url(dataset, start)
                phase, http_status = "transport", None
                raw, transport = _fetch(network, url, token)
                http_status = transport["http_status"]
                calls += 1
                retrieved = datetime.now(UTC).isoformat()
                phase = "parse_page"
                rows, cursor = parse_page(raw, dataset, start)
                if total is not None and total != cursor["TOTAL"]:
                    raise ValueError("inventory cursor total changed")
                total = cursor["TOTAL"]
                path = staging / f"raw_{dataset}_{number:03d}.json"
                path.write_bytes(raw)
                pages.append({**_identity(path), **transport,
                              "dataset": dataset, "request_url": url,
                              "retrieved_at_utc": retrieved, "cursor": cursor})
                start += len(rows)
                if start == total:
                    break
            else:
                raise ValueError("inventory page ceiling reached")
        phase = "raw_replay"
        inventory = _replay(staging, pages)
        artifact = staging / "inventory.json"
        artifact.write_bytes(_json_bytes(inventory))
        counts = {name: sum(row["dataset"] == name for row in inventory)
                  for name in EXPECTED_CONFIG["datasets"]}
        missing_counts = {name: sum(row["dataset"] == name and row["asset_code_missing"]
                                    for row in inventory)
                          for name in EXPECTED_CONFIG["datasets"]}
        manifest = {"protocol_id": PROTOCOL, "closure": closure, "pages": pages,
                    "inventory": _identity(artifact), "dataset_rows": counts,
                    "missing_asset_code_rows": missing_counts,
                    "asset_code_missing_policy": EXPECTED_CONFIG["asset_code_missing_policy"],
                    "source_metadata_only": True, "current_vintage": True,
                    "historical_model_eligible": False, "live_trading_allowed": False,
                    "status": "complete", "empty_datasets": [k for k, v in counts.items() if not v]}
        (staging / "manifest.json").write_bytes(_json_bytes(manifest))
        phase = "audit"
        audit(staging, seal_sha, sha((staging / "manifest.json").read_bytes()))
        staging.rename(final)
        return final
    except Exception as error:
        # Preserve only already-validated source metadata for an explicit failed attempt.
        if isinstance(error, InventoryFailure):
            phase, http_status = error.phase, error.http_status
        diagnostic = staging / "failure.json"
        diagnostic.write_bytes(_json_bytes({
            "status": "failed_no_canonical_output", "phase": phase, "dataset": dataset,
            "start": start, "http_status": http_status, "failed_response_raw_saved": False,
            "validated_pages_saved": len(pages),
        }))
        raise InventoryFailure(phase, http_status, str(diagnostic)) from None


def audit(directory: Path, seal_sha: str, manifest_sha: str) -> dict:
    closure = verify_seal(seal_sha)
    raw_manifest = (directory / "manifest.json").read_bytes()
    if sha(raw_manifest) != manifest_sha:
        raise ValueError("inventory manifest identity mismatch")
    manifest = json.loads(raw_manifest)
    if manifest["protocol_id"] != PROTOCOL or manifest["closure"] != closure:
        raise ValueError("inventory protocol identity mismatch")
    replay = _replay(directory, manifest["pages"])
    artifact = manifest["inventory"]
    if artifact["path"] != "inventory.json":
        raise ValueError("inventory artifact path mismatch")
    path = directory / artifact["path"]
    counts = {name: sum(row["dataset"] == name for row in replay)
              for name in EXPECTED_CONFIG["datasets"]}
    missing_counts = {name: sum(row["dataset"] == name and row["asset_code_missing"]
                                for row in replay)
                      for name in EXPECTED_CONFIG["datasets"]}
    checks = {
        "inventory_identity": _identity(path) == artifact,
        "raw_replay_exact": json.loads(path.read_bytes()) == replay,
        "counts_exact": manifest["dataset_rows"] == counts,
        "missing_asset_code_counts_exact": manifest["missing_asset_code_rows"] == missing_counts,
        "missing_asset_code_policy_exact": manifest["asset_code_missing_policy"]
        == EXPECTED_CONFIG["asset_code_missing_policy"],
        "empty_datasets_exact": manifest["empty_datasets"]
        == [k for k, v in counts.items() if not v],
        "metadata_only": manifest["source_metadata_only"] is True,
        "current_vintage": manifest["current_vintage"] is True,
        "historical_ineligible": manifest["historical_model_eligible"] is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "complete": manifest["status"] == "complete",
    }
    if not all(checks.values()):
        raise ValueError("inventory source audit failed")
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
                raise ValueError("audit requires manifest SHA")
            print(json.dumps(audit(args.audit, args.seal_sha, args.manifest_sha)))
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
        raise SystemExit("Inventory operation failed; sensitive error details suppressed") from None


if __name__ == "__main__":
    main()

