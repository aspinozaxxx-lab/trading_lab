"""One private secured-intermediation contraction screen; unchanged futures ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

import pandas as pd

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v109_private_deleveraging_v1.json"
SEAL = base.PROJECT / "configs/v109_private_deleveraging_v1.seal.json"
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def source_url(cfg):
    spec = cfg["source"]
    return "https://markets.newyorkfed.org/read?" + urlencode(
        {
            "productCode": "40",
            "startDt": spec["raw_start"],
            "endDt": spec["raw_end"],
            "keyIds": ",".join(spec["borrowing_keys"] + spec["lending_keys"]),
            "format": "json",
        }
    )


def availability(day, days):
    local_day = (day + pd.Timedelta(days=days)).tz_localize("America/New_York")
    return (local_day + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).tz_convert("UTC")


def records(raw, cfg, *, numeric=False):
    """Only inspect cells after date and computed publication-boundary filtering."""
    spec = cfg["source"]
    doc = json.loads(raw.decode("utf-8-sig"), parse_float=str, parse_int=str)
    base.require(isinstance(doc, dict) and set(doc) == {"data"}, "source envelope")
    base.require(isinstance(doc["data"], list), "source rows")
    keys = spec["borrowing_keys"] + spec["lending_keys"]
    base.require(len(keys) == len(set(keys)) == 12, "declared key identity")
    dates, result = [], []
    for row in doc["data"]:
        base.require(set(row) == {"_id", "values"} and set(row["_id"]) == {"date"}, "row identity")
        text = row["_id"]["date"]
        base.require(
            isinstance(text, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text),
            "invalid source date",
        )
        day = pd.Timestamp(text)
        base.require(
            spec["raw_start"] <= text <= spec["raw_end"] and day < base.BOUNDARY,
            "outside requested/protected dates",
        )
        dates.append(day)
        clock = availability(day, spec["availability_calendar_days"])
        if clock >= pd.Timestamp(base.BOUNDARY, tz="UTC"):
            continue  # No excluded cell inspection, including malformed numeric tokens.
        base.require(isinstance(row["values"], list), "values shape")
        cells = {}
        for cell in row["values"]:
            base.require(set(cell) == {"keyId", "value"}, "cell schema")
            key, value = cell["keyId"], cell["value"]
            base.require(key in keys and key not in cells, "duplicate/unknown key")
            base.require(
                value is None or isinstance(value, str) and NUMBER.fullmatch(value),
                "invalid financing token",
            )
            cells[key] = value
        record = {
            "source_date": day,
            "available_at_utc": clock,
            "schema_era": "SBN2022" if text < spec["schema_break"] else "SBN2024",
            "cells_complete": len(cells) == 12 and all(v is not None for v in cells.values()),
            "reported_cells": len(cells),
            "source_url": source_url(cfg) + "#observation-date=" + text,
            "original_receipt_verified": False,
        }
        if numeric:
            record["values"] = {key: cells.get(key) for key in keys}
        result.append(record)
    expected = list(pd.date_range(spec["raw_start"], spec["raw_end"], freq="W-WED"))
    base.require(
        sorted(dates) == expected and len(dates) == spec["expected_raw_reports"],
        "incomplete/duplicate weekly calendar",
    )
    result.sort(key=lambda r: r["source_date"])
    base.require(len(result) == spec["expected_eligible_reports"], "eligible report count")
    return result


def states(rows, cfg):
    spec, signal = cfg["source"], cfg["signal"]
    summaries, result = [], []
    for row in rows:
        converted = {}
        for key, value in row["values"].items():
            number = None if value is None else Decimal(value)
            base.require(
                number is None or number.is_finite() and number >= 0, "nonfinite/negative financing"
            )
            converted[key] = number
        totals = {}
        for side in ("borrowing", "lending"):
            parts = [converted[key] for key in spec[side + "_keys"]]
            totals[side] = None if any(v is None for v in parts) else sum(parts, Decimal(0))
        valid = row["cells_complete"] and all(v is not None and v > 0 for v in totals.values())
        summaries.append({**totals, "valid": valid, "era": row["schema_era"]})
        n = signal["comparison_reports"] + 1
        window = summaries[-n:]
        ready = len(window) == n and all(s["valid"] for s in window)
        ready = ready and len({s["era"] for s in window}) == 1
        long = ready and all(totals[side] < window[0][side] for side in totals)
        result.append(
            {
                **{k: v for k, v in row.items() if k != "values"},
                "asset_code": "SI",
                "ready": ready,
                "primary_direction": float(long),
                "control_direction": float(ready),
                "borrowing_total": None
                if totals["borrowing"] is None
                else str(totals["borrowing"]),
                "lending_total": None if totals["lending"] is None else str(totals["lending"]),
                "comparison_source_date": rows[len(summaries) - n]["source_date"]
                if len(summaries) >= n
                else pd.NaT,
            }
        )
    d = pd.DataFrame(result)
    base.require(
        not d.empty
        and d.source_date.is_monotonic_increasing
        and not d.source_date.duplicated().any(),
        "unordered/empty states",
    )
    base.require(
        d.available_at_utc.lt(pd.Timestamp(base.BOUNDARY, tz="UTC")).all(), "protected states"
    )
    return d


def source(cfg, storage=STORAGE):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    evidence = {}
    for folder, digest in spec["manifests"].items():
        path = root / folder / "manifest.json"
        base.require(base.sha(path) == digest, "source manifest drift")
        manifest = prior.read_json(path)
        expected = (
            "COMPLETE_RAW_QUARANTINE_ONLY" if folder == "source" else "COMPLETE_METADATA_ONLY"
        )
        base.require(manifest["status"] == expected, "incomplete source")
        for name, sha in manifest["files"].items():
            base.require(base.sha(base.safe(path.parent, name)) == sha, "source artifact drift")
        evidence[folder] = manifest
    raw = root / "source/financing.json"
    base.require(base.sha(raw) == spec["raw_sha256"], "raw drift")
    started = prior.read_json(root / "source/started.json")
    base.require(started["url"] == source_url(cfg), "captured query identity drift")
    return raw.read_bytes(), evidence


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V109 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V109 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["SI"]
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
            "source_manifests": evidence,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    base.write_json(out / "source_metadata.json", metadata)
    state = states(records(raw, cfg, numeric=True), cfg)
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
    case = engine.simulate_case(out / "case", signals, market, quality, cfg, "private_deleveraging")
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
