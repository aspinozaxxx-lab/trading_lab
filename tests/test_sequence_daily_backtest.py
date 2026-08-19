"""Tochnye proverki prichinnogo pyatisleeve daily-backtesta."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.sequence.daily_backtest import (
    DailyBacktestConfig,
    DailyStrategySpec,
    run_staggered_daily_backtest,
    select_daily_weights,
)

TEST_CAPITAL = 1_000.0  # Nachalnyi kapital korotkih arifmeticheskih testov.
LARGE_DAILY_VALUE = 1_000_000.0  # Likvidnost bez ogranicheniya testovyh orderov.


def _panel(
    sessions: pd.DatetimeIndex,
    opens_by_ticker: dict[str, list[float]],
    raw_value: float = LARGE_DAILY_VALUE,
) -> pd.DataFrame:
    """Stroit minimalnyi factual daily-panel s zadannymi open."""
    rows: list[dict[str, object]] = []
    for ticker, opens in opens_by_ticker.items():
        if len(opens) != len(sessions):
            raise ValueError("Dlina open ne sovpadaet s session-calendar")
        rows.extend(
            {
                "session_date": session,
                "ticker": ticker,
                "raw_open": open_price,
                "raw_value": raw_value,
            }
            for session, open_price in zip(sessions, opens, strict=True)
        )
    return pd.DataFrame(rows)


def _signals(rows: list[tuple[pd.Timestamp, str, float]]) -> pd.DataFrame:
    """Stroit signaly posle close bez execution-kolonok."""
    return pd.DataFrame(rows, columns=["session_date", "ticker", "prediction"])


def _zero_cost_config(**updates: float) -> DailyBacktestConfig:
    """Vozvrashchaet malyi portfolio-config bez skrytyh izderzhek."""
    values: dict[str, float] = {
        "initial_capital": TEST_CAPITAL,
        "commission_bps": 0.0,
        "slippage_bps": 0.0,
        "target_gross_leverage": 1.0,
        "maximum_gross_leverage": 1.0,
    }
    values.update(updates)
    return DailyBacktestConfig(**values)


def test_next_open_exact_arithmetic_and_five_session_sleeve() -> None:
    """Proveryaet vhody D+1, pyatidnevnyi hold i tochnyi cash-PnL."""
    sessions = pd.bdate_range("2025-01-02", periods=7)
    panel = _panel(sessions, {"AAA": [9.0, 10.0, 11.0, 11.0, 11.0, 11.0, 12.0]})
    predictions = _signals([(sessions[0], "AAA", 1.0)])
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(top_k=1, keep_rank=1),
        _zero_cost_config(),
    )
    assert result.orders["session_date"].tolist() == [sessions[1], sessions[6]]
    assert result.orders["price"].tolist() == pytest.approx([10.0, 12.0])
    assert result.orders["quantity"].tolist() == pytest.approx([20.0, -20.0])
    assert result.metrics["final_equity"] == pytest.approx(1_040.0)
    assert result.metrics["total_return"] == pytest.approx(0.04)
    assert result.metrics["trade_count"] == 2
    assert result.ledger["rebalanced_sleeve"].tolist() == [0, 1, 2, 3, 4, 0]


def test_commission_slippage_and_participation_are_exact() -> None:
    """Proveryaet adverse costs po actual net order notional."""
    sessions = pd.bdate_range("2025-02-03", periods=7)
    panel = _panel(sessions, {"AAA": [10.0] * 7})
    predictions = _signals([(sessions[0], "AAA", 1.0)])
    config = DailyBacktestConfig(
        initial_capital=TEST_CAPITAL,
        commission_bps=100.0,
        slippage_bps=200.0,
        target_gross_leverage=1.0,
        maximum_gross_leverage=1.0,
    )
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(),
        config,
    )
    expected_notional = 200.0 / 1.006
    expected_commission = 2.0 * expected_notional * 0.01
    expected_slippage = 2.0 * expected_notional * 0.02
    expected_equity = TEST_CAPITAL - expected_commission - expected_slippage
    assert result.orders["absolute_notional"].tolist() == pytest.approx(
        [expected_notional, expected_notional]
    )
    assert result.metrics["commission_cost"] == pytest.approx(expected_commission)
    assert result.metrics["slippage_cost"] == pytest.approx(expected_slippage)
    assert result.metrics["final_equity"] == pytest.approx(expected_equity)
    assert result.orders.iloc[0]["participation"] == pytest.approx(
        expected_notional / LARGE_DAILY_VALUE
    )


def test_all_five_sleeves_are_staggered_and_respect_gross_cap() -> None:
    """Proveryaet ezhednevnyi phase-start i odin rebalance na sleeve za pyat session."""
    sessions = pd.bdate_range("2025-03-03", periods=7)
    panel = _panel(sessions, {"AAA": [10.0] * 7})
    predictions = _signals([(session, "AAA", 1.0) for session in sessions[:5]])
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(),
        _zero_cost_config(),
    )
    first_five = result.ledger.iloc[:5]
    assert first_five["rebalanced_sleeve"].tolist() == [0, 1, 2, 3, 4]
    assert first_five["gross_leverage"].tolist() == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0])
    assert (result.ledger["gross_leverage"] <= 1.0 + 1e-8).all()


def test_pending_exit_and_new_entry_are_netted_across_sleeves() -> None:
    """Proveryaet vnutrennii perenos quantities bez fiktivnogo oborota."""
    sessions = pd.bdate_range("2025-04-01", periods=8)
    opens = [10.0] * 8
    opens[6] = np.nan
    panel = _panel(sessions, {"AAA": opens})
    predictions = _signals(
        [
            (sessions[0], "AAA", 1.0),
            (sessions[6], "AAA", 1.0),
        ]
    )
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(),
        _zero_cost_config(),
    )
    day_seven_orders = result.orders.loc[result.orders["session_date"].eq(sessions[7])]
    assert day_seven_orders.empty
    day_seven = result.weights.loc[
        result.weights["session_date"].eq(sessions[7]) & result.weights["ticker"].eq("AAA")
    ]
    assert day_seven.set_index("sleeve_id")["quantity"].to_dict() == pytest.approx({1: 20.0})
    assert result.metrics["missing_exit_count"] == 1
    assert result.metrics["holding_extension_sessions"] == 1
    assert not result.execution_complete


def test_missing_exit_carries_to_first_real_open_without_synthetic_price() -> None:
    """Proveryaet carry cherez dve session i zakrytie po pervomu factual open."""
    sessions = pd.bdate_range("2025-05-05", periods=9)
    opens = [10.0] * 9
    opens[6] = np.nan
    opens[7] = np.nan
    opens[8] = 8.0
    panel = _panel(sessions, {"AAA": opens})
    result = run_staggered_daily_backtest(
        _signals([(sessions[0], "AAA", 1.0)]),
        panel,
        DailyStrategySpec(),
        _zero_cost_config(),
    )
    exit_order = result.orders.iloc[-1]
    assert exit_order["session_date"] == sessions[8]
    assert exit_order["price"] == pytest.approx(8.0)
    assert exit_order["quantity"] == pytest.approx(-20.0)
    assert result.metrics["final_equity"] == pytest.approx(960.0)
    assert result.metrics["missing_exit_count"] == 1
    assert result.metrics["holding_extension_sessions"] == 2
    assert result.metrics["maximum_holding_extension_sessions"] == 2
    assert result.metrics["unresolved_exit_count"] == 0
    assert not result.execution_complete


def test_short_borrow_uses_actual_value_and_calendar_elapsed() -> None:
    """Proveryaet borrow po short market value za pyatnicu-vyhodnye."""
    sessions = pd.DatetimeIndex(["2025-01-02", "2025-01-03", "2025-01-06"])
    panel = _panel(sessions, {"AAA": [10.0] * 3, "BBB": [10.0, 10.0, 20.0]})
    predictions = _signals(
        [
            (sessions[0], "AAA", 1.0),
            (sessions[0], "BBB", -1.0),
        ]
    )
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(position_mode="long_short"),
        _zero_cost_config(short_borrow_rate_annual=0.36525),
    )
    assert result.ledger.iloc[0]["short_borrow_cost"] == pytest.approx(0.0)
    assert result.ledger.iloc[1]["short_borrow_cost"] == pytest.approx(0.6)
    assert result.metrics["short_borrow_cost"] == pytest.approx(0.6)
    assert result.metrics["final_equity"] == pytest.approx(899.4)
    entry_orders = result.orders.loc[result.orders["session_date"].eq(sessions[1])]
    signed = entry_orders.set_index("ticker")["signed_notional"].to_dict()
    assert signed == pytest.approx({"AAA": 100.0, "BBB": -100.0})


def test_selection_ignores_future_columns_and_missing_entry_stays_cash() -> None:
    """Proveryaet chto target/open ne menyayut intent, a no-fill ne zamenyaetsya B."""
    session = pd.Timestamp("2025-06-02")
    signals = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "prediction": [2.0, 1.0],
            "future_target": [np.nan, 0.50],
            "future_open": [np.nan, 10.0],
        }
    )
    first = select_daily_weights(signals, DailyStrategySpec())
    changed = signals.assign(future_target=[-0.99, np.nan], future_open=[999.0, np.nan])
    second = select_daily_weights(changed, DailyStrategySpec())
    pd.testing.assert_series_equal(first, second)
    sessions = pd.bdate_range(session, periods=2)
    panel = _panel(sessions, {"AAA": [10.0, np.nan], "BBB": [10.0, 10.0]})
    predictions = _signals([(sessions[0], "AAA", 2.0), (sessions[0], "BBB", 1.0)])
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(),
        _zero_cost_config(),
    )
    assert result.orders.empty
    assert result.metrics["missing_entry_count"] == 1
    assert result.metrics["final_equity"] == pytest.approx(TEST_CAPITAL)
    assert not result.execution_complete


def test_hysteresis_uses_actual_fill_instead_of_previous_intent() -> None:
    """Proveryaet chto no-fill A ne schitaetsya uderzhivaemoi poziciei cherez pyat dnei."""
    sessions = pd.bdate_range("2025-07-01", periods=7)
    a_opens = [10.0] * 7
    a_opens[1] = np.nan
    panel = _panel(sessions, {"AAA": a_opens, "BBB": [10.0] * 7})
    predictions = _signals(
        [
            (sessions[0], "AAA", 2.0),
            (sessions[0], "BBB", 1.0),
            (sessions[5], "AAA", 1.5),
            (sessions[5], "BBB", 2.0),
        ]
    )
    result = run_staggered_daily_backtest(
        predictions,
        panel,
        DailyStrategySpec(top_k=1, keep_rank=2),
        _zero_cost_config(),
    )
    rebalance_orders = result.orders.loc[result.orders["session_date"].eq(sessions[6])]
    assert rebalance_orders["ticker"].tolist() == ["BBB"]
    assert rebalance_orders.iloc[0]["quantity"] == pytest.approx(20.0)


def test_long_short_uses_relative_spread_instead_of_score_sign() -> None:
    """Proveryaet dollar-neutral selection pri proizvol'nom sdvige score."""
    signals = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD"],
            "prediction": [4.0, 3.0, 2.0, 1.0],
        }
    )
    weights = select_daily_weights(
        signals,
        DailyStrategySpec(position_mode="long_short", top_k=2, keep_rank=2),
    )
    assert weights.abs().sum() == pytest.approx(1.0)
    assert weights.sum() == pytest.approx(0.0)
    assert (weights.loc[["AAA", "BBB"]] > 0.0).all()
    assert (weights.loc[["CCC", "DDD"]] < 0.0).all()


def test_unknown_lagged_liquidity_fails_participation_gate_closed() -> None:
    """Proveryaet chto neizvestnyi oborot ne maskiruetsya nulevoi participation."""
    sessions = pd.bdate_range("2025-08-01", periods=7)
    panel = _panel(sessions, {"AAA": [10.0] * 7}, raw_value=0.0)
    result = run_staggered_daily_backtest(
        _signals([(sessions[0], "AAA", 1.0)]),
        panel,
        DailyStrategySpec(),
        _zero_cost_config(),
    )
    assert np.isinf(result.orders["participation"]).all()
    assert result.metrics["invalid_participation_count"] == 2
    assert result.metrics["maximum_participation"] >= 1.0
    assert not result.execution_complete


def test_unavailable_same_direction_rebalance_is_reported() -> None:
    """Proveryaet fail-closed status esli uderzhivaemuyu poziciyu nelzya rebalance."""
    sessions = pd.bdate_range("2025-09-01", periods=7)
    opens = [10.0] * 7
    opens[6] = np.nan
    panel = _panel(sessions, {"AAA": opens})
    result = run_staggered_daily_backtest(
        _signals(
            [
                (sessions[0], "AAA", 1.0),
                (sessions[5], "AAA", 1.0),
            ]
        ),
        panel,
        DailyStrategySpec(),
        _zero_cost_config(),
    )
    assert result.metrics["missing_rebalance_count"] == 1
    assert not result.execution_complete
