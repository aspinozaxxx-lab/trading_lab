"""Tochnye synthetic testy target-free evaluator i event-ledger futures-v8."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType

import pytest

from market_lab.futures_v8.aggressive_strategies import (
    AGGRESSIVE_CANDIDATE_IDS,
    AggressiveCandidateId,
    CandidateExecutionEvidence,
    CandidateExitExecutionEvidence,
    CausalAssetSnapshot,
    CausalDecisionContext,
    CorridorPositionStatus,
    FactualTenMinuteBar,
    HoldingSleeveSchedule,
    ScheduledCandidateExecution,
    open_volatility_corridor_position,
    run_aggressive_candidate,
    transition_volatility_corridor,
)
from market_lab.futures_v8.eval_run import (
    AGGRESSIVE_CATALOG_SHA256,
    CORE_STRATEGY_ID,
    V8AssetContractSnapshot,
    V8CandleTrustStatus,
    V8ContractSpec,
    V8EquityPoint,
    V8EventLedgerState,
    V8LedgerPosition,
    V8LedgerRiskError,
    V8OrderBinding,
    V8OrderCause,
    V8PositionKey,
    V8ScenarioId,
    V8ScenarioMetrics,
    V8ScenarioSpec,
    V8SealedEvaluationInputBundle,
    V8StrategyMetricsBundle,
    V8TargetFreePrediction,
    V8TrustedCandleIndex,
    V8YearMetric,
    apply_v8_corridor_exit_to_ledger,
    apply_v8_execution_batch,
    build_v8_gate_and_ranking,
    build_v8_long_paired_roll_binding,
    build_v8_signed_paired_roll_binding,
    build_v8_strategy_decision_set,
    candidate_execution_evidence_from_primary,
    canonical_sha256,
    create_v8_evaluation_ledger_matrix,
    fixed_v8_scenarios,
    integer_contracts_for_weight,
    plan_v8_scenario_execution,
    reconcile_v8_breakout_execution,
    select_v8_contract_spec_snapshot,
    settle_v8_event_ledger,
    summarize_v8_scenario,
)
from market_lab.futures_v8.execution import (
    ExecutionStatus,
    OrderExecution,
    PredeclaredMarketOrder,
    TenMinuteCandle,
)

# Edinyi fake SHA predictions dlya same-prediction invariantov.
PREDICTION_SHA = "a" * 64
# Edinyi fake SHA market evidence dlya synthetic input bundle.
MARKET_SHA = "b" * 64
# Edinyi fake SHA calendar dlya schedule/evaluation identity.
CALENDAR_SHA = "c" * 64
# Edinyi fake SHA contract-spec source.
SPEC_SHA = "d" * 64
# Edinyi fake SHA full evaluation bundle dlya ranking fixtures.
EVALUATION_SHA = "e" * 64


def _decision(day: int = 2) -> datetime:
    """Vozvrashchaet D18:50 Moscow kak 15:50 UTC v development 2025."""
    return datetime(2025, 6, day, 15, 50, tzinfo=UTC)


def _asset(
    asset_id: str, decision_at: datetime, residual: float, range_position: float
) -> CausalAssetSnapshot:
    """Stroit minimal'nyi validnyi target-free asset prediction snapshot."""
    return CausalAssetSnapshot(
        asset_id=asset_id,
        known_at=decision_at - timedelta(minutes=1),
        factor_decision_score=0.4,
        residual_decision_score=residual,
        residual_location=residual,
        total_scale=0.2,
        abstain_probability=0.1,
        normal_probability=0.2,
        trend_probability=0.7,
        crash_probability=0.1,
        close=100.0,
        atr_20=2.0,
        daily_volatility_20=0.02,
        momentum_20=0.02 if residual > 0 else -0.02,
        range_position_20=range_position,
        volatility_ratio_20=1.7,
        volume_ratio_20=1.7,
        market_data_sha256=MARKET_SHA,
        carry_z=None,
        cftc_crowd_z=None,
        key_rate_change_z=None,
        usd_rub_return_z=None,
    )


def _prediction(
    decision_at: datetime | None = None, prediction_sha: str = PREDICTION_SHA
) -> V8TargetFreePrediction:
    """Stroit edinyi prediction record, kotoryi aktiviruet breakout BR/MIX."""
    decision = decision_at or _decision()
    assets = (
        _asset("BR", decision, 0.6, 1.1),
        _asset("MIX", decision, -0.7, -0.1),
        _asset("RI", decision, 0.2, 0.6),
        _asset("SI", decision, -0.2, 0.4),
    )
    context = CausalDecisionContext(decision, assets, prediction_sha)
    contracts = tuple(
        V8AssetContractSnapshot(
            asset_id=asset_id,
            contract_id=f"{asset_id}U5",
            entry_effective_session_date=decision.date() + timedelta(days=1),
            known_at=decision - timedelta(minutes=1),
            asset_mask=True,
            nominal_span_eligible=True,
            source_sha256=SPEC_SHA,
        )
        for asset_id in ("BR", "MIX", "RI", "SI")
    )
    return V8TargetFreePrediction(context, 0.5, 0.2, contracts)


def _spec(
    asset_id: str = "BR",
    contract_id: str = "BRU5",
    *,
    day: int = 2,
    decision_at: datetime | None = None,
    effective_session_date: date | None = None,
    multiplier: float = 10.0,
    sizing_multiplier: float | None = None,
    accounting_multiplier: float | None = None,
    margin: float = 100.0,
    fee: float = 2.0,
) -> V8ContractSpec:
    """Stroit exact daily lag-1/current spec s upravlyaemymi constants."""
    decision = decision_at or _decision(day)
    effective_session = effective_session_date or (decision.date() + timedelta(days=1))
    return V8ContractSpec(
        asset_id=asset_id,
        contract_id=contract_id,
        effective_session_date=effective_session,
        sizing_observed_session_date=decision.date(),
        sizing_known_at=decision - timedelta(minutes=1),
        accounting_known_at=decision + timedelta(days=1, hours=5),
        sizing_price_multiplier=(multiplier if sizing_multiplier is None else sizing_multiplier),
        accounting_price_multiplier=(
            multiplier if accounting_multiplier is None else accounting_multiplier
        ),
        initial_margin_per_contract=margin,
        fee_per_contract=fee,
        source_sha256=SPEC_SHA,
    )


def _candle(
    contract_id: str,
    opened_at: datetime,
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: int,
) -> TenMinuteCandle:
    """Stroit polnyi factual 10m bar bez price/volume substitution."""
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


def _execution_candles(
    contract_id: str,
    decision_at: datetime,
    *,
    observed_volume: int = 2_000,
    execution_volume: int = 2_000,
    delay_volume: int = 500,
    execution_open: float = 100.0,
    execution_high: float = 105.0,
    execution_low: float = 95.0,
    delay_open: float = 101.0,
    delay_high: float = 110.0,
    delay_low: float = 99.0,
) -> tuple[TenMinuteCandle, ...]:
    """Stroit exact capacity, primary i next-complete delay windows."""
    return (
        _candle(
            contract_id,
            decision_at + timedelta(minutes=10),
            open_price=100.0,
            high_price=100.0,
            low_price=100.0,
            close_price=100.0,
            volume=observed_volume,
        ),
        _candle(
            contract_id,
            decision_at + timedelta(minutes=30),
            open_price=execution_open,
            high_price=execution_high,
            low_price=execution_low,
            close_price=execution_open,
            volume=execution_volume,
        ),
        _candle(
            contract_id,
            decision_at + timedelta(minutes=40),
            open_price=delay_open,
            high_price=delay_high,
            low_price=delay_low,
            close_price=delay_open,
            volume=delay_volume,
        ),
    )


def _binding(
    signed_contracts: int,
    *,
    decision_at: datetime | None = None,
    contract_id: str = "BRU5",
    strategy_id: str = CORE_STRATEGY_ID,
    sleeve_id: str = "sleeve-1",
    order_id: str = "order-1",
    effective_session_date: date | None = None,
) -> V8OrderBinding:
    """Stroit odin primary market order i ego exact ledger position key."""
    decision = decision_at or _decision()
    key = V8PositionKey(strategy_id, sleeve_id, contract_id[:2], contract_id)
    return V8OrderBinding(
        request=PredeclaredMarketOrder(order_id, contract_id, decision, signed_contracts),
        cause=V8OrderCause.ENTRY,
        effective_session_date=(effective_session_date or (decision.date() + timedelta(days=1))),
        single_position=key,
    )


@dataclass(frozen=True, slots=True, init=False)
class _SyntheticTrustedCandleIndex(V8TrustedCandleIndex):
    """Tests-only capability; authoritative result ego nikogda ne prinimaet."""

    _candles: tuple[TenMinuteCandle, ...]
    _index: Mapping[tuple[str, datetime], TenMinuteCandle]
    trust_status: V8CandleTrustStatus
    candle_panel_sha256: str
    coverage_sha256: str
    key_set_sha256: str
    evaluation_bundle_sha256: str
    market_data_sha256: str
    source_identity_sha256: str
    source_manifest_sha256: str
    artifact_bytes: int
    row_count: int

    def __init__(self, bundle: V8SealedEvaluationInputBundle) -> None:
        """Sealit explicit synthetic panel bez production issuer API."""
        candles = bundle.candles
        index = {(item.contract_id, item.opened_at): item for item in candles}
        keys = tuple(sorted(index, key=lambda item: (item[1], item[0])))
        key_hash = canonical_sha256(keys)
        coverage_hash = canonical_sha256(
            {
                "trust_status": V8CandleTrustStatus.SYNTHETIC_TEST,
                "evaluation_bundle_sha256": bundle.evaluation_bundle_sha256,
                "keys": keys,
            }
        )
        object.__setattr__(self, "_candles", candles)
        object.__setattr__(self, "_index", MappingProxyType(index))
        object.__setattr__(
            self,
            "trust_status",
            V8CandleTrustStatus.SYNTHETIC_TEST,
        )
        object.__setattr__(
            self,
            "candle_panel_sha256",
            canonical_sha256(
                {
                    "coverage_sha256": coverage_hash,
                    "candles": candles,
                }
            ),
        )
        object.__setattr__(self, "coverage_sha256", coverage_hash)
        object.__setattr__(self, "key_set_sha256", key_hash)
        object.__setattr__(
            self,
            "evaluation_bundle_sha256",
            bundle.evaluation_bundle_sha256,
        )
        object.__setattr__(self, "market_data_sha256", bundle.market_data_sha256)
        object.__setattr__(self, "source_identity_sha256", "f" * 64)
        object.__setattr__(self, "source_manifest_sha256", "e" * 64)
        object.__setattr__(self, "artifact_bytes", max(1, len(candles)))
        object.__setattr__(self, "row_count", len(candles))

    @property
    def candles(self) -> tuple[TenMinuteCandle, ...]:
        """Vozvrashchaet immutable synthetic panel."""
        return self._candles

    @property
    def index(self) -> Mapping[tuple[str, datetime], TenMinuteCandle]:
        """Vozvrashchaet read-only synthetic lookup."""
        return self._index


def _trusted_index(candles: tuple[TenMinuteCandle, ...]) -> V8TrustedCandleIndex:
    """Vypuskaet explicit tests-only full-panel capability."""
    bundle = V8SealedEvaluationInputBundle(
        predictions=(_prediction(),),
        contract_specs=tuple(
            _spec(asset_id, f"{asset_id}U5")
            for asset_id in ("BR", "MIX", "RI", "SI")
        ),
        candles=candles,
        market_data_sha256=MARKET_SHA,
        calendar_sha256=CALENDAR_SHA,
    )
    return _SyntheticTrustedCandleIndex(bundle)


def _pin_state(
    state: V8EventLedgerState,
    trusted_index: V8TrustedCandleIndex,
) -> V8EventLedgerState:
    """Privyazyvaet unit ledger k explicit synthetic bundle/panel root."""
    return replace(
        state,
        candle_trust_status=trusted_index.trust_status,
        evaluation_bundle_sha256=trusted_index.evaluation_bundle_sha256,
        trusted_candle_panel_sha256=trusted_index.candle_panel_sha256,
    )


def test_fixed_scenarios_are_exact_and_runtime_tuning_is_rejected() -> None:
    """Fiksiruet primary, doubled-cost i next-bar delay bez chetvertogo scenariya."""
    scenarios = fixed_v8_scenarios()
    assert tuple(item.scenario_id for item in scenarios) == (
        V8ScenarioId.PRIMARY,
        V8ScenarioId.DOUBLE_COST,
        V8ScenarioId.DELAY,
    )
    assert tuple(
        (item.fee_multiplier, item.adverse_excursion_multiplier, item.delay_bars)
        for item in scenarios
    ) == ((1.0, 1.0, 0), (2.0, 2.0, 0), (1.0, 1.0, 1))
    with pytest.raises(ValueError, match="fixed protocol"):
        V8ScenarioSpec(V8ScenarioId.PRIMARY, 1.0, 1.5, 0)


def test_one_prediction_builds_core_and_exact_ten_candidates_without_target_fields() -> None:
    """Dokazyvaet 11 variants na odnom SHA i otsutstvie label/return v prediction type."""
    prediction = _prediction()
    decision_set = build_v8_strategy_decision_set(prediction)

    assert len(decision_set.aggressive_runs) == 10
    assert tuple(run.decision.candidate_id.value for run in decision_set.aggressive_runs) == (
        AGGRESSIVE_CANDIDATE_IDS
    )
    assert {run.decision.prediction_sha256 for run in decision_set.aggressive_runs} == {
        PREDICTION_SHA
    }
    forbidden_tokens = ("target", "label", "return")
    assert not any(
        token in item.name for item in fields(V8TargetFreePrediction) for token in forbidden_tokens
    )


def test_sealed_input_bundle_hashes_predictions_specs_and_candles_and_rejects_2026() -> None:
    """Proveryaet odin immutable evaluation seal i zashchitu holdout candles."""
    prediction = _prediction()
    specs = tuple(_spec(asset, f"{asset}U5") for asset in ("BR", "MIX", "RI", "SI"))
    bundle = V8SealedEvaluationInputBundle(
        predictions=(prediction,),
        contract_specs=specs,
        candles=_execution_candles("BRU5", prediction.context.decision_at),
        market_data_sha256=MARKET_SHA,
        calendar_sha256=CALENDAR_SHA,
        catalog_sha256=AGGRESSIVE_CATALOG_SHA256,
    )

    assert bundle.prediction_sha256 == PREDICTION_SHA
    assert len(bundle.evaluation_bundle_sha256) == 64
    matrix = create_v8_evaluation_ledger_matrix(
        bundle,
        _SyntheticTrustedCandleIndex(bundle),
        initial_cash=1_000_000.0,
    )
    assert len(matrix.ledgers) == 33
    assert all(
        item.evaluation_bundle_sha256 == bundle.evaluation_bundle_sha256
        and item.trusted_candle_panel_sha256
        == matrix.trusted_candle_panel_sha256
        and item.candle_trust_status is V8CandleTrustStatus.SYNTHETIC_TEST
        for item in matrix.ledgers
    )
    assert matrix.ledger(CORE_STRATEGY_ID, V8ScenarioId.PRIMARY).cash == 1_000_000.0
    future = _candle(
        "BRU5",
        datetime(2026, 1, 2, tzinfo=UTC),
        open_price=100.0,
        high_price=100.0,
        low_price=100.0,
        close_price=100.0,
        volume=1_000,
    )
    with pytest.raises(ValueError, match="2026"):
        V8SealedEvaluationInputBundle(
            predictions=(prediction,),
            contract_specs=specs,
            candles=(future,),
            market_data_sha256=MARKET_SHA,
            calendar_sha256=CALENDAR_SHA,
        )


def test_sealed_bundle_accepts_daily_contract_snapshots_and_requires_exact_session() -> None:
    """Fiksiruet contract/session key vmesto odnoi static spec na zhizn' contracta."""
    predictions = (_prediction(_decision(2)), _prediction(_decision(3)))
    specs = tuple(
        _spec(asset, f"{asset}U5", day=day) for day in (2, 3) for asset in ("BR", "MIX", "RI", "SI")
    )
    bundle = V8SealedEvaluationInputBundle(
        predictions=predictions,
        contract_specs=specs,
        candles=(),
        market_data_sha256=MARKET_SHA,
        calendar_sha256=CALENDAR_SHA,
    )
    assert len(bundle.contract_specs) == 8
    with pytest.raises(ValueError, match="exact contract/session"):
        V8SealedEvaluationInputBundle(
            predictions=predictions,
            contract_specs=tuple(
                item
                for item in specs
                if not (
                    item.contract_id == "BRU5"
                    and item.effective_session_date == _decision(3).date() + timedelta(days=1)
                )
            ),
            candles=(),
            market_data_sha256=MARKET_SHA,
            calendar_sha256=CALENDAR_SHA,
        )
    with pytest.raises(ValueError, match="duplicate contract/session"):
        V8SealedEvaluationInputBundle(
            predictions=predictions,
            contract_specs=(*specs, specs[-1]),
            candles=(),
            market_data_sha256=MARKET_SHA,
            calendar_sha256=CALENDAR_SHA,
        )


def test_january_four_decision_joins_january_five_entry_spec_with_observed_d() -> None:
    """Regressiya: D=Jan-4 join'itsya k entry Jan-5, no ne k stale Jan-4 row."""
    decision = datetime(2021, 1, 4, 15, 50, tzinfo=UTC)
    prediction = _prediction(decision)
    specs = tuple(
        _spec(
            asset,
            f"{asset}U5",
            decision_at=decision,
            effective_session_date=date(2021, 1, 5),
        )
        for asset in ("BR", "MIX", "RI", "SI")
    )
    bundle = V8SealedEvaluationInputBundle(
        predictions=(prediction,),
        contract_specs=specs,
        candles=(),
        market_data_sha256=MARKET_SHA,
        calendar_sha256=CALENDAR_SHA,
    )
    assert {item.entry_effective_session_date for item in prediction.contracts} == {
        date(2021, 1, 5)
    }
    assert {item.effective_session_date for item in bundle.contract_specs} == {date(2021, 1, 5)}
    assert {item.sizing_observed_session_date for item in bundle.contract_specs} == {
        date(2021, 1, 4)
    }
    binding = _binding(
        1,
        decision_at=decision,
        effective_session_date=date(2021, 1, 5),
    )
    trusted_candles = _execution_candles("BRU5", decision)
    trusted_index = _trusted_index(trusted_candles)
    evidence = plan_v8_scenario_execution(
        (binding,),
        trusted_index,
        V8ScenarioId.PRIMARY,
    )
    assert evidence[0].effective_session_date == date(2021, 1, 5)
    ledger = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.PRIMARY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    ledger = apply_v8_execution_batch(
        ledger,
        (binding,),
        evidence,
        specs,
        trusted_candles=trusted_index,
        accounting_as_of=max(item.accounting_known_at for item in specs),
    )
    assert ledger.fills[0].spec_effective_session_date == date(2021, 1, 5)
    with pytest.raises(ValueError, match="posle decision D"):
        _binding(
            1,
            decision_at=decision,
            effective_session_date=date(2021, 1, 4),
        )

    wrong_observed = tuple(
        replace(
            item,
            sizing_observed_session_date=date(2020, 12, 30),
            sizing_known_at=decision - timedelta(days=5),
        )
        for item in specs
    )
    with pytest.raises(ValueError, match="exact contract/session"):
        V8SealedEvaluationInputBundle(
            predictions=(prediction,),
            contract_specs=wrong_observed,
            candles=(),
            market_data_sha256=MARKET_SHA,
            calendar_sha256=CALENDAR_SHA,
        )
    stale_january_four = tuple(
        replace(
            item,
            effective_session_date=date(2021, 1, 4),
            sizing_observed_session_date=date(2020, 12, 30),
            sizing_known_at=decision - timedelta(days=5),
            accounting_known_at=decision + timedelta(hours=5),
        )
        for item in specs
    )
    with pytest.raises(ValueError, match="exact contract/session"):
        V8SealedEvaluationInputBundle(
            predictions=(prediction,),
            contract_specs=stale_january_four,
            candles=(),
            market_data_sha256=MARKET_SHA,
            calendar_sha256=CALENDAR_SHA,
        )
    with pytest.raises(LookupError, match="exact contract/session"):
        apply_v8_execution_batch(
            V8EventLedgerState.create(
                CORE_STRATEGY_ID,
                V8ScenarioId.PRIMARY,
                100_000.0,
                trusted_candles=trusted_index,
            ),
            (binding,),
            evidence,
            stale_january_four,
            trusted_candles=trusted_index,
            accounting_as_of=max(item.accounting_known_at for item in specs),
        )


def test_primary_double_cost_and_delay_use_exact_evidence_prices_and_capacity() -> None:
    """Proveryaet 105 primary, 110 doubled excursion i delay partial 5 po next bar."""
    binding = _binding(10)
    candles = _execution_candles("BRU5", _decision())
    trusted_index = _trusted_index(candles)

    primary = plan_v8_scenario_execution((binding,), trusted_index, V8ScenarioId.PRIMARY)[0]
    doubled = plan_v8_scenario_execution((binding,), trusted_index, V8ScenarioId.DOUBLE_COST)[0]
    delayed = plan_v8_scenario_execution((binding,), trusted_index, V8ScenarioId.DELAY)[0]

    assert isinstance(primary.base_execution, OrderExecution)
    assert primary.legs[0].execution_price == 105.0
    assert doubled.legs[0].execution_price == 110.0
    assert delayed.executed_contracts == 5
    assert delayed.carry_contracts == 5
    assert delayed.status is ExecutionStatus.PARTIAL_CARRY
    assert delayed.legs[0].execution_price == 110.0
    assert delayed.legs[0].window_opened_at == _decision() + timedelta(minutes=40)
    assert len({primary.evidence_sha256, doubled.evidence_sha256, delayed.evidence_sha256}) == 3

    double_state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.DOUBLE_COST,
        100_000.0,
        trusted_candles=trusted_index,
    )
    double_spec = _spec()
    double_state = apply_v8_execution_batch(
        double_state,
        (binding,),
        (doubled,),
        (double_spec,),
        trusted_candles=trusted_index,
        accounting_as_of=double_spec.accounting_known_at,
    )
    assert double_state.cash == pytest.approx(99_960.0)
    double_state = settle_v8_event_ledger(
        double_state,
        (double_spec,),
        {"BRU5": 100.0},
        marked_at=_decision() + timedelta(minutes=40),
        effective_session_date=double_spec.effective_session_date,
        accounting_as_of=double_spec.accounting_known_at,
    )
    assert double_state.cash == pytest.approx(98_960.0)


def test_primary_single_replace_forgery_is_rejected_before_ledger() -> None:
    """Repro: coherent scenario quantity forgery ne mozhet otvyazat'sya ot base."""
    binding = _binding(10)
    evidence = plan_v8_scenario_execution(
        (binding,),
        _execution_candles("BRU5", _decision()),
        V8ScenarioId.PRIMARY,
    )[0]
    assert evidence.executed_contracts == 10

    with pytest.raises(ValueError, match="scenario/base executed_contracts mismatch"):
        replace(
            evidence,
            executed_contracts=5,
            carry_contracts=5,
            status=ExecutionStatus.PARTIAL_CARRY,
            legs=(replace(evidence.legs[0], signed_contracts=5),),
        )


def test_primary_paired_replace_forgery_exact_audit_repro_is_rejected() -> None:
    """Fiksiruet audit repro OLD2/NEW2 pri immutable base execution=3."""
    old_position = V8LedgerPosition(
        V8PositionKey(CORE_STRATEGY_ID, "old-audit", "BR", "BRU5"),
        4,
        100.0,
    )
    roll = build_v8_long_paired_roll_binding(
        old_position=old_position,
        new_contract_id="BRZ5",
        new_sleeve_id="new-audit",
        decision_at=_decision(),
        effective_session_date=_spec().effective_session_date,
        contracts=4,
    )
    candles = (
        *_execution_candles(
            "BRU5",
            _decision(),
            observed_volume=500,
            execution_volume=300,
            execution_high=102.0,
            execution_low=99.0,
        ),
        *_execution_candles(
            "BRZ5",
            _decision(),
            observed_volume=500,
            execution_volume=500,
            execution_high=102.0,
            execution_low=98.0,
        ),
    )
    evidence = plan_v8_scenario_execution(
        (roll,),
        candles,
        V8ScenarioId.PRIMARY,
    )[0]
    assert evidence.base_execution.executed_contracts == 3

    with pytest.raises(ValueError, match="scenario/base executed_contracts mismatch"):
        replace(
            evidence,
            executed_contracts=2,
            carry_contracts=2,
            legs=(
                replace(evidence.legs[0], signed_contracts=-2),
                replace(evidence.legs[1], signed_contracts=2),
            ),
        )


def test_primary_derivation_rejects_leg_and_status_mutations_before_ledger() -> None:
    """Blokiruet exact price/window/OHLCV/capacity/reason/contract i status drift."""
    evidence = plan_v8_scenario_execution(
        (_binding(10),),
        _execution_candles("BRU5", _decision()),
        V8ScenarioId.PRIMARY,
    )[0]
    leg = evidence.legs[0]
    shifted_open = leg.window_opened_at + timedelta(minutes=10)
    mutations = (
        replace(leg, execution_price=leg.execution_price + 1.0),
        replace(
            leg,
            window_opened_at=shifted_open,
            window_closed_at=shifted_open + timedelta(minutes=10),
        ),
        replace(leg, capacity_contracts=leg.capacity_contracts + 1),
        replace(leg, factual_open=leg.factual_open - 1.0),
        replace(leg, factual_volume=leg.factual_volume + 1),
        replace(leg, reason="forged_reason"),
        replace(leg, contract_id="BRZ5"),
    )
    for forged_leg in mutations:
        with pytest.raises(ValueError, match="scenario/base"):
            replace(evidence, legs=(forged_leg,))
    with pytest.raises(ValueError, match="status"):
        replace(evidence, status=ExecutionStatus.CARRIED)


def test_double_and_delay_derivations_reject_price_window_and_capacity_mutations() -> None:
    """Fiksiruet 2x base stress i next-bar delay kak derivational evidence."""
    binding = _binding(10)
    candles = _execution_candles("BRU5", _decision())
    doubled = plan_v8_scenario_execution((binding,), candles, V8ScenarioId.DOUBLE_COST)[0]
    delayed = plan_v8_scenario_execution((binding,), candles, V8ScenarioId.DELAY)[0]

    assert doubled.legs[0].execution_price == 110.0
    with pytest.raises(ValueError, match="scenario/base leg execution_price mismatch"):
        replace(
            doubled,
            legs=(replace(doubled.legs[0], execution_price=111.0),),
        )

    delay_leg = delayed.legs[0]
    assert delayed.base_execution.executed_contracts == 10
    assert delayed.executed_contracts == 5
    delay_mutations = (
        replace(delay_leg, execution_price=delay_leg.execution_price + 1.0),
        replace(
            delay_leg,
            window_opened_at=delay_leg.window_opened_at + timedelta(minutes=10),
            window_closed_at=delay_leg.window_closed_at + timedelta(minutes=10),
        ),
        replace(delay_leg, capacity_contracts=delay_leg.capacity_contracts + 1),
        replace(delay_leg, factual_volume=delay_leg.factual_volume + 100),
        replace(delay_leg, contract_id="BRZ5"),
    )
    for forged_leg in delay_mutations:
        with pytest.raises(ValueError, match="scenario/base"):
            replace(delayed, legs=(forged_leg,))
    with pytest.raises(ValueError, match="status"):
        replace(delayed, status=ExecutionStatus.CARRIED)


def test_delay_self_consistent_factual_leg_forgery_is_rejected_by_trusted_replay() -> None:
    """Blokiruet forged delayed OHLC/reason, kotorye lokal'no self-consistent."""
    binding = _binding(10)
    trusted_index = _trusted_index(_execution_candles("BRU5", _decision()))
    evidence = plan_v8_scenario_execution(
        (binding,),
        trusted_index,
        V8ScenarioId.DELAY,
    )[0]
    forged_leg = replace(
        evidence.legs[0],
        execution_price=210.0,
        factual_open=201.0,
        factual_high=210.0,
        factual_low=199.0,
        factual_close=202.0,
        reason="forged_delayed_filled",
    )
    forged = replace(evidence, legs=(forged_leg,))
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.DELAY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    spec = _spec()

    with pytest.raises(ValueError, match="exact trusted-candle batch replay"):
        apply_v8_execution_batch(
            state,
            (binding,),
            (forged,),
            (spec,),
            trusted_candles=trusted_index,
            accounting_as_of=spec.accounting_known_at,
        )
    assert state.fills == ()
    assert state.unresolved_orders == ()


def test_delay_nested_source_and_capacity_forgery_is_rejected_by_trusted_replay() -> None:
    """Blokiruet coherent forged base+delay OHLCV/capacity/quantity evidence."""
    binding = _binding(10)
    trusted_index = _trusted_index(_execution_candles("BRU5", _decision()))
    evidence = plan_v8_scenario_execution(
        (binding,),
        trusted_index,
        V8ScenarioId.DELAY,
    )[0]
    assert isinstance(evidence.base_execution, OrderExecution)
    forged_base_leg = replace(
        evidence.base_execution.leg,
        observed_capacity_volume=1_000,
        observed_capacity_contracts=10,
        factual_execution_open=200.0,
        factual_execution_high=220.0,
        factual_execution_low=190.0,
        factual_execution_close=200.0,
        realized_execution_volume=1_000,
        realized_execution_capacity_contracts=10,
        aggregate_available_before=10,
        execution_price=220.0,
        reason="forged_base_filled",
    )
    forged_base = replace(
        evidence.base_execution,
        reason="forged_base_filled",
        leg=forged_base_leg,
    )
    forged_delay_leg = replace(
        evidence.legs[0],
        signed_contracts=10,
        execution_price=310.0,
        factual_open=300.0,
        factual_high=310.0,
        factual_low=290.0,
        factual_close=300.0,
        factual_volume=1_000,
        capacity_contracts=10,
        reason="forged_delayed_filled",
    )
    forged = replace(
        evidence,
        base_execution=forged_base,
        executed_contracts=10,
        carry_contracts=0,
        status=ExecutionStatus.FILLED,
        legs=(forged_delay_leg,),
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.DELAY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    spec = _spec()

    with pytest.raises(ValueError, match="exact trusted-candle batch replay"):
        apply_v8_execution_batch(
            state,
            (binding,),
            (forged,),
            (spec,),
            trusted_candles=trusted_index,
            accounting_as_of=spec.accounting_known_at,
        )
    assert state == V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.DELAY,
        100_000.0,
        trusted_candles=trusted_index,
    )


def test_nested_base_single_quantity_forgery_is_rejected_by_trusted_replay() -> None:
    """Blokiruet coherent single base/result/leg quantity rewrite do mutation."""
    binding = _binding(10)
    trusted_index = _trusted_index(_execution_candles("BRU5", _decision()))
    evidence = plan_v8_scenario_execution(
        (binding,),
        trusted_index,
        V8ScenarioId.PRIMARY,
    )[0]
    assert isinstance(evidence.base_execution, OrderExecution)
    forged_base = replace(
        evidence.base_execution,
        executed_contracts=5,
        carry_contracts=5,
        status=ExecutionStatus.PARTIAL_CARRY,
        leg=replace(evidence.base_execution.leg, executed_contracts=5),
    )
    forged = replace(
        evidence,
        base_execution=forged_base,
        executed_contracts=5,
        carry_contracts=5,
        status=ExecutionStatus.PARTIAL_CARRY,
        legs=(replace(evidence.legs[0], signed_contracts=5),),
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.PRIMARY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    spec = _spec()

    with pytest.raises(ValueError, match="exact trusted-candle batch replay"):
        apply_v8_execution_batch(
            state,
            (binding,),
            (forged,),
            (spec,),
            trusted_candles=trusted_index,
            accounting_as_of=spec.accounting_known_at,
        )
    assert state.fills == ()


def test_nested_base_paired_audit_forgery_is_rejected_by_trusted_replay() -> None:
    """Repro OLD2/NEW2: coherent nested base rewrite ne prohodit admission."""
    old_position = V8LedgerPosition(
        V8PositionKey(CORE_STRATEGY_ID, "old-nested-audit", "BR", "BRU5"),
        4,
        100.0,
    )
    roll = build_v8_long_paired_roll_binding(
        old_position=old_position,
        new_contract_id="BRZ5",
        new_sleeve_id="new-nested-audit",
        decision_at=_decision(),
        effective_session_date=_spec().effective_session_date,
        contracts=4,
    )
    candles = (
        *_execution_candles(
            "BRU5",
            _decision(),
            observed_volume=500,
            execution_volume=300,
        ),
        *_execution_candles(
            "BRZ5",
            _decision(),
            observed_volume=500,
            execution_volume=500,
        ),
    )
    trusted_index = _trusted_index(candles)
    evidence = plan_v8_scenario_execution(
        (roll,),
        trusted_index,
        V8ScenarioId.PRIMARY,
    )[0]
    forged_base = replace(
        evidence.base_execution,
        executed_contracts=2,
        carry_contracts=2,
        old_leg=replace(evidence.base_execution.old_leg, executed_contracts=-2),
        new_leg=replace(evidence.base_execution.new_leg, executed_contracts=2),
    )
    forged = replace(
        evidence,
        base_execution=forged_base,
        executed_contracts=2,
        carry_contracts=2,
        legs=(
            replace(evidence.legs[0], signed_contracts=-2),
            replace(evidence.legs[1], signed_contracts=2),
        ),
    )
    state = V8EventLedgerState(
        strategy_id=CORE_STRATEGY_ID,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100_000.0,
        cash=100_000.0,
        positions=(old_position,),
    )
    state = _pin_state(state, trusted_index)
    specs = (_spec(contract_id="BRU5"), _spec(contract_id="BRZ5"))

    with pytest.raises(ValueError, match="exact trusted-candle batch replay"):
        apply_v8_execution_batch(
            state,
            (roll,),
            (forged,),
            specs,
            trusted_candles=trusted_index,
            accounting_as_of=max(item.accounting_known_at for item in specs),
        )
    assert state.fills == ()


def test_truncated_caller_panel_cannot_fabricate_missing_delay_bar() -> None:
    """Typed absence prihodit iz full index, a ne iz caller-supplied subset."""
    binding = _binding(10)
    candles = _execution_candles("BRU5", _decision())
    full_index = _trusted_index(candles)
    truncated_index = _trusted_index(candles[:-1])
    forged_absence = plan_v8_scenario_execution(
        (binding,),
        truncated_index,
        V8ScenarioId.DELAY,
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.DELAY,
        100_000.0,
        trusted_candles=full_index,
    )
    spec = _spec()

    assert not hasattr(V8TrustedCandleIndex, "from_bundle")
    assert not hasattr(V8TrustedCandleIndex, "_from_verified_bundle")
    with pytest.raises(TypeError, match="public issuer"):
        V8TrustedCandleIndex()
    with pytest.raises(TypeError, match="full sealed V8TrustedCandleIndex"):
        apply_v8_execution_batch(
            state,
            (binding,),
            forged_absence,
            (spec,),
            trusted_candles=candles,  # type: ignore[arg-type]
            accounting_as_of=spec.accounting_known_at,
        )
    with pytest.raises(ValueError, match="trusted candle panel SHA"):
        apply_v8_execution_batch(
            state,
            (binding,),
            forged_absence,
            (spec,),
            trusted_candles=full_index,
            accounting_as_of=spec.accounting_known_at,
        )
    with pytest.raises(ValueError, match="trust-root identity mismatch"):
        apply_v8_execution_batch(
            state,
            (binding,),
            forged_absence,
            (spec,),
            trusted_candles=truncated_index,
            accounting_as_of=spec.accounting_known_at,
        )
    with pytest.raises(TypeError):
        replace(full_index, row_count=2)
    assert state.fills == ()


def test_trusted_replay_materializes_only_order_windows_from_large_full_panel() -> None:
    """Per-batch replay O(legs), hot path ne skaniruet ves' authoritative panel."""
    binding = _binding(10)
    irrelevant_start = datetime(2024, 1, 1, tzinfo=UTC)
    irrelevant = tuple(
        _candle(
            "RIH4",
            irrelevant_start + timedelta(minutes=10 * index),
            open_price=100.0,
            high_price=101.0,
            low_price=99.0,
            close_price=100.0,
            volume=1_000,
        )
        for index in range(1_000)
    )
    trusted_index = _trusted_index(
        (*irrelevant, *_execution_candles("BRU5", _decision()))
    )

    replay_subset = trusted_index.replay_subset((binding,))

    assert trusted_index.row_count == 1_003
    assert len(replay_subset) == 3
    assert {item.contract_id for item in replay_subset} == {"BRU5"}


def test_partial_carry_is_terminal_unresolved_and_exact_replay_is_rejected() -> None:
    """Ne retry'it carry i ne podderzhivaet split-state replay odnogo ordera."""
    binding = _binding(10)
    trusted_candles = _execution_candles("BRU5", _decision())
    trusted_index = _trusted_index(trusted_candles)
    evidence = plan_v8_scenario_execution(
        (binding,),
        trusted_index,
        V8ScenarioId.DELAY,
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.DELAY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    spec = _spec()
    state = apply_v8_execution_batch(
        state,
        (binding,),
        evidence,
        (spec,),
        trusted_candles=trusted_index,
        accounting_as_of=spec.accounting_known_at,
    )

    assert state.positions[0].quantity == 5
    assert len(state.unresolved_orders) == 1
    assert state.unresolved_orders[0].carry_contracts == 5
    with pytest.raises(ValueError, match="povtorno"):
        apply_v8_execution_batch(
            state,
            (binding,),
            evidence,
            (spec,),
            trusted_candles=trusted_index,
            accounting_as_of=spec.accounting_known_at,
        )


def test_delay_missing_exact_next_bar_carries_and_never_uses_later_fallback() -> None:
    """Zapreshchaet delay scenariyu pereskakivat' cherez missing 19:30 window."""
    binding = _binding(2)
    candles = list(_execution_candles("BRU5", _decision())[:2])
    candles.append(
        _candle(
            "BRU5",
            _decision() + timedelta(minutes=50),
            open_price=500.0,
            high_price=600.0,
            low_price=400.0,
            close_price=500.0,
            volume=1_000_000,
        )
    )

    delayed = plan_v8_scenario_execution((binding,), candles, V8ScenarioId.DELAY)[0]

    assert delayed.executed_contracts == 0
    assert delayed.carry_contracts == 2
    assert delayed.legs[0].execution_price is None
    assert delayed.legs[0].reason == "missing_next_factual_10m_window"


def test_pov_capacity_cannot_be_reset_by_splitting_one_window_into_two_calls() -> None:
    """Persistit gross capacity i zapreshchaet povtornyi API batch v tom zhe okne."""
    candles = _execution_candles(
        "BRU5",
        _decision(),
        observed_volume=300,
        execution_volume=300,
    )
    trusted_index = _trusted_index(candles)
    first = _binding(2, sleeve_id="sleeve-a", order_id="split-a")
    first_evidence = plan_v8_scenario_execution(
        (first,), trusted_index, V8ScenarioId.PRIMARY
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.PRIMARY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    spec = _spec()
    state = apply_v8_execution_batch(
        state,
        (first,),
        first_evidence,
        (spec,),
        trusted_candles=trusted_index,
        accounting_as_of=spec.accounting_known_at,
    )
    assert state.capacity_consumption[0].capacity_contracts == 3
    assert state.capacity_consumption[0].consumed_contracts == 2

    second = _binding(2, sleeve_id="sleeve-b", order_id="split-b")
    second_evidence = plan_v8_scenario_execution(
        (second,), trusted_index, V8ScenarioId.PRIMARY
    )
    with pytest.raises(ValueError, match="predydushchego batch window"):
        apply_v8_execution_batch(
            state,
            (second,),
            second_evidence,
            (spec,),
            trusted_candles=trusted_index,
            accounting_as_of=spec.accounting_known_at,
        )


def test_event_ledger_exact_vm_fee_turnover_slippage_and_integer_reversal() -> None:
    """Schitaet entry, settlement i reversal bez spot-cash ili fractional pozicii."""
    spec = _spec()
    first = _binding(2)
    first_candles = _execution_candles("BRU5", _decision())
    second_decision = _decision(3)
    reversal = _binding(-3, decision_at=second_decision, order_id="reversal")
    reversal_candles = _execution_candles(
        "BRU5",
        second_decision,
        execution_open=110.0,
        execution_high=112.0,
        execution_low=108.0,
        delay_open=109.0,
        delay_high=111.0,
        delay_low=107.0,
    )
    trusted_index = _trusted_index((*first_candles, *reversal_candles))
    first_evidence = plan_v8_scenario_execution(
        (first,),
        trusted_index,
        V8ScenarioId.PRIMARY,
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.PRIMARY,
        100_000.0,
        trusted_candles=trusted_index,
    )
    state = apply_v8_execution_batch(
        state,
        (first,),
        first_evidence,
        (spec,),
        trusted_candles=trusted_index,
        accounting_as_of=spec.accounting_known_at,
    )

    assert state.cash == pytest.approx(99_996.0)
    assert state.positions[0].quantity == 2
    assert state.cumulative_fees == pytest.approx(4.0)
    assert state.cumulative_turnover == pytest.approx(2_100.0)
    assert state.cumulative_adverse_slippage == pytest.approx(100.0)

    state = settle_v8_event_ledger(
        state,
        (spec,),
        {"BRU5": 110.0},
        marked_at=_decision() + timedelta(hours=5),
        effective_session_date=spec.effective_session_date,
        accounting_as_of=spec.accounting_known_at,
    )
    assert state.cash == pytest.approx(100_096.0)

    reversal_evidence = plan_v8_scenario_execution(
        (reversal,), trusted_index, V8ScenarioId.PRIMARY
    )
    next_spec = _spec(day=3)
    state = apply_v8_execution_batch(
        state,
        (reversal,),
        reversal_evidence,
        (next_spec,),
        trusted_candles=trusted_index,
        accounting_as_of=next_spec.accounting_known_at,
    )

    assert state.cash == pytest.approx(100_050.0)
    assert state.positions[0].quantity == -1
    assert state.positions[0].reference_price == 108.0
    assert state.cumulative_fees == pytest.approx(10.0)
    assert state.cumulative_turnover == pytest.approx(5_340.0)
    assert state.cumulative_adverse_slippage == pytest.approx(160.0)

    state = settle_v8_event_ledger(
        state,
        (next_spec,),
        {"BRU5": 100.0},
        marked_at=second_decision + timedelta(hours=5),
        effective_session_date=next_spec.effective_session_date,
        accounting_as_of=next_spec.accounting_known_at,
    )
    assert state.cash == pytest.approx(100_130.0)


def test_daily_spec_snapshot_changes_vm_fee_gross_and_im_without_stale_fallback() -> None:
    """Dokazyvaet event-session multiplier/fee/IM i fail-closed missing daily row."""
    day_two = _spec(
        day=2,
        sizing_multiplier=9.0,
        accounting_multiplier=10.0,
        margin=100.0,
        fee=2.0,
    )
    day_three = _spec(
        day=3,
        sizing_multiplier=12.0,
        accounting_multiplier=20.0,
        margin=250.0,
        fee=5.0,
    )
    key = V8PositionKey(CORE_STRATEGY_ID, "daily-spec", "BR", "BRU5")
    state = V8EventLedgerState(
        strategy_id=CORE_STRATEGY_ID,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100_000.0,
        cash=100_000.0,
        positions=(V8LedgerPosition(key, 1, 100.0),),
    )
    state = settle_v8_event_ledger(
        state,
        (day_two,),
        {"BRU5": 110.0},
        marked_at=_decision(2) + timedelta(hours=5),
        effective_session_date=day_two.effective_session_date,
        accounting_as_of=day_two.accounting_known_at,
    )
    assert state.cash == pytest.approx(100_100.0)

    order = _binding(
        1,
        decision_at=_decision(3),
        sleeve_id="daily-spec",
        order_id="daily-spec-add",
    )
    bars = _execution_candles(
        "BRU5",
        _decision(3),
        execution_open=108.0,
        execution_high=108.0,
        execution_low=108.0,
    )
    trusted_index = _trusted_index(bars)
    evidence = plan_v8_scenario_execution(
        (order,), trusted_index, V8ScenarioId.PRIMARY
    )
    state = _pin_state(state, trusted_index)
    with pytest.raises(LookupError, match="exact contract/session"):
        apply_v8_execution_batch(
            state,
            (order,),
            evidence,
            (day_two,),
            trusted_candles=trusted_index,
            accounting_as_of=day_three.accounting_known_at,
        )

    state = apply_v8_execution_batch(
        state,
        (order,),
        evidence,
        (day_two, day_three),
        trusted_candles=trusted_index,
        accounting_as_of=day_three.accounting_known_at,
    )
    fill = state.fills[-1]
    stale_counterfactual_cash = 100_100.0 + (108.0 - 110.0) * 10.0 - 2.0
    assert fill.variation_margin == pytest.approx(-40.0)
    assert fill.fee == pytest.approx(5.0)
    assert fill.turnover_notional == pytest.approx(2_160.0)
    assert fill.spec_effective_session_date == day_three.effective_session_date
    assert fill.spec_snapshot_sha256 == day_three.snapshot_sha256
    assert state.cash == pytest.approx(100_055.0)
    assert state.cash != pytest.approx(stale_counterfactual_cash)

    state = settle_v8_event_ledger(
        state,
        (day_two, day_three),
        {"BRU5": 108.0},
        marked_at=_decision(3) + timedelta(hours=5),
        effective_session_date=day_three.effective_session_date,
        accounting_as_of=day_three.accounting_known_at,
    )
    assert state.equity_curve[-1].gross_notional == pytest.approx(4_320.0)
    assert state.equity_curve[-1].initial_margin == pytest.approx(500.0)
    with pytest.raises(LookupError, match="accounting byl neizvesten"):
        select_v8_contract_spec_snapshot(
            (day_three,),
            contract_id="BRU5",
            effective_session_date=day_three.effective_session_date,
            accounting_as_of=day_three.accounting_known_at - timedelta(seconds=1),
        )


def test_paired_roll_partial_fill_carries_old_and_books_both_legs() -> None:
    """Proveryaet equal-leg partial roll, old carry, dve fees i dve real'nye ceny."""
    old_spec = _spec(contract_id="BRU5", fee=1.0)
    new_spec = _spec(contract_id="BRZ5", fee=1.0)
    old_key = V8PositionKey(CORE_STRATEGY_ID, "old-sleeve", "BR", "BRU5")
    state = V8EventLedgerState(
        strategy_id=CORE_STRATEGY_ID,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100_000.0,
        cash=100_000.0,
        positions=(V8LedgerPosition(old_key, 4, 100.0),),
    )
    roll = build_v8_long_paired_roll_binding(
        old_position=state.positions[0],
        new_contract_id="BRZ5",
        new_sleeve_id="new-sleeve",
        decision_at=_decision(),
        effective_session_date=old_spec.effective_session_date,
        contracts=4,
    )
    old_bars = _execution_candles(
        "BRU5",
        _decision(),
        observed_volume=500,
        execution_volume=300,
        execution_open=100.0,
        execution_high=102.0,
        execution_low=99.0,
    )
    new_bars = _execution_candles(
        "BRZ5",
        _decision(),
        observed_volume=500,
        execution_volume=500,
        execution_open=100.0,
        execution_high=102.0,
        execution_low=98.0,
    )
    trusted_index = _trusted_index((*old_bars, *new_bars))
    evidence = plan_v8_scenario_execution(
        (roll,), trusted_index, V8ScenarioId.PRIMARY
    )
    state = _pin_state(state, trusted_index)
    state = apply_v8_execution_batch(
        state,
        (roll,),
        evidence,
        (old_spec, new_spec),
        trusted_candles=trusted_index,
        accounting_as_of=max(
            old_spec.accounting_known_at,
            new_spec.accounting_known_at,
        ),
    )

    by_contract = {item.key.contract_id: item for item in state.positions}
    assert evidence[0].executed_contracts == 3
    assert evidence[0].carry_contracts == 1
    assert by_contract["BRU5"].quantity == 1
    assert by_contract["BRZ5"].quantity == 3
    assert state.cash == pytest.approx(99_954.0)
    assert state.cumulative_fees == pytest.approx(6.0)
    assert len(state.unresolved_orders) == 1


@pytest.mark.parametrize(
    ("scenario_id", "executed", "carry", "old_price", "new_price"),
    (
        (V8ScenarioId.PRIMARY, -3, -1, 102.0, 98.0),
        (V8ScenarioId.DOUBLE_COST, -3, -1, 104.0, 96.0),
        (V8ScenarioId.DELAY, -2, -2, 103.0, 96.0),
    ),
)
def test_signed_short_paired_roll_is_compatible_with_all_fixed_scenarios(
    scenario_id: V8ScenarioId,
    executed: int,
    carry: int,
    old_price: float,
    new_price: float,
) -> None:
    """Fiksiruet signed short geometry v primary, double-cost i next-bar delay."""
    old_key = V8PositionKey(CORE_STRATEGY_ID, "old-short", "BR", "BRU5")
    old_position = V8LedgerPosition(old_key, -4, 100.0)
    roll = build_v8_signed_paired_roll_binding(
        old_position=old_position,
        new_contract_id="BRZ5",
        new_sleeve_id="new-short",
        decision_at=_decision(),
        effective_session_date=_spec().effective_session_date,
        signed_contracts=-4,
    )
    candles = (
        *_execution_candles(
            "BRU5",
            _decision(),
            observed_volume=500,
            execution_volume=300,
            delay_volume=200,
            execution_open=100.0,
            execution_high=102.0,
            execution_low=99.0,
            delay_open=100.0,
            delay_high=103.0,
            delay_low=97.0,
        ),
        *_execution_candles(
            "BRZ5",
            _decision(),
            observed_volume=500,
            execution_volume=500,
            delay_volume=500,
            execution_open=100.0,
            execution_high=102.0,
            execution_low=98.0,
            delay_open=100.0,
            delay_high=104.0,
            delay_low=96.0,
        ),
    )

    evidence = plan_v8_scenario_execution((roll,), candles, scenario_id)[0]

    assert roll.request.signed_contracts == -4
    assert evidence.requested_contracts == -4
    assert evidence.executed_contracts == executed
    assert evidence.carry_contracts == carry
    assert tuple(leg.signed_contracts for leg in evidence.legs) == (-executed, executed)
    assert tuple(leg.execution_price for leg in evidence.legs) == (old_price, new_price)
    assert evidence.base_execution.broker_atomicity_not_proven is True


def test_signed_short_roll_books_both_legs_vm_fees_gross_without_sign_inversion() -> None:
    """Auditit short roll: old buy/new sell, VM, dve fees, turnover i residual gross."""
    old_spec = _spec(contract_id="BRU5", fee=1.0)
    new_spec = _spec(contract_id="BRZ5", fee=1.0)
    old_key = V8PositionKey(CORE_STRATEGY_ID, "old-short", "BR", "BRU5")
    state = V8EventLedgerState(
        strategy_id=CORE_STRATEGY_ID,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100_000.0,
        cash=100_000.0,
        positions=(V8LedgerPosition(old_key, -4, 100.0),),
    )
    roll = build_v8_signed_paired_roll_binding(
        old_position=state.positions[0],
        new_contract_id="BRZ5",
        new_sleeve_id="new-short",
        decision_at=_decision(),
        effective_session_date=old_spec.effective_session_date,
        signed_contracts=-4,
    )
    candles = (
        *_execution_candles(
            "BRU5",
            _decision(),
            observed_volume=500,
            execution_volume=300,
            execution_open=100.0,
            execution_high=102.0,
            execution_low=99.0,
        ),
        *_execution_candles(
            "BRZ5",
            _decision(),
            observed_volume=500,
            execution_volume=500,
            execution_open=100.0,
            execution_high=102.0,
            execution_low=98.0,
        ),
    )
    trusted_index = _trusted_index(candles)
    evidence = plan_v8_scenario_execution(
        (roll,), trusted_index, V8ScenarioId.PRIMARY
    )
    state = _pin_state(state, trusted_index)

    state = apply_v8_execution_batch(
        state,
        (roll,),
        evidence,
        (old_spec, new_spec),
        trusted_candles=trusted_index,
        accounting_as_of=max(old_spec.accounting_known_at, new_spec.accounting_known_at),
    )

    by_contract = {item.key.contract_id: item for item in state.positions}
    assert by_contract["BRU5"].quantity == -1
    assert by_contract["BRZ5"].quantity == -3
    assert tuple(item.signed_contracts for item in state.fills) == (3, -3)
    assert state.cash == pytest.approx(99_914.0)
    assert state.cumulative_fees == pytest.approx(6.0)
    assert state.cumulative_turnover == pytest.approx(6_000.0)
    assert state.cumulative_adverse_slippage == pytest.approx(120.0)
    assert {item.consumed_contracts for item in state.capacity_consumption} == {3}
    assert state.unresolved_orders[0].carry_contracts == -1

    state = settle_v8_event_ledger(
        state,
        (old_spec, new_spec),
        {"BRU5": 100.0, "BRZ5": 100.0},
        marked_at=_decision() + timedelta(hours=5),
        effective_session_date=old_spec.effective_session_date,
        accounting_as_of=max(old_spec.accounting_known_at, new_spec.accounting_known_at),
    )
    assert state.cash == pytest.approx(99_874.0)
    assert state.equity_curve[-1].gross_notional == pytest.approx(4_000.0)
    assert state.equity_curve[-1].initial_margin == pytest.approx(400.0)


def test_signed_roll_rejects_direction_mismatch_and_absolute_overroll() -> None:
    """Sveriaet znak i modul q s factual old exposure do sozdaniya bindinga."""
    old_key = V8PositionKey(CORE_STRATEGY_ID, "old-short", "BR", "BRU5")
    old_position = V8LedgerPosition(old_key, -4, 100.0)
    common = {
        "old_position": old_position,
        "new_contract_id": "BRZ5",
        "new_sleeve_id": "new-short",
        "decision_at": _decision(),
        "effective_session_date": _spec().effective_session_date,
    }

    with pytest.raises(ValueError, match="direction"):
        build_v8_signed_paired_roll_binding(**common, signed_contracts=4)
    with pytest.raises(ValueError, match="absolute q"):
        build_v8_signed_paired_roll_binding(**common, signed_contracts=-5)
    with pytest.raises(ValueError, match="absolute q"):
        build_v8_signed_paired_roll_binding(**common, signed_contracts=-3)
    with pytest.raises(ValueError, match="zero exposure"):
        build_v8_signed_paired_roll_binding(**common, signed_contracts=0)


def test_signed_roll_ledger_rechecks_factual_positions_before_any_fill() -> None:
    """Ne doveryaet helperu: ledger povtorno blokiruet wrong sign/size i new inversion."""
    old_key = V8PositionKey(CORE_STRATEGY_ID, "old-short", "BR", "BRU5")
    declared_old = V8LedgerPosition(old_key, -2, 100.0)
    roll = build_v8_signed_paired_roll_binding(
        old_position=declared_old,
        new_contract_id="BRZ5",
        new_sleeve_id="new-short",
        decision_at=_decision(),
        effective_session_date=_spec().effective_session_date,
        signed_contracts=-2,
    )
    candles = (
        *_execution_candles("BRU5", _decision()),
        *_execution_candles("BRZ5", _decision()),
    )
    trusted_index = _trusted_index(candles)
    evidence = plan_v8_scenario_execution(
        (roll,), trusted_index, V8ScenarioId.PRIMARY
    )
    specs = (_spec(contract_id="BRU5"), _spec(contract_id="BRZ5"))
    accounting_as_of = max(item.accounting_known_at for item in specs)

    wrong_direction = V8EventLedgerState(
        strategy_id=CORE_STRATEGY_ID,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100_000.0,
        cash=100_000.0,
        positions=(V8LedgerPosition(old_key, 2, 100.0),),
    )
    wrong_direction = _pin_state(wrong_direction, trusted_index)
    with pytest.raises(ValueError, match="direction"):
        apply_v8_execution_batch(
            wrong_direction,
            (roll,),
            evidence,
            specs,
            trusted_candles=trusted_index,
            accounting_as_of=accounting_as_of,
        )

    insufficient = replace(
        wrong_direction,
        positions=(V8LedgerPosition(old_key, -1, 100.0),),
    )
    with pytest.raises(ValueError, match="absolute q"):
        apply_v8_execution_batch(
            insufficient,
            (roll,),
            evidence,
            specs,
            trusted_candles=trusted_index,
            accounting_as_of=accounting_as_of,
        )

    assert roll.new_roll_position is not None
    opposite_new = replace(
        wrong_direction,
        positions=(declared_old, V8LedgerPosition(roll.new_roll_position, 1, 100.0)),
    )
    with pytest.raises(ValueError, match="invertirovat"):
        apply_v8_execution_batch(
            opposite_new,
            (roll,),
            evidence,
            specs,
            trusted_candles=trusted_index,
            accounting_as_of=accounting_as_of,
        )


def test_post_fill_gross_and_initial_margin_are_fail_closed() -> None:
    """Ne clipping'uet order zadnim chislom pri gross breach."""
    spec = _spec(multiplier=100.0, margin=100.0, fee=0.0)
    binding = _binding(1)
    trusted_candles = _trusted_index(_execution_candles("BRU5", _decision()))
    evidence = plan_v8_scenario_execution(
        (binding,),
        trusted_candles,
        V8ScenarioId.PRIMARY,
    )
    state = V8EventLedgerState.create(
        CORE_STRATEGY_ID,
        V8ScenarioId.PRIMARY,
        1_000.0,
        trusted_candles=trusted_candles,
    )

    with pytest.raises(V8LedgerRiskError, match="gross"):
        apply_v8_execution_batch(
            state,
            (binding,),
            evidence,
            (spec,),
            trusted_candles=trusted_candles,
            accounting_as_of=spec.accounting_known_at,
        )


def test_integer_sizing_truncates_toward_zero_and_never_creates_fraction() -> None:
    """Fiksiruet integer owner ledger i simmetrichnoe rounding long/short."""
    spec = _spec(multiplier=10.0)
    assert integer_contracts_for_weight(0.25, 10_000.0, 100.0, spec) == 2
    assert integer_contracts_for_weight(-0.25, 10_000.0, 100.0, spec) == -2
    assert integer_contracts_for_weight(0.01, 10_000.0, 200.0, spec) == 0


def test_breakout_partial_execution_is_reconciled_as_unresolved_without_level_advance() -> None:
    """Svya zyvaet breakout state tol'ko s actual primary execution.py evidence."""
    prediction = _prediction()
    decision_set = build_v8_strategy_decision_set(prediction)
    run = next(
        item
        for item in decision_set.aggressive_runs
        if item.decision.candidate_id is AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP
    )
    assert run.breakout_intents
    bindings: list[V8OrderBinding] = []
    candles: list[TenMinuteCandle] = []
    for priority, intent in enumerate(run.breakout_intents):
        contract_id = f"{intent.asset_id}U5"
        direction = intent.desired_direction or -intent.prior_direction
        key = V8PositionKey(
            run.decision.candidate_id.value, "breakout-sleeve", intent.asset_id, contract_id
        )
        bindings.append(
            V8OrderBinding(
                request=PredeclaredMarketOrder(
                    f"breakout-{intent.asset_id}",
                    contract_id,
                    prediction.context.decision_at,
                    direction * 2,
                    priority,
                ),
                cause=V8OrderCause.BREAKOUT_TRANSITION,
                effective_session_date=(prediction.contracts[0].entry_effective_session_date),
                single_position=key,
            )
        )
        candles.extend(
            _execution_candles(
                contract_id,
                prediction.context.decision_at,
                observed_volume=100,
                execution_volume=100,
                delay_volume=100,
            )
        )
    primary = plan_v8_scenario_execution(bindings, candles, V8ScenarioId.PRIMARY)
    schedule = HoldingSleeveSchedule(
        sleeve_id="breakout-sleeve",
        calendar_sha256=CALENDAR_SHA,
        entry_common_session_sequence_id=10,
        exit_common_session_sequence_id=15,
        entry_window_closed_at=prediction.context.decision_at + timedelta(minutes=40),
        exit_window_closed_at=prediction.context.decision_at + timedelta(days=7, minutes=40),
    )
    scheduled = tuple(
        candidate_execution_evidence_from_primary(
            item,
            binding=binding,
            candidate_run=run,
            schedule=schedule,
            execution_bar_sequence_id=100 + index,
        )
        for index, (binding, item) in enumerate(zip(bindings, primary, strict=True))
    )
    next_state = reconcile_v8_breakout_execution(run, scheduled)

    assert {item.effective_session_date for item in scheduled} == {
        prediction.contracts[0].entry_effective_session_date
    }
    assert not next_state.assets
    assert set(next_state.unresolved_asset_ids) == {item.asset_id for item in run.breakout_intents}
    assert all(item.evidence.carry_contracts for item in scheduled)


def test_corridor_partial_actual_exit_updates_vm_and_stays_unresolved() -> None:
    """Ne zakryvaet ostatok corridor bez capacity evidence i ne sozdaet synthetic fill."""
    base = _prediction().context
    assets = tuple(
        replace(
            item,
            residual_decision_score=0.4,
            residual_location=0.4,
            range_position_20=0.1,
        )
        if item.asset_id == "RI"
        else item
        for item in base.assets
    )
    context = CausalDecisionContext(base.decision_at, assets, base.prediction_sha256)
    run = run_aggressive_candidate(AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST, context)
    asset = next(item for item in context.assets if item.asset_id == "RI")
    schedule = HoldingSleeveSchedule(
        sleeve_id="corridor-sleeve",
        calendar_sha256=CALENDAR_SHA,
        entry_common_session_sequence_id=10,
        exit_common_session_sequence_id=15,
        entry_window_closed_at=context.decision_at + timedelta(minutes=40),
        exit_window_closed_at=context.decision_at + timedelta(days=7, minutes=40),
    )
    entry = CandidateExecutionEvidence(
        candidate_id=AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        decision_at=context.decision_at,
        prediction_sha256=context.prediction_sha256,
        input_bundle_sha256=context.input_bundle_sha256,
        sleeve_id=schedule.sleeve_id,
        asset_id="RI",
        contract_id="RIU5",
        order_id="corridor-entry",
        common_session_sequence_id=10,
        execution_bar_sequence_id=100,
        requested_contracts=2,
        executed_contracts=2,
        carry_contracts=0,
        observed_capacity_contracts=10,
        realized_capacity_contracts=10,
        execution_window_closed_at=schedule.entry_window_closed_at,
        execution_price=100.0,
        execution_evidence_sha256="f" * 64,
    )
    position = open_volatility_corridor_position(
        asset,
        decision=run.decision,
        execution=ScheduledCandidateExecution(schedule, entry),
    )
    trigger_bar = FactualTenMinuteBar(
        asset_id="RI",
        contract_id="RIU5",
        bar_sequence_id=101,
        common_session_sequence_id=10,
        opened_at=position.last_bar_closed_at,
        closed_at=position.last_bar_closed_at + timedelta(minutes=10),
        open_price=93.0,
        high_price=102.0,
        low_price=92.0,
        close_price=99.0,
        volume=100,
    )
    transition = transition_volatility_corridor(position, trigger_bar)
    assert transition.exit_intent is not None
    intent = transition.exit_intent
    exit_evidence = CandidateExitExecutionEvidence(
        intent_id=intent.intent_id,
        order_id="corridor-exit",
        asset_id="RI",
        contract_id="RIU5",
        sleeve_id=schedule.sleeve_id,
        execution_bar_sequence_id=intent.trigger_bar_sequence_id,
        requested_contracts=-2,
        executed_contracts=-1,
        carry_contracts=-1,
        execution_price=intent.conservative_reference_price,
        factual_bar_volume=100,
        execution_evidence_sha256="1" * 64,
    )
    key = V8PositionKey(
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST.value,
        schedule.sleeve_id,
        "RI",
        "RIU5",
    )
    state = V8EventLedgerState(
        strategy_id=AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST.value,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100_000.0,
        cash=100_000.0,
        positions=(V8LedgerPosition(key, 2, 100.0),),
    )
    corridor_spec = _spec("RI", "RIU5")
    with pytest.raises(ValueError, match="stress transition"):
        apply_v8_corridor_exit_to_ledger(
            replace(state, scenario_id=V8ScenarioId.DOUBLE_COST),
            position_key=key,
            corridor_position=transition.position,
            intent=intent,
            evidence=exit_evidence,
            specs=(corridor_spec,),
            effective_session_date=corridor_spec.effective_session_date,
            accounting_as_of=corridor_spec.accounting_known_at,
        )
    next_state, next_position = apply_v8_corridor_exit_to_ledger(
        state,
        position_key=key,
        corridor_position=transition.position,
        intent=intent,
        evidence=exit_evidence,
        specs=(corridor_spec,),
        effective_session_date=corridor_spec.effective_session_date,
        accounting_as_of=corridor_spec.accounting_known_at,
    )

    assert next_position.status is CorridorPositionStatus.CARRY_UNRESOLVED
    assert next_position.open_contracts == 1
    assert next_state.positions[0].quantity == 1
    assert next_state.positions[0].reference_price == pytest.approx(93.0)
    assert next_state.cash == pytest.approx(99_858.0)
    assert len(next_state.unresolved_orders) == 1


def _scenario_metrics(scenario_id: V8ScenarioId, sharpe: float) -> V8ScenarioMetrics:
    """Stroit passing fixed-gate metric fixture s pyat'yu polozhitel'nymi godami."""
    return V8ScenarioMetrics(
        scenario_id=scenario_id,
        net_cagr=0.12 if scenario_id is not V8ScenarioId.DOUBLE_COST else 0.04,
        sharpe=sharpe,
        max_drawdown=0.10,
        yearly=tuple(V8YearMetric(year, 0.10, sharpe) for year in range(2021, 2026)),
        critical_execution_failure_count=0,
        maximum_participation_bps=100.0,
        unknown_capacity_count=0,
        unresolved_positions_at_terminal=0,
        cumulative_fees=100.0,
        cumulative_turnover=10_000.0,
    )


def test_scenario_summary_uses_net_equity_drawdown_and_exact_calendar_years() -> None:
    """Proveryaet CAGR formula, 10-percent drawdown i yearly net compounding."""
    values = (100.0, 110.0, 99.0, 108.9, 119.79, 131.769)
    points = tuple(
        V8EquityPoint(
            marked_at=datetime(year, 12, 30, tzinfo=UTC),
            cash=value,
            equity=value,
            gross_notional=0.0,
            initial_margin=0.0,
        )
        for year, value in zip(range(2020, 2026), values, strict=True)
    )
    state = V8EventLedgerState(
        strategy_id=CORE_STRATEGY_ID,
        scenario_id=V8ScenarioId.PRIMARY,
        initial_cash=100.0,
        cash=values[-1],
        equity_curve=points,
    )

    metrics = summarize_v8_scenario(state, ())

    assert metrics.net_cagr == pytest.approx((values[-1] / values[0]) ** (252 / 5) - 1)
    assert metrics.max_drawdown == pytest.approx(0.10)
    assert tuple(item.net_return for item in metrics.yearly) == pytest.approx(
        (0.10, -0.10, 0.10, 0.10, 0.10)
    )
    assert metrics.unresolved_positions_at_terminal == 0


def test_fixed_gate_ranking_uses_exact_eleven_same_prediction_bundles() -> None:
    """Rank'uet passing aggressive po sealed median Sharpe i ne vybirayet scenario."""
    strategy_ids = (CORE_STRATEGY_ID, *AGGRESSIVE_CANDIDATE_IDS)
    bundles = tuple(
        V8StrategyMetricsBundle(
            strategy_id=strategy_id,
            prediction_sha256=PREDICTION_SHA,
            evaluation_bundle_sha256=EVALUATION_SHA,
            scenarios=tuple(
                _scenario_metrics(scenario.scenario_id, 0.6 + index / 10.0)
                for scenario in fixed_v8_scenarios()
            ),
        )
        for index, strategy_id in enumerate(strategy_ids)
    )
    result = build_v8_gate_and_ranking(bundles)

    assert len(result.outcomes) == 11
    assert all(item.passed for item in result.outcomes)
    assert result.aggressive_ranking[0].candidate_id.value == AGGRESSIVE_CANDIDATE_IDS[-1]
    with pytest.raises(ValueError, match=r"core \+ exact 10"):
        build_v8_gate_and_ranking(bundles[:-1])


def test_terminal_partial_carry_forces_no_go_without_retry_resolution() -> None:
    """Dokazyvaet, chto unresolved carry ne ischezaet iz hard terminal gate."""
    bundles: list[V8StrategyMetricsBundle] = []
    for strategy_id in (CORE_STRATEGY_ID, *AGGRESSIVE_CANDIDATE_IDS):
        scenarios = []
        for scenario in fixed_v8_scenarios():
            metrics = _scenario_metrics(scenario.scenario_id, 0.8)
            if strategy_id == CORE_STRATEGY_ID and scenario.scenario_id is V8ScenarioId.PRIMARY:
                metrics = replace(
                    metrics,
                    critical_execution_failure_count=1,
                    unresolved_positions_at_terminal=1,
                )
            scenarios.append(metrics)
        bundles.append(
            V8StrategyMetricsBundle(
                strategy_id=strategy_id,
                prediction_sha256=PREDICTION_SHA,
                evaluation_bundle_sha256=EVALUATION_SHA,
                scenarios=tuple(scenarios),
            )
        )

    outcome = build_v8_gate_and_ranking(tuple(bundles)).outcomes[0]
    checks = dict(outcome.checks)
    assert outcome.passed is False
    assert checks["critical_execution"] is False
    assert checks["terminal_resolution"] is False
