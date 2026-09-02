"""Tests for current V48 readiness with credential-safe FRED routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_lab.futures import v48_frontier_forward_readiness_v3 as subject


def test_empty_sources_report_missing_key_without_credential_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    option_root = tmp_path / "option"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()

    report = subject.assess(option_root, component_root)

    assert report["protocol_id"] == "v48_frontier_forward_fred_api_correction_v1"
    assert report["FRED_API_KEY_configured"] is False
    assert report["FRED_route_if_collected_now"] == "anonymous_fredgraph"
    assert report["fixed_mode"]["V39_mapped_target_multiplier"] == 1.5
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["contains_signal_return_target_prediction_or_pnl"] is False
    assert report["live_trading_allowed"] is False


def test_valid_key_only_changes_predeclared_transport_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "c" * 32)
    option_root = tmp_path / "option"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()

    report = subject.assess(option_root, component_root)

    assert report["FRED_API_KEY_configured"] is True
    assert report["FRED_route_if_collected_now"] == "authenticated_official_API"
    assert report["fixed_mode"]["name"] == "frontier"
    assert report["valid_macro_FRED_snapshots"] == 0
