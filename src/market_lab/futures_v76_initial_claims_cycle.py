"""Fixed US labor-claims demand-cycle screen, conditional current-vintage source."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v64_si_tax_calendar as base
from market_lab import futures_v68_reported_option_flow as shared
from market_lab import futures_v72_policy_guidance as adapter

CONFIG = base.PROJECT / "configs/v76_initial_claims_cycle_v1.json"
SEAL = base.PROJECT / "configs/v76_initial_claims_cycle_v1.seal.json"


def read_claims(path):
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
    base.require(reader.fieldnames == ["observation_date", "ICNSA"], "claims CSV schema")
    records = []
    for row in reader:
        base.require(set(row) == set(reader.fieldnames), "malformed CSV row")
        day = pd.Timestamp(row["observation_date"])
        base.require(
            day.tzinfo is None
            and day == day.normalize()
            and day < base.BOUNDARY
            and day.weekday() == 5,
            "invalid/protected week ending",
        )
        text = row["ICNSA"]
        count = np.nan if text in ("", ".") else float(text)
        base.require(
            text in ("", ".") or (np.isfinite(count) and count >= 0 and count.is_integer()),
            "invalid claims count",
        )
        records.append({"source_date": day, "claims": count})
    frame = pd.DataFrame(records)
    base.require(len(frame) > 0, "empty claims")
    base.require(
        frame.source_date.is_monotonic_increasing and not frame.source_date.duplicated().any(),
        "duplicate/unordered source dates",
    )
    quality = {
        "rows": len(frame),
        "minimum_date": str(frame.source_date.min().date()),
        "maximum_date": str(frame.source_date.max().date()),
        "missing_values": int(frame.claims.isna().sum()),
        "all_true": True,
        "original_vintages_proved": False,
    }
    return frame, quality


def states(raw, cfg):
    d = raw.copy().sort_values("source_date", ignore_index=True)
    d["source_date"] = pd.to_datetime(d.source_date)
    base.require(
        d.source_date.notna().all()
        and d.source_date.lt(base.BOUNDARY).all()
        and d.source_date.dt.dayofweek.eq(5).all()
        and not d.source_date.duplicated().any(),
        "invalid state dates",
    )
    count = pd.to_numeric(d.claims, errors="raise")
    base.require(
        (count.isna() | (np.isfinite(count) & count.ge(0) & count.eq(count.round()))).all(),
        "invalid state counts",
    )
    average = cfg["signal"]["average_weeks"]
    lag = cfg["signal"]["seasonal_comparison_weeks"]
    window = lag + average
    d["four_week_mean"] = count.rolling(average, min_periods=average).mean()
    d["prior_year_mean"] = d.four_week_mean.shift(lag)
    d["claims_change"] = d.four_week_mean - d.prior_year_mean
    regular = d.source_date.diff().dt.days.eq(7).rolling(window - 1).sum().eq(window - 1)
    d["ready"] = regular & count.rolling(window).count().eq(window) & d.claims_change.notna()
    # Construct local calendar-end first: adding timedeltas to aware timestamps crosses DST.
    local_end = d.source_date + pd.Timedelta(
        days=cfg["signal"]["availability_lag_calendar_days"], hours=23, minutes=59, seconds=59
    )
    d["available_at_utc"] = local_end.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    d = d.loc[d.available_at_utc.lt("2026-01-01T00:00:00Z")].copy()
    d["reason"] = np.where(d.ready, "ready", "missing_or_irregular_56week_history")
    d["source_url"] = cfg["source"]["url"] + "#week=" + d.source_date.dt.strftime("%Y-%m-%d")
    risk_on = (-np.sign(d.claims_change)).where(d.ready, 0.0)
    parts = []
    for asset in cfg["assets"]:
        part = d.copy()
        part["asset_code"] = asset
        sign = cfg["risk_on_directions"][asset]
        part["primary_direction"] = risk_on * sign
        part["control_direction"] = d.ready.astype(float) * sign
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def load(expected):
    base.require(base.sha(SEAL) == expected, "V76 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V76 frozen file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    _, parent = adapter.load(cfg["parent_v72_seal_sha256"])
    base.require(
        cfg["assets"] == ["BR", "MIX", "SI"] and cfg["protected_from"] == "2026-01-01",
        "scope drift",
    )
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg, parent


def preflight(cfg, parent, storage):
    declaration = cfg["source"]
    path = base.safe(storage, declaration["path"])
    base.require(
        path.stat().st_size == declaration["bytes"] and base.sha(path) == declaration["sha256"],
        "source identity drift",
    )
    claims, quality = read_claims(path)
    for key in ("rows", "minimum_date", "maximum_date", "missing_values"):
        base.require(quality[key] == declaration[key], "source metadata drift: " + key)
    return (
        claims,
        quality,
        {
            "source": declaration,
            "source_checks": quality,
            "futures": base.preflight(parent, storage),
            "all_true": True,
        },
    )


def replay(output, payload, signals, quality, cfg):
    replays = 0
    for arm, costs in payload["metrics"].items():
        pd.testing.assert_frame_equal(
            signals[arm], pd.read_parquet(output / f"targets_{arm}.parquet")
        )
        used = signals[arm].loc[signals[arm].target_weight.ne(0)]
        base.require(
            used.available_at_utc.le(used.decision_at_utc).all()
            and used.decision_date.lt(used.effective_date).all(),
            "future signal/fill",
        )
        for cost, value in costs.items():
            ledger = pd.read_parquet(output / f"ledger_{arm}_{cost}.parquet")
            metrics = base._performance_metrics(
                ledger.ending_cash, ledger.session_date, base.CAPITAL
            )
            base.require(all(np.isclose(value[k], v) for k, v in metrics.items()), "metric drift")
            days = pd.to_datetime(ledger.session_date)
            base.require(days.lt(base.BOUNDARY).all(), "protected ledger")
            daily = ledger.ending_cash / ledger.starting_cash - 1
            annual = {
                str(y): float(np.prod(1 + daily.loc[days.dt.year.eq(y)]) - 1)
                for y in sorted(days.dt.year.unique())
            }
            base.require(
                set(annual) == set(value["annual_returns"])
                and all(np.isclose(value["annual_returns"][k], v) for k, v in annual.items()),
                "annual drift",
            )
            pos = pd.read_parquet(output / f"positions_{arm}_{cost}.parquet")
            base.require(
                all(value[k] == v for k, v in shared.position_counts(pos).items()),
                "trade count drift",
            )
            orders = pd.read_parquet(output / f"orders_{arm}_{cost}.parquet")
            filled = orders.loc[orders.filled]
            paid = filled.commission_cost.sum() + filled.slippage_cost.sum()
            base.require(
                np.isclose(paid, value["total_cost"])
                and np.isclose(ledger.variation_margin.sum() - paid, value["net_pnl"]),
                "cash drift",
            )
            replays += 1
    base.require(
        replays == 4 and payload["assessment"] == adapter.assess(payload["metrics"], quality, cfg),
        "assessment drift",
    )
    return replays


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--storage-root", required=True, type=Path)
    cli.add_argument("--audit", action="store_true")
    args = cli.parse_args()
    base.require(
        os.name == "posix" and str(args.storage_root.resolve()) == "/srv/trading_lab_data",
        "server only",
    )
    cfg, parent = load(args.seal_sha)
    claims, quality, verified = preflight(cfg, parent, args.storage_root)
    output = base.safe(args.storage_root, "runs/" + cfg["protocol_id"] + "_" + args.seal_sha[:12])
    if args.audit:
        identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run seal drift")
        for name, digest in identity["files"].items():
            base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    else:
        output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    state = states(claims, cfg)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(args.storage_root, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = {arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}
    primary = signals["primary"]
    quality.update(
        ready_asset_date_fraction=float(
            (~(primary.feature_unavailable | primary.stale_at_fill)).mean()
        ),
        source_state_rows=len(state),
        state_dates=int(state.source_date.nunique()),
        ready_states=int(state.ready.sum()),
    )
    counts = {
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
    if args.audit:
        pd.testing.assert_frame_equal(claims, pd.read_parquet(output / "claims.parquet"))
        pd.testing.assert_frame_equal(state, pd.read_parquet(output / "claim_states.parquet"))
        payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        base.require(
            payload["source_quality"] == quality and payload["counts"] == counts, "coverage drift"
        )
        replays = replay(output, payload, signals, quality, cfg)
        print(
            json.dumps(
                {
                    "artifact_hashes": len(identity["files"]),
                    "metric_count_cash_replays": replays,
                    "raw_csv_state_target_replay": True,
                    "all_true": True,
                }
            )
        )
        return
    base.write_json(output / "inputs.json", verified)
    claims.to_parquet(output / "claims.parquet", index=False)
    state.to_parquet(output / "claim_states.parquet", index=False)
    obs = pd.read_parquet(
        base.safe(args.storage_root, declared["observations"]["path"]), columns=base.OBS_COLS
    )
    specs = pd.read_parquet(
        base.safe(args.storage_root, declared["specs"]["path"]),
        columns=sorted(base.SPEC_PROXY_COLUMNS),
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
        market.asset_code.isin(cfg["assets"])
        & pd.to_datetime(market.session_date).between(cfg["period"]["start"], cfg["period"]["end"])
    ]
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
            print(json.dumps({"completed": arm, "cost": cost}), flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": args.seal_sha,
        "stage": 1,
        "metrics": metrics,
        "counts": counts,
        "source_quality": quality,
        "assessment": adapter.assess(metrics, quality, cfg),
        "economic_runtime_seconds": time.monotonic() - started,
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": args.seal_sha,
            "files": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)


if __name__ == "__main__":
    main()
