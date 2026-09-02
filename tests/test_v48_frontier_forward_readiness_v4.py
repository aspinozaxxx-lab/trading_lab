"""Tests for V48 readiness with anonymous FRED transport V2 admission."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from market_lab.futures import moex_v27_forward_fred_anonymous_transport_v2 as fred_source
from market_lab.futures import v48_frontier_forward_readiness_v4 as subject


class _Response:
    status_code = 200
    content = b"observation_date,STLFSI4\n2026-08-21,-0.8107\n"


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        return _Response()


def test_anonymous_v2_route_is_selected_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    option_root = tmp_path / "option"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()
    fred_source.collect(
        component_root,
        session=_Session(),
        retrieved_at="2026-09-02T22:10:00Z",
    )

    report = subject.assess(option_root, component_root)

    assert report["protocol_id"] == "v48_frontier_forward_fred_transport_v2_correction_v1"
    assert report["FRED_route_if_collected_now"] == "anonymous_fredgraph_header_v2"
    assert report["valid_macro_FRED_anonymous_v1_snapshots"] == 0
    assert report["valid_macro_FRED_anonymous_v2_snapshots"] == 1
    assert report["component_source_invalid_snapshot_count"] == 0
    assert report["progress"]["FRED_component_available"] is True
    assert report["contains_signal_return_target_prediction_or_pnl"] is False


def test_authenticated_route_remains_selected_for_valid_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "c" * 32)
    option_root = tmp_path / "option"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()

    report = subject.assess(option_root, component_root)

    assert report["FRED_route_if_collected_now"] == "authenticated_official_API"
    assert report["fixed_mode"]["V39_mapped_target_multiplier"] == 1.5
    assert report["live_trading_allowed"] is False
