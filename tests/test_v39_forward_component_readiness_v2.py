"""Tests for V39 component readiness with anonymous FRED V2."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from market_lab.futures import moex_v27_forward_fred_anonymous_transport_v2 as fred_source
from market_lab.futures import v39_forward_component_readiness_v2 as subject


class _Response:
    status_code = 200
    content = b"observation_date,STLFSI4\n2026-08-21,-0.8107\n"


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        return _Response()


def test_anonymous_v2_is_valid_but_cannot_start_incomplete_warmup(tmp_path: Path) -> None:
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

    assert report["protocol_id"] == "futures_v39_forward_validation_v1"
    assert report["valid_macro_FRED_anonymous_v2_snapshots"] == 1
    assert report["component_source_invalid_snapshot_count"] == 0
    assert report["progress"]["FRED_component_available"] is True
    assert report["progress"]["CBR_component_available"] is False
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["contains_signal_return_target_prediction_or_pnl"] is False
