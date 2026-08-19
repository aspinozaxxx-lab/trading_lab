"""Validity-aware causal context futures-v8 bez targets, PnL i protected 2026."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from math import isclose, isfinite, log, sqrt
from pathlib import Path
from statistics import fmean
from typing import Any, Final
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from market_lab.futures.cftc_radar import (
    CFTC_CHANNEL_COMPONENTS,
    build_causal_cftc_asset_scores,
    build_causal_cftc_features,
    official_development_release_overrides,
)
from market_lab.futures_v8.aggressive_strategies import (
    BASE_PROTOCOL_SHA256,
    V8_ASSET_IDS,
    CausalAssetSnapshot,
    CausalDecisionContext,
    PointInTimeObservation,
)

# Kanonicheskii protocol validity-aware context, zapechatannyi do candidate PnL.
DEFAULT_CONTEXT_PROTOCOL_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "configs" / "futures_v8_evaluation_context.yaml"
)
# SHA-256 tochnyh BOM YAML baitov; obnovlyaetsya tol'ko vmeste s protocol sidecar.
DEFAULT_CONTEXT_PROTOCOL_SHA256: Final[str] = (
    "84573f410cd28e101395a9f87ecd8c436c588d3fcd37e3a016990d3c1d8d45ba"
)
# Exact schema target-free context source, ne dopushchennogo poka v legacy evaluator.
CONTEXT_SOURCE_SCHEMA: Final[str] = "market-lab-futures-v8-context-source-v2"
# Yavnoe imya konservativnogo proxy, kotoryi ne yavlyaetsya five-session proof.
NOMINAL_SPAN_RULE: Final[str] = "calendar_14d_conservative_proxy"
# Minimal'noe chislo strictly-prior znachenii dlya expanding z.
EXPANDING_Z_MINIMUM_HISTORY: Final[int] = 60
# Hard clip expanding z posle rascheta na strictly-prior history.
EXPANDING_Z_CLIP: Final[float] = 5.0
# Chislo scheduled 10m bucket starts 10:00..18:40 MSK inclusive.
MAIN_SESSION_EXPECTED_BUCKETS: Final[int] = 53
# Predeclared 90-percent coverage floor: ceil(53 * 0.90) = 48.
MAIN_SESSION_MINIMUM_BUCKETS: Final[int] = 48
# Exact poslednii D-known bar dlya raw close.
MAIN_SESSION_CLOSE_BAR_OPEN: Final[time] = time(18, 40)
# Exact decision i scheduled close poslednego main-session bara.
MAIN_SESSION_CLOSE_BAR_CLOSE: Final[time] = time(18, 50)
# Exact evaluation-only common-decision horizon; ne strategy input.
EVALUATION_EXIT_HORIZON_DECISIONS: Final[int] = 5
# Fiksirovannaya stolitsa ekonomicheskogo ledgera; ne runner knob.
INITIAL_CAPITAL_RUB: Final[float] = 1_000_000.0
# Sealed research-only spec proxy dataset dlya point value, fee i initial margin.
SPEC_PROXY_DATASET_SHA256: Final[str] = (
    "8494235f8782a258ed86d448c1c57adf2d313062da06845211991bda2f76d682"
)
# Exact real 1269x4 OOS prediction source bez target columns.
BASE_PREDICTIONS_SHA256: Final[str] = (
    "ca7dae8d856e512a6b3e476662b73d7d7f4f87521f0c103606b147f117acd437"
)
# Exact V2 target-free regime manifest i ego ensemble parquet.
REGIME_ENRICHMENT_MANIFEST_SHA256: Final[str] = (
    "3de404989d18d04e668e5880871b1aa98b74b756a6f72e62553961e4358e2727"
)
REGIME_ENRICHMENT_SHA256: Final[str] = (
    "4fd847f49f837516e637c81c81d17344ccf3ff781c808d1318da7ce17f40c14a"
)
# Vse dynamic inputs, kotorye obyazany popast' v artifact dependency bundle.
REQUIRED_CONTEXT_DEPENDENCIES: Final[tuple[str, ...]] = (
    "v8_assembly_manifest",
    "v8_assembly",
    "base_predictions",
    "checkpoint_identities",
    "regime_enrichment_manifest",
    "regime_enrichment",
    "adjusted_daily_chain",
    "active_contract_map",
    "main_session_10m",
    "cbr_manifest",
    "cftc_manifest",
    "carry_pit",
    "cftc_pit",
    "cbr_key_rate_pit",
    "cbr_usdrub_pit",
    "spec_proxy_dataset",
    "spec_proxy_manifest",
    "aggressive_catalog",
    "aggressive_catalog_sidecar",
    "aggressive_implementation",
    "context_implementation",
)
# Granica fizicheski zapreshchennogo market/target holdout.
PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)
# Zapreshchennye imena, kotorye context builder ne dolzhen chitat' ili sohranyat'.
FORBIDDEN_CONTEXT_TOKENS: Final[tuple[str, ...]] = (
    "target",
    "label",
    "pnl",
    "realized_return",
    "future_return",
)
# Standardnye futures month codes, prichinno razreshimye iz contract code.
FUTURES_MONTH_CODES: Final[Mapping[str, int]] = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}
# Contract-code suffix; podderzhivaet canonical id s ':' i long-name tokenami.
_CONTRACT_SUFFIX_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:^|[^A-Z0-9])([A-Z]{1,8})([FGHJKMNQUVXZ])(\d{1,2})(?=$|[^0-9])"
)


def _sha256_bytes(content: bytes) -> str:
    """Vozvrashchaet lower-case SHA-256 bez neodnoznachnogo text decode."""
    return sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    """Hashiruet artifact streamingom bez izmeneniya faila."""
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    """Hashiruet canonical JSON payload s zapretom NaN."""
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: (
            value.isoformat() if isinstance(value, (date, datetime)) else str(value)
        ),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _require_sha256(value: str, label: str) -> str:
    """Trebuet exact lower/upper hex SHA-256 i vozvrashchaet lower-case."""
    normalized = str(value).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} dolzhen byt' SHA-256")
    return normalized


def _require_identifier(value: str, label: str) -> str:
    """Trebuet nepustoi identifier bez kraevyh probelov."""
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} dolzhen byt' nepustym bez kraevyh probelov")
    return value


def _resolve_project_file(relative_path: str, label: str) -> Path:
    """Razreshaet tol'ko relative project path bez symlink/path escape."""
    relative = Path(_require_identifier(relative_path, label))
    project_root = DEFAULT_CONTEXT_PROTOCOL_PATH.resolve().parents[1]
    if relative.is_absolute():
        raise ValueError(f"{label} dolzhen byt' relative project path")
    resolved = (project_root / relative).resolve()
    if not resolved.is_relative_to(project_root) or not resolved.is_file():
        raise ValueError(f"{label} otsutstvuet ili vykhodit za project root")
    return resolved


def _require_aware(value: datetime, label: str, *, allow_nominal_2026: bool = False) -> datetime:
    """Normalizuet aware timestamp v UTC i blokiruet protected observations."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} dolzhen byt' timezone-aware datetime")
    normalized = value.astimezone(UTC)
    if not allow_nominal_2026 and normalized.date() >= PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} pytayetsya ispol'zovat' protected 2026")
    return normalized


def _finite(value: float, label: str) -> float:
    """Trebuet finite numeric bez bool coercion."""
    if isinstance(value, bool):
        raise TypeError(f"{label} ne mozhet byt' bool")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{label} dolzhen byt' finite")
    return numeric


@dataclass(frozen=True, slots=True)
class EvaluationContextProtocol:
    """Typed minimum iz byte-sealed context YAML, nuzhnyi builderu."""

    path: Path
    sha256: str
    protocol_name: str
    protocol_version: int
    base_protocol_sha256: str
    minimum_prior_observations: int
    clip_minimum: float
    clip_maximum: float
    nominal_span_rule: str
    minimum_calendar_days: int
    initial_capital_rub: float
    required_dependency_names: tuple[str, ...]
    dependency_pins: Mapping[str, tuple[str, str]]
    raw: Mapping[str, Any]


def _read_context_sidecar(path: Path) -> str:
    """Chitaet exact ``sha256  filename`` sidecar s BOM support."""
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(sidecar)
    parts = sidecar.read_text(encoding="utf-8-sig").strip().split()
    if len(parts) != 2 or parts[1] != path.name:
        raise ValueError("context sidecar dolzhen soderzhat' exact hash i filename")
    return _require_sha256(parts[0], "context sidecar hash")


def load_context_protocol(
    path: Path = DEFAULT_CONTEXT_PROTOCOL_PATH,
) -> EvaluationContextProtocol:
    """Proveriaet byte seal, sidecar i exact non-tunable causal formulas."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    actual = _sha256_file(resolved)
    if _read_context_sidecar(resolved) != actual:
        raise ValueError("context protocol sidecar seal mismatch")
    if resolved == DEFAULT_CONTEXT_PROTOCOL_PATH.resolve() and (
        actual != DEFAULT_CONTEXT_PROTOCOL_SHA256
    ):
        raise ValueError("default context protocol seal mismatch")
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("context protocol dolzhen byt' YAML object")
    dependencies = payload.get("dependencies")
    standardization = payload.get("standardization")
    nominal = payload.get("nominal_span")
    market = payload.get("market")
    validity = payload.get("validity")
    evaluation_exit = payload.get("evaluation_exit")
    economics = payload.get("economics")
    artifact = payload.get("artifact")
    if not all(
        isinstance(item, dict)
        for item in (
            dependencies,
            standardization,
            nominal,
            market,
            validity,
            evaluation_exit,
            economics,
            artifact,
        )
    ):
        raise ValueError("context protocol ne soderzhit required typed sections")
    if dependencies["base_protocol_sha256"] != BASE_PROTOCOL_SHA256:
        raise ValueError("context protocol base SHA drift")
    if dependencies.get("base_predictions_sha256") != BASE_PREDICTIONS_SHA256:
        raise ValueError("context base prediction SHA drift")
    if (
        dependencies.get("regime_enrichment_manifest_sha256") != REGIME_ENRICHMENT_MANIFEST_SHA256
        or dependencies.get("regime_enrichment_sha256") != REGIME_ENRICHMENT_SHA256
    ):
        raise ValueError("context V2 regime source SHA drift")
    required_exact = {
        "signal_price_basis": ("causal_raw_10m_forward_additive_adjusted_active_contract"),
        "signal_chain_scope": "economic_asset_chain_across_rolls_no_reset",
        "daily_source": "verified_raw_10m_only",
        "daily_session_interval": ("previous_d_18_50_exclusive_to_current_d_18_50_inclusive"),
        "daily_candle_cutoff": "raw_end_at_lte_scheduled_close_lte_decision_at",
        "active_contract_and_adjustment_as_of": ("known_at_lte_previous_decision_at"),
        "final_daily_panel_role": "qa_only_never_numeric_fallback",
        "final_daily_panel_qa_scope": "published_2021_2025_context_rows_only",
        "final_daily_panel_close_reconciliation": ("global_artifact_no_go_on_unexplained_mismatch"),
        "execution_reference_price_basis": "raw_active_contract",
        "close_formula": "raw_close_of_exact_scheduled_18_40_to_18_50_msk_bar",
        "close_fallback": "forbidden",
        "invalid_session_policy": "optional_none_never_impute",
    }
    if any(market.get(key) != value for key, value in required_exact.items()):
        raise ValueError("context market formula drift")
    if (
        market.get("atr20", {}).get("chain_scope")
        != "causal_forward_additive_economic_asset_chain_across_rolls_no_reset"
        or market.get("momentum20", {}).get("chain_scope")
        != "causal_forward_additive_economic_asset_chain_across_rolls_no_reset"
    ):
        raise ValueError("context adjusted signal chain scope drift")
    if standardization.get("formula") != (
        "(current_value-mean_strictly_prior_history)/population_std_strictly_prior_history"
    ):
        raise ValueError("context expanding-z formula drift")
    if (
        standardization.get("ddof") != 0
        or standardization.get("minimum_prior_observations") != EXPANDING_Z_MINIMUM_HISTORY
        or float(standardization.get("clip_minimum", 0.0)) != -EXPANDING_Z_CLIP
        or float(standardization.get("clip_maximum", 0.0)) != EXPANDING_Z_CLIP
        or standardization.get("zero_std_policy") != "missing"
        or standardization.get("future_append_invariance_required") is not True
    ):
        raise ValueError("context expanding-z ddof drift")
    expected_channels = {
        "carry_z": ("sealed_v8_roll_yield", "per_asset", "decision_snapshot"),
        "cftc_crowd_z": (
            "sealed_v8_cftc_primary_score",
            "per_asset",
            "unique_composite_report_release_observation_id",
        ),
        "key_rate_change_z": (
            "causal_cbr_key_rate_change",
            "global",
            "unique_consecutive_level_change_observation_id",
        ),
        "usd_rub_return_z": (
            "causal_cbr_usdrub_return_1",
            "global",
            "unique_release_observation_id",
        ),
    }
    channels = standardization.get("channels", {})
    if {
        name: (
            channels.get(name, {}).get("raw_source"),
            channels.get(name, {}).get("scope"),
            channels.get(name, {}).get("history_unit"),
        )
        for name in expected_channels
    } != expected_channels:
        raise ValueError("context expanding-z channel semantics drift")
    if (
        nominal.get("rule") != NOMINAL_SPAN_RULE
        or nominal.get("exact_five_session_proof_claimed") is not False
    ):
        raise ValueError("context nominal proxy drift")
    if validity.get("missing_policy") != "optional_none_never_impute":
        raise ValueError("context missing policy drift")
    expected_validity = {
        "model_input_valid": "base_prediction_asset_valid_and_finite_required_model_outputs",
        "decision_market_valid": "all_required_market_features_current_and_finite",
        "planned_contract_valid": ("d_known_contract_code_nominal_mapping_and_14d_proxy_pass"),
        "strategy_eligible": (
            "model_input_valid_and_decision_market_valid_and_planned_contract_valid"
        ),
        "future_execution_outcome": ("separate_post_decision_state_never_used_in_d_signal"),
        "cross_section_policy": "exclude_invalid_before_rank_demean_normalize",
        "stateful_invalid_policy": (
            "preserve_existing_position_without_state_advance_or_new_intent"
        ),
    }
    if any(validity.get(key) != value for key, value in expected_validity.items()):
        raise ValueError("context validity/state contract drift")
    if evaluation_exit != {
        "role": "evaluation_only_never_strategy_input",
        "horizon_common_decisions": 5,
        "mapping": "decision_i_to_decision_i_plus_5_on_exact_sealed_1269_calendar",
        "trailing_decisions_policy": "last_5_false_no_entry",
        "protected_timestamp_rule": "exit_and_accounting_timestamps_lt_2026_01_01",
        "final_expiration_date_used": False,
        "independent_of_strategy_validity_masks": True,
    }:
        raise ValueError("context evaluation-exit observability drift")
    volatility = market.get("volatility_ratio20", {})
    volume = market.get("volume_ratio20", {})
    if any(
        section.get("expected_distinct_buckets") != MAIN_SESSION_EXPECTED_BUCKETS
        or section.get("minimum_distinct_completed_buckets") != MAIN_SESSION_MINIMUM_BUCKETS
        for section in (volatility, volume)
    ):
        raise ValueError("context main-session coverage drift")
    completed_rule = "raw_end_at_lte_scheduled_close_lte_decision"
    if any(
        section.get("completed_bucket_rule") != completed_rule for section in (volatility, volume)
    ):
        raise ValueError("context raw-end availability rule drift")
    atr = market.get("atr20", {})
    momentum = market.get("momentum20", {})
    daily_volatility = market.get("daily_volatility20", {})
    range_position = market.get("range_position20", {})
    if (
        atr.get("source") != "causal_raw_10m_derived_forward_additive_daily_ohlc"
        or atr.get("true_range_formula")
        != "max(high_d-low_d,abs(high_d-close_d_minus_1),abs(low_d-close_d_minus_1))"
        or atr.get("window") != 20
        or atr.get("include_current_session") is not True
        or momentum.get("source") != "causal_raw_10m_derived_forward_additive_daily_close"
        or momentum.get("formula") != "log_close_d_minus_log_close_d_minus_20"
        or daily_volatility.get("source") != "causal_raw_10m_derived_forward_additive_daily_close"
        or daily_volatility.get("formula")
        != "population_std_of_20_one_session_log_returns_ending_d"
        or daily_volatility.get("ddof") != 0
        or daily_volatility.get("zero_policy") != "invalid"
        or range_position.get("source") != "causal_raw_10m_derived_forward_additive_daily_ohlc"
        or range_position.get("formula")
        != "(close_d-min_low_prior_20)/(max_high_prior_20-min_low_prior_20)"
        or range_position.get("lookback_sessions") != 20
        or range_position.get("current_session_in_range") is not False
        or range_position.get("clipping") != "none"
    ):
        raise ValueError("context daily market feature formula drift")
    key_rate = channels.get("key_rate_change_z", {})
    if (
        key_rate.get("observed_unique_finite_changes_2018_2025") != 41
        or key_rate.get("minimum_prior_observations_outcome_2021_2025")
        != "sleeping_missing_all_oos"
        or key_rate.get("adaptive_minimum_history") != "forbidden"
    ):
        raise ValueError("context key-rate sleeping audit drift")
    if (
        volatility.get("numerator")
        != "sqrt_sum_squared_log_close_to_previous_bar_close_within_current_session"
        or volatility.get("first_bar_cross_session_return") != "excluded"
        or volatility.get("denominator")
        != "arithmetic_mean_current_definition_rv_of_prior_20_factual_common_sessions"
        or volatility.get("epsilon") != "none"
        or volume.get("numerator")
        != "sum_nonnegative_volume_of_current_completed_main_session_buckets"
        or volume.get("denominator")
        != "arithmetic_mean_same_definition_volume_of_prior_20_factual_common_sessions"
    ):
        raise ValueError("context intraday ratio formula drift")
    if (
        nominal.get("minimum_calendar_days_after_decision") != 14
        or nominal.get("source") != "contract_code_plus_fixed_nominal_schedule_rule_known_at_d"
        or nominal.get("final_expiration_date_role") != "qa_only_never_decision"
        or nominal.get("unproved_mapping_policy") != "planned_contract_invalid_cash"
        or nominal.get("month_codes") != dict(FUTURES_MONTH_CODES)
        or nominal.get("asset_rules")
        != {
            "BR": "first_calendar_day_of_contract_month_conservative",
            "MIX": "third_thursday_of_contract_month",
            "RI": "third_thursday_of_contract_month",
            "SI": "third_thursday_of_contract_month",
        }
    ):
        raise ValueError("context nominal maturity derivation drift")
    if float(economics.get("initial_capital_rub", -1.0)) != INITIAL_CAPITAL_RUB:
        raise ValueError("context initial capital drift")
    if (
        economics.get("collateral_interest") != 0.0
        or economics.get("bankruptcy_or_negative_equity") != "no_go"
    ):
        raise ValueError("context economic fail-closed policy drift")
    if (
        economics.get("taxes") != "not_modeled"
        or economics.get("dividends") != "not_applicable_futures"
        or economics.get("broker_queue_exact_claim") is not False
        or economics.get("variation_margin_gap_policy")
        != "retain_all_factual_mark_gaps_no_synthetic_fill"
    ):
        raise ValueError("context economic reproducibility policy drift")
    spec_proxy = economics.get("point_value_fee_initial_margin_spec", {})
    if (
        spec_proxy.get("dataset_sha256") != SPEC_PROXY_DATASET_SHA256
        or spec_proxy.get("unknown_spec_policy") != "no_go_no_sizing_or_accounting_fallback"
    ):
        raise ValueError("context research spec proxy drift")
    required_dependencies = tuple(artifact.get("required_dependency_names", ()))
    if required_dependencies != REQUIRED_CONTEXT_DEPENDENCIES:
        raise ValueError("context required dependency bundle drift")
    if (
        artifact.get("schema") != CONTEXT_SOURCE_SCHEMA
        or artifact.get("context_completion_status")
        != "validity_aware_causal_raw_10m_context_proxy_calendar"
        or artifact.get("evaluator_admission_status") != "blocked_pending_schema_followup"
        or artifact.get("target_columns_forbidden") is not True
        or artifact.get("pnl_columns_forbidden") is not True
    ):
        raise ValueError("context artifact/admission contract drift")
    spec_proxy = economics["point_value_fee_initial_margin_spec"]
    pin_fields = {
        "v8_assembly_manifest": (
            dependencies["v8_assembly_manifest_path"],
            dependencies["v8_assembly_manifest_sha256"],
        ),
        "v8_assembly": (
            dependencies["v8_assembly_path"],
            dependencies["v8_assembly_sha256"],
        ),
        "base_predictions": (
            dependencies["base_predictions_path"],
            dependencies["base_predictions_sha256"],
        ),
        "checkpoint_identities": (
            dependencies["checkpoint_identities_path"],
            dependencies["checkpoint_identities_sha256"],
        ),
        "regime_enrichment_manifest": (
            dependencies["regime_enrichment_manifest_path"],
            dependencies["regime_enrichment_manifest_sha256"],
        ),
        "regime_enrichment": (
            dependencies["regime_enrichment_path"],
            dependencies["regime_enrichment_sha256"],
        ),
        "adjusted_daily_chain": (
            dependencies["adjusted_daily_chain_path"],
            dependencies["adjusted_daily_chain_sha256"],
        ),
        "active_contract_map": (
            dependencies["active_contract_map_path"],
            dependencies["active_contract_map_sha256"],
        ),
        "main_session_10m": (
            dependencies["main_session_10m_manifest_path"],
            dependencies["main_session_10m_manifest_sha256"],
        ),
        "cbr_manifest": (
            dependencies["cbr_manifest_path"],
            dependencies["cbr_manifest_sha256"],
        ),
        "cftc_manifest": (
            dependencies["cftc_manifest_path"],
            dependencies["cftc_manifest_sha256"],
        ),
        "carry_pit": (
            dependencies["v8_assembly_path"],
            dependencies["v8_assembly_sha256"],
        ),
        "cftc_pit": (
            dependencies["cftc_dataset_path"],
            dependencies["cftc_dataset_sha256"],
        ),
        "cbr_key_rate_pit": (
            dependencies["cbr_dataset_path"],
            dependencies["cbr_dataset_sha256"],
        ),
        "cbr_usdrub_pit": (
            dependencies["cbr_dataset_path"],
            dependencies["cbr_dataset_sha256"],
        ),
        "spec_proxy_dataset": (
            spec_proxy["dataset_path"],
            spec_proxy["dataset_sha256"],
        ),
        "spec_proxy_manifest": (
            spec_proxy["manifest_path"],
            spec_proxy["manifest_sha256"],
        ),
        "aggressive_implementation": (
            dependencies["aggressive_implementation_path"],
            dependencies["aggressive_implementation_sha256"],
        ),
    }
    normalized_pins: dict[str, tuple[str, str]] = {}
    for name, (relative_path, expected_sha) in pin_fields.items():
        expected = _require_sha256(expected_sha, f"{name} pinned SHA")
        source_path = _resolve_project_file(relative_path, f"{name} pinned path")
        if _sha256_file(source_path) != expected:
            raise ValueError(f"context pinned dependency byte drift: {name}")
        normalized_pins[name] = (str(relative_path).replace("\\", "/"), expected)
    return EvaluationContextProtocol(
        path=resolved,
        sha256=actual,
        protocol_name=_require_identifier(payload["protocol_name"], "protocol_name"),
        protocol_version=int(payload["protocol_version"]),
        base_protocol_sha256=_require_sha256(
            dependencies["base_protocol_sha256"], "base_protocol_sha256"
        ),
        minimum_prior_observations=int(standardization["minimum_prior_observations"]),
        clip_minimum=float(standardization["clip_minimum"]),
        clip_maximum=float(standardization["clip_maximum"]),
        nominal_span_rule=str(nominal["rule"]),
        minimum_calendar_days=int(nominal["minimum_calendar_days_after_decision"]),
        initial_capital_rub=float(economics["initial_capital_rub"]),
        required_dependency_names=required_dependencies,
        dependency_pins=normalized_pins,
        raw=payload,
    )


@dataclass(frozen=True, slots=True)
class AdjustedDailyObservation:
    """Ex-post QA panel row; ne yavlyaetsya PIT source ili decision input."""

    decision_at: datetime
    asset_id: str
    active_chain_id: str
    active_contract_id: str
    open: float
    high: float
    low: float
    close: float
    source_id: str
    observation_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        """Proveriaet tol'ko trade-date key/OHLC; availability claim zapreshchen."""
        decision = _require_aware(self.decision_at, "QA trade-date decision_at")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("market asset vne sealed universe")
        _require_identifier(self.active_chain_id, "active_chain_id")
        _require_identifier(self.active_contract_id, "active_contract_id")
        values = {
            name: _finite(getattr(self, name), name) for name in ("open", "high", "low", "close")
        }
        if min(values.values()) <= 0.0:
            raise ValueError("adjusted daily OHLC dolzhny byt' >0")
        if values["high"] < max(values["open"], values["low"], values["close"]):
            raise ValueError("market high narushaet OHLC")
        if values["low"] > min(values["open"], values["high"], values["close"]):
            raise ValueError("market low narushaet OHLC")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "source_id", _require_identifier(self.source_id, "source_id"))
        object.__setattr__(
            self, "observation_id", _require_identifier(self.observation_id, "observation_id")
        )
        object.__setattr__(
            self, "source_sha256", _require_sha256(self.source_sha256, "source_sha256")
        )


@dataclass(frozen=True, slots=True)
class MainSessionBarObservation:
    """Raw active-contract 10m bar s scheduled granitsami i raw end."""

    decision_at: datetime
    asset_id: str
    contract_id: str
    bar_open_at: datetime
    bar_close_at: datetime
    raw_end_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_id: str
    observation_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        """Trebuet completed 10m main-session bucket, dostupnyi ne pozhe D."""
        decision = _require_aware(self.decision_at, "bar decision_at")
        opened = _require_aware(self.bar_open_at, "bar_open_at")
        closed = _require_aware(self.bar_close_at, "bar_close_at")
        raw_end = _require_aware(self.raw_end_at, "raw_end_at")
        if closed - opened != timedelta(minutes=10) or closed > decision:
            raise ValueError("main-session bar dolzhen byt' exact completed 10m bucket")
        if not opened < raw_end <= closed:
            raise ValueError("raw end dolzhen byt' posle open i ne pozhe scheduled close")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("main-session asset vne sealed universe")
        local_open = opened.astimezone(ZoneInfo("Europe/Moscow"))
        minute = local_open.hour * 60 + local_open.minute
        if local_open.second != 0 or local_open.microsecond != 0 or minute % 10 != 0:
            raise ValueError("bar ne prinadlezhit scheduled 10m grid")
        values = {
            name: _finite(getattr(self, name), name) for name in ("open", "high", "low", "close")
        }
        volume = _finite(self.volume, "volume")
        if min(values.values()) <= 0.0 or volume < 0.0:
            raise ValueError("raw OHLC dolzhny byt' >0, volume >=0")
        if values["high"] < max(values["open"], values["low"], values["close"]):
            raise ValueError("raw high narushaet OHLC")
        if values["low"] > min(values["open"], values["high"], values["close"]):
            raise ValueError("raw low narushaet OHLC")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "bar_open_at", opened)
        object.__setattr__(self, "bar_close_at", closed)
        object.__setattr__(self, "raw_end_at", raw_end)
        for name in ("contract_id", "source_id", "observation_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        object.__setattr__(
            self, "source_sha256", _require_sha256(self.source_sha256, "source_sha256")
        )


@dataclass(frozen=True, slots=True)
class CausalSessionContractObservation:
    """Active contract i forward adjustment, izvestnye do nachala D intervala."""

    decision_at: datetime
    previous_decision_at: datetime
    asset_id: str
    contract_id: str
    forward_additive_adjustment: float
    known_at: datetime
    source_id: str
    observation_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        """Trebuet contract/offset known ne pozhe previous D18:50."""
        decision = _require_aware(self.decision_at, "session contract decision_at")
        previous = _require_aware(
            self.previous_decision_at,
            "session contract previous_decision_at",
        )
        known = _require_aware(self.known_at, "session contract known_at")
        if not known <= previous < decision:
            raise ValueError("session contract/adjustment dolzhen byt' known do intervala")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("session contract asset vne sealed universe")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "previous_decision_at", previous)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(
            self,
            "forward_additive_adjustment",
            _finite(self.forward_additive_adjustment, "forward_additive_adjustment"),
        )
        for name in ("contract_id", "source_id", "observation_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_sha256",
            _require_sha256(self.source_sha256, "session contract source_sha256"),
        )


@dataclass(frozen=True, slots=True)
class MarketFeatureSnapshot:
    """Optional market features i explicit D-validity bez imputation."""

    decision_at: datetime
    asset_id: str
    known_at: datetime | None
    close: float | None
    adjusted_signal_open: float | None
    adjusted_signal_high: float | None
    adjusted_signal_low: float | None
    adjusted_signal_close: float | None
    atr_20: float | None
    daily_volatility_20: float | None
    momentum_20: float | None
    range_position_20: float | None
    volatility_ratio_20: float | None
    volume_ratio_20: float | None
    decision_market_valid: bool
    reason_codes: tuple[str, ...]
    market_data_sha256: str | None
    main_session_bucket_count: int
    close_bar_open_at: datetime | None = None
    close_bar_scheduled_close_at: datetime | None = None
    close_bar_raw_end_at: datetime | None = None
    main_session_source_sha256s: tuple[str, ...] = ()
    main_session_expected_bucket_count: int = MAIN_SESSION_EXPECTED_BUCKETS


@dataclass(frozen=True, slots=True)
class _MainSessionMetrics:
    """Vnutrennii raw close/RV/volume rezultat odnogo D-contract session."""

    known_at: datetime | None
    raw_close: float | None
    realized_volatility: float | None
    completed_volume: float | None
    bucket_count: int
    valid: bool
    ratio_comparable: bool
    reason_codes: tuple[str, ...]
    observation_ids: tuple[str, ...]
    source_sha256s: tuple[str, ...]
    close_bar_open_at: datetime | None
    close_bar_scheduled_close_at: datetime | None
    close_bar_raw_end_at: datetime | None


@dataclass(frozen=True, slots=True)
class _CausalDailyMetrics:
    """Raw-10m D interval, predeclared additive adjustment i derived daily OHLC."""

    known_at: datetime | None
    adjusted_open: float | None
    adjusted_high: float | None
    adjusted_low: float | None
    adjusted_close: float | None
    session: _MainSessionMetrics
    valid: bool
    reason_codes: tuple[str, ...]
    observation_ids: tuple[str, ...]
    source_sha256s: tuple[str, ...]


def _population_std(values: Sequence[float]) -> float:
    """Schitaet population std bez epsilon i skrytoi fallback scale."""
    center = fmean(values)
    return sqrt(fmean((value - center) ** 2 for value in values))


def _main_session_metrics(
    bars: Sequence[MainSessionBarObservation],
) -> _MainSessionMetrics:
    """Schitaet RV bez overnight return i raw close tol'ko exact 18:40 bucket."""
    reasons: list[str] = []
    ordered = tuple(sorted(bars, key=lambda item: item.bar_open_at))
    opens = tuple(item.bar_open_at for item in ordered)
    if len(set(opens)) != len(opens):
        reasons.append("main_session_duplicate_bucket")
    distinct = tuple({item.bar_open_at: item for item in ordered}.values())
    bucket_count = len(distinct)
    if bucket_count < MAIN_SESSION_MINIMUM_BUCKETS:
        reasons.append("main_session_below_48_of_53_buckets")
    exact_close = tuple(
        item
        for item in distinct
        if item.bar_open_at.astimezone(ZoneInfo("Europe/Moscow")).time()
        == MAIN_SESSION_CLOSE_BAR_OPEN
        and item.bar_close_at.astimezone(ZoneInfo("Europe/Moscow")).time()
        == MAIN_SESSION_CLOSE_BAR_CLOSE
    )
    raw_close = exact_close[0].close if len(exact_close) == 1 else None
    if raw_close is None:
        reasons.append("missing_exact_18_40_to_18_50_close_bar")
    realized = None
    if len(distinct) >= 2:
        realized = sqrt(
            sum(
                (log(current.close) - log(previous.close)) ** 2
                for previous, current in zip(distinct, distinct[1:], strict=False)
            )
        )
    else:
        reasons.append("main_session_rv_requires_two_bars")
    volume = sum(item.volume for item in distinct) if distinct else None
    ratio_blockers = {
        "main_session_duplicate_bucket",
        "main_session_below_48_of_53_buckets",
        "main_session_rv_requires_two_bars",
    }
    ratio_comparable = (
        realized is not None and volume is not None and not ratio_blockers.intersection(reasons)
    )
    valid = ratio_comparable and raw_close is not None
    close_bar = exact_close[0] if len(exact_close) == 1 else None
    return _MainSessionMetrics(
        known_at=None if not distinct else max(item.bar_close_at for item in distinct),
        raw_close=raw_close,
        realized_volatility=realized,
        completed_volume=volume,
        bucket_count=bucket_count,
        valid=valid,
        ratio_comparable=ratio_comparable,
        reason_codes=tuple(sorted(set(reasons))),
        observation_ids=tuple(item.observation_id for item in distinct),
        source_sha256s=tuple(sorted({item.source_sha256 for item in distinct})),
        close_bar_open_at=None if close_bar is None else close_bar.bar_open_at,
        close_bar_scheduled_close_at=(None if close_bar is None else close_bar.bar_close_at),
        close_bar_raw_end_at=None if close_bar is None else close_bar.raw_end_at,
    )


def _is_current_main_session_bar(
    bar: MainSessionBarObservation,
    decision_at: datetime,
) -> bool:
    """Otbirayet scheduled 10:00..18:40 starts tekushchego Moscow D."""
    opened = bar.bar_open_at.astimezone(ZoneInfo("Europe/Moscow"))
    local_decision = decision_at.astimezone(ZoneInfo("Europe/Moscow"))
    minute = opened.hour * 60 + opened.minute
    return (
        opened.date() == local_decision.date()
        and 10 * 60 <= minute <= 18 * 60 + 40
        and minute % 10 == 0
    )


def _causal_daily_metrics(
    contract: CausalSessionContractObservation,
    bars: Sequence[MainSessionBarObservation],
) -> _CausalDailyMetrics:
    """Agregiruet raw interval (prev D, D] i ne chitaet final daily panel."""
    reasons: list[str] = []
    ordered = tuple(sorted(bars, key=lambda item: item.bar_open_at))
    for bar in ordered:
        if (
            bar.decision_at != contract.decision_at
            or bar.asset_id != contract.asset_id
            or bar.contract_id != contract.contract_id
        ):
            reasons.append("raw_10m_contract_or_decision_mismatch")
        if not contract.previous_decision_at < bar.bar_close_at <= contract.decision_at:
            reasons.append("raw_10m_outside_causal_daily_interval")
    distinct_by_open: dict[datetime, MainSessionBarObservation] = {}
    for bar in ordered:
        if bar.bar_open_at in distinct_by_open:
            reasons.append("daily_interval_duplicate_bucket")
        else:
            distinct_by_open[bar.bar_open_at] = bar
    distinct = tuple(distinct_by_open.values())
    if not distinct:
        reasons.append("daily_interval_empty")
    main_bars = tuple(
        item for item in distinct if _is_current_main_session_bar(item, contract.decision_at)
    )
    session = _main_session_metrics(main_bars)
    reasons.extend(session.reason_codes)
    adjusted_open = adjusted_high = adjusted_low = adjusted_close = None
    if distinct and session.raw_close is not None:
        adjustment = contract.forward_additive_adjustment
        adjusted_open = distinct[0].open + adjustment
        adjusted_high = max(item.high for item in distinct) + adjustment
        adjusted_low = min(item.low for item in distinct) + adjustment
        adjusted_close = session.raw_close + adjustment
        if min(adjusted_open, adjusted_high, adjusted_low, adjusted_close) <= 0.0:
            reasons.append("adjusted_daily_ohlc_nonpositive")
            adjusted_open = adjusted_high = adjusted_low = adjusted_close = None
    daily_blockers = {
        "daily_interval_duplicate_bucket",
        "daily_interval_empty",
        "raw_10m_contract_or_decision_mismatch",
        "raw_10m_outside_causal_daily_interval",
        "missing_exact_18_40_to_18_50_close_bar",
        "adjusted_daily_ohlc_nonpositive",
    }
    return _CausalDailyMetrics(
        known_at=None if not distinct else max(item.bar_close_at for item in distinct),
        adjusted_open=adjusted_open,
        adjusted_high=adjusted_high,
        adjusted_low=adjusted_low,
        adjusted_close=adjusted_close,
        session=session,
        valid=not daily_blockers.intersection(reasons),
        reason_codes=tuple(sorted(set(reasons))),
        observation_ids=tuple(item.observation_id for item in distinct),
        source_sha256s=tuple(sorted({item.source_sha256 for item in distinct})),
    )


def build_market_feature_snapshots(
    decisions: Sequence[datetime],
    session_contracts: Sequence[CausalSessionContractObservation],
    raw_10m_bars: Sequence[MainSessionBarObservation],
    *,
    raw_10m_source_sha256: str,
) -> dict[tuple[datetime, str], MarketFeatureSnapshot]:
    """Stroit vse price features iz raw 10m, active contract i D-known offset."""
    raw_source_sha = _require_sha256(raw_10m_source_sha256, "raw_10m_source_sha256")
    normalized_decisions = tuple(_require_aware(value, "decision") for value in decisions)
    if (
        len(set(normalized_decisions)) != len(normalized_decisions)
        or tuple(sorted(normalized_decisions)) != normalized_decisions
    ):
        raise ValueError("decisions dolzhny byt' unique i strogo vozrastayushchie")
    observation_by_key: dict[tuple[datetime, str], CausalSessionContractObservation] = {}
    for observation in session_contracts:
        key = (observation.decision_at, observation.asset_id)
        if key in observation_by_key:
            raise ValueError("session contracts soderzhat duplicate decision/asset")
        observation_by_key[key] = observation
    bars_by_key: dict[tuple[datetime, str, str], list[MainSessionBarObservation]] = defaultdict(
        list
    )
    for bar in raw_10m_bars:
        bars_by_key[(bar.decision_at, bar.asset_id, bar.contract_id)].append(bar)
    output: dict[tuple[datetime, str], MarketFeatureSnapshot] = {}
    for asset_id in V8_ASSET_IDS:
        daily_history: list[_CausalDailyMetrics | None] = []
        intraday_history: list[_MainSessionMetrics] = []
        for decision_index, decision_at in enumerate(normalized_decisions):
            key = (decision_at, asset_id)
            current = observation_by_key.get(key)
            if current is None:
                empty_session = _main_session_metrics(())
                output[key] = MarketFeatureSnapshot(
                    decision_at=decision_at,
                    asset_id=asset_id,
                    known_at=None,
                    close=None,
                    adjusted_signal_open=None,
                    adjusted_signal_high=None,
                    adjusted_signal_low=None,
                    adjusted_signal_close=None,
                    atr_20=None,
                    daily_volatility_20=None,
                    momentum_20=None,
                    range_position_20=None,
                    volatility_ratio_20=None,
                    volume_ratio_20=None,
                    decision_market_valid=False,
                    reason_codes=("missing_current_session_contract",),
                    market_data_sha256=None,
                    main_session_bucket_count=0,
                )
                daily_history.append(None)
                intraday_history.append(empty_session)
                continue
            reasons: list[str] = []
            if (
                decision_index
                and current.previous_decision_at != normalized_decisions[decision_index - 1]
            ):
                reasons.append("session_contract_previous_decision_mismatch")
            daily = _causal_daily_metrics(
                current,
                bars_by_key.get((decision_at, asset_id, current.contract_id), ()),
            )
            session = daily.session
            reasons.extend(session.reason_codes)
            reasons.extend(daily.reason_codes)
            history_with_current = [*daily_history, daily]
            atr = None
            momentum_value = None
            daily_volatility_value = None
            last_21 = history_with_current[-21:]
            if len(last_21) == 21 and all(item is not None and item.valid for item in last_21):
                complete_daily = tuple(item for item in last_21 if item is not None)
                true_ranges = tuple(
                    max(
                        float(item.adjusted_high) - float(item.adjusted_low),
                        abs(float(item.adjusted_high) - float(previous.adjusted_close)),
                        abs(float(item.adjusted_low) - float(previous.adjusted_close)),
                    )
                    for previous, item in zip(complete_daily, complete_daily[1:], strict=False)
                )
                atr = fmean(true_ranges)
                closes = tuple(float(item.adjusted_close) for item in complete_daily)
                momentum_value = log(closes[-1]) - log(closes[0])
                one_session_returns = tuple(
                    log(current_close) - log(previous_close)
                    for previous_close, current_close in zip(closes, closes[1:], strict=False)
                )
                daily_volatility_value = _population_std(one_session_returns)
                if daily_volatility_value <= 0.0:
                    daily_volatility_value = None
                    reasons.append("daily_volatility20_zero")
            else:
                reasons.append("atr20_insufficient_consecutive_history")
                reasons.append("momentum20_insufficient_consecutive_history")
                reasons.append("daily_volatility20_insufficient_consecutive_history")
            range_position = None
            prior_daily = daily_history[-20:]
            if (
                daily.valid
                and len(prior_daily) == 20
                and all(item is not None and item.valid for item in prior_daily)
            ):
                prior = tuple(item for item in prior_daily if item is not None)
                lower = min(float(item.adjusted_low) for item in prior)
                upper = max(float(item.adjusted_high) for item in prior)
                if upper > lower:
                    range_position = (float(daily.adjusted_close) - lower) / (upper - lower)
                else:
                    reasons.append("range20_zero_prior_range")
            else:
                reasons.append("range20_insufficient_consecutive_history")
            volatility_ratio = None
            volume_ratio = None
            prior_intraday = intraday_history[-20:]
            if len(prior_intraday) == 20 and all(item.ratio_comparable for item in prior_intraday):
                baseline_rv = fmean(
                    item.realized_volatility
                    for item in prior_intraday
                    if item.realized_volatility is not None
                )
                baseline_volume = fmean(
                    item.completed_volume
                    for item in prior_intraday
                    if item.completed_volume is not None
                )
                if baseline_rv > 0.0 and session.realized_volatility is not None:
                    volatility_ratio = session.realized_volatility / baseline_rv
                else:
                    reasons.append("volatility_ratio_zero_prior20_mean_rv")
                if baseline_volume > 0.0 and session.completed_volume is not None:
                    volume_ratio = session.completed_volume / baseline_volume
                else:
                    reasons.append("volume_ratio_zero_prior20_mean")
            else:
                reasons.append("intraday_ratio_prior20_sessions_not_comparable")
            feature_values = (
                atr,
                daily_volatility_value,
                momentum_value,
                range_position,
                volatility_ratio,
                volume_ratio,
            )
            valid = (
                not reasons
                and daily.valid
                and session.valid
                and session.raw_close is not None
                and all(value is not None and isfinite(value) for value in feature_values)
            )
            source_payload = {
                "protocol_sha256": DEFAULT_CONTEXT_PROTOCOL_SHA256,
                "raw_10m_top_manifest_sha256": raw_source_sha,
                "session_contract": {
                    "source_id": current.source_id,
                    "observation_id": current.observation_id,
                    "source_sha256": current.source_sha256,
                    "contract_id": current.contract_id,
                    "forward_additive_adjustment": current.forward_additive_adjustment,
                    "known_at": current.known_at,
                },
                "raw_10m_derived_daily_rolling_observation_ids": [
                    None if item is None else item.observation_ids for item in daily_history[-20:]
                ],
                "raw_main_session": {
                    "active_contract_id": current.contract_id,
                    "bucket_count": session.bucket_count,
                    "bars": [
                        {
                            "bar_open_at": item.bar_open_at,
                            "bar_close_at": item.bar_close_at,
                            "raw_end_at": item.raw_end_at,
                            "open": item.open,
                            "high": item.high,
                            "low": item.low,
                            "close": item.close,
                            "volume": item.volume,
                            "source_id": item.source_id,
                            "observation_id": item.observation_id,
                            "source_sha256": item.source_sha256,
                        }
                        for item in sorted(
                            bars_by_key.get((decision_at, asset_id, current.contract_id), ()),
                            key=lambda value: value.bar_open_at,
                        )
                    ],
                    "source_sha256s": session.source_sha256s,
                },
                "prior20_main_session_observation_ids": [
                    item.observation_ids for item in prior_intraday
                ],
            }
            market_sha = _canonical_sha256(source_payload)
            output[key] = MarketFeatureSnapshot(
                decision_at=decision_at,
                asset_id=asset_id,
                known_at=(
                    current.known_at
                    if daily.known_at is None
                    else max(current.known_at, daily.known_at)
                ),
                close=session.raw_close,
                adjusted_signal_open=daily.adjusted_open,
                adjusted_signal_high=daily.adjusted_high,
                adjusted_signal_low=daily.adjusted_low,
                adjusted_signal_close=daily.adjusted_close,
                atr_20=atr,
                daily_volatility_20=daily_volatility_value,
                momentum_20=momentum_value,
                range_position_20=range_position,
                volatility_ratio_20=volatility_ratio,
                volume_ratio_20=volume_ratio,
                decision_market_valid=valid,
                reason_codes=tuple(sorted(set(reasons))),
                market_data_sha256=market_sha,
                main_session_bucket_count=session.bucket_count,
                close_bar_open_at=session.close_bar_open_at,
                close_bar_scheduled_close_at=session.close_bar_scheduled_close_at,
                close_bar_raw_end_at=session.close_bar_raw_end_at,
                main_session_source_sha256s=session.source_sha256s,
            )
            daily_history.append(daily)
            intraday_history.append(session)
    return output


@dataclass(frozen=True, slots=True)
class FinalDailyPanelQaAudit:
    """QA-only reconciliation counters bez prava podmenyat' raw-10m features."""

    compared_rows: int
    missing_rows: int
    open_mismatch_rows: int
    high_mismatch_rows: int
    low_mismatch_rows: int
    close_mismatch_rows: int
    invalidated_rows: int
    qa_bundle_sha256: str


def reconcile_final_daily_panel_qa(
    snapshots: Mapping[tuple[datetime, str], MarketFeatureSnapshot],
    qa_observations: Sequence[AdjustedDailyObservation],
    *,
    relative_tolerance: float = 1e-12,
    absolute_tolerance: float = 1e-12,
) -> tuple[dict[tuple[datetime, str], MarketFeatureSnapshot], FinalDailyPanelQaAudit]:
    """Audit-only sverka; unexplained close mismatch blokiruet ves' artifact."""
    if relative_tolerance < 0.0 or absolute_tolerance < 0.0:
        raise ValueError("QA tolerances ne mogut byt' otricatel'nymi")
    qa_by_key: dict[tuple[datetime, str], AdjustedDailyObservation] = {}
    for item in qa_observations:
        key = (item.decision_at, item.asset_id)
        if key in qa_by_key:
            raise ValueError("final daily QA soderzhit duplicate decision/asset")
        qa_by_key[key] = item
    output = dict(snapshots)
    compared = missing = open_mismatch = high_mismatch = low_mismatch = 0
    close_mismatch = invalidated = 0
    fatal_keys: list[tuple[datetime, str]] = []
    evidence: list[dict[str, object]] = []
    for key in sorted(snapshots, key=lambda item: (item[0], item[1])):
        snapshot = snapshots[key]
        qa = qa_by_key.get(key)
        if qa is None:
            missing += 1
            evidence.append({"decision_at": key[0], "asset": key[1], "qa": None})
            if snapshot.adjusted_signal_close is not None:
                fatal_keys.append(key)
            continue
        compared += 1
        pairs = {
            "open": (snapshot.adjusted_signal_open, qa.open),
            "high": (snapshot.adjusted_signal_high, qa.high),
            "low": (snapshot.adjusted_signal_low, qa.low),
            "close": (snapshot.adjusted_signal_close, qa.close),
        }
        mismatches: dict[str, bool] = {}
        for name, (derived, expected) in pairs.items():
            mismatches[name] = derived is not None and not isclose(
                float(derived),
                float(expected),
                rel_tol=relative_tolerance,
                abs_tol=absolute_tolerance,
            )
        open_mismatch += int(mismatches["open"])
        high_mismatch += int(mismatches["high"])
        low_mismatch += int(mismatches["low"])
        close_mismatch += int(mismatches["close"])
        if mismatches["close"]:
            fatal_keys.append(key)
        qa_payload = {
            "source_id": qa.source_id,
            "observation_id": qa.observation_id,
            "source_sha256": qa.source_sha256,
            "mismatches": mismatches,
        }
        evidence.append({"decision_at": key[0], "asset": key[1], **qa_payload})
    audit = FinalDailyPanelQaAudit(
        compared_rows=compared,
        missing_rows=missing,
        open_mismatch_rows=open_mismatch,
        high_mismatch_rows=high_mismatch,
        low_mismatch_rows=low_mismatch,
        close_mismatch_rows=close_mismatch,
        invalidated_rows=invalidated,
        qa_bundle_sha256=_canonical_sha256(evidence),
    )
    if fatal_keys:
        raise ValueError(
            "final daily panel exact-close reconciliation global NO_GO; "
            f"unreconciled_rows={len(fatal_keys)}"
        )
    return output, audit


@dataclass(frozen=True, slots=True)
class RawPitObservation:
    """Latest PIT raw value na odin decision/asset ili global channel."""

    decision_at: datetime
    asset_id: str | None
    channel: str
    raw_value: float
    published_at: datetime
    available_at: datetime
    source_id: str
    observation_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        """Zapreshchaet future release/availability i pustuyu provenance."""
        decision = _require_aware(self.decision_at, "PIT decision_at")
        published = _require_aware(self.published_at, "PIT published_at")
        available = _require_aware(self.available_at, "PIT available_at")
        if published > available or available > decision:
            raise ValueError("PIT published/available timestamps dolzhny byt' <= decision")
        if self.asset_id is not None and self.asset_id not in V8_ASSET_IDS:
            raise ValueError("PIT asset vne sealed universe")
        if self.channel not in {
            "carry_z",
            "cftc_crowd_z",
            "key_rate_change_z",
            "usd_rub_return_z",
        }:
            raise ValueError("neizvestnyi PIT channel")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "published_at", published)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "raw_value", _finite(self.raw_value, "PIT raw_value"))
        object.__setattr__(self, "source_id", _require_identifier(self.source_id, "source_id"))
        object.__setattr__(
            self, "observation_id", _require_identifier(self.observation_id, "observation_id")
        )
        object.__setattr__(
            self, "source_sha256", _require_sha256(self.source_sha256, "source_sha256")
        )


@dataclass(frozen=True, slots=True)
class StandardizedPitObservation:
    """Expanding-z rezultat s raw value, freshness i polnoi provenance."""

    raw: RawPitObservation
    standardized: PointInTimeObservation | None
    unclipped_z: float | None
    history_count: int
    freshness_seconds: float
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class PitStandardizationAudit:
    """Deterministic coverage odnogo PIT channel na ukazannom decision kalendare."""

    channel: str
    snapshot_rows: int
    unique_observation_ids: int
    standardized_rows: int
    sleeping_rows: int
    minimum_history_count: int
    maximum_history_count: int


def audit_pit_standardization(
    standardized: Mapping[tuple[datetime, str | None, str], StandardizedPitObservation],
    *,
    channel: str,
    decisions: Sequence[datetime],
) -> PitStandardizationAudit:
    """Schitaet sleeping/ready bez adaptivnogo snizheniya minimum history."""
    normalized = {_require_aware(item, "PIT audit decision") for item in decisions}
    rows = [
        item
        for (decision_at, _asset, item_channel), item in standardized.items()
        if item_channel == channel and decision_at in normalized
    ]
    counts = [item.history_count for item in rows]
    ready = sum(item.standardized is not None for item in rows)
    return PitStandardizationAudit(
        channel=channel,
        snapshot_rows=len(rows),
        unique_observation_ids=len({item.raw.observation_id for item in rows}),
        standardized_rows=ready,
        sleeping_rows=len(rows) - ready,
        minimum_history_count=min(counts, default=0),
        maximum_history_count=max(counts, default=0),
    )


def _z_from_history(
    current: float,
    history: Sequence[float],
) -> tuple[float | None, float | None, str | None]:
    """Schitaet strict-past population z bez epsilon i clipping fallback."""
    if len(history) < EXPANDING_Z_MINIMUM_HISTORY:
        return None, None, "expanding_z_insufficient_prior_history"
    scale = _population_std(history)
    if scale <= 0.0:
        return None, None, "expanding_z_zero_prior_std"
    raw_z = (current - fmean(history)) / scale
    clipped = max(-EXPANDING_Z_CLIP, min(EXPANDING_Z_CLIP, raw_z))
    return clipped, raw_z, None


def _standardized_record(
    raw: RawPitObservation,
    history: Sequence[float],
) -> StandardizedPitObservation:
    """Upakovyvaet expanding z i nasleduet identity tekushchego raw release."""
    clipped, raw_z, reason = _z_from_history(raw.raw_value, history)
    point = (
        None
        if clipped is None
        else PointInTimeObservation(
            value=clipped,
            published_at=raw.available_at,
            source_id=raw.source_id,
            observation_id=raw.observation_id,
            source_sha256=raw.source_sha256,
        )
    )
    return StandardizedPitObservation(
        raw=raw,
        standardized=point,
        unclipped_z=raw_z,
        history_count=len(history),
        freshness_seconds=(raw.decision_at - raw.available_at).total_seconds(),
        reason_code=reason,
    )


def build_expanding_pit_standardization(
    observations: Sequence[RawPitObservation],
) -> dict[tuple[datetime, str | None, str], StandardizedPitObservation]:
    """Stroit per-asset snapshots i global unique-release CBR z bez future weighting."""
    output: dict[tuple[datetime, str | None, str], StandardizedPitObservation] = {}
    per_asset_channels = {"carry_z", "cftc_crowd_z"}
    decision_snapshot_channels = {"carry_z"}
    unique_release_channels = {"cftc_crowd_z", "key_rate_change_z", "usd_rub_return_z"}
    global_channels = {"key_rate_change_z", "usd_rub_return_z"}
    grouped: dict[tuple[str, str | None], list[RawPitObservation]] = defaultdict(list)
    for item in observations:
        if item.channel in per_asset_channels and item.asset_id is None:
            raise ValueError("carry/CFTC z trebuet per-asset observation")
        if item.channel in global_channels and item.asset_id is not None:
            raise ValueError("CBR z trebuet global observation bez asset duplication")
        grouped[(item.channel, item.asset_id)].append(item)
    for (channel, asset_id), rows in grouped.items():
        ordered = sorted(rows, key=lambda item: (item.decision_at, item.observation_id))
        if len({item.decision_at for item in ordered}) != len(ordered):
            raise ValueError("PIT group soderzhit duplicate decision")
        if channel in decision_snapshot_channels:
            history: list[float] = []
            for item in ordered:
                key = (item.decision_at, asset_id, channel)
                output[key] = _standardized_record(item, history)
                history.append(item.raw_value)
            continue
        if channel not in unique_release_channels:
            raise RuntimeError("PIT channel ne popal v sealed history semantics")
        release_values: dict[tuple[str, str, str, datetime], float] = {}
        release_rows: dict[tuple[str, str, str, datetime], RawPitObservation] = {}
        for item in ordered:
            identity = (
                item.source_id,
                item.observation_id,
                item.source_sha256,
                item.available_at,
            )
            previous = release_values.setdefault(identity, item.raw_value)
            if previous != item.raw_value:
                raise ValueError("odin global PIT release imeet raznye raw values")
            release_rows.setdefault(identity, item)
        release_order = sorted(
            release_rows,
            key=lambda identity: (identity[3], identity[1], identity[0], identity[2]),
        )
        history: list[float] = []
        by_release: dict[tuple[str, str, str, datetime], StandardizedPitObservation] = {}
        release_groups: dict[datetime, list[tuple[str, str, str, datetime]]] = defaultdict(list)
        for identity in release_order:
            release_groups[identity[3]].append(identity)
        for available_at in sorted(release_groups):
            identities = release_groups[available_at]
            for identity in identities:
                item = release_rows[identity]
                by_release[identity] = _standardized_record(item, history)
            history.extend(release_rows[identity].raw_value for identity in identities)
        for item in ordered:
            identity = (
                item.source_id,
                item.observation_id,
                item.source_sha256,
                item.available_at,
            )
            template = by_release[identity]
            output[(item.decision_at, asset_id, channel)] = StandardizedPitObservation(
                raw=item,
                standardized=(
                    None
                    if template.standardized is None
                    else PointInTimeObservation(
                        value=template.standardized.value,
                        published_at=item.available_at,
                        source_id=item.source_id,
                        observation_id=item.observation_id,
                        source_sha256=item.source_sha256,
                    )
                ),
                unclipped_z=template.unclipped_z,
                history_count=template.history_count,
                freshness_seconds=(item.decision_at - item.available_at).total_seconds(),
                reason_code=template.reason_code,
            )
    return output


@dataclass(frozen=True, slots=True)
class PlannedContractObservation:
    """Tol'ko izvestnyi na D planned contract code; final expiry ne decision input."""

    decision_at: datetime
    asset_id: str
    contract_id: str
    contract_code: str
    known_at: datetime
    source_id: str
    observation_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        """Trebuet D-known plan i ne validiruet ego cherez future fill outcome."""
        decision = _require_aware(self.decision_at, "contract decision_at")
        known = _require_aware(self.known_at, "contract known_at")
        if known > decision:
            raise ValueError("planned contract ne byl izvesten na D")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("planned contract asset vne sealed universe")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "known_at", known)
        for name in ("contract_id", "contract_code", "source_id", "observation_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        object.__setattr__(
            self, "source_sha256", _require_sha256(self.source_sha256, "source_sha256")
        )


@dataclass(frozen=True, slots=True)
class NominalContractAssessment:
    """D-known 14d proxy result s explicit non-claim exact session span."""

    observation: PlannedContractObservation | None
    nominal_maturity_date: date | None
    planned_contract_valid: bool
    reason_codes: tuple[str, ...]
    nominal_span_rule: str
    provenance_sha256: str


@dataclass(frozen=True, slots=True)
class NominalExpirationQa:
    """Otdel'nyi ex-post QA, kotoryi ne vhodit v decision context ili ego hash."""

    asset_id: str
    contract_id: str
    nominal_maturity_date: date
    final_expiration_date: date
    differs: bool


def _resolve_contract_year(year_token: str, month: int, decision_date: date) -> int | None:
    """Razreshaet one/two-digit year tol'ko otnositel'no D-known current contract."""
    suffix = int(year_token)
    if len(year_token) == 2:
        year = 2000 + suffix
        return year if decision_date.year - 1 <= year <= decision_date.year + 8 else None
    candidates = [
        year
        for year in range(decision_date.year - 1, decision_date.year + 9)
        if year % 10 == suffix
    ]
    viable = [
        year for year in candidates if date(year, month, 1) >= decision_date - timedelta(days=45)
    ]
    return min(viable) if viable else None


def derive_nominal_maturity_date(
    asset_id: str,
    contract_code: str,
    decision_date: date,
) -> date | None:
    """Vyvodit conservative nominal maturity iz code, ne iz final expiration."""
    if asset_id not in V8_ASSET_IDS or isinstance(decision_date, datetime):
        return None
    matches = list(_CONTRACT_SUFFIX_PATTERN.finditer(f" {contract_code}"))
    if not matches:
        return None
    match = matches[-1]
    month = FUTURES_MONTH_CODES[match.group(2).upper()]
    year = _resolve_contract_year(match.group(3), month, decision_date)
    if year is None:
        return None
    if asset_id == "BR":
        return date(year, month, 1)
    first = date(year, month, 1)
    days_to_thursday = (3 - first.weekday()) % 7
    return first + timedelta(days=days_to_thursday + 14)


def assess_planned_contract(
    observation: PlannedContractObservation | None,
    *,
    decision_at: datetime,
    asset_id: str,
) -> NominalContractAssessment:
    """Primenyayet D+14 proxy; final expiration smotrit tol'ko kak QA anomaly."""
    decision = _require_aware(decision_at, "assessment decision_at")
    reasons: list[str] = []
    maturity = None
    if observation is None:
        reasons.append("planned_contract_observation_missing")
    elif observation.decision_at != decision or observation.asset_id != asset_id:
        reasons.append("planned_contract_key_mismatch")
    else:
        maturity = derive_nominal_maturity_date(
            asset_id, observation.contract_code, decision.date()
        )
        if maturity is None:
            reasons.append("nominal_maturity_mapping_unproved")
        elif maturity < decision.date() + timedelta(days=14):
            reasons.append("nominal_maturity_fails_14d_proxy")
    valid = not reasons
    provenance = _canonical_sha256(
        {
            "protocol_sha256": DEFAULT_CONTEXT_PROTOCOL_SHA256,
            "nominal_span_rule": NOMINAL_SPAN_RULE,
            "decision_at": decision,
            "asset_id": asset_id,
            "observation": (
                None
                if observation is None
                else {
                    "decision_at": observation.decision_at,
                    "asset_id": observation.asset_id,
                    "contract_id": observation.contract_id,
                    "contract_code": observation.contract_code,
                    "known_at": observation.known_at,
                    "source_id": observation.source_id,
                    "observation_id": observation.observation_id,
                    "source_sha256": observation.source_sha256,
                }
            ),
            "derived_nominal_maturity_date": maturity,
            "final_expiration_date_used_for_decision": False,
            "valid": valid,
            "reason_codes": sorted(reasons),
        }
    )
    return NominalContractAssessment(
        observation=observation,
        nominal_maturity_date=maturity,
        planned_contract_valid=valid,
        reason_codes=tuple(sorted(reasons)),
        nominal_span_rule=NOMINAL_SPAN_RULE,
        provenance_sha256=provenance,
    )


def compare_final_expiration_qa(
    assessment: NominalContractAssessment,
    final_expiration_date: date,
) -> NominalExpirationQa:
    """Sravnivaet final expiry tol'ko posle decision path bez obratnoi svyazi."""
    if assessment.observation is None or assessment.nominal_maturity_date is None:
        raise ValueError("expiration QA trebuet dokazannuyu nominal mapping")
    if isinstance(final_expiration_date, datetime) or not isinstance(final_expiration_date, date):
        raise TypeError("final_expiration_date dolzhen byt' exact date")
    observation = assessment.observation
    return NominalExpirationQa(
        asset_id=observation.asset_id,
        contract_id=observation.contract_id,
        nominal_maturity_date=assessment.nominal_maturity_date,
        final_expiration_date=final_expiration_date,
        differs=final_expiration_date != assessment.nominal_maturity_date,
    )


@dataclass(frozen=True, slots=True)
class ModelSignalObservation:
    """Target-free base/regime output odnogo asseta s original model mask."""

    decision_at: datetime
    asset_id: str
    known_at: datetime
    model_input_valid: bool
    factor_decision_score: float | None
    residual_decision_score: float | None
    residual_location: float | None
    total_scale: float | None
    abstain_probability: float | None
    normal_probability: float | None
    trend_probability: float | None
    crash_probability: float | None
    source_sha256: str

    def __post_init__(self) -> None:
        """Trebuet finite model payload tol'ko kogda original model mask true."""
        decision = _require_aware(self.decision_at, "model decision_at")
        known = _require_aware(self.known_at, "model known_at")
        if known > decision:
            raise ValueError("model output byl sozdan posle decision")
        if self.asset_id not in V8_ASSET_IDS or not isinstance(self.model_input_valid, bool):
            raise ValueError("model observation asset/mask invalid")
        fields = (
            "factor_decision_score",
            "residual_decision_score",
            "residual_location",
            "total_scale",
            "abstain_probability",
            "normal_probability",
            "trend_probability",
            "crash_probability",
        )
        for name in fields:
            value = getattr(self, name)
            if value is not None:
                _finite(value, name)
        if self.model_input_valid and any(getattr(self, name) is None for name in fields):
            raise ValueError("model_input_valid trebuet full finite output")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(
            self, "source_sha256", _require_sha256(self.source_sha256, "model source_sha256")
        )


@dataclass(frozen=True, slots=True)
class BuiltAssetContext:
    """Full target-free audit row, vklyuchaya optional PIT i contract proxy."""

    snapshot: CausalAssetSnapshot
    market: MarketFeatureSnapshot
    contract: NominalContractAssessment
    pit: tuple[StandardizedPitObservation, ...]


@dataclass(frozen=True, slots=True)
class EvaluationExitObservation:
    """Evaluation-only D_i->D_i+5 calendar mapping, skrytyi ot strategy."""

    decision_at: datetime
    evaluation_exit_observable: bool
    evaluation_exit_decision_at: datetime | None
    provenance_sha256: str


def build_evaluation_exit_observability(
    decisions: Sequence[datetime],
) -> dict[datetime, EvaluationExitObservation]:
    """Otmechaet last-five no-entry bez contract expiry ili strategy masks."""
    normalized = tuple(_require_aware(item, "evaluation decision") for item in decisions)
    if (
        not normalized
        or tuple(sorted(normalized)) != normalized
        or len(set(normalized)) != len(normalized)
    ):
        raise ValueError("evaluation decisions dolzhny byt' nonempty unique increasing")
    calendar_sha = _canonical_sha256(normalized)
    output: dict[datetime, EvaluationExitObservation] = {}
    for index, decision_at in enumerate(normalized):
        exit_index = index + EVALUATION_EXIT_HORIZON_DECISIONS
        exit_at = normalized[exit_index] if exit_index < len(normalized) else None
        observable = exit_at is not None and exit_at.date() < PROTECTED_HOLDOUT_START
        provenance = _canonical_sha256(
            {
                "context_protocol_sha256": DEFAULT_CONTEXT_PROTOCOL_SHA256,
                "calendar_sha256": calendar_sha,
                "decision_index": index,
                "decision_at": decision_at,
                "horizon_common_decisions": EVALUATION_EXIT_HORIZON_DECISIONS,
                "evaluation_exit_decision_at": exit_at,
                "observable": observable,
                "final_expiration_date_used": False,
                "strategy_validity_masks_used": False,
            }
        )
        output[decision_at] = EvaluationExitObservation(
            decision_at=decision_at,
            evaluation_exit_observable=observable,
            evaluation_exit_decision_at=exit_at if observable else None,
            provenance_sha256=provenance,
        )
    return output


@dataclass(frozen=True, slots=True)
class BuiltDecisionContext:
    """Strategy context plus full validity/provenance records na odin D."""

    context: CausalDecisionContext
    assets: tuple[BuiltAssetContext, ...]
    evaluation_exit: EvaluationExitObservation


def build_validity_aware_contexts(
    decisions: Sequence[datetime],
    model_signals: Sequence[ModelSignalObservation],
    market: Mapping[tuple[datetime, str], MarketFeatureSnapshot],
    pit: Mapping[tuple[datetime, str | None, str], StandardizedPitObservation],
    contract_plans: Sequence[PlannedContractObservation],
    *,
    prediction_sha256: str,
) -> tuple[BuiltDecisionContext, ...]:
    """Join'it exact four assets, sohranyaya None/masks do strategy filtering."""
    prediction_sha = _require_sha256(prediction_sha256, "prediction_sha256")
    normalized_decisions = tuple(_require_aware(item, "decision") for item in decisions)
    if (
        not normalized_decisions
        or len(set(normalized_decisions)) != len(normalized_decisions)
        or tuple(sorted(normalized_decisions)) != normalized_decisions
    ):
        raise ValueError("context decisions dolzhny byt' nonempty unique increasing")
    expected_keys = {
        (decision_at, asset_id) for decision_at in normalized_decisions for asset_id in V8_ASSET_IDS
    }
    model_by_key = {(item.decision_at, item.asset_id): item for item in model_signals}
    if len(model_by_key) != len(model_signals):
        raise ValueError("model signals soderzhat duplicate keys")
    if set(model_by_key) != expected_keys:
        raise ValueError("model signals ne imeyut exact decision x four-asset coverage")
    if set(market) != expected_keys:
        raise ValueError("market snapshots ne imeyut exact decision x four-asset coverage")
    plan_by_key = {(item.decision_at, item.asset_id): item for item in contract_plans}
    if len(plan_by_key) != len(contract_plans):
        raise ValueError("contract plans soderzhat duplicate keys")
    if not set(plan_by_key).issubset(expected_keys):
        raise ValueError("contract plans soderzhat key vne decision x asset coverage")
    if any(key[0] not in set(normalized_decisions) for key in pit):
        raise ValueError("PIT mapping soderzhit decision vne context calendar")
    results: list[BuiltDecisionContext] = []
    evaluation_exit = build_evaluation_exit_observability(normalized_decisions)
    for decision_at in normalized_decisions:
        built_assets: list[BuiltAssetContext] = []
        snapshots: list[CausalAssetSnapshot] = []
        for asset_id in V8_ASSET_IDS:
            key = (decision_at, asset_id)
            if key not in model_by_key or key not in market:
                raise ValueError("context join trebuet exact model/market four-asset coverage")
            model = model_by_key[key]
            market_item = market[key]
            contract = assess_planned_contract(
                plan_by_key.get(key),
                decision_at=decision_at,
                asset_id=asset_id,
            )
            pit_items: list[StandardizedPitObservation] = []
            pit_points: dict[str, PointInTimeObservation | None] = {}
            for channel in (
                "carry_z",
                "cftc_crowd_z",
                "key_rate_change_z",
                "usd_rub_return_z",
            ):
                pit_key = (
                    decision_at,
                    asset_id if channel in {"carry_z", "cftc_crowd_z"} else None,
                    channel,
                )
                item = pit.get(pit_key)
                if item is not None:
                    pit_items.append(item)
                pit_points[channel] = None if item is None else item.standardized
            reasons: list[str] = []
            if not model.model_input_valid:
                reasons.append("model_input_invalid")
            if not market_item.decision_market_valid:
                reasons.extend(market_item.reason_codes)
                reasons.append("decision_market_invalid")
            if not contract.planned_contract_valid:
                reasons.extend(contract.reason_codes)
                reasons.append("planned_contract_invalid")
            validity_sha = _canonical_sha256(
                {
                    "context_protocol_sha256": DEFAULT_CONTEXT_PROTOCOL_SHA256,
                    "model_source_sha256": model.source_sha256,
                    "market_source_sha256": market_item.market_data_sha256,
                    "contract_provenance_sha256": contract.provenance_sha256,
                    "pit": [
                        {
                            "channel": item.raw.channel,
                            "observation_id": item.raw.observation_id,
                            "source_sha256": item.raw.source_sha256,
                            "history_count": item.history_count,
                        }
                        for item in sorted(pit_items, key=lambda value: value.raw.channel)
                    ],
                    "reason_codes": sorted(set(reasons)),
                }
            )
            known_candidates = [model.known_at]
            if market_item.known_at is not None:
                known_candidates.append(market_item.known_at)
            if contract.observation is not None:
                known_candidates.append(contract.observation.known_at)
            snapshot = CausalAssetSnapshot(
                asset_id=asset_id,
                known_at=max(known_candidates),
                factor_decision_score=model.factor_decision_score,
                residual_decision_score=model.residual_decision_score,
                residual_location=model.residual_location,
                total_scale=model.total_scale,
                abstain_probability=model.abstain_probability,
                normal_probability=model.normal_probability,
                trend_probability=model.trend_probability,
                crash_probability=model.crash_probability,
                close=market_item.close,
                atr_20=market_item.atr_20,
                daily_volatility_20=market_item.daily_volatility_20,
                momentum_20=market_item.momentum_20,
                range_position_20=market_item.range_position_20,
                volatility_ratio_20=market_item.volatility_ratio_20,
                volume_ratio_20=market_item.volume_ratio_20,
                market_data_sha256=market_item.market_data_sha256,
                carry_z=pit_points["carry_z"],
                cftc_crowd_z=pit_points["cftc_crowd_z"],
                key_rate_change_z=pit_points["key_rate_change_z"],
                usd_rub_return_z=pit_points["usd_rub_return_z"],
                model_input_valid=model.model_input_valid,
                decision_market_valid=market_item.decision_market_valid,
                planned_contract_valid=contract.planned_contract_valid,
                invalid_reason_codes=tuple(sorted(set(reasons))),
                planned_contract_id=(
                    None if contract.observation is None else contract.observation.contract_id
                ),
                nominal_maturity_date=contract.nominal_maturity_date,
                nominal_span_rule=contract.nominal_span_rule,
                validity_provenance_sha256=validity_sha,
            )
            snapshots.append(snapshot)
            built_assets.append(
                BuiltAssetContext(snapshot, market_item, contract, tuple(pit_items))
            )
        context = CausalDecisionContext(
            decision_at=decision_at,
            assets=tuple(snapshots),
            prediction_sha256=prediction_sha,
        )
        results.append(
            BuiltDecisionContext(
                context,
                tuple(built_assets),
                evaluation_exit[decision_at],
            )
        )
    return tuple(results)


def context_records_frame(contexts: Sequence[BuiltDecisionContext]) -> pd.DataFrame:
    """Serializuet target-free optional rows bez PnL/label kolonok."""
    rows: list[dict[str, object]] = []
    for built in contexts:
        for item in built.assets:
            snapshot = item.snapshot
            row: dict[str, object] = {
                "decision_at": built.context.decision_at,
                "asset": snapshot.asset_id,
                "known_at": snapshot.known_at,
                "model_input_valid": snapshot.model_input_valid,
                "decision_market_valid": snapshot.decision_market_valid,
                "planned_contract_valid": snapshot.planned_contract_valid,
                "strategy_eligible": snapshot.strategy_eligible,
                "evaluation_exit_observable": (built.evaluation_exit.evaluation_exit_observable),
                "evaluation_exit_decision_at": (built.evaluation_exit.evaluation_exit_decision_at),
                "evaluation_exit_provenance_sha256": (built.evaluation_exit.provenance_sha256),
                "invalid_reason_codes": "|".join(snapshot.invalid_reason_codes),
                "factor_decision_score": snapshot.factor_decision_score,
                "residual_decision_score": snapshot.residual_decision_score,
                "residual_location": snapshot.residual_location,
                "total_scale": snapshot.total_scale,
                "abstain_probability": snapshot.abstain_probability,
                "normal_probability": snapshot.normal_probability,
                "trend_probability": snapshot.trend_probability,
                "crash_probability": snapshot.crash_probability,
                "close": snapshot.close,
                "adjusted_signal_open": item.market.adjusted_signal_open,
                "adjusted_signal_high": item.market.adjusted_signal_high,
                "adjusted_signal_low": item.market.adjusted_signal_low,
                "adjusted_signal_close": item.market.adjusted_signal_close,
                "atr_20": snapshot.atr_20,
                "daily_volatility_20": snapshot.daily_volatility_20,
                "momentum_20": snapshot.momentum_20,
                "range_position_20": snapshot.range_position_20,
                "volatility_ratio_20": snapshot.volatility_ratio_20,
                "volume_ratio_20": snapshot.volume_ratio_20,
                "market_data_sha256": snapshot.market_data_sha256,
                "market_reason_codes": "|".join(item.market.reason_codes),
                "main_session_bucket_count": item.market.main_session_bucket_count,
                "main_session_expected_bucket_count": (
                    item.market.main_session_expected_bucket_count
                ),
                "close_bar_open_at": item.market.close_bar_open_at,
                "close_bar_scheduled_close_at": (item.market.close_bar_scheduled_close_at),
                "close_bar_raw_end_at": item.market.close_bar_raw_end_at,
                "main_session_source_sha256s": "|".join(item.market.main_session_source_sha256s),
                "planned_contract_id": snapshot.planned_contract_id,
                "nominal_maturity_date": snapshot.nominal_maturity_date,
                "nominal_span_rule": snapshot.nominal_span_rule,
                "contract_reason_codes": "|".join(item.contract.reason_codes),
                "contract_provenance_sha256": item.contract.provenance_sha256,
                "validity_provenance_sha256": snapshot.validity_provenance_sha256,
                "input_bundle_sha256": built.context.input_bundle_sha256,
            }
            if item.contract.observation is None:
                row.update(
                    {
                        "planned_contract_code": None,
                        "planned_contract_known_at": None,
                        "planned_contract_source_id": None,
                        "planned_contract_observation_id": None,
                        "planned_contract_source_sha256": None,
                    }
                )
            else:
                observation = item.contract.observation
                row.update(
                    {
                        "planned_contract_code": observation.contract_code,
                        "planned_contract_known_at": observation.known_at,
                        "planned_contract_source_id": observation.source_id,
                        "planned_contract_observation_id": observation.observation_id,
                        "planned_contract_source_sha256": observation.source_sha256,
                    }
                )
            pit_by_channel = {pit_item.raw.channel: pit_item for pit_item in item.pit}
            for channel in (
                "carry_z",
                "cftc_crowd_z",
                "key_rate_change_z",
                "usd_rub_return_z",
            ):
                pit_item = pit_by_channel.get(channel)
                row[f"{channel}_raw_value"] = None if pit_item is None else pit_item.raw.raw_value
                row[f"{channel}_value"] = (
                    None
                    if pit_item is None or pit_item.standardized is None
                    else pit_item.standardized.value
                )
                row[f"{channel}_unclipped_z"] = None if pit_item is None else pit_item.unclipped_z
                row[f"{channel}_history_count"] = (
                    None if pit_item is None else pit_item.history_count
                )
                row[f"{channel}_published_at"] = (
                    None if pit_item is None else pit_item.raw.published_at
                )
                row[f"{channel}_available_at"] = (
                    None if pit_item is None else pit_item.raw.available_at
                )
                row[f"{channel}_source_id"] = None if pit_item is None else pit_item.raw.source_id
                row[f"{channel}_observation_id"] = (
                    None if pit_item is None else pit_item.raw.observation_id
                )
                row[f"{channel}_source_sha256"] = (
                    None if pit_item is None else pit_item.raw.source_sha256
                )
                row[f"{channel}_freshness_seconds"] = (
                    None if pit_item is None else pit_item.freshness_seconds
                )
                row[f"{channel}_reason_code"] = None if pit_item is None else pit_item.reason_code
            rows.append(row)
    frame = pd.DataFrame(rows).sort_values(["decision_at", "asset"], kind="stable")
    forbidden = [
        column
        for column in frame
        if any(token in column.lower() for token in FORBIDDEN_CONTEXT_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"context frame soderzhit forbidden columns: {forbidden}")
    if pd.to_datetime(frame["decision_at"], utc=True).dt.date.ge(PROTECTED_HOLDOUT_START).any():
        raise ValueError("context frame pytayetsya zapisat' protected 2026")
    return frame.reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class ContextDependencyProof:
    """Caller-independent file identity, kotoraya proveriaetsya po project bytes."""

    name: str
    relative_path: str
    sha256: str
    bytes: int
    rows: int | None = None

    def __post_init__(self) -> None:
        """Normalizuet deklaraciyu bez doveriya k ee hash/size assertions."""
        object.__setattr__(self, "name", _require_identifier(self.name, "dependency name"))
        relative = Path(_require_identifier(self.relative_path, "dependency relative_path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("dependency path dolzhen byt' relative bez parent escape")
        object.__setattr__(self, "relative_path", relative.as_posix())
        object.__setattr__(
            self,
            "sha256",
            _require_sha256(self.sha256, f"{self.name} dependency SHA"),
        )
        if isinstance(self.bytes, bool) or not isinstance(self.bytes, int) or self.bytes < 0:
            raise ValueError("dependency bytes dolzhen byt' nonnegative int")
        if self.rows is not None and (
            isinstance(self.rows, bool) or not isinstance(self.rows, int) or self.rows < 0
        ):
            raise ValueError("dependency rows dolzhen byt' nonnegative int ili None")


@dataclass(frozen=True, slots=True)
class MainSessionManifestTreeProof:
    """Rezultat nezavisimoi proverki vseh 10m child manifests/raw/parquet."""

    asset_manifest_count: int
    segment_manifest_count: int
    raw_artifact_count: int
    parquet_artifact_count: int
    parquet_rows: int
    child_bundle_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedContextDependencies:
    """Exact dependency proofs plus transitive 10m child-set identity."""

    proofs: tuple[ContextDependencyProof, ...]
    main_session_tree: MainSessionManifestTreeProof


def _resolve_data_child(project_root: Path, relative_path: str, label: str) -> Path:
    """Razreshaet sealed manifest child tol'ko pod project ``data`` root."""
    relative = Path(_require_identifier(relative_path, label))
    data_root = (project_root / "data").resolve()
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} dolzhen byt' relative data path")
    resolved = (data_root / relative).resolve()
    if not resolved.is_relative_to(data_root) or not resolved.is_file():
        raise ValueError(f"{label} otsutstvuet ili vykhodit za data root")
    return resolved


def _verify_manifest_file_record(
    project_root: Path,
    record: Mapping[str, Any],
    *,
    role: str,
) -> tuple[Path, dict[str, object]]:
    """Proveriaet path/bytes/SHA odnogo transitive manifest child do read."""
    if not isinstance(record, Mapping):
        raise TypeError(f"{role} record dolzhen byt' object")
    relative_path = _require_identifier(str(record.get("path", "")), f"{role} path")
    resolved = _resolve_data_child(project_root, relative_path, f"{role} path")
    expected_bytes = record.get("bytes")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
    ):
        raise ValueError(f"{role} bytes dolzhen byt' nonnegative int")
    expected_sha = _require_sha256(str(record.get("sha256", "")), f"{role} SHA")
    if resolved.stat().st_size != expected_bytes or _sha256_file(resolved) != expected_sha:
        raise ValueError(f"{role} child bytes/hash mismatch")
    normalized: dict[str, object] = {
        "role": role,
        "path": relative_path.replace("\\", "/"),
        "bytes": expected_bytes,
        "sha256": expected_sha,
    }
    if "rows" in record:
        rows = record["rows"]
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError(f"{role} rows dolzhen byt' nonnegative int")
        normalized["rows"] = rows
    return resolved, normalized


def _require_parquet_pre_holdout_timestamps(
    parquet_path: Path,
    parquet: Any,
) -> None:
    """Dokazyvaet physical timestamp/end_timestamp <2026 i raw-end bucket bound."""
    required = ("timestamp", "end_timestamp")
    if any(name not in parquet.schema.names for name in required):
        raise ValueError("10m parquet ne imeet timestamp/end_timestamp")
    frame = pd.read_parquet(parquet_path, columns=list(required))
    starts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    raw_ends = pd.to_datetime(frame["end_timestamp"], utc=True, errors="coerce")
    if starts.isna().any() or raw_ends.isna().any():
        raise ValueError("10m parquet timestamp/end_timestamp soderzhit NaT")
    protected = pd.Timestamp(datetime(2026, 1, 1, tzinfo=UTC))
    if (starts >= protected).any() or (raw_ends >= protected).any():
        raise ValueError("10m parquet physical timestamp dostigaet protected 2026")
    if ((raw_ends <= starts) | (raw_ends > starts + pd.Timedelta(minutes=10))).any():
        raise ValueError("10m raw end narushaet scheduled ten-minute boundary")


def verify_main_session_manifest_tree(top_manifest_path: Path) -> MainSessionManifestTreeProof:
    """Proveriaet top->asset->segment->raw/parquet tree bez doveriya calleru."""
    top = top_manifest_path.resolve()
    project_root = DEFAULT_CONTEXT_PROTOCOL_PATH.resolve().parents[1]
    if not top.is_relative_to((project_root / "data").resolve()):
        raise ValueError("10m top manifest dolzhen byt' v project data root")
    payload = json.loads(top.read_text(encoding="utf-8-sig"))
    if (
        payload.get("requested_end") != "2025-12-31"
        or payload.get("protected_from") != "2026-01-01"
        or payload.get("completion") != "all_four_asset_manifests_verified"
    ):
        raise ValueError("10m top manifest temporal/completion contract drift")
    assets = payload.get("assets")
    if not isinstance(assets, list) or {
        item.get("asset_code") for item in assets if isinstance(item, dict)
    } != {"BR", "MIX", "RTS", "Si"}:
        raise ValueError("10m top manifest ne imeet exact four-asset set")
    child_records: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    segment_count = 0
    raw_count = 0
    parquet_count = 0
    parquet_rows = 0
    for asset_record in assets:
        asset_path, normalized_asset = _verify_manifest_file_record(
            project_root,
            asset_record,
            role="asset_manifest",
        )
        if normalized_asset["path"] in seen_paths:
            raise ValueError("10m manifest tree soderzhit duplicate child path")
        seen_paths.add(str(normalized_asset["path"]))
        child_records.append(normalized_asset)
        asset_payload = json.loads(asset_path.read_text(encoding="utf-8-sig"))
        if (
            asset_payload.get("requested_end") != "2025-12-31"
            or asset_payload.get("protected_from") != "2026-01-01"
        ):
            raise ValueError("10m asset manifest temporal contract drift")
        segment_records = asset_payload.get("segment_manifests")
        if not isinstance(segment_records, list):
            raise TypeError("10m asset segment_manifests dolzhen byt' list")
        asset_rows = 0
        for segment_record in segment_records:
            if not isinstance(segment_record, Mapping):
                raise TypeError("10m segment record dolzhen byt' object")
            if segment_record.get("status") not in {"complete", "complete_empty"}:
                raise ValueError("10m segment ne imeet sealed completion status")
            segment_path, normalized_segment = _verify_manifest_file_record(
                project_root,
                segment_record,
                role="segment_manifest",
            )
            if normalized_segment["path"] in seen_paths:
                raise ValueError("10m manifest tree soderzhit duplicate child path")
            seen_paths.add(str(normalized_segment["path"]))
            child_records.append(normalized_segment)
            segment_payload = json.loads(segment_path.read_text(encoding="utf-8-sig"))
            if segment_payload.get("status") != segment_record.get("status"):
                raise ValueError("10m segment status ne sootvetstvuet parent manifest")
            counts = segment_payload.get("counts")
            artifacts = segment_payload.get("artifacts")
            quality = segment_payload.get("quality")
            segment = segment_payload.get("segment")
            pagination = segment_payload.get("pagination")
            if not all(
                isinstance(item, dict) for item in (counts, artifacts, quality, segment, pagination)
            ):
                raise TypeError("10m segment manifest ne imeet counts/artifacts/quality/pagination")
            segment_end = date.fromisoformat(str(segment.get("requested_end")))
            top_end = date.fromisoformat(str(payload["requested_end"]))
            if segment_end > top_end:
                raise ValueError("10m segment requested_end vykhodit v protected period")
            if (
                quality.get("out_of_bounds_rows") != 0
                or quality.get("duplicate_timestamps") != 0
                or quality.get("invalid_ohlc_rows") != 0
                or quality.get("strictly_increasing_timestamps") is not True
            ):
                raise ValueError("10m segment quality ne fail-closed")
            pages = pagination.get("pages")
            if not isinstance(pages, list):
                raise TypeError("10m segment pagination pages dolzhen byt' list")
            for page in pages:
                if not isinstance(page, dict):
                    raise TypeError("10m pagination page dolzhen byt' object")
                query = parse_qs(urlparse(str(page.get("url", ""))).query)
                if query.get("till") != [segment_end.isoformat()]:
                    raise ValueError("10m page URL till ne raven segment requested_end")
                page_from = date.fromisoformat(query.get("from", [""])[0])
                if page_from > segment_end or segment_end >= PROTECTED_HOLDOUT_START:
                    raise ValueError("10m page URL peresekaet protected holdout")
            segment_rows = int(counts.get("rows", -1))
            if segment_rows != segment_record.get("rows") or segment_rows < 0:
                raise ValueError("10m segment row count ne sootvetstvuet parent")
            asset_rows += segment_rows
            segment_count += 1
            for artifact_role in ("raw", "parquet"):
                artifact_path, normalized_artifact = _verify_manifest_file_record(
                    project_root,
                    artifacts.get(artifact_role, {}),
                    role=f"segment_{artifact_role}",
                )
                if normalized_artifact["path"] in seen_paths:
                    raise ValueError("10m manifest tree soderzhit duplicate child path")
                seen_paths.add(str(normalized_artifact["path"]))
                if normalized_artifact.get("rows") != segment_rows:
                    raise ValueError("10m artifact rows ne sootvetstvuyut segment")
                child_records.append(normalized_artifact)
                if artifact_role == "raw":
                    raw_count += 1
                    continue
                from pyarrow import parquet as parquet_module

                parquet = parquet_module.ParquetFile(artifact_path)
                if parquet.metadata.num_rows != segment_rows:
                    raise ValueError("10m parquet physical row count mismatch")
                forbidden = [
                    name
                    for name in parquet.schema.names
                    if any(token in name.lower() for token in FORBIDDEN_CONTEXT_TOKENS)
                ]
                if forbidden:
                    raise ValueError("10m parquet soderzhit forbidden target/PnL schema")
                _require_parquet_pre_holdout_timestamps(artifact_path, parquet)
                parquet_count += 1
                parquet_rows += segment_rows
        if asset_rows != asset_record.get("rows"):
            raise ValueError("10m asset rows ne ravny summe segmentov")
    totals = payload.get("totals", {})
    if (
        segment_count != totals.get("segments")
        or parquet_rows != totals.get("rows")
        or raw_count != segment_count
        or parquet_count != segment_count
    ):
        raise ValueError("10m top totals ne sootvetstvuyut verified child tree")
    return MainSessionManifestTreeProof(
        asset_manifest_count=len(assets),
        segment_manifest_count=segment_count,
        raw_artifact_count=raw_count,
        parquet_artifact_count=parquet_count,
        parquet_rows=parquet_rows,
        child_bundle_sha256=_canonical_sha256(
            sorted(child_records, key=lambda item: (str(item["path"]), str(item["role"])))
        ),
    )


def verify_context_dependency_proofs(
    proofs: Sequence[ContextDependencyProof],
    protocol: EvaluationContextProtocol,
) -> VerifiedContextDependencies:
    """Hashiruet vse source bytes do per-file parsing i dokazyvaet transitive seals."""
    by_name = {item.name: item for item in proofs}
    if len(by_name) != len(proofs):
        raise ValueError("context dependencies soderzhat duplicate name")
    if tuple(sorted(by_name)) != tuple(sorted(REQUIRED_CONTEXT_DEPENDENCIES)):
        missing = sorted(set(REQUIRED_CONTEXT_DEPENDENCIES) - set(by_name))
        extra = sorted(set(by_name) - set(REQUIRED_CONTEXT_DEPENDENCIES))
        raise ValueError(f"context dependency names ne exact; missing={missing}, extra={extra}")
    resolved: dict[str, Path] = {}
    for name, proof in by_name.items():
        path = _resolve_project_file(proof.relative_path, f"{name} dependency path")
        if path.stat().st_size != proof.bytes or _sha256_file(path) != proof.sha256:
            raise ValueError(f"context dependency bytes/hash mismatch: {name}")
        resolved[name] = path
    for name, (pinned_path, pinned_sha) in protocol.dependency_pins.items():
        proof = by_name[name]
        if proof.relative_path != pinned_path or proof.sha256 != pinned_sha:
            raise ValueError(f"context dependency ne sootvetstvuet protocol pin: {name}")
    for name, proof in by_name.items():
        if proof.rows is None:
            continue
        if resolved[name].suffix.lower() != ".parquet":
            raise ValueError("dependency rows razresheny tol'ko dlya parquet")
        from pyarrow import parquet as parquet_module

        actual_rows = parquet_module.ParquetFile(resolved[name]).metadata.num_rows
        if actual_rows != proof.rows:
            raise ValueError(f"context dependency row-count mismatch: {name}")
    main_session_tree = verify_main_session_manifest_tree(resolved["main_session_10m"])
    artifact_contract = protocol.raw["artifact"]
    expected_tree_counts = artifact_contract.get("main_session_transitive_counts", {})
    if (
        main_session_tree.child_bundle_sha256
        != artifact_contract.get("main_session_transitive_child_bundle_sha256")
        or {
            "asset_manifests": main_session_tree.asset_manifest_count,
            "segment_manifests": main_session_tree.segment_manifest_count,
            "raw_artifacts": main_session_tree.raw_artifact_count,
            "parquet_artifacts": main_session_tree.parquet_artifact_count,
            "parquet_rows": main_session_tree.parquet_rows,
        }
        != expected_tree_counts
    ):
        raise ValueError("10m transitive child tree ne sootvetstvuet context seal")
    catalog = by_name["aggressive_catalog"]
    catalog_sidecar = by_name["aggressive_catalog_sidecar"]
    sidecar_parts = (
        resolved["aggressive_catalog_sidecar"].read_text(encoding="utf-8-sig").strip().split()
    )
    if sidecar_parts != [catalog.sha256, resolved["aggressive_catalog"].name]:
        raise ValueError("aggressive catalog sidecar ne sootvetstvuet catalog bytes")
    catalog_payload = yaml.safe_load(resolved["aggressive_catalog"].read_text(encoding="utf-8-sig"))
    if not isinstance(catalog_payload, dict):
        raise TypeError("aggressive catalog dolzhen byt' YAML object")
    if (
        catalog_payload.get("context_protocol_sha256") != protocol.sha256
        or catalog_payload.get("context_protocol")
        != protocol.path.relative_to(DEFAULT_CONTEXT_PROTOCOL_PATH.resolve().parents[1]).as_posix()
        or catalog_payload.get("implementation_sha256")
        != by_name["aggressive_implementation"].sha256
        or catalog_payload.get("implementation")
        != by_name["aggressive_implementation"].relative_path
        or catalog_payload.get("context_implementation_sha256")
        != by_name["context_implementation"].sha256
        or catalog_payload.get("context_implementation")
        != by_name["context_implementation"].relative_path
        or catalog_payload.get("base_protocol_sha256") != protocol.base_protocol_sha256
    ):
        raise ValueError("catalog/context/implementation transitive closure mismatch")
    if resolved["context_implementation"] != Path(__file__).resolve():
        raise ValueError("context implementation proof ne ukazyvaet na executing builder")
    if catalog_sidecar.relative_path != f"{catalog.relative_path.rsplit('.', 1)[0]}.sha256":
        raise ValueError("aggressive catalog sidecar path ne kanonichen")
    return VerifiedContextDependencies(
        proofs=tuple(by_name[name] for name in sorted(by_name)),
        main_session_tree=main_session_tree,
    )


@dataclass(frozen=True, slots=True)
class ContextArtifactPaths:
    """Puti target-free parquet i BOM manifesta context buildera."""

    parquet_path: Path
    manifest_path: Path
    manifest_sidecar_path: Path


@dataclass(frozen=True, slots=True)
class RealContextBuildAudit:
    """Target-free counters deterministic real raw-to-context builda."""

    full_calendar_decisions: int
    oos_decisions: int
    context_rows: int
    selected_raw_10m_bars: int
    model_input_valid_rows: int
    decision_market_valid_rows: int
    planned_contract_valid_rows: int
    strategy_eligible_rows: int
    evaluation_exit_observable_rows: int
    final_daily_panel_qa: FinalDailyPanelQaAudit
    pit_channels: tuple[PitStandardizationAudit, ...]
    key_rate_unique_finite_changes: int
    source_columns_read: tuple[tuple[str, tuple[str, ...]], ...]
    protected_holdout_accessed: bool = False


@dataclass(frozen=True, slots=True)
class RealContextBuildResult:
    """Puti content-addressed source i ego deterministic coverage audit."""

    artifacts: ContextArtifactPaths
    audit: RealContextBuildAudit


def _dependency_proof_from_file(
    name: str,
    relative_path: str,
) -> ContextDependencyProof:
    """Stroit typed proof iz factual bytes; verifier zanovo proveryaet ego."""
    path = _resolve_project_file(relative_path, f"{name} proof path")
    return ContextDependencyProof(
        name=name,
        relative_path=relative_path.replace("\\", "/"),
        sha256=_sha256_file(path),
        bytes=path.stat().st_size,
        rows=None,
    )


def build_real_dependency_proofs(
    protocol: EvaluationContextProtocol,
) -> tuple[ContextDependencyProof, ...]:
    """Sobiraet exact pinned plus dynamic code/catalog closure bez data parsing."""
    records = [
        _dependency_proof_from_file(name, relative_path)
        for name, (relative_path, _sha) in protocol.dependency_pins.items()
    ]
    records.extend(
        (
            _dependency_proof_from_file(
                "aggressive_catalog",
                "configs/futures_v8_aggressive_candidates.yaml",
            ),
            _dependency_proof_from_file(
                "aggressive_catalog_sidecar",
                "configs/futures_v8_aggressive_candidates.sha256",
            ),
            _dependency_proof_from_file(
                "context_implementation",
                "src/market_lab/futures_v8/context_run.py",
            ),
        )
    )
    return tuple(records)


def _read_whitelisted_parquet(
    path: Path,
    columns: Sequence[str],
    *,
    source_name: str,
) -> pd.DataFrame:
    """Chitaet tol'ko explicit target-free columns posle dependency verification."""
    requested = tuple(columns)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError(f"{source_name} whitelist dolzhen byt' nonempty unique")
    forbidden = [
        name
        for name in requested
        if any(token in name.lower() for token in FORBIDDEN_CONTEXT_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"{source_name} whitelist soderzhit forbidden names")
    from pyarrow import parquet as parquet_module

    schema_names = set(parquet_module.ParquetFile(path).schema.names)
    missing = set(requested) - schema_names
    if missing:
        raise ValueError(f"{source_name} ne imeet whitelisted columns: {sorted(missing)}")
    return pd.read_parquet(path, columns=list(requested))


def _verified_raw_parquet_records(
    top_manifest_path: Path,
    verified_tree: MainSessionManifestTreeProof | None = None,
) -> tuple[tuple[Path, str], ...]:
    """Vozvrashchaet child parquet paths tol'ko posle transitive tree verifiera."""
    tree = verified_tree or verify_main_session_manifest_tree(top_manifest_path)
    if tree.parquet_artifact_count <= 0 or tree.parquet_rows <= 0:
        raise ValueError("verified 10m tree ne mozhet byt' pustym")
    project_root = DEFAULT_CONTEXT_PROTOCOL_PATH.resolve().parents[1]
    data_root = project_root / "data"
    top = json.loads(top_manifest_path.read_text(encoding="utf-8-sig"))
    records: list[tuple[Path, str]] = []
    for asset_record in top["assets"]:
        asset_path = data_root / str(asset_record["path"])
        asset = json.loads(asset_path.read_text(encoding="utf-8-sig"))
        for segment_record in asset["segment_manifests"]:
            segment_path = data_root / str(segment_record["path"])
            segment = json.loads(segment_path.read_text(encoding="utf-8-sig"))
            parquet_record = segment["artifacts"]["parquet"]
            records.append(
                (
                    (data_root / str(parquet_record["path"])).resolve(),
                    str(parquet_record["sha256"]),
                )
            )
    return tuple(records)


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Atomarno zamenyaet odin artifact v ego roditel'skom kataloge."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_context_source(
    output_dir: Path,
    contexts: Sequence[BuiltDecisionContext],
    *,
    dependency_proofs: Sequence[ContextDependencyProof],
    real_build_audit: RealContextBuildAudit | None = None,
    verified_dependencies: VerifiedContextDependencies | None = None,
) -> ContextArtifactPaths:
    """Persistit target-free proxy-calendar source, no ne prisvaivaet evaluator admission."""
    protocol = load_context_protocol()
    verified = verified_dependencies or verify_context_dependency_proofs(
        dependency_proofs, protocol
    )
    if verified_dependencies is not None and tuple(
        sorted(verified_dependencies.proofs, key=lambda item: item.name)
    ) != tuple(sorted(dependency_proofs, key=lambda item: item.name)):
        raise ValueError("preverified dependency bundle ne sootvetstvuet persist proofs")
    dependency_records = [
        {
            "name": item.name,
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "bytes": item.bytes,
            "rows": item.rows,
        }
        for item in verified.proofs
    ]
    frame = context_records_frame(contexts)
    output = output_dir.resolve()
    project_root = DEFAULT_CONTEXT_PROTOCOL_PATH.resolve().parents[1]
    if not output.is_relative_to(project_root):
        raise ValueError("context artifact dolzhen ostavat'sya v project root")
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / ".validity_aware_context.parquet.tmp"
    try:
        frame.to_parquet(temporary, index=False)
        parquet_sha = _sha256_file(temporary)
        parquet_path = output / f"validity_aware_context_{parquet_sha[:16]}.parquet"
        if parquet_path.exists():
            if _sha256_file(parquet_path) != parquet_sha:
                raise FileExistsError(
                    f"content-addressed parquet prefix collision: {parquet_path.name}"
                )
        else:
            os.replace(temporary, parquet_path)
    finally:
        temporary.unlink(missing_ok=True)
    reloaded = pd.read_parquet(parquet_path)
    if (
        len(reloaded) != len(frame)
        or list(reloaded.columns) != list(frame.columns)
        or reloaded.duplicated(["decision_at", "asset"]).any()
        or _sha256_file(parquet_path) != parquet_sha
    ):
        raise RuntimeError("persisted context ne proshel reload/hash/key verification")
    reason_counts: dict[str, int] = defaultdict(int)
    for encoded in frame["invalid_reason_codes"].astype(str):
        for reason in filter(None, encoded.split("|")):
            reason_counts[reason] += 1
    bucket_counts = {
        str(int(bucket)): int(count)
        for bucket, count in frame["main_session_bucket_count"].value_counts().sort_index().items()
    }
    manifest = {
        "schema": CONTEXT_SOURCE_SCHEMA,
        "context_completion_status": ("validity_aware_causal_raw_10m_context_proxy_calendar"),
        "evaluator_admission_status": "blocked_pending_schema_followup",
        "exact_five_session_proof_claimed": False,
        "nominal_span_rule": NOMINAL_SPAN_RULE,
        "context_protocol_sha256": protocol.sha256,
        "base_protocol_sha256": protocol.base_protocol_sha256,
        "initial_capital_rub": protocol.initial_capital_rub,
        "economic_policy": {
            "collateral_interest": 0.0,
            "taxes": "not_modeled",
            "dividends": "not_applicable_futures",
            "broker_queue_exact_claim": False,
            "bankruptcy_or_negative_equity": "no_go",
            "spec_proxy_dataset_sha256": SPEC_PROXY_DATASET_SHA256,
        },
        "artifact": {
            "path": parquet_path.name,
            "rows": len(frame),
            "sha256": parquet_sha,
            "columns": list(frame.columns),
        },
        "audit": {
            "decisions": int(frame["decision_at"].nunique()),
            "rows_by_asset": {
                str(asset): int(count)
                for asset, count in frame.groupby("asset", observed=True).size().items()
            },
            "model_input_valid_rows": int(frame["model_input_valid"].sum()),
            "decision_market_valid_rows": int(frame["decision_market_valid"].sum()),
            "planned_contract_valid_rows": int(frame["planned_contract_valid"].sum()),
            "strategy_eligible_rows": int(frame["strategy_eligible"].sum()),
            "evaluation_exit_observable_rows": int(frame["evaluation_exit_observable"].sum()),
            "evaluation_exit_observable_decisions": int(
                frame.loc[frame["evaluation_exit_observable"], "decision_at"].nunique()
            ),
            "invalid_reason_counts": dict(sorted(reason_counts.items())),
            "main_session_bucket_count_distribution": bucket_counts,
            "main_session_at_least_48_rows": int(
                frame["main_session_bucket_count"].ge(MAIN_SESSION_MINIMUM_BUCKETS).sum()
            ),
        },
        "dependencies": dependency_records,
        "dependency_bundle_sha256": _canonical_sha256(dependency_records),
        "main_session_transitive_tree": {
            "asset_manifest_count": verified.main_session_tree.asset_manifest_count,
            "segment_manifest_count": verified.main_session_tree.segment_manifest_count,
            "raw_artifact_count": verified.main_session_tree.raw_artifact_count,
            "parquet_artifact_count": verified.main_session_tree.parquet_artifact_count,
            "parquet_rows": verified.main_session_tree.parquet_rows,
            "child_bundle_sha256": verified.main_session_tree.child_bundle_sha256,
        },
        "context_protocol_sidecar_sha256": _sha256_file(protocol.path.with_suffix(".sha256")),
        "target_or_pnl_read": False,
        "protected_holdout_accessed": False,
    }
    if real_build_audit is not None:
        manifest["real_source_build_audit"] = {
            "full_calendar_decisions": real_build_audit.full_calendar_decisions,
            "oos_decisions": real_build_audit.oos_decisions,
            "context_rows": real_build_audit.context_rows,
            "selected_raw_10m_bars": real_build_audit.selected_raw_10m_bars,
            "model_input_valid_rows": real_build_audit.model_input_valid_rows,
            "decision_market_valid_rows": real_build_audit.decision_market_valid_rows,
            "planned_contract_valid_rows": real_build_audit.planned_contract_valid_rows,
            "strategy_eligible_rows": real_build_audit.strategy_eligible_rows,
            "evaluation_exit_observable_rows": (real_build_audit.evaluation_exit_observable_rows),
            "final_daily_panel_qa": {
                name: getattr(real_build_audit.final_daily_panel_qa, name)
                for name in FinalDailyPanelQaAudit.__dataclass_fields__
            },
            "pit_channels": [
                {name: getattr(item, name) for name in PitStandardizationAudit.__dataclass_fields__}
                for item in real_build_audit.pit_channels
            ],
            "key_rate_unique_finite_changes": (real_build_audit.key_rate_unique_finite_changes),
            "source_columns_read": {
                name: list(columns) for name, columns in real_build_audit.source_columns_read
            },
            "protected_holdout_accessed": (real_build_audit.protected_holdout_accessed),
        }
    manifest_payload_sha = _canonical_sha256(manifest)
    manifest["manifest_payload_sha256"] = manifest_payload_sha
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8-sig")
        + b"\n"
    )
    manifest_path = output / f"context_manifest_{manifest_payload_sha[:16]}.json"
    manifest_sidecar_path = manifest_path.with_suffix(".json.sha256")
    manifest_byte_sha = _sha256_bytes(manifest_bytes)
    sidecar_bytes = f"{manifest_byte_sha}  {manifest_path.name}\n".encode("utf-8-sig")
    for path, content in (
        (manifest_path, manifest_bytes),
        (manifest_sidecar_path, sidecar_bytes),
    ):
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"content-addressed artifact drift: {path.name}")
        else:
            _atomic_replace_bytes(path, content)
    reloaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    embedded_sha = reloaded_manifest.pop("manifest_payload_sha256", None)
    if (
        embedded_sha != manifest_payload_sha
        or _canonical_sha256(reloaded_manifest) != manifest_payload_sha
        or _sha256_file(manifest_path) != manifest_byte_sha
        or manifest_sidecar_path.read_text(encoding="utf-8-sig").strip().split()
        != [manifest_byte_sha, manifest_path.name]
    ):
        raise RuntimeError("context manifest ne proshel reload/payload/byte seal verification")
    return ContextArtifactPaths(parquet_path, manifest_path, manifest_sidecar_path)


def _decision_at_moscow_close(value: object) -> datetime:
    """Prevrashchaet factual common-session date v exact 18:50 MSK UTC."""
    day = pd.Timestamp(value).date()
    return datetime.combine(
        day, MAIN_SESSION_CLOSE_BAR_CLOSE, ZoneInfo("Europe/Moscow")
    ).astimezone(UTC)


def _asset_id(value: object) -> str:
    """Normalizuet tol'ko sealed aliases raw RTS/Si k RI/SI."""
    normalized = str(value).upper()
    aliases = {"RTS": "RI", "SI": "SI", "BR": "BR", "MIX": "MIX", "RI": "RI"}
    try:
        return aliases[normalized]
    except KeyError as error:
        raise ValueError(f"neizvestnyi futures asset alias: {value!r}") from error


def _load_active_contract_sources(
    path: Path,
    source_sha256: str,
    oos_decisions: Sequence[datetime],
) -> tuple[
    tuple[datetime, ...],
    tuple[CausalSessionContractObservation, ...],
    tuple[PlannedContractObservation, ...],
    pd.DataFrame,
    tuple[str, ...],
]:
    """Stroit D-session contract/offset i otdel'nyi entry plan bez final expiry."""
    columns = (
        "effective_date",
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "secid",
        "forward_additive_adjustment",
        "plan_tradable",
        "execution_open_available",
        "feature_input_valid",
    )
    frame = _read_whitelisted_parquet(path, columns, source_name="active_contract_map")
    for name in ("effective_date", "decision_date", "observed_through"):
        frame[name] = pd.to_datetime(frame[name], errors="coerce").dt.date
    frame["asset_id"] = frame["asset_code"].map(_asset_id)
    if frame.duplicated(["effective_date", "asset_id"]).any():
        raise ValueError("active map duplicate effective_date/asset")
    protected = frame["effective_date"].map(
        lambda item: pd.notna(item) and item >= PROTECTED_HOLDOUT_START
    )
    if protected.any():
        raise ValueError("active map whitelist dostig protected 2026")
    calendar_counts = (
        frame.dropna(subset=["effective_date"])
        .groupby("effective_date", observed=True)["asset_id"]
        .nunique()
    )
    calendar_days = tuple(sorted(calendar_counts[calendar_counts == len(V8_ASSET_IDS)].index))
    full_decisions = tuple(_decision_at_moscow_close(item) for item in calendar_days)
    full_set = set(full_decisions)
    if not set(oos_decisions).issubset(full_set):
        raise ValueError("OOS prediction calendar ne podmnozhestvo factual active-map calendar")
    prior_by_decision = {
        decision: full_decisions[index - 1]
        for index, decision in enumerate(full_decisions)
        if index > 0
    }
    session_contracts: list[CausalSessionContractObservation] = []
    for row in frame.itertuples(index=False):
        if pd.isna(row.effective_date):
            continue
        decision_at = _decision_at_moscow_close(row.effective_date)
        previous = prior_by_decision.get(decision_at)
        if previous is None:
            continue
        expected_previous_day = previous.astimezone(ZoneInfo("Europe/Moscow")).date()
        usable = (
            pd.notna(row.feature_input_valid)
            and bool(row.feature_input_valid)
            and pd.notna(row.contract_id)
            and pd.notna(row.forward_additive_adjustment)
            and row.decision_date == expected_previous_day
            and row.observed_through == expected_previous_day
        )
        if not usable:
            continue
        asset = str(row.asset_id)
        observation_payload = {
            "effective_date": row.effective_date,
            "decision_date": row.decision_date,
            "observed_through": row.observed_through,
            "asset": asset,
            "contract_id": str(row.contract_id),
            "forward_additive_adjustment": float(row.forward_additive_adjustment),
        }
        session_contracts.append(
            CausalSessionContractObservation(
                decision_at=decision_at,
                previous_decision_at=previous,
                asset_id=asset,
                contract_id=str(row.contract_id),
                forward_additive_adjustment=float(row.forward_additive_adjustment),
                known_at=previous,
                source_id="sealed-active-contract-map-effective-row",
                observation_id=_canonical_sha256(observation_payload),
                source_sha256=source_sha256,
            )
        )
    oos_set = set(oos_decisions)
    planned: list[PlannedContractObservation] = []
    planned_rows = frame[frame["decision_date"].notna()].copy()
    if planned_rows.duplicated(["decision_date", "asset_id"]).any():
        raise ValueError("active map duplicate planned decision_date/asset")
    for row in planned_rows.itertuples(index=False):
        decision_at = _decision_at_moscow_close(row.decision_date)
        if decision_at not in oos_set:
            continue
        usable = (
            pd.notna(row.plan_tradable)
            and bool(row.plan_tradable)
            and pd.notna(row.execution_open_available)
            and bool(row.execution_open_available)
            and pd.notna(row.contract_id)
            and pd.notna(row.secid)
            and row.observed_through == row.decision_date
        )
        if not usable:
            continue
        asset = str(row.asset_id)
        payload = {
            "decision_date": row.decision_date,
            "effective_date": row.effective_date,
            "asset": asset,
            "contract_id": str(row.contract_id),
            "secid": str(row.secid),
            "plan_tradable": True,
            "execution_open_available": True,
        }
        planned.append(
            PlannedContractObservation(
                decision_at=decision_at,
                asset_id=asset,
                contract_id=str(row.contract_id),
                contract_code=str(row.secid),
                known_at=decision_at,
                source_id="sealed-active-contract-map-entry-plan",
                observation_id=_canonical_sha256(payload),
                source_sha256=source_sha256,
            )
        )
    return full_decisions, tuple(session_contracts), tuple(planned), frame, columns


def _load_selected_raw_bars(
    parquet_records: Sequence[tuple[Path, str]],
    full_decisions: Sequence[datetime],
    session_contracts: Sequence[CausalSessionContractObservation],
) -> tuple[tuple[MainSessionBarObservation, ...], tuple[str, ...]]:
    """Chitaet raw segmenty po whitelist i ostavlyaet tol'ko D-active contract."""
    columns = (
        "timestamp",
        "end_timestamp",
        "asset_code",
        "canonical_contract_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )
    decision_values = np.asarray(
        [pd.Timestamp(item).value for item in full_decisions], dtype=np.int64
    )
    contract_by_key = {(item.decision_at, item.asset_id): item for item in session_contracts}
    selected: list[MainSessionBarObservation] = []
    for path, source_sha in parquet_records:
        frame = _read_whitelisted_parquet(path, columns, source_name="raw_10m_segment")
        starts = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        raw_ends = pd.to_datetime(frame["end_timestamp"], errors="coerce", utc=True)
        closes = starts + pd.Timedelta(minutes=10)
        if starts.isna().any() or raw_ends.isna().any():
            raise ValueError("raw 10m selected columns soderzhat NaT")
        indices = np.searchsorted(decision_values, closes.astype("int64"), side="left")
        within = indices < len(full_decisions)
        if not within.any():
            continue
        candidate = frame.loc[within].copy()
        candidate["bar_open_at"] = starts.loc[within]
        candidate["raw_end_at"] = raw_ends.loc[within]
        candidate["decision_index"] = indices[within]
        for row in candidate.itertuples(index=False):
            decision_at = full_decisions[int(row.decision_index)]
            asset = _asset_id(row.asset_code)
            contract = contract_by_key.get((decision_at, asset))
            if contract is None or str(row.canonical_contract_id) != contract.contract_id:
                continue
            opened = pd.Timestamp(row.bar_open_at).to_pydatetime()
            closed = opened + timedelta(minutes=10)
            if not contract.previous_decision_at < closed <= contract.decision_at:
                continue
            numeric = tuple(
                float(getattr(row, name)) for name in ("open", "high", "low", "close", "volume")
            )
            if not all(isfinite(value) for value in numeric):
                raise ValueError("active raw 10m bar imeet non-finite OHLCV")
            observation_id = _canonical_sha256(
                {
                    "segment_sha256": source_sha,
                    "timestamp": opened,
                    "raw_end_at": pd.Timestamp(row.raw_end_at).to_pydatetime(),
                    "contract_id": contract.contract_id,
                }
            )
            selected.append(
                MainSessionBarObservation(
                    decision_at=decision_at,
                    asset_id=asset,
                    contract_id=contract.contract_id,
                    bar_open_at=opened,
                    bar_close_at=closed,
                    raw_end_at=pd.Timestamp(row.raw_end_at).to_pydatetime(),
                    open=numeric[0],
                    high=numeric[1],
                    low=numeric[2],
                    close=numeric[3],
                    volume=numeric[4],
                    source_id=path.relative_to(
                        DEFAULT_CONTEXT_PROTOCOL_PATH.resolve().parents[1]
                    ).as_posix(),
                    observation_id=observation_id,
                    source_sha256=source_sha,
                )
            )
    return tuple(selected), columns


def _load_final_daily_panel_qa(
    path: Path,
    source_sha256: str,
    decisions: Sequence[datetime],
) -> tuple[tuple[AdjustedDailyObservation, ...], tuple[str, ...]]:
    """Chitaet final panel tol'ko posle raw build dlya non-causal QA reporta."""
    columns = (
        "trade_date",
        "asset_code",
        "active_contract_id",
        "active_chain_id",
        "active_contract_valid",
        "open",
        "high",
        "low",
        "close",
    )
    frame = _read_whitelisted_parquet(path, columns, source_name="final_daily_panel_qa")
    frame["decision_at"] = frame["trade_date"].map(_decision_at_moscow_close)
    frame["asset_id"] = frame["asset_code"].map(_asset_id)
    allowed = set(decisions)
    frame = frame[frame["decision_at"].isin(allowed)]
    if frame.duplicated(["decision_at", "asset_id"]).any():
        raise ValueError("final daily QA panel duplicate decision/asset")
    observations: list[AdjustedDailyObservation] = []
    for row in frame.itertuples(index=False):
        numeric = tuple(float(getattr(row, name)) for name in ("open", "high", "low", "close"))
        if (
            pd.isna(row.active_contract_valid)
            or not bool(row.active_contract_valid)
            or pd.isna(row.active_contract_id)
            or pd.isna(row.active_chain_id)
            or not all(isfinite(value) for value in numeric)
        ):
            continue
        observations.append(
            AdjustedDailyObservation(
                decision_at=row.decision_at,
                asset_id=str(row.asset_id),
                active_chain_id=str(row.active_chain_id),
                active_contract_id=str(row.active_contract_id),
                open=numeric[0],
                high=numeric[1],
                low=numeric[2],
                close=numeric[3],
                source_id="final-daily-panel-qa-only",
                observation_id=_canonical_sha256(
                    {
                        "trade_date": row.trade_date,
                        "asset": row.asset_id,
                        "contract": row.active_contract_id,
                    }
                ),
                source_sha256=source_sha256,
            )
        )
    return tuple(observations), columns


def _optional_finite(value: object) -> float | None:
    """Vozvrashchaet finite float ili explicit None bez imputation."""
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _load_model_signals(
    base_path: Path,
    regime_path: Path,
    decisions: Sequence[datetime],
) -> tuple[tuple[ModelSignalObservation, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """Join'it exact base/V2 target-free outputs i original validity mask."""
    base_columns = (
        "decision_at",
        "asset",
        "asset_valid",
        "factor_score",
        "residual_location",
        "residual_scale",
        "residual_decision_score",
        "model_id",
    )
    regime_columns = (
        "decision_at",
        "asset",
        "asset_valid",
        "model_id",
        "regime_probability_normal",
        "regime_probability_trend",
        "regime_probability_crash",
        "residual_abstain_probability",
    )
    base = _read_whitelisted_parquet(base_path, base_columns, source_name="base_predictions")
    regime = _read_whitelisted_parquet(
        regime_path, regime_columns, source_name="regime_enrichment_v2"
    )
    for frame in (base, regime):
        frame["decision_at"] = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
        frame["asset"] = frame["asset"].map(_asset_id)
        if frame.duplicated(["decision_at", "asset"]).any():
            raise ValueError("model source duplicate decision/asset")
    expected_keys = {
        (pd.Timestamp(decision), asset) for decision in decisions for asset in V8_ASSET_IDS
    }
    if (
        set(zip(base["decision_at"], base["asset"], strict=True)) != expected_keys
        or set(zip(regime["decision_at"], regime["asset"], strict=True)) != expected_keys
    ):
        raise ValueError("base/V2 ne imeyut exact 1269x4 calendar")
    joined = base.merge(
        regime,
        on=["decision_at", "asset"],
        how="inner",
        validate="one_to_one",
        suffixes=("_base", "_regime"),
    )
    if not (
        joined["asset_valid_base"].fillna(False).astype(bool)
        == joined["asset_valid_regime"].fillna(False).astype(bool)
    ).all():
        raise ValueError("base/V2 original asset_valid identity mismatch")
    if not (joined["model_id_base"].astype(str) == joined["model_id_regime"].astype(str)).all():
        raise ValueError("base/V2 model identity mismatch")
    signals: list[ModelSignalObservation] = []
    model_source_sha = _canonical_sha256(
        {
            "base_predictions_sha256": BASE_PREDICTIONS_SHA256,
            "regime_enrichment_sha256": REGIME_ENRICHMENT_SHA256,
        }
    )
    numeric_names = (
        "factor_score",
        "residual_decision_score",
        "residual_location",
        "residual_scale",
        "residual_abstain_probability",
        "regime_probability_normal",
        "regime_probability_trend",
        "regime_probability_crash",
    )
    for row in joined.sort_values(["decision_at", "asset"], kind="stable").itertuples(index=False):
        values = {name: _optional_finite(getattr(row, name)) for name in numeric_names}
        valid = bool(row.asset_valid_base) and all(
            values[name] is not None for name in numeric_names
        )
        probabilities = tuple(
            values[name]
            for name in (
                "regime_probability_normal",
                "regime_probability_trend",
                "regime_probability_crash",
            )
        )
        if valid and (
            abs(sum(float(value) for value in probabilities) - 1.0) > 1e-6
            or any(not 0.0 <= float(value) <= 1.0 for value in probabilities)
            or float(values["residual_scale"]) <= 0.0
        ):
            valid = False
        if not valid:
            values = {name: None for name in numeric_names}
        decision_at = pd.Timestamp(row.decision_at).to_pydatetime()
        signals.append(
            ModelSignalObservation(
                decision_at=decision_at,
                asset_id=str(row.asset),
                known_at=decision_at,
                model_input_valid=valid,
                factor_decision_score=values["factor_score"],
                residual_decision_score=values["residual_decision_score"],
                residual_location=values["residual_location"],
                total_scale=values["residual_scale"],
                abstain_probability=values["residual_abstain_probability"],
                normal_probability=values["regime_probability_normal"],
                trend_probability=values["regime_probability_trend"],
                crash_probability=values["regime_probability_crash"],
                source_sha256=model_source_sha,
            )
        )
    return tuple(signals), (
        ("base_predictions", base_columns),
        ("regime_enrichment", regime_columns),
    )


def _assembly_carry_observations(
    assembly_path: Path,
    source_sha256: str,
) -> tuple[
    list[RawPitObservation],
    dict[tuple[datetime, str], float],
    dict[tuple[datetime, str], float],
]:
    """Chitaet tol'ko decision_times/daily_context/daily_valid i izvlekaet carry index4."""
    with np.load(assembly_path, allow_pickle=False) as archive:
        decision_raw = np.asarray(archive["decision_times"])
        daily = np.asarray(archive["daily_context"], dtype=np.float64)
        valid = np.asarray(archive["daily_valid"], dtype=bool)
    decision_ns = decision_raw.astype("datetime64[ns]")
    if np.isnat(decision_ns).any() or decision_ns.max() >= np.datetime64("2026-01-01", "ns"):
        raise ValueError("assembly causal whitelist dostig protected 2026")
    expected_shape = (len(decision_ns), len(V8_ASSET_IDS), 16)
    if daily.shape != expected_shape or valid.shape != expected_shape:
        raise ValueError("assembly daily_context/daily_valid shape drift")
    rows: list[RawPitObservation] = []
    carry_by_key: dict[tuple[datetime, str], float] = {}
    cftc_by_key: dict[tuple[datetime, str], float] = {}
    for index, raw_decision in enumerate(decision_ns):
        decision_at = pd.Timestamp(raw_decision).tz_localize("UTC").to_pydatetime()
        for asset_index, asset in enumerate(V8_ASSET_IDS):
            value = float(daily[index, asset_index, 4])
            if not valid[index, asset_index, 4] or not isfinite(value):
                continue
            carry_by_key[(decision_at, asset)] = value
            cftc_value = float(daily[index, asset_index, 14])
            if valid[index, asset_index, 14] and isfinite(cftc_value):
                cftc_by_key[(decision_at, asset)] = cftc_value
            rows.append(
                RawPitObservation(
                    decision_at=decision_at,
                    asset_id=asset,
                    channel="carry_z",
                    raw_value=value,
                    published_at=decision_at,
                    available_at=decision_at,
                    source_id="sealed-v8-assembly-roll-yield-index-4",
                    observation_id=f"carry:{asset}:{decision_at.isoformat()}",
                    source_sha256=source_sha256,
                )
            )
    return rows, carry_by_key, cftc_by_key


def _cftc_observations(
    cftc_path: Path,
    source_sha256: str,
    decisions: Sequence[datetime],
    assembly_cftc: Mapping[tuple[datetime, str], float],
) -> tuple[list[RawPitObservation], tuple[str, ...]]:
    """Rebuildit official CFTC router i composite unique-release provenance."""
    columns = (
        "report_date",
        "report_kind",
        "market_id",
        "economic_channel",
        "contract_code",
        "market_name",
        "category",
        "open_interest",
        "long_positions",
        "short_positions",
        "source_url",
        "archive_sha256",
        "csv_sha256",
        "revision_id",
        "radar_version",
        "net_positions",
        "net_share_oi",
        "net_share_oi_change",
    )
    history = _read_whitelisted_parquet(cftc_path, columns, source_name="cftc_pit")
    decision_index = pd.DatetimeIndex(decisions)
    features = build_causal_cftc_features(
        history,
        decision_index,
        release_overrides=official_development_release_overrides(),
    )
    scores = build_causal_cftc_asset_scores(features)
    available_columns = [f"{channel}_available_at" for channel in CFTC_CHANNEL_COMPONENTS]
    scores["available_at"] = scores[available_columns].max(axis=1)
    rows: list[RawPitObservation] = []
    max_assembly_difference = 0.0
    compared = 0
    for row in scores.itertuples(index=False):
        score = _optional_finite(row.score)
        available = pd.to_datetime(row.available_at, errors="coerce", utc=True)
        if score is None or pd.isna(available):
            continue
        decision_at = pd.Timestamp(row.decision_at).to_pydatetime()
        asset = _asset_id(row.asset_symbol)
        required_channels = tuple(str(row.required_channels).split(","))
        provenance: list[dict[str, object]] = []
        usable = True
        for channel in required_channels:
            report_date = getattr(row, f"{channel}_report_date")
            channel_available = pd.to_datetime(
                getattr(row, f"{channel}_available_at"), errors="coerce", utc=True
            )
            if pd.isna(report_date) or pd.isna(channel_available):
                usable = False
                break
            provenance.append(
                {
                    "channel": channel,
                    "report_date": pd.Timestamp(report_date).date(),
                    "available_at": pd.Timestamp(channel_available).to_pydatetime(),
                }
            )
        if not usable:
            continue
        assembly_value = assembly_cftc.get((decision_at, asset))
        if assembly_value is not None:
            max_assembly_difference = max(max_assembly_difference, abs(score - assembly_value))
            compared += 1
        observation_id = _canonical_sha256({"asset": asset, "composite_release": provenance})
        available_at = pd.Timestamp(available).to_pydatetime()
        rows.append(
            RawPitObservation(
                decision_at=decision_at,
                asset_id=asset,
                channel="cftc_crowd_z",
                raw_value=score,
                published_at=available_at,
                available_at=available_at,
                source_id="official-cftc-composite-router-v1",
                observation_id=observation_id,
                source_sha256=source_sha256,
            )
        )
    if compared == 0 or max_assembly_difference > 1e-6:
        raise ValueError("rebuilt CFTC primary score ne sovpadaet s sealed assembly causal context")
    return rows, columns


def _latest_release_snapshots(
    releases: Sequence[dict[str, object]],
    decisions: Sequence[datetime],
    *,
    channel: str,
    source_sha256: str,
) -> list[RawPitObservation]:
    """Razvorachivaet unique releases v latest-as-of-D snapshots bez stale weighting."""
    ordered = sorted(releases, key=lambda item: item["available_at"])
    available_ns = np.asarray(
        [pd.Timestamp(item["available_at"]).value for item in ordered], dtype=np.int64
    )
    output: list[RawPitObservation] = []
    for decision_at in decisions:
        index = (
            int(np.searchsorted(available_ns, pd.Timestamp(decision_at).value, side="right")) - 1
        )
        if index < 0:
            continue
        release = ordered[index]
        available_at = pd.Timestamp(release["available_at"]).to_pydatetime()
        output.append(
            RawPitObservation(
                decision_at=decision_at,
                asset_id=None,
                channel=channel,
                raw_value=float(release["raw_value"]),
                published_at=available_at,
                available_at=available_at,
                source_id=str(release["source_id"]),
                observation_id=str(release["observation_id"]),
                source_sha256=source_sha256,
            )
        )
    return output


def _cbr_observations(
    cbr_path: Path,
    source_sha256: str,
    decisions: Sequence[datetime],
) -> tuple[list[RawPitObservation], int, tuple[str, ...]]:
    """Stroit unique FX returns i consecutive key-rate changes s exact min60 sleep."""
    columns = (
        "source",
        "series_id",
        "observation_date",
        "effective_date",
        "publication_date",
        "available_at",
        "value",
        "status",
        "availability_rule",
    )
    frame = _read_whitelisted_parquet(cbr_path, columns, source_name="cbr_pit")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce", utc=True)
    if (
        frame["available_at"].isna().any()
        or (frame["available_at"] >= pd.Timestamp("2026-01-01", tz="UTC")).any()
    ):
        raise ValueError("CBR availability invalid ili dostigaet protected 2026")
    releases: list[dict[str, object]] = []
    fx = frame[frame["series_id"].astype(str) == "usd_rub_official"].sort_values(
        "available_at", kind="stable"
    )
    previous_fx: float | None = None
    for row in fx.itertuples(index=False):
        value = float(row.value)
        if previous_fx is not None and value > 0.0 and previous_fx > 0.0:
            releases.append(
                {
                    "available_at": row.available_at,
                    "raw_value": log(value) - log(previous_fx),
                    "source_id": "cbr-usd-rub-official-return-1",
                    "observation_id": _canonical_sha256(
                        {
                            "series": "usd_rub_official",
                            "observation_date": row.observation_date,
                            "available_at": row.available_at,
                        }
                    ),
                }
            )
        previous_fx = value
    key_releases: list[dict[str, object]] = []
    rates = frame[frame["series_id"].astype(str) == "key_rate"].sort_values(
        "available_at", kind="stable"
    )
    previous_rate: float | None = None
    for row in rates.itertuples(index=False):
        value = float(row.value)
        if previous_rate is not None and value != previous_rate:
            key_releases.append(
                {
                    "available_at": row.available_at,
                    "raw_value": value - previous_rate,
                    "source_id": "cbr-key-rate-consecutive-level-change",
                    "observation_id": _canonical_sha256(
                        {
                            "series": "key_rate",
                            "effective_date": row.effective_date,
                            "available_at": row.available_at,
                            "previous_level": previous_rate,
                            "current_level": value,
                        }
                    ),
                }
            )
        previous_rate = value
    if len(key_releases) != 41:
        raise ValueError(f"sealed key-rate unique finite changes drift: {len(key_releases)} != 41")
    observations = _latest_release_snapshots(
        releases,
        decisions,
        channel="usd_rub_return_z",
        source_sha256=source_sha256,
    )
    observations.extend(
        _latest_release_snapshots(
            key_releases,
            decisions,
            channel="key_rate_change_z",
            source_sha256=source_sha256,
        )
    )
    return observations, len(key_releases), columns


def build_real_context_source(
    output_dir: Path,
) -> RealContextBuildResult:
    """Stroit real 1269x4 target-free context iz verified 2018-25 causal sources."""
    protocol = load_context_protocol()
    proofs = build_real_dependency_proofs(protocol)
    verified = verify_context_dependency_proofs(proofs, protocol)
    proof_by_name = {item.name: item for item in verified.proofs}
    resolved = {
        name: _resolve_project_file(item.relative_path, f"{name} verified path")
        for name, item in proof_by_name.items()
    }

    base_probe = _read_whitelisted_parquet(
        resolved["base_predictions"],
        ("decision_at", "asset"),
        source_name="base_calendar_probe",
    )
    base_probe["decision_at"] = pd.to_datetime(base_probe["decision_at"], errors="raise", utc=True)
    if len(base_probe) != 5_076 or base_probe.duplicated(["decision_at", "asset"]).any():
        raise ValueError("base prediction source ne exact 5076 unique rows")
    oos_decisions = tuple(
        item.to_pydatetime() for item in sorted(base_probe["decision_at"].drop_duplicates())
    )
    if len(oos_decisions) != 1_269 or any(
        item.date() >= PROTECTED_HOLDOUT_START for item in oos_decisions
    ):
        raise ValueError("base OOS calendar ne exact 1269 pre-2026 decisions")

    (
        full_decisions,
        session_contracts,
        planned_contracts,
        _active_frame,
        active_columns,
    ) = _load_active_contract_sources(
        resolved["active_contract_map"],
        proof_by_name["active_contract_map"].sha256,
        oos_decisions,
    )
    raw_records = _verified_raw_parquet_records(
        resolved["main_session_10m"],
        verified.main_session_tree,
    )
    raw_bars, raw_columns = _load_selected_raw_bars(
        raw_records,
        full_decisions,
        session_contracts,
    )
    raw_market = build_market_feature_snapshots(
        full_decisions,
        session_contracts,
        raw_bars,
        raw_10m_source_sha256=proof_by_name["main_session_10m"].sha256,
    )
    qa_observations, qa_columns = _load_final_daily_panel_qa(
        resolved["adjusted_daily_chain"],
        proof_by_name["adjusted_daily_chain"].sha256,
        full_decisions,
    )
    oos_set = set(oos_decisions)
    oos_raw_market = {
        key: value for key, value in raw_market.items() if key[0] in oos_set
    }
    oos_market, qa_audit = reconcile_final_daily_panel_qa(
        oos_raw_market,
        qa_observations,
    )
    if len(oos_market) != 5_076:
        raise ValueError("raw market builder ne vernul exact 1269x4 OOS rows")

    model_signals, model_column_audit = _load_model_signals(
        resolved["base_predictions"],
        resolved["regime_enrichment"],
        oos_decisions,
    )
    carry_rows, _carry_values, assembly_cftc = _assembly_carry_observations(
        resolved["v8_assembly"],
        proof_by_name["v8_assembly"].sha256,
    )
    cftc_rows, cftc_columns = _cftc_observations(
        resolved["cftc_pit"],
        proof_by_name["cftc_pit"].sha256,
        full_decisions,
        assembly_cftc,
    )
    cbr_rows, key_rate_changes, cbr_columns = _cbr_observations(
        resolved["cbr_key_rate_pit"],
        proof_by_name["cbr_key_rate_pit"].sha256,
        full_decisions,
    )
    standardized = build_expanding_pit_standardization((*carry_rows, *cftc_rows, *cbr_rows))
    oos_pit = {key: value for key, value in standardized.items() if key[0] in oos_set}
    pit_audits = tuple(
        audit_pit_standardization(
            standardized,
            channel=channel,
            decisions=oos_decisions,
        )
        for channel in (
            "carry_z",
            "cftc_crowd_z",
            "key_rate_change_z",
            "usd_rub_return_z",
        )
    )
    key_audit = next(item for item in pit_audits if item.channel == "key_rate_change_z")
    if (
        key_rate_changes != 41
        or key_audit.snapshot_rows != len(oos_decisions)
        or key_audit.standardized_rows != 0
        or key_audit.sleeping_rows != len(oos_decisions)
    ):
        raise ValueError("key-rate min60 sleeping audit ne sootvetstvuet seal")

    contexts = build_validity_aware_contexts(
        oos_decisions,
        model_signals,
        oos_market,
        oos_pit,
        planned_contracts,
        prediction_sha256=BASE_PREDICTIONS_SHA256,
    )
    frame = context_records_frame(contexts)
    if (
        len(frame) != 5_076
        or frame["decision_at"].nunique() != 1_269
        or frame.duplicated(["decision_at", "asset"]).any()
        or any(
            token in column.lower()
            for column in frame.columns
            for token in FORBIDDEN_CONTEXT_TOKENS
        )
    ):
        raise ValueError("real context frame ne proshel exact target-free 5076-row audit")
    source_columns = (
        ("base_calendar_probe", ("decision_at", "asset")),
        ("active_contract_map", active_columns),
        ("raw_10m_segments", raw_columns),
        ("final_daily_panel_qa_only", qa_columns),
        *model_column_audit,
        ("v8_assembly", ("decision_times", "daily_context", "daily_valid")),
        ("cftc_pit", cftc_columns),
        ("cbr_pit", cbr_columns),
    )
    audit = RealContextBuildAudit(
        full_calendar_decisions=len(full_decisions),
        oos_decisions=len(oos_decisions),
        context_rows=len(frame),
        selected_raw_10m_bars=len(raw_bars),
        model_input_valid_rows=int(frame["model_input_valid"].sum()),
        decision_market_valid_rows=int(frame["decision_market_valid"].sum()),
        planned_contract_valid_rows=int(frame["planned_contract_valid"].sum()),
        strategy_eligible_rows=int(frame["strategy_eligible"].sum()),
        evaluation_exit_observable_rows=int(frame["evaluation_exit_observable"].sum()),
        final_daily_panel_qa=qa_audit,
        pit_channels=pit_audits,
        key_rate_unique_finite_changes=key_rate_changes,
        source_columns_read=source_columns,
        protected_holdout_accessed=False,
    )
    artifacts = persist_context_source(
        output_dir,
        contexts,
        dependency_proofs=proofs,
        real_build_audit=audit,
        verified_dependencies=verified,
    )
    return RealContextBuildResult(artifacts=artifacts, audit=audit)


def _cli_parser() -> argparse.ArgumentParser:
    """Stroit uzkii target-free context CLI bez evaluation/PnL komand."""
    parser = argparse.ArgumentParser(prog="python -m market_lab.futures_v8.context_run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-real")
    build.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/v8_20260818T111317Z_83135473_context_raw10m_v2"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Zapuskaet tol'ko verified real target-free context build i pechataet paths."""
    arguments = _cli_parser().parse_args(argv)
    if arguments.command != "build-real":
        raise RuntimeError("neizvestnaya context command")
    result = build_real_context_source(arguments.output_dir)
    print(
        json.dumps(
            {
                "parquet": str(result.artifacts.parquet_path),
                "manifest": str(result.artifacts.manifest_path),
                "rows": result.audit.context_rows,
                "model_input_valid": result.audit.model_input_valid_rows,
                "decision_market_valid": result.audit.decision_market_valid_rows,
                "planned_contract_valid": result.audit.planned_contract_valid_rows,
                "strategy_eligible": result.audit.strategy_eligible_rows,
                "evaluation_exit_observable": (result.audit.evaluation_exit_observable_rows),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "CONTEXT_SOURCE_SCHEMA",
    "DEFAULT_CONTEXT_PROTOCOL_PATH",
    "DEFAULT_CONTEXT_PROTOCOL_SHA256",
    "EXPANDING_Z_CLIP",
    "EXPANDING_Z_MINIMUM_HISTORY",
    "NOMINAL_SPAN_RULE",
    "BuiltAssetContext",
    "BuiltDecisionContext",
    "ContextArtifactPaths",
    "ContextDependencyProof",
    "EvaluationContextProtocol",
    "AdjustedDailyObservation",
    "CausalSessionContractObservation",
    "FinalDailyPanelQaAudit",
    "MainSessionBarObservation",
    "MainSessionManifestTreeProof",
    "MarketFeatureSnapshot",
    "ModelSignalObservation",
    "NominalContractAssessment",
    "PlannedContractObservation",
    "RawPitObservation",
    "RealContextBuildAudit",
    "RealContextBuildResult",
    "StandardizedPitObservation",
    "PitStandardizationAudit",
    "VerifiedContextDependencies",
    "assess_planned_contract",
    "audit_pit_standardization",
    "build_expanding_pit_standardization",
    "build_market_feature_snapshots",
    "build_real_context_source",
    "build_real_dependency_proofs",
    "build_validity_aware_contexts",
    "context_records_frame",
    "derive_nominal_maturity_date",
    "load_context_protocol",
    "main",
    "persist_context_source",
    "reconcile_final_daily_panel_qa",
    "verify_context_dependency_proofs",
    "verify_main_session_manifest_tree",
]


if __name__ == "__main__":
    raise SystemExit(main())
