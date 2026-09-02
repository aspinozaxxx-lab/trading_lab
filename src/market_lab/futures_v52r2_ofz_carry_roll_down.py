"""Map MOEX's legacy SUR history code to the sealed RUB OFZ universe meaning."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Final

import yaml

from market_lab import futures_v52_ofz_carry_roll_down as base
from market_lab import futures_v52r1_ofz_carry_roll_down as r1

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v52r2_ofz_carry_roll_down.yaml"
CONFIG_SHA256: Final[str] = "8a2e97e23c2f56a57069c00de8661000b9bb39f0ab4b0851e789ca05879d0c88"


def load_protocol() -> base.Protocol:
    actual = base._sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(correction, dict):
        raise ValueError("V52R2 config must be an object")
    parent = correction["parent_r1"]
    semantic = correction["semantic_correction"]
    observed = correction["observed_identity_failure"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or correction.get("protocol_id") != "v52r2_ofz_carry_roll_down"
        or correction.get("status")
        != "sealed_after_r1_legacy_currency_identity_failure_before_any_ofz_trade_or_return"
        or correction.get("live_trading_allowed") is not False
        or base._sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or base._sha(PROJECT_ROOT / parent["corrected_shared_engine_path"])
        != parent["corrected_shared_engine_sha256"]
        or observed["trades"] != 0
        or observed["positions"] != 0
        or observed["OFZ_return_or_pnl_computed"] is not False
        or semantic["incorrect_literal_history_currency_id"] != "RUB"
        or semantic["correct_MOEX_ISS_legacy_history_currency_id"] != "SUR"
        or semantic["face_unit_remains"] != "RUB"
        or semantic[
            "duration_liquidity_top_count_weights_rebalance_costs_gates_and_portfolio_changed"
        ]
        is not False
    ):
        raise ValueError("V52R2 correction drifted")
    protocol = r1.load_protocol()
    payload = copy.deepcopy(protocol.payload)
    payload["protocol_id"] = correction["protocol_id"]
    payload["status"] = correction["status"]
    payload["selection"]["currency_id"] = "SUR"
    payload["outputs"]["root"] = correction["output_override"]["root"]
    payload["semantic_currency_correction"] = semantic
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
