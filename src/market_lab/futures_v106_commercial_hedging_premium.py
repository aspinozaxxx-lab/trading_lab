"""One commercial net-risk-supply premium screen; existing source and daily ledger."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from fractions import Fraction

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v101_manufacturing_demand as prior
from market_lab.futures.cftc_radar import official_development_release_overrides

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v106_commercial_hedging_premium_v1.json"
SEAL = base.PROJECT / "configs/v106_commercial_hedging_premium_v1.seal.json"
NUMBERS = ["open_interest", "producer_long", "producer_short"]


def report_clock(day):
    dates = [day + pd.Timedelta(days=7)]
    official = official_development_release_overrides().get(day.date())
    if official is not None:
        dates.append(official.tz_convert("America/New_York").tz_localize(None).normalize())
    return (
        (max(dates) + pd.Timedelta(days=1)).tz_localize("America/New_York")
        - pd.Timedelta(seconds=1)
    ).tz_convert("UTC")


def metadata(cfg, storage=STORAGE):
    s = cfg["source"]
    p = base.safe(storage, s["root"]) / s["processed"]["file"]
    d = pd.read_parquet(p, columns=s["metadata_columns"])
    d["report_date"] = pd.to_datetime(d.report_date, errors="raise")
    base.require(
        d.report_date.notna().all()
        and d.report_date.lt(base.BOUNDARY).all()
        and d.report_date.eq(d.report_date.dt.normalize()).all()
        and d.source_archive_year.eq(d.report_date.dt.year).all()
        and not d.duplicated(["logical_market", "report_date"]).any(),
        "source metadata dates",
    )
    w = d.loc[d.logical_market.eq("WTI")].sort_values("report_date", ignore_index=True)
    base.require(
        len(w) == s["wti_rows"]
        and w.cftc_contract_market_code.eq("067651").all()
        and w.contract_units.eq(s["contract_units"]).all()
        and str(d.report_date.min().date()) == s["minimum_report_date"]
        and str(d.report_date.max().date()) == s["maximum_report_date"],
        "WTI identity/date bounds",
    )
    w["report_available_at_utc"] = w.report_date.map(report_clock)
    return w


def preflight(cfg, parent, storage=STORAGE):
    s = cfg["source"]
    r = base.safe(storage, s["root"])
    for name, key in (("manifest.json", "manifest_sha256"), ("audit.json", "audit_sha256")):
        base.require(base.sha(r / name) == s[key], "source manifest/audit drift")
    manifest = prior.read_json(r / "manifest.json")
    base.require(
        manifest["protocol_sha256"] == s["protocol_sha256"]
        and manifest["source_only"]
        and not manifest["contains_moex_price_return_target_signal_trade_or_pnl"],
        "source admission drift",
    )
    for kind in ("processed", "raw"):
        item = s[kind]
        base.require(
            all(manifest[kind][k] == v for k, v in item.items()), "source declaration drift"
        )
        p = base.safe(r, item["file"])
        base.require(
            p.stat().st_size == item["bytes"] and base.sha(p) == item["sha256"], "source drift"
        )
    pf = pq.ParquetFile(r / s["processed"]["file"])
    base.require(
        pf.metadata.num_rows == s["processed"]["rows"]
        and set(s["allowed_columns"]) <= set(pf.schema_arrow.names),
        "schema drift",
    )
    d = metadata(cfg, storage)
    return {
        "source": s,
        "eligible_wti_reports": int(d.report_available_at_utc.lt("2026-01-01").sum()),
        "futures": base.preflight(parent, storage),
        "all_true": True,
    }


def read_source(cfg, storage=STORAGE):
    d = metadata(cfg, storage)
    dates = d.loc[d.report_available_at_utc.lt("2026-01-01"), "report_date"].tolist()
    s = cfg["source"]
    return pd.read_parquet(
        base.safe(storage, s["root"]) / s["processed"]["file"],
        columns=s["allowed_columns"],
        filters=[("logical_market", "==", "WTI"), ("report_date", "in", dates)],
    )


def states(raw, cfg):
    d = raw.loc[:, cfg["source"]["allowed_columns"]].copy()
    d["source_date"] = pd.to_datetime(d.report_date, errors="raise")
    d = d.sort_values("source_date", ignore_index=True)
    base.require(
        not d.empty
        and d.source_date.notna().all()
        and d.source_date.between("2018-01-01", "2025-12-31").all()
        and d.source_date.eq(d.source_date.dt.normalize()).all()
        and not d.source_date.duplicated().any(),
        "invalid/protected/duplicate dates",
    )
    base.require(
        d.logical_market.eq("WTI").all()
        and d.cftc_contract_market_code.eq("067651").all()
        and d.contract_units.eq(cfg["source"]["contract_units"]).all(),
        "WTI identity",
    )
    d["report_available_at_utc"] = d.source_date.map(report_clock)
    base.require(d.report_available_at_utc.lt("2026-01-01").all(), "protected numeric availability")
    numbers = d[NUMBERS].apply(pd.to_numeric, errors="coerce").astype(float)
    valid = (
        np.isfinite(numbers).all(axis=1)
        & numbers.ge(0).all(axis=1)
        & numbers.le(2**53 - 1).all(axis=1)
        & numbers.eq(np.floor(numbers)).all(axis=1)
        & numbers.open_interest.gt(0)
        & numbers.producer_long.le(numbers.open_interest)
        & numbers.producer_short.le(numbers.open_interest)
    )
    d["position_values_valid"] = valid
    count = cfg["signal"]["baseline_reports"]
    base.require(count == 52, "undeclared baseline")
    gaps = d.source_date.diff().dt.days.rolling(count).max()
    span = (d.source_date - d.source_date.shift(count)).dt.days
    d["ready"] = (
        valid.rolling(count + 1).sum().eq(count + 1)
        & gaps.le(cfg["signal"]["maximum_report_gap_calendar_days"])
        & span.le(cfg["signal"]["maximum_window_calendar_days"])
    )
    fractions = [
        Fraction(int(row.producer_short) - int(row.producer_long), int(row.open_interest))
        if good
        else None
        for row, good in zip(numbers.itertuples(index=False), valid, strict=True)
    ]
    medians, directions = [], []
    for i, ready in enumerate(d.ready):
        if not ready:
            medians.append(np.nan)
            directions.append(0.0)
            continue
        ordered = sorted(fractions[i - count : i])
        median = (ordered[count // 2 - 1] + ordered[count // 2]) / 2
        medians.append(float(median))
        directions.append(float(fractions[i] > 0 and fractions[i] > median))
    d["commercial_net_short_share"] = [float(x) if x is not None else np.nan for x in fractions]
    d["prior52_median_share"] = medians
    d["primary_direction"] = directions
    d["control_direction"] = d.ready.astype(float)
    d["available_at_utc"] = pd.Series(
        [d.report_available_at_utc.iloc[max(0, i - count) : i + 1].max() for i in range(len(d))],
        dtype="datetime64[ns, UTC]",
    )
    d["baseline_latest_report_date"] = d.source_date.shift(1)
    d["baseline_rows_required"] = count
    d["source_url"] = (
        "https://www.cftc.gov/files/dea/history/fut_disagg_txt_"
        + d.source_date.dt.strftime("%Y")
        + ".zip#WTI-"
        + d.source_date.dt.strftime("%Y-%m-%d")
    )
    d["asset_code"] = "BR"
    d["original_receipt_verified"] = False
    d = d.sort_values(["available_at_utc", "source_date"], ignore_index=True)
    d["dominated_late_report"] = d.source_date.lt(d.source_date.cummax())
    return d, d.loc[~d.dominated_late_report].reset_index(drop=True)


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V106 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V106 file drift")
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
    out = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    out.mkdir(exist_ok=False)
    base.write_json(
        out / "inputs.json",
        {
            "seal_sha256": expected,
            "verified": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    reports, state = states(read_source(cfg), cfg)
    reports.to_parquet(out / "source_reports.parquet", index=False)
    state.to_parquet(out / "source_states.parquet", index=False)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = targets(active, state, cfg)
    p = signals["primary"]
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "source_report_rows": len(reports),
        "valid_position_rows": int(reports.position_values_valid.sum()),
        "ready_source_rows": int(state.ready.sum()),
        "long_source_rows": int(state.primary_direction.gt(0).sum()),
        "dominated_late_rows": int(reports.dominated_late_report.sum()),
        "original_receipt_verified": False,
    }
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(out / "case", signals, market, quality, cfg, "commercial_hedging")
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
