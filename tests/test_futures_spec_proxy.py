"""Testy causal versioned futures spec-proxy bez returns i holdout I/O."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.spec_proxy import (
    EXPECTED_MARGIN_BUFFER_MULTIPLE,
    FALLBACK_REALIZED_POINT_VALUE_FORMULA,
    MODELED_INITIAL_MARGIN_RATE,
    SPEC_PROXY_VERSION,
    assert_append_only_spec_proxy,
    build_causal_spec_proxy,
    conservative_futures_spec,
    realized_rub_open_interest_point_multiplier,
    realized_rub_point_multiplier,
    require_realized_accounting_point_value,
    require_sizing_spec,
)


def _calendar() -> pd.DatetimeIndex:
    """Stroit tri factual development session dlya lag/stale testov."""
    return pd.DatetimeIndex(["2025-03-10", "2025-03-11", "2025-03-12"])


def _daily(rows: int = 3) -> pd.DataFrame:
    """Stroit synthetic factual VALUE/VOLUME/WAPRICE bez cenovogo targeta."""
    return pd.DataFrame(
        {
            "session_date": _calendar()[:rows],
            "contract_id": ["SiH5"] * rows,
            "asset_symbol": ["Si"] * rows,
            "value": [10_000.0, 18_000.0, 28_000.0][:rows],
            "volume": [100.0, 100.0, 100.0][:rows],
            "waprice": [50.0, 60.0, 70.0][:rows],
            "settle": [50.5, 60.5, 70.5][:rows],
            "open_interest": [200.0, 200.0, 200.0][:rows],
            "open_interest_value": [20_200.0, 36_300.0, 56_400.0][:rows],
        }
    )


def test_fixed_versioned_tick_fee_and_modeled_margin_assumptions() -> None:
    """Fiksiruet tick SI/RI/BR/MIX, konservativnyi fee, IM 25% i buffer 2x."""
    expected = {
        "SI": (1.0, 4.0),
        "RI": (10.0, 9.0),
        "BR": (0.01, 10.0),
        "MIX": (25.0, 15.0),
    }
    for symbol, (tick, fee) in expected.items():
        spec = conservative_futures_spec(symbol)
        assert spec.tick_size == tick
        assert spec.conservative_fee_per_side == fee
        assert spec.modeled_initial_margin_rate == MODELED_INITIAL_MARGIN_RATE == 0.25
        assert spec.expected_margin_buffer_multiple == EXPECTED_MARGIN_BUFFER_MULTIPLE == 2.0
        assert spec.version == SPEC_PROXY_VERSION
        assert spec.approximate and spec.research_only
        assert not spec.historical_exchange_exact and not spec.broker_exact
    assert conservative_futures_spec("RTS").asset_symbol == "RI"
    assert conservative_futures_spec("MX").asset_symbol == "MIX"
    with pytest.raises(ValueError, match="Neizvestnyi"):
        conservative_futures_spec("UNKNOWN")


@pytest.mark.parametrize(
    ("value", "volume", "waprice"),
    [
        (np.nan, 1.0, 1.0),
        (1.0, np.inf, 1.0),
        (1.0, 1.0, 0.0),
        (-1.0, 1.0, 1.0),
        ("bad", 1.0, 1.0),
    ],
)
def test_realized_multiplier_accepts_only_finite_positive_inputs(
    value: object,
    volume: object,
    waprice: object,
) -> None:
    """Zapreshchaet nulevye, otricatel'nye, beskonechnye i ne-number proxy inputs."""
    assert np.isnan(realized_rub_point_multiplier(value, volume, waprice))
    assert realized_rub_point_multiplier(10_000.0, 100.0, 50.0) == pytest.approx(2.0)


def test_accounting_and_sizing_point_values_are_explicitly_separate() -> None:
    """Proveryaet current accounting formulu i strogo predydushchii sizing spec."""
    proxy = build_causal_spec_proxy(_daily(), _calendar())
    first, second = proxy.iloc[:2].itertuples(index=False)
    assert first.realized_accounting_point_value == pytest.approx(2.0)
    assert first.realized_point_value_formula == "VALUE/(VOLUME*WAPRICE)"
    assert first.realized_accounting_status == "available_primary_after_session"
    assert first.sizing_status == "missing_previous_contract_session"
    assert np.isnan(first.sizing_point_value)
    assert second.realized_accounting_point_value == pytest.approx(3.0)
    assert second.sizing_point_value == pytest.approx(2.0)
    assert second.sizing_reference_price == pytest.approx(50.0)
    assert second.sizing_notional == pytest.approx(100.0)
    assert second.sizing_tick_cash_value == pytest.approx(2.0)
    assert second.modeled_initial_margin == pytest.approx(25.0)
    assert second.expected_buffered_initial_margin == pytest.approx(50.0)
    assert second.conservative_fee_per_side == pytest.approx(4.0)
    assert second.sizing_observed_session_date == pd.Timestamp("2025-03-10")
    assert bool(second.approximate) and bool(second.research_only)
    assert not bool(second.historical_exchange_exact) and not bool(second.broker_exact)
    sizing = require_sizing_spec(proxy, "SiH5", "2025-03-11")
    assert sizing.sizing_point_value == pytest.approx(2.0)
    assert sizing.expected_buffered_initial_margin == pytest.approx(50.0)
    assert require_realized_accounting_point_value(
        proxy,
        "SiH5",
        "2025-03-11",
    ) == pytest.approx(3.0)
    with pytest.raises(LookupError, match="missing_previous"):
        require_sizing_spec(proxy, "SiH5", "2025-03-10")
    tampered = proxy.copy()
    tampered["approximate"] = tampered["approximate"].astype(object)
    tampered.loc[1, "approximate"] = "False"
    with pytest.raises(ValueError, match="oslableny"):
        require_sizing_spec(tampered, "SiH5", "2025-03-11")


def test_open_interest_fallback_is_selected_and_lagged_with_settle_reference() -> None:
    """Ispolzuet factual OI fallback tolko pri invalid primary i lagaet ego settle."""
    daily = _daily()
    daily.loc[0, "waprice"] = 0.0
    proxy = build_causal_spec_proxy(daily, _calendar())
    first, second = proxy.iloc[:2].itertuples(index=False)
    assert np.isnan(first.primary_trade_accounting_point_value)
    assert first.fallback_open_interest_accounting_point_value == pytest.approx(2.0)
    assert first.realized_accounting_point_value == pytest.approx(2.0)
    assert first.realized_reference_price == pytest.approx(50.5)
    assert first.realized_point_value_formula == FALLBACK_REALIZED_POINT_VALUE_FORMULA
    assert first.realized_accounting_status == "available_fallback_after_session"
    assert second.sizing_point_value == pytest.approx(2.0)
    assert second.sizing_reference_price == pytest.approx(50.5)
    assert second.sizing_notional == pytest.approx(101.0)
    assert require_realized_accounting_point_value(
        proxy, "SiH5", "2025-03-10"
    ) == pytest.approx(2.0)
    assert realized_rub_open_interest_point_multiplier(
        20_200.0, 200.0, 50.5
    ) == pytest.approx(2.0)


def test_current_and_future_mutation_cannot_change_current_sizing() -> None:
    """Dokazyvaet, chto current realized i future row ne pronikayut v tekushchii sizing."""
    original = build_causal_spec_proxy(_daily(), _calendar())
    mutated_daily = _daily()
    mutated_daily.loc[1, ["value", "waprice"]] = [1_000_000.0, 500.0]
    mutated_daily.loc[2, ["value", "volume", "waprice"]] = [9_000_000.0, 2.0, 900.0]
    mutated = build_causal_spec_proxy(mutated_daily, _calendar())
    assert mutated.iloc[1]["realized_accounting_point_value"] != original.iloc[1][
        "realized_accounting_point_value"
    ]
    assert mutated.iloc[1]["sizing_point_value"] == original.iloc[1]["sizing_point_value"]
    assert mutated.iloc[1]["sizing_reference_price"] == original.iloc[1][
        "sizing_reference_price"
    ]
    pd.testing.assert_series_equal(
        mutated.iloc[0],
        original.iloc[0],
        check_names=False,
    )


def test_future_append_preserves_prefix_and_detects_historical_rewrite() -> None:
    """Prinimaet tol'ko budushchii append i otklonyaet mutaciyu starogo VALUE."""
    existing = build_causal_spec_proxy(_daily(2), _calendar())
    candidate = build_causal_spec_proxy(_daily(3), _calendar())
    assert_append_only_spec_proxy(existing, candidate)
    pd.testing.assert_frame_equal(existing, candidate.iloc[:2].reset_index(drop=True))
    rewritten_daily = _daily(3)
    rewritten_daily.loc[0, "value"] = 11_000.0
    rewritten = build_causal_spec_proxy(rewritten_daily, _calendar())
    with pytest.raises(ValueError, match="izmenil"):
        assert_append_only_spec_proxy(existing, rewritten)


def test_missing_previous_invalid_and_stale_are_not_usable() -> None:
    """Fail-closed delaet NaN dlya invalid previous proxy i propushchennoi sessii."""
    invalid_previous = _daily(2)
    invalid_previous.loc[0, "waprice"] = np.nan
    invalid_previous.loc[0, "open_interest_value"] = np.nan
    invalid_proxy = build_causal_spec_proxy(invalid_previous, _calendar())
    assert invalid_proxy.iloc[0]["realized_accounting_status"] == (
        "invalid_primary_and_fallback"
    )
    assert invalid_proxy.iloc[1]["sizing_status"] == "previous_session_proxy_invalid"
    assert not bool(invalid_proxy.iloc[1]["sizing_usable"])
    assert np.isnan(invalid_proxy.iloc[1]["sizing_point_value"])
    with pytest.raises(LookupError, match="previous_session_proxy_invalid"):
        require_sizing_spec(invalid_proxy, "SiH5", "2025-03-11")

    stale_daily = _daily().iloc[[0, 2]].reset_index(drop=True)
    stale_proxy = build_causal_spec_proxy(stale_daily, _calendar())
    assert stale_proxy.iloc[1]["sizing_status"] == "stale_previous_contract_session"
    assert not bool(stale_proxy.iloc[1]["sizing_usable"])
    assert np.isnan(stale_proxy.iloc[1]["modeled_initial_margin"])
    with pytest.raises(LookupError, match="stale_previous_contract_session"):
        require_sizing_spec(stale_proxy, "SiH5", "2025-03-12")


def test_unknown_missing_duplicate_calendar_and_holdout_fail_closed() -> None:
    """Otkazyvaetsya ot unknown asset, skhemy, duplicate, vnesession i 2026 dat."""
    unknown = _daily(1)
    unknown.loc[0, "asset_symbol"] = "UNKNOWN"
    with pytest.raises(ValueError, match="Neizvestnyi"):
        build_causal_spec_proxy(unknown, _calendar())
    with pytest.raises(ValueError, match="kolonok"):
        build_causal_spec_proxy(_daily(1).drop(columns="waprice"), _calendar())
    duplicated = pd.concat([_daily(1), _daily(1)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        build_causal_spec_proxy(duplicated, _calendar())
    with pytest.raises(ValueError, match="vne factual"):
        build_causal_spec_proxy(_daily(3), _calendar()[:2])
    bad_calendar = pd.DatetimeIndex(["2025-03-11", "2025-03-10"])
    with pytest.raises(ValueError, match="rastushchim"):
        build_causal_spec_proxy(_daily(1), bad_calendar)
    holdout = _daily(1)
    holdout.loc[0, "session_date"] = "2026-01-05"
    with pytest.raises(ValueError, match="holdout"):
        build_causal_spec_proxy(holdout, pd.DatetimeIndex(["2026-01-05"]))


def test_real_iss_alias_columns_and_input_order_are_deterministic() -> None:
    """Prinimaet trade_date/secid/asset_code i ne zavisit ot poryadka strok."""
    aliased = _daily().rename(
        columns={
            "session_date": "trade_date",
            "contract_id": "secid",
            "asset_symbol": "asset_code",
        }
    )
    direct = build_causal_spec_proxy(_daily(), _calendar())
    shuffled = build_causal_spec_proxy(aliased.sample(frac=1.0, random_state=42), _calendar())
    pd.testing.assert_frame_equal(direct, shuffled)
