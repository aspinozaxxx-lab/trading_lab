"""Target-free evaluator i event-ledger dlya development protokola futures-v8."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import Enum, StrEnum
from hashlib import sha256
from math import floor, isfinite, sqrt
from typing import Any, Final
from zoneinfo import ZoneInfo

from market_lab.futures_v8.aggressive_strategies import (
    AGGRESSIVE_CANDIDATE_IDS,
    BASE_PROTOCOL_SHA256,
    DEVELOPMENT_YEARS,
    MAXIMUM_PARTICIPATION_BPS,
    MINIMUM_POSITIVE_YEARS,
    PRIMARY_MAX_DRAWDOWN_MAXIMUM,
    PRIMARY_NET_CAGR_MINIMUM,
    PRIMARY_SHARPE_MINIMUM,
    REPORT_ONLY_STRETCH_CAGR,
    V8_ASSET_IDS,
    WORST_CALENDAR_YEAR_RETURN_MINIMUM,
    AggressiveCandidateId,
    BreakoutPyramidState,
    CandidateAnnualMetric,
    CandidateExecutionEvidence,
    CandidateExitExecutionEvidence,
    CandidateGateMetric,
    CandidateRun,
    CandidateSelectionRecord,
    CausalDecisionContext,
    CorridorExitIntent,
    CorridorPosition,
    HoldingSleeveSchedule,
    ScheduledCandidateExecution,
    apply_breakout_execution,
    apply_volatility_corridor_exit,
    rank_gate_passing_candidates,
    run_aggressive_candidate,
)
from market_lab.futures_v8.execution import (
    BASIS_POINTS,
    CAPACITY_BPS,
    RESEARCH_ONLY_NOT_QUEUE_EXACT,
    ExecutionLeg,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    OrderExecution,
    PredeclaredMarketOrder,
    PredeclaredPairedMarketRollOrder,
    RollExecution,
    TenMinuteCandle,
    plan_causal_v8_execution,
)
from market_lab.futures_v8.portfolio import (
    HOLDING_SLEEVE_COUNT,
    SLEEVE_WEIGHT,
    AssetDecisionInput,
    DecisionModelSnapshot,
    PortfolioDecision,
    build_v8_portfolio_path,
)

# Kanonicheskii ID osnovnoi factor/residual strategii, ne vhodyashchei v desyat' kandidatov.
CORE_STRATEGY_ID: Final[str] = "core_v8_factor_residual"
# Exact chislo vseh sravnivaemyh strategii: odna core i desyat' aggressive.
TOTAL_STRATEGY_COUNT: Final[int] = 1 + len(AGGRESSIVE_CANDIDATE_IDS)
# Kanonicheskii poryadok strategy rows vo vseh scenario matrices.
V8_STRATEGY_IDS: Final[tuple[str, ...]] = (CORE_STRATEGY_ID, *AGGRESSIVE_CANDIDATE_IDS)
# Byte-seal otdel'nogo kataloga desyati aggressive strategii.
AGGRESSIVE_CATALOG_SHA256: Final[str] = (
    "52d08ac8727eaa08342d2430158b18b19f2d5bdb4271a929f16fb02d032b7a62"
)
# Nachalo zashchishchennogo holdout, kotoryi evaluator foundation ne prinimaet.
PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)
# Birzhevaya timezone dlya calendar holdout, a ne proizvol'nogo UTC date.
MOSCOW_TIMEZONE: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
# Zhestkii gross limit bez plecha dlya kazhdogo izolirovannogo portfolio.
MAX_GROSS_EXPOSURE: Final[float] = 1.0
# Chislo bazisnyh punktov v odnoi edinice dlya cost audit.
BPS_DENOMINATOR: Final[int] = 10_000
# Godovaya normalizaciya dnevnyh development returns.
TRADING_SESSIONS_PER_YEAR: Final[int] = 252
# Malen'kii dopusk tol'ko dlya floating-point invariantov.
FLOAT_TOLERANCE: Final[float] = 1e-10
# Edinstvennyi dopustimyi causal lag sizing spec v factual contract sessions.
SPEC_SIZING_LAG_SESSIONS: Final[int] = 1
# Exact upstream status, podtverzhdayushchii prigodnost' lag-1 sizing snapshot.
SPEC_SIZING_STATUS: Final[str] = "available_lag_1_session"
# Razreshennye upstream statusy current-session accounting tol'ko posle session.
SPEC_ACCOUNTING_STATUSES: Final[tuple[str, ...]] = (
    "available_primary_after_session",
    "available_fallback_after_session",
)
# Exact provenance tekushchego stateful -> common-ledger bridge.
STATEFUL_REPLAY_PROVENANCE: Final[str] = "stateful_factual_bridge_v1"
# Exact poryadok hard gate proverok bez dobavleniya stretch celi v selection.
V8_GATE_CHECK_IDS: Final[tuple[str, ...]] = (
    "primary_net_cagr",
    "primary_sharpe",
    "primary_max_drawdown",
    "positive_year_count",
    "worst_calendar_year",
    "doubled_cost_cagr",
    "critical_execution",
    "participation",
    "known_capacity",
    "terminal_resolution",
)


class V8ScenarioId(StrEnum):
    """Tri zapechatannyh scenariya bez runtime selection ili tuning."""

    PRIMARY = "primary"
    DOUBLE_COST = "double_cost"
    DELAY = "delay"


@dataclass(frozen=True, slots=True)
class V8ScenarioSpec:
    """Fiksiruet fee, adverse excursion i exact delay odnogo scenariya."""

    scenario_id: V8ScenarioId
    fee_multiplier: float
    adverse_excursion_multiplier: float
    delay_bars: int

    def __post_init__(self) -> None:
        """Zapreshchaet proizvol'nye scenarii i numeric drift."""
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        if not isfinite(self.fee_multiplier) or self.fee_multiplier <= 0.0:
            raise ValueError("fee_multiplier dolzhen byt' finite i > 0")
        if (
            not isfinite(self.adverse_excursion_multiplier)
            or self.adverse_excursion_multiplier <= 0.0
        ):
            raise ValueError("adverse_excursion_multiplier dolzhen byt' finite i > 0")
        if isinstance(self.delay_bars, bool) or not isinstance(self.delay_bars, int):
            raise TypeError("delay_bars dolzhen byt' int")
        expected = {
            scenario_id: (fee, excursion, delay)
            for scenario_id, fee, excursion, delay in _FIXED_SCENARIO_ROWS
        }.get(self.scenario_id)
        if (
            expected is None
            or (
                self.fee_multiplier,
                self.adverse_excursion_multiplier,
                self.delay_bars,
            )
            != expected
        ):
            raise ValueError("V8 scenario spec otklonilsya ot fixed protocol")


# Raw fixed scenarii zadany do sozdaniya public V8ScenarioSpec validation registry.
_FIXED_SCENARIO_ROWS: Final[tuple[tuple[V8ScenarioId, float, float, int], ...]] = (
    (V8ScenarioId.PRIMARY, 1.0, 1.0, 0),
    (V8ScenarioId.DOUBLE_COST, 2.0, 2.0, 0),
    (V8ScenarioId.DELAY, 1.0, 1.0, 1),
)


def fixed_v8_scenarios() -> tuple[V8ScenarioSpec, ...]:
    """Vozvrashchaet exact primary, doubled-cost i next-complete-bar delay."""
    return tuple(V8ScenarioSpec(*row) for row in _FIXED_SCENARIO_ROWS)


def _require_sha256(value: str, label: str) -> str:
    """Normalizuet lowercase SHA-256 i fail-closed ot nevalidnoi stroki."""
    if not isinstance(value, str):
        raise TypeError(f"{label} dolzhen byt' strokoj")
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} dolzhen byt' SHA-256")
    return normalized


def _require_identifier(value: str, label: str) -> str:
    """Trebuet nepustoi stable identifier bez kraevyh probelov."""
    if not isinstance(value, str):
        raise TypeError(f"{label} dolzhen byt' strokoj")
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise ValueError(f"{label} dolzhen byt' nepustym i bez probelov")
    return value


def _require_aware(value: datetime, label: str) -> datetime:
    """Trebuet timezone-aware timestamp i normalizuet ego k UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} dolzhen byt' timezone-aware datetime")
    return value.astimezone(UTC)


def _require_session_date(value: date, label: str) -> date:
    """Trebuet explicit factual session date bez vyvoda iz wall-clock timestamp."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{label} dolzhen byt' date")
    if value >= PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} popal v 2026 holdout")
    return value


def _decision_trade_date(decision_at: datetime) -> date:
    """Vozvrashchaet lokal'nyi trade date D tol'ko dlya proverki lag-1 identity."""
    return _require_aware(decision_at, "decision_at").astimezone(MOSCOW_TIMEZONE).date()


def _require_finite_positive(value: float, label: str) -> float:
    """Trebuet finite polozhitel'noe chislo bez bool masquerade."""
    if isinstance(value, bool):
        raise TypeError(f"{label} ne mozhet byt' bool")
    numeric = float(value)
    if not isfinite(numeric) or numeric <= 0.0:
        raise ValueError(f"{label} dolzhen byt' finite i > 0")
    return numeric


def _canonical_value(value: Any) -> Any:
    """Prevrashchaet typed evidence v stable JSON-safe hash payload."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("canonical hash ne prinimaet NaN/Inf")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Nepodderzhivaemyi canonical tip: {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    """Schitaet stable SHA-256 canonical JSON bez target/return derivation."""
    payload = json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class V8ContractSpec:
    """Exact contract/session snapshot s razdelennymi sizing i accounting polyami."""

    asset_id: str
    contract_id: str
    effective_session_date: date
    sizing_observed_session_date: date
    sizing_known_at: datetime
    accounting_known_at: datetime
    sizing_price_multiplier: float
    accounting_price_multiplier: float
    initial_margin_per_contract: float
    fee_per_contract: float
    source_sha256: str
    sizing_lag_sessions: int = SPEC_SIZING_LAG_SESSIONS
    sizing_status: str = SPEC_SIZING_STATUS
    accounting_status: str = SPEC_ACCOUNTING_STATUSES[0]
    snapshot_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Proveryaet exact session, lag-1 provenance i razdelennye multipliers."""
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("contract spec asset vne sealed BR/MIX/RI/SI universe")
        object.__setattr__(
            self, "contract_id", _require_identifier(self.contract_id, "contract_id")
        )
        if isinstance(self.effective_session_date, datetime) or not isinstance(
            self.effective_session_date, date
        ):
            raise TypeError("effective_session_date dolzhen byt' date")
        if self.effective_session_date >= PROTECTED_HOLDOUT_START:
            raise ValueError("contract spec iz 2026 holdout zapreshchen")
        if isinstance(self.sizing_observed_session_date, datetime) or not isinstance(
            self.sizing_observed_session_date, date
        ):
            raise TypeError("sizing_observed_session_date dolzhen byt' date")
        if self.sizing_observed_session_date >= self.effective_session_date:
            raise ValueError("sizing spec dolzhen byt' iz proshloi factual session")
        sizing_known = _require_aware(self.sizing_known_at, "sizing_known_at")
        accounting_known = _require_aware(self.accounting_known_at, "accounting_known_at")
        if accounting_known.astimezone(MOSCOW_TIMEZONE).date() < self.effective_session_date:
            raise ValueError("current accounting ne mozhet byt' izvesten do effective session")
        if sizing_known >= accounting_known:
            raise ValueError("lag-1 sizing dolzhen byt' izvesten ran'she current accounting")
        if self.sizing_lag_sessions != SPEC_SIZING_LAG_SESSIONS:
            raise ValueError("contract spec sizing lag dolzhen byt' rovno odnu session")
        if self.sizing_status != SPEC_SIZING_STATUS:
            raise ValueError("contract spec sizing status ne podtverzhdaet lag-1")
        if self.accounting_status not in SPEC_ACCOUNTING_STATUSES:
            raise ValueError("contract spec accounting status unknown/unavailable")
        object.__setattr__(self, "sizing_known_at", sizing_known)
        object.__setattr__(self, "accounting_known_at", accounting_known)
        object.__setattr__(
            self,
            "sizing_price_multiplier",
            _require_finite_positive(
                self.sizing_price_multiplier,
                "sizing_price_multiplier",
            ),
        )
        object.__setattr__(
            self,
            "accounting_price_multiplier",
            _require_finite_positive(
                self.accounting_price_multiplier,
                "accounting_price_multiplier",
            ),
        )
        object.__setattr__(
            self,
            "initial_margin_per_contract",
            _require_finite_positive(
                self.initial_margin_per_contract,
                "initial_margin_per_contract",
            ),
        )
        if isinstance(self.fee_per_contract, bool):
            raise TypeError("fee_per_contract ne mozhet byt' bool")
        fee = float(self.fee_per_contract)
        if not isfinite(fee) or fee < 0.0:
            raise ValueError("fee_per_contract dolzhen byt' finite i >= 0")
        object.__setattr__(self, "fee_per_contract", fee)
        object.__setattr__(
            self,
            "source_sha256",
            _require_sha256(self.source_sha256, "source_sha256"),
        )
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "snapshot_sha256"
        }
        object.__setattr__(self, "snapshot_sha256", canonical_sha256(payload))


@dataclass(frozen=True, slots=True)
class V8AssetContractSnapshot:
    """D-known current contract i eligibility dlya odnogo model asseta."""

    asset_id: str
    contract_id: str
    entry_effective_session_date: date
    known_at: datetime
    asset_mask: bool
    nominal_span_eligible: bool
    source_sha256: str

    def __post_init__(self) -> None:
        """Svyazyvaet contract s sealed universe i D-known momentom."""
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("asset contract snapshot vne sealed universe")
        object.__setattr__(
            self, "contract_id", _require_identifier(self.contract_id, "contract_id")
        )
        if isinstance(self.entry_effective_session_date, datetime) or not isinstance(
            self.entry_effective_session_date, date
        ):
            raise TypeError("entry_effective_session_date dolzhen byt' date")
        if self.entry_effective_session_date >= PROTECTED_HOLDOUT_START:
            raise ValueError("entry effective session popala v 2026 holdout")
        known_at = _require_aware(self.known_at, "known_at")
        if self.entry_effective_session_date <= known_at.astimezone(MOSCOW_TIMEZONE).date():
            raise ValueError("entry effective session dolzhna byt' posle D-known contract snapshot")
        object.__setattr__(self, "known_at", known_at)
        if not isinstance(self.asset_mask, bool) or not isinstance(
            self.nominal_span_eligible, bool
        ):
            raise TypeError("asset_mask i nominal_span_eligible dolzhny byt' bool")
        object.__setattr__(
            self,
            "source_sha256",
            _require_sha256(self.source_sha256, "source_sha256"),
        )


@dataclass(frozen=True, slots=True)
class V8TargetFreePrediction:
    """Edinyi target-free prediction record dlya core i vseh desyati kandidatov."""

    context: CausalDecisionContext
    factor_location: float
    factor_scale: float
    contracts: tuple[V8AssetContractSnapshot, ...]
    record_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Dokazyvaet same-time contract/model identity bez labels ili returns."""
        if not isinstance(self.context, CausalDecisionContext):
            raise TypeError("context dolzhen byt' CausalDecisionContext")
        factor_location = float(self.factor_location)
        factor_scale = _require_finite_positive(self.factor_scale, "factor_scale")
        if not isfinite(factor_location):
            raise ValueError("factor_location dolzhen byt' finite")
        contracts = tuple(sorted(self.contracts, key=lambda item: item.asset_id))
        if any(not isinstance(item, V8AssetContractSnapshot) for item in contracts):
            raise TypeError("contracts dolzhny soderzhat' V8AssetContractSnapshot")
        if tuple(item.asset_id for item in contracts) != V8_ASSET_IDS:
            raise ValueError("prediction trebuet exact BR/MIX/RI/SI contracts")
        for item in contracts:
            if item.known_at > self.context.decision_at:
                raise ValueError("future contract snapshot posle prediction decision zapreshchen")
        decision_trade_date = self.context.decision_at.astimezone(MOSCOW_TIMEZONE).date()
        effective_dates = {item.entry_effective_session_date for item in contracts}
        if len(effective_dates) != 1 or next(iter(effective_dates)) <= decision_trade_date:
            raise ValueError("prediction trebuet edinuju next factual entry effective session")
        factor_scores = {asset.factor_decision_score for asset in self.context.assets}
        if len(factor_scores) != 1:
            raise ValueError("factor_decision_score dolzhen byt' edinym cross-asset output")
        object.__setattr__(self, "factor_location", factor_location)
        object.__setattr__(self, "factor_scale", factor_scale)
        object.__setattr__(self, "contracts", contracts)
        payload = {
            "context": self.context,
            "factor_location": factor_location,
            "factor_scale": factor_scale,
            "contracts": contracts,
        }
        object.__setattr__(self, "record_sha256", canonical_sha256(payload))

    def core_snapshot(self) -> DecisionModelSnapshot:
        """Stroit core snapshot iz togo zhe prediction record bez novogo signala."""
        contract_by_asset = {item.asset_id: item for item in self.contracts}
        factor_score = self.context.assets[0].factor_decision_score
        assets = tuple(
            AssetDecisionInput(
                asset=asset.asset_id,
                contract_id=contract_by_asset[asset.asset_id].contract_id,
                residual_decision_score=asset.residual_decision_score,
                total_scale=asset.total_scale,
                ex_ante_daily_vol20=asset.daily_volatility_20,
                asset_mask=contract_by_asset[asset.asset_id].asset_mask,
                nominal_span_eligible=contract_by_asset[asset.asset_id].nominal_span_eligible,
            )
            for asset in self.context.assets
        )
        return DecisionModelSnapshot(
            decision_at=self.context.decision_at,
            factor_location=self.factor_location,
            factor_scale=self.factor_scale,
            factor_decision_score=factor_score,
            assets=assets,
        )


@dataclass(frozen=True, slots=True)
class V8SealedEvaluationInputBundle:
    """Odna immutable granica predictions, specs i factual 10m evidence."""

    predictions: tuple[V8TargetFreePrediction, ...]
    contract_specs: tuple[V8ContractSpec, ...]
    candles: tuple[TenMinuteCandle, ...]
    market_data_sha256: str
    calendar_sha256: str
    protocol_sha256: str = BASE_PROTOCOL_SHA256
    catalog_sha256: str = AGGRESSIVE_CATALOG_SHA256
    evaluation_bundle_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Fail-closed proverka holdout, chronology, duplicate i seal identity."""
        predictions = tuple(self.predictions)
        if not predictions or any(
            not isinstance(item, V8TargetFreePrediction) for item in predictions
        ):
            raise ValueError("evaluation bundle trebuet target-free predictions")
        if any(
            right.context.decision_at <= left.context.decision_at
            for left, right in zip(predictions, predictions[1:], strict=False)
        ):
            raise ValueError("predictions dolzhny byt' strogo chronologichny")
        prediction_hashes = {item.context.prediction_sha256 for item in predictions}
        if len(prediction_hashes) != 1:
            raise ValueError("vse resheniya dolzhny nasledovat' odin prediction SHA")
        specs = tuple(
            sorted(
                self.contract_specs,
                key=lambda item: (item.contract_id, item.effective_session_date),
            )
        )
        if any(not isinstance(item, V8ContractSpec) for item in specs):
            raise TypeError("contract_specs dolzhny soderzhat' V8ContractSpec")
        spec_keys = {(item.contract_id, item.effective_session_date) for item in specs}
        if len(spec_keys) != len(specs):
            raise ValueError("contract_specs soderzhat duplicate contract/session")
        spec_ids = {item.contract_id for item in specs}
        used_contract_ids = {
            item.contract_id for prediction in predictions for item in prediction.contracts
        }
        if not used_contract_ids.issubset(spec_ids):
            raise ValueError("prediction contract ne imeet point-in-time spec")
        candles = tuple(sorted(self.candles, key=lambda item: (item.opened_at, item.contract_id)))
        if any(not isinstance(item, TenMinuteCandle) for item in candles):
            raise TypeError("candles dolzhny soderzhat' TenMinuteCandle")
        candle_keys = {(item.contract_id, item.opened_at) for item in candles}
        if len(candle_keys) != len(candles):
            raise ValueError("evaluation candles soderzhat duplicate contract/timestamp")
        if any(
            item.opened_at.astimezone(MOSCOW_TIMEZONE).date() >= PROTECTED_HOLDOUT_START
            or item.closed_at.astimezone(MOSCOW_TIMEZONE).date() >= PROTECTED_HOLDOUT_START
            for item in candles
        ):
            raise ValueError("evaluation bundle ne mozhet chitat' 2026 candles")
        market_hash = _require_sha256(self.market_data_sha256, "market_data_sha256")
        calendar_hash = _require_sha256(self.calendar_sha256, "calendar_sha256")
        protocol_hash = _require_sha256(self.protocol_sha256, "protocol_sha256")
        catalog_hash = _require_sha256(self.catalog_sha256, "catalog_sha256")
        if protocol_hash != BASE_PROTOCOL_SHA256:
            raise ValueError("evaluation protocol SHA ne sootvetstvuet aggressive seal")
        if catalog_hash != AGGRESSIVE_CATALOG_SHA256:
            raise ValueError("aggressive catalog SHA drift")
        spec_by_key = {(item.contract_id, item.effective_session_date): item for item in specs}
        for prediction in predictions:
            decision_trade_date = prediction.context.decision_at.astimezone(MOSCOW_TIMEZONE).date()
            for contract in prediction.contracts:
                spec = spec_by_key.get(
                    (contract.contract_id, contract.entry_effective_session_date)
                )
                if (
                    spec is None
                    or spec.effective_session_date != contract.entry_effective_session_date
                    or spec.sizing_observed_session_date != decision_trade_date
                    or spec.asset_id != contract.asset_id
                    or spec.sizing_known_at > prediction.context.decision_at
                ):
                    raise ValueError(
                        "exact contract/session sizing spec ne byl D-known ili asset mismatch"
                    )
        object.__setattr__(self, "predictions", predictions)
        object.__setattr__(self, "contract_specs", specs)
        object.__setattr__(self, "candles", candles)
        object.__setattr__(self, "market_data_sha256", market_hash)
        object.__setattr__(self, "calendar_sha256", calendar_hash)
        object.__setattr__(self, "protocol_sha256", protocol_hash)
        object.__setattr__(self, "catalog_sha256", catalog_hash)
        payload = {
            "prediction_records": tuple(item.record_sha256 for item in predictions),
            "prediction_sha256": next(iter(prediction_hashes)),
            "contract_specs": specs,
            "candles": candles,
            "market_data_sha256": market_hash,
            "calendar_sha256": calendar_hash,
            "protocol_sha256": protocol_hash,
            "catalog_sha256": catalog_hash,
        }
        object.__setattr__(self, "evaluation_bundle_sha256", canonical_sha256(payload))

    @property
    def prediction_sha256(self) -> str:
        """Vozvrashchaet obshchii seal target-free OOS predictions."""
        return self.predictions[0].context.prediction_sha256


class V8CandleTrustStatus(StrEnum):
    """Razdelyaet verified production capability i tests-only synthetic index."""

    AUTHORITATIVE = "authoritative_verified_source"
    SYNTHETIC_TEST = "synthetic_test_only"


class V8TrustedCandleIndex:
    """Interface immutable full-panel capability bez caller-callable issuer."""

    __slots__ = ()

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

    def __new__(cls, *_args: object, **_kwargs: object) -> V8TrustedCandleIndex:
        """Zapreshchaet pryamoe sozdanie interface bez concrete trust root."""
        if cls is V8TrustedCandleIndex:
            raise TypeError("V8TrustedCandleIndex ne imeet public issuer")
        return super().__new__(cls)

    @property
    def candles(self) -> tuple[TenMinuteCandle, ...]:
        """Vozvrashchaet immutable full panel dlya audit/serialization."""
        raise NotImplementedError

    @property
    def index(self) -> Mapping[tuple[str, datetime], TenMinuteCandle]:
        """Vozvrashchaet read-only exact contract/window lookup."""
        raise NotImplementedError

    def replay_subset(
        self,
        bindings: Sequence[V8OrderBinding],
    ) -> tuple[TenMinuteCandle, ...]:
        """Materializuet tol'ko fixed-planner bars iz full sealed absence proof."""
        keys: set[tuple[str, datetime]] = set()
        for binding in bindings:
            request = binding.request
            contracts = (
                (request.contract_id,)
                if isinstance(request, PredeclaredMarketOrder)
                else (request.old_contract_id, request.new_contract_id)
            )
            for contract_id in contracts:
                for offset in (10, 30, 40):
                    keys.add(
                        (
                            contract_id,
                            request.decision_at + timedelta(minutes=offset),
                        )
                    )
        return tuple(
            self.index[key]
            for key in sorted(keys, key=lambda item: (item[1], item[0]))
            if key in self.index
        )


def _require_candle_capability_type(index: V8TrustedCandleIndex) -> None:
    """Authoritative ledger prinimaet tol'ko exact verified-loader concrete type."""
    status = V8CandleTrustStatus(index.trust_status)
    if status is V8CandleTrustStatus.SYNTHETIC_TEST:
        return
    from market_lab.futures_v8.evaluation_run import _V8AuthoritativeCandleIndex

    if type(index) is not _V8AuthoritativeCandleIndex:
        raise TypeError("authoritative ledger otklonil non-loader candle capability")


@dataclass(frozen=True, slots=True)
class V8StrategyDecisionSet:
    """Odin core input i rovno desyat' candidate runs na odnom prediction record."""

    prediction: V8TargetFreePrediction
    core_snapshot: DecisionModelSnapshot
    aggressive_runs: tuple[CandidateRun, ...]

    def __post_init__(self) -> None:
        """Dokazyvaet exact catalog order i same prediction/input seals."""
        if self.core_snapshot.decision_at != self.prediction.context.decision_at:
            raise ValueError("core snapshot decision mismatch")
        runs = tuple(self.aggressive_runs)
        ids = tuple(run.decision.candidate_id.value for run in runs)
        if ids != AGGRESSIVE_CANDIDATE_IDS:
            raise ValueError("strategy set dolzhen soderzhat' exact 10 catalog candidates")
        for run in runs:
            if run.decision.prediction_sha256 != self.prediction.context.prediction_sha256:
                raise ValueError("candidate ispol'zoval drugoi prediction SHA")
            if run.decision.input_bundle_sha256 != self.prediction.context.input_bundle_sha256:
                raise ValueError("candidate ispol'zoval drugoi decision input bundle")
        object.__setattr__(self, "aggressive_runs", runs)


def build_v8_strategy_decision_set(
    prediction: V8TargetFreePrediction,
    *,
    breakout_state: BreakoutPyramidState | None = None,
) -> V8StrategyDecisionSet:
    """Stroit core i vse 10 formulas bez candidate selection ili target access."""
    runs = tuple(
        run_aggressive_candidate(
            candidate_id,
            prediction.context,
            breakout_state=(
                breakout_state
                if candidate_id == AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP.value
                else None
            ),
        )
        for candidate_id in AGGRESSIVE_CANDIDATE_IDS
    )
    return V8StrategyDecisionSet(prediction, prediction.core_snapshot(), runs)


def build_v8_core_path(bundle: V8SealedEvaluationInputBundle) -> tuple[PortfolioDecision, ...]:
    """Stroit core five-sleeve path iz tol'ko target-free bundle predictions."""
    return build_v8_portfolio_path(tuple(item.core_snapshot() for item in bundle.predictions))


@dataclass(frozen=True, slots=True, order=True)
class V8PositionKey:
    """Izoliruet poziciyu po strategy, sleeve, asset i real'nomu contractu."""

    strategy_id: str
    sleeve_id: str
    asset_id: str
    contract_id: str

    def __post_init__(self) -> None:
        """Proveryaet stable identity bez skrytoi cross-strategy netting."""
        object.__setattr__(
            self, "strategy_id", _require_identifier(self.strategy_id, "strategy_id")
        )
        object.__setattr__(self, "sleeve_id", _require_identifier(self.sleeve_id, "sleeve_id"))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("position asset vne sealed universe")
        object.__setattr__(
            self, "contract_id", _require_identifier(self.contract_id, "contract_id")
        )


class V8OrderCause(StrEnum):
    """Yavnaya prichina event ordera dlya audit trail."""

    ENTRY = "entry"
    EXIT = "exit"
    REBALANCE = "rebalance"
    PAIRED_ROLL = "paired_roll"
    CORRIDOR_EXIT = "corridor_exit"
    BREAKOUT_TRANSITION = "breakout_transition"


@dataclass(frozen=True, slots=True)
class V8StatefulReplayPolicy:
    """Trusted predeclared windows/reason dlya stateful candle replay."""

    scenario_id: V8ScenarioId
    base_window_opened_at: datetime
    scenario_window_opened_at: datetime
    reason: str
    adverse_reference_price: float | None = None

    def __post_init__(self) -> None:
        """Trebuet same-window primary/double ili strict next-bar delay."""
        scenario_id = V8ScenarioId(self.scenario_id)
        base_open = _require_aware(self.base_window_opened_at, "base_window_opened_at")
        scenario_open = _require_aware(
            self.scenario_window_opened_at,
            "scenario_window_opened_at",
        )
        expected_scenario_open = (
            base_open + timedelta(minutes=10)
            if scenario_id is V8ScenarioId.DELAY
            else base_open
        )
        if scenario_open != expected_scenario_open:
            raise ValueError("stateful replay window ne sootvetstvuet fixed scenario")
        reason = _require_identifier(self.reason, "stateful replay reason")
        reference = self.adverse_reference_price
        if reference is not None:
            reference = _require_finite_positive(reference, "adverse_reference_price")
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "base_window_opened_at", base_open)
        object.__setattr__(self, "scenario_window_opened_at", scenario_open)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "adverse_reference_price", reference)


@dataclass(frozen=True, slots=True)
class V8OrderBinding:
    """Svyazyvaet execution request s odnoi ili dvumya ledger poziciyami."""

    request: ExecutionRequest
    cause: V8OrderCause
    effective_session_date: date
    single_position: V8PositionKey | None = None
    old_roll_position: V8PositionKey | None = None
    new_roll_position: V8PositionKey | None = None
    stateful_replay_policy: V8StatefulReplayPolicy | None = None

    def __post_init__(self) -> None:
        """Trebuet exact mapping dlya single ili paired roll request."""
        object.__setattr__(self, "cause", V8OrderCause(self.cause))
        object.__setattr__(
            self,
            "effective_session_date",
            _require_session_date(
                self.effective_session_date,
                "effective_session_date",
            ),
        )
        if self.effective_session_date <= _decision_trade_date(self.request.decision_at):
            raise ValueError("order effective session dolzhna byt' posle decision D")
        if self.stateful_replay_policy is not None:
            if not isinstance(self.stateful_replay_policy, V8StatefulReplayPolicy):
                raise TypeError("stateful_replay_policy imeet nevernyi tip")
            if self.stateful_replay_policy.base_window_opened_at <= self.request.decision_at:
                raise ValueError("stateful replay window dolzhno byt' posle decision")
        if isinstance(self.request, PredeclaredMarketOrder):
            if self.single_position is None or any(
                item is not None for item in (self.old_roll_position, self.new_roll_position)
            ):
                raise ValueError("single order trebuet tol'ko single_position")
            if self.request.contract_id != self.single_position.contract_id:
                raise ValueError("single order contract/binding mismatch")
            if self.stateful_replay_policy is not None and self.cause not in (
                V8OrderCause.ENTRY,
                V8OrderCause.CORRIDOR_EXIT,
            ):
                raise ValueError("stateful replay policy dopustima tol'ko dlya corridor order")
        elif isinstance(self.request, PredeclaredPairedMarketRollOrder):
            if self.stateful_replay_policy is not None:
                raise ValueError("paired roll ne prinimaet stateful replay policy")
            if self.single_position is not None or any(
                item is None for item in (self.old_roll_position, self.new_roll_position)
            ):
                raise ValueError("paired roll trebuet old i new position")
            if (
                self.old_roll_position is None
                or self.new_roll_position is None
                or self.old_roll_position.contract_id != self.request.old_contract_id
                or self.new_roll_position.contract_id != self.request.new_contract_id
            ):
                raise ValueError("paired roll contract/binding mismatch")
            if (
                self.old_roll_position.strategy_id != self.new_roll_position.strategy_id
                or self.old_roll_position.asset_id != self.new_roll_position.asset_id
            ):
                raise ValueError("paired roll ne mozhet perenosit' exposure mezhdu strategy/asset")
        else:
            raise TypeError("V8 evaluator prinimaet tol'ko primary market requests")


@dataclass(frozen=True, slots=True)
class V8ScenarioFillLeg:
    """Scenario-adjusted fill leg s ssylkoi na factual candle evidence."""

    contract_id: str
    signed_contracts: int
    execution_price: float | None
    factual_open: float | None
    factual_high: float | None
    factual_low: float | None
    factual_close: float | None
    factual_volume: int | None
    capacity_contracts: int | None
    window_opened_at: datetime
    window_closed_at: datetime
    reason: str

    def __post_init__(self) -> None:
        """Proveryaet signed quantity, cenu i exact 10m factual window."""
        object.__setattr__(
            self, "contract_id", _require_identifier(self.contract_id, "contract_id")
        )
        opened = _require_aware(self.window_opened_at, "window_opened_at")
        closed = _require_aware(self.window_closed_at, "window_closed_at")
        if closed - opened != timedelta(minutes=10):
            raise ValueError("scenario fill window dolzhen byt' rovno 10 minut")
        if isinstance(self.signed_contracts, bool) or not isinstance(self.signed_contracts, int):
            raise TypeError("signed_contracts dolzhen byt' int")
        if self.signed_contracts:
            object.__setattr__(
                self,
                "execution_price",
                _require_finite_positive(self.execution_price, "execution_price"),
            )
        elif self.execution_price is not None:
            raise ValueError("zero fill ne mozhet imet' execution_price")
        for name in ("factual_open", "factual_high", "factual_low", "factual_close"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_finite_positive(value, name))
        if (
            self.factual_high is not None
            and self.factual_low is not None
            and self.factual_high < self.factual_low
        ):
            raise ValueError("scenario factual high/low invariant narushen")
        if all(
            value is not None
            for value in (
                self.factual_open,
                self.factual_high,
                self.factual_low,
                self.factual_close,
            )
        ) and (
            self.factual_high < max(self.factual_open, self.factual_close)
            or (self.factual_low > min(self.factual_open, self.factual_close))
        ):
            raise ValueError("scenario factual OHLC invariant narushen")
        if self.signed_contracts > 0 and (
            self.factual_high is None or self.execution_price < self.factual_high
        ):
            raise ValueError("scenario buy price dolzhna byt' ne luchshe factual high")
        if self.signed_contracts < 0 and (
            self.factual_low is None or self.execution_price > self.factual_low
        ):
            raise ValueError("scenario sell price dolzhna byt' ne luchshe factual low")
        if self.factual_volume is not None and (
            isinstance(self.factual_volume, bool)
            or not isinstance(self.factual_volume, int)
            or self.factual_volume < 0
        ):
            raise ValueError("factual_volume dolzhen byt' nonnegative int ili None")
        if self.capacity_contracts is not None and (
            isinstance(self.capacity_contracts, bool)
            or not isinstance(self.capacity_contracts, int)
            or self.capacity_contracts < 0
        ):
            raise ValueError("capacity_contracts dolzhen byt' nonnegative int ili None")
        if (
            self.capacity_contracts is not None
            and abs(self.signed_contracts) > self.capacity_contracts
        ):
            raise ValueError("scenario fill prevysil factual capacity")
        object.__setattr__(self, "window_opened_at", opened)
        object.__setattr__(self, "window_closed_at", closed)


def _execution_result_legs(result: ExecutionResult) -> tuple[ExecutionLeg, ...]:
    """Vozvrashchaet base legi v kanonicheskom single/old-new poryadke."""
    if isinstance(result, OrderExecution):
        return (result.leg,)
    return result.old_leg, result.new_leg


def _base_leg_capacity(leg: ExecutionLeg) -> int | None:
    """Vyvodit exact gross POV cap iz dvuh factual capacity granic base leg'a."""
    if leg.observed_capacity_contracts is None or leg.realized_execution_capacity_contracts is None:
        return None
    return min(
        leg.observed_capacity_contracts,
        leg.realized_execution_capacity_contracts,
    )


def _adverse_stress_price(
    leg: ExecutionLeg,
    signed_contracts: int,
    multiplier: float,
) -> float:
    """Uvelichivaet tol'ko observed adverse excursion ot factual window open."""
    if leg.factual_execution_open is None:
        raise ValueError("filled leg ne imeet factual execution open")
    if signed_contracts > 0:
        if leg.factual_execution_high is None:
            raise ValueError("filled buy leg ne imeet factual high")
        price = leg.factual_execution_open + multiplier * (
            leg.factual_execution_high - leg.factual_execution_open
        )
    else:
        if leg.factual_execution_low is None:
            raise ValueError("filled sell leg ne imeet factual low")
        price = leg.factual_execution_open - multiplier * (
            leg.factual_execution_open - leg.factual_execution_low
        )
    return _require_finite_positive(price, "scenario adverse execution price")


def _assert_exact_value(actual: object, expected: object, label: str) -> None:
    """Fail-closed sravnivaet odno derivational evidence pole bez dopuska."""
    if actual != expected:
        raise ValueError(f"scenario/base {label} mismatch")


def _assert_primary_or_double_leg_derivation(
    scenario_id: V8ScenarioId,
    scenario_leg: V8ScenarioFillLeg,
    base_leg: ExecutionLeg,
) -> None:
    """Dokazyvaet exact primary copy ili edinstvennyi fixed 2x price stress."""
    expected_price = base_leg.execution_price
    if scenario_id is V8ScenarioId.DOUBLE_COST and base_leg.executed_contracts:
        expected_price = _adverse_stress_price(
            base_leg,
            base_leg.executed_contracts,
            2.0,
        )
    expected = {
        "contract_id": base_leg.contract_id,
        "signed_contracts": base_leg.executed_contracts,
        "execution_price": expected_price,
        "factual_open": base_leg.factual_execution_open,
        "factual_high": base_leg.factual_execution_high,
        "factual_low": base_leg.factual_execution_low,
        "factual_close": base_leg.factual_execution_close,
        "factual_volume": base_leg.realized_execution_volume,
        "capacity_contracts": _base_leg_capacity(base_leg),
        "window_opened_at": base_leg.execution_window_open_at,
        "window_closed_at": base_leg.execution_window_close_at,
        "reason": base_leg.reason,
    }
    for name, value in expected.items():
        _assert_exact_value(getattr(scenario_leg, name), value, f"leg {name}")


def _assert_delay_leg_derivation(
    scenario_leg: V8ScenarioFillLeg,
    base_leg: ExecutionLeg,
) -> None:
    """Svyazyvaet delay s next exact 10m bar i D-known base capacity."""
    _assert_exact_value(
        scenario_leg.contract_id,
        base_leg.contract_id,
        "delay contract_id",
    )
    expected_open = base_leg.execution_window_close_at
    _assert_exact_value(
        scenario_leg.window_opened_at,
        expected_open,
        "delay window_opened_at",
    )
    _assert_exact_value(
        scenario_leg.window_closed_at,
        expected_open + timedelta(minutes=10),
        "delay window_closed_at",
    )
    delayed_realized_capacity = (
        scenario_leg.factual_volume * CAPACITY_BPS // BASIS_POINTS
        if scenario_leg.factual_volume is not None
        else None
    )
    expected_capacity = (
        min(base_leg.observed_capacity_contracts, delayed_realized_capacity)
        if base_leg.observed_capacity_contracts is not None
        and delayed_realized_capacity is not None
        else None
    )
    _assert_exact_value(
        scenario_leg.capacity_contracts,
        expected_capacity,
        "delay capacity_contracts",
    )
    if scenario_leg.signed_contracts > 0:
        expected_price = scenario_leg.factual_high
    elif scenario_leg.signed_contracts < 0:
        expected_price = scenario_leg.factual_low
    else:
        expected_price = None
    _assert_exact_value(
        scenario_leg.execution_price,
        expected_price,
        "delay execution_price",
    )
    if scenario_leg.signed_contracts and (
        expected_capacity is None
        or expected_capacity <= 0
        or abs(scenario_leg.signed_contracts) > expected_capacity
    ):
        raise ValueError("scenario/base delay fill ne podtverzhden capacity")


@dataclass(frozen=True, slots=True)
class V8ScenarioExecutionEvidence:
    """Audit odnogo ordera: base execution.py evidence i scenario fill legs."""

    scenario_id: V8ScenarioId
    order_id: str
    effective_session_date: date
    base_execution: ExecutionResult
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    status: ExecutionStatus
    legs: tuple[V8ScenarioFillLeg, ...]
    trusted_candle_panel_sha256: str | None = None
    evidence_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Svyazyvaet scenario outcome s original'nym primary request evidence."""
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        object.__setattr__(self, "order_id", _require_identifier(self.order_id, "order_id"))
        object.__setattr__(
            self,
            "effective_session_date",
            _require_session_date(
                self.effective_session_date,
                "effective_session_date",
            ),
        )
        if not isinstance(self.base_execution, (OrderExecution, RollExecution)):
            raise TypeError("base_execution dolzhen byt' execution.py result")
        if self.base_execution.order_id != self.order_id:
            raise ValueError("scenario/base order_id mismatch")
        if self.effective_session_date <= _decision_trade_date(self.base_execution.decision_at):
            raise ValueError("evidence effective session dolzhna byt' posle decision D")
        if isinstance(self.requested_contracts, bool) or not isinstance(
            self.requested_contracts, int
        ):
            raise TypeError("requested_contracts dolzhen byt' int")
        if isinstance(self.executed_contracts, bool) or not isinstance(
            self.executed_contracts, int
        ):
            raise TypeError("executed_contracts dolzhen byt' int")
        if isinstance(self.carry_contracts, bool) or not isinstance(self.carry_contracts, int):
            raise TypeError("carry_contracts dolzhen byt' int")
        object.__setattr__(self, "status", ExecutionStatus(self.status))
        legs = tuple(self.legs)
        expected_legs = 1 if isinstance(self.base_execution, OrderExecution) else 2
        if len(legs) != expected_legs:
            raise ValueError("scenario evidence imeet nevernoe chislo legs")
        if self.requested_contracts == 0:
            raise ValueError("scenario requested_contracts ne mozhet byt' zero")
        if self.requested_contracts != self.base_execution.requested_contracts:
            raise ValueError("scenario/base requested quantity mismatch")
        if isinstance(self.base_execution, OrderExecution):
            if legs[0].signed_contracts != self.executed_contracts:
                raise ValueError("single scenario leg ne sootvetstvuet executed quantity")
            if self.carry_contracts != self.requested_contracts - self.executed_contracts:
                raise ValueError("single scenario carry invariant narushen")
            if self.executed_contracts and (
                (self.executed_contracts > 0) != (self.requested_contracts > 0)
            ):
                raise ValueError("single scenario executed direction mismatch")
        else:
            if tuple(item.signed_contracts for item in legs) != (
                -self.executed_contracts,
                self.executed_contracts,
            ):
                raise ValueError("paired scenario legs dolzhny byt' equal i opposite")
            if self.executed_contracts and (
                (self.executed_contracts > 0) != (self.requested_contracts > 0)
            ):
                raise ValueError("paired scenario executed direction mismatch")
            if self.carry_contracts != self.requested_contracts - self.executed_contracts:
                raise ValueError("paired scenario quantity/carry invariant narushen")
        absolute_request = abs(self.requested_contracts)
        absolute_execution = abs(self.executed_contracts)
        if absolute_execution == absolute_request and self.carry_contracts == 0:
            expected_status = ExecutionStatus.FILLED
        elif absolute_execution == 0 and abs(self.carry_contracts) == absolute_request:
            expected_status = ExecutionStatus.CARRIED
        elif 0 < absolute_execution < absolute_request:
            expected_status = ExecutionStatus.PARTIAL_CARRY
        else:
            raise ValueError("scenario quantity geometry nevalidna")
        if self.status is not expected_status:
            raise ValueError("scenario status ne sootvetstvuet quantity/carry")
        if self.trusted_candle_panel_sha256 is not None:
            object.__setattr__(
                self,
                "trusted_candle_panel_sha256",
                _require_sha256(
                    self.trusted_candle_panel_sha256,
                    "trusted_candle_panel_sha256",
                ),
            )
        if self.scenario_id in (V8ScenarioId.PRIMARY, V8ScenarioId.DOUBLE_COST):
            for name in ("requested_contracts", "executed_contracts", "carry_contracts", "status"):
                _assert_exact_value(
                    getattr(self, name),
                    getattr(self.base_execution, name),
                    name,
                )
            for scenario_leg, base_leg in zip(
                legs,
                _execution_result_legs(self.base_execution),
                strict=True,
            ):
                _assert_primary_or_double_leg_derivation(
                    self.scenario_id,
                    scenario_leg,
                    base_leg,
                )
        else:
            for scenario_leg, base_leg in zip(
                legs,
                _execution_result_legs(self.base_execution),
                strict=True,
            ):
                _assert_delay_leg_derivation(scenario_leg, base_leg)
        object.__setattr__(self, "legs", legs)
        payload = {
            "scenario_id": self.scenario_id,
            "order_id": self.order_id,
            "effective_session_date": self.effective_session_date,
            "base_execution": self.base_execution,
            "requested_contracts": self.requested_contracts,
            "executed_contracts": self.executed_contracts,
            "carry_contracts": self.carry_contracts,
            "status": self.status,
            "legs": legs,
            "trusted_candle_panel_sha256": self.trusted_candle_panel_sha256,
        }
        object.__setattr__(self, "evidence_sha256", canonical_sha256(payload))


def _scenario_spec(scenario_id: V8ScenarioId | str) -> V8ScenarioSpec:
    """Razreshaet tol'ko odin iz treh fixed scenario ID."""
    resolved = V8ScenarioId(scenario_id)
    for row in _FIXED_SCENARIO_ROWS:
        if row[0] is resolved:
            return V8ScenarioSpec(*row)
    raise RuntimeError("Neizvestnyi fixed scenario")


def _primary_or_double_evidence(
    result: ExecutionResult,
    spec: V8ScenarioSpec,
    effective_session_date: date,
) -> V8ScenarioExecutionEvidence:
    """Prevrashchaet execution.py result v primary ili doubled adverse evidence."""
    raw_legs = (
        (result.leg,) if isinstance(result, OrderExecution) else (result.old_leg, result.new_leg)
    )
    scenario_legs = tuple(
        V8ScenarioFillLeg(
            contract_id=leg.contract_id,
            signed_contracts=leg.executed_contracts,
            execution_price=(
                leg.execution_price
                if spec.scenario_id is V8ScenarioId.PRIMARY
                else _adverse_stress_price(leg, leg.executed_contracts, 2.0)
                if leg.executed_contracts
                else None
            ),
            factual_open=leg.factual_execution_open,
            factual_high=leg.factual_execution_high,
            factual_low=leg.factual_execution_low,
            factual_close=leg.factual_execution_close,
            factual_volume=leg.realized_execution_volume,
            capacity_contracts=_base_leg_capacity(leg),
            window_opened_at=leg.execution_window_open_at,
            window_closed_at=leg.execution_window_close_at,
            reason=leg.reason,
        )
        for leg in raw_legs
    )
    return V8ScenarioExecutionEvidence(
        scenario_id=spec.scenario_id,
        order_id=result.order_id,
        effective_session_date=effective_session_date,
        base_execution=result,
        requested_contracts=result.requested_contracts,
        executed_contracts=result.executed_contracts,
        carry_contracts=result.carry_contracts,
        status=result.status,
        legs=scenario_legs,
    )


@dataclass(frozen=True, slots=True)
class _DelayProbe:
    """Internal exact next-10m window probe dlya delay stress allocation."""

    contract_id: str
    requested_contracts: int
    opened_at: datetime
    closed_at: datetime
    factual_open: float | None
    factual_high: float | None
    factual_low: float | None
    factual_close: float | None
    factual_volume: int | None
    capacity_contracts: int | None
    reason: str

    @property
    def ready(self) -> bool:
        """Pokazyvaet polnyi factual delay bar s polozhitel'nym 1-percent cap."""
        return self.reason == "ready"


def _delay_probe(
    result_leg: ExecutionLeg,
    signed_contracts: int,
    index: Mapping[tuple[str, datetime], TenMinuteCandle],
) -> _DelayProbe:
    """Chitaet tol'ko sleduyushchii factual 10m bar posle primary window."""
    opened_at = result_leg.execution_window_close_at
    closed_at = opened_at + timedelta(minutes=10)
    candle = index.get((result_leg.contract_id, opened_at))
    observed = result_leg.observed_capacity_contracts
    if candle is None:
        return _DelayProbe(
            result_leg.contract_id,
            signed_contracts,
            opened_at,
            closed_at,
            None,
            None,
            None,
            None,
            None,
            None,
            "missing_next_factual_10m_window",
        )
    realized = candle.volume * CAPACITY_BPS // BASIS_POINTS if candle.volume is not None else None
    capacity = min(observed, realized) if observed is not None and realized is not None else None
    if not candle.has_factual_ohlc:
        reason = "unavailable_next_factual_ohlc"
    elif candle.volume is None:
        reason = "unavailable_next_factual_volume"
    elif observed is None:
        reason = "unavailable_observed_capacity"
    elif capacity is None or capacity <= 0:
        reason = "zero_next_factual_capacity"
    else:
        reason = "ready"
    return _DelayProbe(
        result_leg.contract_id,
        signed_contracts,
        opened_at,
        closed_at,
        candle.open_price,
        candle.high_price,
        candle.low_price,
        candle.close_price,
        candle.volume,
        capacity,
        reason,
    )


def _delay_fill_leg(probe: _DelayProbe, signed_contracts: int, reason: str) -> V8ScenarioFillLeg:
    """Materializuet delayed adverse high/low ili explicit zero-fill carry."""
    price = None
    if signed_contracts > 0:
        price = probe.factual_high
    elif signed_contracts < 0:
        price = probe.factual_low
    return V8ScenarioFillLeg(
        contract_id=probe.contract_id,
        signed_contracts=signed_contracts,
        execution_price=price,
        factual_open=probe.factual_open,
        factual_high=probe.factual_high,
        factual_low=probe.factual_low,
        factual_close=probe.factual_close,
        factual_volume=probe.factual_volume,
        capacity_contracts=probe.capacity_contracts,
        window_opened_at=probe.opened_at,
        window_closed_at=probe.closed_at,
        reason=reason,
    )


def _delayed_evidence_batch(
    bindings: Sequence[V8OrderBinding],
    base_results: Sequence[ExecutionResult],
    candles: Sequence[TenMinuteCandle],
) -> tuple[V8ScenarioExecutionEvidence, ...]:
    """Allocation'it exact next completed bar gross-cap bez fallback na bolee pozdnii."""
    index = {(item.contract_id, item.opened_at): item for item in candles}
    result_by_id = {item.order_id: item for item in base_results}
    probes: dict[str, tuple[_DelayProbe, ...]] = {}
    remaining: dict[tuple[str, datetime], int] = {}
    for binding in bindings:
        result = result_by_id[binding.request.order_id]
        if isinstance(result, OrderExecution):
            row = (_delay_probe(result.leg, binding.request.signed_contracts, index),)
        else:
            if not isinstance(binding.request, PredeclaredPairedMarketRollOrder):
                raise TypeError("roll result/request type mismatch")
            row = (
                _delay_probe(result.old_leg, -binding.request.signed_contracts, index),
                _delay_probe(result.new_leg, binding.request.signed_contracts, index),
            )
        probes[binding.request.order_id] = row
        for probe in row:
            if probe.ready and probe.capacity_contracts is not None:
                key = (probe.contract_id, probe.opened_at)
                previous = remaining.setdefault(key, probe.capacity_contracts)
                if previous != probe.capacity_contracts:
                    raise ValueError("delay probes imeyut nesovmestimy capacity dlya odnogo bara")
    evidence_by_id: dict[str, V8ScenarioExecutionEvidence] = {}
    ordered = sorted(
        bindings, key=lambda item: (item.request.allocation_priority, item.request.order_id)
    )
    for binding in ordered:
        request = binding.request
        result = result_by_id[request.order_id]
        row = probes[request.order_id]
        failed = next((probe for probe in row if not probe.ready), None)
        if failed is not None:
            executed = 0
            carry = request.signed_contracts
            status = ExecutionStatus.CARRIED
            reason = failed.reason
            legs = tuple(_delay_fill_leg(probe, 0, reason) for probe in row)
        elif isinstance(request, PredeclaredMarketOrder):
            probe = row[0]
            key = (probe.contract_id, probe.opened_at)
            quantity = min(abs(request.signed_contracts), remaining[key])
            remaining[key] -= quantity
            executed = quantity if request.signed_contracts > 0 else -quantity
            carry = request.signed_contracts - executed
            if quantity == 0:
                status = ExecutionStatus.CARRIED
                reason = "delayed_aggregate_capacity_exhausted"
            elif carry:
                status = ExecutionStatus.PARTIAL_CARRY
                reason = "delayed_aggregate_capacity_limited"
            else:
                status = ExecutionStatus.FILLED
                reason = "delayed_filled"
            legs = (_delay_fill_leg(probe, executed, reason),)
        else:
            old_probe, new_probe = row
            old_key = (old_probe.contract_id, old_probe.opened_at)
            new_key = (new_probe.contract_id, new_probe.opened_at)
            absolute_request = abs(request.signed_contracts)
            quantity = min(absolute_request, remaining[old_key], remaining[new_key])
            remaining[old_key] -= quantity
            remaining[new_key] -= quantity
            executed = quantity if request.signed_contracts > 0 else -quantity
            carry = request.signed_contracts - executed
            if quantity == 0:
                status = ExecutionStatus.CARRIED
                reason = "delayed_paired_capacity_exhausted"
            elif quantity < absolute_request:
                status = ExecutionStatus.PARTIAL_CARRY
                reason = "delayed_paired_capacity_limited"
            else:
                status = ExecutionStatus.FILLED
                reason = "delayed_paired_research_fill"
            legs = (
                _delay_fill_leg(old_probe, -executed, reason),
                _delay_fill_leg(new_probe, executed, reason),
            )
        evidence_by_id[request.order_id] = V8ScenarioExecutionEvidence(
            scenario_id=V8ScenarioId.DELAY,
            order_id=request.order_id,
            effective_session_date=binding.effective_session_date,
            base_execution=result,
            requested_contracts=request.signed_contracts,
            executed_contracts=executed,
            carry_contracts=carry,
            status=status,
            legs=legs,
        )
    return tuple(evidence_by_id[item.request.order_id] for item in bindings)


def _status_from_signed_geometry(requested: int, executed: int) -> tuple[int, ExecutionStatus]:
    """Vyvodit carry/status iz signed request i canonical executed quantity."""
    carry = requested - executed
    if carry == 0:
        status = ExecutionStatus.FILLED
    elif executed == 0:
        status = ExecutionStatus.CARRIED
    else:
        status = ExecutionStatus.PARTIAL_CARRY
    return carry, status


def _stateful_bar_capacity(candle: TenMinuteCandle | None) -> int | None:
    """Schitaet 1-percent cap tol'ko iz polnogo trusted OHLCV bara."""
    if candle is None or not candle.has_factual_ohlc or candle.volume is None:
        return None
    return candle.volume * CAPACITY_BPS // BASIS_POINTS


def _stateful_replay_evidence(
    binding: V8OrderBinding,
    candle_index: Mapping[tuple[str, datetime], TenMinuteCandle],
    used_capacity: Mapping[tuple[str, datetime], int],
) -> V8ScenarioExecutionEvidence:
    """Rebuildit odin stateful fill iz trusted bars i predeclared binding policy."""
    policy = binding.stateful_replay_policy
    if policy is None or not isinstance(binding.request, PredeclaredMarketOrder):
        raise TypeError("stateful replay trebuet single binding s policy")
    request = binding.request
    contract_id = request.contract_id
    base_opened = policy.base_window_opened_at
    scenario_opened = policy.scenario_window_opened_at
    base_candle = candle_index.get((contract_id, base_opened))
    scenario_candle = candle_index.get((contract_id, scenario_opened))
    base_capacity = _stateful_bar_capacity(base_candle)
    scenario_realized_capacity = _stateful_bar_capacity(scenario_candle)
    scenario_capacity = (
        min(base_capacity, scenario_realized_capacity)
        if policy.scenario_id is V8ScenarioId.DELAY
        and base_capacity is not None
        and scenario_realized_capacity is not None
        else scenario_realized_capacity
        if policy.scenario_id is not V8ScenarioId.DELAY
        else None
    )
    base_available = (
        max(0, base_capacity - used_capacity.get((contract_id, base_opened), 0))
        if base_capacity is not None
        else 0
    )
    scenario_available = (
        max(0, scenario_capacity - used_capacity.get((contract_id, scenario_opened), 0))
        if scenario_capacity is not None
        else 0
    )
    absolute_request = abs(request.signed_contracts)
    base_absolute = min(absolute_request, base_available)
    base_executed = base_absolute if request.signed_contracts > 0 else -base_absolute
    reference_reached = True
    if (
        policy.scenario_id is V8ScenarioId.DELAY
        and scenario_candle is not None
        and scenario_candle.has_factual_ohlc
        and policy.adverse_reference_price is not None
    ):
        if request.signed_contracts > 0:
            reference_reached = (
                scenario_candle.high_price is not None
                and scenario_candle.high_price >= policy.adverse_reference_price
            )
        else:
            reference_reached = (
                scenario_candle.low_price is not None
                and scenario_candle.low_price <= policy.adverse_reference_price
            )
    scenario_absolute = (
        min(absolute_request, scenario_available) if reference_reached else 0
    )
    scenario_executed = (
        scenario_absolute if request.signed_contracts > 0 else -scenario_absolute
    )
    base_carry, base_status = _status_from_signed_geometry(
        request.signed_contracts,
        base_executed,
    )
    carry, status = _status_from_signed_geometry(
        request.signed_contracts,
        scenario_executed,
    )
    complete_scenario = bool(
        scenario_candle is not None
        and scenario_candle.has_factual_ohlc
        and scenario_candle.volume is not None
        and scenario_capacity is not None
    )
    reason = (
        policy.reason
        if complete_scenario and reference_reached
        else "delayed_adverse_reference_not_reached"
        if complete_scenario
        else "missing_corridor_exit_execution_window"
    )
    base_reason = "base_" + reason if policy.scenario_id is V8ScenarioId.DELAY else reason
    base_price = (
        _adverse_stress_price(
            ExecutionLeg(
                contract_id=contract_id,
                requested_contracts=request.signed_contracts,
                capacity_candle_open_at=base_opened,
                capacity_candle_close_at=base_opened + timedelta(minutes=10),
                observed_capacity_volume=(base_candle.volume if base_candle is not None else None),
                observed_capacity_contracts=base_capacity,
                order_live_at=request.decision_at,
                execution_window_open_at=base_opened,
                execution_window_close_at=base_opened + timedelta(minutes=10),
                factual_execution_open=(
                    base_candle.open_price if base_candle is not None else None
                ),
                factual_execution_high=(
                    base_candle.high_price if base_candle is not None else None
                ),
                factual_execution_low=(
                    base_candle.low_price if base_candle is not None else None
                ),
                factual_execution_close=(
                    base_candle.close_price if base_candle is not None else None
                ),
                realized_execution_volume=(
                    base_candle.volume if base_candle is not None else None
                ),
                realized_execution_capacity_contracts=base_capacity,
                execution_volume_is_post_window_outcome=True,
                aggregate_available_before=(
                    base_available if base_capacity is not None else None
                ),
                executed_contracts=base_executed,
                execution_price=None,
                reason=base_reason,
                provenance=STATEFUL_REPLAY_PROVENANCE,
            ),
            base_executed,
            1.0,
        )
        if base_executed
        else None
    )
    base_leg = ExecutionLeg(
        contract_id=contract_id,
        requested_contracts=request.signed_contracts,
        capacity_candle_open_at=base_opened,
        capacity_candle_close_at=base_opened + timedelta(minutes=10),
        observed_capacity_volume=(base_candle.volume if base_candle is not None else None),
        observed_capacity_contracts=base_capacity,
        order_live_at=request.decision_at,
        execution_window_open_at=base_opened,
        execution_window_close_at=base_opened + timedelta(minutes=10),
        factual_execution_open=(base_candle.open_price if base_candle is not None else None),
        factual_execution_high=(base_candle.high_price if base_candle is not None else None),
        factual_execution_low=(base_candle.low_price if base_candle is not None else None),
        factual_execution_close=(base_candle.close_price if base_candle is not None else None),
        realized_execution_volume=(base_candle.volume if base_candle is not None else None),
        realized_execution_capacity_contracts=base_capacity,
        execution_volume_is_post_window_outcome=True,
        aggregate_available_before=(base_available if base_capacity is not None else None),
        executed_contracts=base_executed,
        execution_price=base_price,
        reason=base_reason,
        provenance=STATEFUL_REPLAY_PROVENANCE,
    )
    base = OrderExecution(
        order_id=request.order_id,
        decision_at=request.decision_at,
        requested_contracts=request.signed_contracts,
        executed_contracts=base_executed,
        carry_contracts=base_carry,
        allocation_priority=0,
        status=base_status,
        reason=base_reason,
        provenance=STATEFUL_REPLAY_PROVENANCE,
        leg=base_leg,
    )
    scenario_price = (
        _adverse_stress_price(
            ExecutionLeg(
                contract_id=contract_id,
                requested_contracts=request.signed_contracts,
                capacity_candle_open_at=scenario_opened,
                capacity_candle_close_at=scenario_opened + timedelta(minutes=10),
                observed_capacity_volume=(
                    scenario_candle.volume if scenario_candle is not None else None
                ),
                observed_capacity_contracts=scenario_capacity,
                order_live_at=request.decision_at,
                execution_window_open_at=scenario_opened,
                execution_window_close_at=scenario_opened + timedelta(minutes=10),
                factual_execution_open=(
                    scenario_candle.open_price if scenario_candle is not None else None
                ),
                factual_execution_high=(
                    scenario_candle.high_price if scenario_candle is not None else None
                ),
                factual_execution_low=(
                    scenario_candle.low_price if scenario_candle is not None else None
                ),
                factual_execution_close=(
                    scenario_candle.close_price if scenario_candle is not None else None
                ),
                realized_execution_volume=(
                    scenario_candle.volume if scenario_candle is not None else None
                ),
                realized_execution_capacity_contracts=scenario_capacity,
                execution_volume_is_post_window_outcome=True,
                aggregate_available_before=(
                    scenario_available if scenario_capacity is not None else None
                ),
                executed_contracts=scenario_executed,
                execution_price=None,
                reason=reason,
                provenance=STATEFUL_REPLAY_PROVENANCE,
            ),
            scenario_executed,
            2.0 if policy.scenario_id is V8ScenarioId.DOUBLE_COST else 1.0,
        )
        if scenario_executed
        else None
    )
    scenario_leg = V8ScenarioFillLeg(
        contract_id=contract_id,
        signed_contracts=scenario_executed,
        execution_price=scenario_price,
        factual_open=(scenario_candle.open_price if scenario_candle is not None else None),
        factual_high=(scenario_candle.high_price if scenario_candle is not None else None),
        factual_low=(scenario_candle.low_price if scenario_candle is not None else None),
        factual_close=(scenario_candle.close_price if scenario_candle is not None else None),
        factual_volume=(scenario_candle.volume if scenario_candle is not None else None),
        capacity_contracts=scenario_capacity,
        window_opened_at=scenario_opened,
        window_closed_at=scenario_opened + timedelta(minutes=10),
        reason=reason,
    )
    return V8ScenarioExecutionEvidence(
        scenario_id=policy.scenario_id,
        order_id=request.order_id,
        effective_session_date=binding.effective_session_date,
        base_execution=base,
        requested_contracts=request.signed_contracts,
        executed_contracts=scenario_executed,
        carry_contracts=carry,
        status=status,
        legs=(scenario_leg,),
    )


def plan_v8_scenario_execution(
    bindings: Sequence[V8OrderBinding],
    candles: Sequence[TenMinuteCandle] | V8TrustedCandleIndex,
    scenario_id: V8ScenarioId | str,
    *,
    prior_capacity_consumption: Sequence[V8CapacityConsumption] = (),
) -> tuple[V8ScenarioExecutionEvidence, ...]:
    """Stroit evidence batch s obyazatel'nym base call v execution.py dlya kazhdogo ordera."""
    spec = _scenario_spec(scenario_id)
    frozen = tuple(bindings)
    if not frozen:
        return ()
    order_ids = [item.request.order_id for item in frozen]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("order bindings soderzhat duplicate order_id")
    decisions = {item.request.decision_at for item in frozen}
    strategies = {
        (
            item.single_position.strategy_id
            if item.single_position is not None
            else item.old_roll_position.strategy_id
            if item.old_roll_position is not None
            else None
        )
        for item in frozen
    }
    effective_dates = {item.effective_session_date for item in frozen}
    if len(decisions) != 1 or len(strategies) != 1 or len(effective_dates) != 1:
        raise ValueError("odin execution batch dolzhen byt' odnoi strategy i decision")
    trusted_index = candles if isinstance(candles, V8TrustedCandleIndex) else None
    trusted_candles = (
        trusted_index.replay_subset(frozen)
        if trusted_index is not None
        else tuple(candles)
    )

    def bind_to_trusted_panel(
        rows: Sequence[V8ScenarioExecutionEvidence],
    ) -> tuple[V8ScenarioExecutionEvidence, ...]:
        frozen_rows = tuple(rows)
        if trusted_index is None:
            return frozen_rows
        return tuple(
            replace(
                item,
                trusted_candle_panel_sha256=trusted_index.candle_panel_sha256,
            )
            for item in frozen_rows
        )
    stateful_bindings = tuple(
        item for item in frozen if item.stateful_replay_policy is not None
    )
    if stateful_bindings:
        if any(
            item.stateful_replay_policy is not None
            and item.stateful_replay_policy.scenario_id is not spec.scenario_id
            for item in frozen
        ):
            raise ValueError("stateful replay policy/scenario mismatch")
        candle_index: Mapping[tuple[str, datetime], TenMinuteCandle]
        if trusted_index is not None:
            candle_index = trusted_index.index
        else:
            mutable_candle_index: dict[tuple[str, datetime], TenMinuteCandle] = {}
            for candle in trusted_candles:
                key = (candle.contract_id, candle.opened_at)
                if key in mutable_candle_index:
                    raise ValueError("trusted candles soderzhat duplicate contract/window")
                mutable_candle_index[key] = candle
            candle_index = mutable_candle_index
        used_capacity = {
            (item.contract_id, item.window_opened_at): item.consumed_contracts
            for item in prior_capacity_consumption
        }
        if len(used_capacity) != len(tuple(prior_capacity_consumption)):
            raise ValueError("prior capacity consumption soderzhit duplicate window")
        standard = tuple(
            item for item in frozen if item.stateful_replay_policy is None
        )
        standard_rows = (
            plan_v8_scenario_execution(
                standard,
                trusted_index if trusted_index is not None else trusted_candles,
                spec.scenario_id,
            )
            if standard
            else ()
        )
        standard_by_id = {item.order_id: item for item in standard_rows}
        replay_rows: list[V8ScenarioExecutionEvidence] = []
        for binding in frozen:
            if binding.stateful_replay_policy is None:
                evidence = standard_by_id[binding.request.order_id]
            else:
                evidence = _stateful_replay_evidence(
                    binding,
                    candle_index,
                    used_capacity,
                )
            replay_rows.append(evidence)
            for leg in evidence.legs:
                if leg.signed_contracts:
                    key = (leg.contract_id, leg.window_opened_at)
                    used_capacity[key] = used_capacity.get(key, 0) + abs(
                        leg.signed_contracts
                    )
        return bind_to_trusted_panel(replay_rows)
    if prior_capacity_consumption:
        raise ValueError("prior capacity consumption trebuet stateful replay policy")
    base = plan_causal_v8_execution(
        tuple(item.request for item in frozen),
        trusted_candles,
    )
    if spec.scenario_id is V8ScenarioId.DELAY:
        return bind_to_trusted_panel(
            _delayed_evidence_batch(frozen, base, trusted_candles)
        )
    binding_by_id = {item.request.order_id: item for item in frozen}
    return bind_to_trusted_panel(
        tuple(
            _primary_or_double_evidence(
                item,
                spec,
                binding_by_id[item.order_id].effective_session_date,
            )
            for item in base
        )
    )


@dataclass(frozen=True, slots=True)
class V8LedgerPosition:
    """Integer futures position s poslednei VM reference cenoi."""

    key: V8PositionKey
    quantity: int
    reference_price: float

    def __post_init__(self) -> None:
        """Zapreshchaet zero quantity i fractional contract state."""
        if not isinstance(self.key, V8PositionKey):
            raise TypeError("position key dolzhen byt' V8PositionKey")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("position quantity dolzhen byt' int")
        if self.quantity == 0:
            raise ValueError("zero position ne dolzhna hranit'sya v ledger")
        object.__setattr__(
            self,
            "reference_price",
            _require_finite_positive(self.reference_price, "reference_price"),
        )


@dataclass(frozen=True, slots=True)
class V8UnresolvedOrder:
    """Terminal NO-GO carry bez synthetic retry ili split-state continuation."""

    order_id: str
    scenario_id: V8ScenarioId
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    reason: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        """Trebuet real'nyi nonzero carry i evidence seal."""
        object.__setattr__(self, "order_id", _require_identifier(self.order_id, "order_id"))
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        if self.carry_contracts == 0:
            raise ValueError("unresolved order trebuet nonzero carry")
        object.__setattr__(
            self,
            "evidence_sha256",
            _require_sha256(self.evidence_sha256, "evidence_sha256"),
        )


@dataclass(frozen=True, slots=True)
class V8CapacityConsumption:
    """Persisted gross POV use odnogo contracta v odnom factual window."""

    contract_id: str
    window_opened_at: datetime
    window_closed_at: datetime
    capacity_contracts: int
    consumed_contracts: int

    def __post_init__(self) -> None:
        """Trebuet exact 10m key i consumed ne vyshe immutable capacity."""
        object.__setattr__(
            self,
            "contract_id",
            _require_identifier(self.contract_id, "contract_id"),
        )
        opened = _require_aware(self.window_opened_at, "window_opened_at")
        closed = _require_aware(self.window_closed_at, "window_closed_at")
        if closed - opened != timedelta(minutes=10):
            raise ValueError("capacity consumption window dolzhen byt' rovno 10 minut")
        for name in ("capacity_contracts", "consumed_contracts"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} dolzhen byt' nonnegative int")
        if self.consumed_contracts > self.capacity_contracts:
            raise ValueError("persisted consumed contracts prevysili POV capacity")
        object.__setattr__(self, "window_opened_at", opened)
        object.__setattr__(self, "window_closed_at", closed)

    @property
    def key(self) -> tuple[str, datetime]:
        """Vozvrashchaet aggregate contract/window capacity key."""
        return self.contract_id, self.window_opened_at


@dataclass(frozen=True, slots=True)
class V8LedgerFillEvent:
    """Odin fakticheskii contract fill s VM, fee i slippage audit."""

    event_sequence: int
    scenario_id: V8ScenarioId
    order_id: str
    executed_at: datetime
    position_key: V8PositionKey
    signed_contracts: int
    execution_price: float
    prior_quantity: int
    resulting_quantity: int
    variation_margin: float
    fee: float
    turnover_notional: float
    adverse_slippage_notional: float
    evidence_sha256: str
    spec_effective_session_date: date
    spec_snapshot_sha256: str
    spec_accounting_as_of: datetime

    def __post_init__(self) -> None:
        """Proveryaet event arithmetic identity i finite cash components."""
        if isinstance(self.event_sequence, bool) or not isinstance(self.event_sequence, int):
            raise TypeError("event_sequence dolzhen byt' int")
        if self.event_sequence < 0:
            raise ValueError("event_sequence ne mozhet byt' otricatel'nym")
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        object.__setattr__(self, "order_id", _require_identifier(self.order_id, "order_id"))
        object.__setattr__(self, "executed_at", _require_aware(self.executed_at, "executed_at"))
        if self.signed_contracts == 0:
            raise ValueError("fill event ne mozhet byt' zero")
        if self.resulting_quantity != self.prior_quantity + self.signed_contracts:
            raise ValueError("fill event quantity invariant narushen")
        object.__setattr__(
            self,
            "execution_price",
            _require_finite_positive(self.execution_price, "execution_price"),
        )
        for name in ("variation_margin", "fee", "turnover_notional", "adverse_slippage_notional"):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} dolzhen byt' finite")
            if name != "variation_margin" and value < 0.0:
                raise ValueError(f"{name} ne mozhet byt' otricatel'nym")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "evidence_sha256",
            _require_sha256(self.evidence_sha256, "evidence_sha256"),
        )
        object.__setattr__(
            self,
            "spec_effective_session_date",
            _require_session_date(
                self.spec_effective_session_date,
                "spec_effective_session_date",
            ),
        )
        object.__setattr__(
            self,
            "spec_snapshot_sha256",
            _require_sha256(self.spec_snapshot_sha256, "spec_snapshot_sha256"),
        )
        accounting_as_of = _require_aware(
            self.spec_accounting_as_of,
            "spec_accounting_as_of",
        )
        if accounting_as_of < self.executed_at:
            raise ValueError("fill accounting as-of ne mozhet byt' ranshe execution")
        object.__setattr__(self, "spec_accounting_as_of", accounting_as_of)


@dataclass(frozen=True, slots=True)
class V8EquityPoint:
    """Exact post-settlement equity point odnogo factual event momenta."""

    marked_at: datetime
    cash: float
    equity: float
    gross_notional: float
    initial_margin: float
    spec_effective_session_date: date | None = None
    spec_snapshot_sha256: str | None = None
    spec_accounting_as_of: datetime | None = None

    def __post_init__(self) -> None:
        """Trebuet aware moment i finite nonnegative risk values."""
        object.__setattr__(self, "marked_at", _require_aware(self.marked_at, "marked_at"))
        for name in ("cash", "equity", "gross_notional", "initial_margin"):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} dolzhen byt' finite")
            if name in ("gross_notional", "initial_margin") and value < 0.0:
                raise ValueError(f"{name} ne mozhet byt' otricatel'nym")
            object.__setattr__(self, name, value)
        spec_fields = (
            self.spec_effective_session_date,
            self.spec_snapshot_sha256,
            self.spec_accounting_as_of,
        )
        if any(item is None for item in spec_fields) and not all(
            item is None for item in spec_fields
        ):
            raise ValueError("equity point spec session, SHA i as-of dolzhny byt' vmeste")
        if self.spec_effective_session_date is not None:
            object.__setattr__(
                self,
                "spec_effective_session_date",
                _require_session_date(
                    self.spec_effective_session_date,
                    "spec_effective_session_date",
                ),
            )
            object.__setattr__(
                self,
                "spec_snapshot_sha256",
                _require_sha256(self.spec_snapshot_sha256, "spec_snapshot_sha256"),
            )
            accounting_as_of = _require_aware(
                self.spec_accounting_as_of,
                "spec_accounting_as_of",
            )
            if accounting_as_of < self.marked_at:
                raise ValueError("equity accounting as-of ne mozhet byt' ranshe mark")
            object.__setattr__(self, "spec_accounting_as_of", accounting_as_of)


@dataclass(frozen=True, slots=True)
class V8EventLedgerState:
    """Immutable exact integer-contract VM/cash ledger odnogo strategy/scenario."""

    strategy_id: str
    scenario_id: V8ScenarioId
    initial_cash: float
    cash: float
    candle_trust_status: V8CandleTrustStatus = V8CandleTrustStatus.SYNTHETIC_TEST
    evaluation_bundle_sha256: str | None = None
    trusted_candle_panel_sha256: str | None = None
    positions: tuple[V8LedgerPosition, ...] = ()
    fills: tuple[V8LedgerFillEvent, ...] = ()
    unresolved_orders: tuple[V8UnresolvedOrder, ...] = ()
    capacity_consumption: tuple[V8CapacityConsumption, ...] = ()
    equity_curve: tuple[V8EquityPoint, ...] = ()
    cumulative_fees: float = 0.0
    cumulative_turnover: float = 0.0
    cumulative_adverse_slippage: float = 0.0

    def __post_init__(self) -> None:
        """Zapreshchaet duplicate position keys i nonfinite accounting state."""
        object.__setattr__(
            self, "strategy_id", _require_identifier(self.strategy_id, "strategy_id")
        )
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        trust_status = V8CandleTrustStatus(self.candle_trust_status)
        bundle_hash = self.evaluation_bundle_sha256
        panel_hash = self.trusted_candle_panel_sha256
        if (bundle_hash is None) != (panel_hash is None):
            raise ValueError("ledger bundle/panel identities dolzhny byt' all-or-none")
        if bundle_hash is not None and panel_hash is not None:
            bundle_hash = _require_sha256(
                bundle_hash,
                "evaluation_bundle_sha256",
            )
            panel_hash = _require_sha256(
                panel_hash,
                "trusted_candle_panel_sha256",
            )
        if trust_status is V8CandleTrustStatus.AUTHORITATIVE and bundle_hash is None:
            raise ValueError("authoritative ledger trebuet pinned bundle/panel identities")
        object.__setattr__(self, "candle_trust_status", trust_status)
        object.__setattr__(self, "evaluation_bundle_sha256", bundle_hash)
        object.__setattr__(self, "trusted_candle_panel_sha256", panel_hash)
        initial = _require_finite_positive(self.initial_cash, "initial_cash")
        cash = float(self.cash)
        if not isfinite(cash):
            raise ValueError("cash dolzhen byt' finite")
        positions = tuple(sorted(self.positions, key=lambda item: item.key))
        if len({item.key for item in positions}) != len(positions):
            raise ValueError("ledger soderzhit duplicate position key")
        for item in positions:
            if item.key.strategy_id != self.strategy_id:
                raise ValueError("position strategy ne sootvetstvuet ledger")
        for name in (
            "cumulative_fees",
            "cumulative_turnover",
            "cumulative_adverse_slippage",
        ):
            value = float(getattr(self, name))
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} dolzhen byt' finite i >= 0")
            object.__setattr__(self, name, value)
        fills = tuple(self.fills)
        if tuple(item.event_sequence for item in fills) != tuple(range(len(fills))):
            raise ValueError("ledger fill event_sequence dolzhen byt' plotnym ot nulya")
        if any(item.scenario_id is not self.scenario_id for item in fills):
            raise ValueError("ledger fill scenario mismatch")
        if any(item.position_key.strategy_id != self.strategy_id for item in fills):
            raise ValueError("ledger fill strategy mismatch")
        if any(
            right.executed_at < left.executed_at
            for left, right in zip(fills, fills[1:], strict=False)
        ):
            raise ValueError("ledger fills dolzhny byt' chronologichny")
        if abs(self.cumulative_fees - sum(item.fee for item in fills)) > FLOAT_TOLERANCE:
            raise ValueError("ledger cumulative_fees ne ravny summe fill events")
        if (
            abs(self.cumulative_turnover - sum(item.turnover_notional for item in fills))
            > FLOAT_TOLERANCE
        ):
            raise ValueError("ledger cumulative_turnover ne raven summe fill events")
        if (
            abs(
                self.cumulative_adverse_slippage
                - sum(item.adverse_slippage_notional for item in fills)
            )
            > FLOAT_TOLERANCE
        ):
            raise ValueError("ledger slippage ne raven summe fill events")
        unresolved_orders = tuple(self.unresolved_orders)
        if any(item.scenario_id is not self.scenario_id for item in unresolved_orders):
            raise ValueError("ledger unresolved order scenario mismatch")
        capacity_consumption = tuple(sorted(self.capacity_consumption, key=lambda item: item.key))
        if len({item.key for item in capacity_consumption}) != len(capacity_consumption):
            raise ValueError("ledger capacity consumption soderzhit duplicate window key")
        curve = tuple(self.equity_curve)
        if any(
            right.marked_at <= left.marked_at for left, right in zip(curve, curve[1:], strict=False)
        ):
            raise ValueError("ledger equity curve dolzhna byt' strogo chronologichna")
        object.__setattr__(self, "initial_cash", initial)
        object.__setattr__(self, "cash", cash)
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "fills", fills)
        object.__setattr__(self, "unresolved_orders", unresolved_orders)
        object.__setattr__(self, "capacity_consumption", capacity_consumption)
        object.__setattr__(self, "equity_curve", curve)

    @classmethod
    def create(
        cls,
        strategy_id: str,
        scenario_id: V8ScenarioId | str,
        initial_cash: float,
        *,
        trusted_candles: V8TrustedCandleIndex | None = None,
        evaluation_bundle_sha256: str | None = None,
    ) -> V8EventLedgerState:
        """Sozdaet pustoi isolated ledger bez pozicii i skrytyh zaimov."""
        if trusted_candles is None:
            if evaluation_bundle_sha256 is not None:
                raise ValueError("unpinned ledger ne prinimaet bundle SHA")
            trust_status = V8CandleTrustStatus.SYNTHETIC_TEST
            bundle_hash = None
            panel_hash = None
        else:
            if not isinstance(trusted_candles, V8TrustedCandleIndex):
                raise TypeError("ledger create trebuet trusted candle capability")
            bundle_hash = trusted_candles.evaluation_bundle_sha256
            if (
                evaluation_bundle_sha256 is not None
                and evaluation_bundle_sha256 != bundle_hash
            ):
                raise ValueError("ledger create bundle/capability SHA mismatch")
            trust_status = trusted_candles.trust_status
            panel_hash = trusted_candles.candle_panel_sha256
        return cls(
            strategy_id=strategy_id,
            scenario_id=V8ScenarioId(scenario_id),
            initial_cash=initial_cash,
            cash=initial_cash,
            candle_trust_status=trust_status,
            evaluation_bundle_sha256=bundle_hash,
            trusted_candle_panel_sha256=panel_hash,
        )


@dataclass(frozen=True, slots=True)
class V8EvaluationLedgerMatrix:
    """Exact 11-by-3 isolated ledger matrix odnogo sealed evaluation bundle."""

    prediction_sha256: str
    evaluation_bundle_sha256: str
    trusted_candle_panel_sha256: str
    candle_trust_status: V8CandleTrustStatus
    ledgers: tuple[V8EventLedgerState, ...]

    def __post_init__(self) -> None:
        """Dokazyvaet polnyi Cartesian product bez scenario/candidate selection."""
        object.__setattr__(
            self,
            "prediction_sha256",
            _require_sha256(self.prediction_sha256, "prediction_sha256"),
        )
        object.__setattr__(
            self,
            "evaluation_bundle_sha256",
            _require_sha256(self.evaluation_bundle_sha256, "evaluation_bundle_sha256"),
        )
        object.__setattr__(
            self,
            "trusted_candle_panel_sha256",
            _require_sha256(
                self.trusted_candle_panel_sha256,
                "trusted_candle_panel_sha256",
            ),
        )
        trust_status = V8CandleTrustStatus(self.candle_trust_status)
        object.__setattr__(self, "candle_trust_status", trust_status)
        ledgers = tuple(self.ledgers)
        expected = tuple(
            (strategy_id, scenario.scenario_id)
            for strategy_id in V8_STRATEGY_IDS
            for scenario in fixed_v8_scenarios()
        )
        actual = tuple((item.strategy_id, item.scenario_id) for item in ledgers)
        if actual != expected:
            raise ValueError("ledger matrix dolzhna byt' exact core+10 x 3 scenarios")
        if len({item.initial_cash for item in ledgers}) != 1:
            raise ValueError("vse ledger matrix rows dolzhny imet' odin initial_cash")
        if any(
            item.evaluation_bundle_sha256 != self.evaluation_bundle_sha256
            or item.trusted_candle_panel_sha256
            != self.trusted_candle_panel_sha256
            or item.candle_trust_status is not trust_status
            for item in ledgers
        ):
            raise ValueError("ledger matrix rows ne privyazany k odnomu trust root")
        object.__setattr__(self, "ledgers", ledgers)

    def ledger(
        self,
        strategy_id: str,
        scenario_id: V8ScenarioId | str,
    ) -> V8EventLedgerState:
        """Vozvrashchaet exact isolated ledger po typed strategy/scenario key."""
        normalized_strategy = _require_identifier(strategy_id, "strategy_id")
        if normalized_strategy not in V8_STRATEGY_IDS:
            raise ValueError("strategy_id vne exact evaluation matrix")
        normalized_scenario = V8ScenarioId(scenario_id)
        return next(
            item
            for item in self.ledgers
            if item.strategy_id == normalized_strategy and item.scenario_id is normalized_scenario
        )


def create_v8_evaluation_ledger_matrix(
    bundle: V8SealedEvaluationInputBundle,
    trusted_candles: V8TrustedCandleIndex,
    *,
    initial_cash: float,
) -> V8EvaluationLedgerMatrix:
    """Sozdaet 33 isolated cash/VM ledgers, privyazannyh k odnomu input seal."""
    if not isinstance(trusted_candles, V8TrustedCandleIndex):
        raise TypeError("ledger matrix trebuet trusted candle capability")
    _require_candle_capability_type(trusted_candles)
    if trusted_candles.evaluation_bundle_sha256 != bundle.evaluation_bundle_sha256:
        raise ValueError("ledger matrix bundle/candle capability mismatch")
    ledgers = tuple(
        V8EventLedgerState.create(
            strategy_id,
            scenario.scenario_id,
            initial_cash,
            trusted_candles=trusted_candles,
            evaluation_bundle_sha256=bundle.evaluation_bundle_sha256,
        )
        for strategy_id in V8_STRATEGY_IDS
        for scenario in fixed_v8_scenarios()
    )
    return V8EvaluationLedgerMatrix(
        prediction_sha256=bundle.prediction_sha256,
        evaluation_bundle_sha256=bundle.evaluation_bundle_sha256,
        trusted_candle_panel_sha256=trusted_candles.candle_panel_sha256,
        candle_trust_status=trusted_candles.trust_status,
        ledgers=ledgers,
    )


class V8LedgerRiskError(ValueError):
    """Fail-closed signal pri narushenii cash, IM ili gross bez clipping zadnim chislom."""


def _spec_index(
    specs: Sequence[V8ContractSpec],
) -> dict[tuple[str, date], V8ContractSpec]:
    """Indeksiruet unique contract/session snapshots bez latest-known fallback."""
    result: dict[tuple[str, date], V8ContractSpec] = {}
    for spec in specs:
        if not isinstance(spec, V8ContractSpec):
            raise TypeError("specs dolzhny soderzhat' V8ContractSpec")
        key = (spec.contract_id, spec.effective_session_date)
        if key in result:
            raise ValueError("duplicate contract/session spec")
        result[key] = spec
    return result


def _select_spec_snapshot(
    index: Mapping[tuple[str, date], V8ContractSpec],
    *,
    contract_id: str,
    effective_session_date: date,
    sizing_as_of: datetime | None = None,
    accounting_as_of: datetime | None = None,
) -> V8ContractSpec:
    """Vyberaet rovno exact contract/session snapshot i proveryaet dve as-of granicy."""
    contract = _require_identifier(contract_id, "contract_id")
    if isinstance(effective_session_date, datetime) or not isinstance(effective_session_date, date):
        raise TypeError("effective_session_date dolzhen byt' date")
    spec = index.get((contract, effective_session_date))
    if spec is None:
        raise LookupError("exact contract/session spec snapshot unknown")
    if sizing_as_of is not None:
        sizing_cutoff = _require_aware(sizing_as_of, "sizing_as_of")
        if spec.sizing_known_at > sizing_cutoff:
            raise LookupError("lag-1 sizing spec byl neizvesten na as-of moment")
    if accounting_as_of is not None:
        accounting_cutoff = _require_aware(accounting_as_of, "accounting_as_of")
        if spec.accounting_known_at > accounting_cutoff:
            raise LookupError("current-session accounting byl neizvesten na as-of moment")
    return spec


def select_v8_contract_spec_snapshot(
    specs: Sequence[V8ContractSpec],
    *,
    contract_id: str,
    effective_session_date: date,
    sizing_as_of: datetime | None = None,
    accounting_as_of: datetime | None = None,
) -> V8ContractSpec:
    """Publikuet fail-closed exact selector bez nearest, stale ili future fallback."""
    return _select_spec_snapshot(
        _spec_index(specs),
        contract_id=contract_id,
        effective_session_date=effective_session_date,
        sizing_as_of=sizing_as_of,
        accounting_as_of=accounting_as_of,
    )


def _position_index(positions: Sequence[V8LedgerPosition]) -> dict[V8PositionKey, V8LedgerPosition]:
    """Prevrashchaet immutable positions v local mutable index dlya batch transition."""
    return {item.key: item for item in positions}


def _capacity_index(
    rows: Sequence[V8CapacityConsumption],
) -> dict[tuple[str, datetime], V8CapacityConsumption]:
    """Indeksiruet persisted aggregate POV use bez sbrosa mezhdu API calls."""
    return {item.key: item for item in rows}


def _consume_capacity(
    capacity: dict[tuple[str, datetime], V8CapacityConsumption],
    *,
    contract_id: str,
    window_opened_at: datetime,
    window_closed_at: datetime,
    capacity_contracts: int | None,
    filled_contracts: int,
) -> None:
    """Atomarno uvelichivaet gross use i fail-closed ot reset/overfill."""
    if filled_contracts <= 0:
        return
    if capacity_contracts is None:
        raise ValueError("nonzero fill ne imeet factual capacity")
    key = (contract_id, window_opened_at)
    previous = capacity.get(key)
    if previous is not None and (
        previous.capacity_contracts != capacity_contracts
        or previous.window_closed_at != window_closed_at
    ):
        raise ValueError("persisted capacity ne sovpala s novym evidence")
    consumed_before = previous.consumed_contracts if previous is not None else 0
    capacity[key] = V8CapacityConsumption(
        contract_id=contract_id,
        window_opened_at=window_opened_at,
        window_closed_at=window_closed_at,
        capacity_contracts=capacity_contracts,
        consumed_contracts=consumed_before + filled_contracts,
    )


def _binding_fill_keys(
    binding: V8OrderBinding,
    evidence: V8ScenarioExecutionEvidence,
) -> tuple[tuple[V8PositionKey, V8ScenarioFillLeg], ...]:
    """Svyazyvaet odnu ili dve scenario legs s exact ledger keys."""
    if isinstance(binding.request, PredeclaredMarketOrder):
        if binding.single_position is None:
            raise RuntimeError("single binding poteryal position")
        return ((binding.single_position, evidence.legs[0]),)
    if binding.old_roll_position is None or binding.new_roll_position is None:
        raise RuntimeError("roll binding poteryal old/new position")
    return (
        (binding.old_roll_position, evidence.legs[0]),
        (binding.new_roll_position, evidence.legs[1]),
    )


def _portfolio_risk(
    cash: float,
    positions: Mapping[V8PositionKey, V8LedgerPosition],
    specs: Mapping[tuple[str, date], V8ContractSpec],
    marks: Mapping[str, float] | None,
    *,
    effective_session_date: date,
    accounting_as_of: datetime,
) -> tuple[float, float, float, tuple[str, ...]]:
    """Schitaet equity/gross current-session, a IM iz exact lag-1 snapshot."""
    if marks is not None:
        required_marks = {item.key.contract_id for item in positions.values()}
        if not required_marks.issubset(marks):
            raise ValueError("risk marks dolzhny pokryvat' vse open contracts")
    equity = cash
    gross = 0.0
    initial_margin = 0.0
    snapshot_hashes: set[str] = set()
    for position in positions.values():
        spec = _select_spec_snapshot(
            specs,
            contract_id=position.key.contract_id,
            effective_session_date=effective_session_date,
            sizing_as_of=accounting_as_of,
            accounting_as_of=accounting_as_of,
        )
        if spec.asset_id != position.key.asset_id:
            raise ValueError("open position/spec asset mismatch")
        snapshot_hashes.add(spec.snapshot_sha256)
        mark = (
            _require_finite_positive(marks[position.key.contract_id], "risk mark")
            if marks is not None and position.key.contract_id in marks
            else position.reference_price
        )
        equity += (
            position.quantity * (mark - position.reference_price) * spec.accounting_price_multiplier
        )
        gross += abs(position.quantity) * mark * spec.accounting_price_multiplier
        initial_margin += abs(position.quantity) * spec.initial_margin_per_contract
    return equity, gross, initial_margin, tuple(sorted(snapshot_hashes))


def apply_v8_execution_batch(
    state: V8EventLedgerState,
    bindings: Sequence[V8OrderBinding],
    evidence: Sequence[V8ScenarioExecutionEvidence],
    specs: Sequence[V8ContractSpec],
    *,
    trusted_candles: V8TrustedCandleIndex,
    accounting_as_of: datetime,
    risk_marks: Mapping[str, float] | None = None,
) -> V8EventLedgerState:
    """Replan'it trusted candles do mutation i primenyayet tol'ko exact evidence."""
    frozen_bindings = tuple(bindings)
    frozen_evidence = tuple(evidence)
    if not isinstance(trusted_candles, V8TrustedCandleIndex):
        raise TypeError("ledger admission trebuet full sealed V8TrustedCandleIndex")
    _require_candle_capability_type(trusted_candles)
    if (
        state.evaluation_bundle_sha256 is None
        or state.trusted_candle_panel_sha256 is None
    ):
        raise ValueError("ledger admission trebuet pinned bundle/panel identities")
    if (
        state.candle_trust_status is not trusted_candles.trust_status
        or state.evaluation_bundle_sha256
        != trusted_candles.evaluation_bundle_sha256
        or state.trusted_candle_panel_sha256
        != trusted_candles.candle_panel_sha256
    ):
        raise ValueError("ledger/candle capability trust-root identity mismatch")
    if not frozen_bindings and not frozen_evidence:
        return state
    if any(
        item.trusted_candle_panel_sha256
        != trusted_candles.candle_panel_sha256
        for item in frozen_evidence
    ):
        raise ValueError("ledger evidence ne privyazano k trusted candle panel SHA")
    trusted_replay = plan_v8_scenario_execution(
        frozen_bindings,
        trusted_candles,
        state.scenario_id,
        prior_capacity_consumption=(
            state.capacity_consumption
            if any(item.stateful_replay_policy is not None for item in frozen_bindings)
            else ()
        ),
    )
    trusted_replay_sha256 = canonical_sha256(trusted_replay)
    supplied_evidence_sha256 = canonical_sha256(frozen_evidence)
    if (
        frozen_evidence != trusted_replay
        or supplied_evidence_sha256 != trusted_replay_sha256
    ):
        raise ValueError(
            "ledger evidence ne sovpalo s exact trusted-candle batch replay"
        )
    binding_by_id = {item.request.order_id: item for item in frozen_bindings}
    evidence_by_id = {item.order_id: item for item in frozen_evidence}
    if len(binding_by_id) != len(frozen_bindings) or len(evidence_by_id) != len(frozen_evidence):
        raise ValueError("duplicate order ID v ledger batch")
    if set(binding_by_id) != set(evidence_by_id):
        raise ValueError("ledger bindings/evidence dolzhny exact sovpadat'")
    if any(item.scenario_id is not state.scenario_id for item in frozen_evidence):
        raise ValueError("scenario evidence ne sootvetstvuet ledger")
    prior_order_ids = {
        *(item.order_id for item in state.fills),
        *(item.order_id for item in state.unresolved_orders),
    }
    if prior_order_ids.intersection(evidence_by_id):
        raise ValueError("order_id ne mozhet povtorno primenyat'sya k ledger")
    for binding in frozen_bindings:
        strategy_id = (
            binding.single_position.strategy_id
            if binding.single_position is not None
            else binding.old_roll_position.strategy_id
            if binding.old_roll_position is not None
            else ""
        )
        if strategy_id != state.strategy_id:
            raise ValueError("binding strategy ne sootvetstvuet ledger")
    binding_sessions = {item.effective_session_date for item in frozen_bindings}
    evidence_sessions = {item.effective_session_date for item in frozen_evidence}
    if len(binding_sessions) != 1 or binding_sessions != evidence_sessions:
        raise ValueError("ledger bindings/evidence trebuyut odnu exact effective session")
    event_session = next(iter(binding_sessions))
    window_closes = tuple(leg.window_closed_at for item in frozen_evidence for leg in item.legs)
    if not window_closes:
        raise ValueError("ledger batch ne imeet execution windows")
    last_window_close = max(window_closes)
    accounting_cutoff = _require_aware(
        accounting_as_of,
        "accounting_as_of",
    )
    if accounting_cutoff < last_window_close:
        raise ValueError("accounting_as_of ne mozhet byt' ranshe execution window")
    spec_by_contract = _spec_index(specs)
    positions = _position_index(state.positions)
    capacity_consumption = _capacity_index(state.capacity_consumption)
    cash = state.cash
    fill_events = list(state.fills)
    unresolved = list(state.unresolved_orders)
    fee_total = state.cumulative_fees
    turnover_total = state.cumulative_turnover
    slippage_total = state.cumulative_adverse_slippage
    scenario_spec = _scenario_spec(state.scenario_id)
    effective_risk_marks = dict(risk_marks or {})
    prior_execution_at = state.fills[-1].executed_at if state.fills else None
    ordered_bindings = sorted(
        frozen_bindings,
        key=lambda item: (item.request.allocation_priority, item.request.order_id),
    )
    for binding in ordered_bindings:
        item = evidence_by_id[binding.request.order_id]
        if item.effective_session_date != binding.effective_session_date:
            raise ValueError("ledger binding/evidence effective session mismatch")
        if item.base_execution.decision_at != binding.request.decision_at:
            raise ValueError("ledger binding/evidence decision_at mismatch")
        if isinstance(binding.request, PredeclaredMarketOrder):
            if item.requested_contracts != binding.request.signed_contracts:
                raise ValueError("single binding/evidence requested quantity mismatch")
            if len(item.legs) != 1 or item.legs[0].contract_id != binding.request.contract_id:
                raise ValueError("single binding/evidence contract mismatch")
        else:
            if item.requested_contracts != binding.request.signed_contracts:
                raise ValueError("roll binding/evidence requested quantity mismatch")
            if tuple(leg.contract_id for leg in item.legs) != (
                binding.request.old_contract_id,
                binding.request.new_contract_id,
            ):
                raise ValueError("roll binding/evidence contracts mismatch")
        nonzero_legs = tuple(leg for leg in item.legs if leg.signed_contracts)
        if prior_execution_at is not None and any(
            leg.window_closed_at <= prior_execution_at for leg in nonzero_legs
        ):
            raise ValueError("execution batch dolzhen byt' posle predydushchego batch window")
        if state.equity_curve and any(
            leg.window_closed_at <= state.equity_curve[-1].marked_at for leg in nonzero_legs
        ):
            raise ValueError("execution fill dolzhen byt' posle poslednego settlement")
        if isinstance(binding.request, PredeclaredPairedMarketRollOrder):
            if binding.old_roll_position is None or binding.new_roll_position is None:
                raise RuntimeError("paired roll poteryal old/new position")
            old_position = positions.get(binding.old_roll_position)
            signed_request = binding.request.signed_contracts
            if old_position is None:
                raise ValueError("paired roll ne imeet factual old exposure")
            if (old_position.quantity > 0) != (signed_request > 0):
                raise ValueError("paired roll direction ne sovpala s factual old exposure")
            if abs(old_position.quantity) != abs(signed_request):
                raise ValueError("paired roll absolute q ne ravno factual old exposure")
            new_position = positions.get(binding.new_roll_position)
            if new_position is not None and ((new_position.quantity > 0) != (signed_request > 0)):
                raise ValueError("paired roll ne mozhet invertirovat' factual new exposure")
        if item.carry_contracts:
            # Carry ostayotsya terminal'nym audit NO-GO: evaluator ne generiruet
            # retry/split request, no prodolzhaet nezavisimoe factual accounting.
            unresolved.append(
                V8UnresolvedOrder(
                    order_id=item.order_id,
                    scenario_id=item.scenario_id,
                    requested_contracts=item.requested_contracts,
                    executed_contracts=item.executed_contracts,
                    carry_contracts=item.carry_contracts,
                    reason=";".join(leg.reason for leg in item.legs),
                    evidence_sha256=item.evidence_sha256,
                )
            )
        for key, leg in _binding_fill_keys(binding, item):
            if leg.factual_close is not None:
                previous_mark = effective_risk_marks.setdefault(
                    leg.contract_id,
                    leg.factual_close,
                )
                if abs(previous_mark - leg.factual_close) > FLOAT_TOLERANCE:
                    raise ValueError("odin contract/window imeet nesovmestimye factual close")
            if leg.signed_contracts == 0:
                continue
            _consume_capacity(
                capacity_consumption,
                contract_id=leg.contract_id,
                window_opened_at=leg.window_opened_at,
                window_closed_at=leg.window_closed_at,
                capacity_contracts=leg.capacity_contracts,
                filled_contracts=abs(leg.signed_contracts),
            )
            if leg.execution_price is None:
                raise RuntimeError("nonzero scenario leg ne imeet execution price")
            spec = _select_spec_snapshot(
                spec_by_contract,
                contract_id=key.contract_id,
                effective_session_date=event_session,
                sizing_as_of=binding.request.decision_at,
                accounting_as_of=accounting_cutoff,
            )
            if spec.sizing_observed_session_date != _decision_trade_date(
                binding.request.decision_at
            ):
                raise LookupError("fill sizing observed session ne ravna decision D")
            if spec.asset_id != key.asset_id:
                raise ValueError("fill contract spec asset mismatch")
            prior = positions.get(key)
            prior_quantity = prior.quantity if prior is not None else 0
            prior_reference = prior.reference_price if prior is not None else leg.execution_price
            variation_margin = (
                prior_quantity
                * (leg.execution_price - prior_reference)
                * spec.accounting_price_multiplier
            )
            fee = abs(leg.signed_contracts) * spec.fee_per_contract * scenario_spec.fee_multiplier
            turnover = (
                abs(leg.signed_contracts) * leg.execution_price * spec.accounting_price_multiplier
            )
            if leg.factual_open is None:
                raise ValueError("filled leg ne imeet factual open dlya slippage audit")
            adverse_slippage = (
                abs(leg.signed_contracts)
                * abs(leg.execution_price - leg.factual_open)
                * spec.accounting_price_multiplier
            )
            resulting_quantity = prior_quantity + leg.signed_contracts
            cash += variation_margin - fee
            if resulting_quantity:
                positions[key] = V8LedgerPosition(key, resulting_quantity, leg.execution_price)
            else:
                positions.pop(key, None)
            fill_events.append(
                V8LedgerFillEvent(
                    event_sequence=len(fill_events),
                    scenario_id=state.scenario_id,
                    order_id=item.order_id,
                    executed_at=leg.window_closed_at,
                    position_key=key,
                    signed_contracts=leg.signed_contracts,
                    execution_price=leg.execution_price,
                    prior_quantity=prior_quantity,
                    resulting_quantity=resulting_quantity,
                    variation_margin=variation_margin,
                    fee=fee,
                    turnover_notional=turnover,
                    adverse_slippage_notional=adverse_slippage,
                    evidence_sha256=item.evidence_sha256,
                    spec_effective_session_date=event_session,
                    spec_snapshot_sha256=spec.snapshot_sha256,
                    spec_accounting_as_of=accounting_cutoff,
                )
            )
            fee_total += fee
            turnover_total += turnover
            slippage_total += adverse_slippage
    equity, gross, initial_margin, _ = _portfolio_risk(
        cash,
        positions,
        spec_by_contract,
        effective_risk_marks,
        effective_session_date=event_session,
        accounting_as_of=accounting_cutoff,
    )
    if cash <= 0.0 or equity <= 0.0:
        raise V8LedgerRiskError("ledger cash/equity ne mozhet byt' <= 0")
    if initial_margin > equity + FLOAT_TOLERANCE:
        raise V8LedgerRiskError("post-fill initial margin prevysil equity")
    if gross > MAX_GROSS_EXPOSURE * equity + FLOAT_TOLERANCE:
        raise V8LedgerRiskError("post-fill gross prevysil 1.0 equity")
    return V8EventLedgerState(
        strategy_id=state.strategy_id,
        scenario_id=state.scenario_id,
        initial_cash=state.initial_cash,
        cash=cash,
        candle_trust_status=state.candle_trust_status,
        evaluation_bundle_sha256=state.evaluation_bundle_sha256,
        trusted_candle_panel_sha256=state.trusted_candle_panel_sha256,
        positions=tuple(positions.values()),
        fills=tuple(fill_events),
        unresolved_orders=tuple(unresolved),
        capacity_consumption=tuple(capacity_consumption.values()),
        equity_curve=state.equity_curve,
        cumulative_fees=fee_total,
        cumulative_turnover=turnover_total,
        cumulative_adverse_slippage=slippage_total,
    )


def settle_v8_event_ledger(
    state: V8EventLedgerState,
    specs: Sequence[V8ContractSpec],
    marks: Mapping[str, float],
    *,
    marked_at: datetime,
    effective_session_date: date,
    accounting_as_of: datetime,
) -> V8EventLedgerState:
    """Nachislyaet VM po exact current-session accounting snapshot bez fallback."""
    marked = _require_aware(marked_at, "marked_at")
    accounting_cutoff = _require_aware(
        accounting_as_of,
        "accounting_as_of",
    )
    if accounting_cutoff < marked:
        raise ValueError("accounting_as_of ne mozhet byt' ranshe marked_at")
    event_session = _require_session_date(
        effective_session_date,
        "effective_session_date",
    )
    if state.equity_curve and marked <= state.equity_curve[-1].marked_at:
        raise ValueError("settlement moments dolzhny byt' strogo chronologichny")
    if state.fills and marked < state.fills[-1].executed_at:
        raise ValueError("settlement ne mozhet byt' ranshe poslednego fill")
    spec_by_contract = _spec_index(specs)
    positions: list[V8LedgerPosition] = []
    cash = state.cash
    snapshot_hashes: set[str] = set()
    for position in state.positions:
        if position.key.contract_id not in marks:
            raise ValueError("settlement marks dolzhny pokryvat' vse open contracts")
        mark = _require_finite_positive(marks[position.key.contract_id], "settlement mark")
        spec = _select_spec_snapshot(
            spec_by_contract,
            contract_id=position.key.contract_id,
            effective_session_date=event_session,
            sizing_as_of=accounting_cutoff,
            accounting_as_of=accounting_cutoff,
        )
        if spec.asset_id != position.key.asset_id:
            raise ValueError("settlement contract spec asset mismatch")
        snapshot_hashes.add(spec.snapshot_sha256)
        cash += (
            position.quantity * (mark - position.reference_price) * spec.accounting_price_multiplier
        )
        positions.append(V8LedgerPosition(position.key, position.quantity, mark))
    position_index = _position_index(positions)
    equity, gross, initial_margin, risk_hashes = _portfolio_risk(
        cash,
        position_index,
        spec_by_contract,
        marks,
        effective_session_date=event_session,
        accounting_as_of=accounting_cutoff,
    )
    if tuple(sorted(snapshot_hashes)) != risk_hashes:
        raise RuntimeError("settlement VM i risk ispol'zovali raznye spec snapshots")
    if cash <= 0.0 or equity <= 0.0:
        raise V8LedgerRiskError("settlement privel k nonpositive cash/equity")
    if initial_margin > equity + FLOAT_TOLERANCE:
        raise V8LedgerRiskError("settlement initial margin prevysil equity")
    if gross > MAX_GROSS_EXPOSURE * equity + FLOAT_TOLERANCE:
        raise V8LedgerRiskError("settlement gross prevysil 1.0 equity")
    point = V8EquityPoint(
        marked,
        cash,
        equity,
        gross,
        initial_margin,
        event_session if snapshot_hashes else None,
        canonical_sha256(tuple(sorted(snapshot_hashes))) if snapshot_hashes else None,
        accounting_cutoff if snapshot_hashes else None,
    )
    return V8EventLedgerState(
        strategy_id=state.strategy_id,
        scenario_id=state.scenario_id,
        initial_cash=state.initial_cash,
        cash=cash,
        candle_trust_status=state.candle_trust_status,
        evaluation_bundle_sha256=state.evaluation_bundle_sha256,
        trusted_candle_panel_sha256=state.trusted_candle_panel_sha256,
        positions=tuple(positions),
        fills=state.fills,
        unresolved_orders=state.unresolved_orders,
        capacity_consumption=state.capacity_consumption,
        equity_curve=(*state.equity_curve, point),
        cumulative_fees=state.cumulative_fees,
        cumulative_turnover=state.cumulative_turnover,
        cumulative_adverse_slippage=state.cumulative_adverse_slippage,
    )


def integer_contracts_for_weight(
    weight: float,
    portfolio_equity: float,
    reference_price: float,
    spec: V8ContractSpec,
) -> int:
    """Sizing'uet target truncated-toward-zero bez fractional contracts."""
    if not isfinite(weight) or abs(weight) > 1.0 + FLOAT_TOLERANCE:
        raise ValueError("weight dolzhen byt' finite i v [-1, 1]")
    equity = _require_finite_positive(portfolio_equity, "portfolio_equity")
    price = _require_finite_positive(reference_price, "reference_price")
    raw = weight * equity / (price * spec.sizing_price_multiplier)
    quantity = floor(abs(raw))
    return quantity if raw >= 0.0 else -quantity


@dataclass(frozen=True, slots=True)
class V8SleeveTarget:
    """Odin novyi 0.20 sleeve target odnogo strategy/asset/contracta."""

    strategy_id: str
    sleeve_id: str
    asset_id: str
    contract_id: str
    decision_at: datetime
    entry_effective_session_date: date
    entry_common_session_sequence_id: int
    exit_common_session_sequence_id: int
    target_weight: float
    prediction_sha256: str
    decision_input_sha256: str

    def __post_init__(self) -> None:
        """Fiksiruet D+5 schedule, sealed weight i provenance hashes."""
        object.__setattr__(
            self, "strategy_id", _require_identifier(self.strategy_id, "strategy_id")
        )
        object.__setattr__(self, "sleeve_id", _require_identifier(self.sleeve_id, "sleeve_id"))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("sleeve asset vne sealed universe")
        object.__setattr__(
            self, "contract_id", _require_identifier(self.contract_id, "contract_id")
        )
        object.__setattr__(self, "decision_at", _require_aware(self.decision_at, "decision_at"))
        effective_session = _require_session_date(
            self.entry_effective_session_date,
            "entry_effective_session_date",
        )
        if effective_session <= _decision_trade_date(self.decision_at):
            raise ValueError("sleeve entry effective session dolzhna byt' posle decision D")
        object.__setattr__(self, "entry_effective_session_date", effective_session)
        if (
            isinstance(self.entry_common_session_sequence_id, bool)
            or not isinstance(self.entry_common_session_sequence_id, int)
            or self.entry_common_session_sequence_id < 0
        ):
            raise ValueError("entry sequence dolzhen byt' nonnegative int")
        if self.exit_common_session_sequence_id != (
            self.entry_common_session_sequence_id + HOLDING_SLEEVE_COUNT
        ):
            raise ValueError("sleeve exit dolzhen byt' rovno cherez 5 common sessions")
        weight = float(self.target_weight)
        if not isfinite(weight) or abs(weight) > SLEEVE_WEIGHT + FLOAT_TOLERANCE:
            raise ValueError("odin new sleeve target ne mozhet prevyshat' 0.20")
        object.__setattr__(self, "target_weight", weight)
        object.__setattr__(
            self,
            "prediction_sha256",
            _require_sha256(self.prediction_sha256, "prediction_sha256"),
        )
        object.__setattr__(
            self,
            "decision_input_sha256",
            _require_sha256(self.decision_input_sha256, "decision_input_sha256"),
        )


def build_v8_new_sleeve_targets(
    decision_set: V8StrategyDecisionSet,
    core_decision: PortfolioDecision,
    *,
    common_session_sequence_id: int,
) -> tuple[V8SleeveTarget, ...]:
    """Materializuet core plus 10 novyh sleeves na odnom prediction record."""
    if core_decision.decision_at != decision_set.prediction.context.decision_at:
        raise ValueError("core/candidate decision timestamp mismatch")
    if (
        isinstance(common_session_sequence_id, bool)
        or not isinstance(common_session_sequence_id, int)
        or common_session_sequence_id < 0
    ):
        raise ValueError("common_session_sequence_id dolzhen byt' nonnegative int")
    prediction = decision_set.prediction
    contract_by_asset = {item.asset_id: item for item in prediction.contracts}
    rows: list[V8SleeveTarget] = []
    core_sleeve_id = f"{CORE_STRATEGY_ID}-{common_session_sequence_id:06d}"
    for asset in core_decision.new_sleeve.assets:
        if asset.contract_id is None or abs(asset.combined_weight) <= FLOAT_TOLERANCE:
            continue
        rows.append(
            V8SleeveTarget(
                strategy_id=CORE_STRATEGY_ID,
                sleeve_id=core_sleeve_id,
                asset_id=asset.asset,
                contract_id=asset.contract_id,
                decision_at=core_decision.decision_at,
                entry_effective_session_date=contract_by_asset[
                    asset.asset
                ].entry_effective_session_date,
                entry_common_session_sequence_id=common_session_sequence_id,
                exit_common_session_sequence_id=(common_session_sequence_id + HOLDING_SLEEVE_COUNT),
                target_weight=SLEEVE_WEIGHT * asset.combined_weight,
                prediction_sha256=prediction.context.prediction_sha256,
                decision_input_sha256=prediction.context.input_bundle_sha256,
            )
        )
    for run in decision_set.aggressive_runs:
        strategy_id = run.decision.candidate_id.value
        sleeve_id = f"{strategy_id}-{common_session_sequence_id:06d}"
        for asset_id, unit_weight in run.decision.target_weights:
            contract_snapshot = contract_by_asset[asset_id]
            if not (contract_snapshot.asset_mask and contract_snapshot.nominal_span_eligible):
                continue
            rows.append(
                V8SleeveTarget(
                    strategy_id=strategy_id,
                    sleeve_id=sleeve_id,
                    asset_id=asset_id,
                    contract_id=contract_snapshot.contract_id,
                    decision_at=run.decision.decision_at,
                    entry_effective_session_date=(contract_snapshot.entry_effective_session_date),
                    entry_common_session_sequence_id=common_session_sequence_id,
                    exit_common_session_sequence_id=(
                        common_session_sequence_id + HOLDING_SLEEVE_COUNT
                    ),
                    target_weight=SLEEVE_WEIGHT * unit_weight,
                    prediction_sha256=run.decision.prediction_sha256,
                    decision_input_sha256=run.decision.input_bundle_sha256,
                )
            )
    strategy_gross: dict[str, float] = {}
    for row in rows:
        strategy_gross[row.strategy_id] = strategy_gross.get(row.strategy_id, 0.0) + abs(
            row.target_weight
        )
    if any(value > SLEEVE_WEIGHT + FLOAT_TOLERANCE for value in strategy_gross.values()):
        raise RuntimeError("new sleeve strategy gross prevysil 0.20")
    return tuple(sorted(rows, key=lambda item: (item.strategy_id, item.asset_id)))


def build_v8_entry_bindings(
    targets: Sequence[V8SleeveTarget],
    *,
    strategy_id: str,
    portfolio_equity: float,
    reference_prices: Mapping[str, float],
    specs: Sequence[V8ContractSpec],
) -> tuple[V8OrderBinding, ...]:
    """Prevrashchaet odin strategy sleeve v integer primary market entry requests."""
    rows = tuple(item for item in targets if item.strategy_id == strategy_id)
    if not rows:
        return ()
    decisions = {item.decision_at for item in rows}
    sleeves = {item.sleeve_id for item in rows}
    effective_sessions = {item.entry_effective_session_date for item in rows}
    if len(decisions) != 1 or len(sleeves) != 1 or len(effective_sessions) != 1:
        raise ValueError("entry binding batch trebuet odin decision i odin sleeve")
    spec_by_contract = _spec_index(specs)
    bindings: list[V8OrderBinding] = []
    for priority, row in enumerate(sorted(rows, key=lambda item: item.asset_id)):
        if row.contract_id not in reference_prices:
            raise ValueError("entry target ne imeet D-known reference price")
        event_session = row.entry_effective_session_date
        spec = _select_spec_snapshot(
            spec_by_contract,
            contract_id=row.contract_id,
            effective_session_date=event_session,
            sizing_as_of=row.decision_at,
        )
        if spec.asset_id != row.asset_id:
            raise ValueError("entry target/spec asset mismatch")
        if spec.sizing_observed_session_date != _decision_trade_date(row.decision_at):
            raise LookupError("entry sizing observed session ne ravna decision D")
        quantity = integer_contracts_for_weight(
            row.target_weight,
            portfolio_equity,
            reference_prices[row.contract_id],
            spec,
        )
        if quantity == 0:
            continue
        key = V8PositionKey(row.strategy_id, row.sleeve_id, row.asset_id, row.contract_id)
        order_id = f"entry-{row.sleeve_id}-{row.asset_id}"
        bindings.append(
            V8OrderBinding(
                request=PredeclaredMarketOrder(
                    order_id,
                    row.contract_id,
                    row.decision_at,
                    quantity,
                    priority,
                ),
                cause=V8OrderCause.ENTRY,
                effective_session_date=event_session,
                single_position=key,
            )
        )
    return tuple(bindings)


def build_v8_sleeve_exit_bindings(
    state: V8EventLedgerState,
    *,
    sleeve_id: str,
    decision_at: datetime,
    effective_session_date: date,
) -> tuple[V8OrderBinding, ...]:
    """Stroit exact signed flatten orders dlya odnogo istekshego sleeve."""
    normalized_sleeve = _require_identifier(sleeve_id, "sleeve_id")
    decision = _require_aware(decision_at, "decision_at")
    effective_session = _require_session_date(
        effective_session_date,
        "effective_session_date",
    )
    positions = tuple(item for item in state.positions if item.key.sleeve_id == normalized_sleeve)
    bindings = tuple(
        V8OrderBinding(
            request=PredeclaredMarketOrder(
                f"exit-{normalized_sleeve}-{item.key.asset_id}-{item.key.contract_id}",
                item.key.contract_id,
                decision,
                -item.quantity,
                priority,
            ),
            cause=V8OrderCause.EXIT,
            effective_session_date=effective_session,
            single_position=item.key,
        )
        for priority, item in enumerate(sorted(positions, key=lambda row: row.key))
    )
    return bindings


def build_v8_signed_paired_roll_binding(
    *,
    old_position: V8LedgerPosition,
    new_contract_id: str,
    new_sleeve_id: str,
    decision_at: datetime,
    effective_session_date: date,
    signed_contracts: int,
    allocation_priority: int = 0,
) -> V8OrderBinding:
    """Stroit signed atomic research roll exact factual long ili short exposure."""
    if isinstance(signed_contracts, bool) or not isinstance(signed_contracts, int):
        raise TypeError("signed_contracts dolzhen byt' int")
    if signed_contracts == 0:
        raise ValueError("signed paired roll ne mozhet imet' zero exposure")
    if (old_position.quantity > 0) != (signed_contracts > 0):
        raise ValueError("signed paired roll direction ne sovpala s factual old exposure")
    if abs(signed_contracts) != abs(old_position.quantity):
        raise ValueError("signed paired roll absolute q ne ravno factual old exposure")
    new_contract = _require_identifier(new_contract_id, "new_contract_id")
    new_key = V8PositionKey(
        old_position.key.strategy_id,
        new_sleeve_id,
        old_position.key.asset_id,
        new_contract,
    )
    order_id = f"roll-{old_position.key.sleeve_id}-{old_position.key.contract_id}-{new_contract}"
    return V8OrderBinding(
        request=PredeclaredPairedMarketRollOrder(
            order_id,
            old_position.key.contract_id,
            new_contract,
            decision_at,
            signed_contracts,
            allocation_priority,
        ),
        cause=V8OrderCause.PAIRED_ROLL,
        effective_session_date=_require_session_date(
            effective_session_date,
            "effective_session_date",
        ),
        old_roll_position=old_position.key,
        new_roll_position=new_key,
    )


def build_v8_long_paired_roll_binding(
    *,
    old_position: V8LedgerPosition,
    new_contract_id: str,
    new_sleeve_id: str,
    decision_at: datetime,
    effective_session_date: date,
    contracts: int,
    allocation_priority: int = 0,
) -> V8OrderBinding:
    """Backward-compatible long-only alias canonical signed roll helpera."""
    if isinstance(contracts, bool) or not isinstance(contracts, int):
        raise TypeError("contracts dolzhen byt' int")
    if contracts <= 0:
        raise ValueError("long paired roll contracts dolzhny byt' > 0")
    return build_v8_signed_paired_roll_binding(
        old_position=old_position,
        new_contract_id=new_contract_id,
        new_sleeve_id=new_sleeve_id,
        decision_at=decision_at,
        effective_session_date=effective_session_date,
        signed_contracts=contracts,
        allocation_priority=allocation_priority,
    )


@dataclass(frozen=True, slots=True)
class V8EffectiveScheduledCandidateExecution:
    """Dopolnyaet sealed catalog schedule yavnoi economic effective session."""

    schedule: HoldingSleeveSchedule
    effective_session_date: date
    evidence: CandidateExecutionEvidence
    scenario_evidence_sha256: str

    def __post_init__(self) -> None:
        """Sokhranyaet catalog invariants i zapreshchaet wall-clock session podmenu."""
        ScheduledCandidateExecution(self.schedule, self.evidence)
        effective_session = _require_session_date(
            self.effective_session_date,
            "effective_session_date",
        )
        window_trade_date = self.schedule.entry_window_closed_at.astimezone(MOSCOW_TIMEZONE).date()
        if effective_session <= window_trade_date:
            raise ValueError("candidate effective session dolzhna byt' posle decision D")
        object.__setattr__(self, "effective_session_date", effective_session)
        object.__setattr__(
            self,
            "scenario_evidence_sha256",
            _require_sha256(
                self.scenario_evidence_sha256,
                "scenario_evidence_sha256",
            ),
        )


def candidate_execution_evidence_from_primary(
    scenario_evidence: V8ScenarioExecutionEvidence,
    *,
    binding: V8OrderBinding,
    candidate_run: CandidateRun,
    schedule: HoldingSleeveSchedule,
    execution_bar_sequence_id: int,
) -> V8EffectiveScheduledCandidateExecution:
    """Konvertiruet tol'ko primary execution.py result v catalog evidence boundary."""
    if scenario_evidence.scenario_id is not V8ScenarioId.PRIMARY:
        raise ValueError("candidate state reconciliation ispol'zuet tol'ko primary evidence")
    base = scenario_evidence.base_execution
    if not isinstance(base, OrderExecution):
        raise TypeError("candidate state transition ne prinimaet paired roll kak odin asset order")
    if not isinstance(binding.request, PredeclaredMarketOrder) or binding.single_position is None:
        raise TypeError("candidate state transition trebuet single primary binding")
    if binding.request.order_id != base.order_id:
        raise ValueError("candidate binding/evidence order_id mismatch")
    if binding.effective_session_date != scenario_evidence.effective_session_date:
        raise ValueError("candidate binding/evidence effective session mismatch")
    if binding.single_position.strategy_id != candidate_run.decision.candidate_id.value:
        raise ValueError("candidate binding strategy mismatch")
    if binding.single_position.sleeve_id != schedule.sleeve_id:
        raise ValueError("candidate binding sleeve mismatch")
    if len(scenario_evidence.legs) != 1:
        raise RuntimeError("single candidate evidence dolzhna imet' odin leg")
    leg = base.leg
    observed = leg.observed_capacity_contracts if leg.observed_capacity_contracts is not None else 0
    realized = (
        leg.realized_execution_capacity_contracts
        if leg.realized_execution_capacity_contracts is not None
        else 0
    )
    evidence = CandidateExecutionEvidence(
        candidate_id=candidate_run.decision.candidate_id,
        decision_at=candidate_run.decision.decision_at,
        prediction_sha256=candidate_run.decision.prediction_sha256,
        input_bundle_sha256=candidate_run.decision.input_bundle_sha256,
        sleeve_id=schedule.sleeve_id,
        asset_id=binding.single_position.asset_id,
        contract_id=leg.contract_id,
        order_id=base.order_id,
        common_session_sequence_id=schedule.entry_common_session_sequence_id,
        execution_bar_sequence_id=execution_bar_sequence_id,
        requested_contracts=base.requested_contracts,
        executed_contracts=base.executed_contracts,
        carry_contracts=base.carry_contracts,
        observed_capacity_contracts=observed,
        realized_capacity_contracts=realized,
        execution_window_closed_at=leg.execution_window_close_at,
        execution_price=leg.execution_price,
        execution_evidence_sha256=scenario_evidence.evidence_sha256,
        provenance=RESEARCH_ONLY_NOT_QUEUE_EXACT,
    )
    return V8EffectiveScheduledCandidateExecution(
        schedule=schedule,
        effective_session_date=scenario_evidence.effective_session_date,
        evidence=evidence,
        scenario_evidence_sha256=scenario_evidence.evidence_sha256,
    )


def reconcile_v8_breakout_execution(
    candidate_run: CandidateRun,
    executions: Sequence[V8EffectiveScheduledCandidateExecution],
) -> BreakoutPyramidState:
    """Prodvigaet pyramid level tol'ko cherez full factual catalog evidence."""
    catalog_rows = tuple(
        ScheduledCandidateExecution(item.schedule, item.evidence) for item in executions
    )
    return apply_breakout_execution(candidate_run, catalog_rows)


def reconcile_v8_corridor_exit(
    position: CorridorPosition,
    intent: CorridorExitIntent,
    evidence: CandidateExitExecutionEvidence,
) -> CorridorPosition:
    """Zakryvaet ili carry'it corridor tol'ko po actual typed exit evidence."""
    return apply_volatility_corridor_exit(position, intent, evidence)


def apply_v8_corridor_exit_to_ledger(
    state: V8EventLedgerState,
    *,
    position_key: V8PositionKey,
    corridor_position: CorridorPosition,
    intent: CorridorExitIntent,
    evidence: CandidateExitExecutionEvidence,
    specs: Sequence[V8ContractSpec],
    effective_session_date: date,
    accounting_as_of: datetime,
    risk_marks: Mapping[str, float] | None = None,
) -> tuple[V8EventLedgerState, CorridorPosition]:
    """Atomarno reconciliiruet corridor state i ego actual fill v event-ledger."""
    if state.scenario_id is not V8ScenarioId.PRIMARY:
        raise ValueError(
            "sealed corridor state hardcode'it primary window; stress transition zapreshchen"
        )
    reconciled = reconcile_v8_corridor_exit(corridor_position, intent, evidence)
    if evidence.order_id in {
        *(item.order_id for item in state.fills),
        *(item.order_id for item in state.unresolved_orders),
    }:
        raise ValueError("corridor exit order_id uzhe primenen k ledger")
    if state.fills and intent.trigger_bar_closed_at < state.fills[-1].executed_at:
        raise ValueError("corridor exit ne mozhet byt' ranshe poslednego fill")
    if state.equity_curve and intent.trigger_bar_closed_at <= state.equity_curve[-1].marked_at:
        raise ValueError("corridor exit dolzhen byt' posle poslednego settlement")
    event_session = _require_session_date(
        effective_session_date,
        "effective_session_date",
    )
    accounting_cutoff = _require_aware(
        accounting_as_of,
        "accounting_as_of",
    )
    if accounting_cutoff < intent.trigger_bar_closed_at:
        raise ValueError("accounting_as_of ne mozhet byt' ranshe corridor fill")
    if position_key.strategy_id != AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST.value:
        raise ValueError("corridor ledger key strategy mismatch")
    if (
        position_key.sleeve_id != corridor_position.sleeve_id
        or position_key.asset_id != corridor_position.asset_id
        or position_key.contract_id != corridor_position.contract_id
    ):
        raise ValueError("corridor ledger key identity mismatch")
    spec_by_contract = _spec_index(specs)
    spec = _select_spec_snapshot(
        spec_by_contract,
        contract_id=position_key.contract_id,
        effective_session_date=event_session,
        sizing_as_of=intent.trigger_bar_closed_at,
        accounting_as_of=accounting_cutoff,
    )
    if spec.asset_id != position_key.asset_id:
        raise ValueError("corridor contract spec identity mismatch")
    positions = _position_index(state.positions)
    capacity_consumption = _capacity_index(state.capacity_consumption)
    ledger_position = positions.get(position_key)
    if ledger_position is None:
        raise ValueError("corridor exit ne imeet open ledger position")
    expected_quantity = corridor_position.direction * corridor_position.open_contracts
    if ledger_position.quantity != expected_quantity:
        raise ValueError("corridor state/ledger open quantity mismatch")
    cash = state.cash
    fills = list(state.fills)
    unresolved = list(state.unresolved_orders)
    fee_total = state.cumulative_fees
    turnover_total = state.cumulative_turnover
    slippage_total = state.cumulative_adverse_slippage
    executed = evidence.executed_contracts
    if executed:
        if evidence.execution_price is None:
            raise RuntimeError("corridor nonzero exit ne imeet execution price")
        variation_margin = (
            ledger_position.quantity
            * (evidence.execution_price - ledger_position.reference_price)
            * spec.accounting_price_multiplier
        )
        fee = (
            abs(executed) * spec.fee_per_contract * _scenario_spec(state.scenario_id).fee_multiplier
        )
        turnover = abs(executed) * evidence.execution_price * spec.accounting_price_multiplier
        adverse_slippage = (
            abs(executed)
            * abs(evidence.execution_price - intent.conservative_reference_price)
            * spec.accounting_price_multiplier
        )
        resulting_quantity = ledger_position.quantity + executed
        _consume_capacity(
            capacity_consumption,
            contract_id=position_key.contract_id,
            window_opened_at=intent.trigger_bar_closed_at - timedelta(minutes=10),
            window_closed_at=intent.trigger_bar_closed_at,
            capacity_contracts=(
                evidence.factual_bar_volume * MAXIMUM_PARTICIPATION_BPS // BPS_DENOMINATOR
            ),
            filled_contracts=abs(executed),
        )
        cash += variation_margin - fee
        if resulting_quantity:
            positions[position_key] = V8LedgerPosition(
                position_key,
                resulting_quantity,
                evidence.execution_price,
            )
        else:
            positions.pop(position_key, None)
        fills.append(
            V8LedgerFillEvent(
                event_sequence=len(fills),
                scenario_id=state.scenario_id,
                order_id=evidence.order_id,
                executed_at=intent.trigger_bar_closed_at,
                position_key=position_key,
                signed_contracts=executed,
                execution_price=evidence.execution_price,
                prior_quantity=ledger_position.quantity,
                resulting_quantity=resulting_quantity,
                variation_margin=variation_margin,
                fee=fee,
                turnover_notional=turnover,
                adverse_slippage_notional=adverse_slippage,
                evidence_sha256=evidence.execution_evidence_sha256,
                spec_effective_session_date=event_session,
                spec_snapshot_sha256=spec.snapshot_sha256,
                spec_accounting_as_of=accounting_cutoff,
            )
        )
        fee_total += fee
        turnover_total += turnover
        slippage_total += adverse_slippage
    if evidence.carry_contracts:
        unresolved.append(
            V8UnresolvedOrder(
                order_id=evidence.order_id,
                scenario_id=state.scenario_id,
                requested_contracts=evidence.requested_contracts,
                executed_contracts=evidence.executed_contracts,
                carry_contracts=evidence.carry_contracts,
                reason="corridor_partial_or_zero_capacity_exit",
                evidence_sha256=evidence.execution_evidence_sha256,
            )
        )
    effective_risk_marks = dict(risk_marks or {})
    effective_risk_marks.setdefault(
        position_key.contract_id,
        evidence.execution_price
        if evidence.execution_price is not None
        else intent.conservative_reference_price,
    )
    equity, gross, initial_margin, _ = _portfolio_risk(
        cash,
        positions,
        spec_by_contract,
        effective_risk_marks,
        effective_session_date=event_session,
        accounting_as_of=accounting_cutoff,
    )
    if cash <= 0.0 or equity <= 0.0:
        raise V8LedgerRiskError("corridor exit privel k nonpositive cash/equity")
    if initial_margin > equity + FLOAT_TOLERANCE:
        raise V8LedgerRiskError("corridor exit IM prevysil equity")
    if gross > MAX_GROSS_EXPOSURE * equity + FLOAT_TOLERANCE:
        raise V8LedgerRiskError("corridor exit gross prevysil equity")
    next_state = V8EventLedgerState(
        strategy_id=state.strategy_id,
        scenario_id=state.scenario_id,
        initial_cash=state.initial_cash,
        cash=cash,
        candle_trust_status=state.candle_trust_status,
        evaluation_bundle_sha256=state.evaluation_bundle_sha256,
        trusted_candle_panel_sha256=state.trusted_candle_panel_sha256,
        positions=tuple(positions.values()),
        fills=tuple(fills),
        unresolved_orders=tuple(unresolved),
        capacity_consumption=tuple(capacity_consumption.values()),
        equity_curve=state.equity_curve,
        cumulative_fees=fee_total,
        cumulative_turnover=turnover_total,
        cumulative_adverse_slippage=slippage_total,
    )
    return next_state, reconciled


@dataclass(frozen=True, slots=True)
class V8YearMetric:
    """Calendar-year net return i Sharpe odnogo strategy/scenario."""

    year: int
    net_return: float
    sharpe: float

    def __post_init__(self) -> None:
        """Trebuet development year i finite metrics."""
        if self.year not in DEVELOPMENT_YEARS:
            raise ValueError("year metric vne sealed 2021--2025 development interval")
        if not isfinite(self.net_return) or not isfinite(self.sharpe):
            raise ValueError("year metrics dolzhny byt' finite")


@dataclass(frozen=True, slots=True)
class V8ScenarioMetrics:
    """Net performance i execution audit odnogo fixed scenario."""

    scenario_id: V8ScenarioId
    net_cagr: float
    sharpe: float
    max_drawdown: float
    yearly: tuple[V8YearMetric, ...]
    critical_execution_failure_count: int
    maximum_participation_bps: float
    unknown_capacity_count: int
    unresolved_positions_at_terminal: int
    cumulative_fees: float
    cumulative_turnover: float

    def __post_init__(self) -> None:
        """Proveryaet exact five years i finite risk/audit metrics."""
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        for name in (
            "net_cagr",
            "sharpe",
            "max_drawdown",
            "maximum_participation_bps",
            "cumulative_fees",
            "cumulative_turnover",
        ):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} dolzhen byt' finite")
            if name not in ("net_cagr", "sharpe") and value < 0.0:
                raise ValueError(f"{name} ne mozhet byt' otricatel'nym")
            object.__setattr__(self, name, value)
        yearly = tuple(sorted(self.yearly, key=lambda item: item.year))
        if tuple(item.year for item in yearly) != DEVELOPMENT_YEARS:
            raise ValueError("scenario metrics trebuyut exact 2021--2025 yearly rows")
        object.__setattr__(self, "yearly", yearly)
        for name in (
            "critical_execution_failure_count",
            "unknown_capacity_count",
            "unresolved_positions_at_terminal",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} dolzhen byt' nonnegative int")


@dataclass(frozen=True, slots=True)
class V8StrategyMetricsBundle:
    """Rovno tri scenariya odnogo strategy na obshchih predictions/evidence."""

    strategy_id: str
    prediction_sha256: str
    evaluation_bundle_sha256: str
    scenarios: tuple[V8ScenarioMetrics, ...]

    def __post_init__(self) -> None:
        """Zapreshchaet scenario selection i mixed prediction/evaluation seals."""
        object.__setattr__(
            self, "strategy_id", _require_identifier(self.strategy_id, "strategy_id")
        )
        object.__setattr__(
            self,
            "prediction_sha256",
            _require_sha256(self.prediction_sha256, "prediction_sha256"),
        )
        object.__setattr__(
            self,
            "evaluation_bundle_sha256",
            _require_sha256(self.evaluation_bundle_sha256, "evaluation_bundle_sha256"),
        )
        scenarios = tuple(sorted(self.scenarios, key=lambda item: item.scenario_id.value))
        expected_ids = {item.scenario_id for item in fixed_v8_scenarios()}
        if {item.scenario_id for item in scenarios} != expected_ids or len(scenarios) != 3:
            raise ValueError("strategy metrics trebuyut exact tri fixed scenariya")
        object.__setattr__(self, "scenarios", scenarios)

    def scenario(self, scenario_id: V8ScenarioId | str) -> V8ScenarioMetrics:
        """Vozvrashchaet odin fixed scenario bez fallback ili selection."""
        resolved = V8ScenarioId(scenario_id)
        return next(item for item in self.scenarios if item.scenario_id is resolved)


@dataclass(frozen=True, slots=True)
class V8GateOutcome:
    """Fixed GO/NO-GO checks i otdel'nyi report-only 50-percent stretch."""

    strategy_id: str
    passed: bool
    stretch_50_reached: bool
    checks: tuple[tuple[str, bool], ...]

    def __post_init__(self) -> None:
        """Trebuet exact checks i ne pozvolyaet stretch menyat' passed."""
        strategy_id = _require_identifier(self.strategy_id, "strategy_id")
        if strategy_id not in V8_STRATEGY_IDS:
            raise ValueError("gate outcome strategy vne exact 11 variants")
        if not isinstance(self.passed, bool) or not isinstance(self.stretch_50_reached, bool):
            raise TypeError("gate passed/stretch dolzhny byt' bool")
        checks = tuple(self.checks)
        if tuple(name for name, _ in checks) != V8_GATE_CHECK_IDS or any(
            not isinstance(value, bool) for _, value in checks
        ):
            raise ValueError("gate outcome checks ne sootvetstvuyut fixed protocol")
        if self.passed != all(value for _, value in checks):
            raise ValueError("gate outcome passed ne sootvetstvuet checks")
        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "checks", checks)


@dataclass(frozen=True, slots=True)
class V8GateAndRanking:
    """Gate outcomes dlya 11 strategii i sealed ranking aggressive passing set."""

    outcomes: tuple[V8GateOutcome, ...]
    aggressive_ranking: tuple[CandidateSelectionRecord, ...]

    def __post_init__(self) -> None:
        """Svyazyvaet exact 11 outcomes i ranking tol'ko passing aggressive."""
        outcomes = tuple(self.outcomes)
        if tuple(item.strategy_id for item in outcomes) != V8_STRATEGY_IDS:
            raise ValueError("gate outcomes dolzhny byt' exact core+10 order")
        ranking = tuple(self.aggressive_ranking)
        ranked_ids = tuple(item.candidate_id.value for item in ranking)
        if len(ranked_ids) != len(set(ranked_ids)):
            raise ValueError("aggressive ranking soderzhit duplicate candidate")
        passed_ids = {item.strategy_id for item in outcomes[1:] if item.passed}
        if set(ranked_ids) != passed_ids:
            raise ValueError("aggressive ranking dolzhen soderzhat' vse i tol'ko passing")
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "aggressive_ranking", ranking)


def _returns_from_equity(points: Sequence[V8EquityPoint]) -> tuple[tuple[datetime, float], ...]:
    """Stroit net returns tol'ko iz posledovatel'nyh post-settlement equity points."""
    rows = tuple(points)
    if len(rows) < 2:
        raise ValueError("metrics trebuyut minimum dva equity point")
    result: list[tuple[datetime, float]] = []
    for previous, current in zip(rows, rows[1:], strict=False):
        if current.marked_at <= previous.marked_at:
            raise ValueError("equity points dolzhny byt' strogo chronologichny")
        if previous.equity <= 0.0 or current.equity <= 0.0:
            raise ValueError("equity metrics ne prinimayut ruin/nonpositive equity")
        result.append((current.marked_at, current.equity / previous.equity - 1.0))
    return tuple(result)


def _sharpe(returns: Sequence[float]) -> float:
    """Schitaet annualized population Sharpe s zero dlya constant series."""
    values = tuple(float(item) for item in returns)
    if not values:
        raise ValueError("Sharpe trebuet returns")
    mean_value = sum(values) / len(values)
    variance = sum((item - mean_value) ** 2 for item in values) / len(values)
    if variance <= FLOAT_TOLERANCE:
        return 0.0
    return mean_value / sqrt(variance) * sqrt(TRADING_SESSIONS_PER_YEAR)


def _maximum_drawdown(equity: Sequence[float]) -> float:
    """Schitaet maximum peak-to-trough drawdown po net equity."""
    values = tuple(float(item) for item in equity)
    if not values or any(not isfinite(item) or item <= 0.0 for item in values):
        raise ValueError("drawdown trebuet positive finite equity")
    peak = values[0]
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, 1.0 - value / peak)
    return maximum


def summarize_v8_scenario(
    state: V8EventLedgerState,
    evidence: Sequence[V8ScenarioExecutionEvidence],
) -> V8ScenarioMetrics:
    """Stroit fixed gate metrics iz ledger i ego sobstvennogo execution evidence."""
    if not state.equity_curve:
        raise ValueError("scenario summary trebuet equity curve")
    first_point = state.equity_curve[0]
    if (
        abs(first_point.equity - state.initial_cash) > FLOAT_TOLERANCE
        or abs(first_point.cash - state.initial_cash) > FLOAT_TOLERANCE
        or first_point.gross_notional > FLOAT_TOLERANCE
        or first_point.initial_margin > FLOAT_TOLERANCE
    ):
        raise ValueError("equity curve dolzhna nachinat'sya pre-trade initial-cash anchor")
    if any(item.scenario_id is not state.scenario_id for item in evidence):
        raise ValueError("summary evidence scenario mismatch")
    returns = _returns_from_equity(state.equity_curve)
    net_cagr = (state.equity_curve[-1].equity / state.equity_curve[0].equity) ** (
        TRADING_SESSIONS_PER_YEAR / len(returns)
    ) - 1.0
    yearly_rows: list[V8YearMetric] = []
    for year in DEVELOPMENT_YEARS:
        values = tuple(value for timestamp, value in returns if timestamp.year == year)
        if not values:
            raise ValueError(f"scenario ne imeet returns dlya development year {year}")
        compounded = 1.0
        for value in values:
            compounded *= 1.0 + value
        yearly_rows.append(V8YearMetric(year, compounded - 1.0, _sharpe(values)))
    maximum_participation = 0.0
    unknown_capacity = 0
    critical = 0
    for item in evidence:
        if item.carry_contracts:
            critical += 1
        for leg in item.legs:
            if leg.capacity_contracts is None and item.requested_contracts:
                unknown_capacity += 1
            if leg.factual_volume is None:
                continue
            if leg.factual_volume <= 0:
                if leg.signed_contracts:
                    critical += 1
                continue
            participation = abs(leg.signed_contracts) * BPS_DENOMINATOR / leg.factual_volume
            maximum_participation = max(maximum_participation, participation)
            if participation > MAXIMUM_PARTICIPATION_BPS + FLOAT_TOLERANCE:
                critical += 1
    unresolved_terminal = len(state.unresolved_orders) + len(state.positions)
    return V8ScenarioMetrics(
        scenario_id=state.scenario_id,
        net_cagr=net_cagr,
        sharpe=_sharpe(tuple(value for _, value in returns)),
        max_drawdown=_maximum_drawdown(tuple(item.equity for item in state.equity_curve)),
        yearly=tuple(yearly_rows),
        critical_execution_failure_count=critical,
        maximum_participation_bps=maximum_participation,
        unknown_capacity_count=unknown_capacity,
        unresolved_positions_at_terminal=unresolved_terminal,
        cumulative_fees=state.cumulative_fees,
        cumulative_turnover=state.cumulative_turnover,
    )


def _gate_outcome(bundle: V8StrategyMetricsBundle) -> V8GateOutcome:
    """Primenyayet tol'ko predeclared hard gates bez delay-based selection."""
    primary = bundle.scenario(V8ScenarioId.PRIMARY)
    doubled = bundle.scenario(V8ScenarioId.DOUBLE_COST)
    positive_years = sum(item.net_return > 0.0 for item in primary.yearly)
    worst_year = min(item.net_return for item in primary.yearly)
    checks = (
        ("primary_net_cagr", primary.net_cagr >= PRIMARY_NET_CAGR_MINIMUM),
        ("primary_sharpe", primary.sharpe >= PRIMARY_SHARPE_MINIMUM),
        ("primary_max_drawdown", primary.max_drawdown <= PRIMARY_MAX_DRAWDOWN_MAXIMUM),
        ("positive_year_count", positive_years >= MINIMUM_POSITIVE_YEARS),
        ("worst_calendar_year", worst_year >= WORST_CALENDAR_YEAR_RETURN_MINIMUM),
        ("doubled_cost_cagr", doubled.net_cagr > 0.0),
        ("critical_execution", primary.critical_execution_failure_count == 0),
        (
            "participation",
            primary.maximum_participation_bps <= MAXIMUM_PARTICIPATION_BPS,
        ),
        ("known_capacity", primary.unknown_capacity_count == 0),
        ("terminal_resolution", primary.unresolved_positions_at_terminal == 0),
    )
    return V8GateOutcome(
        strategy_id=bundle.strategy_id,
        passed=all(value for _, value in checks),
        stretch_50_reached=primary.net_cagr >= REPORT_ONLY_STRETCH_CAGR,
        checks=checks,
    )


def build_v8_gate_and_ranking(
    bundles: Sequence[V8StrategyMetricsBundle],
) -> V8GateAndRanking:
    """Validiruet exact 11 strategies i rank'uet tol'ko passing aggressive catalog."""
    rows = tuple(bundles)
    expected_ids = (CORE_STRATEGY_ID, *AGGRESSIVE_CANDIDATE_IDS)
    if tuple(item.strategy_id for item in rows) != expected_ids:
        raise ValueError("gate input dolzhen byt' core + exact 10 candidates v catalog order")
    if len({item.prediction_sha256 for item in rows}) != 1:
        raise ValueError("vse 11 strategies dolzhny ispol'zovat' odni predictions")
    if len({item.evaluation_bundle_sha256 for item in rows}) != 1:
        raise ValueError("vse 11 strategies dolzhny ispol'zovat' odin evaluation bundle")
    outcomes = tuple(_gate_outcome(item) for item in rows)
    annual_metrics: list[CandidateAnnualMetric] = []
    gate_metrics: list[CandidateGateMetric] = []
    for item in rows[1:]:
        candidate_id = AggressiveCandidateId(item.strategy_id)
        primary = item.scenario(V8ScenarioId.PRIMARY)
        doubled = item.scenario(V8ScenarioId.DOUBLE_COST)
        annual_metrics.extend(
            CandidateAnnualMetric(
                candidate_id,
                year.year,
                year.net_return,
                year.sharpe,
                item.evaluation_bundle_sha256,
            )
            for year in primary.yearly
        )
        gate_metrics.append(
            CandidateGateMetric(
                candidate_id=candidate_id,
                prediction_sha256=item.prediction_sha256,
                evaluation_bundle_sha256=item.evaluation_bundle_sha256,
                primary_net_cagr=primary.net_cagr,
                primary_sharpe=primary.sharpe,
                primary_max_drawdown=primary.max_drawdown,
                worst_calendar_year_return=min(row.net_return for row in primary.yearly),
                doubled_cost_cagr=doubled.net_cagr,
                critical_execution_failure_count=primary.critical_execution_failure_count,
                maximum_participation_bps=primary.maximum_participation_bps,
                unknown_capacity_count=primary.unknown_capacity_count,
                unresolved_positions_at_terminal=primary.unresolved_positions_at_terminal,
            )
        )
    ranking = rank_gate_passing_candidates(annual_metrics, gate_metrics)
    return V8GateAndRanking(outcomes=outcomes, aggressive_ranking=ranking)


__all__ = [
    "AGGRESSIVE_CATALOG_SHA256",
    "CORE_STRATEGY_ID",
    "MAX_GROSS_EXPOSURE",
    "TOTAL_STRATEGY_COUNT",
    "V8_GATE_CHECK_IDS",
    "V8_STRATEGY_IDS",
    "V8AssetContractSnapshot",
    "V8CandleTrustStatus",
    "V8ContractSpec",
    "V8CapacityConsumption",
    "V8EquityPoint",
    "V8EffectiveScheduledCandidateExecution",
    "V8EventLedgerState",
    "V8EvaluationLedgerMatrix",
    "V8GateAndRanking",
    "V8GateOutcome",
    "V8LedgerFillEvent",
    "V8LedgerPosition",
    "V8LedgerRiskError",
    "V8OrderBinding",
    "V8OrderCause",
    "V8PositionKey",
    "V8ScenarioExecutionEvidence",
    "V8ScenarioFillLeg",
    "V8ScenarioId",
    "V8ScenarioMetrics",
    "V8ScenarioSpec",
    "V8SealedEvaluationInputBundle",
    "V8SleeveTarget",
    "V8StrategyDecisionSet",
    "V8StrategyMetricsBundle",
    "V8StatefulReplayPolicy",
    "V8TargetFreePrediction",
    "V8TrustedCandleIndex",
    "V8UnresolvedOrder",
    "V8YearMetric",
    "apply_v8_corridor_exit_to_ledger",
    "apply_v8_execution_batch",
    "build_v8_core_path",
    "build_v8_entry_bindings",
    "build_v8_gate_and_ranking",
    "build_v8_long_paired_roll_binding",
    "build_v8_new_sleeve_targets",
    "build_v8_signed_paired_roll_binding",
    "build_v8_sleeve_exit_bindings",
    "build_v8_strategy_decision_set",
    "candidate_execution_evidence_from_primary",
    "canonical_sha256",
    "create_v8_evaluation_ledger_matrix",
    "fixed_v8_scenarios",
    "integer_contracts_for_weight",
    "plan_v8_scenario_execution",
    "reconcile_v8_breakout_execution",
    "reconcile_v8_corridor_exit",
    "select_v8_contract_spec_snapshot",
    "settle_v8_event_ledger",
    "summarize_v8_scenario",
]
