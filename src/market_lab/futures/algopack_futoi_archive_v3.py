"""FUTOI raw archive with global-final-point proof and immutable V2 page reuse."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from market_lab.futures import algopack_futoi_archive_v2 as parent

base = parent.base
Error = parent.Error
REPO = parent.REPO
PROTOCOL = "algopack_futoi_archive_v3"
PARENT_SEAL = "345204a8a9624fa5f6778107193187e4e14edd72d195da28d920eb8ec2e73ca8"


def verify(seal_sha: str) -> dict:
    if not re.fullmatch("[0-9a-f]{64}", seal_sha):
        raise Error("invalid_seal")
    path = REPO / f"configs/{PROTOCOL}.seal.json"
    if base.sha(path.read_bytes()) != seal_sha:
        raise Error("seal_changed")
    seal = base.read(path)
    required = {f"configs/{PROTOCOL}.json", f"src/market_lab/futures/{PROTOCOL}.py",
                f"tests/test_{PROTOCOL}.py", "docs/ALGOPACK_FUTOI_ARCHIVE_V3.md",
                "configs/algopack_futoi_archive_v2.seal.json"}
    if seal["protocol_id"] != PROTOCOL or set(seal["files"]) != required:
        raise Error("incomplete_seal")
    for name, digest in seal["files"].items():
        if base.sha((REPO / name).read_bytes()) != digest:
            raise Error("sealed_file_changed")
    parent.verify(PARENT_SEAL)
    config = base.read(REPO / f"configs/{PROTOCOL}.json")
    if (config["protocol_id"] != PROTOCOL or config["start"] != "2020-01-01"
            or config["end"] != "2025-12-31" or config["source_only"] is not True
            or config["live_trading_allowed"] is not False):
        raise Error("scope_changed")
    return config


def prior_inventory(config: dict) -> dict:
    root = Path(config["prior_root"])
    base.regular(root)
    for name in ("identity", "status"):
        if base.sha((root / f"{name}.json").read_bytes()) != config[f"prior_{name}_sha256"]:
            raise Error("prior_archive_changed")
    items = {str(p.relative_to(root)): base.sha(p.read_bytes())
             for p in sorted(root.glob("*/*/*/page_000000000/page.json"))}
    if (len(items) != config["prior_pages"]
            or base.sha(base.encoded(items)) != config["prior_inventory_sha256"]):
        raise Error("prior_inventory_changed")
    return items


def global_tail(raw: bytes, day: str, ticker: str | None) -> dict:
    """Latest means the last common sequence point, not stale rows from other groups."""
    parent.parse(raw, day, ticker)  # immutable schema/date/cap/duplicate/group validation
    table = json.loads(raw.decode("utf-8-sig"))["futoi"]
    groups: dict[str, dict[tuple, list[dict]]] = {}
    for values in table["data"]:
        row = dict(zip(table["columns"], values, strict=True))
        point = (row["sess_id"], row["seqnum"], row["tradetime"])
        groups.setdefault(row["ticker"], {}).setdefault(point, []).append(row)
    if ticker is None and any(len(points) != 1 for points in groups.values()):
        raise Error("daily_latest_not_single_point")
    return {name: parent.stable_sha(points[max(points)]) for name, points in groups.items()}


def source_response(root: Path, day: str, ticker: str | None, config: dict,
                    session: requests.Session, token: str, inventory: dict) -> dict:
    relative = Path(day[:4]) / day / ("latest" if ticker is None else f"ticker_{ticker}")
    relative /= "page_000000000"
    key = str(relative / "page.json")
    prior = Path(config["prior_root"])
    is_prior = key in inventory
    if is_prior:
        if (root / relative).exists():
            raise Error("duplicate_current_and_prior_page")
        page = prior / relative
        base.regular(page)
        meta_path = page / "page.json"
        if base.sha(meta_path.read_bytes()) != inventory[key]:
            raise Error("prior_page_changed")
        meta = base.read(meta_path)
        result = {"path": str(relative), "page_sha256": inventory[key],
                  "parsed": meta["parsed"], "stored_bytes": 0}
    else:
        result = parent.response(root, day, ticker, config, session, token)
        page = root / result["path"]
        meta = base.read(page / "page.json")
    base.regular(page / "raw.json.gz")
    compressed = (page / "raw.json.gz").read_bytes()
    if (base.sha(compressed) != meta["compressed_sha256"]
            or len(compressed) != meta["compressed_bytes"]):
        raise Error("stored_page_changed")
    raw = gzip.decompress(compressed)
    if base.sha(raw) != meta["raw_sha256"] or len(raw) != meta["raw_bytes"]:
        raise Error("stored_raw_changed")
    if meta["request_url"] != parent.url_for(day, ticker):
        raise Error("wrong_stored_request")
    parsed, _ = parent.parse(raw, day, ticker)
    if parsed != meta["parsed"]:
        raise Error("stored_schema_changed")
    return {**result, "source_root": str(prior if is_prior else root),
            "reused_v2_page": is_prior, "global_tail_sha256": global_tail(raw, day, ticker)}


def collect_day(root: Path, day: str, config: dict, session: requests.Session, token: str,
                inventory: dict, core_counts: dict, core_proof: dict, state: dict) -> dict:
    settings = {**config,
                "remaining_bytes": config["maximum_archive_bytes"] - state["stored_bytes"]}
    latest = source_response(root, day, None, settings, session, token, inventory)
    stored, rows_new = latest["stored_bytes"], 0
    reused_pages = int(latest["reused_v2_page"])
    entries = []
    for ticker in latest["parsed"]["tickers"]:
        key = (day, ticker)
        expected = latest["global_tail_sha256"][ticker]
        if (set(latest["parsed"]["columns"]) == set(parent.COLUMNS)
                and key in core_counts and core_proof[key] == expected):
            item = {"ticker": ticker, "status": "REUSED_CORE4", "rows": core_counts[key],
                    "core_manifest_sha256": parent.CORE_SHA, "global_tail_sha256": expected}
        else:
            settings["remaining_bytes"] = (config["maximum_archive_bytes"]
                                           - state["stored_bytes"] - stored)
            page = source_response(root, day, ticker, settings, session, token, inventory)
            if (page["parsed"]["columns"] != latest["parsed"]["columns"]
                    or page["global_tail_sha256"][ticker] != expected):
                raise Error("intraday_daily_latest_mismatch")
            stored += page["stored_bytes"]
            reused_pages += int(page["reused_v2_page"])
            if not page["reused_v2_page"]:
                rows_new += page["parsed"]["rows"]
            item = {"ticker": ticker, "status": "SOURCE_PAGE", "rows": page["parsed"]["rows"],
                    "page": page}
        entries.append(item)
        state.update(current_date=day, current_ticker=ticker, current_day_done=len(entries),
                     current_day_planned=len(latest["parsed"]["tickers"]),
                     updated_at_utc=datetime.now(UTC).isoformat())
        base.status_write(root, state)
    result = {"date": day, "status": "COMPLETE" if entries else "EMPTY", "latest": latest,
              "tickers": entries, "intraday_rows": sum(item["rows"] for item in entries),
              "new_root_intraday_rows": rows_new, "reused_v2_pages": reused_pages,
              "stored_bytes": stored,
              "reused_core_ticker_days": sum(item["status"] == "REUSED_CORE4" for item in entries),
              "original_version_verified": False, "economic_admission": False}
    path = root / day[:4] / day / "manifest.json"
    base.regular(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if base.read(path) != result:
            raise Error("day_manifest_changed")
    else:
        base.write_new(path, result)
    return {key: result[key] for key in (
        "date", "status", "intraday_rows", "new_root_intraday_rows", "stored_bytes",
        "reused_core_ticker_days", "reused_v2_pages",
    )} | {"ticker_days": len(entries), "manifest_path": str(path.relative_to(root)),
         "manifest_sha256": base.sha(path.read_bytes())}


def run(seal_sha: str) -> dict:
    import fcntl

    config = verify(seal_sha)
    if os.name != "posix" or os.getuid() != 999:
        raise Error("server_trading_lab_only")
    token = os.environ.get(base.TOKEN_ENV, "")
    if not token.strip():
        raise Error("credential_missing")
    root = Path(config["output_parent"]) / f"{PROTOCOL}_{seal_sha[:12]}"
    base.regular(root)
    root.mkdir(mode=0o750, exist_ok=True)
    prior_lock = Path(config["prior_root"]) / ".writer.lock"
    with prior_lock.open("rb") as old_lock, (root / ".writer.lock").open("a+b") as lock:
        fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / "manifest.json").exists():
            raise Error("archive_already_terminal")
        inventory = prior_inventory(config)
        core_counts, core_proof = parent.core_reuse(config)
        plan = parent.days(config)
        identity = {"seal_sha256": seal_sha, "config": config, "planned_days": len(plan),
                    "day_plan_sha256": base.sha(base.encoded(plan))}
        if (root / "identity.json").exists():
            if base.read(root / "identity.json") != identity:
                raise Error("archive_identity_changed")
        else:
            base.write_new(root / "identity.json", identity)
        totals = ("intraday_rows", "new_root_intraday_rows", "stored_bytes",
                  "reused_core_ticker_days", "reused_v2_pages", "ticker_days")
        state = {"status": "RUNNING", "seal_sha256": seal_sha, "planned_days": len(plan),
                 "completed_days": 0, **dict.fromkeys(totals, 0),
                 "started_at_utc": datetime.now(UTC).isoformat()}
        base.status_write(root, state)
        results = []
        try:
            with requests.Session() as session:
                for day in plan:
                    state.update(current_date=day, current_ticker=None,
                                 current_day_done=0, current_day_planned=None)
                    base.status_write(root, state)
                    item = collect_day(root, day, config, session, token, inventory,
                                       core_counts, core_proof, state)
                    results.append(item)
                    for key in totals:
                        state[key] += item[key]
                    state["completed_days"] += 1
                    state["updated_at_utc"] = datetime.now(UTC).isoformat()
                    base.status_write(root, state)
                    print(json.dumps(state), flush=True)
            verify(seal_sha)
            state["status"] = "COMPLETE"
            base.write_new(root / "manifest.json", {**state, "days": results,
                           "unattempted_days": 0, "original_version_verified": False,
                           "economic_admission": False, "live_trading_allowed": False})
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
