"""Historical full-market FUTOI supplement; no prices, training or economic admission."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pyarrow.parquet as pq
import requests

from market_lab.futures import algopack_archive_v1 as base

PROTOCOL = "algopack_futoi_archive_v1"
REPO = Path(__file__).resolve().parents[3]
PARENT_SEAL = "5b7c66fa0e0446eb3b395d3776c4496907e2c4cc760c5a87bc38e57da32f97e0"
CORE_SHA = "cc432d5938e8b824339975e2d84b29fe3c24219c505c9dfefc4baeb3db46a1ed"
COLUMNS = (
    "sess_id", "seqnum", "tradedate", "tradetime", "ticker", "clgroup", "pos",
    "pos_long", "pos_short", "pos_long_num", "pos_short_num", "systime",
)
CORE_MAP = {
    "sess_id": "sess_id", "seqnum": "seqnum", "tradedate": "source_date",
    "tradetime": "source_time", "ticker": "ticker", "clgroup": "client_group",
    "pos": "net_position", "pos_long": "long_position", "pos_short": "short_position",
    "pos_long_num": "long_accounts", "pos_short_num": "short_accounts",
}
Error = base.ArchiveError


def verify(seal_sha: str) -> dict:
    if not re.fullmatch("[0-9a-f]{64}", seal_sha):
        raise Error("invalid_seal")
    raw = (REPO / f"configs/{PROTOCOL}.seal.json").read_bytes()
    if base.sha(raw) != seal_sha:
        raise Error("seal_changed")
    seal = json.loads(raw.decode("utf-8-sig"))
    required = {f"configs/{PROTOCOL}.json", f"src/market_lab/futures/{PROTOCOL}.py",
                f"tests/test_{PROTOCOL}.py", "docs/ALGOPACK_FUTOI_ARCHIVE_V1.md",
                "configs/algopack_archive_v1.seal.json"}
    if seal["protocol_id"] != PROTOCOL or set(seal["files"]) != required:
        raise Error("incomplete_seal")
    for relative, digest in seal["files"].items():
        if base.sha((REPO / relative).read_bytes()) != digest:
            raise Error("sealed_file_changed")
    base.verify(PARENT_SEAL)
    config = base.read(REPO / f"configs/{PROTOCOL}.json")
    if (config["protocol_id"] != PROTOCOL or config["start"] != "2020-01-01"
            or config["end"] != "2025-12-31" or config["source_only"] is not True
            or config["original_version_verified"] is not False
            or config["live_trading_allowed"] is not False):
        raise Error("scope_changed")
    return config


def days(config: dict) -> list[str]:
    first, last = date.fromisoformat(config["start"]), date.fromisoformat(config["end"])
    if not date(2020, 1, 1) <= first <= last < date(2026, 1, 1):
        raise Error("protected_plan")
    pilots = ["2024-10-15", "2020-05-04", "2025-12-30"]
    result = [day for day in pilots if first <= date.fromisoformat(day) <= last]
    while last >= first:
        day = last.isoformat()
        if day not in pilots:
            result.append(day)
        last -= timedelta(days=1)
    return result


def url_for(day: str, ticker: str | None = None) -> str:
    if (date.fromisoformat(day).isoformat() != day
            or not "2020-01-01" <= day < "2026-01-01"):
        raise Error("invalid_request_date")
    route = "https://apim.moex.com/iss/analyticalproducts/futoi/securities"
    if ticker is None:
        query = {"date": day, "latest": 1, "iss.meta": "off", "iss.only": "futoi"}
    else:
        if not re.fullmatch("[A-Za-z0-9_]{1,32}", ticker):
            raise Error("invalid_ticker")
        route += f"/{ticker.lower()}"
        query = {"from": day, "till": day, "iss.meta": "off", "iss.only": "futoi"}
    return f"{route}.json?{urlencode(query)}"


def stable_sha(rows: list[dict]) -> str:
    stable = [{key: value for key, value in row.items() if key != "systime"} for row in rows]
    return base.sha(base.encoded(sorted(stable, key=lambda row: row["clgroup"])))


def parse(raw: bytes, day: str, ticker: str | None = None) -> tuple[dict, dict]:
    """Inspect date/schema/sequence, preserve all position fields; no offset pagination."""
    url_for(day, ticker)
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=base.pairs_unique)
        if set(value) != {"futoi"}:
            raise Error("unexpected_blocks")
        columns, rows = value["futoi"]["columns"], value["futoi"]["data"]
        if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                or len(columns) != len(set(columns)) or not set(COLUMNS).issubset(columns)
                or not isinstance(rows, list)):
            raise Error("invalid_schema")
        if len(rows) >= 1000:
            raise Error("possibly_truncated_1000_rows")
        groups: dict[str, dict[tuple, list[dict]]] = {}
        keys = set()
        for values in rows:
            if not isinstance(values, list) or len(values) != len(columns):
                raise Error("row_width")
            row = dict(zip(columns, values, strict=True))
            name = row["ticker"]
            if not isinstance(name, str):
                raise Error("invalid_ticker")
            url_for(day, name)  # validated before any subsequent URL/path is constructed
            if row["tradedate"] != day:
                raise Error("protected_or_wrong_date")
            if ticker is not None and name != ticker:
                raise Error("wrong_ticker")
            if (any(type(row[c]) is not int or row[c] < 0 for c in ("sess_id", "seqnum"))
                    or not isinstance(row["tradetime"], str)
                    or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", row["tradetime"])
                    or row["clgroup"] not in {"FIZ", "YUR"}):
                raise Error("invalid_sequence_identity")
            point = (row["sess_id"], row["seqnum"], row["tradetime"])
            key = (name, *point, row["clgroup"])
            if key in keys:
                raise Error("duplicate_sequence_group")
            keys.add(key)
            groups.setdefault(name, {}).setdefault(point, []).append(row)
        latest, counts = {}, {}
        for name, points in groups.items():
            if any({row["clgroup"] for row in pair} != {"FIZ", "YUR"}
                   or len(pair) != 2 for pair in points.values()):
                raise Error("unpaired_sequence")
            if ticker is None and len(points) != 1:
                raise Error("daily_latest_not_unique")
            latest[name] = points[max(points)]
            counts[name] = len(points)
        if ticker is not None and not rows:
            raise Error("missing_planned_ticker_day")
        if len({name.lower() for name in groups}) != len(groups):
            raise Error("ticker_path_collision")
        meta = {"columns": columns, "rows": len(rows), "date_verified": day,
                "tickers": sorted(groups), "paired_points_by_ticker": counts,
                "latest_stable_sha256": {name: stable_sha(pair) for name, pair in latest.items()}}
        return meta, latest
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        raise Error("invalid_payload") from None


def core_reuse(config: dict) -> tuple[dict, dict]:
    """Verify preserved core4 bytes; load only coverage and daily-last source values."""
    root = Path(config["core_root"])
    base.regular(root)
    raw = (root / "manifest.json").read_bytes()
    if base.sha(raw) != CORE_SHA:
        raise Error("core_manifest_changed")
    manifest = json.loads(raw.decode("utf-8-sig"))
    if (manifest["request_bounds"]["till"] != "2025-12-31"
            or manifest["artifacts"]["processed_intraday"]["maximum_source_date"] >= "2026-01-01"):
        raise Error("protected_core")
    for item in manifest["artifacts"].values():
        path = root / item["path"]
        base.regular(path)
        if path.parent != root or base.sha(path.read_bytes()) != item["sha256"]:
            raise Error("core_artifact_changed")
    coverage = pq.read_table(root / "coverage.parquet", columns=[
        "source_date", "ticker", "rows", "response_below_1000_row_cap", "daily_latest_pair_matched",
    ]).to_pylist()
    counts = {}
    for row in coverage:
        day = row["source_date"].date().isoformat()
        key = (day, row["ticker"])
        url_for(*key)
        if (key in counts or not 0 < row["rows"] < 1000
                or row["response_below_1000_row_cap"] is not True
                or row["daily_latest_pair_matched"] is not True):
            raise Error("invalid_core_coverage")
        counts[key] = row["rows"]
    proof = pq.read_table(root / "futoi_daily_latest_proof.parquet",
                          columns=list(CORE_MAP.values())).to_pylist()
    groups: dict[tuple, list[dict]] = {}
    for item in proof:
        row = {key: item[value] for key, value in CORE_MAP.items()}
        row["tradedate"] = row["tradedate"].date().isoformat()
        key = (row["tradedate"], row["ticker"])
        url_for(*key)
        groups.setdefault(key, []).append(row)
    if set(groups) != set(counts) or any(len(pair) != 2 for pair in groups.values()):
        raise Error("core_proof_coverage_mismatch")
    return counts, {key: stable_sha(pair) for key, pair in groups.items()}


def response(root: Path, day: str, ticker: str | None, config: dict,
             session: requests.Session, token: str) -> dict:
    directory = root / day[:4] / day / ("latest" if ticker is None else f"ticker_{ticker}")
    base.regular(directory)
    directory.mkdir(parents=True, exist_ok=True)
    page = directory / "page_000000000"
    url = url_for(day, ticker)
    if page.exists():
        base.regular(page)
        for name in ("raw.json.gz", "page.json"):
            base.regular(page / name)
        meta = base.read(page / "page.json")
        compressed = (page / "raw.json.gz").read_bytes()
        if (meta["request_url"] != url or base.sha(compressed) != meta["compressed_sha256"]
                or len(compressed) != meta["compressed_bytes"]):
            raise Error("stored_page_changed")
        raw = gzip.decompress(compressed)
        if base.sha(raw) != meta["raw_sha256"] or len(raw) != meta["raw_bytes"]:
            raise Error("stored_raw_changed")
        parsed, _ = parse(raw, day, ticker)
        if parsed != meta["parsed"]:
            raise Error("stored_schema_changed")
    else:
        if (root / day[:4] / day / "manifest.json").exists():
            raise Error("completed_day_missing_page")
        if shutil.disk_usage(root).free < config["minimum_free_bytes"]:
            raise Error("disk_reserve")
        if config["remaining_bytes"] < 2 * config["maximum_response_bytes"]:
            raise Error("archive_size_ceiling")
        raw, evidence = base.fetch(session, url, token, config)
        parsed, _ = parse(raw, day, ticker)
        base.page_save(directory, 0, raw, {"request_url": url, "parsed": parsed, **evidence})
        meta = base.read(page / "page.json")
    return {"path": str(page.relative_to(root)), "parsed": parsed,
            "page_sha256": base.sha((page / "page.json").read_bytes()),
            "stored_bytes": meta["compressed_bytes"] + (page / "page.json").stat().st_size}


def collect_day(root: Path, day: str, config: dict, session: requests.Session, token: str,
                core_counts: dict, core_proof: dict, state: dict) -> dict:
    settings = {**config,
                "remaining_bytes": config["maximum_archive_bytes"] - state["stored_bytes"]}
    latest = response(root, day, None, settings, session, token)
    stored, downloaded_rows = latest["stored_bytes"], 0
    entries = []
    for ticker in latest["parsed"]["tickers"]:
        key = (day, ticker)
        expected = latest["parsed"]["latest_stable_sha256"][ticker]
        reuse = (set(latest["parsed"]["columns"]) == set(COLUMNS)
                 and key in core_counts and core_proof[key] == expected)
        if reuse:
            item = {"ticker": ticker, "status": "REUSED_CORE4", "rows": core_counts[key],
                    "core_manifest_sha256": CORE_SHA, "latest_stable_sha256": expected}
        else:
            settings["remaining_bytes"] = (config["maximum_archive_bytes"]
                                           - state["stored_bytes"] - stored)
            page = response(root, day, ticker, settings, session, token)
            if (page["parsed"]["columns"] != latest["parsed"]["columns"]
                    or page["parsed"]["latest_stable_sha256"][ticker] != expected):
                raise Error("intraday_daily_latest_mismatch")
            stored += page["stored_bytes"]
            downloaded_rows += page["parsed"]["rows"]
            item = {"ticker": ticker, "status": "DOWNLOADED", "rows": page["parsed"]["rows"],
                    "core_key_present_but_not_reusable": key in core_counts, "page": page}
        entries.append(item)
        state.update(current_date=day, current_ticker=ticker, current_day_done=len(entries),
                     current_day_planned=len(latest["parsed"]["tickers"]),
                     updated_at_utc=datetime.now(UTC).isoformat())
        base.status_write(root, state)
    result = {"date": day, "status": "COMPLETE" if entries else "EMPTY", "latest": latest,
              "tickers": entries, "intraday_rows": sum(item["rows"] for item in entries),
              "downloaded_intraday_rows": downloaded_rows, "stored_bytes": stored,
              "reused_ticker_days": sum(item["status"] == "REUSED_CORE4" for item in entries),
              "original_version_verified": False, "economic_admission": False}
    path = root / day[:4] / day / "manifest.json"
    if path.exists():
        if base.read(path) != result:
            raise Error("day_manifest_changed")
    else:
        base.write_new(path, result)
    return {key: result[key] for key in (
        "date", "status", "intraday_rows", "downloaded_intraday_rows", "stored_bytes",
        "reused_ticker_days",
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
    parent = Path(config["output_parent"])
    base.regular(parent)
    if not parent.is_dir():
        raise Error("parent_missing")
    root = parent / f"{PROTOCOL}_{seal_sha[:12]}"
    base.regular(root)
    root.mkdir(mode=0o750, exist_ok=True)
    with (root / ".writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / "manifest.json").exists():
            raise Error("archive_already_terminal")
        plan = days(config)
        identity = {"seal_sha256": seal_sha, "config": config, "planned_days": len(plan),
                    "day_plan_sha256": base.sha(base.encoded(plan)),
                    "core_manifest_sha256": CORE_SHA}
        if (root / "identity.json").exists():
            if base.read(root / "identity.json") != identity:
                raise Error("archive_identity_changed")
        else:
            base.write_new(root / "identity.json", identity)
        core_counts, core_proof = core_reuse(config)
        result = []
        totals = ("intraday_rows", "downloaded_intraday_rows", "stored_bytes",
                  "reused_ticker_days", "ticker_days")
        state = {"status": "RUNNING", "seal_sha256": seal_sha, "planned_days": len(plan),
                 "completed_days": 0, **dict.fromkeys(totals, 0),
                 "started_at_utc": datetime.now(UTC).isoformat()}
        base.status_write(root, state)
        try:
            with requests.Session() as session:
                for day in plan:
                    state.update(current_date=day, current_ticker=None,
                                 current_day_done=0, current_day_planned=None)
                    base.status_write(root, state)
                    item = collect_day(root, day, config, session, token, core_counts,
                                       core_proof, state)
                    result.append(item)
                    for key in totals:
                        state[key] += item[key]
                    state["completed_days"] += 1
                    state["updated_at_utc"] = datetime.now(UTC).isoformat()
                    base.status_write(root, state)
                    print(json.dumps(state), flush=True)
            verify(seal_sha)
            state["status"] = "COMPLETE"
            base.write_new(root / "manifest.json", {**state, "days": result,
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
