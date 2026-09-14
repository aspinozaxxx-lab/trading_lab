"""Fixed real-discount and inflation-compensation screens; no new execution engine."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import time
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from market_lab import futures_v76_initial_claims_cycle as prior

base, shared, adapter = prior.base, prior.shared, prior.adapter
CONFIG = base.PROJECT / "configs/v78_treasury_channels_v1.json"
SEAL = base.PROJECT / "configs/v78_treasury_channels_v1.seal.json"


def read_quote_csv(path, series, *, metadata_only=False):
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
    base.require(reader.fieldnames == ["observation_date", series], "quote CSV schema")
    rows = []
    for row in reader:
        base.require(set(row) == set(reader.fieldnames), "CSV row width")
        text = row["observation_date"]
        base.require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)), "non-ISO quote date")
        day = pd.Timestamp(text)
        base.require(pd.Timestamp("2017-01-01") <= day < base.BOUNDARY, "protected quote")
        text = row[series]
        valid = text not in ("", ".")
        base.require(
            not valid or bool(re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", text)), "quote format"
        )
        record = {"source_date": day, series + "_valid": valid}
        if not metadata_only:
            record[series + "_bps"] = float(Decimal(text) * 100) if valid else np.nan
        rows.append(record)
    frame = pd.DataFrame(rows)
    base.require(len(frame) > 0, "empty quote source")
    base.require(
        frame.source_date.is_monotonic_increasing and not frame.source_date.duplicated().any(),
        "duplicate/unordered quotes",
    )
    quality = {
        "rows": len(frame),
        "minimum_date": str(frame.source_date.min().date()),
        "maximum_date": str(frame.source_date.max().date()),
        "missing_values": int((~frame[series + "_valid"]).sum()),
    }
    return frame, quality


def read_sources(cfg, storage, *, metadata_only=False):
    declaration = cfg["source"]
    root = base.safe(storage, declaration["root"])
    base.require(base.sha(root / "manifest.json") == declaration["manifest_sha256"], "manifest")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(
        manifest["all_true"] and manifest["protocol_sha256"] == declaration["protocol_sha256"],
        "source protocol drift",
    )
    frames, quality = [], {}
    for series, info in declaration["series"].items():
        path = base.safe(root, info["path"])
        base.require(
            path.stat().st_size == info["bytes"] and base.sha(path) == info["sha256"],
            "source file drift",
        )
        frame, q = read_quote_csv(path, series, metadata_only=metadata_only)
        base.require(all(q[key] == info[key] for key in q), "source metadata drift")
        frames.append(frame)
        quality[series] = q
    pair = frames[0].merge(frames[1], on="source_date", how="outer", validate="one_to_one")
    pair = pair.sort_values("source_date", ignore_index=True)
    for series in declaration["series"]:
        pair[series + "_valid"] = pair[series + "_valid"].astype("boolean").fillna(False)
    return pair, quality


def clock_states(raw, cfg):
    """Only dates and presence masks are needed; availability covers every input."""
    base.require(
        raw.source_date.notna().all()
        and raw.source_date.lt(base.BOUNDARY).all()
        and not raw.source_date.duplicated().any(),
        "invalid state dates",
    )
    d = raw.loc[raw.DGS10_valid | raw.DFII10_valid].copy()
    d = d.sort_values("source_date", ignore_index=True)
    base.require(not d.empty, "no observed quotes")
    sig = cfg["signal"]
    business_day = pd.offsets.CustomBusinessDay(
        calendar=USFederalHolidayCalendar(), holidays=sig["extra_federal_closures"]
    )
    available = d.source_date.map(
        lambda day: day + sig["availability_lag_federal_business_days"] * business_day
    )
    for day, floor in sig["availability_date_floors"].items():
        selected = d.source_date.eq(day)
        available.loc[selected] = available.loc[selected].clip(lower=pd.Timestamp(floor))
    local_end = available + pd.Timedelta(hours=23, minutes=59, seconds=59)
    d["quote_available_at_utc"] = local_end.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    n = sig["lookback_observations"] + 1
    complete = d.DGS10_valid & d.DFII10_valid
    gaps = d.source_date.diff().dt.days.rolling(n - 1).max()
    span = (d.source_date - d.source_date.shift(n - 1)).dt.days
    d["ready"] = (
        complete.rolling(n).sum().eq(n)
        & gaps.le(sig["maximum_observation_gap_calendar_days"])
        & span.le(sig["maximum_window_calendar_days"])
    )
    seconds = d.quote_available_at_utc.astype("int64") // 1_000_000_000
    d["available_at_utc"] = pd.to_datetime(
        seconds.rolling(n, min_periods=1).max(), unit="s", utc=True
    )
    d["reason"] = np.where(d.ready, "ready", "incomplete_or_gapped_quote_window")
    d["source_url"] = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DFII10#date="
        + d.source_date.dt.strftime("%Y-%m-%d")
    )
    if "DFII10_bps" in d:
        d["real_change_bps"] = d.DFII10_bps - d.DFII10_bps.shift(n - 1)
        compensation = d.DGS10_bps - d.DFII10_bps
        d["compensation_change_bps"] = compensation - compensation.shift(n - 1)
    # Late historical-window corrections cannot replace a newer observation already known.
    d = d.sort_values(["available_at_utc", "source_date"], ignore_index=True)
    d["dominated_late_window"] = d.source_date.lt(d.source_date.cummax())
    return d


def states(raw, cfg, variant):
    d = clock_states(raw, cfg)
    d = d.loc[~d.dominated_late_window & d.available_at_utc.lt("2026-01-01T00:00:00Z")].copy()
    if variant == "metadata":
        risk_on = d.ready.astype(float)  # Coverage probe only; never saved as forecasts.
    elif variant == "real_discount":
        risk_on = (-np.sign(d.real_change_bps)).where(d.ready, 0.0)
    elif variant == "inflation_compensation":
        risk_on = np.sign(d.compensation_change_bps).where(d.ready, 0.0)
    else:
        raise ValueError("unknown variant")
    parts = []
    for asset in cfg["assets"]:
        part = d.copy()
        part["asset_code"] = asset
        part["primary_direction"] = risk_on * cfg["risk_on_directions"][asset]
        part["control_direction"] = d.ready.astype(float) * cfg["risk_on_directions"][asset]
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def load(expected):
    base.require(base.sha(SEAL) == expected, "V78 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V78 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    _, parent = prior.load(cfg["parent_v76_seal_sha256"])
    base.require(cfg["variants"] == ["real_discount", "inflation_compensation"], "variant drift")
    base.require(cfg["assets"] == ["BR", "MIX", "SI"], "asset drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg, parent


def target_counts(signals):
    return {
        arm: {
            "decisions": len(s),
            "decision_dates": int(s.decision_date.nunique()),
            "nonzero_targets": int(s.target_weight.ne(0).sum()),
            "used_releases": int(s.loc[s.target_weight.ne(0), "source_url"].nunique()),
            "feature_unavailable": int(s.feature_unavailable.sum()),
            "source_unavailable": int(s.source_unavailable.sum()),
            "stale_at_fill": int(s.stale_at_fill.sum()),
        }
        for arm, s in signals.items()
    }


def feasibility(raw, cfg, active):
    state = states(raw, cfg, "metadata")
    signal = adapter.targets(active, state, "primary", cfg)
    one = state.loc[state.asset_code.eq(cfg["assets"][0])]
    q = {
        "ready_asset_date_fraction": float(
            (~(signal.feature_unavailable | signal.stale_at_fill)).mean()
        ),
        "ready_source_dates": int((one.ready & one.source_date.ge(cfg["period"]["start"])).sum()),
        "source_state_rows": len(state),
        "state_dates": int(state.source_date.nunique()),
        "source_unavailable": int(signal.source_unavailable.sum()),
        "feature_unavailable": int(signal.feature_unavailable.sum()),
        "stale_at_fill": int(signal.stale_at_fill.sum()),
        "asset_decisions": len(signal),
        "original_vintages_proved": False,
        "quote_values_evaluated": False,
        "moex_prices_or_pnl_read": False,
    }
    q["pass"] = (
        q["ready_asset_date_fraction"] >= cfg["screen_gates"]["minimum_ready_asset_date_fraction"]
        and q["ready_source_dates"] >= cfg["screen_gates"]["minimum_ready_source_dates"]
    )
    return q


def market_inputs(storage, declared, cfg):
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
    return market.loc[
        market.asset_code.isin(cfg["assets"])
        & pd.to_datetime(market.session_date).between(cfg["period"]["start"], cfg["period"]["end"])
    ]


def simulate_case(output, signals, market, quality, cfg, variant):
    output.mkdir(exist_ok=False)
    metrics = {}
    for arm, signal in signals.items():
        signal.to_parquet(output / f"targets_{arm}.parquet", index=False)
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
            print(json.dumps({"completed": variant, "arm": arm, "cost": cost}), flush=True)
    payload = {
        "variant": variant,
        "metrics": metrics,
        "counts": target_counts(signals),
        "source_quality": quality,
        "assessment": adapter.assess(metrics, quality, cfg),
    }
    base.write_json(output / "metrics.json", payload)
    return payload


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--storage-root", required=True, type=Path)
    cli.add_argument("--feasibility-only", action="store_true")
    cli.add_argument("--audit", action="store_true")
    args = cli.parse_args()
    base.require(
        os.name == "posix" and str(args.storage_root.resolve()) == "/srv/trading_lab_data",
        "server only",
    )
    base.require(not (args.audit and args.feasibility_only), "choose one mode")
    cfg, parent = load(args.seal_sha)
    verified = base.preflight(parent, args.storage_root)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(args.storage_root, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    metadata, source_quality = read_sources(cfg, args.storage_root, metadata_only=True)
    coverage = feasibility(metadata, cfg, active)
    name = cfg["protocol_id"] + "_" + args.seal_sha[:12]
    output = base.safe(args.storage_root, "runs/" + name)
    if args.feasibility_only:
        target = base.safe(args.storage_root, "runs/" + name + "_feasibility")
        target.mkdir(parents=True, exist_ok=False)
        base.write_json(
            target / "feasibility.json",
            {
                "seal_sha256": args.seal_sha,
                "source_quality": source_quality,
                "coverage": coverage,
                "market_price_load_performed": False,
                "economic_run_performed": False,
            },
        )
        print(json.dumps({"output": str(target), "coverage": coverage}), flush=True)
        return
    # Even if an operator skips the separate CLI probe, no outcome load before these gates.
    base.require(coverage["pass"], "source clock/count gate failed before price load")
    raw, same_quality = read_sources(cfg, args.storage_root)
    base.require(source_quality == same_quality, "metadata/numeric parser mismatch")
    quality = {
        k: v
        for k, v in coverage.items()
        if k not in ("quote_values_evaluated", "moex_prices_or_pnl_read")
    }
    quality["series"] = source_quality
    if args.audit:
        identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run seal drift")
        for name, digest in identity["files"].items():
            base.require(base.sha(base.safe(output, name)) == digest, "run artifact drift")
        payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        base.require(payload["feasibility"] == coverage, "feasibility drift")
        pd.testing.assert_frame_equal(raw, pd.read_parquet(output / "treasury_quotes.parquet"))
        total = 0
        for variant in cfg["variants"]:
            state = states(raw, cfg, variant)
            signals = {
                arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")
            }
            case = payload["variants"][variant]
            folder = output / variant
            pd.testing.assert_frame_equal(state, pd.read_parquet(folder / "states.parquet"))
            base.require(
                case == json.loads((folder / "metrics.json").read_text(encoding="utf-8-sig")),
                "case copy drift",
            )
            base.require(
                case["counts"] == target_counts(signals) and case["source_quality"] == quality,
                "case metadata drift",
            )
            total += prior.replay(folder, case, signals, quality, cfg)
        base.require(
            payload["variants"][cfg["variants"][0]]["metrics"]["control"]
            == payload["variants"][cfg["variants"][1]]["metrics"]["control"],
            "control drift",
        )
        print(
            json.dumps(
                {
                    "artifact_hashes": len(identity["files"]),
                    "metric_count_cash_replays": total,
                    "raw_csv_state_target_replay": True,
                    "all_true": True,
                }
            )
        )
        return
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    base.write_json(output / "inputs.json", {"source": cfg["source"], "futures": verified})
    raw.to_parquet(output / "treasury_quotes.parquet", index=False)
    market = market_inputs(args.storage_root, declared, cfg)
    cases = {}
    for variant in cfg["variants"]:
        state = states(raw, cfg, variant)
        signals = {arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}
        cases[variant] = simulate_case(output / variant, signals, market, quality, cfg, variant)
        state.to_parquet(output / variant / "states.parquet", index=False)
    base.require(
        cases[cfg["variants"][0]]["metrics"]["control"]
        == cases[cfg["variants"][1]]["metrics"]["control"],
        "control mismatch",
    )
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": args.seal_sha,
        "stage": 1,
        "variants": cases,
        "feasibility": coverage,
        "goal_verified": False,
        "economic_runtime_seconds": time.monotonic() - started,
        "limitations": cfg["limitations"],
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": args.seal_sha,
            "files": {
                str(p.relative_to(output)): base.sha(p)
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(
        json.dumps(
            {"output": str(output), "assessments": {k: v["assessment"] for k, v in cases.items()}}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
