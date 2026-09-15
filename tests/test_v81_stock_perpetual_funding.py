"""Synthetic funding units, unknown cash flows and bounded source requests."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import v81_stock_perpetual_funding as m


def cfg():
    return m.read(m.CONFIG)


def frame():
    dates = pd.bdate_range("2024-10-01", "2025-12-31")
    return pd.DataFrame({"TRADEDATE": dates, "SETTLEPRICE": 200.0,
                         "SWAPRATE": 0.3, "NUMTRADES": 100.0})


def summary(data, custom=None):
    return m.summarize(data, cfg() if custom is None else custom, data.TRADEDATE)


def test_lot_applied_to_both_credit_and_notional_no_hundredfold_yield():
    data = frame()
    result = summary(data)
    assert result["initial_notional_proxy_rub"] == 20000
    assert result["funding_credit_rub_per_contract"] == pytest.approx((len(data) - 1) * 30)
    span = (data.TRADEDATE.iloc[-1] - data.TRADEDATE.iloc[0]).days
    rate = (len(data) - 1) * 0.3 / 200 * 365.25 / span
    assert result["simple_funding_apr"] == pytest.approx(rate)
    custom = cfg()
    custom["lot_shares"] = 1
    assert summary(data, custom)["simple_funding_apr"] == pytest.approx(rate)


def test_first_funding_excluded_and_later_price_not_a_new_normalizer():
    data = frame()
    expected = summary(data)
    data.loc[0, "SWAPRATE"] = 9999
    data.loc[1:, "SETTLEPRICE"] = 99999
    assert expected == summary(data)


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_unknown_payment_does_not_disappear_or_become_zero(value):
    data = frame()
    data.loc[5, "SWAPRATE"] = value
    r = summary(data)
    assert r["unknown_payments"] == 1 and not r["complete_cashflow"]
    assert r["simple_funding_apr"] is None
    assert r["verdict"] == "INCOMPLETE_COMPONENT_NO_PROMOTION"


@pytest.mark.parametrize("rate", [0.0, -0.5, 0.01])
def test_zero_negative_or_small_stream_fails_without_flipping(rate):
    data = frame()
    data["SWAPRATE"] = rate
    r = summary(data)
    assert r["complete_cashflow"] and r["verdict"] == "REJECT_FUNDING_COMPONENT"
    assert r["filled_trades"] == 0 and r["cagr"] is None and r["portfolio_pnl"] is None


def test_untraded_payment_not_dropped_and_fee_hurdles_not_called_pnl():
    data = frame()
    data["NUMTRADES"] = 0
    r = summary(data)
    assert r["zero_trade_source_days"] == len(data)
    assert r["payment_observations"] == len(data) - 1
    fees = r["illustrative_fee_adjusted_apr"]
    assert fees["double"] < fees["base"] < r["simple_funding_apr"]
    assert sum(r["monthly_credit_rub"].values()) == pytest.approx(
        r["funding_credit_rub_per_contract"])


def test_short_period_cannot_pass_large_funding():
    assert summary(frame().iloc[:40])["verdict"] == "INCOMPLETE_COMPONENT_NO_PROMOTION"


def test_single_observation_has_no_payment_or_annualization():
    r = summary(frame().iloc[:1])
    assert r["payment_observations"] == 0 and r["payment_coverage"] is None
    assert not r["complete_cashflow"] and r["simple_funding_apr"] is None
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize("kind", ["duplicate", "unordered", "protected"])
def test_dates_guard(kind):
    data = frame()
    if kind == "duplicate":
        data.loc[1, "TRADEDATE"] = data.TRADEDATE.iloc[0]
    elif kind == "unordered":
        data = data.iloc[::-1]
    else:
        data.loc[len(data) - 1, "TRADEDATE"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="history"):
        summary(data)


def test_missing_expected_session_is_unknown_not_zero_funding():
    data = frame()
    r = m.summarize(data.drop(index=5), cfg(), data.TRADEDATE)
    assert r["unknown_payments"] == 0 and len(r["missing_proxy_session_dates"]) == 1
    assert not r["complete_cashflow"] and r["simple_funding_apr"] is None
    assert r["verdict"] == "INCOMPLETE_COMPONENT_NO_PROMOTION"


def body(day="2024-10-01", ticker="SBERF", total=1):
    return json.dumps({"history": {"columns": cfg()["columns"], "data": [
        ["RFUD", day, ticker, 200.0, 0.2, 12, 4]]},
        "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, total, 100]]}}
    ).encode()


def test_parser_keeps_units_and_date_and_honors_cursor():
    d, count = m.parse(body(), "SBERF", 0, cfg())
    assert count == 1 and d.SWAPRATE.iloc[0] == 0.2 and d.SETTLEPRICE.iloc[0] == 200
    with pytest.raises(ValueError, match="cursor"):
        m.parse(body(total=101), "SBERF", 0, cfg())


def test_response_column_order_does_not_change_units():
    normal, _ = m.parse(body(), "SBERF", 0, cfg())
    alternate = json.loads(body())
    alternate["history"]["columns"].reverse()
    alternate["history"]["data"][0].reverse()
    reordered, _ = m.parse(json.dumps(alternate).encode(), "SBERF", 0, cfg())
    pd.testing.assert_frame_equal(normal, reordered.loc[:, normal.columns])


@pytest.mark.parametrize("day,ticker", [("2026-01-01", "SBERF"), ("2024-09-01", "SBERF"),
                                      ("2024-10-01", "CNYRUBF")])
def test_parser_protected_range_and_ticker(day, ticker):
    with pytest.raises(ValueError, match="protected_date_or_identity"):
        m.parse(body(day, ticker), "SBERF", 0, cfg())


def test_url_is_bounded_and_not_a_latest_market_route():
    url = m.url_for("SBERF", 0, cfg())
    assert "/history/" in url and "till=2025-12-31" in url and "from=2024-10-01" in url
    for ticker, start in [("CNYRUBF", 0), ("SBERF", 1000), ("SBERF", -1)]:
        with pytest.raises(ValueError, match="out_of_scope"):
            m.url_for(ticker, start, cfg())
