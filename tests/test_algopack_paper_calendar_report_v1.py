"""Synthetic calendar/report bridge; full ledger with separately tested child sources."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_journal_v1 import END, START
from test_algopack_paper_report_v1 import TestReport as ReportFixture

from market_lab.futures import algopack_paper_calendar_report_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="real Linux ledger and reports")
class TestBinding:
    observe = ReportFixture.observe
    quote = ReportFixture.quote
    reserve = ReportFixture.reserve
    enter = ReportFixture.enter
    publish = ReportFixture.publish

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        ReportFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        self.selection = dict(
            expected_days=[END.date().isoformat()],
            calendar_sha256="a" * 64,
            days=[dict(day=END.date().isoformat(), status="OPEN")],
        )
        monkeypatch.setattr(core.calendar, "build", lambda *_args, **_kwargs: self.selection)

    def build(self):
        self.at = core.report.daily.window(END.date()) + timedelta(seconds=31)
        return core.build(self.account, self.market, self.reports, self.market, through=END.date())

    def test_open_calendar_binds_real_report(self):
        self.publish()
        result = self.build()
        assert result["calendar_source_verified"] is True
        assert result["report"]["calendar_source_verified"] is False
        assert result["evaluation"]["arms"]["price_flow"]["metrics"]["1x"]["cagr"] is None
        assert result["target_income_verified"] is False

    def test_missing_snapshot_still_missing(self):
        result = self.build()
        assert result["evaluation"]["missing_days"] == [END.date().isoformat()]
        assert result["evaluation"]["arms"]["price_flow"]["metrics"] is None

    def test_unresolved_calendar_no_economic_reads(self, monkeypatch):
        self.selection["expected_days"] = None

        def forbidden(*args, **kwargs):
            raise AssertionError("economic read before calendar resolution")

        monkeypatch.setattr(core, "excluded_days", forbidden)
        monkeypatch.setattr(core.report, "build", forbidden)
        assert self.build()["evaluation"] is None

    def test_closed_flat_day_not_profit(self):
        self.publish()
        self.selection["days"][0]["status"] = "CLOSED"
        self.selection["expected_days"] = []
        result = self.build()
        assert result["evaluation"]["status"] == "NO_DATA"
        assert result["excluded_day_audit"]["excluded_days"] == [END.date().isoformat()]

    @pytest.mark.parametrize("status", ["CLOSED", "OUT_OF_SCOPE_WEEKEND"])
    def test_excluded_day_cannot_hide_reservation(self, status):
        self.reserve()
        self.selection["days"][0]["status"] = status
        self.selection["expected_days"] = []
        with pytest.raises(ValueError, match="economic activity"):
            self.build()

    def test_carried_risk_on_day_without_events_rejected(self):
        self.enter()
        decisions = [
            dict(day=END.date().isoformat(), status="OPEN"),
            dict(day=(END.date() + timedelta(days=1)).isoformat(), status="CLOSED"),
        ]
        with pytest.raises(ValueError, match="carries risk"):
            core.excluded_days(self.account, decisions)

    def test_completed_roundtrip_cannot_be_dropped(self):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["exit_at"])
        self.shift = 100
        self.bridge.fill_due(position="price_flow_BR", quote_reference="exit_quote")
        self.selection["days"][0]["status"] = "CLOSED"
        self.selection["expected_days"] = []
        with pytest.raises(ValueError, match="economic activity"):
            self.build()
