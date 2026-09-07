"""Synthetic sealed runner tests; no market artifacts, credentials, or network."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_algopack_fo_history_quality_v1.py"
SPEC = importlib.util.spec_from_file_location("quality_runner_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(runner, "PROJECT_ROOT", repo)
    parent_files = {}
    for index in range(21):
        name = f"parent/dependency_{index}.txt"
        _write(repo / name, f"synthetic dependency {index}".encode())
        parent_files[name] = runner.quality._hash(repo / name)
    parent_raw = runner.history._json({"files": parent_files})
    _write(repo / runner.PARENT_SEAL_PATH, parent_raw)
    parent_sha = runner.core.sha(parent_raw)
    monkeypatch.setattr(runner, "PARENT_SEAL_SHA", parent_sha)
    monkeypatch.setattr(
        runner.core,
        "verify_seal",
        lambda digest: {"seal_sha256": digest, "files": parent_files},
    )
    config = runner.expected_config("a" * 64)
    for relative in runner.NEW_FILES - {runner.CONFIG_PATH, runner.SIDECAR_PATH}:
        _write(repo / relative, b"synthetic sealed code")

    def reseal(config_value=None, change_files=None):
        payload = config if config_value is None else config_value
        raw = runner.history._json(payload)
        _write(repo / runner.CONFIG_PATH, raw)
        _write(
            repo / runner.SIDECAR_PATH,
            f"{runner.core.sha(raw)}  {Path(runner.CONFIG_PATH).name}\n".encode(),
        )
        files = dict(parent_files)
        for name in runner.NEW_FILES | {runner.PARENT_SEAL_PATH}:
            files[name] = runner.quality._hash(repo / name)
        if change_files:
            change_files(files)
        seal = {"protocol_id": runner.PROTOCOL, "source_only": True, "files": files}
        seal_raw = runner.history._json(seal)
        _write(repo / runner.SEAL_PATH, seal_raw)
        return runner.core.sha(seal_raw)

    digest = reseal()
    storage = tmp_path / "storage"
    (storage / runner.SOURCE_PATH).mkdir(parents=True)
    return SimpleNamespace(
        repo=repo,
        storage=storage,
        digest=digest,
        config=config,
        reseal=reseal,
        parent_files=parent_files,
    )


def _audit(config):
    return {
        "status": "PASS",
        "protocol_id": runner.core.PROTOCOL,
        "manifest_sha256": config["source"]["manifest_sha256"],
        "jobs": 294,
        "rows": 123,
        "pages": 294,
        "source_date_coverage_admitted": False,
        **runner.quality.FLAGS,
    }


def _report(config):
    return {
        "protocol_id": runner.PROTOCOL,
        "status": "metadata_report_complete",
        "source_protocol_id": runner.core.PROTOCOL,
        "source_manifest_sha256": config["source"]["manifest_sha256"],
        "source_closure": {"seal_sha256": runner.PARENT_SEAL_SHA},
        "metadata_columns_read": list(runner.quality.METADATA_COLUMNS),
        "full_raw_replay_performed": False,
        "requires_separate_history_audit": True,
        "totals": {
            "job_count": 294,
            "rows": 123,
            "pages": 294,
            "source_date_coverage_admitted": False,
        },
        **runner.quality.FLAGS,
    }


def _mock_work(monkeypatch, sealed, audit=None, report=None):
    events = []

    def replay(source, storage, source_sha, manifest_sha):
        assert source == sealed.storage / runner.SOURCE_PATH
        assert storage == sealed.storage
        assert source_sha == runner.PARENT_SEAL_SHA
        assert manifest_sha == sealed.config["source"]["manifest_sha256"]
        events.append("audit")
        return copy.deepcopy(_audit(sealed.config) if audit is None else audit)

    def metadata(source, manifest_sha):
        assert events == ["audit"]
        assert source == sealed.storage / runner.SOURCE_PATH
        assert manifest_sha == sealed.config["source"]["manifest_sha256"]
        events.append("metadata")
        return copy.deepcopy(_report(sealed.config) if report is None else report)

    monkeypatch.setattr(runner.history, "audit", replay)
    monkeypatch.setattr(runner.quality, "build_report", metadata)
    return events


def test_fixed_seal_and_transitive_parent_pass(sealed):
    verified = runner.verify_seal(sealed.digest)
    assert verified["config"] == sealed.config
    assert len(verified["files"]) == 28


@pytest.mark.parametrize("digest", ["x" * 64, "a" * 63, "A" * 64, "../invalid"])
def test_invalid_seal_sha_rejected(sealed, digest):
    with pytest.raises(ValueError):
        runner.verify_seal(digest)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda config: config.update(expected_jobs=293),
        lambda config: config.update(expected_pairs=True),
        lambda config: config.update(historical_model_eligible=True),
        lambda config: config.update(source_only=1),
        lambda config: config.update(output_parent="../escaped"),
        lambda config: config.update(metadata_columns=["vol"]),
        lambda config: config["source"].update(path="data/processed/other"),
        lambda config: config["source"].update(seal_sha256="b" * 64),
        lambda config: config["source"].update(manifest_sha256="bad"),
    ],
)
def test_frozen_config_rejected_even_with_new_hashes(sealed, mutation):
    config = copy.deepcopy(sealed.config)
    mutation(config)
    digest = sealed.reseal(config)
    with pytest.raises(ValueError):
        runner.verify_seal(digest)


@pytest.mark.parametrize(
    "change_files",
    [
        lambda files: files.pop(next(iter(runner.NEW_FILES))),
        lambda files: files.update({"parent/dependency_0.txt": "f" * 64}),
        lambda files: files.update({"../escape.txt": "f" * 64}),
    ],
)
def test_closure_omission_parent_drift_or_extra_path_rejected(sealed, change_files):
    digest = sealed.reseal(change_files=change_files)
    with pytest.raises(ValueError):
        runner.verify_seal(digest)


def test_dependency_tamper_rejected(sealed):
    (sealed.repo / "parent/dependency_0.txt").write_bytes(b"changed")
    with pytest.raises(ValueError):
        runner.verify_seal(sealed.digest)


def test_duplicate_json_key_rejected(sealed):
    with pytest.raises(ValueError, match="duplicate"):
        runner._load(b'{"status":1,"status":2}')


def test_run_audits_before_projection_and_report_writes(sealed, monkeypatch, capsys):
    events = _mock_work(monkeypatch, sealed)
    original_write = runner.history._write

    def checked_write(path, raw):
        assert events == ["audit", "metadata"]
        original_write(path, raw)

    monkeypatch.setattr(runner.history, "_write", checked_write)
    output = runner.run(sealed.storage, sealed.digest)
    assert {path.name for path in output.iterdir()} == {
        "audit.json",
        "quality.json",
        "manifest.json",
    }
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["jobs_completed_and_replay_audited"] == 294
    assert manifest["historical_model_eligible"] is False
    assert json.loads((output / "audit.json").read_bytes()) == _audit(sealed.config)
    for name, identity in manifest["artifacts"].items():
        assert identity == runner.history._identity(output / name)
    phases = [json.loads(line)["phase"] for line in capsys.readouterr().out.splitlines()]
    assert phases == ["raw_replay", "metadata_projection", "publish"]


def test_parent_verifier_must_independently_agree(sealed, monkeypatch):
    monkeypatch.setattr(
        runner.core, "verify_seal", lambda digest: {"seal_sha256": digest, "files": {}}
    )
    with pytest.raises(ValueError, match="parent verification"):
        runner.verify_seal(sealed.digest)


def test_code_change_during_projection_prevents_writing(sealed, monkeypatch):
    _mock_work(monkeypatch, sealed)

    def changing_report(*args):
        (sealed.repo / "parent/dependency_0.txt").write_bytes(b"changed during reporting")
        return _report(sealed.config)

    monkeypatch.setattr(runner.quality, "build_report", changing_report)
    with pytest.raises(ValueError, match="byte identity"):
        runner.run(sealed.storage, sealed.digest)
    assert list((sealed.storage / runner.OUTPUT_PARENT).glob("*.staging-*")) == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "FAIL"),
        ("jobs", 293),
        ("jobs", True),
        ("manifest_sha256", "b" * 64),
        ("protocol_id", "other"),
        ("source_only", 1),
        ("historical_model_eligible", True),
        ("rows", -1),
    ],
)
def test_audit_failure_prevents_projection_or_report_writes(sealed, monkeypatch, key, value):
    audit = _audit(sealed.config)
    audit[key] = value
    events = _mock_work(monkeypatch, sealed, audit=audit)
    with pytest.raises(ValueError):
        runner.run(sealed.storage, sealed.digest)
    assert events == ["audit"]
    assert list((sealed.storage / runner.OUTPUT_PARENT).glob("*.json")) == []
    assert list((sealed.storage / runner.OUTPUT_PARENT).glob("*.staging-*")) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.update(live_trading_allowed=True),
        lambda report: report.update(source_manifest_sha256="b" * 64),
        lambda report: report.update(full_raw_replay_performed=True),
        lambda report: report["totals"].update(rows=124),
        lambda report: report["totals"].update(job_count=True),
        lambda report: report["totals"].update(source_date_coverage_admitted=True),
    ],
)
def test_report_mismatch_prevents_publication(sealed, monkeypatch, mutation):
    report = _report(sealed.config)
    mutation(report)
    _mock_work(monkeypatch, sealed, report=report)
    with pytest.raises(ValueError):
        runner.run(sealed.storage, sealed.digest)
    destination = sealed.storage / runner.OUTPUT_PARENT / f"{runner.PROTOCOL}_{sealed.digest[:12]}"
    assert not destination.exists()


def test_existing_canonical_is_never_replaced(sealed, monkeypatch):
    events = _mock_work(monkeypatch, sealed)
    output = runner.run(sealed.storage, sealed.digest)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.run(sealed.storage, sealed.digest)
    assert (output / "manifest.json").read_bytes() == before
    assert events == ["audit", "metadata"]


def test_write_failure_preserves_staging_without_canonical(sealed, monkeypatch):
    _mock_work(monkeypatch, sealed)
    original = runner.history._write

    def fail_second(path, raw):
        if path.name == "quality.json":
            raise OSError("synthetic failure")
        original(path, raw)

    monkeypatch.setattr(runner.history, "_write", fail_second)
    with pytest.raises(OSError):
        runner.run(sealed.storage, sealed.digest)
    parent = sealed.storage / runner.OUTPUT_PARENT
    stages = list(parent.glob("*.staging-*"))
    assert len(stages) == 1 and (stages[0] / "audit.json").is_file()
    assert not (parent / f"{runner.PROTOCOL}_{sealed.digest[:12]}").exists()


def test_quality_lock_is_distinct_and_exclusive(sealed, monkeypatch):
    events = _mock_work(monkeypatch, sealed)
    destination, lock = runner._output_paths(sealed.storage, sealed.digest)
    assert lock.parent == destination.parent == sealed.storage / runner.OUTPUT_PARENT
    with runner.history._exclusive_lock(lock), pytest.raises(ValueError, match="locked"):
        runner.run(sealed.storage, sealed.digest)
    assert events == []


def test_unexpected_staging_child_prevents_publication(sealed, monkeypatch):
    _mock_work(monkeypatch, sealed)
    original = runner.history._write

    def write_with_extra(path, raw):
        original(path, raw)
        if path.name == "manifest.json":
            (path.parent / "unexpected.txt").write_bytes(b"synthetic extra")

    monkeypatch.setattr(runner.history, "_write", write_with_extra)
    with pytest.raises(ValueError, match="unexpected children"):
        runner.run(sealed.storage, sealed.digest)
    parent = sealed.storage / runner.OUTPUT_PARENT
    stages = list(parent.glob("*.staging-*"))
    assert len(stages) == 1 and (stages[0] / "unexpected.txt").is_file()
    assert not (parent / f"{runner.PROTOCOL}_{sealed.digest[:12]}").exists()


def test_relative_storage_root_rejected():
    with pytest.raises(ValueError):
        runner._root(Path("relative"))


def test_symlink_storage_root_rejected(sealed, tmp_path):
    link = tmp_path / "linked-storage"
    try:
        link.symlink_to(sealed.storage, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit synthetic symlink creation")
    with pytest.raises(ValueError):
        runner._root(link)


def test_cli_failure_is_sanitized(monkeypatch, capsys, tmp_path):
    def fail(*args):
        raise ValueError("synthetic-private-response-text")

    monkeypatch.setattr(runner, "run", fail)
    monkeypatch.setattr(
        sys, "argv", ["runner", "--storage-root", str(tmp_path), "--seal-sha", "a" * 64]
    )
    with pytest.raises(SystemExit) as exit_info:
        runner.main()
    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert "synthetic-private-response-text" not in output.out + output.err
    assert json.loads(output.out)["status"] == "FAIL"
