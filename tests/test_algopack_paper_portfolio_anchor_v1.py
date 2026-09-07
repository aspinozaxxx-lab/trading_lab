"""Synthetic crash/recovery scenarios; no market access or production activation."""

import os

import pytest
from test_algopack_paper_execution_v1 import fixture
from test_algopack_paper_journal_v1 import NOW, START

from market_lab.futures import algopack_paper_portfolio_anchor_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_missing_activation_cannot_initialize(tmp_path):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    with pytest.raises((FileNotFoundError, ValueError)):
        core.initialize(tmp_path / "control", tmp_path / "ledger", activation)


@pytest.mark.skipif(os.name != "posix", reason="Linux journal durability/locks")
class TestAnchors:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.control, self.ledger = tmp_path / "control", tmp_path / "ledger"
        for root in (self.control, self.ledger):
            root.mkdir(mode=0o700)
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.cached, "ready", lambda _: None)
        monkeypatch.setattr(core.portfolio, "_ready", lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: NOW)

    def open(self):
        return core.AnchoredPortfolio(self.control, self.ledger, self.activation)

    def initialized(self):
        core.initialize(self.control, self.ledger, self.activation)
        return self.open()

    def mark(self, session):
        return session.append(operation="MARK", data=dict(marks={}))

    def test_missing_genesis_is_not_a_fresh_account(self):
        with pytest.raises(FileNotFoundError):
            self.open()

    def test_restart_preserves_reserved_capital(self):
        session = self.initialized()
        self.mark(session)
        intent = core.portfolio.execution.make_intent(**fixture())[1]
        state, _ = session.append(operation="RESERVE", data=dict(intent=intent))
        assert self.open().snapshot() == state
        assert core.portfolio.view(state, "price_flow", NOW)["free_notional_rub"] == 750000
        with pytest.raises(ValueError, match="unused"):
            core.initialize(self.control, self.ledger, self.activation)

    @pytest.mark.parametrize("after_publication", [False, True])
    def test_lost_anchor_ack_recovers_without_reexecuting(self, monkeypatch, after_publication):
        session = self.initialized()
        publish = core.AnchoredPortfolio._publish_anchor

        def lose(instance, state, command):
            if after_publication:
                publish(instance, state, command)
            raise OSError("synthetic anchor acknowledgment loss")

        monkeypatch.setattr(core.AnchoredPortfolio, "_publish_anchor", lose)
        with pytest.raises(OSError):
            self.mark(session)
        with pytest.raises(ValueError, match="invalidated"):
            session.snapshot()
        monkeypatch.setattr(core.AnchoredPortfolio, "_publish_anchor", publish)
        restored = self.open().snapshot()
        assert restored["sequence"] == 1
        assert self.open().snapshot() == restored
        assert len(list((self.ledger / "source").iterdir())) == 1

    def test_lost_portfolio_ack_recovers_committed_operation(self, monkeypatch):
        session = self.initialized()
        publish = core.journal.publish

        def lose(root, **kwargs):
            result = publish(root, **kwargs)
            if root == self.ledger:
                raise OSError("synthetic portfolio acknowledgment loss")
            return result

        monkeypatch.setattr(core.journal, "publish", lose)
        with pytest.raises(OSError):
            self.mark(session)
        monkeypatch.setattr(core.journal, "publish", publish)
        assert self.open().snapshot()["sequence"] == 1

    def test_orphan_command_is_retained_but_never_executed(self):
        session = self.initialized()
        with pytest.raises(ValueError):
            session.append(operation="BOGUS", data=dict(position="none"))
        reopened = self.open()
        assert reopened.snapshot()["sequence"] == 0
        self.mark(reopened)
        assert self.open().snapshot()["sequence"] == 1
        assert len(list((self.control / "source").glob("command_*"))) == 2

    def test_truncated_portfolio_cannot_reset_capital(self):
        session = self.initialized()
        self.mark(session)
        event = self.ledger / "source/portfolio_00000001"
        event.rename(self.ledger.parent / "retained_synthetic_event")
        with pytest.raises(FileNotFoundError):
            self.open()

    def test_partial_anchor_is_not_overwritten(self):
        session = self.initialized()
        (self.control / "source/anchor_00000001").mkdir(mode=0o700)
        with pytest.raises(ValueError):
            self.mark(session)
        with pytest.raises(FileNotFoundError):
            self.open()

    def test_competing_writer_invalidates_cache(self):
        first = self.initialized()
        second = self.open()
        self.mark(first)
        with pytest.raises(ValueError, match="another"):
            self.mark(second)
        with pytest.raises(ValueError, match="invalidated"):
            second.snapshot()

    def test_missing_cached_anchor_blocks_write(self):
        session = self.initialized()
        anchor = self.control / "source/anchor_00000000"
        anchor.rename(self.control.parent / "retained_synthetic_anchor")
        with pytest.raises(FileNotFoundError):
            self.mark(session)
        with pytest.raises(ValueError, match="invalidated"):
            session.snapshot()

    def test_foreign_command_reference_rejected(self):
        session = self.initialized()
        with pytest.raises(ValueError, match="runtime-owned"):
            session.append(operation="MARK", data={core.COMMAND_FIELD: {}, "marks": {}})
        assert session.snapshot()["sequence"] == 0

    def test_legacy_unanchored_event_without_command_rejected(self):
        self.initialized()
        core.portfolio.append(self.ledger, self.activation, operation="MARK", data=dict(marks={}))
        with pytest.raises(KeyError):
            self.open()
