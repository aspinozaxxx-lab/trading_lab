"""Synthetic quarterly identities, publication clocks, decimal rule and ledger checks."""

import copy

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v107_current_account as screen


def config():
    return screen.prior.read_json(screen.CONFIG)


def si_active(dates):
    frame = active(dates)
    return frame.loc[frame.asset_code.eq("SI")].assign(contract_id="SITEST")


def table(q="2021Q1", three=False, current="20,1", previous="10,1"):
    quarter = pd.Period(q)
    years = list(range(quarter.year - (2 if three else 1), quarter.year + 1))
    headers, values = [], []
    for year in years:
        for n in range(1, (4 if year < quarter.year else quarter.quarter) + 1):
            headers.append(list(screen.QUARTERS)[n - 1])
            values.append(
                current
                if year == quarter.year and n == quarter.quarter
                else previous
                if year == quarter.year - 1 and n == quarter.quarter
                else "2,0"
            )
        if year < quarter.year or quarter.quarter == 4:
            headers.append("Год")
            values.append("9999,0")
    return (
        "ПЛАТЕЖНЫЙ БАЛАНС РОССИИ*\n(МЛРД ДОЛЛ. США)\n"
        + " ".join(map(str, years))
        + "\n"
        + " ".join(headers)
        + "\n"
        + "Счет текущих операций "
        + " ".join(values)
        + "\nТорговый баланс 1,0\n"
    )


def row(current="20.1", previous="10.1", published="2021-04-15", quarter="2021Q1"):
    return {
        "quarter": quarter,
        "publication_date": published,
        "current_account_usd_bn": current,
        "prior_year_same_quarter_usd_bn": previous,
        "source_url": "https://cbr.ru/synthetic",
        "raw_sha256": "a" * 64,
    }


@pytest.mark.parametrize("q,three", [("2021Q1", False), ("2021Q4", False), ("2025Q3", True)])
def test_exact_quarter_headers_not_annual_or_rounded_text(q, three):
    value = screen.parse_table(table(q, three), q)
    assert value == {"current_account_usd_bn": "20.1", "prior_year_same_quarter_usd_bn": "10.1"}


@pytest.mark.parametrize(
    "current,previous,direction",
    [
        ("20.1", "10.1", -1),
        ("10.1", "10.1", 0),
        ("0", "-2", 0),
        ("-1", "-2", 0),
        ("10", "11", 0),
        ("0.1000000000000000001", "0.1", -1),
    ],
)
def test_frozen_decimal_rule_and_constant_short_control(current, previous, direction):
    state = screen.states([row(current, previous)]).iloc[0]
    assert state.primary_direction == direction and state.control_direction == -1
    assert state.available_at_utc == pd.Timestamp("2021-04-15T20:59:59Z")


@pytest.mark.parametrize("mutation", ["unit", "year", "quarter", "missing", "annual", "duplicate"])
def test_ambiguous_table_rejected(mutation):
    text = table()
    if mutation == "unit":
        text = text.replace("МЛРД", "МЛН")
    elif mutation == "year":
        text = text.replace("2020 2021", "2019 2021")
    elif mutation == "quarter":
        text = text.replace("IV Год", "III Год")
    elif mutation == "missing":
        text = text.replace("20,1", "-")
    elif mutation == "annual":
        text = text.replace("Год I", "Год Год")
    else:
        text += text
    with pytest.raises(ValueError):
        screen.parse_table(text, "2021Q1")


def inventory():
    rows = []
    for q in pd.period_range("2020Q3", "2025Q3", freq="Q"):
        if str(q) == "2022Q1":
            continue
        day = q.end_time.normalize() + pd.Timedelta(days=20)
        published = f"{day.day} {list(screen.MONTHS)[day.month - 1]} {day.year}"
        rows.append(
            f'<a class="versions_item" href="/Collection/Collection/File/{q.ordinal}/'
            f'Balance_of_Payments_{q.year}-{q.quarter}.pdf" '
            f'data-tooltip-content="Опубликовано {published}">'
            f"№ 1 • {list(screen.QUARTERS)[q.quarter - 1]} квартал {q.year} г.</a>"
        )
    return "".join(rows)


def test_inventory_uses_publication_tooltip_and_ignores_later_quarters():
    raw = inventory()
    selected = screen.select(raw.encode(), config())
    assert len(selected) == 20 and selected[0]["publication_date"] == "2020-10-20"
    assert "2022Q1" not in {r["quarter"] for r in selected}
    extra = (
        '<a class="versions_item" href="/Collection/Collection/File/999/'
        'Balance_of_Payments_2025-4.pdf" data-tooltip-content="bad">'
        "№ 1 • IV квартал 2025 г.</a>"
    )
    assert screen.select((raw + extra).encode(), config()) == selected


@pytest.mark.parametrize("mutation", ["tooltip", "future", "duplicate", "missing"])
def test_inventory_failure_before_any_pdf_read(mutation):
    raw = inventory()
    if mutation == "tooltip":
        raw = raw.replace("Опубликовано", "Подготовлено", 1)
    elif mutation == "future":
        raw = raw.replace("20 октября 2025", "20 января 2026")
    elif mutation == "duplicate":
        raw += raw
    else:
        raw = raw[raw.index("</a>") + 4 :]
    with pytest.raises(ValueError):
        screen.select(raw.encode(), config())


def test_future_pdf_rejected_before_reader(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("reader must not run")

    monkeypatch.setattr(screen.pypdf, "PdfReader", fail)
    with pytest.raises(ValueError, match="protected"):
        screen.parse_pdf(b"not read", {"publication_date": "2026-01-01", "quarter": "2025Q4"})


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_invalid_values_not_zeros(bad):
    with pytest.raises(ValueError, match="nonfinite"):
        screen.states([row(bad)])


def test_clock_next_open_staleness_missing_plan_terminal_and_future_invariance():
    cfg = config()
    state = screen.states([row()])
    plan = si_active(pd.bdate_range("2021-04-14", "2021-04-23"))
    p = screen.targets(plan, state, cfg)["primary"]
    assert p.loc[p.effective_date.eq("2021-04-15"), "target_weight"].iloc[0] == 0
    assert p.loc[p.effective_date.eq("2021-04-16"), "target_weight"].iloc[0] == -0.9
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0
    added = screen.states([row(), row("1", "2", "2021-07-15", "2021Q2")])
    later = screen.targets(plan, added, cfg)["primary"]
    pd.testing.assert_series_equal(p.target_weight, later.target_weight)
    late_plan = si_active(pd.bdate_range("2021-09-01", "2021-09-08"))
    late = screen.targets(late_plan, state, cfg)["primary"]
    assert late.stale_at_fill.all() and late.target_weight.eq(0).all()
    absent = screen.targets(plan.assign(plan_tradable=False), state, cfg)["primary"]
    assert absent.source_unavailable.all() and absent.target_weight.eq(0).all()
    with pytest.raises(ValueError):
        screen.states([row(), copy.deepcopy(row())])


def test_existing_integer_short_ledger_flat_price_and_cash_tampering(tmp_path):
    cfg = config()
    state = screen.states([row()])
    plan = si_active(pd.bdate_range("2021-04-16", "2021-05-03"))
    signals = screen.targets(plan, state, cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": day,
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
            for day in signals["primary"].effective_date
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
        for metric in costs.values():
            assert metric["execution_complete"] and metric["round_trips"] == 1
            assert metric["gross_vm_pnl"] == pytest.approx(0)
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert costs["double"]["net_pnl"] < costs["base"]["net_pnl"] < 0
    file = tmp_path / "case/ledger_primary_base.parquet"
    ledger = pd.read_parquet(file)
    ledger.loc[1, "starting_cash"] += 100
    ledger.to_parquet(file, index=False)
    with pytest.raises(ValueError, match="cash continuity"):
        screen.prior.audit_case(tmp_path / "case", case, signals)
