"""Testy completed-window POV, adverse cen i paired research rolla futures-v8."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from market_lab.futures_v8.config import load_v8_research_config
from market_lab.futures_v8.execution import (
    FUTURES_V8_EXECUTION_VERSION,
    PRIMARY_ORDER_PRICE_POLICY,
    RESEARCH_ONLY_NOT_QUEUE_EXACT,
    CausalPovExecutionPolicy,
    ExecutionStatus,
    PredeclaredLimitOrder,
    PredeclaredMarketOrder,
    PredeclaredPairedMarketRollOrder,
    TenMinuteCandle,
    assert_causal_v8_policy_matches_protocol,
    plan_causal_v8_execution,
    plan_diagnostic_limit_v8_execution,
)

MOSCOW = ZoneInfo("Europe/Moscow")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
V8_CONFIG_PATH = PROJECT_ROOT / "configs" / "futures_v8_development_protocol.yaml"


def _decision() -> datetime:
    """Vozvrashchaet fiksirovannyi D18:50 Moscow moment bez holdout dannyh."""
    return datetime(2025, 9, 1, 18, 50, tzinfo=MOSCOW)


def _candle(
    contract_id: str,
    opened_at: datetime,
    *,
    open_price: float | None = 100.0,
    high_price: float | None = None,
    low_price: float | None = None,
    close_price: float | None = None,
    volume: int | None,
) -> TenMinuteCandle:
    """Sobiraet factual 10m OHLCV candle bez synthetic zapolneniya."""
    if open_price is not None:
        high_price = open_price if high_price is None else high_price
        low_price = open_price if low_price is None else low_price
        close_price = open_price if close_price is None else close_price
    return TenMinuteCandle(
        contract_id=contract_id,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=10),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )


def _bars(
    contract_id: str,
    decision: datetime,
    *,
    observed_volume: int | None = 1_000,
    execution_volume: int | None = 1_000,
    execution_open: float = 100.0,
    execution_high: float | None = None,
    execution_low: float | None = None,
    execution_close: float | None = None,
) -> list[TenMinuteCandle]:
    """Stroit tol'ko nuzhnye 19:00 capacity i default 19:20 execution bar'y."""
    return [
        _candle(
            contract_id,
            decision + timedelta(minutes=10),
            volume=observed_volume,
        ),
        _candle(
            contract_id,
            decision + timedelta(minutes=30),
            open_price=execution_open,
            high_price=execution_high,
            low_price=execution_low,
            close_price=execution_close,
            volume=execution_volume,
        ),
    ]


def test_completed_execution_window_has_explicit_nonzero_latency() -> None:
    """Dokazyvaet 19:00--19:10 observe, propusk 19:10 i live tol'ko v 19:20."""
    decision = _decision()
    order = PredeclaredMarketOrder("buy-si", "SiU5", decision, 10)
    required = _bars("SiU5", decision, execution_open=100.0)
    candles = [
        required[0],
        _candle(
            "SiU5",
            decision + timedelta(minutes=20),
            open_price=1.0,
            high_price=1.0,
            low_price=1.0,
            close_price=1.0,
            volume=999_999,
        ),
        required[1],
    ]

    result = plan_causal_v8_execution([order], candles)[0]

    assert result.status is ExecutionStatus.FILLED
    assert result.leg.capacity_candle_open_at == result.decision_at + timedelta(minutes=10)
    assert result.leg.capacity_candle_close_at == result.decision_at + timedelta(minutes=20)
    assert result.leg.order_live_at == result.decision_at + timedelta(minutes=30)
    assert result.leg.execution_window_open_at == result.leg.order_live_at
    assert result.leg.execution_window_close_at == result.decision_at + timedelta(minutes=40)
    assert result.leg.observed_capacity_volume == 1_000
    assert result.leg.observed_capacity_contracts == 10
    assert result.leg.realized_execution_volume == 1_000
    assert result.leg.realized_execution_capacity_contracts == 10
    assert result.leg.execution_volume_is_post_window_outcome is True
    assert result.leg.execution_price == 100.0


def test_policy_rejects_zero_latency() -> None:
    """Zapreshchaet modelirovat' fill v moment zakrytiya capacity candle."""
    with pytest.raises(ValueError, match="rovno odin polnyi 10m bar"):
        CausalPovExecutionPolicy(order_latency=timedelta(0))

    with pytest.raises(ValueError, match="rovno odin polnyi 10m bar"):
        CausalPovExecutionPolicy(order_latency=timedelta(minutes=20))


def test_p0_large_observed_volume_and_one_contract_execution_volume_is_zero_cap() -> None:
    """Vosproizvodit P0: prior 1m volume ne mozhet perebit' factual execution 1."""
    decision = _decision()
    order = PredeclaredMarketOrder("p0-si", "SiU5", decision, 5)
    result = plan_causal_v8_execution(
        [order],
        _bars("SiU5", decision, observed_volume=1_000_000, execution_volume=1),
    )[0]

    assert result.status is ExecutionStatus.CARRIED
    assert result.executed_contracts == 0
    assert result.carry_contracts == 5
    assert result.leg.observed_capacity_contracts == 10_000
    assert result.leg.realized_execution_capacity_contracts == 0
    assert result.leg.reason == "zero_realized_execution_capacity"
    assert result.leg.execution_price is None


def test_buy_uses_execution_high_and_sell_uses_execution_low() -> None:
    """Proveryaet adverse factual price, a ne exact execution-bar open."""
    decision = _decision()
    buy = PredeclaredMarketOrder("buy-br", "BRV5", decision, 2)
    sell = PredeclaredMarketOrder("sell-ri", "RIU5", decision, -2)
    results = plan_causal_v8_execution(
        [buy, sell],
        [
            *_bars(
                "BRV5",
                decision,
                execution_open=100.0,
                execution_high=105.0,
                execution_low=95.0,
                execution_close=101.0,
            ),
            *_bars(
                "RIU5",
                decision,
                execution_open=100.0,
                execution_high=105.0,
                execution_low=95.0,
                execution_close=99.0,
            ),
        ],
    )
    buy_result, sell_result = results

    assert buy_result.leg.execution_price == 105.0
    assert sell_result.leg.execution_price == 95.0
    assert buy_result.leg.factual_execution_open == 100.0
    assert sell_result.leg.factual_execution_open == 100.0
    assert buy_result.provenance == RESEARCH_ONLY_NOT_QUEUE_EXACT
    assert sell_result.provenance == RESEARCH_ONLY_NOT_QUEUE_EXACT


def test_limit_uses_worst_price_across_completed_execution_window() -> None:
    """Ne razreshaet buy/sell limit po blagopriyatnom open ili close."""
    decision = _decision()
    buy = PredeclaredLimitOrder("buy-limit", "BRV5", decision, 2, 102.0)
    sell = PredeclaredLimitOrder("sell-limit", "RIU5", decision, -2, 98.0)
    buy_result, sell_result = plan_diagnostic_limit_v8_execution(
        [buy, sell],
        [
            *_bars(
                "BRV5",
                decision,
                execution_open=100.0,
                execution_high=105.0,
                execution_low=95.0,
                execution_close=101.0,
            ),
            *_bars(
                "RIU5",
                decision,
                execution_open=100.0,
                execution_high=105.0,
                execution_low=95.0,
                execution_close=99.0,
            ),
        ],
    )

    assert buy_result.status is ExecutionStatus.SKIPPED_LIMIT
    assert sell_result.status is ExecutionStatus.SKIPPED_LIMIT
    assert buy_result.leg.execution_price is None
    assert sell_result.leg.execution_price is None


def test_primary_surface_rejects_diagnostic_limit_order() -> None:
    """Ne daet limit-price degree of freedom popast' v primary protocol."""
    decision = _decision()
    diagnostic = PredeclaredLimitOrder("limit", "BRV5", decision, 1, 999.0)

    with pytest.raises(TypeError, match="tol'ko primary market"):
        plan_causal_v8_execution([diagnostic], _bars("BRV5", decision))  # type: ignore[list-item]


def test_runtime_policy_exactly_matches_byte_sealed_execution_protocol() -> None:
    """Svyazyvaet executor s final'nym sealed YAML bez svobodnogo price policy."""
    config = load_v8_research_config(V8_CONFIG_PATH)

    assert_causal_v8_policy_matches_protocol(config.execution)

    assert config.execution.execution_version == FUTURES_V8_EXECUTION_VERSION
    assert config.execution.primary_order_price_policy == PRIMARY_ORDER_PRICE_POLICY
    assert not hasattr(PredeclaredMarketOrder("market", "BRV5", _decision(), 1), "limit_price")


def test_aggregate_same_contract_fills_never_exceed_actual_execution_bar_cap() -> None:
    """Proveryaet deterministic gross allocation pod 1-percent realized bar cap."""
    decision = _decision()
    later = PredeclaredMarketOrder("z-later", "SiU5", decision, 3)
    earlier = PredeclaredMarketOrder("a-earlier", "SiU5", decision, 3)
    results = plan_causal_v8_execution(
        [later, earlier],
        _bars("SiU5", decision, observed_volume=1_000, execution_volume=300),
    )
    by_id = {result.order_id: result for result in results}
    aggregate = sum(abs(result.executed_contracts) for result in results)

    assert by_id["a-earlier"].executed_contracts == 3
    assert by_id["z-later"].executed_contracts == 0
    assert by_id["z-later"].reason == "aggregate_capacity_exhausted"
    assert aggregate == 3
    assert aggregate <= by_id["a-earlier"].leg.realized_execution_capacity_contracts
    assert aggregate <= by_id["z-later"].leg.observed_capacity_contracts


def test_missing_execution_ohlcv_carries_without_price_substitution() -> None:
    """Ne zapolnyaet missing OHLCV i ne perenosit fill na sleduyushchii bar."""
    decision = _decision()
    order = PredeclaredMarketOrder("buy-mix", "MXU5", decision, 2)
    candles = [
        _candle("MXU5", decision + timedelta(minutes=10), volume=1_000),
        _candle(
            "MXU5",
            decision + timedelta(minutes=30),
            open_price=None,
            high_price=None,
            low_price=2_999.0,
            close_price=3_000.0,
            volume=1_000,
        ),
        _candle("MXU5", decision + timedelta(minutes=40), open_price=3_001.0, volume=1_000),
    ]
    result = plan_causal_v8_execution([order], candles)[0]

    assert result.status is ExecutionStatus.CARRIED
    assert result.reason == "unavailable_execution_ohlc"
    assert result.leg.execution_price is None


def test_paired_roll_is_research_only_and_carries_old_exposure_when_leg_fails() -> None:
    """Ne zayavlyaet broker atomicity i ne fillit odnu nogu pri fail drugei."""
    decision = _decision()
    roll = PredeclaredPairedMarketRollOrder("roll-si", "SiU5", "SiZ5", decision, 2)
    result = plan_causal_v8_execution(
        [roll],
        [
            *_bars("SiU5", decision, execution_open=100.0),
            *_bars("SiZ5", decision, execution_open=103.0, execution_volume=None),
        ],
    )[0]

    assert result.status is ExecutionStatus.CARRIED
    assert result.paired_research_fill is False
    assert result.old_exposure_carried is True
    assert result.broker_atomicity_not_proven is True
    assert result.old_leg.executed_contracts == 0
    assert result.new_leg.executed_contracts == 0
    assert result.old_leg.execution_price is None
    assert result.new_leg.execution_price is None


def test_paired_roll_fills_equal_legs_only_when_both_conservative_checks_pass() -> None:
    """Proveryaet paired research fill s adverse cenami i residual carry staroi nogi."""
    decision = _decision()
    roll = PredeclaredPairedMarketRollOrder("roll-ri", "RIU5", "RIZ5", decision, 4)
    result = plan_causal_v8_execution(
        [roll],
        [
            *_bars(
                "RIU5",
                decision,
                observed_volume=500,
                execution_volume=300,
                execution_open=100.0,
                execution_high=102.0,
                execution_low=99.0,
                execution_close=101.0,
            ),
            *_bars(
                "RIZ5",
                decision,
                observed_volume=500,
                execution_volume=500,
                execution_open=100.0,
                execution_high=102.0,
                execution_low=98.0,
                execution_close=100.0,
            ),
        ],
    )[0]

    assert result.status is ExecutionStatus.PARTIAL_CARRY
    assert result.paired_research_fill is True
    assert result.broker_atomicity_not_proven is True
    assert result.executed_contracts == 3
    assert result.carry_contracts == 1
    assert result.old_leg.executed_contracts == -3
    assert result.new_leg.executed_contracts == 3
    assert result.old_leg.execution_price == 99.0
    assert result.new_leg.execution_price == 102.0


def test_signed_short_paired_roll_preserves_direction_through_partial_carry() -> None:
    """Rollit short q atomarno: old buy, new sell, signed residual bez inversii."""
    decision = _decision()
    roll = PredeclaredPairedMarketRollOrder("roll-short-ri", "RIU5", "RIZ5", decision, -4)
    result = plan_causal_v8_execution(
        [roll],
        [
            *_bars(
                "RIU5",
                decision,
                observed_volume=500,
                execution_volume=300,
                execution_open=100.0,
                execution_high=102.0,
                execution_low=99.0,
            ),
            *_bars(
                "RIZ5",
                decision,
                observed_volume=500,
                execution_volume=500,
                execution_open=100.0,
                execution_high=102.0,
                execution_low=98.0,
            ),
        ],
    )[0]

    assert roll.signed_contracts == -4
    assert result.status is ExecutionStatus.PARTIAL_CARRY
    assert result.requested_contracts == -4
    assert result.executed_contracts == -3
    assert result.carry_contracts == -1
    assert result.old_leg.requested_contracts == 4
    assert result.new_leg.requested_contracts == -4
    assert result.old_leg.executed_contracts == 3
    assert result.new_leg.executed_contracts == -3
    assert result.old_leg.execution_price == 102.0
    assert result.new_leg.execution_price == 98.0
    assert result.old_exposure_carried is True
    assert result.broker_atomicity_not_proven is True


def test_signed_short_roll_missing_leg_carries_both_without_synthetic_fill() -> None:
    """Pri missing new short leg ne pokupaet old leg i sokhranyaet signed carry."""
    decision = _decision()
    roll = PredeclaredPairedMarketRollOrder("roll-short-missing", "SiU5", "SiZ5", decision, -2)
    result = plan_causal_v8_execution(
        [roll],
        [
            *_bars("SiU5", decision, execution_open=100.0),
            *_bars("SiZ5", decision, execution_open=103.0, execution_volume=None),
        ],
    )[0]

    assert result.status is ExecutionStatus.CARRIED
    assert result.requested_contracts == -2
    assert result.executed_contracts == 0
    assert result.carry_contracts == -2
    assert result.old_leg.executed_contracts == 0
    assert result.new_leg.executed_contracts == 0
    assert result.old_leg.execution_price is None
    assert result.new_leg.execution_price is None
    assert result.paired_research_fill is False
    assert result.broker_atomicity_not_proven is True


def test_signed_paired_roll_rejects_zero_exposure() -> None:
    """Zapreshchaet ambiguous q=0, no prinimaet factual short exposure."""
    decision = _decision()
    assert PredeclaredPairedMarketRollOrder(
        "roll-short", "RIU5", "RIZ5", decision, -1
    ).signed_contracts == -1
    with pytest.raises(ValueError, match="ne mozhet byt' ravnym nulyu"):
        PredeclaredPairedMarketRollOrder("roll-zero", "RIU5", "RIZ5", decision, 0)


def test_future_candle_mutation_cannot_change_completed_execution_prefix() -> None:
    """Dokazyvaet, chto posle zakrytiya execution window candles ne chitayutsya."""
    decision = _decision()
    order = PredeclaredMarketOrder("sell-ri", "RIU5", decision, -4)
    base = [
        *_bars("RIU5", decision, execution_open=98_500.0),
        _candle("RIU5", decision + timedelta(minutes=40), open_price=1.0, volume=0),
    ]
    mutated_future = [
        *base[:2],
        _candle(
            "RIU5",
            decision + timedelta(minutes=40),
            open_price=1_000_000.0,
            volume=999_999,
        ),
    ]

    assert plan_causal_v8_execution([order], base) == plan_causal_v8_execution(
        [order], mutated_future
    )
