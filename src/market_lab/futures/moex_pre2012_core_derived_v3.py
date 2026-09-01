"""Normalize deterministic persistence types for the sealed pre-2012 derivation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_pre2012_core_derived_v1 as v1
from market_lab.futures import moex_pre2012_core_derived_v2 as v2
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2012_core_derived_v3.yaml"
DERIVED_SOURCE_ID: Final[str] = (
    "moex-pre2012-core3-plus-late-mix-causal-derived-2008-2011-v3"
)
PARENT_CONFIG_RELATIVE: Final[str] = "configs/moex_pre2012_core_derived_v2.yaml"
PARENT_CONFIG_SHA256: Final[str] = (
    "f928e58b0bacce4d80c7d77fab7b399b3aba4650034bd3d518f45ef2f5c92c83"
)
PARENT_MODULE_SHA256: Final[str] = (
    "2e01c3fcbfb2c9ff7043bc68f4f2345918600c6f9d0d17866fae777fc34983fe"
)
FAILED_D2_MANIFEST_SHA256: Final[str] = (
    "da7c922ddd429fcd6b5c3d1070329574c742207a56617a7592020169dde88405"
)
BOOL_NORMALIZATION_COLUMNS: Final[tuple[str, ...]] = (
    "curve_valid",
    "participant_snapshot_complete",
)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"pre-2012 derived V3 {label} must be a mapping")
    return value


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> v1.DerivedProtocol:
    """Verify the persistence-only successor and its byte-sealed D2 parent."""
    path = config_path.resolve()
    config_sha = v1.derived_base.sha256_file(path)
    if v1.derived_base._sidecar_sha(path) != config_sha:
        raise ValueError("pre-2012 derived V3 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("pre-2012 derived V3 protocol must be a YAML object")
    parent_identity = _mapping(payload.get("parent_D2_protocol"), "parent protocol")
    failed = _mapping(payload.get("failed_D2_audit"), "failed D2 audit")
    correction = _mapping(payload.get("deterministic_persistence_correction"), "correction")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    if (
        payload.get("protocol_id") != "moex_pre2012_core_derived_source_v3"
        or payload.get("scope") != "source_derived_no_strategy_no_outcomes"
        or payload.get("sealed_before_D3_build") is not True
        or payload.get("live_trading_allowed") is not False
        or str(parent_identity.get("path")) != PARENT_CONFIG_RELATIVE
        or str(parent_identity.get("sha256")).lower() != PARENT_CONFIG_SHA256
        or str(failed.get("manifest_sha256")).lower() != FAILED_D2_MANIFEST_SHA256
        or failed.get("output_published_but_accepted") is not False
        or failed.get("market_value_mismatch_count") != 0
        or tuple(correction.get("boolean_columns", ())) != BOOL_NORMALIZATION_COLUMNS
        or correction.get("boolean_values_changed") is not False
        or correction.get("month_code_values_changed") is not False
        or correction.get("panel_roll_spec_availability_rules_changed") is not False
        or output.get("immutable_no_overwrite") is not True
        or output.get("outside_git_via_data_junction") is not True
    ):
        raise ValueError("pre-2012 derived V3 protocol invariants drifted")
    parent_path = v1.derived_base._project_path(str(parent_identity["path"]))
    if v1.derived_base.sha256_file(parent_path) != PARENT_CONFIG_SHA256:
        raise ValueError("pre-2012 derived D2 config bytes drifted")
    parent = v2.load_protocol(parent_path)
    expected_dependencies = {
        "src/market_lab/futures/moex_pre2012_core_derived_v3.py",
        "src/market_lab/futures/moex_pre2012_core_derived_v2.py",
        "src/market_lab/io_utils.py",
    }
    if set(map(str, dependencies)) != expected_dependencies:
        raise ValueError("pre-2012 derived V3 dependency set drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = v1.derived_base._project_path(str(relative))
        digest = str(expected).lower()
        if v1.derived_base.sha256_file(dependency_path) != digest:
            raise ValueError(f"pre-2012 derived V3 dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    if (
        dependency_hashes["src/market_lab/futures/moex_pre2012_core_derived_v2.py"]
        != PARENT_MODULE_SHA256
    ):
        raise ValueError("pre-2012 derived D2 module identity drifted")
    return replace(
        parent,
        config_path=path,
        config_sha256=config_sha,
        output_directory=v1.derived_base._project_path(str(output["directory"])),
        dependency_hashes=dependency_hashes,
    )


def normalize_persistence_types(
    tables: v1.derived_base.DerivedTables,
) -> v1.derived_base.DerivedTables:
    """Canonicalize two boolean dtypes and JSON-native month-code containers only."""
    panel = tables.panel.copy()
    for column in BOOL_NORMALIZATION_COLUMNS:
        if panel[column].isna().any():
            raise ValueError(f"pre-2012 V3 boolean normalization found missing {column}")
        before = panel[column].astype(str)
        panel[column] = panel[column].astype(bool)
        if not before.eq(panel[column].astype(str)).all():
            raise ValueError(f"pre-2012 V3 boolean normalization changed {column}")
    audit = copy.deepcopy(tables.audit)
    admission = audit.get("contract_admission")
    if not isinstance(admission, dict):
        raise ValueError("pre-2012 V3 audit lacks contract admission")
    codes = admission.get("admitted_month_codes")
    if not isinstance(codes, dict):
        raise ValueError("pre-2012 V3 audit lacks admitted month codes")
    admission["admitted_month_codes"] = {
        str(asset): [str(code) for code in values]
        for asset, values in codes.items()
    }
    return v1.derived_base.DerivedTables(
        panel=panel,
        active_contract_map=tables.active_contract_map,
        contract_observations=tables.contract_observations,
        spec_proxy=tables.spec_proxy,
        audit=audit,
    )


def build_derived_tables(protocol: v1.DerivedProtocol) -> v1.derived_base.DerivedTables:
    """Build D2-identical tables and canonicalize persistence representation."""
    return normalize_persistence_types(v2.build_derived_tables(protocol))


def persist_derived(
    protocol: v1.DerivedProtocol,
    tables: v1.derived_base.DerivedTables,
) -> Path:
    """Publish one separate immutable V3 bundle with deterministic lineage."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"pre-2012 derived V3 output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        frames = {
            "panel": tables.panel,
            "active_contract_map": tables.active_contract_map,
            "contract_observations": tables.contract_observations,
            "spec_proxy": tables.spec_proxy,
        }
        v1.derived_base._assert_source_only_schema(frames)
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            v1.derived_base._atomic_parquet(path, frame)
            artifacts[name] = v1.derived_base._artifact(path, len(frame))
            artifacts[name]["columns"] = frame.columns.tolist()
        audit_path = temporary / "audit.json"
        write_json(audit_path, tables.audit)
        artifacts["audit"] = v1.derived_base._artifact(audit_path)
        manifest_core = {
            "schema_version": 3,
            "source_id": DERIVED_SOURCE_ID,
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "parent_source": {
                "directory": protocol.source_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.source_manifest_sha256,
                "daily_sha256": protocol.source_daily_sha256,
                "raw_sha256": protocol.source_raw_sha256,
            },
            "lineage": {
                "D1_config_sha256": v2.PARENT_CONFIG_SHA256,
                "D1_output_published": False,
                "D2_config_sha256": PARENT_CONFIG_SHA256,
                "D2_manifest_sha256": FAILED_D2_MANIFEST_SHA256,
                "D2_output_accepted": False,
                "strategy_outcomes_observed_before_D3": False,
            },
            "implementation_dependencies": protocol.dependency_hashes,
            "contract_admission": tables.audit["contract_admission"],
            "variable_availability": {
                "master_assets": list(v1.CORE3),
                "MIX_first_source_session": tables.audit["MIX_first_source_session"],
                "MIX_unavailable_session_count": tables.audit[
                    "MIX_unavailable_session_count"
                ],
                "MIX_unavailable_policy": tables.audit["MIX_unavailable_policy"],
            },
            "deterministic_persistence_correction": {
                "boolean_columns": list(BOOL_NORMALIZATION_COLUMNS),
                "boolean_values_changed": False,
                "month_code_container": "JSON_native_lists",
                "month_code_values_changed": False,
                "market_value_mismatch_count_in_D2_diagnosis": 0,
            },
            "temporal_semantics": {
                "minimum_session": tables.audit["calendar_start"],
                "maximum_session": tables.audit["calendar_end"],
                "source_acquisition_protected_from": "2026-01-01",
                "derived_market_rows_must_be_before": "2012-01-01",
                "contains_prices": True,
                "contains_returns_targets_labels_signals_equity_or_pnl": False,
                "causal_forward_adjustment": True,
                "missing_values_preserved": True,
                "missing_or_listing_gap_return_bridge_created": False,
            },
            "quality_gates": {
                "successful_rolls": tables.audit["successful_rolls"],
                "action_counts": tables.audit["action_counts"],
                "unresolved_roll_count": tables.audit["unresolved_roll_count"],
                "unresolved_exit_count": tables.audit["unresolved_exit_count"],
                "panel_rows": tables.audit["panel_rows"],
                "active_contract_rows": tables.audit["active_contract_rows"],
            },
            "limitations": {
                "participant_oi_available": False,
                "historical_exchange_specs_exact": False,
                "historical_broker_fees_and_margin_exact": False,
                "MIX_available_only_late_2011": True,
                "live_admission_possible": False,
            },
            "artifacts": artifacts,
        }
        identity = hashlib.sha256(
            v1.derived_base._canonical_json(manifest_core)
        ).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": identity},
        )
        atomic_write_text(
            temporary / "manifest.sha256",
            f"{v1.derived_base.sha256_file(manifest_path)}  manifest.json\n",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_bundle(protocol: v1.DerivedProtocol) -> v1.DerivedAudit:
    """Rebuild V3 tables and compare every immutable outcome-free artifact."""
    root = protocol.output_directory.resolve()
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    identity_payload = dict(manifest)
    identity = identity_payload.pop("manifest_payload_sha256", None)
    rebuilt = build_derived_tables(protocol)
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar_path.read_text(encoding="utf-8-sig").split()[0]
        == v1.derived_base.sha256_file(manifest_path),
        "manifest_payload_sha_exact": hashlib.sha256(
            v1.derived_base._canonical_json(identity_payload)
        ).hexdigest()
        == identity,
        "source_id_exact": manifest.get("source_id") == DERIVED_SOURCE_ID,
        "protocol_sha_exact": manifest.get("protocol", {}).get("sha256")
        == protocol.config_sha256,
        "implementation_dependencies_exact": manifest.get(
            "implementation_dependencies"
        )
        == protocol.dependency_hashes,
        "parent_source_exact": manifest.get("parent_source", {}).get(
            "manifest_sha256"
        )
        == protocol.source_manifest_sha256,
        "audit_exact": json.loads(
            (root / manifest["artifacts"]["audit"]["path"]).read_text(
                encoding="utf-8-sig"
            )
        )
        == rebuilt.audit,
    }
    frames = {
        "panel": rebuilt.panel,
        "active_contract_map": rebuilt.active_contract_map,
        "contract_observations": rebuilt.contract_observations,
        "spec_proxy": rebuilt.spec_proxy,
    }
    for name, expected in frames.items():
        record = manifest["artifacts"][name]
        path = root / str(record["path"])
        checks[f"{name}_bytes"] = path.stat().st_size == int(record["bytes"])
        checks[f"{name}_sha256"] = v1.derived_base.sha256_file(path) == record["sha256"]
        stored = pd.read_parquet(path)
        checks[f"{name}_rows"] = len(stored) == int(record["rows"])
        checks[f"{name}_columns"] = stored.columns.tolist() == record["columns"]
        try:
            pd.testing.assert_frame_equal(
                v1._normalized(stored),
                v1._normalized(expected),
                check_dtype=False,
            )
        except AssertionError:
            checks[f"{name}_rebuild_exact"] = False
        else:
            checks[f"{name}_rebuild_exact"] = True
    return v1.DerivedAudit(
        checks=checks,
        counts={
            "master_sessions": int(rebuilt.audit["master_session_count"]),
            "panel_rows": len(rebuilt.panel),
            "active_contract_rows": len(rebuilt.active_contract_map),
            "contract_observation_rows": len(rebuilt.contract_observations),
            "spec_proxy_rows": len(rebuilt.spec_proxy),
        },
    )


def build_and_persist(config_path: Path = DEFAULT_CONFIG) -> Path:
    protocol = load_protocol(config_path)
    output = persist_derived(protocol, build_derived_tables(protocol))
    audit = audit_bundle(protocol)
    if not all(audit.checks.values()):
        failed = sorted(name for name, passed in audit.checks.items() if not passed)
        raise ValueError(f"pre-2012 derived V3 audit failed: {failed}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol(arguments.config)
    if arguments.audit_only:
        audit = audit_bundle(protocol)
        print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
        return 0
    print(build_and_persist(arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
