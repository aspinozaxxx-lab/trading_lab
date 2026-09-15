"""Offline funding-capital diagnostic; never reports a paired portfolio return."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = "v82_stock_perpetual_capital_v1"
CONFIG = REPO / f"configs/{PROTOCOL}.json"
SEAL = REPO / f"configs/{PROTOCOL}.seal.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def paired_cashflow_identity(spot_mtm, short_price_mtm, short_funding,
                             dividend_debit, dividend_net_cash, costs):
    """Known cashflows only; neither unknown liabilities nor receipts become zero."""
    values = (spot_mtm, short_price_mtm, short_funding,
              dividend_debit, dividend_net_cash, costs)
    if not all(finite(value) for value in values):
        return None
    if dividend_debit < 0 or dividend_net_cash < 0 or costs < 0:
        raise ValueError("invalid_debit_or_cost")
    return spot_mtm + short_price_mtm + short_funding - dividend_debit + dividend_net_cash - costs


def component(record, cfg):
    first = date.fromisoformat(record["minimum_date"])
    last = date.fromisoformat(record["maximum_date"])
    if not date.fromisoformat(cfg["period"]["start"]) <= first <= last <= date.fromisoformat(
            cfg["period"]["end"]) < date(2026, 1, 1):
        raise ValueError("protected_or_changed_dates")
    span = (last - first).days
    if span <= 0 or span != record["calendar_span_days"]:
        raise ValueError("invalid_span")
    notional, credit = (record["initial_notional_proxy_rub"],
                        record["funding_credit_rub_per_contract"])
    if (not record["complete_cashflow"] or record["unknown_payments"]
            or record["missing_proxy_session_dates"]
            or not finite(notional) or notional <= 0 or not finite(credit)):
        raise ValueError("incomplete_parent_component")
    if record["rows"] - 1 != record["payment_observations"]:
        raise ValueError("invalid_payment_count")
    for name in ("monthly_credit_rub", "yearly_credit_rub"):
        amounts = record[name]
        if (not amounts or not all(finite(v) for v in amounts.values())
                or not math.isclose(math.fsum(amounts.values()), credit, abs_tol=1e-7)):
            raise ValueError("cashflow_totals_changed")
    reserve = cfg["capital_reserve_fraction"]
    if not finite(reserve) or reserve <= 0:
        raise ValueError("invalid_reserve")
    factor = 365.25 / span
    nominal_apr = credit / notional * factor
    if not math.isclose(nominal_apr, record["simple_funding_apr"], abs_tol=1e-12):
        raise ValueError("parent_apr_changed")
    cases = {}
    for name, bps in cfg["roundtrip_fee_bps"].items():
        if not finite(bps) or bps < 0:
            raise ValueError("invalid_fee")
        fee = notional * bps / 10000
        nominal_net_apr = (credit - fee) / notional * factor
        capital_apr = nominal_net_apr / (1 + reserve)
        requirements = {}
        for target in cfg["annual_target_fractions"]:
            if not finite(target) or target <= 0:
                raise ValueError("invalid_target")
            requirements[str(target)] = {
                "maximum_extra_capital_fraction_funding_alone": nominal_net_apr / target - 1,
                "additional_profit_required_rub_over_period": max(
                    0.0, target * notional * (1 + reserve) / factor - (credit - fee)),
                "reserve_simple_apr_required_if_only_reserve_earns": max(
                    0.0, (target * (1 + reserve) - nominal_net_apr) / reserve),
                "reserve_income_is_credited": False,
            }
        cases[name] = {
            "illustrative_fee_rub": fee,
            "funding_less_fee_rub": credit - fee,
            "nominal_funding_less_fee_simple_apr": nominal_net_apr,
            "capital_scaled_funding_less_fee_simple_apr": capital_apr,
            "funding_alone_clears_20pct_simple_apr": capital_apr >= 0.20,
            "target_requirements": requirements,
        }
    years = {
        year: {"funding_rub": amount,
               "funding_fraction_of_fixed_initial_capital_before_fees":
                   amount / (notional * (1 + reserve)),
               "period_label": "partial_2024" if year == str(first.year) else
                   "2025_through_last_observed_session",
               "portfolio_return": None}
        for year, amount in record["yearly_credit_rub"].items()
    }
    return {
        "source_rows": record["rows"], "payment_observations": record["payment_observations"],
        "minimum_date": str(first), "maximum_date": str(last), "calendar_span_days": span,
        "unknown_funding_payments": 0, "funding_coverage": record["payment_coverage"],
        "initial_nominal_proxy_rub": notional, "reserve_proxy_rub": notional * reserve,
        "initial_capital_proxy_rub": notional * (1 + reserve),
        "nominal_funding_simple_apr": nominal_apr, "cost_cases": cases,
        "yearly_component_flows": years,
        "decisions": 0, "filled_trades": 0, "paired_execution_evaluated": False,
        "paired_pnl": None, "cagr": None, "sharpe": None, "maximum_drawdown": None,
        "cash_benchmark_return": None, "unresolved_pair_inputs": cfg["unresolved_pair_inputs"],
        "stage2_admission": False, "goal_verified": False,
        "verdict": ("FUNDING_CAPACITY_CANDIDATE_PAIR_UNRESOLVED"
                    if all(c["funding_alone_clears_20pct_simple_apr"] for c in cases.values())
                    else "FUNDING_ALONE_BELOW_TARGET_PAIR_UNRESOLVED"),
    }


def verify(expected):
    if sha(SEAL) != expected:
        raise ValueError("seal_changed")
    for name, digest in read(SEAL)["files"].items():
        if sha(REPO / name) != digest:
            raise ValueError("sealed_file_changed")
    cfg = read(CONFIG)
    if (cfg["protocol_id"] != PROTOCOL or cfg["goal_verified"] or cfg["stage2_admission"]
            or cfg["live_trading_allowed"]):
        raise ValueError("scope_changed")
    return cfg


def write_new(path, payload):
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8-sig")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


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
    source = cfg["parent_metrics"]
    parent_path = Path(source["path"])
    if sha(parent_path) != source["sha256"]:
        raise ValueError("parent_metrics_changed")
    parent = read(parent_path)
    if (parent["seal_sha256"] != source["seal_sha256"]
            or set(parent["components"]) != set(cfg["tickers"])
            or parent["goal_verified"] or parent["paired_execution_evaluated"]):
        raise ValueError("parent_identity_changed")
    for entry in cfg["specification_evidence"]:
        p = Path(entry["path"])
        if p.stat().st_size != entry["bytes"] or sha(p) != entry["sha256"]:
            raise ValueError("specification_evidence_changed")
    payload = {
        "protocol_id": PROTOCOL, "seal_sha256": expected,
        "parent_metrics_sha256": source["sha256"],
        "components": {ticker: component(parent["components"][ticker], cfg)
                       for ticker in cfg["tickers"]},
        "limitations": cfg["limitations"], "paired_execution_evaluated": False,
        "stage2_admission": False, "goal_verified": False,
    }
    verify(expected)
    if audit:
        if payload != read(root / "metrics.json"):
            raise ValueError("diagnostic_replay_changed")
        return {"all_true": True, "capital_diagnostics_replayed": len(payload["components"]),
                "new_http_requests": 0, "paired_backtests": 0}
    write_new(root / "metrics.json", payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.seal_sha, args.audit), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
