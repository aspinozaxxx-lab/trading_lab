"""Synthetic release/header/clock and real-ledger tests; no historical prices."""


import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v101_manufacturing_demand as screen


def config():
    return screen.read_json(screen.CONFIG)


def calendar_raw():
    dates = [p.strftime("%Y%m") + "15" for p in pd.period_range("2017-12", "2025-09", freq="M")]
    dates += ["20251203", "20251223", "20260116"]
    links = [f'<a href="{d}{"" if d == "20251203" else "/"}">HTML</a>' for d in dates]
    links += ['<a href="Revisions/20251124/DefaultRev.htm">revision</a>',
              '<a href="20250916/g17sup.htm">supplement</a>',
              '<a href="https://example.invalid/releases/g17/20251001/">foreign</a>',
              '<a href="20251223/default.htm">duplicate navigation</a>']
    return "".join(links).encode()


def source_text(day="2020-07-16", last="2020-06", count=6, change=".5"):
    periods = pd.period_range(end=last, periods=count, freq="M")
    headers, values = [], []
    for i, p in enumerate(periods):
        flag = "p" if i == count - 1 or (count == 7 and i == count - 2) else "r"
        headers.append(f'<th id="y{i}">{p.year}</th><th id="m{i}">'
                       f'{p.strftime("%b")}.[{flag}]</th>')
        values.append(f'<td headers="pct y{i} m{i} mfg">{change if i == count-1 else "9.9"}</td>')
    table = (f'<table title="{screen.TITLE}"><tr><th id="pct">Percent&nbsp;change</th>'
             '<th id="idx">2017=100</th><th id="annual">Year-on-year</th></tr><tr>'
             + "".join(headers) + '</tr><tr><th id="mfg">Manufacturing (see note below)</th>'
             '<td headers="idx mfg">999.9</td>' + "".join(values)
             + '<td headers="pct annual mfg">77.7</td></tr><tr><th>Previous estimates</th>'
             '<td>99.9</td></tr></table>')
    # Text can be split across tags: month and preliminary marker must remain separate.
    table = table.replace('.[', '.<abbr title="preliminary">[').replace(']</th>', ']</abbr></th>')
    return (f'<p>Release Date: {pd.Timestamp(day).strftime("%B %d, %Y")}</p>'
            '<h5>Seasonally adjusted</h5>' + table).encode()


def release(day="2020-07-16", value=.5, month="2020-06"):
    return {"release_date": day, "observation_month": month,
            "available_at_utc": screen.prior.day_availability(day).isoformat(),
            "manufacturing_mom_percent": value, "usable": True, "source_url": "synthetic:"+day}


def test_inventory_actual_dates_noslash_and_excluded_revision_future_and_foreign():
    selected = screen.select_dates(calendar_raw(), config())
    assert len(selected) == 96 and selected[-2:] == ["20251203", "20251223"]
    assert all(d < "20260101" for d in selected)
    with pytest.raises(ValueError, match="coverage"):
        screen.select_dates(calendar_raw().replace(b'20251203', b'20251124'), config())


@pytest.mark.parametrize("day,last,count,change", [
    ("2020-07-16", "2020-06", 6, ".5"),
    ("2020-01-17", "2019-12", 6, "-.6"),
    ("2025-12-03", "2025-09", 6, ".0"),
    ("2025-12-23", "2025-11", 7, ".0"),
])
def test_header_bound_latest_monthly_preliminary_not_level_prior_or_yoy(day,last,count,change):
    raw = source_text(day,last,count,change)
    if count == 7:
        raw = raw.replace(b"Manufacturing (see note below)", b"Manufacturing*")
    row = screen.parse_release(raw, day, "synthetic")
    assert row["observation_month"] == last
    assert row["monthly_columns"] == count
    assert row["manufacturing_mom_percent"] == float(change)
    assert pd.Timestamp(row["available_at_utc"]) > pd.Timestamp(day).tz_localize("UTC")
    assert not row["original_receipt_verified"]


@pytest.mark.parametrize("mutation", [
    lambda b: b.replace(b'>.5<', b'>unknown<'),
    lambda b: b.replace(b'July 16, 2020', b'July 17, 2020'),
    lambda b: b.replace(b'[p]', b'[r]'),
    lambda b: b.replace(b'id="pct"', b'id="wrong"'),
    lambda b: b.replace(b'id="m5"', b'id="m4"'),
    lambda b: b + b,
])
def test_bad_source_never_defaults_to_zero(mutation):
    with pytest.raises(ValueError):
        screen.parse_release(mutation(source_text()), "20200716", "synthetic")


def test_protected_future_observation_and_source_clock_rejected():
    with pytest.raises(ValueError, match="protected"):
        screen.parse_release(source_text("2026-01-16","2025-12"), "20260116", "x")
    with pytest.raises(ValueError, match="prior preliminary"):
        screen.parse_release(source_text(last="2020-08"), "20200716", "x")
    with pytest.raises(ValueError, match="duplicate"):
        screen.states([release(), release()])
    bad = release()
    bad["available_at_utc"] = "2020-07-16T00:00:00Z"
    with pytest.raises(ValueError, match="clock"):
        screen.states([bad])


def test_next_open_positive_rule_zero_and_negative_cash_terminal_flat():
    dates = pd.bdate_range("2020-07-14", "2020-07-29")
    for value in [.5, 0., -.5]:
        signals = screen.targets(active(dates), screen.states([release(value=value)]), config())
        p = signals["primary"]
        assert p.loc[p.effective_date.le("2020-07-17"), "target_weight"].eq(0).all()
        assert p.loc[p.effective_date.eq("2020-07-20"), "target_weight"].iloc[0] == (
            .9 if value > 0 else 0.)
        for f in signals.values():
            used = f.loc[f.target_weight.ne(0)]
            assert used.available_at_utc.le(used.decision_at_utc).all()
            assert f.iloc[-1].terminal_flat and f.iloc[-1].target_weight == 0
        assert signals["control"].target_weight.gt(0).any()


def test_new_release_changes_only_after_availability_no_future_exit_filter():
    dates = pd.bdate_range("2020-07-14", "2020-08-05")
    first = screen.states([release()])
    later = screen.states([release(), release("2020-07-23", -.5)])
    a = screen.targets(active(dates), first, config())["primary"]
    b = screen.targets(active(dates), later, config())["primary"]
    pd.testing.assert_frame_equal(a[a.effective_date.le("2020-07-24")],
                                  b[b.effective_date.le("2020-07-24")])
    assert b.loc[b.effective_date.ge("2020-07-27"), "target_weight"].eq(0).all()
    assert not b.loc[b.effective_date.ge("2020-07-27"), "feature_unavailable"].any()


def test_expiry_at_fill_source_age_and_missing_plan_mask_preserved():
    dates = pd.to_datetime(["2020-07-16","2020-07-17","2020-07-24","2020-07-27","2020-07-28"])
    p = screen.targets(active(dates), screen.states([release()]), config())["primary"]
    row = p.loc[p.effective_date.eq("2020-07-24")].iloc[0]
    assert row.requested_weight == .9 and row.stale_at_fill and row.target_weight == 0
    assert p.loc[p.effective_date.eq("2020-07-27"), "target_weight"].iloc[0] == .9
    late = screen.targets(active(pd.bdate_range("2020-09-01","2020-09-07")),
                          screen.states([release()]), config())["primary"]
    assert late.feature_unavailable.all() and late.target_weight.eq(0).all()
    plan = active(pd.bdate_range("2020-07-14","2020-07-29"))
    plan.loc[plan.asset_code.eq("BR"), "plan_tradable"] = False
    masked = screen.targets(plan, screen.states([release()]), config())["primary"]
    assert masked.requested_weight.gt(0).any() and masked.target_weight.eq(0).all()


def test_flat_market_both_costs_and_cash_tamper_detection(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2020-07-14","2020-07-29")),
                             screen.states([release()]), cfg)
    market = pd.DataFrame([{
        "session_date": d, "asset_code": "BR", "contract_id": "BRTEST", "open": 100.,
        "high": 100., "low": 100., "settle": 100., "volume": 1e7,
        "sizing_point_value": 100., "accounting_point_value": 100., "tick_size": .01,
        "fee_per_contract": 1., "initial_margin": 1000.,
    } for d in signals["primary"].effective_date])
    folder = tmp_path / "case"
    case = screen.engine.simulate_case(folder, signals, market,
                                      {"ready_asset_date_fraction":1.}, cfg, "synthetic")
    for arm in case["metrics"].values():
        for m in arm.values():
            assert m["execution_complete"] and m["round_trips"] == 1
            assert m["gross_vm_pnl"] == pytest.approx(0)
            assert m["net_pnl"] == pytest.approx(-m["total_cost"])
        assert arm["double"]["net_pnl"] < arm["base"]["net_pnl"]
    assert screen.audit_case(folder, case, signals)["cash_cost_metric_annual_count_replays"] == 4
    path = folder / "ledger_primary_base.parquet"
    ledger = pd.read_parquet(path)
    ledger.loc[2,"starting_cash"] += 100
    ledger.to_parquet(path,index=False)
    with pytest.raises(ValueError, match="cash continuity"):
        screen.audit_case(folder, case, signals)


def test_source_failure_kept_once_no_retry_or_economics(tmp_path, monkeypatch):
    cfg = config()
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "index.html").write_bytes(calendar_raw())
    (probe / "index.html.metadata.json").write_text('{}')
    screen.base.write_json(probe / "manifest.json", {
        "status":"COMPLETE_FEASIBILITY_ONLY",
        "files":{p.name:screen.base.sha(p) for p in probe.iterdir() if p.is_file()}})
    cfg["source"].update(probe_path="probe", probe_manifest_sha256=screen.base.sha(
        probe / "manifest.json"), source_parent="source", reused_probe_dates=[])
    (tmp_path / "source").mkdir()
    monkeypatch.setattr(screen, "STORAGE", tmp_path)
    calls = []

    def refused(url,destination,*args):
        calls.append(url)
        destination.write_bytes(b"synthetic refusal")
        raise ValueError("HTTP source failure")

    monkeypatch.setattr(screen.prior.source_tools,"fetch",refused)
    with pytest.raises(ValueError, match="source failed"):
        screen.collect(cfg,"a"*64)
    root = tmp_path / "source" / ("a"*12)
    manifest = screen.read_json(root / "manifest.json")
    assert manifest["status"] == "FAILED_SOURCE_NO_RETRY" and len(calls) == 1
    assert manifest["parsed_releases"] == 0 and not (root / "releases.json").exists()
    assert "raw/20171215.html" in manifest["files"]
