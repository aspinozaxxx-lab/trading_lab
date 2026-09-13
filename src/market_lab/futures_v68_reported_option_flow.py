"""A fixed reported-option-volume screen with the existing futures cash ledger."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v64_si_tax_calendar as base

CONFIG = base.PROJECT / "configs/v68_reported_option_flow_v1.json"
SEAL = base.PROJECT / "configs/v68_reported_option_flow_v1.seal.json"
ARMS = ("primary", "control")
VALUE_COLUMNS = ("volume", "openposition")


def load(expected):
    base.require(base.sha(SEAL) == expected, "V68 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V68 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    base.require(cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "capital drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def source_preflight(cfg, storage):
    """Verify declared hashes, schema and date-only boundary before economic loading."""
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    manifest_file, audit_file = root / "manifest.json", root / "audit.json"
    base.require(base.sha(manifest_file) == spec["manifest_sha256"], "option manifest drift")
    base.require(base.sha(audit_file) == spec["audit_sha256"], "option audit drift")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    audit = json.loads(audit_file.read_text(encoding="utf-8-sig"))
    declared = spec["processed"]
    for key, value in declared.items():
        base.require(manifest["processed"][key] == value, "option declaration drift")
    path = base.safe(root, declared["path"])
    base.require(path.stat().st_size == declared["bytes"], "option size drift")
    base.require(base.sha(path) == declared["sha256"], "option bytes drift")
    pf = pq.ParquetFile(path)
    base.require(pf.metadata.num_rows == declared["rows"], "option row drift")
    base.require(set(spec["allowed_columns"]) <= set(pf.schema_arrow.names), "option schema")
    dates = pd.to_datetime(pd.read_parquet(path, columns=["tradedate"]).tradedate)
    base.require(dates.notna().all() and dates.lt(base.BOUNDARY).all(), "protected options")
    base.require(str(dates.min().date()) == declared["minimum_tradedate"], "option minimum")
    base.require(str(dates.max().date()) == declared["maximum_tradedate"], "option maximum")
    base.require(audit["all_true"] is True, "source audit failed")
    base.require(manifest["contains_returns_targets_predictions_or_pnl"] is False, "not source")
    return {"processed": declared, "manifest_sha256": spec["manifest_sha256"], "all_true": True}


def states(raw):
    """Sum only observed cells; retain missing counts and never declare complete totals."""
    d = raw.copy()
    d["tradedate"] = pd.to_datetime(d.tradedate)
    d["available_at_utc"] = pd.to_datetime(d.available_at_utc, utc=True)
    base.require(
        d.tradedate.notna().all() and d.tradedate.lt(base.BOUNDARY).all(), "protected date"
    )
    base.require(not d.duplicated(["tradedate", "boardid", "secid"]).any(), "duplicate option")
    base.require(d.option_type.isin(["call", "put"]).all(), "unknown option side")
    base.require(d.available_at_utc.notna().all(), "missing availability")
    earliest = (d.tradedate.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).dt.tz_convert(
        "UTC"
    )
    base.require(d.available_at_utc.ge(earliest).all(), "premature availability")
    for column in VALUE_COLUMNS:
        d[column] = pd.to_numeric(d[column], errors="raise")
        finite = d[column].dropna()
        base.require(np.isfinite(finite).all() and finite.ge(0).all(), "invalid observed activity")
    rows = []
    for (day, asset), group in d.groupby(["tradedate", "logical_asset"], sort=True):
        base.require(group.available_at_utc.nunique() == 1, "mixed availability")
        row = {
            "source_date": day,
            "asset_code": asset,
            "available_at_utc": group.available_at_utc.iloc[0],
            "source_rows": len(group),
        }
        for side in ("call", "put"):
            sub = group.loc[group.option_type.eq(side)]
            row[f"{side}_rows"] = len(sub)
            for column in VALUE_COLUMNS:
                row[f"{side}_{column}"] = sub[column].sum(min_count=1)
                row[f"{side}_{column}_observed_rows"] = int(sub[column].notna().sum())
                row[f"{side}_{column}_missing_rows"] = int(sub[column].isna().sum())
        rows.append(row)
    out = pd.DataFrame(rows)
    base.require(not out.empty, "no option states")
    for column in VALUE_COLUMNS:
        total = out[f"call_{column}"] + out[f"put_{column}"]
        out[f"call_{column}_share"] = out[f"call_{column}"] / total.where(total.gt(0))
    out["volume_excess_share"] = out.call_volume_share - out.call_openposition_share
    out["ready"] = np.isfinite(out[["call_volume_share", "call_openposition_share"]]).all(axis=1)
    out["primary_direction"] = np.sign(out.volume_excess_share).where(out.ready)
    out["control_direction"] = np.sign(out.call_openposition_share - 0.5).where(out.ready)
    return out.sort_values(["asset_code", "source_date"], ignore_index=True)


def targets(active, state, arm, cfg):
    base.require(arm in ARMS, "unknown arm")
    parts = []
    for asset in cfg["assets"]:
        left = active.loc[active.asset_code.eq(asset), base.ACTIVE_COLS].copy()
        for column in ("decision_date", "effective_date", "observed_through"):
            left[column] = pd.to_datetime(left[column])
        left = left.loc[
            left.decision_date.notna()
            & left.effective_date.between(cfg["period"]["start"], cfg["period"]["end"])
        ].sort_values("decision_date")
        base.require(not left.empty, "missing map")
        base.require(left.decision_date.lt(left.effective_date).all(), "noncausal map")
        base.require(left.observed_through.le(left.decision_date).all(), "future map")
        base.require(left.effective_date.lt(base.BOUNDARY).all(), "protected map")
        base.require(not left.effective_date.duplicated().any(), "duplicate map")
        left["decision_at_utc"] = (
            left.decision_date.dt.tz_localize("Europe/Moscow")
            + pd.Timedelta(days=1)
            - pd.Timedelta(nanoseconds=1)
        ).dt.tz_convert("UTC")
        right = state.loc[state.asset_code.eq(asset)].drop(columns="asset_code")
        right = right.sort_values(["available_at_utc", "source_date"])
        frame = pd.merge_asof(
            left,
            right,
            left_on="decision_at_utc",
            right_on="available_at_utc",
            direction="backward",
            allow_exact_matches=True,
        )
        prior = frame.source_date.lt(frame.decision_date)
        fresh = (frame.effective_date - frame.source_date).dt.days.le(
            cfg["signal"]["maximum_source_age_at_fill_calendar_days"]
        )
        delay = (frame.effective_date - frame.decision_date).dt.days.le(
            cfg["signal"]["maximum_decision_to_fill_calendar_days"]
        )
        frame["feature_unavailable"] = ~(frame.ready.astype("boolean").fillna(False) & prior)
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
        frame["provenance"] = "v68_reported_option_flow_" + arm
        parts.append(frame)
    result = pd.concat(parts, ignore_index=True).sort_values(["effective_date", "asset_code"])
    base.require(result.target_weight.notna().all(), "unknown target")
    base.require(
        result.groupby("effective_date").asset_code.nunique().eq(len(cfg["assets"])).all(),
        "incomplete joint target",
    )
    gross = result.groupby("effective_date").target_weight.apply(lambda x: x.abs().sum())
    base.require(gross.le(cfg["execution"]["maximum_signal_gross"] + 1e-12).all(), "gross breach")
    return result.reset_index(drop=True)


def position_counts(positions):
    entries, exits, exposed = 0, 0, 0
    for _, group in positions.groupby("asset_code"):
        group = group.sort_values("session_date")
        sign = np.sign(group.contracts)
        prior = sign.shift(1, fill_value=0)
        contract = group.contract_id.fillna("__FLAT__").astype(str)
        change = sign.ne(prior) | contract.ne(contract.shift(1))
        entries += int((sign.ne(0) & (prior.eq(0) | change)).sum())
        exits += int((prior.ne(0) & (sign.eq(0) | change)).sum())
        exposed += int(sign.ne(0).sum())
    return {"position_entries": entries, "round_trips": exits, "exposed_asset_sessions": exposed}


def summarize(result):
    out = base.summarize(result)
    out.pop("exposed_sessions")
    return {**out, **position_counts(result.positions)}


def assess(metrics, quality, cfg):
    g = cfg["screen_gates"]
    base.require(set(metrics) == set(ARMS), "missing arm")
    checks = {
        "reported_state_coverage": quality["ready_asset_date_fraction"]
        >= g["minimum_ready_asset_date_fraction"]
    }
    for arm in ARMS:
        base.require(set(metrics[arm]) == set(cfg["execution"]["costs"]), "missing cost")
        for cost, value in metrics[arm].items():
            checks[f"{arm}_{cost}_execution"] = bool(
                value["execution_complete"]
                and value["critical_failure_count"] == 0
                and value["unresolved_halt_count"] == 0
                and not value["terminal_carried"]
            )
    for cost, value in metrics["primary"].items():
        checks[cost + "_trades"] = value["round_trips"] >= g["minimum_round_trips"]
        checks[cost + "_cagr"] = value["cagr"] >= g["minimum_cagr_each_cost"]
        checks[cost + "_sharpe"] = value["sharpe"] >= g["minimum_sharpe_each_cost"]
        checks[cost + "_drawdown"] = value["maximum_drawdown"] <= g["maximum_drawdown_each_cost"]
        checks[cost + "_positive_years"] = (
            value["positive_years"] >= g["minimum_positive_years_each_cost"]
        )
        checks[cost + "_years"] = sorted(value["annual_returns"]) == g["expected_years"]
        checks[cost + "_worst_year"] = value["worst_year"] >= g["minimum_worst_year_each_cost"]
        checks[cost + "_beats_control"] = value["cagr"] > metrics["control"][cost]["cagr"]
    valid = all(v for k, v in checks.items() if k.endswith("_execution"))
    return {
        "checks": checks,
        "verdict": "STAGE2_CANDIDATE"
        if all(checks.values())
        else ("REJECT_STAGE1" if valid else "INVALID_EXECUTION_NO_PROMOTION"),
        "historical_20_percent_each_cost": valid
        and all(v["cagr"] >= 0.2 for v in metrics["primary"].values()),
        "historical_50_percent_each_cost": valid
        and all(v["cagr"] >= 0.5 for v in metrics["primary"].values()),
        "goal_verified": False,
    }


def run(cfg, parent, storage, expected):
    base.require(os.name == "posix", "economic run must use gpu-mlserver")
    output = base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing canonical run; no repeat")
    verified = {
        "futures": base.preflight(parent, storage),
        "options": source_preflight(cfg, storage),
    }
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    base.write_json(output / "inputs.json", verified)
    source = cfg["source"]
    raw = pd.read_parquet(
        base.safe(storage, source["root"] + "/" + source["processed"]["path"]),
        columns=source["allowed_columns"],
    )
    state = states(raw)
    base.require(len(state) == source["expected_asset_dates"], "state count drift")
    base.require(state.source_date.nunique() == source["expected_source_dates"], "date count drift")
    base.require(set(state.asset_code) == set(cfg["assets"]), "asset drift")
    state.to_parquet(output / "reported_option_states.parquet", index=False)
    quality = {
        "source_rows": len(raw),
        "asset_dates": len(state),
        "ready_asset_dates": int(state.ready.sum()),
        "ready_asset_date_fraction": float(state.ready.mean()),
        "missing_rows": {c: int(raw[c].isna().sum()) for c in VALUE_COLUMNS},
        "all_market_totals_complete": False,
    }
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(storage, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    obs = pd.read_parquet(
        base.safe(storage, declared["observations"]["path"]), columns=base.OBS_COLS
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
    for arm in ARMS:
        signal = targets(active, state, arm, cfg)
        signal.to_parquet(output / f"targets_{arm}.parquet", index=False)
        counts[arm] = {
            "decisions": len(signal),
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
            metrics[arm][cost] = summarize(result)
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


def audit(output, cfg):
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    replays = 0
    for arm, costs in payload["metrics"].items():
        signal = pd.read_parquet(output / f"targets_{arm}.parquet")
        used = signal.loc[signal.target_weight.ne(0)]
        base.require(used.available_at_utc.le(used.decision_at_utc).all(), "future source")
        base.require(used.source_date.lt(used.decision_date).all(), "same-date source")
        for cost, value in costs.items():
            ledger = pd.read_parquet(output / f"ledger_{arm}_{cost}.parquet")
            replay = base._performance_metrics(
                ledger.ending_cash, ledger.session_date, base.CAPITAL
            )
            base.require(all(np.isclose(value[k], v) for k, v in replay.items()), "metric drift")
            position = pd.read_parquet(output / f"positions_{arm}_{cost}.parquet")
            base.require(
                all(value[k] == v for k, v in position_counts(position).items()), "count drift"
            )
            replays += 1
    base.require(replays == 4, "incomplete screen")
    base.require(
        assess(payload["metrics"], payload["source_quality"], cfg) == payload["assessment"],
        "verdict drift",
    )
    return {"artifact_hashes": len(identity["files"]), "metric_replays": replays, "all_true": True}


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
