"""Audit V27 components from anonymous or authenticated official FRED routes."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_v27_forward_component_source as base_source
from market_lab.futures import moex_v27_forward_fred_api_component_source as api_source
from market_lab.futures import v27_forward_component_readiness as base_readiness

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/v48_frontier_forward_fred_api_correction_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "b638ee931574a4b526125d80e1cef355fb223e30a724cb3aef846704ffa70c6f"
)


def _sha(path: Path) -> str:
    return base_source._sha(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent = config["parent_component_correction"]
    api = config["authenticated_FRED_component"]
    route = config["route_policy"]
    economics = config["economic_invariants"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id")
        != "v48_frontier_forward_fred_api_correction_v1"
        or config.get("live_trading_allowed") is not False
        or parent["protocol_sha256"]
        != _sha(PROJECT_ROOT / parent["protocol_path"])
        or api["protocol_sha256"] != api_source.CONFIG_SHA256
        or api["implementation_sha256"]
        != _sha(PROJECT_ROOT / api["implementation_path"])
        or route["fallback_after_authenticated_failure"] != "forbidden"
        or route["selection_by_signal_market_return_or_PnL"] != "forbidden"
        or route["credential_persistence"] != "forbidden"
        or economics["V48_mode_or_parameters_changed"] is not False
        or economics["V39_signal_window_quantiles_or_sign_changed"] is not False
        or economics["STLFSI4_series_or_release_availability_changed"] is not False
        or economics["macro_join_rule_changed"] is not False
        or economics["execution_cost_margin_capacity_or_quote_mark_changed"] is not False
        or economics["promotion_gates_changed"] is not False
    ):
        raise ValueError("V27 FRED-route readiness correction drifted")
    base_source.load_config()
    api_source.load_config()
    return config


def _audit_snapshot(snapshot: Path, protocol_id: str) -> dict[str, bool]:
    if protocol_id == "futures_v27_forward_components_v1":
        return base_source.audit(snapshot)
    if protocol_id == "futures_v27_forward_fred_api_component_v1":
        return api_source.audit(snapshot)
    raise ValueError(f"unapproved V27 component protocol: {protocol_id}")


def assess(output_root: Path = base_source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    correction = load_config()
    source_config = base_source.load_config()
    root = output_root.resolve()
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    market_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)
    macro_fred: list[dict[str, Any]] = []
    macro_cbr: list[dict[str, Any]] = []
    for snapshot in sorted(path for path in root.glob("snapshot_*") if path.is_dir()):
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            protocol_id = str(manifest["protocol_id"])
            checks = _audit_snapshot(snapshot, protocol_id)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"component replay audit failed: {', '.join(failed)}")
            component = str(manifest["component"])
            transport = str(
                manifest.get(
                    "transport",
                    "anonymous_fredgraph" if component == "macro_fred" else "direct_official",
                )
            )
            item = {
                "protocol_id": protocol_id,
                "component": component,
                "transport": transport,
                "snapshot": snapshot.name,
                "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
                "source_dates": list(manifest["source_dates"]),
                "rows": int(manifest["processed"]["rows"]),
            }
            valid.append(item)
            if component.startswith("market_"):
                if protocol_id != "futures_v27_forward_components_v1":
                    raise ValueError("market component came from FRED-only protocol")
                if len(item["source_dates"]) != 1:
                    raise ValueError("market component must expose exactly one source date")
                identity = (component, str(item["source_dates"][0]))
                label = f"{identity[0]}:{identity[1]}"
                if identity in market_by_identity:
                    duplicates[label].extend(
                        [market_by_identity[identity]["snapshot"], snapshot.name]
                    )
                    del market_by_identity[identity]
                elif label in duplicates:
                    duplicates[label].append(snapshot.name)
                else:
                    market_by_identity[identity] = item
            elif component == "macro_fred":
                macro_fred.append(item)
            elif component == "macro_cbr":
                if protocol_id != "futures_v27_forward_components_v1":
                    raise ValueError("CBR component came from FRED-only protocol")
                macro_cbr.append(item)
            else:
                raise ValueError(f"unknown component: {component}")
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})

    decisions = sorted(
        (
            item
            for (component, _), item in market_by_identity.items()
            if component == "market_decision"
        ),
        key=lambda item: item["source_dates"][0],
    )
    executions = sorted(
        (
            item
            for (component, _), item in market_by_identity.items()
            if component == "market_execution"
        ),
        key=lambda item: item["source_dates"][0],
    )
    fred_times = sorted(pd.Timestamp(item["retrieved_at_utc"]) for item in macro_fred)
    cbr_times = sorted(pd.Timestamp(item["retrieved_at_utc"]) for item in macro_cbr)
    joinable = [
        str(item["source_dates"][0])
        for item in decisions
        if any(value <= pd.Timestamp(item["retrieved_at_utc"]) for value in fred_times)
        and any(value <= pd.Timestamp(item["retrieved_at_utc"]) for value in cbr_times)
    ]
    progress = base_readiness.phase_progress(
        len(decisions),
        len(executions),
        len(macro_fred),
        len(macro_cbr),
        source_config,
    )
    authenticated_count = sum(
        item["protocol_id"] == "futures_v27_forward_fred_api_component_v1"
        for item in macro_fred
    )
    anonymous_count = len(macro_fred) - authenticated_count
    return {
        "protocol_id": "futures_v27_forward_component_readiness_v2",
        "admission_protocol_id": correction["protocol_id"],
        "admission_protocol_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "snapshot_count": len(valid) + len(invalid),
        "valid_snapshot_count": len(valid),
        "invalid_snapshot_count": len(invalid),
        "valid_market_execution_dates": len(executions),
        "valid_market_decision_dates": len(decisions),
        "valid_macro_FRED_snapshots": len(macro_fred),
        "valid_macro_FRED_anonymous_snapshots": anonymous_count,
        "valid_macro_FRED_authenticated_snapshots": authenticated_count,
        "valid_macro_CBR_snapshots": len(macro_cbr),
        "causally_joinable_decision_dates": len(joinable),
        "joinable_source_dates": joinable,
        "duplicate_market_component_dates": {
            key: sorted(set(value)) for key, value in duplicates.items()
        },
        "invalid_snapshots": invalid,
        "valid_snapshots": valid,
        "contains_signal_return_target_prediction_or_pnl": False,
        "progress": progress,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=base_source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
