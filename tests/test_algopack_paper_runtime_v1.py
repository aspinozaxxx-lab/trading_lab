"""Synthetic scheduler integration; no production activation or market calls."""

import os
import sys

import pytest
from test_algopack_paper_journal_v1 import END, NOW, START

from market_lab.futures import algopack_paper_runtime_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_cli_missing_activation_stops_before_secret_access(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["runtime", "--activation-sha256", "a" * 64, "--serve"])
    original = core.os.environ.get

    def guarded(key, *args):
        if key == "MOEX_ALGOPACK_TOKEN":
            pytest.fail("secret access")
        return original(key, *args)

    monkeypatch.setattr(core.os.environ, "get", guarded)
    assert core.main() == 1
    assert "RUNTIME_STOPPED_REQUIRES_REVIEW" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "posix", reason="Linux scheduler locks/anchored state")
class TestRuntime:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.at, self.calls = NOW, []
        monkeypatch.setattr(core, "DATA_ROOT", tmp_path / "data")
        for module, name in (
            (core, "ready"),
            (core.bridge, "ready"),
            (core.bridge.anchors, "ready"),
            (core.bridge.anchors.cached, "ready"),
            (core.bridge.portfolio, "_ready"),
        ):
            monkeypatch.setattr(module, name, lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.pump, "run", self.pump)
        monkeypatch.setattr(core.flow, "select_and_import", self.flow)
        monkeypatch.setattr(core.slots, "run", self.slot)
        monkeypatch.setattr(core.daily, "publish", self.daily)
        core.initialize(self.activation)
        self.runtime = self.open()

    def open(self):
        return core.Runtime(self.activation, object(), "synthetic")

    def pump(self, *_, **__):
        self.calls.append("pump")
        return dict(status="NOTHING_DUE")

    def flow(self, *_):
        self.calls.append("flow")
        return dict(selection=dict(state="MISSING_FLOW"), reference=None)

    def slot(self, *_, **kwargs):
        assert kwargs["flow_reference"] is None
        self.calls.append("slot")
        return dict(status="COMPLETE")

    def daily(self, *_):
        self.calls.append("daily")
        return dict(status="RECORDED")

    def test_pump_first_selection_persisted_and_restart_no_duplicate(self):
        assert self.runtime.tick()["work"] == "COMPLETE"
        assert self.calls == ["pump", "flow", "slot"]
        self.calls.clear()
        assert self.open().tick()["work"] == "EXISTING_ATTEMPT"
        assert self.calls == ["pump"]
        event = core.bridge.anchors.read_event(
            self.runtime.root / "scheduler", "slot_20260908T080000Z_selection", self.activation
        )
        assert event["payload"]["result"]["reference"] is None

    def test_daily_once_and_no_forecast(self):
        self.at = core.daily.window(END.date())
        assert self.runtime.tick()["work"] == "RECORDED"
        assert self.calls == ["pump", "daily"]
        assert self.runtime.tick()["work"] == "EXISTING_ATTEMPT"

    def test_idle_tick_has_no_scheduled_work(self):
        self.at = END.replace(hour=19)
        assert self.runtime.tick()["work"] is None
        assert self.calls == ["pump"]

    def test_pump_uncertainty_prevents_forecast(self, monkeypatch):
        monkeypatch.setattr(
            core.pump, "run", lambda *_, **__: dict(status="FAILED_REOPEN_REQUIRED")
        )
        with pytest.raises(RuntimeError, match="reopen"):
            self.runtime.tick()
        assert not self.runtime.valid and not self.calls
        with pytest.raises(ValueError, match="invalidated"):
            self.runtime.tick()

    def test_failed_selection_reserved_and_not_retried_after_reopen(self, monkeypatch):
        def fail(*_):
            raise ValueError("synthetic private data")

        monkeypatch.setattr(core.flow, "select_and_import", fail)
        with pytest.raises(RuntimeError, match="reopen"):
            self.runtime.tick()
        assert self.open().tick()["work"] == "EXISTING_ATTEMPT"
        event = core.bridge.anchors.read_event(
            self.runtime.root / "scheduler", "slot_20260908T080000Z_failed", self.activation
        )
        assert "private data" not in str(event)

    def test_initialize_does_not_reset_existing_account(self):
        with pytest.raises(FileExistsError):
            core.initialize(self.activation)
