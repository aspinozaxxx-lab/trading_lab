"""Tests for the CDN-compatible anonymous FRED transport V2."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
import requests

from market_lab.futures import moex_v27_forward_fred_anonymous_transport_v2 as source

CSV = b"observation_date,STLFSI4\n2026-08-21,-0.8107\n2026-08-28,.\n"


class _Response:
    status_code = 200
    content = CSV


class _Session:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        assert "id=STLFSI4" in url
        assert "cosd=" in url and "coed=" in url
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert headers["Accept"] == "text/csv"
        assert headers["Accept-Encoding"] == "identity"
        assert headers["Connection"] == "close"
        assert timeout == 30.0
        if self.fail:
            raise requests.ReadTimeout("synthetic timeout")
        return _Response()


def test_config_changes_only_anonymous_transport_headers() -> None:
    config = source.load_config()
    official = config["official_source"]
    diagnosis = config["transport_diagnosis"]
    assert official["query_and_date_bounds_changed_from_parent"] is False
    assert official["parser_and_output_columns_changed_from_parent"] is False
    assert diagnosis["response_payload_values_read"] is False
    assert config["live_trading_allowed"] is False


def test_collect_and_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-02T22:05:00Z",
    )
    checks = source.audit(snapshot)
    assert all(checks.values())
    assert (snapshot / "raw_fred_stlfsi4.csv.gz").is_file()


def test_transport_failure_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="transport v2 failed"):
        source.collect(
            tmp_path,
            session=_Session(fail=True),
            retrieved_at="2026-09-02T22:05:00Z",
        )
    assert not list(tmp_path.glob("snapshot_*"))
