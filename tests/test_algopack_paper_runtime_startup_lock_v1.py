"""Regression: acquire exclusive serving lock before reading any portfolio state."""

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import requests
from test_algopack_paper_journal_v1 import START

from market_lab.futures import algopack_paper_runtime_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


@pytest.mark.parametrize("busy", [False, True])
def test_runtime_constructed_only_after_exclusive_serving_lock(tmp_path, monkeypatch, busy):
    activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
    trace = []
    monkeypatch.setattr(sys, "argv", ["runtime", "--activation-sha256", "a" * 64, "--serve"])
    monkeypatch.setattr(core, "load_activation", lambda *_: activation)
    monkeypatch.setattr(core, "ready", lambda _: None)
    monkeypatch.setattr(core, "DATA_ROOT", tmp_path)
    original = core.os.environ.get
    monkeypatch.setattr(
        core.os.environ,
        "get",
        lambda key, *args: "SYNTHETIC" if key == "MOEX_ALGOPACK_TOKEN" else original(key, *args),
    )

    @contextmanager
    def session():
        yield SimpleNamespace(trust_env=True)

    @contextmanager
    def lock(path):
        assert path == tmp_path / activation.activation_sha256
        trace.append("lock")
        if busy:
            raise BlockingIOError("synthetic competing process")
        yield

    def tick():
        trace.append("tick")
        raise RuntimeError("synthetic stop after one tick")

    def construct(*_):
        trace.append("construct")
        return SimpleNamespace(root=tmp_path / activation.activation_sha256, tick=tick)

    monkeypatch.setattr(requests, "Session", session)
    monkeypatch.setattr(core.bridge.anchors, "transaction", lock)
    monkeypatch.setattr(core, "Runtime", construct)
    assert core.main() == 1
    assert trace == (["lock"] if busy else ["lock", "construct", "tick"])
