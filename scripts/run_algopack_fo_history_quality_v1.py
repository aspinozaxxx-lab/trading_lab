"""Sealed source replay followed by immutable, metadata-only FO quality reporting."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures import algopack_fo_history_core_v1 as core
from market_lab.futures import algopack_fo_history_quality_v1 as quality
from market_lab.futures import moex_algopack_fo_history_v1 as history

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "algopack_fo_history_quality_v1"
PARENT_SEAL_SHA = "c5fb0b96b12d77f5c01b1625b0b9b7ab582ed82d09117dc6217d577de33751d1"
SOURCE_PATH = "data/processed/algopack/moex_algopack_fo_history_v1_c5fb0b96b12d"
OUTPUT_PARENT = "data/processed/algopack_quality"
CONFIG_PATH = f"configs/{PROTOCOL}.yaml"
SIDECAR_PATH = f"configs/{PROTOCOL}.sha256"
SEAL_PATH = f"configs/{PROTOCOL}.seal.json"
PARENT_SEAL_PATH = "configs/moex_algopack_fo_history_v1.seal.json"
NEW_FILES = {
    CONFIG_PATH,
    SIDECAR_PATH,
    f"src/market_lab/futures/{PROTOCOL}.py",
    f"tests/test_{PROTOCOL}.py",
    f"scripts/run_{PROTOCOL}.py",
    f"tests/test_run_{PROTOCOL}.py",
}


def _sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid quality SHA identity")
    return value


def _root(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("quality root must be an absolute ordinary directory")
    for component in reversed((path, *path.parents)):
        quality._ordinary(component, directory=True)
    return path


def _load(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=core._json_pairs)
    if not isinstance(value, dict):
        raise ValueError("quality JSON must be an object")
    return value


def _phase(name: str) -> None:
    print(json.dumps({"protocol_id": PROTOCOL, "status": "RUNNING", "phase": name}), flush=True)


def expected_config(manifest_sha: str) -> dict:
    return {
        "protocol_id": PROTOCOL,
        "source": {
            "path": SOURCE_PATH,
            "seal_sha256": PARENT_SEAL_SHA,
            "manifest_sha256": _sha(manifest_sha),
        },
        "metadata_columns": list(quality.METADATA_COLUMNS),
        "expected_jobs": 294,
        "expected_pairs": 147,
        "output_parent": OUTPUT_PARENT,
        **quality.FLAGS,
    }


def verify_seal(seal_sha: str) -> dict:
    root = _root(PROJECT_ROOT)
    seal_raw = quality._safe(root, SEAL_PATH).read_bytes()
    if core.sha(seal_raw) != _sha(seal_sha):
        raise ValueError("quality seal byte identity differs")
    seal = _load(seal_raw)
    files = seal.get("files")
    parent_raw = quality._safe(root, PARENT_SEAL_PATH).read_bytes()
    if core.sha(parent_raw) != PARENT_SEAL_SHA:
        raise ValueError("quality parent seal differs")
    parent_files = _load(parent_raw).get("files")
    if (
        seal.get("protocol_id") != PROTOCOL
        or seal.get("source_only") is not True
        or not isinstance(files, dict)
        or not isinstance(parent_files, dict)
        or len(parent_files) != 21
        or set(files) != set(parent_files) | NEW_FILES | {PARENT_SEAL_PATH}
        or any(files.get(path) != digest for path, digest in parent_files.items())
        or files.get(PARENT_SEAL_PATH) != PARENT_SEAL_SHA
    ):
        raise ValueError("quality closure is incomplete or changes its parent")
    for relative, digest in files.items():
        if quality._hash(quality._safe(root, relative)) != _sha(digest):
            raise ValueError("quality dependency byte identity differs")
    raw = quality._safe(root, CONFIG_PATH).read_bytes()
    config = _load(raw)
    source = config.get("source")
    if not isinstance(source, dict):
        raise ValueError("quality source configuration is absent")
    expected = expected_config(source.get("manifest_sha256"))
    sidecar = quality._safe(root, SIDECAR_PATH).read_text(encoding="utf-8-sig").split()
    if quality._json(config) != quality._json(expected) or sidecar != [
        core.sha(raw),
        Path(CONFIG_PATH).name,
    ]:
        raise ValueError("quality fixed configuration differs")
    parent = core.verify_seal(PARENT_SEAL_SHA)
    if parent["files"] != parent_files or parent["seal_sha256"] != PARENT_SEAL_SHA:
        raise ValueError("quality parent verification disagrees")
    return {
        "seal_sha256": seal_sha,
        "config_sha256": core.sha(raw),
        "files": files,
        "config": config,
    }


def _output_paths(root: Path, seal_sha: str) -> tuple[Path, Path]:
    parent = root
    for part in OUTPUT_PARENT.split("/"):
        parent = parent / part
        if not parent.exists() and not parent.is_symlink():
            parent.mkdir()
        quality._ordinary(parent, directory=True)
    stem = f"{PROTOCOL}_{_sha(seal_sha)[:12]}"
    lock = parent / f".{stem}.lock"
    if lock.exists() or lock.is_symlink():
        quality._ordinary(lock)
    return parent / stem, lock


def _validate_audit(audit: dict, config: dict) -> None:
    manifest_sha = config["source"]["manifest_sha256"]
    if (
        audit.get("status") != "PASS"
        or audit.get("protocol_id") != core.PROTOCOL
        or audit.get("manifest_sha256") != manifest_sha
        or type(audit.get("jobs")) is not int
        or audit["jobs"] != config["expected_jobs"]
        or any(type(audit.get(key)) is not int or audit[key] < 0 for key in ("rows", "pages"))
        or type(audit.get("source_date_coverage_admitted")) is not bool
        or any(audit.get(key) is not value for key, value in quality.FLAGS.items())
    ):
        raise ValueError("full historical replay did not pass the fixed identity")


def _validate_results(audit: dict, report: dict, config: dict) -> None:
    _validate_audit(audit, config)
    manifest_sha = config["source"]["manifest_sha256"]
    if (
        report.get("protocol_id") != PROTOCOL
        or report.get("status") != "metadata_report_complete"
        or report.get("source_protocol_id") != core.PROTOCOL
        or report.get("source_manifest_sha256") != manifest_sha
        or report.get("source_closure", {}).get("seal_sha256") != PARENT_SEAL_SHA
        or report.get("metadata_columns_read") != config["metadata_columns"]
        or report.get("full_raw_replay_performed") is not False
        or report.get("requires_separate_history_audit") is not True
        or any(report.get(key) is not value for key, value in quality.FLAGS.items())
    ):
        raise ValueError("quality metadata report identity or flags differ")
    totals = report.get("totals", {})
    for key, source_key in (("job_count", "jobs"), ("rows", "rows"), ("pages", "pages")):
        if type(totals.get(key)) is not int or totals[key] != audit[source_key]:
            raise ValueError("quality metadata and full replay totals differ")
    if (
        type(audit.get("source_date_coverage_admitted")) is not bool
        or totals.get("source_date_coverage_admitted") is not audit["source_date_coverage_admitted"]
    ):
        raise ValueError("quality source date admission differs from full replay")


def run(storage_root: Path, seal_sha: str) -> Path:
    closure = verify_seal(seal_sha)
    config = closure["config"]
    root = _root(storage_root)
    source = quality._safe(root, config["source"]["path"], directory=True)
    destination, lock = _output_paths(root, seal_sha)
    with history._exclusive_lock(lock):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("immutable quality destination already exists")
        source_spec = config["source"]
        _phase("raw_replay")
        audit = history.audit(
            source, root, source_spec["seal_sha256"], source_spec["manifest_sha256"]
        )
        # Reject failed audit before projecting metadata or writing any report artifact.
        _validate_audit(audit, config)
        _phase("metadata_projection")
        report = quality.build_report(source, source_spec["manifest_sha256"])
        _validate_results(audit, report, config)
        if verify_seal(seal_sha) != closure:
            raise ValueError("quality closure changed during reporting")
        stage = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
        )
        # Never delete stage on failure: incomplete evidence stays separate from canonical output.
        payloads = {"audit.json": audit, "quality.json": report}
        for name, payload in payloads.items():
            history._write(stage / name, history._json(payload))
        manifest = {
            "protocol_id": PROTOCOL,
            "status": "complete",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "closure": {key: closure[key] for key in ("seal_sha256", "config_sha256", "files")},
            "source": source_spec,
            "full_raw_replay_status": "PASS",
            "jobs_completed_and_replay_audited": audit["jobs"],
            "artifacts": {name: history._identity(stage / name) for name in payloads},
            **quality.FLAGS,
        }
        history._write(stage / "manifest.json", history._json(manifest))
        quality._ordinary(stage, directory=True)
        if {path.name for path in stage.iterdir()} != {*payloads, "manifest.json"}:
            raise ValueError("quality staging contains unexpected children")
        quality._ordinary(stage / "manifest.json")
        for name, payload in payloads.items():
            if history._identity(stage / name) != manifest["artifacts"][name] or (
                stage / name
            ).read_bytes() != history._json(payload):
                raise ValueError("quality staged report changed before publication")
        if (stage / "manifest.json").read_bytes() != history._json(manifest):
            raise ValueError("quality staged manifest changed before publication")
        quality._ordinary(destination.parent, directory=True)
        _phase("publish")
        history._publish(stage, destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--seal-sha", required=True)
    args = parser.parse_args()
    try:
        result = run(args.storage_root, args.seal_sha)
    except Exception:
        print(json.dumps({"status": "FAIL", "protocol_id": PROTOCOL, **quality.FLAGS}))
        raise SystemExit(2) from None
    print(json.dumps({"status": "PASS", "output": str(result), **quality.FLAGS}))


if __name__ == "__main__":
    main()
