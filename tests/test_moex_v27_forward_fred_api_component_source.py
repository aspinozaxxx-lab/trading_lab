"""Tests for credential-safe official FRED API forward capture."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from market_lab.futures import moex_v27_forward_fred_api_component_source as source


class _Response:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


class _Session:
    def __init__(self, api_key: str, status_code: int = 200) -> None:
        self.api_key = api_key
        self.status_code = status_code

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        assert f"api_key={self.api_key}" in url
        assert headers["User-Agent"].startswith("market-lab-v27-fred-api/")
        assert timeout == 30.0
        payload = json.dumps(
            {
                "realtime_start": "2026-09-02",
                "realtime_end": "2026-09-02",
                "observations": [
                    {"date": "2026-08-21", "value": "-0.8107"},
                    {"date": "2026-08-28", "value": "."},
                ],
            }
        ).encode()
        return _Response(payload, self.status_code)


def test_missing_api_key_fails_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(ValueError, match="FRED_API_KEY is not configured"):
        source.collect(tmp_path, retrieved_at="2026-09-02T12:00:00Z")

    assert not list(tmp_path.glob("snapshot_*"))


def test_authenticated_component_never_persists_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_key = "a" * 32
    monkeypatch.setenv("FRED_API_KEY", api_key)

    snapshot = source.collect(
        tmp_path,
        session=_Session(api_key),
        retrieved_at="2026-09-02T12:00:00Z",
    )
    manifest_bytes = (snapshot / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    audit = source.audit(snapshot)

    assert api_key.encode() not in manifest_bytes
    assert b"api_key" not in manifest_bytes.lower()
    assert manifest["credential_persisted"] is False
    assert manifest["component"] == "macro_fred"
    assert manifest["processed"]["rows"] == 2
    assert all(audit.values())


def test_http_error_is_sanitized_and_does_not_persist_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_key = "b" * 32
    monkeypatch.setenv("FRED_API_KEY", api_key)

    with pytest.raises(RuntimeError) as captured:
        source.collect(
            tmp_path,
            session=_Session(api_key, status_code=403),
            retrieved_at="2026-09-02T12:00:00Z",
        )

    assert api_key not in str(captured.value)
    assert "HTTP 403" in str(captured.value)
    assert not list(tmp_path.glob("snapshot_*"))

