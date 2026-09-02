"""Tests for V27 readiness with the approved anonymous FRED transport V2."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from market_lab.futures import moex_v27_forward_fred_anonymous_transport_v2 as anon_source
from market_lab.futures import v27_forward_component_readiness_v3 as readiness


class _Response:
    status_code = 200
    content = b"observation_date,STLFSI4\n2026-08-21,-0.8107\n"


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        assert "id=STLFSI4" in url
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert timeout == 30.0
        return _Response()


def test_readiness_correction_preserves_economics() -> None:
    config = readiness.load_config()
    assert config["route_policy"]["absent_FRED_API_KEY"] == (
        "anonymous_fredgraph_header_v2_only"
    )
    assert config["economic_invariants"]["STLFSI4_series_or_values_changed"] is False
    assert config["economic_invariants"]["economic_parameters_changed"] == 0


def test_empty_root_reports_all_three_routes_as_zero(tmp_path: Path) -> None:
    report = readiness.assess(tmp_path)
    assert report["valid_macro_FRED_snapshots"] == 0
    assert report["valid_macro_FRED_anonymous_v1_snapshots"] == 0
    assert report["valid_macro_FRED_anonymous_v2_snapshots"] == 0
    assert report["valid_macro_FRED_authenticated_snapshots"] == 0
    assert report["progress"]["paper_economics_may_start"] is False


def test_anonymous_v2_snapshot_is_audited_and_counted(tmp_path: Path) -> None:
    anon_source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-02T22:10:00Z",
    )
    report = readiness.assess(tmp_path)
    assert report["invalid_snapshot_count"] == 0
    assert report["valid_macro_FRED_snapshots"] == 1
    assert report["valid_macro_FRED_anonymous_snapshots"] == 1
    assert report["valid_macro_FRED_anonymous_v2_snapshots"] == 1
    assert report["valid_macro_FRED_authenticated_snapshots"] == 0
    assert report["progress"]["FRED_component_available"] is True
