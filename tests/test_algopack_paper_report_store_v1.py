"""Immutable synthetic report publication, failure/restart and offline CLI guards."""

import os
import sys
from contextlib import contextmanager
from datetime import timedelta

import pytest
from test_algopack_paper_calendar_report_v1 import TestBinding as BindingFixture
from test_algopack_paper_journal_v1 import END, START

from market_lab.futures import algopack_paper_report_store_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_missing_activation_cli_refuses(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["report", "--activation-sha256", "a" * 64, "--through", "2026-09-08"]
    )
    assert core.main() == 1
    assert "REPORT_STOPPED_REQUIRES_REVIEW" in capsys.readouterr().out


def test_busy_runtime_lock_before_account_recovery(tmp_path, monkeypatch):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    monkeypatch.setattr(
        sys, "argv", ["report", "--activation-sha256", "a" * 64, "--through", "2026-09-08"]
    )
    monkeypatch.setattr(core, "load_activation", lambda *args: activation)
    monkeypatch.setattr(core, "ready", lambda *_: None)

    @contextmanager
    def busy(root):
        raise BlockingIOError("synthetic competing runtime")
        yield

    constructed = []

    def forbidden(*args):
        constructed.append(True)
        raise AssertionError("account constructed before exclusive lock")

    monkeypatch.setattr(core.anchors, "transaction", busy)
    monkeypatch.setattr(core.anchors, "AnchoredPortfolio", forbidden)
    assert core.main() == 1
    assert constructed == []


@pytest.mark.skipif(os.name != "posix", reason="real Linux immutable report journal")
class TestStore:
    observe = BindingFixture.observe
    quote = BindingFixture.quote
    reserve = BindingFixture.reserve
    enter = BindingFixture.enter
    publish = BindingFixture.publish

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        BindingFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        self.output = tmp_path / "economic_reports"
        self.output.mkdir(mode=0o700)

    def store(self):
        self.at = core.report.report.daily.window(END.date()) + timedelta(seconds=31)
        return core.publish(
            self.account, self.market, self.reports, self.market, self.output, through=END.date()
        )

    def test_full_report_persisted_and_later_read_not_recomputed(self):
        self.publish()
        ref = self.store()
        first = core.observe(self.output, ref, self.activation)
        self.at += timedelta(hours=1)
        second = core.observe(self.output, ref, self.activation)
        assert first["payload"] == second["payload"]
        assert first["observed_at"] != second["observed_at"]
        assert second["economic_recomputed"] is False
        assert first["payload"]["result"]["calendar_source_verified"] is True
        assert (
            first["payload"]["result"]["evaluation"]["arms"]["price_flow"]["metrics"]["1x"]["cagr"]
            is None
        )

    def test_duplicate_no_rebuild(self, monkeypatch):
        self.store()

        def forbidden(*args, **kwargs):
            raise AssertionError("duplicate economic build")

        monkeypatch.setattr(core.report, "build", forbidden)
        with pytest.raises(FileExistsError):
            self.store()

    def test_failure_sanitized_and_not_retried(self, monkeypatch):
        def fail(*args, **kwargs):
            raise RuntimeError("private synthetic provider response")

        monkeypatch.setattr(core.report, "build", fail)
        with pytest.raises(ValueError, match="retained"):
            self.store()
        event = core.anchors.read_event(self.output, "evaluation_20260908_failed", self.activation)
        assert "private synthetic" not in str(event)
        with pytest.raises(FileExistsError):
            self.store()

    def test_unresolved_calendar_saved_as_no_evaluation(self):
        self.selection["expected_days"] = None
        ref = self.store()
        result = core.observe(self.output, ref, self.activation)["payload"]["result"]
        assert result["evaluation"] is None
        assert result["calendar_source_verified"] is False

    def test_corrupt_saved_report_rejected(self):
        ref = self.store()
        path = self.output / "source" / ref["key"] / "payload.json"
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError):
            core.observe(self.output, ref, self.activation)

    def test_output_cannot_be_input(self):
        with pytest.raises(ValueError, match="separate"):
            core.publish(
                self.account,
                self.market,
                self.reports,
                self.market,
                self.market,
                through=END.date(),
            )
