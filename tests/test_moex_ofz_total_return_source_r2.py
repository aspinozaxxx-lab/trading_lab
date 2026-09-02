"""Tests for the OFZ global-start bondization correction."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from market_lab.futures import moex_ofz_total_return_source_r2 as subject


def test_real_r2_changes_only_schedule_transport() -> None:
    config = subject.load_config()

    correction = config["schedule_transport_correction"]
    assert correction["R1_output_created"] is False
    assert correction["R1_daily_history_transport_unchanged"] is True
    assert correction["market_fields_or_economics_changed"] is False
    assert config["scope"]["computes_return_target_prediction_or_pnl"] is False
    assert config["live_trading_allowed"] is False


def test_schedule_url_uses_global_start() -> None:
    config = subject.load_config()
    url = subject.schedule_url(config, "SU26238RMFS4", "coupons", 20)
    query = parse_qs(urlparse(url).query)

    assert query["start"] == ["20"]
    assert "coupons.start" not in query
    assert query["iss.only"] == ["coupons,coupons.cursor"]
