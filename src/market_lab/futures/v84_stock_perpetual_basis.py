"""Measured funding/basis components; unresolved cash liabilities are never zero."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

from market_lab.futures import v81_stock_perpetual_funding as parent

PROTOCOL = "v84_stock_perpetual_basis_v1"
REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / f"configs/{PROTOCOL}.json"
SEAL = REPO / f"configs/{PROTOCOL}.seal.json"


def checked(path, digest):
    raw = path.read_bytes()
    if parent.sha(raw) != digest:
        raise ValueError("input_hash_changed")
    return raw


def verify(expected):
    seal = json.loads(checked(SEAL, expected).decode("utf-8-sig"))
    for name, digest in seal["files"].items():
        checked(REPO / name, digest)
    cfg = parent.read(CONFIG)
    if cfg["protocol_id"] != PROTOCOL or any(
        cfg[k] for k in ("goal_verified", "stage2_admission", "live_trading_allowed")
    ):
        raise ValueError("scope_changed")
    return cfg


def bounded_dates(values):
    dates = pd.to_datetime(values, utc=True, errors="raise")
    if len(dates) == 0 or not dates.notna().all() or not (dates < "2026-01-01").all():
        raise ValueError("protected_or_missing_date")
    return dates


def candle_frame(raw, day, cfg):
    block = json.loads(raw)["candles"]
    columns = cfg["candles"]["columns"]
    if (set(block["columns"]) != set(columns) or len(block["columns"]) != len(columns)
            or any(len(row) != len(columns) for row in block["data"])
            or len(block["data"]) >= cfg["candles"]["limit"]):
        raise ValueError("candle_schema_or_page_cap")
    frame = pd.DataFrame(block["data"], columns=block["columns"])
    if frame.empty:
        frame.index = pd.DatetimeIndex([], tz="UTC")
        return frame  # Valid empty source => unresolved exact endpoints, never zero prices.
    # Establish date admission before converting/using any economic columns.
    starts = pd.to_datetime(frame.begin, errors="raise").dt.tz_localize("Europe/Moscow")
    ends = pd.to_datetime(frame.end, errors="raise").dt.tz_localize("Europe/Moscow")
    bounded_dates(starts)
    bounded_dates(ends)
    if (not starts.dt.strftime("%Y-%m-%d").eq(day).all()
            or not ends.dt.strftime("%Y-%m-%d").eq(day).all()
            or starts.duplicated().any() or not starts.is_monotonic_increasing
            or not ((ends >= starts) & (ends < starts + pd.Timedelta(minutes=10))).all()):
        raise ValueError("candle_date_or_order")
    frame.index = pd.DatetimeIndex(starts.dt.tz_convert("UTC"))
    frame["end_timestamp"] = pd.DatetimeIndex(ends.dt.tz_convert("UTC"))
    return frame


def endpoint(frame, day, cfg):
    decision = pd.Timestamp(day + " " + cfg["decision_bar_local"], tz="Europe/Moscow")
    fill = pd.Timestamp(day + " " + cfg["execution_bar_local"], tz="Europe/Moscow")
    if frame.index.has_duplicates:
        raise ValueError("duplicate_bar")
    if decision not in frame.index or fill not in frame.index:
        return {"reason": "missing_exact_decision_or_fill_bar"}
    d, f = frame.loc[decision], frame.loc[fill]
    end = (pd.Timestamp(d["end_timestamp"]) if "end_timestamp" in frame.columns
           else decision + pd.Timedelta(minutes=10) - pd.Timedelta(seconds=1))
    values = np.array([d["close"], d["volume"], f["open"], f["volume"]], dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all() or end >= fill:
        return {"reason": "nonpositive_missing_or_unfinished_bar"}
    return {"price": float(f["open"]), "volume": float(f["volume"]),
            "decision_information_end": end.isoformat(), "fill_at": fill.isoformat()}


def funding_window(frame, dates, lot):
    wanted = pd.to_datetime(dates)
    if (frame.TRADEDATE.duplicated().any() or not frame.TRADEDATE.is_monotonic_increasing
            or not pd.DatetimeIndex(frame.TRADEDATE).equals(wanted)):
        raise ValueError("funding_calendar_gap")
    selected = frame.iloc[:-1]  # Intraday entry gets entry-day, not exit-day funding.
    values = selected.SWAPRATE.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("missing_funding")
    return [{"date": row.TRADEDATE.date().isoformat(), "unrounded_rub":
             float(row.SWAPRATE * lot)} for row in selected.itertuples()]


def benchmark(frame, cfg):
    bounded_dates(frame.available_at)
    frame = frame.loc[frame.series_id.eq("ruonia")].sort_values("available_at").copy()
    frame["available_at"] = pd.to_datetime(frame.available_at, utc=True)
    if frame.available_at.duplicated().any():
        raise ValueError("ambiguous_rate_version")
    days = pd.date_range(*cfg["dates"], inclusive="left")
    records, growth, simple = [], 1.0, 0.0
    for day in days:
        at = pd.Timestamp(str(day.date()) + " " + cfg["execution_bar_local"],
                          tz="Europe/Moscow")
        known = frame.loc[frame.available_at <= at]
        if known.empty:
            return {"reason": "missing_prior_rate", "return": None, "records": records}
        row = known.iloc[-1]
        rate = float(row.value) / 100
        if not np.isfinite(rate) or rate <= -1:
            return {"reason": "invalid_rate", "return": None, "records": records}
        daily = rate / cfg["year_days"]
        growth *= 1 + daily
        simple += daily
        records.append({"date": str(day.date()), "available_at": row.available_at.isoformat(),
                        "annual_rate_fraction": rate,
                        "age_days": float((at - row.available_at).total_seconds() / 86400)})
    return {"return": growth - 1, "simple_return": simple, "days": len(days),
            "maximum_availability_age_days": max(r["age_days"] for r in records),
            "records": records, "investable_income_proven": False}


def components(prices, funding, cash_return, cfg):
    if any("price" not in prices[k] for k in ("stock_in", "stock_out", "future_in", "future_out")):
        return {"verdict": "UNRESOLVED_ENDPOINT", "scenarios": None}
    si, so, fi, fo = [prices[k]["price"] for k in
                      ("stock_in", "stock_out", "future_in", "future_out")]
    lot, reserve = cfg["lot_shares"], cfg["reserve_fraction"]
    capital = si * lot * (1 + reserve)
    basis = lot * ((so - si) + (fi - fo))
    credit = sum(r["unrounded_rub"] for r in funding)
    span = (pd.Timestamp(cfg["dates"][1]) - pd.Timestamp(cfg["dates"][0])).days
    base_fee = lot / 10000 * (cfg["fee_bps_per_side"]["stock"] * (si + so)
                              + cfg["fee_bps_per_side"]["future"] * (fi + fo))
    scenarios = {}
    for name, multiplier in cfg["cost_multipliers"].items():
        fee = multiplier * base_fee
        total = credit + basis - fee
        target = cfg["target_simple_apr"] * capital * span / cfg["year_days"]
        cash_gap = None if cash_return is None else capital * cash_return - total
        scenarios[name] = {"fee_rub": fee, "measured_component_rub": total,
                           "component_simple_apr": total / capital * cfg["year_days"] / span,
                           "target_residual_rub": target - total,
                           "cash_residual_rub": cash_gap}
    stress = scenarios["double"]
    met = (stress["target_residual_rub"] <= 0 and stress["cash_residual_rub"] is not None
           and stress["cash_residual_rub"] <= 0)
    return {"capital_rub": capital, "basis_rub": basis, "funding_proxy_rub": credit,
            "payment_count": len(funding), "scenarios": scenarios,
            "verdict": "COMPONENT_HURDLES_MET" if met else "COMPONENT_HURDLES_NOT_MET"}


def run(expected):
    cfg = verify(expected)
    if os.name != "posix" or os.getuid() != 999:
        raise ValueError("server_service_user_only")
    root = Path(cfg["root"])
    if root.resolve() != root.absolute() or not root.is_dir() or any(root.iterdir()):
        raise ValueError("new_empty_root_required")
    parent.write_new(root / "identity.json", {"seal_sha256": expected})
    pconfig = parent.read(parent.CONFIG)
    calendar = parent.calendar_dates(pconfig)
    if [str(calendar[0].date()), str(calendar[-1].date())] != cfg["dates"]:
        raise ValueError("changed_parent_endpoints")
    ppath = Path(cfg["parent_metrics"]["path"])
    pmetrics = json.loads(checked(ppath, cfg["parent_metrics"]["sha256"]).decode("utf-8-sig"))
    spotroot = Path(cfg["spot_root"])
    sm = json.loads(checked(spotroot / "manifest.json", cfg["spot_manifest_sha256"])
                    .decode("utf-8-sig"))
    if sm["cutoff_exclusive_utc"] != "2026-01-01T00:00:00+00:00":
        raise ValueError("spot_cutoff")
    rs = cfg["rates"]
    rr = Path(rs["root"])
    checked(rr / "manifest.json", rs["manifest_sha256"])
    checked(rr / rs["file"], rs["sha256"])
    rates = pd.read_parquet(rr / rs["file"], columns=["series_id", "available_at", "value"])
    cash = benchmark(rates, cfg)
    candles, receipts = {}, []
    with requests.Session() as session:
        for ticker in cfg["pairs"]:
            for day in cfg["dates"]:
                url = cfg["candles"]["url_template"].format(ticker=ticker) + "?" + urlencode({
                    "from": day, "till": day, "interval": 10, "start": 0, "limit": 500,
                    "iss.only": "candles", "iss.meta": "off"})
                raw, receipt = parent.fetch(session, url)
                name = f"{ticker}_{day}.json"
                with (root / name).open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                frame = candle_frame(raw, day, cfg)
                receipt.update({"file": name, "ticker": ticker, "date": day, "rows": len(frame),
                                "date_admitted_before_price_use": True})
                parent.write_new(root / f"{name}.receipt.json", receipt)
                receipts.append(receipt)
                candles[ticker, day] = frame
    parent.write_new(root / "candle_manifest.json", {"pages": receipts,
                     "maximum_source_date": cfg["dates"][1], "source_only": True})
    results = {}
    for ticker, stock in cfg["pairs"].items():
        spec = next(x for x in sm["artifacts"] if x["ticker"] == stock)
        bounded_dates([spec["minimum_timestamp"], spec["maximum_timestamp"]])
        path = spotroot / spec["path"]
        checked(path, spec["sha256"])
        spot = pd.read_parquet(path, columns=["open", "close", "volume"])
        bounded_dates(spot.index)
        if len(spot) != spec["rows"]:
            raise ValueError("spot_row_count")
        frames = []
        for start in range(0, len(calendar), 100):
            rawpath = ppath.parent / f"{ticker}_{start:04d}.json"
            receipt = next(r for r in pmetrics["pages"]
                           if r["url"] == parent.url_for(ticker, start, pconfig))
            raw = checked(rawpath, receipt["sha256"])
            frame, _ = parent.parse(raw, ticker, start, pconfig)
            frames.append(frame)
        payments = funding_window(pd.concat(frames, ignore_index=True), calendar,
                                  cfg["lot_shares"])
        prices = {}
        for side, day in zip(("in", "out"), cfg["dates"], strict=True):
            prices[f"stock_{side}"] = endpoint(spot, day, cfg)
            prices[f"future_{side}"] = endpoint(candles[ticker, day], day, cfg)
        result = components(prices, payments, cash["return"], cfg)
        yearly, monthly = {}, {}
        for payment in payments:
            year, month = payment["date"][:4], payment["date"][:7]
            yearly[year] = yearly.get(year, 0.0) + payment["unrounded_rub"]
            monthly[month] = monthly.get(month, 0.0) + payment["unrounded_rub"]
        result.update({"prices": prices, "funding_payments": payments,
                       "yearly_funding_only_rub": yearly, "monthly_funding_only_rub": monthly,
                       "scheduled_pair_endpoints": 2,
                       "leg_proxy_fills": sum("price" in x for x in prices.values()),
                       "actual_decisions": 0, "actual_fills": 0, "actual_trades": 0,
                       "full_pair_pnl": None, "CAGR": None, "Sharpe": None, "MDD": None,
                       "annual_pair_returns": None,
                       "unresolved_pair_inputs": cfg["unresolved_pair_inputs"]})
        results[ticker] = result
    payload = {"protocol_id": PROTOCOL, "seal_sha256": expected, "scope": cfg["scope"],
               "completed_at_utc": datetime.now(UTC).isoformat(), "components": results,
               "benchmark": cash, "source_pages": receipts, "goal_verified": False,
               "stage2_admission": False, "live_trading_allowed": False}
    verify(expected)
    parent.write_new(root / "metrics.json", payload)
    return {"completed_at_utc": payload["completed_at_utc"],
            "metrics_sha256": parent.sha((root / "metrics.json").read_bytes()),
            "components": {k: {x: y for x, y in v.items() if x != "funding_payments"}
                           for k, v in results.items()},
            "benchmark": {k: v for k, v in cash.items() if k != "records"}}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    print(json.dumps(run(cli.parse_args().seal_sha), ensure_ascii=False, allow_nan=False))
