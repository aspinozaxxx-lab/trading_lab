"""Synthetic completion chains and actual Linux forecast journal, no model or HTTP."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_journal_v1 import END, NOW, START, candidate

from market_lab.futures import algopack_paper_preparation_intake_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="actual Linux durable completion chain")
class TestIntake:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.at = END + timedelta(minutes=3)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.worker.runtime, "DATA_ROOT", tmp_path / "data")
        self.root = core.worker.runtime.DATA_ROOT / self.activation.activation_sha256
        self.root.mkdir(parents=True, mode=0o700)
        self.market, self.scheduler = self.root / "market", self.root / "scheduler"
        for path in (self.market, self.scheduler):
            path.mkdir(mode=0o700)
        self.key = "prepare_" + END.strftime("%Y%m%dT%H%M%SZ")

    def record(self, root, suffix, state, **data):
        return core.journal.publish(
            root,
            kind="source",
            key=self.key + suffix,
            future_start=START,
            payload=dict(
                protocol_id=core.worker.PROTOCOL,
                state=state,
                activation_sha256=self.activation.activation_sha256,
                execution_admitted=False,
                **data,
            ),
        )

    def complete(self, case=None):
        self.record(self.scheduler, "_started", "STARTED", information_end=END.isoformat())
        self.record(self.market, "_started", "STARTED")
        capture = core.journal.publish(
            self.market, kind="source", key="capture_1", future_start=START, payload={}
        )
        forecast = candidate()
        forecast["source_observations"][0]["record_sha256"] = capture["record_sha256"]
        self.at = NOW
        ref = core.journal.publish_forecast(self.market, forecast)
        if case == "slot":
            ref["key"] = "20260908T081000Z"
        if case == "lifetime":
            self.at -= timedelta(seconds=1)
        self.record(
            self.market,
            "_finished",
            "FAILED" if case == "child_failed" else "COMPLETE",
            forecast=ref,
        )
        self.at = NOW
        self.record(
            self.scheduler,
            "_finished",
            "WORKER_EXITED",
            exit_code=True if case == "bool_code" else 1 if case == "exit_code" else 0,
        )

    def test_waiting_does_not_reserve_or_read_forecast(self):
        assert core.consume(self.activation, END)["status"] == "WAITING_PREPARATION"
        assert not (self.scheduler / "source").exists()
        self.complete()
        assert (
            core.consume(self.activation, END)["status"]
            == "FORECAST_OBSERVED_NOT_EXECUTION_ADMITTED"
        )

    def test_completed_chain_consumed_once(self):
        self.complete()
        result = core.consume(self.activation, END)
        assert result["consumed"]["payload"]["arms"]["price_flow"]["status"] == "READY"
        assert result["execution_admitted"] is False
        assert core.consume(self.activation, END)["status"] == "EXISTING_INTAKE_ATTEMPT"

    def test_deadline_no_forecast_read(self, monkeypatch):
        self.at = END + timedelta(minutes=10)
        reads = []
        monkeypatch.setattr(core.anchors, "read_event", lambda *args: reads.append(1))
        assert core.consume(self.activation, END)["status"] == "MISSED_INTAKE_DEADLINE"
        assert reads == []

    @pytest.mark.parametrize("case", ["slot", "lifetime", "child_failed", "bool_code", "exit_code"])
    def test_invalid_chain_retained_without_retry(self, case):
        self.complete(case)
        with pytest.raises(ValueError, match="retained"):
            core.consume(self.activation, END)
        assert core.consume(self.activation, END)["status"] == "EXISTING_INTAKE_ATTEMPT"
