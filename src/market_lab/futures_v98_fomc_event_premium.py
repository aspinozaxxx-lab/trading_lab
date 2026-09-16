"""One scheduled-FOMC event-premium screen with the existing daily ledger."""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

from market_lab import futures_v97_hurricane_supply as source_tools

engine = source_tools.engine
base = engine.base
mapping_tools = source_tools.mapping_tools
CONFIG = base.PROJECT / "configs/v98_fomc_event_premium_v1.json"
SEAL = base.PROJECT / "configs/v98_fomc_event_premium_v1.seal.json"
STORAGE = Path("/srv/trading_lab_data")
MONTH = {name: i for i, name in enumerate(calendar.month_name) if name}
MONTH_PATTERN = "(?:" + "|".join(MONTH) + ")"
WEEKDAY = "(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def normalize(text):
    return " ".join(text.replace("\u2013", "-").replace("\u2014", "-").split())


def day_availability(day):
    # Deliberate end-of-publication-day +1h convention, not witnessed receipt.
    return ((pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize("America/New_York")
            .tz_convert("UTC") + pd.Timedelta(hours=1))


def parse_schedule(raw, spec):
    year = spec["year"]
    base.require(2018 <= year <= 2025, "protected schedule year")
    parser = TextParser()
    parser.feed(raw.decode("utf-8-sig"))
    text = normalize(" ".join(parser.parts))
    published = pd.Timestamp(spec["published_day"])
    base.require(published.strftime("%B %d, %Y") in text
                 and f"meeting schedule for {year}" in text
                 and "For release at" in text, "schedule identity mismatch")
    available = day_availability(spec["published_day"])
    events = []
    if year == 2025:
        base.require(text.count("For 2025:") == 1 and "For 2026:" in text, "year section")
        body = text.split("For 2025:")[1].split("For 2026:")[0]
        pattern = (rf"({WEEKDAY}),\s*({MONTH_PATTERN})\s+(\d{{1,2}}),\s*and\s*"
                   rf"({WEEKDAY}),\s*({MONTH_PATTERN})\s+(\d{{1,2}})")
        matches = [(m1, d1, m2, d2, str(year), w1, w2)
                   for w1, m1, d1, w2, m2, d2 in re.findall(pattern, body)]
    else:
        pattern = (rf"({MONTH_PATTERN})\s+(\d{{1,2}})\s*-\s*"
                   rf"(?:({MONTH_PATTERN})\s+)?(\d{{1,2}})(?:,\s*(\d{{4}}))?\s*"
                   rf"\(({WEEKDAY})\s*-\s*({WEEKDAY})\)")
        matches = re.findall(pattern, text)
    for m1, d1, m2, d2, explicit_year, w1, w2 in matches:
        current_year = int(explicit_year or year)
        if current_year != year:
            base.require(current_year == year + 1, "unexpected calendar year")
            continue
        first = pd.Timestamp(year=year, month=MONTH[m1], day=int(d1))
        last = pd.Timestamp(year=year, month=MONTH[m2 or m1], day=int(d2))
        base.require(last - first == pd.Timedelta(days=1)
                     and first.day_name() == w1 and last.day_name() == w2
                     and available < first.tz_localize("UTC"), "calendar date mismatch")
        events.append({"meeting_date": last.date().isoformat(),
                       "meeting_start_date": first.date().isoformat(),
                       "available_at_utc": available.isoformat(), "source_url": spec["url"],
                       "cancel_available_at_utc": None, "cancel_source_url": None})
    dates = [e["meeting_date"] for e in events]
    base.require(len(dates) == len(set(dates)) == 8 and dates == sorted(dates),
                 "incomplete or duplicate schedule")
    return events


def validate_cancel_text(text):
    text = normalize(text)
    base.require("March 15, 2020" in text and "Page 5 of 21" in text
                 and "in lieu of the meeting scheduled for next Tuesday and Wednesday" in text,
                 "cancellation press-conference evidence mismatch")


def collect(cfg, expected):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    try:
        events = []
        for spec in cfg["source"]["schedules"]:
            raw = source_tools.fetch(spec["url"], root / "raw" / f"schedule_{spec['year']}.html",
                                     1000000, 1.0)
            events.extend(parse_schedule(raw, spec))
        cancel = cfg["source"]["cancellation"]
        page = source_tools.fetch(cancel["page_url"], root / "raw" / "conference_20200315.html",
                                  1000000, 1.0)
        base.require(b"FOMCpresconf20200315.pdf" in page, "conference link missing")
        pdf = root / "raw" / "FOMCpresconf20200315.pdf"
        raw = source_tools.fetch(cancel["pdf_url"], pdf, 1000000, 1.0)
        base.require(raw.startswith(b"%PDF"), "invalid PDF")
        text = subprocess.check_output(["pdftotext", "-f", "5", "-l", "5", str(pdf), "-"],
                                       text=True, timeout=30)
        validate_cancel_text(text)
        base.write_json(root / "cancellation_evidence.json", {
            **cancel, "page": 5, "page_text": text,
            "available_at_utc": day_availability(cancel["public_day"]).isoformat(),
            "original_pdf_receipt_verified": False,
            "clock_basis": "public spoken statement date, not private meeting or PDF creation"})
        selected = [e for e in events if e["meeting_date"] == cancel["meeting_date"]]
        base.require(len(events) == 64 and len(selected) == 1, "source scope mismatch")
        selected[0].update(cancel_available_at_utc=day_availability(cancel["public_day"]).isoformat(),
                           cancel_source_url=cancel["pdf_url"])
        base.write_json(root / "events.json", events)
        status, error = "COMPLETE", None
    except (ValueError, OSError, subprocess.SubprocessError) as failure:
        status, error = "FAILED_SOURCE_NO_RETRY", str(failure)
    manifest = {"status": status, "error": error, "seal_sha256": expected,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "original_receipt_verified": False, "economic_admission": False,
                "files": {p.relative_to(root).as_posix(): base.sha(p)
                          for p in sorted(root.rglob("*")) if p.is_file()}}
    base.write_json(root / "manifest.json", manifest)
    print(json.dumps({"source_root": str(root), "status": status, "error": error,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(status == "COMPLETE", "source failed; preserve root and do not run economics")


def targets(active, events, cfg):
    plan = mapping_tools.mapping(active)
    plan = plan.loc[plan.asset_code.eq("MIX") & plan.decision_date.notna()].copy()
    prepared = []
    for event in events:
        date = pd.Timestamp(event["meeting_date"])
        available = pd.Timestamp(event["available_at_utc"])
        cancel = (pd.Timestamp(event["cancel_available_at_utc"])
                  if event["cancel_available_at_utc"] else None)
        base.require(date < base.BOUNDARY and available < date.tz_localize("UTC")
                     and (cancel is None or cancel < base.BOUNDARY.tz_localize("UTC")),
                     "protected or noncausal event")
        prepared.append({**event, "date": date, "available": available, "cancel": cancel})
    base.require(len({e["date"] for e in prepared}) == len(prepared), "duplicate events")
    result = {"primary": [], "control": []}
    for original in plan.to_dict("records"):
        day, effective = original["decision_date"], original["effective_date"]
        if not pd.Timestamp(cfg["period"]["start"]) <= effective <= pd.Timestamp(
                cfg["period"]["end"]):
            continue
        decision = (day + pd.Timedelta(hours=18, minutes=45)).tz_localize(
            "Europe/Moscow").tz_convert("UTC")
        # Intent uses only the next CALENDAR day; no future exit/session validity filter.
        intended = day + pd.Timedelta(days=1)
        known_year = any(e["date"].year == effective.year and e["available"] <= decision
                         for e in prepared)
        for arm in result:
            shift = 0 if arm == "primary" else cfg["signal"]["control_shift_days"]
            candidates, cancelled = [], []
            for event in prepared:
                last = event["date"] + pd.Timedelta(days=shift)
                if (event["available"] <= decision
                        and last - pd.Timedelta(days=1) <= intended <= last):
                    if event["cancel"] is not None and event["cancel"] <= decision:
                        cancelled.append(event)
                    else:
                        candidates.append((event, last))
            survives = any(last - pd.Timedelta(days=1) <= effective <= last
                           for _, last in candidates)
            row = dict(original)
            row["feature_unavailable"] = not known_year
            row["source_unavailable"] = not (row["plan_tradable"] is True
                                               and pd.notna(row["contract_id"]))
            row["stale_at_fill"] = bool(candidates) and (not survives or (effective - day).days
                                       > cfg["signal"]["maximum_fill_gap_calendar_days"])
            row["requested_weight"] = (cfg["signal"]["target_weight"]
                                       if candidates and known_year else 0.0)
            row["target_weight"] = row["requested_weight"] if not (
                row["source_unavailable"] or row["stale_at_fill"]) else 0.0
            row["cancelled_window_count"] = len(cancelled)
            row["event_ids"] = ";".join(e["meeting_date"] for e, _ in candidates)
            row["source_url"] = ";".join(sorted({e["source_url"] for e, _ in candidates}))
            row["available_at_utc"] = max((e["available"] for e, _ in candidates), default=pd.NaT)
            row["decision_at_utc"] = decision
            row["provenance"] = "v98_scheduled_fomc_event_" + arm
            result[arm].append(row)
    for arm, rows in result.items():
        frame = pd.DataFrame(rows)
        base.require(not frame.empty, "empty evaluation calendar")
        frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
        frame.loc[frame.terminal_flat, "target_weight"] = 0.0
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        result[arm] = frame.sort_values("effective_date", ignore_index=True)
    return result


def load(expected):
    base.require(base.sha(SEAL) == expected, "V98 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V98 file drift")
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
    events = json.loads((source / "events.json").read_text(encoding="utf-8-sig"))
    base.require(len(events) == 64 and {pd.Timestamp(e["meeting_date"]).year for e in events}
                 == set(range(2018, 2026)), "incomplete event calendar")
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = targets(active, events, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "scheduled_meetings": len(events),
               "documented_cancellations": sum(bool(e["cancel_available_at_utc"]) for e in events),
               "original_receipt_verified": False}
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "futures": verified,
                    "source_manifest": manifest, "started_at_utc": datetime.now(UTC).isoformat()})
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "fomc_event")
    case["event_counts"] = {
        arm: {"used_event_ids": int(frame.loc[frame.target_weight.ne(0), "event_ids"].nunique()),
              "cancelled_window_decisions": int(frame.cancelled_window_count.sum())}
        for arm, frame in signals.items()}
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
    base.require(args.collect != bool(args.source_manifest_sha), "choose source or economic run")
    cfg, parent = load(args.seal_sha)
    if args.collect:
        collect(cfg, args.seal_sha)
    else:
        run(cfg, parent, args.seal_sha, args.source_manifest_sha)


if __name__ == "__main__":
    main()
