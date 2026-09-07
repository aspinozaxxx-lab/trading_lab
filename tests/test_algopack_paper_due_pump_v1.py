"""Synthetic due pump with actual anchored account and stubbed quote collector."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_execution_bridge_v1 import TestBridge as BridgeFixture
from test_algopack_paper_journal_v1 import START

from market_lab.futures import algopack_paper_due_pump_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


def test_exits_prioritized_over_earlier_entries():
    state = dict(
        positions={
            "entry": dict(status="PENDING", entry=None, intent=dict(entry_at=START.isoformat())),
            "exit": dict(
                status="OPEN",
                entry={},
                intent=dict(exit_at=(START + timedelta(seconds=1)).isoformat()),
            ),
            "unresolved": dict(status="UNRESOLVED", entry={}, intent={}),
        }
    )
    assert [row[2] for row in core.due_positions(state, START + timedelta(seconds=2))] == [
        "exit",
        "entry",
    ]


@pytest.mark.skipif(os.name != "posix", reason="Linux actual anchored persistence")
class TestPump:
    observe = BridgeFixture.observe
    quote = BridgeFixture.quote
    reserve = BridgeFixture.reserve
    enter = BridgeFixture.enter

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        BridgeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        self.attempts = tmp_path / "attempts"
        self.attempts.mkdir(mode=0o700)
        self.requests = 0
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.bridge.source, "collect", self.collect)

    def collect(self, *_, **__):
        self.requests += 1
        return "synthetic_quote"

    def run(self):
        return core.run(self.bridge, object(), self.attempts, token="synthetic")

    def entry_time(self):
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.bridge.source._stamp(row["intent"]["entry_at"])

    def test_not_due_makes_no_request(self):
        self.reserve()
        assert self.run()["status"] == "NOTHING_DUE"
        assert self.requests == 0

    def test_entry_exit_and_repeat_do_not_duplicate(self):
        self.reserve()
        self.entry_time()
        assert self.run()["outcomes"][0]["result"]["operation"] == "ENTRY"
        assert self.run()["status"] == "NOTHING_DUE"
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.bridge.source._stamp(row["intent"]["exit_at"])
        self.shift = 100
        assert self.run()["outcomes"][0]["result"]["operation"] == "EXIT"
        assert self.run()["status"] == "NOTHING_DUE"
        assert self.account.snapshot()["closed_trades"] == 1 and self.requests == 2

    def test_same_contract_and_due_share_one_quote_between_arms(self):
        self.reserve()
        self.bridge.reserve(
            asset="BR",
            arm="price_only",
            forecast_reference="forecast",
            quote_reference="quote",
            calendar_reference="calendar",
        )
        self.entry_time()
        result = self.run()
        assert len(result["outcomes"]) == 2 and self.requests == 1
        assert all(
            row["entry"] is not None for row in self.account.snapshot()["positions"].values()
        )

    def test_expired_entry_cancels_without_request(self):
        self.reserve()
        self.entry_time()
        self.at += timedelta(seconds=31)
        assert self.run()["outcomes"][0]["result"]["operation"] == "CANCEL"
        assert self.requests == 0

    def test_quote_failure_crossing_exit_deadline_retains_risk(self, monkeypatch):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.bridge.source._stamp(row["intent"]["exit_at"])

        def fail(*_, **__):
            self.at += timedelta(seconds=31)
            raise ValueError("synthetic private failure")

        monkeypatch.setattr(core.bridge.source, "collect", fail)
        result = self.run()["outcomes"][0]
        assert result["source_failed"] and result["result"]["operation"] == "UNRESOLVED"
        assert self.run()["status"] == "NOTHING_DUE"
        assert self.account.snapshot()["positions"]["price_flow_BR"]["entry"] is not None

    def test_uncertain_fill_stops_and_requires_reopen(self, monkeypatch):
        self.reserve()
        self.entry_time()
        original = self.bridge.fill_due

        def lost(**kwargs):
            original(**kwargs)
            raise OSError("synthetic lost acknowledgment")

        monkeypatch.setattr(self.bridge, "fill_due", lost)
        assert self.run()["status"] == "FAILED_REOPEN_REQUIRED"
        recovered = core.bridge.anchors.AnchoredPortfolio(
            self.control, self.ledger, self.activation
        )
        assert recovered.snapshot()["positions"]["price_flow_BR"]["entry"] is not None
