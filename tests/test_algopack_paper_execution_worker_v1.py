"""Bounded fake children and real source replay/journals; no live requests or fills."""

import os
import sys
from dataclasses import replace
from datetime import timedelta

import pytest
from test_algopack_paper_execution_source_v1 import Session
from test_algopack_paper_execution_source_v1 import runtime as source_fixture
from test_algopack_paper_journal_v1 import NOW
from test_algopack_paper_preparation_worker_v1 import Process

from market_lab.futures import algopack_paper_execution_worker_v1 as core


def test_missing_activation_refuses_cli(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--activation-sha256",
            "a" * 64,
            "--key",
            "async_" + "1" * 32,
            "--kind",
            "quote",
            "--not-before",
            NOW.isoformat(),
            "--deadline",
            (NOW + timedelta(seconds=30)).isoformat(),
        ],
    )
    assert core.main() == 1


@pytest.mark.skipif(os.name != "posix", reason="private Linux source/scheduler journals")
class TestPool:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.activation, _ = source_fixture.__wrapped__(tmp_path, monkeypatch)
        monkeypatch.setattr(core, "ready", lambda _: None)
        monkeypatch.setattr(core.runtime, "DATA_ROOT", tmp_path / "data")
        self.at, self.mono, self.children = NOW, 0, []
        monkeypatch.setattr(core.journal, "now", lambda: self.at)
        monkeypatch.setattr(core.time, "monotonic", lambda: self.mono)
        self.root = core.runtime.DATA_ROOT / self.activation.activation_sha256
        self.root.mkdir(parents=True, mode=0o700)
        for name in ("market", "scheduler"):
            (self.root / name).mkdir(mode=0o700)

        def launch(argv, **kwargs):
            assert "SYNTHETIC" not in str(argv)
            assert kwargs["stdout"] == core.subprocess.DEVNULL
            child = Process()
            self.children.append(child)
            return child

        monkeypatch.setattr(core.subprocess, "Popen", launch)
        self.pool = core.Pool(self.activation)
        self.job = core.Job(
            "async_" + "1" * 32, "quote", NOW, NOW + timedelta(seconds=30), "BR", "BRU6"
        )

    def test_four_owned_children_no_waiting_queue(self):
        for i in range(4):
            assert self.pool.start(replace(self.job, key="async_" + str(i) * 32)) == "STARTED"
        assert self.pool.start(replace(self.job, key="async_" + "5" * 32)) == "POOL_FULL"
        assert self.pool.poll() == [] and len(self.children) == 4

    def test_expire_one_does_not_block_other_children(self):
        self.pool.start(self.job)
        later = replace(self.job, key="async_" + "2" * 32, deadline=NOW + timedelta(seconds=60))
        self.pool.start(later)
        self.at += timedelta(seconds=30)
        assert self.pool.poll() == []
        assert self.children[0].terminated == 1 and self.children[1].terminated == 0
        self.mono += 5
        self.pool.poll()
        assert self.children[0].killed == 1
        self.children[0].code = -9
        assert self.pool.poll()[0]["state"] == "EXPIRED"
        assert len(self.pool.active) == 1

    def test_exit_zero_not_source_admission_or_duplicate(self):
        self.pool.start(self.job)
        self.children[0].code = 0
        assert self.pool.poll() == [dict(key=self.job.key, state="EXITED", source_admitted=False)]
        assert core.Pool(self.activation).start(self.job) == "EXISTING_ATTEMPT"

    def test_source_roundtrip_and_exact_identity(self):
        ref = core.collect(Session(), self.job, self.activation, token="SYNTHETIC")
        result = core.observe(self.job, self.activation)
        assert result["reference"]["record_sha256"] == ref["record_sha256"]
        assert result["execution_admitted"] is False
        with pytest.raises(ValueError, match="identity"):
            core.observe(replace(self.job, secid="BRZ6"), self.activation)

    def test_late_observation_never_admitted(self):
        core.collect(Session(), self.job, self.activation, token="SYNTHETIC")
        self.at = self.job.deadline
        with pytest.raises(ValueError, match="window"):
            core.observe(self.job, self.activation)

    @pytest.mark.parametrize("case", ["early", "span", "key", "route"])
    def test_job_scope_before_spawn(self, case):
        changes = {
            "early": dict(not_before=NOW + timedelta(seconds=1)),
            "span": dict(deadline=NOW + timedelta(minutes=11)),
            "key": dict(key="../escape"),
            "route": dict(kind="prices"),
        }
        with pytest.raises(ValueError):
            self.pool.start(replace(self.job, **changes[case]))
        assert not self.children
