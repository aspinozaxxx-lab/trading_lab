"""Fail-closed admission-v2 foundation for authoritative futures-v8 evaluation.

The trust anchor is code-pinned and the public verifier accepts no certificate path or
digest override.  Its digest is intentionally a placeholder until an independent audit
releases one exact certificate.

The producer code identity deliberately excludes this admission module and the pinned
certificate.  Otherwise embedding the certificate byte digest here while the certificate
also binds the producer digest would create a self-hash cycle.  The admission verifier is
instead covered by the installed evaluator release and its code-pinned trust anchor; source
producer identities cover only the code which produced the sealed source artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

V8_ADMISSION_CERTIFICATE_FORMAT: Final[str] = "market-lab-futures-v8-authoritative-admission-v2"
V8_NORMALIZED_SOURCE_FORMAT: Final[str] = "market-lab-futures-v8-evaluation-source-v2"
V8_ADMISSION_CERTIFICATE_PATH: Final[str] = "configs/futures_v8_authoritative_admission_v2.json"
V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER: Final[str] = "0" * 64
V8_AUTHORITATIVE_ADMISSION_STATUS: Final[str] = "authoritative_admitted"
V8_INDEPENDENT_AUDIT_STATUS: Final[str] = "independently_admitted"
V8_PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)
V8_INITIAL_CAPITAL_RUB: Final[float] = 1_000_000.0
V8_DECISION_ROW_COUNT: Final[int] = 1_269
V8_PANEL_ROW_COUNT: Final[int] = 5_076
V8_CHECKPOINT_COUNT: Final[int] = 15
V8_ASSET_IDS: Final[tuple[str, ...]] = ("BR", "MIX", "RI", "SI")
V8_PANEL_KEY_COLUMNS: Final[tuple[str, ...]] = ("decision_at", "asset")
V8_VALIDITY_MASK_COLUMNS: Final[tuple[str, ...]] = (
    "model_input_valid",
    "decision_market_valid",
    "planned_contract_valid",
    "strategy_eligible",
)
V8_STRATEGY_ELIGIBILITY_FORMULA: Final[str] = (
    "model_input_valid&decision_market_valid&planned_contract_valid"
)
V8_INVALID_ROW_POLICY: Final[str] = "cash_exclude_before_cross_section_no_imputation"
V8_STRATEGY_IDS: Final[tuple[str, ...]] = (
    "core_v8_factor_residual",
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
V8_SCENARIO_IDS: Final[tuple[str, ...]] = ("primary", "double_cost", "delay")
V8_LEDGER_COUNT: Final[int] = len(V8_STRATEGY_IDS) * len(V8_SCENARIO_IDS)
V8_MAX_CONTROL_BYTES: Final[int] = 1_048_576

# These two paths cannot participate in a producer identity which is embedded in the
# certificate whose digest is itself pinned in this module.
V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS: Final[tuple[str, ...]] = (
    "src/market_lab/futures_v8/admission.py",
    V8_ADMISSION_CERTIFICATE_PATH,
)


class V8SourceKind(StrEnum):
    """Seven normalized target-free source kinds admitted by evaluator v2."""

    CHECKPOINT_IDENTITIES = "checkpoint_identities"
    BASE_PREDICTIONS = "base_predictions"
    REGIME_V2 = "regime_v2"
    CALENDAR = "calendar"
    SPEC_PROXY = "spec_proxy"
    MOEX_10M = "moex_10m"
    FULL_CONTEXT = "full_context"


V8_REQUIRED_SOURCE_KINDS: Final[tuple[V8SourceKind, ...]] = tuple(V8SourceKind)
V8_REQUIRED_SOURCE_DEPENDENCIES: Final[Mapping[V8SourceKind, tuple[V8SourceKind, ...]]] = (
    MappingProxyType(
        {
            V8SourceKind.CHECKPOINT_IDENTITIES: (),
            V8SourceKind.BASE_PREDICTIONS: (V8SourceKind.CHECKPOINT_IDENTITIES,),
            V8SourceKind.REGIME_V2: (
                V8SourceKind.BASE_PREDICTIONS,
                V8SourceKind.CHECKPOINT_IDENTITIES,
            ),
            V8SourceKind.CALENDAR: (V8SourceKind.BASE_PREDICTIONS,),
            V8SourceKind.SPEC_PROXY: (V8SourceKind.CALENDAR,),
            V8SourceKind.MOEX_10M: (V8SourceKind.CALENDAR,),
            V8SourceKind.FULL_CONTEXT: (
                V8SourceKind.BASE_PREDICTIONS,
                V8SourceKind.REGIME_V2,
                V8SourceKind.CALENDAR,
                V8SourceKind.SPEC_PROXY,
                V8SourceKind.MOEX_10M,
            ),
        }
    )
)

V8_CHECKPOINT_IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "checkpoint_bytes",
    "checkpoint_path",
    "checkpoint_sha256",
    "fold_name",
    "manifest_sha256",
    "resumed",
    "seed",
    "sidecar_bytes",
    "sidecar_path",
    "sidecar_sha256",
)
V8_BASE_PREDICTION_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
    "asset_valid",
    "factor_location",
    "factor_scale",
    "factor_score",
    "residual_location",
    "residual_scale",
    "residual_decision_score",
    "direction_logit",
    "model_id",
)
V8_REGIME_V2_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
    "asset_valid",
    "model_id",
    "fold_name",
    "seed_count",
    "seed_set_sha256",
    "regime_probability_normal",
    "regime_probability_trend",
    "regime_probability_crash",
    "factor_abstain_probability",
    "residual_abstain_probability",
)
V8_CALENDAR_COLUMNS: Final[tuple[str, ...]] = (
    "sequence_id",
    "decision_session_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "evaluation_exit_observable",
    "evaluation_exit_decision_at",
    "evaluation_exit_provenance_sha256",
)
V8_SPEC_PROXY_COLUMNS: Final[tuple[str, ...]] = (
    "session_date",
    "asset",
    "contract_id",
    "realized_accounting_point_value",
    "realized_accounting_status",
    "realized_available_after_session",
    "sizing_observed_session_date",
    "sizing_point_value",
    "modeled_initial_margin",
    "conservative_fee_per_side",
    "sizing_lag_sessions",
    "sizing_status",
    "sizing_usable",
    "spec_proxy_version",
    "approximate",
    "research_only",
    "historical_exchange_exact",
    "broker_exact",
)
V8_MOEX_10M_COLUMNS: Final[tuple[str, ...]] = (
    "contract_id",
    "opened_at",
    "closed_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
_V8_PIT_CHANNELS: Final[tuple[str, ...]] = (
    "carry_z",
    "cftc_crowd_z",
    "key_rate_change_z",
    "usd_rub_return_z",
)
_V8_PIT_SUFFIXES: Final[tuple[str, ...]] = (
    "raw_value",
    "value",
    "unclipped_z",
    "history_count",
    "published_at",
    "available_at",
    "source_id",
    "observation_id",
    "source_sha256",
    "freshness_seconds",
    "reason_code",
)
V8_FULL_CONTEXT_COLUMNS: Final[tuple[str, ...]] = (
    "decision_at",
    "asset",
    "known_at",
    *V8_VALIDITY_MASK_COLUMNS,
    "evaluation_exit_observable",
    "evaluation_exit_decision_at",
    "evaluation_exit_provenance_sha256",
    "invalid_reason_codes",
    "factor_decision_score",
    "residual_decision_score",
    "residual_location",
    "total_scale",
    "abstain_probability",
    "normal_probability",
    "trend_probability",
    "crash_probability",
    "close",
    "adjusted_signal_open",
    "adjusted_signal_high",
    "adjusted_signal_low",
    "adjusted_signal_close",
    "atr_20",
    "daily_volatility_20",
    "momentum_20",
    "range_position_20",
    "volatility_ratio_20",
    "volume_ratio_20",
    "market_data_sha256",
    "market_reason_codes",
    "main_session_bucket_count",
    "main_session_expected_bucket_count",
    "close_bar_open_at",
    "close_bar_scheduled_close_at",
    "close_bar_raw_end_at",
    "main_session_source_sha256s",
    "planned_contract_id",
    "nominal_maturity_date",
    "nominal_span_rule",
    "contract_reason_codes",
    "contract_provenance_sha256",
    "validity_provenance_sha256",
    "input_bundle_sha256",
    "planned_contract_code",
    "planned_contract_known_at",
    "planned_contract_source_id",
    "planned_contract_observation_id",
    "planned_contract_source_sha256",
    *tuple(f"{channel}_{suffix}" for channel in _V8_PIT_CHANNELS for suffix in _V8_PIT_SUFFIXES),
)

V8_EXACT_SOURCE_COLUMNS: Final[Mapping[V8SourceKind, tuple[str, ...]]] = MappingProxyType(
    {
        V8SourceKind.CHECKPOINT_IDENTITIES: V8_CHECKPOINT_IDENTITY_COLUMNS,
        V8SourceKind.BASE_PREDICTIONS: V8_BASE_PREDICTION_COLUMNS,
        V8SourceKind.REGIME_V2: V8_REGIME_V2_COLUMNS,
        V8SourceKind.CALENDAR: V8_CALENDAR_COLUMNS,
        V8SourceKind.SPEC_PROXY: V8_SPEC_PROXY_COLUMNS,
        V8SourceKind.MOEX_10M: V8_MOEX_10M_COLUMNS,
        V8SourceKind.FULL_CONTEXT: V8_FULL_CONTEXT_COLUMNS,
    }
)
V8_EXACT_SOURCE_ROWS: Final[Mapping[V8SourceKind, int]] = MappingProxyType(
    {
        V8SourceKind.CHECKPOINT_IDENTITIES: V8_CHECKPOINT_COUNT,
        V8SourceKind.BASE_PREDICTIONS: V8_PANEL_ROW_COUNT,
        V8SourceKind.REGIME_V2: V8_PANEL_ROW_COUNT,
        V8SourceKind.CALENDAR: V8_DECISION_ROW_COUNT,
        V8SourceKind.FULL_CONTEXT: V8_PANEL_ROW_COUNT,
    }
)

_SOURCE_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "format",
        "kind",
        "artifact",
        "temporal_bounds",
        "dependencies",
        "producer",
        "audit",
        "source_identity_sha256",
    }
)
_ARTIFACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "path",
        "sha256",
        "bytes",
        "rows",
        "columns",
        "decision_calendar_sha256",
        "decision_asset_key_set_sha256",
    }
)
_TEMPORAL_KEYS: Final[frozenset[str]] = frozenset({"minimum_session_date", "maximum_session_date"})
_DEPENDENCY_KEYS: Final[frozenset[str]] = frozenset({"manifest_sha256", "artifact_sha256"})
_PRODUCER_KEYS: Final[frozenset[str]] = frozenset(
    {"code_identity_sha256", "protocol_sha256", "excluded_paths"}
)
_AUDIT_KEYS: Final[frozenset[str]] = frozenset({"status", "certificate_sha256"})
_CERTIFICATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "format",
        "status",
        "protected_holdout_start",
        "initial_capital_rub",
        "calendar_contract",
        "validity_contract",
        "ledger_contract",
        "producer_code_identity",
        "protocol_bundle_sha256",
        "independent_audit_certificate_sha256",
        "sources",
    }
)
_CALENDAR_CONTRACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "decision_rows",
        "panel_rows",
        "assets",
        "key_columns",
        "minimum_decision_date",
        "maximum_decision_date",
        "year_counts",
        "decision_calendar_sha256",
        "decision_asset_key_set_sha256",
    }
)
_VALIDITY_CONTRACT_KEYS: Final[frozenset[str]] = frozenset(
    {"mask_columns", "strategy_eligible_formula", "invalid_row_policy"}
)
_LEDGER_CONTRACT_KEYS: Final[frozenset[str]] = frozenset(
    {"strategy_ids", "scenario_ids", "ledger_count"}
)
_CERTIFICATE_SOURCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "manifest_path",
        "manifest_sha256",
        "artifact_sha256",
        "source_identity_sha256",
    }
)
_PRODUCER_CODE_IDENTITY_KEYS: Final[frozenset[str]] = frozenset({"sha256", "excluded_paths"})
_FORBIDDEN_NAME_FRAGMENTS: Final[tuple[str, ...]] = (
    "target",
    "label",
    "future_return",
    "realized_return",
    "pnl",
    "p&l",
    "profit_loss",
    "assembly",
)
_YEAR_IN_PATH = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


class V8AdmissionError(ValueError):
    """A normalized control contract failed before authoritative evaluation."""


class V8AdmissionBlockedError(RuntimeError):
    """The code-pinned admission release is absent or intentionally blocked."""


@dataclass(frozen=True, slots=True, init=False)
class V8AdmissionTrustAnchor:
    """Non-overridable certificate location and digest compiled into this release."""

    certificate_path: str
    certificate_sha256: str

    def __init__(self) -> None:
        object.__setattr__(self, "certificate_path", V8_ADMISSION_CERTIFICATE_PATH)
        object.__setattr__(
            self,
            "certificate_sha256",
            V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER,
        )

    @property
    def released(self) -> bool:
        """Return false while the explicit all-zero release placeholder remains."""

        return self.certificate_sha256 != V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER


V8_AUTHORITATIVE_ADMISSION_TRUST_ANCHOR: Final[V8AdmissionTrustAnchor] = V8AdmissionTrustAnchor()


@dataclass(frozen=True, slots=True)
class V8SourceDependencySeal:
    """Both identities required to prevent dependency manifest mix-and-match."""

    manifest_sha256: str
    artifact_sha256: str


@dataclass(frozen=True, slots=True)
class V8SourceArtifactSeal:
    """Exact artifact identity declared by one normalized source control."""

    relative_path: str
    sha256: str
    bytes: int
    rows: int
    columns: tuple[str, ...]
    decision_calendar_sha256: str | None
    decision_asset_key_set_sha256: str | None


@dataclass(frozen=True, slots=True)
class V8SourceTemporalBounds:
    """Manifest-only market bounds checked before artifact I/O."""

    minimum_session_date: date
    maximum_session_date: date


@dataclass(frozen=True, slots=True)
class V8SourceProducerSeal:
    """Producer code and protocol identities with explicit cycle exclusions."""

    code_identity_sha256: str
    protocol_sha256: str
    excluded_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V8SourceAuditSeal:
    """Independent pre-admission audit certificate identity."""

    status: str
    certificate_sha256: str


@dataclass(frozen=True, slots=True)
class V8NormalizedSourceManifest:
    """Typed, byte-sealed source wrapper parsed without opening its artifact."""

    kind: V8SourceKind
    artifact: V8SourceArtifactSeal
    temporal_bounds: V8SourceTemporalBounds
    dependencies: tuple[tuple[V8SourceKind, V8SourceDependencySeal], ...]
    producer: V8SourceProducerSeal
    audit: V8SourceAuditSeal
    source_identity_sha256: str

    def dependency(self, kind: V8SourceKind | str) -> V8SourceDependencySeal:
        """Return one exact dependency or fail closed."""

        resolved = V8SourceKind(kind)
        for dependency_kind, seal in self.dependencies:
            if dependency_kind is resolved:
                return seal
        raise KeyError(resolved.value)


@dataclass(frozen=True, slots=True)
class V8AdmissionSourceControl:
    """One certificate-pinned normalized source manifest and artifact identity."""

    kind: V8SourceKind
    manifest_relative_path: str
    manifest_sha256: str
    artifact_sha256: str
    source_identity_sha256: str


@dataclass(frozen=True, slots=True)
class V8AdmissionCalendarContract:
    """Exact 1269-by-4 decision universe and semantic key seals."""

    decision_rows: int
    panel_rows: int
    assets: tuple[str, ...]
    key_columns: tuple[str, ...]
    minimum_decision_date: date
    maximum_decision_date: date
    year_counts: tuple[tuple[int, int], ...]
    decision_calendar_sha256: str
    decision_asset_key_set_sha256: str


@dataclass(frozen=True, slots=True)
class V8AdmissionValidityContract:
    """Independent validity masks and the only allowed eligibility conjunction."""

    mask_columns: tuple[str, ...]
    strategy_eligible_formula: str
    invalid_row_policy: str


@dataclass(frozen=True, slots=True)
class V8AdmissionLedgerContract:
    """Exact isolated strategy-by-scenario matrix."""

    strategy_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    ledger_count: int


@dataclass(frozen=True, slots=True)
class V8AdmissionCertificate:
    """Parsed authoritative control certificate, before artifact verification."""

    status: str
    protected_holdout_start: date
    initial_capital_rub: float
    calendar_contract: V8AdmissionCalendarContract
    validity_contract: V8AdmissionValidityContract
    ledger_contract: V8AdmissionLedgerContract
    producer_code_identity_sha256: str
    producer_code_identity_excluded_paths: tuple[str, ...]
    protocol_bundle_sha256: str
    independent_audit_certificate_sha256: str
    sources: tuple[V8AdmissionSourceControl, ...]

    def source(self, kind: V8SourceKind | str) -> V8AdmissionSourceControl:
        """Return a certificate source control by normalized kind."""

        resolved = V8SourceKind(kind)
        for source in self.sources:
            if source.kind is resolved:
                return source
        raise KeyError(resolved.value)


@dataclass(frozen=True, slots=True)
class V8VerifiedAdmissionSource:
    """Artifact identity verified only after the global phase-zero safety pass."""

    kind: V8SourceKind
    manifest_path: Path
    manifest_sha256: str
    artifact_path: Path
    artifact_sha256: str
    artifact_bytes: int
    rows: int
    source_identity_sha256: str
    manifest: V8NormalizedSourceManifest


@dataclass(frozen=True, slots=True)
class V8VerifiedAdmission:
    """Safe handoff object for the later evaluator integration."""

    project_root: Path
    certificate_path: Path
    certificate_sha256: str
    certificate: V8AdmissionCertificate
    sources: tuple[V8VerifiedAdmissionSource, ...]

    @property
    def initial_capital_rub(self) -> float:
        """Return the sealed economic capital; no runner override exists."""

        return self.certificate.initial_capital_rub

    def source(self, kind: V8SourceKind | str) -> V8VerifiedAdmissionSource:
        """Return one byte-verified source by normalized kind."""

        resolved = V8SourceKind(kind)
        for source in self.sources:
            if source.kind is resolved:
                return source
        raise KeyError(resolved.value)


def _canonical_json_bytes(payload: Any) -> bytes:
    """Serialize identity payloads without BOM or formatting dependence."""

    return json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def compute_v8_normalized_source_identity_sha256(payload: Mapping[str, Any]) -> str:
    """Compute the normalized identity, excluding only its own declared field."""

    identity_payload = dict(payload)
    identity_payload.pop("source_identity_sha256", None)
    return _canonical_sha256(identity_payload)


def _require_exact_keys(payload: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise V8AdmissionError(
            f"{label} keys mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise V8AdmissionError(f"{label} must be an object")
    return value


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise V8AdmissionError(f"{label} must be a list")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise V8AdmissionError(f"{label} must be a nonempty string")
    return value


def _require_int(value: Any, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V8AdmissionError(f"{label} must be an integer")
    if positive and value <= 0:
        raise V8AdmissionError(f"{label} must be positive")
    return value


def _require_sha256(value: Any, label: str, *, placeholder_allowed: bool = False) -> str:
    text = _require_string(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise V8AdmissionError(f"{label} must be a lowercase SHA-256")
    if not placeholder_allowed and text == V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER:
        raise V8AdmissionError(f"{label} cannot be the release placeholder")
    return text


def _require_iso_date(value: Any, label: str) -> date:
    text = _require_string(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise V8AdmissionError(f"{label} must be an ISO date") from error
    if parsed.isoformat() != text:
        raise V8AdmissionError(f"{label} must use canonical ISO date form")
    return parsed


def _contains_forbidden_fragment(value: str) -> bool:
    lowered = value.casefold()
    return any(fragment in lowered for fragment in _FORBIDDEN_NAME_FRAGMENTS)


def _require_safe_relative_path(value: Any, label: str) -> str:
    text = _require_string(value, label)
    if "\\" in text or _contains_forbidden_fragment(text):
        raise V8AdmissionError(f"{label} contains a forbidden target/PnL/assembly path")
    candidate = PurePosixPath(text)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise V8AdmissionError(f"{label} must be a normalized project-relative POSIX path")
    if candidate.as_posix() != text or ":" in candidate.parts[0]:
        raise V8AdmissionError(f"{label} must be a normalized project-relative POSIX path")
    protected_year = V8_PROTECTED_HOLDOUT_START.year
    if any(int(match.group(1)) >= protected_year for match in _YEAR_IN_PATH.finditer(text)):
        raise V8AdmissionError(f"{label} contains a protected 2026+ year")
    return text


def _bounded_project_path(root: Path, relative_path: str, label: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise V8AdmissionError(f"{label} escapes project root") from error
    return candidate


def _parse_dependency(value: Any, label: str) -> V8SourceDependencySeal:
    payload = _require_mapping(value, label)
    _require_exact_keys(payload, _DEPENDENCY_KEYS, label)
    return V8SourceDependencySeal(
        manifest_sha256=_require_sha256(payload["manifest_sha256"], f"{label}.manifest"),
        artifact_sha256=_require_sha256(payload["artifact_sha256"], f"{label}.artifact"),
    )


def _parse_source_manifest(
    payload: Mapping[str, Any],
    expected_control: V8AdmissionSourceControl,
) -> V8NormalizedSourceManifest:
    label = f"{expected_control.kind.value} source manifest"
    _require_exact_keys(payload, _SOURCE_MANIFEST_KEYS, label)
    if payload["format"] != V8_NORMALIZED_SOURCE_FORMAT:
        raise V8AdmissionError(f"{label} format mismatch")
    try:
        kind = V8SourceKind(payload["kind"])
    except (TypeError, ValueError) as error:
        raise V8AdmissionError(f"{label} has a forbidden source kind") from error
    if kind is not expected_control.kind:
        raise V8AdmissionError(f"{label} kind mismatch")

    artifact_payload = _require_mapping(payload["artifact"], f"{label}.artifact")
    _require_exact_keys(artifact_payload, _ARTIFACT_KEYS, f"{label}.artifact")
    columns = tuple(
        _require_string(item, f"{label}.artifact.columns")
        for item in _require_sequence(artifact_payload["columns"], f"{label}.artifact.columns")
    )
    if len(set(columns)) != len(columns):
        raise V8AdmissionError(f"{label} artifact columns contain duplicates")
    if any(_contains_forbidden_fragment(column) for column in columns):
        raise V8AdmissionError(f"{label} declares forbidden target/PnL/assembly columns")
    if columns != V8_EXACT_SOURCE_COLUMNS[kind]:
        raise V8AdmissionError(f"{label} columns do not match the exact {kind.value} schema")

    decision_calendar_sha = artifact_payload["decision_calendar_sha256"]
    if decision_calendar_sha is not None:
        decision_calendar_sha = _require_sha256(
            decision_calendar_sha,
            f"{label}.artifact.decision_calendar_sha256",
        )
    decision_asset_key_sha = artifact_payload["decision_asset_key_set_sha256"]
    if decision_asset_key_sha is not None:
        decision_asset_key_sha = _require_sha256(
            decision_asset_key_sha,
            f"{label}.artifact.decision_asset_key_set_sha256",
        )
    artifact = V8SourceArtifactSeal(
        relative_path=_require_safe_relative_path(
            artifact_payload["path"], f"{label}.artifact.path"
        ),
        sha256=_require_sha256(artifact_payload["sha256"], f"{label}.artifact.sha256"),
        bytes=_require_int(artifact_payload["bytes"], f"{label}.artifact.bytes", positive=True),
        rows=_require_int(artifact_payload["rows"], f"{label}.artifact.rows", positive=True),
        columns=columns,
        decision_calendar_sha256=decision_calendar_sha,
        decision_asset_key_set_sha256=decision_asset_key_sha,
    )
    if artifact.sha256 != expected_control.artifact_sha256:
        raise V8AdmissionError(f"{label} artifact SHA differs from admission certificate")

    temporal_payload = _require_mapping(payload["temporal_bounds"], f"{label}.temporal_bounds")
    _require_exact_keys(temporal_payload, _TEMPORAL_KEYS, f"{label}.temporal_bounds")
    minimum = _require_iso_date(
        temporal_payload["minimum_session_date"], f"{label}.minimum_session_date"
    )
    maximum = _require_iso_date(
        temporal_payload["maximum_session_date"], f"{label}.maximum_session_date"
    )
    if minimum > maximum:
        raise V8AdmissionError(f"{label} temporal bounds are reversed")
    if maximum >= V8_PROTECTED_HOLDOUT_START:
        raise V8AdmissionError(f"{label} declares protected 2026+ market data")
    temporal = V8SourceTemporalBounds(minimum, maximum)

    dependency_payload = _require_mapping(payload["dependencies"], f"{label}.dependencies")
    expected_dependencies = V8_REQUIRED_SOURCE_DEPENDENCIES[kind]
    if set(dependency_payload) != {item.value for item in expected_dependencies}:
        raise V8AdmissionError(f"{label} dependency kinds do not match exact DAG")
    dependencies = tuple(
        (
            dependency_kind,
            _parse_dependency(
                dependency_payload[dependency_kind.value],
                f"{label}.dependencies.{dependency_kind.value}",
            ),
        )
        for dependency_kind in expected_dependencies
    )

    producer_payload = _require_mapping(payload["producer"], f"{label}.producer")
    _require_exact_keys(producer_payload, _PRODUCER_KEYS, f"{label}.producer")
    excluded_paths = tuple(
        _require_string(item, f"{label}.producer.excluded_paths")
        for item in _require_sequence(
            producer_payload["excluded_paths"], f"{label}.producer.excluded_paths"
        )
    )
    if excluded_paths != V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS:
        raise V8AdmissionError(f"{label} producer self-hash exclusions drifted")
    producer = V8SourceProducerSeal(
        code_identity_sha256=_require_sha256(
            producer_payload["code_identity_sha256"], f"{label}.producer.code_identity"
        ),
        protocol_sha256=_require_sha256(
            producer_payload["protocol_sha256"], f"{label}.producer.protocol"
        ),
        excluded_paths=excluded_paths,
    )

    audit_payload = _require_mapping(payload["audit"], f"{label}.audit")
    _require_exact_keys(audit_payload, _AUDIT_KEYS, f"{label}.audit")
    if audit_payload["status"] != V8_INDEPENDENT_AUDIT_STATUS:
        raise V8AdmissionError(f"{label} lacks independent audit admission")
    audit = V8SourceAuditSeal(
        status=V8_INDEPENDENT_AUDIT_STATUS,
        certificate_sha256=_require_sha256(
            audit_payload["certificate_sha256"], f"{label}.audit.certificate"
        ),
    )

    declared_identity = _require_sha256(
        payload["source_identity_sha256"], f"{label}.source_identity"
    )
    actual_identity = compute_v8_normalized_source_identity_sha256(payload)
    if (
        declared_identity != actual_identity
        or declared_identity != expected_control.source_identity_sha256
    ):
        raise V8AdmissionError(f"{label} source identity mismatch")
    return V8NormalizedSourceManifest(
        kind=kind,
        artifact=artifact,
        temporal_bounds=temporal,
        dependencies=dependencies,
        producer=producer,
        audit=audit,
        source_identity_sha256=declared_identity,
    )


def _parse_calendar_contract(value: Any) -> V8AdmissionCalendarContract:
    payload = _require_mapping(value, "calendar_contract")
    _require_exact_keys(payload, _CALENDAR_CONTRACT_KEYS, "calendar_contract")
    decision_rows = _require_int(payload["decision_rows"], "calendar decision_rows", positive=True)
    panel_rows = _require_int(payload["panel_rows"], "calendar panel_rows", positive=True)
    if decision_rows != V8_DECISION_ROW_COUNT or panel_rows != V8_PANEL_ROW_COUNT:
        raise V8AdmissionError("calendar contract must be exact 1269x4")
    assets = tuple(
        _require_string(item, "calendar assets")
        for item in _require_sequence(payload["assets"], "calendar assets")
    )
    if assets != V8_ASSET_IDS:
        raise V8AdmissionError("calendar assets must be exact BR/MIX/RI/SI")
    key_columns = tuple(
        _require_string(item, "calendar key_columns")
        for item in _require_sequence(payload["key_columns"], "calendar key_columns")
    )
    if key_columns != V8_PANEL_KEY_COLUMNS:
        raise V8AdmissionError("calendar panel key must be exact decision_at/asset")
    minimum = _require_iso_date(payload["minimum_decision_date"], "minimum_decision_date")
    maximum = _require_iso_date(payload["maximum_decision_date"], "maximum_decision_date")
    if minimum.year != 2021 or maximum.year != 2025 or minimum > maximum:
        raise V8AdmissionError("calendar decision range must cover the sealed 2021-2025 span")
    if maximum >= V8_PROTECTED_HOLDOUT_START:
        raise V8AdmissionError("calendar contract reaches protected 2026")
    year_payload = _require_mapping(payload["year_counts"], "calendar year_counts")
    expected_years = {str(year) for year in range(2021, 2026)}
    if set(year_payload) != expected_years:
        raise V8AdmissionError("calendar year_counts must contain exact 2021-2025 years")
    year_counts = tuple(
        (year, _require_int(year_payload[str(year)], f"calendar year {year}", positive=True))
        for year in range(2021, 2026)
    )
    if sum(count for _, count in year_counts) != V8_DECISION_ROW_COUNT:
        raise V8AdmissionError("calendar year_counts do not sum to 1269")
    return V8AdmissionCalendarContract(
        decision_rows=decision_rows,
        panel_rows=panel_rows,
        assets=assets,
        key_columns=key_columns,
        minimum_decision_date=minimum,
        maximum_decision_date=maximum,
        year_counts=year_counts,
        decision_calendar_sha256=_require_sha256(
            payload["decision_calendar_sha256"], "calendar semantic SHA"
        ),
        decision_asset_key_set_sha256=_require_sha256(
            payload["decision_asset_key_set_sha256"], "calendar panel key-set SHA"
        ),
    )


def _parse_validity_contract(value: Any) -> V8AdmissionValidityContract:
    payload = _require_mapping(value, "validity_contract")
    _require_exact_keys(payload, _VALIDITY_CONTRACT_KEYS, "validity_contract")
    masks = tuple(
        _require_string(item, "validity mask")
        for item in _require_sequence(payload["mask_columns"], "validity mask_columns")
    )
    if masks != V8_VALIDITY_MASK_COLUMNS:
        raise V8AdmissionError("validity masks do not match the exact four-mask contract")
    if payload["strategy_eligible_formula"] != V8_STRATEGY_ELIGIBILITY_FORMULA:
        raise V8AdmissionError("strategy eligibility formula drifted")
    if payload["invalid_row_policy"] != V8_INVALID_ROW_POLICY:
        raise V8AdmissionError("invalid-row cash/no-imputation policy drifted")
    return V8AdmissionValidityContract(
        mask_columns=masks,
        strategy_eligible_formula=V8_STRATEGY_ELIGIBILITY_FORMULA,
        invalid_row_policy=V8_INVALID_ROW_POLICY,
    )


def _parse_ledger_contract(value: Any) -> V8AdmissionLedgerContract:
    payload = _require_mapping(value, "ledger_contract")
    _require_exact_keys(payload, _LEDGER_CONTRACT_KEYS, "ledger_contract")
    strategy_ids = tuple(
        _require_string(item, "ledger strategy_id")
        for item in _require_sequence(payload["strategy_ids"], "ledger strategy_ids")
    )
    scenario_ids = tuple(
        _require_string(item, "ledger scenario_id")
        for item in _require_sequence(payload["scenario_ids"], "ledger scenario_ids")
    )
    ledger_count = _require_int(payload["ledger_count"], "ledger_count", positive=True)
    if strategy_ids != V8_STRATEGY_IDS or scenario_ids != V8_SCENARIO_IDS:
        raise V8AdmissionError("ledger contract must contain exact sealed 11x3 IDs")
    if ledger_count != V8_LEDGER_COUNT or ledger_count != 33:
        raise V8AdmissionError("ledger contract must contain exact 33 isolated ledgers")
    return V8AdmissionLedgerContract(strategy_ids, scenario_ids, ledger_count)


def _parse_certificate(payload: Mapping[str, Any]) -> V8AdmissionCertificate:
    _require_exact_keys(payload, _CERTIFICATE_KEYS, "admission certificate")
    if payload["format"] != V8_ADMISSION_CERTIFICATE_FORMAT:
        raise V8AdmissionError("admission certificate format mismatch")
    if payload["status"] != V8_AUTHORITATIVE_ADMISSION_STATUS:
        raise V8AdmissionBlockedError("admission certificate is not authoritative_admitted")
    protected = _require_iso_date(payload["protected_holdout_start"], "protected_holdout_start")
    if protected != V8_PROTECTED_HOLDOUT_START:
        raise V8AdmissionError("protected holdout boundary drifted")
    capital = payload["initial_capital_rub"]
    if isinstance(capital, bool) or not isinstance(capital, (int, float)):
        raise V8AdmissionError("initial_capital_rub must be numeric")
    if float(capital) != V8_INITIAL_CAPITAL_RUB:
        raise V8AdmissionError("authoritative initial capital must be exactly 1,000,000 RUB")

    producer_payload = _require_mapping(payload["producer_code_identity"], "producer_code_identity")
    _require_exact_keys(
        producer_payload,
        _PRODUCER_CODE_IDENTITY_KEYS,
        "producer_code_identity",
    )
    exclusions = tuple(
        _require_string(item, "producer code exclusion")
        for item in _require_sequence(
            producer_payload["excluded_paths"], "producer code excluded_paths"
        )
    )
    if exclusions != V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS:
        raise V8AdmissionError("producer code identity self-hash exclusions drifted")

    source_rows = _require_sequence(payload["sources"], "admission sources")
    controls: list[V8AdmissionSourceControl] = []
    for index, value in enumerate(source_rows):
        source_payload = _require_mapping(value, f"admission sources[{index}]")
        _require_exact_keys(
            source_payload,
            _CERTIFICATE_SOURCE_KEYS,
            f"admission sources[{index}]",
        )
        try:
            kind = V8SourceKind(source_payload["kind"])
        except (TypeError, ValueError) as error:
            raise V8AdmissionError("admission contains a forbidden source kind") from error
        controls.append(
            V8AdmissionSourceControl(
                kind=kind,
                manifest_relative_path=_require_safe_relative_path(
                    source_payload["manifest_path"], f"{kind.value} manifest_path"
                ),
                manifest_sha256=_require_sha256(
                    source_payload["manifest_sha256"], f"{kind.value} manifest SHA"
                ),
                artifact_sha256=_require_sha256(
                    source_payload["artifact_sha256"], f"{kind.value} artifact SHA"
                ),
                source_identity_sha256=_require_sha256(
                    source_payload["source_identity_sha256"], f"{kind.value} source identity"
                ),
            )
        )
    if tuple(item.kind for item in controls) != V8_REQUIRED_SOURCE_KINDS:
        raise V8AdmissionError("admission sources must contain the exact ordered seven-source DAG")
    manifest_paths = tuple(item.manifest_relative_path for item in controls)
    if len(set(manifest_paths)) != len(manifest_paths):
        raise V8AdmissionError("admission source manifest paths must be unique")

    return V8AdmissionCertificate(
        status=V8_AUTHORITATIVE_ADMISSION_STATUS,
        protected_holdout_start=protected,
        initial_capital_rub=float(capital),
        calendar_contract=_parse_calendar_contract(payload["calendar_contract"]),
        validity_contract=_parse_validity_contract(payload["validity_contract"]),
        ledger_contract=_parse_ledger_contract(payload["ledger_contract"]),
        producer_code_identity_sha256=_require_sha256(
            producer_payload["sha256"], "producer code identity SHA"
        ),
        producer_code_identity_excluded_paths=exclusions,
        protocol_bundle_sha256=_require_sha256(
            payload["protocol_bundle_sha256"], "protocol bundle SHA"
        ),
        independent_audit_certificate_sha256=_require_sha256(
            payload["independent_audit_certificate_sha256"],
            "independent audit certificate SHA",
        ),
        sources=tuple(controls),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_bom_json_control(path: Path, expected_sha256: str, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing {label}: {path}")
    size = path.stat().st_size
    if size <= 3 or size > V8_MAX_CONTROL_BYTES:
        raise V8AdmissionError(f"{label} exceeds the small-control byte bound")
    content = path.read_bytes()
    if len(content) != size:
        raise V8AdmissionError(f"{label} changed while being read")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise V8AdmissionError(f"{label} byte SHA mismatch")
    if not content.startswith(b"\xef\xbb\xbf"):
        raise V8AdmissionError(f"{label} must be UTF-8 BOM JSON")
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V8AdmissionError(f"{label} is not valid BOM JSON") from error
    if not isinstance(payload, dict):
        raise V8AdmissionError(f"{label} top-level value must be an object")
    return payload


def _validate_global_source_contract(
    certificate: V8AdmissionCertificate,
    manifests: tuple[V8NormalizedSourceManifest, ...],
) -> None:
    by_kind = {item.kind: item for item in manifests}
    if tuple(by_kind) != V8_REQUIRED_SOURCE_KINDS:
        raise V8AdmissionError("parsed source manifests do not match exact seven-source order")

    for manifest in manifests:
        exact_rows = V8_EXACT_SOURCE_ROWS.get(manifest.kind)
        if exact_rows is not None and manifest.artifact.rows != exact_rows:
            raise V8AdmissionError(f"{manifest.kind.value} must declare exact {exact_rows} rows")
        if manifest.audit.certificate_sha256 != certificate.independent_audit_certificate_sha256:
            raise V8AdmissionError(
                f"{manifest.kind.value} audit certificate differs from admission root"
            )
        for dependency_kind, dependency in manifest.dependencies:
            target_control = certificate.source(dependency_kind)
            target_manifest = by_kind[dependency_kind]
            if (
                dependency.manifest_sha256 != target_control.manifest_sha256
                or dependency.artifact_sha256 != target_manifest.artifact.sha256
            ):
                raise V8AdmissionError(
                    f"{manifest.kind.value} dependency manifest+artifact seal mismatch: "
                    f"{dependency_kind.value}"
                )

    calendar = certificate.calendar_contract
    panel_kinds = {
        V8SourceKind.BASE_PREDICTIONS,
        V8SourceKind.REGIME_V2,
        V8SourceKind.CALENDAR,
        V8SourceKind.FULL_CONTEXT,
    }
    for kind in panel_kinds:
        bounds = by_kind[kind].temporal_bounds
        if (
            bounds.minimum_session_date != calendar.minimum_decision_date
            or bounds.maximum_session_date != calendar.maximum_decision_date
        ):
            raise V8AdmissionError(f"{kind.value} temporal bounds differ from exact calendar")
    for kind in (V8SourceKind.SPEC_PROXY, V8SourceKind.MOEX_10M):
        bounds = by_kind[kind].temporal_bounds
        if (
            bounds.minimum_session_date > calendar.minimum_decision_date
            or bounds.maximum_session_date < calendar.maximum_decision_date
        ):
            raise V8AdmissionError(f"{kind.value} does not cover the exact evaluation calendar")

    for kind, manifest in by_kind.items():
        calendar_sha = manifest.artifact.decision_calendar_sha256
        key_set_sha = manifest.artifact.decision_asset_key_set_sha256
        if kind is V8SourceKind.CHECKPOINT_IDENTITIES:
            if calendar_sha is not None or key_set_sha is not None:
                raise V8AdmissionError("checkpoint source cannot claim evaluation calendar keys")
            continue
        if calendar_sha != calendar.decision_calendar_sha256:
            raise V8AdmissionError(f"{kind.value} decision calendar seal mismatch")
        if kind in {
            V8SourceKind.BASE_PREDICTIONS,
            V8SourceKind.REGIME_V2,
            V8SourceKind.FULL_CONTEXT,
        }:
            if key_set_sha != calendar.decision_asset_key_set_sha256:
                raise V8AdmissionError(f"{kind.value} decision-asset key-set seal mismatch")
        elif key_set_sha is not None:
            raise V8AdmissionError(f"{kind.value} cannot claim a panel key-set seal")


def _verify_artifact_bytes(
    root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    manifest: V8NormalizedSourceManifest,
) -> V8VerifiedAdmissionSource:
    artifact_path = _bounded_project_path(
        root,
        manifest.artifact.relative_path,
        f"{manifest.kind.value} artifact",
    )
    if not artifact_path.is_file():
        raise FileNotFoundError(f"missing {manifest.kind.value} artifact: {artifact_path}")
    before = artifact_path.stat()
    if before.st_size != manifest.artifact.bytes:
        raise V8AdmissionError(f"{manifest.kind.value} artifact byte count mismatch")
    if _sha256_file(artifact_path) != manifest.artifact.sha256:
        raise V8AdmissionError(f"{manifest.kind.value} artifact byte SHA mismatch")
    after = artifact_path.stat()
    if (
        before.st_size,
        before.st_mtime_ns,
        before.st_ino,
    ) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise V8AdmissionError(f"{manifest.kind.value} artifact changed while hashing")
    return V8VerifiedAdmissionSource(
        kind=manifest.kind,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        artifact_path=artifact_path,
        artifact_sha256=manifest.artifact.sha256,
        artifact_bytes=manifest.artifact.bytes,
        rows=manifest.artifact.rows,
        source_identity_sha256=manifest.source_identity_sha256,
        manifest=manifest,
    )


def _verify_v8_released_admission(project_root: Path) -> V8VerifiedAdmission:
    """Verify controls after the public entry point has admitted its compiled anchor."""

    anchor = V8_AUTHORITATIVE_ADMISSION_TRUST_ANCHOR
    root = Path(project_root).resolve()
    expected_certificate_sha = _require_sha256(
        anchor.certificate_sha256,
        "admission certificate trust anchor",
    )
    certificate_path = _bounded_project_path(
        root,
        V8_ADMISSION_CERTIFICATE_PATH,
        "admission certificate",
    )
    certificate_payload = _read_bom_json_control(
        certificate_path,
        expected_certificate_sha,
        "admission certificate",
    )
    certificate = _parse_certificate(certificate_payload)

    # Phase zero: every source control is read and every safety/schema/DAG contract is
    # validated before _verify_artifact_bytes is allowed to open even one artifact.
    parsed: list[tuple[Path, V8NormalizedSourceManifest]] = []
    for control in certificate.sources:
        manifest_path = _bounded_project_path(
            root,
            control.manifest_relative_path,
            f"{control.kind.value} source manifest",
        )
        manifest_payload = _read_bom_json_control(
            manifest_path,
            control.manifest_sha256,
            f"{control.kind.value} source manifest",
        )
        parsed.append((manifest_path, _parse_source_manifest(manifest_payload, control)))
    manifests = tuple(item[1] for item in parsed)
    _validate_global_source_contract(certificate, manifests)
    artifact_paths = tuple(item.artifact.relative_path for item in manifests)
    if len(set(artifact_paths)) != len(artifact_paths):
        raise V8AdmissionError("normalized artifact paths must be unique")
    control_paths = {
        V8_ADMISSION_CERTIFICATE_PATH,
        *(item.manifest_relative_path for item in certificate.sources),
    }
    if set(artifact_paths) & control_paths:
        raise V8AdmissionError("normalized artifacts must be disjoint from control paths")

    # Phase one: content access begins only after every phase-zero check has passed.
    verified = tuple(
        _verify_artifact_bytes(
            root,
            manifest_path,
            certificate.source(manifest.kind).manifest_sha256,
            manifest,
        )
        for manifest_path, manifest in parsed
    )

    # Re-read only the small controls to detect mutation across artifact hashing.
    _read_bom_json_control(
        certificate_path,
        expected_certificate_sha,
        "admission certificate final recheck",
    )
    for source in verified:
        _read_bom_json_control(
            source.manifest_path,
            source.manifest_sha256,
            f"{source.kind.value} source manifest final recheck",
        )
    return V8VerifiedAdmission(
        project_root=root,
        certificate_path=certificate_path,
        certificate_sha256=expected_certificate_sha,
        certificate=certificate,
        sources=verified,
    )


def verify_v8_authoritative_admission(project_root: Path) -> V8VerifiedAdmission:
    """Verify the one code-pinned release; callers cannot supply a path, hash, or capital."""

    anchor = V8_AUTHORITATIVE_ADMISSION_TRUST_ANCHOR
    if not isinstance(anchor, V8AdmissionTrustAnchor):
        raise V8AdmissionBlockedError("authoritative admission trust-anchor type drifted")
    if not anchor.released:
        raise V8AdmissionBlockedError(
            "authoritative admission is blocked: certificate SHA trust anchor is a placeholder"
        )
    if anchor.certificate_path != V8_ADMISSION_CERTIFICATE_PATH:
        raise V8AdmissionBlockedError("authoritative admission certificate path drifted")
    return _verify_v8_released_admission(project_root)


__all__ = [
    "V8_ADMISSION_CERTIFICATE_FORMAT",
    "V8_ADMISSION_CERTIFICATE_PATH",
    "V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER",
    "V8_ASSET_IDS",
    "V8_AUTHORITATIVE_ADMISSION_STATUS",
    "V8_AUTHORITATIVE_ADMISSION_TRUST_ANCHOR",
    "V8_BASE_PREDICTION_COLUMNS",
    "V8_CALENDAR_COLUMNS",
    "V8_CHECKPOINT_COUNT",
    "V8_CHECKPOINT_IDENTITY_COLUMNS",
    "V8_DECISION_ROW_COUNT",
    "V8_EXACT_SOURCE_COLUMNS",
    "V8_EXACT_SOURCE_ROWS",
    "V8_FULL_CONTEXT_COLUMNS",
    "V8_INDEPENDENT_AUDIT_STATUS",
    "V8_INITIAL_CAPITAL_RUB",
    "V8_INVALID_ROW_POLICY",
    "V8_LEDGER_COUNT",
    "V8_MOEX_10M_COLUMNS",
    "V8_NORMALIZED_SOURCE_FORMAT",
    "V8_PANEL_KEY_COLUMNS",
    "V8_PANEL_ROW_COUNT",
    "V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS",
    "V8_PROTECTED_HOLDOUT_START",
    "V8_REGIME_V2_COLUMNS",
    "V8_REQUIRED_SOURCE_DEPENDENCIES",
    "V8_REQUIRED_SOURCE_KINDS",
    "V8_SCENARIO_IDS",
    "V8_SPEC_PROXY_COLUMNS",
    "V8_STRATEGY_IDS",
    "V8_STRATEGY_ELIGIBILITY_FORMULA",
    "V8_VALIDITY_MASK_COLUMNS",
    "V8AdmissionBlockedError",
    "V8AdmissionCalendarContract",
    "V8AdmissionCertificate",
    "V8AdmissionError",
    "V8AdmissionLedgerContract",
    "V8AdmissionSourceControl",
    "V8AdmissionTrustAnchor",
    "V8AdmissionValidityContract",
    "V8NormalizedSourceManifest",
    "V8SourceArtifactSeal",
    "V8SourceAuditSeal",
    "V8SourceDependencySeal",
    "V8SourceKind",
    "V8SourceProducerSeal",
    "V8SourceTemporalBounds",
    "V8VerifiedAdmission",
    "V8VerifiedAdmissionSource",
    "compute_v8_normalized_source_identity_sha256",
    "verify_v8_authoritative_admission",
]
