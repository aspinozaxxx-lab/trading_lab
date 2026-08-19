"""Synthetic-only tests for the fail-closed futures-v8 admission-v2 foundation."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import market_lab.futures_v8.admission as admission
from market_lab.futures_v8.admission import (
    V8_ADMISSION_CERTIFICATE_FORMAT,
    V8_ADMISSION_CERTIFICATE_PATH,
    V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER,
    V8_ASSET_IDS,
    V8_AUTHORITATIVE_ADMISSION_STATUS,
    V8_DECISION_ROW_COUNT,
    V8_EXACT_SOURCE_COLUMNS,
    V8_FULL_CONTEXT_COLUMNS,
    V8_INDEPENDENT_AUDIT_STATUS,
    V8_INITIAL_CAPITAL_RUB,
    V8_INVALID_ROW_POLICY,
    V8_LEDGER_COUNT,
    V8_NORMALIZED_SOURCE_FORMAT,
    V8_PANEL_KEY_COLUMNS,
    V8_PANEL_ROW_COUNT,
    V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS,
    V8_REQUIRED_SOURCE_DEPENDENCIES,
    V8_REQUIRED_SOURCE_KINDS,
    V8_SCENARIO_IDS,
    V8_STRATEGY_ELIGIBILITY_FORMULA,
    V8_STRATEGY_IDS,
    V8_VALIDITY_MASK_COLUMNS,
    V8AdmissionBlockedError,
    V8AdmissionError,
    V8AdmissionTrustAnchor,
    V8SourceKind,
    compute_v8_normalized_source_identity_sha256,
    verify_v8_authoritative_admission,
)
from market_lab.futures_v8.eval_run import (
    V8_STRATEGY_IDS as V8_RUNTIME_STRATEGY_IDS,
)
from market_lab.futures_v8.eval_run import (
    V8ScenarioId,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
YEAR_COUNTS = {"2021": 252, "2022": 252, "2023": 252, "2024": 256, "2025": 257}


@dataclass(frozen=True, slots=True)
class _AdmissionFixture:
    """One complete fake control graph with tiny opaque artifact bytes."""

    project_root: Path
    certificate_sha256: str
    artifact_paths: tuple[Path, ...]


def _write_bom_json(path: Path, payload: object) -> str:
    """Write a small deterministic BOM control and return its byte SHA."""

    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
    )
    path.write_text(content, encoding="utf-8-sig", newline="\n")
    return sha256(path.read_bytes()).hexdigest()


def _artifact_rows(kind: V8SourceKind) -> int:
    return {
        V8SourceKind.CHECKPOINT_IDENTITIES: 15,
        V8SourceKind.BASE_PREDICTIONS: V8_PANEL_ROW_COUNT,
        V8SourceKind.REGIME_V2: V8_PANEL_ROW_COUNT,
        V8SourceKind.CALENDAR: V8_DECISION_ROW_COUNT,
        V8SourceKind.SPEC_PROXY: 101,
        V8SourceKind.MOEX_10M: 303,
        V8SourceKind.FULL_CONTEXT: V8_PANEL_ROW_COUNT,
    }[kind]


def _temporal_bounds(kind: V8SourceKind) -> tuple[str, str]:
    if kind is V8SourceKind.CHECKPOINT_IDENTITIES:
        return "2018-01-01", "2020-12-31"
    if kind in {
        V8SourceKind.BASE_PREDICTIONS,
        V8SourceKind.REGIME_V2,
        V8SourceKind.CALENDAR,
        V8SourceKind.FULL_CONTEXT,
    }:
        return "2021-01-04", "2025-12-30"
    return "2018-01-01", "2025-12-31"


def _build_admission(
    tmp_path: Path,
    *,
    decision_rows: int = V8_DECISION_ROW_COUNT,
    assets: tuple[str, ...] = V8_ASSET_IDS,
    initial_capital: float = V8_INITIAL_CAPITAL_RUB,
    source_row_override: tuple[V8SourceKind, int] | None = None,
    source_columns_override: tuple[V8SourceKind, tuple[str, ...]] | None = None,
    maximum_date_override: tuple[V8SourceKind, str] | None = None,
    artifact_path_override: tuple[V8SourceKind, str] | None = None,
    dependency_override: tuple[V8SourceKind, V8SourceKind, str, str] | None = None,
    validity_masks: tuple[str, ...] = V8_VALIDITY_MASK_COLUMNS,
) -> _AdmissionFixture:
    """Build a self-consistent synthetic graph, optionally with one intended defect."""

    artifact_records: dict[V8SourceKind, dict[str, Any]] = {}
    artifact_paths: list[Path] = []
    for index, kind in enumerate(V8_REQUIRED_SOURCE_KINDS):
        relative_path = f"artifacts/{kind.value}.opaque"
        if artifact_path_override is not None and artifact_path_override[0] is kind:
            relative_path = artifact_path_override[1]
        path = tmp_path.joinpath(*Path(relative_path).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"synthetic-{index}-{kind.value}".encode("ascii")
        path.write_bytes(content)
        artifact_paths.append(path.resolve())
        rows = _artifact_rows(kind)
        if source_row_override is not None and source_row_override[0] is kind:
            rows = source_row_override[1]
        columns = V8_EXACT_SOURCE_COLUMNS[kind]
        if source_columns_override is not None and source_columns_override[0] is kind:
            columns = source_columns_override[1]
        calendar_sha: str | None = SHA_A
        panel_key_sha: str | None = None
        if kind is V8SourceKind.CHECKPOINT_IDENTITIES:
            calendar_sha = None
        elif kind in {
            V8SourceKind.BASE_PREDICTIONS,
            V8SourceKind.REGIME_V2,
            V8SourceKind.FULL_CONTEXT,
        }:
            panel_key_sha = SHA_B
        artifact_records[kind] = {
            "path": relative_path,
            "sha256": sha256(content).hexdigest(),
            "bytes": len(content),
            "rows": rows,
            "columns": list(columns),
            "decision_calendar_sha256": calendar_sha,
            "decision_asset_key_set_sha256": panel_key_sha,
        }

    source_records: dict[V8SourceKind, dict[str, Any]] = {}
    for index, kind in enumerate(V8_REQUIRED_SOURCE_KINDS):
        dependencies: dict[str, dict[str, str]] = {}
        for dependency_kind in V8_REQUIRED_SOURCE_DEPENDENCIES[kind]:
            dependency = source_records[dependency_kind]
            dependency_seal = {
                "manifest_sha256": dependency["manifest_sha256"],
                "artifact_sha256": artifact_records[dependency_kind]["sha256"],
            }
            if (
                dependency_override is not None
                and dependency_override[0] is kind
                and dependency_override[1] is dependency_kind
            ):
                dependency_seal[dependency_override[2]] = dependency_override[3]
            dependencies[dependency_kind.value] = dependency_seal
        minimum, maximum = _temporal_bounds(kind)
        if maximum_date_override is not None and maximum_date_override[0] is kind:
            maximum = maximum_date_override[1]
        source_payload: dict[str, Any] = {
            "format": V8_NORMALIZED_SOURCE_FORMAT,
            "kind": kind.value,
            "artifact": artifact_records[kind],
            "temporal_bounds": {
                "minimum_session_date": minimum,
                "maximum_session_date": maximum,
            },
            "dependencies": dependencies,
            "producer": {
                "code_identity_sha256": f"{index + 1:x}" * 64,
                "protocol_sha256": SHA_C,
                "excluded_paths": list(V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS),
            },
            "audit": {
                "status": V8_INDEPENDENT_AUDIT_STATUS,
                "certificate_sha256": SHA_D,
            },
        }
        source_payload["source_identity_sha256"] = compute_v8_normalized_source_identity_sha256(
            source_payload
        )
        manifest_relative_path = f"controls/{kind.value}.json"
        manifest_path = tmp_path / manifest_relative_path
        manifest_sha = _write_bom_json(manifest_path, source_payload)
        source_records[kind] = {
            "kind": kind.value,
            "manifest_path": manifest_relative_path,
            "manifest_sha256": manifest_sha,
            "artifact_sha256": artifact_records[kind]["sha256"],
            "source_identity_sha256": source_payload["source_identity_sha256"],
        }

    certificate = {
        "format": V8_ADMISSION_CERTIFICATE_FORMAT,
        "status": V8_AUTHORITATIVE_ADMISSION_STATUS,
        "protected_holdout_start": "2026-01-01",
        "initial_capital_rub": initial_capital,
        "calendar_contract": {
            "decision_rows": decision_rows,
            "panel_rows": V8_PANEL_ROW_COUNT,
            "assets": list(assets),
            "key_columns": list(V8_PANEL_KEY_COLUMNS),
            "minimum_decision_date": "2021-01-04",
            "maximum_decision_date": "2025-12-30",
            "year_counts": YEAR_COUNTS,
            "decision_calendar_sha256": SHA_A,
            "decision_asset_key_set_sha256": SHA_B,
        },
        "validity_contract": {
            "mask_columns": list(validity_masks),
            "strategy_eligible_formula": V8_STRATEGY_ELIGIBILITY_FORMULA,
            "invalid_row_policy": V8_INVALID_ROW_POLICY,
        },
        "ledger_contract": {
            "strategy_ids": list(V8_STRATEGY_IDS),
            "scenario_ids": list(V8_SCENARIO_IDS),
            "ledger_count": V8_LEDGER_COUNT,
        },
        "producer_code_identity": {
            "sha256": SHA_C,
            "excluded_paths": list(V8_PRODUCER_CODE_IDENTITY_EXCLUDED_PATHS),
        },
        "protocol_bundle_sha256": SHA_C,
        "independent_audit_certificate_sha256": SHA_D,
        "sources": [source_records[kind] for kind in V8_REQUIRED_SOURCE_KINDS],
    }
    certificate_path = tmp_path.joinpath(*Path(V8_ADMISSION_CERTIFICATE_PATH).parts)
    certificate_sha = _write_bom_json(certificate_path, certificate)
    return _AdmissionFixture(tmp_path, certificate_sha, tuple(artifact_paths))


def _verify(fixture: _AdmissionFixture) -> admission.V8VerifiedAdmission:
    """Install a test-only module anchor without adding any public caller parameter."""

    test_anchor = object.__new__(V8AdmissionTrustAnchor)
    object.__setattr__(test_anchor, "certificate_path", V8_ADMISSION_CERTIFICATE_PATH)
    object.__setattr__(test_anchor, "certificate_sha256", fixture.certificate_sha256)
    with patch.object(admission, "V8_AUTHORITATIVE_ADMISSION_TRUST_ANCHOR", test_anchor):
        return verify_v8_authoritative_admission(fixture.project_root)


def _install_artifact_spy(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    original = admission._sha256_file  # noqa: SLF001

    def spy(path: Path) -> str:
        calls.append(path.resolve())
        return original(path)

    monkeypatch.setattr(admission, "_sha256_file", spy)
    return calls


def test_valid_admission_verifies_exact_seven_source_handoff(tmp_path: Path) -> None:
    """Verify exact capital, calendar, masks, DAG and 11-by-3 identities."""

    fixture = _build_admission(tmp_path)
    verified = _verify(fixture)

    assert verified.initial_capital_rub == 1_000_000.0
    assert tuple(item.kind for item in verified.sources) == V8_REQUIRED_SOURCE_KINDS
    assert verified.certificate.calendar_contract.decision_rows == 1_269
    assert verified.certificate.calendar_contract.panel_rows == 5_076
    assert verified.certificate.validity_contract.mask_columns == V8_VALIDITY_MASK_COLUMNS
    assert verified.certificate.ledger_contract.ledger_count == 33
    assert V8_STRATEGY_IDS == V8_RUNTIME_STRATEGY_IDS
    assert tuple(item.value for item in V8ScenarioId) == V8_SCENARIO_IDS
    assert verified.source(V8SourceKind.FULL_CONTEXT).rows == 5_076
    assert verified.source("moex_10m").artifact_path in fixture.artifact_paths


@pytest.mark.parametrize("decision_rows", [V8_DECISION_ROW_COUNT - 1, V8_DECISION_ROW_COUNT + 1])
def test_calendar_rejects_plus_or_minus_one_decision_row(
    tmp_path: Path,
    decision_rows: int,
) -> None:
    """Do not admit a nearly-correct calendar declaration."""

    fixture = _build_admission(tmp_path, decision_rows=decision_rows)
    with pytest.raises(V8AdmissionError, match="exact 1269x4"):
        _verify(fixture)


@pytest.mark.parametrize("rows", [V8_PANEL_ROW_COUNT - 1, V8_PANEL_ROW_COUNT + 1])
def test_panel_source_rejects_plus_or_minus_one_row(tmp_path: Path, rows: int) -> None:
    """Bind exact 5076 rows independently from the certificate headline count."""

    fixture = _build_admission(
        tmp_path,
        source_row_override=(V8SourceKind.BASE_PREDICTIONS, rows),
    )
    with pytest.raises(V8AdmissionError, match="base_predictions must declare exact 5076 rows"):
        _verify(fixture)


def test_calendar_rejects_missing_asset(tmp_path: Path) -> None:
    """Reject a three-asset panel even when the declared panel row count remains 5076."""

    fixture = _build_admission(tmp_path, assets=("BR", "MIX", "RI"))
    with pytest.raises(V8AdmissionError, match="exact BR/MIX/RI/SI"):
        _verify(fixture)


def test_full_context_rejects_missing_validity_mask(tmp_path: Path) -> None:
    """Keep model, market, contract and conjunction masks independently sealed."""

    fixture = _build_admission(
        tmp_path,
        validity_masks=V8_VALIDITY_MASK_COLUMNS[:-1],
    )
    with pytest.raises(V8AdmissionError, match="exact four-mask contract"):
        _verify(fixture)


def test_initial_capital_is_exactly_one_million_rub(tmp_path: Path) -> None:
    """Reject a certificate-level capital knob before artifact access."""

    fixture = _build_admission(tmp_path, initial_capital=999_999.0)
    with pytest.raises(V8AdmissionError, match="exactly 1,000,000 RUB"):
        _verify(fixture)


def test_declared_2026_is_rejected_before_any_artifact_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A last-source temporal violation cannot leak earlier artifact bytes."""

    fixture = _build_admission(
        tmp_path,
        maximum_date_override=(V8SourceKind.FULL_CONTEXT, "2026-01-02"),
    )
    artifact_hash_calls = _install_artifact_spy(monkeypatch)

    with pytest.raises(V8AdmissionError, match="protected 2026"):
        _verify(fixture)
    assert artifact_hash_calls == []


def test_target_path_is_rejected_before_any_artifact_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a target-bearing path from control metadata without touching that file."""

    fixture = _build_admission(
        tmp_path,
        artifact_path_override=(
            V8SourceKind.BASE_PREDICTIONS,
            "artifacts/target_labels.opaque",
        ),
    )
    artifact_hash_calls = _install_artifact_spy(monkeypatch)

    with pytest.raises(V8AdmissionError, match="forbidden target/PnL/assembly path"):
        _verify(fixture)
    assert artifact_hash_calls == []


@pytest.mark.parametrize("column", ["target_return", "net_pnl", "assembly_index"])
def test_forbidden_columns_are_rejected_before_artifact_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
) -> None:
    """Reject target, PnL and assembly schema names at the small-control boundary."""

    fixture = _build_admission(
        tmp_path,
        source_columns_override=(
            V8SourceKind.FULL_CONTEXT,
            (*V8_FULL_CONTEXT_COLUMNS, column),
        ),
    )
    artifact_hash_calls = _install_artifact_spy(monkeypatch)

    with pytest.raises(V8AdmissionError, match="forbidden target/PnL/assembly columns"):
        _verify(fixture)
    assert artifact_hash_calls == []


@pytest.mark.parametrize("dependency_field", ["manifest_sha256", "artifact_sha256"])
def test_dag_rejects_manifest_or_artifact_dependency_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dependency_field: str,
) -> None:
    """One matching half of a dependency seal cannot hide a mismatched other half."""

    fixture = _build_admission(
        tmp_path,
        dependency_override=(
            V8SourceKind.FULL_CONTEXT,
            V8SourceKind.REGIME_V2,
            dependency_field,
            "f" * 64,
        ),
    )
    artifact_hash_calls = _install_artifact_spy(monkeypatch)

    with pytest.raises(V8AdmissionError, match=r"manifest\+artifact seal mismatch"):
        _verify(fixture)
    assert artifact_hash_calls == []


def test_public_authoritative_api_has_no_trust_or_capital_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a code edit/release can replace the placeholder trust anchor."""

    signature = inspect.signature(verify_v8_authoritative_admission)
    assert tuple(signature.parameters) == ("project_root",)
    assert tuple(inspect.signature(V8AdmissionTrustAnchor).parameters) == ()
    anchor = V8AdmissionTrustAnchor()
    assert anchor.certificate_path == V8_ADMISSION_CERTIFICATE_PATH
    assert anchor.certificate_sha256 == V8_ADMISSION_CERTIFICATE_SHA256_PLACEHOLDER
    assert not anchor.released
    with pytest.raises(TypeError):
        V8AdmissionTrustAnchor("certificate.json", SHA_A)  # type: ignore[call-arg]

    def forbidden_control_read(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("placeholder trust anchor must block before certificate I/O")

    monkeypatch.setattr(admission, "_read_bom_json_control", forbidden_control_read)
    with pytest.raises(V8AdmissionBlockedError, match="trust anchor is a placeholder"):
        verify_v8_authoritative_admission(tmp_path)
