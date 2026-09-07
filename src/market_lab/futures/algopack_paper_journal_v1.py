"""Immutable Linux paper-event journal. No market IO, activation, or execution authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, TEN, utc
from market_lab.futures.algopack_paper_inference_v1 import MODEL_SHA, TRAINED_AT
from market_lab.futures.algopack_paper_model_v1 import TARGET_COLUMNS

MAX_PAYLOAD = 32 * 1024 * 1024
KINDS = {"source", "forecast"}


def now() -> datetime:
    return datetime.now(UTC)


def encode(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    )


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate journal JSON key")
        result[key] = value
    return result


def _ordinary(path: Path, *, directory: bool = False) -> None:
    if not path.is_absolute() or path.resolve() != path.absolute():
        raise ValueError("journal path must be absolute without symlinks")
    info = path.lstat()
    if (
        not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or not directory
        and info.st_nlink != 1
    ):
        raise ValueError("journal requires ordinary unlinked files")


def _sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, raw: bytes) -> None:
    _ordinary(path.parent, directory=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read(path: Path, limit: int = MAX_PAYLOAD) -> bytes:
    _ordinary(path)
    if path.stat().st_size > limit:
        raise ValueError("journal artifact exceeds limit")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("journal artifact changed size")
    return raw


def _decode(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=_pairs)
    # Also rejects nonfinite JSON extensions, which Python accepts when decoding.
    encode(value)
    if not isinstance(value, dict):
        raise ValueError("journal record must be a mapping")
    return value


@contextmanager
def _lock(root: Path):
    if os.name != "posix":
        raise ValueError("durable journal requires Linux server")
    import fcntl

    _ordinary(root, directory=True)
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("journal root must be private and runtime-owned")
    path = root / ".journal.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _ordinary(path)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _key(kind: str, key: str) -> None:
    if (
        kind not in KINDS
        or not isinstance(key, str)
        or re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", key) is None
    ):
        raise ValueError("invalid journal kind/key")


def _boundary(start: datetime, observed: datetime) -> None:
    if utc(start) <= TRAINED_AT or utc(observed) < utc(start):
        raise ValueError("journal clock precedes permitted future boundary")


def publish(root: Path, *, kind: str, key: str, future_start: datetime, payload: dict) -> dict:
    """Exclusive event reservation survives failure; never replace or retry that key.

    Source callers still owe source schema/raw replay and full activation validation.
    Commit proves durable payload, not that any prediction was consumed before entry.
    """
    _key(kind, key)
    begun = now()
    _boundary(future_start, begun)
    if not isinstance(payload, dict):
        raise ValueError("journal payload must be a mapping")
    raw = encode(payload)
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("journal payload exceeds limit")
    with _lock(root):
        parent = root / kind
        if not parent.exists():
            parent.mkdir(mode=0o700)
            _sync_dir(root)
        _ordinary(parent, directory=True)
        event = parent / key
        event.mkdir(mode=0o700, exist_ok=False)
        _sync_dir(parent)
        header = dict(
            kind=kind,
            key=key,
            future_start=utc(future_start).isoformat(),
            begun_at=begun.isoformat(),
            live_trading_allowed=False,
        )
        _write(event / "STARTED.json", encode(header))
        _write(event / "payload.json", raw)
        record = dict(**header, payload=dict(path="payload.json", bytes=len(raw), sha256=sha(raw)))
        record_raw = encode(record)
        _write(event / "record.json", record_raw)
        if _read(event / "payload.json") != raw or _read(event / "record.json") != record_raw:
            raise ValueError("journal readback differs")
        _sync_dir(event)
        durable = now()  # All payload/record bytes AND their directory entries already fsynced.
        if durable < begun:
            raise ValueError("journal clock discontinuity")
        marker = dict(
            record_sha256=sha(record_raw),
            durable_payload_at=durable.isoformat(),
            state="RECORDED_NOT_CONSUMED",
            live_trading_allowed=False,
        )
        _write(event / "COMMITTED.json", encode(marker))
        _sync_dir(event)
        acknowledged = now()
        if acknowledged < durable:
            raise ValueError("journal acknowledgment clock discontinuity")
        return dict(
            kind=kind,
            key=key,
            record_sha256=sha(record_raw),
            durable_payload_at=durable.isoformat(),
            acknowledged_at=acknowledged.isoformat(),
            state="RECORDED_NOT_CONSUMED",
            execution_admitted=False,
        )


def observe(root: Path, *, kind: str, key: str, record_sha256: str, future_start: datetime) -> dict:
    """Verify metadata before payload read; actual post-read observation is the usable clock."""
    _key(kind, key)
    _boundary(future_start, now())
    if re.fullmatch(r"[0-9a-f]{64}", record_sha256) is None:
        raise ValueError("invalid expected journal identity")
    with _lock(root):
        event = root / kind / key
        _ordinary(event, directory=True)
        if {path.name for path in event.iterdir()} != {
            "STARTED.json",
            "payload.json",
            "record.json",
            "COMMITTED.json",
        }:
            raise ValueError("incomplete or unexpected journal membership")
        record_raw = _read(event / "record.json", 8192)
        if sha(record_raw) != record_sha256:
            raise ValueError("journal record identity mismatch")
        record = _decode(record_raw)
        marker = _decode(_read(event / "COMMITTED.json", 8192))
        started = _decode(_read(event / "STARTED.json", 8192))
        header = {
            name: record[name]
            for name in ("kind", "key", "future_start", "begun_at", "live_trading_allowed")
        }
        if (
            header != started
            or record["kind"] != kind
            or record["key"] != key
            or record["future_start"] != utc(future_start).isoformat()
            or record["live_trading_allowed"] is not False
            or marker["record_sha256"] != record_sha256
            or marker["state"] != "RECORDED_NOT_CONSUMED"
            or marker["live_trading_allowed"] is not False
        ):
            raise ValueError("journal commit/header mismatch")
        begun = utc(datetime.fromisoformat(record["begun_at"]))
        durable = utc(datetime.fromisoformat(marker["durable_payload_at"]))
        if not utc(future_start) <= begun <= durable <= now():
            raise ValueError("journal event clock mismatch")
        ref = record["payload"]
        if (
            ref["path"] != "payload.json"
            or type(ref["bytes"]) is not int
            or not 0 <= ref["bytes"] <= MAX_PAYLOAD
        ):
            raise ValueError("invalid journal payload declaration")
        raw = _read(event / "payload.json")
        if len(raw) != ref["bytes"] or sha(raw) != ref["sha256"]:
            raise ValueError("journal payload identity mismatch")
        payload = _decode(raw)
        observed = now()
        if observed < durable:
            raise ValueError("journal observation clock discontinuity")
        return dict(
            payload=payload,
            kind=kind,
            key=key,
            record_sha256=record_sha256,
            observed_at=observed.isoformat(),
            durable_payload_at=durable.isoformat(),
            execution_admitted=False,
        )


def forecast_key(candidate: dict) -> str:
    end = utc(datetime.fromisoformat(candidate["information_end"]))
    cutoff = utc(datetime.fromisoformat(candidate["input_cutoff"]))
    completed = utc(datetime.fromisoformat(candidate["completed_at"]))
    start = utc(datetime.fromisoformat(candidate["future_start"]))
    if (
        candidate["state"] != "COMPUTED_NOT_PERSISTED"
        or candidate["live_trading_allowed"] is not False
        or candidate["execution_admitted"] is not False
        or not start <= end <= cutoff <= completed
        or end.minute % 10
        or end.second
        or end.microsecond
        or candidate["planned_entry_at"] != (end + TEN).isoformat()
        or candidate["target_exit_at"] != (end + 7 * TEN).isoformat()
        or set(candidate["arms"]) != set(MODEL_SHA)
        or candidate["target_names"] != list(TARGET_COLUMNS)
        or [row["asset"] for row in candidate["assets"]] != list(ASSETS)
    ):
        raise ValueError("invalid computed forecast declaration")
    _boundary(start, completed)
    observations = candidate["source_observations"]
    if not isinstance(observations, list) or not observations:
        raise ValueError("forecast source observations are required")
    seen = set()
    for observation in observations:
        _key(observation["kind"], observation["key"])
        if (
            observation["kind"] != "source"
            or observation["key"] in seen
            or re.fullmatch(r"[0-9a-f]{64}", observation["record_sha256"]) is None
            or not start <= utc(datetime.fromisoformat(observation["observed_at"])) <= cutoff
        ):
            raise ValueError("invalid as-of forecast source reference")
        seen.add(observation["key"])
    for name, arm in candidate["arms"].items():
        if arm["model_sha256"] != MODEL_SHA[name]:
            raise ValueError("forecast model identity mismatch")
        if arm["status"] == "READY":
            values = arm["prediction"]
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError("invalid forecast prediction width")
            if completed >= end + TEN:
                raise ValueError("late computed forecast cannot be READY")
            encode(values)  # Reject nonfinite; None/strings/bools are not predictions.
            if any(type(value) not in (float, int) for value in values):
                raise ValueError("invalid forecast prediction values")
        elif arm["prediction"] is not None:
            raise ValueError("sleeping forecast carries a prediction")
    return end.strftime("%Y%m%dT%H%M%SZ")


def publish_forecast(root: Path, candidate: dict) -> dict:
    key = forecast_key(candidate)
    if utc(datetime.fromisoformat(candidate["completed_at"])) > now():
        raise ValueError("cannot publish a future computation")
    for source in candidate["source_observations"]:
        checked = observe(
            root,
            kind="source",
            key=source["key"],
            record_sha256=source["record_sha256"],
            future_start=datetime.fromisoformat(candidate["future_start"]),
        )
        if utc(datetime.fromisoformat(checked["durable_payload_at"])) > utc(
            datetime.fromisoformat(source["observed_at"])
        ):
            raise ValueError("source was not published at claimed observation time")
    return publish(
        root,
        kind="forecast",
        key=key,
        future_start=datetime.fromisoformat(candidate["future_start"]),
        payload=candidate,
    )


def consume_forecast(root: Path, reference: dict, future_start: datetime) -> dict:
    """Late observation masks both arms. This is still not an executable order/fill."""
    if reference["kind"] != "forecast":
        raise ValueError("not a forecast reference")
    record = observe(
        root,
        kind="forecast",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=future_start,
    )
    candidate = record["payload"]
    if (
        forecast_key(candidate) != reference["key"]
        or candidate["future_start"] != utc(future_start).isoformat()
        or utc(datetime.fromisoformat(candidate["completed_at"]))
        > utc(datetime.fromisoformat(record["durable_payload_at"]))
    ):
        raise ValueError("forecast key differs from information boundary")
    observed = utc(datetime.fromisoformat(record["observed_at"]))
    deadline = utc(datetime.fromisoformat(candidate["planned_entry_at"]))
    if observed >= deadline:
        for arm in candidate["arms"].values():
            arm["status"], arm["prediction"] = "MISSED_CONSUMPTION_DEADLINE", None
    return dict(**record, state="OBSERVED_NOT_EXECUTION_ADMITTED")
