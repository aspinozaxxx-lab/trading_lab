import json

import pandas as pd
import pytest

from market_lab.futures import v84_stock_perpetual_basis as m


@pytest.fixture
def cfg():
    return m.parent.read(m.CONFIG)


def prices(si=100, so=90, fi=101, fo=90):
    return {k: {"price": v} for k, v in zip(
        ("stock_in", "stock_out", "future_in", "future_out"), (si, so, fi, fo), strict=True)}


def test_units_costs_and_basis(cfg):
    r = m.components(prices(), [{"unrounded_rub": 1000}], .30, cfg)
    assert r["capital_rub"] == 13000
    assert r["basis_rub"] == 100
    assert r["funding_proxy_rub"] == 1000
    assert r["scenarios"]["base"]["fee_rub"] == pytest.approx(28.55)
    assert r["scenarios"]["double"]["measured_component_rub"] == pytest.approx(1042.9)
    assert r["scenarios"]["double"]["cash_residual_rub"] == pytest.approx(2857.1)
    assert r["verdict"] == "COMPONENT_HURDLES_NOT_MET"


def test_sign_and_directional_cancellation(cfg):
    assert m.components(prices(100, 200, 100, 200), [], 0, cfg)["basis_rub"] == 0
    assert m.components(prices(100, 90, 100, 91), [], 0, cfg)["basis_rub"] == -100


def test_unresolved_never_zero(cfg):
    p = prices()
    p["future_out"] = {"reason": "missing"}
    assert m.components(p, [], .2, cfg)["scenarios"] is None
    r = m.components(prices(), [{"unrounded_rub": 100000}], None, cfg)
    assert r["scenarios"]["double"]["cash_residual_rub"] is None
    assert r["verdict"] != "COMPONENT_HURDLES_MET"


def test_hurdles(cfg):
    assert m.components(prices(), [{"unrounded_rub": 10000}], .2, cfg)["verdict"] == (
        "COMPONENT_HURDLES_MET")


def test_funding_includes_first_excludes_last():
    dates = pd.to_datetime(["2024-10-01", "2024-10-02", "2024-10-03"])
    frame = pd.DataFrame({"TRADEDATE": dates, "SWAPRATE": [1, 2, 500]})
    out = m.funding_window(frame, dates, 100)
    assert [r["unrounded_rub"] for r in out] == [100, 200]
    with pytest.raises(ValueError, match="gap"):
        m.funding_window(frame.iloc[1:], dates, 100)


@pytest.mark.parametrize("value", [None, "2026-01-01", "2026-09-15"])
def test_protected_dates(value):
    with pytest.raises(ValueError):
        m.bounded_dates([value])


def test_exact_causal_bar(cfg):
    frame = pd.DataFrame({"open": [100, 102], "close": [101, 103], "volume": [10, 20]},
                         index=pd.date_range("2024-10-01 15:40", periods=2,
                                             freq="10min", tz="Europe/Moscow"))
    assert m.endpoint(frame, "2024-10-01", cfg)["price"] == 102
    assert "reason" in m.endpoint(frame.iloc[:1], "2024-10-01", cfg)
    frame.iloc[1, frame.columns.get_loc("volume")] = 0
    assert "reason" in m.endpoint(frame, "2024-10-01", cfg)


def test_candles_date_validation_before_prices(cfg):
    body = {"candles": {"columns": cfg["candles"]["columns"], "data": [
        [None] * 6 + ["2024-10-01 15:40:00", "2024-10-01 15:49:59"]]}}
    assert len(m.candle_frame(json.dumps(body), "2024-10-01", cfg)) == 1
    with pytest.raises(ValueError, match="date"):
        m.candle_frame(json.dumps(body), "2024-10-02", cfg)
    body["candles"]["data"] *= 500
    with pytest.raises(ValueError, match="cap"):
        m.candle_frame(json.dumps(body), "2024-10-01", cfg)
    body["candles"]["data"] = []
    empty = m.candle_frame(json.dumps(body), "2024-10-01", cfg)
    assert "reason" in m.endpoint(empty, "2024-10-01", cfg)


def test_rate_availability_and_compounding(cfg):
    cfg = dict(cfg, dates=["2024-10-01", "2024-10-03"])
    frame = pd.DataFrame({"series_id": ["ruonia"] * 3, "value": [10, 20, 90],
                          "available_at": pd.to_datetime([
                              "2024-09-30T21:00Z", "2024-10-02T00:00Z",
                              "2024-10-03T00:00Z"], utc=True)})
    r = m.benchmark(frame, cfg)
    assert [x["annual_rate_fraction"] for x in r["records"]] == [.1, .2]
    assert r["return"] == pytest.approx((1 + .1 / 365.25) * (1 + .2 / 365.25) - 1)
    assert m.benchmark(frame.iloc[1:], cfg)["return"] is None
