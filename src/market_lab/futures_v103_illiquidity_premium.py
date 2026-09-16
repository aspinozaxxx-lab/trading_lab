"""One slow cross-market illiquidity-premium screen on existing sealed daily inputs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
mapping_tools = prior.prior.mapping_tools
ASSETS = mapping_tools.ASSETS
CONFIG = base.PROJECT / "configs/v103_illiquidity_premium_v1.json"
SEAL = base.PROJECT / "configs/v103_illiquidity_premium_v1.seal.json"
SPEC_FEATURES = [
    "session_date",
    "asset_symbol",
    "contract_id",
    "sizing_point_value",
    "sizing_observed_session_date",
    "sizing_lag_sessions",
    "sizing_usable",
]


def features(active, observations, specs, cfg):
    # Reuse the tested exact-contract/adjacent-calendar pairing, not its skew signal.
    frame = mapping_tools.features(active, observations, cfg).drop(
        columns=["skewness", "window_count"]
    )
    raw = (
        specs.loc[:, SPEC_FEATURES]
        .copy()
        .rename(columns={"session_date": "effective_date", "asset_symbol": "asset_code"})
    )
    for key in ("effective_date", "sizing_observed_session_date"):
        raw[key] = pd.to_datetime(raw[key], errors="raise")
    base.require(
        raw.effective_date.notna().all()
        and raw.effective_date.lt(base.BOUNDARY).all()
        and raw.sizing_observed_session_date.dropna().lt(base.BOUNDARY).all(),
        "protected/invalid feature specs",
    )
    base.require(
        not raw.duplicated(["effective_date", "asset_code", "contract_id"]).any(),
        "duplicate feature specs",
    )
    frame = frame.merge(
        raw, on=["effective_date", "asset_code", "contract_id"], how="left", validate="many_to_one"
    )
    value = pd.to_numeric(frame.sizing_point_value, errors="coerce").astype(float)
    gap = (frame.effective_date - frame.decision_date).dt.days
    size_valid = (
        frame.sizing_usable.eq(True)
        & frame.sizing_lag_sessions.eq(1)
        & frame.sizing_observed_session_date.notna()
        & frame.sizing_observed_session_date.lt(frame.effective_date)
        & frame.sizing_observed_session_date.le(frame.decision_date)
        & np.isfinite(value)
        & value.gt(0)
    )
    notional = (
        pd.to_numeric(frame.current_close, errors="coerce").astype(float)
        * pd.to_numeric(frame.current_volume, errors="coerce").astype(float)
        * value
    )
    valid = (
        frame.return_observed
        & size_valid
        & gap.between(1, cfg["signal"]["maximum_observation_gap_days"])
        & np.isfinite(notional)
        & notional.gt(0)
    )
    frame["notional_volume_rub_proxy"] = notional.where(valid)
    frame["illiquidity_observed"] = valid
    frame["daily_illiquidity"] = (1e6 * frame.same_contract_return.abs() / notional).where(valid)
    window = cfg["signal"]["lookback_sessions"]
    group = frame.groupby("asset_code", sort=False).daily_illiquidity
    frame["illiquidity_window_count"] = group.transform(lambda s: s.rolling(window).count())
    frame["illiquidity"] = group.transform(lambda s: s.rolling(window, min_periods=window).mean())
    return frame


def targets(active, feature, cfg):
    plan = mapping_tools.mapping(active)
    plan = plan.loc[plan.decision_date.notna()].copy()
    wide = feature.pivot(index="effective_date", columns="asset_code", values="illiquidity")
    base.require(set(wide.columns) == set(ASSETS), "feature universe drift")
    dates = pd.Series(sorted(wide.index))
    predecessor = dict(zip(dates.iloc[1:], dates.iloc[:-1], strict=True))
    weights, last_month, selected, source_day = dict.fromkeys(ASSETS, 0.0), None, pd.NaT, pd.NaT
    ready, rows = False, []
    for day, part in plan.groupby("decision_date", sort=True):
        base.require(
            set(part.asset_code) == set(ASSETS) and part.effective_date.nunique() == 1,
            "incomplete decision calendar",
        )
        month = day.to_period("M")
        rebalance = month != last_month
        if rebalance:
            last_month, selected, source_day = month, day, predecessor.get(day, pd.NaT)
            values = (
                wide.loc[source_day].reindex(ASSETS)
                if pd.notna(source_day)
                else pd.Series(dtype=float)
            )
            ready = (
                len(values) == 4
                and bool(np.isfinite(values).all())
                and 0 < (day - source_day).days <= cfg["signal"]["maximum_observation_gap_days"]
            )
            weights = dict.fromkeys(ASSETS, 0.0)
            if ready:
                low, high = values.min(), values.max()
                ready = bool(
                    low < high and values.eq(low).sum() == 1 and values.eq(high).sum() == 1
                )
                if ready:
                    weights[values.idxmax()] = cfg["execution"]["weight_per_leg"]
                    weights[values.idxmin()] = -cfg["execution"]["weight_per_leg"]
        available = (
            (source_day + pd.Timedelta(days=1, hours=8))
            .tz_localize("Europe/Moscow")
            .tz_convert("UTC")
            if pd.notna(source_day)
            else pd.NaT
        )
        decision = (
            (day + pd.Timedelta(hours=18, minutes=45))
            .tz_localize("Europe/Moscow")
            .tz_convert("UTC")
        )
        for row in part.to_dict("records"):
            row.update(
                selection_date=selected,
                monthly_rebalance=rebalance,
                feature_unavailable=not ready,
                requested_weight=weights[row["asset_code"]],
                source_date=source_day,
                available_at_utc=available,
                decision_at_utc=decision,
                source_url="derived:illiquidity63:" + selected.strftime("%Y-%m-%d"),
            )
            row["source_unavailable"] = not (
                row["plan_tradable"] is True and pd.notna(row["contract_id"])
            )
            row["stale_at_fill"] = (row["effective_date"] - day).days > cfg["signal"][
                "maximum_fill_gap_days"
            ]
            row["target_weight"] = (
                row["requested_weight"]
                if not (row["source_unavailable"] or row["stale_at_fill"])
                else 0.0
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame = frame.loc[
        frame.effective_date.between(cfg["period"]["start"], cfg["period"]["end"])
    ].copy()
    base.require(not frame.empty, "empty evaluation calendar")
    frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
    frame.loc[frame.terminal_flat, "target_weight"] = 0.0
    frame.loc[frame.target_weight.eq(0), "contract_id"] = None
    frame["provenance"] = "v103_lagged63_illiquidity_high_minus_low"
    frame = frame.sort_values(["effective_date", "asset_code"], ignore_index=True)
    used = frame.loc[frame.target_weight.ne(0)]
    base.require(
        used.source_date.lt(used.selection_date).all()
        and used.available_at_utc.le(used.decision_at_utc).all(),
        "noncausal feature",
    )
    control = frame.copy()
    control[["requested_weight", "target_weight"]] *= -1.0
    control["provenance"] = "v103_same_readiness_mirror_not_promotable"
    return {"primary": frame, "control": control}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V103 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V103 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == list(ASSETS)
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected):
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(
        output / "inputs.json",
        {
            "seal_sha256": expected,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    observations = pd.read_parquet(
        base.safe(STORAGE, declared["observations"]["path"]), columns=base.OBS_COLS
    )
    specs = pd.read_parquet(
        base.safe(STORAGE, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
    )
    feature = features(active, observations, specs, cfg)
    feature.to_parquet(output / "features.parquet", index=False)
    signals = targets(active, feature, cfg)
    p = signals["primary"]
    monthly = p.loc[p.monthly_rebalance].drop_duplicates("selection_date")
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "monthly_selections": len(monthly),
        "ready_monthly_selections": int((~monthly.feature_unavailable).sum()),
        "feature_rows": len(feature),
        "observed_illiquidity_rows": int(feature.illiquidity_observed.sum()),
        "original_receipt_verified": False,
    }
    market = base.build_portfolio_market(
        observations.rename(
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
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "illiquidity")
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
