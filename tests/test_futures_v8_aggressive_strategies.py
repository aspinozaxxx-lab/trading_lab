"""Testy predeclared aggressive futures-v8 candidates bez PnL."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from market_lab.futures_v8.aggressive_strategies import (
    AGGRESSIVE_CANDIDATE_IDS,
    BASE_PROTOCOL_SHA256,
    CANDIDATE_SPECS,
    AggressiveCandidateId,
    BreakoutAction,
    BreakoutAssetState,
    BreakoutPyramidState,
    CandidateAnnualMetric,
    CandidateExecutionEvidence,
    CandidateExitExecutionEvidence,
    CandidateGateMetric,
    CausalAssetSnapshot,
    CausalDecisionContext,
    CorridorPositionStatus,
    FactualTenMinuteBar,
    HoldingSleeveSchedule,
    PointInTimeObservation,
    ScheduledCandidateExecution,
    apply_breakout_execution,
    apply_volatility_corridor_exit,
    mark_volatility_corridor_missing_exit_window,
    open_volatility_corridor_position,
    rank_gate_passing_candidates,
    run_aggressive_candidate,
    transition_volatility_corridor,
)

# Absolyutnyi koren' testiruemogo proekta.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Put' byte-sealed kataloga aggressive candidates.
CATALOG_PATH = PROJECT_ROOT / "configs" / "futures_v8_aggressive_candidates.yaml"
# Fiksirovannyi fake prediction hash dlya causal unit testov.
PREDICTION_SHA = "a" * 64
# Fiksirovannyi fake market-data hash dlya full input bundle testov.
MARKET_SHA = "c" * 64
# Fiksirovannyi fake source hash PIT release.
PIT_SHA = "d" * 64
# Fiksirovannyi fake execution evidence hash.
EXECUTION_SHA = "e" * 64
# Fiksirovannyi fake calendar hash.
CALENDAR_SHA = "f" * 64
# Fiksirovannyi fake evaluation bundle hash.
EVALUATION_SHA = "9" * 64


def _pit(value: float, known_at: datetime, source_id: str) -> PointInTimeObservation:
    """Stroit odin causal PIT release s immutable source provenance."""
    return PointInTimeObservation(
        value=value,
        published_at=known_at,
        source_id=source_id,
        observation_id=f"{source_id}-2025-06-02",
        source_sha256=PIT_SHA,
    )


def _asset(
    asset_id: str,
    *,
    known_at: datetime,
    residual_score: float,
    residual_location: float,
    factor_score: float = 0.3,
    normal_probability: float = 0.25,
    trend_probability: float = 0.60,
    crash_probability: float = 0.15,
    range_position: float = 0.5,
    volatility_ratio: float = 1.2,
    volume_ratio: float = 1.4,
    momentum: float = 0.02,
    carry_z: float | None = 0.8,
    cftc_z: float | None = 0.0,
    rate_z: float | None = 0.0,
    fx_z: float | None = 0.0,
    close: float = 100.0,
    atr: float = 2.0,
) -> CausalAssetSnapshot:
    """Stroit odin validnyi D-known snapshot s upravlyaemymi signalami."""
    return CausalAssetSnapshot(
        asset_id=asset_id,
        known_at=known_at,
        factor_decision_score=factor_score,
        residual_decision_score=residual_score,
        residual_location=residual_location,
        total_scale=0.20,
        abstain_probability=0.10,
        normal_probability=normal_probability,
        trend_probability=trend_probability,
        crash_probability=crash_probability,
        close=close,
        atr_20=atr,
        daily_volatility_20=0.02,
        momentum_20=momentum,
        range_position_20=range_position,
        volatility_ratio_20=volatility_ratio,
        volume_ratio_20=volume_ratio,
        market_data_sha256=MARKET_SHA,
        carry_z=_pit(carry_z, known_at, f"carry-{asset_id}") if carry_z is not None else None,
        cftc_crowd_z=(
            _pit(cftc_z, known_at, f"cftc-{asset_id}") if cftc_z is not None else None
        ),
        key_rate_change_z=(
            _pit(rate_z, known_at, "cbr-rate") if rate_z is not None else None
        ),
        usd_rub_return_z=_pit(fx_z, known_at, "cbr-fx") if fx_z is not None else None,
    )


def _context(decision_at: datetime | None = None) -> CausalDecisionContext:
    """Stroit chetyrehassetnyi causal context, aktiviruyushchii raznye vetki."""
    decision = decision_at or datetime(2025, 6, 2, 15, 50, tzinfo=UTC)
    known = decision - timedelta(minutes=1)
    assets = (
        _asset(
            "BR",
            known_at=known,
            residual_score=0.55,
            residual_location=0.50,
            range_position=1.05,
            volatility_ratio=1.7,
            volume_ratio=1.6,
            cftc_z=-1.7,
            rate_z=1.7,
            fx_z=1.8,
        ),
        _asset(
            "MIX",
            known_at=known,
            residual_score=-0.65,
            residual_location=-0.50,
            range_position=-0.05,
            volatility_ratio=1.7,
            volume_ratio=1.6,
            momentum=-0.02,
            carry_z=-0.9,
            cftc_z=1.8,
            rate_z=1.7,
            fx_z=1.8,
        ),
        _asset(
            "RI",
            known_at=known,
            residual_score=0.25,
            residual_location=0.20,
            range_position=0.10,
            volatility_ratio=1.3,
            normal_probability=0.65,
            trend_probability=0.25,
            crash_probability=0.10,
            rate_z=1.7,
            fx_z=1.8,
        ),
        _asset(
            "SI",
            known_at=known,
            residual_score=-0.30,
            residual_location=-0.20,
            range_position=0.90,
            volatility_ratio=1.3,
            normal_probability=0.65,
            trend_probability=0.25,
            crash_probability=0.10,
            momentum=-0.02,
            carry_z=-0.7,
            rate_z=1.7,
            fx_z=1.8,
        ),
    )
    return CausalDecisionContext(decision, assets, PREDICTION_SHA)


def test_catalog_has_exactly_ten_fixed_diverse_candidates() -> None:
    """Fiksiruet exact ID, poryadok, registry i otsutstvie skrytyh kandidatov."""
    expected = (
        "volatility_corridor_harvest",
        "concentrated_residual_dispersion",
        "breakout_pyramiding_trailing_stop",
        "regime_switch_trend_reversion",
        "crash_expert_convex_defense",
        "carry_momentum_confirmation",
        "cftc_crowded_unwind",
        "macro_shock_rotation",
        "confidence_concentration",
        "volatility_expansion_breakout",
    )
    assert expected == AGGRESSIVE_CANDIDATE_IDS
    assert tuple(spec.candidate_id.value for spec in CANDIDATE_SPECS) == expected
    assert len({spec.family for spec in CANDIDATE_SPECS}) == 10


def test_every_candidate_is_pure_bounded_and_uses_same_prediction_seal() -> None:
    """Proveryaet vse desyat' formul, gross<=1, sleeves i immutable output."""
    context = _context()
    for candidate_id in AggressiveCandidateId:
        run = run_aggressive_candidate(candidate_id, context)
        decision = run.decision
        assert decision.candidate_id is candidate_id
        assert decision.prediction_sha256 == PREDICTION_SHA
        assert decision.gross_exposure <= 1.0 + 1e-12
        assert decision.holding_sleeve_count == 5
        assert decision.holding_sleeve_weight == 0.20
        with pytest.raises(FrozenInstanceError):
            decision.holding_sleeve_count = 4  # type: ignore[misc]


def test_future_observation_is_rejected_and_past_decision_is_repeatable() -> None:
    """Budushchaya mutaciya ne mozhet proniknut' v uzhe postroennyi context."""
    context = _context()
    baseline = run_aggressive_candidate(
        AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION,
        context,
    )
    future_asset = replace(
        context.assets[0],
        known_at=context.decision_at + timedelta(seconds=1),
        residual_decision_score=-0.99,
    )
    with pytest.raises(ValueError, match="future observation"):
        CausalDecisionContext(
            context.decision_at,
            (future_asset, *context.assets[1:]),
            PREDICTION_SHA,
        )
    repeated = run_aggressive_candidate(
        AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION,
        context,
    )
    assert repeated == baseline


def test_context_requires_exact_time_pre_holdout_and_full_universe() -> None:
    """Blokiruet arbitrary decision, protected 2026 i nepolnyi universe."""
    context = _context()
    with pytest.raises(ValueError, match="18:50 Moscow"):
        CausalDecisionContext(
            context.decision_at + timedelta(minutes=1),
            context.assets,
            PREDICTION_SHA,
        )
    holdout_decision = datetime(2026, 1, 2, 15, 50, tzinfo=UTC)
    holdout_assets = tuple(
        replace(
            asset,
            known_at=holdout_decision - timedelta(minutes=1),
        )
        for asset in context.assets
    )
    with pytest.raises(ValueError, match="protected 2026"):
        CausalDecisionContext(holdout_decision, holdout_assets, PREDICTION_SHA)
    with pytest.raises(ValueError, match="exact full"):
        CausalDecisionContext(context.decision_at, context.assets[:-1], PREDICTION_SHA)


def test_future_pit_release_is_rejected_and_full_bundle_hash_changes() -> None:
    """PIT published_at i znachenie yavlyayutsya chast'yu causal input seal."""
    context = _context()
    ri = next(asset for asset in context.assets if asset.asset_id == "RI")
    future_carry = PointInTimeObservation(
        value=0.8,
        published_at=context.decision_at + timedelta(seconds=1),
        source_id="carry-RI",
        observation_id="future-release",
        source_sha256=PIT_SHA,
    )
    changed_assets = tuple(
        replace(asset, carry_z=future_carry) if asset.asset_id == "RI" else asset
        for asset in context.assets
    )
    with pytest.raises(ValueError, match="future publication carry_z"):
        CausalDecisionContext(context.decision_at, changed_assets, PREDICTION_SHA)
    changed_ri = replace(
        ri,
        carry_z=replace(ri.carry_z, value=0.81),
    )
    changed_context = CausalDecisionContext(
        context.decision_at,
        tuple(changed_ri if asset.asset_id == "RI" else asset for asset in context.assets),
        PREDICTION_SHA,
    )
    assert changed_context.input_bundle_sha256 != context.input_bundle_sha256
    decision = run_aggressive_candidate(
        AggressiveCandidateId.CARRY_MOMENTUM_CONFIRMATION,
        context,
    ).decision
    assert decision.input_bundle_sha256 == context.input_bundle_sha256
    assert decision.base_protocol_sha256 == BASE_PROTOCOL_SHA256
    inconsistent_rate = replace(
        ri.key_rate_change_z,
        value=ri.key_rate_change_z.value + 0.1,
    )
    inconsistent_assets = tuple(
        replace(asset, key_rate_change_z=inconsistent_rate)
        if asset.asset_id == "RI"
        else asset
        for asset in context.assets
    )
    with pytest.raises(ValueError, match="odin PIT release"):
        CausalDecisionContext(context.decision_at, inconsistent_assets, PREDICTION_SHA)


def _schedule(context: CausalDecisionContext, sequence_id: int = 100) -> HoldingSleeveSchedule:
    """Stroit exact D+5 common-session schedule s sealed calendar hash."""
    entry_close = context.decision_at + timedelta(minutes=40)
    return HoldingSleeveSchedule(
        sleeve_id=f"sleeve-{sequence_id}",
        calendar_sha256=CALENDAR_SHA,
        entry_common_session_sequence_id=sequence_id,
        exit_common_session_sequence_id=sequence_id + 5,
        entry_window_closed_at=entry_close,
        exit_window_closed_at=entry_close + timedelta(days=7),
    )


def _scheduled_execution(
    context: CausalDecisionContext,
    candidate_id: AggressiveCandidateId,
    asset_id: str,
    signed_contracts: int,
    *,
    executed_contracts: int | None = None,
    sequence_id: int = 100,
    execution_bar_sequence_id: int = 1_000,
) -> ScheduledCandidateExecution:
    """Stroit factual primary fill boundary s upravlyaemym carry."""
    schedule = _schedule(context, sequence_id)
    executed = signed_contracts if executed_contracts is None else executed_contracts
    evidence = CandidateExecutionEvidence(
        candidate_id=candidate_id,
        decision_at=context.decision_at,
        prediction_sha256=context.prediction_sha256,
        input_bundle_sha256=context.input_bundle_sha256,
        sleeve_id=schedule.sleeve_id,
        asset_id=asset_id,
        contract_id=f"{asset_id}M5",
        order_id=f"order-{sequence_id}-{asset_id}",
        common_session_sequence_id=sequence_id,
        execution_bar_sequence_id=execution_bar_sequence_id,
        requested_contracts=signed_contracts,
        executed_contracts=executed,
        carry_contracts=signed_contracts - executed,
        observed_capacity_contracts=10,
        realized_capacity_contracts=10,
        execution_window_closed_at=schedule.entry_window_closed_at,
        execution_price=100.0 if executed else None,
        execution_evidence_sha256=EXECUTION_SHA,
    )
    return ScheduledCandidateExecution(schedule, evidence)


def _corridor_position(
    asset_id: str = "RI",
    signed_contracts: int = 2,
) -> tuple[CausalDecisionContext, object, object]:
    """Stroit execution-bound corridor position dlya state-machine testov."""
    context = _context()
    decision = run_aggressive_candidate(
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        context,
    ).decision
    asset = next(item for item in context.assets if item.asset_id == asset_id)
    execution = _scheduled_execution(
        context,
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        asset_id,
        signed_contracts,
    )
    position = open_volatility_corridor_position(
        asset,
        decision=decision,
        execution=execution,
    )
    return context, position, execution


def _bar(
    position: object,
    *,
    sequence_offset: int = 1,
    common_session_sequence_id: int | None = None,
    opened_at: datetime | None = None,
    prices: tuple[float, float, float, float] = (100.0, 101.0, 99.0, 100.0),
    volume: int = 1_000,
) -> FactualTenMinuteBar:
    """Stroit sleduyushchii factual bar po typed corridor state."""
    start = opened_at or position.last_bar_closed_at
    common_sequence = (
        position.entry_common_session_sequence_id
        if common_session_sequence_id is None
        else common_session_sequence_id
    )
    return FactualTenMinuteBar(
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        bar_sequence_id=position.last_bar_sequence_id + sequence_offset,
        common_session_sequence_id=common_sequence,
        opened_at=start,
        closed_at=start + timedelta(minutes=10),
        open_price=prices[0],
        high_price=prices[1],
        low_price=prices[2],
        close_price=prices[3],
        volume=volume,
    )


def test_corridor_entry_requires_linked_signal_schedule_and_execution() -> None:
    """Zapreshchaet protivopolozhnyi signal i sohranyaet partial entry carry."""
    context = _context()
    decision = run_aggressive_candidate(
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        context,
    ).decision
    asset = next(item for item in context.assets if item.asset_id == "RI")
    wrong = _scheduled_execution(
        context,
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        "RI",
        -2,
    )
    with pytest.raises(ValueError, match="protivorechit"):
        open_volatility_corridor_position(asset, decision=decision, execution=wrong)
    partial = _scheduled_execution(
        context,
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        "RI",
        3,
        executed_contracts=2,
    )
    position = open_volatility_corridor_position(asset, decision=decision, execution=partial)
    assert position.initial_contracts == 2
    assert position.open_contracts == 2
    assert position.entry_carry_contracts == 1
    assert position.contract_id == "RIM5"


def test_schedule_and_execution_capacity_are_fail_closed() -> None:
    """D+5/window i observed/realized capacity nel'zya oboiti boundary objectom."""
    context = _context()
    scheduled = _scheduled_execution(
        context,
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        "RI",
        2,
    )
    with pytest.raises(ValueError, match=r"rovno D\+5"):
        replace(
            scheduled.schedule,
            exit_common_session_sequence_id=(
                scheduled.schedule.entry_common_session_sequence_id + 4
            ),
        )
    with pytest.raises(ValueError, match="19:30 Moscow"):
        replace(
            scheduled.schedule,
            entry_window_closed_at=(
                scheduled.schedule.entry_window_closed_at + timedelta(minutes=1)
            ),
        )
    with pytest.raises(ValueError, match="prevysili factual capacity"):
        replace(
            scheduled.evidence,
            requested_contracts=11,
            executed_contracts=11,
            carry_contracts=0,
        )


@pytest.mark.parametrize(
    ("asset_id", "signed_contracts", "prices", "expected_reference"),
    [
        ("RI", 2, (93.0, 102.0, 92.0, 99.0), 93.0),
        ("SI", -2, (107.0, 108.0, 98.0, 101.0), 107.0),
    ],
)
def test_corridor_ambiguous_bar_creates_adverse_exit_intent_then_factual_close(
    asset_id: str,
    signed_contracts: int,
    prices: tuple[float, float, float, float],
    expected_reference: float,
) -> None:
    """Long/short ambiguous bar ne zakryvaetsya do otdel'nogo capacity outcome."""
    _, position, _ = _corridor_position(asset_id, signed_contracts)
    transition = transition_volatility_corridor(position, _bar(position, prices=prices))
    assert transition.position.status is CorridorPositionStatus.EXIT_PENDING
    assert transition.position.exit_price is None
    assert transition.exit_intent is not None
    intent = transition.exit_intent
    assert intent.trigger_reason == "stop_loss_ambiguous_bar_adverse_first"
    assert intent.conservative_reference_price == pytest.approx(expected_reference)
    outcome = CandidateExitExecutionEvidence(
        intent_id=intent.intent_id,
        order_id=f"exit-{asset_id}",
        asset_id=asset_id,
        contract_id=position.contract_id,
        sleeve_id=position.sleeve_id,
        execution_bar_sequence_id=intent.trigger_bar_sequence_id,
        requested_contracts=intent.requested_contracts,
        executed_contracts=intent.requested_contracts,
        carry_contracts=0,
        execution_price=expected_reference,
        factual_bar_volume=intent.trigger_bar_volume,
        execution_evidence_sha256=EXECUTION_SHA,
    )
    closed = apply_volatility_corridor_exit(transition.position, intent, outcome)
    assert closed.status is CorridorPositionStatus.CLOSED
    assert closed.open_contracts == 0
    assert closed.exit_price == pytest.approx(expected_reference)


def test_corridor_missing_expected_bar_is_unresolved_not_silently_skipped() -> None:
    """Vnutrisessionnyi sequence gap nemedlenno stanovitsya unresolved."""
    _, position, _ = _corridor_position()
    transition = transition_volatility_corridor(
        position,
        _bar(
            position,
            sequence_offset=2,
            opened_at=position.last_bar_closed_at + timedelta(minutes=20),
        ),
    )
    assert transition.position.status is CorridorPositionStatus.CARRY_UNRESOLVED
    assert transition.position.exit_reason == "missing_expected_factual_bar"
    assert transition.exit_intent is None


def test_corridor_partial_exit_capacity_never_becomes_synthetic_close() -> None:
    """Partial 1-percent exit ostavlyaet ostatok unresolved i zapisivaet fill."""
    _, position, _ = _corridor_position()
    transition = transition_volatility_corridor(
        position,
        _bar(position, prices=(100.0, 102.0, 99.0, 101.0), volume=100),
    )
    assert transition.exit_intent is not None
    intent = transition.exit_intent
    outcome = CandidateExitExecutionEvidence(
        intent_id=intent.intent_id,
        order_id="partial-exit-RI",
        asset_id="RI",
        contract_id=position.contract_id,
        sleeve_id=position.sleeve_id,
        execution_bar_sequence_id=intent.trigger_bar_sequence_id,
        requested_contracts=-2,
        executed_contracts=-1,
        carry_contracts=-1,
        execution_price=intent.conservative_reference_price,
        factual_bar_volume=100,
        execution_evidence_sha256=EXECUTION_SHA,
    )
    carried = apply_volatility_corridor_exit(transition.position, intent, outcome)
    assert carried.status is CorridorPositionStatus.CARRY_UNRESOLVED
    assert carried.open_contracts == 1
    assert carried.executed_exit_contracts == 1
    assert carried.exit_price is None


def test_corridor_fifth_session_exit_is_intent_and_missing_window_is_carry() -> None:
    """Time exit trebuet exact sequence/bar, a otsutstvie okna ne sozdaet cenu."""
    _, position, _ = _corridor_position()
    ready_for_exit = replace(
        position,
        last_bar_sequence_id=position.last_bar_sequence_id + 500,
        last_bar_closed_at=position.scheduled_exit_window_closed_at - timedelta(minutes=10),
    )
    exit_bar = _bar(
        ready_for_exit,
        common_session_sequence_id=ready_for_exit.exit_common_session_sequence_id,
        prices=(100.0, 101.0, 99.0, 100.5),
    )
    transition = transition_volatility_corridor(ready_for_exit, exit_bar)
    assert transition.position.status is CorridorPositionStatus.EXIT_PENDING
    assert transition.exit_intent is not None
    assert transition.exit_intent.trigger_reason == "scheduled_fifth_session_adverse_window_exit"
    assert transition.exit_intent.conservative_reference_price == pytest.approx(99.0)
    unresolved = mark_volatility_corridor_missing_exit_window(
        position,
        observed_through=position.scheduled_exit_window_closed_at + timedelta(minutes=10),
    )
    assert unresolved.status is CorridorPositionStatus.CARRY_UNRESOLVED
    assert unresolved.exit_price is None


def _all_long_breakout_context(decision_at: datetime | None = None) -> CausalDecisionContext:
    """Stroit four-asset simultaneous long breakout dlya aggregate ladder testov."""
    base = _context(decision_at)
    assets = tuple(
        replace(
            asset,
            residual_decision_score=0.30,
            residual_location=0.30,
            normal_probability=0.30,
            trend_probability=0.60,
            crash_probability=0.10,
            range_position_20=1.05,
            volatility_ratio_20=1.20,
        )
        for asset in base.assets
    )
    return CausalDecisionContext(base.decision_at, assets, PREDICTION_SHA)


def _breakout_executions(
    context: CausalDecisionContext,
    run: object,
    *,
    zero_fill_asset: str | None = None,
) -> tuple[ScheduledCandidateExecution, ...]:
    """Stroit po odnom execution outcome na kazhdyi breakout intent."""
    rows: list[ScheduledCandidateExecution] = []
    for intent in run.breakout_intents:
        direction = (
            intent.desired_direction
            if intent.action in (BreakoutAction.ENTER, BreakoutAction.ADD)
            else -intent.prior_direction
        )
        executed = 0 if intent.asset_id == zero_fill_asset else direction
        rows.append(
            _scheduled_execution(
                context,
                AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
                intent.asset_id,
                direction,
                executed_contracts=executed,
                sequence_id=200,
                execution_bar_sequence_id=2_000,
            )
        )
    return tuple(rows)


def test_breakout_aggregate_gross_ladder_advances_only_after_full_fill() -> None:
    """Four-asset ladder imeet gross 1/3, 2/3, 1 i ne advance na zero fill."""
    first_context = _all_long_breakout_context()
    first = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        first_context,
    )
    assert first.decision.gross_exposure == pytest.approx(1.0 / 3.0)
    assert first.breakout_state is not None
    assert first.breakout_state.assets == ()
    level_one = apply_breakout_execution(
        first,
        _breakout_executions(first_context, first),
    )
    assert {item.pyramid_level for item in level_one.assets} == {1}

    second_context = _all_long_breakout_context(
        first_context.decision_at + timedelta(days=1)
    )
    second = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        second_context,
        breakout_state=level_one,
    )
    assert second.decision.gross_exposure == pytest.approx(2.0 / 3.0)
    assert {item.pyramid_level for item in second.breakout_state.assets} == {1}
    partially_filled = apply_breakout_execution(
        second,
        _breakout_executions(second_context, second, zero_fill_asset="BR"),
    )
    levels = {item.asset_id: item.pyramid_level for item in partially_filled.assets}
    assert levels["BR"] == 1
    assert set(levels.values()) == {1, 2}
    assert partially_filled.unresolved_asset_ids == ("BR",)
    unresolved = partially_filled.unresolved_executions[0]
    assert unresolved.contract_id == "BRM5"
    assert unresolved.executed_contracts == 0
    assert unresolved.carry_contracts == 1

    fully_filled_two = apply_breakout_execution(
        second,
        _breakout_executions(second_context, second),
    )
    third_context = _all_long_breakout_context(
        second_context.decision_at + timedelta(days=1)
    )
    third = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        third_context,
        breakout_state=fully_filled_two,
    )
    assert third.decision.gross_exposure == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("direction", "prior_extreme", "first_close", "second_close", "range_position", "score"),
    [
        (1, 120.0, 115.0, 110.0, 1.05, 0.30),
        (-1, 80.0, 85.0, 88.0, -0.05, -0.30),
    ],
)
def test_breakout_trailing_extreme_is_monotone_long_and_short(
    direction: int,
    prior_extreme: float,
    first_close: float,
    second_close: float,
    range_position: float,
    score: float,
) -> None:
    """Same-direction confirmation nikogda ne oslablyaet long/short ATR trail."""
    first_context = _context()
    prior = BreakoutPyramidState(
        first_context.decision_at - timedelta(days=1),
        (
            BreakoutAssetState(
                "RI",
                "RIM5",
                direction,
                1,
                prior_extreme,
                "prior-sleeve",
                "prior-order",
                CALENDAR_SHA,
                EXECUTION_SHA,
            ),
        ),
    )
    first_assets = tuple(
        replace(
            asset,
            close=first_close,
            atr_20=3.0,
            range_position_20=range_position if asset.asset_id == "RI" else 0.5,
            residual_decision_score=score if asset.asset_id == "RI" else 0.0,
            residual_location=score if asset.asset_id == "RI" else 0.0,
        )
        for asset in first_context.assets
    )
    confirmation_context = CausalDecisionContext(
        first_context.decision_at,
        first_assets,
        PREDICTION_SHA,
    )
    confirmation = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        confirmation_context,
        breakout_state=prior,
    )
    assert confirmation.breakout_state is not None
    ri_state = next(item for item in confirmation.breakout_state.assets if item.asset_id == "RI")
    assert ri_state.extreme_close == pytest.approx(prior_extreme)

    next_context_base = _context(first_context.decision_at + timedelta(days=1))
    next_assets = tuple(
        replace(
            asset,
            close=second_close,
            atr_20=3.0,
            range_position_20=0.5,
            residual_decision_score=0.0,
            residual_location=0.0,
        )
        for asset in next_context_base.assets
    )
    next_context = CausalDecisionContext(
        next_context_base.decision_at,
        next_assets,
        PREDICTION_SHA,
    )
    stopped = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        next_context,
        breakout_state=confirmation.breakout_state,
    )
    ri_intent = next(item for item in stopped.breakout_intents if item.asset_id == "RI")
    assert ri_intent.action is BreakoutAction.EXIT_TRAIL


def test_breakout_rejects_time_replay() -> None:
    """Filled breakout state nel'zya primenit' k proshlomu ili duplicate decision."""
    context = _context()
    state = BreakoutPyramidState(context.decision_at)
    with pytest.raises(ValueError, match="strogo po vremeni"):
        run_aggressive_candidate(
            AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
            context,
            breakout_state=state,
        )


def test_breakout_add_rejects_wrong_contract_and_reversal_exits_first() -> None:
    """ADD svyazan s prior contractom, a opposite signal ne delaet instant flip."""
    first_context = _all_long_breakout_context()
    first = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        first_context,
    )
    level_one = apply_breakout_execution(first, _breakout_executions(first_context, first))
    second_context = _all_long_breakout_context(
        first_context.decision_at + timedelta(days=1)
    )
    second = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        second_context,
        breakout_state=level_one,
    )
    executions = list(_breakout_executions(second_context, second))
    executions[0] = ScheduledCandidateExecution(
        executions[0].schedule,
        replace(executions[0].evidence, contract_id="WRONG-CONTRACT"),
    )
    with pytest.raises(ValueError, match="prior state"):
        apply_breakout_execution(second, executions)

    ri_prior = next(item for item in level_one.assets if item.asset_id == "RI")
    isolated = BreakoutPyramidState(
        first_context.decision_at,
        (replace(ri_prior, extreme_close=100.0),),
    )
    reverse_base = _context(first_context.decision_at + timedelta(days=1))
    reverse_assets = tuple(
        replace(
            asset,
            close=100.0,
            normal_probability=0.30,
            trend_probability=0.60,
            crash_probability=0.10,
            range_position_20=-0.05 if asset.asset_id == "RI" else 0.5,
            residual_decision_score=-0.30 if asset.asset_id == "RI" else 0.0,
            residual_location=-0.30 if asset.asset_id == "RI" else 0.0,
        )
        for asset in reverse_base.assets
    )
    reverse_context = CausalDecisionContext(
        reverse_base.decision_at,
        reverse_assets,
        PREDICTION_SHA,
    )
    reversal = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        reverse_context,
        breakout_state=isolated,
    )
    intent = next(item for item in reversal.breakout_intents if item.asset_id == "RI")
    assert intent.action is BreakoutAction.EXIT_REVERSAL
    assert "RI" not in dict(reversal.decision.target_weights)


def test_invalid_breakout_state_is_locked_carry_only_before_peer_normalization() -> None:
    """Invalid prior asset ne poluchaet target rebalance pri smene valid peer universe."""
    first_context = _all_long_breakout_context()
    first = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        first_context,
    )
    level_one = apply_breakout_execution(first, _breakout_executions(first_context, first))
    prior_br = next(item for item in level_one.assets if item.asset_id == "BR")
    next_base = _all_long_breakout_context(first_context.decision_at + timedelta(days=1))
    next_assets = tuple(
        replace(
            asset,
            planned_contract_valid=False,
            invalid_reason_codes=("planned_contract_invalid",),
        )
        if asset.asset_id == "BR"
        else asset
        for asset in next_base.assets
    )
    context = CausalDecisionContext(next_base.decision_at, next_assets, PREDICTION_SHA)
    run = run_aggressive_candidate(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        context,
        breakout_state=level_one,
    )
    assert "BR" not in dict(run.decision.target_weights)
    assert all(item.asset_id != "BR" for item in run.breakout_intents)
    assert len(run.breakout_locked_positions) == 1
    locked = run.breakout_locked_positions[0]
    assert locked.state is prior_br
    assert locked.reason_codes == ("planned_contract_invalid",)
    assert next(item for item in run.breakout_state.assets if item.asset_id == "BR") is prior_br


def _annual_metrics() -> list[CandidateAnnualMetric]:
    """Stroit exact 5-year metriky s dvumya gate-passing kandidatami."""
    rows: list[CandidateAnnualMetric] = []
    for candidate_index, candidate_id in enumerate(AggressiveCandidateId):
        for year_index, year in enumerate((2021, 2022, 2023, 2024, 2025)):
            net_return = 0.10 + 0.01 * year_index
            sharpe = 0.7 + 0.01 * candidate_index + 0.02 * year_index
            if candidate_index >= 2 and year_index >= 3:
                net_return = -0.02
            rows.append(
                CandidateAnnualMetric(
                    candidate_id,
                    year,
                    net_return,
                    sharpe,
                    EVALUATION_SHA,
                )
            )
    return rows


def _gate_metrics() -> list[CandidateGateMetric]:
    """Stroit validnye execution/double-cost gates na odnom prediction hash."""
    return [
        CandidateGateMetric(
            candidate_id=candidate_id,
            prediction_sha256=PREDICTION_SHA,
            evaluation_bundle_sha256=EVALUATION_SHA,
            primary_net_cagr=0.12,
            primary_sharpe=0.70,
            primary_max_drawdown=0.15,
            worst_calendar_year_return=0.10 if candidate_index < 2 else -0.02,
            doubled_cost_cagr=0.01,
            critical_execution_failure_count=0,
            maximum_participation_bps=100.0,
            unknown_capacity_count=0,
            unresolved_positions_at_terminal=0,
        )
        for candidate_index, candidate_id in enumerate(AggressiveCandidateId)
    ]


def test_selection_uses_fixed_gates_then_median_sharpe_and_worst_year() -> None:
    """Otsekaet 3/5 positive i sortiruet ne po CAGR ili stretch 50 procentov."""
    ranked = rank_gate_passing_candidates(_annual_metrics(), _gate_metrics())
    assert [row.candidate_id for row in ranked] == [
        AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION,
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
    ]
    assert all(row.positive_year_count == 5 for row in ranked)


def test_selection_rejects_prediction_reuse_drift_and_participation_breach() -> None:
    """Zapreshchaet raznye predictions i primenyaet exact 1-percent fill gate."""
    gates = _gate_metrics()
    gates[1] = replace(gates[1], prediction_sha256="b" * 64)
    with pytest.raises(ValueError, match="odin prediction SHA"):
        rank_gate_passing_candidates(_annual_metrics(), gates)
    gates = _gate_metrics()
    gates[0] = replace(gates[0], maximum_participation_bps=100.01)
    ranked = rank_gate_passing_candidates(_annual_metrics(), gates)
    assert AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST not in {
        row.candidate_id for row in ranked
    }


def test_selection_rejects_evaluation_bundle_and_worst_year_inconsistency() -> None:
    """Annual/gate rows ne mogut smeshivat' evaluator/data seals ili worst year."""
    gates = _gate_metrics()
    gates[1] = replace(gates[1], evaluation_bundle_sha256="8" * 64)
    with pytest.raises(ValueError, match="evaluation bundle SHA"):
        rank_gate_passing_candidates(_annual_metrics(), gates)
    gates = _gate_metrics()
    gates[0] = replace(gates[0], worst_calendar_year_return=0.11)
    with pytest.raises(ValueError, match="worst year"):
        rank_gate_passing_candidates(_annual_metrics(), gates)


def test_public_runner_has_no_numeric_runtime_tuning_surface() -> None:
    """API prinimaet tol'ko ID, snapshot i state, a ne post-PnL parametry."""
    signature = inspect.signature(run_aggressive_candidate)
    assert tuple(signature.parameters) == ("candidate_id", "context", "breakout_state")
    assert signature.parameters["breakout_state"].kind is inspect.Parameter.KEYWORD_ONLY
    for spec in CANDIDATE_SPECS:
        assert isinstance(spec.numeric_constants, tuple)
        with pytest.raises(FrozenInstanceError):
            spec.stateful = False  # type: ignore[misc]


def test_yaml_catalog_is_bom_sealed_and_matches_code_contract() -> None:
    """Proveryaet exact bytes, sidecar, ID i multiple-testing hard gates."""
    sidecar = CATALOG_PATH.with_suffix(".sha256")
    assert CATALOG_PATH.read_bytes().startswith(b"\xef\xbb\xbf")
    assert sidecar.read_bytes().startswith(b"\xef\xbb\xbf")
    expected = sidecar.read_text(encoding="utf-8-sig").split()[0]
    assert sha256(CATALOG_PATH.read_bytes()).hexdigest() == expected
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8-sig"))
    base_protocol_path = PROJECT_ROOT / payload["base_protocol"]
    base_protocol_sidecar = base_protocol_path.with_suffix(".sha256")
    base_protocol_expected = base_protocol_sidecar.read_text(encoding="utf-8-sig").split()[0]
    assert sha256(base_protocol_path.read_bytes()).hexdigest() == base_protocol_expected
    assert payload["base_protocol_sha256"] == base_protocol_expected
    assert payload["base_protocol_sha256"] == BASE_PROTOCOL_SHA256
    implementation_path = PROJECT_ROOT / payload["implementation"]
    assert sha256(implementation_path.read_bytes()).hexdigest() == payload[
        "implementation_sha256"
    ]
    assert tuple(candidate["id"] for candidate in payload["candidates"]) == (
        AGGRESSIVE_CANDIDATE_IDS
    )
    payload_by_id = {row["id"]: row for row in payload["candidates"]}
    for spec in CANDIDATE_SPECS:
        row = payload_by_id[spec.candidate_id.value]
        flattened = dict(row)
        if "pyramid_level_fractions" in row:
            for index, value in enumerate(row["pyramid_level_fractions"], start=1):
                flattened[f"pyramid_level_fraction_{index}"] = value
        for family_key, prefix in (
            ("rate_sensitivities", "rate_sensitivity"),
            ("fx_sensitivities", "fx_sensitivity"),
        ):
            for asset_id, value in row.get(family_key, {}).items():
                flattened[f"{prefix}_{asset_id}"] = value
        for name, expected_value in spec.numeric_constants:
            assert flattened[name] == pytest.approx(expected_value)
    assert payload["multiple_testing_control"]["candidate_family_size"] == 10
    assert payload["multiple_testing_control"]["all_candidates_predeclared_before_new_pnl"]
    assert payload["multiple_testing_control"]["post_pnl_parameter_or_candidate_edit"] == (
        "forbidden"
    )
    assert payload["causality"]["development_universe"] == ["BR", "MIX", "RI", "SI"]
    assert payload["causality"]["full_universe_required"] is True
    assert payload["multiple_testing_control"][
        "same_full_evaluation_bundle_for_every_candidate"
    ]
    assert payload["multiple_testing_control"]["ranking"] == [
        "median_yearly_sharpe_descending",
        "worst_calendar_year_return_descending",
        "candidate_id_ascending_tiebreak",
    ]
    gates = payload["multiple_testing_control"]["hard_gates"]
    assert gates["positive_calendar_year_count_minimum"] == 4
    assert gates["primary_net_cagr_minimum"] == 0.08
    assert gates["primary_sharpe_minimum"] == 0.50
    assert gates["primary_max_drawdown_maximum"] == 0.25
    assert gates["worst_calendar_year_return_minimum"] == -0.10
    assert gates["doubled_cost_cagr_strictly_positive"] is True
    assert gates["critical_execution_failure_count"] == 0
    assert gates["maximum_participation_bps"] == 100
    assert payload["multiple_testing_control"]["fifty_percent_cagr"] == {
        "threshold": 0.50,
        "report_only": True,
        "used_for_ranking": False,
        "used_for_holdout_access": False,
    }
