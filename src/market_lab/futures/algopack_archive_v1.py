"""Resumable, all-field, pre-2026 AlgoPack archive. No economic calculations."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

PROTOCOL = "algopack_archive_v1"
REPO = Path(__file__).resolve().parents[3]
CONFIG = f"configs/{PROTOCOL}.json"
TOKEN_ENV = "MOEX_ALGOPACK_TOKEN"
RETRYABLE = {429, 500, 502, 503, 504}
DATASETS = (
    "eq/tradestats", "eq/obstats", "eq/orderstats", "fo/tradestats", "fo/obstats",
    "fx/tradestats", "fx/obstats", "fx/orderstats", "eq/hi2", "fo/hi2", "fx/hi2",
    "eq/alerts", "fo/alerts", "fx/alerts",
)


class ArchiveError(ValueError):
    """Diagnostics deliberately exclude provider text and credentials."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code, self.status = code, status


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8-sig")


def write_new(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def regular(path: Path) -> None:
    if path.resolve() != path.absolute():
        raise ArchiveError("symlink_or_path_escape")


def verify(seal_sha: str) -> tuple[dict, dict]:
    if not re.fullmatch("[0-9a-f]{64}", seal_sha):
        raise ArchiveError("invalid_seal")
    path = REPO / f"configs/{PROTOCOL}.seal.json"
    raw = path.read_bytes()
    if sha(raw) != seal_sha:
        raise ArchiveError("seal_changed")
    seal = json.loads(raw.decode("utf-8-sig"))
    required = {CONFIG, f"src/market_lab/futures/{PROTOCOL}.py",
                f"tests/test_{PROTOCOL}.py", "docs/ALGOPACK_ARCHIVE_V1.md",
                "docs/ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md"}
    if seal["protocol_id"] != PROTOCOL or not required.issubset(seal["files"]):
        raise ArchiveError("incomplete_seal")
    for relative, digest in seal["files"].items():
        item = (REPO / relative).resolve()
        if not item.is_relative_to(REPO.resolve()) or sha(item.read_bytes()) != digest:
            raise ArchiveError("sealed_file_changed")
    config = read(REPO / CONFIG)
    if (config["protocol_id"] != PROTOCOL or tuple(config["datasets"]) != DATASETS
            or config["start"] != "2020-01-01" or config["end"] != "2025-12-31"
            or config["source_only"] is not True or config["live_trading_allowed"] is not False):
        raise ArchiveError("scope_changed")
    return config, seal


def jobs(config: dict) -> list[tuple[str, str]]:
    start, end = date.fromisoformat(config["start"]), date.fromisoformat(config["end"])
    if not date(2020, 1, 1) <= start <= end < date(2026, 1, 1):
        raise ArchiveError("protected_plan")
    days = [config["pilot_date"]]
    while end >= start:
        if end.isoformat() != config["pilot_date"]:
            days.append(end.isoformat())
        end -= timedelta(days=1)
    return [(dataset, day) for day in days for dataset in config["datasets"]
            if not dataset.endswith("/alerts") or day >= config["alerts_start"]]


def url_for(dataset: str, day: str, start: int) -> str:
    if (dataset not in DATASETS or type(start) is not int or start < 0
            or not date(2020, 1, 1) <= date.fromisoformat(day) < date(2026, 1, 1)
            or date.fromisoformat(day).isoformat() != day):
        raise ArchiveError("invalid_request_scope")
    params = {"date": day, "latest": 0, "start": start, "iss.meta": "off",
              "iss.only": "data,data.cursor"}
    return f"https://apim.moex.com/iss/datashop/algopack/{dataset}.json?{urlencode(params)}"


def pairs_unique(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError("duplicate_json_key")
        result[key] = value
    return result


def parse(raw: bytes, day: str, start: int) -> dict:
    """Project only schema/date/cursor; preserve numeric values without interpreting them."""
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs_unique)
        if set(payload) != {"data", "data.cursor"}:
            raise ArchiveError("unexpected_blocks")
        table, cursor = payload["data"], payload["data.cursor"]
        columns, rows = table["columns"], table["data"]
        if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                or len(columns) != len(set(columns)) or not isinstance(rows, list)
                or cursor["columns"] != ["INDEX", "TOTAL", "PAGESIZE"]
                or len(cursor["data"]) != 1 or len(cursor["data"][0]) != 3):
            raise ArchiveError("invalid_schema")
        index, total, size = cursor["data"][0]
        if (any(type(n) is not int for n in (index, total, size)) or index != start
                or total < index or size < 1 or len(rows) != min(size, total - start)):
            raise ArchiveError("incomplete_cursor")
        lower = [c.lower() for c in columns]
        if "tradedate" not in lower:
            raise ArchiveError("missing_date_column")
        position = lower.index("tradedate")
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ArchiveError("row_width")
            if row[position] != day or day >= "2026-01-01":
                raise ArchiveError("protected_or_wrong_date")
        return {"columns": columns, "rows": len(rows), "index": index,
                "total": total, "page_size": size, "date_verified": day}
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        raise ArchiveError("invalid_payload") from None


def fetch(session: requests.Session, url: str, token: str, config: dict) -> tuple[bytes, dict]:
    attempts = []
    for attempt, delay in enumerate([0, *config["retry_delays_seconds"]]):
        time.sleep(delay + config["request_interval_seconds"])
        status = None
        try:
            with session.get(url, headers={"Authorization": f"Bearer {token}",
                                           "Accept": "application/json"},
                             timeout=(15, 45), allow_redirects=False, stream=True) as response:
                status = int(response.status_code)
                if status != 200:
                    raise ArchiveError("http_status", status)
                if response.url != url:
                    raise ArchiveError("redirect_or_url_changed", status)
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > config["maximum_response_bytes"]:
                        raise ArchiveError("response_too_large", status)
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if not raw or token.encode() in raw or b"Bearer " in raw:
                    raise ArchiveError("response_safety", status)
            attempts.append({"attempt": attempt + 1, "http_status": status})
            return raw, {"retrieved_at_utc": datetime.now(UTC).isoformat(),
                         "http_status": 200, "attempts": attempts,
                         "final_url": url, "bearer_sent": True}
        except requests.RequestException:
            error = ArchiveError("transport")
        except ArchiveError as caught:
            error = caught
        attempts.append({"attempt": attempt + 1, "http_status": error.status,
                         "error": error.code})
        if ((error.code != "transport" and error.status not in RETRYABLE)
                or attempt == len(config["retry_delays_seconds"])):
            raise error from None
    raise ArchiveError("unreachable")


def page_read(directory: Path, dataset: str, day: str, index: int) -> dict:
    regular(directory)
    for name in ("page.json", "raw.json.gz"):
        regular(directory / name)
    meta = read(directory / "page.json")
    compressed = (directory / "raw.json.gz").read_bytes()
    if (meta["compressed_sha256"] != sha(compressed)
            or meta["request_url"] != url_for(dataset, day, index)):
        raise ArchiveError("stored_page_changed")
    raw = gzip.decompress(compressed)
    if meta["raw_sha256"] != sha(raw) or meta["raw_bytes"] != len(raw):
        raise ArchiveError("stored_raw_changed")
    parsed = parse(raw, day, index)
    if meta["parsed"] != parsed:
        raise ArchiveError("stored_schema_changed")
    return meta


def page_save(parent: Path, index: int, raw: bytes, meta: dict) -> None:
    """Only a committed directory is reusable; interrupted temporary dirs remain untouched."""
    destination = parent / f"page_{index:09d}"
    if destination.exists():
        raise ArchiveError("page_already_exists")
    temporary = Path(tempfile.mkdtemp(prefix=".partial_page_", dir=parent))
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    with (temporary / "raw.json.gz").open("xb") as stream:
        stream.write(compressed)
        stream.flush()
        os.fsync(stream.fileno())
    write_new(temporary / "page.json", {**meta, "raw_bytes": len(raw),
              "raw_sha256": sha(raw), "compressed_bytes": len(compressed),
              "compressed_sha256": sha(compressed)})
    temporary.rename(destination)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def collect_job(root: Path, dataset: str, day: str, config: dict,
                session: requests.Session, token: str) -> dict:
    directory = root / dataset.replace("/", "_") / day[:4] / day
    regular(directory)
    directory.mkdir(parents=True, exist_ok=True)
    index, total, columns = 0, None, None
    pages, reused, stored_bytes = [], 0, 0
    for _ in range(config["page_ceiling"]):
        page = directory / f"page_{index:09d}"
        if page.exists():
            meta = page_read(page, dataset, day, index)
            reused += 1
        else:
            if (directory / "manifest.json").exists():
                raise ArchiveError("completed_job_missing_page")
            if shutil.disk_usage(root).free < config["minimum_free_bytes"]:
                raise ArchiveError("disk_reserve")
            remaining = config.get("remaining_archive_bytes", config["maximum_archive_bytes"])
            if stored_bytes + config["maximum_response_bytes"] >= remaining:
                raise ArchiveError("archive_size_ceiling")
            raw, evidence = fetch(session, url_for(dataset, day, index), token, config)
            parsed = parse(raw, day, index)
            if total is not None and (parsed["total"] != total or parsed["columns"] != columns):
                raise ArchiveError("source_changed_during_cursor")
            page_save(directory, index, raw, {"request_url": url_for(dataset, day, index),
                                             "parsed": parsed, **evidence})
            meta = page_read(page, dataset, day, index)
        parsed = meta["parsed"]
        if total is not None and (parsed["total"] != total or parsed["columns"] != columns):
            raise ArchiveError("source_changed_during_cursor")
        total, columns = parsed["total"], parsed["columns"]
        pages.append({"path": page.name, "sha256": sha((page / "page.json").read_bytes())})
        stored_bytes += meta["compressed_bytes"] + (page / "page.json").stat().st_size
        index += parsed["rows"]
        if index == total:
            break
    else:
        raise ArchiveError("page_ceiling")
    result = {"dataset": dataset, "date": day, "rows": total, "pages": pages,
              "columns": columns, "compressed_plus_metadata_bytes": stored_bytes,
              "status": "EMPTY" if not total else "COMPLETE", "current_vintage": True,
              "original_version_verified": False, "economic_admission": False}
    manifest = directory / "manifest.json"
    if manifest.exists():
        if read(manifest) != result:
            raise ArchiveError("manifest_changed")
    else:
        write_new(manifest, result)
    return {"dataset": dataset, "date": day, "rows": total, "pages": len(pages),
            "reused_pages": reused, "status": result["status"],
            "stored_bytes": stored_bytes, "manifest_sha256": sha(manifest.read_bytes()),
            "manifest_path": str(manifest.relative_to(root))}


def status_write(root: Path, value: dict) -> None:
    """Operational checkpoint only, never used as source-completion evidence."""
    temporary = root / f".status_{os.getpid()}.json"
    with temporary.open("wb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(root / "status.json")


def run(seal_sha: str) -> dict:
    import fcntl

    config, seal = verify(seal_sha)
    if os.name != "posix" or os.getuid() != 999:
        raise ArchiveError("server_trading_lab_only")
    token = os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        raise ArchiveError("credential_missing")
    parent = Path(config["output_parent"])
    regular(parent)
    if not parent.is_dir():
        raise ArchiveError("parent_missing")
    root = parent / f"{PROTOCOL}_{seal_sha[:12]}"
    regular(root)
    root.mkdir(mode=0o750, exist_ok=True)
    with (root / ".writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = jobs(config)
        identity = {"seal_sha256": seal_sha, "config": config, "files": seal["files"],
                    "plan_sha256": sha(encoded(plan)), "planned_jobs": len(plan)}
        if (root / "identity.json").exists():
            if read(root / "identity.json") != identity:
                raise ArchiveError("archive_identity_changed")
        else:
            write_new(root / "identity.json", identity)
        if (root / "manifest.json").exists():
            raise ArchiveError("archive_already_terminal")
        result, failures, blocked = [], [], set()
        state = {"status": "RUNNING", "seal_sha256": seal_sha,
                 "planned_jobs": len(plan), "completed_jobs": 0, "rows": 0, "pages": 0,
                 "stored_bytes": 0, "failed_jobs": 0, "blocked_datasets": [],
                 "started_at_utc": datetime.now(UTC).isoformat()}
        status_write(root, state)
        try:
            with requests.Session() as session:
                for dataset, day in plan:
                    if dataset in blocked:
                        continue
                    state.update(current_dataset=dataset, current_date=day)
                    if state["stored_bytes"] >= config["maximum_archive_bytes"]:
                        raise ArchiveError("archive_size_ceiling")
                    try:
                        settings = {**config, "remaining_archive_bytes":
                                    config["maximum_archive_bytes"] - state["stored_bytes"]}
                        item = collect_job(root, dataset, day, settings, session, token)
                    except ArchiveError as error:
                        failure = {"dataset": dataset, "date": day,
                                   "error": error.code, "http_status": error.status}
                        failures.append(failure)
                        state["failed_jobs"] += 1
                        if error.status == 401 or error.code in {
                            "disk_reserve", "archive_size_ceiling",
                            "protected_or_wrong_date", "transport",
                            "stored_page_changed", "stored_raw_changed", "stored_schema_changed",
                            "completed_job_missing_page", "manifest_changed", "response_safety",
                        } or error.status in RETRYABLE:
                            raise
                        # A denied/unsupported dataset is recorded, not repeatedly probed.
                        blocked.add(dataset)
                        state["blocked_datasets"] = sorted(blocked)
                        failure_name = f"failure_{dataset.replace('/', '_')}_{time.time_ns()}.json"
                        write_new(root / failure_name, failure)
                    else:
                        result.append(item)
                        for name in ("rows", "pages", "stored_bytes"):
                            state[name] += item[name]
                        state["completed_jobs"] += 1
                    state["updated_at_utc"] = datetime.now(UTC).isoformat()
                    status_write(root, state)
                    print(json.dumps({key: state[key] for key in (
                        "completed_jobs", "rows", "pages", "failed_jobs",
                        "current_dataset", "current_date")}), flush=True)
            state["status"] = "COMPLETE" if not failures else "PARTIAL_UNAVAILABLE_DATASETS"
            final = {**state, "jobs": result, "failures": failures,
                     "unattempted_jobs": len(plan) - len(result) - len(failures),
                     "original_version_verified": False, "live_trading_allowed": False}
            verify(seal_sha)
            write_new(root / "manifest.json", final)
            status_write(root, state)
            return state
        except Exception as error:
            state["status"] = "STOPPED_INCOMPLETE"
            state["error"] = error.code if isinstance(error, ArchiveError) else type(error).__name__
            state["http_status"] = error.status if isinstance(error, ArchiveError) else None
            status_write(root, state)
            write_new(root / f"stopped_{time.time_ns()}.json", state)
            raise ArchiveError("archive_stopped_safely") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.seal_sha256)), flush=True)
    except ArchiveError as error:
        print(json.dumps({"status": "STOPPED", "error": error.code}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
