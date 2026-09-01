"""Correct source/derived boundary semantics for the sealed pre-2012 derivation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_pre2012_core_derived_v1 as v1
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2012_core_derived_v2.yaml"
DERIVED_SOURCE_ID: Final[str] = (
    "moex-pre2012-core3-plus-late-mix-causal-derived-2008-2011-v2"
)
PARENT_CONFIG_RELATIVE: Final[str] = "configs/moex_pre2012_core_derived_v1.yaml"
PARENT_CONFIG_SHA256: Final[str] = (
    "8f5737bc44b21a8777b55de037da7ad7cf925f652e3b715115e46d4765b1f959"
)
PARENT_MODULE_SHA256: Final[str] = (
    "d0c22df731b64c32211f1b92b771ff1d61b7892f31ff6385856ea8649f9c0e33"
)
SOURCE_ACQUISITION_PROTECTED_FROM: Final[str] = "2026-01-01"
DERIVED_MARKET_CEILING: Final[pd.Timestamp] = pd.Timestamp("2012-01-01")
D1_VERIFIER: Final[Any] = v1.verify_and_load_source
D1_DERIVED_SOURCE_ID: Final[str] = v1.DERIVED_SOURCE_ID


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"pre-2012 derived V2 {label} must be a mapping")
    return value


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> v1.DerivedProtocol:
    """Verify the boundary-only successor and its byte-sealed D1 parent."""
    path = config_path.resolve()
    config_sha = v1.derived_base.sha256_file(path)
    if v1.derived_base._sidecar_sha(path) != config_sha:
        raise ValueError("pre-2012 derived V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("pre-2012 derived V2 protocol must be a YAML object")
    parent_identity = _mapping(payload.get("parent_D1_protocol"), "parent protocol")
    failure = _mapping(payload.get("failed_D1_build"), "failed D1 build")
    correction = _mapping(payload.get("boundary_semantics_correction"), "correction")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    if (
        payload.get("protocol_id") != "moex_pre2012_core_derived_source_v2"
        or payload.get("scope") != "source_derived_no_strategy_no_outcomes"
        or payload.get("sealed_before_first_derived_price_load") is not True
        or payload.get("live_trading_allowed") is not False
        or str(parent_identity.get("path")) != PARENT_CONFIG_RELATIVE
        or str(parent_identity.get("sha256")).lower() != PARENT_CONFIG_SHA256
        or failure.get("daily_parquet_loaded") is not False
        or failure.get("output_published") is not False
        or failure.get("returns_targets_labels_signals_equity_or_pnl_observed") is not False
        or correction.get("source_acquisition_protected_from")
        != SOURCE_ACQUISITION_PROTECTED_FROM
        or correction.get("derived_market_rows_must_be_before") != "2012-01-01"
        or correction.get("panel_roll_spec_and_availability_rules_unchanged") is not True
        or output.get("immutable_no_overwrite") is not True
        or output.get("outside_git_via_data_junction") is not True
    ):
        raise ValueError("pre-2012 derived V2 protocol invariants drifted")
    parent_path = v1.derived_base._project_path(str(parent_identity["path"]))
    if v1.derived_base.sha256_file(parent_path) != PARENT_CONFIG_SHA256:
        raise ValueError("pre-2012 derived D1 config bytes drifted")
    parent = v1.load_protocol(parent_path)
    expected_dependencies = {
        "src/market_lab/futures/moex_pre2012_core_derived_v2.py",
        "src/market_lab/futures/moex_pre2012_core_derived_v1.py",
        "src/market_lab/io_utils.py",
    }
    if set(map(str, dependencies)) != expected_dependencies:
        raise ValueError("pre-2012 derived V2 dependency set drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = v1.derived_base._project_path(str(relative))
        digest = str(expected).lower()
        if v1.derived_base.sha256_file(dependency_path) != digest:
            raise ValueError(f"pre-2012 derived V2 dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    if (
        dependency_hashes["src/market_lab/futures/moex_pre2012_core_derived_v1.py"]
        != PARENT_MODULE_SHA256
    ):
        raise ValueError("pre-2012 derived D1 module identity drifted")
    return replace(
        parent,
        config_path=path,
        config_sha256=config_sha,
        output_directory=v1.derived_base._project_path(str(output["directory"])),
        dependency_hashes=dependency_hashes,
    )


def _source_manifest_contract_matches(
    protocol: v1.DerivedProtocol,
    manifest: Mapping[str, Any],
) -> bool:
    bounds = manifest.get("request_bounds")
    counts = manifest.get("counts")
    artifacts = manifest.get("artifacts")
    if not all(isinstance(item, Mapping) for item in (bounds, counts, artifacts)):
        return False
    assert isinstance(bounds, Mapping)
    assert isinstance(counts, Mapping)
    assert isinstance(artifacts, Mapping)
    return bool(
        manifest.get("source_id") == v1.SOURCE_ID
        and bounds.get("from") == "2008-01-01"
        and bounds.get("till") == "2011-12-31"
        and bounds.get("protected_from") == SOURCE_ACQUISITION_PROTECTED_FROM
        and bounds.get("all_daily_requests_end_before_2012") is True
        and int(counts.get("contracts", -1)) == protocol.source_contracts
        and int(counts.get("daily_rows", -1)) == protocol.source_daily_rows
        and int(counts.get("inert_daily_rows", -1)) == 2
        and str(artifacts["daily"]["sha256"]).lower()
        == protocol.source_daily_sha256
        and str(artifacts["raw_archive"]["sha256"]).lower()
        == protocol.source_raw_sha256
    )


def verify_and_load_source(
    protocol: v1.DerivedProtocol,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Use source acquisition protection and enforce the derived ceiling separately."""
    manifest_path = protocol.source_directory / "manifest.json"
    content = manifest_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != protocol.source_manifest_sha256:
        raise ValueError("pre-2012 V2 source manifest SHA-256 mismatch")
    stated = (
        protocol.source_directory.joinpath("manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        .lower()
    )
    if stated != protocol.source_manifest_sha256:
        raise ValueError("pre-2012 V2 source manifest sidecar mismatch")
    manifest = json.loads(content.decode("utf-8-sig"))
    core = dict(manifest)
    identity = str(core.pop("manifest_payload_sha256", ""))
    if hashlib.sha256(v1.derived_base._canonical_json(core)).hexdigest() != identity:
        raise ValueError("pre-2012 V2 source manifest payload identity mismatch")
    if not _source_manifest_contract_matches(protocol, manifest):
        raise ValueError("pre-2012 V2 source manifest contract drifted")
    artifacts = _mapping(manifest.get("artifacts"), "source artifacts")
    verified = {
        name: v1._verified_artifact(protocol.source_directory, record)
        for name, record in artifacts.items()
    }
    daily = pd.read_parquet(verified["daily"])
    contracts = pd.read_parquet(verified["contracts"])
    if len(daily) != protocol.source_daily_rows or len(contracts) != protocol.source_contracts:
        raise ValueError("pre-2012 V2 loaded source row count mismatch")
    if (
        daily["trade_date"].min() != pd.Timestamp("2008-01-09")
        or daily["trade_date"].max() != pd.Timestamp("2011-12-16")
        or daily["trade_date"].ge(DERIVED_MARKET_CEILING).any()
        or daily.duplicated(["trade_date", "canonical_contract_id", "board_id"]).any()
    ):
        raise ValueError("pre-2012 V2 derived market ceiling or identity gate failed")
    inert = daily.loc[
        ~daily["reported_trade_activity"]
        & ~daily["ohlc_complete"]
        & ~daily["has_settlement"]
    ]
    identities = tuple(
        sorted(
            (str(row.secid), row.trade_date.date().isoformat())
            for row in inert[["secid", "trade_date"]].itertuples(index=False)
        )
    )
    if identities != tuple(sorted(v1.EXPECTED_SOURCE_INERT_IDENTITIES)):
        raise ValueError("pre-2012 V2 source inert identities changed")
    return manifest, daily, contracts


@contextmanager
def _v2_context() -> Iterator[None]:
    original_verifier = v1.verify_and_load_source
    original_source_id = v1.DERIVED_SOURCE_ID
    if original_verifier is not D1_VERIFIER or original_source_id != D1_DERIVED_SOURCE_ID:
        raise RuntimeError("pre-2012 derived D1 globals are already patched")
    v1.verify_and_load_source = verify_and_load_source
    v1.DERIVED_SOURCE_ID = DERIVED_SOURCE_ID
    try:
        yield
    finally:
        v1.verify_and_load_source = original_verifier
        v1.DERIVED_SOURCE_ID = original_source_id


def build_derived_tables(protocol: v1.DerivedProtocol) -> v1.derived_base.DerivedTables:
    """Run D1 economics-free transformation under corrected boundary semantics."""
    with _v2_context():
        return v1.build_derived_tables(protocol)


def _rewrite_manifest(staging: Path) -> None:
    manifest_path = staging / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest.pop("manifest_payload_sha256", None)
    manifest["schema_version"] = 2
    manifest["lineage"] = {
        "D1_config_sha256": PARENT_CONFIG_SHA256,
        "D1_output_published": False,
        "D1_daily_parquet_loaded": False,
        "D1_strategy_outcomes_observed": False,
    }
    manifest["boundary_semantics_correction"] = {
        "source_acquisition_protected_from": SOURCE_ACQUISITION_PROTECTED_FROM,
        "derived_market_rows_must_be_before": "2012-01-01",
        "source_request_till": "2011-12-31",
        "panel_roll_spec_and_availability_rules_unchanged": True,
    }
    identity = hashlib.sha256(v1.derived_base._canonical_json(manifest)).hexdigest()
    write_json(
        manifest_path,
        {**manifest, "manifest_payload_sha256": identity},
    )
    atomic_write_text(
        staging / "manifest.sha256",
        f"{v1.derived_base.sha256_file(manifest_path)}  manifest.json\n",
    )


def persist_derived(
    protocol: v1.DerivedProtocol,
    tables: v1.derived_base.DerivedTables,
) -> Path:
    """Publish a separate atomic V2 bundle with explicit D1 failure lineage."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"pre-2012 derived V2 output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f".{final.name}.v2.", dir=final.parent))
    staging = workspace / "bundle"
    temporary_protocol = replace(protocol, output_directory=staging)
    try:
        with _v2_context():
            v1.persist_derived(temporary_protocol, tables)
        _rewrite_manifest(staging)
        staging.replace(final)
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    shutil.rmtree(workspace, ignore_errors=True)
    return final


def audit_bundle(protocol: v1.DerivedProtocol) -> v1.DerivedAudit:
    """Reuse the full D1 deterministic artifact audit under corrected semantics."""
    with _v2_context():
        return v1.audit_bundle(protocol)


def build_and_persist(config_path: Path = DEFAULT_CONFIG) -> Path:
    protocol = load_protocol(config_path)
    output = persist_derived(protocol, build_derived_tables(protocol))
    audit = audit_bundle(protocol)
    if not all(audit.checks.values()):
        failed = sorted(name for name, passed in audit.checks.items() if not passed)
        raise ValueError(f"pre-2012 derived V2 audit failed: {failed}")
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
