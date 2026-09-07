"""Synthetic binding verification and tamper rejection, never actual historical outcomes."""

import copy
import os
from datetime import timedelta

import pytest
from test_algopack_paper_execution_bridge_v1 import TestBridge as BridgeFixture
from test_algopack_paper_journal_v1 import NOW, START

from market_lab.futures import algopack_paper_execution_audit_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_activation_required(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.ready(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


def test_claimed_observation_before_durable_source_rejected(tmp_path, monkeypatch):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    monkeypatch.setattr(
        core.journal, "observe", lambda *_, **__: dict(durable_payload_at=NOW.isoformat())
    )
    reference = dict(
        kind="source",
        key="test",
        record_sha256="a" * 64,
        observed_at=(NOW - timedelta(seconds=1)).isoformat(),
    )
    with pytest.raises(ValueError, match="chronology"):
        core.observation(tmp_path, reference, activation, NOW)


@pytest.mark.skipif(os.name != "posix", reason="actual Linux anchored journal")
class TestAudit:
    quote = BridgeFixture.quote
    reserve = BridgeFixture.reserve
    enter = BridgeFixture.enter

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.saved = {}
        BridgeFixture.setup.__wrapped__(self, tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.marks, "ready", lambda _: None)
        self.monkeypatch = monkeypatch

    def observe(self, root, reference, activation):
        value = BridgeFixture.observe(self, root, reference, activation)
        self.saved[reference] = self.quote(value)
        return value

    def replay_sources(self):
        def observed(root, ref, activation, at):
            assert core.source._stamp(ref["observed_at"]) <= at
            if ref["kind"] == "forecast":
                return copy.deepcopy(self.args["consumed"])
            return dict(synthetic_inputs=self.saved[ref["key"]])

        self.monkeypatch.setattr(core, "observation", observed)
        self.monkeypatch.setattr(
            core.source, "quote_inputs", lambda value: value["synthetic_inputs"]
        )

    def test_roundtrip_replays_without_promoting_forecast(self):
        self.enter()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["exit_at"])
        self.shift = 100
        self.bridge.fill_due(position="price_flow_BR", quote_reference="exit_quote")
        self.replay_sources()
        result = core.audit(self.account, self.market)
        assert result["events"] == 3 and result["status"] == "EXECUTION_BINDINGS_REPLAYED"
        assert result["forecast_recomputed"] is result["target_income_verified"] is False

    @pytest.mark.parametrize("field", ["price", "reference_mid", "quantity"])
    def test_tampered_fill_rejected_even_if_reducer_shape_is_valid(self, field):
        self.reserve()
        before = self.account.snapshot()
        intent = before["positions"]["price_flow_BR"]["intent"]
        self.at = core.source._stamp(intent["entry_at"])
        self.bridge.fill_due(position="price_flow_BR", quote_reference="entry_quote")
        record = core.bridge.anchors.read_event(self.ledger, "portfolio_00000002", self.activation)
        value = copy.deepcopy(record["payload"])
        if field == "quantity":
            value["data"]["fill"]["intent"][field] += 1
        else:
            value["data"]["fill"][field] += 1
        self.replay_sources()
        with pytest.raises(ValueError, match="source-derived"):
            core.verify_event(before, value, self.market, self.activation)

    @pytest.mark.parametrize("missing", [False, True])
    def test_mark_and_explicit_missing_mask_replay(self, missing):
        self.enter()
        core.marks.refresh(self.bridge, {} if missing else {"price_flow_BR": "mark_quote"})
        self.replay_sources()
        assert core.audit(self.account, self.market)["events"] == 3

    def test_missed_entry_cancellation_replays(self):
        self.reserve()
        row = self.account.snapshot()["positions"]["price_flow_BR"]
        self.at = core.source._stamp(row["intent"]["entry_at"]) + timedelta(seconds=31)
        self.bridge.fill_due(position="price_flow_BR")
        self.replay_sources()
        assert core.audit(self.account, self.market)["events"] == 2

    def test_foreign_evidence_root_rejected_before_source_io(self):
        self.reserve()
        record = core.bridge.anchors.read_event(self.ledger, "portfolio_00000001", self.activation)
        record["payload"]["data"]["execution_evidence"]["market_root"] = "/foreign"
        self.monkeypatch.setattr(core, "observation", lambda *_: pytest.fail("foreign IO"))
        with pytest.raises(ValueError, match="scope"):
            core.verify_event(
                core.portfolio.initial(START), record["payload"], self.market, self.activation
            )
