"""Zapechatannye causal aggressive candidates futures-v8 bez PnL i holdout."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from statistics import median
from zoneinfo import ZoneInfo

# Edinyi hard gross cap dlya kazhdogo kandidata bez kreditnogo plecha.
MAX_GROSS_EXPOSURE = 1.0
# Exact logical universe aggressive futures-v8 development kataloga.
V8_ASSET_IDS = ("BR", "MIX", "RI", "SI")
# Timezone decision momenta sealed futures-v8 protokola.
MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")
# Edinoe local'noe vremya development decision.
DECISION_LOCAL_TIME = time(18, 50)
# Granica zablokirovannogo protected holdout.
PROTECTED_HOLDOUT_START = date(2026, 1, 1)
# Exact SHA-256 byte-sealed base protocola, nasledovannogo katalogom.
BASE_PROTOCOL_SHA256 = "e0175b0e02d5a304d90f33f61bd77ed5649005e91e6af50662d4545dc070035d"
# Exact primary execution provenance boundary bez queue-exact zayavleniya.
PRIMARY_EXECUTION_PROVENANCE = "research_only_not_queue_exact"
# Maksimal'naya factual participation v odnom bare v basis points.
MAXIMUM_BAR_PARTICIPATION_BPS = 100
# Chislo pyatidnevnyh sleeves bazovogo v8 portfolio handoff.
HOLDING_SLEEVE_COUNT = 5
# Ravnyi ves odnogo pyatidnevnogo sleeve.
HOLDING_SLEEVE_WEIGHT = 0.20
# Minimal'nyi absolyutnyi target, nizhe kotorogo integer handoff ostanetsya cash.
MINIMUM_SIGNAL_MAGNITUDE = 1e-12
# Razmer take-profit volatility corridor v edinicah ATR.
CORRIDOR_TAKE_PROFIT_ATR = 0.80
# Dal'nii stop-loss volatility corridor v edinicah ATR.
CORRIDOR_STOP_LOSS_ATR = 2.80
# Maksimal'noe chislo assetov v odnom corridor harvest signale.
CORRIDOR_MAX_ASSETS = 2
# Porog volatility expansion dlya corridor harvest.
CORRIDOR_VOLATILITY_RATIO_MINIMUM = 1.15
# Granica nizhnei zony causal 20-session koridora.
CORRIDOR_LOWER_ZONE = 0.20
# Granica verhnei zony causal 20-session koridora.
CORRIDOR_UPPER_ZONE = 0.80
# Minimal'nyi residual score dlya vhoda v corridor.
CORRIDOR_RESIDUAL_SCORE_MINIMUM = 0.15
# Maksimal'naya crash probability dlya corridor mean reversion.
CORRIDOR_CRASH_PROBABILITY_MAXIMUM = 0.35
# Chislo assetov, ostavlyaemyh concentrated dispersion.
DISPERSION_LEG_COUNT = 1
# Minimal'nyi spread residual score dlya concentrated dispersion.
DISPERSION_SCORE_SPREAD_MINIMUM = 0.45
# Minimal'nyi absolyutnyi residual score dlya concentrated dispersion.
DISPERSION_ABSOLUTE_SCORE_MINIMUM = 0.20
# Maksimal'naya abstain probability concentrated dispersion.
DISPERSION_ABSTAIN_PROBABILITY_MAXIMUM = 0.50
# Chislo posledovatel'nyh urovnei breakout pyramiding.
BREAKOUT_PYRAMID_LEVELS = 3
# ATR multiplier trailing stop dlya breakout pyramiding.
BREAKOUT_TRAILING_STOP_ATR = 2.00
# Minimal'naya trend probability dlya breakout pyramiding.
BREAKOUT_TREND_PROBABILITY_MINIMUM = 0.50
# Minimal'nyi residual score v napravlenii breakout.
BREAKOUT_RESIDUAL_SCORE_MINIMUM = 0.25
# Minimal'nyi volatility expansion dlya breakout pyramiding.
BREAKOUT_VOLATILITY_RATIO_MINIMUM = 1.10
# Granica long breakout v causal range position.
BREAKOUT_LONG_RANGE_POSITION_MINIMUM = 1.0
# Granica short breakout v causal range position.
BREAKOUT_SHORT_RANGE_POSITION_MAXIMUM = 0.0
# Granica trend regime dlya regime switch.
REGIME_TREND_PROBABILITY_MINIMUM = 0.55
# Granica normal regime dlya regime switch mean reversion.
REGIME_NORMAL_PROBABILITY_MINIMUM = 0.55
# Minimal'nyi direction agreement dlya regime switch.
REGIME_SCORE_MINIMUM = 0.15
# Granica crash probability dlya convex defense.
CRASH_PROBABILITY_MINIMUM = 0.40
# Minimal'nyi factor score dlya crash reversal.
CRASH_FACTOR_SCORE_MINIMUM = 0.20
# Minimal'naya sila carry z-score.
CARRY_Z_MINIMUM = 0.40
# Minimal'naya sila momentum dlya carry confirmation.
CARRY_MOMENTUM_MINIMUM = 0.01
# Minimal'naya sila residual score dlya carry confirmation.
CARRY_RESIDUAL_SCORE_MINIMUM = 0.15
# Porog crowd z-score dlya CFTC unwind.
CFTC_CROWD_Z_MINIMUM = 1.50
# Minimal'nyi reversal momentum protiv crowded napravleniya.
CFTC_REVERSAL_MOMENTUM_MINIMUM = 0.005
# Porog absolute rate-shock z-score.
MACRO_RATE_SHOCK_Z_MINIMUM = 1.50
# Porog absolute FX-shock z-score.
MACRO_FX_SHOCK_Z_MINIMUM = 1.50
# Minimal'nyi model SNR dlya confidence concentration.
CONFIDENCE_SNR_MINIMUM = 1.75
# Maksimal'naya abstain probability dlya confidence concentration.
CONFIDENCE_ABSTAIN_MAXIMUM = 0.25
# Chislo samyh sil'nyh assetov confidence concentration.
CONFIDENCE_MAX_ASSETS = 1
# Porog volatility expansion dlya expansion breakout.
VOLATILITY_BREAKOUT_RATIO_MINIMUM = 1.50
# Porog volume expansion dlya expansion breakout.
VOLUME_BREAKOUT_RATIO_MINIMUM = 1.30
# Minimal'nyi residual score dlya expansion breakout.
VOLATILITY_BREAKOUT_SCORE_MINIMUM = 0.20
# Granica long volatility expansion breakout.
VOLATILITY_BREAKOUT_LONG_RANGE_POSITION_MINIMUM = 1.0
# Granica short volatility expansion breakout.
VOLATILITY_BREAKOUT_SHORT_RANGE_POSITION_MAXIMUM = 0.0
# Maksimal'noe chislo assetov expansion breakout.
VOLATILITY_BREAKOUT_MAX_ASSETS = 2
# Fiksirovannye gody adaptive development sravneniya.
DEVELOPMENT_YEARS = (2021, 2022, 2023, 2024, 2025)
# Minimal'noe chislo polozhitel'nyh godov dlya selection gate.
MINIMUM_POSITIVE_YEARS = 4
# Maksimal'naya factual participation v basis points.
MAXIMUM_PARTICIPATION_BPS = 100
# Minimal'nyi aggregate primary net CAGR core v8 gate.
PRIMARY_NET_CAGR_MINIMUM = 0.08
# Minimal'nyi aggregate primary Sharpe core v8 gate.
PRIMARY_SHARPE_MINIMUM = 0.50
# Maksimal'naya primary max drawdown core v8 gate.
PRIMARY_MAX_DRAWDOWN_MAXIMUM = 0.25
# Minimal'nyi worst calendar year return core v8 gate.
WORST_CALENDAR_YEAR_RETURN_MINIMUM = -0.10
# Stretch 50 procentov CAGR tol'ko dlya otcheta, ne dlya vybora.
REPORT_ONLY_STRETCH_CAGR = 0.50
# Exact prodolzhitel'nost' factual intraday bara.
TEN_MINUTE_BAR_DURATION = timedelta(minutes=10)
# Sdvig ot D18:50 do zakrytiya primary 19:20--19:30 execution window.
PRIMARY_ENTRY_WINDOW_CLOSE_DELAY = timedelta(minutes=40)
# Yarlyk development rezultatov posle izucheniya predydushchih versii.
DEVELOPMENT_STATUS = "adaptive_development_backtest_not_fresh_oos"


class AggressiveCandidateId(StrEnum):
    """Desyat' exact candidate ID, zapechatannyh do lyubogo novogo PnL."""

    VOLATILITY_CORRIDOR_HARVEST = "volatility_corridor_harvest"
    CONCENTRATED_RESIDUAL_DISPERSION = "concentrated_residual_dispersion"
    BREAKOUT_PYRAMIDING_TRAILING_STOP = "breakout_pyramiding_trailing_stop"
    REGIME_SWITCH_TREND_REVERSION = "regime_switch_trend_reversion"
    CRASH_EXPERT_CONVEX_DEFENSE = "crash_expert_convex_defense"
    CARRY_MOMENTUM_CONFIRMATION = "carry_momentum_confirmation"
    CFTC_CROWDED_UNWIND = "cftc_crowded_unwind"
    MACRO_SHOCK_ROTATION = "macro_shock_rotation"
    CONFIDENCE_CONCENTRATION = "confidence_concentration"
    VOLATILITY_EXPANSION_BREAKOUT = "volatility_expansion_breakout"


# Kanonicheskii poryadok kandidata yavlyaetsya chast'yu byte-sealed contracta.
AGGRESSIVE_CANDIDATE_IDS = tuple(candidate.value for candidate in AggressiveCandidateId)


class CorridorPositionStatus(StrEnum):
    """Sostoyanie odnoi stateful corridor pozicii."""

    OPEN = "open"
    EXIT_PENDING = "exit_pending"
    CLOSED = "closed"
    CARRY_UNRESOLVED = "carry_unresolved"


@dataclass(frozen=True, slots=True)
class FixedCandidateSpec:
    """Audit-opisanie kandidata bez optimiziruemyh parametrov."""

    candidate_id: AggressiveCandidateId
    family: str
    stateful: bool
    input_channels: tuple[str, ...]
    numeric_constants: tuple[tuple[str, float | int], ...]


@dataclass(frozen=True, slots=True)
class PointInTimeObservation:
    """Odin vypusk vneshnego kanala s proveryaemym publication provenance."""

    value: float
    published_at: datetime
    source_id: str
    observation_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        """Fail-closed proveryaet znachenie, publication timestamp i source seal."""
        object.__setattr__(self, "value", _require_finite(self.value, "pit value"))
        object.__setattr__(
            self,
            "published_at",
            _require_aware(self.published_at, "published_at"),
        )
        for label in ("source_id", "observation_id"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError(f"{label} dolzhen byt' nepustym i bez kraevyh probelov")
        object.__setattr__(
            self,
            "source_sha256",
            _require_sha256(self.source_sha256, "source_sha256"),
        )


@dataclass(frozen=True, slots=True)
class CausalAssetSnapshot:
    """Tol'ko dostupnyi k decision momentu model i market snapshot odnogo asseta."""

    asset_id: str
    known_at: datetime
    factor_decision_score: float | None
    residual_decision_score: float | None
    residual_location: float | None
    total_scale: float | None
    abstain_probability: float | None
    normal_probability: float | None
    trend_probability: float | None
    crash_probability: float | None
    close: float | None
    atr_20: float | None
    daily_volatility_20: float | None
    momentum_20: float | None
    range_position_20: float | None
    volatility_ratio_20: float | None
    volume_ratio_20: float | None
    market_data_sha256: str | None
    carry_z: PointInTimeObservation | None
    cftc_crowd_z: PointInTimeObservation | None
    key_rate_change_z: PointInTimeObservation | None
    usd_rub_return_z: PointInTimeObservation | None
    model_input_valid: bool = True
    decision_market_valid: bool = True
    planned_contract_valid: bool = True
    invalid_reason_codes: tuple[str, ...] = ()
    planned_contract_id: str | None = None
    nominal_maturity_date: date | None = None
    nominal_span_rule: str | None = None
    validity_provenance_sha256: str | None = None

    def __post_init__(self) -> None:
        """Fail-closed proveryaet finite values, mask granicy i timezone."""
        if not self.asset_id or self.asset_id.strip() != self.asset_id:
            raise ValueError("asset_id dolzhen byt' nepustym i bez kraevyh probelov")
        object.__setattr__(self, "known_at", _require_aware(self.known_at, "known_at"))
        model_fields = (
            "factor_decision_score",
            "residual_decision_score",
            "residual_location",
            "total_scale",
            "abstain_probability",
            "normal_probability",
            "trend_probability",
            "crash_probability",
        )
        market_fields = (
            "close",
            "atr_20",
            "daily_volatility_20",
            "momentum_20",
            "range_position_20",
            "volatility_ratio_20",
            "volume_ratio_20",
        )
        for name in (*model_fields, *market_fields):
            value = getattr(self, name)
            if value is not None:
                _require_finite(value, name)
        for name in ("model_input_valid", "decision_market_valid", "planned_contract_valid"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} dolzhen byt' exact bool")
        if self.model_input_valid and any(getattr(self, name) is None for name in model_fields):
            raise ValueError("model_input_valid trebuet vse finite model fields")
        if self.decision_market_valid and (
            any(getattr(self, name) is None for name in market_fields)
            or self.market_data_sha256 is None
        ):
            raise ValueError("decision_market_valid trebuet vse finite current-session fields")
        if self.market_data_sha256 is not None:
            object.__setattr__(
                self,
                "market_data_sha256",
                _require_sha256(self.market_data_sha256, "market_data_sha256"),
            )
        for name in ("carry_z", "cftc_crowd_z", "key_rate_change_z", "usd_rub_return_z"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, PointInTimeObservation):
                raise TypeError(f"{name} dolzhen byt' PointInTimeObservation ili None")
        if self.total_scale is not None and self.total_scale <= 0.0:
            raise ValueError("total_scale dolzhen byt' > 0")
        if any(
            value is not None and value <= 0.0
            for value in (self.close, self.atr_20, self.daily_volatility_20)
        ):
            raise ValueError("close, atr_20 i daily_volatility_20 dolzhny byt' > 0")
        if any(
            value is not None and value < 0.0
            for value in (self.volatility_ratio_20, self.volume_ratio_20)
        ):
            raise ValueError("volatility i volume ratios ne mogut byt' otricatel'nymi")
        probabilities = (
            self.abstain_probability,
            self.normal_probability,
            self.trend_probability,
            self.crash_probability,
        )
        present_probabilities = tuple(value for value in probabilities if value is not None)
        if present_probabilities and len(present_probabilities) != len(probabilities):
            raise ValueError("regime probabilities dolzhny byt' libo vse, libo None")
        if any(value < 0.0 or value > 1.0 for value in present_probabilities):
            raise ValueError("probabilities dolzhny byt' v [0, 1]")
        if present_probabilities and abs(sum(present_probabilities[1:]) - 1.0) > 1e-6:
            raise ValueError("regime probabilities dolzhny summirovat'sya v 1")
        reasons = tuple(sorted(set(self.invalid_reason_codes)))
        if any(not reason or reason.strip() != reason for reason in reasons):
            raise ValueError("invalid_reason_codes dolzhny byt' nepustymi identifierami")
        if self.strategy_eligible and reasons:
            raise ValueError("validnyi asset ne mozhet imet' invalid_reason_codes")
        if not self.strategy_eligible and not reasons:
            raise ValueError("invalidnyi asset trebuet explicit reason code")
        object.__setattr__(self, "invalid_reason_codes", reasons)
        if self.planned_contract_id is not None and (
            not self.planned_contract_id
            or self.planned_contract_id.strip() != self.planned_contract_id
        ):
            raise ValueError("planned_contract_id dolzhen byt' nepustym bez kraevyh probelov")
        if self.nominal_maturity_date is not None:
            object.__setattr__(
                self,
                "nominal_maturity_date",
                _require_date(self.nominal_maturity_date, "nominal_maturity_date"),
            )
        if self.nominal_span_rule is not None and (
            not self.nominal_span_rule or self.nominal_span_rule.strip() != self.nominal_span_rule
        ):
            raise ValueError("nominal_span_rule dolzhen byt' nepustym")
        if self.validity_provenance_sha256 is not None:
            object.__setattr__(
                self,
                "validity_provenance_sha256",
                _require_sha256(
                    self.validity_provenance_sha256,
                    "validity_provenance_sha256",
                ),
            )

    @property
    def strategy_eligible(self) -> bool:
        """Vozvrashchaet conjunction vseh D-known validity mask bez future execution."""
        return self.model_input_valid and self.decision_market_valid and self.planned_contract_valid


@dataclass(frozen=True, slots=True)
class CausalDecisionContext:
    """Immutable exact development snapshot s vychislyaemym full input seal."""

    decision_at: datetime
    assets: tuple[CausalAssetSnapshot, ...]
    prediction_sha256: str
    input_bundle_sha256: str = field(init=False)
    base_protocol_sha256: str = BASE_PROTOCOL_SHA256

    def __post_init__(self) -> None:
        """Zapreshchaet future/PIT drift, holdout, nepolnyi universe i hash drift."""
        decision_at = _require_development_decision_time(self.decision_at)
        prediction_sha256 = _require_sha256(
            self.prediction_sha256,
            "prediction_sha256",
        )
        base_protocol_sha256 = _require_sha256(
            self.base_protocol_sha256,
            "base_protocol_sha256",
        )
        if base_protocol_sha256 != BASE_PROTOCOL_SHA256:
            raise ValueError("base_protocol_sha256 ne sootvetstvuet sealed aggressive contract")
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("asset_id ne dolzhny povtoryat'sya")
        if tuple(sorted(ids)) != V8_ASSET_IDS:
            raise ValueError("decision context trebuet exact full BR/MIX/RI/SI universe")
        pit_releases: dict[tuple[str, str, str, str], tuple[float, datetime]] = {}
        for asset in self.assets:
            if asset.known_at.astimezone(UTC) > decision_at:
                raise ValueError("future observation posle decision_at zapreshchena")
            for label in (
                "carry_z",
                "cftc_crowd_z",
                "key_rate_change_z",
                "usd_rub_return_z",
            ):
                observation = getattr(asset, label)
                if observation is not None and observation.published_at > decision_at:
                    raise ValueError(f"future publication {label} posle decision_at zapreshchena")
                if observation is not None:
                    release_key = (
                        label,
                        observation.source_id,
                        observation.observation_id,
                        observation.source_sha256,
                    )
                    release_value = (observation.value, observation.published_at)
                    previous_release = pit_releases.setdefault(release_key, release_value)
                    if previous_release != release_value:
                        raise ValueError(
                            "odin PIT release ne mozhet imet' raznye values/timestamps"
                        )
        object.__setattr__(self, "decision_at", decision_at)
        ordered_assets = tuple(sorted(self.assets, key=lambda item: item.asset_id))
        object.__setattr__(self, "assets", ordered_assets)
        object.__setattr__(self, "prediction_sha256", prediction_sha256)
        object.__setattr__(self, "base_protocol_sha256", base_protocol_sha256)
        object.__setattr__(
            self,
            "input_bundle_sha256",
            _input_bundle_sha256(decision_at, ordered_assets, prediction_sha256),
        )

    @property
    def strategy_assets(self) -> tuple[CausalAssetSnapshot, ...]:
        """Ostavlyaet tol'ko polnost'yu D-known valid assets do cross-section operacii."""
        return tuple(asset for asset in self.assets if asset.strategy_eligible)


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    """Bounded fractional target do obshchego v8 integer execution handoff."""

    candidate_id: AggressiveCandidateId
    decision_at: datetime
    prediction_sha256: str
    input_bundle_sha256: str
    base_protocol_sha256: str
    target_weights: tuple[tuple[str, float], ...]
    holding_sleeve_count: int = HOLDING_SLEEVE_COUNT
    holding_sleeve_weight: float = HOLDING_SLEEVE_WEIGHT
    integer_handoff: str = "truncate_toward_zero_no_trade_below_one_contract"

    def __post_init__(self) -> None:
        """Fiksiruet stable sort, unique assets i gross bez plecha."""
        object.__setattr__(self, "candidate_id", AggressiveCandidateId(self.candidate_id))
        object.__setattr__(
            self,
            "decision_at",
            _require_development_decision_time(self.decision_at),
        )
        object.__setattr__(
            self,
            "prediction_sha256",
            _require_sha256(self.prediction_sha256, "prediction_sha256"),
        )
        object.__setattr__(
            self,
            "input_bundle_sha256",
            _require_sha256(self.input_bundle_sha256, "input_bundle_sha256"),
        )
        protocol_sha = _require_sha256(self.base_protocol_sha256, "base_protocol_sha256")
        if protocol_sha != BASE_PROTOCOL_SHA256:
            raise ValueError("CandidateDecision base protocol seal drift")
        object.__setattr__(self, "base_protocol_sha256", protocol_sha)
        ordered = tuple(sorted(self.target_weights))
        if len({asset for asset, _ in ordered}) != len(ordered):
            raise ValueError("target_weights soderzhat duplicate asset")
        for asset, weight in ordered:
            if asset not in V8_ASSET_IDS:
                raise ValueError("target asset dolzhen vhodit' v sealed universe")
            _require_finite(weight, "target_weight")
            if abs(weight) > 1.0 + 1e-12:
                raise ValueError("odin target ne mozhet prevyshat' 1")
        if sum(abs(weight) for _, weight in ordered) > MAX_GROSS_EXPOSURE + 1e-12:
            raise ValueError("candidate gross ne mozhet prevyshat' 1")
        if self.holding_sleeve_count != HOLDING_SLEEVE_COUNT:
            raise ValueError("v8 candidate trebuet rovno pyat' sleeves")
        if self.holding_sleeve_weight != HOLDING_SLEEVE_WEIGHT:
            raise ValueError("v8 candidate trebuet sleeve weight 0.20")
        object.__setattr__(self, "target_weights", ordered)

    @property
    def gross_exposure(self) -> float:
        """Vozvrashchaet gross target do integer contract rounding."""
        return sum(abs(weight) for _, weight in self.target_weights)


@dataclass(frozen=True, slots=True)
class HoldingSleeveSchedule:
    """Sealed common-session schedule odnogo pyatidnevnogo sleeve."""

    sleeve_id: str
    calendar_sha256: str
    entry_common_session_sequence_id: int
    exit_common_session_sequence_id: int
    entry_window_closed_at: datetime
    exit_window_closed_at: datetime

    def __post_init__(self) -> None:
        """Trebuet exact D+5 sequence i obe 19:30 Moscow granicy do holdout."""
        object.__setattr__(self, "sleeve_id", _require_identifier(self.sleeve_id, "sleeve_id"))
        object.__setattr__(
            self,
            "calendar_sha256",
            _require_sha256(self.calendar_sha256, "calendar_sha256"),
        )
        entry_sequence = _require_nonnegative_int(
            self.entry_common_session_sequence_id,
            "entry_common_session_sequence_id",
        )
        exit_sequence = _require_nonnegative_int(
            self.exit_common_session_sequence_id,
            "exit_common_session_sequence_id",
        )
        if exit_sequence != entry_sequence + HOLDING_SLEEVE_COUNT:
            raise ValueError("sleeve exit sequence dolzhen byt' rovno D+5")
        entry_close = _require_execution_window_close(
            self.entry_window_closed_at,
            "entry_window_closed_at",
        )
        exit_close = _require_execution_window_close(
            self.exit_window_closed_at,
            "exit_window_closed_at",
        )
        if exit_close <= entry_close:
            raise ValueError("sleeve exit dolzhen byt' posle entry")
        calendar_days = (
            exit_close.astimezone(MOSCOW_TIMEZONE).date()
            - entry_close.astimezone(MOSCOW_TIMEZONE).date()
        ).days
        if calendar_days < HOLDING_SLEEVE_COUNT:
            raise ValueError("D+5 common sessions ne mogut zakonchit'sya ran'she 5 calendar days")
        object.__setattr__(self, "entry_common_session_sequence_id", entry_sequence)
        object.__setattr__(self, "exit_common_session_sequence_id", exit_sequence)
        object.__setattr__(self, "entry_window_closed_at", entry_close)
        object.__setattr__(self, "exit_window_closed_at", exit_close)


@dataclass(frozen=True, slots=True)
class CandidateExecutionEvidence:
    """Typed boundary factual primary execution dlya candidate entry/rebalance."""

    candidate_id: AggressiveCandidateId
    decision_at: datetime
    prediction_sha256: str
    input_bundle_sha256: str
    sleeve_id: str
    asset_id: str
    contract_id: str
    order_id: str
    common_session_sequence_id: int
    execution_bar_sequence_id: int
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    observed_capacity_contracts: int
    realized_capacity_contracts: int
    execution_window_closed_at: datetime
    execution_price: float | None
    execution_evidence_sha256: str
    provenance: str = PRIMARY_EXECUTION_PROVENANCE

    def __post_init__(self) -> None:
        """Fail-closed svyazyvaet signed fill s exact schedule, cap i input seal."""
        object.__setattr__(self, "candidate_id", AggressiveCandidateId(self.candidate_id))
        decision = _require_development_decision_time(self.decision_at)
        object.__setattr__(self, "decision_at", decision)
        for label in ("prediction_sha256", "input_bundle_sha256", "execution_evidence_sha256"):
            object.__setattr__(self, label, _require_sha256(getattr(self, label), label))
        for label in ("sleeve_id", "contract_id", "order_id"):
            object.__setattr__(self, label, _require_identifier(getattr(self, label), label))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("execution asset_id vne sealed universe")
        for label in ("common_session_sequence_id", "execution_bar_sequence_id"):
            object.__setattr__(self, label, _require_nonnegative_int(getattr(self, label), label))
        requested = _require_nonzero_int(self.requested_contracts, "requested_contracts")
        executed = _require_int(self.executed_contracts, "executed_contracts")
        carry = _require_int(self.carry_contracts, "carry_contracts")
        if executed and _sign(float(executed)) != _sign(float(requested)):
            raise ValueError("executed direction ne sootvetstvuet requested")
        if abs(executed) > abs(requested) or carry != requested - executed:
            raise ValueError("execution quantity/carry invariant narushen")
        observed = _require_nonnegative_int(
            self.observed_capacity_contracts,
            "observed_capacity_contracts",
        )
        realized = _require_nonnegative_int(
            self.realized_capacity_contracts,
            "realized_capacity_contracts",
        )
        if abs(executed) > min(observed, realized):
            raise ValueError("executed contracts prevysili factual capacity")
        window_close = _require_execution_window_close(
            self.execution_window_closed_at,
            "execution_window_closed_at",
        )
        if window_close != decision + PRIMARY_ENTRY_WINDOW_CLOSE_DELAY:
            raise ValueError("entry execution window ne sootvetstvuet D18:50 schedule")
        if executed:
            price = _require_positive(self.execution_price, "execution_price")
        elif self.execution_price is not None:
            raise ValueError("zero execution ne mozhet imet' execution_price")
        else:
            price = None
        if self.provenance != PRIMARY_EXECUTION_PROVENANCE:
            raise ValueError("execution provenance ne sootvetstvuet primary boundary")
        object.__setattr__(self, "requested_contracts", requested)
        object.__setattr__(self, "executed_contracts", executed)
        object.__setattr__(self, "carry_contracts", carry)
        object.__setattr__(self, "observed_capacity_contracts", observed)
        object.__setattr__(self, "realized_capacity_contracts", realized)
        object.__setattr__(self, "execution_window_closed_at", window_close)
        object.__setattr__(self, "execution_price", price)

    @property
    def fully_filled(self) -> bool:
        """Pokazyvaet exact full fill bez carry."""
        return self.executed_contracts == self.requested_contracts and self.carry_contracts == 0


@dataclass(frozen=True, slots=True)
class ScheduledCandidateExecution:
    """Atomarnaya para sealed sleeve schedule i factual execution evidence."""

    schedule: HoldingSleeveSchedule
    evidence: CandidateExecutionEvidence

    def __post_init__(self) -> None:
        """Svyazyvaet sleeve, sequence i exact entry window bez caller timestamps."""
        if not isinstance(self.schedule, HoldingSleeveSchedule):
            raise TypeError("schedule dolzhen byt' HoldingSleeveSchedule")
        if not isinstance(self.evidence, CandidateExecutionEvidence):
            raise TypeError("evidence dolzhen byt' CandidateExecutionEvidence")
        if self.evidence.sleeve_id != self.schedule.sleeve_id:
            raise ValueError("execution sleeve_id ne sootvetstvuet schedule")
        if (
            self.evidence.common_session_sequence_id
            != self.schedule.entry_common_session_sequence_id
        ):
            raise ValueError("execution common-session sequence ne sootvetstvuet schedule")
        if self.evidence.execution_window_closed_at != self.schedule.entry_window_closed_at:
            raise ValueError("execution window ne sootvetstvuet sleeve entry")
        if (
            self.evidence.decision_at.astimezone(MOSCOW_TIMEZONE).date()
            != self.schedule.entry_window_closed_at.astimezone(MOSCOW_TIMEZONE).date()
        ):
            raise ValueError("decision i sleeve entry dolzhny byt' v odnu common session")


class BreakoutAction(StrEnum):
    """Tip predeclared breakout target transition do factual execution."""

    ENTER = "enter"
    ADD = "add"
    HOLD = "hold"
    EXIT_TRAIL = "exit_trail"
    EXIT_REVERSAL = "exit_reversal"


@dataclass(frozen=True, slots=True)
class BreakoutAssetState:
    """Fakticheski podtverzhdennyi pyramid level i monotone trailing extreme."""

    asset_id: str
    contract_id: str
    direction: int
    pyramid_level: int
    extreme_close: float
    last_filled_sleeve_id: str
    last_filled_order_id: str
    last_calendar_sha256: str
    last_execution_evidence_sha256: str

    def __post_init__(self) -> None:
        """Proveryaet napravlenie, level, contract i factual execution seals."""
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("breakout asset_id vne sealed universe")
        object.__setattr__(
            self,
            "contract_id",
            _require_identifier(self.contract_id, "contract_id"),
        )
        object.__setattr__(
            self,
            "last_filled_sleeve_id",
            _require_identifier(self.last_filled_sleeve_id, "last_filled_sleeve_id"),
        )
        object.__setattr__(
            self,
            "last_filled_order_id",
            _require_identifier(self.last_filled_order_id, "last_filled_order_id"),
        )
        object.__setattr__(
            self,
            "last_calendar_sha256",
            _require_sha256(self.last_calendar_sha256, "last_calendar_sha256"),
        )
        object.__setattr__(
            self,
            "last_execution_evidence_sha256",
            _require_sha256(
                self.last_execution_evidence_sha256,
                "last_execution_evidence_sha256",
            ),
        )
        if self.direction not in (-1, 1):
            raise ValueError("direction dolzhen byt' -1 ili +1")
        if not 1 <= self.pyramid_level <= BREAKOUT_PYRAMID_LEVELS:
            raise ValueError("pyramid_level vne fixed diapazona")
        object.__setattr__(
            self,
            "extreme_close",
            _require_positive(self.extreme_close, "extreme_close"),
        )


@dataclass(frozen=True, slots=True)
class BreakoutAssetIntent:
    """Target transition, kotoryi ne menyaet filled level do execution evidence."""

    asset_id: str
    action: BreakoutAction
    prior_direction: int
    prior_level: int
    desired_direction: int
    desired_level: int
    next_extreme_close: float

    def __post_init__(self) -> None:
        """Proveryaet dopustimuyu state machine geometriyu breakout intent."""
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("breakout intent asset_id vne sealed universe")
        object.__setattr__(self, "action", BreakoutAction(self.action))
        if self.prior_direction not in (-1, 0, 1) or self.desired_direction not in (-1, 0, 1):
            raise ValueError("breakout intent direction vne -1/0/+1")
        if not 0 <= self.prior_level <= BREAKOUT_PYRAMID_LEVELS:
            raise ValueError("breakout prior_level nevaliden")
        if not 0 <= self.desired_level <= BREAKOUT_PYRAMID_LEVELS:
            raise ValueError("breakout desired_level nevaliden")
        object.__setattr__(
            self,
            "next_extreme_close",
            _require_positive(self.next_extreme_close, "next_extreme_close"),
        )


@dataclass(frozen=True, slots=True)
class BreakoutUnresolvedExecution:
    """Polnyi audit partial/zero fill, kotoryi blokiruet dal'neishii level advance."""

    asset_id: str
    contract_id: str
    sleeve_id: str
    order_id: str
    action: BreakoutAction
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    calendar_sha256: str
    execution_evidence_sha256: str

    def __post_init__(self) -> None:
        """Sohranyaet exact unresolved quantity i typed execution identity."""
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("breakout unresolved asset vne sealed universe")
        for label in ("contract_id", "sleeve_id", "order_id"):
            object.__setattr__(self, label, _require_identifier(getattr(self, label), label))
        action = BreakoutAction(self.action)
        if action is BreakoutAction.HOLD:
            raise ValueError("HOLD ne mozhet sozdat' unresolved execution")
        object.__setattr__(self, "action", action)
        requested = _require_nonzero_int(self.requested_contracts, "requested_contracts")
        executed = _require_int(self.executed_contracts, "executed_contracts")
        carry = _require_int(self.carry_contracts, "carry_contracts")
        if executed and _sign(float(executed)) != _sign(float(requested)):
            raise ValueError("unresolved executed direction mismatch")
        if abs(executed) > abs(requested) or carry != requested - executed:
            raise ValueError("unresolved quantity/carry invariant narushen")
        if carry == 0:
            raise ValueError("unresolved execution trebuet nonzero carry")
        object.__setattr__(self, "requested_contracts", requested)
        object.__setattr__(self, "executed_contracts", executed)
        object.__setattr__(self, "carry_contracts", carry)
        object.__setattr__(
            self,
            "calendar_sha256",
            _require_sha256(self.calendar_sha256, "calendar_sha256"),
        )
        object.__setattr__(
            self,
            "execution_evidence_sha256",
            _require_sha256(
                self.execution_evidence_sha256,
                "execution_evidence_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class BreakoutPyramidState:
    """Filled breakout state posle poslednego reconciled execution evidence."""

    last_decision_at: datetime | None = None
    assets: tuple[BreakoutAssetState, ...] = ()
    unresolved_executions: tuple[BreakoutUnresolvedExecution, ...] = ()

    def __post_init__(self) -> None:
        """Zapreshchaet duplicate asset/unresolved i normalizuet poryadok."""
        if self.last_decision_at is not None:
            object.__setattr__(
                self,
                "last_decision_at",
                _require_development_decision_time(self.last_decision_at),
            )
        if len({state.asset_id for state in self.assets}) != len(self.assets):
            raise ValueError("breakout state soderzhit duplicate asset")
        if len({item.asset_id for item in self.unresolved_executions}) != len(
            self.unresolved_executions
        ):
            raise ValueError("breakout unresolved executions soderzhat duplicate asset")
        unresolved = tuple(
            sorted(self.unresolved_executions, key=lambda item: item.asset_id)
        )
        ordered_assets = tuple(sorted(self.assets, key=lambda item: item.asset_id))
        object.__setattr__(self, "assets", ordered_assets)
        object.__setattr__(self, "unresolved_executions", unresolved)

    @property
    def unresolved_asset_ids(self) -> tuple[str, ...]:
        """Vozvrashchaet stable IDs vseh partial/zero fill blokirovok."""
        return tuple(item.asset_id for item in self.unresolved_executions)


@dataclass(frozen=True, slots=True)
class BreakoutLockedPosition:
    """Carry-only marker: invalid D snapshot ne sozdaet target ili order intent."""

    state: BreakoutAssetState
    decision_at: datetime
    reason_codes: tuple[str, ...]
    input_bundle_sha256: str

    def __post_init__(self) -> None:
        """Svyazyvaet frozen factual state s invalid D context i ego seal."""
        if not isinstance(self.state, BreakoutAssetState):
            raise TypeError("locked breakout state dolzhen byt' BreakoutAssetState")
        object.__setattr__(
            self,
            "decision_at",
            _require_development_decision_time(self.decision_at),
        )
        reasons = tuple(sorted(set(self.reason_codes)))
        if not reasons or any(not value or value.strip() != value for value in reasons):
            raise ValueError("locked breakout position trebuet explicit reason codes")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "input_bundle_sha256",
            _require_sha256(self.input_bundle_sha256, "input_bundle_sha256"),
        )


@dataclass(frozen=True, slots=True)
class CandidateRun:
    """Pure candidate target i execution intents bez neproverennogo state advance."""

    decision: CandidateDecision
    breakout_state: BreakoutPyramidState | None = None
    breakout_intents: tuple[BreakoutAssetIntent, ...] = ()
    breakout_locked_positions: tuple[BreakoutLockedPosition, ...] = ()

    def __post_init__(self) -> None:
        """Zapreshchaet odnovremennyi order intent i carry-only marker odnogo asseta."""
        intent_assets = {item.asset_id for item in self.breakout_intents}
        locked_assets = {item.state.asset_id for item in self.breakout_locked_positions}
        if len(locked_assets) != len(self.breakout_locked_positions):
            raise ValueError("breakout locked positions ne dolzhny dublit' asset")
        if intent_assets & locked_assets:
            raise ValueError("breakout asset ne mozhet byt' locked i imet' order intent")
        object.__setattr__(
            self,
            "breakout_locked_positions",
            tuple(
                sorted(
                    self.breakout_locked_positions,
                    key=lambda item: item.state.asset_id,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class CorridorExitIntent:
    """Predeclared exit intent posle causal factual trigger bez synthetic close."""

    intent_id: str
    position_id: str
    sleeve_id: str
    asset_id: str
    contract_id: str
    trigger_reason: str
    trigger_bar_sequence_id: int
    trigger_bar_closed_at: datetime
    requested_contracts: int
    conservative_reference_price: float
    trigger_bar_volume: int
    prediction_sha256: str
    input_bundle_sha256: str

    def __post_init__(self) -> None:
        """Proveryaet signed exit, factual trigger i immutable provenance."""
        for label in ("intent_id", "position_id", "sleeve_id", "contract_id"):
            object.__setattr__(self, label, _require_identifier(getattr(self, label), label))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("corridor exit asset vne sealed universe")
        if not self.trigger_reason:
            raise ValueError("corridor trigger_reason ne mozhet byt' pustym")
        object.__setattr__(
            self,
            "trigger_bar_sequence_id",
            _require_nonnegative_int(self.trigger_bar_sequence_id, "trigger_bar_sequence_id"),
        )
        object.__setattr__(
            self,
            "trigger_bar_closed_at",
            _require_aware(self.trigger_bar_closed_at, "trigger_bar_closed_at"),
        )
        object.__setattr__(
            self,
            "requested_contracts",
            _require_nonzero_int(self.requested_contracts, "requested_contracts"),
        )
        object.__setattr__(
            self,
            "conservative_reference_price",
            _require_positive(
                self.conservative_reference_price,
                "conservative_reference_price",
            ),
        )
        object.__setattr__(
            self,
            "trigger_bar_volume",
            _require_nonnegative_int(self.trigger_bar_volume, "trigger_bar_volume"),
        )
        for label in ("prediction_sha256", "input_bundle_sha256"):
            object.__setattr__(self, label, _require_sha256(getattr(self, label), label))


@dataclass(frozen=True, slots=True)
class CandidateExitExecutionEvidence:
    """Factual capacity-bounded outcome odnogo predeclared corridor exit intent."""

    intent_id: str
    order_id: str
    asset_id: str
    contract_id: str
    sleeve_id: str
    execution_bar_sequence_id: int
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    execution_price: float | None
    factual_bar_volume: int
    execution_evidence_sha256: str
    provenance: str = PRIMARY_EXECUTION_PROVENANCE

    def __post_init__(self) -> None:
        """Trebuet signed quantity invariant i exact 1-percent factual capacity."""
        for label in ("intent_id", "order_id", "contract_id", "sleeve_id"):
            object.__setattr__(self, label, _require_identifier(getattr(self, label), label))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("corridor exit evidence asset vne sealed universe")
        object.__setattr__(
            self,
            "execution_bar_sequence_id",
            _require_nonnegative_int(
                self.execution_bar_sequence_id,
                "execution_bar_sequence_id",
            ),
        )
        requested = _require_nonzero_int(self.requested_contracts, "requested_contracts")
        executed = _require_int(self.executed_contracts, "executed_contracts")
        carry = _require_int(self.carry_contracts, "carry_contracts")
        if executed and _sign(float(executed)) != _sign(float(requested)):
            raise ValueError("corridor exit executed direction ne sootvetstvuet request")
        if abs(executed) > abs(requested) or carry != requested - executed:
            raise ValueError("corridor exit quantity/carry invariant narushen")
        volume = _require_nonnegative_int(self.factual_bar_volume, "factual_bar_volume")
        capacity = volume * MAXIMUM_BAR_PARTICIPATION_BPS // 10_000
        if abs(executed) > capacity:
            raise ValueError("corridor exit prevysil 1-percent factual bar capacity")
        if executed:
            price = _require_positive(self.execution_price, "execution_price")
        elif self.execution_price is not None:
            raise ValueError("zero corridor exit ne mozhet imet' execution_price")
        else:
            price = None
        if self.provenance != PRIMARY_EXECUTION_PROVENANCE:
            raise ValueError("corridor exit provenance ne sootvetstvuet primary boundary")
        object.__setattr__(self, "requested_contracts", requested)
        object.__setattr__(self, "executed_contracts", executed)
        object.__setattr__(self, "carry_contracts", carry)
        object.__setattr__(self, "execution_price", price)
        object.__setattr__(self, "factual_bar_volume", volume)
        object.__setattr__(
            self,
            "execution_evidence_sha256",
            _require_sha256(self.execution_evidence_sha256, "execution_evidence_sha256"),
        )


@dataclass(frozen=True, slots=True)
class CorridorTransition:
    """Rezultat odnogo bar transition: state i optional exit intent."""

    position: CorridorPosition
    exit_intent: CorridorExitIntent | None = None


@dataclass(frozen=True, slots=True)
class CorridorPosition:
    """Immutable execution-bound corridor state s predeclared ATR bracket."""

    position_id: str
    sleeve_id: str
    asset_id: str
    contract_id: str
    entry_order_id: str
    direction: int
    initial_contracts: int
    open_contracts: int
    entry_carry_contracts: int
    decision_at: datetime
    opened_at: datetime
    entry_price: float
    take_profit: float
    stop_loss: float
    entry_common_session_sequence_id: int
    exit_common_session_sequence_id: int
    entry_execution_bar_sequence_id: int
    last_bar_sequence_id: int
    last_bar_closed_at: datetime
    scheduled_exit_window_closed_at: datetime
    prediction_sha256: str
    input_bundle_sha256: str
    calendar_sha256: str
    entry_execution_evidence_sha256: str
    status: CorridorPositionStatus = CorridorPositionStatus.OPEN
    pending_exit_intent_id: str | None = None
    executed_exit_contracts: int = 0
    realized_exit_average_price: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    def __post_init__(self) -> None:
        """Proveryaet causal schedule, identity, quantity i bracket geometriyu."""
        status = CorridorPositionStatus(self.status)
        object.__setattr__(self, "status", status)
        for label in ("position_id", "sleeve_id", "contract_id", "entry_order_id"):
            object.__setattr__(self, label, _require_identifier(getattr(self, label), label))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("corridor asset_id vne sealed universe")
        decision_at = _require_development_decision_time(self.decision_at)
        opened_at = _require_execution_window_close(self.opened_at, "opened_at")
        last_bar_closed_at = _require_aware(self.last_bar_closed_at, "last_bar_closed_at")
        scheduled_exit = _require_execution_window_close(
            self.scheduled_exit_window_closed_at,
            "scheduled_exit_window_closed_at",
        )
        if opened_at <= decision_at:
            raise ValueError("corridor fill dolzhen byt' posle decision")
        if last_bar_closed_at < opened_at:
            raise ValueError("last_bar_closed_at ne mozhet byt' do fill")
        if scheduled_exit <= opened_at:
            raise ValueError("scheduled corridor exit dolzhen byt' posle fill")
        if self.direction not in (-1, 1):
            raise ValueError("corridor direction nevaliden")
        initial = _require_nonnegative_int(self.initial_contracts, "initial_contracts")
        opened = _require_nonnegative_int(self.open_contracts, "open_contracts")
        entry_carry = _require_nonnegative_int(
            self.entry_carry_contracts,
            "entry_carry_contracts",
        )
        if initial <= 0 or opened > initial:
            raise ValueError("corridor initial/open contracts nevalidny")
        entry_sequence = _require_nonnegative_int(
            self.entry_common_session_sequence_id,
            "entry_common_session_sequence_id",
        )
        exit_sequence = _require_nonnegative_int(
            self.exit_common_session_sequence_id,
            "exit_common_session_sequence_id",
        )
        if exit_sequence != entry_sequence + HOLDING_SLEEVE_COUNT:
            raise ValueError("corridor exit sequence dolzhen byt' rovno D+5")
        entry_bar_sequence = _require_nonnegative_int(
            self.entry_execution_bar_sequence_id,
            "entry_execution_bar_sequence_id",
        )
        last_bar_sequence = _require_nonnegative_int(
            self.last_bar_sequence_id,
            "last_bar_sequence_id",
        )
        if last_bar_sequence < entry_bar_sequence:
            raise ValueError("corridor last bar sequence ne mozhet byt' do entry")
        for name in ("entry_price", "take_profit", "stop_loss"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} dolzhen byt' finite i > 0")
        if self.direction > 0 and not self.stop_loss < self.entry_price < self.take_profit:
            raise ValueError("long corridor bracket nevaliden")
        if self.direction < 0 and not self.take_profit < self.entry_price < self.stop_loss:
            raise ValueError("short corridor bracket nevaliden")
        if self.pending_exit_intent_id is not None:
            object.__setattr__(
                self,
                "pending_exit_intent_id",
                _require_identifier(self.pending_exit_intent_id, "pending_exit_intent_id"),
            )
        if status is CorridorPositionStatus.OPEN and any(
            value is not None
            for value in (self.pending_exit_intent_id, self.exit_price, self.exit_reason)
        ):
            raise ValueError("open position ne mozhet imet' exit")
        if status is CorridorPositionStatus.EXIT_PENDING and (
            self.pending_exit_intent_id is None or self.exit_reason is None
        ):
            raise ValueError("exit-pending position trebuet intent/reason")
        if status is CorridorPositionStatus.CLOSED and (
            self.exit_price is None or self.exit_reason is None or opened != 0
        ):
            raise ValueError("closed position trebuet zero open contracts i exit")
        if status is CorridorPositionStatus.CARRY_UNRESOLVED and (
            self.exit_price is not None or self.exit_reason is None
        ):
            raise ValueError("carry unresolved trebuet reason bez synthetic full exit")
        exited = _require_nonnegative_int(
            self.executed_exit_contracts,
            "executed_exit_contracts",
        )
        if exited > initial or exited + opened != initial:
            raise ValueError("corridor exited/open quantity invariant narushen")
        if exited:
            object.__setattr__(
                self,
                "realized_exit_average_price",
                _require_positive(
                    self.realized_exit_average_price,
                    "realized_exit_average_price",
                ),
            )
        elif self.realized_exit_average_price is not None:
            raise ValueError("realized exit price bez executed contracts zapreshchena")
        if status is CorridorPositionStatus.CLOSED and (
            self.exit_price != self.realized_exit_average_price
        ):
            raise ValueError("closed exit_price dolzhna ravnyat'sya realized average")
        for label in (
            "prediction_sha256",
            "input_bundle_sha256",
            "calendar_sha256",
            "entry_execution_evidence_sha256",
        ):
            object.__setattr__(self, label, _require_sha256(getattr(self, label), label))
        object.__setattr__(self, "decision_at", decision_at)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "last_bar_closed_at", last_bar_closed_at)
        object.__setattr__(self, "scheduled_exit_window_closed_at", scheduled_exit)
        object.__setattr__(self, "initial_contracts", initial)
        object.__setattr__(self, "open_contracts", opened)
        object.__setattr__(self, "entry_carry_contracts", entry_carry)
        object.__setattr__(self, "entry_common_session_sequence_id", entry_sequence)
        object.__setattr__(self, "exit_common_session_sequence_id", exit_sequence)
        object.__setattr__(self, "entry_execution_bar_sequence_id", entry_bar_sequence)
        object.__setattr__(self, "last_bar_sequence_id", last_bar_sequence)
        object.__setattr__(self, "executed_exit_contracts", exited)


@dataclass(frozen=True, slots=True)
class FactualTenMinuteBar:
    """Polnyi factual 10m OHLC bar dlya causal bracket transition."""

    asset_id: str
    contract_id: str
    bar_sequence_id: int
    common_session_sequence_id: int
    opened_at: datetime
    closed_at: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int

    def __post_init__(self) -> None:
        """Proveryaet identity, exact sequence fields, chronology i OHLCV."""
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("bar asset_id vne sealed universe")
        object.__setattr__(
            self,
            "contract_id",
            _require_identifier(self.contract_id, "contract_id"),
        )
        object.__setattr__(
            self,
            "bar_sequence_id",
            _require_nonnegative_int(self.bar_sequence_id, "bar_sequence_id"),
        )
        object.__setattr__(
            self,
            "common_session_sequence_id",
            _require_nonnegative_int(
                self.common_session_sequence_id,
                "common_session_sequence_id",
            ),
        )
        opened_at = _require_aware(self.opened_at, "opened_at")
        closed_at = _require_aware(self.closed_at, "closed_at")
        if closed_at - opened_at != TEN_MINUTE_BAR_DURATION:
            raise ValueError("factual bar dolzhen imet' rovno 10 minut")
        prices = (self.open_price, self.high_price, self.low_price, self.close_price)
        if any(not isfinite(value) or value <= 0.0 for value in prices):
            raise ValueError("bar OHLC dolzhen byt' finite i > 0")
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("bar high narushaet OHLC invariant")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("bar low narushaet OHLC invariant")
        object.__setattr__(self, "volume", _require_nonnegative_int(self.volume, "volume"))
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "closed_at", closed_at)


@dataclass(frozen=True, slots=True)
class CandidateAnnualMetric:
    """Odin calendar-year rezultat odnogo predeclared kandidata."""

    candidate_id: AggressiveCandidateId
    year: int
    net_return: float
    sharpe: float
    evaluation_bundle_sha256: str

    def __post_init__(self) -> None:
        """Fiksiruet candidate/year, finite metrics i full evaluation bundle seal."""
        object.__setattr__(self, "candidate_id", AggressiveCandidateId(self.candidate_id))
        year = _require_int(self.year, "year")
        if year not in DEVELOPMENT_YEARS:
            raise ValueError("annual metric year vne sealed development years")
        object.__setattr__(self, "year", year)
        object.__setattr__(self, "net_return", _require_finite(self.net_return, "net_return"))
        object.__setattr__(self, "sharpe", _require_finite(self.sharpe, "sharpe"))
        object.__setattr__(
            self,
            "evaluation_bundle_sha256",
            _require_sha256(self.evaluation_bundle_sha256, "evaluation_bundle_sha256"),
        )


@dataclass(frozen=True, slots=True)
class CandidateGateMetric:
    """Fixed execution i doubled-cost gate kandidata na odnih predictions."""

    candidate_id: AggressiveCandidateId
    prediction_sha256: str
    evaluation_bundle_sha256: str
    primary_net_cagr: float
    primary_sharpe: float
    primary_max_drawdown: float
    worst_calendar_year_return: float
    doubled_cost_cagr: float
    critical_execution_failure_count: int
    maximum_participation_bps: float
    unknown_capacity_count: int
    unresolved_positions_at_terminal: int

    def __post_init__(self) -> None:
        """Proveryaet hash, finite economic metrics i nonnegative audit counts."""
        object.__setattr__(self, "candidate_id", AggressiveCandidateId(self.candidate_id))
        normalized_hash = _require_sha256(self.prediction_sha256, "prediction_sha256")
        evaluation_hash = _require_sha256(
            self.evaluation_bundle_sha256,
            "evaluation_bundle_sha256",
        )
        for name in (
            "primary_net_cagr",
            "primary_sharpe",
            "primary_max_drawdown",
            "worst_calendar_year_return",
            "doubled_cost_cagr",
            "maximum_participation_bps",
        ):
            _require_finite(getattr(self, name), name)
        if self.primary_max_drawdown < 0.0 or self.maximum_participation_bps < 0.0:
            raise ValueError("drawdown i participation ne mogut byt' otricatel'nymi")
        for name in (
            "critical_execution_failure_count",
            "unknown_capacity_count",
            "unresolved_positions_at_terminal",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} dolzhen byt' nonnegative int")
        object.__setattr__(self, "prediction_sha256", normalized_hash)
        object.__setattr__(self, "evaluation_bundle_sha256", evaluation_hash)


@dataclass(frozen=True, slots=True)
class CandidateSelectionRecord:
    """Multiple-testing-aware ranking record posle vseh hard gates."""

    candidate_id: AggressiveCandidateId
    median_yearly_sharpe: float
    worst_year_return: float
    positive_year_count: int
    prediction_sha256: str
    evaluation_bundle_sha256: str


def _require_aware(value: datetime, label: str) -> datetime:
    """Trebuet timezone-aware timestamp i vozvrashchaet UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} dolzhen byt' timezone-aware datetime")
    return value.astimezone(UTC)


def _require_date(value: date, label: str) -> date:
    """Trebuet exact calendar date bez skrytoi vremennoy komponenty."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{label} dolzhen byt' exact date")
    return value


def _require_finite(value: float, label: str) -> float:
    """Trebuet finite numeric i zapreshchaet bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} dolzhen byt' finite numeric")
    return float(value)


def _require_positive(value: float | None, label: str) -> float:
    """Trebuet finite strogo polozhitel'noe numeric znachenie."""
    if value is None:
        raise ValueError(f"{label} dolzhen byt' zadan")
    normalized = _require_finite(value, label)
    if normalized <= 0.0:
        raise ValueError(f"{label} dolzhen byt' > 0")
    return normalized


def _require_int(value: int, label: str) -> int:
    """Trebuet exact int bez bool podmeny."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} dolzhen byt' int")
    return value


def _require_nonzero_int(value: int, label: str) -> int:
    """Trebuet nenulevoi exact int."""
    normalized = _require_int(value, label)
    if normalized == 0:
        raise ValueError(f"{label} dolzhen byt' nenulevym")
    return normalized


def _require_nonnegative_int(value: int, label: str) -> int:
    """Trebuet nonnegative exact int."""
    normalized = _require_int(value, label)
    if normalized < 0:
        raise ValueError(f"{label} ne mozhet byt' otricatel'nym")
    return normalized


def _require_identifier(value: str, label: str) -> str:
    """Trebuet nepustoi stable identifier bez kraevyh probelov."""
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} dolzhen byt' nepustym i bez kraevyh probelov")
    return value


def _require_sha256(value: str, label: str) -> str:
    """Normalizuet i proveryaet lowercase hex SHA-256."""
    if not isinstance(value, str):
        raise TypeError(f"{label} dolzhen byt' strokoi")
    normalized = value.lower()
    if len(normalized) != 64 or any(symbol not in "0123456789abcdef" for symbol in normalized):
        raise ValueError(f"{label} dolzhen byt' hex SHA-256")
    return normalized


def _require_development_decision_time(value: datetime) -> datetime:
    """Trebuet exact 18:50 Moscow i fail-closed blokiruet protected 2026."""
    normalized = _require_aware(value, "decision_at")
    local = normalized.astimezone(MOSCOW_TIMEZONE)
    if local.time().replace(tzinfo=None) != DECISION_LOCAL_TIME:
        raise ValueError("aggressive decision dolzhen byt' rovno v 18:50 Moscow")
    if local.date() >= PROTECTED_HOLDOUT_START:
        raise ValueError("protected 2026 holdout zablokirovan do fixed gates")
    return normalized


def _require_execution_window_close(value: datetime, label: str) -> datetime:
    """Trebuet exact 19:30 Moscow execution close do protected holdout."""
    normalized = _require_aware(value, label)
    local = normalized.astimezone(MOSCOW_TIMEZONE)
    if local.time().replace(tzinfo=None) != time(19, 30):
        raise ValueError(f"{label} dolzhen byt' rovno v 19:30 Moscow")
    if local.date() >= PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} ne mozhet kasat'sya protected 2026 holdout")
    return normalized


def _pit_payload(observation: PointInTimeObservation | None) -> dict[str, object] | None:
    """Serializuet odin PIT release v canonical full-input payload."""
    if observation is None:
        return None
    return {
        "value": observation.value,
        "published_at": observation.published_at.isoformat(),
        "source_id": observation.source_id,
        "observation_id": observation.observation_id,
        "source_sha256": observation.source_sha256,
    }


def _input_bundle_sha256(
    decision_at: datetime,
    assets: Sequence[CausalAssetSnapshot],
    prediction_sha256: str,
) -> str:
    """Vychislyaet canonical SHA po vsem model, market i PIT input values."""
    asset_rows: list[dict[str, object]] = []
    for asset in assets:
        asset_rows.append(
            {
                "asset_id": asset.asset_id,
                "known_at": asset.known_at.astimezone(UTC).isoformat(),
                "factor_decision_score": asset.factor_decision_score,
                "residual_decision_score": asset.residual_decision_score,
                "residual_location": asset.residual_location,
                "total_scale": asset.total_scale,
                "abstain_probability": asset.abstain_probability,
                "normal_probability": asset.normal_probability,
                "trend_probability": asset.trend_probability,
                "crash_probability": asset.crash_probability,
                "close": asset.close,
                "atr_20": asset.atr_20,
                "daily_volatility_20": asset.daily_volatility_20,
                "momentum_20": asset.momentum_20,
                "range_position_20": asset.range_position_20,
                "volatility_ratio_20": asset.volatility_ratio_20,
                "volume_ratio_20": asset.volume_ratio_20,
                "market_data_sha256": asset.market_data_sha256,
                "carry_z": _pit_payload(asset.carry_z),
                "cftc_crowd_z": _pit_payload(asset.cftc_crowd_z),
                "key_rate_change_z": _pit_payload(asset.key_rate_change_z),
                "usd_rub_return_z": _pit_payload(asset.usd_rub_return_z),
                "model_input_valid": asset.model_input_valid,
                "decision_market_valid": asset.decision_market_valid,
                "planned_contract_valid": asset.planned_contract_valid,
                "invalid_reason_codes": list(asset.invalid_reason_codes),
                "planned_contract_id": asset.planned_contract_id,
                "nominal_maturity_date": (
                    None
                    if asset.nominal_maturity_date is None
                    else asset.nominal_maturity_date.isoformat()
                ),
                "nominal_span_rule": asset.nominal_span_rule,
                "validity_provenance_sha256": asset.validity_provenance_sha256,
            }
        )
    payload = {
        "base_protocol_sha256": BASE_PROTOCOL_SHA256,
        "decision_at": decision_at.astimezone(UTC).isoformat(),
        "prediction_sha256": prediction_sha256,
        "assets": asset_rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _sign(value: float, threshold: float = 0.0) -> int:
    """Vozvrashchaet -1/0/+1 s yavnym simmetrichnym porogom."""
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _normalise_weights(
    raw: Mapping[str, float],
    gross_cap: float = MAX_GROSS_EXPOSURE,
) -> tuple[tuple[str, float], ...]:
    """Normalizuet finite nenulevye weights k hard gross cap bez plecha."""
    clean = {
        asset: float(weight)
        for asset, weight in raw.items()
        if isfinite(weight) and abs(weight) > MINIMUM_SIGNAL_MAGNITUDE
    }
    gross = sum(abs(weight) for weight in clean.values())
    if gross <= MINIMUM_SIGNAL_MAGNITUDE:
        return ()
    scale = min(1.0, gross_cap / gross)
    return tuple(sorted((asset, weight * scale) for asset, weight in clean.items()))


def _decision(
    candidate_id: AggressiveCandidateId,
    context: CausalDecisionContext,
    raw_weights: Mapping[str, float],
) -> CandidateDecision:
    """Stroit odin bounded candidate target s inherited prediction seal."""
    return CandidateDecision(
        candidate_id=candidate_id,
        decision_at=context.decision_at,
        prediction_sha256=context.prediction_sha256,
        input_bundle_sha256=context.input_bundle_sha256,
        base_protocol_sha256=context.base_protocol_sha256,
        target_weights=_normalise_weights(raw_weights),
    )


def _volatility_corridor(context: CausalDecisionContext) -> CandidateDecision:
    """Beret kontrarian TP v aktivnom koridore s dal'nim predeclared stopom."""
    ranked: list[tuple[float, str, int]] = []
    for asset in context.strategy_assets:
        if (
            asset.volatility_ratio_20 < CORRIDOR_VOLATILITY_RATIO_MINIMUM
            or asset.crash_probability > CORRIDOR_CRASH_PROBABILITY_MAXIMUM
        ):
            continue
        direction = 0
        if (
            asset.range_position_20 <= CORRIDOR_LOWER_ZONE
            and asset.residual_decision_score >= CORRIDOR_RESIDUAL_SCORE_MINIMUM
        ):
            direction = 1
        elif (
            asset.range_position_20 >= CORRIDOR_UPPER_ZONE
            and asset.residual_decision_score <= -CORRIDOR_RESIDUAL_SCORE_MINIMUM
        ):
            direction = -1
        if direction:
            edge = abs(asset.residual_decision_score) * asset.volatility_ratio_20
            ranked.append((edge, asset.asset_id, direction))
    selected = sorted(ranked, key=lambda row: (-row[0], row[1]))[:CORRIDOR_MAX_ASSETS]
    raw = {asset: direction / len(selected) for _, asset, direction in selected} if selected else {}
    return _decision(AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST, context, raw)


def _concentrated_dispersion(context: CausalDecisionContext) -> CandidateDecision:
    """Koncentriruet long/short v ekstremal'nyh residual bez factor beta claim."""
    eligible = [
        asset
        for asset in context.strategy_assets
        if asset.abstain_probability <= DISPERSION_ABSTAIN_PROBABILITY_MAXIMUM
    ]
    if len(eligible) < 2:
        return _decision(AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION, context, {})
    ordered = sorted(eligible, key=lambda asset: (asset.residual_decision_score, asset.asset_id))
    short_assets = ordered[:DISPERSION_LEG_COUNT]
    long_assets = ordered[-DISPERSION_LEG_COUNT:]
    spread = long_assets[-1].residual_decision_score - short_assets[0].residual_decision_score
    if (
        spread < DISPERSION_SCORE_SPREAD_MINIMUM
        or long_assets[-1].residual_decision_score < DISPERSION_ABSOLUTE_SCORE_MINIMUM
        or short_assets[0].residual_decision_score > -DISPERSION_ABSOLUTE_SCORE_MINIMUM
    ):
        return _decision(AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION, context, {})
    raw = {asset.asset_id: 0.5 / len(long_assets) for asset in long_assets}
    raw.update({asset.asset_id: -0.5 / len(short_assets) for asset in short_assets})
    return _decision(AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION, context, raw)


def _breakout_direction(asset: CausalAssetSnapshot) -> int:
    """Vozvrashchaet causal breakout direction po D-known koridoru i model score."""
    if (
        asset.trend_probability < BREAKOUT_TREND_PROBABILITY_MINIMUM
        or asset.volatility_ratio_20 < BREAKOUT_VOLATILITY_RATIO_MINIMUM
    ):
        return 0
    if (
        asset.range_position_20 >= BREAKOUT_LONG_RANGE_POSITION_MINIMUM
        and asset.residual_decision_score >= BREAKOUT_RESIDUAL_SCORE_MINIMUM
    ):
        return 1
    if (
        asset.range_position_20 <= BREAKOUT_SHORT_RANGE_POSITION_MAXIMUM
        and asset.residual_decision_score <= -BREAKOUT_RESIDUAL_SCORE_MINIMUM
    ):
        return -1
    return 0


def _breakout_pyramiding(
    context: CausalDecisionContext,
    state: BreakoutPyramidState | None,
) -> CandidateRun:
    """Stroit desired ladder, no ne menyaet filled level bez execution evidence."""
    prior = state or BreakoutPyramidState()
    if prior.last_decision_at is not None and prior.last_decision_at >= context.decision_at:
        raise ValueError("breakout decisions dolzhny postupat' strogo po vremeni")
    prior_by_asset = {item.asset_id: item for item in prior.assets}
    observed_states: list[BreakoutAssetState] = []
    intents: list[BreakoutAssetIntent] = []
    locked_positions: list[BreakoutLockedPosition] = []
    desired: list[tuple[str, int, int]] = []
    for asset in context.assets:
        previous = prior_by_asset.get(asset.asset_id)
        if not asset.strategy_eligible:
            if previous is not None:
                observed_states.append(previous)
                locked_positions.append(
                    BreakoutLockedPosition(
                        state=previous,
                        decision_at=context.decision_at,
                        reason_codes=asset.invalid_reason_codes,
                        input_bundle_sha256=context.input_bundle_sha256,
                    )
                )
            continue
        direction = _breakout_direction(asset)
        if asset.asset_id in prior.unresolved_asset_ids:
            if previous is not None:
                observed_states.append(previous)
                desired.append((asset.asset_id, previous.direction, previous.pyramid_level))
            continue
        if previous is not None:
            next_extreme = (
                max(previous.extreme_close, asset.close)
                if previous.direction > 0
                else min(previous.extreme_close, asset.close)
            )
            stopped = (
                previous.direction > 0
                and asset.close <= next_extreme - BREAKOUT_TRAILING_STOP_ATR * asset.atr_20
            ) or (
                previous.direction < 0
                and asset.close >= next_extreme + BREAKOUT_TRAILING_STOP_ATR * asset.atr_20
            )
            if stopped:
                intents.append(
                    BreakoutAssetIntent(
                        asset.asset_id,
                        BreakoutAction.EXIT_TRAIL,
                        previous.direction,
                        previous.pyramid_level,
                        0,
                        0,
                        next_extreme,
                    )
                )
                observed_states.append(
                    BreakoutAssetState(
                        previous.asset_id,
                        previous.contract_id,
                        previous.direction,
                        previous.pyramid_level,
                        next_extreme,
                        previous.last_filled_sleeve_id,
                        previous.last_filled_order_id,
                        previous.last_calendar_sha256,
                        previous.last_execution_evidence_sha256,
                    )
                )
                continue
            if direction and direction != previous.direction:
                intents.append(
                    BreakoutAssetIntent(
                        asset.asset_id,
                        BreakoutAction.EXIT_REVERSAL,
                        previous.direction,
                        previous.pyramid_level,
                        0,
                        0,
                        next_extreme,
                    )
                )
                observed_states.append(
                    BreakoutAssetState(
                        previous.asset_id,
                        previous.contract_id,
                        previous.direction,
                        previous.pyramid_level,
                        next_extreme,
                        previous.last_filled_sleeve_id,
                        previous.last_filled_order_id,
                        previous.last_calendar_sha256,
                        previous.last_execution_evidence_sha256,
                    )
                )
                continue
            desired_level = previous.pyramid_level
            action = BreakoutAction.HOLD
            if direction == previous.direction and previous.pyramid_level < BREAKOUT_PYRAMID_LEVELS:
                desired_level += 1
                action = BreakoutAction.ADD
                intents.append(
                    BreakoutAssetIntent(
                        asset.asset_id,
                        action,
                        previous.direction,
                        previous.pyramid_level,
                        previous.direction,
                        desired_level,
                        next_extreme,
                    )
                )
            observed_states.append(
                BreakoutAssetState(
                    previous.asset_id,
                    previous.contract_id,
                    previous.direction,
                    previous.pyramid_level,
                    next_extreme,
                    previous.last_filled_sleeve_id,
                    previous.last_filled_order_id,
                    previous.last_calendar_sha256,
                    previous.last_execution_evidence_sha256,
                )
            )
            desired.append((asset.asset_id, previous.direction, desired_level))
        elif direction:
            intents.append(
                BreakoutAssetIntent(
                    asset.asset_id,
                    BreakoutAction.ENTER,
                    0,
                    0,
                    direction,
                    1,
                    asset.close,
                )
            )
            desired.append((asset.asset_id, direction, 1))
    next_state = BreakoutPyramidState(
        context.decision_at,
        tuple(observed_states),
        prior.unresolved_executions,
    )
    active_count = len(desired)
    raw = (
        {
            asset_id: direction * level / BREAKOUT_PYRAMID_LEVELS / active_count
            for asset_id, direction, level in desired
        }
        if active_count
        else {}
    )
    decision = _decision(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        context,
        raw,
    )
    return CandidateRun(
        decision=decision,
        breakout_state=next_state,
        breakout_intents=tuple(intents),
        breakout_locked_positions=tuple(locked_positions),
    )


def apply_breakout_execution(
    run: CandidateRun,
    executions: Sequence[ScheduledCandidateExecution],
) -> BreakoutPyramidState:
    """Menyaet breakout filled level tol'ko po full factual execution evidence."""
    if run.decision.candidate_id is not AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP:
        raise ValueError("apply_breakout_execution trebuet breakout CandidateRun")
    if run.breakout_state is None:
        raise ValueError("breakout CandidateRun ne soderzhit observed state")
    required = {intent.asset_id: intent for intent in run.breakout_intents}
    if len(required) != len(run.breakout_intents):
        raise RuntimeError("breakout run soderzhit duplicate intents")
    provided = {item.evidence.asset_id: item for item in executions}
    if len(provided) != len(tuple(executions)) or set(provided) != set(required):
        raise ValueError("breakout execution evidence dolzhny exact sootvetstvovat' intents")
    state_by_asset = {item.asset_id: item for item in run.breakout_state.assets}
    unresolved = {
        item.asset_id: item for item in run.breakout_state.unresolved_executions
    }
    for asset_id, intent in required.items():
        scheduled = provided[asset_id]
        evidence = scheduled.evidence
        if evidence.candidate_id is not run.decision.candidate_id:
            raise ValueError("breakout execution candidate_id mismatch")
        if evidence.decision_at != run.decision.decision_at:
            raise ValueError("breakout execution decision_at mismatch")
        if evidence.prediction_sha256 != run.decision.prediction_sha256:
            raise ValueError("breakout execution prediction seal mismatch")
        if evidence.input_bundle_sha256 != run.decision.input_bundle_sha256:
            raise ValueError("breakout execution input bundle seal mismatch")
        expected_sign = (
            intent.desired_direction
            if intent.action in (BreakoutAction.ENTER, BreakoutAction.ADD)
            else -intent.prior_direction
        )
        if _sign(float(evidence.requested_contracts)) != expected_sign:
            raise ValueError("breakout execution direction ne sootvetstvuet intent")
        previous = state_by_asset.get(asset_id)
        if intent.action is not BreakoutAction.ENTER:
            if previous is None:
                raise RuntimeError("breakout non-entry intent ne imeet prior filled state")
            if evidence.contract_id != previous.contract_id:
                raise ValueError("breakout execution contract ne sootvetstvuet prior state")
        if not evidence.fully_filled:
            unresolved[asset_id] = BreakoutUnresolvedExecution(
                asset_id=asset_id,
                contract_id=evidence.contract_id,
                sleeve_id=evidence.sleeve_id,
                order_id=evidence.order_id,
                action=intent.action,
                requested_contracts=evidence.requested_contracts,
                executed_contracts=evidence.executed_contracts,
                carry_contracts=evidence.carry_contracts,
                calendar_sha256=scheduled.schedule.calendar_sha256,
                execution_evidence_sha256=evidence.execution_evidence_sha256,
            )
            continue
        unresolved.pop(asset_id, None)
        if intent.action in (BreakoutAction.EXIT_TRAIL, BreakoutAction.EXIT_REVERSAL):
            state_by_asset.pop(asset_id, None)
            continue
        if intent.action is BreakoutAction.ENTER:
            state_by_asset[asset_id] = BreakoutAssetState(
                asset_id,
                evidence.contract_id,
                intent.desired_direction,
                intent.desired_level,
                intent.next_extreme_close,
                evidence.sleeve_id,
                evidence.order_id,
                scheduled.schedule.calendar_sha256,
                evidence.execution_evidence_sha256,
            )
            continue
        if intent.action is BreakoutAction.ADD:
            if previous is None:
                raise RuntimeError("breakout ADD ne imeet prior filled state")
            state_by_asset[asset_id] = BreakoutAssetState(
                asset_id,
                evidence.contract_id,
                previous.direction,
                intent.desired_level,
                intent.next_extreme_close,
                evidence.sleeve_id,
                evidence.order_id,
                scheduled.schedule.calendar_sha256,
                evidence.execution_evidence_sha256,
            )
    return BreakoutPyramidState(
        run.decision.decision_at,
        tuple(state_by_asset.values()),
        tuple(unresolved.values()),
    )


def _regime_switch(context: CausalDecisionContext) -> CandidateDecision:
    """Pereklyuchaet trend i range reversion tol'ko po same-time regime output."""
    raw: dict[str, float] = {}
    for asset in context.strategy_assets:
        if asset.trend_probability >= REGIME_TREND_PROBABILITY_MINIMUM:
            agreement = _sign(asset.momentum_20) == _sign(asset.residual_decision_score)
            direction = _sign(asset.residual_decision_score, REGIME_SCORE_MINIMUM)
            if agreement and direction:
                raw[asset.asset_id] = direction / asset.daily_volatility_20
        elif asset.normal_probability >= REGIME_NORMAL_PROBABILITY_MINIMUM:
            residual_direction = _sign(asset.residual_decision_score, REGIME_SCORE_MINIMUM)
            if asset.range_position_20 <= CORRIDOR_LOWER_ZONE and residual_direction > 0:
                raw[asset.asset_id] = 1.0 / asset.daily_volatility_20
            elif asset.range_position_20 >= CORRIDOR_UPPER_ZONE and residual_direction < 0:
                raw[asset.asset_id] = -1.0 / asset.daily_volatility_20
    return _decision(AggressiveCandidateId.REGIME_SWITCH_TREND_REVERSION, context, raw)


def _crash_defense(context: CausalDecisionContext) -> CandidateDecision:
    """Reversiruet common factor pri crash regime i plavno narashchivaet zashchitu."""
    eligible = context.strategy_assets
    if not eligible:
        return _decision(AggressiveCandidateId.CRASH_EXPERT_CONVEX_DEFENSE, context, {})
    crash_probability = sum(asset.crash_probability for asset in eligible) / len(eligible)
    factor_score = sum(asset.factor_decision_score for asset in eligible) / len(eligible)
    if (
        crash_probability < CRASH_PROBABILITY_MINIMUM
        or abs(factor_score) < CRASH_FACTOR_SCORE_MINIMUM
    ):
        return _decision(AggressiveCandidateId.CRASH_EXPERT_CONVEX_DEFENSE, context, {})
    intensity = min(
        1.0,
        (crash_probability - CRASH_PROBABILITY_MINIMUM)
        / (1.0 - CRASH_PROBABILITY_MINIMUM),
    )
    direction = -_sign(factor_score)
    inverse_vol = {asset.asset_id: 1.0 / asset.daily_volatility_20 for asset in eligible}
    denominator = sum(inverse_vol.values())
    raw = {
        asset: direction * intensity * value / denominator for asset, value in inverse_vol.items()
    }
    return _decision(AggressiveCandidateId.CRASH_EXPERT_CONVEX_DEFENSE, context, raw)


def _carry_momentum(context: CausalDecisionContext) -> CandidateDecision:
    """Trebuet troinoe soglasie carry, 20d momentum i residual modela."""
    raw: dict[str, float] = {}
    for asset in context.strategy_assets:
        if asset.carry_z is None or abs(asset.carry_z.value) < CARRY_Z_MINIMUM:
            continue
        carry_value = asset.carry_z.value
        direction = _sign(carry_value)
        if (
            direction * asset.momentum_20 >= CARRY_MOMENTUM_MINIMUM
            and direction * asset.residual_decision_score >= CARRY_RESIDUAL_SCORE_MINIMUM
        ):
            raw[asset.asset_id] = direction * abs(carry_value) / asset.daily_volatility_20
    return _decision(AggressiveCandidateId.CARRY_MOMENTUM_CONFIRMATION, context, raw)


def _cftc_unwind(context: CausalDecisionContext) -> CandidateDecision:
    """Torguet unwind protiv ekstremenogo crowded positioning posle reversal."""
    raw: dict[str, float] = {}
    for asset in context.strategy_assets:
        crowd_observation = asset.cftc_crowd_z
        if crowd_observation is None or abs(crowd_observation.value) < CFTC_CROWD_Z_MINIMUM:
            continue
        crowd = crowd_observation.value
        unwind_direction = -_sign(crowd)
        if unwind_direction * asset.momentum_20 >= CFTC_REVERSAL_MOMENTUM_MINIMUM:
            raw[asset.asset_id] = unwind_direction * abs(crowd) / asset.daily_volatility_20
    return _decision(AggressiveCandidateId.CFTC_CROWDED_UNWIND, context, raw)


def _macro_shock(context: CausalDecisionContext) -> CandidateDecision:
    """Primenyayet predeclared MOEX futures sensitivities k PIT rate/FX shock."""
    raw: dict[str, float] = {}
    for asset in context.strategy_assets:
        rate = asset.key_rate_change_z.value if asset.key_rate_change_z is not None else None
        fx = asset.usd_rub_return_z.value if asset.usd_rub_return_z is not None else None
        score = 0.0
        if rate is not None and abs(rate) >= MACRO_RATE_SHOCK_Z_MINIMUM:
            rate_sensitivity = {"RI": -1.0, "MIX": -1.0, "SI": 0.35, "BR": 0.0}.get(
                asset.asset_id, 0.0
            )
            score += rate_sensitivity * rate
        if fx is not None and abs(fx) >= MACRO_FX_SHOCK_Z_MINIMUM:
            fx_sensitivity = {"SI": 1.0, "BR": 0.50, "RI": -0.50, "MIX": -0.35}.get(
                asset.asset_id, 0.0
            )
            score += fx_sensitivity * fx
        if abs(score) > MINIMUM_SIGNAL_MAGNITUDE:
            raw[asset.asset_id] = score / asset.daily_volatility_20
    return _decision(AggressiveCandidateId.MACRO_SHOCK_ROTATION, context, raw)


def _confidence_concentration(context: CausalDecisionContext) -> CandidateDecision:
    """Ostavlyaet tol'ko samyi vysokii residual SNR bez direction-logit podmeny."""
    ranked: list[tuple[float, str, int]] = []
    for asset in context.strategy_assets:
        snr = asset.residual_location / asset.total_scale
        if (
            abs(snr) >= CONFIDENCE_SNR_MINIMUM
            and asset.abstain_probability <= CONFIDENCE_ABSTAIN_MAXIMUM
        ):
            ranked.append((abs(snr), asset.asset_id, _sign(snr)))
    selected = sorted(ranked, key=lambda row: (-row[0], row[1]))[:CONFIDENCE_MAX_ASSETS]
    raw = {asset: float(direction) for _, asset, direction in selected}
    return _decision(AggressiveCandidateId.CONFIDENCE_CONCENTRATION, context, raw)


def _volatility_breakout(context: CausalDecisionContext) -> CandidateDecision:
    """Torguet tol'ko direction breakout pri odnovremennom vol i volume expansion."""
    ranked: list[tuple[float, str, int]] = []
    for asset in context.strategy_assets:
        if (
            asset.volatility_ratio_20 < VOLATILITY_BREAKOUT_RATIO_MINIMUM
            or asset.volume_ratio_20 < VOLUME_BREAKOUT_RATIO_MINIMUM
        ):
            continue
        direction = 0
        if (
            asset.range_position_20 >= VOLATILITY_BREAKOUT_LONG_RANGE_POSITION_MINIMUM
            and asset.residual_decision_score >= VOLATILITY_BREAKOUT_SCORE_MINIMUM
        ):
            direction = 1
        elif (
            asset.range_position_20 <= VOLATILITY_BREAKOUT_SHORT_RANGE_POSITION_MAXIMUM
            and asset.residual_decision_score <= -VOLATILITY_BREAKOUT_SCORE_MINIMUM
        ):
            direction = -1
        if direction:
            strength = (
                abs(asset.residual_decision_score)
                * asset.volatility_ratio_20
                * asset.volume_ratio_20
            )
            ranked.append((strength, asset.asset_id, direction))
    selected = sorted(ranked, key=lambda row: (-row[0], row[1]))[
        :VOLATILITY_BREAKOUT_MAX_ASSETS
    ]
    raw = {asset: direction / len(selected) for _, asset, direction in selected} if selected else {}
    return _decision(AggressiveCandidateId.VOLATILITY_EXPANSION_BREAKOUT, context, raw)


# Stateless dispatch zapechatyvaet devyat' formul s otdel'noi breakout state vetkoi.
_STATELESS_BUILDERS: Mapping[
    AggressiveCandidateId, Callable[[CausalDecisionContext], CandidateDecision]
] = {
    AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST: _volatility_corridor,
    AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION: _concentrated_dispersion,
    AggressiveCandidateId.REGIME_SWITCH_TREND_REVERSION: _regime_switch,
    AggressiveCandidateId.CRASH_EXPERT_CONVEX_DEFENSE: _crash_defense,
    AggressiveCandidateId.CARRY_MOMENTUM_CONFIRMATION: _carry_momentum,
    AggressiveCandidateId.CFTC_CROWDED_UNWIND: _cftc_unwind,
    AggressiveCandidateId.MACRO_SHOCK_ROTATION: _macro_shock,
    AggressiveCandidateId.CONFIDENCE_CONCENTRATION: _confidence_concentration,
    AggressiveCandidateId.VOLATILITY_EXPANSION_BREAKOUT: _volatility_breakout,
}


def run_aggressive_candidate(
    candidate_id: AggressiveCandidateId | str,
    context: CausalDecisionContext,
    *,
    breakout_state: BreakoutPyramidState | None = None,
) -> CandidateRun:
    """Zapuskaet exact fixed formulu; runtime knobs namerenno otsutstvuyut."""
    resolved = AggressiveCandidateId(candidate_id)
    if resolved is AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP:
        return _breakout_pyramiding(context, breakout_state)
    if breakout_state is not None:
        raise ValueError("breakout_state dopustim tol'ko dlya breakout kandidata")
    return CandidateRun(decision=_STATELESS_BUILDERS[resolved](context))


def open_volatility_corridor_position(
    asset: CausalAssetSnapshot,
    *,
    decision: CandidateDecision,
    execution: ScheduledCandidateExecution,
) -> CorridorPosition:
    """Otkryvaet bracket tol'ko iz linked corridor decision i factual entry fill."""
    if decision.candidate_id is not AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST:
        raise ValueError("corridor open trebuet volatility_corridor_harvest decision")
    if not asset.strategy_eligible:
        raise ValueError("corridor open zapreshchen dlya invalid asset snapshot")
    if not isinstance(execution, ScheduledCandidateExecution):
        raise TypeError("execution dolzhen byt' ScheduledCandidateExecution")
    evidence = execution.evidence
    schedule = execution.schedule
    if evidence.candidate_id is not decision.candidate_id:
        raise ValueError("corridor execution candidate_id mismatch")
    if evidence.decision_at != decision.decision_at:
        raise ValueError("corridor execution decision_at mismatch")
    if evidence.prediction_sha256 != decision.prediction_sha256:
        raise ValueError("corridor execution prediction seal mismatch")
    if evidence.input_bundle_sha256 != decision.input_bundle_sha256:
        raise ValueError("corridor execution input bundle seal mismatch")
    if evidence.asset_id != asset.asset_id:
        raise ValueError("corridor execution asset mismatch")
    decision_weights = dict(decision.target_weights)
    target_weight = decision_weights.get(asset.asset_id, 0.0)
    if abs(target_weight) <= MINIMUM_SIGNAL_MAGNITUDE:
        raise ValueError("corridor asset ne byl vybran candidate decision")
    if _sign(target_weight) != _sign(float(evidence.requested_contracts)):
        raise ValueError("corridor requested direction protivorechit candidate signal")
    if evidence.executed_contracts == 0 or evidence.execution_price is None:
        raise ValueError("corridor position ne mozhet otkryt'sya bez factual fill")
    if asset.known_at.astimezone(UTC) > decision.decision_at:
        raise ValueError("asset snapshot byl nedostupen k decision")
    direction = _sign(float(evidence.executed_contracts))
    fill_price = evidence.execution_price
    take_profit = fill_price + direction * CORRIDOR_TAKE_PROFIT_ATR * asset.atr_20
    stop_loss = fill_price - direction * CORRIDOR_STOP_LOSS_ATR * asset.atr_20
    position_id = f"{schedule.sleeve_id}:{asset.asset_id}:{evidence.contract_id}"
    return CorridorPosition(
        position_id=position_id,
        sleeve_id=schedule.sleeve_id,
        asset_id=asset.asset_id,
        contract_id=evidence.contract_id,
        entry_order_id=evidence.order_id,
        direction=direction,
        initial_contracts=abs(evidence.executed_contracts),
        open_contracts=abs(evidence.executed_contracts),
        entry_carry_contracts=abs(evidence.carry_contracts),
        decision_at=decision.decision_at,
        opened_at=evidence.execution_window_closed_at,
        entry_price=fill_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        entry_common_session_sequence_id=schedule.entry_common_session_sequence_id,
        exit_common_session_sequence_id=schedule.exit_common_session_sequence_id,
        entry_execution_bar_sequence_id=evidence.execution_bar_sequence_id,
        last_bar_sequence_id=evidence.execution_bar_sequence_id,
        last_bar_closed_at=evidence.execution_window_closed_at,
        scheduled_exit_window_closed_at=schedule.exit_window_closed_at,
        prediction_sha256=decision.prediction_sha256,
        input_bundle_sha256=decision.input_bundle_sha256,
        calendar_sha256=schedule.calendar_sha256,
        entry_execution_evidence_sha256=evidence.execution_evidence_sha256,
    )


def transition_volatility_corridor(
    position: CorridorPosition,
    bar: FactualTenMinuteBar,
) -> CorridorTransition:
    """Stroit exit intent po sleduyushchemu exact factual baru bez synthetic close."""
    if position.status is not CorridorPositionStatus.OPEN:
        raise ValueError("non-open corridor position ne mozhet obrabatyvat' novyi bar")
    if bar.asset_id != position.asset_id or bar.contract_id != position.contract_id:
        raise ValueError("bar asset/contract ne sootvetstvuet corridor position")
    if bar.opened_at < position.last_bar_closed_at or bar.closed_at <= position.last_bar_closed_at:
        raise ValueError("corridor bar chronology narushena")
    if bar.bar_sequence_id <= position.last_bar_sequence_id:
        raise ValueError("corridor bars dolzhny postupat' strogo po sequence")
    if bar.bar_sequence_id != position.last_bar_sequence_id + 1:
        unresolved = replace(
            position,
            last_bar_sequence_id=bar.bar_sequence_id,
            last_bar_closed_at=bar.closed_at,
            status=CorridorPositionStatus.CARRY_UNRESOLVED,
            exit_reason="missing_expected_factual_bar",
        )
        return CorridorTransition(unresolved)
    if bar.closed_at > position.scheduled_exit_window_closed_at:
        unresolved = replace(
            position,
            last_bar_sequence_id=bar.bar_sequence_id,
            last_bar_closed_at=bar.closed_at,
            status=CorridorPositionStatus.CARRY_UNRESOLVED,
            exit_reason="missing_scheduled_exit_window",
        )
        return CorridorTransition(unresolved)
    if position.direction > 0:
        stop_touched = bar.low_price <= position.stop_loss
        take_touched = bar.high_price >= position.take_profit
        adverse_stop_fill = min(bar.open_price, position.stop_loss)
    else:
        stop_touched = bar.high_price >= position.stop_loss
        take_touched = bar.low_price <= position.take_profit
        adverse_stop_fill = max(bar.open_price, position.stop_loss)
    scheduled_exit = bar.closed_at == position.scheduled_exit_window_closed_at
    if (
        scheduled_exit
        and bar.common_session_sequence_id != position.exit_common_session_sequence_id
    ):
        unresolved = replace(
            position,
            last_bar_sequence_id=bar.bar_sequence_id,
            last_bar_closed_at=bar.closed_at,
            status=CorridorPositionStatus.CARRY_UNRESOLVED,
            exit_reason="scheduled_exit_common_session_mismatch",
        )
        return CorridorTransition(unresolved)
    if stop_touched:
        reason = (
            "stop_loss_ambiguous_bar_adverse_first"
            if take_touched
            else "stop_loss"
        )
        reference_price = adverse_stop_fill
    elif take_touched:
        reason = "take_profit"
        reference_price = position.take_profit
    elif scheduled_exit:
        reason = "scheduled_fifth_session_adverse_window_exit"
        reference_price = bar.low_price if position.direction > 0 else bar.high_price
    else:
        held = replace(
            position,
            last_bar_sequence_id=bar.bar_sequence_id,
            last_bar_closed_at=bar.closed_at,
        )
        return CorridorTransition(held)
    intent_payload = (
        f"{position.position_id}|{bar.bar_sequence_id}|{reason}|"
        f"{position.input_bundle_sha256}"
    ).encode()
    intent_id = f"corridor-exit-{sha256(intent_payload).hexdigest()[:20]}"
    intent = CorridorExitIntent(
        intent_id=intent_id,
        position_id=position.position_id,
        sleeve_id=position.sleeve_id,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        trigger_reason=reason,
        trigger_bar_sequence_id=bar.bar_sequence_id,
        trigger_bar_closed_at=bar.closed_at,
        requested_contracts=-position.direction * position.open_contracts,
        conservative_reference_price=reference_price,
        trigger_bar_volume=bar.volume,
        prediction_sha256=position.prediction_sha256,
        input_bundle_sha256=position.input_bundle_sha256,
    )
    pending = replace(
        position,
        last_bar_sequence_id=bar.bar_sequence_id,
        last_bar_closed_at=bar.closed_at,
        status=CorridorPositionStatus.EXIT_PENDING,
        pending_exit_intent_id=intent.intent_id,
        exit_reason=reason,
    )
    return CorridorTransition(pending, intent)


def apply_volatility_corridor_exit(
    position: CorridorPosition,
    intent: CorridorExitIntent,
    evidence: CandidateExitExecutionEvidence,
) -> CorridorPosition:
    """Zakryvaet corridor tol'ko po factual capacity-bounded exit evidence."""
    if position.status is not CorridorPositionStatus.EXIT_PENDING:
        raise ValueError("corridor exit evidence trebuet EXIT_PENDING position")
    if position.pending_exit_intent_id != intent.intent_id:
        raise ValueError("corridor pending intent mismatch")
    identity = (position.asset_id, position.contract_id, position.sleeve_id)
    if identity != (intent.asset_id, intent.contract_id, intent.sleeve_id):
        raise ValueError("corridor intent identity mismatch")
    if identity != (evidence.asset_id, evidence.contract_id, evidence.sleeve_id):
        raise ValueError("corridor exit evidence identity mismatch")
    if evidence.intent_id != intent.intent_id:
        raise ValueError("corridor exit evidence intent_id mismatch")
    if evidence.execution_bar_sequence_id != intent.trigger_bar_sequence_id:
        raise ValueError("corridor exit evidence bar sequence mismatch")
    if evidence.requested_contracts != intent.requested_contracts:
        raise ValueError("corridor exit evidence requested contracts mismatch")
    if evidence.factual_bar_volume != intent.trigger_bar_volume:
        raise ValueError("corridor exit evidence factual volume mismatch")
    if evidence.executed_contracts and evidence.execution_price is not None:
        if evidence.requested_contracts < 0 and (
            evidence.execution_price > intent.conservative_reference_price
        ):
            raise ValueError("long exit price dolzhna byt' ne luchshe conservative reference")
        if evidence.requested_contracts > 0 and (
            evidence.execution_price < intent.conservative_reference_price
        ):
            raise ValueError("short exit price dolzhna byt' ne luchshe conservative reference")
    executed = abs(evidence.executed_contracts)
    remaining = position.open_contracts - executed
    if remaining < 0:
        raise ValueError("corridor exit executed bol'she open contracts")
    realized_price = evidence.execution_price if executed else None
    if remaining:
        return replace(
            position,
            open_contracts=remaining,
            status=CorridorPositionStatus.CARRY_UNRESOLVED,
            pending_exit_intent_id=None,
            executed_exit_contracts=position.executed_exit_contracts + executed,
            realized_exit_average_price=realized_price,
            exit_reason="partial_or_zero_capacity_exit_carry",
        )
    return replace(
        position,
        open_contracts=0,
        status=CorridorPositionStatus.CLOSED,
        pending_exit_intent_id=None,
        executed_exit_contracts=position.initial_contracts,
        realized_exit_average_price=realized_price,
        exit_price=realized_price,
        exit_reason=intent.trigger_reason,
    )


def mark_volatility_corridor_missing_exit_window(
    position: CorridorPosition,
    *,
    observed_through: datetime,
) -> CorridorPosition:
    """Fiksiruet carry/unresolved, esli exact scheduled exit window otsutstvuet."""
    if position.status is not CorridorPositionStatus.OPEN:
        raise ValueError("tol'ko open corridor position mozhet stat' unresolved")
    observed_utc = _require_aware(observed_through, "observed_through")
    if observed_utc <= position.scheduled_exit_window_closed_at:
        raise ValueError("missing exit mozhno fiksirovat' tol'ko posle scheduled window")
    return replace(
        position,
        last_bar_closed_at=observed_utc,
        status=CorridorPositionStatus.CARRY_UNRESOLVED,
        exit_reason="missing_scheduled_exit_window",
    )


def rank_gate_passing_candidates(
    annual_metrics: Iterable[CandidateAnnualMetric],
    gate_metrics: Iterable[CandidateGateMetric],
) -> tuple[CandidateSelectionRecord, ...]:
    """Primenyayet fixed hard gates i rank median Sharpe, zatem worst year."""
    annual_rows = tuple(annual_metrics)
    gate_rows = tuple(gate_metrics)
    gate_by_id = {row.candidate_id: row for row in gate_rows}
    if len(gate_by_id) != len(gate_rows):
        raise ValueError("duplicate candidate gate metric")
    prediction_hashes = {row.prediction_sha256.lower() for row in gate_rows}
    if len(prediction_hashes) > 1:
        raise ValueError("vse kandidaty dolzhny ispol'zovat' odin prediction SHA")
    evaluation_hashes = {row.evaluation_bundle_sha256 for row in gate_rows}
    if len(evaluation_hashes) > 1:
        raise ValueError("vse kandidaty dolzhny ispol'zovat' odin evaluation bundle SHA")
    ranked: list[CandidateSelectionRecord] = []
    for candidate_id in AggressiveCandidateId:
        yearly = [row for row in annual_rows if row.candidate_id is candidate_id]
        if tuple(sorted(row.year for row in yearly)) != DEVELOPMENT_YEARS:
            raise ValueError(f"{candidate_id.value} trebuet exact pyat' development years")
        gate = gate_by_id.get(candidate_id)
        if gate is None:
            raise ValueError(f"{candidate_id.value} ne imeet gate metric")
        yearly_hashes = {row.evaluation_bundle_sha256 for row in yearly}
        if yearly_hashes != {gate.evaluation_bundle_sha256}:
            raise ValueError(f"{candidate_id.value} annual/gate evaluation bundle mismatch")
        factual_worst_year = min(row.net_return for row in yearly)
        if abs(gate.worst_calendar_year_return - factual_worst_year) > 1e-12:
            raise ValueError(f"{candidate_id.value} gate worst year ne sootvetstvuet annual rows")
        positive_count = sum(row.net_return > 0.0 for row in yearly)
        passes = (
            positive_count >= MINIMUM_POSITIVE_YEARS
            and gate.primary_net_cagr >= PRIMARY_NET_CAGR_MINIMUM
            and gate.primary_sharpe >= PRIMARY_SHARPE_MINIMUM
            and gate.primary_max_drawdown <= PRIMARY_MAX_DRAWDOWN_MAXIMUM
            and gate.worst_calendar_year_return >= WORST_CALENDAR_YEAR_RETURN_MINIMUM
            and factual_worst_year >= WORST_CALENDAR_YEAR_RETURN_MINIMUM
            and gate.doubled_cost_cagr > 0.0
            and gate.critical_execution_failure_count == 0
            and gate.maximum_participation_bps <= MAXIMUM_PARTICIPATION_BPS
            and gate.unknown_capacity_count == 0
            and gate.unresolved_positions_at_terminal == 0
        )
        if passes:
            ranked.append(
                CandidateSelectionRecord(
                    candidate_id=candidate_id,
                    median_yearly_sharpe=median(row.sharpe for row in yearly),
                    worst_year_return=factual_worst_year,
                    positive_year_count=positive_count,
                    prediction_sha256=gate.prediction_sha256.lower(),
                    evaluation_bundle_sha256=gate.evaluation_bundle_sha256,
                )
            )
    return tuple(
        sorted(
            ranked,
            key=lambda row: (
                -row.median_yearly_sharpe,
                -row.worst_year_return,
                row.candidate_id.value,
            ),
        )
    )


# Fiksirovannyi registry publikuet vse numeric constants dlya audita bez runtime tuning.
CANDIDATE_SPECS = (
    FixedCandidateSpec(
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST,
        "stateful_intraday_range_harvest",
        True,
        ("v8_predictions", "d_known_daily", "factual_later_10m"),
        (
            ("take_profit_atr", CORRIDOR_TAKE_PROFIT_ATR),
            ("stop_loss_atr", CORRIDOR_STOP_LOSS_ATR),
            ("maximum_assets", CORRIDOR_MAX_ASSETS),
            ("volatility_ratio_minimum", CORRIDOR_VOLATILITY_RATIO_MINIMUM),
            ("lower_range_position_maximum", CORRIDOR_LOWER_ZONE),
            ("upper_range_position_minimum", CORRIDOR_UPPER_ZONE),
            ("residual_score_minimum", CORRIDOR_RESIDUAL_SCORE_MINIMUM),
            ("crash_probability_maximum", CORRIDOR_CRASH_PROBABILITY_MAXIMUM),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.CONCENTRATED_RESIDUAL_DISPERSION,
        "cross_asset_residual",
        False,
        ("v8_predictions", "d_known_daily"),
        (
            ("leg_count_each_side", DISPERSION_LEG_COUNT),
            ("score_spread_minimum", DISPERSION_SCORE_SPREAD_MINIMUM),
            ("absolute_score_minimum", DISPERSION_ABSOLUTE_SCORE_MINIMUM),
            ("abstain_probability_maximum", DISPERSION_ABSTAIN_PROBABILITY_MAXIMUM),
            ("long_gross", 0.50),
            ("short_gross", 0.50),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP,
        "stateful_trend",
        True,
        ("v8_predictions", "d_known_daily", "d_known_10m"),
        (
            ("pyramid_levels", BREAKOUT_PYRAMID_LEVELS),
            ("pyramid_level_fraction_1", 1.0 / BREAKOUT_PYRAMID_LEVELS),
            ("pyramid_level_fraction_2", 2.0 / BREAKOUT_PYRAMID_LEVELS),
            ("pyramid_level_fraction_3", 1.0),
            ("trailing_stop_atr", BREAKOUT_TRAILING_STOP_ATR),
            ("trend_probability_minimum", BREAKOUT_TREND_PROBABILITY_MINIMUM),
            ("residual_score_minimum", BREAKOUT_RESIDUAL_SCORE_MINIMUM),
            ("volatility_ratio_minimum", BREAKOUT_VOLATILITY_RATIO_MINIMUM),
            ("breakout_long_range_position_minimum", BREAKOUT_LONG_RANGE_POSITION_MINIMUM),
            ("breakout_short_range_position_maximum", BREAKOUT_SHORT_RANGE_POSITION_MAXIMUM),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.REGIME_SWITCH_TREND_REVERSION,
        "regime_switch",
        False,
        ("v8_predictions", "d_known_daily"),
        (
            ("trend_probability_minimum", REGIME_TREND_PROBABILITY_MINIMUM),
            ("normal_probability_minimum", REGIME_NORMAL_PROBABILITY_MINIMUM),
            ("residual_score_minimum", REGIME_SCORE_MINIMUM),
            ("lower_range_position_maximum", CORRIDOR_LOWER_ZONE),
            ("upper_range_position_minimum", CORRIDOR_UPPER_ZONE),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.CRASH_EXPERT_CONVEX_DEFENSE,
        "crash_defense",
        False,
        ("v8_predictions", "d_known_daily"),
        (
            ("crash_probability_minimum", CRASH_PROBABILITY_MINIMUM),
            ("factor_score_minimum", CRASH_FACTOR_SCORE_MINIMUM),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.CARRY_MOMENTUM_CONFIRMATION,
        "carry_trend",
        False,
        ("v8_predictions", "d_known_daily", "carry"),
        (
            ("carry_z_minimum", CARRY_Z_MINIMUM),
            ("momentum_20_minimum_in_direction", CARRY_MOMENTUM_MINIMUM),
            ("residual_score_minimum_in_direction", CARRY_RESIDUAL_SCORE_MINIMUM),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.CFTC_CROWDED_UNWIND,
        "positioning_reversal",
        False,
        ("v8_predictions", "d_known_daily", "cftc"),
        (
            ("cftc_crowd_z_minimum", CFTC_CROWD_Z_MINIMUM),
            ("reversal_momentum_minimum", CFTC_REVERSAL_MOMENTUM_MINIMUM),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.MACRO_SHOCK_ROTATION,
        "macro_event",
        False,
        ("v8_predictions", "d_known_daily", "cbr"),
        (
            ("rate_shock_z_minimum", MACRO_RATE_SHOCK_Z_MINIMUM),
            ("fx_shock_z_minimum", MACRO_FX_SHOCK_Z_MINIMUM),
            ("rate_sensitivity_RI", -1.0),
            ("rate_sensitivity_MIX", -1.0),
            ("rate_sensitivity_SI", 0.35),
            ("rate_sensitivity_BR", 0.0),
            ("fx_sensitivity_SI", 1.0),
            ("fx_sensitivity_BR", 0.50),
            ("fx_sensitivity_RI", -0.50),
            ("fx_sensitivity_MIX", -0.35),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.CONFIDENCE_CONCENTRATION,
        "uncertainty_concentration",
        False,
        ("v8_predictions", "d_known_daily"),
        (
            ("residual_snr_minimum", CONFIDENCE_SNR_MINIMUM),
            ("abstain_probability_maximum", CONFIDENCE_ABSTAIN_MAXIMUM),
            ("maximum_assets", CONFIDENCE_MAX_ASSETS),
        ),
    ),
    FixedCandidateSpec(
        AggressiveCandidateId.VOLATILITY_EXPANSION_BREAKOUT,
        "volume_volatility_breakout",
        False,
        ("v8_predictions", "d_known_daily", "d_known_10m"),
        (
            ("volatility_ratio_minimum", VOLATILITY_BREAKOUT_RATIO_MINIMUM),
            ("volume_ratio_minimum", VOLUME_BREAKOUT_RATIO_MINIMUM),
            ("residual_score_minimum", VOLATILITY_BREAKOUT_SCORE_MINIMUM),
            (
                "breakout_long_range_position_minimum",
                VOLATILITY_BREAKOUT_LONG_RANGE_POSITION_MINIMUM,
            ),
            (
                "breakout_short_range_position_maximum",
                VOLATILITY_BREAKOUT_SHORT_RANGE_POSITION_MAXIMUM,
            ),
            ("maximum_assets", VOLATILITY_BREAKOUT_MAX_ASSETS),
        ),
    ),
)


__all__ = [
    "AGGRESSIVE_CANDIDATE_IDS",
    "BASE_PROTOCOL_SHA256",
    "CANDIDATE_SPECS",
    "AggressiveCandidateId",
    "BreakoutAction",
    "BreakoutAssetIntent",
    "BreakoutAssetState",
    "BreakoutLockedPosition",
    "BreakoutPyramidState",
    "BreakoutUnresolvedExecution",
    "CandidateAnnualMetric",
    "CandidateDecision",
    "CandidateExecutionEvidence",
    "CandidateExitExecutionEvidence",
    "CandidateGateMetric",
    "CandidateRun",
    "CandidateSelectionRecord",
    "CausalAssetSnapshot",
    "CausalDecisionContext",
    "CorridorExitIntent",
    "CorridorPosition",
    "CorridorPositionStatus",
    "CorridorTransition",
    "FactualTenMinuteBar",
    "HoldingSleeveSchedule",
    "PointInTimeObservation",
    "ScheduledCandidateExecution",
    "apply_breakout_execution",
    "apply_volatility_corridor_exit",
    "mark_volatility_corridor_missing_exit_window",
    "open_volatility_corridor_position",
    "rank_gate_passing_candidates",
    "run_aggressive_candidate",
    "transition_volatility_corridor",
]
