"""Fixed denominator and durable forecast tests, all synthetic."""

import os
from datetime import date, timedelta

import pytest
from test_algopack_paper_journal_v1 import END, NOW, START, candidate

from market_lab.futures import algopack_paper_coverage_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_fixed_grid_has_42_slots_and_no_weekends():
    grid = core.slots(date(2026, 9, 8))
    assert len(grid) == 42 and grid[-1] - grid[0] == timedelta(minutes=410)
    with pytest.raises(ValueError):
        core.slots(date(2026, 9, 12))


def test_no_activation_refuses_coverage(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        core.build(
            tmp_path, VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64), date(2026, 9, 8)
        )


@pytest.mark.skipif(os.name != "posix", reason="Linux durable publication")
class TestCoverage:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.root, self.reports = tmp_path / "source", tmp_path / "reports"
        for root in (self.root, self.reports):
            root.mkdir(mode=0o700)
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.at = NOW
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: self.at)

    def forecast(self, late=False):
        self.at = END + timedelta(minutes=3)
        source = core.journal.publish(
            self.root, kind="source", key="capture_1", future_start=START, payload={}
        )
        value = candidate()
        value["source_observations"][0]["record_sha256"] = source["record_sha256"]
        value["arms"]["price_flow"].update(status="SLEEP_MISSING_FEATURES", prediction=None)
        self.at = END + timedelta(minutes=10) if late else NOW
        core.journal.publish_forecast(self.root, value)

    def report(self):
        self.at = END.replace(hour=16)
        return core.build(self.root, self.activation, END.date())

    def test_empty_day_is_168_missing_not_zero_denominator(self):
        result = self.report()
        assert all(
            row == dict(ready=0, sleep=0, failed=0, missing=168) for row in result["arms"].values()
        )

    def test_independent_arms_and_late_report_not_late_consumption(self):
        self.forecast()
        result = self.report()
        assert result["arms"]["price_only"] == dict(ready=4, sleep=0, failed=0, missing=164)
        assert result["arms"]["price_flow"] == dict(ready=0, sleep=4, failed=0, missing=164)
        assert result["forecast_consumption_verified"] is False

    def test_late_durable_forecast_counts_failed(self):
        self.forecast(late=True)
        assert all(row["failed"] == 4 for row in self.report()["arms"].values())

    def test_partial_forecast_is_failed_not_missing(self):
        partial = self.root / "forecast" / END.strftime("%Y%m%dT%H%M%SZ")
        partial.mkdir(parents=True, mode=0o700)
        assert all(row["failed"] == 4 for row in self.report()["arms"].values())

    def test_immature_day_is_rejected(self):
        with pytest.raises(ValueError, match="immature"):
            core.build(self.root, self.activation, END.date())

    def test_daily_report_is_immutable(self):
        self.report()
        ref = core.publish(self.root, self.reports, self.activation, END.date())
        event = core.journal.observe(
            self.reports,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=START,
        )
        assert event["payload"]["arms"]["price_only"]["missing"] == 168
        with pytest.raises((ValueError, FileExistsError)):
            core.publish(self.root, self.reports, self.activation, END.date())
