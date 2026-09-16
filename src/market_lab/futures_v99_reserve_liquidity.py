"""One monthly published-bank-reserve regime screen; existing daily ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from market_lab import futures_v98_fomc_event_premium as prior

base = prior.base
engine = prior.engine
CONFIG = base.PROJECT / "configs/v99_reserve_liquidity_v1.json"
SEAL = base.PROJECT / "configs/v99_reserve_liquidity_v1.seal.json"
STORAGE = Path("/srv/trading_lab_data")
LABEL = "Reserve balances with Federal Reserve Banks"


def select_dates(raw, cfg):
    selected = []
    for year in json.loads(raw):
        for month in year["Months"]:
            key = month["MonthValue"]
            if cfg["source"]["first_month"] <= key <= cfg["source"]["last_month"]:
                dates = month["Dates"]
                base.require(dates and len(dates) == len(set(dates)), "calendar duplicates")
                base.require(all(re.fullmatch(r"\d{8}", d) and d[:6] == key for d in dates),
                             "calendar identity mismatch")
                selected.append(min(dates))
    selected.sort()
    base.require(len(selected) == cfg["source"]["expected_months"]
                 and len({d[:6] for d in selected}) == len(selected), "missing source months")
    expected = pd.period_range(cfg["source"]["first_month"], cfg["source"]["last_month"], freq="M")
    base.require([d[:6] for d in selected] == expected.strftime("%Y%m").tolist(), "month gap")
    base.require(all(pd.Timestamp(d) < base.BOUNDARY for d in selected), "protected date")
    return selected


def parse_release(raw, release, url, cfg):
    day = pd.Timestamp(release)
    base.require(day < base.BOUNDARY, "protected source")
    parser = prior.TextParser()
    parser.feed(raw.decode("utf-8-sig"))
    text = prior.normalize(" ".join(parser.parts))
    header = re.search(r"Release Date:\s*(?:\w+,\s*)?([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    base.require(header is not None and pd.Timestamp(header[1]) == day, "release identity")
    base.require("Millions of dollars" in text and "Averages of daily figures" in text,
                 "table unit/header mismatch")
    # Old preformatted and new HTML tables share this fixed four-column row.
    number = r"([+-]?\s*\d[\d,]*)"
    matches = list(re.finditer(re.escape(LABEL) + r"\s+" + r"\s+".join([number] * 4)
                               + r"\s+Note:", text))
    base.require(len(matches) == 1 and text.count(LABEL) == 1, "ambiguous reserve row")
    values = [int(re.sub(r"[\s,]", "", v)) for v in matches[0].groups()]
    heading = text[:matches[0].start()]
    observed = re.search(r"Wednesday.{0,200}?([A-Z][a-z]{2,8} \d{1,2}, \d{4})", heading)
    base.require(observed is not None, "missing Wednesday heading")
    observation = pd.Timestamp(observed[1])
    base.require(observation.dayofweek == 2 and 1 <= (day - observation).days <= 3,
                 "Wednesday/release date mismatch")
    base.require(values[0] > 0 and values[3] > 0, "invalid reserve level")
    delayed = day.date().isoformat() in cfg["source"]["unresolved_delay_dates"]
    return {"release_date": day.date().isoformat(), "month": day.strftime("%Y-%m"),
            "observation_date": observation.date().isoformat(),
            "available_at_utc": prior.day_availability(day).isoformat(),
            "reserve_wednesday_million_usd": values[3],
            "weekly_average_audit_only": values[0], "source_url": url,
            "usable": not delayed,
            "reason": "documented_delay_no_original_clock" if delayed else "dated_archive_proxy"}


def collect(cfg, expected):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    rows = []
    try:
        for name, spec in cfg["source"]["discovery_inputs"].items():
            path = base.safe(STORAGE, spec["path"])
            base.require(path.stat().st_size == spec["bytes"] and base.sha(path) == spec["sha256"],
                         "discovery input drift")
            shutil.copyfile(path, root / "raw" / name)
        dates = select_dates((root / "raw/releaseDates.json").read_bytes(), cfg)
        base.write_json(root / "selected_dates.json", dates)
        for release in dates:
            url = "https://www.federalreserve.gov/releases/h41/" + release + "/"
            raw = prior.source_tools.fetch(url, root / "raw" / (release + ".html"), 3000000, 1.0)
            rows.append(parse_release(raw, release, url, cfg))
            print(json.dumps({"parsed_months": len(rows), "release_date": release}), flush=True)
        base.write_json(root / "releases.json", rows)
        status, error = "COMPLETE", None
    except (ValueError, OSError, subprocess.SubprocessError) as failure:
        status, error = "FAILED_SOURCE_NO_RETRY", str(failure)
    manifest = {"status": status, "error": error, "seal_sha256": expected,
                "parsed_months": len(rows), "usable_months": sum(r["usable"] for r in rows),
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "original_receipt_verified": False, "economic_admission": False,
                "files": {p.relative_to(root).as_posix(): base.sha(p)
                          for p in sorted(root.rglob("*")) if p.is_file()}}
    base.write_json(root / "manifest.json", manifest)
    print(json.dumps({"source_root": str(root), "status": status, "error": error,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(status == "COMPLETE", "source failed; preserve root and do not run economics")


def states(releases, cfg):
    by_month = {}
    for row in releases:
        day, available = pd.Timestamp(row["release_date"]), pd.Timestamp(row["available_at_utc"])
        base.require(day < base.BOUNDARY and available < base.BOUNDARY.tz_localize("UTC")
                     and day.tz_localize("UTC") < available, "protected/noncausal source")
        base.require(row["month"] == day.strftime("%Y-%m") and row["month"] not in by_month,
                     "duplicate/mislabelled month")
        base.require(row["reserve_wednesday_million_usd"] > 0, "nonpositive reserves")
        by_month[row["month"]] = row
    result = []
    for month, row in sorted(by_month.items()):
        lag_month = str(pd.Period(month, freq="M") - cfg["signal"]["lookback_months"])
        lag = by_month.get(lag_month)
        ready = row["usable"] and lag is not None and lag["usable"]
        growth = (row["reserve_wednesday_million_usd"] / lag["reserve_wednesday_million_usd"] - 1
                  if ready else None)
        result.append({**row, "ready": ready, "growth": growth, "lag_month": lag_month,
                       "lag_source_url": lag["source_url"] if lag else None,
                       "available": pd.Timestamp(row["available_at_utc"]),
                       "lag_available": pd.Timestamp(lag["available_at_utc"]) if lag else pd.NaT})
        base.require(lag is None or result[-1]["lag_available"] < result[-1]["available"],
                     "future baseline")
    return result


def targets(active, state, cfg):
    plan = prior.mapping_tools.mapping(active)
    plan = plan.loc[plan.asset_code.eq("MIX") & plan.decision_date.notna()].copy()
    result = {"primary": [], "control": []}
    for original in plan.to_dict("records"):
        day, effective = original["decision_date"], original["effective_date"]
        if not pd.Timestamp(cfg["period"]["start"]) <= effective <= pd.Timestamp(
                cfg["period"]["end"]):
            continue
        decision = (day + pd.Timedelta(hours=18, minutes=45)).tz_localize(
            "Europe/Moscow").tz_convert("UTC")
        available = [s for s in state if s["available"] <= decision]
        source = max(available, key=lambda s: s["available"]) if available else None
        age = (day - pd.Timestamp(source["release_date"])).days if source else None
        ready = bool(source and source["ready"] and age <= cfg["signal"]["maximum_age_days"])
        for arm in result:
            row = dict(original)
            row["feature_unavailable"] = not ready
            row["source_unavailable"] = not (row["plan_tradable"] is True
                                               and pd.notna(row["contract_id"]))
            requested = cfg["signal"]["target_weight"] if ready and (
                arm == "control" or source["growth"] > 0) else 0.0
            stale = bool(requested and (
                (effective - day).days > cfg["signal"]["maximum_fill_gap_days"]
                or (effective - pd.Timestamp(source["release_date"])).days
                > cfg["signal"]["maximum_age_days"]))
            row.update(requested_weight=requested, stale_at_fill=stale,
                       target_weight=requested if not (row["source_unavailable"] or stale) else 0.0,
                       source_url=source["source_url"] if source else "",
                       source_month=source["month"] if source else None,
                       source_date=pd.Timestamp(source["release_date"]) if source else pd.NaT,
                       available_at_utc=source["available"] if source else pd.NaT,
                       lag_available_at_utc=source["lag_available"] if source else pd.NaT,
                       growth_3m=source["growth"] if source else None, decision_at_utc=decision,
                       provenance="v99_bank_reserve_regime_" + arm)
            result[arm].append(row)
    for arm, rows in result.items():
        frame = pd.DataFrame(rows)
        base.require(not frame.empty, "empty calendar")
        frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
        frame.loc[frame.terminal_flat, "target_weight"] = 0.0
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        result[arm] = frame.sort_values("effective_date", ignore_index=True)
    return result


def load(expected):
    base.require(base.sha(SEAL) == expected, "V99 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V99 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["assets"] == ["MIX"] and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"], "scope drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def run(cfg, parent, expected, manifest_sha):
    source = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    base.require(base.sha(source / "manifest.json") == manifest_sha, "source manifest drift")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(manifest["status"] == "COMPLETE" and manifest["seal_sha256"] == expected,
                 "incomplete source")
    for path, digest in manifest["files"].items():
        base.require(base.sha(base.safe(source, path)) == digest, "source artifact drift")
    releases = json.loads((source / "releases.json").read_text(encoding="utf-8-sig"))
    base.require(len(releases) == cfg["source"]["expected_months"], "source count drift")
    state = states(releases, cfg)
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = targets(active, state, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "source_months": len(releases), "usable_source_months": manifest["usable_months"],
               "ready_month_states": sum(s["ready"] for s in state),
               "original_receipt_verified": False}
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "futures": verified,
                    "source_manifest": manifest, "started_at_utc": datetime.now(UTC).isoformat()})
    base.write_json(output / "reserve_states.json", [{k: v for k, v in s.items()
                    if k not in ("available", "lag_available")} for s in state])
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "reserve_liquidity")
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"],
               "seal_sha256": expected, "source_manifest_sha256": manifest_sha,
               "completed_at_utc": datetime.now(UTC).isoformat(), "case": case,
               "limitations": cfg["limitations"], "goal_verified": False}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "manifest.json", {"status": "COMPLETE", "seal_sha256": expected,
                    "completed_at_utc": payload["completed_at_utc"], "files": {
                        p.relative_to(output).as_posix(): base.sha(p)
                        for p in sorted(output.rglob("*")) if p.is_file()}})
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--collect", action="store_true")
    cli.add_argument("--source-manifest-sha")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    base.require(args.collect != bool(args.source_manifest_sha), "choose source or economics")
    cfg, parent = load(args.seal_sha)
    if args.collect:
        collect(cfg, args.seal_sha)
    else:
        run(cfg, parent, args.seal_sha, args.source_manifest_sha)


if __name__ == "__main__":
    main()
