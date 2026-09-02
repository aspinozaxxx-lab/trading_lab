"""Tests for dual-route official FRED component readiness."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from market_lab.futures import moex_v27_forward_fred_api_component_source as api_source
from market_lab.futures import v27_forward_component_readiness_v2 as readiness


class _Response:
    status_code = 200
    content = json.dumps(
        {"observations": [{"date": "2026-08-21", "value": "-0.8107"}]}
    ).encode()


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        assert "api_key=" in url
        assert headers
        assert timeout == 30.0
        return _Response()


def test_dual_route_protocol_is_sealed_without_economic_change() -> None:
    config = readiness.load_config()

    assert config["protocol_id"] == "v48_frontier_forward_fred_api_correction_v1"
    assert config["live_trading_allowed"] is False
    assert config["economic_invariants"]["V48_mode_or_parameters_changed"] is False
    assert config["route_policy"]["fallback_after_authenticated_failure"] == "forbidden"
    assert config["route_policy"]["credential_persistence"] == "forbidden"


def test_empty_root_reports_both_FRED_routes_as_zero(tmp_path: Path) -> None:
    report = readiness.assess(tmp_path)

    assert report["valid_macro_FRED_snapshots"] == 0
    assert report["valid_macro_FRED_anonymous_snapshots"] == 0
    assert report["valid_macro_FRED_authenticated_snapshots"] == 0
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["contains_signal_return_target_prediction_or_pnl"] is False


def test_authenticated_snapshot_is_dispatched_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "d" * 32)
    api_source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-02T12:00:00Z",
    )

    report = readiness.assess(tmp_path)

    assert report["invalid_snapshot_count"] == 0
    assert report["valid_macro_FRED_snapshots"] == 1
    assert report["valid_macro_FRED_anonymous_snapshots"] == 0
    assert report["valid_macro_FRED_authenticated_snapshots"] == 1
    assert report["progress"]["FRED_component_available"] is True
