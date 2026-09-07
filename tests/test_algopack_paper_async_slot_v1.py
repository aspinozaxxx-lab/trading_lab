"""Actual Linux attempt journal with fake background pool/intake and ledger callbacks."""

import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_algopack_paper_async_due_v1 import Pool
from test_algopack_paper_journal_v1 import END, NOW, START

from market_lab.futures import algopack_paper_async_slot_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


@pytest.mark.skipif(os.name != "posix", reason="actual private Linux attempt journal")
class TestSlot:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.at, self.positions, self.reserves, self.mark_refs = NOW, {}, [], []
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.worker.runtime, "DATA_ROOT", tmp_path / "data")
        root = core.worker.runtime.DATA_ROOT / self.activation.activation_sha256
        root.mkdir(parents=True, mode=0o700)
        for name in ("market", "control", "ledger", "attempts"):
            (root / name).mkdir(mode=0o700)
        self.attempts = root / "attempts"
        account = SimpleNamespace(
            activation=self.activation,
            control=root / "control",
            ledger=root / "ledger",
            snapshot=lambda: dict(positions=self.positions),
        )
        self.runtime = SimpleNamespace(
            account=account, market_root=root / "market", reserve=self.reserve
        )
        monkeypatch.setattr(core.worker, "Pool", Pool)
        monkeypatch.setattr(
            core.worker, "observe", lambda job, *_: dict(reference=dict(key=job.key))
        )
        monkeypatch.setattr(
            core.marks, "refresh", lambda runtime, refs: self.mark_refs.append(refs)
        )
        self.intake = dict(
            status="FORECAST_OBSERVED_NOT_EXECUTION_ADMITTED",
            forecast="forecast",
            reference="intake",
            consumed=dict(
                payload=dict(
                    assets=[dict(asset=asset, secid=asset + "SYNTH") for asset in core.ASSETS]
                )
            ),
        )
        monkeypatch.setattr(core.intake, "consume", lambda *args: self.intake)
        self.slot = core.Slot(self.runtime, self.attempts, END)

    def reserve(self, **kwargs):
        self.reserves.append(kwargs)
        return dict(status="RECORDED")

    def to_quotes(self):
        assert self.slot.tick()["status"] == "CALENDAR"
        assert self.slot.tick()["status"] == "CALENDAR"
        self.slot.pool.finish()
        assert self.slot.tick()["status"] == "MARKS"
        assert self.slot.tick()["status"] == "MARKS"
        assert len(self.slot.pool.active) == 4

    def test_full_stepwise_admission_without_wait_or_duplicate(self):
        self.to_quotes()
        assert not self.reserves and not self.mark_refs
        self.slot.pool.finish()
        assert self.slot.tick()["status"] == "DECISIONS"
        for _ in range(4):
            result = self.slot.tick()
        assert result["status"] == "COMPLETE"
        assert len(self.reserves) == 8 and len(self.slot.pool.started) == 5
        assert [row["asset"] for row in self.reserves] == [
            asset for asset in core.ASSETS for _ in range(2)
        ]
        assert self.slot.tick()["status"] == "COMPLETE" and len(self.reserves) == 8
        with pytest.raises(FileExistsError):
            core.Slot(self.runtime, self.attempts, END)

    def test_waiting_intake_does_not_start_http_jobs(self):
        self.intake = dict(status="WAITING_PREPARATION")
        assert self.slot.tick()["status"] == "WAITING_PREPARATION"
        assert self.slot.pool.started == []

    def test_expiry_does_not_wait_for_workers(self):
        self.to_quotes()
        self.at = END + timedelta(minutes=10)
        assert self.slot.tick()["status"] == "EXPIRED"
        assert not self.reserves
        self.slot.pool.finish("EXPIRED")
        assert self.slot.tick()["active_workers"] == 0

    def test_missing_calendar_stops_new_intents(self):
        self.slot.tick()
        self.slot.tick()
        self.slot.pool.finish("FAILED")
        assert self.slot.tick()["status"] == "SOURCE_FAILED"
        assert not self.reserves

    def test_failed_quotes_mask_all_intents(self):
        self.to_quotes()
        self.slot.pool.finish("FAILED")
        self.slot.tick()
        for _ in range(4):
            self.slot.tick()
        assert self.slot.phase == "COMPLETE" and not self.reserves

    def test_quote_shared_for_mark_and_new_intent(self):
        self.positions["price_flow_BR"] = dict(entry={}, intent=dict(asset="BR", secid="BRSYNTH"))
        self.to_quotes()
        self.slot.pool.finish()
        self.slot.tick()
        self.slot.tick()
        assert self.mark_refs[0]["price_flow_BR"] == self.reserves[0]["quote_reference"]

    def test_closed_during_source_work_not_marked(self):
        self.positions["price_flow_BR"] = dict(entry={}, intent=dict(asset="BR", secid="BRSYNTH"))
        self.to_quotes()
        self.positions.clear()
        self.slot.pool.finish()
        self.slot.tick()
        assert self.mark_refs == [{}]

    def test_uncertain_reserve_invalidates_slot(self):
        self.to_quotes()
        self.slot.pool.finish()
        self.slot.tick()

        def fail(**kwargs):
            self.reserves.append(kwargs)
            raise OSError("synthetic lost ack")

        self.runtime.reserve = fail
        with pytest.raises(RuntimeError, match="reopen"):
            self.slot.tick()
        assert len(self.reserves) == 1 and not self.slot.valid
        with pytest.raises(ValueError, match="invalidated"):
            self.slot.tick()
