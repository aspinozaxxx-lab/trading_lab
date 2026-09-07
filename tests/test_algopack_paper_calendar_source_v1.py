"""Fake HTTP, synthetic authority and real Linux durable journals; no actual API."""

import copy
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from test_algopack_paper_execution_source_v1 import Response
from test_algopack_paper_journal_v1 import NOW, START

from market_lab.futures import algopack_paper_calendar_source_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation


class Session:
    trust_env = False
    auth = None

    def __init__(self, bad=None, fail_after=None):
        self.calls, self.bad, self.fail_after = [], bad, fail_after

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        rows = (
            []
            if parse_qs(urlsplit(url).query)["start"] == ["1"]
            else [["2026-09-08", 1, None, "N", "2026-09-08 08:00:00"]]
        )
        raw = json.dumps({"off_days": {"columns": core.core.COLUMNS, "data": rows}}).encode()
        status = 403 if self.fail_after is not None and len(self.calls) > self.fail_after else 200
        return Response(url, raw if self.bad is None else self.bad, status)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(VerifiedActivation, "request_ready", lambda _: None)
    monkeypatch.setattr(core.journal, "now", lambda: NOW)
    monkeypatch.setattr(core.transport, "check_ca", lambda: None)
    monkeypatch.setattr(core.time, "sleep", lambda _: None)
    (tmp_path / "configs").mkdir()
    modules = (
        core.__file__,
        core.core.__file__,
        core.source.__file__,
        core.source.execution.__file__,
    )
    files = {
        "src/market_lab/futures/" + Path(name).name: hashlib.sha256(
            Path(name).read_bytes()
        ).hexdigest()
        for name in modules
    }
    raw = json.dumps({"files": files}).encode()
    (tmp_path / core.BUNDLE).write_bytes(raw)
    activation = VerifiedActivation(tmp_path, "a" * 64, START, hashlib.sha256(raw).hexdigest())
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    return activation, root


def test_fetch_replay_tls_and_no_secret(runtime):
    activation, _ = runtime
    session = Session()
    step = core.fetch(session, activation, token="SYNTHETIC", start=0)
    page, window = core.replay_step(step, activation)
    assert core.core.parse_page(page, window)[0]["status"] == "OPEN"
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["verify"] == str(core.transport.CA_PATH)
    assert "SYNTHETIC" not in json.dumps(step)


@pytest.mark.parametrize("case", ["normalization", "raw", "url", "day", "chronology"])
def test_altered_receipt_rejected(runtime, case):
    activation, _ = runtime
    step = core.fetch(Session(), activation, token="SYNTHETIC", start=0)
    if case == "normalization":
        step["normalized"][0]["status"] = "CLOSED"
    elif case == "raw":
        step["raw_sha256"] = "b" * 64
    elif case == "url":
        step["url"] = "https://example.com/"
    elif case == "day":
        step["day"] = "2026-09-09"
    else:
        step["validated_at"] = START.isoformat()
    with pytest.raises(ValueError):
        core.replay_step(step, activation)


@pytest.mark.parametrize("bad", [b"", b"SYNTHETIC", b"{}"])
def test_bad_response_sanitized(runtime, bad):
    activation, _ = runtime
    with pytest.raises(core.transport.CaptureFailure, match="^calendar_fetch$"):
        core.fetch(Session(bad), activation, token="SYNTHETIC", start=0)


def test_missing_closure_and_ambient_auth_no_http(runtime):
    activation, _ = runtime
    session = Session()
    session.trust_env = True
    with pytest.raises(core.transport.CaptureFailure):
        core.fetch(session, activation, token="SYNTHETIC", start=0)
    session.trust_env = False
    (activation.project / core.BUNDLE).write_bytes(b"{}")
    with pytest.raises(ValueError):
        core.fetch(session, activation, token="SYNTHETIC", start=0)
    assert not session.calls


@pytest.mark.skipif(os.name != "posix", reason="real private Linux journal")
class TestDurable:
    def test_capture_full_replay_and_no_overwrite(self, runtime):
        activation, root = runtime
        session = Session()
        ref = core.collect(session, root, "calendar", activation, token="SYNTHETIC")
        result = core.observe(root, ref, activation)
        assert len(session.calls) == 2
        assert result["rows"][0]["status"] == "OPEN"
        assert result["calendar_source_verified"] is False
        with pytest.raises(FileExistsError):
            core.collect(session, root, "calendar", activation, token="SYNTHETIC")
        assert len(session.calls) == 2

    def test_partial_failure_is_retained(self, runtime):
        activation, root = runtime
        with pytest.raises(core.transport.CaptureFailure):
            core.collect(Session(fail_after=1), root, "partial", activation, token="SYNTHETIC")
        assert (root / "source" / "partial_p0" / "COMMITTED.json").is_file()
        assert (root / "source" / "partial_failed" / "COMMITTED.json").is_file()
        assert not (root / "source" / "partial").exists()

    def test_corrupt_saved_page_rejected(self, runtime):
        activation, root = runtime
        ref = core.collect(Session(), root, "calendar", activation, token="SYNTHETIC")
        path = root / "source" / "calendar_p0" / "payload.json"
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError):
            core.observe(root, ref, activation)

    def test_hash_valid_wrong_normalization_rejected(self, runtime):
        activation, root = runtime
        ref = core.collect(Session(), root, "original", activation, token="SYNTHETIC")
        event = core.journal.observe(
            root,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=START,
        )
        payload = copy.deepcopy(event["payload"])
        for index, old in enumerate(payload["steps"]):
            part = core.journal.observe(
                root,
                kind="source",
                key=old["key"],
                record_sha256=old["record_sha256"],
                future_start=START,
            )["payload"]
            if index == 0:
                part["step"]["normalized"][0]["status"] = "CLOSED"
            payload["steps"][index] = core.journal.publish(
                root, kind="source", key=f"forged_p{index}", future_start=START, payload=part
            )
        forged = core.journal.publish(
            root, kind="source", key="forged", future_start=START, payload=payload
        )
        with pytest.raises(ValueError, match="normalization"):
            core.observe(root, forged, activation)
