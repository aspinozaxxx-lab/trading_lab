"""V101 V2 structural correction, unchanged economics, no historical prices."""

import copy

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active
from test_futures_v101_manufacturing_demand import source_text

from market_lab import futures_v101_manufacturing_demand_v2 as screen


def combined_header(raw):
    return raw.replace(b'<th id="y5">2018</th><th id="m5">Jan.',
                       b'<th id="m5">2018 Jan.').replace(b'pct y5 m5 mfg', b'pct m5 mfg')


def test_combined_year_month_recognized_not_annual_column():
    raw = source_text("2018-02-15", "2018-01", change=".0")
    combined = combined_header(raw)
    with pytest.raises(ValueError, match="monthly column count"):
        screen.original.parse_release(combined, "20180215", "x")
    assert screen.parse_release(combined, "20180215", "x") == screen.parse_release(
        raw, "20180215", "x")


@pytest.mark.parametrize("day,last,count,change", [
    ("2020-07-16", "2020-06", 6, ".5"), ("2020-01-17", "2019-12", 6, "-.6"),
    ("2025-12-03", "2025-09", 6, ".0"), ("2025-12-23", "2025-11", 7, ".0")])
def test_old_formats_exactly_equal(day,last,count,change):
    raw = source_text(day,last,count,change)
    assert screen.parse_release(raw, day, "x") == screen.original.parse_release(raw, day, "x")


@pytest.mark.parametrize("mutation", [
    lambda b: b.replace(b'2018 Jan.', b'2017 Jan.'),
    lambda b: b.replace(b'>.0<', b'>unknown<'),
    lambda b: b.replace(b'[p]', b'[r]'),
    lambda b: b.replace(b'2018 Jan.', b'2018 Bogus.'),
    lambda b: b.replace(b'pct m5 mfg', b'pct y4 m5 mfg'),
    lambda b: b.replace(b'id="m5"', b'id="m4"'),
    lambda b: b.replace(b'February 15, 2018', b'February 16, 2018'),
    lambda b: b + b,
])
def test_bad_combined_never_masked_or_zeroed(mutation):
    raw = combined_header(source_text("2018-02-15", "2018-01", change=".0"))
    with pytest.raises(ValueError):
        screen.parse_release(mutation(raw), "20180215", "x")


def test_economic_fields_and_targets_unchanged():
    old = screen.original.read_json(screen.original.CONFIG)
    new = screen.config()
    for name in ("stage", "goal_verified", "live_trading_allowed", "protected_from",
                 "parent_v64_seal_sha256", "period", "assets", "signal", "execution",
                 "screen_gates", "limitations"):
        assert new[name] == old[name]
    dates = pd.bdate_range("2020-07-14", "2020-08-07")
    releases = [screen.parse_release(source_text(), "20200716", "x")]
    state = screen.original.states(releases)
    a = screen.original.targets(active(dates), state, old)
    b = screen.original.targets(active(dates), state, new)
    for arm in a:
        pd.testing.assert_frame_equal(a[arm], b[arm])


def test_reused_source_hash_and_terminal_status_are_required(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "raw.html").write_bytes(b"synthetic")
    manifest = {"status":"FAILED_SOURCE_NO_RETRY",
                "files":{"raw.html":screen.base.sha(root / "raw.html")}}
    screen.base.write_json(root / "manifest.json",manifest)
    digest = screen.base.sha(root / "manifest.json")
    assert screen.checked_inventory(root,digest,"FAILED_SOURCE_NO_RETRY") == manifest
    with pytest.raises(ValueError,match="status drift"):
        screen.checked_inventory(root,digest,"COMPLETE")
    (root / "raw.html").write_bytes(b"tampered")
    with pytest.raises(ValueError,match="artifact drift"):
        screen.checked_inventory(root,digest,"FAILED_SOURCE_NO_RETRY")


def test_source_refusal_is_preserved_no_retry(tmp_path, monkeypatch):
    cfg = copy.deepcopy(screen.config())
    cfg["source"].update(probe_path="probe",failed_source_path="failed",source_parent="new")
    (tmp_path / "probe").mkdir()
    (tmp_path / "failed").mkdir()
    (tmp_path / "new").mkdir()
    for name in ("index.html","index.html.metadata.json"):
        (tmp_path / "probe" / name).write_text("synthetic")
    monkeypatch.setattr(screen,"STORAGE",tmp_path)
    monkeypatch.setattr(screen,"checked_inventory",lambda root,*args: {
        "error":"unexpected monthly column count","parsed_releases":2,"new_http_requests":3})
    monkeypatch.setattr(screen.original,"select_dates",lambda *args:["20180316"])
    calls = []

    def refused(url,path,*args):
        calls.append(url)
        path.write_bytes(b"refusal")
        raise ValueError("HTTP refusal")

    monkeypatch.setattr(screen.original.prior.source_tools,"fetch",refused)
    with pytest.raises(ValueError,match="source failed"):
        screen.collect(cfg,"a"*64)
    root = tmp_path / "new" / ("a"*12)
    manifest = screen.original.read_json(root / "manifest.json")
    assert len(calls) == 1 and manifest["status"] == "FAILED_SOURCE_NO_RETRY"
    assert manifest["parsed_releases"] == 0 and not (root / "releases.json").exists()
    assert "raw/20180316.html" in manifest["files"]
