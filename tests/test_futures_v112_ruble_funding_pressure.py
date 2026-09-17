"""Synthetic same-date funding inputs, conservative clocks, masks and cash ledger."""

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v112_ruble_funding_pressure as screen


def config():
    cfg = screen.prior.read_json(screen.CONFIG)
    cfg["source"]["expected_raw_rows"] = 3
    cfg["monetary"].update(ruonia_rows=3, key_rate_rows=3)
    return cfg


def table(rows, headers):
    return (
        "<table class='data'><tr>"
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr>"
        + "".join("<tr>" + "".join(f"<td>{x}</td>" for x in row) + "</tr>" for row in rows)
        + "</table>"
    ).encode()


def fixture(deficits=None, ruonia=None, key=None):
    deficits = ["1", "1", "1"] if deficits is None else deficits
    ruonia = ["5,1", "5,1", "5,1"] if ruonia is None else ruonia
    key = ["5", "5", "5"] if key is None else key
    stock, overnight, policy = [], [], []
    for i, day in enumerate(pd.date_range("2020-03-02", periods=3)):
        stock.append([day.strftime("%d.%m.%Y"), "UNUSED_HEADLINE", deficits[i]] + ["UNUSED"] * 12)
        overnight.append(
            [day.strftime("%d.%m.%Y"), ruonia[i]]
            + ["UNUSED"] * 8
            + [(day + pd.Timedelta(days=1)).strftime("%d.%m.%Y")]
        )
        policy.append(f"<KR><DT>{day.date()}T00:00:00+03:00</DT><Rate>{key[i]}</Rate></KR>")
    bank = table(stock[::-1], ["Дата", "С учетом корсчетов", "без учета корсчетов"])
    money = {
        "ruonia": table(overnight[::-1], ["Дата", "RUONIA"]),
        "key_rate": ("<Data>" + "".join(policy) + "</Data>").encode(),
    }
    return bank, money


def states(**kwargs):
    bank, money = fixture(**kwargs)
    return screen.states(screen.records(bank, money, config(), numeric=True))


def test_metadata_never_converts_selected_values(monkeypatch):
    def fail(*_):
        raise AssertionError("numeric source inspection before seal")

    monkeypatch.setattr(screen, "number", fail)
    bank, money = fixture(deficits=["BAD"] * 3, ruonia=["BAD"] * 3, key=["BAD"] * 3)
    rows = screen.records(bank, money, config())
    assert len(rows) == 3 and all(r["date_matched"] for r in rows)
    assert all("ruonia" not in r and "deficit" not in r for r in rows)


@pytest.mark.parametrize(
    "deficit,rate,direction,control",
    [
        ("1", "5,1", -1, -1),
        ("0", "5,1", 0, -1),
        ("-1", "5,1", 0, -1),
        ("1", "5", 0, 0),
        ("1", "4,9", 0, 0),
        ("0,00000001", "5,00000001", -1, -1),
    ],
)
def test_exact_joint_boundary(deficit, rate, direction, control):
    s = states(deficits=[deficit] * 3, ruonia=[rate] * 3)
    assert s.ready.all() and s.primary_direction.eq(direction).all()
    assert s.control_direction.eq(control).all()


def test_same_observation_date_key_rate_not_future_policy_level():
    s = states(key=["5", "10", "10"])
    assert s.primary_direction.tolist() == [-1, 0, 0]
    assert s.key_rate.tolist() == ["5", "10", "10"]
    assert s.available_at_utc.iloc[0] == pd.Timestamp("2020-03-03T21:00:00Z")
    assert s.liquidity_proxy_available_at_utc.iloc[0] == pd.Timestamp("2020-03-03T20:59:59Z")


@pytest.mark.parametrize("field", ["deficits", "ruonia", "key"])
@pytest.mark.parametrize("missing", ["", "-", "—"])
def test_latest_missing_cell_masks_both_arms_no_older_good_fallback(field, missing):
    values = {"deficits": ["1", "1", "1"], "ruonia": ["5,1"] * 3, "key": ["5"] * 3}
    values[field][1] = missing
    s = states(**values)
    assert s.ready.tolist() == [True, False, True]
    signals = screen.targets(active(pd.bdate_range("2020-03-03", "2020-03-10")), s, config())
    for t in signals.values():
        at = t.loc[t.effective_date.eq("2020-03-06")].iloc[0]
        assert at.feature_unavailable and at.target_weight == 0


def test_exact_date_missing_stock_masks_published_rate():
    cfg = config()
    bank, money = fixture()
    bank = bank.replace(b"03.03.2020", b"01.03.2020")
    s = screen.states(screen.records(bank, money, cfg, numeric=True))
    assert s.date_matched.tolist() == [True, False, True]
    assert not s.ready.iloc[1] and s.control_direction.iloc[1] == 0


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e-9", "--1", "abc"])
def test_malformed_selected_values_fail_closed(bad):
    with pytest.raises(ValueError, match="malformed selected number"):
        states(deficits=[bad] * 3)


@pytest.mark.parametrize(
    "kind", ["duplicate", "short_row", "swapped_header", "bad_date", "missing"]
)
def test_stock_calendar_and_schema_fail_closed(kind):
    bank, money = fixture()
    if kind == "duplicate":
        bank = bank.replace(b"03.03.2020", b"02.03.2020")
    elif kind == "short_row":
        bank = bank.replace(b"<td>UNUSED</td>", b"", 1)
    elif kind == "swapped_header":
        bank = bank.replace("без учета корсчетов".encode(), b"WRONG_COLUMN")
    elif kind == "bad_date":
        bank = bank.replace(b"03.03.2020", b"31.02.2020")
    else:
        bank = bank.replace(b"03.03.2020", b"not_a_date")
    with pytest.raises(ValueError):
        screen.records(bank, money, config(), numeric=True)


def test_protected_availability_cells_not_interpreted():
    bank, money = fixture()
    cfg = config()
    cfg["source"]["expected_raw_rows"] = 4
    stock_row = (
        "<tr><td>31.12.2025</td><td>UNUSED</td><td>POISON</td>" + "<td>UNUSED</td>" * 12 + "</tr>"
    ).encode()
    bank = bank.replace(b"</table>", stock_row + b"</table>")
    rrow = (
        "<tr><td>30.12.2025</td><td>POISON</td>"
        + "<td>UNUSED</td>" * 8
        + "<td>31.12.2025</td></tr>"
    ).encode()
    money["ruonia"] = money["ruonia"].replace(b"</table>", rrow + b"</table>")
    money["key_rate"] = money["key_rate"].replace(
        b"</Data>", b"<KR><DT>2025-12-31T00:00:00+03:00</DT><Rate>POISON</Rate></KR></Data>"
    )
    assert len(screen.records(bank, money, cfg, numeric=True)) == 3


def test_later_value_change_cannot_change_prior_states():
    original = states()
    changed = states(deficits=["1", "1", "-1"])
    pd.testing.assert_frame_equal(original.iloc[:-1], changed.iloc[:-1])


def test_delayed_publication_changes_clock_not_observation_key():
    bank, money = fixture()
    money["ruonia"] = money["ruonia"].replace(b"<td>05.03.2020</td>", b"<td>09.03.2020</td>")
    s = screen.states(screen.records(bank, money, config(), numeric=True))
    assert s.source_date.iloc[-1] == pd.Timestamp("2020-03-04")
    assert s.available_at_utc.iloc[-1] == pd.Timestamp("2020-03-09T21:00:00Z")


def test_next_actual_open_source_ttl_plan_masks_and_terminal():
    cfg, s = config(), states()
    t = screen.targets(active(pd.bdate_range("2020-03-02", "2020-03-10")), s, cfg)["primary"]
    assert t.loc[t.effective_date.eq("2020-03-04"), "target_weight"].iloc[0] == 0
    assert t.loc[t.effective_date.eq("2020-03-05"), "target_weight"].iloc[0] == -0.9
    assert t.iloc[-1].terminal_flat and t.iloc[-1].target_weight == 0
    missing = screen.targets(active().assign(plan_tradable=False), s, cfg)
    assert all(t.target_weight.eq(0).all() for t in missing.values())
    stale = screen.targets(active(pd.bdate_range("2020-03-16", "2020-03-24")), s, cfg)
    assert all(t.stale_at_fill.all() and t.target_weight.eq(0).all() for t in stale.values())


def test_flat_market_fees_and_cash_replay(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2020-03-02", "2020-03-10")), states(), cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": d,
                "asset_code": "SI",
                "contract_id": "SITEST",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "settle": 100.0,
                "volume": 1e7,
                "sizing_point_value": 100.0,
                "accounting_point_value": 100.0,
                "tick_size": 0.01,
                "fee_per_contract": 1.0,
                "initial_margin": 1000.0,
            }
            for d in signals["primary"].effective_date
        ]
    )
    case = screen.engine.simulate_case(
        tmp_path / "case", signals, market, {"ready_asset_date_fraction": 1.0}, cfg, "synthetic"
    )
    assert (
        screen.prior.audit_case(tmp_path / "case", case, signals)[
            "cash_cost_metric_annual_count_replays"
        ]
        == 4
    )
    for costs in case["metrics"].values():
        for m in costs.values():
            assert m["execution_complete"] and m["round_trips"] == 1
            assert m["gross_vm_pnl"] == pytest.approx(0)
            assert m["net_pnl"] == pytest.approx(-m["total_cost"])
        assert costs["double"]["net_pnl"] < costs["base"]["net_pnl"] < 0


def test_source_manifest_drift_before_read(tmp_path):
    cfg = config()
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="source manifest drift"):
        screen.source(cfg, tmp_path)
