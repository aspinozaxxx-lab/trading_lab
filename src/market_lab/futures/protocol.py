"""Strogii zapechatannyi protocol futures-v5 bez dostupa k holdout-dannym."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.io_utils import TEXT_ENCODING

FUTURES_V5_PROTOCOL_FILENAME = (  # Kanonicheskoe imya zapechatannogo YAML-protocola.
    "futures_v5_protocol.yaml"
)
FUTURES_V5_PROTOCOL_SHA256 = (  # SHA-256 tochnyh baitov kanonicheskogo YAML s BOM.
    "d73d17ffd9caeac46cbd3a353526c178df792070a4ea17744ab32abdfc32da38"
)


class StrictProtocolModel(BaseModel):
    """Zapreshchaet lishnie polya i mutaciyu razdelov protocola."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FuturesInstrumentProtocol(StrictProtocolModel):
    """Fiksiruet logical symbol, official asset_code i prefiks kontrakta."""

    logical_symbol: str = Field(min_length=1)
    asset_code: str = Field(min_length=1)
    security_prefix: str = Field(min_length=1)


class FuturesUniverseProtocol(StrictProtocolModel):
    """Fiksiruet ISS-rynok i chetyre development-serii futures."""

    engine: str = Field(min_length=1)
    market: str = Field(min_length=1)
    board: str = Field(min_length=1)
    instruments: list[FuturesInstrumentProtocol] = Field(min_length=4, max_length=4)


class FuturesHoldoutProtocol(StrictProtocolModel):
    """Opisyvaet odnorazovyi period bez razresheniya ego chitat ili skachivat."""

    start: date
    end: date
    status: str = Field(min_length=1)
    evaluation_budget: int = Field(ge=1)
    network_download_allowed: bool
    local_read_allowed: bool
    unlock_condition: str = Field(min_length=1)


class FuturesPeriodsProtocol(StrictProtocolModel):
    """Razdelyaet development i zapechatannyi vremennoy holdout."""

    development_start: date
    development_end: date
    holdout: FuturesHoldoutProtocol


class FuturesOuterFoldProtocol(StrictProtocolModel):
    """Zadaet odin expanding outer-fold s kalendarnym godom ocenki."""

    name: str = Field(min_length=1)
    train_start: date
    train_end: date
    outer_start: date
    outer_end: date


class FuturesValidationProtocol(StrictProtocolModel):
    """Fiksiruet pyat' outer-fold i pyatisessionnyi purge."""

    scheme: str = Field(min_length=1)
    purge_sessions: int = Field(ge=0)
    folds: list[FuturesOuterFoldProtocol] = Field(min_length=5, max_length=5)


class FuturesRollProtocol(StrictProtocolModel):
    """Fiksiruet causal roll posle dvuh sessii volume i contract OI."""

    ranking_inputs: list[str] = Field(min_length=2, max_length=2)
    dominance_sessions: int = Field(ge=1)
    dominance_ratio: float = Field(gt=0)
    hard_fallback_sessions_before_expiry: int = Field(ge=1)
    decision_time: str = Field(min_length=1)
    execution_time: str = Field(min_length=1)
    missing_overlap_policy: str = Field(min_length=1)
    execution_failure_policy: str = Field(min_length=1)
    adjustment_direction: str = Field(min_length=1)
    adjustment_method: str = Field(min_length=1)
    adjustment_anchor: str = Field(min_length=1)
    backward_adjustment_allowed: bool


class ParticipantOpenInterestProtocol(StrictProtocolModel):
    """Fiksiruet dostupnost participant OI tolko so sleduyushchei sessii."""

    availability_lag_sessions: int = Field(ge=0)
    usable_from: str = Field(min_length=1)
    same_session_use_allowed: bool


class FuturesFeatureTimingProtocol(StrictProtocolModel):
    """Obedinyaet zapechatannye lag-pravila vneshnih priznakov."""

    participant_open_interest: ParticipantOpenInterestProtocol


class FuturesCostsProtocol(StrictProtocolModel):
    """Fiksiruet tick-stress i udvoennyi fee-stress dlya kazhdoi nogi."""

    slippage_unit: str = Field(min_length=1)
    tick_stress_scenarios: list[int] = Field(min_length=3, max_length=3)
    fee_source: str = Field(min_length=1)
    fee_multiplier_scenarios: list[float] = Field(min_length=2, max_length=2)
    require_round_trip_costs: bool


class FuturesExecutionProtocol(StrictProtocolModel):
    """Fiksiruet konservativnye limity ispolneniya celymi kontraktami."""

    integer_contracts: bool
    maximum_gross_leverage: float = Field(gt=0)
    initial_margin_buffer_multiplier: float = Field(gt=0)
    maximum_participation: float = Field(gt=0, le=1)
    participation_denominator: str = Field(min_length=1)
    unknown_liquidity_policy: str = Field(min_length=1)
    costs: FuturesCostsProtocol


class FuturesPreHoldoutGatesProtocol(StrictProtocolModel):
    """Fiksiruet porogi, kotorye nel'zya izmenit posle development-resultatov."""

    minimum_positive_outer_folds: int = Field(ge=1)
    minimum_worst_fold_net_cagr: float
    minimum_aggregate_net_cagr: float
    minimum_aggregate_net_sharpe: float
    maximum_aggregate_drawdown: float = Field(gt=0, lt=1)
    minimum_double_cost_net_cagr: float
    maximum_failed_execution_events: int = Field(ge=0)
    maximum_unknown_participation_events: int = Field(ge=0)
    maximum_unknown_point_value_events: int = Field(ge=0)
    model_and_feature_seal_required: bool
    all_candidates_reported: bool
    unlock_scope: str = Field(min_length=1)


class FuturesResearchLimitsProtocol(StrictProtocolModel):
    """Yavno fiksiruet otsutstvuyushchie free-data i zapret broker-claim."""

    historical_bid_ask_available: bool
    historical_fee_schedule_complete: bool
    historical_initial_margin_complete: bool
    exact_intraday_rub_point_value_all_assets: bool
    conservative_proxy_must_be_versioned: bool
    broker_executable_pnl_claim_allowed: bool
    live_trading_allowed: bool


class FuturesStretchGateProtocol(StrictProtocolModel):
    """Pomeshchaet 50 procentov tolko v stretch, ne v selection ili garantiyu."""

    minimum_net_cagr: float = Field(gt=0)
    role: str = Field(min_length=1)
    used_for_model_selection: bool
    used_for_holdout_access: bool
    guarantee: bool
    live_trading_allowed: bool


class FuturesV5Protocol(StrictProtocolModel):
    """Predstavlyaet polnyi futures-v5 protocol i otklonyaet semantic drift."""

    protocol_name: str = Field(min_length=1)
    protocol_version: int = Field(ge=1)
    sealed_at_utc: str = Field(min_length=1)
    research_status: str = Field(min_length=1)
    universe: FuturesUniverseProtocol
    periods: FuturesPeriodsProtocol
    validation: FuturesValidationProtocol
    roll: FuturesRollProtocol
    feature_timing: FuturesFeatureTimingProtocol
    execution: FuturesExecutionProtocol
    pre_holdout_gates: FuturesPreHoldoutGatesProtocol
    research_limits: FuturesResearchLimitsProtocol
    stretch_gate: FuturesStretchGateProtocol

    @model_validator(mode="after")
    def reject_semantic_drift(self) -> FuturesV5Protocol:
        """Sravnivaet kazhdoe pole s kanonicheskoi semantikoi v5."""
        actual = self.model_dump(mode="json")
        drift = _first_semantic_drift(actual, EXPECTED_FUTURES_V5_SEMANTICS)
        if drift is not None:
            raise ValueError(f"Semantic drift futures-v5: {drift}")
        return self


EXPECTED_FUTURES_V5_SEMANTICS = {  # Kanonicheskii smysl, nezavisimyi ot YAML-parsera.
    "protocol_name": "futures-v5-causal-continuous",
    "protocol_version": 5,
    "sealed_at_utc": "2026-08-18T00:00:00Z",
    "research_status": "development_only_holdout_untouched",
    "universe": {
        "engine": "futures",
        "market": "forts",
        "board": "RFUD",
        "instruments": [
            {"logical_symbol": "Si", "asset_code": "Si", "security_prefix": "Si"},
            {"logical_symbol": "RI", "asset_code": "RTS", "security_prefix": "RI"},
            {"logical_symbol": "BR", "asset_code": "BR", "security_prefix": "BR"},
            {"logical_symbol": "MIX", "asset_code": "MIX", "security_prefix": "MX"},
        ],
    },
    "periods": {
        "development_start": "2018-01-01",
        "development_end": "2025-12-31",
        "holdout": {
            "start": "2026-01-01",
            "end": "2026-07-31",
            "status": "untouched",
            "evaluation_budget": 1,
            "network_download_allowed": False,
            "local_read_allowed": False,
            "unlock_condition": "sealed_development_passes_pre_holdout_gates",
        },
    },
    "validation": {
        "scheme": "outer_expanding_calendar_years",
        "purge_sessions": 5,
        "folds": [
            {
                "name": f"outer_{year}",
                "train_start": "2018-01-01",
                "train_end": f"{year - 1}-12-31",
                "outer_start": f"{year}-01-01",
                "outer_end": f"{year}-12-31",
            }
            for year in range(2021, 2026)
        ],
    },
    "roll": {
        "ranking_inputs": ["session_volume", "contract_open_interest"],
        "dominance_sessions": 2,
        "dominance_ratio": 1.0,
        "hard_fallback_sessions_before_expiry": 5,
        "decision_time": "session_close",
        "execution_time": "next_session_open",
        "missing_overlap_policy": "flat_skip",
        "execution_failure_policy": "carry_position_and_invalidate_run",
        "adjustment_direction": "forward_only",
        "adjustment_method": "additive",
        "adjustment_anchor": "settle",
        "backward_adjustment_allowed": False,
    },
    "feature_timing": {
        "participant_open_interest": {
            "availability_lag_sessions": 1,
            "usable_from": "next_session",
            "same_session_use_allowed": False,
        }
    },
    "execution": {
        "integer_contracts": True,
        "maximum_gross_leverage": 1.0,
        "initial_margin_buffer_multiplier": 2.0,
        "maximum_participation": 0.01,
        "participation_denominator": "lagged_contract_volume",
        "unknown_liquidity_policy": "reject_execution",
        "costs": {
            "slippage_unit": "ticks_per_leg",
            "tick_stress_scenarios": [1, 2, 4],
            "fee_source": "versioned_conservative_proxy",
            "fee_multiplier_scenarios": [1.0, 2.0],
            "require_round_trip_costs": True,
        },
    },
    "pre_holdout_gates": {
        "minimum_positive_outer_folds": 4,
        "minimum_worst_fold_net_cagr": -0.10,
        "minimum_aggregate_net_cagr": 0.12,
        "minimum_aggregate_net_sharpe": 0.80,
        "maximum_aggregate_drawdown": 0.25,
        "minimum_double_cost_net_cagr": 0.00,
        "maximum_failed_execution_events": 0,
        "maximum_unknown_participation_events": 0,
        "maximum_unknown_point_value_events": 0,
        "model_and_feature_seal_required": True,
        "all_candidates_reported": True,
        "unlock_scope": "one_time_research_evaluation_only",
    },
    "research_limits": {
        "historical_bid_ask_available": False,
        "historical_fee_schedule_complete": False,
        "historical_initial_margin_complete": False,
        "exact_intraday_rub_point_value_all_assets": False,
        "conservative_proxy_must_be_versioned": True,
        "broker_executable_pnl_claim_allowed": False,
        "live_trading_allowed": False,
    },
    "stretch_gate": {
        "minimum_net_cagr": 0.50,
        "role": "stretch_only",
        "used_for_model_selection": False,
        "used_for_holdout_access": False,
        "guarantee": False,
        "live_trading_allowed": False,
    },
}


def _first_semantic_drift(actual: Any, expected: Any, path: str = "$") -> str | None:
    """Nahodit pervoe otlichie tipa, klucha, poryadka ili znacheniya."""
    if type(actual) is not type(expected):
        return f"{path}: type {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(expected, dict):
        if list(actual) != list(expected):
            return f"{path}: keys/order {list(actual)!r} != {list(expected)!r}"
        for key in expected:
            drift = _first_semantic_drift(actual[key], expected[key], f"{path}.{key}")
            if drift is not None:
                return drift
        return None
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} != {len(expected)}"
        for index, expected_item in enumerate(expected):
            drift = _first_semantic_drift(actual[index], expected_item, f"{path}[{index}]")
            if drift is not None:
                return drift
        return None
    if actual != expected:
        return f"{path}: {actual!r} != {expected!r}"
    return None


def futures_protocol_sha256(path: Path) -> str:
    """Vozvrashchaet SHA-256 tochnyh baitov protocol-faila, vklyuchaya BOM."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_futures_protocol_seal(
    path: Path,
    expected_sha256: str = FUTURES_V5_PROTOCOL_SHA256,
) -> str:
    """Fail-closed sravnivaet protocol s ozhidaemym SHA-256 i vozvrashchaet hash."""
    actual_sha256 = futures_protocol_sha256(path)
    normalized_expected = expected_sha256.strip().lower()
    if len(normalized_expected) != 64 or any(
        symbol not in "0123456789abcdef" for symbol in normalized_expected
    ):
        raise ValueError("Ozhidaemyi SHA-256 dolzhen byt 64-znachnym hex")
    if actual_sha256 != normalized_expected:
        raise ValueError(
            "Futures-v5 protocol seal mismatch: "
            f"expected {normalized_expected}, actual {actual_sha256}"
        )
    return actual_sha256


def validate_futures_v5_protocol(payload: Any) -> FuturesV5Protocol:
    """Validiruet uzhe poluchennyi payload bez chteniya failov ili rynochnyh dannyh."""
    return FuturesV5Protocol.model_validate(payload)


def load_futures_v5_protocol(
    path: Path,
    *,
    verify_seal: bool = True,
) -> FuturesV5Protocol:
    """Chitaet tolko YAML-protocol i po umolchaniyu proveriaet ego byte-seal."""
    protocol_path = path.resolve()
    if verify_seal:
        verify_futures_protocol_seal(protocol_path)
    with protocol_path.open("r", encoding=TEXT_ENCODING) as stream:
        payload = yaml.safe_load(stream)
    return validate_futures_v5_protocol(payload)
