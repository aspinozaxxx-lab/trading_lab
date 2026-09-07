"""Synthetic calendar scheduling/restart gates; actual Linux scheduler journals."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_journal_v1 import END
from test_algopack_paper_runtime_v1 import TestRuntime as RuntimeFixture

from market_lab.futures import algopack_paper_runtime_v1 as core


def test_calendar_component_required():
    assert "calendar" in core.COMPONENTS


@pytest.mark.skipif(os.name != "posix", reason="Linux scheduler journal")
class TestCalendar:
    open = RuntimeFixture.open
    pump = RuntimeFixture.pump
    flow = RuntimeFixture.flow
    slot = RuntimeFixture.slot
    daily = RuntimeFixture.daily

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        RuntimeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        self.at = core.calendar.window(END.date())[0]
        monkeypatch.setattr(core.calendar, "capture", self.capture)

    def capture(self, session, root, activation, *, token):
        assert root == self.runtime.root / "calendar"
        assert session is self.runtime.session and activation is self.activation
        assert token == "synthetic"
        self.calls.append("calendar")
        return dict(kind="source", key=core.calendar.key(END.date()), record_sha256="c" * 64)

    def test_once_pump_first_and_restart_no_duplicate(self):
        assert self.runtime.tick()["work"] == "RECORDED_CALENDAR_NOT_REPORT_ADMITTED"
        assert self.calls == ["pump", "calendar"]
        self.calls.clear()
        assert self.open().tick()["work"] == "EXISTING_ATTEMPT"
        assert self.calls == ["pump"]

    @pytest.mark.parametrize("offset", [-1, 300])
    def test_window_boundaries_no_backfill(self, offset):
        self.at += timedelta(seconds=offset)
        assert self.runtime.tick()["work"] is None
        assert self.calls == ["pump"]

    def test_weekend_has_no_calendar_job(self):
        self.at += timedelta(days=4)
        assert self.at.weekday() == 5
        assert self.runtime.tick()["work"] is None
        assert self.calls == ["pump"]

    def test_failure_preserved_without_retry_on_reopen(self, monkeypatch):
        def fail(*args, **kwargs):
            raise ValueError("synthetic private response")

        monkeypatch.setattr(core.calendar, "capture", fail)
        with pytest.raises(RuntimeError, match="reopen"):
            self.runtime.tick()
        assert not self.runtime.valid
        assert self.open().tick()["work"] == "EXISTING_ATTEMPT"
        record = core.bridge.anchors.read_event(
            self.runtime.root / "scheduler",
            core.calendar.key(END.date()) + "_failed",
            self.activation,
        )
        assert "private response" not in str(record)

    def test_pump_failure_precedes_calendar(self, monkeypatch):
        monkeypatch.setattr(
            core.pump, "run", lambda *args, **kwargs: dict(status="FAILED_REOPEN_REQUIRED")
        )
        with pytest.raises(RuntimeError, match="reopen"):
            self.runtime.tick()
        assert self.calls == []

    def test_missing_calendar_root_not_silently_created(self):
        (self.runtime.root / "calendar").rmdir()
        with pytest.raises(FileNotFoundError):
            self.open()
