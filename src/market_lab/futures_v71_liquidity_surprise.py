"""One fixed CBR forecast-error screen; existing SI cash ledger, no fitting."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v68_reported_option_flow as shared

base = shared.base
CONFIG = base.PROJECT / "configs/v71_cbr_liquidity_surprise_v1.json"
SEAL = base.PROJECT / "configs/v71_cbr_liquidity_surprise_v1.seal.json"
VALUE = "government_accounts_change_bln_rub"
ARMS = shared.ARMS


def load(expected):
    base.require(base.sha(SEAL) == expected, "V71 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V71 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    base.require(cfg["assets"] == ["SI"], "universe drift")
    base.require(cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "capital drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def preflight(cfg, parent, storage):
    verified = {"futures": base.preflight(parent, storage), "sources": {}}
    evidence = cfg["method_evidence"]
    path = base.safe(storage, evidence["path"])
    base.require(
        path.stat().st_size == evidence["bytes"] and base.sha(path) == evidence["sha256"],
        "method evidence drift",
    )
    verified["method_evidence"] = evidence
    for role, spec in cfg["sources"].items():
        root = base.safe(storage, spec["root"])
        manifest_path = root / "manifest.json"
        base.require(base.sha(manifest_path) == spec["manifest_sha256"], "manifest drift")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        declared = spec["processed"]
        base.require(
            all(manifest["artifacts"]["processed"][k] == v for k, v in declared.items()),
            "source declaration drift",
        )
        for item in manifest["artifacts"].values():
            path = base.safe(root, item["path"])
            base.require(path.stat().st_size == item["bytes"], "source size drift")
            base.require(base.sha(path) == item["sha256"], "source hash drift")
        path = base.safe(root, declared["path"])
        pf = pq.ParquetFile(path)
        base.require(pf.metadata.num_rows == declared["rows"], "source row drift")
        base.require(set(spec["allowed_columns"]) <= set(pf.schema_arrow.names), "source schema")
        columns = ["publication_date", "available_at"]
        if role == "actual":
            columns.append("observation_date")
        dates = pd.read_parquet(path, columns=columns)
        for column in columns:
            d = pd.to_datetime(dates[column], utc=True)
            base.require(d.notna().all() and d.lt("2026-01-01T00:00:00Z").all(), "protected source")
        semantic = manifest["temporal_semantics"]
        base.require(semantic["development_backtest_admissible"] is True, "source not admitted")
        base.require(
            semantic["contains_prices_returns_targets_labels_or_pnl"] is False, "not macro"
        )
        verified["sources"][role] = {"manifest_sha256": base.sha(manifest_path), **declared}
    return verified


def moscow_eod(day):
    return (
        pd.Timestamp(day).tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).tz_convert("UTC")


def states(forecast, actual, cfg):
    """Compare only complete, ordinary periods; retain invalid releases as masks."""
    f, a = forecast.copy(), actual.copy()
    for frame, columns in (
        (f, ["publication_date", "forecast_period_start", "forecast_period_end"]),
        (a, ["observation_date", "publication_date"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
            base.require(frame[column].notna().all(), "missing source date")
        frame["available_at"] = pd.to_datetime(frame.available_at, utc=True)
        base.require(
            frame.available_at.notna().all()
            and frame.available_at.lt("2026-01-01T00:00:00Z").all(),
            "protected availability",
        )
        base.require(frame.publication_date.lt(base.BOUNDARY).all(), "protected publication")
        frame[VALUE] = pd.to_numeric(frame[VALUE], errors="raise")
        base.require(np.isfinite(frame[VALUE].dropna()).all(), "nonfinite contribution")
    base.require(a.observation_date.lt(base.BOUNDARY).all(), "protected actual")
    base.require(not f.publication_date.duplicated().any(), "duplicate forecast")
    base.require(not a.observation_date.duplicated().any(), "duplicate actual")
    base.require(a.publication_date.gt(a.observation_date).all(), "premature actual date")
    actual_floor = (
        a.publication_date.dt.tz_localize("Europe/Moscow") + pd.Timedelta(hours=10, minutes=31)
    ).dt.tz_convert("UTC")
    base.require(a.available_at.ge(actual_floor).all(), "premature actual clock")
    base.require(
        f.available_at.ge(f.publication_date.map(moscow_eod)).all(), "premature forecast clock"
    )
    base.require(f.forecast_period_start.ge(f.publication_date).all(), "backward forecast")
    base.require(f.forecast_period_end.ge(f.forecast_period_start).all(), "backward period")
    f = f.loc[f.publication_date.between(cfg["period"]["start"], cfg["period"]["end"])].sort_values(
        "publication_date"
    )
    a = a.sort_values("observation_date")
    rows = []
    for event in f.itertuples(index=False):
        start, end = event.forecast_period_start, event.forecast_period_end
        in_window = end <= pd.Timestamp(cfg["period"]["end"])
        regular = bool(
            event.publication_date.weekday() == 1
            and start == event.publication_date + pd.Timedelta(days=1)
            and end == start + pd.Timedelta(days=6)
        )
        expected = pd.bdate_range(start, end) if in_window else pd.DatetimeIndex([])
        block = a.loc[a.observation_date.between(start, end)] if in_window else a.iloc[:0]
        complete = regular and len(expected) == 5 and list(block.observation_date) == list(expected)
        finite = complete and block[VALUE].notna().all() and pd.notna(getattr(event, VALUE))
        ready = bool(in_window and finite)
        clock = max(event.available_at, moscow_eod(end + pd.Timedelta(days=1)))
        if not block.empty:
            clock = max(clock, block.available_at.max())
        realized = float(block[VALUE].cumsum().mean()) if ready else np.nan
        predicted = getattr(event, VALUE)
        error = realized - predicted if ready else np.nan
        reason = (
            "ready"
            if ready
            else (
                "period_outside_window"
                if not in_window
                else (
                    "irregular_period"
                    if not regular
                    else ("missing_dates" if not complete else "missing_value")
                )
            )
        )
        rows.append(
            {
                "asset_code": "SI",
                "publication_date": event.publication_date,
                "forecast_period_start": start,
                "source_date": end,
                "forecast_available_at_utc": event.available_at,
                "actual_last_available_at_utc": block.available_at.max()
                if not block.empty
                else pd.NaT,
                "available_at_utc": clock,
                "in_window": in_window,
                "regular_period": regular,
                "actual_rows": len(block),
                "actual_observed_values": int(block[VALUE].notna().sum()),
                "ready": ready,
                "reason": reason,
                "forecast_value": predicted,
                "actual_matching_value": realized,
                "forecast_error": error,
                "primary_direction": float(np.sign(error)) if ready else np.nan,
                "control_direction": float(np.sign(realized)) if ready else np.nan,
                "forecast_raw_sha256": event.raw_sha256,
                "actual_raw_sha256": ";".join(sorted(block.raw_sha256.unique())),
            }
        )
    base.require(bool(rows), "no forecast releases")
    return pd.DataFrame(rows).sort_values(["available_at_utc", "source_date"], ignore_index=True)


def assess(metrics, quality, cfg):
    result = shared.assess(metrics, quality, cfg)
    for cost, value in metrics["primary"].items():
        result["checks"][cost + "_meaningful_excess"] = (
            value["cagr"] - metrics["control"][cost]["cagr"]
            >= cfg["screen_gates"]["minimum_cagr_excess_over_control_each_cost"]
        )
    if result["verdict"] == "STAGE2_CANDIDATE" and not all(result["checks"].values()):
        result["verdict"] = "REJECT_STAGE1"
    return result


def run(cfg, parent, storage, expected):
    base.require(
        os.name != "nt" and str(storage.resolve()) == "/srv/trading_lab_data",
        "economic compute on gpu-mlserver only",
    )
    verified = preflight(cfg, parent, storage)
    output = base.safe(storage, f"runs/{cfg['protocol_id']}_{expected[:12]}")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    base.write_json(output / "inputs.json", verified)
    raw = {
        role: pd.read_parquet(
            base.safe(storage, spec["root"]) / spec["processed"]["path"],
            columns=spec["allowed_columns"],
        )
        for role, spec in cfg["sources"].items()
    }
    state = states(raw["forecast"], raw["actual"], cfg)
    state.to_parquet(output / "liquidity_surprise_states.parquet", index=False)
    declared = base.declarations(parent)["recent"]
    obs = pd.read_parquet(
        base.safe(storage, declared["observations"]["path"]), columns=base.OBS_COLS
    )
    obs = obs.loc[
        obs.logical_asset.eq("SI")
        & pd.to_datetime(obs.trade_date).between(cfg["period"]["start"], cfg["period"]["end"])
    ]
    specs = pd.read_parquet(
        base.safe(storage, declared["specs"]["path"]), columns=sorted(base.SPEC_PROXY_COLUMNS)
    )
    active = pd.read_parquet(
        base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
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
    eligible = state.loc[state.in_window]
    quality = {
        "source_forecast_rows": len(raw["forecast"]),
        "source_actual_rows": len(raw["actual"]),
        "forecast_releases_2021_2025": len(state),
        "completed_window_releases": len(eligible),
        "ready_releases": int(eligible.ready.sum()),
        "ready_asset_date_fraction": float(eligible.ready.mean()),
        "state_reason_counts": {str(k): int(v) for k, v in state.reason.value_counts().items()},
        "original_vintages_proved": False,
    }
    metrics, counts = {}, {}
    for arm in ARMS:
        signal = shared.targets(active, state, arm, cfg)
        signal["provenance"] = cfg["protocol_id"] + "_" + arm
        signal.to_parquet(output / f"targets_{arm}.parquet", index=False)
        counts[arm] = {
            "decisions": len(signal),
            "nonzero_targets": int(signal.target_weight.ne(0).sum()),
            "used_releases": int(
                signal.loc[signal.target_weight.ne(0), "publication_date"].nunique()
            ),
            "feature_unavailable": int(signal.feature_unavailable.sum()),
            "source_unavailable": int(signal.source_unavailable.sum()),
            "stale_at_fill": int(signal.stale_at_fill.sum()),
        }
        metrics[arm] = {}
        for cost, (ticks, fee) in cfg["execution"]["costs"].items():
            result = base.run_futures_portfolio_ledger(
                market.loc[pd.to_datetime(market.session_date).le(signal.effective_date.max())],
                signal,
                base.FuturesPortfolioLedgerConfig(
                    initial_cash=base.CAPITAL,
                    expected_assets=("SI",),
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
        "assessment": assess(metrics, quality, cfg),
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


def audit(output, cfg, storage):
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    base.require(identity["seal_sha256"] == base.sha(SEAL), "run seal drift")
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    base.require(payload["protocol_id"] == cfg["protocol_id"], "run protocol drift")
    raw = {}
    for role, spec in cfg["sources"].items():
        path = base.safe(storage, spec["root"]) / spec["processed"]["path"]
        base.require(base.sha(path) == spec["processed"]["sha256"], "replay source drift")
        raw[role] = pd.read_parquet(path, columns=spec["allowed_columns"])
    expected_states = states(raw["forecast"], raw["actual"], cfg)
    pd.testing.assert_frame_equal(
        expected_states, pd.read_parquet(output / "liquidity_surprise_states.parquet")
    )
    replays = 0
    for arm, costs in payload["metrics"].items():
        signal = pd.read_parquet(output / f"targets_{arm}.parquet")
        used = signal.loc[signal.target_weight.ne(0)]
        base.require(used.available_at_utc.le(used.decision_at_utc).all(), "future source")
        base.require(used.source_date.lt(used.decision_date).all(), "unfinished period")
        base.require(
            used.actual_last_available_at_utc.le(used.decision_at_utc).all(), "late actual"
        )
        base.require(used.ready.all(), "unavailable state traded")
        for cost, value in costs.items():
            ledger = pd.read_parquet(output / f"ledger_{arm}_{cost}.parquet")
            replay = base._performance_metrics(
                ledger.ending_cash, ledger.session_date, base.CAPITAL
            )
            base.require(all(np.isclose(value[k], v) for k, v in replay.items()), "metric drift")
            position = pd.read_parquet(output / f"positions_{arm}_{cost}.parquet")
            base.require(
                all(value[k] == v for k, v in shared.position_counts(position).items()),
                "count drift",
            )
            orders = pd.read_parquet(output / f"orders_{arm}_{cost}.parquet")
            filled = orders.loc[orders.filled]
            costs_total = filled.commission_cost.sum() + filled.slippage_cost.sum()
            base.require(np.isclose(costs_total, value["total_cost"]), "cost drift")
            base.require(
                np.isclose(ledger.variation_margin.sum() - costs_total, value["net_pnl"]),
                "cash drift",
            )
            replays += 1
    base.require(replays == 4, "incomplete screen")
    base.require(
        assess(payload["metrics"], payload["source_quality"], cfg) == payload["assessment"],
        "verdict drift",
    )
    return {
        "artifact_hashes": len(identity["files"]),
        "source_state_replay": True,
        "metric_count_cash_replays": replays,
        "all_true": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, parent = load(args.seal_sha)
    print(json.dumps(audit(args.audit, cfg, args.storage_root))) if args.audit else run(
        cfg, parent, args.storage_root, args.seal_sha
    )


if __name__ == "__main__":
    main()
