"""Synthetic calendar/source and flat-market tests; no historical market outcomes."""

import json

import pandas as pd
import pytest

from market_lab import futures_v98_fomc_event_premium as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


def spec(year):
    return next(s for s in config()["source"]["schedules"] if s["year"] == year)


def schedule(year):
    pairs = []
    for month in range(1, 9):
        first = pd.date_range(f"{year}-{month:02d}-01", periods=7)
        start = next(d for d in first if d.day_name() == "Tuesday")
        pairs.append((start, start + pd.Timedelta(days=1)))
    published = pd.Timestamp(spec(year)["published_day"]).strftime("%B %d, %Y")
    header = f"<h1>meeting schedule for {year}</h1><p>{published}</p><p>For release at noon</p>"
    if year == 2025:
        body = "<p>For 2025:</p>" + "".join(
            f"<li>Tuesday, {a.strftime('%B')} {a.day}, and "
            f"Wednesday, {b.strftime('%B')} {b.day}</li>" for a, b in pairs)
        body += "<p>For 2026:</p><li>Tuesday, January 27, and Wednesday, January 28</li>"
    else:
        body = "".join(f"<p>{a.strftime('%B')} {a.day}-{b.day} (Tuesday-Wednesday)</p>"
                       for a, b in pairs)
        body += f"<p>January 1-2, {year + 1} (Tuesday-Wednesday)</p>"
    return (header + body).encode()


def active(dates=None):
    dates = pd.bdate_range("2020-03-02", "2020-03-25") if dates is None else dates
    return pd.concat([pd.DataFrame({
        "effective_date": dates, "decision_date": pd.Series(dates).shift(1),
        "observed_through": pd.Series(dates).shift(1), "asset_code": asset,
        "contract_id": asset + "TEST", "plan_tradable": True, "roll": False,
    }) for asset in ("BR", "MIX", "RI", "SI")], ignore_index=True)


def event(cancel=None, available="2019-05-18T05:00:00+00:00"):
    return {"meeting_date": "2020-03-18", "available_at_utc": available,
            "cancel_available_at_utc": cancel, "source_url": "https://example.invalid/calendar"}


def nonzero(frame):
    return frame.loc[frame.target_weight.ne(0), "effective_date"].dt.strftime("%Y-%m-%d").tolist()


@pytest.mark.parametrize("year", [2018, 2023, 2025])
def test_schedule_parsing_requires_eight_ordered_dates_and_ignores_next_year(year):
    events = screen.parse_schedule(schedule(year), spec(year))
    assert len(events) == 8 and all(e["meeting_date"].startswith(str(year)) for e in events)
    assert all(pd.Timestamp(e["available_at_utc"]) < pd.Timestamp(e["meeting_date"], tz="UTC")
               for e in events)


def test_cross_month_and_explicit_next_year_metadata():
    raw = schedule(2023).replace(b"January 3-4", b"January 31-February 1")
    events = screen.parse_schedule(raw, spec(2023))
    assert events[0]["meeting_date"] == "2023-02-01"
    with pytest.raises(ValueError, match="date mismatch"):
        screen.parse_schedule(raw.replace(b"31-February 1", b"30-February 1"), spec(2023))


def test_missing_duplicate_publication_mismatch_and_protected_sources_fail_closed():
    raw = schedule(2023)
    with pytest.raises(ValueError, match="incomplete"):
        screen.parse_schedule(raw.replace(b"August 1-2", b"August UNKNOWN"), spec(2023))
    with pytest.raises(ValueError, match="duplicate"):
        screen.parse_schedule(raw + b"<p>August 1-2 (Tuesday-Wednesday)</p>", spec(2023))
    with pytest.raises(ValueError, match="identity"):
        screen.parse_schedule(raw.replace(b"June 24, 2022", b"June 25, 2022"), spec(2023))
    with pytest.raises(ValueError, match="protected"):
        screen.parse_schedule(raw, {**spec(2023), "year": 2026})


def test_spoken_cancellation_day_not_private_meeting_date_and_pdf_page_identity():
    assert screen.day_availability("2020-03-15") == pd.Timestamp("2020-03-16T05:00:00Z")
    assert screen.day_availability("2020-01-15") == pd.Timestamp("2020-01-16T06:00:00Z")
    sentence = ("March 15, 2020 Page 5 of 21 in lieu of the meeting scheduled "
                "for next Tuesday and Wednesday")
    screen.validate_cancel_text(sentence)
    for wrong in [sentence.replace("Page 5", "Page 4"), sentence.replace("in lieu of", "not")]:
        with pytest.raises(ValueError, match="evidence"):
            screen.validate_cancel_text(wrong)


def test_fixed_two_day_primary_and_previous_week_control():
    result = screen.targets(active(), [event()], config())
    assert nonzero(result["primary"]) == ["2020-03-17", "2020-03-18"]
    assert nonzero(result["control"]) == ["2020-03-10", "2020-03-11"]
    for frame in result.values():
        assert (frame.decision_date < frame.effective_date).all()
        used = frame.loc[frame.target_weight.ne(0)]
        assert used.available_at_utc.le(used.decision_at_utc).all()
        assert frame.iloc[-1].terminal_flat and frame.iloc[-1].contract_id is None


def test_cancellation_does_not_delete_already_taken_control():
    result = screen.targets(active(), [event(cancel="2020-03-16T05:00:00Z")], config())
    assert nonzero(result["primary"]) == []
    assert result["primary"].cancelled_window_count.sum() == 2
    assert nonzero(result["control"]) == ["2020-03-10", "2020-03-11"]
    assert result["control"].cancelled_window_count.sum() == 0


def test_future_cancellation_and_late_publication_never_backdate():
    late_cancel = screen.targets(active(), [event(cancel="2020-03-17T16:00:00Z")], config())
    assert nonzero(late_cancel["primary"]) == ["2020-03-17", "2020-03-18"]
    late_source = screen.targets(active(), [event(available="2020-03-16T16:00:00Z")], config())
    assert nonzero(late_source["primary"]) == ["2020-03-18"]
    assert nonzero(late_source["control"]) == []


def test_expired_actual_fill_cancels_intent_without_using_future_exit():
    dates = pd.bdate_range("2020-03-02", "2020-03-25")
    missing = pd.to_datetime(["2020-03-17", "2020-03-18", "2020-03-19", "2020-03-20"])
    delayed = dates[~dates.isin(missing)]
    frame = screen.targets(active(delayed), [event()], config())["primary"]
    row = frame.loc[frame.decision_date.eq(pd.Timestamp("2020-03-16"))].iloc[0]
    assert row.requested_weight == 0.9 and row.stale_at_fill and row.target_weight == 0
    missing_exit_day = dates[dates != pd.Timestamp("2020-03-19")]
    before = screen.targets(active(), [event()], config())["primary"]
    after = screen.targets(active(missing_exit_day), [event()], config())["primary"]
    assert nonzero(before) == nonzero(after) == ["2020-03-17", "2020-03-18"]


def test_missing_plan_masks_execution_not_calendar_and_protected_event_rejected():
    frame = active()
    frame.loc[frame.asset_code.eq("MIX"), "plan_tradable"] = False
    result = screen.targets(frame, [event()], config())["primary"]
    assert result.requested_weight.gt(0).any() and result.target_weight.eq(0).all()
    assert not result.feature_unavailable.any()
    with pytest.raises(ValueError, match="protected"):
        screen.targets(active(), [{**event(), "meeting_date": "2026-03-18"}], config())


def test_existing_flat_ledger_costs_all_four_scenarios(tmp_path):
    cfg = config()
    signals = screen.targets(active(), [event()], cfg)
    market = pd.DataFrame([{
        "session_date": day, "asset_code": "MIX", "contract_id": "MIXTEST",
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
            assert metric["round_trips"] == 1
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert arm["double"]["net_pnl"] < arm["base"]["net_pnl"]


def test_collector_stops_after_first_failure_and_preserves_partial_evidence(tmp_path, monkeypatch):
    cfg = config()
    cfg["source"]["source_parent"] = "source"
    (tmp_path / "source").mkdir()
    monkeypatch.setattr(screen, "STORAGE", tmp_path)
    calls = []

    def refused(url, destination, *args):
        calls.append(url)
        destination.write_bytes(b"synthetic refusal")
        raise ValueError("HTTP failure, no retry")

    monkeypatch.setattr(screen.source_tools, "fetch", refused)
    with pytest.raises(ValueError, match="source failed"):
        screen.collect(cfg, "a" * 64)
    root = tmp_path / "source" / ("a" * 12)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    assert len(calls) == 1 and manifest["status"] == "FAILED_SOURCE_NO_RETRY"
    assert not (root / "events.json").exists()
    assert "raw/schedule_2018.html" in manifest["files"]
