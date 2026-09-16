"""V102 correction of one unused prior-year header; unchanged economic hypothesis."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime

import pandas as pd

from market_lab import futures_v102_tic_bank_funding as original

base, engine, STORAGE = original.base, original.engine, original.STORAGE
CONFIG = base.PROJECT / "configs/v102_tic_bank_funding_v2.json"
SEAL = base.PROJECT / "configs/v102_tic_bank_funding_v2.seal.json"
TYPO_SHA = "0a12dba5637e022d9e84f3c4d5b1011ea4fb4758b9a0cd990dc9eca138567760"


def config():
    fix = original.read_json(CONFIG)
    cfg = copy.deepcopy(original.read_json(original.CONFIG))
    cfg["protocol_id"] = fix["protocol_id"]
    cfg["source"].update(source_parent=fix["source_parent"],
                          failed_source=fix["failed_source"])
    return cfg


def parse_release(raw, date, url):
    corrected = pd.Timestamp(date) == pd.Timestamp("2019-06-17")
    if corrected:
        base.require(hashlib.sha256(raw).hexdigest() == TYPO_SHA, "unrecognized typo bytes")
        parser = original.Release()
        parser.feed(raw.decode("utf-8-sig"))
        headers = [r for t in parser.tables for r in t if [c for c in r if c] == [
            "2017", "2018", "Apr-19", "Apr-19", "Jan", "Feb", "Mar", "Apr"]]
        base.require(len(headers) == 1 and raw.count(b"Apr-19") == 2, "typo header drift")
        # Only the unused prior-year rolling header, never the feature column or saved raw.
        raw = raw.replace(b"Apr-19", b"Apr-18", 1)
    row = original.parse_release(raw, date, url)
    return {**row, "unused_prior_rolling_header_corrected": corrected}


def collect(cfg, expected):
    spec = cfg["source"]
    probes = {}
    for key, item in spec["probes"].items():
        root = base.safe(STORAGE, item["path"])
        original.checked_inventory(root, item["manifest_sha256"], "COMPLETE_FEASIBILITY_ONLY")
        probes[key] = root
    failed = base.safe(STORAGE, spec["failed_source"]["path"])
    failure = original.checked_inventory(failed, spec["failed_source"]["manifest_sha256"],
                                         "FAILED_SOURCE_NO_RETRY")
    base.require(failure["error"] == "rolling year/month mismatch"
                 and failure["parsed_releases"] == 18 and failure["new_http_requests"] == 18,
                 "not the observed failure")
    root = base.safe(STORAGE, spec["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    rows, requests, reused = [], 0, 0
    try:
        for name in ("index.html", "index.html.metadata.json"):
            shutil.copyfile(probes["initial"] / name, root / "raw" / name)
        original.check_http(root / "raw/index.html", original.INDEX_URL)
        dates = original.select_dates((root / "raw/index.html").read_bytes(), cfg)
        base.write_json(root / "selected_dates.json", dates)
        for date, url in dates.items():
            name = date + ".html"
            source = (failed / "raw" if "raw/" + name in failure["files"] else
                      probes[spec["reused_dates"][date]] if date in spec["reused_dates"] else None)
            if source is not None:
                for suffix in ("", ".metadata.json"):
                    shutil.copyfile(source / (name + suffix), root / "raw" / (name + suffix))
                raw = (root / "raw" / name).read_bytes()
                reused += 1
            else:
                requests += 1
                raw = original.prior.prior.source_tools.fetch(url, root / "raw" / name, 3000000, 1.)
            original.check_http(root / "raw" / name, url)
            rows.append(parse_release(raw, date, url))
            print(json.dumps({"parsed_releases": len(rows), "release_date": date}), flush=True)
        original.states(rows)
        base.require(requests == 74 and reused == 22, "unexpected request/reuse count")
        base.write_json(root / "releases.json", rows)
        status, error = "COMPLETE", None
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        status, error = "FAILED_SOURCE_NO_RETRY", str(exc)
    base.write_json(root / "manifest.json", {
        "status": status, "error": error, "seal_sha256": expected,
        "parsed_releases": len(rows), "new_http_requests": requests, "reused_releases": reused,
        "completed_at_utc": datetime.now(UTC).isoformat(), "economic_admission": False,
        "original_receipt_verified": False, "files": {
            p.relative_to(root).as_posix(): base.sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}})
    print(json.dumps({"source_root": str(root), "status": status, "error": error,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(status == "COMPLETE", "source failed; preserve root, no economics")


def verify_source(cfg, expected, manifest_sha):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    manifest = original.checked_inventory(root, manifest_sha, "COMPLETE")
    base.require(manifest["seal_sha256"] == expected and manifest["new_http_requests"] == 74
                 and manifest["reused_releases"] == 22, "source seal/count drift")
    dates = original.select_dates((root / "raw/index.html").read_bytes(), cfg)
    base.require(dates == original.read_json(root / "selected_dates.json"), "calendar drift")
    original.check_http(root / "raw/index.html", original.INDEX_URL)
    for date, url in dates.items():
        original.check_http(root / "raw" / (date + ".html"), url)
    releases = original.read_json(root / "releases.json")
    replay = [parse_release((root / "raw" / (d + ".html")).read_bytes(), d, u)
              for d, u in dates.items()]
    base.require(releases == replay and len(releases) == manifest["parsed_releases"],
                 "source reparse drift")
    return manifest, releases


def load(expected):
    base.require(base.sha(SEAL) == expected, "V102 V2 seal drift")
    for name, digest in original.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V102 V2 file drift")
    _, parent = original.load(original.read_json(CONFIG)["parent_v102_seal_sha256"])
    return config(), parent


def run(cfg, parent, expected, manifest_sha):
    manifest, releases = verify_source(cfg, expected, manifest_sha)
    state = original.states(releases)
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "source_manifest": manifest,
                    "effective_config": cfg, "futures": verified,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = original.targets(active, state, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "source_releases": len(releases), "original_receipt_verified": False}
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "tic_bank_funding")
    audit = original.prior.audit_case(output / "case", case, signals)
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"], "seal_sha256": expected,
               "source_manifest_sha256": manifest_sha,
               "completed_at_utc": datetime.now(UTC).isoformat(),
               "case": case, "audit": audit, "limitations": cfg["limitations"],
               "correction": original.read_json(CONFIG), "goal_verified": False}
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
