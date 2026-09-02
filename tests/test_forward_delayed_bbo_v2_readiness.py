from __future__ import annotations

from market_lab.futures import forward_delayed_bbo_v2_readiness as readiness


def test_empty_delayed_sources_are_discovery_only(tmp_path) -> None:
    payload = readiness.readiness(tmp_path / "cross", tmp_path / "broad")

    assert payload["cross_market"]["counts"]["snapshot_directories"] == 0
    assert payload["broad_carry"]["counts"]["snapshot_directories"] == 0
    assert not payload["cross_market"]["gates"]["annualization_allowed"]
    assert not payload["broad_carry"]["gates"]["realtime_or_depth_promotion_allowed"]
