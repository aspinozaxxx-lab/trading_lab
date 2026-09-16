"""Synthetic inputs only; no historical weather or market outcomes."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from market_lab import futures_v97_hurricane_supply as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


def bulletin(day="31", month="AUG", year="2021", lat="27.0N", lon="90.0W", wind="70"):
    return (f"SYNTHETIC FORECAST/ADVISORY NUMBER   1\n"
            f"SYNTHETIC NHC AL012021\n0900 UTC TUE {month} {day} {year}\n"
            f"FORECAST VALID 01/1200Z {lat} {lon}\nMAX WIND {wind} KT...GUSTS 80 KT.\n"
            "FORECAST VALID 02/1200Z...DISSIPATED\n").encode()


def record(**kwargs):
    result = screen.parse_advisory(bulletin(**kwargs), "al012021.fstadv.001.08310830", 2021, 1)
    return {**result, "url": "https://example.invalid/synthetic"}


def active():
    dates = pd.bdate_range("2021-08-30", "2021-09-06")
    return pd.concat([pd.DataFrame({
        "effective_date": dates, "decision_date": pd.Series(dates).shift(1),
        "observed_through": pd.Series(dates).shift(1), "asset_code": asset,
        "contract_id": asset + "TEST", "plan_tradable": True, "roll": False,
    }) for asset in ("BR", "MIX", "RI", "SI")], ignore_index=True)


def test_filename_scope_and_daily_latest_version_before_cutoff():
    names = ["al012021.fstadv.001.08310830", "al012021.fstadv.001.08311030",
             "al012021.fstadv.002.08311401", "al012021.fstadv.001",
             "ep012021.fstadv.001.08310830"]
    html = "".join(f'<a href="{n}">item</a>' for n in names).encode()
    chosen, metadata = screen.select_files(html, 2021, "1400")
    assert chosen == [names[1]]
    assert metadata == {"versioned_files": 3, "storms": 1, "selected_storm_dates": 1}
    for name, year in [("al012026.fstadv.001.01010900", 2026),
                       ("../al012021.fstadv.001.08310830", 2021), (names[0], 2020)]:
        with pytest.raises(ValueError, match="protected"):
            screen.archive_identity(name, year)


def test_same_clock_different_advisories_fail_closed():
    raw = b'<a href="al012021.fstadv.001.08310900"><a href="al012021.fstadv.002.08310900">'
    with pytest.raises(ValueError, match="ambiguous"):
        screen.select_files(raw, 2021, "1400")


def test_parse_issue_month_rollover_units_and_conservative_availability():
    event = record()
    assert event["issued_at_utc"] == "2021-08-31T09:00:00+00:00"
    assert event["available_at_utc"] == "2021-08-31T10:00:00+00:00"
    assert event["points"] == [{"valid_at_utc": "2021-09-01T12:00:00+00:00",
                                "latitude": 27.0, "longitude": -90.0, "wind_knots": 70}]
    later = screen.parse_advisory(bulletin(), "al012021.fstadv.001.08311100", 2021, 1)
    assert later["available_at_utc"] == "2021-08-31T12:00:00+00:00"


def test_protected_or_mismatched_issue_rejected_before_coordinates():
    with pytest.raises(ValueError, match="protected"):
        screen.parse_advisory(bulletin(year="2026"), "al012021.fstadv.001.08310830", 2021, 1)
    with pytest.raises(ValueError, match="identity"):
        screen.parse_advisory(bulletin().replace(b"NUMBER   1", b"NUMBER   2"),
                              "al012021.fstadv.001.08310830", 2021, 1)
    with pytest.raises(ValueError, match="positions|block"):
        screen.parse_advisory(bulletin().replace(b"MAX WIND 70 KT", b"MAX WIND MISSING KT"),
                              "al012021.fstadv.001.08310830", 2021, 1)


def test_dissipation_is_not_a_fake_zero_wind_measurement():
    raw = bulletin().split(b"FORECAST VALID")[0] + b"FORECAST VALID 01/1200Z...DISSIPATED\n"
    event = screen.parse_advisory(raw, "al012021.fstadv.001.08310830", 2021, 1)
    assert event["points"] == []


def test_gulf_primary_and_non_gulf_control_use_same_rule_except_geography():
    a = screen.targets(active(), [record()], [], config())
    day = pd.Timestamp("2021-09-01")
    for arm in a.values():
        assert arm.loc[arm.effective_date.eq(day), "target_weight"].item() == 0.9
        assert arm.iloc[-1].target_weight == 0 and arm.iloc[-1].contract_id is None
    other = screen.targets(active(), [record(lon="60.0W")], [], config())
    assert other["primary"].target_weight.eq(0).all()
    assert other["control"].target_weight.gt(0).any()


def test_future_release_and_forecast_after_horizon_cannot_trigger():
    future = record()
    future["available_at_utc"] = "2021-08-31T16:00:00+00:00"
    result = screen.targets(active(), [future], [], config())["primary"]
    assert result.target_weight.eq(0).all()
    distant = record()
    distant["points"][0]["valid_at_utc"] = "2021-09-04T12:00:00+00:00"
    assert screen.targets(active(), [distant], [], config())["primary"].target_weight.eq(0).all()


def test_revision_replaces_old_forecast_without_backdating():
    early, late = record(), record(wind="40")
    late["available_at_utc"] = "2021-08-31T14:00:00+00:00"
    result = screen.targets(active(), [early, late], [], config())["primary"]
    assert result.target_weight.eq(0).all()


def test_parse_gap_masks_both_arms_without_fabricating_a_forecast():
    gap = {"version_at_utc": "2021-08-31T08:30:00+00:00"}
    result = screen.targets(active(), [record()], [gap], config())
    for arm in result.values():
        assert arm.feature_unavailable.any()
        assert arm.target_weight.eq(0).all()


def test_weather_expiring_before_fill_is_cancelled():
    event = record()
    event["points"][0]["valid_at_utc"] = "2021-08-31T18:00:00+00:00"
    result = screen.targets(active(), [event], [], config())["primary"]
    row = result.loc[result.effective_date.eq(pd.Timestamp("2021-09-01"))].iloc[0]
    assert row.requested_weight == 0.9 and row.stale_at_fill and row.target_weight == 0


def test_http_failure_preserves_evidence_and_does_not_retry(tmp_path, monkeypatch):
    calls = []

    def refused(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=b"refused\n__HTTP__403", stderr=b"", returncode=0)

    monkeypatch.setattr(screen.subprocess, "run", refused)
    with pytest.raises(ValueError, match="HTTP failure"):
        screen.fetch("https://example.invalid/source", tmp_path / "response", 1000, 0)
    assert len(calls) == 1 and (tmp_path / "response").read_bytes() == b"refused"
    assert json.loads((tmp_path / "response.metadata.json").read_text(
        encoding="utf-8-sig"))["http_status"] == "403"


def test_source_age_and_wind_threshold_are_not_zero_imputation():
    low = screen.targets(active(), [record(wind="63")], [], config())["primary"]
    assert low.target_weight.eq(0).all() and not low.feature_unavailable.any()
    assert config()["screen_gates"]["minimum_round_trips"] == 20


def test_existing_ledger_flat_market_is_only_cost_loss_for_all_four_arms(tmp_path):
    cfg = config()
    signals = screen.targets(active(), [record()], [], cfg)
    market = pd.DataFrame([{
        "session_date": day, "asset_code": "BR", "contract_id": "BRTEST",
        "open": 100.0, "high": 100.0, "low": 100.0, "settle": 100.0,
        "volume": 1e7, "sizing_point_value": 100.0, "accounting_point_value": 100.0,
        "tick_size": 0.01, "fee_per_contract": 1.0, "initial_margin": 1000.0,
    } for day in signals["primary"].effective_date])
    case = screen.engine.simulate_case(tmp_path / "case", signals, market,
                                       {"ready_asset_date_fraction": 1.0}, cfg, "synthetic")
    for arm in case["metrics"].values():
        for metric in arm.values():
            assert metric["execution_complete"] and not metric["terminal_carried"]
            assert metric["gross_vm_pnl"] == pytest.approx(0)
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert arm["double"]["net_pnl"] < arm["base"]["net_pnl"]
    assert case["assessment"]["verdict"] == "REJECT_STAGE1"
