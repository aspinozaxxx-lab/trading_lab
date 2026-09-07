"""Synthetic bridge integration with real Linux ledger and stubbed source observations."""

import os
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_algopack_paper_execution_v1 import fixture
from test_algopack_paper_journal_v1 import NOW, START

from market_lab.futures import algopack_paper_execution_bridge_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_bridge_requires_production_activation(tmp_path):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ExecutionBridge(SimpleNamespace(activation=activation), tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="real Linux anchored ledger")
class TestBridge:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.control, self.ledger, self.market = [
            tmp_path / name for name in ("control", "ledger", "market")
        ]
        for root in (self.control, self.ledger, self.market):
            root.mkdir(mode=0o700)
        self.at, self.shift, self.available = NOW, 0, True
        self.args = fixture()
        for module, name in (
            (core, "ready"),
            (core.anchors, "ready"),
            (core.anchors.cached, "ready"),
            (core.portfolio, "_ready"),
        ):
            monkeypatch.setattr(module, name, lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.journal, "consume_forecast", lambda *_: self.args["consumed"])
        monkeypatch.setattr(core.source, "observe", self.observe)
        monkeypatch.setattr(core.source, "quote_inputs", self.quote)
        monkeypatch.setattr(core.source, "session_input", lambda *_, **__: self.args["session"])
        core.anchors.initialize(self.control, self.ledger, self.activation)
        self.account = core.anchors.AnchoredPortfolio(self.control, self.ledger, self.activation)
        self.bridge = core.ExecutionBridge(self.account, self.market)

    def observe(self, root, reference, activation):
        assert root == self.market and activation == self.activation
        return dict(
            source_observation=dict(
                kind="source",
                key=reference,
                record_sha256="b" * 64,
                observed_at=self.at.isoformat(),
            )
        )

    def quote(self, _):
        if not self.available:
            return None
        quote = replace(
            self.args["quote"],
            bid=10000 + self.shift,
            ask=10001 + self.shift,
            exchange_at=self.at,
            request_started_at=self.at,
            observed_at=self.at,
        )
        return quote, replace(self.args["terms"], observed_at=self.at)

    def reserve(self):
        return self.bridge.reserve(
            asset="BR",
            arm="price_flow",
            forecast_reference="forecast",
            quote_reference="quote",
            calendar_reference="calendar",
        )

    def enter(self):
        self.reserve()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["entry_at"])
        return self.bridge.fill_due(position="price_flow_BR", quote_reference="entry_quote")

    def test_roundtrip_sources_commands_and_restart(self):
        assert self.enter()["operation"] == "ENTRY"
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["exit_at"])
        self.shift = 100
        assert (
            self.bridge.fill_due(position="price_flow_BR", quote_reference="exit_quote")[
                "operation"
            ]
            == "EXIT"
        )
        state = self.account.snapshot()
        assert state["cash"]["price_flow"] == {"1x": 1002088.0, "2x": 1001776.0}
        assert (
            core.anchors.AnchoredPortfolio(self.control, self.ledger, self.activation).snapshot()
            == state
        )
        event = core.anchors.read_event(self.ledger, "portfolio_00000003", self.activation)
        evidence = event["payload"]["data"]["execution_evidence"]
        assert evidence["observations"][0]["key"] == "exit_quote"
        assert evidence["execution_admitted"] is False

    def test_missing_quote_cannot_reserve_capital(self):
        self.available = False
        assert self.reserve()["status"] == "UNAVAILABLE_QUOTE"
        assert self.account.snapshot()["sequence"] == 0

    def test_missing_or_early_entry_does_not_invent_fill(self):
        self.reserve()
        assert self.bridge.fill_due(position="price_flow_BR")["status"] == "NOT_DUE"
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["entry_at"])
        assert (
            self.bridge.fill_due(position="price_flow_BR")["status"]
            == "AWAITING_POST_BOUNDARY_QUOTE"
        )
        assert self.account.snapshot()["sequence"] == 1

    def test_missed_entry_releases_reservation_not_seen_slot(self):
        self.reserve()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["entry_at"]) + timedelta(seconds=31)
        assert self.bridge.fill_due(position="price_flow_BR")["operation"] == "CANCEL"
        state = self.account.snapshot()
        assert not state["positions"] and len(state["seen"]) == 1
        assert state["cash"]["price_flow"]["1x"] == 1000000

    def test_missed_exit_retains_position_and_is_idempotent(self):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["exit_at"]) + timedelta(seconds=31)
        assert self.bridge.fill_due(position="price_flow_BR")["operation"] == "UNRESOLVED"
        state = self.account.snapshot()
        assert state["positions"]["price_flow_BR"]["entry"] is not None
        assert (
            self.bridge.fill_due(position="price_flow_BR")["status"]
            == "UNRESOLVED_POSITION_RETAINED"
        )
        assert self.account.snapshot() == state

    def test_source_failure_does_not_create_operation(self, monkeypatch):
        def fail(*_):
            raise ValueError("synthetic source integrity failure")

        monkeypatch.setattr(core.source, "observe", fail)
        with pytest.raises(ValueError, match="integrity"):
            self.reserve()
        assert self.account.snapshot()["sequence"] == 0

    def test_no_caller_supplied_fill_or_clock(self):
        with pytest.raises(TypeError):
            self.bridge.fill_due(position="price_flow_BR", fill={}, at=NOW)
