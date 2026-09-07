"""Real anchored paper execution, fake asynchronous source pool and synthetic quotes."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_execution_bridge_v1 import TestBridge as BridgeFixture
from test_algopack_paper_journal_v1 import START

from market_lab.futures import algopack_paper_async_due_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


def test_groups_exits_first_and_two_arms_share_contract():
    positions = {}
    for arm in ("price_only", "price_flow"):
        for asset in ("BR", "SI"):
            positions[arm + "_" + asset] = dict(
                status="OPEN",
                entry={} if asset == "SI" else None,
                intent=dict(
                    asset=asset,
                    secid=asset + "SYNTH",
                    entry_at=START.isoformat(),
                    exit_at=START.isoformat(),
                ),
            )
    groups = core.groups(dict(positions=positions), START)
    assert [group[2] for group in groups] == ["SI", "BR"]
    assert all(len(rows) == 2 for rows in groups.values())


class Pool:
    def __init__(self, activation):
        self.active, self.completed, self.started = {}, [], []

    def start(self, job):
        if len(self.active) >= 4:
            return "POOL_FULL"
        self.active[job.key] = job
        self.started.append(job)
        return "STARTED"

    def poll(self):
        completed, self.completed = self.completed, []
        for row in completed:
            del self.active[row["key"]]
        return completed

    def finish(self, state="EXITED"):
        self.completed = [dict(key=key, state=state) for key in self.active]


@pytest.mark.skipif(os.name != "posix", reason="actual anchored Linux ledger")
class TestDue:
    observe = BridgeFixture.observe
    quote = BridgeFixture.quote
    reserve = BridgeFixture.reserve
    enter = BridgeFixture.enter

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        BridgeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core, "market_root", lambda _: self.market)
        monkeypatch.setattr(core.worker, "Pool", Pool)
        monkeypatch.setattr(core.worker, "observe", lambda *args: dict(reference="synthetic_quote"))
        self.attempts = tmp_path / "async_attempts"
        self.attempts.mkdir(mode=0o700)
        self.executor = core.Executor(self.bridge, self.attempts)

    def due(self):
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.bridge.source._stamp(
            row["intent"]["exit_at" if row["entry"] else "entry_at"]
        )

    def test_not_due_no_job(self):
        self.reserve()
        assert self.executor.tick()["active_workers"] == 0
        assert not self.executor.pool.started

    def test_two_arms_share_async_quote_and_no_fill_while_running(self):
        self.reserve()
        self.bridge.reserve(
            asset="BR",
            arm="price_only",
            forecast_reference="forecast",
            quote_reference="quote",
            calendar_reference="calendar",
        )
        self.due()
        self.executor.tick()
        assert len(self.executor.pool.started) == 1
        assert self.executor.tick()["outcomes"] == []
        assert all(row["entry"] is None for row in self.account.snapshot()["positions"].values())
        self.executor.pool.finish()
        result = self.executor.tick()
        assert len(result["outcomes"]) == 2
        assert all(row["result"]["operation"] == "ENTRY" for row in result["outcomes"])
        assert self.executor.tick()["outcomes"] == []

    def test_failed_source_retries_fresh_job_later(self):
        self.reserve()
        self.due()
        self.executor.tick()
        self.executor.pool.finish("FAILED")
        assert self.executor.tick()["outcomes"] == []
        assert len(self.executor.pool.started) == 1
        self.executor.tick()
        assert len(self.executor.pool.started) == 2
        assert self.executor.pool.started[0].key != self.executor.pool.started[1].key

    @pytest.mark.parametrize("opened", [False, True])
    def test_expiry_preserves_exit_risk_or_cancels_entry(self, opened):
        self.enter() if opened else self.reserve()
        self.due()
        self.executor.tick()
        self.at += timedelta(seconds=31)
        result = self.executor.tick()
        assert result["outcomes"][0]["result"]["operation"] == (
            "UNRESOLVED" if opened else "CANCEL"
        )
        self.executor.pool.finish("EXPIRED")
        self.executor.tick()
        assert not self.executor.jobs

    def test_stale_or_bad_source_not_a_fill(self, monkeypatch):
        self.reserve()
        self.due()
        self.executor.tick()
        self.executor.pool.finish()

        def fail(*args):
            raise ValueError("synthetic invalid source")

        monkeypatch.setattr(core.worker, "observe", fail)
        assert self.executor.tick()["outcomes"] == []
        assert self.account.snapshot()["positions"]["price_flow_BR"]["entry"] is None

    def test_lost_fill_ack_requires_reopen(self, monkeypatch):
        self.reserve()
        self.due()
        self.executor.tick()
        self.executor.pool.finish()
        original = self.bridge.fill_due

        def fail(**kwargs):
            original(**kwargs)
            raise OSError("synthetic lost ack")

        monkeypatch.setattr(self.bridge, "fill_due", fail)
        with pytest.raises(RuntimeError, match="reopen"):
            self.executor.tick()
        assert not self.executor.valid
        assert self.account.snapshot()["positions"]["price_flow_BR"]["entry"] is not None
        with pytest.raises(ValueError, match="invalidated"):
            self.executor.tick()
