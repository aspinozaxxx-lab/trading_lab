"""Integrated tick ordering/restart using actual Linux journals and controlled async actors."""

import json
import os
import sys
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_algopack_paper_runtime_v1 as parent_fixture
from test_algopack_paper_journal_v1 import END, START
from test_algopack_paper_runtime_v1 import TestRuntime as RuntimeFixture

from market_lab.futures import algopack_paper_runtime_v2 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_cli_missing_activation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["async", "--activation-sha256", "a" * 64, "--serve"])
    assert core.main() == 1
    assert "ASYNC_RUNTIME_STOPPED_REQUIRES_REVIEW" in capsys.readouterr().out


def test_old_cli_cannot_serve_async_activation(tmp_path, monkeypatch):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    (tmp_path / "configs").mkdir()
    (tmp_path / core.CONFIG).write_text(json.dumps(dict(runtime_protocol=core.PROTOCOL)))
    monkeypatch.setattr(core.parent, "load_activation", lambda *_: activation)
    monkeypatch.setattr(core.parent, "ready", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["legacy", "--activation-sha256", "a" * 64, "--serve"])
    reads = []
    original = os.environ.get

    def get(key, *args):
        if key == "MOEX_ALGOPACK_TOKEN":
            reads.append(key)
        return original(key, *args)

    monkeypatch.setattr(os.environ, "get", get)
    assert core.parent.main() == 1 and not reads


@pytest.mark.skipif(os.name != "posix", reason="actual runtime/anchor/scheduler journals")
class TestAsync:
    open = RuntimeFixture.open
    pump = RuntimeFixture.pump
    flow = RuntimeFixture.flow
    slot = RuntimeFixture.slot
    daily = RuntimeFixture.daily

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(parent_fixture, "NOW", END.replace(hour=5))
        RuntimeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        self.duration, self.due_times = 120, []
        owner = self

        class Due:
            def __init__(self, *args):
                self.pool = SimpleNamespace(active={})

            def tick(self):
                owner.calls.append("due")
                owner.due_times.append(owner.at)
                return dict(outcomes=[], active_workers=0)

        class Preparation:
            def __init__(self, *args):
                self.process = None

            def start(self, end):
                owner.calls.append("start_preparation")
                self.process = object()
                self.finish = owner.at + timedelta(seconds=owner.duration)
                return dict(status="WORKER_STARTED")

            def poll(self):
                owner.calls.append("poll_preparation")
                if self.process is not None and owner.at >= self.finish:
                    self.process = None
                    return dict(status="WORKER_EXITED")
                return dict(status="WORKER_RUNNING" if self.process else "NO_WORKER")

        class Slot:
            def __init__(self, runtime, attempts, end):
                owner.calls.append("create_slot")
                self.end = end
                self.pool = SimpleNamespace(active={})

            def tick(self):
                owner.calls.append("slot_step")
                return dict(
                    status="EXPIRED"
                    if owner.at >= self.end + timedelta(minutes=10)
                    else "WAITING_PREPARATION"
                )

        monkeypatch.setattr(core.due, "Executor", Due)
        monkeypatch.setattr(core.preparation, "Supervisor", Preparation)
        monkeypatch.setattr(core.slots, "Slot", Slot)
        self.runtime = core.Runtime(self.activation, object(), "synthetic")

    @pytest.mark.parametrize("start,duration", [(241, 120), (480, 20), (540, 120), (599, 40)])
    def test_old_interference_cases_service_due_on_time(self, start, duration):
        self.at = END + timedelta(seconds=start)
        self.duration = duration
        assert self.runtime.tick()["work"] == "ASYNC_SLOT_STARTED"
        assert self.calls[:2] == ["due", "poll_preparation"]
        assert self.at == END + timedelta(seconds=start)  # No artificial blocking advance.
        self.calls.clear()
        self.at = END + timedelta(minutes=10)
        self.runtime.tick()
        assert self.due_times[-1] == END + timedelta(minutes=10)
        assert self.calls[0] == "due" and self.runtime.valid
        if start + duration > 600:
            assert self.runtime.preparation.process is not None

    def test_dispatch_once_after_restart(self):
        self.at = END + timedelta(minutes=4)
        self.runtime.tick()
        self.calls.clear()
        restarted = core.Runtime(self.activation, object(), "synthetic")
        assert restarted.tick()["work"] == "EXISTING_ATTEMPT"
        assert "start_preparation" not in self.calls

    def test_due_failure_blocks_later_work(self, monkeypatch):
        self.at = END + timedelta(minutes=4)

        def fail():
            raise RuntimeError("synthetic due uncertainty")

        monkeypatch.setattr(self.runtime.due, "tick", fail)
        with pytest.raises(RuntimeError, match="reopen"):
            self.runtime.tick()
        assert not self.runtime.valid and self.calls == []

    def test_calendar_only_when_no_actionable_risk(self, monkeypatch):
        self.at = core.parent.calendar.window(END.date())[0]
        monkeypatch.setattr(self.runtime, "capture_calendar", lambda: dict(status="CALENDAR"))
        monkeypatch.setattr(
            self.runtime.bridge.account,
            "snapshot",
            lambda: dict(positions={"synthetic": dict(status="OPEN")}),
        )
        assert self.runtime.tick()["work"] is None
        monkeypatch.setattr(self.runtime.bridge.account, "snapshot", lambda: dict(positions={}))
        assert self.runtime.tick()["work"] == "CALENDAR"

    def test_daily_snapshot_after_due_and_without_workers(self):
        self.at = core.parent.daily.window(END.date())
        assert self.runtime.tick()["work"] == "RECORDED"
        assert self.calls == ["due", "poll_preparation", "daily"]

    def test_shutdown_kills_all_before_reaping(self):
        order = []

        class Child:
            def __init__(self, name):
                self.name = name

            def poll(self):
                return None

            def kill(self):
                order.append("kill" + self.name)

            def wait(self, timeout):
                assert timeout == 2
                order.append("wait" + self.name)

        self.runtime.due.pool.active = {"a": dict(child=Child("a"))}
        self.runtime.preparation.process = Child("b")
        self.runtime.stop_children()
        assert order == ["killa", "killb", "waita", "waitb"]
