"""Synthetic dated PDF tables, missingness, signals and unchanged next-open bridge."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v113_private_demand_breadth as screen


def text(values=None, *, modern=False, month="Апр.", release="13.05.2021", header=""):
    values = dict.fromkeys(screen.LABELS, "1,0") if values is None else values
    labels = {key: choices[-1] if modern else choices[0] for key, choices in screen.LABELS.items()}
    rows = [f"{labels[key]} {values[key]} -999,0 999,0" for key in screen.LABELS]
    return (
        f"3 № 14 (50) / {release} Таблица 1. Темп роста объема входящих платежей "
        "к среднему в прошлом квартале, взвешенный по доле отраслей в ВДС, "
        f"сезонность устранена, % {header}{month} 2021 Мар. 2021 Фев. 2021 " + " ".join(rows)
    )


def parsed(values=None, **kwargs):
    return screen.parse_table(text(values, **kwargs), "2021-05-13", numeric=True)


def config():
    cfg = screen.prior.read_json(screen.CONFIG)
    cfg["protocol_id"] = "synthetic_v113"
    return cfg


@pytest.mark.parametrize("modern", [False, True])
def test_label_versions_latest_month_only_and_eod_clock(modern):
    row = parsed(modern=modern)
    assert row["values"] == dict.fromkeys(screen.LABELS, "1,0")
    assert row["source_date"] == pd.Timestamp("2021-04-30")
    assert row["available_at_utc"] == pd.Timestamp("2021-05-13T20:59:59.999999999Z")
    assert not row["original_receipt_verified"]


def test_metadata_does_not_compute_directions_or_numbers(monkeypatch):
    def forbidden(*args):
        raise AssertionError("numeric conversion before seal")

    monkeypatch.setattr(screen, "Decimal", forbidden)
    row = screen.parse_table(text(), "2021-05-13")
    assert "values" not in row and "primary_direction" not in row


@pytest.mark.parametrize("field", ["consumer", "investment", "external"])
@pytest.mark.parametrize("value", ["-1,0", "0,0", "-0,0"])
def test_all_three_strictly_positive_not_majority(field, value):
    vals = dict.fromkeys(screen.LABELS, "1,0")
    vals[field] = value
    state = screen.states([parsed(vals)])
    assert state.ready.all() and state.primary_direction.eq(0).all()
    assert state.control_direction.eq(1).all()


def test_aggregate_not_an_extra_primary_gate():
    vals = dict.fromkeys(screen.LABELS, "1,0")
    vals["aggregate"] = "-1,0"
    state = screen.states([parsed(vals)])
    assert state.primary_direction.eq(1).all() and state.control_direction.eq(0).all()


@pytest.mark.parametrize("missing", screen.MISSING)
def test_one_missing_masks_both_even_if_irrelevant_to_primary(missing):
    vals = dict.fromkeys(screen.LABELS, "1,0")
    vals["aggregate"] = missing
    state = screen.states([parsed(vals)])
    assert not state.ready.any()
    assert not state.primary_direction.any() and not state.control_direction.any()


@pytest.mark.parametrize("token", ["NaN", "inf", "1.0", "1,000", "3,13,1", "word", "", "1"])
def test_malformed_or_merged_cell_fails_closed(token):
    vals = dict.fromkeys(screen.LABELS, "1,0")
    vals["consumer"] = token
    with pytest.raises(ValueError, match="unreadable|missing/ambiguous"):
        parsed(vals)


def test_chart_legend_without_cells_is_not_another_table_row():
    sample = text() + " Конечное потребление д/x Валовое накопление (инвестиции) Экспорт"
    assert screen.parse_table(sample, "2021-05-13", numeric=True)["values"] == dict.fromkeys(
        screen.LABELS, "1,0"
    )


def test_short_lowercase_month_header_and_hyphenation():
    sample = text().replace("Апр. 2021 Мар. 2021 Фев. 2021", "апр.21 мар.21 фев.21")
    sample = sample.replace("квартале", "квар- тале").replace("весами", "ве- сами")
    assert screen.parse_table(sample, "2021-05-13")["source_date"] == pd.Timestamp("2021-04-30")


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "wrong_release",
        "wrong_month",
        "quarter_first",
        "unadjusted",
        "outgoing",
        "wrong_reference",
    ],
)
def test_table_schema_and_dates_fail_closed(kind):
    sample = text()
    if kind == "duplicate":
        sample += " Экспорт 1,0"
    elif kind == "wrong_release":
        sample = sample.replace("13.05.2021", "14.05.2021")
    elif kind == "wrong_month":
        sample = sample.replace("Апр. 2021", "Март 2021")
    elif kind == "quarter_first":
        sample = text(header="I кв. 2021 ")
    elif kind == "unadjusted":
        sample = sample.replace("сезонность устранена", "без сезонной корректировки")
    elif kind == "outgoing":
        sample = sample.replace("входящих платежей", "исходящих платежей")
    else:
        sample = sample.replace("к среднему в прошлом квартале", "к предыдущему году")
    with pytest.raises(ValueError):
        screen.parse_table(sample, "2021-05-13", numeric=True)


def test_protected_date_rejected_before_text_is_touched():
    class Forbidden:
        def split(self):
            raise AssertionError("protected content inspected")

    with pytest.raises(ValueError, match="protected release"):
        screen.parse_table(Forbidden(), "2026-01-15")


def test_impossible_negative_growth_rejected():
    vals = dict.fromkeys(screen.LABELS, "1,0")
    vals["consumer"] = "-100,1"
    with pytest.raises(ValueError, match="invalid/nonfinite"):
        screen.states([parsed(vals)])


def test_pdf_clock_later_than_release_rejected(monkeypatch, tmp_path):
    stamp = datetime(2021, 5, 14, tzinfo=ZoneInfo("Europe/Moscow"))
    reader = SimpleNamespace(
        metadata=SimpleNamespace(creation_date=stamp, modification_date=stamp),
        pages=[SimpleNamespace(extract_text=lambda: text())],
    )
    monkeypatch.setattr(screen, "PdfReader", lambda path: reader)
    with pytest.raises(ValueError, match="later than stated publication"):
        screen.pdf_record(tmp_path / "sample.pdf", {"release_date": "2021-05-13"})


def mix_active(dates):
    frame = active(dates)
    return frame.loc[frame.asset_code.eq("MIX")].copy()


def test_release_cannot_fill_same_day_and_terminal_flats():
    state = screen.states([parsed()])
    state["source_url"] = "https://example.invalid/synthetic"
    frame = mix_active(pd.bdate_range("2021-05-10", "2021-05-21"))
    signals = screen.targets(frame, state, config())
    for p in signals.values():
        assert p.loc[p.effective_date.le("2021-05-13"), "target_weight"].eq(0).all()
        assert p.loc[p.effective_date.eq("2021-05-14"), "target_weight"].eq(0.9).all()
        assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0


def test_latest_missing_publication_does_not_fall_back():
    first = parsed()
    second = parsed({**dict.fromkeys(screen.LABELS, "1,0"), "consumer": "—"})
    second.update(
        publication_date=pd.Timestamp("2021-06-17"),
        source_date=pd.Timestamp("2021-05-31"),
        available_at_utc=pd.Timestamp("2021-06-17T20:59:59.999999999Z"),
    )
    state = screen.states([first, second])
    state["source_url"] = "https://example.invalid/synthetic"
    signals = screen.targets(
        mix_active(pd.bdate_range("2021-06-15", "2021-06-25")), state, config()
    )
    for p in signals.values():
        assert p.loc[p.effective_date.ge("2021-06-18"), "feature_unavailable"].all()
        assert p.loc[p.effective_date.ge("2021-06-18"), "target_weight"].eq(0).all()


def test_stale_source_masks_both_arms():
    state = screen.states([parsed()])
    state["source_url"] = "https://example.invalid/synthetic"
    signals = screen.targets(
        mix_active(pd.bdate_range("2021-07-12", "2021-07-20")), state, config()
    )
    assert all(p.stale_at_fill.all() and p.target_weight.eq(0).all() for p in signals.values())


def test_flat_price_cash_cost_replay_unchanged_ledger(tmp_path):
    cfg = config()
    state = screen.states([parsed()])
    state["source_url"] = "https://example.invalid/synthetic"
    signals = screen.targets(mix_active(pd.bdate_range("2021-05-10", "2021-05-25")), state, cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": d,
                "asset_code": "MIX",
                "contract_id": "MIXTEST",
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
    audit = screen.prior.audit_case(tmp_path / "case", case, signals)
    assert audit["cash_cost_metric_annual_count_replays"] == 4
    for costs in case["metrics"].values():
        for m in costs.values():
            assert m["execution_complete"] and m["round_trips"] == 1
            assert m["gross_vm_pnl"] == pytest.approx(0)
            assert m["net_pnl"] == pytest.approx(-m["total_cost"])
        assert costs["double"]["net_pnl"] < costs["base"]["net_pnl"] < 0


def test_source_hash_drift_before_pdf_or_values(tmp_path, monkeypatch):
    cfg = config()
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")

    def forbidden(*args, **kwargs):
        raise AssertionError("PDF read before hash admission")

    monkeypatch.setattr(screen, "PdfReader", forbidden)
    with pytest.raises(ValueError, match="manifest drift"):
        screen.source(cfg, tmp_path)
