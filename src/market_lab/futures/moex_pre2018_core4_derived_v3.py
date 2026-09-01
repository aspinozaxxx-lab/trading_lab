"""Build the sealed gap-aware causal MOEX 2012-2017 source bundle."""

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
from market_lab.futures import moex_pre2018_core4_derived_v2 as v2
from market_lab.futures.panel import build_causal_development_panel
from market_lab.futures.spec_proxy import build_causal_spec_proxy
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2018_core4_derived_v3.yaml"
EXPECTED_ROLLS: Final[dict[str, int]] = {
    "SI": 22,
    "RI": 23,
    "BR": 70,
    "MIX": 23,
}
EXPECTED_ACTION_COUNTS: Final[dict[str, dict[str, int]]] = {
    "SI": {"hold": 1448, "roll": 22, "flat": 6, "enter": 2, "flat_skip": 1},
    "RI": {"hold": 1454, "roll": 23, "enter": 1, "flat": 1},
    "BR": {"hold": 1402, "roll": 70, "flat": 5, "enter": 1, "flat_skip": 1},
    "MIX": {"hold": 1453, "roll": 23, "flat": 1, "enter": 1, "carry_missing_mark": 1},
}
SI_CONTROLLED_GAP_FLAT_DATES: Final[tuple[str, ...]] = (
    "2016-12-12",
    "2016-12-13",
    "2016-12-14",
    "2016-12-15",
    "2017-01-03",
)


@dataclass(frozen=True, slots=True)
class DerivedV3Protocol:
    """D3 seal inheriting D2 source, admission, and transformation bytes."""

    config_path: Path
    config_sha256: str
    parent: v2.DerivedV2Protocol
    output_directory: Path
    dependency_hashes: dict[str, str]
    failed_d2_config_sha256: str

    @property
    def source_directory(self) -> Path:
        return self.parent.source_directory

    @property
    def source_manifest_sha256(self) -> str:
        return self.parent.source_manifest_sha256

    @property
    def source_daily_sha256(self) -> str:
        return self.parent.source_daily_sha256

    @property
    def source_raw_replay_sha256(self) -> str:
        return self.parent.source_raw_replay_sha256

    @property
    def source_daily_rows(self) -> int:
        return self.parent.source_daily_rows

    @property
    def source_contracts(self) -> int:
        return self.parent.source_contracts

    @property
    def roll_config(self) -> Any:
        return self.parent.roll_config

    @property
    def previous_attempt_manifest_sha256(self) -> str:
        return self.parent.previous_attempt_manifest_sha256


def _mapping(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = payload.get(name)
    if not isinstance(section, Mapping):
        raise ValueError(f"derived V3 protocol has invalid {name}")
    return section


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> DerivedV3Protocol:
    """Verify D3 and its complete sealed D2 inheritance before source prices load."""
    path = config_path.resolve()
    actual_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("derived V3 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("derived V3 protocol must be a YAML object")
    if payload.get("protocol_id") != "moex_pre2018_core4_derived_source_v3":
        raise ValueError("unexpected derived V3 protocol id")
    if payload.get("scope") != "source_derived_no_strategy_no_outcomes":
        raise ValueError("derived V3 protocol is not source-only")
    parent_record = _mapping(payload, "parent_D2_protocol")
    parent_path = v1._project_path(str(parent_record["path"]))
    parent = v2.load_protocol(parent_path)
    if parent.config_sha256 != str(parent_record["sha256"]).lower():
        raise ValueError("derived V3 parent D2 protocol identity mismatch")
    failed = _mapping(payload, "failed_D2_build")
    if (
        str(failed["config_sha256"]).lower() != parent.config_sha256
        or failed.get("output_published") is not False
        or failed.get("strategy_outcomes_observed") is not False
    ):
        raise ValueError("derived V3 D2 failure record changed")
    gate = _mapping(payload, "quality_gate_correction")
    configured_rolls = {
        str(asset): int(count)
        for asset, count in _mapping(gate, "required_successful_rolls").items()
    }
    configured_actions = {
        str(asset): {str(action): int(count) for action, count in counts.items()}
        for asset, counts in _mapping(gate, "required_action_counts").items()
    }
    configured_gap_dates = tuple(str(value) for value in gate["SI_flat_session_dates"])
    if (
        configured_rolls != EXPECTED_ROLLS
        or configured_actions != EXPECTED_ACTION_COUNTS
        or configured_gap_dates != SI_CONTROLLED_GAP_FLAT_DATES
        or gate.get("maximum_unresolved_rolls") != 0
        or gate.get("maximum_unresolved_exits") != 0
    ):
        raise ValueError("D3 gap-aware quality gate changed")
    dependencies = _mapping(payload, "implementation_dependencies")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = v1._project_path(str(relative))
        digest = str(expected).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"derived V3 dependency SHA drift: {relative}")
        dependency_hashes[str(relative)] = digest
    output = _mapping(payload, "output")
    return DerivedV3Protocol(
        config_path=path,
        config_sha256=actual_sha,
        parent=parent,
        output_directory=v1._project_path(str(output["directory"])),
        dependency_hashes=dependency_hashes,
        failed_d2_config_sha256=parent.config_sha256,
    )


def _action_counts(active: pd.DataFrame) -> dict[str, dict[str, int]]:
    return {
        asset: (
            active.loc[active["asset_code"] == asset, "action"]
            .astype(str)
            .value_counts()
            .astype(int)
            .to_dict()
        )
        for asset in v1.ASSETS
    }


def _verify_controlled_si_gap(active: pd.DataFrame) -> dict[str, Any]:
    si = active.loc[active["asset_code"] == "SI"].copy()
    flat_skip = si.loc[si["action"].astype(str).eq("flat_skip")]
    if len(flat_skip) != 1:
        raise ValueError("D3 requires exactly one controlled SI flat_skip")
    row = flat_skip.iloc[0]
    if (
        pd.Timestamp(row["effective_date"]) != pd.Timestamp("2016-12-09")
        or str(row["reason"]) != "hard_fallback_without_next_contract"
        or pd.notna(row["contract_id"])
        or pd.isna(row["exit_execution_price"])
    ):
        raise ValueError("D3 controlled SI flat_skip identity changed")
    flat = si.loc[
        si["effective_date"].isin(pd.to_datetime(SI_CONTROLLED_GAP_FLAT_DATES))
    ]
    if len(flat) != len(SI_CONTROLLED_GAP_FLAT_DATES) or not flat["action"].astype(str).eq(
        "flat"
    ).all():
        raise ValueError("D3 controlled SI cash-gap sessions changed")
    enters = si.loc[si["action"].astype(str).eq("enter"), "effective_date"].dt.strftime(
        "%Y-%m-%d"
    )
    if enters.tolist() != ["2012-01-04", "2017-01-04"]:
        raise ValueError("D3 SI re-entry identity changed")
    return {
        "exit_effective_date": "2016-12-09",
        "exit_reason": "hard_fallback_without_next_contract",
        "flat_session_dates": list(SI_CONTROLLED_GAP_FLAT_DATES),
        "reentry_effective_date": "2017-01-04",
        "missing_return_bridge_created": False,
        "position_during_gap": "flat_cash",
    }


def build_derived_tables(protocol: DerivedV3Protocol) -> v1.DerivedTables:
    """Build exact D2 inputs while admitting one proven flat SI source discontinuity."""
    manifest, daily, contracts = v1.verify_and_load_source(protocol)
    admitted_daily, admitted_contracts, admission_audit = v2.admit_structural_contract_cycles(
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
    actions = _action_counts(active)
    if roll_counts != EXPECTED_ROLLS or actions != EXPECTED_ACTION_COUNTS:
        raise ValueError(
            f"D3 exact roll/action gate changed: rolls={roll_counts}, actions={actions}"
        )
    unresolved_rolls = sum(
        counts.get("carry_unfilled_roll", 0) for counts in actions.values()
    )
    unresolved_exits = sum(
        counts.get("carry_unfilled_exit", 0) for counts in actions.values()
    )
    if unresolved_rolls or unresolved_exits:
        raise ValueError("D3 contains an unresolved roll or exit")
    gap_audit = _verify_controlled_si_gap(active)
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
        "D1_manifest_sha256": protocol.previous_attempt_manifest_sha256,
        "D2_config_sha256": protocol.failed_d2_config_sha256,
        "D2_output_published": False,
        "D1_or_D2_strategy_outcomes_observed": False,
        "contract_admission": admission_audit,
        "roll_config": asdict(protocol.roll_config),
        "successful_rolls": roll_counts,
        "action_counts": actions,
        "unresolved_roll_count": unresolved_rolls,
        "unresolved_exit_count": unresolved_exits,
        "controlled_SI_source_gap": gap_audit,
        "maximum_consecutive_feature_invalid": {
            asset: v2._maximum_true_streak(
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


def persist_derived(protocol: DerivedV3Protocol, tables: v1.DerivedTables) -> Path:
    """Publish one immutable gap-aware source bundle outside Git."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"derived V3 output already exists: {final}")
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
            "schema_version": 3,
            "source_id": "moex-pre2018-core4-causal-derived-2012-2017-v3",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "parent_source": {
                "directory": protocol.source_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.source_manifest_sha256,
            },
            "lineage": {
                "D1_manifest_sha256": protocol.previous_attempt_manifest_sha256,
                "D1_verdict": "OPERATIONALLY_UNUSABLE_SOURCE_DERIVATION",
                "D2_config_sha256": protocol.failed_d2_config_sha256,
                "D2_output_published": False,
                "strategy_outcomes_observed_before_D3": False,
            },
            "implementation_dependencies": protocol.dependency_hashes,
            "contract_admission": tables.audit["contract_admission"],
            "controlled_SI_source_gap": tables.audit["controlled_SI_source_gap"],
            "temporal_semantics": {
                "minimum_session": tables.audit["calendar_start"],
                "maximum_session": tables.audit["calendar_end"],
                "protected_from": v1.PROTECTED_FROM.isoformat(),
                "contains_prices": True,
                "contains_returns_targets_labels_or_pnl": False,
                "causal_forward_adjustment": True,
                "missing_values_preserved": True,
                "missing_return_bridge_created": False,
            },
            "quality_gates": {
                "successful_rolls": tables.audit["successful_rolls"],
                "action_counts": tables.audit["action_counts"],
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
