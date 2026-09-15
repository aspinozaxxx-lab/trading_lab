"""Preserve FUTOI responses with explicit coverage gaps and immutable V2/V3 reuse."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import requests

from market_lab.futures import algopack_futoi_archive_v3 as parent

base = parent.base
source = parent.parent
Error = parent.Error
REPO = parent.REPO
PROTOCOL = "algopack_futoi_archive_v4"
PARENT_SEAL = "721f2418b0dcbfb65a76e45af387b4c7da9964276ba67e81db500dd45400c69b"
TOTALS = ("intraday_rows", "new_root_intraday_rows", "stored_bytes", "reused_pages",
          "ticker_days", "unresolved_ticker_days", "resolved_ticker_days")


def verify(seal_sha: str) -> dict:
    if not re.fullmatch("[0-9a-f]{64}", seal_sha):
        raise Error("invalid_seal")
    path = REPO / f"configs/{PROTOCOL}.seal.json"
    if base.sha(path.read_bytes()) != seal_sha:
        raise Error("seal_changed")
    seal = base.read(path)
    required = {f"configs/{PROTOCOL}.json", f"src/market_lab/futures/{PROTOCOL}.py",
                f"tests/test_{PROTOCOL}.py", "docs/ALGOPACK_FUTOI_ARCHIVE_V4.md",
                "configs/algopack_futoi_archive_v3.seal.json"}
    if seal["protocol_id"] != PROTOCOL or set(seal["files"]) != required:
        raise Error("incomplete_seal")
    for name, digest in seal["files"].items():
        if base.sha((REPO / name).read_bytes()) != digest:
            raise Error("sealed_file_changed")
    parent.verify(PARENT_SEAL)
    config = base.read(REPO / f"configs/{PROTOCOL}.json")
    if (config["protocol_id"] != PROTOCOL or config["start"] != "2020-01-01"
            or config["end"] != "2025-12-31" or config["source_only"] is not True
            or config["original_version_verified"] is not False
            or config["live_trading_allowed"] is not False):
        raise Error("scope_changed")
    return config


def prior_inventory(config: dict) -> dict:
    inventory = {}
    for prior in config["prior_archives"]:
        items = parent.prior_inventory(prior)
        for key, digest in items.items():
            if key in inventory:
                raise Error("duplicate_prior_request")
            inventory[key] = {"source_root": prior["prior_root"], "page_sha256": digest}
    return inventory


def parse(raw: bytes, day: str, ticker: str | None) -> tuple[dict, dict]:
    """Only a valid, empty HTTP payload is a gap; never fabricate a position."""
    try:
        parsed, _ = source.parse(raw, day, ticker)
    except Error as error:
        if error.code != "missing_planned_ticker_day":
            raise
        parsed, _ = source.parse(raw, day, None)
        if parsed["rows"] != 0 or parsed["tickers"]:
            raise Error("invalid_empty_payload") from None
        return parsed, {}
    return parsed, parent.global_tail(raw, day, ticker)


def source_response(root: Path, day: str, ticker: str | None, config: dict,
                    session: requests.Session, token: str, inventory: dict) -> dict:
    url = source.url_for(day, ticker)
    relative = Path(day[:4]) / day / ("latest" if ticker is None else f"ticker_{ticker}")
    relative /= "page_000000000"
    old = inventory.get(str(relative / "page.json"))
    source_root = Path(old["source_root"]) if old else root
    page = source_root / relative
    base.regular(page)
    if old and (root / relative).exists():
        raise Error("duplicate_current_and_prior_page")
    if not page.exists():
        if old:
            raise Error("missing_prior_page")
        if (root / day[:4] / day / "manifest.json").exists():
            raise Error("completed_day_missing_page")
        if shutil.disk_usage(root).free < config["minimum_free_bytes"]:
            raise Error("disk_reserve")
        if config["remaining_bytes"] < 2 * config["maximum_response_bytes"]:
            raise Error("archive_size_ceiling")
        raw, evidence = base.fetch(session, url, token, config)
        parsed, _ = parse(raw, day, ticker)
        page.parent.mkdir(parents=True, exist_ok=True)
        base.page_save(page.parent, 0, raw, {"request_url": url, "parsed": parsed, **evidence})
    for name in ("page.json", "raw.json.gz"):
        base.regular(page / name)
    metadata_bytes = (page / "page.json").read_bytes()
    if old and base.sha(metadata_bytes) != old["page_sha256"]:
        raise Error("prior_page_changed")
    meta = base.read(page / "page.json")
    compressed = (page / "raw.json.gz").read_bytes()
    if (base.sha(compressed) != meta["compressed_sha256"]
            or len(compressed) != meta["compressed_bytes"]):
        raise Error("stored_page_changed")
    raw = gzip.decompress(compressed)
    if base.sha(raw) != meta["raw_sha256"] or len(raw) != meta["raw_bytes"]:
        raise Error("stored_raw_changed")
    if meta["request_url"] != url:
        raise Error("wrong_stored_request")
    parsed, tail = parse(raw, day, ticker)
    if parsed != meta["parsed"]:
        raise Error("stored_schema_changed")
    return {"path": str(relative), "source_root": str(source_root),
            "page_sha256": base.sha(metadata_bytes), "parsed": parsed,
            "stored_bytes": 0 if old else len(compressed) + len(metadata_bytes),
            "reused_page": bool(old), "global_tail_sha256": tail}


def collect_day(root: Path, day: str, config: dict, session: requests.Session, token: str,
                inventory: dict, state: dict) -> dict:
    settings = {**config,
                "remaining_bytes": config["maximum_archive_bytes"] - state["stored_bytes"]}
    latest = source_response(root, day, None, settings, session, token, inventory)
    stored, rows_new = latest["stored_bytes"], 0
    reused = int(latest["reused_page"])
    entries = []
    for ticker in latest["parsed"]["tickers"]:
        settings["remaining_bytes"] = (config["maximum_archive_bytes"]
                                       - state["stored_bytes"] - stored)
        page = source_response(root, day, ticker, settings, session, token, inventory)
        reasons = []
        if page["parsed"]["columns"] != latest["parsed"]["columns"]:
            reasons.append("intraday_daily_schema_mismatch")
        if page["parsed"]["rows"] == 0:
            reasons.append("empty_planned_ticker_response")
        elif page["global_tail_sha256"].get(ticker) != latest["global_tail_sha256"][ticker]:
            reasons.append("intraday_daily_latest_mismatch")
        stored += page["stored_bytes"]
        reused += int(page["reused_page"])
        if not page["reused_page"]:
            rows_new += page["parsed"]["rows"]
        entries.append({"ticker": ticker, "rows": page["parsed"]["rows"], "page": page,
                        "status": "UNRESOLVED_SOURCE_GAP" if reasons else "SOURCE_MATCHED",
                        "unresolved_reasons": reasons,
                        "expected_global_tail_sha256": latest["global_tail_sha256"][ticker]})
        state.update(current_date=day, current_ticker=ticker, current_day_done=len(entries),
                     current_day_planned=len(latest["parsed"]["tickers"]),
                     updated_at_utc=datetime.now(UTC).isoformat())
        base.status_write(root, state)
    gaps = sum(bool(item["unresolved_reasons"]) for item in entries)
    result = {"date": day, "status": ("WITH_SOURCE_GAPS" if gaps else
                                      "COMPLETE" if entries else "EMPTY"),
              "latest": latest, "tickers": entries,
              "intraday_rows": sum(item["rows"] for item in entries),
              "new_root_intraday_rows": rows_new, "reused_pages": reused,
              "stored_bytes": stored, "ticker_days": len(entries),
              "unresolved_ticker_days": gaps, "resolved_ticker_days": len(entries) - gaps,
              "original_version_verified": False, "economic_admission": False}
    path = root / day[:4] / day / "manifest.json"
    base.regular(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if base.read(path) != result:
            raise Error("day_manifest_changed")
    else:
        base.write_new(path, result)
    return {key: result[key] for key in ("date", "status", *TOTALS)} | {
        "manifest_path": str(path.relative_to(root)),
        "manifest_sha256": base.sha(path.read_bytes())}


def final_manifest(state: dict, results: list[dict]) -> dict:
    if (len(results) != state["planned_days"] or state["processed_days"] != len(results)
            or len({item["date"] for item in results}) != len(results)):
        raise Error("incomplete_plan")
    for key in TOTALS:
        if state[key] != sum(item[key] for item in results):
            raise Error("totals_mismatch")
    return {**state, "status": "COMPLETE_WITH_SOURCE_GAPS" if state["unresolved_ticker_days"]
            else "COMPLETE", "days": results, "unattempted_days": 0,
            "source_coverage_complete": state["unresolved_ticker_days"] == 0,
            "original_version_verified": False, "economic_admission": False,
            "live_trading_allowed": False}


def run(seal_sha: str) -> dict:
    import fcntl

    config = verify(seal_sha)
    if os.name != "posix" or os.getuid() != 999:
        raise Error("server_trading_lab_only")
    token = os.environ.get(base.TOKEN_ENV, "")
    if not token.strip():
        raise Error("credential_missing")
    if base.sha(Path(config["ca_bundle_path"]).read_bytes()) != config["ca_bundle_sha256"]:
        raise Error("ca_bundle_changed")
    root = Path(config["output_parent"]) / f"{PROTOCOL}_{seal_sha[:12]}"
    base.regular(root)
    root.mkdir(mode=0o750, exist_ok=True)
    with ExitStack() as stack:
        for prior in config["prior_archives"]:
            path = Path(prior["prior_root"]) / ".writer.lock"
            base.regular(path)
            old_lock = stack.enter_context(path.open("rb"))
            fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base.regular(root / ".writer.lock")
        lock = stack.enter_context((root / ".writer.lock").open("a+b"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / "manifest.json").exists():
            raise Error("archive_already_terminal")
        inventory = prior_inventory(config)
        plan = source.days(config)
        identity = {"seal_sha256": seal_sha, "config": config, "planned_days": len(plan),
                    "day_plan_sha256": base.sha(base.encoded(plan))}
        if (root / "identity.json").exists():
            if base.read(root / "identity.json") != identity:
                raise Error("archive_identity_changed")
        else:
            base.write_new(root / "identity.json", identity)
        state = {"status": "RUNNING", "seal_sha256": seal_sha, "planned_days": len(plan),
                 "processed_days": 0, "days_with_gaps": 0, **dict.fromkeys(TOTALS, 0),
                 "started_at_utc": datetime.now(UTC).isoformat()}
        base.status_write(root, state)
        results = []
        try:
            with requests.Session() as session:
                session.verify = config["ca_bundle_path"]
                for day in plan:
                    state.update(current_date=day, current_ticker=None,
                                 current_day_done=0, current_day_planned=None)
                    base.status_write(root, state)
                    item = collect_day(root, day, config, session, token, inventory, state)
                    results.append(item)
                    for key in TOTALS:
                        state[key] += item[key]
                    state["processed_days"] += 1
                    state["days_with_gaps"] += int(item["unresolved_ticker_days"] > 0)
                    state["updated_at_utc"] = datetime.now(UTC).isoformat()
                    base.status_write(root, state)
                    print(json.dumps(state), flush=True)
            verify(seal_sha)
            manifest = final_manifest(state, results)
            base.write_new(root / "manifest.json", manifest)
            state["status"] = manifest["status"]
            base.status_write(root, state)
            return state
        except Exception as error:
            state.update(status="STOPPED_INCOMPLETE",
                         error=error.code if isinstance(error, Error) else type(error).__name__,
                         http_status=error.status if isinstance(error, Error) else None)
            base.status_write(root, state)
            base.write_new(root / f"stopped_{time.time_ns()}.json", state)
            raise Error("archive_stopped_safely") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.seal_sha256)), flush=True)
    except Error as error:
        print(json.dumps({"status": "STOPPED", "error": error.code}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
