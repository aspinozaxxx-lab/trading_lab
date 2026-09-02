"""Tests for V49 forward and paper readiness with FRED transport V2."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from market_lab.futures import moex_v27_forward_fred_anonymous_transport_v2 as fred_source
from market_lab.futures import v49_double_risk_forward_readiness_v2 as forward
from market_lab.futures import v49_double_risk_paper_readiness_v2 as paper


class _Response:
    status_code = 200
    content = b"observation_date,STLFSI4\n2026-08-21,-0.8107\n"


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        return _Response()


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    option_root = tmp_path / "option"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()
    fred_source.collect(
        component_root,
        session=_Session(),
        retrieved_at="2026-09-02T22:10:00Z",
    )
    return option_root, component_root


def test_forward_counts_postseal_anonymous_v2_without_changing_arm(tmp_path: Path) -> None:
    option_root, component_root = _roots(tmp_path)

    report = forward.assess(option_root, component_root)

    assert report["postseal_valid_macro_FRED_snapshots"] == 1
    assert report["component_source_invalid_snapshot_count"] == 0
    assert report["fixed_arm"]["V39_mapped_target_multiplier"] == 2.0
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["contains_signal_return_target_prediction_or_pnl"] is False


def test_paper_counts_postseal_anonymous_v2_without_changing_boundary(tmp_path: Path) -> None:
    option_root, component_root = _roots(tmp_path)

    report = paper.assess(option_root, component_root)

    assert report["postseal_valid_macro_FRED_snapshots"] == 1
    assert report["component_source_invalid_snapshot_count"] == 0
    assert report["eligibility_boundary_utc"] == "2026-09-02T19:16:00+00:00"
    assert report["progress"]["cagr_reporting_allowed"] is False
    assert report["live_trading_allowed"] is False
