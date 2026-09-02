"""Publish V52's valid empty-trade result with an explicit artifact schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Final

import yaml

from market_lab import futures_v52_ofz_carry_roll_down as base

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v52r1_ofz_carry_roll_down.yaml"
CONFIG_SHA256: Final[str] = "491e53c3d8d5fe4e5be931b41bc876be277dd4079beaccdf6fd83a3c9aea31eb"


def load_protocol() -> base.Protocol:
    actual = base._sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(correction, dict):
        raise ValueError("V52R1 config must be an object")
    parent = correction["parent_v52"]
    mechanical = correction["mechanical_correction"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or correction.get("protocol_id") != "v52r1_ofz_carry_roll_down"
        or correction.get("status") != "sealed_after_v52_empty_concat_failure_before_output"
        or correction.get("live_trading_allowed") is not False
        or base._sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or parent["implementation_sha256_at_failed_run"]
        != "a7752bd03520118aa3e8a777ba0bb7714363461445f6ab17c10cc48abb95e312"
        or base._sha(PROJECT_ROOT / mechanical["corrected_shared_engine_path"])
        != mechanical["corrected_shared_engine_sha256"]
        or correction["observed_failure"]["output_directory_created"] is not False
        or mechanical[
            "selection_duration_liquidity_top_count_weights_rebalance_costs_and_gates_changed"
        ]
        is not False
    ):
        raise ValueError("V52R1 correction drifted")
    protocol = base.load_protocol()
    payload: dict[str, Any] = copy.deepcopy(protocol.payload)
    payload["protocol_id"] = correction["protocol_id"]
    payload["status"] = correction["status"]
    payload["outputs"]["root"] = correction["output_override"]["root"]
    payload["mechanical_correction"] = mechanical
    return base.Protocol(payload, actual, protocol.ofz_root, protocol.v49_root)


def main() -> None:
    protocol = load_protocol()
    output = base.run(protocol)
    summary = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    print(f"run={output.name}")
    print(f"verdict={summary['verdict']}")
    print(f"audit_all_true={audit['all_true']}")


if __name__ == "__main__":
    main()


__all__ = ["CONFIG_PATH", "CONFIG_SHA256", "load_protocol", "main"]
