"""Synthetic source-to-forecast integration; no real requests or production activation."""

import json
import os
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from test_algopack_paper_capture_v1 import NOW, START, Response, payload
from test_algopack_paper_inference_v1 import models  # noqa: F401

from market_lab.futures import algopack_paper_predictor_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation

END = NOW.replace(minute=0)


def test_unverified_activation_prevents_source_io(tmp_path, monkeypatch):
    monkeypatch.setattr(core.source, "_read", lambda _: pytest.fail("unexpected source IO"))
    with pytest.raises(ValueError, match="verified activation"):
        core.load_flow("anything", "a" * 64, None)


@pytest.mark.skipif(os.name != "posix", reason="Linux durable journal integration")
class TestPipeline:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch, models):  # noqa: F811
        self.root = tmp_path / "journal"
        self.root.mkdir(mode=0o700)
        flow_root = tmp_path / "flow"
        flow_root.mkdir(mode=0o700)
        self.clock = NOW
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        monkeypatch.setattr(VerifiedActivation, "request_ready", lambda _: None)
        (tmp_path / "configs").mkdir()
        (tmp_path / core.BUNDLE).write_text(
            json.dumps(
                dict(
                    files={
                        "src/market_lab/futures/algopack_paper_predictor_v1.py": core.source.sha(
                            core.source._read(core.Path(core.__file__))
                        ),
                    }
                )
            )
        )
        monkeypatch.setattr(core, "FLOW_ROOT", flow_root)
        monkeypatch.setattr(core.journal, "now", lambda: self.clock)
        monkeypatch.setattr(core.source, "_now", lambda: NOW)
        monkeypatch.setattr(core.source, "verify_seal", lambda _: {})
        monkeypatch.setattr(core.source.time, "sleep", lambda _: None)
        monkeypatch.setattr(core.market.transport, "now", lambda: NOW)
        monkeypatch.setattr(core.market.transport, "check_ca", lambda: None)
        monkeypatch.setattr(core.inference, "load_fixed_models", lambda _: models)
        monkeypatch.setattr(core.journal, "MODEL_SHA", core.inference.MODEL_SHA)

        def fetch(_session, url, _token, _deadline):
            paid = "/datashop/" in url
            raw = payload(url) if not paid else self.flow_payload(url)
            return raw, dict(
                url=url,
                http_status=200,
                bearer_sent=paid,
                request_started_at=NOW.isoformat(),
                response_completed_at=NOW.isoformat(),
                request_elapsed_seconds=0.0,
            )

        monkeypatch.setattr(core.source, "_fetch", fetch)
        result = core.source._capture_locked(
            flow_root, core.WITNESSED_SEAL_SHA, "SYNTHETIC_ONLY", None
        )
        self.capture_id, self.sha = result["capture_id"], result["manifest_sha256"]
        self.flow_ref = core.import_flow(self.root, self.capture_id, self.sha, self.activation)

        class Session:
            def get(_self, url, **_kwargs):
                response = Response(url)
                query = parse_qs(urlsplit(url).query)
                if query["iss.only"] == ["candles"]:
                    data = json.loads(response.raw)
                    rows = []
                    if query["start"] == ["0"]:
                        for offset in range(-7, 0):
                            begin = END + timedelta(minutes=offset * 10, hours=3)
                            rows.append(
                                [
                                    begin.strftime("%Y-%m-%d %H:%M:%S"),
                                    (begin + timedelta(minutes=10, seconds=-1)).strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                    100.0 + offset,
                                    102.0 + offset,
                                    99.0 + offset,
                                    101.0 + offset,
                                    5.0,
                                ]
                            )
                    data["candles"]["data"] = rows
                    response.raw = json.dumps(data).encode()
                return response

        self.market_ref = core.market.capture_packet(
            Session(),
            activation=self.activation,
            root=self.root,
            key="synthetic_market",
            token="SYNTHETIC_ONLY",
        )

    @staticmethod
    def flow_payload(url):
        parts = urlsplit(url).path.split("/")
        dataset, secid = parts[-2], parts[-1].removesuffix(".json")
        asset = core.source.core._outright_asset(secid)
        columns = core.source.core.COMMON + core.source.core.FIELDS[dataset]
        rows = []
        for day, clock in (
            ("2026-09-07", "11:00:00"),
            ("2026-09-08", "10:55:00"),
            ("2026-09-08", "11:00:00"),
            ("2026-09-08", "11:05:00"),
        ):
            row = dict(
                tradedate=day,
                tradetime=clock,
                secid=secid,
                asset_code=core.source.core.ASSETS[asset],
                SYSTIME="2026-09-08 11:03:00",
            )
            row.update({name: 1.0 for name in core.source.core.FIELDS[dataset]})
            rows.append([row[name] for name in columns])
        return json.dumps(
            {
                "data": dict(columns=columns, data=rows),
                "data.cursor": dict(columns=["INDEX", "TOTAL", "PAGESIZE"], data=[[0, 4, 4]]),
            }
        ).encode()

    def predict(self, flow=True):
        return core.predict_slot(
            self.root,
            activation=self.activation,
            information_end=END,
            market_reference=self.market_ref,
            flow_reference=self.flow_ref if flow else None,
        )

    def test_full_capture_flow_prediction_durable_consumption(self):
        self.clock += timedelta(seconds=30)
        ref = self.predict()
        result = core.journal.consume_forecast(self.root, ref, START)
        candidate = result["payload"]
        assert result["state"] == "OBSERVED_NOT_EXECUTION_ADMITTED"
        assert all(arm["status"] == "READY" for arm in candidate["arms"].values())
        assert candidate["arms"]["price_flow"]["prediction"] == [0.001, -0.002, 0.003, -0.004]
        assert len(candidate["source_observations"]) == 2
        assert all(
            row["observed_at"] == self.clock.isoformat() for row in candidate["source_observations"]
        )
        assert candidate["execution_admitted"] is False

    def test_no_flow_preserves_baseline_and_records_sleep(self):
        result = core.journal.consume_forecast(self.root, self.predict(False), START)["payload"]
        assert result["arms"]["price_only"]["status"] == "READY"
        assert result["arms"]["price_flow"]["status"] == "SLEEP_MISSING_FEATURES"
        assert result["arms"]["price_flow"]["prediction"] is None

    def test_projection_excludes_prior_and_uncompleted_vendor_labels(self):
        projection = core.load_flow(self.capture_id, self.sha, self.activation)
        assert len(projection["rows"]) == projection["excluded_uncompleted_or_pre_F"] == 32
        self.clock += timedelta(seconds=20)
        versions = core.observe_flow(self.root, self.flow_ref, self.activation)["versions"]
        assert len(versions) == 32
        assert all(row.available_at == self.clock for row in versions)

    @pytest.mark.parametrize("case", ["raw", "normalized", "manifest_sha", "path"])
    def test_bad_flow_never_produces_forecast(self, case):
        path = core.FLOW_ROOT / self.capture_id
        if case in ("raw", "normalized"):
            name = (
                "BRU6_tradestats_000.json.gz"
                if case == "raw"
                else "BRU6_tradestats_normalized.json.gz"
            )
            (path / name).write_bytes(b"{}")
            with pytest.raises((ValueError, OSError)):
                self.predict()
        else:
            with pytest.raises(ValueError):
                core.load_flow(
                    "../escape" if case == "path" else self.capture_id, "0" * 64, self.activation
                )
        assert not (self.root / "forecast").exists()

    def test_pre_F_capture_rejected_before_full_audit(self, monkeypatch):
        activation = VerifiedActivation(
            self.activation.project, "a" * 64, NOW + timedelta(seconds=1), "b" * 64
        )
        monkeypatch.setattr(core.source, "audit", lambda *_: pytest.fail("pre-F artifact audit"))
        with pytest.raises(ValueError, match="prospective boundary"):
            core.load_flow(self.capture_id, self.sha, activation)

    def test_late_calculation_is_saved_as_missed_not_ready(self, monkeypatch):
        original = core.inference.predict_prepared

        def delayed(*args):
            result = original(*args)
            self.clock = END + timedelta(minutes=10)
            return result

        monkeypatch.setattr(core.inference, "predict_prepared", delayed)
        ref = self.predict()
        saved = core.journal.observe(
            self.root,
            kind="forecast",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=START,
        )["payload"]
        assert all(arm["prediction"] is None for arm in saved["arms"].values())

    def test_duplicate_slot_does_not_overwrite(self):
        ref = self.predict()
        with pytest.raises(FileExistsError):
            self.predict()
        assert (
            core.journal.consume_forecast(self.root, ref, START)["payload"]["arms"]["price_only"][
                "status"
            ]
            == "READY"
        )
