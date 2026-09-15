"""One fixed archived-GPR risk-persistence screen using the existing futures ledger."""

from __future__ import annotations

import argparse
import io
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v78_treasury_channels as prior
from market_lab.futures import gpr_vintages_source_v2 as source

base, adapter = prior.base, prior.adapter
CONFIG = base.PROJECT / "configs/v80_gpr_risk_v1.json"
SEAL = base.PROJECT / "configs/v80_gpr_risk_v1.seal.json"


def vintage_feature(frame, month, commit_clock, cfg):
    """All thirteen inputs come from this edition, never a later revised edition."""
    start = pd.Timestamp(month + "01")
    dates = frame.month.dropna()
    base.require(
        pd.api.types.is_datetime64_any_dtype(frame.month)
        and not dates.empty and dates.is_monotonic_increasing
        and not dates.duplicated().any() and dates.lt(base.BOUNDARY).all()
        and dates.le(start).all(), "invalid or protected GPR months",
    )
    n = cfg["signal"]["mean_lookback_months"]
    recent = frame.loc[frame.month.lt(start)].tail(n + 1)
    expected = pd.period_range(start.to_period("M") - n - 1,
                               start.to_period("M") - 1, freq="M")
    calendar = recent.month.dt.to_period("M").tolist() == expected.tolist()
    values = recent[cfg["source"]["variable"]].astype(float)
    valid = values.notna() & np.isfinite(values) & values.between(0, 100)
    ready = bool(calendar and valid.all())
    clock = pd.Timestamp(commit_clock)
    base.require(clock.tzinfo is not None, "untimed commit proxy")
    available = max(clock.tz_convert("UTC"), start.tz_localize("UTC")) + pd.Timedelta(
        days=cfg["signal"]["commit_proxy_lag_calendar_days"]
    )
    latest = float(values.iloc[-1]) if calendar and valid.iloc[-1] else np.nan
    mean = float(values.iloc[:-1].mean()) if ready else np.nan
    return {
        "edition": month, "source_date": start - pd.Timedelta(days=1),
        "available_at_utc": available, "ready": ready,
        "latest_complete_month_percent": latest, "prior12_mean_percent": mean,
        "risk_change_percent": latest - mean if ready else np.nan,
        "reason": "ready" if ready else "incomplete_or_invalid_prior13_window",
    }


def read_sources(cfg, storage):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "source manifest")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(
        manifest["source_seal_sha256"] == spec["seal_sha256"]
        and manifest["status"] == "SOURCE_METADATA_COMPLETE"
        and manifest["all_46_vintages"] and not manifest["economic_admission"]
        and [item["month"] for item in manifest["vintages"]] == source.plan(),
        "source scope drift",
    )
    records, undated, raw_bytes = [], 0, 0
    for item in manifest["vintages"]:
        month = item["month"]
        folder = base.safe(root, month)
        base.require(
            item == json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig")),
            "vintage manifest drift",
        )
        blobs = {}
        for filename, key in (("commits.json", "history"), ("data.dta", "raw")):
            raw = (folder / filename).read_bytes()
            base.require(
                source.sha(raw) == item[key]["sha256"] and len(raw) == item[key]["bytes"],
                "vintage file drift",
            )
            blobs[key] = raw
        commit = source.first_commit(blobs["history"])
        base.require(
            commit == item["commit"] and item["history"]["url"] == source.history_url(month)
            and item["raw"]["url"] == source.raw_url(month, commit["commit"]), "commit drift",
        )
        meta = source.metadata(blobs["raw"], month)  # Validate dates BEFORE reading values.
        base.require(meta == item["metadata"], "vintage metadata drift")
        base.require(meta["columns"][spec["variable"]] == spec["variable_label"], "GPR unit")
        frame = pd.read_stata(io.BytesIO(blobs["raw"]), columns=spec["allowed_columns"])
        record = vintage_feature(frame, month, commit["commit_timestamp_proxy"], cfg)
        record.update(source_url=item["raw"]["url"], raw_sha256=item["raw"]["sha256"])
        records.append(record)
        undated += meta["undated_rows_preserved_not_used"]
        raw_bytes += item["raw"]["bytes"]
    raw = pd.DataFrame(records).sort_values("edition", ignore_index=True)
    quality = {
        "vintages": len(raw), "raw_bytes": raw_bytes, "undated_rows_retained": undated,
        "ready_windows": int(raw.ready.sum()), "invalid_windows": int((~raw.ready).sum()),
        "original_public_push_time_verified": False, "archived_first_commit_content": True,
    }
    base.require(all(quality[k] == spec[k] for k in (
        "vintages", "raw_bytes", "undated_rows_retained")), "source totals drift")
    return raw, quality


def states(raw, cfg):
    d = raw.sort_values(["available_at_utc", "source_date"], ignore_index=True).copy()
    base.require(not d.edition.duplicated().any(), "duplicate edition")
    base.require(d.source_date.lt(base.BOUNDARY).all(), "protected state")
    d["dominated_late_vintage"] = d.source_date.lt(d.source_date.cummax())
    d = d.loc[~d.dominated_late_vintage & d.available_at_utc.lt("2026-01-01T00:00:00Z")]
    risk = np.sign(d.risk_change_percent).where(d.ready, 0.0)
    parts = []
    for asset in cfg["assets"]:
        part = d.copy()
        part["asset_code"] = asset
        part["primary_direction"] = risk * cfg["stress_directions"][asset]
        part["control_direction"] = d.ready.astype(float) * cfg["stress_directions"][asset]
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def feasibility(state, cfg, active):
    signals = {arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}
    s = signals["primary"]
    one = state.loc[state.asset_code.eq(cfg["assets"][0])]
    q = {
        "ready_asset_date_fraction": float((~(s.feature_unavailable | s.stale_at_fill)).mean()),
        "ready_source_dates": int(one.loc[one.ready, "source_date"].nunique()),
        "asset_decisions": len(s), "decision_dates": int(s.decision_date.nunique()),
        "feature_unavailable": int(s.feature_unavailable.sum()),
        "stale_at_fill": int(s.stale_at_fill.sum()),
        "source_unavailable": int(s.source_unavailable.sum()),
        "gpr_values_evaluated": True, "moex_prices_or_pnl_read_for_feasibility": False,
    }
    g = cfg["screen_gates"]
    q["pass"] = (q["ready_asset_date_fraction"] >= g["minimum_ready_asset_date_fraction"]
                 and q["ready_source_dates"] >= g["minimum_ready_source_dates"])
    return signals, q


def load(expected):
    base.require(base.sha(SEAL) == expected, "V80 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V80 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    _, parent = prior.load(cfg["parent_v78_seal_sha256"])
    source.verify(cfg["source"]["seal_sha256"])
    base.require(cfg["assets"] == ["BR", "MIX", "SI"], "asset drift")
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg, parent


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--storage-root", required=True, type=Path)
    cli.add_argument("--feasibility-only", action="store_true")
    cli.add_argument("--audit", action="store_true")
    args = cli.parse_args()
    base.require(
        os.name == "posix" and os.getuid() == 999
        and str(args.storage_root.resolve()) == "/srv/trading_lab_data", "server user only",
    )
    base.require(not (args.audit and args.feasibility_only), "choose one mode")
    cfg, parent = load(args.seal_sha)
    name = cfg["protocol_id"] + "_" + args.seal_sha[:12]
    output = base.safe(args.storage_root, "runs/" + name)
    probe = base.safe(args.storage_root, "runs/" + name + "_feasibility")
    if not args.audit:
        base.require(not (probe if args.feasibility_only else output).exists(), "no rerun")
    verified = base.preflight(parent, args.storage_root)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(args.storage_root, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    raw, source_quality = read_sources(cfg, args.storage_root)
    state = states(raw, cfg)
    signals, coverage = feasibility(state, cfg, active)
    quality = {**coverage, "source": source_quality}
    if args.feasibility_only:
        probe.mkdir(parents=True, exist_ok=False)
        base.write_json(probe / "feasibility.json", {
            "seal_sha256": args.seal_sha, "quality": quality,
            "market_price_load_performed": False, "economic_run_performed": False,
        })
        print(json.dumps({"output": str(probe), "quality": quality}), flush=True)
        return
    base.require(coverage["pass"], "source clock/count gate failed before price load")
    if args.audit:
        identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run identity drift")
        for name, digest in identity["files"].items():
            base.require(base.sha(base.safe(output, name)) == digest, "run artifact drift")
        payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        case = payload["case"]
        pd.testing.assert_frame_equal(raw, pd.read_parquet(output / "gpr_vintages.parquet"))
        pd.testing.assert_frame_equal(state, pd.read_parquet(output / "states.parquet"))
        base.require(case == json.loads((output / "case/metrics.json").read_text(
            encoding="utf-8-sig")), "case drift")
        base.require(case["source_quality"] == quality and payload["feasibility"] == coverage
                     and case["counts"] == prior.target_counts(signals), "quality drift")
        count = prior.prior.replay(output / "case", case, signals, quality, cfg)
        print(json.dumps({"artifact_hashes": len(identity["files"]),
                          "raw_dta_commit_state_target_replay": True,
                          "metric_annual_count_cash_replays": count, "all_true": True}))
        return
    output.mkdir(parents=True, exist_ok=False)
    base.write_json(output / "inputs.json", {"source": cfg["source"], "futures": verified})
    raw.to_parquet(output / "gpr_vintages.parquet", index=False)
    state.to_parquet(output / "states.parquet", index=False)
    started = time.monotonic()
    market = prior.market_inputs(args.storage_root, declared, cfg)
    case = prior.simulate_case(output / "case", signals, market, quality, cfg, "gpr_risk")
    payload = {"protocol_id": cfg["protocol_id"], "seal_sha256": args.seal_sha, "stage": 1,
               "case": case, "feasibility": coverage, "goal_verified": False,
               "economic_runtime_seconds": time.monotonic() - started,
               "limitations": cfg["limitations"]}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "identity.json", {"seal_sha256": args.seal_sha, "files": {
        str(p.relative_to(output)): base.sha(p) for p in sorted(output.rglob("*")) if p.is_file()
    }})
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


if __name__ == "__main__":
    main()
