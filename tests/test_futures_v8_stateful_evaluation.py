"""Adversarial synthetic checks for the futures-v8 stateful evaluation adapter."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from market_lab.futures_v8.eval_run import (
    V8OrderBinding,
    V8OrderCause,
    V8PositionKey,
    V8ScenarioId,
    plan_v8_scenario_execution,
)
from market_lab.futures_v8.execution import (
    ExecutionStatus,
    PredeclaredMarketOrder,
    TenMinuteCandle,
)
from market_lab.futures_v8.stateful_evaluation import (
    BREAKOUT_STRATEGY_ID,
    CORRIDOR_STRATEGY_ID,
    BreakoutDecisionObservation,
    BreakoutScenarioState,
    CorridorEntryProtocol,
    CorridorStatus,
    ExactScenarioExecutionWindows,
    MissingBarEvidence,
    ScenarioExecutionWindow,
    ScenarioFactualBar,
    StatefulAction,
    StatefulExecutionEvidence,
    StatefulOrderIntent,
    StatefulResolution,
    StatefulSealSet,
    advance_breakout_observation,
    assert_exact_scenario_partition,
    bind_breakout_order,
    mark_corridor_missing_bar,
    propose_breakout_transition,
    reconcile_breakout_execution,
    reconcile_corridor_entry,
    reconcile_corridor_exit,
    reconcile_order_intent,
    transition_corridor_bar,
)

PREDICTION_SHA = "1" * 64
INPUT_SHA = "2" * 64
CALENDAR_SHA = "3" * 64
CONTRACT_SHA = "4" * 64
SLEEVE_SHA = "5" * 64
EVIDENCE_SHA = "6" * 64
MARKET_SHA = "7" * 64


def _decision(day: int = 2) -> datetime:
    return datetime(2025, 6, day, 15, 50, tzinfo=UTC)


def _seals(
    *,
    prediction: str = PREDICTION_SHA,
    input_bundle: str = INPUT_SHA,
) -> StatefulSealSet:
    return StatefulSealSet(
        prediction,
        input_bundle,
        CALENDAR_SHA,
        CONTRACT_SHA,
        SLEEVE_SHA,
    )


def _windows(
    decision: datetime | None = None,
    *,
    primary_bar: int = 100,
    session: int = 10,
) -> ExactScenarioExecutionWindows:
    decided = decision or _decision()
    primary = ScenarioExecutionWindow(
        V8ScenarioId.PRIMARY,
        primary_bar,
        session,
        decided + timedelta(minutes=30),
        decided + timedelta(minutes=40),
    )
    doubled = replace(primary, scenario_id=V8ScenarioId.DOUBLE_COST)
    delayed = ScenarioExecutionWindow(
        V8ScenarioId.DELAY,
        primary_bar + 1,
        session,
        decided + timedelta(minutes=40),
        decided + timedelta(minutes=50),
    )
    return ExactScenarioExecutionWindows((primary, doubled, delayed))


def _intent(
    *,
    strategy: str,
    action: StatefulAction,
    scenario: V8ScenarioId = V8ScenarioId.PRIMARY,
    requested: int = 2,
    decision: datetime | None = None,
    window: ScenarioExecutionWindow | None = None,
    order_id: str = "order-1",
    asset_id: str = "RI",
    contract_id: str = "RIU5",
    sleeve_id: str = "stateful-sleeve",
    seals: StatefulSealSet | None = None,
) -> StatefulOrderIntent:
    decided = decision or _decision()
    slot = window or _windows(decided).for_scenario(scenario)
    return StatefulOrderIntent(
        strategy_id=strategy,
        action=action,
        scenario_id=scenario,
        decision_at=decided,
        effective_session_date=date(2025, 6, 3),
        asset_id=asset_id,
        contract_id=contract_id,
        sleeve_id=sleeve_id,
        order_id=order_id,
        requested_contracts=requested,
        execution_window=slot,
        seals=seals or _seals(),
    )


def _evidence(
    intent: StatefulOrderIntent,
    *,
    executed: int | None = None,
    price: float | None = None,
    capacity: int | None = 20,
    complete: bool = True,
    evidence_sha: str = EVIDENCE_SHA,
    factual_open: float = 100.0,
    factual_high: float = 105.0,
    factual_low: float = 95.0,
    factual_close: float = 100.0,
    factual_volume: int = 2_000,
) -> StatefulExecutionEvidence:
    filled = intent.requested_contracts if executed is None else executed
    carry = intent.requested_contracts - filled
    status = (
        ExecutionStatus.FILLED
        if carry == 0
        else ExecutionStatus.CARRIED
        if filled == 0
        else ExecutionStatus.PARTIAL_CARRY
    )
    if price is None and filled:
        price = factual_high if filled > 0 else factual_low
    return StatefulExecutionEvidence(
        scenario_id=intent.scenario_id,
        order_id=intent.order_id,
        decision_at=intent.decision_at,
        effective_session_date=intent.effective_session_date,
        asset_id=intent.asset_id,
        contract_id=intent.contract_id,
        sleeve_id=intent.sleeve_id,
        bar_sequence_id=intent.execution_window.bar_sequence_id,
        common_session_sequence_id=intent.execution_window.common_session_sequence_id,
        window_opened_at=intent.execution_window.opened_at,
        window_closed_at=intent.execution_window.closed_at,
        requested_contracts=intent.requested_contracts,
        executed_contracts=filled,
        carry_contracts=carry,
        status=status,
        execution_price=price,
        factual_open=factual_open if complete else None,
        factual_high=factual_high if complete else None,
        factual_low=factual_low if complete else None,
        factual_close=factual_close if complete else None,
        factual_volume=factual_volume if complete else None,
        capacity_contracts=capacity,
        observed_at=intent.execution_window.closed_at,
        reason="synthetic_factual_fill" if complete else "missing_factual_window",
        evidence_sha256=evidence_sha,
        seals=intent.seals,
    )


def _time_exit_window(
    scenario: V8ScenarioId,
    *,
    entry_window: ScenarioExecutionWindow,
    bar_sequence_id: int = 110,
) -> ScenarioExecutionWindow:
    return ScenarioExecutionWindow(
        scenario,
        bar_sequence_id,
        15,
        entry_window.closed_at + timedelta(days=7) - timedelta(minutes=10),
        entry_window.closed_at + timedelta(days=7),
    )


def _open_corridor(
    scenario: V8ScenarioId = V8ScenarioId.PRIMARY,
    *,
    requested: int = 2,
) -> tuple[StatefulOrderIntent, CorridorEntryProtocol, object]:
    entry = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=StatefulAction.CORRIDOR_ENTRY,
        scenario=scenario,
        requested=requested,
        window=_windows().for_scenario(scenario),
        order_id=f"corridor-entry-{scenario.value}",
    )
    protocol = CorridorEntryProtocol(
        intent=entry,
        asset_known_at=entry.decision_at - timedelta(minutes=1),
        atr_20=2.0,
        entry_common_session_sequence_id=10,
        time_exit_window=_time_exit_window(
            scenario,
            entry_window=entry.execution_window,
            bar_sequence_id=111 if scenario is V8ScenarioId.DELAY else 110,
        ),
    )
    transition = reconcile_corridor_entry(protocol, _evidence(entry))
    assert transition.position is not None
    return entry, protocol, transition.position


def _bar(
    position: object,
    *,
    sequence: int | None = None,
    opened_at: datetime | None = None,
    common_session: int | None = None,
    open_price: float = 100.0,
    high_price: float = 101.0,
    low_price: float = 99.0,
    close_price: float = 100.0,
) -> ScenarioFactualBar:
    sequence_id = sequence if sequence is not None else position.last_bar_sequence_id + 1
    opened = opened_at or position.last_bar_closed_at
    return ScenarioFactualBar(
        scenario_id=position.scenario_id,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        bar_sequence_id=sequence_id,
        common_session_sequence_id=(
            position.entry_common_session_sequence_id
            if common_session is None
            else common_session
        ),
        opened_at=opened,
        closed_at=opened + timedelta(minutes=10),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=2_000,
        observed_at=opened + timedelta(minutes=10),
        calendar_sha256=position.seals.calendar_sha256,
        contract_sha256=position.seals.contract_sha256,
        market_evidence_sha256=MARKET_SHA,
    )


def _breakout_observation(
    *,
    day: int,
    direction: int,
    close: float | None,
    valid: bool = True,
    input_sha: str | None = None,
) -> BreakoutDecisionObservation:
    decided = _decision(day)
    return BreakoutDecisionObservation(
        decision_at=decided,
        known_at=decided - timedelta(minutes=1),
        asset_id="RI",
        contract_id="RIU5",
        sleeve_id="stateful-sleeve",
        close_price=close,
        atr_20=2.0 if valid else None,
        breakout_direction=direction,
        input_valid=valid,
        seals=_seals(
            prediction=str(day) * 64,
            input_bundle=input_sha or chr(96 + day) * 64,
        ),
        invalid_reason_codes=() if valid else ("decision_market_invalid",),
    )


def _breakout_intent(
    proposal: object,
    *,
    requested: int,
    order_id: str,
) -> StatefulOrderIntent:
    observation = proposal.observation
    return _intent(
        strategy=BREAKOUT_STRATEGY_ID,
        action=proposal.action,
        scenario=V8ScenarioId.PRIMARY,
        requested=requested,
        decision=observation.decision_at,
        window=_windows(observation.decision_at).for_scenario(V8ScenarioId.PRIMARY),
        order_id=order_id,
        seals=observation.seals,
    )


def _entered_breakout_state() -> BreakoutScenarioState:
    state = BreakoutScenarioState.create(V8ScenarioId.PRIMARY, CALENDAR_SHA)
    proposal = propose_breakout_transition(
        state,
        _breakout_observation(day=2, direction=1, close=100.0),
    )
    assert proposal.action is StatefulAction.BREAKOUT_ENTER
    intent = _breakout_intent(proposal, requested=1, order_id="breakout-enter")
    pending = bind_breakout_order(proposal, intent)
    return reconcile_breakout_execution(state, pending, _evidence(intent)).state


def test_exact_scenario_windows_and_v8_converter_preserve_actual_delay_timestamp() -> None:
    decision = _decision()
    windows = _windows(decision)
    assert windows.for_scenario(V8ScenarioId.PRIMARY).closed_at == decision + timedelta(minutes=40)
    assert windows.for_scenario(V8ScenarioId.DELAY).closed_at == decision + timedelta(minutes=50)

    request = PredeclaredMarketOrder("scenario-order", "RIU5", decision, 2)
    binding = V8OrderBinding(
        request=request,
        cause=V8OrderCause.ENTRY,
        effective_session_date=date(2025, 6, 3),
        single_position=V8PositionKey(
            CORRIDOR_STRATEGY_ID,
            "stateful-sleeve",
            "RI",
            "RIU5",
        ),
    )
    candles = (
        TenMinuteCandle(
            "RIU5",
            decision + timedelta(minutes=10),
            decision + timedelta(minutes=20),
            100.0,
            101.0,
            99.0,
            100.0,
            2_000,
        ),
        TenMinuteCandle(
            "RIU5",
            decision + timedelta(minutes=30),
            decision + timedelta(minutes=40),
            100.0,
            105.0,
            95.0,
            100.0,
            2_000,
        ),
        TenMinuteCandle(
            "RIU5",
            decision + timedelta(minutes=40),
            decision + timedelta(minutes=50),
            101.0,
            106.0,
            96.0,
            101.0,
            2_000,
        ),
    )
    primary_raw = plan_v8_scenario_execution(
        (binding,), candles, V8ScenarioId.PRIMARY
    )[0]
    delay_raw = plan_v8_scenario_execution((binding,), candles, V8ScenarioId.DELAY)[0]
    primary_fact = StatefulExecutionEvidence.from_v8_scenario(
        primary_raw,
        asset_id="RI",
        sleeve_id="stateful-sleeve",
        bar_sequence_id=100,
        common_session_sequence_id=10,
        seals=_seals(),
    )
    delay_fact = StatefulExecutionEvidence.from_v8_scenario(
        delay_raw,
        asset_id="RI",
        sleeve_id="stateful-sleeve",
        bar_sequence_id=101,
        common_session_sequence_id=10,
        seals=_seals(),
    )
    primary_intent = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=StatefulAction.CORRIDOR_ENTRY,
        scenario=V8ScenarioId.PRIMARY,
        order_id="scenario-order",
        window=windows.for_scenario(V8ScenarioId.PRIMARY),
    )
    delay_intent = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=StatefulAction.CORRIDOR_ENTRY,
        scenario=V8ScenarioId.DELAY,
        order_id="scenario-order",
        window=windows.for_scenario(V8ScenarioId.DELAY),
    )
    assert reconcile_order_intent(primary_intent, primary_fact).executed_at == (
        decision + timedelta(minutes=40)
    )
    assert reconcile_order_intent(delay_intent, delay_fact).executed_at == (
        decision + timedelta(minutes=50)
    )
    with pytest.raises(ValueError, match="mismatch"):
        reconcile_order_intent(primary_intent, delay_fact)


def test_corridor_state_isolated_by_scenario_and_anchored_to_each_fill() -> None:
    _, _, primary = _open_corridor(V8ScenarioId.PRIMARY)
    _, _, doubled = _open_corridor(V8ScenarioId.DOUBLE_COST)
    _, _, delayed = _open_corridor(V8ScenarioId.DELAY)

    assert primary.opened_at == _decision() + timedelta(minutes=40)
    assert doubled.opened_at == _decision() + timedelta(minutes=40)
    assert delayed.opened_at == _decision() + timedelta(minutes=50)
    assert len({primary.position_id, doubled.position_id, delayed.position_id}) == 3
    assert delayed.last_bar_sequence_id == primary.last_bar_sequence_id + 1
    with pytest.raises(ValueError, match="identity or seal"):
        transition_corridor_bar(primary, replace(_bar(primary), scenario_id=V8ScenarioId.DELAY))


@pytest.mark.parametrize(
    ("executed", "capacity", "complete", "reason"),
    (
        (1, 20, True, "partial_or_zero_execution_carry"),
        (0, 20, True, "partial_or_zero_execution_carry"),
        (2, None, True, "unknown_factual_capacity"),
        (2, 20, False, "incomplete_factual_window"),
    ),
)
def test_corridor_entry_partial_missing_or_unknown_capacity_never_advances(
    executed: int,
    capacity: int | None,
    complete: bool,
    reason: str,
) -> None:
    intent = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=StatefulAction.CORRIDOR_ENTRY,
        order_id="adversarial-entry",
    )
    protocol = CorridorEntryProtocol(
        intent,
        intent.decision_at - timedelta(minutes=1),
        2.0,
        10,
        _time_exit_window(V8ScenarioId.PRIMARY, entry_window=intent.execution_window),
    )
    transition = reconcile_corridor_entry(
        protocol,
        _evidence(intent, executed=executed, capacity=capacity, complete=complete),
    )
    assert transition.position is None
    assert transition.unresolved is not None
    assert transition.event.resolution is StatefulResolution.UNRESOLVED
    assert transition.unresolved.reason == reason


def test_corridor_stop_first_on_ambiguous_bar_and_full_exit_event() -> None:
    _, _, position = _open_corridor()
    bar = _bar(
        position,
        open_price=100.0,
        high_price=107.0,
        low_price=99.0,
        close_price=100.0,
    )
    transition = transition_corridor_bar(position, bar)
    assert transition.trigger is not None
    assert transition.trigger.action is StatefulAction.CORRIDOR_EXIT_STOP
    assert transition.trigger.reason == "stop_loss_ambiguous_bar_adverse_first"
    assert transition.trigger.adverse_reference_price == pytest.approx(99.4)

    trigger = transition.trigger
    intent = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=trigger.action,
        requested=trigger.requested_contracts,
        window=trigger.trigger_window,
        order_id="corridor-stop-exit",
    )
    evidence = _evidence(
        intent,
        price=99.0,
        factual_open=100.0,
        factual_high=107.0,
        factual_low=99.0,
        factual_close=100.0,
    )
    outcome = reconcile_corridor_exit(transition.position, trigger, intent, evidence)
    assert outcome.unresolved is None
    assert outcome.position.status is CorridorStatus.CLOSED
    assert outcome.position.open_contracts == 0
    assert outcome.event.position_key == (
        CORRIDOR_STRATEGY_ID,
        "stateful-sleeve",
        "RI",
        "RIU5",
    )


def test_corridor_delay_exit_requires_next_actual_bar_not_trigger_timestamp() -> None:
    _, _, position = _open_corridor(V8ScenarioId.DELAY)
    transition = transition_corridor_bar(
        position,
        _bar(
            position,
            open_price=100.0,
            high_price=103.0,
            low_price=94.0,
            close_price=100.0,
        ),
    )
    trigger = transition.trigger
    assert trigger is not None
    false_primary_intent = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=trigger.action,
        scenario=V8ScenarioId.DELAY,
        requested=trigger.requested_contracts,
        window=trigger.trigger_window,
        order_id="delay-exit",
    )
    with pytest.raises(ValueError, match="next complete"):
        reconcile_corridor_exit(
            transition.position,
            trigger,
            false_primary_intent,
            _evidence(false_primary_intent, price=94.0, factual_low=94.0),
        )

    delayed_window = ScenarioExecutionWindow(
        V8ScenarioId.DELAY,
        trigger.trigger_window.bar_sequence_id + 1,
        trigger.trigger_window.common_session_sequence_id,
        trigger.trigger_window.closed_at,
        trigger.trigger_window.closed_at + timedelta(minutes=10),
    )
    delayed_intent = replace(false_primary_intent, execution_window=delayed_window)
    outcome = reconcile_corridor_exit(
        transition.position,
        trigger,
        delayed_intent,
        _evidence(
            delayed_intent,
            price=94.0,
            factual_open=99.0,
            factual_high=100.0,
            factual_low=94.0,
            factual_close=96.0,
        ),
    )
    assert outcome.position.closed_at == delayed_window.closed_at
    assert outcome.event.executed_at > trigger.trigger_window.closed_at


def test_corridor_partial_exit_and_missing_bar_become_terminal_unresolved() -> None:
    _, _, position = _open_corridor()
    trigger_transition = transition_corridor_bar(
        position,
        _bar(position, high_price=103.0, low_price=94.0),
    )
    trigger = trigger_transition.trigger
    assert trigger is not None
    intent = _intent(
        strategy=CORRIDOR_STRATEGY_ID,
        action=trigger.action,
        requested=trigger.requested_contracts,
        window=trigger.trigger_window,
        order_id="partial-exit",
    )
    partial = reconcile_corridor_exit(
        trigger_transition.position,
        trigger,
        intent,
        _evidence(
            intent,
            executed=-1,
            price=94.0,
            factual_high=103.0,
            factual_low=94.0,
        ),
    )
    assert partial.position.status is CorridorStatus.UNRESOLVED
    assert partial.position.open_contracts == 2
    assert partial.unresolved is not None
    assert partial.unresolved.executed_contracts == -1

    _, _, fresh = _open_corridor()
    gap = transition_corridor_bar(fresh, _bar(fresh, sequence=fresh.last_bar_sequence_id + 2))
    assert gap.position.status is CorridorStatus.UNRESOLVED
    assert gap.unresolved is not None
    assert gap.unresolved.reason == "missing_expected_factual_bar"


def test_exact_fifth_session_time_exit_and_explicit_missing_slot() -> None:
    _, _, position = _open_corridor()
    slot = position.time_exit_window
    before_time = replace(
        position,
        last_bar_sequence_id=slot.bar_sequence_id - 1,
        last_bar_closed_at=slot.opened_at,
    )
    time_bar = _bar(
        before_time,
        sequence=slot.bar_sequence_id,
        opened_at=slot.opened_at,
        common_session=slot.common_session_sequence_id,
        open_price=105.0,
        high_price=106.0,
        low_price=104.0,
        close_price=105.0,
    )
    transition = transition_corridor_bar(before_time, time_bar)
    assert transition.trigger is not None
    assert transition.trigger.action is StatefulAction.CORRIDOR_EXIT_TIME

    missing = MissingBarEvidence(
        scenario_id=position.scenario_id,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        expected_window=ScenarioExecutionWindow(
            position.scenario_id,
            position.last_bar_sequence_id + 1,
            position.entry_common_session_sequence_id,
            position.last_bar_closed_at,
            position.last_bar_closed_at + timedelta(minutes=10),
        ),
        observed_through=position.last_bar_closed_at + timedelta(minutes=20),
        calendar_sha256=position.seals.calendar_sha256,
        contract_sha256=position.seals.contract_sha256,
        evidence_sha256=MARKET_SHA,
    )
    missing_transition = mark_corridor_missing_bar(position, missing)
    assert missing_transition.position.status is CorridorStatus.UNRESOLVED
    assert missing_transition.trigger is None


def test_breakout_full_enter_add_and_monotone_hold_then_trailing_exit() -> None:
    state = _entered_breakout_state()
    assert state.assets[0].pyramid_level == 1
    assert state.assets[0].extreme_close == 100.0

    add_proposal = propose_breakout_transition(
        state,
        _breakout_observation(day=3, direction=1, close=110.0),
    )
    assert add_proposal.action is StatefulAction.BREAKOUT_ADD
    add_intent = _breakout_intent(add_proposal, requested=1, order_id="breakout-add")
    state = reconcile_breakout_execution(
        state,
        bind_breakout_order(add_proposal, add_intent),
        _evidence(add_intent),
    ).state
    assert state.assets[0].pyramid_level == 2
    assert state.assets[0].open_contracts == 2
    assert state.assets[0].extreme_close == 110.0

    hold = propose_breakout_transition(
        state,
        _breakout_observation(day=4, direction=0, close=108.0),
    )
    assert hold.action is None
    state = advance_breakout_observation(state, hold)
    assert state.assets[0].extreme_close == 110.0

    trail = propose_breakout_transition(
        state,
        _breakout_observation(day=5, direction=0, close=105.0),
    )
    assert trail.action is StatefulAction.BREAKOUT_EXIT_TRAIL
    exit_intent = _breakout_intent(trail, requested=-2, order_id="breakout-trail")
    outcome = reconcile_breakout_execution(
        state,
        bind_breakout_order(trail, exit_intent),
        _evidence(exit_intent),
    )
    assert not outcome.state.assets
    assert outcome.unresolved is None


def test_breakout_reversal_exit_requires_full_flatten_evidence() -> None:
    state = _entered_breakout_state()
    reversal = propose_breakout_transition(
        state,
        _breakout_observation(day=3, direction=-1, close=101.0),
    )
    assert reversal.action is StatefulAction.BREAKOUT_EXIT_REVERSAL
    intent = _breakout_intent(reversal, requested=-1, order_id="breakout-reversal")
    outcome = reconcile_breakout_execution(
        state,
        bind_breakout_order(reversal, intent),
        _evidence(intent),
    )
    assert not outcome.state.assets


@pytest.mark.parametrize(
    ("executed", "capacity", "complete"),
    ((0, 20, True), (1, None, True), (1, 20, False)),
)
def test_breakout_partial_or_unproven_add_preserves_filled_level_and_blocks(
    executed: int,
    capacity: int | None,
    complete: bool,
) -> None:
    state = _entered_breakout_state()
    prior = state.assets[0]
    proposal = propose_breakout_transition(
        state,
        _breakout_observation(day=3, direction=1, close=110.0),
    )
    intent = _breakout_intent(proposal, requested=2, order_id="blocked-add")
    outcome = reconcile_breakout_execution(
        state,
        bind_breakout_order(proposal, intent),
        _evidence(intent, executed=executed, capacity=capacity, complete=complete),
    )
    assert outcome.state.assets[0].pyramid_level == prior.pyramid_level
    assert outcome.state.assets[0].open_contracts == prior.open_contracts
    assert outcome.state.assets[0].extreme_close == prior.extreme_close
    assert outcome.unresolved is not None


def test_invalid_breakout_prior_position_is_locked_carry_without_order_or_rebalance() -> None:
    state = _entered_breakout_state()
    prior = state.assets[0]
    invalid = _breakout_observation(day=3, direction=0, close=None, valid=False)
    proposal = propose_breakout_transition(state, invalid)

    assert proposal.action is None
    assert proposal.next_extreme_close == prior.extreme_close
    locked_state = advance_breakout_observation(state, proposal)
    assert locked_state.assets == state.assets
    assert len(locked_state.locked_positions) == 1
    lock = locked_state.locked_positions[0]
    assert lock.state == prior
    assert lock.reason_codes == ("decision_market_invalid",)
    with pytest.raises(ValueError, match="has no order"):
        bind_breakout_order(
            proposal,
            _intent(
                strategy=BREAKOUT_STRATEGY_ID,
                action=StatefulAction.BREAKOUT_ADD,
                decision=invalid.decision_at,
                window=_windows(invalid.decision_at).for_scenario(V8ScenarioId.PRIMARY),
                seals=invalid.seals,
            ),
        )


def test_breakout_scenarios_are_distinct_and_contract_sleeve_seals_fail_closed() -> None:
    states = tuple(
        BreakoutScenarioState.create(scenario, CALENDAR_SHA)
        for scenario in (
            V8ScenarioId.PRIMARY,
            V8ScenarioId.DOUBLE_COST,
            V8ScenarioId.DELAY,
        )
    )
    assert_exact_scenario_partition(states)
    with pytest.raises(ValueError, match="exact"):
        assert_exact_scenario_partition((states[0], states[2], states[1]))

    state = _entered_breakout_state()
    drifted = replace(
        _breakout_observation(day=3, direction=1, close=110.0),
        seals=replace(_seals(prediction="3" * 64, input_bundle="c" * 64), sleeve_sha256="8" * 64),
    )
    with pytest.raises(ValueError, match="identity drift"):
        propose_breakout_transition(state, drifted)


def test_future_execution_changes_cannot_change_breakout_decision_proposal() -> None:
    state = _entered_breakout_state()
    observation = _breakout_observation(day=3, direction=1, close=110.0)
    proposal = propose_breakout_transition(state, observation)
    intent = _breakout_intent(proposal, requested=1, order_id="future-independent")
    low_future = _evidence(
        intent,
        price=105.0,
        factual_open=100.0,
        factual_high=105.0,
        factual_low=90.0,
        factual_close=91.0,
    )
    high_future = _evidence(
        intent,
        price=150.0,
        factual_open=100.0,
        factual_high=150.0,
        factual_low=99.0,
        factual_close=149.0,
        evidence_sha="9" * 64,
    )
    assert proposal == propose_breakout_transition(state, observation)
    assert low_future.execution_price != high_future.execution_price
    assert proposal.action is StatefulAction.BREAKOUT_ADD


def test_adapter_public_records_contain_no_economic_output_fields_and_reject_2026() -> None:
    records = (
        StatefulOrderIntent,
        StatefulExecutionEvidence,
        BreakoutDecisionObservation,
    )
    forbidden = ("pnl", "return", "label", "realized_profit")
    for record in records:
        names = {item.name.lower() for item in fields(record)}
        assert not any(token in name for name in names for token in forbidden)

    with pytest.raises(ValueError, match="2026"):
        ScenarioExecutionWindow(
            V8ScenarioId.PRIMARY,
            1,
            1,
            datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 10, 10, tzinfo=UTC),
        )
