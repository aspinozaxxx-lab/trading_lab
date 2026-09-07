"""Pure synthetic economics, never historical AlgoPack outcomes or real execution."""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from test_algopack_paper_journal_v1 import END, NOW, START, candidate

from market_lab.futures import algopack_paper_execution_v1 as core


def fixture():
    value = candidate()
    for row in value["assets"]:
        row["secid"] = row["asset"] + "U6"
    for arm in value["arms"].values():
        arm["prediction"] = [0.01] * 4
    return dict(
        consumed=dict(
            payload=value,
            state="OBSERVED_NOT_EXECUTION_ADMITTED",
            kind="forecast",
            key=core.journal.forecast_key(value),
            record_sha256="a" * 64,
            durable_payload_at=NOW.isoformat(),
            observed_at=NOW.isoformat(),
            execution_admitted=False,
        ),
        asset="BR",
        arm="price_flow",
        equity_rub=1_000_000.0,
        free_margin_rub=1_000_000.0,
        open_assets=(),
        unresolved_positions=False,
        at=NOW,
        quote=core.Quote("BR", "BRU6", 10000.0, 10001.0, 1000, 1000, NOW, NOW, NOW, "b" * 64, True),
        terms=core.Terms("BR", "BRU6", 1.0, 1.0, 1000.0, 2.0, date(2026, 9, 17), NOW, "c" * 64),
        session=core.Session(END - timedelta(hours=1), END + timedelta(hours=3), NOW, "d" * 64),
    )


def fills(short=False):
    args = fixture()
    if short:
        args["consumed"]["payload"]["arms"]["price_flow"]["prediction"] = [-0.01] * 4
    state, intent = core.make_intent(**args)
    assert state == "PAPER_INTENT_NOT_PERSISTED"
    result = []
    for is_exit, due in ((False, intent.entry_at), (True, intent.exit_at)):
        shift = (-100 if short else 100) if is_exit else 0
        quote = replace(
            args["quote"],
            bid=10000.0 + shift,
            ask=10001.0 + shift,
            exchange_at=due,
            request_started_at=due,
            observed_at=due,
        )
        state, fill = core.simulate_fill(
            intent,
            is_exit=is_exit,
            quote=quote,
            terms=replace(args["terms"], observed_at=due),
            intent_durable_at=NOW,
            at=due,
            future_start=START,
        )
        assert state == "SIMULATED_FILL_NOT_PERSISTED"
        result.append(fill)
    return result


@pytest.mark.parametrize("short", [False, True])
def test_two_sided_crossing_costs_and_stress_use_same_trades(short):
    entry, exit_fill = fills(short)
    result = core.close_trade(entry, exit_fill)
    assert entry.intent.quantity == 24
    assert result["gross_mid_rub"] == 2400.0
    assert result["crossing_slippage_rub"] == 72.0
    assert result["fees_rub"] == 240.0
    assert result["net_rub"] == {"1x": 2088.0, "2x": 1776.0}
    assert result["real_broker_fee_verified"] is result["execution_admitted"] is False


@pytest.mark.parametrize(
    "case,status",
    [
        ("open", "POSITION_ALREADY_OPEN"),
        ("unresolved", "UNRESOLVED_POSITION_BLOCK"),
        ("weak", "EDGE_BELOW_COST_BUFFER"),
        ("outlier", "OUTLIER_FORECAST"),
        ("thin", "INSUFFICIENT_BUDGET_OR_DEPTH"),
        ("margin", "INSUFFICIENT_BUDGET_OR_DEPTH"),
        ("calendar", "NO_UNINTERRUPTED_SESSION"),
        ("date", "UNVERIFIED_QUOTE_DATE"),
        ("stale", "STALE_QUOTE"),
        ("fees", "UNKNOWN_EXCHANGE_FEE"),
        ("old_terms", "STALE_CONTRACT_TERMS"),
        ("expired", "UNRESOLVED_TERMS_DATE"),
        ("late", "MISSED_INTENT_DEADLINE"),
        ("future", "INVALID_QUOTE_CLOCK"),
        ("tick", "OFF_TICK_QUOTE"),
    ],
)
def test_explicit_entry_sleep_reasons(case, status):
    args = fixture()
    if case == "open":
        args["open_assets"] = ("BR",)
    elif case == "unresolved":
        args["unresolved_positions"] = True
    elif case in ("weak", "outlier"):
        args["consumed"]["payload"]["arms"]["price_flow"]["prediction"] = [
            0.0 if case == "weak" else 0.3
        ] * 4
    elif case == "thin":
        args["quote"] = replace(args["quote"], ask_quantity=9)
    elif case == "margin":
        args["free_margin_rub"] = 999.0
    elif case == "calendar":
        args["session"] = replace(args["session"], end=END + timedelta(minutes=70))
    elif case == "date":
        args["quote"] = replace(args["quote"], exchange_date_verified=False)
    elif case == "stale":
        args["quote"] = replace(args["quote"], exchange_at=NOW - timedelta(seconds=6))
    elif case == "fees":
        args["terms"] = replace(args["terms"], exchange_fee_rub=None)
    elif case == "old_terms":
        args["terms"] = replace(args["terms"], observed_at=NOW - timedelta(seconds=31))
    elif case == "expired":
        args["terms"] = replace(args["terms"], expiration_day=date(2026, 9, 8))
    elif case == "late":
        args["at"] = END + timedelta(minutes=10)
    elif case == "future":
        args["quote"] = replace(args["quote"], exchange_at=NOW + timedelta(seconds=1))
    elif case == "tick":
        args["quote"] = replace(args["quote"], bid=10000.5)
    assert core.make_intent(**args) == (status, None)


def test_profit_does_not_raise_fixed_capital_budget():
    args = fixture()
    args["equity_rub"] = 2_000_000.0
    assert core.make_intent(**args)[1].notional_budget_rub == 250_000.0
    args["equity_rub"] = 500_000.0
    assert core.make_intent(**args)[1].notional_budget_rub == 125_000.0


@pytest.mark.parametrize(
    "case,status",
    [
        ("old", "PRE_INTENT_OR_PRE_BOUNDARY_QUOTE"),
        ("thin", "INSUFFICIENT_FOK_DEPTH"),
        ("margin", "BUDGET_CHANGED_BEFORE_ENTRY"),
        ("late", "MISSED_ENTRY_WINDOW"),
    ],
)
def test_new_quote_required_after_intent_and_entry_boundary(case, status):
    args = fixture()
    intent = core.make_intent(**args)[1]
    due = intent.entry_at
    quote = replace(args["quote"], exchange_at=due, observed_at=due, request_started_at=due)
    terms = replace(args["terms"], observed_at=due)
    if case == "old":
        quote = replace(quote, request_started_at=NOW)
    elif case == "thin":
        quote = replace(quote, ask_quantity=10)
    elif case == "margin":
        terms = replace(terms, margin_rub=10000.0)
    elif case == "late":
        due += timedelta(seconds=31)
    assert core.simulate_fill(
        intent,
        is_exit=False,
        quote=quote,
        terms=terms,
        intent_durable_at=NOW,
        at=due,
        future_start=START,
    ) == (status, None)


def test_missing_exit_stays_unresolved_and_does_not_create_zero_return():
    args = fixture()
    intent = core.make_intent(**args)[1]
    assert core.simulate_fill(
        intent,
        is_exit=True,
        quote=args["quote"],
        terms=args["terms"],
        intent_durable_at=NOW,
        at=intent.exit_at + timedelta(seconds=31),
        future_start=START,
    ) == ("EXIT_UNRESOLVED", None)


def test_conversion_change_is_not_silently_priced_with_entry_multiplier():
    entry, exit_fill = fills()
    result = core.close_trade(entry, replace(exit_fill, step_rub=2.0))
    assert result["status"] == "UNRESOLVED_CONVERSION_CHANGE" and result["net_rub"] is None


def test_unknown_fee_not_zero_and_zero_fee_is_allowed():
    args = fixture()
    args["terms"] = replace(args["terms"], exchange_fee_rub=0.0)
    assert core.make_intent(**args)[0] == "PAPER_INTENT_NOT_PERSISTED"


def test_corrupt_consumer_clock_and_intent_identity_fail():
    args = fixture()
    args["consumed"]["durable_payload_at"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="chronology"):
        core.make_intent(**args)
    intent = core.make_intent(**fixture())[1]
    with pytest.raises(ValueError):
        replace(intent, quantity=True)
    with pytest.raises(ValueError):
        replace(intent, forecast_sha256="bad")


def test_adverse_price_move_remains_a_loss():
    entry, exit_fill = fills()
    adverse = replace(exit_fill, reference_mid=9900.5, price=9899.0)
    result = core.close_trade(entry, adverse)
    assert result["net_rub"] == {"1x": -2712.0, "2x": -3024.0}


def test_persisting_intent_at_entry_boundary_is_too_late():
    args = fixture()
    intent = core.make_intent(**args)[1]
    with pytest.raises(ValueError, match="persisted intent"):
        core.simulate_fill(
            intent,
            is_exit=False,
            quote=args["quote"],
            terms=args["terms"],
            intent_durable_at=intent.entry_at,
            at=intent.entry_at,
            future_start=START,
        )
