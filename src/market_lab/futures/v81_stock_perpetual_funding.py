"""Bounded funding-component screen, not a paired-portfolio backtest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = "v81_stock_perpetual_funding_v1"
CONFIG = REPO / f"configs/{PROTOCOL}.json"
SEAL = REPO / f"configs/{PROTOCOL}.seal.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8-sig"
    )
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify(expected):
    if sha(SEAL.read_bytes()) != expected:
        raise ValueError("seal_changed")
    for name, digest in read(SEAL)["files"].items():
        if sha((REPO / name).read_bytes()) != digest:
            raise ValueError("sealed_file_changed")
    cfg = read(CONFIG)
    if cfg["protocol_id"] != PROTOCOL or cfg["goal_verified"] or cfg["live_trading_allowed"]:
        raise ValueError("scope_changed")
    return cfg


def url_for(ticker, start, cfg):
    if ticker not in cfg["tickers"] or not 0 <= start < cfg["maximum_rows_per_ticker"]:
        raise ValueError("request_out_of_scope")
    root = "https://iss.moex.com/iss/history/engines/futures/markets/forts/boards/RFUD/securities/"
    return root + ticker + ".json?" + urlencode({
        "from": cfg["period"]["start"], "till": cfg["period"]["end"], "start": start,
        "iss.only": "history,history.cursor", "history.columns": ",".join(cfg["columns"]),
        "iss.meta": "off",
    })


def parse(raw, ticker, start, cfg):
    body = json.loads(raw)
    data, cursor = body["history"], body["history.cursor"]
    if (set(data["columns"]) != set(cfg["columns"]) or len(data["columns"]) != len(cfg["columns"])
            or cursor["columns"] != ["INDEX", "TOTAL", "PAGESIZE"] or len(cursor["data"]) != 1
            or any(len(row) != len(cfg["columns"]) for row in data["data"])):
        raise ValueError("schema_changed")
    index, total, size = cursor["data"][0]
    if (index != start or not 0 < total <= cfg["maximum_rows_per_ticker"] or size != 100
            or len(data["data"]) != min(size, total - start)):
        raise ValueError("cursor_changed")
    frame = pd.DataFrame(data["data"], columns=data["columns"])
    dates = pd.to_datetime(frame.TRADEDATE, errors="raise")
    if (not dates.notna().all() or not dates.between(
            cfg["period"]["start"], cfg["period"]["end"]).all()
            or not dates.lt("2026-01-01").all()
            or not frame.SECID.eq(ticker).all() or not frame.BOARDID.eq("RFUD").all()):
        raise ValueError("protected_date_or_identity")
    frame["TRADEDATE"] = dates
    for name in ("SETTLEPRICE", "SWAPRATE", "VOLUME", "NUMTRADES"):
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(float)
    return frame, total


def fetch(session, url):
    for attempt, delay in enumerate((0, 5, 15), 1):
        time.sleep(delay + 0.5)
        try:
            with session.get(url, timeout=(15, 40), allow_redirects=False, stream=True,
                             headers={"User-Agent": "TradingLab-funding-research/1.0"}) as r:
                if r.status_code != 200 or r.url != url:
                    raise ValueError(f"http_{r.status_code}")
                parts, count = [], 0
                for part in r.iter_content(65536):
                    count += len(part)
                    if count > 2 * 1024 * 1024:
                        raise ValueError("response_cap")
                    parts.append(part)
                raw = b"".join(parts)
                return raw, {"url": url, "status": 200, "bytes": count, "sha256": sha(raw),
                             "retrieved_at_utc": datetime.now(UTC).isoformat(),
                             "attempt": attempt}
        except requests.RequestException:
            if attempt == 3:
                raise ValueError("transport_exhausted") from None
    raise ValueError("unreachable")


def calendar_dates(cfg):
    spec = cfg["calendar"]
    path = Path("/srv/trading_lab_data") / spec["path"]
    if path.stat().st_size != spec["bytes"] or sha(path.read_bytes()) != spec["sha256"]:
        raise ValueError("calendar_changed")
    frame = pd.read_parquet(path, columns=["effective_date"])
    dates = pd.to_datetime(frame.effective_date)
    if (len(frame) != spec["rows"] or not dates.notna().all()
            or not dates.lt("2026-01-01").all()):
        raise ValueError("protected_or_changed_calendar")
    return pd.DatetimeIndex(dates[dates.between(cfg["period"]["start"], cfg["period"]["end"])]
                            .sort_values().unique())


def summarize(frame, cfg, expected_dates):
    if (frame.empty or frame.TRADEDATE.duplicated().any()
            or not frame.TRADEDATE.is_monotonic_increasing
            or not frame.TRADEDATE.lt("2026-01-01").all()):
        raise ValueError("invalid_full_history")
    lot = cfg["lot_shares"]
    first, last = frame.TRADEDATE.iloc[0], frame.TRADEDATE.iloc[-1]
    span = (last - first).days
    payments = frame.iloc[1:]
    valid = payments.SWAPRATE.notna() & np.isfinite(payments.SWAPRATE)
    initial = frame.SETTLEPRICE.iloc[0]
    expected = pd.DatetimeIndex(expected_dates)
    missing = expected.difference(pd.DatetimeIndex(frame.TRADEDATE))
    complete = bool(len(valid) and valid.all() and np.isfinite(initial) and initial > 0
                    and len(expected) and not len(missing))
    result = {
        "rows": len(frame), "payment_observations": len(payments),
        "minimum_date": str(first.date()), "maximum_date": str(last.date()),
        "calendar_span_days": span, "unknown_payments": int((~valid).sum()),
        "payment_coverage": float(valid.mean()) if len(valid) else None,
        "complete_cashflow": complete,
        "expected_proxy_session_days": len(expected),
        "missing_proxy_session_dates": [str(day.date()) for day in missing],
        "zero_payments": int(payments.SWAPRATE.eq(0).sum()),
        "positive_payments": int(payments.SWAPRATE.gt(0).sum()),
        "negative_payments": int(payments.SWAPRATE.lt(0).sum()),
        "zero_trade_source_days": int(frame.NUMTRADES.eq(0).sum()),
        "untraded_days_not_removed": True,
        "decisions": 0, "filled_trades": 0, "cagr": None, "sharpe": None,
        "maximum_drawdown": None, "portfolio_pnl": None,
    }
    numeric = {"initial_notional_proxy_rub": None, "funding_credit_rub_per_contract": None,
               "credit_fraction_of_initial_notional": None, "simple_funding_apr": None,
               "illustrative_fee_adjusted_apr": None, "monthly_credit_rub": None,
               "yearly_credit_rub": None, "positive_month_fraction": None}
    if complete and span > 0:
        credit = float(payments.SWAPRATE.sum() * lot)
        notional = float(initial * lot)
        monthly = payments.groupby(payments.TRADEDATE.dt.strftime("%Y-%m")).SWAPRATE.sum() * lot
        yearly = payments.groupby(payments.TRADEDATE.dt.strftime("%Y")).SWAPRATE.sum() * lot
        factor = 365.25 / span
        numeric = {
            "initial_notional_proxy_rub": notional, "funding_credit_rub_per_contract": credit,
            "credit_fraction_of_initial_notional": credit / notional,
            "simple_funding_apr": credit / notional * factor,
            "illustrative_fee_adjusted_apr": {
                name: (credit / notional - bps / 10000) * factor
                for name, bps in cfg["illustrative_roundtrip_fee_bps"].items()},
            "monthly_credit_rub": monthly.to_dict(), "yearly_credit_rub": yearly.to_dict(),
            "positive_month_fraction": float(monthly.gt(0).mean()),
        }
    result.update(numeric)
    g = cfg["gates"]
    enough = (span >= g["minimum_calendar_span_days"]
              and (first - pd.Timestamp(cfg["period"]["start"])).days <= 5
              and (pd.Timestamp(cfg["period"]["end"]) - last).days <= 5)
    passed = bool(complete and enough
                  and numeric["illustrative_fee_adjusted_apr"]["double"] >= g["minimum_apr"]
                  and numeric["positive_month_fraction"] >= g["minimum_positive_month_fraction"])
    result["verdict"] = ("FUNDING_COMPONENT_CANDIDATE" if passed else
                         "REJECT_FUNDING_COMPONENT" if complete and enough else
                         "INCOMPLETE_COMPONENT_NO_PROMOTION")
    result["goal_verified"] = False
    return result


def run(expected, audit=False):
    cfg = verify(expected)
    if os.name != "posix" or os.getuid() != 999:
        raise ValueError("server_service_user_only")
    root = Path(cfg["root"])
    if root.resolve() != root.absolute() or not root.is_dir():
        raise ValueError("invalid_root")
    if not audit:
        if any(root.iterdir()):
            raise ValueError("existing_run_no_restart")
        write_new(root / "identity.json", {"seal_sha256": expected})
    elif read(root / "identity.json")["seal_sha256"] != expected:
        raise ValueError("identity_changed")
    calendar = calendar_dates(cfg)  # Date-only projection; no existing market values.
    results, evidence = {}, []
    with requests.Session() as session:
        for ticker in cfg["tickers"]:
            frames, start, total = [], 0, None
            while total is None or start < total:
                path = root / f"{ticker}_{start:04d}.json"
                url = url_for(ticker, start, cfg)
                if audit:
                    raw = path.read_bytes()
                    receipt = read(path.with_suffix(".receipt.json"))
                    if (sha(raw) != receipt["sha256"] or len(raw) != receipt["bytes"]
                            or receipt["url"] != url or receipt["status"] != 200):
                        raise ValueError("raw_changed")
                else:
                    raw, receipt = fetch(session, url)
                    with path.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    write_new(path.with_suffix(".receipt.json"), receipt)
                frame, count = parse(raw, ticker, start, cfg)
                if total is not None and total != count:
                    raise ValueError("total_changed")
                frames.append(frame)
                evidence.append(receipt)
                total, start = count, start + 100
            results[ticker] = summarize(pd.concat(frames, ignore_index=True), cfg, calendar)
    payload = {"protocol_id": PROTOCOL, "seal_sha256": expected, "components": results,
               "pages": evidence, "calendar": cfg["calendar"],
               "limitations": cfg["limitations"], "goal_verified": False,
               "paired_execution_evaluated": False, "stage2_admission": False}
    verify(expected)
    if audit:
        if payload != read(root / "metrics.json"):
            raise ValueError("cashflow_or_metadata_replay_changed")
        return {"all_true": True, "raw_pages_replayed": len(evidence),
                "component_arithmetic_replayed": len(results)}
    write_new(root / "metrics.json", payload)
    return payload


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--audit", action="store_true")
    args = cli.parse_args()
    print(json.dumps(run(args.seal_sha, args.audit), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
