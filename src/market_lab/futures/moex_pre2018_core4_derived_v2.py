"""Build the sealed cycle-filtered causal MOEX 2012-2017 source bundle."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_pre2018_core4_derived as v1
from market_lab.futures.panel import build_causal_development_panel
from market_lab.futures.roll import RollPlannerConfig
from market_lab.futures.spec_proxy import build_causal_spec_proxy
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2018_core4_derived_v2.yaml"
CONTRACT_ROOTS: Final[dict[str, str]] = {
    "SI": "Si",
    "RI": "RI",
    "BR": "BR",
    "MIX": "MX",
}
ADMITTED_MONTH_CODES: Final[dict[str, tuple[str, ...]]] = {
    "SI": ("H", "M", "U", "Z"),
    "RI": ("H", "M", "U", "Z"),
    "BR": ("F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"),
    "MIX": ("H", "M", "U", "Z"),
}
EXPECTED_ADMITTED_CONTRACTS: Final[dict[str, int]] = {
    "SI": 24,
    "RI": 24,
    "BR": 71,
    "MIX": 24,
}
EXPECTED_ROLLS: Final[dict[str, int]] = {
    "SI": 23,
    "RI": 23,
    "BR": 70,
    "MIX": 23,
}
EXPECTED_ADMITTED_DAILY_ROWS: Final[int] = 29_026


@dataclass(frozen=True, slots=True)
class DerivedV2Protocol:
    """Byte-verified D2 protocol and its structural contract-cycle rule."""

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
    previous_attempt_manifest_sha256: str


def _load_mapping(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = payload.get(name)
    if not isinstance(section, Mapping):
        raise ValueError(f"derived V2 protocol has invalid {name}")
    return section


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> DerivedV2Protocol:
    """Verify the D2 seal and all implementation bytes before source prices load."""
    path = config_path.resolve()
    actual_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("derived V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("derived V2 protocol must be a YAML object")
    if payload.get("protocol_id") != "moex_pre2018_core4_derived_source_v2":
        raise ValueError("unexpected derived V2 protocol id")
    if payload.get("scope") != "source_derived_no_strategy_no_outcomes":
        raise ValueError("derived V2 protocol is not source-only")
    source = _load_mapping(payload, "source")
    output = _load_mapping(payload, "output")
    roll = _load_mapping(payload, "causal_roll")
    admission = _load_mapping(payload, "contract_admission")
    dependencies = _load_mapping(payload, "implementation_dependencies")
    previous = _load_mapping(payload, "previous_derived_attempt")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = v1._project_path(str(relative))
        digest = str(expected).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"derived V2 dependency SHA drift: {relative}")
        dependency_hashes[str(relative)] = digest
    settings = RollPlannerConfig(
        confirmation_days=int(roll["confirmation_days"]),
        hard_fallback_sessions=int(roll["hard_fallback_sessions"]),
        dominance_ratio=float(roll["dominance_ratio"]),
        overlap_price_column=str(roll["overlap_price_column"]),
        execution_price_column=str(roll["execution_price_column"]),
    )
    if settings != RollPlannerConfig():
        raise ValueError("pre-2018 D2 roll settings differ from frozen defaults")
    configured_codes = {
        str(asset): tuple(str(code) for code in codes)
        for asset, codes in _load_mapping(admission, "admitted_month_codes").items()
    }
    configured_contracts = {
        str(asset): int(count)
        for asset, count in _load_mapping(admission, "expected_contracts").items()
    }
    configured_rolls = {
        str(asset): int(count)
        for asset, count in _load_mapping(admission, "required_successful_rolls").items()
    }
    if (
        configured_codes != ADMITTED_MONTH_CODES
        or configured_contracts != EXPECTED_ADMITTED_CONTRACTS
        or configured_rolls != EXPECTED_ROLLS
        or int(admission["expected_admitted_daily_rows"]) != EXPECTED_ADMITTED_DAILY_ROWS
    ):
        raise ValueError("D2 structural contract-cycle declaration changed")
    if source.get("maximum_price_date") != "2017-12-21":
        raise ValueError("source maximum date declaration changed")
    if previous.get("verdict") != "OPERATIONALLY_UNUSABLE_SOURCE_DERIVATION":
        raise ValueError("D1 source-only diagnostic verdict changed")
    return DerivedV2Protocol(
        config_path=path,
        config_sha256=actual_sha,
        source_directory=v1._project_path(str(source["directory"])),
        source_manifest_sha256=str(source["manifest_sha256"]).lower(),
        source_daily_sha256=str(source["daily_sha256"]).lower(),
        source_raw_replay_sha256=str(source["raw_replay_sha256"]).lower(),
        source_daily_rows=int(source["daily_rows"]),
        source_contracts=int(source["contracts"]),
        output_directory=v1._project_path(str(output["directory"])),
        roll_config=settings,
        dependency_hashes=dependency_hashes,
        previous_attempt_manifest_sha256=str(previous["manifest_sha256"]).lower(),
    )


def _contract_month_code(row: Mapping[str, Any]) -> str:
    logical = str(row["logical_symbol"])
    root = CONTRACT_ROOTS.get(logical)
    secid = str(row["secid"])
    if root is None or not secid.startswith(root):
        raise ValueError(f"contract root disagrees with logical asset: {logical}/{secid}")
    suffix = secid[len(root) :].split("_", maxsplit=1)[0]
    if len(suffix) != 2 or not suffix[1].isdigit():
        raise ValueError(f"unexpected dated futures SECID: {secid}")
    return suffix[0]


def admit_structural_contract_cycles(
    daily: pd.DataFrame,
    contracts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Keep official quarterly core cycles and the official monthly Brent cycle."""
    selected = contracts.copy()
    selected["contract_month_code"] = [
        _contract_month_code(row) for row in selected.to_dict("records")
    ]
    selected["cycle_admitted"] = [
        month in ADMITTED_MONTH_CODES[str(asset)]
        for asset, month in selected[["logical_symbol", "contract_month_code"]].itertuples(
            index=False,
            name=None,
        )
    ]
    admitted = selected.loc[selected["cycle_admitted"]].copy()
    excluded = selected.loc[~selected["cycle_admitted"]].copy()
    counts = admitted.groupby("logical_symbol").size().astype(int).to_dict()
    if counts != EXPECTED_ADMITTED_CONTRACTS:
        raise ValueError(f"admitted structural contract counts changed: {counts}")
    if not excluded["logical_symbol"].eq("SI").all() or len(excluded) != 12:
        raise ValueError("D2 may exclude only the 12 SI serial contracts")
    admitted_ids = set(admitted["canonical_contract_id"].astype(str))
    admitted_daily = daily.loc[
        daily["canonical_contract_id"].astype(str).isin(admitted_ids)
    ].copy()
    if len(admitted_daily) != EXPECTED_ADMITTED_DAILY_ROWS:
        raise ValueError("admitted D2 daily row count changed")
    audit = {
        "rule": "official_cycle_by_logical_asset_before_any_strategy_outcome",
        "admitted_month_codes": ADMITTED_MONTH_CODES,
        "admitted_contracts": counts,
        "admitted_daily_rows": len(admitted_daily),
        "excluded_contracts": len(excluded),
        "excluded_contract_ids": sorted(excluded["canonical_contract_id"].astype(str)),
        "excluded_logical_assets": sorted(excluded["logical_symbol"].unique()),
        "return_or_pnl_used_for_admission": False,
    }
    return admitted_daily, admitted, audit


def _maximum_true_streak(values: pd.Series) -> int:
    maximum = current = 0
    for value in values.fillna(False).astype(bool):
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def build_derived_tables(protocol: DerivedV2Protocol) -> v1.DerivedTables:
    """Build D2 and fail closed on any unresolved roll or exit transition."""
    manifest, daily, contracts = v1.verify_and_load_source(protocol)
    admitted_daily, admitted_contracts, admission_audit = admit_structural_contract_cycles(
        daily,
        contracts,
    )
    observations = v1._observations_by_asset(admitted_daily, admitted_contracts)
    empty_participants = {
        asset: pd.DataFrame(columns=v1.EMPTY_PARTICIPANT_COLUMNS) for asset in v1.ASSETS
    }
    result = build_causal_development_panel(
        observations,
        empty_participants,
        roll_config=protocol.roll_config,
        protected_from=v1.PROTECTED_FROM,
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
    active = result.active_contract_map
    roll_counts = (
        active.loc[active["roll"]].groupby("asset_code").size().astype(int).to_dict()
    )
    action_counts = {
        asset: (
            active.loc[active["asset_code"] == asset, "action"]
            .astype(str)
            .value_counts()
            .astype(int)
            .to_dict()
        )
        for asset in v1.ASSETS
    }
    unresolved_rolls = sum(
        counts.get("carry_unfilled_roll", 0) for counts in action_counts.values()
    )
    unresolved_exits = sum(
        counts.get("carry_unfilled_exit", 0) for counts in action_counts.values()
    )
    if roll_counts != EXPECTED_ROLLS:
        raise ValueError(f"D2 successful roll counts changed: {roll_counts}")
    if unresolved_rolls or unresolved_exits:
        raise ValueError(
            f"D2 contains unresolved roll/exit: rolls={unresolved_rolls}, exits={unresolved_exits}"
        )
    frames = {
        "panel": result.panel,
        "active_contract_map": active,
        "contract_observations": result.contract_observations,
        "spec_proxy": spec_proxy,
    }
    v1._assert_source_only_schema(frames)
    audit = {
        **result.audit,
        "source_manifest_sha256": protocol.source_manifest_sha256,
        "source_daily_sha256": manifest["artifacts"]["daily"]["sha256"],
        "source_daily_rows": len(daily),
        "source_contracts": len(contracts),
        "previous_attempt_manifest_sha256": protocol.previous_attempt_manifest_sha256,
        "previous_attempt_verdict": "OPERATIONALLY_UNUSABLE_SOURCE_DERIVATION",
        "previous_attempt_returns_targets_labels_or_pnl_observed": False,
        "contract_admission": admission_audit,
        "roll_config": asdict(protocol.roll_config),
        "successful_rolls": roll_counts,
        "action_counts": action_counts,
        "unresolved_roll_count": unresolved_rolls,
        "unresolved_exit_count": unresolved_exits,
        "maximum_consecutive_feature_invalid": {
            asset: _maximum_true_streak(
                ~active.loc[active["asset_code"] == asset, "feature_input_valid"]
            )
            for asset in v1.ASSETS
        },
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
    return v1.DerivedTables(
        panel=result.panel,
        active_contract_map=active,
        contract_observations=result.contract_observations,
        spec_proxy=spec_proxy,
        audit=audit,
    )


def persist_derived(protocol: DerivedV2Protocol, tables: v1.DerivedTables) -> Path:
    """Publish one immutable cycle-filtered source bundle outside Git."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"derived V2 output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        frames = {
            "panel": tables.panel,
            "active_contract_map": tables.active_contract_map,
            "contract_observations": tables.contract_observations,
            "spec_proxy": tables.spec_proxy,
        }
        v1._assert_source_only_schema(frames)
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            v1._atomic_parquet(path, frame)
            artifacts[name] = v1._artifact(path, len(frame))
            artifacts[name]["columns"] = frame.columns.tolist()
        audit_path = temporary / "audit.json"
        write_json(audit_path, tables.audit)
        artifacts["audit"] = v1._artifact(audit_path)
        manifest_core = {
            "schema_version": 2,
            "source_id": "moex-pre2018-core4-causal-derived-2012-2017-v2",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "parent_source": {
                "directory": protocol.source_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.source_manifest_sha256,
            },
            "supersedes_source_derivation": {
                "version": 1,
                "manifest_sha256": protocol.previous_attempt_manifest_sha256,
                "verdict": "OPERATIONALLY_UNUSABLE_SOURCE_DERIVATION",
                "strategy_outcomes_observed": False,
            },
            "implementation_dependencies": protocol.dependency_hashes,
            "contract_admission": tables.audit["contract_admission"],
            "temporal_semantics": {
                "minimum_session": tables.audit["calendar_start"],
                "maximum_session": tables.audit["calendar_end"],
                "protected_from": v1.PROTECTED_FROM.isoformat(),
                "contains_prices": True,
                "contains_returns_targets_labels_or_pnl": False,
                "causal_forward_adjustment": True,
                "missing_values_preserved": True,
            },
            "quality_gates": {
                "successful_rolls": tables.audit["successful_rolls"],
                "unresolved_roll_count": tables.audit["unresolved_roll_count"],
                "unresolved_exit_count": tables.audit["unresolved_exit_count"],
            },
            "limitations": {
                "participant_oi_available": False,
                "historical_exchange_specs_exact": False,
                "historical_broker_fees_and_margin_exact": False,
                "live_admission_possible": False,
            },
            "artifacts": artifacts,
        }
        identity = hashlib.sha256(v1._canonical_json(manifest_core)).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, {**manifest_core, "manifest_payload_sha256": identity})
        manifest_sha = v1.sha256_file(manifest_path)
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
