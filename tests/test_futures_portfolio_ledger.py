"""Testy obshchego cash-pool ledger dlya neskol'kih futures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    run_futures_portfolio_ledger,
)


def _market() -> pd.DataFrame:
    """Stroit tri factual sessii SI i MIX s prostoi tochnoy arifmetikoi."""
    dates = pd.bdate_range("2025-03-10", periods=3)
    rows: list[dict[str, object]] = []
    values = {
        "SI": ("SiH5", [99.0, 100.0, 101.0], [100.0, 101.0, 102.0], 10.0),
        "MIX": ("MXH5", [49.0, 50.0, 51.0], [50.0, 51.0, 50.0], 20.0),
    }
    for asset, (contract, opens, settles, point_value) in values.items():
        for index, session_date in enumerate(dates):
            open_price = opens[index]
            settle = settles[index]
            rows.append(
                {
                    "session_date": session_date,
                    "asset_code": asset,
                    "contract_id": contract,
                    "open": open_price,
                    "high": max(open_price, settle) + 2.0,
                    "low": min(open_price, settle) - 2.0,
                    "settle": settle,
                    "volume": 10_000.0,
                    "point_value": point_value,
                    "tick_size": 0.5,
                    "fee_per_contract": 2.0,
                    "initial_margin": 100.0,
                }
            )
    return pd.DataFrame(rows)


def _config(**changes: object) -> FuturesPortfolioLedgerConfig:
    """Stroit dvuhaktivnyi testovyi config s obshchim kapitalom."""
    values: dict[str, object] = {
        "initial_cash": 10_000.0,
        "expected_assets": ("SI", "MIX"),
    }
    values.update(changes)
    return FuturesPortfolioLedgerConfig(**values)


def _targets(si_weight: float = 0.4, mix_weight: float = 0.4) -> pd.DataFrame:
    """Stroit polnyi next-open snapshot dvuh aktivov."""
    return pd.DataFrame(
        [
            {
                "effective_date": "2025-03-11",
                "decision_date": "2025-03-10",
                "asset_code": "SI",
                "contract_id": "SiH5" if si_weight != 0.0 else None,
                "target_weight": si_weight,
            },
            {
                "effective_date": "2025-03-11",
                "decision_date": "2025-03-10",
                "asset_code": "MIX",
                "contract_id": "MXH5" if mix_weight != 0.0 else None,
                "target_weight": mix_weight,
            },
        ]
    )


def _exit_during_halt_case(
    *, include_reopen: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, FuturesPortfolioLedgerConfig]:
    """Stroit odnoaktivnyi exit vo vremya halt i optional factual reopen."""
    market = _market().loc[lambda frame: frame["asset_code"].eq("SI")].copy()
    halt = market["session_date"].eq(pd.Timestamp("2025-03-12"))
    market.loc[halt, ["open", "high", "low", "settle"]] = [
        np.nan,
        105.0,
        100.0,
        103.0,
    ]
    if include_reopen:
        reopen = market.loc[halt].copy()
        reopen["session_date"] = pd.Timestamp("2025-03-13")
        reopen[["open", "high", "low", "settle"]] = [104.0, 106.0, 103.0, 105.0]
        market = pd.concat([market, reopen], ignore_index=True)
    targets = pd.DataFrame(
        [
            {
                "effective_date": "2025-03-11",
                "decision_date": "2025-03-10",
                "asset_code": "SI",
                "contract_id": "SiH5",
                "target_weight": 0.5,
            },
            {
                "effective_date": "2025-03-12",
                "decision_date": "2025-03-11",
                "asset_code": "SI",
                "contract_id": None,
                "target_weight": 0.0,
            },
        ]
    )
    return market, targets, _config(expected_assets=("SI",))


def test_shared_cash_vm_integer_sizing_and_costs_are_exact() -> None:
    """Proveryaet obshchii kapital, integer contracts, VM i dve izderzhki."""
    result = run_futures_portfolio_ledger(_market(), _targets(), _config())

    entry_day = result.ledger.iloc[1]
    final_day = result.ledger.iloc[2]
    entry_positions = result.positions.loc[
        result.positions["session_date"] == pd.Timestamp("2025-03-11")
    ].set_index("asset_code")
    assert entry_positions.loc["SI", "contracts"] == 4
    assert entry_positions.loc["MIX", "contracts"] == 4
    assert entry_day["intraday_vm"] == pytest.approx(120.0)
    assert entry_day["commission_cost"] == pytest.approx(16.0)
    assert entry_day["slippage_cost"] == pytest.approx(60.0)
    assert entry_day["ending_cash"] == pytest.approx(10_044.0)
    assert final_day["variation_margin"] == pytest.approx(-40.0)
    assert result.metrics["ending_cash"] == pytest.approx(10_004.0)
    assert result.metrics["variation_margin"] == pytest.approx(80.0)
    assert result.metrics["total_cost"] == pytest.approx(76.0)
    assert result.execution_complete


def test_one_missing_leg_rejects_entire_portfolio_snapshot() -> None:
    """Proveryaet atomic halt-retry bez chastichnogo fill pervoi sessii."""
    market = _market()
    missing = (market["session_date"] == pd.Timestamp("2025-03-11")) & market[
        "asset_code"
    ].eq("MIX")
    market.loc[missing, "open"] = np.nan

    result = run_futures_portfolio_ledger(market, _targets(), _config())

    assert not result.orders.empty
    first_attempt = result.orders["session_date"].eq(pd.Timestamp("2025-03-11"))
    retry = result.orders["session_date"].eq(pd.Timestamp("2025-03-12"))
    assert not result.orders.loc[first_attempt, "filled"].any()
    assert result.orders.loc[first_attempt, "rejection_class"].eq(
        "factual_halt"
    ).all()
    assert result.orders.loc[retry, "filled"].all()
    assert result.orders.loc[retry, "rejection_class"].eq("resolved_halt").all()
    entry_positions = result.positions.loc[
        result.positions["session_date"] == pd.Timestamp("2025-03-11")
    ]
    assert (entry_positions["contracts"] == 0).all()
    assert result.metrics["atomic_rejection_count"] == 0
    assert result.metrics["halt_only_portfolio_rejection_count"] == 1
    assert result.metrics["halt_resolved_count"] == 1
    assert result.metrics["critical_failure_count"] == 0
    assert result.metrics["unresolved_halt_count"] == 0
    assert result.execution_complete


def test_asset_atomicity_fills_independent_asset_and_keeps_failed_asset() -> None:
    """Proveryaet nezavisimoe SI execution pri nedostupnom MIX bez partial rola asset."""
    market = _market()
    missing = (market["session_date"] == pd.Timestamp("2025-03-11")) & market[
        "asset_code"
    ].eq("MIX")
    market.loc[missing, "open"] = np.nan

    result = run_futures_portfolio_ledger(
        market,
        _targets(),
        _config(execution_atomicity="asset"),
    )

    positions = result.positions.loc[
        result.positions["session_date"] == pd.Timestamp("2025-03-11")
    ].set_index("asset_code")
    assert positions.loc["SI", "contracts"] == 4
    assert positions.loc["MIX", "contracts"] == 0
    assert result.orders.loc[result.orders["asset_code"].eq("SI"), "filled"].all()
    final_positions = result.positions.loc[
        result.positions["session_date"] == pd.Timestamp("2025-03-12")
    ].set_index("asset_code")
    assert final_positions.loc["MIX", "contracts"] > 0
    assert result.ledger.iloc[1]["status"] == "partial_asset_atomic_halt_pending"
    assert result.metrics["atomic_rejection_count"] == 0
    assert result.metrics["halt_only_asset_rejection_count"] == 1
    assert result.metrics["halt_resolved_count"] == 1
    assert result.metrics["critical_failure_count"] == 0
    assert result.execution_complete


def test_long_short_weights_preserve_sign_and_shared_gross_cap() -> None:
    """Proveryaet odnovremennyi long SI i short MIX bez netting gross-riska."""
    result = run_futures_portfolio_ledger(
        _market(),
        _targets(0.5, -0.5),
        _config(),
    )
    entry_positions = result.positions.loc[
        result.positions["session_date"] == pd.Timestamp("2025-03-11")
    ].set_index("asset_code")
    assert entry_positions.loc["SI", "contracts"] == 4
    assert entry_positions.loc["MIX", "contracts"] == -5
    assert result.ledger.iloc[1]["gross_notional"] == pytest.approx(9_140.0)
    assert result.metrics["maximum_gross_notional"] >= 9_000.0
    assert result.metrics["intraday_adverse_drawdown"] > 0.0


def test_snapshot_must_be_complete_causal_and_at_most_one_x() -> None:
    """Proveryaet polnyi universe, next-open i aggregate target gross."""
    with pytest.raises(ValueError, match="Nepolnyi asset snapshot"):
        run_futures_portfolio_ledger(_market(), _targets().iloc[:1], _config())
    same_day = _targets()
    same_day["decision_date"] = same_day["effective_date"]
    with pytest.raises(ValueError, match="ran'she"):
        run_futures_portfolio_ledger(_market(), same_day, _config())
    excessive = _targets(0.6, 0.6)
    with pytest.raises(ValueError, match="Gross target weights"):
        run_futures_portfolio_ledger(_market(), excessive, _config())


def test_future_market_mutation_cannot_change_past_cash_or_orders() -> None:
    """Proveryaet append-only cash-events do izmenennoi budushchei sessii."""
    market = _market()
    baseline = run_futures_portfolio_ledger(market, _targets(), _config())
    changed = market.copy()
    future = changed["session_date"] == pd.Timestamp("2025-03-12")
    changed.loc[future, ["open", "high", "low", "settle", "volume"]] = [
        150.0,
        155.0,
        145.0,
        152.0,
        1.0,
    ]
    revised = run_futures_portfolio_ledger(changed, _targets(), _config())

    columns = [
        "session_date",
        "variation_margin",
        "commission_cost",
        "slippage_cost",
        "ending_cash",
    ]
    pd.testing.assert_frame_equal(
        baseline.ledger.loc[
            baseline.ledger["session_date"] <= pd.Timestamp("2025-03-11"), columns
        ].reset_index(drop=True),
        revised.ledger.loc[
            revised.ledger["session_date"] <= pd.Timestamp("2025-03-11"), columns
        ].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(baseline.orders, revised.orders)


def test_no_order_halt_with_settle_is_complete_diagnostic_carry() -> None:
    """Proveryaet complete diagnostic carry bez ordera na halt sessii."""
    market = _market()
    missing = (market["session_date"] == pd.Timestamp("2025-03-12")) & market[
        "asset_code"
    ].eq("SI")
    market.loc[missing, "open"] = np.nan

    result = run_futures_portfolio_ledger(market, _targets(), _config())

    missing_day = result.ledger.loc[
        result.ledger["session_date"] == pd.Timestamp("2025-03-12")
    ].iloc[0]
    assert missing_day["fallback_settle_vm"] == pytest.approx(40.0)
    assert missing_day["status"] == "factual_halt_carry"
    assert missing_day["critical_blocked_asset_count"] == 0
    assert missing_day["factual_halt_asset_count"] == 1
    assert result.metrics["factual_halt_mark_count"] == 1
    assert result.metrics["halt_carry_count"] == 1
    assert result.metrics["missing_open_count"] == 0
    assert result.metrics["critical_failure_count"] == 0
    assert result.metrics["unresolved_halt_count"] == 0
    assert result.execution_complete


def test_exit_during_halt_reopens_with_exact_vm_and_costs() -> None:
    """Proveryaet pending exit, factual reopen i tochnyi cash-path."""
    market, targets, config = _exit_during_halt_case(include_reopen=True)

    result = run_futures_portfolio_ledger(market, targets, config)

    halt_day = result.ledger.loc[
        result.ledger["session_date"].eq(pd.Timestamp("2025-03-12"))
    ].iloc[0]
    reopen_day = result.ledger.loc[
        result.ledger["session_date"].eq(pd.Timestamp("2025-03-13"))
    ].iloc[0]
    exit_orders = result.orders.loc[result.orders["leg"].eq("exit")]
    assert halt_day["fallback_settle_vm"] == pytest.approx(100.0)
    assert halt_day["pending_halt_count"] == 1
    assert reopen_day["overnight_gap_vm"] == pytest.approx(50.0)
    assert exit_orders["filled"].tolist() == [False, True]
    assert exit_orders["rejection_class"].tolist() == [
        "factual_halt",
        "resolved_halt",
    ]
    assert result.metrics["variation_margin"] == pytest.approx(200.0)
    assert result.metrics["commission_cost"] == pytest.approx(20.0)
    assert result.metrics["slippage_cost"] == pytest.approx(50.0)
    assert result.metrics["total_cost"] == pytest.approx(70.0)
    assert result.metrics["ending_cash"] == pytest.approx(10_130.0)
    assert result.metrics["halt_resolved_count"] == 1
    assert result.metrics["unresolved_halt_count"] == 0
    assert result.execution_complete


def test_terminal_halt_order_is_unresolved_without_critical_failure() -> None:
    """Proveryaet terminal pending halt kak otdel'nuyu incomplete prichinu."""
    market, targets, config = _exit_during_halt_case(include_reopen=False)

    result = run_futures_portfolio_ledger(market, targets, config)

    assert result.metrics["critical_failure_count"] == 0
    assert result.metrics["unresolved_halt_count"] == 1
    assert result.metrics["halt_resolved_count"] == 0
    assert result.metrics["atomic_rejection_count"] == 0
    assert not result.execution_complete


def test_cancel_and_clip_policy_discards_halt_target_without_retry() -> None:
    """Proveryaet causal cancel tekushchei popytki vmesto GTC cherez halt."""
    market, targets, _ = _exit_during_halt_case(include_reopen=True)
    config = _config(
        expected_assets=("SI",),
        execution_atomicity="asset",
        unexecutable_target_policy="cancel_and_clip",
    )

    result = run_futures_portfolio_ledger(market, targets, config)

    assert result.orders["leg"].eq("entry").all()
    assert result.positions.iloc[-1]["contracts"] == 5
    assert result.metrics["target_cancel_no_open_count"] == 1
    assert result.metrics["unresolved_halt_count"] == 0
    assert result.metrics["critical_failure_count"] == 0
    assert result.execution_complete


def test_cancel_and_clip_policy_sleeps_without_lagged_liquidity() -> None:
    """Proveryaet admission sleep pri unknown prior volume bez missing=zero fill."""
    market = _market().loc[lambda frame: frame["asset_code"].eq("SI")].copy()
    market.loc[
        market["session_date"].eq(pd.Timestamp("2025-03-10")), "volume"
    ] = np.nan
    targets = _targets(si_weight=0.5, mix_weight=0.0).iloc[:1].copy()

    result = run_futures_portfolio_ledger(
        market,
        targets,
        _config(
            expected_assets=("SI",),
            execution_atomicity="asset",
            unexecutable_target_policy="cancel_and_clip",
        ),
    )

    assert result.orders.empty
    assert result.positions["contracts"].eq(0).all()
    assert result.metrics["target_cancel_no_liquidity_count"] == 1
    assert result.metrics["unknown_liquidity_count"] == 0
    assert result.execution_complete


def test_cancel_and_clip_policy_limits_known_participation_before_order() -> None:
    """Proveryaet partial quantity po exact prior-volume capacity."""
    market = _market().loc[lambda frame: frame["asset_code"].eq("SI")].copy()
    market.loc[
        market["session_date"].eq(pd.Timestamp("2025-03-10")), "volume"
    ] = 200.0
    targets = _targets(si_weight=0.9, mix_weight=0.0).iloc[:1].copy()

    result = run_futures_portfolio_ledger(
        market,
        targets,
        _config(
            expected_assets=("SI",),
            execution_atomicity="asset",
            unexecutable_target_policy="cancel_and_clip",
        ),
    )

    assert result.orders.iloc[0]["quantity_delta"] == 2
    assert result.orders.iloc[0]["participation"] == pytest.approx(0.01)
    assert result.orders.iloc[0]["reason"] == "filled_participation_clipped"
    assert result.metrics["participation_clip_count"] == 1
    assert result.metrics["participation_rejection_count"] == 0
    assert result.execution_complete


def test_missing_settle_is_critical_and_never_masked_as_halt() -> None:
    """Proveryaet fail-closed pri neizvestnom settle vmesto halt-diagnostic."""
    market, targets, config = _exit_during_halt_case(include_reopen=False)
    broken = market["session_date"].eq(pd.Timestamp("2025-03-12"))
    market.loc[broken, "settle"] = np.nan

    result = run_futures_portfolio_ledger(market, targets, config)

    rejected_exit = result.orders.loc[result.orders["leg"].eq("exit")].iloc[0]
    assert rejected_exit["rejection_class"] == "critical"
    assert "missing_factual_settle" in rejected_exit["reason"]
    assert result.metrics["missing_settle_count"] > 0
    assert result.metrics["critical_failure_count"] > 0
    assert result.metrics["factual_halt_event_count"] == 0
    assert result.metrics["unresolved_halt_count"] == 0
    assert not result.execution_complete


def test_portfolio_and_asset_atomic_halt_stress_are_unambiguous() -> None:
    """Proveryaet group retry protiv nezavisimogo asset exit na odnom halt."""
    market = _market()
    halt = market["session_date"].eq(pd.Timestamp("2025-03-12")) & market[
        "asset_code"
    ].eq("MIX")
    market.loc[halt, "open"] = np.nan
    reopen = market.loc[
        market["session_date"].eq(pd.Timestamp("2025-03-12"))
    ].copy()
    reopen["session_date"] = pd.Timestamp("2025-03-13")
    reopen.loc[
        reopen["asset_code"].eq("SI"), ["open", "high", "low", "settle"]
    ] = [102.0, 105.0, 100.0, 103.0]
    reopen.loc[
        reopen["asset_code"].eq("MIX"), ["open", "high", "low", "settle"]
    ] = [50.0, 53.0, 48.0, 51.0]
    market = pd.concat([market, reopen], ignore_index=True)
    exits = _targets(0.0, 0.0)
    exits["effective_date"] = "2025-03-12"
    exits["decision_date"] = "2025-03-11"
    targets = pd.concat([_targets(), exits], ignore_index=True)

    portfolio = run_futures_portfolio_ledger(market, targets, _config())
    asset = run_futures_portfolio_ledger(
        market,
        targets,
        _config(execution_atomicity="asset"),
    )

    portfolio_exits = portfolio.orders.loc[portfolio.orders["leg"].eq("exit")]
    portfolio_halt = portfolio_exits["session_date"].eq(
        pd.Timestamp("2025-03-12")
    )
    portfolio_reopen = portfolio_exits["session_date"].eq(
        pd.Timestamp("2025-03-13")
    )
    assert not portfolio_exits.loc[portfolio_halt, "filled"].any()
    assert portfolio_exits.loc[portfolio_halt, "rejection_class"].eq(
        "factual_halt"
    ).all()
    assert portfolio_exits.loc[portfolio_reopen, "filled"].all()
    assert portfolio.metrics["halt_only_portfolio_rejection_count"] == 1
    assert portfolio.metrics["halt_only_asset_rejection_count"] == 0
    assert portfolio.metrics["halt_resolved_count"] == 1
    assert portfolio.execution_complete

    asset_exits = asset.orders.loc[asset.orders["leg"].eq("exit")]
    si_halt_exit = asset_exits["session_date"].eq(
        pd.Timestamp("2025-03-12")
    ) & asset_exits["asset_code"].eq("SI")
    mix_halt_exit = asset_exits["session_date"].eq(
        pd.Timestamp("2025-03-12")
    ) & asset_exits["asset_code"].eq("MIX")
    mix_reopen_exit = asset_exits["session_date"].eq(
        pd.Timestamp("2025-03-13")
    ) & asset_exits["asset_code"].eq("MIX")
    assert asset_exits.loc[si_halt_exit, "filled"].all()
    assert not asset_exits.loc[mix_halt_exit, "filled"].any()
    assert asset_exits.loc[mix_halt_exit, "rejection_class"].eq(
        "factual_halt"
    ).all()
    assert asset_exits.loc[mix_reopen_exit, "rejection_class"].eq(
        "resolved_halt"
    ).all()
    assert asset.metrics["halt_only_asset_rejection_count"] == 1
    assert asset.metrics["halt_only_portfolio_rejection_count"] == 0
    assert asset.metrics["halt_resolved_count"] == 1
    assert asset.execution_complete


def test_sizing_multiplier_and_realized_accounting_multiplier_are_separate() -> None:
    """Proveryaet lagged sizing dlya quantity/cost i current proxy tol'ko dlya VM."""
    market = _market().loc[lambda frame: frame["asset_code"].eq("SI")].copy()
    market["sizing_point_value"] = 10.0
    market["accounting_point_value"] = 12.0
    market = market.drop(columns="point_value")
    targets = _targets(si_weight=0.5, mix_weight=0.0).iloc[:1].copy()
    result = run_futures_portfolio_ledger(
        market,
        targets,
        _config(expected_assets=("SI",)),
    )

    entry = result.ledger.iloc[1]
    order = result.orders.iloc[0]
    position = result.positions.loc[
        result.positions["session_date"] == pd.Timestamp("2025-03-11")
    ].iloc[0]
    assert position["contracts"] == 5
    assert order["point_value"] == pytest.approx(10.0)
    assert order["accounting_point_value"] == pytest.approx(12.0)
    assert order["slippage_cost"] == pytest.approx(25.0)
    assert entry["intraday_vm"] == pytest.approx(60.0)
    assert entry["ending_cash"] == pytest.approx(10_025.0)


def test_missing_either_multiplier_fails_closed_with_no_fill() -> None:
    """Proveryaet otkaz pri unknown lagged sizing ili current accounting proxy."""
    market = _market()
    market["sizing_point_value"] = market["point_value"]
    market["accounting_point_value"] = market["point_value"]
    market = market.drop(columns="point_value")
    missing_sizing = (market["session_date"] == pd.Timestamp("2025-03-11")) & market[
        "asset_code"
    ].eq("SI")
    market.loc[missing_sizing, "sizing_point_value"] = np.nan
    result = run_futures_portfolio_ledger(market, _targets(), _config())
    assert not result.orders["filled"].any()
    assert result.metrics["unknown_point_value_count"] > 0
    assert not result.execution_complete

    missing_accounting_market = _market()
    missing_accounting_market["sizing_point_value"] = missing_accounting_market[
        "point_value"
    ]
    missing_accounting_market["accounting_point_value"] = missing_accounting_market[
        "point_value"
    ]
    missing_accounting_market = missing_accounting_market.drop(columns="point_value")
    missing_accounting_market.loc[
        missing_sizing,
        "accounting_point_value",
    ] = np.nan
    missing_accounting = run_futures_portfolio_ledger(
        missing_accounting_market,
        _targets(),
        _config(),
    )
    assert missing_accounting.metrics["unknown_point_value_count"] > 0
    assert not missing_accounting.execution_complete


def test_intraday_drawdown_uses_running_peak_after_profit() -> None:
    """Proveryaet adverse DD ot novogo pika, dazhe esli equity vyshe starta."""
    market = _market().loc[lambda frame: frame["asset_code"].eq("SI")].copy()
    second = market["session_date"].eq(pd.Timestamp("2025-03-11"))
    third = market["session_date"].eq(pd.Timestamp("2025-03-12"))
    market.loc[second, ["open", "high", "low", "settle"]] = [100.0, 200.0, 100.0, 200.0]
    market.loc[third, ["open", "high", "low", "settle"]] = [200.0, 200.0, 150.0, 200.0]
    market["fee_per_contract"] = 0.0
    targets = _targets(si_weight=0.5, mix_weight=0.0).iloc[:1].copy()

    result = run_futures_portfolio_ledger(
        market,
        targets,
        _config(expected_assets=("SI",)),
    )

    assert result.ledger.iloc[1]["ending_cash"] == pytest.approx(14_975.0)
    assert result.ledger.iloc[2]["intraday_adverse_equity"] == pytest.approx(12_475.0)
    assert result.metrics["intraday_adverse_drawdown"] == pytest.approx(
        2_500.0 / 14_975.0
    )
