"""Synthetic arithmetic, scope and unknown-liability tests; no real market inputs."""

from copy import deepcopy

import pytest

from market_lab.futures import v82_stock_perpetual_capital as m


def fixture():
    cfg = {"period": {"start": "2024-01-01", "end": "2025-12-31"},
           "capital_reserve_fraction": 0.30, "roundtrip_fee_bps": {"base": 30, "double": 60},
           "annual_target_fractions": [0.20, 0.50], "unresolved_pair_inputs": ["cash_and_prices"]}
    record = {"minimum_date": "2024-12-31", "maximum_date": "2025-12-31",
              "calendar_span_days": 365, "initial_notional_proxy_rub": 10000,
              "funding_credit_rub_per_contract": 3000, "complete_cashflow": True,
              "unknown_payments": 0, "missing_proxy_session_dates": [], "rows": 3,
              "payment_observations": 2, "payment_coverage": 1.0,
              "monthly_credit_rub": {"2025-01": 1000, "2025-12": 2000},
              "yearly_credit_rub": {"2025": 3000}, "simple_funding_apr": .3 * 365.25 / 365}
    return record, cfg


def test_capital_includes_full_stock_principal_and_reserve():
    record, cfg = fixture()
    result = m.component(record, cfg)
    assert result["initial_capital_proxy_rub"] == 13000
    base = result["cost_cases"]["base"]
    assert base["illustrative_fee_rub"] == 30
    assert base["capital_scaled_funding_less_fee_simple_apr"] == pytest.approx(
        2970 / 13000 * 365.25 / 365)
    assert result["cost_cases"]["double"]["illustrative_fee_rub"] == 60
    assert all(result[name] is None for name in (
        "paired_pnl", "cagr", "sharpe", "maximum_drawdown"))
    assert not result["goal_verified"] and not result["stage2_admission"]
    assert result["filled_trades"] == result["decisions"] == 0


def test_algebraic_reserve_requirements_are_not_credited():
    record, cfg = fixture()
    out = m.component(record, cfg)["cost_cases"]["double"]
    requirement = out["target_requirements"]["0.5"]
    reserve_income = requirement["reserve_simple_apr_required_if_only_reserve_earns"]
    total_apr = (out["nominal_funding_less_fee_simple_apr"] + .3 * reserve_income) / 1.3
    assert total_apr == pytest.approx(.5)
    assert not requirement["reserve_income_is_credited"]
    maximum_reserve = requirement["maximum_extra_capital_fraction_funding_alone"]
    assert maximum_reserve < 0  # Even stock-principal alone cannot clear this target.


@pytest.mark.parametrize(("key", "value"), [
    ("minimum_date", "2023-12-31"), ("maximum_date", "2026-01-01"),
    ("calendar_span_days", 364), ("complete_cashflow", False), ("unknown_payments", 1),
    ("missing_proxy_session_dates", ["2025-06-01"]), ("initial_notional_proxy_rub", 0),
    ("initial_notional_proxy_rub", float("inf")), ("funding_credit_rub_per_contract", None),
    ("funding_credit_rub_per_contract", float("nan")), ("payment_observations", 1),
    ("yearly_credit_rub", {"2025": 2000}), ("simple_funding_apr", 0.9),
])
def test_invalid_or_incomplete_source_is_not_zero(key, value):
    record, cfg = fixture()
    record[key] = value
    with pytest.raises(ValueError):
        m.component(record, cfg)


def test_source_is_not_mutated_and_both_cost_scenarios_retained():
    record, cfg = fixture()
    original = deepcopy(record)
    result = m.component(record, cfg)
    assert record == original
    assert set(result["cost_cases"]) == {"base", "double"}


def test_negative_funding_is_kept_and_not_promoted():
    record, cfg = fixture()
    record["funding_credit_rub_per_contract"] = -3000
    record["monthly_credit_rub"] = {"2025-01": -1000, "2025-12": -2000}
    record["yearly_credit_rub"] = {"2025": -3000}
    record["simple_funding_apr"] *= -1
    out = m.component(record, cfg)
    assert out["cost_cases"]["base"]["funding_less_fee_rub"] == -3030
    assert out["verdict"] == "FUNDING_ALONE_BELOW_TARGET_PAIR_UNRESOLVED"


@pytest.mark.parametrize("reserve", [0, -1, None, float("nan")])
def test_invalid_reserve_not_silently_zero(reserve):
    record, cfg = fixture()
    cfg["capital_reserve_fraction"] = reserve
    with pytest.raises(ValueError):
        m.component(record, cfg)


def test_matched_price_and_gross_dividend_components_cancel():
    assert m.paired_cashflow_identity(500, -500, 40, 200, 200, 10) == 30
    assert m.paired_cashflow_identity(-500, 500, -40, 200, 170, 10) == -80


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("missing", [None, float("nan"), float("inf")])
def test_unknown_component_never_becomes_factual_zero(index, missing):
    values = [500, -500, 40, 200, 170, 10]
    values[index] = missing
    assert m.paired_cashflow_identity(*values) is None


@pytest.mark.parametrize("index", [3, 4, 5])
def test_negative_debits_and_costs_rejected(index):
    values = [500, -500, 40, 200, 170, 10]
    values[index] = -1
    with pytest.raises(ValueError):
        m.paired_cashflow_identity(*values)
