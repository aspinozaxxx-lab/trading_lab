"""A fixed physical inventory-cover premium screen using existing EIA vintages."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v104_inventory_cover_premium_v1.json"
SEAL = base.PROJECT / "configs/v104_inventory_cover_premium_v1.seal.json"
FIELDS = {
    ("Stocks", "Commercial (Excluding SPR)"): ("stocks", "million_barrels"),
    ("Crude Oil Supply", "Crude Oil Input to Refineries"): ("refinery", "thousand_barrels_per_day"),
}


def clocks(frame):
    d = frame.copy()
    for col in ("release_date", "data_week_ending"):
        d[col] = pd.to_datetime(d[col], errors="raise")
        base.require(
            d[col].notna().all()
            and d[col].lt(base.BOUNDARY).all()
            and d[col].eq(d[col].dt.normalize()).all(),
            "protected/invalid source date",
        )
    d["available_at"] = pd.to_datetime(d.available_at, utc=True, errors="raise")
    expected = d.release_date + pd.Timedelta(hours=23, minutes=59, seconds=59)
    expected = expected.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    base.require(
        d.available_at.eq(expected).all()
        and d.available_at.lt(base.BOUNDARY.tz_localize("UTC")).all()
        and d.data_week_ending.lt(d.release_date).all(),
        "source clock mismatch",
    )
    return d


def states(raw, coverage, cfg):
    d = clocks(coverage).sort_values("release_date", ignore_index=True)
    base.require(not d.empty and not d.release_date.duplicated().any(), "duplicate/empty calendar")
    raw = clocks(raw.loc[:, cfg["source"]["allowed_columns"]])
    selected = raw.loc[pd.MultiIndex.from_frame(raw[["section", "item"]]).isin(FIELDS)].copy()
    base.require(
        not selected.duplicated(["release_date", "section", "item"]).any(), "duplicate selected row"
    )
    base.require(selected.release_specific_archive.eq(True).all(), "not release-specific")
    by_date = d.set_index("release_date")
    for field, other in (
        ("data_week_ending", "data_week_ending"),
        ("available_at", "available_at"),
        ("source_url", "source_url"),
        ("raw_sha256", "sha256"),
    ):
        base.require(
            selected[field].eq(selected.release_date.map(by_date[other])).all(),
            "source/calendar identity mismatch: " + field,
        )
    labels = []
    for row in selected.itertuples(index=False):
        name, unit = FIELDS[(row.section, row.item)]
        base.require(row.unit == unit, "physical unit mismatch")
        labels.append(name)
    selected["field"] = labels
    selected["current_value"] = pd.to_numeric(selected.current_value, errors="coerce")
    values = selected.pivot(index="release_date", columns="field", values="current_value")
    for field in ("stocks", "refinery"):
        d[field] = d.release_date.map(values.get(field, pd.Series(dtype=float))).astype(float)
    numeric = d[["stocks", "refinery"]]
    d["observed"] = (
        d.admissible.eq(True) & np.isfinite(numeric).all(axis=1) & numeric.gt(0).all(axis=1)
    )
    d["cover_days"] = (1000.0 * d.stocks / d.refinery).where(d.observed)
    d["observed"] &= np.isfinite(d.cover_days)
    d.loc[~d.observed, "cover_days"] = np.nan
    # A later revised observation never replaces an earlier usable historical vintage.
    history = d.loc[d.observed].drop_duplicates("data_week_ending", keep="first")
    years = cfg["signal"]["seasonal_prior_years"]
    minimum = cfg["signal"]["minimum_weeks_each_prior_year_month"]
    baselines, complete_years, counts, last_times = [], [], [], []
    for row in d.itertuples(index=False):
        part = history.loc[
            history.available_at.lt(row.available_at)
            & history.data_week_ending.lt(row.data_week_ending)
            & history.data_week_ending.dt.month.eq(row.data_week_ending.month)
            & history.data_week_ending.dt.year.between(
                row.data_week_ending.year - years, row.data_week_ending.year - 1
            )
        ]
        grouped = part.groupby(part.data_week_ending.dt.year).cover_days.agg(["size", "mean"])
        complete = int(grouped["size"].ge(minimum).sum())
        baselines.append(float(grouped["mean"].mean()) if complete == years else np.nan)
        complete_years.append(complete)
        counts.append(len(part))
        last_times.append(part.available_at.max())
    d["seasonal_baseline_days"] = baselines
    d["baseline_complete_years"] = complete_years
    d["baseline_week_count"] = counts
    d["baseline_last_available_at_utc"] = pd.to_datetime(last_times, utc=True)
    d["ready"] = d.observed & np.isfinite(d.seasonal_baseline_days)
    d["scarcity"] = d.ready & d.cover_days.lt(d.seasonal_baseline_days)
    d["primary_direction"] = d.scarcity.astype(float)
    d["control_direction"] = d.ready.astype(float)
    d["source_date"] = d.release_date
    d["available_at_utc"] = d.available_at
    d["asset_code"] = "BR"
    d["original_receipt_verified"] = False
    base.require(
        d.loc[d.ready, "baseline_last_available_at_utc"]
        .lt(d.loc[d.ready, "available_at_utc"])
        .all(),
        "future baseline",
    )
    return d


def preflight(cfg, parent):
    source = cfg["source"]
    root = base.safe(STORAGE, source["root"])
    base.require(
        base.sha(root / "manifest.json") == source["manifest_sha256"], "EIA manifest drift"
    )
    manifest = prior.read_json(root / "manifest.json")
    for item in manifest["artifacts"].values():
        p = base.safe(root, item["path"])
        base.require(
            p.stat().st_size == item["bytes"] and base.sha(p) == item["sha256"],
            "EIA artifact drift",
        )
    semantics = manifest["temporal_semantics"]
    base.require(
        semantics["historical_development_backtest_admissible"] is True
        and semantics["contains_prices_returns_targets_labels_or_pnl"] is False,
        "source admission drift",
    )
    for kind, columns in (
        ("processed", source["allowed_columns"]),
        ("coverage", source["coverage_columns"]),
    ):
        declared = source[kind]
        for key in ("path", "sha256", "bytes", "rows"):
            base.require(
                manifest["artifacts"][kind][key] == declared[key], "source declaration drift"
            )
        path = base.safe(root, declared["path"])
        pf = pq.ParquetFile(path)
        base.require(
            pf.metadata.num_rows == declared["rows"] and set(columns) <= set(pf.schema_arrow.names),
            "source schema/count drift",
        )
        meta = clocks(
            pd.read_parquet(path, columns=["release_date", "data_week_ending", "available_at"])
        )
        base.require(
            str(meta.release_date.min().date()) == source["minimum_release_date"]
            and str(meta.release_date.max().date()) == source["maximum_release_date"]
            and meta.available_at.max() == pd.Timestamp(source["maximum_available_at"]),
            "source date bounds drift",
        )
    coverage = pd.read_parquet(
        root / source["coverage"]["path"], columns=source["coverage_columns"]
    )
    excluded = coverage.loc[~coverage.admissible]
    base.require(
        len(excluded) == 1
        and str(pd.Timestamp(excluded.release_date.iloc[0]).date()) == source["excluded_release"]
        and excluded.exclusion_reason.iloc[0] == source["excluded_reason"],
        "stale exclusion drift",
    )
    return {"source": source, "futures": base.preflight(parent, STORAGE), "all_true": True}


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V104 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V104 file drift")
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
    verified = preflight(cfg, parent)
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(
        output / "inputs.json",
        {
            "seal_sha256": expected,
            "verified": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    spec = cfg["source"]
    root = base.safe(STORAGE, spec["root"])
    raw = pd.read_parquet(root / spec["processed"]["path"], columns=spec["allowed_columns"])
    coverage = pd.read_parquet(root / spec["coverage"]["path"], columns=spec["coverage_columns"])
    state = states(raw, coverage, cfg)
    state.to_parquet(output / "source_states.parquet", index=False)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = targets(active, state, cfg)
    p = signals["primary"]
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "source_calendar_rows": len(state),
        "observed_cover_rows": int(state.observed.sum()),
        "ready_source_rows": int(state.ready.sum()),
        "scarcity_source_rows": int(state.scarcity.sum()),
        "original_receipt_verified": False,
    }
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "inventory_cover")
    audit = prior.audit_case(output / "case", case, signals)
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
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "completed_at_utc": payload["completed_at_utc"],
            "files": {
                p.relative_to(output).as_posix(): base.sha(p)
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, args.seal_sha)


if __name__ == "__main__":
    main()
