"""Synthetic preparation and Linux journals; one benign subprocess, no API/model work."""

import os
import sys
import time
from datetime import timedelta

import pytest
from test_algopack_paper_journal_v1 import END, NOW, START

from market_lab.futures import algopack_paper_preparation_worker_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_missing_activation_before_credential(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", "--activation-sha256", "a" * 64, "--information-end", END.isoformat()],
    )
    seen = []
    original = os.environ.get

    def get(key, *args):
        if key == "MOEX_ALGOPACK_TOKEN":
            seen.append(key)
        return original(key, *args)

    monkeypatch.setattr(os.environ, "get", get)
    assert core.main() == 1 and seen == []


class Process:
    code = None
    terminated = killed = 0

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1

    def wait(self, *args, **kwargs):
        raise AssertionError("blocking wait forbidden")

    communicate = wait


@pytest.mark.skipif(os.name != "posix", reason="actual private Linux journal")
class TestWorker:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.at, self.mono, self.calls = NOW, 0.0, []
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.runtime, "DATA_ROOT", tmp_path / "data")
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.time, "monotonic", lambda: self.mono)
        self.root = core.runtime.DATA_ROOT / self.activation.activation_sha256
        self.root.mkdir(parents=True, mode=0o700)
        for name in ("market", "scheduler"):
            (self.root / name).mkdir(mode=0o700)
        self.child = Process()
        self.original_popen = core.subprocess.Popen

        def launch(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return self.child

        monkeypatch.setattr(core.subprocess, "Popen", launch)
        self.supervisor = core.Supervisor(self.activation)

    def test_one_worker_and_nonblocking_poll(self):
        assert self.supervisor.start(END)["status"] == "WORKER_STARTED"
        assert self.supervisor.start(END)["status"] == "WORKER_BUSY"
        for _ in range(20):
            assert self.supervisor.poll()["status"] == "WORKER_RUNNING"
        assert len(self.calls) == 1
        argv, kwargs = self.calls[0]
        assert "--information-end" in argv
        assert kwargs["stdout"] == core.subprocess.DEVNULL
        assert "env" not in kwargs and "SYNTHETIC" not in str(argv)

    def test_real_benign_child_does_not_block_supervisor(self, monkeypatch):
        # A real subprocess, but not the preparation CLI and never market/model work.
        actual_popen = self.original_popen
        child = None

        def launch(argv, **kwargs):
            nonlocal child
            child = actual_popen([sys.executable, "-c", "import time; time.sleep(20)"], **kwargs)
            return child

        monkeypatch.setattr(core.subprocess, "Popen", launch)
        begun = time.perf_counter()
        try:
            self.supervisor.start(END)
            assert self.supervisor.poll()["status"] == "WORKER_RUNNING"
            assert time.perf_counter() - begun < 5
            self.at = END + timedelta(minutes=10)
            assert self.supervisor.poll()["status"] == "WORKER_STOP_REQUESTED"
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)  # Test cleanup only; supervisor never waits.

    def test_deadline_terminate_then_kill_without_wait(self):
        self.supervisor.start(END)
        self.at = END + timedelta(minutes=10)
        assert self.supervisor.poll()["status"] == "WORKER_STOP_REQUESTED"
        assert self.child.terminated == 1 and self.child.killed == 0
        self.mono += 5
        self.supervisor.poll()
        assert self.child.killed == 1
        self.child.code = -9
        assert self.supervisor.poll()["status"] == "WORKER_EXPIRED"
        assert self.supervisor.poll()["status"] == "NO_WORKER"

    @pytest.mark.parametrize("code,status", [(0, "WORKER_EXITED"), (1, "WORKER_FAILED")])
    def test_exit_never_admits_forecast_or_reruns(self, code, status):
        self.supervisor.start(END)
        self.child.code = code
        result = self.supervisor.poll()
        assert result["status"] == status and result["forecast_admitted"] is False
        assert (
            core.Supervisor(self.activation).start(END)["status"] == "EXISTING_PREPARATION_ATTEMPT"
        )
        assert len(self.calls) == 1

    def test_spawn_failure_retains_started(self, monkeypatch):
        def fail(*args, **kwargs):
            raise OSError("private spawn detail")

        monkeypatch.setattr(core.subprocess, "Popen", fail)
        with pytest.raises(ValueError, match="spawn failed"):
            self.supervisor.start(END)
        assert self.supervisor.start(END)["status"] == "EXISTING_PREPARATION_ATTEMPT"

    def test_preparation_writes_sources_not_portfolio(self, monkeypatch):
        phases = []

        def select(*args):
            phases.append("flow")
            return dict(reference=None)

        def capture(*args, **kwargs):
            phases.append("capture")
            return dict(record_sha256="c" * 64)

        def predict(*args, **kwargs):
            phases.append("predict")
            assert kwargs["flow_reference"] is None
            return dict(kind="forecast", key="synthetic", record_sha256="d" * 64)

        monkeypatch.setattr(core.flow, "select_and_import", select)
        monkeypatch.setattr(core.capture, "capture_packet", capture)
        monkeypatch.setattr(core.predictor, "predict_slot", predict)
        ref = core.prepare(object(), self.activation, information_end=END, token="SYNTHETIC")
        assert phases == ["flow", "capture", "predict"]
        assert ref["key"].endswith("_finished")
        assert {path.name for path in self.root.iterdir()} == {"market", "scheduler"}

    def test_late_capture_does_not_start_model(self, monkeypatch):
        monkeypatch.setattr(core.flow, "select_and_import", lambda *_: dict(reference=None))
        predictions = []

        def capture(*args, **kwargs):
            self.at = END + timedelta(minutes=10)
            return {}

        monkeypatch.setattr(core.capture, "capture_packet", capture)
        monkeypatch.setattr(
            core.predictor, "predict_slot", lambda *args, **kwargs: predictions.append(1)
        )
        with pytest.raises(ValueError, match="retained"):
            core.prepare(object(), self.activation, information_end=END, token="SYNTHETIC")
        assert predictions == []
