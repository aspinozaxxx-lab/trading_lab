"""Synthetic risk accounting and Linux restart tests, never actual market outcomes."""

import os
from dataclasses import replace
from datetime import timedelta

import pytest
from test_algopack_paper_execution_v1 import fills, fixture
from test_algopack_paper_journal_v1 import NOW, START

from market_lab.futures import algopack_paper_portfolio_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def transition(state, operation, data, at=NOW):
    event = dict(
        protocol_id=core.PROTOCOL,
        sequence=state["sequence"] + 1,
        previous_record_sha256=state["last_record_sha256"],
        at=at.isoformat(),
        operation=operation,
        data=core.wire(data),
    )
    return core.apply(state, event, durable_at=at, record_sha256=f"{state['sequence'] + 1:064x}")


def reserved():
    intent = core.execution.make_intent(**fixture())[1]
    state = transition(core.initial(START), "RESERVE", dict(intent=intent))
    return state, intent


def opened():
    state, intent = reserved()
    entry, exit_fill = fills()
    state = transition(
        state, "ENTRY", dict(position=core.position_key(intent), fill=entry), entry.observed_at
    )
    return state, entry, exit_fill


def test_pending_budgets_are_reserved_and_other_arm_is_independent():
    state, _ = reserved()
    result = core.view(state, "price_flow", NOW)
    assert result["free_notional_rub"] == 750000
    assert result["free_margin_rub"] == 300000
    assert core.view(state, "price_only", NOW)["free_notional_rub"] == 1000000


def test_four_asset_budget_cannot_be_reused():
    state, intent = reserved()
    for asset in ("MIX", "RI", "SI"):
        changed = replace(intent, asset=asset, secid=asset + "U6")
        state = transition(state, "RESERVE", dict(intent=changed))
    assert core.view(state, "price_flow", NOW)["free_notional_rub"] == 0
    assert core.view(state, "price_flow", NOW)["free_margin_rub"] == 0
    with pytest.raises(ValueError):
        transition(state, "RESERVE", dict(intent=intent))


def test_new_position_without_price_is_unknown_not_zero():
    state, entry, _ = opened()
    result = core.view(state, "price_flow", entry.observed_at)
    assert result["status"] == "UNRESOLVED_MARK" and result["equity_rub"] is None
    assert result["free_margin_rub"] is None


def test_current_liquidation_mark_includes_both_sides_costs_and_expires():
    state, entry, _ = opened()
    args = fixture()
    quote = replace(
        args["quote"],
        exchange_at=entry.observed_at,
        observed_at=entry.observed_at,
        request_started_at=entry.observed_at,
    )
    terms = replace(args["terms"], observed_at=entry.observed_at)
    state = transition(
        state,
        "MARK",
        dict(marks={"price_flow_BR": dict(quote=quote, terms=terms)}),
        entry.observed_at,
    )
    result = core.view(state, "price_flow", entry.observed_at)
    assert result["equity_rub"] == {"1x": 999688.0, "2x": 999376.0}
    assert (
        core.view(state, "price_flow", entry.observed_at + timedelta(seconds=6))["equity_rub"]
        is None
    )


def test_exit_realizes_once_and_releases_budget():
    state, entry, exit_fill = opened()
    state = transition(
        state, "EXIT", dict(position="price_flow_BR", fill=exit_fill), exit_fill.observed_at
    )
    assert state["cash"]["price_flow"] == {"1x": 1002088.0, "2x": 1001776.0}
    assert state["closed_trades"] == 1 and not state["positions"]
    with pytest.raises(ValueError):
        transition(
            state, "EXIT", dict(position="price_flow_BR", fill=exit_fill), exit_fill.observed_at
        )


def test_cancellation_releases_only_unfilled_position_and_does_not_reuse_slot():
    state, intent = reserved()
    state = transition(state, "CANCEL", dict(position="price_flow_BR", reason="NO_FILL"))
    assert not state["positions"]
    with pytest.raises(ValueError):
        transition(state, "RESERVE", dict(intent=intent))
    state, entry, _ = opened()
    with pytest.raises(ValueError):
        transition(
            state, "CANCEL", dict(position="price_flow_BR", reason="NO_FILL"), entry.observed_at
        )


def test_unresolved_and_conversion_change_keep_position():
    state, entry, exit_fill = opened()
    state = transition(
        state,
        "UNRESOLVED",
        dict(position="price_flow_BR", reason="MISSING_EXIT"),
        exit_fill.observed_at,
    )
    assert state["positions"]["price_flow_BR"]["entry"] is not None
    state = transition(
        state,
        "EXIT",
        dict(position="price_flow_BR", fill=replace(exit_fill, step_rub=2.0)),
        exit_fill.observed_at,
    )
    assert state["positions"]["price_flow_BR"]["status"] == "UNRESOLVED"
    assert state["closed_trades"] == 0 and state["cash"]["price_flow"]["1x"] == 1000000


def test_late_durable_reservation_cannot_admit_entry():
    state = core.initial(START)
    entry, _ = fills()
    event = dict(
        protocol_id=core.PROTOCOL,
        sequence=1,
        previous_record_sha256=core.ZERO,
        at=NOW.isoformat(),
        operation="RESERVE",
        data=dict(intent=core.wire(entry.intent)),
    )
    state = core.apply(state, event, durable_at=entry.intent.entry_at, record_sha256="a" * 64)
    with pytest.raises(ValueError, match="publication"):
        transition(state, "ENTRY", dict(position="price_flow_BR", fill=entry), entry.observed_at)


@pytest.mark.parametrize(
    "field,value", [("sequence", True), ("sequence", 2), ("previous_record_sha256", "b" * 64)]
)
def test_chain_corruption_is_rejected(field, value):
    state = core.initial(START)
    event = dict(
        protocol_id=core.PROTOCOL,
        sequence=1,
        previous_record_sha256=core.ZERO,
        at=NOW.isoformat(),
        operation="MARK",
        data=dict(marks={}),
    )
    event[field] = value
    with pytest.raises(ValueError):
        core.apply(state, event, durable_at=NOW, record_sha256="a" * 64)


@pytest.mark.skipif(os.name != "posix", reason="Linux portfolio persistence")
class TestDurable:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.root = tmp_path / "portfolio"
        self.root.mkdir(mode=0o700)
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        monkeypatch.setattr(core, "_ready", lambda _: None)  # Explicit synthetic activation.
        monkeypatch.setattr(core.journal, "now", lambda: NOW)

    def test_restart_replays_reservations_and_rejects_bad_tail(self):
        intent = core.execution.make_intent(**fixture())[1]
        state, ref = core.append(
            self.root, self.activation, operation="RESERVE", data=dict(intent=intent)
        )
        assert core.recover(self.root, self.activation) == state
        assert (
            core.recover(
                self.root,
                self.activation,
                expected_tail=dict(sequence=1, record_sha256=ref["record_sha256"]),
            )
            == state
        )
        for tail in (
            dict(sequence=1, record_sha256="c" * 64),
            dict(sequence=2, record_sha256="c" * 64),
        ):
            with pytest.raises(ValueError):
                core.recover(self.root, self.activation, expected_tail=tail)

    def test_partial_event_is_not_skipped_or_overwritten(self):
        parent = self.root / "source"
        parent.mkdir(mode=0o700)
        (parent / "portfolio_00000001").mkdir(mode=0o700)
        with pytest.raises(FileNotFoundError):
            core.recover(self.root, self.activation)
        with pytest.raises(FileNotFoundError):
            core.append(self.root, self.activation, operation="MARK", data=dict(marks={}))
        assert list(parent.iterdir()) == [parent / "portfolio_00000001"]
