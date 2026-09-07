"""Synthetic orchestration ordering; child source/model/execution calls are stubbed."""

import os
from types import SimpleNamespace

import pytest
from test_algopack_paper_execution_v1 import fixture
from test_algopack_paper_journal_v1 import END, NOW, START

from market_lab.futures import algopack_paper_slot_runner_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_no_activation_no_runner(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="Linux single-attempt lock and journal")
class TestSlot:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.at, self.calls = NOW, []
        roots = {name: tmp_path / name for name in ("attempts", "market", "control", "ledger")}
        for root in roots.values():
            root.mkdir(mode=0o700)
        self.attempts = roots["attempts"]
        self.runtime = SimpleNamespace(
            market_root=roots["market"],
            reserve=self.reserve,
            account=SimpleNamespace(
                activation=self.activation,
                control=roots["control"],
                ledger=roots["ledger"],
                snapshot=lambda: dict(positions={}),
            ),
        )
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.capture, "capture_packet", lambda *_, **__: dict(key="market"))
        monkeypatch.setattr(core.predictor, "predict_slot", lambda *_, **__: dict(key="forecast"))
        monkeypatch.setattr(core.journal, "consume_forecast", lambda *_: fixture()["consumed"])
        monkeypatch.setattr(
            core.bridge.source, "collect", lambda *_, **kwargs: dict(key=kwargs["key"])
        )
        monkeypatch.setattr(core.marks, "refresh", lambda *_: None)

    def reserve(self, **kwargs):
        self.calls.append((kwargs["asset"], kwargs["arm"]))
        return dict(status="SLEEP_FORECAST", execution_admitted=False)

    def run(self):
        return core.run(
            self.runtime, object(), self.attempts, information_end=END, token="synthetic"
        )

    def test_eight_ordered_decisions_and_no_second_execution(self):
        result = self.run()
        assert result["status"] == "COMPLETE" and len(result["outcomes"]) == 8
        assert self.calls == [
            (asset, arm) for asset in core.ASSETS for arm in core.journal.MODEL_SHA
        ]
        assert self.run()["status"] == "EXISTING_ATTEMPT_NOT_REEXECUTED"
        assert len(self.calls) == 8

    @pytest.mark.parametrize("phase", ["capture", "predict", "calendar"])
    def test_failed_phase_is_retained_without_secret_text(self, monkeypatch, phase):
        def fail(*_, **__):
            raise ValueError("synthetic private failure")

        module, name = {
            "capture": (core.capture, "capture_packet"),
            "predict": (core.predictor, "predict_slot"),
            "calendar": (core.bridge.source, "collect"),
        }[phase]
        monkeypatch.setattr(module, name, fail)
        result = self.run()
        assert result == dict(status="FAILED", phase=phase, execution_admitted=False)
        event = core.bridge.anchors.read_event(
            self.attempts, "slot_20260908T080000Z_failed", self.activation
        )
        assert "private failure" not in str(event)
        assert self.run()["status"] == "EXISTING_ATTEMPT_NOT_REEXECUTED"
        assert not self.calls

    def test_lost_decision_ack_never_repeats_reservation(self):
        def uncertain(**kwargs):
            self.reserve(**kwargs)
            raise OSError("synthetic acknowledgment loss")

        self.runtime.reserve = uncertain
        assert self.run()["phase"] == "decisions"
        assert len(self.calls) == 1
        assert self.run()["status"] == "EXISTING_ATTEMPT_NOT_REEXECUTED"
        assert len(self.calls) == 1

    def test_outside_window_has_no_attempt(self):
        self.at = END
        assert self.run()["status"] == "OUTSIDE_SLOT_WINDOW"
        assert not (self.attempts / "source").exists()
