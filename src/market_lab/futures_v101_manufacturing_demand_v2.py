"""V101 source-format correction only; economics are inherited unchanged from V1."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from market_lab import futures_v101_manufacturing_demand as original

base, engine = original.base, original.engine
STORAGE = original.STORAGE
CONFIG = base.PROJECT / "configs/v101_manufacturing_demand_v2.json"
SEAL = base.PROJECT / "configs/v101_manufacturing_demand_v2.seal.json"


def config():
    correction = original.read_json(CONFIG)
    cfg = copy.deepcopy(original.read_json(original.CONFIG))
    cfg["protocol_id"] = correction["protocol_id"]
    cfg["source"]["source_parent"] = correction["source_parent"]
    cfg["source"]["failed_source_path"] = correction["failed_source_path"]
    cfg["source"]["failed_manifest_sha256"] = correction["failed_manifest_sha256"]
    cfg["source"]["reused_failed_dates"] = correction["reused_failed_dates"]
    return cfg


def month_headers(refs):
    """Resolve either separate year/month headers or the observed combined header."""
    years, months = [], []
    for cell in refs:
        text = cell["text"]
        if re.fullmatch(r"\d{4}", text):
            years.append(int(text))
            continue
        match = re.fullmatch(r"(?:(\d{4}) )?([A-Za-z]+)\.? \[([rp])\]", text)
        if match and match[2].lower() in original.MONTHS:
            if match[1]:
                years.append(int(match[1]))
            months.append((original.MONTHS[match[2].lower()], match[3]))
    return years, months


def parse_release(raw, release, url):
    # Same V1 checks and data selection; only month_headers differs.
    day = pd.Timestamp(release)
    base.require(day < base.BOUNDARY, "protected source")
    decoded = raw.decode("utf-8-sig")
    text_parser = original.prior.TextParser()
    text_parser.feed(decoded)
    text = original.prior.normalize(" ".join(text_parser.parts))
    headers = re.findall(r"Release Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    base.require(len(headers) == 1 and pd.Timestamp(headers[0]) == day, "release identity")
    base.require("Seasonally adjusted" in text, "missing seasonal unit")
    parser = original.SummaryTable()
    parser.feed(decoded)
    base.require(len(parser.tables) == 1 and parser.rows is None, "ambiguous summary table")
    rows = parser.tables[0]
    identified = [c for row in rows for c in row if c["attrs"].get("id")]
    by_id = {c["attrs"]["id"].strip(): c for c in identified}
    base.require(len(by_id) == len(identified), "duplicate table header id")
    manufacturing = [row for row in rows if row and row[0]["tag"] == "th"
                     and row[0]["text"] in {"Manufacturing (see note below)", "Manufacturing*"}]
    base.require(len(manufacturing) == 1, "ambiguous manufacturing row")
    observations = []
    for cell in manufacturing[0][1:]:
        keys = cell["attrs"].get("headers", "").split()
        base.require(keys and all(k in by_id for k in keys), "unknown header reference")
        refs = [by_id[k] for k in keys]
        if not any(c["text"] == "Percent change" for c in refs):
            continue
        years, months = month_headers(refs)
        if not years and not months:  # The distinct year-on-year column.
            continue
        base.require(len(years) == len(months) == 1, "ambiguous month/year headers")
        base.require(re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", cell["text"]) is not None,
                     "missing/non-numeric monthly estimate")
        value = float(cell["text"])
        base.require(np.isfinite(value) and -100 < value <= 1000, "invalid monthly change")
        observations.append((pd.Period(year=years[0], month=months[0][0], freq="M"),
                             months[0][1], value))
    base.require(len(observations) in (6, 7), "unexpected monthly column count")
    periods = [r[0] for r in observations]
    base.require(periods == list(pd.period_range(periods[0], periods[-1], freq="M")),
                 "duplicate/nonconsecutive monthly columns")
    month, flag, value = observations[-1]
    base.require(flag == "p" and 1 <= day.to_period("M").ordinal - month.ordinal <= 3,
                 "latest observation is not prior preliminary month")
    return {"release_date": day.date().isoformat(), "observation_month": str(month),
            "available_at_utc": original.prior.day_availability(day).isoformat(),
            "manufacturing_mom_percent": value, "source_url": url,
            "monthly_columns": len(observations), "usable": True,
            "original_receipt_verified": False}


def checked_inventory(root, digest, status):
    base.require(base.sha(root / "manifest.json") == digest, "reused manifest drift")
    inventory = original.read_json(root / "manifest.json")
    base.require(inventory["status"] == status, "reused source status drift")
    for name, expected in inventory["files"].items():
        base.require(base.sha(base.safe(root, name)) == expected, "reused artifact drift")
    return inventory


def collect(cfg, expected):
    spec = cfg["source"]
    probe = base.safe(STORAGE, spec["probe_path"])
    failed = base.safe(STORAGE, spec["failed_source_path"])
    inventory = checked_inventory(probe, spec["probe_manifest_sha256"],
                                  "COMPLETE_FEASIBILITY_ONLY")
    failure = checked_inventory(failed, spec["failed_manifest_sha256"],
                                "FAILED_SOURCE_NO_RETRY")
    base.require(failure["error"] == "unexpected monthly column count"
                 and failure["parsed_releases"] == 2 and failure["new_http_requests"] == 3,
                 "not the observed structural failure")
    root = base.safe(STORAGE, spec["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    rows, requests, reused = [], 0, 0
    try:
        for name in ("index.html", "index.html.metadata.json"):
            shutil.copyfile(probe / name, root / "raw" / name)
        dates = original.select_dates((root / "raw/index.html").read_bytes(), cfg)
        base.write_json(root / "selected_dates.json", dates)
        for release in dates:
            name, url = release + ".html", original.ORIGIN + release + "/"
            if release in spec["reused_probe_dates"]:
                source, relative, declared = probe, name, inventory
            elif release in spec["reused_failed_dates"]:
                source, relative, declared = failed, "raw/" + name, failure
            else:
                source = None
            if source is not None:
                for suffix in ("", ".metadata.json"):
                    base.require(relative + suffix in declared["files"], "unrecorded reuse")
                    shutil.copyfile(base.safe(source, relative + suffix),
                                    root / "raw" / (name + suffix))
                raw = (root / "raw" / name).read_bytes()
                reused += 1
            else:
                requests += 1
                raw = original.prior.source_tools.fetch(url, root / "raw" / name, 3000000, 1.)
            rows.append(parse_release(raw, release, url))
            print(json.dumps({"parsed_releases": len(rows), "release_date": release}), flush=True)
        original.states(rows)
        base.require(requests == 90 and reused == 6, "unexpected source request count")
        base.write_json(root / "releases.json", rows)
        status, error = "COMPLETE", None
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as failure_error:
        status, error = "FAILED_SOURCE_NO_RETRY", str(failure_error)
    base.write_json(root / "manifest.json", {
        "status": status, "error": error, "seal_sha256": expected,
        "parsed_releases": len(rows), "new_http_requests": requests, "reused_releases": reused,
        "reused_manifests": {"probe": spec["probe_manifest_sha256"],
                             "failed_v1": spec["failed_manifest_sha256"]},
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "original_receipt_verified": False, "economic_admission": False,
        "files": {p.relative_to(root).as_posix(): base.sha(p)
                  for p in sorted(root.rglob("*")) if p.is_file()}})
    print(json.dumps({"source_root": str(root), "status": status, "error": error,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(status == "COMPLETE", "source failed; preserve root, no economics")


def verify_source(cfg, expected, manifest_sha):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    manifest = checked_inventory(root, manifest_sha, "COMPLETE")
    base.require(manifest["seal_sha256"] == expected and manifest["new_http_requests"] == 90
                 and manifest["reused_releases"] == 6, "source identity/count drift")
    dates = original.select_dates((root / "raw/index.html").read_bytes(), cfg)
    base.require(dates == original.read_json(root / "selected_dates.json"), "calendar drift")
    releases = original.read_json(root / "releases.json")
    replay = [parse_release((root / "raw" / (d + ".html")).read_bytes(), d,
                            original.ORIGIN + d + "/") for d in dates]
    base.require(releases == replay and len(releases) == manifest["parsed_releases"],
                 "source reparse drift")
    return manifest, releases


def load(expected):
    base.require(base.sha(SEAL) == expected, "V101 V2 seal drift")
    for name, digest in original.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V101 V2 file drift")
    correction = original.read_json(CONFIG)
    _, parent = original.load(correction["parent_v101_seal_sha256"])
    return config(), parent


def run(cfg, parent, expected, manifest_sha):
    manifest, releases = verify_source(cfg, expected, manifest_sha)
    state = original.states(releases)
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = original.targets(active, state, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "source_releases": len(releases), "original_receipt_verified": False}
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "source_manifest": manifest,
                    "effective_config": cfg, "futures": verified,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "manufacturing")
    audit = original.audit_case(output / "case", case, signals)
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"],
               "seal_sha256": expected, "source_manifest_sha256": manifest_sha,
               "completed_at_utc": datetime.now(UTC).isoformat(), "case": case,
               "audit": audit, "limitations": cfg["limitations"], "goal_verified": False,
               "correction": original.read_json(CONFIG)}
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
