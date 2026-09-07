"""Offline transport, immutable storage and receipt replay regression tests."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import pytest
from test_algopack_fo_witnessed_core_v1 import discovery, encode, job, page

from market_lab.futures import moex_algopack_fo_witnessed_v1 as source

SYNTHETIC_TOKEN = "synthetic-test-not-a-real-credential"


class Response:
    status_code = 200

    def __init__(self, url, raw):
        self.url, self.raw = url, raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.raw


class Session:
    def __init__(self, raw=b"{}"):
        self.raw, self.calls = raw, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(url, self.raw)


@pytest.mark.parametrize("paid", [True, False])
def test_transport_header_and_tls_scope(paid):
    session = Session()
    url = source.core.flow_url(job(), 0) if paid else source.core.metadata_urls()["rfud"]
    raw, receipt = source._fetch(session, url, SYNTHETIC_TOKEN, time.monotonic() + 10)
    assert raw == b"{}" and receipt["bearer_sent"] is paid
    options = session.calls[0][1]
    assert options["allow_redirects"] is False
    assert options["stream"] is True
    assert ("Authorization" in options["headers"]) is paid
    assert options["verify"] == (source.CA_PATH if paid else source.requests.certs.where())
    assert SYNTHETIC_TOKEN not in json.dumps(receipt)


@pytest.mark.parametrize("url", ["https://evil.test/", "http://apim.moex.com/",
                                 "https://apim.moex.com@evil.test/", "https://iss.moex.com/"])
def test_bad_request_never_sends(url):
    session = Session()
    with pytest.raises(source.CaptureFailure):
        source._fetch(session, url, SYNTHETIC_TOKEN, time.monotonic() + 10)
    assert not session.calls


@pytest.mark.parametrize("body", [b"", SYNTHETIC_TOKEN.encode()])
def test_empty_and_reflected_token_not_persistable(body):
    with pytest.raises(source.CaptureFailure, match="empty_or_secret_reflection"):
        source._fetch(Session(body), source.core.flow_url(job(), 0),
                      SYNTHETIC_TOKEN, time.monotonic() + 10)


def test_body_limit(monkeypatch):
    monkeypatch.setitem(source.EXPECTED_CONFIG, "max_response_bytes", 1)
    with pytest.raises(source.CaptureFailure, match="response_limit"):
        source._fetch(Session(b"{}"), source.core.flow_url(job(), 0),
                      SYNTHETIC_TOKEN, time.monotonic() + 10)


def test_redirect_status_rejected(monkeypatch):
    monkeypatch.setattr(Response, "status_code", 302)
    with pytest.raises(source.CaptureFailure, match="http_status_or_redirect"):
        source._fetch(Session(), source.core.flow_url(job(), 0),
                      SYNTHETIC_TOKEN, time.monotonic() + 10)


def test_transport_exception_sanitized():
    class BadSession:
        def get(self, *args, **kwargs):
            raise RuntimeError(SYNTHETIC_TOKEN)

    with pytest.raises(source.CaptureFailure) as failure:
        source._fetch(BadSession(), source.core.flow_url(job(), 0),
                      SYNTHETIC_TOKEN, time.monotonic() + 10)
    assert str(failure.value) == "transport"


@pytest.fixture
def fake_capture(monkeypatch, tmp_path):
    fixed = datetime(2026, 9, 7, 12, tzinfo=UTC)
    monkeypatch.setattr(source, "_now", lambda: fixed)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    metadata = dict(zip(source.core.metadata_urls(), map(encode, discovery()), strict=True))

    def fetch(session, url, token, deadline):
        match = next((name for name, value in source.core.metadata_urls().items()
                      if value == url), None)
        if match:
            raw = metadata[match]
        else:
            path = urlsplit(url).path.split("/")
            secid, dataset = path[-1].removesuffix(".json"), path[-2]
            payload = page(dataset)
            payload["data"]["data"][0][2] = secid
            asset = source.core._outright_asset(secid)
            payload["data"]["data"][0][3] = source.core.ASSETS[asset]
            raw = encode(payload)
        return raw, {"url": url, "http_status": 200, "bearer_sent": match is None,
                     "request_started_at": fixed.isoformat(),
                     "response_completed_at": fixed.isoformat(),
                     "request_elapsed_seconds": 0.0}

    monkeypatch.setattr(source, "_fetch", fetch)
    monkeypatch.setattr(source, "verify_seal", lambda _: {})
    return tmp_path, metadata, fetch


def test_capture_replays_every_response_and_preserves_versions(fake_capture):
    root, _, _ = fake_capture
    result = source._capture_locked(root, "a" * 64, SYNTHETIC_TOKEN, None)
    first = root / result["capture_id"]
    assert result["rows"] == result["pages"] == 16
    assert source.audit(first, "a" * 64)["passed"]
    manifest = source.core._decode((first / "manifest.json").read_bytes())
    assert manifest["bounds"] == {"from": "2026-09-05", "till": "2026-09-21"}
    assert manifest["available_at"] >= manifest["discovery"]["series"]["validated_at"]
    assert not manifest["flags"]["historical_model_eligible"]
    second = source._capture_locked(root, "a" * 64, SYNTHETIC_TOKEN, None)
    assert second["capture_id"] != result["capture_id"]
    assert source.audit(first, "a" * 64)["passed"]
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".gz":
            assert SYNTHETIC_TOKEN.encode() not in path.read_bytes()


@pytest.mark.parametrize("artifact", ["raw", "normalized", "receipt", "plan", "extra", "audit"])
def test_replay_detects_tampering(fake_capture, artifact):
    root, _, _ = fake_capture
    result = source._capture_locked(root, "a" * 64, SYNTHETIC_TOKEN, None)
    path = root / result["capture_id"]
    names = {"raw": "rfud.json.gz", "normalized": "BRU6_tradestats_normalized.json.gz",
             "receipt": "BRU6_tradestats_000.receipt.json", "plan": "plan.json",
             "extra": "unexpected.json", "audit": "audit.json"}
    (path / names[artifact]).write_bytes(b"{}")
    with pytest.raises((ValueError, KeyError, OSError)):
        source.audit(path, "a" * 64)


def test_discovery_failure_keeps_safe_evidence(fake_capture):
    root, metadata, _ = fake_capture
    rfud, _ = discovery()
    rfud["securities"]["data"] = []
    metadata["rfud"] = encode(rfud)
    with pytest.raises(source.CaptureFailure):
        source._capture_locked(root, "a" * 64, SYNTHETIC_TOKEN, None)
    failed = list(root.glob(".incomplete_*"))
    assert len(failed) == 1
    assert (failed[0] / "failure.json").is_file()
    assert (failed[0] / "rfud.json.gz").is_file()
    assert not (failed[0] / "manifest.json").exists()


def test_bad_schema_not_archived(fake_capture):
    root, metadata, _ = fake_capture
    metadata["rfud"] = b'{"marketdata":{"columns":["price"],"data":[]}}'
    with pytest.raises(source.CaptureFailure):
        source._capture_locked(root, "a" * 64, SYNTHETIC_TOKEN, None)
    failed = next(root.glob(".incomplete_*"))
    assert not (failed / "rfud.json.gz").exists()


def test_cursor_revision_preserves_but_does_not_publish(fake_capture, monkeypatch):
    root, _, original = fake_capture
    count = 0

    def fetch(session, url, token, deadline):
        nonlocal count
        raw, receipt = original(session, url, token, deadline)
        if "tradestats/BRU6" in url:
            payload = source.core._decode(raw)
            payload["data.cursor"]["data"][0] = [count, 2 + count, 1]
            payload["data"]["data"][0][1] = f"10:0{count}:00"
            count += 1
            raw = encode(payload)
        return raw, receipt

    monkeypatch.setattr(source, "_fetch", fetch)
    with pytest.raises(source.CaptureFailure, match="pagination_changed"):
        source._capture_locked(root, "a" * 64, SYNTHETIC_TOKEN, None)
    failed = next(root.glob(".incomplete_*"))
    assert (failed / "BRU6_tradestats_001.json.gz").is_file()
    assert not (failed / "manifest.json").exists()


def test_receipt_clock_backward():
    evidence = {"response_completed_at": "2026-09-07T12:00:00+00:00"}
    with pytest.raises(source.CaptureFailure, match="clock_discontinuity"):
        source._receipt(b"{}", evidence, datetime(2026, 9, 7, 11, tzinfo=UTC))


def test_exclusive_write(tmp_path):
    path = tmp_path / "immutable"
    source._write(path, b"first")
    with pytest.raises(FileExistsError):
        source._write(path, b"second")
    assert path.read_bytes() == b"first"


@pytest.mark.skipif(os.name == "nt", reason="Linux runtime lock and symlink semantics")
def test_linux_lock_and_symlinks(tmp_path):
    tmp_path.chmod(0o700)
    with source._lock(tmp_path), pytest.raises(BlockingIOError), source._lock(tmp_path):
        pass
    target = tmp_path / "ordinary"
    target.write_bytes(b"x")
    link = tmp_path / "symlink"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        source._read(link)
    hard = tmp_path / "hardlink"
    os.link(target, hard)
    with pytest.raises(ValueError):
        source._read(target)


def test_artifact_path_escape(tmp_path):
    with pytest.raises(ValueError):
        source._artifact(tmp_path, {"file": "../outside"})


def test_config_and_closure_files_declared():
    assert len(source.REQUIRED_FILES) == 7
    assert source.EXPECTED_CONFIG["lookahead_label_days"] == 14
    assert source.EXPECTED_CONFIG["retries"] == 0
    assert PurePosixPath(source.CA_PATH).is_absolute()


def test_actual_source_seal():
    raw = (source.PROJECT_ROOT / f"configs/{source.PROTOCOL}.seal.json").read_bytes()
    assert len(source.verify_seal(source.sha(raw))["files"]) == 7
    with pytest.raises(ValueError):
        source.verify_seal("0" * 64)


@pytest.mark.parametrize("defect", ["dependency", "missing_file", "config", "sidecar"])
def test_seal_detects_source_drift(tmp_path, monkeypatch, defect):
    seal_path = f"configs/{source.PROTOCOL}.seal.json"
    raw = (source.PROJECT_ROOT / seal_path).read_bytes()
    for relative in source.REQUIRED_FILES | {seal_path}:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source.PROJECT_ROOT / relative).read_bytes())
    monkeypatch.setattr(source, "PROJECT_ROOT", tmp_path)
    names = {"dependency": "pyproject.toml", "config": f"configs/{source.PROTOCOL}.json",
             "sidecar": f"configs/{source.PROTOCOL}.sha256", "missing_file": "pyproject.toml"}
    target = tmp_path / names[defect]
    if defect == "missing_file":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"drift")
    with pytest.raises((ValueError, FileNotFoundError)):
        source.verify_seal(source.sha(raw))
