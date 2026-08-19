"""Build a pending admission-v2 candidate from sealed target-free real artifacts.

This module is deliberately not an authoritative release mechanism.  It normalizes the
seven admitted sources, writes content-addressed pending wrappers and emits a candidate
certificate whose independent-audit digest is the all-zero placeholder.  It never edits
the code-pinned trust anchor.

Only explicitly listed target-free inputs are accepted.  All direct dependency bytes are
verified before any JSON or Parquet parsing, and every nested checkpoint/MOEX path is
validated as a complete set before its bytes are opened.  Assembly, labels, targets, PnL
and protected 2026+ market artifacts are outside the input type and rejected by path/schema
guards before I/O.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
from pyarrow import parquet as pq

from market_lab.futures_v8.admission import (
    V8_ADMISSION_CERTIFICATE_FORMAT,
    V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER,
    V8_ASSET_IDS,
    V8_BASE_PREDICTION_COLUMNS,
    V8_CALENDAR_COLUMNS,
    V8_CHECKPOINT_COUNT,
    V8_CHECKPOINT_IDENTITY_COLUMNS,
    V8_DECISION_ROW_COUNT,
    V8_EXACT_SOURCE_COLUMNS,
    V8_FULL_CONTEXT_COLUMNS,
    V8_INITIAL_CAPITAL_RUB,
    V8_INVALID_ROW_POLICY,
    V8_MOEX_10M_COLUMNS,
    V8_NORMALIZED_SOURCE_FORMAT,
    V8_PANEL_KEY_COLUMNS,
    V8_PANEL_ROW_COUNT,
    V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS,
    V8_PROTECTED_HOLDOUT_START,
    V8_REGIME_V2_COLUMNS,
    V8_REQUIRED_SOURCE_DEPENDENCIES,
    V8_REQUIRED_SOURCE_KINDS,
    V8_SCENARIO_IDS,
    V8_SPEC_PROXY_COLUMNS,
    V8_STRATEGY_ELIGIBILITY_FORMULA,
    V8_STRATEGY_IDS,
    V8_VALIDITY_MASK_COLUMNS,
    V8SourceKind,
    compute_v8_normalized_source_identity_sha256,
)
from market_lab.io_utils import atomic_write_bytes

V8_ADMISSION_CANDIDATE_STATUS: Final[str] = "pending_independent_audit"
V8_CHECKPOINT_NORMALIZATION_FORMAT: Final[str] = (
    "market-lab-futures-v8-checkpoint-inventory-normalized-v2"
)
V8_MOEX_COVERAGE_FORMAT: Final[str] = "market-lab-futures-v8-moex-10m-coverage-index-v2"
V8_CALENDAR_ARTIFACT_FORMAT: Final[str] = "market-lab-futures-v8-calendar-v2"
V8_SPEC_ARTIFACT_FORMAT: Final[str] = "market-lab-futures-v8-spec-proxy-normalized-v2"
V8_REAL_MOEX_PARQUET_CHILDREN: Final[int] = 219
V8_REAL_MOEX_ROWS: Final[int] = 1_699_545
V8_CONTEXT_MANIFEST_PAYLOAD_SHA256: Final[str] = (
    "b430e90ddf07890b24ba6d64d019c4761099891e8d2025a09f6ce0e072d4e915"
)
MOSCOW_TIMEZONE: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")

_FORBIDDEN_PATH_FRAGMENTS: Final[tuple[str, ...]] = (
    "assembly",
    "target",
    "label",
    "pnl",
    "p&l",
    "profit",
)
_FORBIDDEN_COLUMN_FRAGMENTS: Final[tuple[str, ...]] = (
    "target",
    "label",
    "future_return",
    "realized_return",
    "pnl",
    "p&l",
    "profit_loss",
    "assembly",
)
_PROTECTED_YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_BOM: Final[bytes] = b"\xef\xbb\xbf"

_RAW_SPEC_COLUMNS: Final[tuple[str, ...]] = (
    "session_date",
    "asset_symbol",
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
_RAW_MOEX_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "end_timestamp",
    "asset_code",
    "logical_symbol",
    "canonical_contract_id",
    "canonical_segment_id",
    "secid",
    "board_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
)
_MOEX_TIMESTAMP_COLUMNS: Final[tuple[str, ...]] = ("timestamp", "end_timestamp")
_BASE_CALENDAR_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
)
_PANEL_KINDS: Final[frozenset[V8SourceKind]] = frozenset(
    {
        V8SourceKind.BASE_PREDICTIONS,
        V8SourceKind.REGIME_V2,
        V8SourceKind.FULL_CONTEXT,
    }
)


class V8AdmissionBuildError(ValueError):
    """A pending candidate could not be built without weakening an invariant."""


@dataclass(frozen=True, slots=True)
class V8AdmissionInputSeal:
    """One exact, explicitly permitted project-relative build dependency."""

    role: str
    relative_path: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        if not self.role or not isinstance(self.role, str):
            raise TypeError("admission input role must be a nonempty string")
        _require_safe_relative_path(self.relative_path, f"{self.role} input path")
        _require_sha256(self.sha256, f"{self.role} input SHA")
        _require_positive_int(self.bytes, f"{self.role} input bytes")


@dataclass(frozen=True, slots=True)
class V8AdmissionBuildInputs:
    """Closed direct-input set; forbidden assembly/target sources have no fields."""

    project_root: Path
    checkpoint_inventory: V8AdmissionInputSeal
    base_predictions: V8AdmissionInputSeal
    regime_manifest: V8AdmissionInputSeal
    regime_artifact: V8AdmissionInputSeal
    context_manifest: V8AdmissionInputSeal
    context_artifact: V8AdmissionInputSeal
    spec_manifest: V8AdmissionInputSeal
    spec_artifact: V8AdmissionInputSeal
    moex_10m_manifest: V8AdmissionInputSeal
    base_protocol: V8AdmissionInputSeal
    context_protocol: V8AdmissionInputSeal
    context_implementation: V8AdmissionInputSeal
    context_manifest_payload_sha256: str
    expected_moex_children: int = V8_REAL_MOEX_PARQUET_CHILDREN
    expected_moex_rows: int = V8_REAL_MOEX_ROWS

    def __post_init__(self) -> None:
        root = Path(self.project_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"project root does not exist: {root}")
        object.__setattr__(self, "project_root", root)
        expected_roles = (
            "checkpoint_inventory",
            "base_predictions",
            "regime_manifest",
            "regime_artifact",
            "context_manifest",
            "context_artifact",
            "spec_manifest",
            "spec_artifact",
            "moex_10m_manifest",
            "base_protocol",
            "context_protocol",
            "context_implementation",
        )
        if tuple(item.role for item in self.direct_seals) != expected_roles:
            raise V8AdmissionBuildError("admission input roles are not the exact closed set")
        _require_sha256(
            self.context_manifest_payload_sha256,
            "context manifest payload SHA",
        )
        _require_positive_int(self.expected_moex_children, "expected MOEX children")
        _require_positive_int(self.expected_moex_rows, "expected MOEX rows")

    @property
    def direct_seals(self) -> tuple[V8AdmissionInputSeal, ...]:
        """Return the complete direct-input tuple in verification order."""

        return (
            self.checkpoint_inventory,
            self.base_predictions,
            self.regime_manifest,
            self.regime_artifact,
            self.context_manifest,
            self.context_artifact,
            self.spec_manifest,
            self.spec_artifact,
            self.moex_10m_manifest,
            self.base_protocol,
            self.context_protocol,
            self.context_implementation,
        )


@dataclass(frozen=True, slots=True)
class V8VerifiedBuildInput:
    """Direct input whose byte count and SHA were checked before parsing."""

    seal: V8AdmissionInputSeal
    path: Path


@dataclass(frozen=True, slots=True)
class V8BuiltArtifact:
    """One direct or generated normalized artifact used by a source wrapper."""

    relative_path: str
    sha256: str
    bytes: int
    rows: int
    columns: tuple[str, ...]
    minimum_session_date: date
    maximum_session_date: date


@dataclass(frozen=True, slots=True)
class V8BuiltSourceWrapper:
    """One pending source wrapper and the artifact identity it seals."""

    kind: V8SourceKind
    manifest_relative_path: str
    manifest_sha256: str
    source_identity_sha256: str
    artifact: V8BuiltArtifact


@dataclass(frozen=True, slots=True)
class V8CalendarNormalization:
    """Exact target-free calendar plus its semantic key identities."""

    frame: pd.DataFrame
    decision_calendar_sha256: str
    decision_asset_key_set_sha256: str
    year_counts: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class V8MoexCoverage:
    """Complete byte-verified 10-minute child index without merging market rows."""

    payload: Mapping[str, Any]
    rows: int
    minimum_session_date: date
    maximum_session_date: date
    child_bundle_sha256: str


@dataclass(frozen=True, slots=True)
class V8AdmissionCandidateBuild:
    """Persisted pending candidate; never an authoritative admission object."""

    output_directory: Path
    certificate_path: Path
    certificate_sha256: str
    certificate_payload_sha256: str
    sources: tuple[V8BuiltSourceWrapper, ...]
    input_bundle_sha256: str
    builder_code_identity_sha256: str

    def source(self, kind: V8SourceKind | str) -> V8BuiltSourceWrapper:
        resolved = V8SourceKind(kind)
        for source in self.sources:
            if source.kind is resolved:
                return source
        raise KeyError(resolved.value)


def _require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise V8AdmissionBuildError(f"{label} must be a positive integer")
    return value


def _require_sha256(value: Any, label: str, *, placeholder_allowed: bool = False) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise V8AdmissionBuildError(f"{label} must be a lowercase SHA-256")
    if not placeholder_allowed and value == V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER:
        raise V8AdmissionBuildError(f"{label} cannot be the pending placeholder")
    return value


def _contains_forbidden_path(value: str) -> bool:
    lowered = value.casefold()
    return any(fragment in lowered for fragment in _FORBIDDEN_PATH_FRAGMENTS)


def _contains_forbidden_column(value: str) -> bool:
    lowered = value.casefold()
    return any(fragment in lowered for fragment in _FORBIDDEN_COLUMN_FRAGMENTS)


def _require_safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise V8AdmissionBuildError(f"{label} must be a nonempty string")
    if "\\" in value or _contains_forbidden_path(value):
        raise V8AdmissionBuildError(f"{label} contains forbidden assembly/target/PnL path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or ":" in path.parts[0]
    ):
        raise V8AdmissionBuildError(f"{label} must be normalized project-relative POSIX")
    for match in _PROTECTED_YEAR_PATTERN.finditer(value):
        if int(match.group(1)) >= V8_PROTECTED_HOLDOUT_START.year:
            raise V8AdmissionBuildError(f"{label} contains protected 2026+ path")
    return value


def _bounded_path(root: Path, relative_path: str, label: str) -> Path:
    resolved = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise V8AdmissionBuildError(f"{label} escapes project root") from error
    return resolved


def _project_relative(root: Path, path: Path, label: str) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise V8AdmissionBuildError(f"{label} must remain inside project root") from error
    return _require_safe_relative_path(relative, label)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _json_bom_bytes(payload: Any) -> bytes:
    text = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    )
    return _BOM + (text + "\n").encode("utf-8")


def _read_verified_bom_json(verified: V8VerifiedBuildInput) -> Mapping[str, Any]:
    content = verified.path.read_bytes()
    if len(content) != verified.seal.bytes or hashlib.sha256(content).hexdigest() != verified.seal.sha256:
        raise V8AdmissionBuildError(f"{verified.seal.role} changed after byte verification")
    if not content.startswith(_BOM):
        raise V8AdmissionBuildError(f"{verified.seal.role} must be UTF-8 BOM JSON")
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V8AdmissionBuildError(f"{verified.seal.role} is not valid BOM JSON") from error
    if not isinstance(payload, dict):
        raise V8AdmissionBuildError(f"{verified.seal.role} must contain a JSON object")
    return payload


def _verify_direct_inputs(inputs: V8AdmissionBuildInputs) -> Mapping[str, V8VerifiedBuildInput]:
    """Validate the full path set, then hash all direct bytes before any parsing."""

    root = inputs.project_root
    paths: dict[str, Path] = {}
    for seal in inputs.direct_seals:
        relative = _require_safe_relative_path(seal.relative_path, f"{seal.role} path")
        path = _bounded_path(root, relative, f"{seal.role} path")
        paths[seal.role] = path
    if len(set(paths.values())) != len(paths):
        raise V8AdmissionBuildError("direct admission input paths must be unique")
    for seal in inputs.direct_seals:
        path = paths[seal.role]
        if not path.is_file() or path.stat().st_size != seal.bytes:
            raise V8AdmissionBuildError(f"{seal.role} byte count mismatch")
        if _sha256_file(path) != seal.sha256:
            raise V8AdmissionBuildError(f"{seal.role} byte SHA mismatch")
    return {
        seal.role: V8VerifiedBuildInput(seal=seal, path=paths[seal.role])
        for seal in inputs.direct_seals
    }


def _assert_exact_parquet_schema(path: Path, expected: Sequence[str], label: str) -> int:
    parquet = pq.ParquetFile(path)
    columns = tuple(parquet.schema.names)
    if any(_contains_forbidden_column(column) for column in columns):
        raise V8AdmissionBuildError(f"{label} contains forbidden target/PnL/assembly schema")
    if columns != tuple(expected):
        raise V8AdmissionBuildError(f"{label} exact Parquet schema mismatch")
    return int(parquet.metadata.num_rows)


def _read_exact_parquet(path: Path, expected: Sequence[str], label: str) -> pd.DataFrame:
    rows = _assert_exact_parquet_schema(path, expected, label)
    frame = pd.read_parquet(path, columns=list(expected))
    if len(frame) != rows or tuple(frame.columns) != tuple(expected):
        raise V8AdmissionBuildError(f"{label} changed during explicit-column read")
    return frame


def _read_whitelisted_parquet(
    path: Path,
    columns: Sequence[str],
    label: str,
) -> pd.DataFrame:
    parquet = pq.ParquetFile(path)
    schema = tuple(parquet.schema.names)
    if any(_contains_forbidden_column(column) for column in schema):
        raise V8AdmissionBuildError(f"{label} contains forbidden target/PnL/assembly schema")
    if not set(columns).issubset(schema):
        raise V8AdmissionBuildError(f"{label} lacks an explicit whitelisted column")
    frame = pd.read_parquet(path, columns=list(columns))
    if len(frame) != parquet.metadata.num_rows:
        raise V8AdmissionBuildError(f"{label} row count changed during explicit read")
    return frame


def _assert_pre_holdout_timestamps(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    for column in columns:
        values = pd.to_datetime(frame[column], errors="coerce", utc=True).dropna()
        if values.empty:
            continue
        local_dates = values.dt.tz_convert(MOSCOW_TIMEZONE).dt.date
        if local_dates.ge(V8_PROTECTED_HOLDOUT_START).any():
            raise V8AdmissionBuildError(f"{label}.{column} reaches protected 2026")


def _strict_boolean_series(series: pd.Series, label: str) -> pd.Series:
    if series.isna().any() or not series.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise V8AdmissionBuildError(f"{label} must contain strict non-null booleans")
    return series.astype(bool)


def _equal_with_nan(left: pd.Series, right: pd.Series) -> bool:
    left_values = pd.to_numeric(left, errors="coerce").to_numpy(dtype=np.float64)
    right_values = pd.to_numeric(right, errors="coerce").to_numpy(dtype=np.float64)
    return bool(np.array_equal(left_values, right_values, equal_nan=True))


def _persist_content_addressed_bytes(
    output_directory: Path,
    stem: str,
    suffix: str,
    content: bytes,
) -> tuple[Path, str, int]:
    sha256 = hashlib.sha256(content).hexdigest()
    path = output_directory / f"{stem}_{sha256[:16]}{suffix}"
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise V8AdmissionBuildError(f"content-addressed collision: {path}")
    else:
        atomic_write_bytes(path, content)
    if path.stat().st_size != len(content) or _sha256_file(path) != sha256:
        raise V8AdmissionBuildError(f"persisted artifact failed reload: {path}")
    return path, sha256, len(content)


def _parquet_bytes(
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, str],
) -> bytes:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    encoded_metadata = {
        key.encode("utf-8"): value.encode("utf-8") for key, value in sorted(metadata.items())
    }
    table = table.replace_schema_metadata(encoded_metadata)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
    )
    return sink.getvalue().to_pybytes()

