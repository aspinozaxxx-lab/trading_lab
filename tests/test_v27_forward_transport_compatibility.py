"""Tests for the sealed transport-only V27 forward source lineage."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import moex_v27_forward_validation_source as source
from market_lab.futures import v27_forward_transport_compatibility as compatibility


def test_current_collector_is_explicitly_approved_without_economic_change() -> None:
    config = compatibility.load_config()

    assert config["protocol_id"] == "futures_v27_forward_transport_compatibility_v1"
    assert config["live_trading_allowed"] is False
    assert config["compatibility_invariants"]["economic_hypothesis_changed"] is False
    assert config["compatibility_invariants"]["failed_request_substitution"] == "forbidden"
    assert compatibility.sha256_file(Path(source.__file__)) in (
        compatibility.approved_implementation_hashes(config)
    )


def test_original_sealed_collector_identity_is_preserved() -> None:
    config = compatibility.load_config()
    original = config["parent_source"]["original_implementation_sha256"]

    current = compatibility.assert_compatible(original)

    assert current == compatibility.sha256_file(Path(source.__file__))
    assert current != original

