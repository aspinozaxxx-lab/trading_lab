"""One EBP risk-appetite rule, MIX long/cash; unchanged daily execution ledger."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v111_credit_risk_appetite_v1.json"
SEAL = base.PROJECT / "configs/v111_credit_risk_appetite_v1.seal.json"
URL = "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv"
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def clock(day):
    end = day + pd.offsets.MonthEnd(0)
    proxy = end + pd.offsets.MonthEnd(1)
    available = (
        (proxy + pd.Timedelta(days=1)).tz_localize("America/New_York") - pd.Timedelta(seconds=1)
    ).tz_convert("UTC")
    return end, proxy, available


def records(raw, cfg, *, numeric=False):
    spec = cfg["source"]
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    base.require(reader.fieldnames == spec["headers"], "CSV header identity")
    rows = list(reader)
    dates, selected, result = [], [], []
    for row in rows:
        base.require(set(row) == set(spec["headers"]), "row schema")
        token = row[spec["date_column"]]
        base.require(
            isinstance(token, str) and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", token),
            "source date format",
        )
        month, dom, year = map(int, token.split("/"))
        day = pd.Timestamp(year=year, month=month, day=dom)
        text = day.strftime("%Y-%m-%d")
        base.require(day.day == 1, "monthly label must be first day")
        dates.append(day)
        if not spec["raw_start"] <= text <= spec["raw_end"]:
            continue  # No value access to other dates or protected2026 observations.
        selected.append(day)
        end, proxy, available = clock(day)
        if available >= pd.Timestamp(base.BOUNDARY, tz="UTC"):
            continue  # Do not inspect even malformed cells when availability is protected.
        value = row[spec["value_column"]]
        missing = value in spec["missing_tokens"]
        base.require(
            missing or isinstance(value, str) and NUMBER.fullmatch(value), "invalid EBP token"
        )
        record = {
            "original_date_token": token,
            "observation_date": day,
            "source_date": end,
            "proxy_release_date": proxy,
            "available_at_utc": available,
            "cells_complete": not missing,
            "source_url": URL + "#month=" + text,
            "original_receipt_verified": False,
        }
        if numeric:
            record["ebp"] = None if missing else value
        result.append(record)
    base.require(dates == sorted(set(dates)), "duplicate/unordered raw dates")
    expected = list(pd.date_range(spec["raw_start"], spec["raw_end"], freq="MS"))
    base.require(
        selected == expected and len(selected) == spec["expected_raw_reports"],
        "monthly calendar coverage",
    )
    base.require(len(result) == spec["expected_eligible_reports"], "eligible calendar")
    return result


def states(rows):
    result = []
    for row in rows:
        value = None if row["ebp"] is None else Decimal(row["ebp"])
        base.require(value is None or value.is_finite(), "nonfinite EBP")
        ready = row["cells_complete"] and value is not None
        result.append(
            {
                **row,
                "asset_code": "MIX",
                "ready": ready,
                "primary_direction": float(ready and value <= 0),
                "control_direction": float(ready),
            }
        )
    return pd.DataFrame(result)


def source(cfg, storage=STORAGE):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    base.require(
        base.sha(root / "manifest.json") == spec["manifest_sha256"], "source manifest drift"
    )
    manifest = prior.read_json(root / "manifest.json")
    base.require(
        manifest["status"] == spec["capture_status"]
        and manifest["failure"] == spec["capture_parser_failure"],
        "capture status drift",
    )
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "source artifact drift")
    path = root / "ebp.csv"
    base.require(base.sha(path) == spec["raw_sha256"], "raw drift")
    meta = prior.read_json(root / "ebp.csv.metadata.json")
    base.require(meta["url"] == URL and meta["http_status"] == "200", "source query/status drift")
    base.require(
        meta["curl_returncode"] == 0 and meta["bytes"] == path.stat().st_size, "incomplete raw HTTP"
    )
    return path.read_bytes(), manifest


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V111 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V111 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["MIX"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected):
    raw, evidence = source(cfg)
    metadata = records(raw, cfg)
    verified = base.preflight(parent, STORAGE)
    out = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    out.mkdir(exist_ok=False)
    base.write_json(
        out / "inputs.json",
        {
            "seal_sha256": expected,
            "source_manifest": evidence,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    base.write_json(out / "source_metadata.json", metadata)
    state = states(records(raw, cfg, numeric=True))
    state.to_parquet(out / "source_states.parquet", index=False)
    pd.testing.assert_frame_equal(state, pd.read_parquet(out / "source_states.parquet"))
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = targets(active, state, cfg)
    p = signals["primary"]
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "source_reports": len(state),
        "ready_reports": int(state.ready.sum()),
        "long_reports": int(state.primary_direction.gt(0).sum()),
        "original_receipt_verified": False,
    }
    base.write_json(out / "source_quality.json", quality)
    base.require(
        quality["ready_asset_date_fraction"]
        >= cfg["screen_gates"]["minimum_ready_asset_date_fraction"],
        "source coverage gate",
    )
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(out / "case", signals, market, quality, cfg, "credit_risk_appetite")
    audit = prior.audit_case(out / "case", case, signals)
    base.write_json(
        out / "metrics.json",
        {
            "status": "COMPLETE",
            "protocol_id": cfg["protocol_id"],
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "case": case,
            "audit": audit,
            "limitations": cfg["limitations"],
            "goal_verified": False,
        },
    )
    base.write_json(
        out / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "files": {
                p.relative_to(out).as_posix(): base.sha(p)
                for p in sorted(out.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(json.dumps({"output": str(out), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, args.seal_sha)


if __name__ == "__main__":
    main()
