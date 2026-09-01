"""Build an immutable causal panel/spec bundle from the sealed MOEX pre-2018 source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures.panel import build_causal_development_panel
from market_lab.futures.roll import RollPlannerConfig
from market_lab.futures.spec_proxy import build_causal_spec_proxy
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2018_core4_derived.yaml"
PROTECTED_FROM: Final[date] = date(2018, 1, 1)
ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
SOURCE_TO_LOGICAL: Final[dict[str, str]] = {"Si": "SI", "RTS": "RI", "BR": "BR", "MIX": "MIX"}
EMPTY_PARTICIPANT_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "asset_code",
    "is_physical",
    "open_position_long",
    "open_position_short",
)
FORBIDDEN_OUTCOME_COLUMN_TOKENS: Final[tuple[str, ...]] = (
    "return",
    "target",
    "label",
    "prediction",
    "signal",
    "strategy",
    "pnl",
    "equity",
)


@dataclass(frozen=True, slots=True)
class DerivedProtocol:
    """Verified source-derived protocol with byte-pinned transformation dependencies."""

    config_path: Path
    config_sha256: str
    source_directory: Path
    source_manifest_sha256: str
    source_daily_sha256: str
    source_raw_replay_sha256: str
    source_daily_rows: int
    source_contracts: int
    output_directory: Path
    roll_config: RollPlannerConfig
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class DerivedTables:
    """Causal market/source tables; no returns, targets, labels, or PnL."""

    panel: pd.DataFrame
    active_contract_map: pd.DataFrame
    contract_observations: pd.DataFrame
    spec_proxy: pd.DataFrame
    audit: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _project_path(relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("path must be project-relative")
    root = PROJECT_ROOT.resolve()
    # Keep the lexical path for the repository's intentional data/runs/models
    # junctions.  Resolving first would make a valid ``data/...`` path appear to
    # escape into the sibling external-storage directory.
    path = Path(os.path.abspath(root / relative))
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes project root: {relative}") from error
    first_component = path.relative_to(root).parts[0]
    if first_component not in {"data", "runs", "models"}:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"path resolves outside project root: {relative}") from error
    return path


def _sidecar_sha(path: Path) -> str:
    parts = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").strip().split()
    if len(parts) != 2 or parts[1] != path.name:
        raise ValueError(f"invalid SHA sidecar for {path}")
    return parts[0].lower()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> DerivedProtocol:
    """Verify config and every imported transformation module before source prices load."""
    path = config_path.resolve()
    actual_sha = sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("derived protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("derived protocol must be a YAML object")
    if payload.get("protocol_id") != "moex_pre2018_core4_derived_source_v1":
        raise ValueError("unexpected derived protocol id")
    if payload.get("scope") != "source_derived_no_strategy_no_outcomes":
        raise ValueError("derived protocol is not source-only")
    source = payload.get("source")
    output = payload.get("output")
    roll = payload.get("causal_roll")
    dependencies = payload.get("implementation_dependencies")
    if not all(isinstance(item, Mapping) for item in (source, output, roll, dependencies)):
        raise ValueError("derived protocol has an invalid section")
    assert isinstance(source, Mapping)
    assert isinstance(output, Mapping)
    assert isinstance(roll, Mapping)
    assert isinstance(dependencies, Mapping)
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = _project_path(str(relative))
        digest = str(expected).lower()
        if sha256_file(dependency_path) != digest:
            raise ValueError(f"derived dependency SHA drift: {relative}")
        dependency_hashes[str(relative)] = digest
    settings = RollPlannerConfig(
        confirmation_days=int(roll["confirmation_days"]),
        hard_fallback_sessions=int(roll["hard_fallback_sessions"]),
        dominance_ratio=float(roll["dominance_ratio"]),
        overlap_price_column=str(roll["overlap_price_column"]),
        execution_price_column=str(roll["execution_price_column"]),
    )
    if settings != RollPlannerConfig():
        raise ValueError("pre-2018 roll settings differ from the frozen panel defaults")
    if source.get("maximum_price_date") != "2017-12-21":
        raise ValueError("source maximum date declaration changed")
    return DerivedProtocol(
        config_path=path,
        config_sha256=actual_sha,
        source_directory=_project_path(str(source["directory"])),
        source_manifest_sha256=str(source["manifest_sha256"]).lower(),
        source_daily_sha256=str(source["daily_sha256"]).lower(),
        source_raw_replay_sha256=str(source["raw_replay_sha256"]).lower(),
        source_daily_rows=int(source["daily_rows"]),
        source_contracts=int(source["contracts"]),
        output_directory=_project_path(str(output["directory"])),
        roll_config=settings,
        dependency_hashes=dependency_hashes,
    )


def _load_manifest(protocol: DerivedProtocol) -> dict[str, Any]:
    manifest_path = protocol.source_directory / "manifest.json"
    content = manifest_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != protocol.source_manifest_sha256:
        raise ValueError("source manifest SHA-256 mismatch")
    stated = (
        protocol.source_directory.joinpath("manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        .lower()
    )
    if stated != protocol.source_manifest_sha256:
        raise ValueError("source manifest sidecar mismatch")
    manifest = json.loads(content.decode("utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("source manifest is not an object")
    core = dict(manifest)
    identity = str(core.pop("manifest_payload_sha256", ""))
    if hashlib.sha256(_canonical_json(core)).hexdigest() != identity:
        raise ValueError("source manifest payload identity mismatch")
    if manifest.get("source_id") != "official-moex-core4-daily-current-vintage-2012-2017-v1":
        raise ValueError("unexpected source bundle id")
    bounds = manifest.get("request_bounds", {})
    if bounds.get("till") != "2017-12-31" or bounds.get("pre2018_ceiling") != "2018-01-01":
        raise ValueError("source request bounds changed")
    return manifest


def _verified_artifact(protocol: DerivedProtocol, record: Mapping[str, Any]) -> Path:
    path = (protocol.source_directory / str(record["path"])).resolve()
    try:
        path.relative_to(protocol.source_directory.resolve())
    except ValueError as error:
        raise ValueError("source artifact escapes bundle directory") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(record["bytes"]) or sha256_file(path) != str(
        record["sha256"]
    ).lower():
        raise ValueError(f"source artifact identity mismatch: {path.name}")
    return path


def verify_and_load_source(
    protocol: DerivedProtocol,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Verify all source artifact bytes, then load only daily/contracts for transformation."""
    manifest = _load_manifest(protocol)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("source manifest lacks artifacts")
    if (
        str(artifacts["daily"]["sha256"]).lower() != protocol.source_daily_sha256
        or str(artifacts["raw_archive"]["sha256"]).lower()
        != protocol.source_raw_replay_sha256
    ):
        raise ValueError("source config and manifest artifact identities disagree")
    verified = {name: _verified_artifact(protocol, record) for name, record in artifacts.items()}
    daily = pd.read_parquet(verified["daily"])
    contracts = pd.read_parquet(verified["contracts"])
    if (
        len(daily) != int(artifacts["daily"]["rows"])
        or len(daily) != protocol.source_daily_rows
        or len(contracts) != protocol.source_contracts
    ):
        raise ValueError("source row count mismatch")
    if daily["trade_date"].max() != pd.Timestamp("2017-12-21"):
        raise ValueError("source daily maximum date mismatch")
    if daily["trade_date"].dt.date.ge(PROTECTED_FROM).any():
        raise ValueError("source daily reaches 2018 or later")
    if daily.duplicated(["trade_date", "canonical_contract_id", "board_id"]).any():
        raise ValueError("source daily contains duplicate contract observations")
    return manifest, daily, contracts


def _observations_by_asset(daily: pd.DataFrame, contracts: pd.DataFrame) -> dict[str, pd.DataFrame]:
    metadata = contracts.loc[
        :, ["canonical_contract_id", "expiration_date", "logical_symbol"]
    ].copy()
    if metadata["canonical_contract_id"].duplicated().any():
        raise ValueError("contract metadata contains duplicate canonical ids")
    observations = daily.merge(
        metadata,
        on="canonical_contract_id",
        how="left",
        validate="many_to_one",
    )
    if observations[["expiration_date", "logical_symbol"]].isna().any().any():
        raise ValueError("daily source has an unresolved contract identity")
    if not all(
        observations.loc[observations["asset_code"] == source_code, "logical_symbol"]
        .astype(str)
        .eq(logical)
        .all()
        for source_code, logical in SOURCE_TO_LOGICAL.items()
    ):
        raise ValueError("source asset code disagrees with contract logical symbol")
    output = {
        asset: observations.loc[observations["logical_symbol"] == asset].reset_index(drop=True)
        for asset in ASSETS
    }
    if any(frame.empty for frame in output.values()):
        raise ValueError("one core asset has no source observations")
    return output


def _assert_source_only_schema(frames: Mapping[str, pd.DataFrame]) -> None:
    offenders = {
        name: [
            str(column)
            for column in frame.columns
            if any(token in str(column).lower() for token in FORBIDDEN_OUTCOME_COLUMN_TOKENS)
        ]
        for name, frame in frames.items()
    }
    offenders = {name: columns for name, columns in offenders.items() if columns}
    if offenders:
        raise ValueError(f"derived source bundle contains outcome columns: {offenders}")


def build_derived_tables(protocol: DerivedProtocol) -> DerivedTables:
    """Create frozen causal rolls, active prices, and lag-1 specs without strategy outcomes."""
    manifest, daily, contracts = verify_and_load_source(protocol)
    observations = _observations_by_asset(daily, contracts)
    empty_participants = {
        asset: pd.DataFrame(columns=EMPTY_PARTICIPANT_COLUMNS) for asset in ASSETS
    }
    result = build_causal_development_panel(
        observations,
        empty_participants,
        roll_config=protocol.roll_config,
        protected_from=PROTECTED_FROM,
    )
    calendar = pd.DatetimeIndex(
        result.panel["trade_date"].drop_duplicates().sort_values(ignore_index=True)
    )
    spec_input = result.contract_observations.rename(
        columns={
            "trade_date": "session_date",
            "canonical_contract_id": "contract_id",
            "logical_asset": "asset_symbol",
        }
    )
    spec_proxy = build_causal_spec_proxy(spec_input, calendar)
    if spec_proxy["session_date"].dt.date.ge(PROTECTED_FROM).any():
        raise ValueError("derived spec proxy reaches 2018 or later")
    active = result.active_contract_map
    _assert_source_only_schema(
        {
            "panel": result.panel,
            "active_contract_map": active,
            "contract_observations": result.contract_observations,
            "spec_proxy": spec_proxy,
        }
    )
    audit = {
        **result.audit,
        "source_manifest_sha256": protocol.source_manifest_sha256,
        "source_daily_sha256": manifest["artifacts"]["daily"]["sha256"],
        "source_daily_rows": len(daily),
        "source_contracts": len(contracts),
        "roll_config": asdict(protocol.roll_config),
        "participant_oi_available": False,
        "participant_oi_missing_preserved": True,
        "spec_proxy_rows": len(spec_proxy),
        "spec_sizing_usable_rows": int(spec_proxy["sizing_usable"].sum()),
        "spec_sizing_unusable_rows": int((~spec_proxy["sizing_usable"]).sum()),
        "active_feature_valid_rows": int(active["feature_input_valid"].sum()),
        "active_feature_invalid_rows": int((~active["feature_input_valid"]).sum()),
        "active_execution_open_available_rows": int(active["execution_open_available"].sum()),
        "active_execution_open_missing_rows": int((~active["execution_open_available"]).sum()),
        "contains_prices": True,
        "contains_returns_targets_labels_or_pnl": False,
        "historical_exchange_exact": False,
        "broker_exact": False,
    }
    return DerivedTables(
        panel=result.panel,
        active_contract_map=active,
        contract_observations=result.contract_observations,
        spec_proxy=spec_proxy,
        audit=audit,
    )


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        record["rows"] = rows
    return record


def persist_derived(protocol: DerivedProtocol, tables: DerivedTables) -> Path:
    """Publish one immutable source-derived bundle outside Git."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"derived output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        frames = {
            "panel": tables.panel,
            "active_contract_map": tables.active_contract_map,
            "contract_observations": tables.contract_observations,
            "spec_proxy": tables.spec_proxy,
        }
        _assert_source_only_schema(frames)
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            _atomic_parquet(path, frame)
            artifacts[name] = _artifact(path, len(frame))
            artifacts[name]["columns"] = frame.columns.tolist()
        audit_path = temporary / "audit.json"
        write_json(audit_path, tables.audit)
        artifacts["audit"] = _artifact(audit_path)
        manifest_core = {
            "schema_version": 1,
            "source_id": "moex-pre2018-core4-causal-derived-2012-2017-v1",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "parent_source": {
                "directory": protocol.source_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.source_manifest_sha256,
            },
            "implementation_dependencies": protocol.dependency_hashes,
            "temporal_semantics": {
                "minimum_session": tables.audit["calendar_start"],
                "maximum_session": tables.audit["calendar_end"],
                "protected_from": PROTECTED_FROM.isoformat(),
                "contains_prices": True,
                "contains_returns_targets_labels_or_pnl": False,
                "causal_forward_adjustment": True,
                "missing_values_preserved": True,
            },
            "limitations": {
                "participant_oi_available": False,
                "historical_exchange_specs_exact": False,
                "historical_broker_fees_and_margin_exact": False,
                "live_admission_possible": False,
            },
            "artifacts": artifacts,
        }
        identity = hashlib.sha256(_canonical_json(manifest_core)).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, {**manifest_core, "manifest_payload_sha256": identity})
        manifest_sha = sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def build_and_persist(config_path: Path = DEFAULT_CONFIG) -> Path:
    protocol = load_protocol(config_path)
    return persist_derived(protocol, build_derived_tables(protocol))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    arguments = parser.parse_args(argv)
    print(build_and_persist(arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
