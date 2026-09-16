"""Bounded NHC forecast source and one fixed BR screen using the existing ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from market_lab import futures_v78_treasury_channels as engine
from market_lab import futures_v94_skewness_premium as mapping_tools

base = engine.base
CONFIG = base.PROJECT / "configs/v97_hurricane_supply_v1.json"
SEAL = base.PROJECT / "configs/v97_hurricane_supply_v1.seal.json"
STORAGE = Path("/srv/trading_lab_data")
MONTHS = {name: number for number, name in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def archive_identity(name, year):
    match = re.fullmatch(r"(al\d{2}(\d{4}))\.fstadv\.(\d{3})\.(\d{8})", name)
    base.require(match is not None and int(match[2]) == year and 2018 <= year <= 2025,
                 "invalid/protected NHC filename")
    stamp = pd.Timestamp(datetime.strptime(str(year) + match[4], "%Y%m%d%H%M"), tz="UTC")
    return match[1].upper(), int(match[3]), stamp


def select_files(raw, year, cutoff):
    names = set(re.findall(r'href="([^"]+)"', raw.decode("ascii")))
    names = sorted(n for n in names if re.fullmatch(
        rf"al\d{{2}}{year}\.fstadv\.\d{{3}}\.\d{{8}}", n))
    base.require(bool(names), "no versioned Atlantic forecasts")
    chosen = {}
    for name in names:
        storm, _, stamp = archive_identity(name, year)
        if stamp.strftime("%H%M") <= cutoff:
            key = (storm, str(stamp.date()))
            if key not in chosen or stamp > chosen[key][0]:
                chosen[key] = (stamp, name)
            elif stamp == chosen[key][0]:
                base.require(name == chosen[key][1], "ambiguous same-clock advisories")
    return sorted(value[1] for value in chosen.values()), {
        "versioned_files": len(names), "storms": len({n[:8] for n in names}),
        "selected_storm_dates": len(chosen),
    }


def forecast_date(issue, day, hhmm):
    found = []
    for offset in (-1, 0, 1):
        month = issue.tz_localize(None).to_period("M") + offset
        try:
            candidate = pd.Timestamp(year=month.year, month=month.month, day=int(day),
                                     hour=int(hhmm[:2]), minute=int(hhmm[2:]), tz="UTC")
        except ValueError:
            continue
        if issue < candidate <= issue + pd.Timedelta(days=7):
            found.append(candidate)
    base.require(len(found) == 1, "ambiguous forecast valid date")
    return found[0]


def parse_advisory(raw, filename, year, lag_hours):
    storm, number, version = archive_identity(filename, year)
    text = raw.decode("ascii").replace("\r", "").upper()
    dates = re.findall(r"(?m)^(\d{4}) UTC [A-Z]{3} ([A-Z]{3})\s+(\d{1,2}) (\d{4})\s*$", text)
    base.require(len(dates) == 1, "missing/ambiguous advisory issue clock")
    hhmm, month, day, issue_year = dates[0]
    base.require(int(issue_year) == year and month in MONTHS, "protected/mismatched issue year")
    issue = pd.Timestamp(year=year, month=MONTHS[month], day=int(day),
                         hour=int(hhmm[:2]), minute=int(hhmm[2:]), tz="UTC")
    base.require(issue - pd.Timedelta(hours=2) <= version <= issue + pd.Timedelta(days=7),
                 "version clock inconsistent with issue")
    base.require(storm in text and re.search(
        rf"FORECAST/ADVISORY NUMBER\s+{number}(?:\s|$)", text), "advisory identity mismatch")
    availability = max(issue, version) + pd.Timedelta(hours=lag_hours)
    base.require(availability < pd.Timestamp("2026-01-01", tz="UTC"), "protected availability")
    pattern = (r"(?:FORECAST|OUTLOOK) VALID (\d{2})/(\d{4})Z\s+"
               r"(\d{1,2}\.\d)([NS])\s+(\d{1,3}\.\d)([EW])[^\n]*\n"
               r"MAX WIND\s+(\d+)\s+KT")
    points = []
    for day, hhmm, lat, ns, lon, ew, wind in re.findall(pattern, text):
        valid = forecast_date(issue, day, hhmm)
        latitude = float(lat) * (1 if ns == "N" else -1)
        longitude = float(lon) * (1 if ew == "E" else -1)
        base.require(-90 <= latitude <= 90 and -180 <= longitude <= 180
                     and 0 <= int(wind) <= 250, "invalid forecast units")
        points.append({"valid_at_utc": valid.isoformat(), "latitude": latitude,
                       "longitude": longitude, "wind_knots": int(wind)})
    base.require(bool(points) or "DISSIPAT" in text or "LAST FORECAST/ADVISORY" in text,
                 "unparsed forecast positions")
    # Any coordinate-bearing forecast block must be accounted for, not silently lost.
    positioned = re.findall(r"(?:FORECAST|OUTLOOK) VALID \d{2}/\d{4}Z\s+\d+\.\d[NS]", text)
    base.require(len(positioned) == len(points), "incomplete forecast block parse")
    return {"storm": storm, "advisory_number": number, "filename": filename,
            "version_at_utc": version.isoformat(), "issued_at_utc": issue.isoformat(),
            "available_at_utc": availability.isoformat(), "points": points}


def fetch(url, destination, limit, seconds):
    started = time.monotonic()
    response = subprocess.run([
        "curl", "-q", "--http1.1", "-sS", "--connect-timeout", "10", "--max-time", "30",
        "--max-filesize", str(limit), "--proto", "=https", "--user-agent",
        "TradingLab private historical research", "-w", "\n__HTTP__%{http_code}", url,
    ], capture_output=True, timeout=35, check=False)
    raw, marker, status = response.stdout.rpartition(b"\n__HTTP__")
    if not marker:
        raw, status = response.stdout, b"000"
    with destination.open("xb") as handle:
        handle.write(raw)
    metadata = {"url": url, "received_at_utc": datetime.now(UTC).isoformat(),
                "http_status": status.decode(), "curl_returncode": response.returncode,
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "stderr": response.stderr.decode(errors="replace")[:500]}
    base.write_json(destination.with_suffix(destination.suffix + ".metadata.json"), metadata)
    # No retries; pause is a per-request rate ceiling, never a poll of a timer.
    time.sleep(max(0.0, seconds - (time.monotonic() - started)))
    base.require(response.returncode == 0 and status == b"200" and 0 < len(raw) <= limit,
                 "source HTTP failure; retained raw response, no automatic retry")
    return raw


def collect(cfg, expected):
    spec = cfg["source"]
    root = base.safe(STORAGE, spec["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    jobs, inventories = [], {}
    for year in spec["years"]:
        url = spec["url_template"].format(year=year)
        destination = root / "raw" / f"index_{year}.html"
        reused = spec["reused_indexes"].get(str(year))
        if reused:
            origin = base.safe(STORAGE, reused["path"])
            base.require(base.sha(origin) == reused["sha256"], "sample index drift")
            raw = origin.read_bytes()
            with destination.open("xb") as handle:
                handle.write(raw)
            base.write_json(destination.with_suffix(".reference.json"), reused)
        else:
            raw = fetch(url, destination, spec["maximum_index_bytes"],
                        spec["minimum_request_seconds"])
        selected, inventory = select_files(raw, year, spec["daily_archive_cutoff_utc"])
        inventories[str(year)] = inventory
        jobs.extend((year, name, url + name) for name in selected)
    base.require(0 < len(jobs) + len(spec["years"]) <= spec["maximum_requests"], "request cap")
    base.write_json(root / "inventory.json", {"years": inventories, "jobs": jobs})
    print(json.dumps({"source_jobs": len(jobs), "inventories": inventories}), flush=True)

    def work(job):
        year, name, url = job
        raw = fetch(url, root / "raw" / name, spec["maximum_message_bytes"],
                    spec["minimum_request_seconds"])
        try:
            record = parse_advisory(raw, name, year, spec["publication_lag_hours"])
            return {**record, "url": url, "raw_sha256": hashlib.sha256(raw).hexdigest()}, None
        except (ValueError, KeyError, UnicodeError) as error:
            storm, _, version = archive_identity(name, year)
            return None, {"filename": name, "storm": storm, "url": url,
                          "version_at_utc": version.isoformat(), "reason": str(error)}

    records, gaps, http_errors = [], [], []
    with ThreadPoolExecutor(max_workers=spec["workers"]) as pool:
        # Submit only two requests at a time, so access failures cannot queue a crawl.
        position = 0
        while position < len(jobs) and not http_errors:
            futures = {pool.submit(work, job): job for job in jobs[position:position + 2]}
            position += len(futures)
            for future in as_completed(futures):
                try:
                    record, gap = future.result()
                    (records if record is not None else gaps).append(record or gap)
                except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                    http_errors.append({"job": futures[future], "reason": str(error)})
            if position % 50 < 2 or http_errors or position == len(jobs):
                progress = {"processed": len(records) + len(gaps), "planned": len(jobs),
                            "parse_gaps": len(gaps), "http_errors": http_errors,
                            "updated_at_utc": datetime.now(UTC).isoformat()}
                base.write_json(root / "status.json", progress)
                print(json.dumps(progress), flush=True)
    base.write_json(root / "advisories.json", sorted(records, key=lambda r: r["filename"]))
    base.write_json(root / "parse_gaps.json", gaps)
    status = "COMPLETE" if not http_errors else "FAILED_HTTP_NO_RETRY"
    manifest = {"status": status, "seal_sha256": expected,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "records": len(records), "parse_gaps": len(gaps), "http_errors": http_errors,
                "planned_messages": len(jobs), "years": inventories,
                "original_receipt_verified": False, "economic_admission": False,
                "files": {str(p.relative_to(root)): base.sha(p)
                          for p in sorted(root.rglob("*")) if p.is_file()}}
    base.write_json(root / "manifest.json", manifest)
    print(json.dumps({"source_root": str(root), "status": status,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(not http_errors, "incomplete source; no economic run")


def targets(active, records, gaps, cfg):
    plan = mapping_tools.mapping(active)
    plan = plan.loc[plan.asset_code.eq("BR") & plan.decision_date.notna()].copy()
    rule = cfg["signal"]
    events = []
    for record in records:
        item = {**record, "available": pd.Timestamp(record["available_at_utc"]),
                "issued": pd.Timestamp(record["issued_at_utc"])}
        base.require(item["available"] < pd.Timestamp("2026-01-01", tz="UTC"),
                     "protected advisory input")
        events.append(item)
    bad = [pd.Timestamp(g["version_at_utc"]) + pd.Timedelta(
        hours=cfg["source"]["publication_lag_hours"]) for g in gaps]
    result = {"primary": [], "control": []}
    for original in plan.to_dict("records"):
        day, effective = original["decision_date"], original["effective_date"]
        if not pd.Timestamp(cfg["period"]["start"]) <= effective <= pd.Timestamp(
                cfg["period"]["end"]):
            continue
        decision = (day + pd.Timedelta(hours=18, minutes=45)).tz_localize(
            "Europe/Moscow").tz_convert("UTC")
        fill_clock = (effective + pd.Timedelta(hours=10)).tz_localize(
            "Europe/Moscow").tz_convert("UTC")
        age = pd.Timedelta(hours=rule["maximum_source_age_hours"])
        ready = not any(t <= decision < t + age for t in bad)
        latest = {}
        for event in events:
            if decision - age <= event["available"] <= decision:
                old = latest.get(event["storm"])
                if old is None or event["available"] > old["available"]:
                    latest[event["storm"]] = event
        for arm in result:
            qualifying, surviving = [], []
            for event in latest.values():
                for point in event["points"]:
                    valid = pd.Timestamp(point["valid_at_utc"])
                    strong = point["wind_knots"] >= rule["wind_threshold_knots"]
                    region = (rule["latitude_min"] <= point["latitude"] <= rule["latitude_max"]
                              and rule["longitude_min"] <= point["longitude"]
                              <= rule["longitude_max"])
                    horizon = event["issued"] + pd.Timedelta(hours=rule["forecast_horizon_hours"])
                    if strong and decision < valid <= horizon and (arm == "control" or region):
                        qualifying.append(event)
                        if (fill_clock <= valid and fill_clock <= event["available"] + age):
                            surviving.append(event)
            row = dict(original)
            row["feature_unavailable"] = not ready
            row["source_unavailable"] = not (row["plan_tradable"] is True
                                               and pd.notna(row["contract_id"]))
            row["stale_at_fill"] = ((effective - day).days
                                      > rule["maximum_fill_gap_calendar_days"]
                                      or bool(qualifying) and not surviving)
            row["requested_weight"] = rule["target_weight"] if qualifying and ready else 0.0
            row["target_weight"] = row["requested_weight"] if not (
                row["source_unavailable"] or row["stale_at_fill"]) else 0.0
            row["source_url"] = ";".join(sorted({r["url"] for r in qualifying}))
            row["available_at_utc"] = max((r["available"] for r in qualifying), default=pd.NaT)
            row["decision_at_utc"] = decision
            row["sampled_active_storms"] = len(latest)
            row["provenance"] = "v97_nhc_forecast_" + arm
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
    base.require(base.sha(SEAL) == expected, "V97 seal drift")
    for path, digest in json.loads(SEAL.read_text(encoding="utf-8"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, path)) == digest, "V97 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["assets"] == ["BR"] and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"], "scope drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def run(cfg, parent, expected, manifest_sha):
    source = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    base.require(base.sha(source / "manifest.json") == manifest_sha, "source manifest drift")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(manifest["status"] == "COMPLETE" and manifest["seal_sha256"] == expected
                 and manifest["records"] + manifest["parse_gaps"] == manifest["planned_messages"],
                 "incomplete/unbound source")
    for path, digest in manifest["files"].items():
        base.require(base.sha(base.safe(source, path)) == digest, "source artifact drift")
    records = json.loads((source / "advisories.json").read_text(encoding="utf-8-sig"))
    gaps = json.loads((source / "parse_gaps.json").read_text(encoding="utf-8-sig"))
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = targets(active, records, gaps, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "source_records": len(records), "source_parse_gaps": len(gaps),
               "original_receipt_verified": False}
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "futures": verified,
                    "source_manifest": manifest, "started_at_utc": datetime.now(UTC).isoformat()})
    # All design/source identities and source-only target masks are fixed before prices.
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "hurricane_supply")
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"],
               "seal_sha256": expected, "source_manifest_sha256": manifest_sha,
               "completed_at_utc": datetime.now(UTC).isoformat(), "case": case,
               "limitations": cfg["limitations"], "goal_verified": False}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "manifest.json", {"status": "COMPLETE", "seal_sha256": expected,
                    "completed_at_utc": payload["completed_at_utc"], "files": {
                        str(p.relative_to(output)): base.sha(p)
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
