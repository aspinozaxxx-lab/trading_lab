"""One GOLD managed-money risk-demand hypothesis; reuse the fixed daily ledger."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v78_treasury_channels as engine
from market_lab.futures.cftc_radar import official_development_release_overrides

base, adapter = engine.base, engine.adapter
CONFIG = base.PROJECT / "configs/v87_gold_positioning_risk_v1.json"
SEAL = base.PROJECT / "configs/v87_gold_positioning_risk_v1.seal.json"


def read_gold(cfg, storage):
    """Verify immutable identities and date-only metadata before selected GOLD values."""
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    for name, key in (("manifest.json", "manifest_sha256"), ("audit.json", "audit_sha256")):
        base.require(base.sha(root / name) == spec[key], "source manifest/audit drift")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(manifest["protocol_sha256"] == spec["protocol_sha256"]
                 and manifest["source_only"]
                 and not manifest["contains_moex_price_return_target_signal_trade_or_pnl"],
                 "source scope drift")
    for kind in ("processed", "raw"):
        declared = spec[kind]
        base.require(all(manifest[kind][k] == v for k, v in declared.items()), "source record")
        path = base.safe(root, declared["file"])
        base.require(path.stat().st_size == declared["bytes"]
                     and base.sha(path) == declared["sha256"], "source byte drift")
    path = root / spec["processed"]["file"]
    pf = pq.ParquetFile(path)
    base.require(pf.metadata.num_rows == spec["processed"]["rows"]
                 and set(spec["allowed_columns"]) <= set(pf.schema_arrow.names), "source schema")
    meta = pd.read_parquet(path, columns=["report_date", "logical_market",
                                         "cftc_contract_market_code"])
    dates = pd.to_datetime(meta.report_date)
    base.require(dates.notna().all() and dates.lt(base.BOUNDARY).all()
                 and str(dates.min().date()) == spec["minimum_report_date"]
                 and str(dates.max().date()) == spec["maximum_report_date"]
                 and not meta.duplicated(["logical_market", "report_date"]).any(), "source dates")
    gold_meta = meta.loc[meta.logical_market.eq("GOLD")]
    base.require(len(gold_meta) == spec["gold_rows"]
                 and gold_meta.cftc_contract_market_code.eq("088691").all(), "gold identity")
    return pd.read_parquet(path, columns=spec["allowed_columns"],
                           filters=[("logical_market", "==", "GOLD")])


def report_clock(day, cfg):
    """Old uniform7day clock is NOT accepted during documented delays/corrections."""
    dates = [day + pd.Timedelta(days=7)]
    official = official_development_release_overrides().get(day.date())
    if official is not None:
        dates.append(official.tz_convert("America/New_York").tz_localize(None).normalize())
    correction = cfg["source"]["gold_correction_date_floors"].get(str(day.date()))
    if correction:
        dates.append(pd.Timestamp(correction))
    return ((max(dates) + pd.Timedelta(days=1)).tz_localize("America/New_York")
            - pd.Timedelta(seconds=1)).tz_convert("UTC")


def states(raw, cfg):
    d = raw.copy().sort_values("report_date", ignore_index=True)
    d["source_date"] = pd.to_datetime(d.report_date)
    base.require(not d.empty and d.logical_market.eq("GOLD").all()
                 and d.cftc_contract_market_code.eq("088691").all(), "only declared gold")
    base.require(d.source_date.notna().all() and d.source_date.lt(base.BOUNDARY).all()
                 and d.source_date.ge("2018-01-01").all()
                 and not d.source_date.duplicated().any(), "invalid report dates")
    fields = ["open_interest", "managed_money_long", "managed_money_short"]
    numbers = d[fields].apply(pd.to_numeric, errors="coerce").astype(float)
    valid = (np.isfinite(numbers).all(axis=1) & numbers.ge(0).all(axis=1)
             & numbers.eq(np.floor(numbers)).all(axis=1) & numbers.open_interest.gt(0)
             & numbers.managed_money_long.le(numbers.open_interest)
             & numbers.managed_money_short.le(numbers.open_interest))
    d["position_values_valid"] = valid
    lag = cfg["signal"]["lookback_reports"]
    n = lag + 1
    d["report_available_at_utc"] = d.source_date.map(lambda day: report_clock(day, cfg))
    # Every row in the completeness window must be known; delayed old values cannot leak.
    d["available_at_utc"] = pd.Series([
        d.report_available_at_utc.iloc[max(0, i - lag):i + 1].max() for i in range(len(d))
    ], dtype="datetime64[ns, UTC]")
    gaps = d.source_date.diff().dt.days.rolling(lag).max()
    span = (d.source_date - d.source_date.shift(lag)).dt.days
    d["ready"] = (valid.rolling(n).sum().eq(n)
                  & gaps.le(cfg["signal"]["maximum_report_gap_calendar_days"])
                  & span.le(cfg["signal"]["maximum_window_calendar_days"]))
    net = numbers.managed_money_long - numbers.managed_money_short
    d["net_share"] = (net / numbers.open_interest).where(valid)
    d["change_over13reports"] = (d.net_share - d.net_share.shift(lag)).where(d.ready)
    direction = []
    for i, ready in enumerate(d.ready):
        if not ready:
            direction.append(0)
            continue
        # Exact integer cross-products avoid sign changes from float rounding near zero.
        difference = (int(net.iloc[i]) * int(numbers.open_interest.iloc[i - lag])
                      - int(net.iloc[i - lag]) * int(numbers.open_interest.iloc[i]))
        direction.append(int(difference > 0) - int(difference < 0))
    d["risk_off_direction"] = direction
    d["reason"] = np.where(d.ready, "ready", "incomplete_or_gapped_report_window")
    d["source_url"] = ("https://www.cftc.gov/files/dea/history/fut_disagg_txt_"
                       + d.source_date.dt.strftime("%Y") + ".zip#GOLD-"
                       + d.source_date.dt.strftime("%Y-%m-%d"))
    d = d.sort_values(["available_at_utc", "source_date"], ignore_index=True)
    d["dominated_late_window"] = d.source_date.lt(d.source_date.cummax())
    eligible = d.loc[~d.dominated_late_window
                     & d.available_at_utc.lt("2026-01-01T00:00:00Z")].copy()
    parts = []
    for asset in cfg["assets"]:
        part = eligible.copy()
        part["asset_code"] = asset
        part["primary_direction"] = part.risk_off_direction * cfg["risk_off_directions"][asset]
        part["control_direction"] = part.ready.astype(int) * cfg["risk_off_directions"][asset]
        parts.append(part)
    return d, pd.concat(parts, ignore_index=True)


def load(expected):
    base.require(base.sha(SEAL) == expected, "V87 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V87 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["assets"] == ["MIX", "SI"] and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"]
                 and cfg["execution"]["initial_cash_rub"] == base.CAPITAL, "scope")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--audit", action="store_true")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    cfg, parent = load(args.seal_sha)
    storage = Path("/srv/trading_lab_data")
    output = storage / "runs" / (cfg["protocol_id"] + "_" + args.seal_sha[:12])
    base.require(args.audit or not output.exists(), "no canonical rerun")
    verified = base.preflight(parent, storage)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(storage, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    raw = read_gold(cfg, storage)
    reports, state = states(raw, cfg)
    signals = {arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}
    signal = signals["primary"]
    q = {"ready_asset_date_fraction": float((~(signal.feature_unavailable |
                                              signal.stale_at_fill)).mean()),
         "ready_source_dates": int((reports.ready & reports.source_date.between(
             cfg["period"]["start"], cfg["period"]["end"])
             & reports.available_at_utc.lt("2026-01-01T00:00:00Z")
             & ~reports.dominated_late_window).sum()),
         "gold_source_reports": len(raw),
         "delayed_or_corrected_reports": int((reports.report_available_at_utc
             > reports.source_date.map(lambda d: ((d + pd.Timedelta(days=8))
                 .tz_localize("America/New_York") - pd.Timedelta(seconds=1))
                 .tz_convert("UTC"))).sum()),
         "original_vintages_proved": False}
    if args.audit:
        identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run identity")
        for name, digest in identity["files"].items():
            base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
        for name, frame in (("gold", raw), ("reports", reports), ("states", state)):
            pd.testing.assert_frame_equal(frame, pd.read_parquet(output / (name + ".parquet")))
        payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        base.require(payload["quality"] == q and payload["case"]["counts"] ==
                     engine.target_counts(signals), "quality/count drift")
        n = engine.prior.replay(output / "case", payload["case"], signals, q, cfg)
        print(json.dumps({"artifact_hashes": len(identity["files"]),
                          "gold_clock_state_replay": True,
                          "metric_year_count_cash_replays": n, "all_true": True}))
        return
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"futures": verified, "source": cfg["source"]})
    for name, frame in (("gold", raw), ("reports", reports), ("states", state)):
        frame.to_parquet(output / (name + ".parquet"), index=False)
    base.write_json(output / "feasibility.json", {"quality": q, "moex_outcomes_read": False})
    g = cfg["screen_gates"]
    base.require(q["ready_source_dates"] >= g["minimum_ready_source_dates"]
                 and q["ready_asset_date_fraction"] >= g["minimum_ready_asset_date_fraction"],
                 "source feasibility gate before market outcomes")
    started = time.monotonic()
    market = engine.market_inputs(storage, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, q, cfg, "gold_positioning_risk")
    base.write_json(output / "metrics.json", {"protocol_id": cfg["protocol_id"],
                    "seal_sha256": args.seal_sha, "quality": q, "case": case,
                    "economic_seconds": time.monotonic() - started, "goal_verified": False})
    base.write_json(output / "identity.json", {"seal_sha256": args.seal_sha, "files": {
        str(p.relative_to(output)): base.sha(p) for p in sorted(output.rglob("*")) if p.is_file()
    }})
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


if __name__ == "__main__":
    main()
