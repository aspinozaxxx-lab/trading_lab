"""Cheap same-expiry SBER/SBERP event screen, not a portfolio backtest."""

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

CONFIG = base.PROJECT / "configs/v73_sber_share_class_pair_v1.json"
SEAL = base.PROJECT / "configs/v73_sber_share_class_pair_v1.seal.json"
COLUMNS = [
    "timestamp",
    "end_timestamp",
    "available_at",
    "contract_id",
    "stock_secid",
    "close",
    "open",
    "volume",
]


def load(expected):
    base.require(base.sha(SEAL) == expected, "V73 seal drift")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V73 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(
        cfg["protected_from"] == "2026-01-01" and not cfg["goal_verified"], "boundary/goal"
    )
    return cfg, parent


def preflight(cfg, parent, storage):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    for name in ("manifest.json", "audit.json"):
        base.require(base.sha(root / name) == spec[name], "source identity drift")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(
        manifest["source_only"]
        and not manifest["contains_basis_returns_targets_signals_predictions_equity_or_pnl"],
        "not source",
    )
    base.require(
        json.loads((root / "audit.json").read_text(encoding="utf-8-sig"))["all_true"],
        "source audit",
    )
    for role, item in manifest["artifacts"].items():
        path = base.safe(root, item["file"])
        base.require(
            path.stat().st_size == item["bytes"] and base.sha(path) == item["sha256"],
            "artifact drift",
        )
        if role != "raw":
            base.require(pq.ParquetFile(path).metadata.num_rows == item["rows"], "row drift")
    dates = pd.read_parquet(root / "futures_10m.parquet", columns=["timestamp", "available_at"])
    for column in dates:
        values = pd.to_datetime(dates[column], utc=True)
        base.require(
            values.notna().all()
            and values.ge("2023-01-01T00:00:00Z").all()
            and values.lt("2026-01-01T00:00:00Z").all(),
            "protected candles",
        )
    cal = base.declarations(parent)["recent"]["active_map"]
    path = base.safe(storage, cal["path"])
    base.require(
        base.sha(path) == cal["sha256"] and path.stat().st_size == cal["bytes"], "calendar identity"
    )
    days = pd.to_datetime(pd.read_parquet(path, columns=["effective_date"]).effective_date)
    base.require(days.notna().all() and days.lt(base.BOUNDARY).all(), "protected calendar")
    evidence = cfg["method_evidence"]
    pdf = base.safe(storage, evidence["path"])
    base.require(
        base.sha(pdf) == evidence["sha256"] and pdf.stat().st_size == evidence["bytes"],
        "policy evidence drift",
    )
    return {
        "all_true": True,
        "source_manifest": spec["manifest.json"],
        "calendar": cal,
        "method_evidence": evidence,
    }


def inputs(cfg, parent, storage):
    root = base.safe(storage, cfg["source"]["root"])
    spec = pd.read_parquet(root / "contract_specs.parquet")
    spec = spec.loc[spec.stock_secid.isin(["SBER", "SBERP"])].copy()
    base.require(
        len(spec) == 24 and spec.lot_size_shares.eq(100).all() and spec.board_id.eq("RFUD").all(),
        "pair identity",
    )
    raw = pd.read_parquet(
        root / "futures_10m.parquet",
        columns=COLUMNS,
        filters=[("stock_secid", "in", ["SBER", "SBERP"])],
    )
    declaration = base.declarations(parent)["recent"]["active_map"]
    days = pd.to_datetime(
        pd.read_parquet(
            base.safe(storage, declaration["path"]), columns=["effective_date"]
        ).effective_date
    )
    calendar = pd.DatetimeIndex(
        sorted(days.loc[days.between(cfg["period"]["start"], cfg["period"]["end"])].unique())
    )
    return spec, raw, calendar


def normalize(raw):
    d = raw.copy()
    for column in ("timestamp", "end_timestamp", "available_at"):
        d[column] = pd.to_datetime(d[column], utc=True)
        base.require(
            d[column].notna().all() and d[column].lt("2026-01-01T00:00:00Z").all(),
            "protected/null clock",
        )
    base.require(
        d.end_timestamp.ge(d.timestamp).all() and d.available_at.ge(d.end_timestamp).all(),
        "premature availability",
    )
    base.require(not d.duplicated(["contract_id", "timestamp"]).any(), "duplicate candle")
    local = d.timestamp.dt.tz_convert("Europe/Moscow")
    d["day"] = local.dt.tz_localize(None).dt.normalize()
    d["clock"] = local.dt.strftime("%H:%M")
    return d


def candidates(spec, raw, calendar, cfg):
    """Only completed signal closes enter this function; no future opens or PnL."""
    signal = normalize(raw).loc[lambda x: x.clock.eq(cfg["signal"]["bar_clock"])]
    pairs = spec.loc[spec.stock_secid.eq("SBER")].merge(
        spec.loc[spec.stock_secid.eq("SBERP")],
        on="expiration",
        suffixes=("_common", "_preferred"),
        validate="one_to_one",
    )
    frames = {}
    for pair in pairs.itertuples(index=False):
        common = signal.loc[signal.contract_id.eq(pair.contract_id_common)]
        preferred = signal.loc[signal.contract_id.eq(pair.contract_id_preferred)]
        frame = common.merge(
            preferred, on="day", suffixes=("_common", "_preferred"), validate="one_to_one"
        ).sort_values("day")
        frame["decision_at"] = (
            frame.day.dt.tz_localize("Europe/Moscow") + pd.Timedelta(hours=15, minutes=50)
        ).dt.tz_convert("UTC")
        valid = pd.Series(True, index=frame.index)
        for leg in ("common", "preferred"):
            valid &= (
                np.isfinite(frame["close_" + leg])
                & frame["close_" + leg].gt(0)
                & np.isfinite(frame["volume_" + leg])
                & frame["volume_" + leg].gt(0)
            )
            valid &= frame["available_at_" + leg].le(frame.decision_at)
        frame["valid"] = valid
        frame["log_ratio"] = np.log((frame.close_common / frame.close_preferred).where(valid))
        frames[pair.expiration] = frame
    weeks = pd.Series(calendar).groupby(calendar.to_period("W-SUN")).first()
    rows = []
    for day in weeks:
        eligible = pairs.loc[
            (pairs.expiration - day).dt.days.ge(cfg["signal"]["minimum_dte_calendar_days"])
            & pairs.first_trade_common.le(day)
            & pairs.first_trade_preferred.le(day)
        ].sort_values("expiration")
        row = {
            "decision_date": day,
            "selected": False,
            "reason": "no_eligible_pair",
            "common_id": None,
            "preferred_id": None,
            "expiration": pd.NaT,
            "z": np.nan,
            "common_direction": np.nan,
            "history_rows": 0,
        }
        if not eligible.empty:
            pair = eligible.iloc[0]
            row.update(
                common_id=pair.contract_id_common,
                preferred_id=pair.contract_id_preferred,
                expiration=pair.expiration,
            )
            frame = frames[pair.expiration]
            today = frame.loc[frame.day.eq(day) & frame.valid]
            history = frame.loc[
                frame.day.lt(day)
                & frame.day.ge(day - pd.Timedelta(days=cfg["signal"]["maximum_history_span_days"]))
                & frame.valid
            ].tail(cfg["signal"]["lookback_observations"])
            row["history_rows"] = len(history)
            row["reason"] = "missing_completed_pair" if today.empty else "insufficient_history"
            if len(today) == 1 and len(history) == cfg["signal"]["lookback_observations"]:
                median = float(history.log_ratio.median())
                scale = float((history.log_ratio - median).abs().median() * 1.4826)
                row["reason"] = "zero_scale"
                if scale > 1e-10:
                    z = float((today.log_ratio.iloc[0] - median) / scale)
                    selected = abs(z) >= cfg["signal"]["absolute_z_threshold"]
                    row.update(
                        z=z,
                        selected=selected,
                        common_direction=float(-np.sign(z)),
                        reason="selected" if selected else "below_threshold",
                    )
        rows.append(row)
    return pd.DataFrame(rows)


def outcomes(decisions, raw, calendar, cfg):
    """Fixed six daily observations, exact contracts; missing is unresolved, not skipped."""
    fills = (
        normalize(raw)
        .loc[lambda x: x.clock.eq(cfg["execution"]["bar_clock"])]
        .set_index(["day", "contract_id"])
    )
    records = []
    for event in decisions.loc[decisions.selected].itertuples(index=False):
        location = calendar.get_indexer([event.decision_date])[0]
        days = calendar[location + 1 : location + 2 + cfg["execution"]["hold_sessions"]]
        record = {
            "decision_date": event.decision_date,
            "common_id": event.common_id,
            "preferred_id": event.preferred_id,
            "common_direction": event.common_direction,
            "complete": False,
            "reason": "incomplete_future_calendar",
            "entry_date": days[0] if len(days) else pd.NaT,
            "exit_date": days[-1] if len(days) else pd.NaT,
        }
        if len(days) == cfg["execution"]["hold_sessions"] + 1:
            rows = [
                fills.loc[(day, contract)] if (day, contract) in fills.index else None
                for day in days
                for contract in (event.common_id, event.preferred_id)
            ]
            known = all(
                r is not None
                and np.isfinite(r.open)
                and r.open > 0
                and np.isfinite(r.volume)
                and r.volume > 0
                for r in rows
            )
            record["reason"] = "missing_or_inactive_endpoint_or_intermediate_bar"
            if known and days[-1] < event.expiration:
                ec, ep, xc, xp = (float(rows[j].open) for j in (0, 1, -2, -1))
                gross_notional = ec + ep
                delta = (xc - ec) - (xp - ep)
                record.update(
                    complete=True,
                    reason="complete",
                    common_entry=ec,
                    preferred_entry=ep,
                    common_exit=xc,
                    preferred_exit=xp,
                    gross_entry_notional=gross_notional,
                    one_contract_maximum_participation=max(1 / float(r.volume) for r in rows),
                    one_contract_within_one_percent=all(r.volume >= 100 for r in rows),
                )
                for arm, sign in (("primary", event.common_direction), ("control", -1.0)):
                    record[arm + "_gross"] = sign * delta / gross_notional
                    for cost, bps in cfg["execution"]["cost_bps_per_side"].items():
                        paid = bps / 10000 * (ec + ep + xc + xp) / gross_notional
                        record[arm + "_" + cost + "_net"] = record[arm + "_gross"] - paid
                        record[cost + "_cost_fraction"] = paid
        records.append(record)
    return pd.DataFrame(records)


def summarize(decisions, events, cfg):
    base.require(len(events) == int(decisions.selected.sum()), "selected-event count drift")
    complete = events.loc[events.complete] if len(events) else events
    metrics = {}
    for arm in ("primary", "control"):
        metrics[arm] = {}
        for cost in cfg["execution"]["cost_bps_per_side"]:
            values = complete[f"{arm}_{cost}_net"] if len(complete) else pd.Series(dtype=float)
            annual = (
                {
                    str(y): {
                        "events": int((complete.decision_date.dt.year == y).sum()),
                        "mean_net": float(
                            complete.loc[
                                complete.decision_date.dt.year.eq(y), f"{arm}_{cost}_net"
                            ].mean()
                        )
                        if (complete.decision_date.dt.year == y).any()
                        else None,
                    }
                    for y in cfg["screen_gates"]["years"]
                }
                if len(complete)
                else {str(y): {"events": 0, "mean_net": None} for y in cfg["screen_gates"]["years"]}
            )
            metrics[arm][cost] = {
                "completed_events": len(complete),
                "mean_net": float(values.mean()) if len(values) else None,
                "median_net": float(values.median()) if len(values) else None,
                "positive_fraction": float(values.gt(0).mean()) if len(values) else None,
                "mean_gross": float(complete[arm + "_gross"].mean()) if len(values) else None,
                "annual_event_means": annual,
                "cagr": None,
                "sharpe": None,
                "maximum_drawdown": None,
            }
    checks = {
        "minimum_events": len(complete) >= cfg["screen_gates"]["minimum_completed_events"],
        "no_unresolved": len(events) == len(complete),
    }
    for cost, value in metrics["primary"].items():
        checks[cost + "_net_positive"] = value["mean_net"] is not None and value["mean_net"] > 0
        checks[cost + "_median_positive"] = (
            value["median_net"] is not None and value["median_net"] > 0
        )
        checks[cost + "_all_years_positive"] = all(
            v["mean_net"] is not None and v["mean_net"] > 0
            for v in value["annual_event_means"].values()
        )
        checks[cost + "_beats_control"] = (
            value["mean_net"] is not None
            and value["mean_net"] > metrics["control"][cost]["mean_net"]
        )
    verdict = (
        "STAGE2_PORTFOLIO_CANDIDATE"
        if all(checks.values())
        else ("REJECT_STAGE1" if checks["no_unresolved"] else "INCOMPLETE_NO_PROMOTION")
    )
    return {
        "stage": 1,
        "weekly_decisions": len(decisions),
        "selected_events": len(events),
        "completed_events": len(complete),
        "unresolved_events": len(events) - len(complete),
        "source_reason_counts": decisions.reason.value_counts().to_dict(),
        "event_reason_counts": events.reason.value_counts().to_dict() if len(events) else {},
        "one_contract_one_percent_complete_events": int(
            complete.one_contract_within_one_percent.sum()
        )
        if len(complete)
        else 0,
        "metrics": metrics,
        "checks": checks,
        "verdict": verdict,
        "portfolio_backtest": False,
        "goal_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    base.require(
        os.name == "posix" and str(args.storage_root.resolve()) == "/srv/trading_lab_data",
        "server only",
    )
    cfg, parent = load(args.seal_sha)
    verified = preflight(cfg, parent, args.storage_root)
    root = base.safe(args.storage_root, "runs/" + cfg["protocol_id"] + "_" + args.seal_sha[:12])
    if args.audit:
        identity = json.loads((root / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run identity")
        for name, digest in identity["files"].items():
            base.require(base.sha(root / name) == digest, "run artifact drift")
    else:
        root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    spec, raw, calendar = inputs(cfg, parent, args.storage_root)
    # Extraction receives no open columns: later prices cannot select the candidates.
    decisions = candidates(spec, raw.drop(columns="open"), calendar, cfg)
    events = outcomes(decisions, raw, calendar, cfg)
    result = summarize(decisions, events, cfg)
    if args.audit:
        pd.testing.assert_frame_equal(decisions, pd.read_parquet(root / "decisions.parquet"))
        pd.testing.assert_frame_equal(events, pd.read_parquet(root / "events.parquet"))
        saved = json.loads((root / "metrics.json").read_text(encoding="utf-8-sig"))
        base.require(saved["result"] == result, "metric drift")
        print(
            json.dumps(
                {
                    "artifact_hashes": len(identity["files"]),
                    "source_candidate_endpoint_metric_replay": True,
                    "all_true": True,
                }
            )
        )
    else:
        base.write_json(root / "inputs.json", verified)
        decisions.to_parquet(root / "decisions.parquet", index=False)
        events.to_parquet(root / "events.parquet", index=False)
        base.write_json(
            root / "metrics.json",
            {
                "protocol_id": cfg["protocol_id"],
                "seal_sha256": args.seal_sha,
                "runtime_seconds": time.monotonic() - started,
                "result": result,
                "limitations": cfg["limitations"],
            },
        )
        base.write_json(
            root / "identity.json",
            {
                "seal_sha256": args.seal_sha,
                "files": {p.name: base.sha(p) for p in sorted(root.iterdir())},
            },
        )
        print(json.dumps({"root": str(root), "result": result}), flush=True)


if __name__ == "__main__":
    main()
