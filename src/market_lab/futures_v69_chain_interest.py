"""Fixed reported futures-chain OI growth; existing ledger, no fit or collection."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v68_reported_option_flow as shared

base = shared.base
CONFIG = base.PROJECT / "configs/v69_futures_chain_interest_v1.json"
SEAL = base.PROJECT / "configs/v69_futures_chain_interest_v1.seal.json"
ARMS = shared.ARMS


def load(expected):
    base.require(base.sha(SEAL) == expected, "V69 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V69 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    base.require(cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "capital drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def preflight(cfg, parent, storage):
    verified = base.preflight(parent, storage)
    path = base.safe(storage, cfg["source"]["audit_path"])
    base.require(base.sha(path) == cfg["source"]["audit_sha256"], "source audit drift")
    audit = json.loads(path.read_text(encoding="utf-8-sig"))
    declared = base.declarations(parent)["recent"]["observations"]
    schema = base.pq.ParquetFile(base.safe(storage, declared["path"])).schema_arrow.names
    base.require(set(cfg["source"]["allowed_signal_columns"]) <= set(schema), "OI schema")
    record = audit["output_artifacts"]["contract_observations"]
    base.require(all(record[k] == declared[k] for k in ("bytes", "rows", "sha256")), "audit link")
    base.require(audit["protected_from"] == "2026-01-01", "audit boundary")
    base.require(audit["calendar_start"] == "2018-01-03", "audit start")
    base.require(audit["calendar_end"] == "2025-12-30", "audit end")
    base.require(audit["verified_artifact_count"] == 478, "source lineage")
    return {"futures": verified, "source_audit_sha256": base.sha(path)}


def states(raw, cfg):
    d = raw[cfg["source"]["allowed_signal_columns"]].copy()
    d["trade_date"] = pd.to_datetime(d.trade_date)
    base.require(
        d.trade_date.notna().all() and d.trade_date.lt(base.BOUNDARY).all(), "protected date"
    )
    base.require(d.logical_asset.isin(cfg["assets"]).all(), "unknown asset")
    base.require(d.canonical_contract_id.notna().all(), "missing contract identity")
    base.require(
        not d.duplicated(["trade_date", "logical_asset", "canonical_contract_id"]).any(),
        "duplicate OI",
    )
    d["open_interest"] = pd.to_numeric(d.open_interest, errors="raise")
    known = d.open_interest.dropna()
    base.require(np.isfinite(known).all() and known.ge(0).all(), "invalid observed OI")
    group = d.groupby(["logical_asset", "trade_date"], sort=True).open_interest
    daily = group.agg(source_rows="size", observed_rows="count")
    daily["reported_sum"] = group.sum(min_count=1)
    daily = daily.reset_index()
    daily = daily.rename(columns={"logical_asset": "asset_code", "trade_date": "source_date"})
    daily["missing_rows"] = daily.source_rows - daily.observed_rows
    daily["chain_oi"] = daily.reported_sum.where(
        daily.missing_rows.eq(0) & daily.observed_rows.gt(0)
    )
    parts = []
    n = cfg["signal"]["lookback_sessions"]
    for _, frame in daily.groupby("asset_code", sort=True):
        frame = frame.sort_values("source_date").copy()
        frame["prior_source_date"] = frame.source_date.shift(n)
        frame["prior_chain_oi"] = frame.chain_oi.shift(n)
        max_gap = frame.source_date.diff().dt.days.rolling(n, min_periods=n).max()
        ready = frame.chain_oi.gt(0) & frame.prior_chain_oi.gt(0)
        ready &= max_gap.le(cfg["signal"]["maximum_observation_gap_calendar_days"])
        frame["ready"] = ready
        frame["growth"] = np.log(frame.chain_oi.where(ready) / frame.prior_chain_oi.where(ready))
        frame["primary_direction"] = np.sign(frame.growth)
        frame["control_direction"] = pd.Series(1.0, index=frame.index).where(ready)
        frame["available_at_utc"] = (
            frame.source_date.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
        ).dt.tz_convert("UTC")
        parts.append(frame)
    base.require(bool(parts), "no OI states")
    return pd.concat(parts, ignore_index=True)


def targets(active, state, arm, cfg):
    base.require(arm in ARMS, "unknown arm")
    parts = []
    for asset in cfg["assets"]:
        left = active.loc[active.asset_code.eq(asset), base.ACTIVE_COLS].copy()
        for key in ("decision_date", "effective_date", "observed_through"):
            left[key] = pd.to_datetime(left[key])
        left = left.loc[
            left.decision_date.notna()
            & left.effective_date.between(cfg["period"]["start"], cfg["period"]["end"])
        ].sort_values("decision_date")
        base.require(not left.empty, "missing map")
        base.require(left.decision_date.lt(left.effective_date).all(), "noncausal map")
        base.require(left.observed_through.le(left.decision_date).all(), "future map")
        base.require(left.effective_date.lt(base.BOUNDARY).all(), "protected map")
        base.require(
            not left.effective_date.duplicated().any()
            and not left.decision_date.duplicated().any(),
            "duplicate map",
        )
        left["decision_at_utc"] = (
            left.decision_date.dt.tz_localize("Europe/Moscow")
            + pd.Timedelta(days=1)
            - pd.Timedelta(nanoseconds=1)
        ).dt.tz_convert("UTC")
        right = (
            state.loc[state.asset_code.eq(asset)]
            .drop(columns="asset_code")
            .sort_values("available_at_utc")
        )
        frame = pd.merge_asof(
            left,
            right,
            left_on="decision_at_utc",
            right_on="available_at_utc",
            direction="backward",
        )
        frame["month"] = frame.decision_date.dt.strftime("%Y-%m")
        frame["monthly_update"] = ~frame.month.duplicated()
        columns = list(right.columns)
        snapshot = frame.loc[frame.monthly_update, ["month", "decision_at_utc", *columns]].rename(
            columns={"decision_at_utc": "signal_decision_at_utc"}
        )
        # Exact month join retains a NULL new snapshot; ffill would silently reuse an old signal.
        frame = frame.drop(columns=columns).merge(
            snapshot, on="month", how="left", validate="many_to_one"
        )
        prior = frame.source_date.lt(frame.decision_date)
        frame["feature_unavailable"] = ~(frame.ready.astype("boolean").fillna(False) & prior)
        fresh = (frame.effective_date - frame.source_date).dt.days.le(
            cfg["signal"]["maximum_source_age_at_fill_calendar_days"]
        )
        delay = (frame.effective_date - frame.decision_date).dt.days.le(
            cfg["signal"]["maximum_decision_to_fill_calendar_days"]
        )
        frame["stale_at_fill"] = ~(fresh & delay)
        frame["source_unavailable"] = ~(
            frame.plan_tradable.fillna(False).astype(bool) & frame.contract_id.notna()
        )
        frame["requested_weight"] = frame[f"{arm}_direction"] * cfg["execution"]["weight_per_asset"]
        admitted = ~(frame.feature_unavailable | frame.stale_at_fill | frame.source_unavailable)
        frame["target_weight"] = frame.requested_weight.where(admitted, 0.0)
        frame["terminal_flat"] = False
        frame = frame.sort_values("effective_date", ignore_index=True)
        frame.loc[frame.index[-1], ["target_weight", "terminal_flat"]] = [0.0, True]
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        frame["provenance"] = "v69_monthly_chain_oi_" + arm
        parts.append(frame)
    out = pd.concat(parts, ignore_index=True).sort_values(["effective_date", "asset_code"])
    base.require(out.target_weight.notna().all(), "unknown target")
    base.require(
        out.groupby("effective_date").asset_code.nunique().eq(len(cfg["assets"])).all(),
        "incomplete joint target",
    )
    base.require(
        out.groupby("effective_date")
        .target_weight.apply(lambda x: x.abs().sum())
        .le(cfg["execution"]["maximum_signal_gross"] + 1e-12)
        .all(),
        "gross breach",
    )
    return out.reset_index(drop=True)


def run(cfg, parent, storage, expected):
    base.require(os.name == "posix", "economic run must use gpu-mlserver")
    output = base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing canonical run; no repeat")
    verified = preflight(cfg, parent, storage)
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    base.write_json(output / "inputs.json", verified)
    declared = base.declarations(parent)["recent"]
    obs = pd.read_parquet(
        base.safe(storage, declared["observations"]["path"]),
        columns=list(dict.fromkeys(base.OBS_COLS + cfg["source"]["allowed_signal_columns"])),
    )
    state = states(obs, cfg)
    base.require(
        len(obs) == cfg["source"]["expected_rows"]
        and len(state) == cfg["source"]["expected_asset_dates"],
        "source counts drift",
    )
    state.to_parquet(output / "chain_oi_states.parquet", index=False)
    active = pd.read_parquet(
        base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    specs = pd.read_parquet(
        base.safe(storage, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
    )
    market = base.build_portfolio_market(
        obs.rename(
            columns={
                "trade_date": "session_date",
                "logical_asset": "asset_code",
                "canonical_contract_id": "contract_id",
            }
        ),
        specs,
    )
    market = market.loc[
        pd.to_datetime(market.session_date).between(cfg["period"]["start"], cfg["period"]["end"])
    ]
    metrics, counts = {}, {}
    quality = {
        "source_rows": len(obs),
        "source_asset_dates": len(state),
        "missing_oi_rows": int(obs.open_interest.isna().sum()),
        "complete_reported_asset_dates": int(state.missing_rows.eq(0).sum()),
        "ready_daily_states": int(state.ready.sum()),
        "all_market_totals_complete": False,
    }
    for arm in ARMS:
        signal = targets(active, state, arm, cfg)
        signal.to_parquet(output / f"targets_{arm}.parquet", index=False)
        monthly = signal.loc[signal.monthly_update]
        if arm == "primary":
            quality.update(
                asset_dates=len(monthly),
                ready_asset_dates=int((~monthly.feature_unavailable).sum()),
                ready_asset_date_fraction=float((~monthly.feature_unavailable).mean()),
            )
        counts[arm] = {
            "decisions": len(signal),
            "monthly_asset_decisions": len(monthly),
            "nonzero_targets": int(signal.target_weight.ne(0).sum()),
            "feature_unavailable": int(signal.feature_unavailable.sum()),
            "source_unavailable": int(signal.source_unavailable.sum()),
            "stale": int(signal.stale_at_fill.sum()),
        }
        metrics[arm] = {}
        for cost, (ticks, fee) in cfg["execution"]["costs"].items():
            result = base.run_futures_portfolio_ledger(
                market.loc[pd.to_datetime(market.session_date).le(signal.effective_date.max())],
                signal,
                base.FuturesPortfolioLedgerConfig(
                    initial_cash=base.CAPITAL,
                    expected_assets=tuple(cfg["assets"]),
                    maximum_gross_notional_multiple=cfg["execution"]["maximum_gross_multiple"],
                    initial_margin_buffer_multiplier=cfg["execution"]["margin_buffer"],
                    maximum_participation=cfg["execution"]["maximum_participation"],
                    slippage_ticks=ticks,
                    fee_multiplier=fee,
                    execution_atomicity="asset",
                    unexecutable_target_policy="cancel_and_clip",
                ),
            )
            metrics[arm][cost] = shared.summarize(result)
            for kind in ("ledger", "orders", "positions"):
                getattr(result, kind).to_parquet(
                    output / f"{kind}_{arm}_{cost}.parquet", index=False
                )
            print(json.dumps({"completed": arm, "costs": cost}), flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "stage": 1,
        "metrics": metrics,
        "counts": counts,
        "source_quality": quality,
        "assessment": shared.assess(metrics, quality, cfg),
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
    return output


def audit(output, cfg):
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    base.require(payload["protocol_id"] == cfg["protocol_id"], "run protocol drift")
    base.require(payload["seal_sha256"] == base.sha(SEAL), "run seal drift")
    verified = shared.audit(output, cfg)
    for arm in ARMS:
        frame = pd.read_parquet(output / f"targets_{arm}.parquet")
        used = frame.loc[frame.target_weight.ne(0)]
        base.require(
            used.available_at_utc.le(used.signal_decision_at_utc).all(), "late monthly source"
        )
        base.require(
            used.signal_decision_at_utc.le(used.decision_at_utc).all(), "future monthly choice"
        )
        for _, group in frame.groupby(["asset_code", "month"]):
            base.require(group.monthly_update.sum() == 1, "monthly schedule drift")
            base.require(
                group.requested_weight.nunique(dropna=False) == 1, "intra-month signal drift"
            )
    return {**verified, "monthly_schedule_replay": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, parent = load(args.seal_sha)
    if args.audit:
        print(json.dumps(audit(args.audit, cfg)))
    else:
        run(cfg, parent, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
