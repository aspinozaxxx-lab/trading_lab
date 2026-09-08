"""Four fixed OHLCV hypotheses; reuse sealed input checks and daily cash ledger."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v65_fast_calendar_contest as previous

base = previous.base
PROJECT = base.PROJECT
CONFIG = PROJECT / "configs/v66_fast_volume_contest_v1.json"
SEAL = PROJECT / "configs/v66_fast_volume_contest_v1.seal.json"
KEYS = ["decision_date", "asset_code", "contract_id"]


def load(expected):
    base.require(base.sha(SEAL) == expected, "V66 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(PROJECT, name)) == digest, "V66 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    _, parent = previous.load(cfg["parent_v65_seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    base.require(cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "capital drift")
    return cfg, parent


def features(observations, cfg):
    """Only completed same-contract daily OHLCV and strictly prior rolling references."""
    frame = observations.loc[:, base.OBS_COLS].rename(
        columns={
            "trade_date": "decision_date",
            "logical_asset": "asset_code",
            "canonical_contract_id": "contract_id",
        }
    )
    frame["decision_date"] = pd.to_datetime(frame.decision_date)
    base.require(frame.decision_date.notna().all(), "missing observation date")
    base.require(frame.decision_date.lt(base.BOUNDARY).all(), "protected observation")
    base.require(not frame.duplicated(KEYS).any(), "duplicate observation")
    parts = []
    n = cfg["features"]["prior_sessions"]
    for _, group in frame.groupby(["asset_code", "contract_id"], sort=True):
        group = group.sort_values("decision_date").copy()
        gaps = group.decision_date.diff().dt.days.gt(cfg["features"]["maximum_calendar_gap_days"])
        for _, sub in group.groupby(gaps.cumsum()):
            sub = sub.copy()
            values = sub[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric)
            valid = np.isfinite(values).all(axis=1) & values.gt(0).all(axis=1)
            valid &= values.high.ge(values[["open", "close"]].max(axis=1))
            valid &= values.low.le(values[["open", "close"]].min(axis=1))
            valid &= values.high.gt(values.low)
            body = (values.close / values.open - 1).where(valid)
            width = ((values.high - values.low) / values.open).where(valid)
            prior_sigma = body.shift(1).rolling(n, min_periods=n).std(ddof=0)
            prior_width = width.shift(1).rolling(n, min_periods=n).median()
            prior_volume = values.volume.where(valid).shift(1).rolling(n, min_periods=n).median()
            prior_high = values.high.where(valid).shift(1).rolling(n, min_periods=n).max()
            prior_low = values.low.where(valid).shift(1).rolling(n, min_periods=n).min()
            out = sub[KEYS].copy()
            out["body_z"] = body / prior_sigma.where(prior_sigma.gt(0))
            out["range_ratio"] = width / prior_width
            out["volume_ratio"] = values.volume / prior_volume
            out["close_location"] = (values.close - values.low) / (values.high - values.low)
            out["breakout"] = np.where(values.close.gt(prior_high), 1, 0) - np.where(
                values.close.lt(prior_low), 1, 0
            )
            out["ready"] = valid & np.isfinite(
                out[["body_z", "range_ratio", "volume_ratio", "close_location"]]
            ).all(axis=1)
            out["ready"] &= prior_high.notna() & prior_low.notna()
            parts.append(out)
    base.require(bool(parts), "empty observations")
    return pd.concat(parts, ignore_index=True).sort_values(KEYS, ignore_index=True)


def directions(frame, name, arm, cfg):
    base.require(arm in previous.ARMS, "unknown arm")
    p = cfg["features"]
    sign = np.sign(frame.body_z)
    extreme = ((sign > 0) & frame.close_location.ge(1 - p["close_edge_fraction"])) | (
        (sign < 0) & frame.close_location.le(p["close_edge_fraction"])
    )
    volume_ok = frame.volume_ratio.ge(p["high_volume_ratio"])
    if name == "volume_shock_reversal":
        price_ok, direction = frame.body_z.abs().ge(p["shock_body_sigma"]), -sign
    elif name == "volume_pressure_continuation":
        price_ok = frame.body_z.abs().ge(p["continuation_body_sigma"]) & extreme
        direction = sign
    elif name == "thin_breakout_fade":
        price_ok, direction = frame.breakout.ne(0), -frame.breakout
        volume_ok = frame.volume_ratio.lt(p["low_volume_ratio"])
    elif name == "compressed_volume_expansion":
        price_ok = frame.range_ratio.le(p["compressed_range_ratio"]) & extreme
        direction = sign
    else:
        raise ValueError("unknown hypothesis")
    admitted = frame.ready.fillna(False).astype(bool) & price_ok
    if arm == "primary":
        admitted &= volume_ok
    return pd.Series(np.where(admitted, direction, 0.0), index=frame.index)


def targets(active, feature_rows, name, arm, cfg):
    frames = []
    for asset in cfg["assets"]:
        frame = active.loc[active.asset_code.eq(asset), base.ACTIVE_COLS].copy()
        for key in ("decision_date", "effective_date", "observed_through"):
            frame[key] = pd.to_datetime(frame[key])
        frame = frame.loc[frame.decision_date.notna()].sort_values("effective_date")
        base.require(not frame.empty, "missing asset map")
        base.require((frame.decision_date < frame.effective_date).all(), "noncausal map")
        base.require((frame.observed_through <= frame.decision_date).all(), "future map")
        base.require(frame.effective_date.lt(base.BOUNDARY).all(), "protected map")
        base.require(not frame.effective_date.duplicated().any(), "duplicate map")
        base.require(frame.decision_date.is_monotonic_increasing, "out-of-order decisions")
        frame = frame.merge(feature_rows, on=KEYS, how="left", validate="one_to_one")
        frame = frame.sort_values("effective_date", ignore_index=True)
        frame["raw_direction"] = directions(frame, name, arm, cfg)
        contract = frame.contract_id.fillna("MISSING")
        reset = contract.ne(contract.shift(1)) | frame.decision_date.diff().dt.days.gt(
            cfg["features"]["maximum_calendar_gap_days"]
        )
        horizon = cfg["execution"]["overlapping_signal_sessions"]
        frame["requested_weight"] = (
            frame.raw_direction.groupby(reset.cumsum()).transform(
                lambda group, n=horizon: group.rolling(n, min_periods=1).sum() / n
            )
            * cfg["execution"]["weight_per_asset"]
        )
        tradable = frame.plan_tradable.fillna(False).astype(bool) & frame.contract_id.notna()
        frame["feature_unavailable"] = ~frame.ready.fillna(False).astype(bool)
        frame["source_unavailable"] = ~tradable
        frame["stale_at_fill"] = (frame.effective_date - frame.decision_date).dt.days.gt(
            cfg["features"]["maximum_calendar_gap_days"]
        )
        admitted = tradable & ~frame.feature_unavailable & ~frame.stale_at_fill
        frame["target_weight"] = frame.requested_weight.where(admitted, 0.0)
        frame["terminal_flat"] = False
        frame.loc[frame.index[-1], ["target_weight", "terminal_flat"]] = [0.0, True]
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        frame["provenance"] = f"v66_{name}_{arm}_completed_daily_ohlcv"
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True).sort_values(["effective_date", "asset_code"])
    base.require(
        result.groupby("effective_date").asset_code.nunique().eq(len(cfg["assets"])).all(),
        "incomplete joint target snapshot",
    )
    base.require(
        result.groupby("effective_date")
        .target_weight.apply(lambda x: x.abs().sum())
        .le(cfg["execution"]["maximum_signal_gross"] + 1e-12)
        .all(),
        "signal gross breach",
    )
    return result.reset_index(drop=True)


def position_counts(positions):
    entries, exits, exposure = 0, 0, 0
    for _, group in positions.groupby("asset_code"):
        group = group.sort_values("session_date")
        sign = np.sign(group.contracts)
        prior = sign.shift(1, fill_value=0)
        change = sign.ne(prior) | group.contract_id.ne(group.contract_id.shift(1))
        entries += int((sign.ne(0) & (prior.eq(0) | change)).sum())
        exits += int((prior.ne(0) & (sign.eq(0) | change)).sum())
        exposure += int(sign.ne(0).sum())
    return {"position_entries": entries, "round_trips": exits, "exposed_asset_sessions": exposure}


def summarize(result):
    values = base.summarize(result)
    values.pop("exposed_sessions")
    return {**values, **position_counts(result.positions)}


def run(cfg, parent, storage, expected):
    base.require(os.name == "posix", "economics runs on GPU server only")
    output = base.safe(storage, "runs/v66_fast_volume_contest_v1_" + expected[:12])
    base.require(not output.exists(), "existing run; do not repeat")
    verified = base.preflight(parent, storage)
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    base.write_json(output / "inputs.json", verified)
    declarations = base.declarations(parent)
    metrics = {h["id"]: {} for h in cfg["hypotheses"]}
    counts = {h["id"]: {} for h in cfg["hypotheses"]}
    for era in parent["eras"]:
        declared = declarations[era["id"]]
        active = pd.read_parquet(
            base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
        )
        obs = pd.read_parquet(
            base.safe(storage, declared["observations"]["path"]), columns=base.OBS_COLS
        )
        obs = obs.loc[obs.logical_asset.isin(cfg["assets"])]
        specs = pd.read_parquet(
            base.safe(storage, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
        )
        feature_rows = features(obs, cfg)
        feature_rows.to_parquet(output / f"features_{era['id']}.parquet", index=False)
        market = base.build_portfolio_market(
            obs.rename(
                columns={
                    "trade_date": "session_date",
                    "logical_asset": "asset_code",
                    "canonical_contract_id": "contract_id",
                }
            ),
            specs.loc[specs.asset_symbol.isin(cfg["assets"])],
        )
        for h in cfg["hypotheses"]:
            name = h["id"]
            metrics[name][era["id"]], counts[name][era["id"]] = {}, {}
            for arm in previous.ARMS:
                signal = targets(active, feature_rows, name, arm, cfg)
                prefix = f"{name}_{era['id']}_{arm}"
                signal.to_parquet(output / f"targets_{prefix}.parquet", index=False)
                counts[name][era["id"]][arm] = {
                    "decisions": len(signal),
                    "ready": int((~signal.feature_unavailable).sum()),
                    "events": int(signal.raw_direction.ne(0).sum()),
                    "nonzero": int(signal.target_weight.ne(0).sum()),
                    "source_unavailable": int(signal.source_unavailable.sum()),
                    "stale": int(signal.stale_at_fill.sum()),
                }
                metrics[name][era["id"]][arm] = {}
                for cost, (ticks, fee) in cfg["execution"]["costs"].items():
                    result = base.run_futures_portfolio_ledger(
                        market.loc[
                            pd.to_datetime(market.session_date).le(signal.effective_date.max())
                        ],
                        signal,
                        base.FuturesPortfolioLedgerConfig(
                            initial_cash=base.CAPITAL,
                            expected_assets=tuple(cfg["assets"]),
                            maximum_gross_notional_multiple=cfg["execution"][
                                "maximum_gross_multiple"
                            ],
                            initial_margin_buffer_multiplier=cfg["execution"]["margin_buffer"],
                            maximum_participation=cfg["execution"]["maximum_participation"],
                            slippage_ticks=ticks,
                            fee_multiplier=fee,
                            execution_atomicity="asset",
                            unexecutable_target_policy="cancel_and_clip",
                        ),
                    )
                    metrics[name][era["id"]][arm][cost] = summarize(result)
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
        "assessment": {
            name: previous.assess(eras, cfg["screen_gates"]) for name, eras in metrics.items()
        },
        "economic_runtime_seconds": time.monotonic() - started,
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


def audit(output):
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    replay_count = 0
    for name, eras in payload["metrics"].items():
        for era, arms in eras.items():
            for arm, costs in arms.items():
                for cost, values in costs.items():
                    replay_count += 1
                    prefix = f"{name}_{era}_{arm}_{cost}"
                    ledger = pd.read_parquet(output / f"ledger_{prefix}.parquet")
                    replay = base._performance_metrics(
                        ledger.ending_cash, ledger.session_date, base.CAPITAL
                    )
                    base.require(
                        all(np.isclose(values[k], v) for k, v in replay.items()), "metric drift"
                    )
                    positions = pd.read_parquet(output / f"positions_{prefix}.parquet")
                    base.require(
                        all(values[k] == v for k, v in position_counts(positions).items()),
                        "counts drift",
                    )
    base.require(replay_count == 48, "incomplete contest")
    return {
        "artifact_hashes": len(identity["files"]),
        "metric_replays": replay_count,
        "all_true": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, parent = load(args.seal_sha)
    if args.audit:
        print(json.dumps(audit(args.audit)))
    else:
        run(cfg, parent, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
