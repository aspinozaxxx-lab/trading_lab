"""Synthetic current-day metadata selection, never production flow archives."""

import os
from datetime import timedelta

import pytest
from test_algopack_paper_journal_v1 import END, NOW, START

from market_lab.futures import algopack_paper_flow_selection_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


def test_no_production_activation_no_selection(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        core.select(VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64))


class TestSelection:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.root = tmp_path / "witnessed"
        self.root.mkdir()
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.predictor, "FLOW_ROOT", self.root)
        monkeypatch.setattr(core.journal, "now", lambda: NOW)

    def add(self, start, available, **changes):
        key = start.strftime("%Y%m%dT%H%M%S%fZ") + "_aaaaaaaaaaaa"
        path = self.root / key
        path.mkdir()
        payload = dict(
            capture_id=key,
            protocol_id=core.source.PROTOCOL,
            seal_sha256=core.WITNESSED_SEAL_SHA,
            started_at=start.isoformat(),
            available_at=available.isoformat(),
        )
        payload.update(changes)
        (path / "manifest.json").write_bytes(core.journal.encode(payload))
        return key

    def test_latest_completion_not_latest_start(self):
        older = self.add(END, NOW - timedelta(seconds=1))
        self.add(END + timedelta(minutes=1), NOW - timedelta(seconds=2))
        assert core.select(self.activation)["capture_id"] == older

    def test_future_completion_excluded(self):
        self.add(END, NOW + timedelta(seconds=1))
        assert core.select(self.activation)["state"] == "MISSING_FLOW"

    def test_pre_boundary_and_incomplete_not_read(self):
        old = (START - timedelta(seconds=1)).strftime("%Y%m%dT%H%M%S%fZ") + "_bbbbbbbbbbbb"
        (self.root / old).mkdir()
        (self.root / ".incomplete_synthetic").mkdir()
        assert core.select(self.activation)["candidate_count"] == 0

    def test_bad_metadata_does_not_fall_back(self):
        self.add(END, NOW - timedelta(seconds=2))
        self.add(END + timedelta(minutes=1), NOW - timedelta(seconds=1), seal_sha256="c" * 64)
        with pytest.raises(ValueError, match="metadata"):
            core.select(self.activation)

    def test_no_candidate_returns_missing_reference(self, tmp_path):
        assert core.select_and_import(tmp_path, self.activation)["reference"] is None

    def test_selected_replay_failure_is_not_replaced_by_older_source(self, tmp_path, monkeypatch):
        self.add(END, NOW - timedelta(seconds=2))
        latest = self.add(END + timedelta(minutes=1), NOW - timedelta(seconds=1))
        seen = []

        def fail(root, capture_id, digest, activation):
            seen.append(capture_id)
            raise ValueError("synthetic replay failure")

        monkeypatch.setattr(core.predictor, "import_flow", fail)
        with pytest.raises(ValueError, match="replay"):
            core.select_and_import(tmp_path, self.activation)
        assert seen == [latest]

    @pytest.mark.skipif(os.name != "posix", reason="Linux durable import reuse")
    def test_existing_import_is_replayed_without_overwrite(self, tmp_path, monkeypatch):
        capture = self.add(END, NOW - timedelta(seconds=1))
        root = tmp_path / "market"
        root.mkdir(mode=0o700)
        imports, replays = [], []

        def import_flow(root, capture_id, digest, activation):
            imports.append(capture_id)
            return core.journal.publish(
                root,
                kind="source",
                key="flow_" + capture_id,
                future_start=START,
                payload=dict(projection=dict(manifest_sha256=digest)),
            )

        def observe_flow(root, reference, activation):
            replays.append(reference["key"])
            return dict(source_observation=dict(key=reference["key"]))

        monkeypatch.setattr(core.predictor, "import_flow", import_flow)
        monkeypatch.setattr(core.predictor, "observe_flow", observe_flow)
        first = core.select_and_import(root, self.activation)
        second = core.select_and_import(root, self.activation)
        assert first["reference"]["record_sha256"] == second["reference"]["record_sha256"]
        assert imports == [capture] and replays == ["flow_" + capture]

    def test_partial_import_is_not_overwritten(self, tmp_path, monkeypatch):
        capture = self.add(END, NOW - timedelta(seconds=1))
        (tmp_path / "source" / ("flow_" + capture)).mkdir(parents=True)
        monkeypatch.setattr(core.predictor, "import_flow", lambda *_: pytest.fail("overwrite"))
        with pytest.raises(FileNotFoundError):
            core.select_and_import(tmp_path, self.activation)
