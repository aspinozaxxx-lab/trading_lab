"""Causal deterministic portfolio constructor dlya sealed futures-v8."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from math import isfinite
from numbers import Real
from typing import Protocol
from zoneinfo import ZoneInfo

# Fiksirovannyi cross-asset universe portfolio v8.
V8_PORTFOLIO_ASSETS = ("BR", "MIX", "RI", "SI")
# Chislo odnovremenno aktivnyh common-session sleeves.
HOLDING_SLEEVE_COUNT = 5
# Vklad kazhdogo unit sleeve v aggregate target.
SLEEVE_WEIGHT = 0.20
# Gross budget obshchego factor komponenta unit sleeve.
FACTOR_GROSS_BUDGET = 0.35
# Gross budget market-neutral residual komponenta unit sleeve.
RESIDUAL_GROSS_BUDGET = 0.65
# Zhestkii combined gross cap portfolio.
COMBINED_GROSS_CAP = 1.0
# Sealed minimum absolute factor signal-to-noise dlya vhoda.
FACTOR_ABSTAIN_Z_THRESHOLD = 1.0
# Floor D-known daily volatility dlya stabil'nogo inverse-vol.
DAILY_VOLATILITY_FLOOR = 0.01
# Edinoe local'noe vremya formirovaniya resheniya.
DECISION_LOCAL_TIME = time(18, 50)
# Timezone birzhevogo resheniya v sealed protocole.
MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")
# Granica zablokirovannogo holdout, nedostupnogo constructoru.
PROTECTED_HOLDOUT_START = date(2026, 1, 1)
# Yavnyi vladelec whole-contract sizing posle notional handoff.
INTEGER_SIZING_OWNER = "ledger"
# Tol'ko machine-epsilon guard, ne strategicheskii porog.
FLOAT_TOLERANCE = 1e-12


class SealedPortfolioProtocol(Protocol):
    """Minimal'nyi typed view sealed portfolio sekcii config v8."""

    holding_sleeve_count: int
    sleeve_weight: float
    new_sleeve_cadence: str
    sleeve_entry: str
    sleeve_exit: str
    factor_gross_budget: float
    residual_gross_budget: float
    combined_gross_cap: float
    factor_snr_definition: str
    factor_common_exposure: str
    factor_asset_allocation: str
    factor_abstain_z_threshold: float
    factor_abstain_rule: str
    residual_score_source: str
    residual_demeaning: str
    residual_inverse_volatility: str
    residual_net_notional_neutralization: str
    residual_neutrality: str
    inference_contract_eligibility: str
    new_sleeve_cash_condition: str
    selected_contract_binding: str
    post_entry_contract_failure: str
    invalid_or_same_contract_impossible_position: str
    uncertainty_abstain_position: str
    no_leverage_above_one: bool
    minimum_trade_delta_contracts: int
    integer_contract_rounding: str
    costs_and_initial_margin: str
    selection_tuning: bool


def assert_v8_portfolio_constants_match_protocol(protocol: SealedPortfolioProtocol) -> None:
    """Fail-closed svyazyvaet constructor s byte-sealed portfolio protocolom."""
    expected: dict[str, object] = {
        "holding_sleeve_count": HOLDING_SLEEVE_COUNT,
        "sleeve_weight": SLEEVE_WEIGHT,
        "new_sleeve_cadence": "each_common_session",
        "sleeve_entry": "factual_19_20_19_30_execution_window",
        "sleeve_exit": "analogous_execution_window_after_d_plus_5_common_sessions",
        "factor_gross_budget": FACTOR_GROSS_BUDGET,
        "residual_gross_budget": RESIDUAL_GROSS_BUDGET,
        "combined_gross_cap": COMBINED_GROSS_CAP,
        "factor_snr_definition": "factor_location_divided_by_factor_scale",
        "factor_common_exposure": "sign_of_factor_snr_if_not_abstained",
        "factor_asset_allocation": "inverse_ex_ante_volatility_across_eligible_assets",
        "factor_abstain_z_threshold": FACTOR_ABSTAIN_Z_THRESHOLD,
        "factor_abstain_rule": "cash_when_absolute_factor_snr_below_1",
        "residual_score_source": "residual_decision_score",
        "residual_demeaning": "cross_section_demean_across_eligible_assets",
        "residual_inverse_volatility": "inverse_ex_ante_volatility_after_demeaning",
        "residual_net_notional_neutralization": (
            "rescale_long_and_short_legs_to_equal_absolute_notional"
        ),
        "residual_neutrality": "net_notional_neutral_only_no_beta_claim",
        "inference_contract_eligibility": (
            "decision_time_current_contract_nominal_maturity_and_session_calendar_only"
        ),
        "new_sleeve_cash_condition": (
            "cash_only_when_decision_time_known_contract_cannot_span_five_common_sessions"
        ),
        "selected_contract_binding": "lock_decision_time_contract_for_all_five_sessions",
        "post_entry_contract_failure": (
            "carry_and_record_execution_failure_not_hindsight_cash_filter"
        ),
        "invalid_or_same_contract_impossible_position": "cash",
        "uncertainty_abstain_position": "cash",
        "no_leverage_above_one": True,
        "minimum_trade_delta_contracts": 1,
        "integer_contract_rounding": "truncate_toward_zero_after_allocation",
        "costs_and_initial_margin": "handled_by_ledger",
        "selection_tuning": False,
    }
    for field_name, expected_value in expected.items():
        actual_value = getattr(protocol, field_name, None)
        if actual_value != expected_value:
            raise ValueError(
                f"Portfolio protocol drift: {field_name}={actual_value!r}, "
                f"expected {expected_value!r}"
            )


def _optional_numeric(value: float | None, label: str) -> float | None:
    """Normalizuet optional numeric pole bez skrytogo zapolneniya missing."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} dolzhen byt' chislom ili None")
    return float(value)


def _normalized_contract_id(value: str | None) -> str | None:
    """Normalizuet decision-time contract, sohranyaya missing kak cash."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("contract_id dolzhen byt' strokoj ili None")
    normalized = value.strip()
    if not normalized:
        return None
    if any(character.isspace() for character in normalized):
        raise ValueError("contract_id ne mozhet soderzhat' probely")
    return normalized


@dataclass(frozen=True, slots=True)
class AssetDecisionInput:
    """D-known model, volatility i contract polya odnogo asseta."""

    asset: str
    contract_id: str | None
    residual_decision_score: float | None
    total_scale: float | None
    ex_ante_daily_vol20: float | None
    asset_mask: bool
    nominal_span_eligible: bool

    def __post_init__(self) -> None:
        """Proveryaet tipy, no ostavlyaet missing/nonfinite dlya cash maski."""
        if not isinstance(self.asset, str):
            raise TypeError("asset dolzhen byt' strokoj")
        if not isinstance(self.asset_mask, bool):
            raise TypeError("asset_mask dolzhen byt' bool")
        if not isinstance(self.nominal_span_eligible, bool):
            raise TypeError("nominal_span_eligible dolzhen byt' bool")
        object.__setattr__(self, "contract_id", _normalized_contract_id(self.contract_id))
        for field_name in (
            "residual_decision_score",
            "total_scale",
            "ex_ante_daily_vol20",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_numeric(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class DecisionModelSnapshot:
    """Polnyi odnovremennyi model snapshot odnogo common-session resheniya."""

    decision_at: datetime
    factor_location: float | None
    factor_scale: float | None
    factor_decision_score: float | None
    assets: tuple[AssetDecisionInput, ...]

    def __post_init__(self) -> None:
        """Trebuet D18:50 Moscow, pre-2026 i polnyi fixed-order universe."""
        if not isinstance(self.decision_at, datetime):
            raise TypeError("decision_at dolzhen byt' datetime")
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("decision_at dolzhen imet' timezone")
        local = self.decision_at.astimezone(MOSCOW_TIMEZONE)
        if local.time().replace(tzinfo=None) != DECISION_LOCAL_TIME:
            raise ValueError("V8 portfolio snapshot dolzhen byt' v 18:50 Moscow")
        if local.date() >= PROTECTED_HOLDOUT_START:
            raise ValueError("V8 portfolio guard zapreshchaet 2026 holdout")
        assets = tuple(self.assets)
        if any(not isinstance(item, AssetDecisionInput) for item in assets):
            raise TypeError("assets dolzhny soderzhat' AssetDecisionInput")
        if tuple(item.asset for item in assets) != V8_PORTFOLIO_ASSETS:
            raise ValueError("Snapshot dolzhen soderzhat' BR,MIX,RI,SI v fixed order")
        object.__setattr__(self, "decision_at", self.decision_at.astimezone(UTC))
        object.__setattr__(self, "assets", assets)
        for field_name in ("factor_location", "factor_scale", "factor_decision_score"):
            object.__setattr__(
                self,
                field_name,
                _optional_numeric(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class AssetSleeveProvenance:
    """Audit vybrannogo contracta, eligibility i komponentov odnogo sleeve."""

    asset: str
    contract_id: str | None
    eligible: bool
    eligibility_reason: str
    inverse_volatility: float
    residual_decision_score: float | None
    total_scale: float | None
    factor_weight: float
    residual_weight: float
    combined_weight: float


@dataclass(frozen=True, slots=True)
class SleeveProvenance:
    """Locked pyatisessionnyi unit sleeve do primeneniya 0.20 ladder weight."""

    sequence_number: int
    opened_at: datetime
    active_through_sequence: int
    exit_before_sequence: int
    factor_signal_to_noise: float | None
    factor_state: str
    residual_state: str
    factor_gross: float
    residual_gross: float
    combined_gross: float
    combined_net: float
    assets: tuple[AssetSleeveProvenance, ...]


@dataclass(frozen=True, slots=True)
class ContractTargetWeight:
    """Deterministic aggregate target weight odnogo locked contracta."""

    asset: str
    contract_id: str
    target_weight: float


@dataclass(frozen=True, slots=True)
class DesiredNotionalTarget:
    """Signed notional handoff bez contract rounding ili execution ceny."""

    asset: str
    contract_id: str
    target_weight: float
    desired_notional: float


@dataclass(frozen=True, slots=True)
class DesiredNotionalHandoff:
    """Granica portfolio--ledger: notional zdes', integer sizing v ledger."""

    decision_at: datetime
    portfolio_notional: float
    integer_sizing_owner: str
    targets: tuple[DesiredNotionalTarget, ...]


@dataclass(frozen=True, slots=True)
class PortfolioDecision:
    """Aggregate poslednih pyati sleeves i ikh causal audit na decision time."""

    sequence_number: int
    decision_at: datetime
    new_sleeve: SleeveProvenance
    active_sleeves: tuple[SleeveProvenance, ...]
    target_weights: tuple[ContractTargetWeight, ...]
    gross_weight: float
    net_weight: float

    def desired_notional_handoff(self, portfolio_notional: float) -> DesiredNotionalHandoff:
        """Masshtabiruet weights v notional, ne prisvaivaya sebe integer sizing."""
        if (
            isinstance(portfolio_notional, bool)
            or not isinstance(portfolio_notional, Real)
            or not isfinite(float(portfolio_notional))
            or float(portfolio_notional) <= 0.0
        ):
            raise ValueError("portfolio_notional dolzhen byt' finite i > 0")
        normalized = float(portfolio_notional)
        targets = tuple(
            DesiredNotionalTarget(
                asset=item.asset,
                contract_id=item.contract_id,
                target_weight=item.target_weight,
                desired_notional=item.target_weight * normalized,
            )
            for item in self.target_weights
        )
        return DesiredNotionalHandoff(
            decision_at=self.decision_at,
            portfolio_notional=normalized,
            integer_sizing_owner=INTEGER_SIZING_OWNER,
            targets=targets,
        )


def _finite(value: float | None) -> bool:
    """Pokazyvaet, chto optional value prisutstvuet i finite."""
    return value is not None and isfinite(value)


def _asset_eligibility(item: AssetDecisionInput) -> tuple[bool, str, float]:
    """Stroit fail-closed D-known eligibility i inverse volatility."""
    if not item.asset_mask:
        return False, "asset_mask_false", 0.0
    if item.contract_id is None:
        return False, "missing_current_contract", 0.0
    if not item.nominal_span_eligible:
        return False, "nominal_span_ineligible_at_decision", 0.0
    if not _finite(item.ex_ante_daily_vol20) or item.ex_ante_daily_vol20 < 0.0:
        return False, "missing_or_invalid_ex_ante_vol20", 0.0
    if not _finite(item.total_scale) or item.total_scale <= 0.0:
        return False, "missing_or_invalid_total_scale", 0.0
    if not _finite(item.residual_decision_score):
        return False, "missing_or_invalid_residual_decision_score", 0.0
    volatility = max(item.ex_ante_daily_vol20, DAILY_VOLATILITY_FLOOR)
    return True, "eligible", 1.0 / volatility


def _factor_direction(snapshot: DecisionModelSnapshot) -> tuple[int, float | None, str]:
    """Primensyaet sealed SNR abstention i consistency factor decision score."""
    if (
        not _finite(snapshot.factor_location)
        or not _finite(snapshot.factor_scale)
        or snapshot.factor_scale <= 0.0
        or not _finite(snapshot.factor_decision_score)
    ):
        return 0, None, "cash_invalid_factor_inputs"
    signal_to_noise = snapshot.factor_location / snapshot.factor_scale
    if abs(signal_to_noise) < FACTOR_ABSTAIN_Z_THRESHOLD:
        return 0, signal_to_noise, "cash_factor_snr_below_one"
    direction = 1 if signal_to_noise > 0.0 else -1
    decision_direction = (
        1
        if snapshot.factor_decision_score > 0.0
        else -1
        if snapshot.factor_decision_score < 0.0
        else 0
    )
    if decision_direction != direction:
        return 0, signal_to_noise, "cash_factor_decision_uncertain_or_inconsistent"
    return direction, signal_to_noise, "active_long" if direction > 0 else "active_short"


def _build_sleeve(snapshot: DecisionModelSnapshot, sequence_number: int) -> SleeveProvenance:
    """Stroit odin unit sleeve iz tol'ko tekushchego decision snapshot."""
    eligibility = tuple(_asset_eligibility(item) for item in snapshot.assets)
    eligible_indices = [index for index, item in enumerate(eligibility) if item[0]]
    factor_direction, factor_snr, factor_state = _factor_direction(snapshot)
    factor_weights = [0.0] * len(snapshot.assets)
    if not eligible_indices:
        factor_direction = 0
        factor_state = "cash_no_eligible_assets"
    if factor_direction:
        denominator = sum(eligibility[index][2] for index in eligible_indices)
        for index in eligible_indices:
            factor_weights[index] = (
                factor_direction
                * FACTOR_GROSS_BUDGET
                * eligibility[index][2]
                / denominator
            )

    residual_weights = [0.0] * len(snapshot.assets)
    residual_state = "cash_insufficient_or_constant_cross_section"
    if len(eligible_indices) >= 2:
        mean_score = sum(
            snapshot.assets[index].residual_decision_score for index in eligible_indices
        ) / len(eligible_indices)
        scaled_scores = {
            index: (
                snapshot.assets[index].residual_decision_score - mean_score
            )
            * eligibility[index][2]
            for index in eligible_indices
        }
        positive_sum = sum(value for value in scaled_scores.values() if value > 0.0)
        negative_sum = sum(-value for value in scaled_scores.values() if value < 0.0)
        if positive_sum > 0.0 and negative_sum > 0.0:
            half_budget = RESIDUAL_GROSS_BUDGET / 2.0
            for index, value in scaled_scores.items():
                if value > 0.0:
                    residual_weights[index] = half_budget * value / positive_sum
                elif value < 0.0:
                    residual_weights[index] = half_budget * value / negative_sum
            residual_state = "active_equal_long_short_notional"

    assets = tuple(
        AssetSleeveProvenance(
            asset=item.asset,
            contract_id=item.contract_id,
            eligible=eligibility[index][0],
            eligibility_reason=eligibility[index][1],
            inverse_volatility=eligibility[index][2],
            residual_decision_score=item.residual_decision_score,
            total_scale=item.total_scale,
            factor_weight=factor_weights[index],
            residual_weight=residual_weights[index],
            combined_weight=factor_weights[index] + residual_weights[index],
        )
        for index, item in enumerate(snapshot.assets)
    )
    factor_gross = sum(abs(item.factor_weight) for item in assets)
    residual_gross = sum(abs(item.residual_weight) for item in assets)
    combined_gross = sum(abs(item.combined_weight) for item in assets)
    combined_net = sum(item.combined_weight for item in assets)
    if factor_gross > FACTOR_GROSS_BUDGET + FLOAT_TOLERANCE:
        raise RuntimeError("Factor gross prevysil sealed budget")
    if residual_gross > RESIDUAL_GROSS_BUDGET + FLOAT_TOLERANCE:
        raise RuntimeError("Residual gross prevysil sealed budget")
    if combined_gross > COMBINED_GROSS_CAP + FLOAT_TOLERANCE:
        raise RuntimeError("Combined gross prevysil sealed cap")
    return SleeveProvenance(
        sequence_number=sequence_number,
        opened_at=snapshot.decision_at,
        active_through_sequence=sequence_number + HOLDING_SLEEVE_COUNT - 1,
        exit_before_sequence=sequence_number + HOLDING_SLEEVE_COUNT,
        factor_signal_to_noise=factor_snr,
        factor_state=factor_state,
        residual_state=residual_state,
        factor_gross=factor_gross,
        residual_gross=residual_gross,
        combined_gross=combined_gross,
        combined_net=combined_net,
        assets=assets,
    )


def _validate_ordered_snapshots(snapshots: Sequence[DecisionModelSnapshot]) -> None:
    """Fail-closed ot duplicate, shuffle i nepolnogo typed snapshot."""
    previous: datetime | None = None
    for snapshot in snapshots:
        if not isinstance(snapshot, DecisionModelSnapshot):
            raise TypeError("snapshots dolzhny soderzhat' DecisionModelSnapshot")
        if previous is not None and snapshot.decision_at <= previous:
            raise ValueError("Portfolio snapshots dolzhny byt' strogo chronologichny bez duplicate")
        previous = snapshot.decision_at


def build_v8_portfolio_path(
    snapshots: Sequence[DecisionModelSnapshot],
) -> tuple[PortfolioDecision, ...]:
    """Stroit append-only target path s odnim 0.20 sleeve na common session."""
    frozen = tuple(snapshots)
    _validate_ordered_snapshots(frozen)
    sleeves: list[SleeveProvenance] = []
    seen_contracts: dict[tuple[str, str], int] = {}
    decisions: list[PortfolioDecision] = []
    for sequence_number, snapshot in enumerate(frozen):
        new_sleeve = _build_sleeve(snapshot, sequence_number)
        sleeves.append(new_sleeve)
        for item in new_sleeve.assets:
            if item.contract_id is not None:
                seen_contracts.setdefault((item.asset, item.contract_id), len(seen_contracts))
        active = tuple(sleeves[max(0, sequence_number - HOLDING_SLEEVE_COUNT + 1) :])
        aggregate = dict.fromkeys(seen_contracts, 0.0)
        for sleeve in active:
            for item in sleeve.assets:
                if item.contract_id is not None:
                    aggregate[(item.asset, item.contract_id)] += (
                        SLEEVE_WEIGHT * item.combined_weight
                    )
        asset_rank = {asset: index for index, asset in enumerate(V8_PORTFOLIO_ASSETS)}
        ordered_keys = sorted(
            seen_contracts,
            key=lambda key: (asset_rank[key[0]], seen_contracts[key], key[1]),
        )
        targets = tuple(
            ContractTargetWeight(asset=asset, contract_id=contract, target_weight=aggregate[key])
            for key in ordered_keys
            for asset, contract in (key,)
        )
        gross_weight = sum(abs(item.target_weight) for item in targets)
        net_weight = sum(item.target_weight for item in targets)
        if gross_weight > COMBINED_GROSS_CAP + FLOAT_TOLERANCE:
            raise RuntimeError("Aggregate pyati sleeves prevysil gross cap")
        decisions.append(
            PortfolioDecision(
                sequence_number=sequence_number,
                decision_at=snapshot.decision_at,
                new_sleeve=new_sleeve,
                active_sleeves=active,
                target_weights=targets,
                gross_weight=gross_weight,
                net_weight=net_weight,
            )
        )
    return tuple(decisions)


__all__ = [
    "COMBINED_GROSS_CAP",
    "DAILY_VOLATILITY_FLOOR",
    "FACTOR_ABSTAIN_Z_THRESHOLD",
    "FACTOR_GROSS_BUDGET",
    "HOLDING_SLEEVE_COUNT",
    "INTEGER_SIZING_OWNER",
    "RESIDUAL_GROSS_BUDGET",
    "SLEEVE_WEIGHT",
    "V8_PORTFOLIO_ASSETS",
    "AssetDecisionInput",
    "AssetSleeveProvenance",
    "ContractTargetWeight",
    "DecisionModelSnapshot",
    "DesiredNotionalHandoff",
    "DesiredNotionalTarget",
    "PortfolioDecision",
    "SealedPortfolioProtocol",
    "SleeveProvenance",
    "assert_v8_portfolio_constants_match_protocol",
    "build_v8_portfolio_path",
]
