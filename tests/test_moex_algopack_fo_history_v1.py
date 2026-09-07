"""Synthetic resumable history collector tests: no external data or credentials."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from market_lab.futures import moex_algopack_fo_history_v1 as source

SECRET = "synthetic-history-secret"
SEAL = "a" * 64


def _job(dataset: str = "tradestats") -> dict:
    return {
        "job_id": f"{dataset}_SI_SiZ4_2024-10-15_2024-10-15",
        "dataset": dataset,
        "asset_code": "SI",
        "secid": "SiZ4",
        "from": "2024-10-15",
        "till": "2024-10-15",
        "expected_dates": ["2024-10-15"],
    }


def _page(
    dataset: str = "tradestats",
    *,
    start: int = 0,
    total: int = 2,
    stamp: str | None = None,
    changes: dict | None = None,
) -> bytes:
    row = {
        "tradedate": "2024-10-15",
        "tradetime": stamp or f"10:{start * 5:02d}:00",
        "secid": "SiZ4",
        "asset_code": "Si",
        "SYSTIME": "2024-10-15 23:59:59",
        **dict.fromkeys(source.core.FIELDS[dataset], 1),
    }
    row.update(changes or {})
    columns = source.core.EXPECTED_CONFIG["columns"][dataset]
    return json.dumps(
        {
            "data": {
                "columns": columns,
                "data": [[row[field] for field in columns]] if total else [],
            },
            "data.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[start, total, 1]]},
        }
    ).encode()


class FakeSession:
    def __init__(self, responses: list) -> None:
        self.responses = iter(responses)
        self.calls: list[str] = []

    def get(self, url: str, *, headers: dict, timeout: float, allow_redirects: bool) -> object:
        assert headers == {"Authorization": f"Bearer {SECRET}", "Accept": "application/json"}
        assert timeout == 30.0 and allow_redirects is False
        self.calls.append(url)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        status, raw = response if isinstance(response, tuple) else (200, response)
        return SimpleNamespace(status_code=status, content=raw, url=url)


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(source.transport.TOKEN_ENV, SECRET)
    monkeypatch.setattr(
        source.core,
        "verify_seal",
        lambda _: {
            "seal_sha256": SEAL,
            "config_sha256": "b" * 64,
            "files": {"synthetic": "c" * 64},
        },
    )
    monkeypatch.setattr(source.core, "verify_parent_sample", lambda _: {"status": "PASS"})
    monkeypatch.setattr(source.core, "build_plan", lambda _: [_job()])
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    return tmp_path / "storage"


def _paths(root: Path) -> tuple[Path, Path, Path, Path]:
    return source._paths(root, SEAL)


def _interrupt(root: Path) -> Path:
    session = FakeSession([_page(), KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        source.collect(root, SEAL, session=session)
    assert len(session.calls) == 2
    return _paths(root)[1] / "jobs" / _job()["job_id"]


def _finish(root: Path) -> Path:
    return source.collect(root, SEAL, session=FakeSession([_page(), _page(start=1)]))


def _audit(path: Path, root: Path) -> dict:
    return source.audit(path, root, SEAL, source._identity(path / "manifest.json")["sha256"])


def test_complete_source_full_audit_and_false_pit(environment: Path) -> None:
    final = _finish(environment)
    audit = _audit(final, environment)
    assert audit["status"] == "PASS" and audit["rows"] == 2 and audit["pages"] == 2
    assert audit["current_vintage"] is True and audit["historical_model_eligible"] is False
    rows = (final / "jobs" / _job()["job_id"] / "result/rows.jsonl").read_text().splitlines()
    assert all(json.loads(row)["available_at"] is None for row in rows)
    assert not _paths(environment)[1].exists()


def test_resume_skips_committed_page(environment: Path) -> None:
    directory = _interrupt(environment)
    old = (directory / "pages/p000000/raw.json").read_bytes()
    session = FakeSession([_page(start=1)])
    final = source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 1
    assert parse_qs(urlparse(session.calls[0]).query)["start"] == ["1"]
    assert (final / "jobs" / _job()["job_id"] / "pages/p000000/raw.json").read_bytes() == old
    assert _audit(final, environment)["rows"] == 2


@pytest.mark.parametrize("artifact", ["raw", "evidence", "plan", "identity"])
def test_resume_tamper_fails_before_network(environment: Path, artifact: str) -> None:
    directory = _interrupt(environment)
    path = {
        "raw": directory / "pages/p000000/raw.json",
        "evidence": directory / "pages/p000000/evidence.json",
        "plan": _paths(environment)[1] / "plan.json",
        "identity": _paths(environment)[1] / "identity.json",
    }[artifact]
    path.write_bytes(b"{}")
    session = FakeSession([_page(start=1)])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert session.calls == [] and not _paths(environment)[0].exists()


def test_incomplete_page_ignored_preserved_and_requested_again(environment: Path) -> None:
    directory = _interrupt(environment)
    incomplete = directory / "pages/.p000001.synthetic"
    incomplete.mkdir()
    (incomplete / "raw.json").write_bytes(b"incomplete synthetic bytes")
    session = FakeSession([_page(start=1)])
    final = source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 1
    assert not (final / "jobs" / _job()["job_id"] / "pages/.p000001.synthetic").exists()
    quarantine = _paths(environment)[1].parent / f"{_paths(environment)[1].name}.orphans"
    preserved = list(quarantine.glob("orphan.*/artifact/raw.json"))
    assert len(preserved) == 1 and preserved[0].read_bytes() == b"incomplete synthetic bytes"
    assert _audit(final, environment)["pages"] == 2


def test_advisory_lock_blocks_second_owner(environment: Path) -> None:
    lock = _paths(environment)[2]
    session = FakeSession([])
    with source._exclusive_lock(lock), pytest.raises(ValueError, match="locked"):
        source.collect(environment, SEAL, session=session)
    assert session.calls == []
    # Lock file persists, but a released OS lock permits the next run.
    assert _finish(environment).is_dir()


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_status_retried_with_pacing(
    environment: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    sleeps = []
    monkeypatch.setattr(source.time, "sleep", sleeps.append)
    session = FakeSession([(status, SECRET.encode()), _page(total=1)])
    final = source.collect(environment, SEAL, session=session)
    assert sleeps == [0.5, 5, 0.5]
    manifest = source._read(final / "manifest.json")
    assert manifest["committed_page_request_attempts"] == 2
    assert manifest["committed_page_retry_attempts"] == 1
    assert _audit(final, environment)["status"] == "PASS"
    assert all(
        SECRET.encode() not in path.read_bytes() for path in final.rglob("*") if path.is_file()
    )


def test_transport_retries_exhaust_after_four_requests(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps = []
    monkeypatch.setattr(source.time, "sleep", sleeps.append)
    session = FakeSession([RuntimeError(SECRET)] * 4)
    with pytest.raises(source.transport.InventoryFailure) as caught:
        source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 4 and sleeps == [0.5, 5, 0.5, 15, 0.5, 45, 0.5]
    assert SECRET not in str(caught.value)
    failure = next(_paths(environment)[3].glob("*.json"))
    assert SECRET not in failure.read_text() and len(source._read(failure)["attempts"]) == 4


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_auth_and_permanent_status_never_retry_or_persist_body(
    environment: Path, status: int
) -> None:
    session = FakeSession([(status, SECRET.encode())])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 1
    assert not list(_paths(environment)[1].rglob("raw.json"))
    assert all(
        SECRET.encode() not in path.read_bytes()
        for path in environment.rglob("*")
        if path.is_file()
    )


@pytest.mark.parametrize("raw", [b'{"data":{},"data":{}}', b"not-json", SECRET.encode()])
def test_schema_and_echoed_secret_not_retried_or_committed(environment: Path, raw: bytes) -> None:
    session = FakeSession([raw])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 1 and not list(_paths(environment)[1].rglob("raw.json"))


def test_changed_total_retains_prior_page_and_stops(environment: Path) -> None:
    session = FakeSession([_page(), _page(start=1, total=3)])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 2
    assert len(list(_paths(environment)[1].rglob("raw.json"))) == 1


def test_duplicate_keys_across_pages_not_committed(environment: Path) -> None:
    session = FakeSession([_page(), _page(start=1, stamp="10:00:00")])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert len(list(_paths(environment)[1].rglob("raw.json"))) == 1


def test_protected_2026_observation_not_committed(environment: Path) -> None:
    session = FakeSession([_page(total=1, changes={"tradedate": "2026-01-01"})])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 1 and not list(_paths(environment)[1].rglob("raw.json"))


def test_protected_plan_rejected_before_network(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job()
    job.update({"from": "2026-01-01", "till": "2026-01-01", "expected_dates": ["2026-01-01"]})
    monkeypatch.setattr(source.core, "build_plan", lambda _: [job])
    session = FakeSession([])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert session.calls == []


def test_empty_source_terminal_valid_but_not_coverage_admitted(environment: Path) -> None:
    final = source.collect(environment, SEAL, session=FakeSession([_page(total=0)]))
    result = _audit(final, environment)
    assert result["rows"] == 0 and result["pages"] == 1
    assert result["source_date_coverage_admitted"] is False


def test_missing_alias_retained_and_not_admitted(environment: Path) -> None:
    final = source.collect(
        environment, SEAL, session=FakeSession([_page(total=1, changes={"asset_code": None})])
    )
    assert _audit(final, environment)["source_date_coverage_admitted"] is False


def test_existing_canonical_never_collected_again(environment: Path) -> None:
    final = _finish(environment)
    session = FakeSession([])
    with pytest.raises(FileExistsError):
        source.collect(environment, SEAL, session=session)
    assert session.calls == [] and _audit(final, environment)["status"] == "PASS"


@pytest.mark.parametrize("artifact", ["raw", "normalized", "job_manifest", "global_manifest"])
def test_full_raw_audit_detects_each_artifact_tamper(environment: Path, artifact: str) -> None:
    final = _finish(environment)
    expected_sha = source._identity(final / "manifest.json")["sha256"]
    job_dir = final / "jobs" / _job()["job_id"]
    path = {
        "raw": job_dir / "pages/p000000/raw.json",
        "normalized": job_dir / "result/rows.jsonl",
        "job_manifest": job_dir / "result/manifest.json",
        "global_manifest": final / "manifest.json",
    }[artifact]
    path.write_bytes(b"{}\n")
    with pytest.raises(ValueError):
        source.audit(final, environment, SEAL, expected_sha)


def test_rehashed_normalized_values_still_fail_raw_replay(environment: Path) -> None:
    final = _finish(environment)
    directory = final / "jobs" / _job()["job_id"] / "result"
    path = directory / "rows.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[0]["vol"] = 999
    path.write_bytes(b"".join(source._json(row) for row in rows))
    manifest = source._read(directory / "manifest.json")
    manifest["normalized"] = {**source._identity(path), "rows": len(rows)}
    (directory / "manifest.json").write_bytes(source._json(manifest))
    with pytest.raises(ValueError):
        _audit(final, environment)


def test_parent_sample_checked_before_network_on_resume(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interrupt(environment)

    def rejected(_: Path) -> dict:
        raise ValueError("synthetic parent differs")

    monkeypatch.setattr(source.core, "verify_parent_sample", rejected)
    session = FakeSession([])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert session.calls == []


def test_tamper_in_later_job_checked_before_earlier_job_requests(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = [_job(), _job("obstats")]
    monkeypatch.setattr(source.core, "build_plan", lambda _: jobs)
    session = FakeSession([_page(total=1), _page("obstats"), KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        source.collect(environment, SEAL, session=session)
    work = _paths(environment)[1]
    raw = work / "jobs" / jobs[1]["job_id"] / "pages/p000000/raw.json"
    raw.write_bytes(b"{}")
    resumed = FakeSession([])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=resumed)
    assert resumed.calls == []


def test_completed_pages_without_result_resume_without_network(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source._commit_result

    def interrupted(*args: object) -> dict:
        raise KeyboardInterrupt()

    monkeypatch.setattr(source, "_commit_result", interrupted)
    with pytest.raises(KeyboardInterrupt):
        source.collect(environment, SEAL, session=FakeSession([_page(total=1)]))
    monkeypatch.setattr(source, "_commit_result", original)
    session = FakeSession([])
    final = source.collect(environment, SEAL, session=session)
    assert session.calls == [] and _audit(final, environment)["rows"] == 1


def test_interruption_before_final_rename_recovers_without_token(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source._publish

    def interrupted(temporary: Path, destination: Path) -> None:
        if destination == _paths(environment)[0]:
            raise KeyboardInterrupt()
        original(temporary, destination)

    monkeypatch.setattr(source, "_publish", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _finish(environment)
    monkeypatch.setattr(source, "_publish", original)
    monkeypatch.delenv(source.transport.TOKEN_ENV)
    session = FakeSession([])
    final = source.collect(environment, SEAL, session=session)
    assert session.calls == [] and _audit(final, environment)["status"] == "PASS"


def test_page_limit_stops_without_extra_request(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = copy.deepcopy(source.core.EXPECTED_CONFIG)
    config["max_pages_per_job"] = 1
    monkeypatch.setattr(source.core, "EXPECTED_CONFIG", config)
    session = FakeSession([_page()])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert len(session.calls) == 1


def test_progress_and_failure_stdout_never_show_values_or_secret(
    environment: Path, capsys: pytest.CaptureFixture
) -> None:
    final = source.collect(
        environment, SEAL, session=FakeSession([_page(total=1, changes={"vol": 987654321})])
    )
    output = capsys.readouterr().out
    assert SECRET not in output and "987654321" not in output
    assert json.loads(output)["status"] == "job_complete"
    assert _audit(final, environment)["historical_model_eligible"] is False


def test_orphan_foreign_payload_never_enters_canonical(environment: Path) -> None:
    directory = _interrupt(environment)
    incomplete = directory / ".result.foreign"
    incomplete.mkdir()
    (incomplete / "unparsed.txt").write_bytes(b"opaque foreign payload")
    final = source.collect(environment, SEAL, session=FakeSession([_page(start=1)]))
    assert not list(final.rglob("unparsed.txt"))
    quarantine = _paths(environment)[1].parent / f"{_paths(environment)[1].name}.orphans"
    assert len(list(quarantine.glob("orphan.*/artifact/unparsed.txt"))) == 1
    assert _audit(final, environment)["status"] == "PASS"


def test_orphan_descendant_symlink_preserved_outside_canonical(
    environment: Path, tmp_path: Path
) -> None:
    directory = _interrupt(environment)
    incomplete = directory / "pages/.p000001.foreign"
    incomplete.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"do not open")
    try:
        (incomplete / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit synthetic symlinks")
    final = source.collect(environment, SEAL, session=FakeSession([_page(start=1)]))
    assert not list(final.rglob("link.txt"))
    assert outside.read_bytes() == b"do not open"
    assert _audit(final, environment)["status"] == "PASS"


@pytest.mark.parametrize("location", ["page", "result", "job", "manifest"])
def test_canonical_audit_rejects_incomplete_orphans(environment: Path, location: str) -> None:
    final = _finish(environment)
    directory = final / "jobs" / _job()["job_id"]
    target = {
        "page": directory / "pages/.p000002.synthetic",
        "result": directory / ".result.synthetic",
        "job": final / "jobs" / f".{_job()['job_id']}.synthetic",
        "manifest": final / ".manifest.synthetic",
    }[location]
    if location == "manifest":
        target.write_bytes(b"opaque")
    else:
        target.mkdir()
    with pytest.raises(ValueError):
        _audit(final, environment)


def test_page_gap_stops_resume_before_network(environment: Path) -> None:
    directory = _interrupt(environment)
    (directory / "pages/p000000").rename(directory / "pages/p000001")
    session = FakeSession([])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert session.calls == []


def test_attempt_evidence_boolean_integer_confusion_rejected(environment: Path) -> None:
    directory = _interrupt(environment)
    path = directory / "pages/p000000/evidence.json"
    evidence = source._read(path)
    evidence["attempts"][0]["attempt"] = True
    path.write_bytes(source._json(evidence))
    session = FakeSession([])
    with pytest.raises(source.transport.InventoryFailure):
        source.collect(environment, SEAL, session=session)
    assert session.calls == []


def test_closure_change_during_collection_cannot_publish(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 0

    def changed(_: str) -> dict:
        nonlocal count
        count += 1
        return {
            "seal_sha256": SEAL,
            "config_sha256": ("b" if count == 1 else "d") * 64,
            "files": {"synthetic": "c" * 64},
        }

    monkeypatch.setattr(source.core, "verify_seal", changed)
    with pytest.raises(source.transport.InventoryFailure):
        _finish(environment)
    assert count == 2 and not _paths(environment)[0].exists()
