"""Resumable, immutable current-vintage FO source; no economic admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from market_lab.futures import algopack_fo_history_core_v1 as core
from market_lab.futures import moex_algopack_fo_historical_inventory_v1 as transport

PROTOCOL = core.PROTOCOL
FLAGS = {
    "source_only": True,
    "current_vintage": True,
    "historical_model_eligible": False,
    "live_trading_allowed": False,
    "original_version_verified": False,
}
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _json(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode()


def _read(path: Path) -> dict:
    _regular(path)
    return json.loads(path.read_bytes(), object_pairs_hook=transport._unique_pairs)


def _regular(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    reparse = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if reparse or not valid_type:
        raise ValueError("source artifact is not an ordinary file or directory")


def _identity(path: Path) -> dict:
    _regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _write(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_dir(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _publish(temporary: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("immutable source artifact already exists")
    _sync_dir(temporary)
    temporary.rename(destination)
    _sync_dir(destination.parent)


@contextmanager
def _exclusive_lock(path: Path):
    if path.is_symlink():
        raise ValueError("source lock cannot be a symlink")
    handle = path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError("source collection is already locked") from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError("source collection is already locked") from None
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _paths(storage_root: Path, seal_sha: str) -> tuple[Path, Path, Path, Path]:
    if re.fullmatch(r"[0-9a-f]{64}", seal_sha) is None:
        raise ValueError("invalid source seal identity")
    root = storage_root.resolve()
    parent = root / "data/processed/algopack"
    if not parent.resolve().is_relative_to(root):
        raise ValueError("source output escaped storage root")
    parent.mkdir(parents=True, exist_ok=True)
    stem = f"{PROTOCOL}_{seal_sha[:12]}"
    return (
        parent / stem,
        parent / f".{stem}.work",
        parent / f".{stem}.lock",
        parent / f".{stem}.failures",
    )


def _expected_identity(closure: dict, plan: list[dict]) -> dict:
    raw = _json(plan)
    return {
        "protocol_id": PROTOCOL,
        "closure": closure,
        "parent_sample": core.EXPECTED_CONFIG["parent_sample"],
        "plan": {
            "path": "plan.json",
            "sha256": transport.sha(raw),
            "bytes": len(raw),
            "jobs": len(plan),
        },
        **FLAGS,
    }


def _initialize(work: Path, identity: dict, plan: list[dict]) -> None:
    if work.exists() or work.is_symlink():
        _regular(work, directory=True)
        _regular(work / "plan.json")
        if _json(_read(work / "identity.json")) != _json(identity) or (
            work / "plan.json"
        ).read_bytes() != _json(plan):
            raise ValueError("resumed source identity or plan differs")
        _regular(work / "jobs", directory=True)
        return
    temporary = Path(tempfile.mkdtemp(prefix=f"{work.name}.init.", dir=work.parent))
    _write(temporary / "identity.json", _json(identity))
    _write(temporary / "plan.json", _json(plan))
    (temporary / "jobs").mkdir()
    _publish(temporary, work)


def _job_dir(work: Path, job: dict) -> Path:
    # Core validates job_id and prevents traversal before any filesystem use.
    core.request_url(job, 0)
    directory = work / "jobs" / job["job_id"]
    if directory.exists() or directory.is_symlink():
        _regular(directory, directory=True)
        _regular(directory / "pages", directory=True)
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{job['job_id']}.", dir=work / "jobs"))
        (temporary / "pages").mkdir()
        _publish(temporary, directory)
    return directory


def _check_attempts(attempts: list[dict]) -> None:
    delays = core.EXPECTED_CONFIG["retry_delays_seconds"]
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= len(delays) + 1:
        raise ValueError("source retry evidence invalid")
    for number, item in enumerate(attempts):
        expected = {
            "attempt": number + 1,
            "retry_delay_seconds": delays[number - 1] if number else 0,
            "pacing_seconds": core.EXPECTED_CONFIG["request_interval_seconds"],
            "phase": item.get("phase"),
            "http_status": item.get("http_status"),
        }
        if _json(item) != _json(expected):
            raise ValueError("source retry evidence fields differ")
        if number == len(attempts) - 1:
            if item["phase"] != "success" or item["http_status"] != 200:
                raise ValueError("source successful request evidence missing")
        elif not (
            item["phase"] == "transport"
            and item["http_status"] is None
            or item["phase"] == "http_status"
            and item["http_status"] in RETRY_STATUSES
        ):
            raise ValueError("source nonretryable request evidence")


def _fetch_page(session: object, url: str, token: str, attempts: list[dict]) -> tuple[bytes, dict]:
    delays = [0, *core.EXPECTED_CONFIG["retry_delays_seconds"]]
    for number, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        time.sleep(core.EXPECTED_CONFIG["request_interval_seconds"])
        record = {
            "attempt": number + 1,
            "retry_delay_seconds": delay,
            "pacing_seconds": core.EXPECTED_CONFIG["request_interval_seconds"],
        }
        try:
            raw, evidence = transport._fetch(session, url, token)
        except transport.InventoryFailure as error:
            attempts.append({**record, "phase": error.phase, "http_status": error.http_status})
            retryable = error.phase == "transport" or (
                error.phase == "http_status" and error.http_status in RETRY_STATUSES
            )
            if not retryable or number == len(delays) - 1:
                raise
        else:
            attempts.append({**record, "phase": "success", "http_status": 200})
            return raw, evidence
    raise AssertionError("unreachable retry state")


def _merge(rows: list[dict], seen: set[tuple], page_rows: list[dict], retrieved: str) -> None:
    for row in page_rows:
        key = (row["tradedate"], row["tradetime"], row["secid"])
        if key in seen:
            raise ValueError("duplicate observation across source pages")
        seen.add(key)
        rows.append({**row, "retrieved_at_utc": retrieved, "available_at": None, **FLAGS})


def _replay(directory: Path, job: dict, *, allow_incomplete: bool = True) -> dict:
    _regular(directory, directory=True)
    pages_dir = directory / "pages"
    _regular(pages_dir, directory=True)
    children = sorted(pages_dir.iterdir())
    pages = []
    for path in children:
        if re.fullmatch(r"\.p[0-9]{6}\.[A-Za-z0-9_-]+", path.name):
            _regular(path, directory=True)
            if not allow_incomplete:
                raise ValueError("incomplete page artifact in canonical source")
            continue  # Incomplete atomic page never contributes evidence or observations.
        if not re.fullmatch(r"p[0-9]{6}", path.name):
            raise ValueError("unexpected page artifact")
        pages.append(path)
    if len(pages) > core.EXPECTED_CONFIG["max_pages_per_job"]:
        raise ValueError("source page limit exceeded")
    rows, seen, entries = [], set(), []
    start, total, page_size = 0, None, None
    for number, path in enumerate(pages):
        _regular(path, directory=True)
        if path.name != f"p{number:06d}" or {item.name for item in path.iterdir()} != {
            "raw.json",
            "evidence.json",
        }:
            raise ValueError("source committed page sequence or contents invalid")
        if total is not None and start >= total:
            raise ValueError("source page follows terminal cursor")
        raw_path = path / "raw.json"
        actual_identity = _identity(raw_path)
        evidence = _read(path / "evidence.json")
        page_rows, cursor = core.parse_page(raw_path.read_bytes(), job, start)
        retrieved = evidence["retrieved_at_utc"]
        stamp = datetime.fromisoformat(retrieved)
        if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
            raise ValueError("source retrieval timestamp is not UTC")
        _check_attempts(evidence["attempts"])
        expected = {
            "job_id": job["job_id"],
            "page": number,
            "start": start,
            "request_url": core.request_url(job, start),
            "cursor": cursor,
            "raw": actual_identity,
            "retrieved_at_utc": retrieved,
            "attempts": evidence["attempts"],
            "http_status": 200,
            "bearer_sent": True,
            "final_url": core.request_url(job, start),
        }
        if _json(evidence) != _json(expected):
            raise ValueError("source page identity or transport evidence differs")
        if total is not None and (cursor["TOTAL"] != total or cursor["PAGESIZE"] != page_size):
            raise ValueError("source cursor total or page size changed")
        total, page_size = cursor["TOTAL"], cursor["PAGESIZE"]
        _merge(rows, seen, page_rows, retrieved)
        start += len(page_rows)
        entries.append(
            {
                "page": path.name,
                "evidence": _identity(path / "evidence.json"),
                "raw": actual_identity,
                "rows": len(page_rows),
                "request_attempts": len(evidence["attempts"]),
            }
        )
    return {
        "rows": rows,
        "seen": seen,
        "pages": entries,
        "start": start,
        "total": total,
        "page_size": page_size,
        "complete": total is not None and start == total,
    }


def _job_manifest(job: dict, state: dict, result: Path) -> dict:
    return {
        "protocol_id": PROTOCOL,
        "status": "complete",
        "job": job,
        "pages": state["pages"],
        "normalized": {**_identity(result / "rows.jsonl"), "rows": len(state["rows"])},
        "summary": core.summarize_rows(state["rows"], job),
        **FLAGS,
    }


def _check_result(
    directory: Path, job: dict, state: dict, *, allow_incomplete: bool = True
) -> dict | None:
    result = directory / "result"
    for child in directory.iterdir():
        if child.name not in {"pages", "result"}:
            if not re.fullmatch(r"\.result\.[A-Za-z0-9_-]+", child.name):
                raise ValueError("unexpected job artifact")
            _regular(child, directory=True)
            if not allow_incomplete:
                raise ValueError("incomplete result artifact in canonical source")
    if not result.exists() and not result.is_symlink():
        return None
    _regular(result, directory=True)
    if not state["complete"] or {p.name for p in result.iterdir()} != {
        "rows.jsonl",
        "manifest.json",
    }:
        raise ValueError("source result incomplete or unexpected")
    expected = _job_manifest(job, state, result)
    if _json(_read(result / "manifest.json")) != _json(expected):
        raise ValueError("source job manifest differs from raw replay")
    with (result / "rows.jsonl").open("rb") as handle:
        for row in state["rows"]:
            if handle.readline() != _json(row):
                raise ValueError("source normalized row differs from raw replay")
        if handle.read(1):
            raise ValueError("source normalized trailing contents")
    return expected


def _commit_result(directory: Path, job: dict, state: dict) -> dict:
    existing = _check_result(directory, job, state)
    if existing is not None:
        return existing
    if not state["complete"]:
        raise ValueError("cannot publish incomplete source job")
    temporary = Path(tempfile.mkdtemp(prefix=".result.", dir=directory))
    with (temporary / "rows.jsonl").open("xb") as handle:
        for row in state["rows"]:
            handle.write(_json(row))
        handle.flush()
        os.fsync(handle.fileno())
    manifest = _job_manifest(job, state, temporary)
    _write(temporary / "manifest.json", _json(manifest))
    _publish(temporary, directory / "result")
    return manifest


def _check_work(work: Path, identity: dict, plan: list[dict], *, complete: bool) -> list[dict]:
    _initialize(work, identity, plan)
    for item in work.iterdir():
        if item.name not in {"identity.json", "plan.json", "jobs", "manifest.json"}:
            if not re.fullmatch(r"\.manifest\.[A-Za-z0-9_-]+", item.name):
                raise ValueError("unexpected source work artifact")
            _regular(item)
            if complete:
                raise ValueError("incomplete manifest artifact in canonical source")
    expected_ids = {job["job_id"] for job in plan}
    for item in (work / "jobs").iterdir():
        if item.name not in expected_ids:
            if not any(item.name.startswith(f".{job_id}.") for job_id in expected_ids):
                raise ValueError("unexpected source job")
            _regular(item, directory=True)
            if complete:
                raise ValueError("incomplete job artifact in canonical source")
    summaries = []
    for job in plan:
        directory = work / "jobs" / job["job_id"]
        if not directory.exists() and not directory.is_symlink():
            if complete:
                raise ValueError("missing completed source job")
            continue
        state = _replay(directory, job, allow_incomplete=not complete)
        manifest = _check_result(directory, job, state, allow_incomplete=not complete)
        if complete and manifest is None:
            raise ValueError("missing source job result")
        if manifest is not None:
            summaries.append(_job_summary(directory, manifest))
    return summaries


def _quarantine_incomplete(work: Path, plan: list[dict]) -> None:
    """Preserve opaque crash leftovers outside canonical, without opening their contents."""
    candidates = [item for item in work.iterdir() if item.name.startswith(".manifest.")]
    ids = {job["job_id"] for job in plan}
    for directory in (work / "jobs").iterdir():
        if directory.name not in ids:
            candidates.append(directory)
            continue
        candidates.extend(item for item in directory.iterdir() if item.name.startswith(".result."))
        candidates.extend(
            item for item in (directory / "pages").iterdir() if item.name.startswith(".p")
        )
    if not candidates:
        return
    quarantine = work.parent / f"{work.name}.orphans"
    if quarantine.is_symlink():
        raise ValueError("source orphan quarantine cannot be a symlink")
    quarantine.mkdir(exist_ok=True)
    _regular(quarantine, directory=True)
    for candidate in candidates:
        # Preflight recognized these exact top-level names. Never traverse orphan descendants.
        if not candidate.parent.resolve().is_relative_to(work.resolve()) or candidate.is_symlink():
            raise ValueError("source orphan escaped working directory")
        target = Path(tempfile.mkdtemp(prefix="orphan.", dir=quarantine))
        _write(
            target / "origin.json",
            _json(
                {
                    "status": "incomplete_not_admitted",
                    "original_relative_path": candidate.relative_to(work).as_posix(),
                    **FLAGS,
                }
            ),
        )
        candidate.rename(target / "artifact")
        _sync_dir(candidate.parent)
        _sync_dir(target)


def _job_summary(directory: Path, manifest: dict) -> dict:
    attempts = sum(page["request_attempts"] for page in manifest["pages"])
    return {
        "job_id": manifest["job"]["job_id"],
        "manifest": _identity(directory / "result/manifest.json"),
        "normalized": manifest["normalized"],
        "pages": len(manifest["pages"]),
        "rows": manifest["normalized"]["rows"],
        "committed_page_request_attempts": attempts,
        "committed_page_retry_attempts": attempts - len(manifest["pages"]),
        "source_date_coverage_admitted": manifest["summary"]["source_date_coverage_admitted"],
    }


def _global_manifest(identity: dict, jobs: list[dict]) -> dict:
    return {
        **identity,
        "status": "complete",
        "jobs": jobs,
        "job_count": len(jobs),
        "rows": sum(job["rows"] for job in jobs),
        "pages": sum(job["pages"] for job in jobs),
        "committed_page_request_attempts": sum(
            job["committed_page_request_attempts"] for job in jobs
        ),
        "committed_page_retry_attempts": sum(job["committed_page_retry_attempts"] for job in jobs),
        "source_date_coverage_admitted": all(job["source_date_coverage_admitted"] for job in jobs),
    }


def _audit_locked(directory: Path, identity: dict, plan: list[dict], manifest_sha: str) -> dict:
    _regular(directory, directory=True)
    if _identity(directory / "manifest.json")["sha256"] != manifest_sha:
        raise ValueError("historical source global manifest identity differs")
    jobs = _check_work(directory, identity, plan, complete=True)
    expected = _global_manifest(identity, jobs)
    if _json(_read(directory / "manifest.json")) != _json(expected):
        raise ValueError("historical source global manifest differs from full replay")
    return {
        "status": "PASS",
        "protocol_id": PROTOCOL,
        "manifest_sha256": manifest_sha,
        "jobs": len(jobs),
        "rows": expected["rows"],
        "pages": expected["pages"],
        "source_date_coverage_admitted": expected["source_date_coverage_admitted"],
        **FLAGS,
    }


def audit(directory: Path, storage_root: Path, seal_sha: str, manifest_sha: str) -> dict:
    final, work, lock, _ = _paths(storage_root, seal_sha)
    if directory.resolve() not in {final.resolve(), work.resolve()}:
        raise ValueError("audit directory is not the sealed source destination")
    with _exclusive_lock(lock):
        closure = core.verify_seal(seal_sha)
        core.verify_parent_sample(storage_root)
        plan = core.build_plan(storage_root)
        return _audit_locked(directory, _expected_identity(closure, plan), plan, manifest_sha)


def _failure(path: Path, context: dict) -> None:
    if path.is_symlink():
        return
    path.mkdir(exist_ok=True)
    _regular(path, directory=True)
    descriptor, name = tempfile.mkstemp(prefix="failure.", suffix=".json", dir=path)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(
            _json(
                {
                    "protocol_id": PROTOCOL,
                    "status": "interrupted_or_failed",
                    "recorded_at_utc": datetime.now(UTC).isoformat(),
                    **context,
                    **FLAGS,
                }
            )
        )
        handle.flush()
        os.fsync(handle.fileno())


def collect(storage_root: Path, seal_sha: str, *, session: object | None = None) -> Path:
    final, work, lock, failures = _paths(storage_root, seal_sha)
    with _exclusive_lock(lock):
        if final.exists() or final.is_symlink():
            raise FileExistsError("immutable historical source already exists; use audit")
        context = {"phase": "preflight", "job_id": None, "start": 0, "attempts": []}
        network = None
        try:
            closure = core.verify_seal(seal_sha)
            core.verify_parent_sample(storage_root)
            plan = core.build_plan(storage_root)
            for job in plan:
                core.request_url(job, 0)
            identity = _expected_identity(closure, plan)
            # Replay ALL committed artifacts before allowing a single resumed network request.
            summaries = _check_work(work, identity, plan, complete=False)
            if (work / "manifest.json").exists():
                _quarantine_incomplete(work, plan)
                digest = _identity(work / "manifest.json")["sha256"]
                _audit_locked(work, identity, plan, digest)
                _publish(work, final)
                return final
            token = os.environ.get(transport.TOKEN_ENV, "")
            if not token.strip():
                raise ValueError("MOEX_ALGOPACK_TOKEN is required")
            network = session if session is not None else requests.Session()
            summaries = []
            for job_number, job in enumerate(plan):
                context = {"phase": "replay", "job_id": job["job_id"], "start": 0, "attempts": []}
                directory = _job_dir(work, job)
                state = _replay(directory, job)
                while not state["complete"]:
                    number, start = len(state["pages"]), state["start"]
                    if number >= core.EXPECTED_CONFIG["max_pages_per_job"]:
                        raise ValueError("historical source page limit reached")
                    context = {
                        "phase": "request",
                        "job_id": job["job_id"],
                        "start": start,
                        "attempts": [],
                    }
                    url = core.request_url(job, start)
                    raw, evidence = _fetch_page(network, url, token, context["attempts"])
                    retrieved = datetime.now(UTC).isoformat()
                    context["phase"] = "parse_page"
                    page_rows, cursor = core.parse_page(raw, job, start)
                    if state["total"] is not None and (
                        cursor["TOTAL"] != state["total"]
                        or cursor["PAGESIZE"] != state["page_size"]
                    ):
                        raise ValueError("historical source cursor changed")
                    _merge(state["rows"], state["seen"], page_rows, retrieved)
                    temporary = Path(
                        tempfile.mkdtemp(prefix=f".p{number:06d}.", dir=directory / "pages")
                    )
                    _write(temporary / "raw.json", raw)
                    evidence = {
                        **evidence,
                        "job_id": job["job_id"],
                        "page": number,
                        "start": start,
                        "request_url": url,
                        "cursor": cursor,
                        "raw": _identity(temporary / "raw.json"),
                        "retrieved_at_utc": retrieved,
                        "attempts": context["attempts"],
                    }
                    _write(temporary / "evidence.json", _json(evidence))
                    committed = directory / "pages" / f"p{number:06d}"
                    context["phase"] = "commit_page"
                    _publish(temporary, committed)
                    state["pages"].append(
                        {
                            "page": committed.name,
                            "evidence": _identity(committed / "evidence.json"),
                            "raw": evidence["raw"],
                            "rows": len(page_rows),
                            "request_attempts": len(context["attempts"]),
                        }
                    )
                    state.update(
                        start=start + len(page_rows),
                        total=cursor["TOTAL"],
                        page_size=cursor["PAGESIZE"],
                        complete=start + len(page_rows) == cursor["TOTAL"],
                    )
                    if (number + 1) % 10 == 0:
                        print(
                            json.dumps(
                                {
                                    "status": "collecting",
                                    "job_id": job["job_id"],
                                    "pages": number + 1,
                                    "rows": state["start"],
                                }
                            ),
                            flush=True,
                        )
                context["phase"] = "commit_result"
                manifest = _commit_result(directory, job, state)
                summaries.append(_job_summary(directory, manifest))
                print(
                    json.dumps(
                        {
                            "status": "job_complete",
                            "job_id": job["job_id"],
                            "jobs_complete": job_number + 1,
                            "jobs_total": len(plan),
                            "rows": state["start"],
                            "pages": len(state["pages"]),
                        }
                    ),
                    flush=True,
                )
            context["phase"] = "full_audit"
            _quarantine_incomplete(work, plan)
            # Recheck source closure and pinned parents after a potentially long collection.
            refreshed = core.verify_seal(seal_sha)
            core.verify_parent_sample(storage_root)
            if _json(_expected_identity(refreshed, core.build_plan(storage_root))) != _json(
                identity
            ):
                raise ValueError("historical source inputs changed during collection")
            manifest = _global_manifest(identity, summaries)
            descriptor, name = tempfile.mkstemp(prefix=".manifest.", dir=work)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_json(manifest))
                handle.flush()
                os.fsync(handle.fileno())
            Path(name).rename(work / "manifest.json")
            _sync_dir(work)
            _audit_locked(work, identity, plan, transport.sha(_json(manifest)))
            context["phase"] = "publish"
            _publish(work, final)
            return final
        except BaseException as error:
            if isinstance(error, transport.InventoryFailure):
                context["phase"] = error.phase
                context["http_status"] = error.http_status
            # Preserve the original safe failure if diagnostics cannot be persisted.
            with suppress(Exception):
                _failure(failures, context)
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise transport.InventoryFailure(
                context["phase"], context.get("http_status"), str(failures)
            ) from None
        finally:
            if session is None and network is not None:
                network.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--manifest-sha")
    args = parser.parse_args()
    if bool(args.audit) != bool(args.manifest_sha):
        parser.error("--audit and --manifest-sha must be supplied together")
    try:
        if args.audit:
            result = audit(args.audit, args.storage_root, args.seal_sha, args.manifest_sha)
        else:
            path = collect(args.storage_root, args.seal_sha)
            result = {
                "status": "complete",
                "path": str(path),
                "manifest_sha256": _identity(path / "manifest.json")["sha256"],
            }
    except Exception:
        print(json.dumps({"status": "FAILED", "protocol_id": PROTOCOL}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
