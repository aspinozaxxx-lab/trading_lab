"""Synthetic source, causal-state and unchanged-ledger tests, no market history."""

import json

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v99_reserve_liquidity as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


def release(day="2020-01-02", level=110, usable=True):
    day = pd.Timestamp(day)
    return {"release_date": day.date().isoformat(), "month": day.strftime("%Y-%m"),
            "available_at_utc": screen.prior.day_availability(day).isoformat(),
            "reserve_wednesday_million_usd": level, "usable": usable,
            "source_url": "https://example.invalid/" + day.strftime("%Y%m%d")}


def source_text(day="2020-01-02", observation="Jan 1, 2020"):
    return (f"<p>Release Date: {pd.Timestamp(day).strftime('%B %d, %Y')}</p>"
            f"<p>Millions of dollars Averages of daily figures Wednesday {observation}</p>"
            "<p>Reserve balances with Federal Reserve Banks 1,000 + 20 - 30 1,200</p>"
            "<p>Note: Components may not sum to totals because of rounding.</p>").encode()


def state(level=110, usable=True):
    return screen.states([release("2019-10-03", 100), release(level=level, usable=usable)],
                         config())


def calendar_raw():
    months = pd.period_range("2017-09", "2025-12", freq="M")
    return json.dumps([{"Months": [
        {"MonthValue": m.strftime("%Y%m"), "Dates": [m.strftime("%Y%m") + "08",
                                                     m.strftime("%Y%m") + "01"]}
        for m in months]}]).encode()


def test_calendar_first_date_and_complete_months_excludes_protected_metadata():
    raw = json.loads(calendar_raw())
    raw[0]["Months"].append({"MonthValue": "202601", "Dates": ["20260101"]})
    dates = screen.select_dates(json.dumps(raw).encode(), config())
    assert len(dates) == 100 and dates[0] == "20170901" and dates[-1] == "20251201"
    raw[0]["Months"].pop(20)
    with pytest.raises(ValueError, match="missing"):
        screen.select_dates(json.dumps(raw).encode(), config())


def test_parse_uses_last_column_and_day_after_publication_not_observation():
    row = screen.parse_release(source_text(), "20200102", "https://example.invalid", config())
    assert row["reserve_wednesday_million_usd"] == 1200
    assert row["weekly_average_audit_only"] == 1000
    assert row["available_at_utc"] == "2020-01-03T06:00:00+00:00"
    friday = screen.parse_release(source_text("2019-07-05", "Jul 3, 2019"),
                                  "20190705", "x", config())
    assert friday["observation_date"] == "2019-07-03"
    delayed = screen.parse_release(source_text("2025-01-02", "Jan 1, 2025"),
                                   "20250102", "x", config())
    assert not delayed["usable"] and delayed["reason"] == "documented_delay_no_original_clock"


@pytest.mark.parametrize("raw,day", [
    (source_text().replace(b"1,200", b"unknown"), "20200102"),
    (source_text() + source_text(), "20200102"),
    (source_text(), "20200103"),
    (source_text(observation="Jan 2, 2020"), "20200102"),
    (source_text("2026-01-01", "Dec 31, 2025"), "20260101"),
])
def test_malformed_duplicate_wrong_date_and_protected_sources_rejected(raw, day):
    with pytest.raises(ValueError):
        screen.parse_release(raw, day, "x", config())


def test_exact_three_calendar_months_and_missing_baseline_never_shifted():
    out = state()
    assert out[-1]["ready"] and out[-1]["growth"] == pytest.approx(.1)
    assert not out[0]["ready"] and out[0]["growth"] is None
    missing = screen.states([release("2019-09-05", 100), release()], config())
    assert not missing[-1]["ready"]
    delayed = screen.states([release("2025-01-02", 100, False), release("2025-04-03", 120)],
                            config())
    assert not delayed[-1]["ready"] and delayed[-1]["growth"] is None
    with pytest.raises(ValueError, match="duplicate"):
        screen.states([release(), release()], config())


def test_signal_causality_positive_primary_and_flat_for_nonpositive_growth():
    dates = pd.bdate_range("2019-12-30", "2020-01-15")
    signals = screen.targets(active(dates), state(), config())
    primary = signals["primary"]
    assert primary.loc[primary.effective_date.le("2020-01-03"), "target_weight"].eq(0).all()
    assert primary.loc[primary.effective_date.eq("2020-01-06"), "target_weight"].iloc[0] == .9
    for frame in signals.values():
        used = frame.loc[frame.target_weight.ne(0)]
        assert used.available_at_utc.le(used.decision_at_utc).all()
        assert used.lag_available_at_utc.lt(used.available_at_utc).all()
        assert frame.iloc[-1].terminal_flat and frame.iloc[-1].target_weight == 0
    for level in [100, 90]:
        result = screen.targets(active(dates), state(level), config())
        assert result["primary"].target_weight.eq(0).all()
        assert result["control"].target_weight.gt(0).any()


def test_delay_masks_both_arms_no_forward_fill_and_missing_plan_does_not_alter_feature():
    dates = pd.bdate_range("2019-12-30", "2020-01-15")
    for frame in screen.targets(active(dates), state(usable=False), config()).values():
        assert frame.target_weight.eq(0).all() and frame.feature_unavailable.all()
    plan = active(dates)
    plan.loc[plan.asset_code.eq("MIX"), "plan_tradable"] = False
    frame = screen.targets(plan, state(), config())["primary"]
    assert frame.requested_weight.gt(0).any() and frame.target_weight.eq(0).all()
    assert (~frame.feature_unavailable).any()


def test_stale_fill_and_source_age_expire_no_future_exit_filter():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-10", "2020-01-13", "2020-01-14"])
    frame = screen.targets(active(dates), state(), config())["primary"]
    gap = frame.loc[frame.effective_date.eq("2020-01-10")].iloc[0]
    assert gap.requested_weight == .9 and gap.stale_at_fill and gap.target_weight == 0
    assert frame.loc[frame.effective_date.eq("2020-01-13"), "target_weight"].iloc[0] == .9
    late = screen.targets(active(pd.bdate_range("2020-02-12", "2020-02-18")),
                           state(), config())["primary"]
    assert late.feature_unavailable.all() and late.target_weight.eq(0).all()


def test_flat_ledger_costs_all_scenarios(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2019-12-30", "2020-01-15")), state(), cfg)
    market = pd.DataFrame([{
        "session_date": day, "asset_code": "MIX", "contract_id": "MIXTEST",
        "open": 100., "high": 100., "low": 100., "settle": 100., "volume": 1e7,
        "sizing_point_value": 100., "accounting_point_value": 100., "tick_size": .01,
        "fee_per_contract": 1., "initial_margin": 1000.,
    } for day in signals["primary"].effective_date])
    case = screen.engine.simulate_case(tmp_path / "case", signals, market,
                                       {"ready_asset_date_fraction": 1.}, cfg, "synthetic")
    for arm in case["metrics"].values():
        for metric in arm.values():
            assert metric["execution_complete"] and metric["round_trips"] == 1
            assert metric["gross_vm_pnl"] == pytest.approx(0)
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert arm["double"]["net_pnl"] < arm["base"]["net_pnl"]


def test_collector_preserves_failed_source_without_retry(tmp_path, monkeypatch):
    cfg = config()
    raw = tmp_path / "synthetic_calendar.json"
    raw.write_bytes(calendar_raw())
    cfg["source"]["discovery_inputs"] = {"releaseDates.json": {
        "path": raw.name, "bytes": raw.stat().st_size, "sha256": screen.base.sha(raw)}}
    cfg["source"]["source_parent"] = "source"
    (tmp_path / "source").mkdir()
    monkeypatch.setattr(screen, "STORAGE", tmp_path)
    calls = []

    def refused(url, destination, *args):
        calls.append(url)
        destination.write_bytes(b"synthetic refusal")
        raise ValueError("HTTP failure, no retry")

    monkeypatch.setattr(screen.prior.source_tools, "fetch", refused)
    with pytest.raises(ValueError, match="source failed"):
        screen.collect(cfg, "a" * 64)
    root = tmp_path / "source" / ("a" * 12)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["status"] == "FAILED_SOURCE_NO_RETRY" and manifest["parsed_months"] == 0
    assert len(calls) == 1 and "raw/20170901.html" in manifest["files"]
    assert not (root / "releases.json").exists()


def test_delayed_new_state_replaces_old_positive_without_retrospective_changes():
    cfg = config()
    releases = [release("2019-10-03", 100), release("2019-11-07", 100),
                release(), release("2020-02-06", 150, False)]
    dates = pd.bdate_range("2020-02-03", "2020-02-13")
    result = screen.targets(active(dates), screen.states(releases, cfg), cfg)["primary"]
    assert result.loc[result.effective_date.le("2020-02-07"), "target_weight"].eq(.9).all()
    assert result.loc[result.effective_date.ge("2020-02-10"), "feature_unavailable"].all()
    assert result.loc[result.effective_date.ge("2020-02-10"), "target_weight"].eq(0).all()
    with pytest.raises(ValueError, match="protected"):
        screen.states([release("2026-01-02", 100)], cfg)
