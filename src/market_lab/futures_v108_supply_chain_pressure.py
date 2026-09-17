"""One supply-constraint premium screen from published vintage-labelled GSCPI columns."""

from __future__ import annotations

import argparse
import calendar
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
CONFIG = base.PROJECT / "configs/v108_supply_chain_pressure_v1.json"
SEAL = base.PROJECT / "configs/v108_supply_chain_pressure_v1.seal.json"
MONTHS = {name: i for i, name in enumerate(calendar.month_abbr) if name}
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def month_label(label):
    match = re.fullmatch(r"([A-Z][a-z]{2})-(\d{2})", label)
    base.require(match is not None and match[1] in MONTHS, "invalid vintage label")
    return pd.Period(year=2000 + int(match[2]), month=MONTHS[match[1]], freq="M")


def availability(month):
    return (
        month.end_time.normalize().tz_localize("America/New_York")
        + pd.Timedelta(days=1)
        - pd.Timedelta(seconds=1)
    ).tz_convert("UTC")


def records(raw, cfg, *, numeric=False):
    """Metadata and value paths share exact selection; zero never means missing."""
    table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    base.require(bool(table) and table[0][0] == "Date", "CSV identity")
    header, rows = table[0], table[1:]
    base.require(len(header) == len(set(header)), "duplicate CSV column")
    months = [month_label(label) for label in header[1:]]
    base.require(months == sorted(set(months)), "vintage order/duplicates")
    dated, seen_dates = {}, []
    for row in rows:
        base.require(len(row) == len(header), "CSV row width")
        if not row[0]:
            base.require(all(not cell.strip() for cell in row), "nonempty undated row")
            continue
        match = re.fullmatch(r"(\d{2})-([A-Z][a-z]{2})-(20\d{2}|19\d{2})", row[0])
        base.require(match is not None and match[2] in MONTHS, "invalid observation date")
        day = pd.Timestamp(year=int(match[3]), month=MONTHS[match[2]], day=int(match[1]))
        base.require(day.is_month_end, "observation not month-end")
        seen_dates.append(day)
        if day >= base.BOUNDARY:  # Never inspect protected-period cell contents.
            continue
        dated[day.to_period("M")] = row
    base.require(seen_dates == sorted(set(seen_dates)), "observation order/duplicates")
    spec = cfg["source"]
    first, last = pd.Period(spec["first_vintage"], "M"), pd.Period(spec["last_vintage"], "M")
    selected = []
    for i, month in enumerate(months, 1):
        clock = availability(month)
        if clock >= pd.Timestamp(base.BOUNDARY, tz="UTC") or not first <= month <= last:
            continue  # Excluded columns never undergo numeric conversion.
        current, previous = month - 1, month - 2
        base.require(current in dated and previous in dated, "missing comparison month")
        valid = []
        for observation, row in dated.items():
            token = row[i]
            if observation > current:
                base.require(token == "#N/A", "future value inside historical vintage")
            else:
                base.require(token == "#N/A" or NUMBER.fullmatch(token), "invalid numeric token")
                if token != "#N/A":
                    valid.append(observation)
        base.require(bool(valid), "vintage has no numeric history")
        pair = [dated[observation][i] for observation in (current, previous)]
        record = {
            "vintage": str(month),
            "vintage_label": header[i],
            "observation_month": str(current),
            "comparison_month": str(previous),
            "source_date": month.end_time.normalize(),
            "available_at_utc": clock,
            "ready": all(token != "#N/A" for token in pair),
            "source_url": spec["url"] + "#vintage=" + header[i],
            "numeric_observation_count": len(valid),
            "last_numeric_observation_month": str(max(valid)),
            "original_receipt_verified": False,
        }
        if numeric:
            record["current_index"], record["previous_index"] = [
                None if token == "#N/A" else str(Decimal(token)) for token in pair
            ]
        selected.append(record)
    expected = [str(m) for m in pd.period_range(first, last, freq="M")]
    base.require(
        [row["vintage"] for row in selected] == expected
        and len(selected) == spec["expected_vintages"],
        "incomplete selected vintage inventory",
    )
    return selected


def states(rows):
    result = []
    for row in rows:
        current, previous = [
            None if row[k] is None else Decimal(row[k]) for k in ("current_index", "previous_index")
        ]
        base.require(
            all(v is None or v.is_finite() for v in (current, previous)), "nonfinite index"
        )
        ready = current is not None and previous is not None
        base.require(ready == row["ready"], "ready/value mismatch")
        result.append(
            {
                **row,
                "asset_code": "BR",
                "primary_direction": float(ready and current > 0 and current > previous),
                "control_direction": float(ready),
            }
        )
    d = pd.DataFrame(result).sort_values("available_at_utc", ignore_index=True)
    base.require(not d.empty and not d.source_date.duplicated().any(), "duplicate/empty states")
    base.require(
        d.available_at_utc.lt(pd.Timestamp(base.BOUNDARY, tz="UTC")).all(), "protected states"
    )
    return d


def source(cfg, storage=STORAGE):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "manifest drift")
    manifest = prior.read_json(root / "manifest.json")
    base.require(manifest["status"] == "COMPLETE_FEASIBILITY_CAPTURE_ONLY", "capture incomplete")
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "source artifact drift")
    base.require(
        base.sha(root.parent / "executed_capture_script.py")
        == spec["executed_capture_script_sha256"],
        "executed capture identity drift",
    )
    path = root / "gscpi_interactive_data.csv"
    base.require(base.sha(path) == spec["csv_sha256"], "CSV drift")
    return path.read_bytes(), manifest


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V108 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V108 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["BR"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected):
    raw, manifest = source(cfg)
    metadata = records(raw, cfg)
    verified = base.preflight(parent, STORAGE)
    out = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    out.mkdir(exist_ok=False)
    base.write_json(
        out / "inputs.json",
        {
            "seal_sha256": expected,
            "source_manifest": manifest,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    base.write_json(out / "source_metadata.json", metadata)
    rows = records(raw, cfg, numeric=True)
    state = states(rows)
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
        "source_vintages": len(state),
        "ready_vintages": int(state.ready.sum()),
        "long_vintages": int(state.primary_direction.gt(0).sum()),
        "original_receipt_verified": False,
    }
    base.write_json(out / "source_quality.json", quality)
    base.require(
        quality["ready_asset_date_fraction"]
        >= cfg["screen_gates"]["minimum_ready_asset_date_fraction"],
        "source coverage gate",
    )
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(out / "case", signals, market, quality, cfg, "supply_constraint")
    audit = prior.audit_case(out / "case", case, signals)
    payload = {
        "status": "COMPLETE",
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "case": case,
        "audit": audit,
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(out / "metrics.json", payload)
    base.write_json(
        out / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "completed_at_utc": payload["completed_at_utc"],
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
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, args.seal_sha)


if __name__ == "__main__":
    main()
