"""Publish V53 after casting one NumPy coverage gate to a built-in bool."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Final

import yaml

from market_lab import futures_v53_ofz_curve_v49_governor as base

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v53r1_ofz_curve_v49_governor.yaml"
CONFIG_SHA256: Final[str] = "61c18f551e845cb06ea892c914d34862faf2846ab12b3bb240f0df2bc76b9b9e"


def load_protocol() -> dict:
    actual = base._sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent, mechanical = correction["parent_v53"], correction["mechanical_correction"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or correction.get("protocol_id") != "v53r1_ofz_curve_v49_governor"
        or correction.get("status") != "sealed_after_v53_numpy_bool_serialization_mismatch"
        or correction.get("live_trading_allowed") is not False
        or base._sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or base._sha(PROJECT_ROOT / mechanical["corrected_engine_path"])
        != mechanical["corrected_engine_sha256"]
        or mechanical["curve_state_factors_returns_metrics_and_gates_changed"] is not False
    ):
        raise ValueError("V53R1 correction drifted")
    payload = copy.deepcopy(base.load_protocol())
    payload["protocol_id"] = correction["protocol_id"]
    payload["status"] = correction["status"]
    payload["outputs"]["root"] = correction["output_override"]["root"]
    payload["_config_sha256"] = actual
    payload["mechanical_correction"] = mechanical
    return payload


def main() -> None:
    config = load_protocol()
    output = base.run(config)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    print(f"run={output.name}")
    print(f"verdict={metrics['verdict']}")
    print(f"audit_all_true={audit['all_true']}")


if __name__ == "__main__":
    main()


__all__ = ["CONFIG_PATH", "CONFIG_SHA256", "load_protocol", "main"]
