"""One frozen GDP survey-disagreement contraction screen on existing data."""

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
CONFIG = base.PROJECT / "configs/v105_survey_dispersion_v1.json"
SEAL = base.PROJECT / "configs/v105_survey_dispersion_v1.seal.json"


def clocks(frame, *, metadata=False):
    d = frame.copy()
    d["survey_month"] = pd.to_datetime(d.survey_month, errors="raise")
    base.require(
        d.survey_month.notna().all()
        and d.survey_month.lt(base.BOUNDARY).all()
        and d.survey_month.dt.day.eq(1).all()
        and d.survey_month.eq(d.survey_month.dt.normalize()).all(),
        "invalid/protected survey date",
    )
    d["available_at"] = pd.to_datetime(d.available_at, utc=True, errors="raise")
    expected = d.survey_month + pd.offsets.MonthEnd(2)
    expected += pd.Timedelta(hours=23, minutes=59, seconds=59)
    expected = expected.dt.tz_localize("Europe/Moscow").dt.tz_convert("UTC")
    base.require(d.available_at.eq(expected).all(), "survey clock mismatch")
    if not metadata:
        base.require(
            d.available_at.lt(base.BOUNDARY.tz_localize("UTC")).all(),
            "protected availability in numeric source",
        )
    return d


def calendar(meta):
    d = clocks(meta, metadata=True)[["survey_month", "available_at"]].drop_duplicates()
    base.require(not d.empty and not d.survey_month.duplicated().any(), "invalid calendar")
    return d.loc[d.available_at.lt(base.BOUNDARY.tz_localize("UTC"))].sort_values(
        "survey_month", ignore_index=True
    )


def states(raw, source_calendar, cfg):
    d = clocks(source_calendar).sort_values("survey_month", ignore_index=True)
    base.require(not d.empty and not d.survey_month.duplicated().any(), "duplicate/empty calendar")
    raw = clocks(raw)
    s = cfg["signal"]
    selected = raw.loc[
        raw.indicator.eq(s["indicator"]) & raw.statistic.isin(s["statistics"])
    ].copy()
    base.require(
        selected.unit.eq(s["unit"]).all()
        and selected.current_vintage.eq(True).all()
        and selected.source_url.eq(cfg["source"]["source_url"]).all(),
        "source unit/vintage/identity mismatch",
    )
    base.require(
        selected.available_at.eq(
            selected.survey_month.map(d.set_index("survey_month").available_at)
        ).all(),
        "source calendar identity mismatch",
    )
    year = pd.to_numeric(selected.forecast_year, errors="raise")
    base.require(year.notna().all() and year.eq(np.floor(year)).all(), "invalid forecast year")
    selected["forecast_year"] = year.astype(int)
    periods = pd.to_datetime(selected.forecast_period, errors="raise")
    base.require(
        periods.dt.year.eq(selected.forecast_year).all()
        and periods.dt.month.eq(12).all()
        and periods.dt.day.eq(31).all(),
        "forecast period mismatch",
    )
    keys = ["survey_month", "forecast_year", "statistic"]
    base.require(not selected.duplicated(keys).any(), "duplicate selected row")
    selected["value"] = pd.to_numeric(selected.value, errors="coerce")
    lookup = selected.set_index(keys).value.to_dict()
    d["previous_survey_month"] = d.survey_month.shift(1)
    d["previous_available_at_utc"] = d.available_at.shift(1)
    d["forecast_year"] = d.survey_month.dt.year + 1
    for prefix, month_col in (("current", "survey_month"), ("previous", "previous_survey_month")):
        for stat in s["statistics"]:
            d[prefix + "_" + stat] = [
                lookup.get((month, int(year), stat), np.nan)
                for month, year in zip(d[month_col], d.forecast_year, strict=True)
            ]
        lower, upper = d[prefix + "_p25"], d[prefix + "_p75"]
        with np.errstate(over="ignore", invalid="ignore"):
            width = upper - lower
        valid = np.isfinite(lower) & np.isfinite(upper) & upper.ge(lower) & np.isfinite(width)
        d[prefix + "_observed"] = valid
        d[prefix + "_iqr"] = width.where(valid)
    d["ready"] = (
        d.current_observed & d.previous_observed & d.previous_available_at_utc.lt(d.available_at)
    )
    d["iqr_change"] = (d.current_iqr - d.previous_iqr).where(d.ready)
    d["contraction"] = d.ready & d.iqr_change.lt(0.0)
    d["primary_direction"] = d.contraction.astype(float)
    d["control_direction"] = d.ready.astype(float)
    d["source_date"] = (
        d.available_at.dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    )
    d["available_at_utc"] = d.available_at
    d["asset_code"] = "MIX"
    d["provider_url"] = cfg["source"]["source_url"]
    # Fragment is a derived release identifier for evidence/counts, not another HTTP resource.
    d["source_url"] = d.provider_url + "#survey=" + d.survey_month.dt.strftime("%Y-%m")
    d["original_receipt_verified"] = False
    return d


def preflight(cfg, parent, storage=STORAGE):
    source = cfg["source"]
    root = base.safe(storage, source["root"])
    base.require(base.sha(root / "manifest.json") == source["manifest_sha256"], "manifest drift")
    manifest = prior.read_json(root / "manifest.json")
    for item in manifest["artifacts"].values():
        p = base.safe(root, item["path"])
        base.require(
            p.stat().st_size == item["bytes"] and base.sha(p) == item["sha256"], "source drift"
        )
    sem = manifest["temporal_semantics"]
    base.require(
        sem["development_backtest_admissible"] is True
        and sem["contains_prices_returns_targets_labels_or_pnl"] is False
        and sem["current_vintage_historical_record"] is True
        and sem["original_historical_workbook_vintages_available"] is False,
        "admission drift",
    )
    for key, value in source["processed"].items():
        base.require(manifest["artifacts"]["processed"][key] == value, "declaration drift")
    path = root / source["processed"]["path"]
    pf = pq.ParquetFile(path)
    base.require(
        pf.metadata.num_rows == source["processed"]["rows"]
        and set(source["allowed_columns"]) <= set(pf.schema_arrow.names),
        "source schema/count drift",
    )
    meta = clocks(pd.read_parquet(path, columns=source["metadata_columns"]), metadata=True)
    eligible = calendar(meta)
    base.require(
        str(meta.survey_month.min().date()) == source["minimum_survey_month"]
        and str(meta.survey_month.max().date()) == source["maximum_survey_month"]
        and meta.available_at.max() == pd.Timestamp(source["maximum_available_at"])
        and meta.survey_month.nunique() == source["survey_months"]
        and len(eligible) == source["eligible_survey_months"],
        "source date bounds drift",
    )
    return {"source": source, "futures": base.preflight(parent, storage), "all_true": True}


def read_source(cfg, storage=STORAGE):
    source = cfg["source"]
    path = base.safe(storage, source["root"]) / source["processed"]["path"]
    meta = pd.read_parquet(path, columns=source["metadata_columns"])
    eligible = calendar(meta)
    # Arrow predicate excludes unavailable2026 survey VALUES before materialization.
    raw = pd.read_parquet(
        path,
        columns=source["allowed_columns"],
        filters=[
            ("available_at", "<", base.BOUNDARY.tz_localize("UTC")),
            ("indicator", "==", cfg["signal"]["indicator"]),
            ("statistic", "in", cfg["signal"]["statistics"]),
        ],
    )
    return raw, eligible


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V105 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V105 file drift")
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
    state = states(*read_source(cfg), cfg)
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
        "observed_current_iqr_rows": int(state.current_observed.sum()),
        "ready_source_rows": int(state.ready.sum()),
        "contraction_source_rows": int(state.contraction.sum()),
        "original_receipt_verified": False,
    }
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "survey_dispersion")
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
