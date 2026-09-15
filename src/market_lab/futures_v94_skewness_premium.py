"""One monthly skewness-preference screen; unchanged V64 portfolio execution."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v64_si_tax_calendar as base
from market_lab import futures_v68_reported_option_flow as report

CONFIG = base.PROJECT / "configs/v94_skewness_premium_v1.json"
SEAL = base.PROJECT / "configs/v94_skewness_premium_v1.seal.json"
ASSETS = ("BR", "MIX", "RI", "SI")


def mapping(active):
    frame = active.loc[active.asset_code.isin(ASSETS), base.ACTIVE_COLS].copy()
    for col in ("decision_date", "effective_date", "observed_through"):
        frame[col] = pd.to_datetime(frame[col], errors="raise")
    base.require(not frame.empty and frame.effective_date.notna().all()
                 and frame.effective_date.lt(base.BOUNDARY).all(), "invalid/protected map")
    base.require(not frame.duplicated(["effective_date", "asset_code"]).any(), "duplicate map")
    base.require(frame.groupby("effective_date").asset_code.nunique().eq(4).all(),
                 "incomplete four-asset calendar")
    known = frame.loc[frame.decision_date.notna()]
    base.require((known.observed_through <= known.decision_date).all()
                 and (known.decision_date < known.effective_date).all(), "noncausal map")
    return frame.sort_values(["effective_date", "asset_code"], ignore_index=True)


def features(active, observations, cfg):
    """Each return uses two adjacent closes of ONE preselected exact contract."""
    frame = mapping(active)
    raw = observations.loc[observations.logical_asset.isin(ASSETS),
                           ["trade_date", "logical_asset", "canonical_contract_id",
                            "close", "volume"]].copy()
    raw["trade_date"] = pd.to_datetime(raw.trade_date, errors="raise")
    base.require(raw.trade_date.notna().all() and raw.trade_date.lt(base.BOUNDARY).all(),
                 "invalid/protected observations")
    keys = ["trade_date", "logical_asset", "canonical_contract_id"]
    base.require(not raw.duplicated(keys).any(), "duplicate observation")
    raw = raw.rename(columns={"logical_asset": "asset_code",
                              "canonical_contract_id": "contract_id"})
    for label, day in (("current", "effective_date"), ("previous", "decision_date")):
        renamed = raw.rename(columns={"trade_date": day, "close": label + "_close",
                                      "volume": label + "_volume"})
        frame = frame.merge(renamed, on=[day, "asset_code", "contract_id"],
                            how="left", validate="many_to_one")
    calendar = pd.Series(sorted(frame.effective_date.unique()))
    predecessor = dict(zip(calendar.iloc[1:], calendar.iloc[:-1], strict=True))
    adjacent = frame.decision_date.eq(frame.effective_date.map(predecessor))
    columns = ["current_close", "previous_close", "current_volume", "previous_volume"]
    numbers = frame[columns].apply(pd.to_numeric, errors="coerce").astype(float)
    valid = (adjacent & frame.plan_tradable.eq(True) & frame.contract_id.notna()
             & np.isfinite(numbers).all(axis=1) & numbers.gt(0).all(axis=1))
    frame["same_contract_return"] = (
        numbers.current_close / numbers.previous_close - 1.0).where(valid)
    frame["return_observed"] = valid
    window = cfg["signal"]["lookback_sessions"]
    group = frame.groupby("asset_code", sort=False).same_contract_return
    frame["window_count"] = group.transform(lambda s: s.rolling(window).count())
    frame["skewness"] = group.transform(lambda s: s.rolling(window, min_periods=window).skew())
    deviation = group.transform(lambda s: s.rolling(window, min_periods=window).std())
    frame.loc[~np.isfinite(frame.skewness) | deviation.le(1e-12), "skewness"] = np.nan
    return frame


def targets(active, feature, cfg):
    plan = mapping(active)
    plan = plan.loc[plan.decision_date.notna()].copy()
    wide = feature.pivot(index="effective_date", columns="asset_code", values="skewness")
    base.require(set(wide.columns) == set(ASSETS), "feature universe drift")
    weights, last_month, chosen_at, ready = dict.fromkeys(ASSETS, 0.0), None, pd.NaT, False
    rows = []
    for day, part in plan.groupby("decision_date", sort=True):
        base.require(set(part.asset_code) == set(ASSETS)
                     and part.effective_date.nunique() == 1, "incomplete decision calendar")
        month = day.to_period("M")
        rebalance = month != last_month
        if rebalance:
            last_month, chosen_at = month, day
            values = wide.loc[day].reindex(ASSETS) if day in wide.index else pd.Series(dtype=float)
            ready = len(values) == 4 and bool(np.isfinite(values).all())
            weights = dict.fromkeys(ASSETS, 0.0)
            if ready:
                low, high = values.min(), values.max()
                ready = bool(low < high and values.eq(low).sum() == 1
                             and values.eq(high).sum() == 1)
                if ready:
                    weights[values.idxmin()] = cfg["execution"]["weight_per_leg"]
                    weights[values.idxmax()] = -cfg["execution"]["weight_per_leg"]
        for row in part.to_dict("records"):
            row.update(selection_date=chosen_at, monthly_rebalance=rebalance,
                       feature_unavailable=not ready, requested_weight=weights[row["asset_code"]])
            row["source_unavailable"] = not (row["plan_tradable"] is True
                                               and pd.notna(row["contract_id"]))
            row["stale_at_fill"] = ((row["effective_date"] - day).days
                                    > cfg["signal"]["maximum_fill_gap_calendar_days"])
            row["target_weight"] = (row["requested_weight"] if not (
                row["source_unavailable"] or row["stale_at_fill"]) else 0.0)
            rows.append(row)
    result = pd.DataFrame(rows)
    result = result.loc[result.effective_date.between(cfg["period"]["start"],
                                                     cfg["period"]["end"])].copy()
    base.require(not result.empty, "empty evaluation calendar")
    result["terminal_flat"] = result.effective_date.eq(result.effective_date.max())
    result.loc[result.terminal_flat, "target_weight"] = 0.0
    result.loc[result.target_weight.eq(0), "contract_id"] = None
    result["provenance"] = "v94_prior126_same_contract_returns_monthly_low_minus_high_skew"
    result = result.sort_values(["effective_date", "asset_code"], ignore_index=True)
    control = result.copy()
    control[["requested_weight", "target_weight"]] *= -1.0
    control["provenance"] = "v94_predeclared_mirror_not_promotable"
    return {"primary": result, "control": control}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V94 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V94 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["assets"] == list(ASSETS) and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"]
                 and cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "scope drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def run(cfg, parent, storage, expected):
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    output = base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing run; never repeat or overwrite")
    verified = base.preflight(parent, storage)
    output.mkdir(exist_ok=False)
    base.write_json(output / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    base.write_json(output / "inputs.json", verified)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(storage, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    observations = pd.read_parquet(base.safe(storage, declared["observations"]["path"]),
                                   columns=base.OBS_COLS)
    specs = pd.read_parquet(base.safe(storage, declared["specs"]["path"]),
                            columns=sorted(base.SPEC_PROXY_COLUMNS))
    feature = features(active, observations, cfg)
    feature.to_parquet(output / "features.parquet", index=False)
    signals = targets(active, feature, cfg)
    primary = signals["primary"]
    quality = {"ready_asset_date_fraction": float((~primary.feature_unavailable).mean()),
               "monthly_decisions": int(primary.loc[primary.monthly_rebalance,
                                                      "decision_date"].nunique()),
               "ready_monthly_decisions": int(primary.loc[primary.monthly_rebalance
                   & ~primary.feature_unavailable, "decision_date"].nunique()),
               "source_return_rows": len(feature),
               "observed_same_contract_returns": int(feature.return_observed.sum())}
    market = base.build_portfolio_market(observations.rename(columns={
        "trade_date": "session_date", "logical_asset": "asset_code",
        "canonical_contract_id": "contract_id"}), specs)
    market = market.loc[pd.to_datetime(market.session_date).between(
        cfg["period"]["start"], primary.effective_date.max())]
    metrics, counts = {}, {}
    for arm, signal in signals.items():
        signal.to_parquet(output / ("targets_" + arm + ".parquet"), index=False)
        counts[arm] = {"decisions": len(signal),
                       "nonzero_targets": int(signal.target_weight.ne(0).sum()),
                       **{c: int(signal[c].sum()) for c in (
                           "feature_unavailable", "source_unavailable", "stale_at_fill")}}
        metrics[arm] = {}
        for cost, (ticks, fee) in cfg["execution"]["costs"].items():
            result = base.run_futures_portfolio_ledger(market, signal,
                base.FuturesPortfolioLedgerConfig(
                    initial_cash=base.CAPITAL, expected_assets=ASSETS,
                    maximum_gross_notional_multiple=cfg["execution"]["maximum_gross_multiple"],
                    initial_margin_buffer_multiplier=cfg["execution"]["margin_buffer"],
                    maximum_participation=cfg["execution"]["maximum_participation"],
                    slippage_ticks=ticks, fee_multiplier=fee, execution_atomicity="asset",
                    unexecutable_target_policy="cancel_and_clip"))
            metrics[arm][cost] = report.summarize(result)
            for kind in ("ledger", "orders", "positions"):
                getattr(result, kind).to_parquet(
                    output / f"{kind}_{arm}_{cost}.parquet", index=False)
            print(json.dumps({"completed_arm": arm, "cost": cost}), flush=True)
    payload = {"protocol_id": cfg["protocol_id"], "seal_sha256": expected,
               "completed_at_utc": datetime.now(UTC).isoformat(), "status": "COMPLETE",
               "metrics": metrics, "counts": counts, "source_quality": quality,
               "assessment": report.assess(metrics, quality, cfg),
               "limitations": cfg["limitations"], "goal_verified": False}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "manifest.json", {"status": "COMPLETE", "seal_sha256": expected,
        "completed_at_utc": payload["completed_at_utc"], "files": {
            p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()}})
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)
    return output


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, Path("/srv/trading_lab_data"), args.seal_sha)


if __name__ == "__main__":
    main()
