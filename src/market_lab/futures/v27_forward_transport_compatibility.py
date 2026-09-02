"""Fail-closed registry for transport-only V27 forward collector builds."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

import yaml

from market_lab.futures import moex_v27_forward_validation_source as source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v27_forward_transport_compatibility_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "ae70f0d4979ee724bb9f0759cc7721ad03fed739cf45ae52b8003aa9cb2cf230"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_implementation_hashes(config: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        str(item["implementation_sha256"])
        for item in config["approved_implementations"].values()
    )


def load_config() -> dict[str, Any]:
    actual = sha256_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    invariants = config["compatibility_invariants"]
    current = sha256_file(Path(source.__file__))
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id")
        != "futures_v27_forward_transport_compatibility_v1"
        or config.get("live_trading_allowed") is not False
        or config["parent_source"]["protocol_sha256"] != source.CONFIG_SHA256
        or current not in approved_implementation_hashes(config)
        or invariants["economic_hypothesis_changed"] is not False
        or invariants["signal_or_position_logic_changed"] is not False
        or invariants["endpoint_or_query_changed"] is not False
        or invariants["normalization_or_availability_changed"] is not False
        or invariants["output_schema_changed"] is not False
        or invariants["forward_boundary_changed"] is not False
        or invariants["failed_request_substitution"] != "forbidden"
        or invariants["cached_or_backfilled_response_substitution"] != "forbidden"
        or invariants["partial_snapshot_persistence"] != "forbidden"
        or invariants["all_required_MOEX_FRED_CBR_responses_still_mandatory"] is not True
    ):
        raise ValueError("V27 forward transport compatibility drifted")
    return config


def assert_compatible(original_implementation_sha256: str) -> str:
    config = load_config()
    if (
        original_implementation_sha256
        != config["parent_source"]["original_implementation_sha256"]
    ):
        raise ValueError("V27 original forward implementation identity drifted")
    return sha256_file(Path(source.__file__))

