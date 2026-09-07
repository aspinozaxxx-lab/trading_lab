"""Synthetic source-to-MTM integration; no actual market data or production activation."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_execution_bridge_v1 import TestBridge as BridgeFixture
from test_algopack_paper_journal_v1 import START

from market_lab.futures import algopack_paper_mark_refresh_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_no_actual_activation_cannot_refresh(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="Linux actual durable ledger")
class TestRefresh:
    observe = BridgeFixture.observe
    quote = BridgeFixture.quote
    reserve = BridgeFixture.reserve
    enter = BridgeFixture.enter

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        BridgeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)

    def refresh(self, refs=None):
        return core.refresh(self.bridge, {"price_flow_BR": "mark_quote"} if refs is None else refs)

    def test_cost_adjusted_mark_and_reopen(self):
        self.enter()
        result = self.refresh()
        assert result["arms"]["price_flow"]["equity_rub"] == {"1x": 999688.0, "2x": 999376.0}
        assert result["arms"]["price_only"]["equity_rub"]["1x"] == 1000000
        assert result["state"] == "OBSERVED_PORTFOLIO_NOT_DAILY_SNAPSHOT"
        reopened = core.bridge.anchors.AnchoredPortfolio(self.control, self.ledger, self.activation)
        assert reopened.snapshot() == self.account.snapshot()

    @pytest.mark.parametrize("failure", ["missing", "unavailable", "corrupt"])
    def test_old_successful_mark_is_not_carried_forward(self, monkeypatch, failure):
        self.enter()
        self.refresh()
        if failure == "unavailable":
            self.available = False
        if failure == "corrupt":

            def fail(*_):
                raise ValueError("synthetic private error text")

            monkeypatch.setattr(core.source, "observe", fail)
        result = self.refresh({} if failure == "missing" else None)
        assert result["arms"]["price_flow"]["equity_rub"] is None
        assert result["arms"]["price_flow"]["free_margin_rub"] is None
        assert result["arms"]["price_only"]["status"] == "VALUED"
        assert self.account.snapshot()["marks"] == {"price_flow_BR": None}
        assert "private error" not in str(result)

    def test_publication_delay_can_expire_quote(self, monkeypatch):
        self.enter()
        original = core.journal.publish

        def delayed(root, **kwargs):
            if root == self.ledger:
                self.at += timedelta(seconds=6)
            return original(root, **kwargs)

        monkeypatch.setattr(core.journal, "publish", delayed)
        result = self.refresh()
        assert result["arms"]["price_flow"]["status"] == "UNRESOLVED_MARK"

    def test_fresh_mark_does_not_resolve_missed_exit(self):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["exit_at"]) + timedelta(seconds=31)
        self.bridge.fill_due(position="price_flow_BR")
        result = self.refresh()
        assert result["arms"]["price_flow"]["status"] == "UNRESOLVED_POSITION"
        assert result["arms"]["price_flow"]["equity_rub"] is not None
        assert self.account.snapshot()["closed_trades"] == 0

    def test_pending_budget_preserved_and_foreign_reference_rejected(self):
        self.reserve()
        result = self.refresh({})
        assert result["arms"]["price_flow"]["free_notional_rub"] == 750000
        with pytest.raises(ValueError, match="open positions"):
            self.refresh()
