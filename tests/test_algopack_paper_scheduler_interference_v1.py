"""Characterize synchronous scheduler interference with artificial elapsed time only.

PASS proves the modeled failure is reproduced, NOT that execution latency is acceptable.
"""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_journal_v1 import END
from test_algopack_paper_runtime_v1 import TestRuntime as RuntimeFixture


@pytest.mark.skipif(os.name != "posix", reason="actual Linux scheduler journals")
class TestInterference:
    open = RuntimeFixture.open
    flow = RuntimeFixture.flow
    daily = RuntimeFixture.daily

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.duration = 0
        self.due = END + timedelta(minutes=10)
        self.pump_observations = []
        RuntimeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)

    def pump(self, *args, **kwargs):
        self.calls.append("pump")
        elapsed = (self.at - self.due).total_seconds()
        self.pump_observations.append(dict(at=self.at, due_delay_seconds=elapsed))
        return dict(status="NOTHING_DUE" if elapsed < 0 else "COMPLETE")

    def slot(self, *args, **kwargs):
        self.calls.append("slot")
        self.at += timedelta(seconds=self.duration)
        # Actual slot checks this same E+10 deadline after capture/inference.
        return dict(status="FAILED" if self.at >= self.due else "COMPLETE")

    @pytest.mark.parametrize(
        "start_seconds,duration,missed",
        [
            (241, 120, False),
            (480, 20, False),
            (540, 120, True),
            (599, 40, True),
        ],
    )
    def test_interference_matrix(self, start_seconds, duration, missed):
        self.at = END + timedelta(seconds=start_seconds)
        self.duration = duration
        if missed:
            with pytest.raises(RuntimeError, match="reopen"):
                self.runtime.tick()
            assert self.runtime.valid is False
            # No pump call occurred during the blocking slot, even though due passed.
            assert len(self.pump_observations) == 1
            assert self.pump_observations[0]["due_delay_seconds"] < 0
            # Optimistic immediate reopen has zero restart overhead, yet is already late.
            restarted = self.open()
            restarted.tick()
            assert self.pump_observations[-1]["due_delay_seconds"] > 30
        else:
            assert self.runtime.tick()["work"] == "COMPLETE"
            assert len(self.pump_observations) == 1
            self.at = self.due
            self.runtime.tick()
            assert self.pump_observations[-1]["due_delay_seconds"] == 0
