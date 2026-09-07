"""Complete synthetic raw-source/model forecast reproduction, no actual market archives."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_inference_v1 import models  # noqa: F401
from test_algopack_paper_predictor_v1 import END
from test_algopack_paper_predictor_v1 import TestPipeline as PipelineFixture

from market_lab.futures import algopack_paper_forecast_audit_v1 as core


def test_no_activation_no_audit(tmp_path):
    with pytest.raises(ValueError):
        core.audit(tmp_path, {}, None)


@pytest.mark.skipif(os.name != "posix", reason="complete Linux synthetic source pipeline")
class TestForecastAudit:
    flow_payload = staticmethod(PipelineFixture.flow_payload)
    predict = PipelineFixture.predict

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch, models):  # noqa: F811
        PipelineFixture.setup.__wrapped__(self, tmp_path, monkeypatch, models)
        monkeypatch.setattr(core, "ready", lambda _: None)

    @pytest.mark.parametrize("flow", [False, True])
    def test_later_audit_reconstructs_original_features_and_predictions(self, flow):
        reference = self.predict(flow)
        self.clock += timedelta(days=1)
        result = core.audit(self.root, reference, self.activation)
        assert result["forecast_recomputed"] is True
        assert result["target_income_verified"] is result["execution_admitted"] is False
        assert result["audited_at"] == self.clock.isoformat()

    @pytest.mark.parametrize("field", ["prediction", "contract"])
    def test_hash_valid_but_numerically_altered_publication_rejected(self, monkeypatch, field):
        original = core.inference.predict_prepared

        def altered(*args):
            value = original(*args)
            if field == "prediction":
                value["arms"]["price_flow"]["prediction"][0] += 0.1
            else:
                value["assets"][0]["secid"] = "WRONG"
            return value

        monkeypatch.setattr(core.inference, "predict_prepared", altered)
        reference = self.predict()
        monkeypatch.setattr(core.inference, "predict_prepared", original)
        with pytest.raises(ValueError, match="source reconstruction"):
            core.audit(self.root, reference, self.activation)

    def test_late_completion_remains_masked(self, monkeypatch):
        original = core.inference.predict_prepared

        def delayed(*args):
            value = original(*args)
            self.clock = END + timedelta(minutes=10)
            return value

        monkeypatch.setattr(core.inference, "predict_prepared", delayed)
        reference = self.predict()
        monkeypatch.setattr(core.inference, "predict_prepared", original)
        self.clock += timedelta(days=1)
        assert core.audit(self.root, reference, self.activation)["forecast_recomputed"] is True

    def test_corrupt_raw_flow_fails_even_when_forecast_journal_is_intact(self):
        reference = self.predict()
        path = core.predictor.FLOW_ROOT / self.capture_id / "BRU6_tradestats_000.json.gz"
        path.write_bytes(b"synthetic corruption")
        with pytest.raises((ValueError, OSError)):
            core.audit(self.root, reference, self.activation)
