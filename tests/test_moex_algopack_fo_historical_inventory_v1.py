"""Synthetic metadata-only FO inventory and credential-boundary tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from market_lab.futures import moex_algopack_fo_historical_inventory_v1 as source

SECRET = "synthetic-token-never-real"


def _row(secid: str = "SIZ4", stamp: str = "10:05:00") -> list[str]:
    return ["2024-10-15", stamp, secid, "SI", "2026-09-07 09:00:00"]


def _page(rows: list[list[str]], *, start: int = 0, total: int | None = None,
          size: int = 2) -> bytes:
    return json.dumps({
        "data": {"columns": source.COLUMNS, "data": rows},
        "data.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"],
                        "data": [[start, len(rows) if total is None else total, size]]},
    }).encode()


class FakeSession:
    def __init__(self, responses: list[bytes], *, status: int = 200) -> None:
        self.responses = iter(responses)
        self.status = status
        self.calls: list[str] = []

    def get(self, url: str, *, headers: dict, timeout: float, allow_redirects: bool) -> object:
        assert headers["Authorization"] == f"Bearer {SECRET}"
        assert timeout == 30.0
        assert allow_redirects is False
        self.calls.append(url)
        return SimpleNamespace(status_code=self.status, content=next(self.responses), url=url)


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    files = {}
    for relative in (
        source.MODULE_RELATIVE, "src/market_lab/__init__.py", "src/market_lab/futures/__init__.py",
    ):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Synthetic closure member\n")
        files[relative] = source.sha(path.read_bytes())
    config_path = repository / source.CONFIG_RELATIVE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_raw = yaml.safe_dump(source.EXPECTED_CONFIG).encode()
    config_path.write_bytes(config_raw)
    files[source.CONFIG_RELATIVE] = source.sha(config_raw)
    config_path.with_suffix(".sha256").write_text(source.sha(config_raw), encoding="utf-8")
    seal = json.dumps({"protocol_id": source.PROTOCOL, "files": files}).encode()
    (repository / f"configs/{source.PROTOCOL}.seal.json").write_bytes(seal)
    monkeypatch.setattr(source, "PROJECT_ROOT", repository)
    monkeypatch.setenv(source.TOKEN_ENV, SECRET)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    return tmp_path / "storage", source.sha(seal)


def test_urls_are_fixed_historical_metadata_only() -> None:
    for dataset in ("tradestats", "obstats"):
        parsed = urlparse(source.request_url(dataset, 200))
        query = parse_qs(parsed.query)
        assert parsed.netloc == "apim.moex.com"
        assert query["date"] == ["2024-10-15"]
        assert query["latest"] == ["0"]
        assert query["start"] == ["200"]
        assert query["data.columns"] == [",".join(source.COLUMNS)]
        assert query["iss.only"] == ["data,data.cursor"]
    with pytest.raises(ValueError):
        source.request_url("../tradestats", 0)


def test_current_revision_clock_does_not_change_historical_sample_date() -> None:
    rows, cursor = source.parse_page(_page([_row()]), "tradestats", 0)
    assert rows[0]["SYSTIME"].startswith("2026-")
    assert rows[0]["tradedate"] == "2024-10-15"
    assert cursor["TOTAL"] == 1


@pytest.mark.parametrize("field,value", [
    (0, "2026-01-01"), (1, "25:00:00"), (2, "../SIZ4"), (3, ""),
    (4, "2024-10-15 09:00:00"),
])
def test_invalid_metadata_rows_fail_closed(field: int, value: str) -> None:
    row = _row()
    row[field] = value
    with pytest.raises(ValueError):
        source.parse_page(_page([row]), "tradestats", 0)


def test_duplicate_rows_and_wrong_columns_fail_closed() -> None:
    with pytest.raises(ValueError):
        source.parse_page(_page([_row(), _row()]), "tradestats", 0)
    payload = json.loads(_page([_row()]))
    payload["data"]["columns"].append("price")
    payload["data"]["data"][0].append("999")
    with pytest.raises(ValueError):
        source.parse_page(json.dumps(payload).encode(), "tradestats", 0)


def test_wrong_cursor_and_truncated_page_fail_closed() -> None:
    for raw in (_page([_row()], start=1), _page([_row()], total=2)):
        with pytest.raises(ValueError):
            source.parse_page(raw, "tradestats", 0)


def test_seal_is_checked_before_network(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    session = FakeSession([])
    with pytest.raises(ValueError):
        source.collect(storage, "0" * 64, session=session)
    assert session.calls == []
    assert source.verify_seal(seal_sha)["seal_sha256"] == seal_sha


def test_complete_inventory_replays_and_never_persists_secret(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    session = FakeSession([
        _page([_row(), _row("RIZ4")], total=3),
        _page([_row("MXZ4")], start=2, total=3),
        _page([_row(), _row("BRX4")]),
    ])
    output = source.collect(storage, seal_sha, session=session)
    manifest_raw = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["dataset_rows"] == {"tradestats": 3, "obstats": 2}
    assert len(session.calls) == 3
    assert all(source.audit(output, seal_sha, source.sha(manifest_raw)).values())
    for path in output.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
    for row in json.loads((output / "inventory.json").read_bytes()):
        assert row["available_at"] is None
        assert row["original_version_verified"] is False
        assert row["historical_model_eligible"] is False
    with pytest.raises(FileExistsError):
        source.collect(storage, seal_sha, session=FakeSession([]))


def test_empty_inventory_is_explicit_not_missing(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession([_page([]), _page([])]))
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["empty_datasets"] == ["tradestats", "obstats"]
    assert manifest["dataset_rows"] == {"tradestats": 0, "obstats": 0}


def test_changed_total_or_cross_page_duplicate_blocks_publication(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    session = FakeSession([
        _page([_row(), _row("RIZ4")], total=3),
        _page([_row("MXZ4"), _row("BRX4")], start=2, total=4),
    ])
    with pytest.raises(ValueError):
        source.collect(storage, seal_sha, session=session)
    assert not list(storage.rglob("manifest.json"))


def test_raw_tamper_is_detected(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession([_page([]), _page([])]))
    digest = source.sha((output / "manifest.json").read_bytes())
    (output / "raw_tradestats_000.json").write_bytes(b"{}")
    with pytest.raises(ValueError):
        source.audit(output, seal_sha, digest)


def test_token_reflection_and_http_error_never_persist(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    for status in (200, 401, 302):
        session = FakeSession([SECRET.encode()], status=status)
        with pytest.raises(ValueError) as error:
            source.collect(storage, seal_sha, session=session)
        assert SECRET not in str(error.value)
    for path in storage.rglob("*.json"):
        assert path.name == "failure.json"
        assert SECRET.encode() not in path.read_bytes()


def test_noncanonical_host_rejected_before_network() -> None:
    session = FakeSession([])
    with pytest.raises(ValueError):
        source._fetch(session, "https://example.invalid/", SECRET)
    assert session.calls == []


def test_missing_token_never_starts_network(
    sealed: tuple[Path, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage, seal_sha = sealed
    monkeypatch.delenv(source.TOKEN_ENV)
    session = FakeSession([])
    with pytest.raises(ValueError):
        source.collect(storage, seal_sha, session=session)
    assert session.calls == []


def test_unknown_page_dataset_and_duplicate_paths_fail_replay(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession([_page([]), _page([])]))
    pages = json.loads((output / "manifest.json").read_bytes())["pages"]
    with pytest.raises(ValueError, match="unknown"):
        source._replay(output, [*pages, {**pages[0], "dataset": "unknown"}])
    with pytest.raises(ValueError, match="duplicate"):
        source._replay(output, [*pages, pages[0]])


def test_http403_has_safe_actionable_failure_evidence(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    with pytest.raises(source.InventoryFailure) as error:
        source.collect(storage, seal_sha, session=FakeSession([SECRET.encode()], status=403))
    assert error.value.http_status == 403
    assert error.value.phase == "http_status"
    assert error.value.diagnostic_path is not None
    diagnostic = Path(error.value.diagnostic_path).read_bytes()
    assert SECRET.encode() not in diagnostic
    assert json.loads(diagnostic) == {
        "status": "failed_no_canonical_output", "phase": "http_status",
        "dataset": "tradestats", "start": 0, "http_status": 403,
        "failed_response_raw_saved": False, "validated_pages_saved": 0,
    }
    assert not list(storage.rglob("raw_*.json"))


def test_transport_manifest_evidence_is_replayed(sealed: tuple[Path, str]) -> None:
    storage, seal_sha = sealed
    output = source.collect(storage, seal_sha, session=FakeSession([_page([]), _page([])]))
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert all(page["bearer_sent"] is True for page in manifest["pages"])
    assert all(page["http_status"] == 200 for page in manifest["pages"])
    for field, value in (("bearer_sent", False), ("http_status", 403), ("final_url", "bad")):
        pages = [{**page} for page in manifest["pages"]]
        pages[0][field] = value
        with pytest.raises(ValueError, match="transport evidence"):
            source._replay(output, pages)
