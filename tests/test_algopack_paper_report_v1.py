"""Synthetic combined report bindings; child numerical audits have dedicated suites."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_daily_snapshot_v1 import TestDaily as DailyFixture
from test_algopack_paper_journal_v1 import END, NOW, START, candidate

from market_lab.futures import algopack_paper_report_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="Linux durable report/ledger bindings")
class TestReport:
    observe = DailyFixture.observe
    quote = DailyFixture.quote
    reserve = DailyFixture.reserve
    enter = DailyFixture.enter
    publish = DailyFixture.publish

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        DailyFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(
            core.execution_audit, "audit", lambda *_: dict(status="SYNTHETIC_CHILD_AUDIT")
        )
        monkeypatch.setattr(core.forecast_audit, "audit", lambda *_: dict(forecast_recomputed=True))

    def report(self, root=None):
        self.at = core.daily.window(END.date()) + timedelta(seconds=31)
        return core.build(
            self.account,
            self.market,
            root or self.reports,
            expected_days=(END.date(),),
            calendar_sha256="a" * 64,
        )

    def test_missing_day_does_not_become_flat_equity(self):
        result = self.report()
        assert result["evaluation"]["missing_days"] == [END.date().isoformat()]
        assert result["evaluation"]["arms"]["price_flow"]["metrics"] is None

    def test_verified_flat_day_retains_zero_coverage_and_no_annualization(self):
        self.publish()
        result = self.report()
        arm = result["evaluation"]["arms"]["price_flow"]
        assert arm["decision_coverage"] == 0
        assert arm["metrics"]["1x"]["total_return"] == 0
        assert arm["metrics"]["1x"]["cagr"] is None
        assert result["calendar_source_verified"] is result["target_income_verified"] is False

    def test_roundtrip_counts_come_from_ledger(self):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["exit_at"])
        self.shift = 100
        self.bridge.fill_due(position="price_flow_BR", quote_reference="exit_quote")
        self.publish()
        result = self.report()
        assert result["recomputed_forecasts"] == 1
        assert result["evaluation"]["arms"]["price_flow"]["counts"]["closed"] == 1

    @pytest.mark.parametrize("tamper", [False, True])
    def test_positive_coverage_matches_actual_forecast_status(self, tmp_path, tamper):
        self.at = END + timedelta(minutes=3)
        source = core.journal.publish(
            self.market, kind="source", key="capture_1", future_start=START, payload={}
        )
        forecast = candidate()
        forecast["source_observations"][0]["record_sha256"] = source["record_sha256"]
        self.at = NOW
        core.journal.publish_forecast(self.market, forecast)
        reference = self.publish()["reference"]
        if not tamper:
            result = self.report()
            assert result["evaluation"]["arms"]["price_flow"]["counts"]["ready"] == 4
            return
        record = core.journal.observe(
            self.reports,
            kind="source",
            key=reference["key"],
            record_sha256=reference["record_sha256"],
            future_start=START,
        )
        payload = record["payload"]
        for slot in payload["coverage"]["slots"]:
            if slot["observation"]:
                slot["categories"]["price_flow"] = "sleep"
        for counts in (
            payload["coverage"]["arms"]["price_flow"],
            payload["snapshot"]["arms"]["price_flow"]["counts"],
        ):
            counts["ready"], counts["sleep"] = 0, 4
        forged = tmp_path / "forged_coverage"
        forged.mkdir(mode=0o700)
        core.journal.publish(
            forged, kind="source", key=reference["key"], future_start=START, payload=payload
        )
        with pytest.raises(ValueError, match="category"):
            self.report(forged)

    @pytest.mark.parametrize("field", ["equity", "entries", "ledger"])
    def test_hash_valid_forged_snapshot_rejected(self, tmp_path, field):
        reference = self.publish()["reference"]
        record = core.journal.observe(
            self.reports,
            kind="source",
            key=reference["key"],
            record_sha256=reference["record_sha256"],
            future_start=START,
        )
        payload = record["payload"]
        row = payload["snapshot"]
        if field == "equity":
            row["arms"]["price_flow"]["equity_rub"]["1x"] += 100
        elif field == "entries":
            row["arms"]["price_flow"]["counts"]["entries"] += 1
        else:
            row["ledger_sha256"] = "e" * 64
        forged = tmp_path / "forged"
        forged.mkdir(mode=0o700)
        core.journal.publish(
            forged, kind="source", key=reference["key"], future_start=START, payload=payload
        )
        with pytest.raises(ValueError):
            self.report(forged)
