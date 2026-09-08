"""Small no-fit strategy contest using existing manifests and portfolio accounting."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v64_si_tax_calendar as base

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT / "configs/v65_fast_calendar_contest_v1.json"
SEAL = PROJECT / "configs/v65_fast_calendar_contest_v1.seal.json"
ARMS = ("primary", "control")


def load(expected):
    base.require(base.sha(SEAL) == expected, "contest seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(PROJECT, name)) == digest, "contest file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg, parent


def targets(active, hypothesis, arm):
    base.require(arm in ARMS, "undeclared arm")
    frame = active.loc[active.asset_code.eq(hypothesis["asset"]), base.ACTIVE_COLS].copy()
    for name in ("decision_date", "effective_date", "observed_through"):
        frame[name] = pd.to_datetime(frame[name])
    frame = (
        frame.loc[frame.decision_date.notna()].sort_values("effective_date").reset_index(drop=True)
    )
    base.require(not frame.empty, "missing asset map")
    base.require((frame.decision_date < frame.effective_date).all(), "noncausal execution")
    base.require((frame.observed_through <= frame.decision_date).all(), "future map")
    base.require(frame.effective_date.lt(base.BOUNDARY).all(), "protected date")
    base.require(not frame.effective_date.duplicated().any(), "duplicate map")
    day, fill = frame.decision_date.dt, frame.effective_date.dt
    name = hypothesis["id"]
    if name == "ri_month_turn":
        if arm == "primary":
            requested = day.day.le(4) | day.day.ge(day.days_in_month - 2)
            valid_at_fill = fill.day.le(4) | fill.day.ge(fill.days_in_month - 2)
        else:
            requested, valid_at_fill = day.day.between(12, 18), fill.day.between(12, 18)
    elif name == "br_midweek_report":
        weekdays = (0, 1) if arm == "primary" else (2, 3)
        requested = day.dayofweek.isin(weekdays)
        valid_at_fill = fill.dayofweek.eq(day.dayofweek + 1)
    elif name == "si_weekend_hedge":
        weekday = 3 if arm == "primary" else 0
        requested = day.dayofweek.eq(weekday)
        valid_at_fill = fill.dayofweek.eq(weekday + 1)
    elif name == "br_after_roll":
        groups = frame["roll"].fillna(False).astype(bool).cumsum()
        age = frame.groupby(groups).cumcount()
        lo, hi = (1, 5) if arm == "primary" else (11, 15)
        requested = groups.gt(0) & age.between(lo, hi)
        valid_at_fill = pd.Series(True, index=frame.index)
    else:
        raise ValueError("undeclared hypothesis")
    tradable = frame.plan_tradable.fillna(False).astype(bool) & frame.contract_id.notna()
    frame["requested_weight"] = requested.astype(float)
    frame["source_unavailable"] = requested & ~tradable
    frame["stale_at_fill"] = requested & ~valid_at_fill
    frame["target_weight"] = (requested & tradable & valid_at_fill).astype(float)
    frame["terminal_flat"] = False
    frame.loc[frame.index[-1], ["target_weight", "terminal_flat"]] = [0.0, True]
    frame.loc[frame.target_weight.eq(0), "contract_id"] = None
    frame["provenance"] = f"v65_{name}_{arm}_calendar_only"
    return frame


def assess(eras, gates):
    checks = {
        "complete_and_flat": all(
            m["execution_complete"] and not m["terminal_carried"]
            for arms in eras.values()
            for costs in arms.values()
            for m in costs.values()
        ),
        "enough_trades": all(
            v["primary"]["primary"]["round_trips"] >= gates["minimum_primary_round_trips_each_era"]
            for v in eras.values()
        ),
        "positive_each_era": all(
            v["primary"]["doubled"]["total_return"] > 0 for v in eras.values()
        ),
        "positive_years": all(
            v["primary"]["doubled"]["positive_years"] / v["primary"]["doubled"]["year_segments"]
            >= gates["minimum_positive_year_fraction_each_era"]
            for v in eras.values()
        ),
        "beats_control": sum(
            v["primary"]["doubled"]["cagr"] > v["control"]["doubled"]["cagr"] for v in eras.values()
        )
        >= gates["minimum_eras_beating_control_doubled_cagr"],
        "drawdown": all(
            abs(v["primary"]["doubled"]["maximum_drawdown"]) <= gates["maximum_drawdown_each_era"]
            for v in eras.values()
        ),
    }
    recent = eras["recent"]["primary"]["doubled"]
    checks["recent_cagr"] = recent["cagr"] >= gates["minimum_recent_doubled_cagr"]
    checks["recent_sharpe"] = recent["sharpe"] >= gates["minimum_recent_doubled_sharpe"]
    return {
        "stage": 1,
        "verdict": "STAGE2_CANDIDATE" if all(checks.values()) else "REJECT_STAGE1",
        "failed_gates": [key for key, passed in checks.items() if not passed],
        "checks": checks,
        "historical_20_each_era": checks["complete_and_flat"]
        and all(v["primary"]["doubled"]["cagr"] >= 0.20 for v in eras.values()),
        "historical_50_each_era": checks["complete_and_flat"]
        and all(v["primary"]["doubled"]["cagr"] >= 0.50 for v in eras.values()),
        "goal_verified": False,
    }


def run(cfg, parent, storage, expected):
    base.require(os.name == "posix", "economics runs on GPU server only")
    output = base.safe(storage, "runs/v65_fast_calendar_contest_v1_" + expected[:12])
    base.require(not output.exists(), "existing run; do not repeat")
    verified = base.preflight(parent, storage)
    output.mkdir(parents=True, exist_ok=False)
    base.write_json(output / "inputs.json", verified)
    declarations = base.declarations(parent)
    metrics = {row["id"]: {} for row in cfg["hypotheses"]}
    counts = {row["id"]: {} for row in cfg["hypotheses"]}
    for era in parent["eras"]:
        declared = declarations[era["id"]]
        active = pd.read_parquet(
            base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
        )
        obs = pd.read_parquet(
            base.safe(storage, declared["observations"]["path"]), columns=base.OBS_COLS
        )
        specs = pd.read_parquet(
            base.safe(storage, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
        )
        markets = {}
        for asset in {row["asset"] for row in cfg["hypotheses"]}:
            selected = obs.loc[obs.logical_asset.eq(asset)].rename(
                columns={
                    "trade_date": "session_date",
                    "logical_asset": "asset_code",
                    "canonical_contract_id": "contract_id",
                }
            )
            markets[asset] = base.build_portfolio_market(
                selected, specs.loc[specs.asset_symbol.eq(asset)]
            )
        for hypothesis in cfg["hypotheses"]:
            name = hypothesis["id"]
            metrics[name][era["id"]], counts[name][era["id"]] = {}, {}
            for arm in ARMS:
                signal = targets(active, hypothesis, arm)
                market = markets[hypothesis["asset"]]
                market = market.loc[
                    pd.to_datetime(market.session_date).le(signal.effective_date.max())
                ]
                prefix = f"{name}_{era['id']}_{arm}"
                signal.to_parquet(output / f"targets_{prefix}.parquet", index=False)
                counts[name][era["id"]][arm] = {
                    "decisions": len(signal),
                    "nonzero": int(signal.target_weight.ne(0).sum()),
                    "unavailable": int(signal.source_unavailable.sum()),
                    "stale": int(signal.stale_at_fill.sum()),
                }
                metrics[name][era["id"]][arm] = {}
                for cost, (ticks, fee) in cfg["execution"]["costs"].items():
                    result = base.run_futures_portfolio_ledger(
                        market,
                        signal,
                        base.FuturesPortfolioLedgerConfig(
                            initial_cash=base.CAPITAL,
                            expected_assets=(hypothesis["asset"],),
                            slippage_ticks=ticks,
                            fee_multiplier=fee,
                            execution_atomicity="asset",
                            unexecutable_target_policy="cancel_and_clip",
                        ),
                    )
                    values = base.summarize(result)
                    # Independent small accounting check, not another run of the strategy.
                    replay = base._performance_metrics(
                        result.ledger.ending_cash, result.ledger.session_date, base.CAPITAL
                    )
                    base.require(
                        all(np.isclose(values[k], v) for k, v in replay.items()),
                        "metrics replay mismatch",
                    )
                    metrics[name][era["id"]][arm][cost] = values
                    for kind in ("ledger", "orders", "positions"):
                        getattr(result, kind).to_parquet(
                            output / f"{kind}_{prefix}_{cost}.parquet", index=False
                        )
                    print(json.dumps({"completed": prefix, "costs": cost}), flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "stage": 1,
        "metrics": metrics,
        "counts": counts,
        "assessment": {name: assess(eras, cfg["screen_gates"]) for name, eras in metrics.items()},
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": expected,
            "files": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    args = parser.parse_args()
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
