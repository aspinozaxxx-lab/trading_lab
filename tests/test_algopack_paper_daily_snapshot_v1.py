"""Synthetic daily snapshots from real Linux anchored events; no market outcomes."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_execution_bridge_v1 import TestBridge as BridgeFixture
from test_algopack_paper_journal_v1 import END, START

from market_lab.futures import algopack_paper_daily_snapshot_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_production_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="actual Linux durable journal")
class TestDaily:
    observe = BridgeFixture.observe
    quote = BridgeFixture.quote
    reserve = BridgeFixture.reserve
    enter = BridgeFixture.enter

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        BridgeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        for module in (core, core.coverage, core.marks):
            monkeypatch.setattr(module, "ready", lambda _: None)
        self.reports = tmp_path / "reports"
        self.reports.mkdir(mode=0o700)

    def publish(self):
        self.at = core.window(END.date())
        return core.publish(self.bridge, self.reports, END.date(), {})

    def read(self, result):
        return core.observe(self.reports, self.activation, result["reference"])

    def test_empty_portfolio_keeps_full_missing_denominator(self):
        row = self.read(self.publish())
        for arm in row["arms"].values():
            assert arm["counts"]["missing"] == 168
            assert arm["counts"]["entries"] == arm["counts"]["closed"] == 0
            assert arm["equity_rub"]["1x"] == 1000000

    def test_roundtrip_counts_and_equity_are_replayed(self):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.bridge.source._stamp(row["intent"]["exit_at"])
        self.shift = 100
        self.bridge.fill_due(position="price_flow_BR", quote_reference="exit_quote")
        result = self.publish()
        self.at += timedelta(days=1)
        snapshot = self.read(result)
        arm = snapshot["arms"]["price_flow"]
        assert arm["counts"]["entries"] == arm["counts"]["closed"] == 1
        assert arm["equity_rub"] == {"1x": 1002088.0, "2x": 1001776.0}
        assert snapshot["observed_at"] == core.window(END.date()).isoformat()

    def test_unknown_open_position_not_zero_equity(self):
        self.enter()
        arm = self.read(self.publish())["arms"]["price_flow"]
        assert arm["counts"]["open_positions"] == 1
        assert arm["equity_rub"] is None and arm["status"] == "UNRESOLVED_MARK"

    @pytest.mark.parametrize("offset", [-1, 31])
    def test_outside_window_does_not_write(self, offset):
        self.at = core.window(END.date()) + timedelta(seconds=offset)
        with pytest.raises(ValueError, match="window"):
            core.publish(self.bridge, self.reports, END.date(), {})
        assert self.account.snapshot()["sequence"] == 0

    def test_late_publication_is_retained_but_not_evaluable(self, monkeypatch):
        original = core.journal.publish

        def delay(root, **kwargs):
            if root == self.reports:
                self.at += timedelta(seconds=31)
            return original(root, **kwargs)

        monkeypatch.setattr(core.journal, "publish", delay)
        result = self.publish()
        assert result["status"] == "RECORDED_LATE_NOT_EVALUABLE"
        with pytest.raises(ValueError, match="window"):
            self.read(result)
