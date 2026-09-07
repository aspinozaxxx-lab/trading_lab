"""Immutable, receipt-witnessed FO source only; no prices, labels or execution."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from market_lab.futures import algopack_fo_witnessed_core_v1 as core

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = core.PROTOCOL
CA_PATH = "/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem"
CA_SHA = "aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399"
EXPECTED_CONFIG = {
    "protocol_id": PROTOCOL,
    "assets": core.ASSETS,
    "contracts_per_asset": 2,
    "lookback_calendar_days": 2,
    "lookahead_label_days": 14,
    "max_pages_per_job": 8,
    "max_response_bytes": 8388608,
    "deadline_seconds": 420,
    "request_spacing_seconds": 0.5,
    "retries": 0,
    "timezone": "Europe/Moscow",
    "source_only": True,
    "historical_model_eligible": False,
    "original_version_verified": False,
    "live_trading_allowed": False,
    "rolled_out_contract_retention": False,
    "vendor_atomic_snapshot_proven": False,
    "ca_path": CA_PATH,
    "ca_sha256": CA_SHA,
    "columns": {key: core.COMMON + value for key, value in core.FIELDS.items()},
}
REQUIRED_FILES = {
    f"src/market_lab/futures/{name}.py"
    for name in ("algopack_fo_witnessed_core_v1", "moex_algopack_fo_witnessed_v1")
} | {
    f"tests/test_{name}.py"
    for name in ("algopack_fo_witnessed_core_v1", "moex_algopack_fo_witnessed_v1")
} | {f"configs/{PROTOCOL}.json", f"configs/{PROTOCOL}.sha256", "pyproject.toml"}


class CaptureFailure(Exception):
    """The CLI emits only an enumerated phase, never response bodies or exceptions."""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo != UTC or result.isoformat() != value:
        raise ValueError("noncanonical receipt timestamp")
    return result


def _ordinary(path: Path, directory: bool = False) -> None:
    for parent in [*reversed(path.absolute().parents), path.absolute()]:
        metadata = parent.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("symlink path forbidden")
    metadata = path.lstat()
    valid = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not valid or (not directory and metadata.st_nlink != 1):
        raise ValueError("ordinary unique path required")


def _read(path: Path) -> bytes:
    _ordinary(path)
    return path.read_bytes()


def _write(path: Path, raw: bytes) -> dict:
    _ordinary(path.parent, directory=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"file": path.name, "bytes": len(raw), "sha256": sha(raw)}


def verify_seal(seal_sha256: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", seal_sha256):
        raise ValueError("invalid seal digest")
    raw = _read(PROJECT_ROOT / f"configs/{PROTOCOL}.seal.json")
    seal = core._decode(raw)
    if (sha(raw) != seal_sha256 or seal.get("protocol_id") != PROTOCOL
            or set(seal.get("files", {})) != REQUIRED_FILES):
        raise ValueError("source closure mismatch")
    for relative, digest in seal["files"].items():
        if sha(_read(PROJECT_ROOT / relative)) != digest:
            raise ValueError("source dependency drift")
    raw_config = _read(PROJECT_ROOT / f"configs/{PROTOCOL}.json")
    sidecar = _read(PROJECT_ROOT / f"configs/{PROTOCOL}.sha256").decode("utf-8-sig").split()
    if (core._decode(raw_config) != EXPECTED_CONFIG or sidecar != [sha(raw_config)]):
        raise ValueError("source configuration drift")
    return seal


@contextmanager
def _lock(root: Path):
    import fcntl

    _ordinary(root, directory=True)
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("output root must be private and runtime-owned")
    path = root / ".collector.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _ordinary(path)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _fetch(session, url: str, token: str, deadline: float) -> tuple[bytes, dict]:
    parsed = urlsplit(url)
    paid = parsed.netloc == "apim.moex.com"
    if (parsed.scheme != "https" or parsed.fragment
            or not (paid and parsed.path.startswith("/iss/datashop/algopack/fo/")
                    or url in core.metadata_urls().values())):
        raise CaptureFailure("request_scope")
    if not token or "\n" in token or "\r" in token:
        raise CaptureFailure("credential")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CaptureFailure("deadline")
    headers = {"Accept": "application/json"}
    if paid:
        headers["Authorization"] = "Bearer " + token
    started, monotonic_start = _now(), time.monotonic()
    try:
        with session.get(
            url, headers=headers, timeout=min(30, remaining), allow_redirects=False,
            stream=True, verify=CA_PATH if paid else requests.certs.where(),
        ) as response:
            if response.status_code != 200 or response.url != url:
                raise CaptureFailure("http_status_or_redirect")
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > EXPECTED_CONFIG["max_response_bytes"]:
                    raise CaptureFailure("response_limit")
                if time.monotonic() > deadline:
                    raise CaptureFailure("deadline")
                chunks.append(chunk)
            raw = b"".join(chunks)
        completed = _now()
        elapsed = time.monotonic() - monotonic_start
        if not raw or token.encode() in raw:
            raise CaptureFailure("empty_or_secret_reflection")
        if completed < started or abs((completed - started).total_seconds() - elapsed) > 2:
            raise CaptureFailure("clock_discontinuity")
        return raw, {
            "url": url, "http_status": 200, "bearer_sent": paid,
            "request_started_at": started.isoformat(),
            "response_completed_at": completed.isoformat(),
            "request_elapsed_seconds": elapsed,
        }
    except CaptureFailure:
        raise
    except Exception:
        raise CaptureFailure("transport") from None


def _receipt(raw: bytes, evidence: dict, validated: datetime) -> dict:
    if validated < _stamp(evidence["response_completed_at"]):
        raise CaptureFailure("clock_discontinuity")
    return {**evidence, "validated_at": validated.isoformat(),
            "raw_bytes": len(raw), "raw_sha256": sha(raw)}


def _save_response(path: Path, name: str, raw: bytes, evidence: dict) -> dict:
    artifact = _write(path / f"{name}.json.gz", gzip.compress(raw, mtime=0))
    return {**evidence, "artifact": artifact}


def _artifact(path: Path, identity: dict) -> bytes:
    name = identity["file"]
    if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
        raise ValueError("artifact escaped capture")
    raw = _read(path / name)
    if len(raw) != identity["bytes"] or sha(raw) != identity["sha256"]:
        raise ValueError("artifact identity mismatch")
    return raw


def _response(path: Path, evidence: dict, lower: datetime, upper: datetime) -> bytes:
    raw = gzip.decompress(_artifact(path, evidence["artifact"]))
    if len(raw) != evidence["raw_bytes"] or sha(raw) != evidence["raw_sha256"]:
        raise ValueError("raw replay identity mismatch")
    started, completed, validated = (
        _stamp(evidence[key])
        for key in ("request_started_at", "response_completed_at", "validated_at")
    )
    if not lower <= started <= completed <= validated <= upper:
        raise ValueError("receipt chronology mismatch")
    elapsed = evidence["request_elapsed_seconds"]
    if (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0
            or abs((completed - started).total_seconds() - elapsed) > 2):
        raise ValueError("receipt wall/monotonic clock mismatch")
    if evidence["http_status"] != 200:
        raise ValueError("receipt status mismatch")
    return raw


def _replay(path: Path, manifest: dict) -> dict:
    """Replay every persisted response, exact normalized bytes, pagination and clocks."""
    begin, end = _stamp(manifest["started_at"]), _stamp(manifest["available_at"])
    source_date = begin.astimezone(ZoneInfo("Europe/Moscow")).date()
    if source_date.isoformat() != manifest["source_date"]:
        raise ValueError("discovery date drift")
    expected_bounds = {
        "from": (source_date - timedelta(days=2)).isoformat(),
        "till": (source_date + timedelta(days=14)).isoformat(),
    }
    if manifest["bounds"] != expected_bounds or manifest["flags"] != _flags():
        raise ValueError("capture bounds or admission drift")
    discovery = {}
    previous = begin
    for name, url in core.metadata_urls().items():
        evidence = manifest["discovery"][name]
        if evidence["url"] != url or evidence["bearer_sent"]:
            raise ValueError("discovery transport identity mismatch")
        discovery[name] = _response(path, evidence, previous, end)
        if _read(path / f"{name}.receipt.json") != _json(evidence):
            raise ValueError("discovery receipt mismatch")
        previous = _stamp(evidence["validated_at"])
    plan = core.select_contracts(discovery["rfud"], discovery["series"], source_date.isoformat())
    if manifest["contracts"] != plan:
        raise ValueError("discovery selection replay mismatch")
    expected_plan = {key: value for key, value in manifest.items()
                     if key not in {"rows", "pages", "available_at"}}
    expected_plan["jobs"] = []
    if _read(path / "plan.json") != _json(expected_plan):
        raise ValueError("persisted discovery plan mismatch")
    expected_jobs = [
        {"dataset": dataset, "asset_code": contract["asset_code"], "secid": contract["secid"],
         **expected_bounds}
        for contract in plan for dataset in core.FIELDS
    ]
    if [record["job"] for record in manifest["jobs"]] != expected_jobs:
        raise ValueError("capture job universe mismatch")
    total_rows, pages = 0, 0
    for record in manifest["jobs"]:
        job, rows, seen, index, total = record["job"], [], set(), 0, None
        if not 1 <= len(record["pages"]) <= EXPECTED_CONFIG["max_pages_per_job"]:
            raise ValueError("capture page count mismatch")
        for evidence in record["pages"]:
            if total is not None and index >= total:
                raise ValueError("page after terminal cursor")
            if evidence["url"] != core.flow_url(job, index) or not evidence["bearer_sent"]:
                raise ValueError("FO transport identity mismatch")
            raw = _response(path, evidence, previous, end)
            receipt_name = evidence["artifact"]["file"].removesuffix(".json.gz")
            if _read(path / f"{receipt_name}.receipt.json") != _json(evidence):
                raise ValueError("page receipt mismatch")
            parsed_rows, cursor = core.parse_page(raw, job, index)
            previous = _stamp(evidence["validated_at"])
            if evidence["cursor"] != cursor or (total is not None and cursor["TOTAL"] != total):
                raise ValueError("capture cursor changed")
            total = cursor["TOTAL"]
            for row in parsed_rows:
                key = core.row_key(row)
                if key in seen:
                    raise ValueError("duplicate across pages")
                seen.add(key)
            rows.extend(parsed_rows)
            index += len(parsed_rows)
            pages += 1
        if index != total or record["rows"] != len(rows):
            raise ValueError("incomplete capture job")
        if gzip.decompress(_artifact(path, record["normalized"])) != _json(rows):
            raise ValueError("normalized replay mismatch")
        total_rows += len(rows)
    if manifest["rows"] != total_rows or manifest["pages"] != pages:
        raise ValueError("capture aggregate mismatch")
    expected_files = {"manifest.json", "audit.json", "plan.json",
                      "rfud.receipt.json", "series.receipt.json"}
    expected_files.update(item["artifact"]["file"] for item in manifest["discovery"].values())
    for job in manifest["jobs"]:
        expected_files.add(job["normalized"]["file"])
        expected_files.update(item["artifact"]["file"] for item in job["pages"])
        expected_files.update(item["artifact"]["file"].removesuffix(".json.gz") + ".receipt.json"
                              for item in job["pages"])
    actual_files = {item.name for item in path.iterdir()}
    if (actual_files - expected_files
            or expected_files - {"manifest.json", "audit.json"} - actual_files):
        raise ValueError("unexpected or missing capture artifacts")
    return {"passed": True, "rows": total_rows, "pages": pages,
            "source_only": True, "vendor_atomic_snapshot_proven": False}


def _flags() -> dict:
    return {key: EXPECTED_CONFIG[key] for key in (
        "source_only", "historical_model_eligible", "original_version_verified",
        "live_trading_allowed", "vendor_atomic_snapshot_proven", "rolled_out_contract_retention",
    )}


def audit(path: Path, seal_sha256: str) -> dict:
    verify_seal(seal_sha256)
    _ordinary(path, directory=True)
    raw = _read(path / "manifest.json")
    manifest = core._decode(raw)
    if manifest["protocol_id"] != PROTOCOL or manifest["seal_sha256"] != seal_sha256:
        raise ValueError("capture seal mismatch")
    result = _replay(path, manifest)
    saved = core._decode(_read(path / "audit.json"))
    if saved != {**result, "manifest_sha256": sha(raw)}:
        raise ValueError("saved audit mismatch")
    return saved


def capture(root: Path, seal_sha256: str) -> dict:
    verify_seal(seal_sha256)
    if os.environ.get("REQUESTS_CA_BUNDLE") != CA_PATH or sha(_read(Path(CA_PATH))) != CA_SHA:
        raise CaptureFailure("ca_preflight")
    token = os.environ.get("MOEX_ALGOPACK_TOKEN", "")
    if not token:
        raise CaptureFailure("credential")
    with _lock(root), requests.Session() as session:
        session.trust_env = False  # No proxy credentials, netrc or ambient auth fallback.
        return _capture_locked(root, seal_sha256, token, session)


def _capture_locked(root: Path, seal_sha256: str, token: str, session) -> dict:
    started, monotonic_start = _now(), time.monotonic()
    day = started.astimezone(ZoneInfo("Europe/Moscow")).date()
    capture_id = started.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:12]
    staging = root / (".incomplete_" + capture_id)
    staging.mkdir(mode=0o700)
    phase = "discovery"
    manifest = {
        "protocol_id": PROTOCOL, "seal_sha256": seal_sha256,
        "capture_id": capture_id, "started_at": started.isoformat(),
        "source_date": day.isoformat(), "flags": _flags(),
        "bounds": {"from": (day - timedelta(days=2)).isoformat(),
                   "till": (day + timedelta(days=14)).isoformat()},
        "discovery": {}, "jobs": [],
    }
    try:
        metadata = {}
        deadline = monotonic_start + EXPECTED_CONFIG["deadline_seconds"]
        for name, url in core.metadata_urls().items():
            raw, evidence = _fetch(session, url, token, deadline)
            # Only the exact metadata-only block may be persisted, even on later failure.
            payload = core._decode(raw)
            block = "securities" if name == "rfud" else "series"
            columns = core.RFUD_COLUMNS if name == "rfud" else core.SERIES_COLUMNS
            if set(payload) != {block}:
                raise CaptureFailure("discovery_schema")
            core._block(payload, block, columns)
            metadata[name] = raw
            evidence = _receipt(raw, evidence, _now())
            manifest["discovery"][name] = _save_response(staging, name, raw, evidence)
            _write(staging / f"{name}.receipt.json", _json(manifest["discovery"][name]))
            time.sleep(EXPECTED_CONFIG["request_spacing_seconds"])
        contracts = core.select_contracts(metadata["rfud"], metadata["series"], day.isoformat())
        manifest["contracts"] = contracts
        _write(staging / "plan.json", _json(manifest))
        phase = "flow"
        for contract in contracts:
            for dataset in core.FIELDS:
                job = {"dataset": dataset, "asset_code": contract["asset_code"],
                       "secid": contract["secid"], **manifest["bounds"]}
                record, rows, seen, index, total = {"job": job, "pages": []}, [], set(), 0, None
                for page_number in range(EXPECTED_CONFIG["max_pages_per_job"]):
                    raw, evidence = _fetch(session, core.flow_url(job, index), token, deadline)
                    parsed_rows, cursor = core.parse_page(raw, job, index)
                    evidence = {**_receipt(raw, evidence, _now()), "cursor": cursor}
                    name = f"{contract['secid']}_{dataset}_{page_number:03d}"
                    evidence = _save_response(staging, name, raw, evidence)
                    _write(staging / (name + ".receipt.json"), _json(evidence))
                    record["pages"].append(evidence)
                    if total is not None and cursor["TOTAL"] != total:
                        raise CaptureFailure("pagination_changed")
                    total = cursor["TOTAL"]
                    for row in parsed_rows:
                        key = core.row_key(row)
                        if key in seen:
                            raise CaptureFailure("pagination_duplicate")
                        seen.add(key)
                    rows.extend(parsed_rows)
                    index += len(parsed_rows)
                    time.sleep(EXPECTED_CONFIG["request_spacing_seconds"])
                    if index == total:
                        break
                if index != total:
                    raise CaptureFailure("page_limit")
                record["rows"] = len(rows)
                record["normalized"] = _write(
                    staging / f"{contract['secid']}_{dataset}_normalized.json.gz",
                    gzip.compress(_json(rows), mtime=0),
                )
                manifest["jobs"].append(record)
        phase = "replay"
        manifest["rows"] = sum(record["rows"] for record in manifest["jobs"])
        manifest["pages"] = sum(len(record["pages"]) for record in manifest["jobs"])
        manifest["available_at"] = _now().isoformat()
        _replay(staging, manifest)
        completed = _now()
        elapsed = time.monotonic() - monotonic_start
        if (completed < started or elapsed > EXPECTED_CONFIG["deadline_seconds"]
                or abs((completed - started).total_seconds() - elapsed) > 2):
            raise CaptureFailure("clock_or_deadline")
        manifest["available_at"] = completed.isoformat()
        raw_manifest = _json(manifest)
        _write(staging / "manifest.json", raw_manifest)
        result = {"passed": True, "rows": manifest["rows"], "pages": manifest["pages"],
                  "source_only": True, "vendor_atomic_snapshot_proven": False,
                  "manifest_sha256": sha(raw_manifest)}
        _write(staging / "audit.json", _json(result))
        canonical = root / capture_id
        if canonical.exists() or canonical.is_symlink():
            raise CaptureFailure("publication_collision")
        staging.rename(canonical)
        return {"capture_id": capture_id, **result}
    except Exception as error:
        safe = str(error) if isinstance(error, CaptureFailure) else "validation_or_storage"
        _write(staging / "failure.json", _json({
            "phase": phase, "reason": safe, "failed_at": _now().isoformat(),
            "completed_jobs": len(manifest["jobs"]), "source_only": True,
        }))
        raise CaptureFailure(safe) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    try:
        if bool(args.audit) == bool(args.output_root):
            raise ValueError("choose capture or audit")
        result = (audit(args.audit, args.seal_sha256) if args.audit
                  else capture(args.output_root, args.seal_sha256))
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print('{"passed":false,"reason":"witnessed_source_failed_see_safe_failure_artifact"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
