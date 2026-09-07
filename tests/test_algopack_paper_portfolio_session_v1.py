"""Synthetic Linux cached-state/restart tests; no production activation or market values."""

import os

import pytest
from test_algopack_paper_execution_v1 import fixture
from test_algopack_paper_journal_v1 import NOW, START

from market_lab.futures import algopack_paper_portfolio_session_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_no_actual_activation_no_session(tmp_path):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    with pytest.raises((FileNotFoundError, ValueError)):
        core.PortfolioSession(
            tmp_path, activation, expected_tail=dict(sequence=0, record_sha256=core.portfolio.ZERO)
        )


@pytest.mark.skipif(os.name != "posix", reason="Linux portfolio locks/durability")
class TestSession:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.root = tmp_path / "ledger"
        self.root.mkdir(mode=0o700)
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.zero = dict(sequence=0, record_sha256=core.portfolio.ZERO)
        monkeypatch.setattr(core, "ready", lambda _: None)  # Explicit synthetic closure.
        monkeypatch.setattr(core.portfolio, "_ready", lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: NOW)

    def open(self, anchor=None):
        return core.PortfolioSession(self.root, self.activation, expected_tail=anchor or self.zero)

    def test_hot_append_does_not_replay_history_and_restart_matches(self, monkeypatch):
        session = self.open()
        for _ in range(12):
            session.append(operation="MARK", data=dict(marks={}))
        original = core.portfolio.recover
        original_observe = core.journal.observe
        reads = []

        def observe(*args, **kwargs):
            reads.append(kwargs["key"])
            return original_observe(*args, **kwargs)

        monkeypatch.setattr(core.journal, "observe", observe)
        monkeypatch.setattr(
            core.portfolio, "recover", lambda *_args, **_kwargs: pytest.fail("hot full replay")
        )
        state, _ = session.append(operation="MARK", data=dict(marks={}))
        assert state["sequence"] == 13
        assert reads == ["portfolio_00000012"]
        monkeypatch.setattr(core.portfolio, "recover", original)
        assert self.open(session.anchor()).snapshot() == state

    def test_snapshot_mutation_cannot_change_live_account(self):
        session = self.open()
        view = session.snapshot()
        view["cash"]["price_flow"]["1x"] = 999_999_999
        assert session.snapshot()["cash"]["price_flow"]["1x"] == 1_000_000

    def test_competing_writer_invalidates_stale_cache_without_overwrite(self):
        first, second = self.open(), self.open()
        first.append(operation="MARK", data=dict(marks={}))
        with pytest.raises(ValueError, match="stale"):
            second.append(operation="MARK", data=dict(marks={}))
        with pytest.raises(ValueError, match="invalidated"):
            second.snapshot()
        assert self.open(first.anchor()).snapshot()["sequence"] == 1

    def test_lost_acknowledgment_requires_replay_but_keeps_committed_event(self, monkeypatch):
        session = self.open()
        original = core.journal.publish

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("synthetic lost acknowledgment")

        monkeypatch.setattr(core.journal, "publish", lost)
        with pytest.raises(OSError):
            session.append(operation="MARK", data=dict(marks={}))
        with pytest.raises(ValueError, match="invalidated"):
            session.snapshot()
        monkeypatch.setattr(core.journal, "publish", original)
        assert self.open().snapshot()["sequence"] == 1

    def test_bad_operation_does_not_poison_valid_session(self):
        session = self.open()
        with pytest.raises(ValueError):
            session.append(operation="BOGUS", data=dict(position="none"))
        assert session.snapshot()["sequence"] == 0
        session.append(operation="MARK", data=dict(marks={}))

    def test_partial_next_event_and_bad_external_anchor_fail_closed(self):
        session = self.open()
        session.append(operation="MARK", data=dict(marks={}))
        (self.root / "source/portfolio_00000002").mkdir(mode=0o700)
        with pytest.raises(ValueError, match="incomplete"):
            session.append(operation="MARK", data=dict(marks={}))
        with pytest.raises(FileNotFoundError):
            self.open()

    def test_reservations_remain_after_reopening(self):
        session = self.open()
        intent = core.portfolio.execution.make_intent(**fixture())[1]
        state, _ = session.append(operation="RESERVE", data=dict(intent=intent))
        reopened = self.open(session.anchor())
        assert reopened.snapshot() == state
        assert (
            core.portfolio.view(reopened.snapshot(), "price_flow", NOW)["free_notional_rub"]
            == 750000
        )
