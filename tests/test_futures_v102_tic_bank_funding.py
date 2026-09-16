"""Synthetic TIC identity/calendar/clock tests and the inherited real accounting engine."""

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v102_tic_bank_funding as screen


def config():
    return screen.read_json(screen.CONFIG)


def calendar_raw():
    parts = ['<h4>1. Monthly Releases and Archives of Treasury International Capital</h4>']
    for p in pd.period_range("2017-12", "2026-01", freq="M"):
        if str(p) == "2025-10":
            continue
        year = p.year - int(p.month <= 2)
        parts.append(f'{year}, release date: ')
        if str(p) == "2024-01":
            parts.append('<a href="/news/press-releases/jy2034">01/19/2023</a>')
        else:
            parts.append(f'<a href="/news/press-releases/sm{p.year}{p.month:02d}">'
                         f'{p.month:02d}/15</a>')
    parts.append('<h4>2. Annual Surveys</h4>'
                 '<a href="/news/press-releases/xy123">02/28/2025</a>')
    return "".join(parts).encode()


def source_text(day="2020-07-16", last="2020-05", flow="-12.5", url="synthetic"):
    month = pd.Period(last, freq="M")
    header = [str(month.year-2), str(month.year-1), (month-12).strftime("%b-%y"),
              month.strftime("%b-%y")]
    header += [p.strftime("%b") for p in pd.period_range(end=month, periods=4, freq="M")]
    def row(values):
        return '<tr>' + ''.join(f'<td>{v}</td>' for v in values) + '</tr>'
    return (f'<meta property="og:url" content="{url}">'
            '<h1>U.S. Department of the Treasury</h1>'
            '<h2>Treasury International Capital Data for latest month</h2>'
            f'<time class="datetime" datetime="{day}T16:00:00-04:00">date</time><table>'
            + row(['','','',screen.TITLE])
            + row(['','','','(Billions of dollars, not seasonally adjusted)'])
            + row(['','','','','','',*header])
            + row(['29','',"Change in Banks' Own Net Dollar-Denominated Liabilities",
                   '400','500','600','700','800','900','1000',flow]) + '</table>').encode()


def release(day="2020-07-16", flow="-12.5", last="2020-05"):
    return screen.parse_release(source_text(day,last,flow),day,"synthetic")


def test_calendar_group_year_protected_filter_and_fixed_typo_override():
    dates = screen.select_dates(calendar_raw(),config())
    assert len(dates) == 96 and min(dates) == "20171215" and max(dates) == "20251215"
    assert dates["20240119"].endswith("jy2034")
    assert "20260215" not in dates and "20251015" not in dates
    for raw in [calendar_raw().replace(b'sm202511">11/15',b'sm202511">10/15'),
                calendar_raw().replace(b'01/19/2023',b'01/20/2023')]:
        with pytest.raises(ValueError):
            screen.select_dates(raw,config())


@pytest.mark.parametrize("day,last,flow", [
    ("2018-04-16","2018-02","-36.3"), ("2023-04-17","2023-02","-11.6"),
    ("2025-11-18","2025-09","18.6"), ("2020-02-18","2019-12","0.0")])
def test_latest_month_not_annual_or_rolling_total(day,last,flow):
    row = release(day,flow,last)
    assert row["bank_flow_billion_usd"] == float(flow) and row["observation_month"] == last
    assert row["table_row"] == 29 and not row["original_receipt_verified"]


@pytest.mark.parametrize("mutation", [
    lambda b: b.replace(b'-12.5',b'unknown'),
    lambda b: b.replace(b'>29<',b'>28<'),
    lambda b: b.replace(b'2020-07-16T',b'2020-07-17T'),
    lambda b: b.replace(b'May-20',b'Jun-20'),
    lambda b: b.replace(b'<td>May</td>',b'<td>Apr</td>'),
    lambda b: b.replace(b'not seasonally adjusted',b'seasonally adjusted'),
    lambda b: b.replace(b'content="synthetic"',b'content="wrong"'),
    lambda b: b+b,
])
def test_missing_wrong_unit_row_clock_month_and_identity_fail_closed(mutation):
    with pytest.raises(ValueError):
        screen.parse_release(mutation(source_text()),"20200716","synthetic")


def test_protected_future_observation_duplicate_and_false_clock_rejected():
    with pytest.raises(ValueError,match="protected"):
        release("2026-01-15",last="2025-11")
    with pytest.raises(ValueError,match="future monthly"):
        release(last="2020-08")
    with pytest.raises(ValueError,match="duplicate"):
        screen.states([release(),release()])
    row = release()
    row["available_at_utc"] = "2020-07-16T00:00:00Z"
    with pytest.raises(ValueError,match="clock"):
        screen.states([row])


def test_contraction_long_otherwise_cash_publication_lag_and_terminal_flat():
    dates = pd.bdate_range("2020-07-14","2020-07-29")
    for value in ['-12.5','0.0','12.5']:
        signals = screen.targets(active(dates),screen.states([release(flow=value)]),config())
        p = signals["primary"]
        assert p.asset_code.eq("SI").all()
        assert p.loc[p.effective_date.le("2020-07-17"),"target_weight"].eq(0).all()
        assert p.loc[p.effective_date.eq("2020-07-20"),"target_weight"].iloc[0] == (
            .9 if float(value) < 0 else 0.)
        assert signals["control"].target_weight.gt(0).any()
        for frame in signals.values():
            used = frame.loc[frame.target_weight.ne(0)]
            assert used.available_at_utc.le(used.decision_at_utc).all()
            assert frame.decision_date.lt(frame.effective_date).all()
            assert frame.iloc[-1].terminal_flat and frame.iloc[-1].contract_id is None


def test_no_backdating_of_new_release_no_future_exit_filter():
    dates = pd.bdate_range("2020-07-14","2020-08-05")
    first = screen.states([release()])
    later = screen.states([release(),release("2020-07-23","12.5")])
    a = screen.targets(active(dates),first,config())["primary"]
    b = screen.targets(active(dates),later,config())["primary"]
    pd.testing.assert_frame_equal(a[a.effective_date.le("2020-07-24")],
                                  b[b.effective_date.le("2020-07-24")])
    assert b.loc[b.effective_date.ge("2020-07-27"),"target_weight"].eq(0).all()
    assert not b.loc[b.effective_date.ge("2020-07-27"),"feature_unavailable"].any()
    missing = dates[dates != pd.Timestamp("2020-07-28")]
    c = screen.targets(active(missing),later,config())["primary"]
    assert c.loc[c.effective_date.le("2020-07-24"),"target_weight"].tolist() == (
        b.loc[b.effective_date.le("2020-07-24"),"target_weight"].tolist())


def test_expiry_gap_and_missing_plan_mask():
    dates = pd.to_datetime(["2020-07-16","2020-07-17","2020-07-24","2020-07-27","2020-07-28"])
    p = screen.targets(active(dates),screen.states([release()]),config())["primary"]
    row = p.loc[p.effective_date.eq("2020-07-24")].iloc[0]
    assert row.requested_weight == .9 and row.stale_at_fill and row.target_weight == 0
    late = screen.targets(active(pd.bdate_range("2020-09-01","2020-09-07")),
                          screen.states([release()]),config())["primary"]
    assert late.feature_unavailable.all() and late.target_weight.eq(0).all()
    plan = active(pd.bdate_range("2020-07-14","2020-07-29"))
    plan.loc[plan.asset_code.eq("SI"),"plan_tradable"] = False
    masked = screen.targets(plan,screen.states([release()]),config())["primary"]
    assert masked.requested_weight.gt(0).any() and masked.target_weight.eq(0).all()


def test_flat_ledger_all_costs_and_cash_tamper_detection(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2020-07-14","2020-07-29")),
                             screen.states([release()]),cfg)
    market = pd.DataFrame([{
        "session_date": day, "asset_code": "SI", "contract_id": "SITEST",
        "open":100.,"high":100.,"low":100.,"settle":100.,"volume":1e7,
        "sizing_point_value":100.,"accounting_point_value":100.,"tick_size":.01,
        "fee_per_contract":1.,"initial_margin":1000.,
    } for day in signals["primary"].effective_date])
    folder = tmp_path / "case"
    case = screen.engine.simulate_case(folder,signals,market,
                                       {"ready_asset_date_fraction":1.},cfg,"synthetic")
    screen.prior.audit_case(folder,case,signals)
    for arm in case["metrics"].values():
        for metric in arm.values():
            assert metric["execution_complete"] and metric["gross_vm_pnl"] == pytest.approx(0)
            assert metric["round_trips"] == 1
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert arm["double"]["net_pnl"] < arm["base"]["net_pnl"]
    ledger = pd.read_parquet(folder / "ledger_primary_base.parquet")
    ledger.loc[1,"starting_cash"] += 100
    ledger.to_parquet(folder / "ledger_primary_base.parquet",index=False)
    with pytest.raises(ValueError,match="cash continuity"):
        screen.prior.audit_case(folder,case,signals)


def test_http_metadata_tamper_rejected(tmp_path):
    path = tmp_path / "sample.html"
    path.write_bytes(b"synthetic")
    metadata = {"url":"synthetic","http_status":"200","curl_returncode":0,
                "bytes":9,"sha256":screen.base.sha(path)}
    screen.base.write_json(tmp_path / "sample.html.metadata.json",metadata)
    screen.check_http(path,"synthetic")
    metadata["url"] = "wrong"
    screen.base.write_json(tmp_path / "sample.html.metadata.json",metadata)
    with pytest.raises(ValueError,match="HTTP evidence"):
        screen.check_http(path,"synthetic")


def test_refusal_stops_once_and_preserves_failed_source(tmp_path,monkeypatch):
    cfg = config()
    probe = tmp_path / "probe"
    probe.mkdir()
    raw = calendar_raw()
    (probe / "index.html").write_bytes(raw)
    screen.base.write_json(probe / "index.html.metadata.json", {
        "url":screen.INDEX_URL,"http_status":"200","curl_returncode":0,
        "bytes":len(raw),"sha256":screen.base.sha(probe / "index.html")})
    screen.base.write_json(probe / "manifest.json", {"status":"COMPLETE_FEASIBILITY_ONLY",
        "files":{p.name:screen.base.sha(p) for p in probe.iterdir() if p.is_file()}})
    cfg["source"].update(source_parent="source",reused_dates={},probes={"initial":{
        "path":"probe","manifest_sha256":screen.base.sha(probe / "manifest.json")}})
    (tmp_path / "source").mkdir()
    monkeypatch.setattr(screen,"STORAGE",tmp_path)
    calls = []
    def refused(url,path,*args):
        calls.append(url)
        path.write_bytes(b"synthetic refusal")
        raise ValueError("HTTP failure")
    monkeypatch.setattr(screen.prior.prior.source_tools,"fetch",refused)
    with pytest.raises(ValueError,match="source failed"):
        screen.collect(cfg,"a"*64)
    root = tmp_path / "source" / ("a"*12)
    manifest = screen.read_json(root / "manifest.json")
    assert len(calls) == 1 and manifest["status"] == "FAILED_SOURCE_NO_RETRY"
    assert manifest["parsed_releases"] == 0 and not (root / "releases.json").exists()
