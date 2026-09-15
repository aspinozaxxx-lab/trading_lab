"""Fixed monthly low-beta premium; reuse the existing four-arm daily simulator."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v78_treasury_channels as engine
from market_lab import futures_v94_skewness_premium as mapping_tools

base = engine.base
ASSETS = ("BR", "MIX", "RI", "SI")
CONFIG = base.PROJECT / "configs/v95_beta_premium_v1.json"
SEAL = base.PROJECT / "configs/v95_beta_premium_v1.seal.json"


def features(active, observations, cfg):
    """No skewness computation: exact adjacent returns, then trailing covariance."""
    frame = mapping_tools.mapping(active)
    raw = observations.loc[observations.logical_asset.isin(ASSETS),
                           ["trade_date", "logical_asset", "canonical_contract_id",
                            "close", "volume"]].copy()
    raw["trade_date"] = pd.to_datetime(raw.trade_date, errors="raise")
    base.require(raw.trade_date.notna().all() and raw.trade_date.lt(base.BOUNDARY).all(),
                 "invalid/protected observations")
    base.require(not raw.duplicated(
        ["trade_date", "logical_asset", "canonical_contract_id"]).any(), "duplicate prices")
    raw = raw.rename(columns={"logical_asset": "asset_code",
                              "canonical_contract_id": "contract_id"})
    for label, day in (("current", "effective_date"), ("previous", "decision_date")):
        frame = frame.merge(raw.rename(columns={"trade_date": day,
            "close": label + "_close", "volume": label + "_volume"}),
            on=[day, "asset_code", "contract_id"], how="left", validate="many_to_one")
    calendar = pd.Series(sorted(frame.effective_date.unique()))
    predecessor = dict(zip(calendar.iloc[1:], calendar.iloc[:-1], strict=True))
    numbers = frame[["current_close", "previous_close", "current_volume", "previous_volume"]]
    numbers = numbers.apply(pd.to_numeric, errors="coerce").astype(float)
    valid = (frame.decision_date.eq(frame.effective_date.map(predecessor))
             & frame.plan_tradable.eq(True) & frame.contract_id.notna()
             & np.isfinite(numbers).all(axis=1) & numbers.gt(0).all(axis=1))
    frame["return_observed"] = valid
    frame["same_contract_return"] = (
        numbers.current_close / numbers.previous_close - 1.0).where(valid)
    wide = frame.pivot(index="effective_date", columns="asset_code",
                       values="same_contract_return").reindex(columns=ASSETS)
    factor = wide.mean(axis=1, skipna=False)
    window = cfg["signal"]["lookback_sessions"]
    variance = factor.rolling(window, min_periods=window).var(ddof=1)
    beta = pd.DataFrame(index=wide.index)
    for asset in ASSETS:
        beta[asset] = wide[asset].rolling(window, min_periods=window).cov(factor) / variance
    beta.loc[~np.isfinite(variance) | variance.le(1e-24), :] = np.nan
    beta = beta.replace([np.inf, -np.inf], np.nan)
    beta["factor_variance"] = variance
    beta["complete_return_count"] = factor.rolling(window).count()
    return frame, beta.reset_index()


def allocation(values, cfg):
    """Positive-beta extreme pair only; normalize inverse-beta legs to fixed gross."""
    primary, control = dict.fromkeys(ASSETS, 0.0), dict.fromkeys(ASSETS, 0.0)
    base.require(set(values.index) == set(ASSETS) and not values.index.duplicated().any(),
                 "beta universe drift")
    if len(values) != 4 or not np.isfinite(values).all():
        return primary, control, "incomplete_beta_window"
    eligible = values.loc[values.gt(0)]
    if len(eligible) < 2:
        return primary, control, "fewer_than_two_positive_betas"
    lo, hi = eligible.min(), eligible.max()
    if not (lo < hi and eligible.eq(lo).sum() == 1 and eligible.eq(hi).sum() == 1):
        return primary, control, "tied_extreme_betas"
    low_asset, high_asset = eligible.idxmin(), eligible.idxmax()
    gross = cfg["execution"]["maximum_signal_gross"]
    # Stable ratio avoids an unbounded raw 1 / beta notional for beta near zero.
    ratio = lo / hi
    primary[low_asset] = gross / (1.0 + ratio)
    primary[high_asset] = -gross * ratio / (1.0 + ratio)
    control[low_asset], control[high_asset] = gross / 2.0, -gross / 2.0
    return primary, control, "ready"


def targets(active, beta, cfg):
    plan = mapping_tools.mapping(active)
    plan = plan.loc[plan.decision_date.notna()]
    table = beta.set_index("effective_date")
    table.index = pd.to_datetime(table.index)
    base.require(not table.index.duplicated().any(), "duplicate beta date")
    base.require(table.index.notna().all() and (table.index < base.BOUNDARY).all(),
                 "invalid/protected beta date")
    result = {"primary": [], "control": []}
    weights, last_month, selected_at, reason = {}, None, pd.NaT, "incomplete_beta_window"
    selected_beta = pd.Series(np.nan, index=ASSETS)
    for day, part in plan.groupby("decision_date", sort=True):
        base.require(set(part.asset_code) == set(ASSETS)
                     and part.effective_date.nunique() == 1, "incomplete decision calendar")
        month = day.to_period("M")
        rebalance = month != last_month
        if rebalance:
            last_month, selected_at = month, day
            selected_beta = (table.loc[day, list(ASSETS)] if day in table.index
                             else pd.Series(np.nan, index=ASSETS))
            p, c, reason = allocation(selected_beta, cfg)
            weights = {"primary": p, "control": c}
        for record in part.to_dict("records"):
            asset = record["asset_code"]
            for arm in result:
                row = dict(record)
                row.update(selection_date=selected_at, source_date=selected_at,
                    source_url="local:moex_core4_beta252:" + str(selected_at.date()),
                    monthly_rebalance=rebalance, selection_reason=reason,
                    selected_beta=selected_beta[asset], feature_unavailable=reason != "ready",
                    requested_weight=weights[arm][asset])
                row["source_unavailable"] = not (row["plan_tradable"] is True
                                                   and pd.notna(row["contract_id"]))
                row["stale_at_fill"] = ((row["effective_date"] - day).days
                                        > cfg["signal"]["maximum_fill_gap_calendar_days"])
                row["target_weight"] = (row["requested_weight"] if not (
                    row["source_unavailable"] or row["stale_at_fill"]) else 0.0)
                result[arm].append(row)
    for arm, rows in result.items():
        frame = pd.DataFrame(rows)
        frame = frame.loc[frame.effective_date.between(cfg["period"]["start"],
                                                       cfg["period"]["end"])].copy()
        base.require(not frame.empty, "empty evaluation calendar")
        frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
        frame.loc[frame.terminal_flat, "target_weight"] = 0.0
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        frame["provenance"] = "v95_low_beta_" + arm
        result[arm] = frame.sort_values(["effective_date", "asset_code"], ignore_index=True)
    return result


def load(expected):
    base.require(base.sha(SEAL) == expected, "V95 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V95 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["assets"] == list(ASSETS) and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"]
                 and cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "scope drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def run(cfg, parent, storage, expected):
    base.require(os.name == "posix" and os.getuid() == 999
                 and storage.resolve() == Path("/srv/trading_lab_data"), "server service only")
    output = base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing canonical; no rerun or overwrite")
    verified = base.preflight(parent, storage)
    output.mkdir(exist_ok=False)
    base.write_json(output / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    base.write_json(output / "inputs.json", verified)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(storage, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    obs = pd.read_parquet(base.safe(storage, declared["observations"]["path"]),
                          columns=["trade_date", "logical_asset", "canonical_contract_id",
                                   "close", "volume"])
    returns, beta = features(active, obs, cfg)
    returns.to_parquet(output / "exact_returns.parquet", index=False)
    beta.to_parquet(output / "beta_states.parquet", index=False)
    signals = targets(active, beta, cfg)
    p = signals["primary"]
    monthly = p.loc[p.monthly_rebalance].drop_duplicates("decision_date")
    quality = {"ready_asset_date_fraction": float((~p.feature_unavailable).mean()),
        "monthly_decisions": len(monthly),
        "ready_monthly_decisions": int((~monthly.feature_unavailable).sum()),
        "monthly_reason_counts": {str(k): int(v) for k, v in
                                   monthly.selection_reason.value_counts().items()},
        "source_return_rows": len(returns),
        "observed_same_contract_returns": int(returns.return_observed.sum())}
    market = engine.market_inputs(storage, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "beta_premium")
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"], "seal_sha256": expected,
        "completed_at_utc": datetime.now(UTC).isoformat(), "case": case,
        "limitations": cfg["limitations"], "goal_verified": False}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "manifest.json", {"status": "COMPLETE", "seal_sha256": expected,
        "completed_at_utc": payload["completed_at_utc"], "files": {
            str(p.relative_to(output)): base.sha(p) for p in sorted(output.rglob("*"))
            if p.is_file()}})
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)
    return output


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, Path("/srv/trading_lab_data"), args.seal_sha)


if __name__ == "__main__":
    main()
