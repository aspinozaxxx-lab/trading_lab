"""Authoritative target-free orchestration i persistence dlya futures-v8 evaluation."""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum, StrEnum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from zoneinfo import ZoneInfo

import pandas as pd

from market_lab.futures_v8.aggressive_strategies import (
    MAXIMUM_BAR_PARTICIPATION_BPS,
    V8_ASSET_IDS,
    AggressiveCandidateId,
    CausalAssetSnapshot,
    CausalDecisionContext,
    PointInTimeObservation,
)
from market_lab.futures_v8.eval_run import (
    V8_STRATEGY_IDS,
    V8AssetContractSnapshot,
    V8CandleTrustStatus,
    V8ContractSpec,
    V8EquityPoint,
    V8EvaluationLedgerMatrix,
    V8EventLedgerState,
    V8GateAndRanking,
    V8OrderBinding,
    V8OrderCause,
    V8PositionKey,
    V8ScenarioExecutionEvidence,
    V8ScenarioFillLeg,
    V8ScenarioId,
    V8ScenarioMetrics,
    V8SealedEvaluationInputBundle,
    V8SleeveTarget,
    V8StatefulReplayPolicy,
    V8StrategyMetricsBundle,
    V8TargetFreePrediction,
    V8TrustedCandleIndex,
    apply_v8_execution_batch,
    build_v8_core_path,
    build_v8_entry_bindings,
    build_v8_gate_and_ranking,
    build_v8_new_sleeve_targets,
    build_v8_sleeve_exit_bindings,
    build_v8_strategy_decision_set,
    canonical_sha256,
    create_v8_evaluation_ledger_matrix,
    fixed_v8_scenarios,
    integer_contracts_for_weight,
    plan_v8_scenario_execution,
    select_v8_contract_spec_snapshot,
    settle_v8_event_ledger,
    summarize_v8_scenario,
)
from market_lab.futures_v8.execution import (
    ExecutionLeg,
    ExecutionStatus,
    OrderExecution,
    PredeclaredMarketOrder,
    TenMinuteCandle,
)
from market_lab.futures_v8.stateful_evaluation import (
    BREAKOUT_STRATEGY_ID,
    CORRIDOR_STRATEGY_ID,
    BreakoutDecisionObservation,
    BreakoutScenarioState,
    CorridorBarTransition,
    CorridorEntryProtocol,
    CorridorExitTrigger,
    CorridorScenarioPosition,
    CorridorStatus,
    ExactScenarioExecutionWindows,
    MissingBarEvidence,
    PendingBreakoutTransition,
    ScenarioExecutionWindow,
    ScenarioFactualBar,
    StatefulAction,
    StatefulExecutionEvidence,
    StatefulLedgerEvent,
    StatefulOrderIntent,
    StatefulResolution,
    StatefulSealSet,
    StatefulUnresolvedCarry,
    advance_breakout_observation,
    assert_exact_scenario_partition,
    bind_breakout_order,
    mark_corridor_missing_bar,
    propose_breakout_transition,
    reconcile_breakout_execution,
    reconcile_corridor_entry,
    reconcile_corridor_exit,
    transition_corridor_bar,
)
from market_lab.io_utils import atomic_write_bytes

# Format normalizovannogo source manifesta evaluator inputa.
V8_EVALUATION_SOURCE_FORMAT: Final[str] = "market-lab-futures-v8-evaluation-source-v1"
# Format content-addressed final evaluation manifesta.
V8_EVALUATION_RUN_FORMAT: Final[str] = "market-lab-futures-v8-evaluation-run-v1"
# Yavno synthetic status, kotoryi ne mozhet byt' vydan za authoritative PnL.
V8_SYNTHETIC_RESEARCH_STATUS: Final[str] = "synthetic_test_only_not_real_pnl"
# Status gotovogo authoritative enrichment posle nezavisimogo audita.
V8_AUDITED_ENRICHMENT_STATUS: Final[str] = "audited_complete"
# Status deterministic raw->full-context buildera; regime-only artifact ne prohodit.
V8_FULL_CAUSAL_CONTEXT_STATUS: Final[str] = "audited_full_causal_context"
# Exact chislo completed original training checkpoints 5 folds x 3 seeds.
V8_REQUIRED_COMPLETED_CHECKPOINTS: Final[int] = 15
# Nachalo zashchishchennogo holdout dlya vseh pre-PnL proverok.
V8_PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)
# Birzhevaya timezone dlya decision D i factual window identity.
MOSCOW_TIMEZONE: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
# Exact kinds, kotorye dolzhny byt' byte-provereny do chteniya tablic.
V8_REQUIRED_SOURCE_KINDS: Final[tuple[str, ...]] = (
    "base_predictions",
    "checkpoint_identities",
    "enrichment",
    "calendar",
    "assembly",
    "active_map",
    "spec_proxy",
    "moex_10m",
)
# Exact dependency graph, blokiruyushchii mix-and-match source snapshots.
V8_REQUIRED_SOURCE_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    "base_predictions": ("checkpoint_identities",),
    "checkpoint_identities": (),
    "enrichment": ("assembly", "base_predictions", "checkpoint_identities"),
    "calendar": ("assembly",),
    "assembly": (),
    "active_map": ("assembly", "calendar"),
    "spec_proxy": ("active_map", "calendar"),
    "moex_10m": ("active_map", "calendar"),
}
# Exact code closure, vliyayushchii na prediction, strategy, execution i accounting.
V8_EVALUATION_CODE_PATHS: Final[tuple[str, ...]] = (
    "src/market_lab/futures_v8/evaluation_run.py",
    "src/market_lab/futures_v8/stateful_evaluation.py",
    "src/market_lab/futures_v8/eval_run.py",
    "src/market_lab/futures_v8/aggressive_strategies.py",
    "src/market_lab/futures_v8/execution.py",
    "src/market_lab/futures_v8/portfolio.py",
    "src/market_lab/futures_v8/assembly.py",
    "src/market_lab/futures_v8/train_run.py",
    "src/market_lab/futures_v8/enrich_run.py",
    "src/market_lab/futures_v8/config.py",
    "configs/futures_v8_development_protocol.yaml",
)
# Tokeny, kotorye zapreshcheny v evaluator-loaded columns i array keys.
V8_FORBIDDEN_DATA_TOKENS: Final[tuple[str, ...]] = (
    "target",
    "label",
    "future_return",
    "realized_return",
)
# External PIT channels, dlya kotoryh trebuetsya polnaya release provenance.
V8_PIT_CHANNELS: Final[tuple[str, ...]] = (
    "carry_z",
    "cftc_crowd_z",
    "key_rate_change_z",
    "usd_rub_return_z",
)
# Exact target-free output schema original training runnera.
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
# Exact causal enrichment schema bez labels/targets/returns.
V8_ENRICHMENT_COLUMNS: Final[tuple[str, ...]] = (
    "decision_at",
    "asset",
    "known_at",
    "total_scale",
    "abstain_probability",
    "normal_probability",
    "trend_probability",
    "crash_probability",
    "close",
    "atr_20",
    "daily_volatility_20",
    "momentum_20",
    "range_position_20",
    "volatility_ratio_20",
    "volume_ratio_20",
    "market_data_sha256",
    *tuple(
        f"{channel}_{suffix}"
        for channel in V8_PIT_CHANNELS
        for suffix in (
            "value",
            "published_at",
            "source_id",
            "observation_id",
            "source_sha256",
        )
    ),
)
# Exact D-known active-map/maturity schema dlya nominal 5-session eligibility.
V8_ACTIVE_MAP_COLUMNS: Final[tuple[str, ...]] = (
    "decision_at",
    "asset",
    "contract_id",
    "contract_known_at",
    "entry_effective_session_date",
    "expiration_date",
    "maturity_known_at",
    "asset_mask",
    "source_sha256",
)
# Exact daily spec snapshot schema s lag-1 sizing i current accounting.
V8_SPEC_PROXY_COLUMNS: Final[tuple[str, ...]] = (
    "session_date",
    "asset",
    "contract_id",
    "sizing_observed_session_date",
    "sizing_known_at",
    "accounting_known_at",
    "sizing_point_value",
    "realized_accounting_point_value",
    "modeled_initial_margin",
    "conservative_fee_per_side",
    "sizing_lag_sessions",
    "sizing_status",
    "accounting_status",
    "source_sha256",
)
# Exact factual candle schema dlya execution.py bez price/volume substitution.
V8_TEN_MINUTE_COLUMNS: Final[tuple[str, ...]] = (
    "contract_id",
    "opened_at",
    "closed_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
# Exact factual calendar schema: D, next economic session i odin settlement mark.
V8_CALENDAR_COLUMNS: Final[tuple[str, ...]] = (
    "sequence_id",
    "decision_session_date",
    "decision_at",
    "entry_effective_session_date",
    "calendar_known_at",
    "settlement_candle_opened_at",
    "settlement_candle_closed_at",
    "settlement_at",
    "accounting_as_of",
    "source_sha256",
)
# Stateful candidates, dlya kotoryh generic target execution zapreshchen v real mode.
V8_STATEFUL_STRATEGY_IDS: Final[frozenset[str]] = frozenset(
    {
        AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST.value,
        AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP.value,
    }
)
# Exact imena content-addressed artifact payloads.
V8_EVALUATION_ARTIFACT_KINDS: Final[tuple[str, ...]] = (
    "input_identity",
    "code_identity",
    "decisions",
    "orders",
    "execution_evidence",
    "fills",
    "equity",
    "scenario_metrics",
    "gates",
    "ranking",
    "failure_events",
    "report",
)


class V8EvaluationBlockedError(RuntimeError):
    """Fail-closed signal do real PnL pri otsutstvii audited runtime boundary."""


class V8EvaluationMode(StrEnum):
    """Razdelyaet blokirovannyi authoritative i yavnyi synthetic test mode."""

    AUTHORITATIVE = "authoritative"
    SYNTHETIC_TEST = "synthetic_test"


def _file_sha256(path: Path) -> str:
    """Schitaet byte-exact SHA-256 odnogo proverennogo file."""
    digest = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _require_sha256(value: str, label: str) -> str:
    """Trebuet lowercase hex SHA-256 bez implicit normalization source identity."""
    if not isinstance(value, str):
        raise TypeError(f"{label} dolzhen byt' strokoj")
    normalized = value.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{label} dolzhen byt' SHA-256")
    return normalized


def _require_aware(value: datetime, label: str) -> datetime:
    """Trebuet timezone-aware timestamp i privodit ego k UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} dolzhen byt' timezone-aware datetime")
    return value.astimezone(UTC)


def _require_date(value: object, label: str) -> date:
    """Prevrashchaet date-like value v development-only plain date."""
    if isinstance(value, datetime):
        normalized = value.date()
    elif isinstance(value, date):
        normalized = value
    else:
        parsed = pd.Timestamp(value)
        if pd.isna(parsed):
            raise ValueError(f"{label} ne mozhet byt' NaT")
        normalized = parsed.date()
    if normalized >= V8_PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} popal v protected 2026")
    return normalized


def _bounded_path(root: Path, path: Path, label: str) -> Path:
    """Razreshaet file tol'ko vnutri project root bez path escape."""
    resolved_root = root.resolve()
    candidate = path if path.is_absolute() else resolved_root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{label} vne project root") from error
    return resolved


def _canonical_value(value: Any) -> Any:
    """Serializuet typed orchestration state v stable JSON-safe payload."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("canonical payload ne prinimaet NaN/Inf")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Nepodderzhivaemyi canonical tip: {type(value).__name__}")


def _canonical_json_bytes(payload: Any, *, bom: bool = False) -> bytes:
    """Stroit deterministic compact JSON bytes s optional UTF-8 BOM."""
    content = json.dumps(
        _canonical_value(payload),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (b"\xef\xbb\xbf" + content + b"\n") if bom else content


def _payload_sha256(payload: Any) -> str:
    """Schitaet stable SHA-256 orchestration payload bez BOM."""
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    """Chitaet UTF-8/BOM JSON i trebuet object na korne."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON ne yavlyaetsya object: {path}")
    return payload


def _assert_no_forbidden_names(names: Sequence[object], label: str) -> None:
    """Blokiruet target/label/return columns ili arrays do bundle construction."""
    normalized = tuple(str(item).lower() for item in names)
    poisoned = tuple(
        name for name in normalized if any(token in name for token in V8_FORBIDDEN_DATA_TOKENS)
    )
    if poisoned:
        raise ValueError(f"{label} soderzhit forbidden target/label data: {poisoned}")


def _require_exact_columns(
    frame: pd.DataFrame,
    expected: Sequence[str],
    label: str,
) -> None:
    """Trebuet exact target-free schema bez skrytyh extra columns."""
    _assert_no_forbidden_names(tuple(frame.columns), f"{label} columns")
    if tuple(frame.columns) != tuple(expected):
        missing = sorted(set(expected) - set(frame.columns))
        extra = sorted(set(frame.columns) - set(expected))
        raise ValueError(f"{label} schema mismatch: missing={missing}, extra={extra}")


@dataclass(frozen=True, slots=True)
class V8EvaluationSourceSeal:
    """Byte-seal odnogo manifesta i ego odnogo evaluation artifacta."""

    kind: str
    manifest_path: Path
    manifest_sha256: str
    artifact_path: Path
    artifact_sha256: str
    rows: int

    def __post_init__(self) -> None:
        """Proveryaet stable kind, SHA i declared row count."""
        if self.kind not in V8_REQUIRED_SOURCE_KINDS:
            raise ValueError("evaluation source kind vne exact registry")
        object.__setattr__(
            self,
            "manifest_sha256",
            _require_sha256(self.manifest_sha256, "manifest_sha256"),
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _require_sha256(self.artifact_sha256, "artifact_sha256"),
        )
        if isinstance(self.rows, bool) or not isinstance(self.rows, int) or self.rows < 0:
            raise ValueError("source rows dolzhen byt' nonnegative int")


@dataclass(frozen=True, slots=True)
class V8EvaluationVerificationRequest:
    """Zapros na polnuyu pre-PnL byte/provenance/code proverku."""

    project_root: Path
    sources: tuple[V8EvaluationSourceSeal, ...]
    expected_code_identity_sha256: str

    def __post_init__(self) -> None:
        """Trebuet exact source registry i expected code closure seal."""
        kinds = tuple(item.kind for item in self.sources)
        if tuple(sorted(kinds)) != tuple(sorted(V8_REQUIRED_SOURCE_KINDS)):
            raise ValueError("verification request trebuet exact evaluation source kinds")
        if len(set(kinds)) != len(kinds):
            raise ValueError("verification request soderzhit duplicate source kind")
        object.__setattr__(
            self,
            "expected_code_identity_sha256",
            _require_sha256(
                self.expected_code_identity_sha256,
                "expected_code_identity_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class V8VerifiedEvaluationSource:
    """Resolved byte-proverennyi source s immutable manifest payload."""

    kind: str
    manifest_path: Path
    manifest_sha256: str
    artifact_path: Path
    artifact_sha256: str
    artifact_bytes: int
    rows: int
    manifest_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class V8VerifiedEvaluationSources:
    """Exact pre-PnL source/code closure bez zagruzhennyh target arrays."""

    project_root: Path
    sources: tuple[V8VerifiedEvaluationSource, ...]
    code_identity: dict[str, Any]
    source_identity_sha256: str

    def source(self, kind: str) -> V8VerifiedEvaluationSource:
        """Vozvrashchaet exact verified kind bez fallback."""
        return next(item for item in self.sources if item.kind == kind)


def build_v8_evaluation_code_identity(project_root: Path) -> dict[str, Any]:
    """Hashiruet exact transitive evaluation code/config closure."""
    root = project_root.resolve()
    files: list[dict[str, Any]] = []
    for relative in V8_EVALUATION_CODE_PATHS:
        path = _bounded_path(root, Path(relative), "code closure file")
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    payload = {"files": files}
    return {**payload, "code_identity_sha256": _payload_sha256(payload)}


def _verify_source_manifest(
    root: Path,
    seal: V8EvaluationSourceSeal,
) -> V8VerifiedEvaluationSource:
    """Rehashiruet manifest/artifact i proveriaet normalizovannyi source contract."""
    manifest = _bounded_path(root, seal.manifest_path, f"{seal.kind} manifest")
    artifact = _bounded_path(root, seal.artifact_path, f"{seal.kind} artifact")
    if not manifest.is_file() or not artifact.is_file():
        raise FileNotFoundError(f"Missing {seal.kind} manifest ili artifact")
    if _file_sha256(manifest) != seal.manifest_sha256:
        raise ValueError(f"{seal.kind} manifest byte SHA mismatch")
    if _file_sha256(artifact) != seal.artifact_sha256:
        raise ValueError(f"{seal.kind} artifact byte SHA mismatch")
    payload = _read_json_object(manifest)
    if _file_sha256(manifest) != seal.manifest_sha256:
        raise ValueError(f"{seal.kind} manifest izmenilsya vo vremya read")
    if payload.get("format") != V8_EVALUATION_SOURCE_FORMAT:
        raise ValueError(f"{seal.kind} source format mismatch")
    if payload.get("kind") != seal.kind:
        raise ValueError(f"{seal.kind} manifest kind mismatch")
    record = payload.get("artifact")
    if not isinstance(record, dict):
        raise ValueError(f"{seal.kind} manifest ne soderzhit artifact record")
    expected_relative = artifact.relative_to(root).as_posix()
    expected_record = {
        "path": expected_relative,
        "sha256": seal.artifact_sha256,
        "bytes": artifact.stat().st_size,
        "rows": seal.rows,
    }
    if any(record.get(key) != value for key, value in expected_record.items()):
        raise ValueError(f"{seal.kind} manifest artifact identity mismatch")
    columns = payload.get("columns", [])
    array_keys = payload.get("array_keys", [])
    if not isinstance(columns, list) or not isinstance(array_keys, list):
        raise ValueError(f"{seal.kind} manifest columns/array_keys dolzhny byt' lists")
    _assert_no_forbidden_names(columns, f"{seal.kind} manifest columns")
    _assert_no_forbidden_names(array_keys, f"{seal.kind} manifest array_keys")
    maximum_date = payload.get("maximum_session_date")
    if maximum_date is not None:
        _require_date(maximum_date, f"{seal.kind} maximum_session_date")
    return V8VerifiedEvaluationSource(
        kind=seal.kind,
        manifest_path=manifest,
        manifest_sha256=seal.manifest_sha256,
        artifact_path=artifact,
        artifact_sha256=seal.artifact_sha256,
        artifact_bytes=artifact.stat().st_size,
        rows=seal.rows,
        manifest_payload=payload,
    )


def verify_v8_evaluation_sources(
    request: V8EvaluationVerificationRequest,
) -> V8VerifiedEvaluationSources:
    """Vypolnyaet vse byte/dependency/checkpoint/audit/code checks do tablic i PnL."""
    root = request.project_root.resolve()
    verified = tuple(
        sorted(
            (_verify_source_manifest(root, item) for item in request.sources),
            key=lambda item: item.kind,
        )
    )
    by_kind = {item.kind: item for item in verified}
    artifact_hashes = {kind: item.artifact_sha256 for kind, item in by_kind.items()}
    for item in verified:
        dependencies = item.manifest_payload.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError(f"{item.kind} dependencies dolzhny byt' object")
        expected_dependencies = V8_REQUIRED_SOURCE_DEPENDENCIES[item.kind]
        if set(dependencies) != set(expected_dependencies):
            raise ValueError(
                f"{item.kind} dependencies ne sootvetstvuyut exact graph: "
                f"expected={expected_dependencies}"
            )
        for dependency_kind, dependency_sha in dependencies.items():
            if artifact_hashes.get(str(dependency_kind)) != str(dependency_sha).lower():
                raise ValueError(f"{item.kind} dependency seal mismatch: {dependency_kind}")
    checkpoint_payload = by_kind["checkpoint_identities"].manifest_payload
    if (
        checkpoint_payload.get("completed_checkpoint_count") != V8_REQUIRED_COMPLETED_CHECKPOINTS
        or checkpoint_payload.get("all_completed") is not True
    ):
        raise V8EvaluationBlockedError("original training checkpoints ne dokazali 15/15")
    enrichment_payload = by_kind["enrichment"].manifest_payload
    if enrichment_payload.get("audit_status") != V8_AUDITED_ENRICHMENT_STATUS:
        raise V8EvaluationBlockedError("enrichment manifest eshche ne audited_complete")
    if enrichment_payload.get("context_completion_status") != V8_FULL_CAUSAL_CONTEXT_STATUS:
        raise V8EvaluationBlockedError(
            "regime-only enrichment insufficient: deterministic audited "
            "raw-to-full-causal-context builder artifact otsutstvuet"
        )
    base_dependencies = by_kind["base_predictions"].manifest_payload.get("dependencies", {})
    if (
        base_dependencies.get("checkpoint_identities")
        != by_kind["checkpoint_identities"].artifact_sha256
    ):
        raise ValueError("base predictions ne privyazany k exact checkpoint identities")
    code_identity = build_v8_evaluation_code_identity(root)
    if code_identity["code_identity_sha256"] != request.expected_code_identity_sha256:
        raise ValueError("evaluation code closure SHA mismatch")
    identity_payload = {
        "sources": [
            {
                "kind": item.kind,
                "manifest_sha256": item.manifest_sha256,
                "artifact_sha256": item.artifact_sha256,
                "rows": item.rows,
            }
            for item in verified
        ],
        "code_identity_sha256": code_identity["code_identity_sha256"],
    }
    return V8VerifiedEvaluationSources(
        project_root=root,
        sources=verified,
        code_identity=code_identity,
        source_identity_sha256=_payload_sha256(identity_payload),
    )


def _timestamp(value: object, label: str) -> datetime:
    """Chitaet timezone-aware timestamp i zapreshchaet protected 2026."""
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError(f"{label} dolzhen byt' timezone-aware timestamp")
    result = parsed.to_pydatetime().astimezone(UTC)
    if result.astimezone(MOSCOW_TIMEZONE).date() >= V8_PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} popal v protected 2026")
    return result


def _finite_number(value: object, label: str, *, positive: bool = False) -> float:
    """Trebuet finite numeric bez bool i optional strogo polozhitel'noe znachenie."""
    if isinstance(value, bool):
        raise TypeError(f"{label} ne mozhet byt' bool")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{label} dolzhen byt' numeric") from error
    if not isfinite(result) or (positive and result <= 0.0):
        suffix = " i > 0" if positive else ""
        raise ValueError(f"{label} dolzhen byt' finite{suffix}")
    return result


def _strict_bool(value: object, label: str) -> bool:
    """Trebuet nastoyashchii bool bez implicit 0/1 coercion."""
    if not isinstance(value, bool):
        raise TypeError(f"{label} dolzhen byt' bool")
    return value


def _strict_int(value: object, label: str, *, nonnegative: bool = False) -> int:
    """Trebuet exact integer bez bool/fractional numeric coercion."""
    if isinstance(value, bool):
        raise TypeError(f"{label} ne mozhet byt' bool")
    numeric = _finite_number(value, label)
    if not numeric.is_integer() or (nonnegative and numeric < 0.0):
        raise ValueError(f"{label} dolzhen byt' exact integer")
    return int(numeric)


def _scan_json_safety(value: object, label: str = "JSON") -> None:
    """Rekursivno blokiruet target keys i protected temporal payload do bundle."""
    if isinstance(value, dict):
        _assert_no_forbidden_names(tuple(value), f"{label} keys")
        for key, item in value.items():
            key_text = str(key).lower()
            if isinstance(item, str) and any(
                token in key_text for token in ("date", "session", "timestamp", "_at", "time")
            ):
                try:
                    parsed = pd.Timestamp(item)
                except (TypeError, ValueError):
                    parsed = pd.NaT
                if not pd.isna(parsed) and parsed.date() >= V8_PROTECTED_HOLDOUT_START:
                    raise ValueError(f"{label}.{key} popal v protected 2026")
            _scan_json_safety(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_json_safety(item, f"{label}[{index}]")


def _read_verified_frame(
    source: V8VerifiedEvaluationSource,
    expected_columns: Sequence[str],
) -> pd.DataFrame:
    """Chitaet tol'ko byte-proverennyi parquet i proveriaet exact rows/schema."""
    if source.artifact_path.suffix.lower() != ".parquet":
        raise ValueError(f"{source.kind} artifact dolzhen byt' parquet")
    if _file_sha256(source.artifact_path) != source.artifact_sha256:
        raise ValueError(f"{source.kind} artifact izmenilsya pered parquet read")
    frame = pd.read_parquet(source.artifact_path)
    if _file_sha256(source.artifact_path) != source.artifact_sha256:
        raise ValueError(f"{source.kind} artifact izmenilsya vo vremya parquet read")
    _require_exact_columns(frame, expected_columns, source.kind)
    if len(frame) != source.rows:
        raise ValueError(f"{source.kind} factual rows ne ravny manifest rows")
    manifest_columns = tuple(source.manifest_payload.get("columns", ()))
    if manifest_columns != tuple(expected_columns):
        raise ValueError(f"{source.kind} manifest columns ne exact schema")
    return frame


@dataclass(frozen=True, slots=True)
class V8EvaluationCalendarSession:
    """Odin sealed D->next factual economic-session i settlement transition."""

    sequence_id: int
    decision_session_date: date
    decision_at: datetime
    entry_effective_session_date: date
    calendar_known_at: datetime
    settlement_candle_opened_at: datetime
    settlement_candle_closed_at: datetime
    settlement_at: datetime
    accounting_as_of: datetime
    source_sha256: str

    def __post_init__(self) -> None:
        """Fiksiruet D18:50, next-session identity i post-window settlement."""
        if (
            isinstance(self.sequence_id, bool)
            or not isinstance(self.sequence_id, int)
            or self.sequence_id < 0
        ):
            raise ValueError("calendar sequence_id dolzhen byt' nonnegative int")
        decision_date = _require_date(self.decision_session_date, "decision_session_date")
        effective_date = _require_date(
            self.entry_effective_session_date,
            "entry_effective_session_date",
        )
        decision_at = _timestamp(self.decision_at, "calendar decision_at")
        local_decision = decision_at.astimezone(MOSCOW_TIMEZONE)
        if local_decision.date() != decision_date or local_decision.time().replace(
            tzinfo=None
        ) != time(18, 50):
            raise ValueError("calendar decision dolzhen byt' D 18:50 Moscow")
        if effective_date <= decision_date:
            raise ValueError("entry effective session dolzhna byt' factual posle D")
        known_at = _timestamp(self.calendar_known_at, "calendar_known_at")
        if known_at > decision_at:
            raise ValueError("calendar mapping dolzhen byt' izvesten na D")
        settlement_open = _timestamp(
            self.settlement_candle_opened_at,
            "settlement_candle_opened_at",
        )
        settlement_close = _timestamp(
            self.settlement_candle_closed_at,
            "settlement_candle_closed_at",
        )
        if settlement_close - settlement_open != timedelta(minutes=10):
            raise ValueError("settlement candle dolzhna byt' exact 10m")
        if settlement_close <= decision_at + timedelta(minutes=30):
            raise ValueError("settlement candle dolzhna byt' posle primary window")
        settlement_at = _timestamp(self.settlement_at, "settlement_at")
        if (
            settlement_at.astimezone(MOSCOW_TIMEZONE).date() != effective_date
            or settlement_at <= settlement_close
        ):
            raise ValueError(
                "settlement timestamp dolzhen byt' v economic effective session "
                "i posle factual candle"
            )
        accounting_as_of = _timestamp(self.accounting_as_of, "accounting_as_of")
        if accounting_as_of < settlement_at:
            raise ValueError("accounting_as_of ne mozhet byt' ranshe settlement")
        object.__setattr__(self, "decision_session_date", decision_date)
        object.__setattr__(self, "entry_effective_session_date", effective_date)
        object.__setattr__(self, "decision_at", decision_at)
        object.__setattr__(self, "calendar_known_at", known_at)
        object.__setattr__(self, "settlement_candle_opened_at", settlement_open)
        object.__setattr__(self, "settlement_candle_closed_at", settlement_close)
        object.__setattr__(self, "settlement_at", settlement_at)
        object.__setattr__(self, "accounting_as_of", accounting_as_of)
        object.__setattr__(
            self,
            "source_sha256",
            _require_sha256(self.source_sha256, "calendar source_sha256"),
        )

    @property
    def entry_common_session_sequence_id(self) -> int:
        """Vozvrashchaet exact i+1 common economic-session identifier."""
        return self.sequence_id + 1


@dataclass(frozen=True, slots=True)
class V8LoadedEvaluationInputs:
    """Target-free proverennye raw tables do construction typed bundle."""

    verified: V8VerifiedEvaluationSources
    base_predictions: pd.DataFrame
    enrichment: pd.DataFrame
    active_map: pd.DataFrame
    spec_proxy: pd.DataFrame
    candles: pd.DataFrame
    calendar: tuple[V8EvaluationCalendarSession, ...]


@dataclass(frozen=True, slots=True)
class V8DecisionEligibilityAudit:
    """Razdelyaet model-input validity, contract activity i executable mask."""

    decision_at: datetime
    asset_id: str
    model_input_valid: bool
    entry_contract_active: bool
    executable_asset_mask: bool
    calendar_span_known_at_d: bool
    expiration_date: date
    nominal_exit_effective_session_date: date | None
    nominal_span_eligible: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Dokazyvaet conjunction i stable eligibility reason accounting."""
        object.__setattr__(
            self,
            "decision_at",
            _timestamp(self.decision_at, "eligibility decision_at"),
        )
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("eligibility asset vne exact universe")
        for name in (
            "model_input_valid",
            "entry_contract_active",
            "executable_asset_mask",
            "calendar_span_known_at_d",
            "nominal_span_eligible",
        ):
            _strict_bool(getattr(self, name), name)
        expected_mask = self.model_input_valid and self.entry_contract_active
        if self.executable_asset_mask != expected_mask:
            raise ValueError("executable mask dolzhen byt' base_valid AND active_map")
        expiration = _require_date(self.expiration_date, "eligibility expiration_date")
        object.__setattr__(self, "expiration_date", expiration)
        if self.nominal_exit_effective_session_date is not None:
            nominal_exit = _require_date(
                self.nominal_exit_effective_session_date,
                "nominal_exit_effective_session_date",
            )
            object.__setattr__(
                self,
                "nominal_exit_effective_session_date",
                nominal_exit,
            )
        expected_nominal = bool(
            expected_mask
            and self.calendar_span_known_at_d
            and self.nominal_exit_effective_session_date is not None
            and expiration >= self.nominal_exit_effective_session_date
        )
        if self.nominal_span_eligible != expected_nominal:
            raise ValueError("nominal eligibility ne sootvetstvuet sealed conjunction")
        if not self.reason_codes:
            raise ValueError("eligibility audit trebuet minimum odin reason code")


@dataclass(frozen=True, slots=True)
class V8EvaluationReadinessAudit:
    """Pre-context counters/reasons, dostupnye dazhe pri fail-closed preparation."""

    source_identity_sha256: str
    rows: tuple[V8DecisionEligibilityAudit, ...]
    model_input_invalid_count: int = field(init=False)
    active_contract_inactive_count: int = field(init=False)
    validity_activity_mismatch_count: int = field(init=False)
    executable_asset_count: int = field(init=False)
    audit_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Schitaet exact counters bez numeric prediction/context access."""
        object.__setattr__(
            self,
            "source_identity_sha256",
            _require_sha256(self.source_identity_sha256, "source_identity_sha256"),
        )
        rows = tuple(self.rows)
        if len({(item.decision_at, item.asset_id) for item in rows}) != len(rows):
            raise ValueError("readiness audit soderzhit duplicate decision/asset")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(
            self,
            "model_input_invalid_count",
            sum(not item.model_input_valid for item in rows),
        )
        object.__setattr__(
            self,
            "active_contract_inactive_count",
            sum(not item.entry_contract_active for item in rows),
        )
        object.__setattr__(
            self,
            "validity_activity_mismatch_count",
            sum(item.model_input_valid != item.entry_contract_active for item in rows),
        )
        object.__setattr__(
            self,
            "executable_asset_count",
            sum(item.executable_asset_mask for item in rows),
        )
        object.__setattr__(
            self,
            "audit_sha256",
            _payload_sha256(
                {
                    "source_identity_sha256": self.source_identity_sha256,
                    "rows": rows,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class V8PreparedEvaluation:
    """Immutable rezultat verify+PIT join do lyubogo PnL calculation."""

    verified: V8VerifiedEvaluationSources
    bundle: V8SealedEvaluationInputBundle
    calendar: tuple[V8EvaluationCalendarSession, ...]
    readiness_audit: V8EvaluationReadinessAudit
    trusted_candle_index: V8TrustedCandleIndex = field(repr=False)
    prepared_identity_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Svyazyvaet calendar/source/bundle identity bez caller metrics."""
        if not self.calendar:
            raise ValueError("prepared evaluation trebuet calendar")
        if tuple(item.sequence_id for item in self.calendar) != tuple(range(len(self.calendar))):
            raise ValueError("prepared calendar sequence ne contiguous")
        if tuple(item.decision_at for item in self.calendar) != tuple(
            item.context.decision_at for item in self.bundle.predictions
        ):
            raise ValueError("prepared calendar/prediction decisions mismatch")
        for left, right in zip(self.calendar, self.calendar[1:], strict=False):
            if left.entry_effective_session_date != right.decision_session_date:
                raise ValueError("prepared calendar soderzhit factual session omission")
            if left.settlement_at >= right.decision_at:
                raise ValueError("prior economic settlement dolzhen byt' do next D")
        if self.bundle.calendar_sha256 != self.verified.source("calendar").artifact_sha256:
            raise ValueError("prepared bundle calendar SHA mismatch")
        if self.bundle.market_data_sha256 != self.verified.source("moex_10m").artifact_sha256:
            raise ValueError("prepared bundle market SHA mismatch")
        trusted = self.trusted_candle_index
        source = self.verified.source("moex_10m")
        if type(trusted) is not _V8AuthoritativeCandleIndex:
            raise TypeError("prepared evaluation trebuet authoritative candle capability")
        if (
            trusted.trust_status is not V8CandleTrustStatus.AUTHORITATIVE
            or trusted.evaluation_bundle_sha256 != self.bundle.evaluation_bundle_sha256
            or trusted.market_data_sha256 != source.artifact_sha256
            or trusted.source_identity_sha256 != self.verified.source_identity_sha256
            or trusted.source_manifest_sha256 != source.manifest_sha256
            or trusted.artifact_bytes != source.artifact_bytes
            or trusted.row_count != source.rows
            or trusted.candles != self.bundle.candles
        ):
            raise ValueError("prepared trusted candle artifact/coverage identity mismatch")
        if self.readiness_audit.source_identity_sha256 != self.verified.source_identity_sha256:
            raise ValueError("prepared readiness/source identity mismatch")
        if self.readiness_audit.model_input_invalid_count:
            raise V8EvaluationBlockedError(
                "prepared bundle ne mozhet soderzhat' model-invalid context rows"
            )
        payload = {
            "source_identity_sha256": self.verified.source_identity_sha256,
            "evaluation_bundle_sha256": self.bundle.evaluation_bundle_sha256,
            "trusted_candle_panel_sha256": trusted.candle_panel_sha256,
            "calendar": self.calendar,
            "readiness_audit_sha256": self.readiness_audit.audit_sha256,
        }
        object.__setattr__(self, "prepared_identity_sha256", _payload_sha256(payload))


def _read_verified_json(source: V8VerifiedEvaluationSource) -> dict[str, Any]:
    """Chitaet JSON tol'ko posle byte seal i rekursivnoi target/2026 proverki."""
    if source.artifact_path.suffix.lower() != ".json":
        raise ValueError(f"{source.kind} artifact dolzhen byt' JSON")
    if _file_sha256(source.artifact_path) != source.artifact_sha256:
        raise ValueError(f"{source.kind} artifact izmenilsya pered JSON read")
    payload = _read_json_object(source.artifact_path)
    if _file_sha256(source.artifact_path) != source.artifact_sha256:
        raise ValueError(f"{source.kind} artifact izmenilsya vo vremya JSON read")
    _scan_json_safety(payload, source.kind)
    return payload


def _validate_checkpoint_artifact(
    source: V8VerifiedEvaluationSource,
    payload: Mapping[str, Any],
) -> None:
    """Dokazyvaet exact 5-fold x 3-seed completed checkpoint inventory."""
    rows = payload.get("checkpoints")
    if not isinstance(rows, list) or len(rows) != V8_REQUIRED_COMPLETED_CHECKPOINTS:
        raise V8EvaluationBlockedError("checkpoint artifact ne soderzhit exact 15 rows")
    identities: set[tuple[int, int]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "fold_id",
            "seed",
            "status",
            "checkpoint_sha256",
        }:
            raise ValueError("checkpoint identity row schema mismatch")
        if row["status"] != "completed":
            raise V8EvaluationBlockedError("checkpoint artifact soderzhit incomplete row")
        fold = row["fold_id"]
        seed = row["seed"]
        if isinstance(fold, bool) or not isinstance(fold, int) or fold not in range(5):
            raise ValueError("checkpoint fold_id vne exact 0..4")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed not in range(3):
            raise ValueError("checkpoint seed vne exact 0..2")
        _require_sha256(row["checkpoint_sha256"], "checkpoint_sha256")
        identities.add((fold, seed))
    expected = {(fold, seed) for fold in range(5) for seed in range(3)}
    if identities != expected:
        raise V8EvaluationBlockedError("checkpoint artifact ne dokazyvaet 5x3 matrix")
    if source.rows != len(rows):
        raise ValueError("checkpoint artifact rows mismatch")


def _calendar_from_payload(
    source: V8VerifiedEvaluationSource,
    payload: Mapping[str, Any],
) -> tuple[V8EvaluationCalendarSession, ...]:
    """Stroit strogo contiguous factual calendar bez duplicate ili omission."""
    if set(payload) != {"format", "columns", "sessions"}:
        raise ValueError("calendar artifact root schema mismatch")
    if payload["format"] != "market-lab-futures-v8-evaluation-calendar-v1":
        raise ValueError("calendar artifact format mismatch")
    if tuple(payload["columns"]) != V8_CALENDAR_COLUMNS:
        raise ValueError("calendar artifact columns mismatch")
    rows = payload["sessions"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("calendar sessions dolzhny byt' nonempty list")
    if len(rows) != source.rows:
        raise ValueError("calendar factual rows ne ravny manifest rows")
    result: list[V8EvaluationCalendarSession] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(V8_CALENDAR_COLUMNS):
            raise ValueError("calendar session exact schema mismatch")
        result.append(
            V8EvaluationCalendarSession(
                sequence_id=row["sequence_id"],
                decision_session_date=_require_date(
                    row["decision_session_date"],
                    "calendar decision_session_date",
                ),
                decision_at=_timestamp(row["decision_at"], "calendar decision_at"),
                entry_effective_session_date=_require_date(
                    row["entry_effective_session_date"],
                    "calendar entry_effective_session_date",
                ),
                calendar_known_at=_timestamp(
                    row["calendar_known_at"],
                    "calendar_known_at",
                ),
                settlement_candle_opened_at=_timestamp(
                    row["settlement_candle_opened_at"],
                    "settlement_candle_opened_at",
                ),
                settlement_candle_closed_at=_timestamp(
                    row["settlement_candle_closed_at"],
                    "settlement_candle_closed_at",
                ),
                settlement_at=_timestamp(row["settlement_at"], "settlement_at"),
                accounting_as_of=_timestamp(
                    row["accounting_as_of"],
                    "accounting_as_of",
                ),
                source_sha256=row["source_sha256"],
            )
        )
    calendar = tuple(result)
    if tuple(item.sequence_id for item in calendar) != tuple(range(len(calendar))):
        raise ValueError("calendar sequence_id dolzhny byt' exact contiguous 0..N-1")
    if len({item.decision_session_date for item in calendar}) != len(calendar):
        raise ValueError("calendar soderzhit duplicate decision session")
    if len({item.entry_effective_session_date for item in calendar}) != len(calendar):
        raise ValueError("calendar soderzhit duplicate effective session")
    if len({item.decision_at for item in calendar}) != len(calendar):
        raise ValueError("calendar soderzhit duplicate decision_at")
    for left, right in zip(calendar, calendar[1:], strict=False):
        if left.entry_effective_session_date != right.decision_session_date:
            raise ValueError("calendar omission: next factual D ne raven prior effective")
        if right.decision_at <= left.decision_at or right.settlement_at <= left.settlement_at:
            raise ValueError("calendar chronology narushena")
        if left.settlement_at >= right.decision_at:
            raise ValueError("calendar settlement dolzhen byt' do next decision")
    return calendar


def load_verified_v8_evaluation_inputs(
    verified: V8VerifiedEvaluationSources,
) -> V8LoadedEvaluationInputs:
    """Chitaet raw target-free inputs tol'ko posle polnogo source/code verify."""
    checkpoint_source = verified.source("checkpoint_identities")
    _validate_checkpoint_artifact(
        checkpoint_source,
        _read_verified_json(checkpoint_source),
    )
    assembly = _read_verified_json(verified.source("assembly"))
    if not isinstance(assembly.get("arrays", []), list):
        raise ValueError("assembly arrays dolzhny byt' list")
    if len(assembly.get("arrays", [])) != verified.source("assembly").rows:
        raise ValueError("assembly rows mismatch")
    base = _read_verified_frame(
        verified.source("base_predictions"),
        V8_BASE_PREDICTION_COLUMNS,
    )
    enrichment = _read_verified_frame(
        verified.source("enrichment"),
        V8_ENRICHMENT_COLUMNS,
    )
    active_map = _read_verified_frame(
        verified.source("active_map"),
        V8_ACTIVE_MAP_COLUMNS,
    )
    spec_proxy = _read_verified_frame(
        verified.source("spec_proxy"),
        V8_SPEC_PROXY_COLUMNS,
    )
    candles = _read_verified_frame(
        verified.source("moex_10m"),
        V8_TEN_MINUTE_COLUMNS,
    )
    calendar_source = verified.source("calendar")
    calendar = _calendar_from_payload(
        calendar_source,
        _read_verified_json(calendar_source),
    )
    return V8LoadedEvaluationInputs(
        verified=verified,
        base_predictions=base,
        enrichment=enrichment,
        active_map=active_map,
        spec_proxy=spec_proxy,
        candles=candles,
        calendar=calendar,
    )


def _optional_pit_observation(
    row: Mapping[str, Any],
    channel: str,
    decision_at: datetime,
) -> PointInTimeObservation | None:
    """Stroit all-or-none PIT release s publication <= D i polnoi provenance."""
    names = tuple(
        f"{channel}_{suffix}"
        for suffix in (
            "value",
            "published_at",
            "source_id",
            "observation_id",
            "source_sha256",
        )
    )
    values = tuple(row[name] for name in names)
    missing = tuple(pd.isna(value) for value in values)
    if all(missing):
        return None
    if any(missing):
        raise ValueError(f"{channel} PIT provenance dolzhna byt' all-or-none")
    published_at = _timestamp(row[f"{channel}_published_at"], f"{channel}.published_at")
    if published_at > decision_at:
        raise ValueError(f"{channel} publication posle decision D")
    return PointInTimeObservation(
        value=_finite_number(row[f"{channel}_value"], f"{channel}.value"),
        published_at=published_at,
        source_id=str(row[f"{channel}_source_id"]),
        observation_id=str(row[f"{channel}_observation_id"]),
        source_sha256=_require_sha256(
            row[f"{channel}_source_sha256"],
            f"{channel}.source_sha256",
        ),
    )


def _build_contract_specs(
    frame: pd.DataFrame,
    calendar: Sequence[V8EvaluationCalendarSession],
) -> tuple[V8ContractSpec, ...]:
    """Stroit exact daily contract/session specs bez stale/future fallback."""
    expected_sizing = {
        item.entry_effective_session_date: item.decision_session_date for item in calendar
    }
    rows: list[V8ContractSpec] = []
    seen: set[tuple[str, date]] = set()
    for record in frame.to_dict(orient="records"):
        effective = _require_date(record["session_date"], "spec session_date")
        sizing_observed = _require_date(
            record["sizing_observed_session_date"],
            "spec sizing_observed_session_date",
        )
        if effective not in expected_sizing:
            raise ValueError("spec effective session vne sealed calendar")
        if sizing_observed != expected_sizing[effective]:
            raise ValueError("spec lag-1 session ne ravna factual prior D")
        contract_id = str(record["contract_id"])
        key = (contract_id, effective)
        if key in seen:
            raise ValueError("spec proxy soderzhit duplicate contract/session")
        seen.add(key)
        rows.append(
            V8ContractSpec(
                asset_id=str(record["asset"]),
                contract_id=contract_id,
                effective_session_date=effective,
                sizing_observed_session_date=sizing_observed,
                sizing_known_at=_timestamp(record["sizing_known_at"], "sizing_known_at"),
                accounting_known_at=_timestamp(
                    record["accounting_known_at"],
                    "accounting_known_at",
                ),
                sizing_price_multiplier=_finite_number(
                    record["sizing_point_value"],
                    "sizing_point_value",
                    positive=True,
                ),
                accounting_price_multiplier=_finite_number(
                    record["realized_accounting_point_value"],
                    "realized_accounting_point_value",
                    positive=True,
                ),
                initial_margin_per_contract=_finite_number(
                    record["modeled_initial_margin"],
                    "modeled_initial_margin",
                    positive=True,
                ),
                fee_per_contract=_finite_number(
                    record["conservative_fee_per_side"],
                    "conservative_fee_per_side",
                ),
                source_sha256=_require_sha256(
                    record["source_sha256"],
                    "spec source_sha256",
                ),
                sizing_lag_sessions=_strict_int(
                    record["sizing_lag_sessions"],
                    "sizing_lag_sessions",
                    nonnegative=True,
                ),
                sizing_status=str(record["sizing_status"]),
                accounting_status=str(record["accounting_status"]),
            )
        )
    return tuple(rows)


def _optional_price(value: object, label: str) -> float | None:
    """Chitaet factual nullable OHLC bez imputacii."""
    return None if pd.isna(value) else _finite_number(value, label, positive=True)


def _optional_volume(value: object) -> int | None:
    """Chitaet nullable integer volume bez fractional coercion."""
    if pd.isna(value):
        return None
    numeric = _finite_number(value, "volume")
    if numeric < 0.0 or not numeric.is_integer():
        raise ValueError("volume dolzhen byt' nonnegative integer")
    return int(numeric)


def _build_candles(frame: pd.DataFrame) -> tuple[TenMinuteCandle, ...]:
    """Stroit raw factual candles bez synthetic OHLC/volume fallback."""
    rows: list[TenMinuteCandle] = []
    seen: set[tuple[str, datetime]] = set()
    for record in frame.to_dict(orient="records"):
        contract_id = str(record["contract_id"])
        opened_at = _timestamp(record["opened_at"], "candle opened_at")
        key = (contract_id, opened_at)
        if key in seen:
            raise ValueError("10m panel soderzhit duplicate contract/opened_at")
        seen.add(key)
        rows.append(
            TenMinuteCandle(
                contract_id=contract_id,
                opened_at=opened_at,
                closed_at=_timestamp(record["closed_at"], "candle closed_at"),
                open_price=_optional_price(record["open"], "candle open"),
                high_price=_optional_price(record["high"], "candle high"),
                low_price=_optional_price(record["low"], "candle low"),
                close_price=_optional_price(record["close"], "candle close"),
                volume=_optional_volume(record["volume"]),
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True, init=False)
class _V8AuthoritativeCandleIndex(V8TrustedCandleIndex):
    """Full-panel capability, kotoryi sam rehashit verified moex artifact."""

    _candles: tuple[TenMinuteCandle, ...] = field(repr=False)
    _index: Mapping[tuple[str, datetime], TenMinuteCandle] = field(
        repr=False,
        compare=False,
    )
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

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        """Zapreshchaet module-level issuer; capability sozdaet tol'ko rebuild closure."""
        raise TypeError("authoritative candle capability ne imeet callable issuer")

    @property
    def candles(self) -> tuple[TenMinuteCandle, ...]:
        """Vozvrashchaet exact immutable artifact rows."""
        return self._candles

    @property
    def index(self) -> Mapping[tuple[str, datetime], TenMinuteCandle]:
        """Vozvrashchaet read-only complete-key lookup."""
        return self._index


def _validate_prediction_timing(record: Mapping[str, Any], decision_at: datetime) -> None:
    """Svyazyvaet original training windows s exact D18:50 schedule."""
    decision_date = _require_date(record["decision_date"], "prediction decision_date")
    if decision_date != decision_at.astimezone(MOSCOW_TIMEZONE).date():
        raise ValueError("prediction decision_date/decision_at mismatch")
    expected = {
        "capacity_window_open_at": decision_at + timedelta(minutes=10),
        "capacity_window_close_at": decision_at + timedelta(minutes=20),
        "execution_window_open_at": decision_at + timedelta(minutes=30),
        "execution_window_close_at": decision_at + timedelta(minutes=40),
    }
    for name, expected_value in expected.items():
        if _timestamp(record[name], f"prediction {name}") != expected_value:
            raise ValueError(f"prediction {name} ne sootvetstvuet sealed schedule")


def _prediction_row_index(
    frame: pd.DataFrame,
    label: str,
) -> dict[tuple[datetime, str], dict[str, Any]]:
    """Indeksiruet exact decision/asset rows bez duplicate."""
    result: dict[tuple[datetime, str], dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        decision_at = _timestamp(record["decision_at"], f"{label} decision_at")
        asset = str(record["asset"])
        key = (decision_at, asset)
        if key in result:
            raise ValueError(f"{label} soderzhit duplicate decision/asset")
        result[key] = record
    return result


def audit_loaded_v8_evaluation_readiness(
    loaded: V8LoadedEvaluationInputs,
) -> V8EvaluationReadinessAudit:
    """Audit'it validity/activity/maturity do chteniya nullable numeric outputs."""
    base_index = _prediction_row_index(loaded.base_predictions, "base_predictions")
    active_index = _prediction_row_index(loaded.active_map, "active_map")
    if set(base_index) != set(active_index):
        raise ValueError("base/active-map key coverage mismatch")
    calendar_by_decision = {item.decision_at: item for item in loaded.calendar}
    calendar_position = {item.decision_at: index for index, item in enumerate(loaded.calendar)}
    rows: list[V8DecisionEligibilityAudit] = []
    for decision_at, asset_id in sorted(base_index):
        if decision_at not in calendar_by_decision or asset_id not in V8_ASSET_IDS:
            raise ValueError("readiness key vne exact calendar/universe")
        base = base_index[(decision_at, asset_id)]
        active = active_index[(decision_at, asset_id)]
        model_valid = _strict_bool(base["asset_valid"], "asset_valid")
        contract_active = _strict_bool(active["asset_mask"], "asset_mask")
        position = calendar_position[decision_at]
        future_index = position + 5
        calendar_known = bool(
            future_index < len(loaded.calendar)
            and loaded.calendar[future_index].calendar_known_at <= decision_at
        )
        nominal_exit = (
            loaded.calendar[future_index].entry_effective_session_date
            if future_index < len(loaded.calendar)
            else None
        )
        expiration = _require_date(active["expiration_date"], "expiration_date")
        executable = model_valid and contract_active
        nominal_eligible = bool(
            executable
            and calendar_known
            and nominal_exit is not None
            and expiration >= nominal_exit
        )
        reasons: list[str] = []
        if not model_valid:
            reasons.append("model_input_invalid")
        if not contract_active:
            reasons.append("entry_contract_inactive")
        if not calendar_known:
            reasons.append("nominal_calendar_span_not_known_at_d")
        if nominal_exit is not None and expiration < nominal_exit:
            reasons.append("contract_matures_before_nominal_exit")
        if nominal_eligible:
            reasons.append("executable_nominal_span_eligible")
        elif executable:
            reasons.append("executable_but_nominal_span_ineligible")
        rows.append(
            V8DecisionEligibilityAudit(
                decision_at=decision_at,
                asset_id=asset_id,
                model_input_valid=model_valid,
                entry_contract_active=contract_active,
                executable_asset_mask=executable,
                calendar_span_known_at_d=calendar_known,
                expiration_date=expiration,
                nominal_exit_effective_session_date=nominal_exit,
                nominal_span_eligible=nominal_eligible,
                reason_codes=tuple(reasons),
            )
        )
    return V8EvaluationReadinessAudit(
        source_identity_sha256=loaded.verified.source_identity_sha256,
        rows=tuple(rows),
    )


def inspect_v8_evaluation_readiness(
    request: V8EvaluationVerificationRequest,
) -> V8EvaluationReadinessAudit:
    """Publikuet counters/reasons bez construction CausalDecisionContext ili PnL."""
    verified = verify_v8_evaluation_sources(request)
    loaded = load_verified_v8_evaluation_inputs(verified)
    return audit_loaded_v8_evaluation_readiness(loaded)


def _build_target_free_predictions(
    loaded: V8LoadedEvaluationInputs,
    readiness: V8EvaluationReadinessAudit,
) -> tuple[V8TargetFreePrediction, ...]:
    """Deterministichno join'it prediction/enrichment/active-map po exact PIT keys."""
    base_index = _prediction_row_index(loaded.base_predictions, "base_predictions")
    enrichment_index = _prediction_row_index(loaded.enrichment, "enrichment")
    active_index = _prediction_row_index(loaded.active_map, "active_map")
    if set(base_index) != set(enrichment_index) or set(base_index) != set(active_index):
        raise ValueError("prediction/enrichment/active-map key coverage mismatch")
    calendar_by_decision = {item.decision_at: item for item in loaded.calendar}
    base_decisions = tuple(sorted({key[0] for key in base_index}))
    if base_decisions != tuple(item.decision_at for item in loaded.calendar):
        raise ValueError("predictions dolzhny exact pokryvat' common calendar decisions")
    if len(base_index) != len(base_decisions) * len(V8_ASSET_IDS):
        raise ValueError("predictions trebuyut exact four assets na kazhdyi D")
    prediction_sha = loaded.verified.source("base_predictions").artifact_sha256
    eligibility_by_key = {(item.decision_at, item.asset_id): item for item in readiness.rows}
    predictions: list[V8TargetFreePrediction] = []
    for decision_at in base_decisions:
        session = calendar_by_decision[decision_at]
        assets: list[CausalAssetSnapshot] = []
        contracts: list[V8AssetContractSnapshot] = []
        factor_locations: set[float] = set()
        factor_scales: set[float] = set()
        factor_scores: set[float] = set()
        for asset_id in V8_ASSET_IDS:
            key = (decision_at, asset_id)
            if key not in base_index:
                raise ValueError("prediction D ne imeet exact BR/MIX/RI/SI universe")
            base = base_index[key]
            enrichment = enrichment_index[key]
            active = active_index[key]
            _validate_prediction_timing(base, decision_at)
            known_at = _timestamp(enrichment["known_at"], "enrichment known_at")
            contract_known = _timestamp(active["contract_known_at"], "contract_known_at")
            maturity_known = _timestamp(active["maturity_known_at"], "maturity_known_at")
            if (
                known_at > decision_at
                or contract_known > decision_at
                or maturity_known > decision_at
            ):
                raise ValueError("future market/contract/maturity observation posle D")
            entry_effective = _require_date(
                active["entry_effective_session_date"],
                "active-map entry_effective_session_date",
            )
            if entry_effective != session.entry_effective_session_date:
                raise ValueError("active-map economic session ne ravna calendar D->next")
            eligibility = eligibility_by_key[key]
            factor_location = _finite_number(base["factor_location"], "factor_location")
            factor_scale = _finite_number(
                base["factor_scale"],
                "factor_scale",
                positive=True,
            )
            factor_score = _finite_number(base["factor_score"], "factor_score")
            residual_location = _finite_number(
                base["residual_location"],
                "residual_location",
            )
            residual_score = _finite_number(
                base["residual_decision_score"],
                "residual_decision_score",
            )
            _finite_number(base["residual_scale"], "residual_scale", positive=True)
            _finite_number(base["direction_logit"], "direction_logit")
            factor_locations.add(factor_location)
            factor_scales.add(factor_scale)
            factor_scores.add(factor_score)
            pit = {
                channel: _optional_pit_observation(enrichment, channel, decision_at)
                for channel in V8_PIT_CHANNELS
            }
            assets.append(
                CausalAssetSnapshot(
                    asset_id=asset_id,
                    known_at=known_at,
                    factor_decision_score=factor_score,
                    residual_decision_score=residual_score,
                    residual_location=residual_location,
                    total_scale=_finite_number(
                        enrichment["total_scale"],
                        "total_scale",
                        positive=True,
                    ),
                    abstain_probability=_finite_number(
                        enrichment["abstain_probability"],
                        "abstain_probability",
                    ),
                    normal_probability=_finite_number(
                        enrichment["normal_probability"],
                        "normal_probability",
                    ),
                    trend_probability=_finite_number(
                        enrichment["trend_probability"],
                        "trend_probability",
                    ),
                    crash_probability=_finite_number(
                        enrichment["crash_probability"],
                        "crash_probability",
                    ),
                    close=_finite_number(enrichment["close"], "close", positive=True),
                    atr_20=_finite_number(enrichment["atr_20"], "atr_20", positive=True),
                    daily_volatility_20=_finite_number(
                        enrichment["daily_volatility_20"],
                        "daily_volatility_20",
                        positive=True,
                    ),
                    momentum_20=_finite_number(enrichment["momentum_20"], "momentum_20"),
                    range_position_20=_finite_number(
                        enrichment["range_position_20"],
                        "range_position_20",
                    ),
                    volatility_ratio_20=_finite_number(
                        enrichment["volatility_ratio_20"],
                        "volatility_ratio_20",
                    ),
                    volume_ratio_20=_finite_number(
                        enrichment["volume_ratio_20"],
                        "volume_ratio_20",
                    ),
                    market_data_sha256=_require_sha256(
                        enrichment["market_data_sha256"],
                        "market_data_sha256",
                    ),
                    carry_z=pit["carry_z"],
                    cftc_crowd_z=pit["cftc_crowd_z"],
                    key_rate_change_z=pit["key_rate_change_z"],
                    usd_rub_return_z=pit["usd_rub_return_z"],
                )
            )
            contracts.append(
                V8AssetContractSnapshot(
                    asset_id=asset_id,
                    contract_id=str(active["contract_id"]),
                    entry_effective_session_date=entry_effective,
                    known_at=contract_known,
                    asset_mask=eligibility.executable_asset_mask,
                    nominal_span_eligible=eligibility.nominal_span_eligible,
                    source_sha256=_require_sha256(
                        active["source_sha256"],
                        "active-map source_sha256",
                    ),
                )
            )
        if len(factor_locations) != 1 or len(factor_scales) != 1 or len(factor_scores) != 1:
            raise ValueError("factor output dolzhen byt' edinym na cross-asset D")
        context = CausalDecisionContext(
            decision_at=decision_at,
            assets=tuple(assets),
            prediction_sha256=prediction_sha,
        )
        predictions.append(
            V8TargetFreePrediction(
                context=context,
                factor_location=next(iter(factor_locations)),
                factor_scale=next(iter(factor_scales)),
                contracts=tuple(contracts),
            )
        )
    return tuple(predictions)


def _prepare_verified_v8_evaluation(
    verified: V8VerifiedEvaluationSources,
) -> V8PreparedEvaluation:
    """Stroit target-free sealed bundle iz byte-verified raw PIT sources."""
    loaded = load_verified_v8_evaluation_inputs(verified)
    readiness = audit_loaded_v8_evaluation_readiness(loaded)
    if readiness.model_input_invalid_count:
        raise V8EvaluationBlockedError(
            "validity-aware aggressive catalog unavailable: "
            f"model_input_invalid_count={readiness.model_input_invalid_count}; "
            "nullable outputs ne imputiruyutsya"
        )
    predictions = _build_target_free_predictions(loaded, readiness)
    specs = _build_contract_specs(loaded.spec_proxy, loaded.calendar)
    candles = _build_candles(loaded.candles)
    bundle = V8SealedEvaluationInputBundle(
        predictions=predictions,
        contract_specs=specs,
        candles=candles,
        market_data_sha256=verified.source("moex_10m").artifact_sha256,
        calendar_sha256=verified.source("calendar").artifact_sha256,
    )

    def issue_authoritative_candle_index() -> _V8AuthoritativeCandleIndex:
        """Local no-argument issuer iz canonical verified/bundle closure."""
        source = verified.source("moex_10m")
        source_candles = tuple(
            sorted(
                _build_candles(
                    _read_verified_frame(source, V8_TEN_MINUTE_COLUMNS)
                ),
                key=lambda item: (item.opened_at, item.contract_id),
            )
        )
        if source.artifact_sha256 != bundle.market_data_sha256:
            raise ValueError("authoritative candle artifact/bundle market SHA mismatch")
        if source.rows != len(source_candles) or source_candles != bundle.candles:
            raise ValueError("authoritative candle full artifact coverage mismatch")
        index = {(item.contract_id, item.opened_at): item for item in source_candles}
        if len(index) != len(source_candles):
            raise ValueError("authoritative candle artifact soderzhit duplicate key")
        sorted_keys = tuple(sorted(index, key=lambda item: (item[1], item[0])))
        key_set_hash = canonical_sha256(sorted_keys)
        coverage_hash = canonical_sha256(
            {
                "source_identity_sha256": verified.source_identity_sha256,
                "source_manifest_sha256": source.manifest_sha256,
                "artifact_sha256": source.artifact_sha256,
                "artifact_bytes": source.artifact_bytes,
                "artifact_rows": source.rows,
                "complete_key_set": sorted_keys,
            }
        )
        panel_hash = canonical_sha256(
            {
                "evaluation_bundle_sha256": bundle.evaluation_bundle_sha256,
                "market_data_sha256": bundle.market_data_sha256,
                "source_identity_sha256": verified.source_identity_sha256,
                "source_manifest_sha256": source.manifest_sha256,
                "artifact_bytes": source.artifact_bytes,
                "artifact_rows": source.rows,
                "coverage_sha256": coverage_hash,
                "candles": source_candles,
            }
        )
        capability = object.__new__(_V8AuthoritativeCandleIndex)
        object.__setattr__(capability, "_candles", source_candles)
        object.__setattr__(capability, "_index", MappingProxyType(index))
        object.__setattr__(
            capability,
            "trust_status",
            V8CandleTrustStatus.AUTHORITATIVE,
        )
        object.__setattr__(capability, "candle_panel_sha256", panel_hash)
        object.__setattr__(capability, "coverage_sha256", coverage_hash)
        object.__setattr__(capability, "key_set_sha256", key_set_hash)
        object.__setattr__(
            capability,
            "evaluation_bundle_sha256",
            bundle.evaluation_bundle_sha256,
        )
        object.__setattr__(
            capability,
            "market_data_sha256",
            source.artifact_sha256,
        )
        object.__setattr__(
            capability,
            "source_identity_sha256",
            verified.source_identity_sha256,
        )
        object.__setattr__(
            capability,
            "source_manifest_sha256",
            source.manifest_sha256,
        )
        object.__setattr__(capability, "artifact_bytes", source.artifact_bytes)
        object.__setattr__(capability, "row_count", source.rows)
        return capability

    trusted_candle_index = issue_authoritative_candle_index()
    return V8PreparedEvaluation(
        verified=verified,
        bundle=bundle,
        calendar=loaded.calendar,
        readiness_audit=readiness,
        trusted_candle_index=trusted_candle_index,
    )


def _verification_request_from_verified(
    verified: V8VerifiedEvaluationSources,
) -> V8EvaluationVerificationRequest:
    """Vosstanavlivaet rehash request iz immutable verified identities."""
    return V8EvaluationVerificationRequest(
        project_root=verified.project_root,
        sources=tuple(
            V8EvaluationSourceSeal(
                kind=item.kind,
                manifest_path=item.manifest_path,
                manifest_sha256=item.manifest_sha256,
                artifact_path=item.artifact_path,
                artifact_sha256=item.artifact_sha256,
                rows=item.rows,
            )
            for item in verified.sources
        ),
        expected_code_identity_sha256=verified.code_identity["code_identity_sha256"],
    )


def prepare_verified_v8_evaluation(
    verified: V8VerifiedEvaluationSources,
) -> V8PreparedEvaluation:
    """Rehashiruet caller verified object pered lyubym table/context read."""
    reverified = verify_v8_evaluation_sources(_verification_request_from_verified(verified))
    return _prepare_verified_v8_evaluation(reverified)


def prepare_v8_evaluation(
    request: V8EvaluationVerificationRequest,
) -> V8PreparedEvaluation:
    """Publikuet edinyi verify-then-read-then-PIT-join API do PnL."""
    return _prepare_verified_v8_evaluation(verify_v8_evaluation_sources(request))


def _reverify_prepared_for_run(
    prepared: V8PreparedEvaluation,
) -> V8PreparedEvaluation:
    """Rehashit sources i polnost'yu canonical rebuildit Prepared pered run."""
    if type(prepared) is not V8PreparedEvaluation:
        raise TypeError("prepared dolzhen byt' exact V8PreparedEvaluation")
    reverified = verify_v8_evaluation_sources(
        _verification_request_from_verified(prepared.verified)
    )
    canonical = _prepare_verified_v8_evaluation(reverified)
    supplied_components = {
        "verified": prepared.verified,
        "bundle": prepared.bundle,
        "calendar": prepared.calendar,
        "readiness_audit": prepared.readiness_audit,
        "trusted_candle_index": prepared.trusted_candle_index,
        "prepared_identity_sha256": prepared.prepared_identity_sha256,
    }
    canonical_components = {
        "verified": canonical.verified,
        "bundle": canonical.bundle,
        "calendar": canonical.calendar,
        "readiness_audit": canonical.readiness_audit,
        "trusted_candle_index": canonical.trusted_candle_index,
        "prepared_identity_sha256": canonical.prepared_identity_sha256,
    }
    drift = tuple(
        name
        for name, canonical_value in canonical_components.items()
        if supplied_components[name] != canonical_value
    )
    if drift:
        raise ValueError(f"prepared canonical rebuild mismatch: {drift}")
    return canonical


@dataclass(frozen=True, slots=True)
class V8EvaluationFailureEvent:
    """Structured fail-closed event bez skrytogo fallback ili synthetic price."""

    phase: str
    code: str
    message: str
    strategy_id: str | None = None
    scenario_id: V8ScenarioId | None = None
    decision_at: datetime | None = None
    metric_critical_increment: int = 0
    event_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Proveryaet stable failure identity i explicit metric effect."""
        for name in ("phase", "code", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"failure {name} dolzhen byt' nonempty string")
        if self.strategy_id is not None and self.strategy_id not in V8_STRATEGY_IDS:
            raise ValueError("failure strategy_id vne exact 11")
        if self.scenario_id is not None:
            object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        if self.decision_at is not None:
            object.__setattr__(
                self,
                "decision_at",
                _timestamp(self.decision_at, "failure decision_at"),
            )
        if (
            isinstance(self.metric_critical_increment, bool)
            or not isinstance(self.metric_critical_increment, int)
            or self.metric_critical_increment < 0
        ):
            raise ValueError("metric_critical_increment dolzhen byt' nonnegative int")
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "event_sha256"
        }
        object.__setattr__(self, "event_sha256", _payload_sha256(payload))


@dataclass(frozen=True, slots=True)
class V8EvaluationRunResult:
    """Internal synthetic orchestration result s derivable metrics/gates only."""

    mode: V8EvaluationMode
    research_status: str
    prepared_identity_sha256: str
    source_identity_sha256: str
    code_identity_sha256: str
    prediction_sha256: str
    evaluation_bundle_sha256: str
    decision_rows: tuple[dict[str, Any], ...]
    orders: tuple[V8OrderBinding, ...]
    evidence: tuple[V8ScenarioExecutionEvidence, ...]
    ledger_matrix: V8EvaluationLedgerMatrix
    metrics: tuple[V8StrategyMetricsBundle, ...]
    gates_and_ranking: V8GateAndRanking
    failure_events: tuple[V8EvaluationFailureEvent, ...]
    result_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Zapreshchaet authoritative label i mixed identity v internal result."""
        mode = V8EvaluationMode(self.mode)
        if mode is not V8EvaluationMode.SYNTHETIC_TEST:
            raise ValueError("gotovyi result poka razreshen tol'ko dlya synthetic_test")
        if self.research_status != V8_SYNTHETIC_RESEARCH_STATUS:
            raise ValueError("synthetic result ne mozhet maskirovat'sya kak real PnL")
        object.__setattr__(self, "mode", mode)
        for name in (
            "prepared_identity_sha256",
            "source_identity_sha256",
            "code_identity_sha256",
            "prediction_sha256",
            "evaluation_bundle_sha256",
        ):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        if self.ledger_matrix.prediction_sha256 != self.prediction_sha256:
            raise ValueError("result ledger prediction SHA mismatch")
        if self.ledger_matrix.evaluation_bundle_sha256 != self.evaluation_bundle_sha256:
            raise ValueError("result ledger bundle SHA mismatch")
        if (
            self.ledger_matrix.candle_trust_status
            is not V8CandleTrustStatus.AUTHORITATIVE
        ):
            raise ValueError("result ledger ne imeet authoritative candle trust root")
        if tuple(item.strategy_id for item in self.metrics) != V8_STRATEGY_IDS:
            raise ValueError("result metrics dolzhny byt' exact 11 strategy order")
        if any(item.prediction_sha256 != self.prediction_sha256 for item in self.metrics):
            raise ValueError("result metrics prediction SHA mismatch")
        if any(
            item.evaluation_bundle_sha256 != self.evaluation_bundle_sha256 for item in self.metrics
        ):
            raise ValueError("result metrics bundle SHA mismatch")
        payload = {
            "mode": mode,
            "research_status": self.research_status,
            "prepared_identity_sha256": self.prepared_identity_sha256,
            "source_identity_sha256": self.source_identity_sha256,
            "code_identity_sha256": self.code_identity_sha256,
            "prediction_sha256": self.prediction_sha256,
            "evaluation_bundle_sha256": self.evaluation_bundle_sha256,
            "decision_rows": self.decision_rows,
            "orders": self.orders,
            "evidence": self.evidence,
            "ledger_matrix": self.ledger_matrix,
            "metrics": self.metrics,
            "gates_and_ranking": self.gates_and_ranking,
            "failure_events": self.failure_events,
        }
        object.__setattr__(self, "result_sha256", _payload_sha256(payload))


def _reprioritize_bindings(
    bindings: Sequence[V8OrderBinding],
    *,
    first_priority: int,
) -> tuple[V8OrderBinding, ...]:
    """Naznachaet edinuyu exit-first priority space dlya odnogo factual window."""
    result: list[V8OrderBinding] = []
    for offset, binding in enumerate(bindings):
        request = replace(
            binding.request,
            allocation_priority=first_priority + offset,
        )
        result.append(replace(binding, request=request))
    return tuple(result)


def _settlement_marks(
    state: V8EventLedgerState,
    bindings: Sequence[V8OrderBinding],
    candle_index: Mapping[tuple[str, datetime], TenMinuteCandle],
    session: V8EvaluationCalendarSession,
) -> dict[str, float]:
    """Chitaet exact factual settlement close dlya old i potential new contracts."""
    contract_ids = {item.key.contract_id for item in state.positions}
    for binding in bindings:
        if binding.single_position is not None:
            contract_ids.add(binding.single_position.contract_id)
        if binding.old_roll_position is not None:
            contract_ids.add(binding.old_roll_position.contract_id)
        if binding.new_roll_position is not None:
            contract_ids.add(binding.new_roll_position.contract_id)
    marks: dict[str, float] = {}
    for contract_id in sorted(contract_ids):
        candle = candle_index.get((contract_id, session.settlement_candle_opened_at))
        if candle is None:
            raise V8EvaluationBlockedError(
                f"missing factual settlement candle: {contract_id} "
                f"{session.settlement_candle_opened_at.isoformat()}"
            )
        if candle.closed_at != session.settlement_candle_closed_at or candle.close_price is None:
            raise V8EvaluationBlockedError(f"unavailable exact settlement close: {contract_id}")
        marks[contract_id] = candle.close_price
    return marks


def _decision_rows(
    prepared: V8PreparedEvaluation,
    all_targets: Sequence[Sequence[V8SleeveTarget]],
) -> tuple[dict[str, Any], ...]:
    """Materializuet audit rows bez labels, returns ili caller metrics."""
    rows: list[dict[str, Any]] = []
    eligibility_by_key = {
        (item.decision_at, item.asset_id): item for item in prepared.readiness_audit.rows
    }
    for session, prediction, targets in zip(
        prepared.calendar,
        prepared.bundle.predictions,
        all_targets,
        strict=True,
    ):
        for strategy_id in V8_STRATEGY_IDS:
            strategy_targets = tuple(item for item in targets if item.strategy_id == strategy_id)
            rows.append(
                {
                    "sequence_id": session.sequence_id,
                    "decision_at": session.decision_at,
                    "entry_effective_session_date": (session.entry_effective_session_date),
                    "strategy_id": strategy_id,
                    "prediction_sha256": prediction.context.prediction_sha256,
                    "decision_input_sha256": prediction.context.input_bundle_sha256,
                    "target_count": len(strategy_targets),
                    "target_sha256": _payload_sha256(strategy_targets),
                    "targets": strategy_targets,
                    "eligibility": tuple(
                        eligibility_by_key[(session.decision_at, asset_id)]
                        for asset_id in V8_ASSET_IDS
                    ),
                }
            )
    return tuple(rows)


def _critical_increment(
    failures: Sequence[V8EvaluationFailureEvent],
    strategy_id: str,
    scenario_id: V8ScenarioId,
) -> int:
    """Schitaet tol'ko explicit external fail-closed metric increments."""
    return sum(
        item.metric_critical_increment
        for item in failures
        if item.strategy_id == strategy_id and item.scenario_id is scenario_id
    )


def _derive_metrics_and_gates(
    matrix: V8EvaluationLedgerMatrix,
    evidence: Sequence[V8ScenarioExecutionEvidence],
    failures: Sequence[V8EvaluationFailureEvent],
) -> tuple[tuple[V8StrategyMetricsBundle, ...], V8GateAndRanking]:
    """Edinstvennoe mesto calculation metrics iz sealed ledger/calendar evidence."""
    bundles: list[V8StrategyMetricsBundle] = []
    for strategy_id in V8_STRATEGY_IDS:
        scenarios: list[V8ScenarioMetrics] = []
        for scenario in fixed_v8_scenarios():
            state = matrix.ledger(strategy_id, scenario.scenario_id)
            scenario_evidence = tuple(
                item
                for item in evidence
                if item.scenario_id is scenario.scenario_id
                and any(fill.order_id == item.order_id for fill in state.fills)
                or item.scenario_id is scenario.scenario_id
                and any(
                    unresolved.order_id == item.order_id for unresolved in state.unresolved_orders
                )
            )
            metrics = summarize_v8_scenario(state, scenario_evidence)
            increment = _critical_increment(
                failures,
                strategy_id,
                scenario.scenario_id,
            )
            if increment:
                metrics = replace(
                    metrics,
                    critical_execution_failure_count=(
                        metrics.critical_execution_failure_count + increment
                    ),
                )
            scenarios.append(metrics)
        bundles.append(
            V8StrategyMetricsBundle(
                strategy_id=strategy_id,
                prediction_sha256=matrix.prediction_sha256,
                evaluation_bundle_sha256=matrix.evaluation_bundle_sha256,
                scenarios=tuple(scenarios),
            )
        )
    frozen = tuple(bundles)
    return frozen, build_v8_gate_and_ranking(frozen)


@dataclass(frozen=True, slots=True)
class _StatefulBarGrid:
    """Sealed union calendar for factual 10-minute stateful transitions."""

    windows: tuple[tuple[datetime, datetime], ...]
    candle_by_key: Mapping[tuple[str, datetime], TenMinuteCandle]
    common_session_by_open: Mapping[datetime, int]

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.windows))) != self.windows:
            raise ValueError("stateful factual windows must be unique and ordered")
        if any(closed - opened != timedelta(minutes=10) for opened, closed in self.windows):
            raise ValueError("stateful factual window must be exactly 10 minutes")
        if set(self.common_session_by_open) != {opened for opened, _ in self.windows}:
            raise ValueError("stateful bar grid lost common-session identity")

    def sequence_for_open(self, opened_at: datetime) -> int:
        """Return an exact present slot, or its deterministic missing-slot rank."""
        opened = _timestamp(opened_at, "stateful window opened_at")
        return bisect_left(self.windows, (opened, opened))

    def window(
        self,
        scenario_id: V8ScenarioId,
        opened_at: datetime,
        common_session_sequence_id: int,
    ) -> ScenarioExecutionWindow:
        opened = _timestamp(opened_at, "stateful scenario window opened_at")
        return ScenarioExecutionWindow(
            scenario_id=scenario_id,
            bar_sequence_id=self.sequence_for_open(opened),
            common_session_sequence_id=common_session_sequence_id,
            opened_at=opened,
            closed_at=opened + timedelta(minutes=10),
        )


def _stateful_bar_grid(prepared: V8PreparedEvaluation) -> _StatefulBarGrid:
    """Build one cross-contract factual slot order without filling absent candles."""
    candle_by_key = {
        (item.contract_id, item.opened_at): item for item in prepared.bundle.candles
    }
    windows = tuple(
        sorted({(item.opened_at, item.closed_at) for item in prepared.bundle.candles})
    )
    sessions = tuple(prepared.calendar)
    decisions = tuple(item.decision_at for item in sessions)
    common_by_open: dict[datetime, int] = {}
    for opened, closed in windows:
        session_index = bisect_left(decisions, closed) - 1
        if session_index < 0:
            raise V8EvaluationBlockedError(
                f"factual stateful bar precedes first sealed decision: {opened.isoformat()}"
            )
        session = sessions[session_index]
        common_by_open[opened] = session.entry_common_session_sequence_id
    return _StatefulBarGrid(windows, candle_by_key, common_by_open)


def _exact_stateful_windows(
    session: V8EvaluationCalendarSession,
    grid: _StatefulBarGrid,
) -> ExactScenarioExecutionWindows:
    """Materialize the fixed primary/double/delay windows for one D decision."""
    primary_open = session.decision_at + timedelta(minutes=30)
    primary_sequence = grid.sequence_for_open(primary_open)
    primary = ScenarioExecutionWindow(
        V8ScenarioId.PRIMARY,
        primary_sequence,
        session.entry_common_session_sequence_id,
        primary_open,
        primary_open + timedelta(minutes=10),
    )
    doubled = replace(primary, scenario_id=V8ScenarioId.DOUBLE_COST)
    delayed_open = primary.closed_at
    delayed_sequence = grid.sequence_for_open(delayed_open)
    if delayed_sequence != primary_sequence + 1:
        # A missing delay candle still owns the immediately following sealed slot.
        delayed_sequence = primary_sequence + 1
    delayed = ScenarioExecutionWindow(
        V8ScenarioId.DELAY,
        delayed_sequence,
        session.entry_common_session_sequence_id,
        delayed_open,
        delayed_open + timedelta(minutes=10),
    )
    return ExactScenarioExecutionWindows((primary, doubled, delayed))


def _stateful_seals(
    prepared: V8PreparedEvaluation,
    prediction: V8TargetFreePrediction,
    contract: V8AssetContractSnapshot,
    sleeve_id: str,
) -> StatefulSealSet:
    """Bind every transition to prediction, context, calendar, contract and sleeve."""
    return StatefulSealSet(
        prediction_sha256=prediction.context.prediction_sha256,
        input_bundle_sha256=prediction.context.input_bundle_sha256,
        calendar_sha256=prepared.bundle.calendar_sha256,
        contract_sha256=contract.source_sha256,
        sleeve_sha256=canonical_sha256(
            {
                "strategy_id": "stateful_v8",
                "sleeve_id": sleeve_id,
                "asset_id": contract.asset_id,
            }
        ),
    )


def _stateful_intent(
    binding: V8OrderBinding,
    *,
    action: StatefulAction,
    scenario_id: V8ScenarioId,
    window: ScenarioExecutionWindow,
    seals: StatefulSealSet,
) -> StatefulOrderIntent:
    """Convert one ledger binding into a state-machine intent without new facts."""
    if binding.single_position is None or not isinstance(
        binding.request, PredeclaredMarketOrder
    ):
        raise TypeError("stateful bridge accepts one-contract market bindings only")
    key = binding.single_position
    if key.strategy_id not in V8_STATEFUL_STRATEGY_IDS:
        raise ValueError("stateful intent received a non-stateful strategy")
    return StatefulOrderIntent(
        strategy_id=key.strategy_id,
        action=action,
        scenario_id=scenario_id,
        decision_at=binding.request.decision_at,
        effective_session_date=binding.effective_session_date,
        asset_id=key.asset_id,
        contract_id=key.contract_id,
        sleeve_id=key.sleeve_id,
        order_id=binding.request.order_id,
        requested_contracts=binding.request.signed_contracts,
        execution_window=window,
        seals=seals,
    )


def _bridge_stateful_event_to_v8(
    event: StatefulLedgerEvent,
    binding: V8OrderBinding,
    evidence: V8ScenarioExecutionEvidence,
) -> tuple[V8OrderBinding, V8ScenarioExecutionEvidence]:
    """Prove a lossless StatefulLedgerEvent -> common V8 ledger handoff."""
    if binding.single_position is None or not isinstance(
        binding.request, PredeclaredMarketOrder
    ):
        raise TypeError("stateful ledger handoff requires a single market binding")
    if len(evidence.legs) != 1:
        raise ValueError("stateful ledger handoff requires exactly one factual leg")
    if not isinstance(evidence.base_execution, OrderExecution):
        raise TypeError("stateful ledger handoff requires OrderExecution base evidence")
    key = binding.single_position
    leg = evidence.legs[0]
    base_leg = evidence.base_execution.leg
    if evidence.scenario_id in (V8ScenarioId.PRIMARY, V8ScenarioId.DOUBLE_COST):
        base_identity = (
            evidence.base_execution.requested_contracts,
            evidence.base_execution.executed_contracts,
            evidence.base_execution.carry_contracts,
            evidence.base_execution.status,
            base_leg.contract_id,
            base_leg.executed_contracts,
            base_leg.execution_window_open_at,
            base_leg.execution_window_close_at,
            base_leg.factual_execution_open,
            base_leg.factual_execution_high,
            base_leg.factual_execution_low,
            base_leg.factual_execution_close,
            base_leg.realized_execution_volume,
        )
        scenario_identity = (
            evidence.requested_contracts,
            evidence.executed_contracts,
            evidence.carry_contracts,
            evidence.status,
            leg.contract_id,
            leg.signed_contracts,
            leg.window_opened_at,
            leg.window_closed_at,
            leg.factual_open,
            leg.factual_high,
            leg.factual_low,
            leg.factual_close,
            leg.factual_volume,
        )
        if base_identity != scenario_identity:
            raise ValueError("primary/double scenario evidence diverged from base execution")
    elif (
        leg.window_opened_at != base_leg.execution_window_close_at
        or leg.window_closed_at != leg.window_opened_at + timedelta(minutes=10)
    ):
        raise ValueError("delay scenario is not the exact next complete 10m slot")
    actual = (
        key.strategy_id,
        key.sleeve_id,
        key.asset_id,
        key.contract_id,
        binding.request.order_id,
        binding.request.signed_contracts,
        binding.effective_session_date,
        evidence.scenario_id,
        evidence.requested_contracts,
        evidence.executed_contracts,
        evidence.carry_contracts,
        leg.execution_price,
        leg.capacity_contracts,
        leg.window_opened_at,
        leg.window_closed_at,
        evidence.evidence_sha256,
    )
    expected = (
        event.strategy_id,
        event.sleeve_id,
        event.asset_id,
        event.contract_id,
        event.order_id,
        event.requested_contracts,
        event.effective_session_date,
        event.scenario_id,
        event.requested_contracts,
        event.executed_contracts,
        event.carry_contracts,
        event.execution_price,
        event.capacity_contracts,
        event.window_opened_at,
        event.executed_at,
        event.execution_evidence_sha256,
    )
    if actual != expected:
        raise ValueError("StatefulLedgerEvent/V8 ledger handoff is not lossless")
    complete = all(
        value is not None
        for value in (
            leg.factual_open,
            leg.factual_high,
            leg.factual_low,
            leg.factual_close,
            leg.factual_volume,
            leg.capacity_contracts,
        )
    )
    if complete is not event.factual_window_complete:
        raise ValueError("stateful/V8 factual completeness mismatch")
    if (event.resolution is StatefulResolution.APPLIED) != (
        evidence.status is ExecutionStatus.FILLED and complete
    ):
        raise ValueError("stateful/V8 resolution mismatch")
    return binding, evidence


def _stateful_evidence(
    evidence: V8ScenarioExecutionEvidence,
    intent: StatefulOrderIntent,
    *,
    grid: _StatefulBarGrid,
) -> StatefulExecutionEvidence:
    """Convert common V8 factual evidence while preserving the actual scenario slot."""
    leg = evidence.legs[0]
    common_session = grid.common_session_by_open.get(
        leg.window_opened_at,
        intent.execution_window.common_session_sequence_id,
    )
    return StatefulExecutionEvidence.from_v8_scenario(
        evidence,
        asset_id=intent.asset_id,
        sleeve_id=intent.sleeve_id,
        bar_sequence_id=intent.execution_window.bar_sequence_id,
        common_session_sequence_id=common_session,
        seals=intent.seals,
        observed_at=leg.window_closed_at,
    )


V8_STATEFUL_BRIDGE_PROVENANCE: Final[str] = "stateful_factual_bridge_v1"


def _stateful_binding(
    intent: StatefulOrderIntent,
    *,
    cause: V8OrderCause,
    priority: int,
) -> V8OrderBinding:
    """Create the common-ledger order half of one sealed stateful intent."""
    return V8OrderBinding(
        request=PredeclaredMarketOrder(
            order_id=intent.order_id,
            contract_id=intent.contract_id,
            decision_at=intent.decision_at,
            signed_contracts=intent.requested_contracts,
            allocation_priority=priority,
        ),
        cause=cause,
        effective_session_date=intent.effective_session_date,
        single_position=V8PositionKey(
            intent.strategy_id,
            intent.sleeve_id,
            intent.asset_id,
            intent.contract_id,
        ),
    )


def _capacity_used(
    state: V8EventLedgerState,
) -> dict[tuple[str, datetime], int]:
    """Copy persisted gross POV usage before planning more stateful events."""
    return {
        (item.contract_id, item.window_opened_at): item.consumed_contracts
        for item in state.capacity_consumption
    }


def _adverse_stateful_price(
    candle: TenMinuteCandle,
    signed_contracts: int,
    scenario_id: V8ScenarioId,
    *,
    minimum_adverse_reference: float | None = None,
) -> float:
    """Apply the fixed scenario excursion to one fully factual market window."""
    if not candle.has_factual_ohlc:
        raise ValueError("adverse stateful price requires complete factual OHLC")
    if candle.open_price is None or candle.high_price is None or candle.low_price is None:
        raise RuntimeError("complete factual candle lost OHLC")
    multiplier = 2.0 if scenario_id is V8ScenarioId.DOUBLE_COST else 1.0
    if signed_contracts > 0:
        price = candle.open_price + multiplier * (
            candle.high_price - candle.open_price
        )
        if minimum_adverse_reference is not None:
            price = max(price, minimum_adverse_reference)
    else:
        price = candle.open_price - multiplier * (
            candle.open_price - candle.low_price
        )
        if minimum_adverse_reference is not None:
            price = min(price, minimum_adverse_reference)
    return _finite_number(price, "stateful adverse execution price", positive=True)


def _direct_stateful_v8_evidence(
    intent: StatefulOrderIntent,
    *,
    candle: TenMinuteCandle | None,
    capacity_contracts: int | None,
    already_consumed_contracts: int,
    adverse_reference_price: float | None = None,
    base_window: ScenarioExecutionWindow | None = None,
    base_candle: TenMinuteCandle | None = None,
    base_capacity_contracts: int | None = None,
    base_already_consumed_contracts: int = 0,
    force_unresolved: bool = False,
    reason: str,
) -> V8ScenarioExecutionEvidence:
    """Build factual V8 evidence for a predeclared bracket window or its absence."""
    requested = intent.requested_contracts
    complete = bool(
        candle is not None
        and candle.opened_at == intent.execution_window.opened_at
        and candle.closed_at == intent.execution_window.closed_at
        and candle.has_factual_ohlc
        and candle.volume is not None
        and capacity_contracts is not None
    )
    available = (
        max(0, capacity_contracts - already_consumed_contracts)
        if complete and capacity_contracts is not None
        else 0
    )
    executed_abs = 0 if force_unresolved else min(abs(requested), available)
    executed = executed_abs if requested > 0 else -executed_abs
    carry = requested - executed
    status = (
        ExecutionStatus.FILLED
        if carry == 0
        else ExecutionStatus.CARRIED
        if executed == 0
        else ExecutionStatus.PARTIAL_CARRY
    )
    price = (
        _adverse_stateful_price(
            candle,
            executed,
            intent.scenario_id,
            minimum_adverse_reference=(
                None
                if intent.scenario_id is V8ScenarioId.DELAY
                else adverse_reference_price
            ),
        )
        if executed and candle is not None
        else None
    )
    factual_open = candle.open_price if candle is not None else None
    factual_high = candle.high_price if candle is not None else None
    factual_low = candle.low_price if candle is not None else None
    factual_close = candle.close_price if candle is not None else None
    factual_volume = candle.volume if candle is not None else None
    resolved_base_window = base_window or intent.execution_window
    resolved_base_candle = base_candle if base_window is not None else candle
    resolved_base_capacity = (
        base_capacity_contracts if base_window is not None else capacity_contracts
    )
    resolved_base_consumed = (
        base_already_consumed_contracts
        if base_window is not None
        else already_consumed_contracts
    )
    base_complete = bool(
        resolved_base_candle is not None
        and resolved_base_candle.opened_at == resolved_base_window.opened_at
        and resolved_base_candle.closed_at == resolved_base_window.closed_at
        and resolved_base_candle.has_factual_ohlc
        and resolved_base_candle.volume is not None
        and resolved_base_capacity is not None
    )
    base_available = (
        max(0, resolved_base_capacity - resolved_base_consumed)
        if base_complete and resolved_base_capacity is not None
        else 0
    )
    base_executed_abs = min(abs(requested), base_available)
    base_executed = base_executed_abs if requested > 0 else -base_executed_abs
    base_carry = requested - base_executed
    base_status = (
        ExecutionStatus.FILLED
        if base_carry == 0
        else ExecutionStatus.CARRIED
        if base_executed == 0
        else ExecutionStatus.PARTIAL_CARRY
    )
    base_price = (
        _adverse_stateful_price(
            resolved_base_candle,
            base_executed,
            V8ScenarioId.PRIMARY,
            minimum_adverse_reference=adverse_reference_price,
        )
        if base_executed and resolved_base_candle is not None
        else None
    )
    base_open = (
        resolved_base_candle.open_price if resolved_base_candle is not None else None
    )
    base_high = (
        resolved_base_candle.high_price if resolved_base_candle is not None else None
    )
    base_low = resolved_base_candle.low_price if resolved_base_candle is not None else None
    base_close = (
        resolved_base_candle.close_price if resolved_base_candle is not None else None
    )
    base_volume = (
        resolved_base_candle.volume if resolved_base_candle is not None else None
    )
    leg = ExecutionLeg(
        contract_id=intent.contract_id,
        requested_contracts=requested,
        capacity_candle_open_at=resolved_base_window.opened_at,
        capacity_candle_close_at=resolved_base_window.closed_at,
        observed_capacity_volume=base_volume,
        observed_capacity_contracts=resolved_base_capacity,
        order_live_at=intent.decision_at,
        execution_window_open_at=resolved_base_window.opened_at,
        execution_window_close_at=resolved_base_window.closed_at,
        factual_execution_open=base_open,
        factual_execution_high=base_high,
        factual_execution_low=base_low,
        factual_execution_close=base_close,
        realized_execution_volume=base_volume,
        realized_execution_capacity_contracts=resolved_base_capacity,
        execution_volume_is_post_window_outcome=True,
        aggregate_available_before=base_available if base_complete else None,
        executed_contracts=base_executed,
        execution_price=base_price,
        reason=(reason if intent.scenario_id is not V8ScenarioId.DELAY else "base_" + reason),
        provenance=V8_STATEFUL_BRIDGE_PROVENANCE,
    )
    base = OrderExecution(
        order_id=intent.order_id,
        decision_at=intent.decision_at,
        requested_contracts=requested,
        executed_contracts=base_executed,
        carry_contracts=base_carry,
        allocation_priority=0,
        status=base_status,
        reason=leg.reason,
        provenance=V8_STATEFUL_BRIDGE_PROVENANCE,
        leg=leg,
    )
    scenario_leg = V8ScenarioFillLeg(
        contract_id=intent.contract_id,
        signed_contracts=executed,
        execution_price=price,
        factual_open=factual_open,
        factual_high=factual_high,
        factual_low=factual_low,
        factual_close=factual_close,
        factual_volume=factual_volume,
        capacity_contracts=capacity_contracts,
        window_opened_at=intent.execution_window.opened_at,
        window_closed_at=intent.execution_window.closed_at,
        reason=reason,
    )
    return V8ScenarioExecutionEvidence(
        scenario_id=intent.scenario_id,
        order_id=intent.order_id,
        effective_session_date=intent.effective_session_date,
        base_execution=base,
        requested_contracts=requested,
        executed_contracts=executed,
        carry_contracts=carry,
        status=status,
        legs=(scenario_leg,),
    )


def _shrink_stateful_evidence_to_capacity(
    evidence: V8ScenarioExecutionEvidence,
    *,
    already_consumed_contracts: int,
) -> V8ScenarioExecutionEvidence:
    """Respect exit-first persisted capacity when the generic planner saw a fresh window."""
    leg = evidence.legs[0]
    if leg.capacity_contracts is None:
        return evidence
    available = max(0, leg.capacity_contracts - already_consumed_contracts)
    if abs(evidence.executed_contracts) <= available:
        return evidence
    requested = evidence.requested_contracts
    executed_abs = min(abs(requested), available)
    executed = executed_abs if requested > 0 else -executed_abs
    carry = requested - executed
    status = (
        ExecutionStatus.FILLED
        if carry == 0
        else ExecutionStatus.CARRIED
        if executed == 0
        else ExecutionStatus.PARTIAL_CARRY
    )
    reason = "stateful_exit_first_capacity_adjustment"
    scenario_leg = replace(
        leg,
        signed_contracts=executed,
        execution_price=leg.execution_price if executed else None,
        reason=reason,
    )
    base = evidence.base_execution
    if not isinstance(base, OrderExecution):
        raise TypeError("stateful capacity adjustment requires OrderExecution")
    if evidence.scenario_id in (V8ScenarioId.PRIMARY, V8ScenarioId.DOUBLE_COST):
        base_leg = replace(
            base.leg,
            aggregate_available_before=available,
            executed_contracts=executed,
            execution_price=base.leg.execution_price if executed else None,
            reason=reason,
        )
        base = replace(
            base,
            executed_contracts=executed,
            carry_contracts=carry,
            status=status,
            reason=reason,
            leg=base_leg,
        )
    return V8ScenarioExecutionEvidence(
        scenario_id=evidence.scenario_id,
        order_id=evidence.order_id,
        effective_session_date=evidence.effective_session_date,
        base_execution=base,
        requested_contracts=requested,
        executed_contracts=executed,
        carry_contracts=carry,
        status=status,
        legs=(scenario_leg,),
    )


def _factual_bar_sha256(
    prepared: V8PreparedEvaluation,
    candle: TenMinuteCandle,
) -> str:
    return canonical_sha256(
        {
            "market_data_sha256": prepared.bundle.market_data_sha256,
            "candle": candle,
        }
    )


def _scenario_factual_bar(
    prepared: V8PreparedEvaluation,
    grid: _StatefulBarGrid,
    position: CorridorScenarioPosition,
    candle: TenMinuteCandle,
) -> ScenarioFactualBar:
    """Attach exact scenario/session/seal identity to one completed raw candle."""
    if not candle.has_factual_ohlc or candle.volume is None:
        raise ValueError("scenario factual bar requires complete OHLCV")
    common_session = grid.common_session_by_open[candle.opened_at]
    if any(
        value is None
        for value in (
            candle.open_price,
            candle.high_price,
            candle.low_price,
            candle.close_price,
        )
    ):
        raise RuntimeError("complete scenario factual bar lost OHLC")
    return ScenarioFactualBar(
        scenario_id=position.scenario_id,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        bar_sequence_id=grid.sequence_for_open(candle.opened_at),
        common_session_sequence_id=common_session,
        opened_at=candle.opened_at,
        closed_at=candle.closed_at,
        open_price=candle.open_price,
        high_price=candle.high_price,
        low_price=candle.low_price,
        close_price=candle.close_price,
        volume=candle.volume,
        observed_at=candle.closed_at,
        calendar_sha256=position.seals.calendar_sha256,
        contract_sha256=position.seals.contract_sha256,
        market_evidence_sha256=_factual_bar_sha256(prepared, candle),
    )


def _breakout_signal_target(
    targets: Sequence[V8SleeveTarget],
    asset_id: str,
) -> V8SleeveTarget | None:
    rows = tuple(
        item
        for item in targets
        if item.strategy_id == BREAKOUT_STRATEGY_ID and item.asset_id == asset_id
    )
    if len(rows) > 1:
        raise RuntimeError("breakout decision produced duplicate asset targets")
    return rows[0] if rows else None


def _breakout_tranche_contracts(
    state: V8EventLedgerState,
    prediction: V8TargetFreePrediction,
    target: V8SleeveTarget | None,
    asset_id: str,
    specs: Sequence[V8ContractSpec],
) -> int:
    """Apply the sealed integer handoff before proposing ENTER or ADD."""
    if target is None:
        return 0
    asset = next(item for item in prediction.context.assets if item.asset_id == asset_id)
    if asset.close is None:
        return 0
    spec = select_v8_contract_spec_snapshot(
        specs,
        contract_id=target.contract_id,
        effective_session_date=target.entry_effective_session_date,
        sizing_as_of=target.decision_at,
    )
    return integer_contracts_for_weight(
        target.target_weight,
        state.equity_curve[-1].equity,
        asset.close,
        spec,
    )


def _run_breakout_stateful_ledger(
    prepared: V8PreparedEvaluation,
    initial_state: V8EventLedgerState,
    all_targets: Sequence[Sequence[V8SleeveTarget]],
    grid: _StatefulBarGrid,
    scenario_states: dict[str, BreakoutScenarioState],
) -> tuple[
    V8EventLedgerState,
    tuple[V8OrderBinding, ...],
    tuple[V8ScenarioExecutionEvidence, ...],
    tuple[V8EvaluationFailureEvent, ...],
]:
    """Run a persistent, evidence-advanced breakout state for one scenario ledger."""
    state = initial_state
    orders: list[V8OrderBinding] = []
    evidence_rows: list[V8ScenarioExecutionEvidence] = []
    failures: list[V8EvaluationFailureEvent] = []
    candle_index = grid.candle_by_key
    for index, session in enumerate(prepared.calendar):
        prediction = prepared.bundle.predictions[index]
        windows = _exact_stateful_windows(session, grid)
        scenario_window = windows.for_scenario(state.scenario_id)
        contract_by_asset = {item.asset_id: item for item in prediction.contracts}
        asset_by_id = {item.asset_id: item for item in prediction.context.assets}
        pending_by_order: dict[str, tuple[str, PendingBreakoutTransition]] = {}
        bindings: list[V8OrderBinding] = []
        for asset_id in V8_ASSET_IDS:
            machine = scenario_states[asset_id]
            asset = asset_by_id[asset_id]
            contract = contract_by_asset[asset_id]
            previous = next((item for item in machine.assets if item.asset_id == asset_id), None)
            if previous is not None and previous.contract_id != contract.contract_id:
                raise V8EvaluationBlockedError(
                    "persistent breakout roll unsupported: "
                    f"scenario={state.scenario_id.value}, asset={asset_id}, "
                    f"old={previous.contract_id}, new={contract.contract_id}"
                )
            sleeve_id = f"{BREAKOUT_STRATEGY_ID}-{asset_id}-persistent"
            seals = _stateful_seals(prepared, prediction, contract, sleeve_id)
            target = _breakout_signal_target(all_targets[index], asset_id)
            tranche = _breakout_tranche_contracts(
                state,
                prediction,
                target,
                asset_id,
                prepared.bundle.contract_specs,
            )
            eligible = bool(
                asset.strategy_eligible
                and contract.asset_mask
                and contract.nominal_span_eligible
            )
            reasons = set(asset.invalid_reason_codes)
            if not contract.asset_mask:
                reasons.add("planned_contract_inactive")
            if not contract.nominal_span_eligible:
                reasons.add("nominal_span_ineligible")
            if not eligible and not reasons:
                reasons.add("stateful_breakout_input_invalid")
            direction = (1 if tranche > 0 else -1 if tranche < 0 else 0) if eligible else 0
            observation = BreakoutDecisionObservation(
                decision_at=prediction.context.decision_at,
                known_at=asset.known_at,
                asset_id=asset_id,
                contract_id=contract.contract_id,
                sleeve_id=sleeve_id,
                close_price=asset.close if eligible else None,
                atr_20=asset.atr_20 if eligible else None,
                breakout_direction=direction,
                input_valid=eligible,
                seals=seals,
                invalid_reason_codes=tuple(sorted(reasons)) if not eligible else (),
            )
            proposal = propose_breakout_transition(machine, observation)
            if proposal.action is None:
                scenario_states[asset_id] = advance_breakout_observation(machine, proposal)
                continue
            if proposal.action in (
                StatefulAction.BREAKOUT_ENTER,
                StatefulAction.BREAKOUT_ADD,
            ):
                requested = tranche
            else:
                requested = -proposal.prior_direction * proposal.prior_open_contracts
            if requested == 0:
                raise RuntimeError("non-HOLD breakout proposal lost integer quantity")
            order_id = (
                f"breakout-{proposal.action.value}-{session.sequence_id:06d}-{asset_id}"
            )
            intent = StatefulOrderIntent(
                strategy_id=BREAKOUT_STRATEGY_ID,
                action=proposal.action,
                scenario_id=state.scenario_id,
                decision_at=session.decision_at,
                effective_session_date=session.entry_effective_session_date,
                asset_id=asset_id,
                contract_id=contract.contract_id,
                sleeve_id=sleeve_id,
                order_id=order_id,
                requested_contracts=requested,
                execution_window=scenario_window,
                seals=seals,
            )
            pending = bind_breakout_order(proposal, intent)
            cause_priority = (
                0
                if proposal.action
                in (
                    StatefulAction.BREAKOUT_EXIT_TRAIL,
                    StatefulAction.BREAKOUT_EXIT_REVERSAL,
                )
                else 1
            )
            binding = _stateful_binding(
                intent,
                cause=V8OrderCause.BREAKOUT_TRANSITION,
                priority=cause_priority * len(V8_ASSET_IDS) + V8_ASSET_IDS.index(asset_id),
            )
            bindings.append(binding)
            pending_by_order[order_id] = (asset_id, pending)
        bindings = list(
            _reprioritize_bindings(
                tuple(
                    sorted(
                        bindings,
                        key=lambda item: (
                            item.request.allocation_priority,
                            item.request.order_id,
                        ),
                    )
                ),
                first_priority=0,
            )
        )
        marks = _settlement_marks(state, bindings, candle_index, session)
        if bindings:
            planned = plan_v8_scenario_execution(
                bindings,
                prepared.trusted_candle_index,
                state.scenario_id,
            )
            for binding, evidence in zip(bindings, planned, strict=True):
                asset_id, pending = pending_by_order[binding.request.order_id]
                intent = pending.intent
                if (
                    evidence.legs[0].window_opened_at != intent.execution_window.opened_at
                    or evidence.legs[0].window_closed_at != intent.execution_window.closed_at
                ):
                    raise ValueError("breakout planner used a non-sealed scenario window")
                factual = _stateful_evidence(evidence, intent, grid=grid)
                transition = reconcile_breakout_execution(
                    scenario_states[asset_id],
                    pending,
                    factual,
                )
                scenario_states[asset_id] = transition.state
                bridged_binding, bridged_evidence = _bridge_stateful_event_to_v8(
                    transition.event,
                    binding,
                    evidence,
                )
                orders.append(bridged_binding)
                evidence_rows.append(bridged_evidence)
                if transition.unresolved is not None:
                    failures.append(
                        V8EvaluationFailureEvent(
                            phase="stateful_breakout",
                            code="unresolved_breakout_execution",
                            message=transition.unresolved.reason,
                            strategy_id=state.strategy_id,
                            scenario_id=state.scenario_id,
                            decision_at=session.decision_at,
                        )
                    )
            state = apply_v8_execution_batch(
                state,
                bindings,
                planned,
                prepared.bundle.contract_specs,
                trusted_candles=prepared.trusted_candle_index,
                accounting_as_of=session.accounting_as_of,
                risk_marks=marks,
            )
        open_marks = {
            item.key.contract_id: marks[item.key.contract_id] for item in state.positions
        }
        state = settle_v8_event_ledger(
            state,
            prepared.bundle.contract_specs,
            open_marks,
            marked_at=session.settlement_at,
            effective_session_date=session.entry_effective_session_date,
            accounting_as_of=session.accounting_as_of,
        )
    unresolved_count = sum(len(item.unresolved) for item in scenario_states.values())
    locked_count = sum(len(item.locked_positions) for item in scenario_states.values())
    if unresolved_count or locked_count or state.positions or state.unresolved_orders:
        failures.append(
            V8EvaluationFailureEvent(
                phase="terminal",
                code="unresolved_terminal_stateful_breakout",
                message=(
                    f"positions={len(state.positions)}, "
                    f"unresolved_orders={len(state.unresolved_orders)}, "
                    f"machine_unresolved={unresolved_count}, locked={locked_count}"
                ),
                strategy_id=state.strategy_id,
                scenario_id=state.scenario_id,
                metric_critical_increment=1,
            )
        )
    return state, tuple(orders), tuple(evidence_rows), tuple(failures)


def _missing_corridor_evidence(
    prepared: V8PreparedEvaluation,
    position: CorridorScenarioPosition,
    expected_window: ScenarioExecutionWindow,
    *,
    observed_through: datetime,
) -> MissingBarEvidence:
    """Seal an observed absence without inserting a synthetic OHLCV row."""
    evidence_sha = canonical_sha256(
        {
            "market_data_sha256": prepared.bundle.market_data_sha256,
            "asset_id": position.asset_id,
            "contract_id": position.contract_id,
            "expected_window": expected_window,
            "observed_through": observed_through,
            "reason": "missing_exact_factual_10m_bar",
        }
    )
    return MissingBarEvidence(
        scenario_id=position.scenario_id,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        expected_window=expected_window,
        observed_through=observed_through,
        calendar_sha256=position.seals.calendar_sha256,
        contract_sha256=position.seals.contract_sha256,
        evidence_sha256=evidence_sha,
    )


def _scan_corridor_position(
    prepared: V8PreparedEvaluation,
    grid: _StatefulBarGrid,
    position: CorridorScenarioPosition,
    *,
    closed_through: datetime,
    observed_through: datetime,
) -> CorridorBarTransition:
    """Causally scan every sealed union slot until trigger, missing row or cutoff."""
    current = position
    for sequence_id in range(current.last_bar_sequence_id + 1, len(grid.windows)):
        opened, closed = grid.windows[sequence_id]
        if closed > closed_through:
            break
        common_session = grid.common_session_by_open[opened]
        expected_window = ScenarioExecutionWindow(
            current.scenario_id,
            sequence_id,
            common_session,
            opened,
            closed,
        )
        candle = grid.candle_by_key.get((current.contract_id, opened))
        if candle is None or not candle.has_factual_ohlc or candle.volume is None:
            return mark_corridor_missing_bar(
                current,
                _missing_corridor_evidence(
                    prepared,
                    current,
                    expected_window,
                    observed_through=observed_through,
                ),
            )
        transition = transition_corridor_bar(
            current,
            _scenario_factual_bar(prepared, grid, current, candle),
        )
        current = transition.position
        if transition.trigger is not None or transition.unresolved is not None:
            return transition
    if (
        current.status is CorridorStatus.OPEN
        and current.time_exit_window.closed_at <= closed_through
    ):
        return mark_corridor_missing_bar(
            current,
            _missing_corridor_evidence(
                prepared,
                current,
                current.time_exit_window,
                observed_through=observed_through,
            ),
        )
    return CorridorBarTransition(position=current)


def _corridor_exit_pair(
    prepared: V8PreparedEvaluation,
    grid: _StatefulBarGrid,
    state: V8EventLedgerState,
    position: CorridorScenarioPosition,
    trigger: CorridorExitTrigger,
    used: dict[tuple[str, datetime], int],
    session_by_common: Mapping[int, V8EvaluationCalendarSession],
) -> tuple[
    CorridorScenarioPosition,
    V8OrderBinding,
    V8ScenarioExecutionEvidence,
    StatefulLedgerEvent,
    StatefulUnresolvedCarry | None,
]:
    """Execute one factual corridor trigger in its scenario-specific exact slot."""
    trigger_window = trigger.trigger_window
    if state.scenario_id is V8ScenarioId.DELAY:
        next_index = trigger_window.bar_sequence_id + 1
        opened_at = trigger_window.closed_at
        closed_at = opened_at + timedelta(minutes=10)
        common_session = grid.common_session_by_open.get(
            opened_at,
            trigger_window.common_session_sequence_id,
        )
        execution_window = ScenarioExecutionWindow(
            state.scenario_id,
            next_index,
            common_session,
            opened_at,
            closed_at,
        )
    else:
        execution_window = trigger_window
        common_session = trigger_window.common_session_sequence_id
    causal_session = session_by_common.get(common_session)
    if causal_session is None or causal_session.decision_at >= execution_window.opened_at:
        raise V8EvaluationBlockedError(
            "corridor exit slot has no prior sealed D18:50 calendar decision"
        )
    order_id = f"exit-{position.position_id}-{trigger.trigger_id}"
    intent = StatefulOrderIntent(
        strategy_id=CORRIDOR_STRATEGY_ID,
        action=trigger.action,
        scenario_id=state.scenario_id,
        decision_at=causal_session.decision_at,
        effective_session_date=causal_session.entry_effective_session_date,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        sleeve_id=position.sleeve_id,
        order_id=order_id,
        requested_contracts=trigger.requested_contracts,
        execution_window=execution_window,
        seals=position.seals,
    )
    candle = grid.candle_by_key.get((position.contract_id, execution_window.opened_at))
    complete = bool(
        candle is not None and candle.has_factual_ohlc and candle.volume is not None
    )
    realized_capacity = (
        candle.volume * MAXIMUM_BAR_PARTICIPATION_BPS // 10_000
        if complete and candle is not None and candle.volume is not None
        else None
    )
    capacity_key = (position.contract_id, execution_window.opened_at)
    trigger_candle = grid.candle_by_key.get(
        (position.contract_id, trigger_window.opened_at)
    )
    trigger_complete = bool(
        trigger_candle is not None
        and trigger_candle.has_factual_ohlc
        and trigger_candle.volume is not None
    )
    trigger_capacity = (
        trigger_candle.volume * MAXIMUM_BAR_PARTICIPATION_BPS // 10_000
        if trigger_complete
        and trigger_candle is not None
        and trigger_candle.volume is not None
        else None
    )
    trigger_capacity_key = (position.contract_id, trigger_window.opened_at)
    capacity = (
        min(trigger_capacity, realized_capacity)
        if state.scenario_id is V8ScenarioId.DELAY
        and trigger_capacity is not None
        and realized_capacity is not None
        else realized_capacity
        if state.scenario_id is not V8ScenarioId.DELAY
        else None
    )
    delayed_reference_proven = bool(
        state.scenario_id is not V8ScenarioId.DELAY
        or not complete
        or candle is not None
        and (
            trigger.requested_contracts < 0
            and candle.low_price is not None
            and candle.low_price <= trigger.adverse_reference_price
            or trigger.requested_contracts > 0
            and candle.high_price is not None
            and candle.high_price >= trigger.adverse_reference_price
        )
    )
    evidence_reason = (
        trigger.reason
        if complete and delayed_reference_proven
        else "delayed_adverse_reference_not_reached"
        if complete
        else "missing_corridor_exit_execution_window"
    )
    evidence = _direct_stateful_v8_evidence(
        intent,
        candle=candle,
        capacity_contracts=capacity,
        already_consumed_contracts=used.get(capacity_key, 0),
        adverse_reference_price=trigger.adverse_reference_price,
        base_window=(
            trigger_window if state.scenario_id is V8ScenarioId.DELAY else None
        ),
        base_candle=(
            trigger_candle if state.scenario_id is V8ScenarioId.DELAY else None
        ),
        base_capacity_contracts=(
            trigger_capacity if state.scenario_id is V8ScenarioId.DELAY else None
        ),
        base_already_consumed_contracts=used.get(trigger_capacity_key, 0),
        force_unresolved=not delayed_reference_proven,
        reason=evidence_reason,
    )
    evidence = replace(
        evidence,
        trusted_candle_panel_sha256=(
            prepared.trusted_candle_index.candle_panel_sha256
        ),
    )
    used[capacity_key] = used.get(capacity_key, 0) + abs(evidence.executed_contracts)
    factual = _stateful_evidence(evidence, intent, grid=grid)
    transition = reconcile_corridor_exit(position, trigger, intent, factual)
    binding = replace(
        _stateful_binding(
            intent,
            cause=V8OrderCause.CORRIDOR_EXIT,
            priority=0,
        ),
        stateful_replay_policy=V8StatefulReplayPolicy(
            scenario_id=state.scenario_id,
            base_window_opened_at=trigger_window.opened_at,
            scenario_window_opened_at=execution_window.opened_at,
            reason=trigger.reason,
            adverse_reference_price=trigger.adverse_reference_price,
        ),
    )
    _bridge_stateful_event_to_v8(transition.event, binding, evidence)
    return transition.position, binding, evidence, transition.event, transition.unresolved


def _run_corridor_stateful_ledger(
    prepared: V8PreparedEvaluation,
    initial_state: V8EventLedgerState,
    all_targets: Sequence[Sequence[V8SleeveTarget]],
    grid: _StatefulBarGrid,
    positions: dict[str, CorridorScenarioPosition],
) -> tuple[
    V8EventLedgerState,
    tuple[V8OrderBinding, ...],
    tuple[V8ScenarioExecutionEvidence, ...],
    tuple[V8EvaluationFailureEvent, ...],
]:
    """Run ATR brackets through factual bars with stop-first and exact D+5 exit."""
    state = initial_state
    all_orders: list[V8OrderBinding] = []
    all_evidence: list[V8ScenarioExecutionEvidence] = []
    failures: list[V8EvaluationFailureEvent] = []
    unresolved_machine: list[StatefulUnresolvedCarry] = []
    session_by_common = {
        item.entry_common_session_sequence_id: item for item in prepared.calendar
    }
    for index, session in enumerate(prepared.calendar):
        prediction = prepared.bundle.predictions[index]
        used = _capacity_used(state)
        day_pairs: list[tuple[V8OrderBinding, V8ScenarioExecutionEvidence]] = []
        # Existing brackets see all factual slots known by this settlement boundary.
        for position_id in sorted(tuple(positions)):
            position = positions[position_id]
            scan = _scan_corridor_position(
                prepared,
                grid,
                position,
                closed_through=session.settlement_candle_closed_at,
                observed_through=session.accounting_as_of,
            )
            positions[position_id] = scan.position
            if scan.unresolved is not None:
                unresolved_machine.append(scan.unresolved)
                positions.pop(position_id)
                failures.append(
                    V8EvaluationFailureEvent(
                        phase="stateful_corridor",
                        code="missing_corridor_factual_bar",
                        message=scan.unresolved.reason,
                        strategy_id=state.strategy_id,
                        scenario_id=state.scenario_id,
                        decision_at=session.decision_at,
                    )
                )
                continue
            if scan.trigger is not None:
                next_position, binding, evidence, _event, unresolved = _corridor_exit_pair(
                    prepared,
                    grid,
                    state,
                    scan.position,
                    scan.trigger,
                    used,
                    session_by_common,
                )
                day_pairs.append((binding, evidence))
                positions.pop(position_id)
                if unresolved is not None:
                    unresolved_machine.append(unresolved)
                    failures.append(
                        V8EvaluationFailureEvent(
                            phase="stateful_corridor",
                            code="unresolved_corridor_exit",
                            message=unresolved.reason,
                            strategy_id=state.strategy_id,
                            scenario_id=state.scenario_id,
                            decision_at=session.decision_at,
                        )
                    )
                elif next_position.status is CorridorStatus.OPEN:
                    positions[position_id] = next_position
        # A bracket must have its complete fifth-session slot inside the sealed sample.
        if index + 5 < len(prepared.calendar):
            corridor_targets = tuple(
                item
                for item in all_targets[index]
                if item.strategy_id == CORRIDOR_STRATEGY_ID
            )
        else:
            corridor_targets = ()
        reference_prices = {
            contract.contract_id: asset.close
            for contract, asset in zip(
                prediction.contracts,
                prediction.context.assets,
                strict=True,
            )
            if asset.close is not None
        }
        entry_bindings = build_v8_entry_bindings(
            corridor_targets,
            strategy_id=CORRIDOR_STRATEGY_ID,
            portfolio_equity=state.equity_curve[-1].equity,
            reference_prices=reference_prices,
            specs=prepared.bundle.contract_specs,
        )
        raw_entry_evidence = (
            plan_v8_scenario_execution(
                entry_bindings,
                prepared.trusted_candle_index,
                state.scenario_id,
            )
            if entry_bindings
            else ()
        )
        target_by_sleeve_asset = {
            (item.sleeve_id, item.asset_id): item for item in corridor_targets
        }
        contract_by_asset = {item.asset_id: item for item in prediction.contracts}
        asset_by_id = {item.asset_id: item for item in prediction.context.assets}
        windows = _exact_stateful_windows(session, grid)
        scenario_window = windows.for_scenario(state.scenario_id)
        opened_positions: list[CorridorScenarioPosition] = []
        for binding, raw_evidence in zip(
            entry_bindings,
            raw_entry_evidence,
            strict=True,
        ):
            if binding.single_position is None:
                raise RuntimeError("corridor entry lost its single position key")
            key = binding.single_position
            target = target_by_sleeve_asset[(key.sleeve_id, key.asset_id)]
            contract = contract_by_asset[key.asset_id]
            asset = asset_by_id[key.asset_id]
            seals = _stateful_seals(prepared, prediction, contract, target.sleeve_id)
            intent = _stateful_intent(
                binding,
                action=StatefulAction.CORRIDOR_ENTRY,
                scenario_id=state.scenario_id,
                window=scenario_window,
                seals=seals,
            )
            if (
                raw_evidence.legs[0].window_opened_at != scenario_window.opened_at
                or raw_evidence.legs[0].window_closed_at != scenario_window.closed_at
            ):
                raise ValueError("corridor planner used a non-sealed scenario entry window")
            capacity_key = (key.contract_id, scenario_window.opened_at)
            evidence = _shrink_stateful_evidence_to_capacity(
                raw_evidence,
                already_consumed_contracts=used.get(capacity_key, 0),
            )
            if evidence.base_execution.provenance == V8_STATEFUL_BRIDGE_PROVENANCE:
                evidence = replace(
                    evidence,
                    trusted_candle_panel_sha256=(
                        prepared.trusted_candle_index.candle_panel_sha256
                    ),
                )
                binding = replace(
                    binding,
                    stateful_replay_policy=V8StatefulReplayPolicy(
                        scenario_id=state.scenario_id,
                        base_window_opened_at=(
                            evidence.base_execution.leg.execution_window_open_at
                        ),
                        scenario_window_opened_at=evidence.legs[0].window_opened_at,
                        reason=evidence.legs[0].reason,
                    ),
                )
            used[capacity_key] = used.get(capacity_key, 0) + abs(
                evidence.executed_contracts
            )
            future_session = prepared.calendar[index + 5]
            time_exit_window = _exact_stateful_windows(
                future_session,
                grid,
            ).for_scenario(state.scenario_id)
            if asset.atr_20 is None:
                raise RuntimeError("eligible corridor entry lost causal ATR")
            protocol = CorridorEntryProtocol(
                intent=intent,
                asset_known_at=asset.known_at,
                atr_20=asset.atr_20,
                entry_common_session_sequence_id=(
                    session.entry_common_session_sequence_id
                ),
                time_exit_window=time_exit_window,
            )
            factual = _stateful_evidence(evidence, intent, grid=grid)
            transition = reconcile_corridor_entry(protocol, factual)
            bridged = _bridge_stateful_event_to_v8(
                transition.event,
                binding,
                evidence,
            )
            day_pairs.append(bridged)
            if transition.unresolved is not None:
                unresolved_machine.append(transition.unresolved)
                failures.append(
                    V8EvaluationFailureEvent(
                        phase="stateful_corridor",
                        code="unresolved_corridor_entry",
                        message=transition.unresolved.reason,
                        strategy_id=state.strategy_id,
                        scenario_id=state.scenario_id,
                        decision_at=session.decision_at,
                    )
                )
            elif transition.position is not None:
                opened_positions.append(transition.position)
        # Newly filled brackets can trigger only on bars strictly after their actual fill.
        for position in opened_positions:
            scan = _scan_corridor_position(
                prepared,
                grid,
                position,
                closed_through=session.settlement_candle_closed_at,
                observed_through=session.accounting_as_of,
            )
            if scan.unresolved is not None:
                unresolved_machine.append(scan.unresolved)
                failures.append(
                    V8EvaluationFailureEvent(
                        phase="stateful_corridor",
                        code="missing_corridor_factual_bar",
                        message=scan.unresolved.reason,
                        strategy_id=state.strategy_id,
                        scenario_id=state.scenario_id,
                        decision_at=session.decision_at,
                    )
                )
            elif scan.trigger is not None:
                next_position, binding, evidence, _event, unresolved = _corridor_exit_pair(
                    prepared,
                    grid,
                    state,
                    scan.position,
                    scan.trigger,
                    used,
                    session_by_common,
                )
                day_pairs.append((binding, evidence))
                if unresolved is not None:
                    unresolved_machine.append(unresolved)
                    failures.append(
                        V8EvaluationFailureEvent(
                            phase="stateful_corridor",
                            code="unresolved_corridor_exit",
                            message=unresolved.reason,
                            strategy_id=state.strategy_id,
                            scenario_id=state.scenario_id,
                            decision_at=session.decision_at,
                        )
                    )
                elif next_position.status is CorridorStatus.OPEN:
                    positions[next_position.position_id] = next_position
            else:
                positions[scan.position.position_id] = scan.position
        ordered_pairs = tuple(
            sorted(
                day_pairs,
                key=lambda pair: (
                    pair[1].legs[0].window_opened_at,
                    0 if pair[0].cause is V8OrderCause.CORRIDOR_EXIT else 1,
                    pair[0].request.order_id,
                ),
            )
        )
        raw_bindings = tuple(item[0] for item in ordered_pairs)
        marks = _settlement_marks(state, raw_bindings, grid.candle_by_key, session)
        pairs_by_effective: dict[
            date,
            list[tuple[V8OrderBinding, V8ScenarioExecutionEvidence]],
        ] = {}
        for pair in ordered_pairs:
            pairs_by_effective.setdefault(pair[0].effective_session_date, []).append(pair)
        ordered_groups = sorted(
            pairs_by_effective.values(),
            key=lambda group: group[0][1].legs[0].window_opened_at,
        )
        for group in ordered_groups:
            bindings = _reprioritize_bindings(
                tuple(item[0] for item in group),
                first_priority=0,
            )
            evidences = tuple(item[1] for item in group)
            state = apply_v8_execution_batch(
                state,
                bindings,
                evidences,
                prepared.bundle.contract_specs,
                trusted_candles=prepared.trusted_candle_index,
                accounting_as_of=session.accounting_as_of,
                risk_marks=marks,
            )
            all_orders.extend(bindings)
            all_evidence.extend(evidences)
        open_marks = {
            item.key.contract_id: marks[item.key.contract_id] for item in state.positions
        }
        state = settle_v8_event_ledger(
            state,
            prepared.bundle.contract_specs,
            open_marks,
            marked_at=session.settlement_at,
            effective_session_date=session.entry_effective_session_date,
            accounting_as_of=session.accounting_as_of,
        )
    if positions or unresolved_machine or state.positions or state.unresolved_orders:
        failures.append(
            V8EvaluationFailureEvent(
                phase="terminal",
                code="unresolved_terminal_stateful_corridor",
                message=(
                    f"open_brackets={len(positions)}, "
                    f"machine_unresolved={len(unresolved_machine)}, "
                    f"positions={len(state.positions)}, "
                    f"unresolved_orders={len(state.unresolved_orders)}"
                ),
                strategy_id=state.strategy_id,
                scenario_id=state.scenario_id,
                metric_critical_increment=1,
            )
        )
    return state, tuple(all_orders), tuple(all_evidence), tuple(failures)


def run_v8_evaluation(
    prepared: V8PreparedEvaluation,
    *,
    initial_cash: float,
    mode: V8EvaluationMode | str = V8EvaluationMode.AUTHORITATIVE,
) -> V8EvaluationRunResult:
    """Zapuskaet exact 11x3 plumbing; real mode waits for final context admission."""
    prepared = _reverify_prepared_for_run(prepared)
    resolved_mode = V8EvaluationMode(mode)
    if resolved_mode is V8EvaluationMode.AUTHORITATIVE:
        raise V8EvaluationBlockedError(
            "authoritative PnL blocked: final audited full-context admission "
            "and sealed initial capital are not yet released"
        )
    initial = _finite_number(initial_cash, "initial_cash", positive=True)
    core_path = build_v8_core_path(prepared.bundle)
    if len(core_path) != len(prepared.bundle.predictions):
        raise RuntimeError("core path length ne raven prediction calendar")
    decision_sets = tuple(
        build_v8_strategy_decision_set(prediction) for prediction in prepared.bundle.predictions
    )
    all_targets = tuple(
        build_v8_new_sleeve_targets(
            decision_set,
            core_decision,
            common_session_sequence_id=(session.entry_common_session_sequence_id),
        )
        for decision_set, core_decision, session in zip(
            decision_sets,
            core_path,
            prepared.calendar,
            strict=True,
        )
    )
    decisions = _decision_rows(prepared, all_targets)
    expiries: dict[tuple[str, int], set[str]] = {}
    for targets in all_targets:
        for target in targets:
            expiries.setdefault(
                (target.strategy_id, target.exit_common_session_sequence_id),
                set(),
            ).add(target.sleeve_id)
    candle_index = {(item.contract_id, item.opened_at): item for item in prepared.bundle.candles}
    initial_matrix = create_v8_evaluation_ledger_matrix(
        prepared.bundle,
        prepared.trusted_candle_index,
        initial_cash=initial,
    )
    states: list[V8EventLedgerState] = []
    all_orders: list[V8OrderBinding] = []
    all_evidence: list[V8ScenarioExecutionEvidence] = []
    failures: list[V8EvaluationFailureEvent] = []
    stateful_grid = _stateful_bar_grid(prepared)
    breakout_states = {
        scenario.scenario_id: {
            asset_id: BreakoutScenarioState.create(
                scenario.scenario_id,
                prepared.bundle.calendar_sha256,
            )
            for asset_id in V8_ASSET_IDS
        }
        for scenario in fixed_v8_scenarios()
    }
    for asset_id in V8_ASSET_IDS:
        assert_exact_scenario_partition(
            tuple(
                breakout_states[scenario.scenario_id][asset_id]
                for scenario in fixed_v8_scenarios()
            )
        )
    corridor_positions = {
        scenario.scenario_id: {} for scenario in fixed_v8_scenarios()
    }
    if len({id(item) for item in corridor_positions.values()}) != 3:
        raise RuntimeError("corridor scenario position registries must be isolated")
    for initial_state in initial_matrix.ledgers:
        state = replace(
            initial_state,
            equity_curve=(
                V8EquityPoint(
                    marked_at=prepared.calendar[0].decision_at,
                    cash=initial,
                    equity=initial,
                    gross_notional=0.0,
                    initial_margin=0.0,
                ),
            ),
        )
        if state.strategy_id == CORRIDOR_STRATEGY_ID:
            state, orders, evidence_rows, stateful_failures = (
                _run_corridor_stateful_ledger(
                    prepared,
                    state,
                    all_targets,
                    stateful_grid,
                    corridor_positions[state.scenario_id],
                )
            )
            states.append(state)
            all_orders.extend(orders)
            all_evidence.extend(evidence_rows)
            failures.extend(stateful_failures)
            continue
        if state.strategy_id == BREAKOUT_STRATEGY_ID:
            state, orders, evidence_rows, stateful_failures = (
                _run_breakout_stateful_ledger(
                    prepared,
                    state,
                    all_targets,
                    stateful_grid,
                    breakout_states[state.scenario_id],
                )
            )
            states.append(state)
            all_orders.extend(orders)
            all_evidence.extend(evidence_rows)
            failures.extend(stateful_failures)
            continue
        for index, session in enumerate(prepared.calendar):
            prediction = prepared.bundle.predictions[index]
            exit_bindings: list[V8OrderBinding] = []
            for sleeve_id in sorted(
                expiries.get(
                    (state.strategy_id, session.entry_common_session_sequence_id),
                    set(),
                )
            ):
                exit_bindings.extend(
                    build_v8_sleeve_exit_bindings(
                        state,
                        sleeve_id=sleeve_id,
                        decision_at=session.decision_at,
                        effective_session_date=(session.entry_effective_session_date),
                    )
                )
            ordered_exits = _reprioritize_bindings(
                tuple(sorted(exit_bindings, key=lambda item: item.request.order_id)),
                first_priority=0,
            )
            reference_prices = {
                contract.contract_id: asset.close
                for contract, asset in zip(
                    prediction.contracts,
                    prediction.context.assets,
                    strict=True,
                )
            }
            entry_bindings = build_v8_entry_bindings(
                all_targets[index],
                strategy_id=state.strategy_id,
                portfolio_equity=state.equity_curve[-1].equity,
                reference_prices=reference_prices,
                specs=prepared.bundle.contract_specs,
            )
            ordered_entries = _reprioritize_bindings(
                entry_bindings,
                first_priority=len(ordered_exits),
            )
            bindings = (*ordered_exits, *ordered_entries)
            marks = _settlement_marks(state, bindings, candle_index, session)
            if bindings:
                scenario_evidence = plan_v8_scenario_execution(
                    bindings,
                    prepared.trusted_candle_index,
                    state.scenario_id,
                )
                state = apply_v8_execution_batch(
                    state,
                    bindings,
                    scenario_evidence,
                    prepared.bundle.contract_specs,
                    trusted_candles=prepared.trusted_candle_index,
                    accounting_as_of=session.accounting_as_of,
                    risk_marks=marks,
                )
                all_orders.extend(bindings)
                all_evidence.extend(scenario_evidence)
                for evidence in scenario_evidence:
                    if evidence.carry_contracts:
                        failures.append(
                            V8EvaluationFailureEvent(
                                phase="execution",
                                code="unresolved_execution_carry",
                                message=";".join(leg.reason for leg in evidence.legs),
                                strategy_id=state.strategy_id,
                                scenario_id=state.scenario_id,
                                decision_at=session.decision_at,
                            )
                        )
            open_marks = {
                item.key.contract_id: marks[item.key.contract_id] for item in state.positions
            }
            state = settle_v8_event_ledger(
                state,
                prepared.bundle.contract_specs,
                open_marks,
                marked_at=session.settlement_at,
                effective_session_date=session.entry_effective_session_date,
                accounting_as_of=session.accounting_as_of,
            )
        if state.positions or state.unresolved_orders:
            failures.append(
                V8EvaluationFailureEvent(
                    phase="terminal",
                    code="unresolved_terminal_state_no_synthetic_liquidation",
                    message=(
                        f"positions={len(state.positions)}, "
                        f"unresolved_orders={len(state.unresolved_orders)}"
                    ),
                    strategy_id=state.strategy_id,
                    scenario_id=state.scenario_id,
                )
            )
        states.append(state)
    matrix = V8EvaluationLedgerMatrix(
        prediction_sha256=prepared.bundle.prediction_sha256,
        evaluation_bundle_sha256=prepared.bundle.evaluation_bundle_sha256,
        trusted_candle_panel_sha256=(
            prepared.trusted_candle_index.candle_panel_sha256
        ),
        candle_trust_status=prepared.trusted_candle_index.trust_status,
        ledgers=tuple(states),
    )
    metrics, gates = _derive_metrics_and_gates(matrix, all_evidence, failures)
    return V8EvaluationRunResult(
        mode=resolved_mode,
        research_status=V8_SYNTHETIC_RESEARCH_STATUS,
        prepared_identity_sha256=prepared.prepared_identity_sha256,
        source_identity_sha256=prepared.verified.source_identity_sha256,
        code_identity_sha256=prepared.verified.code_identity["code_identity_sha256"],
        prediction_sha256=prepared.bundle.prediction_sha256,
        evaluation_bundle_sha256=prepared.bundle.evaluation_bundle_sha256,
        decision_rows=decisions,
        orders=tuple(all_orders),
        evidence=tuple(all_evidence),
        ledger_matrix=matrix,
        metrics=metrics,
        gates_and_ranking=gates,
        failure_events=tuple(failures),
    )


@dataclass(frozen=True, slots=True)
class V8PersistedArtifact:
    """Byte i semantic identity odnogo atomarno zapisannogo artifacta."""

    kind: str
    path: Path
    byte_sha256: str
    content_sha256: str
    bytes: int
    rows: int

    def __post_init__(self) -> None:
        """Proveryaet registry, hashes i nonnegative size/rows."""
        if self.kind not in V8_EVALUATION_ARTIFACT_KINDS:
            raise ValueError("persisted artifact kind vne registry")
        object.__setattr__(self, "byte_sha256", _require_sha256(self.byte_sha256, "byte_sha256"))
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        for name in ("bytes", "rows"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"artifact {name} dolzhen byt' nonnegative int")


@dataclass(frozen=True, slots=True)
class V8PersistedEvaluationRun:
    """Final manifest identity synthetic test runa."""

    output_directory: Path
    manifest_path: Path
    manifest_sha256: str
    artifacts: tuple[V8PersistedArtifact, ...]


def _write_content_addressed_bytes(
    root: Path,
    output_directory: Path,
    *,
    kind: str,
    suffix: str,
    content: bytes,
    content_sha256: str,
    rows: int,
) -> V8PersistedArtifact:
    """Atomarno zapisivaet immutable bytes po ih sobstvennomu SHA filename."""
    byte_hash = sha256(content).hexdigest()
    output = _bounded_path(root, output_directory, "evaluation output directory")
    output.mkdir(parents=True, exist_ok=True)
    path = _bounded_path(output, Path(f"{kind}-{byte_hash}.{suffix}"), "artifact path")
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError("content-addressed artifact filename collision")
    else:
        atomic_write_bytes(path, content)
    return V8PersistedArtifact(
        kind=kind,
        path=path,
        byte_sha256=byte_hash,
        content_sha256=content_sha256,
        bytes=len(content),
        rows=rows,
    )


def _write_json_artifact(
    root: Path,
    output_directory: Path,
    *,
    kind: str,
    rows: Sequence[Any],
) -> V8PersistedArtifact:
    """Upakovyvaet audit rows v BOM JSON i atomarno content-addresses ih."""
    frozen_rows = tuple(rows)
    payload = {
        "format": V8_EVALUATION_RUN_FORMAT,
        "kind": kind,
        "row_count": len(frozen_rows),
        "rows": frozen_rows,
    }
    return _write_content_addressed_bytes(
        root,
        output_directory,
        kind=kind,
        suffix="json",
        content=_canonical_json_bytes(payload, bom=True),
        content_sha256=_payload_sha256(payload),
        rows=len(frozen_rows),
    )


def _audit_result_derivations(result: V8EvaluationRunResult) -> None:
    """Pereschityvaet metrics/gates/result seal i blokiruet forged caller payload."""
    metrics, gates = _derive_metrics_and_gates(
        result.ledger_matrix,
        result.evidence,
        result.failure_events,
    )
    if canonical_sha256(metrics) != canonical_sha256(result.metrics):
        raise ValueError("result soderzhit forged/caller-supplied metrics")
    if canonical_sha256(gates) != canonical_sha256(result.gates_and_ranking):
        raise ValueError("result soderzhit forged/caller-supplied gates/ranking")
    rebuilt = replace(result)
    if rebuilt.result_sha256 != result.result_sha256:
        raise ValueError("result semantic SHA mismatch")


def _fresh_prepared_copy(prepared: V8PreparedEvaluation) -> V8PreparedEvaluation:
    """Rehashiruet manifests/artifacts/code i zanovo stroit PIT bundle pered persist."""
    fresh = prepare_v8_evaluation(_verification_request_from_verified(prepared.verified))
    if fresh.prepared_identity_sha256 != prepared.prepared_identity_sha256:
        raise ValueError("prepared input izmenilsya mezhdu run i persistence")
    return fresh


def _result_report(result: V8EvaluationRunResult) -> str:
    """Stroit korotkii report s yavnym synthetic/NO-GO disclosure."""
    passed = tuple(item.strategy_id for item in result.gates_and_ranking.outcomes if item.passed)
    lines = [
        "# Futures V8 evaluation report",
        "",
        f"Status: `{result.research_status}`.",
        "",
        "This artifact is synthetic plumbing evidence and is not real PnL.",
        "",
        f"Prediction SHA-256: `{result.prediction_sha256}`.",
        f"Evaluation bundle SHA-256: `{result.evaluation_bundle_sha256}`.",
        f"Failure events: {len(result.failure_events)}.",
        f"Gate-passing strategies: {', '.join(passed) if passed else 'none'}.",
        "",
        "Authoritative evaluation remains blocked until the audited stateful "
        "corridor/breakout stress-transition boundary is available.",
        "",
    ]
    return "\n".join(lines)


def persist_v8_evaluation_result(
    result: V8EvaluationRunResult,
    *,
    prepared: V8PreparedEvaluation,
    project_root: Path,
    output_directory: Path,
) -> V8PersistedEvaluationRun:
    """Atomarno persistit internal result; success manifest zapisivaet poslednim."""
    if not isinstance(result, V8EvaluationRunResult):
        raise TypeError("result dolzhen byt' V8EvaluationRunResult")
    _audit_result_derivations(result)
    fresh = _fresh_prepared_copy(prepared)
    if result.prepared_identity_sha256 != fresh.prepared_identity_sha256:
        raise ValueError("result/prepared identity mismatch")
    initial_cash_values = {item.initial_cash for item in result.ledger_matrix.ledgers}
    if len(initial_cash_values) != 1:
        raise ValueError("result ledgers ne imeyut edinogo initial cash")
    replayed = run_v8_evaluation(
        fresh,
        initial_cash=next(iter(initial_cash_values)),
        mode=result.mode,
    )
    if replayed.result_sha256 != result.result_sha256:
        raise ValueError("result equity/orders ne sovpali s deterministic replay")
    root = project_root.resolve()
    if root != fresh.verified.project_root:
        raise ValueError("persistence project_root ne raven verified project root")
    output = _bounded_path(root, output_directory, "evaluation output directory")
    input_identity = (
        {
            "prepared_identity_sha256": result.prepared_identity_sha256,
            "source_identity_sha256": result.source_identity_sha256,
            "prediction_sha256": result.prediction_sha256,
            "evaluation_bundle_sha256": result.evaluation_bundle_sha256,
            "research_status": result.research_status,
            "readiness_audit_sha256": fresh.readiness_audit.audit_sha256,
            "readiness_counters": {
                "model_input_invalid_count": (fresh.readiness_audit.model_input_invalid_count),
                "active_contract_inactive_count": (
                    fresh.readiness_audit.active_contract_inactive_count
                ),
                "validity_activity_mismatch_count": (
                    fresh.readiness_audit.validity_activity_mismatch_count
                ),
                "executable_asset_count": (fresh.readiness_audit.executable_asset_count),
            },
            "sources": tuple(
                {
                    "kind": item.kind,
                    "manifest_sha256": item.manifest_sha256,
                    "artifact_sha256": item.artifact_sha256,
                    "bytes": item.artifact_bytes,
                    "rows": item.rows,
                }
                for item in fresh.verified.sources
            ),
        },
    )
    code_identity = (fresh.verified.code_identity,)
    fill_rows = tuple(
        {
            "strategy_id": ledger.strategy_id,
            "scenario_id": ledger.scenario_id,
            "fill": fill,
        }
        for ledger in result.ledger_matrix.ledgers
        for fill in ledger.fills
    )
    equity_rows = tuple(
        {
            "strategy_id": ledger.strategy_id,
            "scenario_id": ledger.scenario_id,
            "point": point,
        }
        for ledger in result.ledger_matrix.ledgers
        for point in ledger.equity_curve
    )
    row_payloads: tuple[tuple[str, Sequence[Any]], ...] = (
        ("input_identity", input_identity),
        ("code_identity", code_identity),
        ("decisions", result.decision_rows),
        ("orders", result.orders),
        ("execution_evidence", result.evidence),
        ("fills", fill_rows),
        ("equity", equity_rows),
        ("scenario_metrics", result.metrics),
        ("gates", result.gates_and_ranking.outcomes),
        ("ranking", result.gates_and_ranking.aggressive_ranking),
        ("failure_events", result.failure_events),
    )
    artifacts = [
        _write_json_artifact(root, output, kind=kind, rows=rows) for kind, rows in row_payloads
    ]
    report = _result_report(result).encode("utf-8-sig")
    artifacts.append(
        _write_content_addressed_bytes(
            root,
            output,
            kind="report",
            suffix="md",
            content=report,
            content_sha256=sha256(report.removeprefix(b"\xef\xbb\xbf")).hexdigest(),
            rows=len(report.decode("utf-8-sig").splitlines()),
        )
    )
    manifest_payload = {
        "format": V8_EVALUATION_RUN_FORMAT,
        "mode": result.mode,
        "research_status": result.research_status,
        "result_sha256": result.result_sha256,
        "artifacts": tuple(
            {
                "kind": item.kind,
                "path": item.path.relative_to(root).as_posix(),
                "byte_sha256": item.byte_sha256,
                "content_sha256": item.content_sha256,
                "bytes": item.bytes,
                "rows": item.rows,
            }
            for item in artifacts
        ),
    }
    manifest_bytes = _canonical_json_bytes(manifest_payload, bom=True)
    manifest_hash = sha256(manifest_bytes).hexdigest()
    manifest_path = _bounded_path(
        output,
        Path(f"evaluation-run-{manifest_hash}.json"),
        "evaluation manifest path",
    )
    if manifest_path.exists():
        if manifest_path.read_bytes() != manifest_bytes:
            raise RuntimeError("evaluation manifest content-address collision")
    else:
        atomic_write_bytes(manifest_path, manifest_bytes)
    return V8PersistedEvaluationRun(
        output_directory=output,
        manifest_path=manifest_path,
        manifest_sha256=manifest_hash,
        artifacts=tuple(artifacts),
    )


def persist_v8_evaluation_failure(
    prepared: V8PreparedEvaluation,
    error: BaseException,
    *,
    project_root: Path,
    output_directory: Path,
) -> V8PersistedArtifact:
    """Persistit fail event bez success manifesta posle blocked/exception runa."""
    event = V8EvaluationFailureEvent(
        phase="run",
        code=type(error).__name__,
        message=str(error) or type(error).__name__,
    )
    rows = (
        {
            "prepared_identity_sha256": prepared.prepared_identity_sha256,
            "source_identity_sha256": prepared.verified.source_identity_sha256,
            "code_identity_sha256": prepared.verified.code_identity["code_identity_sha256"],
            "event": event,
        },
    )
    return _write_json_artifact(
        project_root.resolve(),
        output_directory,
        kind="failure_events",
        rows=rows,
    )


def run_and_persist_v8_evaluation(
    prepared: V8PreparedEvaluation,
    *,
    initial_cash: float,
    mode: V8EvaluationMode | str,
    project_root: Path,
    output_directory: Path,
) -> V8PersistedEvaluationRun:
    """Zapuskaet i persistit result ili failure event, nikogda ne pishet false success."""
    try:
        result = run_v8_evaluation(
            prepared,
            initial_cash=initial_cash,
            mode=mode,
        )
    except Exception as error:
        persist_v8_evaluation_failure(
            prepared,
            error,
            project_root=project_root,
            output_directory=output_directory,
        )
        raise
    return persist_v8_evaluation_result(
        result,
        prepared=prepared,
        project_root=project_root,
        output_directory=output_directory,
    )


__all__ = [
    "V8_AUDITED_ENRICHMENT_STATUS",
    "V8_BASE_PREDICTION_COLUMNS",
    "V8_CALENDAR_COLUMNS",
    "V8_ENRICHMENT_COLUMNS",
    "V8_EVALUATION_CODE_PATHS",
    "V8_EVALUATION_RUN_FORMAT",
    "V8_EVALUATION_SOURCE_FORMAT",
    "V8_FULL_CAUSAL_CONTEXT_STATUS",
    "V8_PROTECTED_HOLDOUT_START",
    "V8_REQUIRED_COMPLETED_CHECKPOINTS",
    "V8_REQUIRED_SOURCE_DEPENDENCIES",
    "V8_REQUIRED_SOURCE_KINDS",
    "V8_SPEC_PROXY_COLUMNS",
    "V8_STATEFUL_STRATEGY_IDS",
    "V8_SYNTHETIC_RESEARCH_STATUS",
    "V8_TEN_MINUTE_COLUMNS",
    "V8_ACTIVE_MAP_COLUMNS",
    "V8EvaluationBlockedError",
    "V8EvaluationCalendarSession",
    "V8DecisionEligibilityAudit",
    "V8EvaluationFailureEvent",
    "V8EvaluationMode",
    "V8EvaluationReadinessAudit",
    "V8EvaluationRunResult",
    "V8EvaluationSourceSeal",
    "V8EvaluationVerificationRequest",
    "V8LoadedEvaluationInputs",
    "V8PersistedArtifact",
    "V8PersistedEvaluationRun",
    "V8PreparedEvaluation",
    "V8VerifiedEvaluationSource",
    "V8VerifiedEvaluationSources",
    "build_v8_evaluation_code_identity",
    "audit_loaded_v8_evaluation_readiness",
    "inspect_v8_evaluation_readiness",
    "load_verified_v8_evaluation_inputs",
    "persist_v8_evaluation_failure",
    "persist_v8_evaluation_result",
    "prepare_v8_evaluation",
    "prepare_verified_v8_evaluation",
    "run_and_persist_v8_evaluation",
    "run_v8_evaluation",
    "verify_v8_evaluation_sources",
]
