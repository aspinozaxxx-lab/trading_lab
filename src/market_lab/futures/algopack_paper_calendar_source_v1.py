"""Activation-gated current-day calendar receipts; no automatic scheduling or admission."""

from __future__ import annotations

import base64
import hashlib
import time
from datetime import date
from pathlib import Path

from market_lab.futures import algopack_paper_calendar_core_v1 as core
from market_lab.futures import algopack_paper_execution_source_v1 as source
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures import algopack_paper_market_transport_v1 as transport
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, VerifiedActivation

PROTOCOL = "algopack_paper_calendar_source_v1"


def ready(activation: VerifiedActivation) -> None:
    source.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != activation.bundle_sha256:
        raise ValueError("calendar activation bundle changed")
    files = source._decode(raw)["files"]
    for module in (__file__, core.__file__):
        path = Path(module)
        if (
            files.get("src/market_lab/futures/" + path.name)
            != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise ValueError("calendar source/core missing from activation")


def current_window(activation: VerifiedActivation) -> core.CalendarWindow:
    window = source.market.RequestWindow(activation.future_start, journal.now())
    day = date.fromisoformat(window.day)
    return core.CalendarWindow(day, day)


def fetch(session, activation: VerifiedActivation, *, token: str, start: int) -> dict:
    ready(activation)
    window = current_window(activation)
    url = core.request_url(window, start)
    if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
        raise transport.CaptureFailure("credential")
    if getattr(session, "trust_env", False) or getattr(session, "auth", None) is not None:
        raise transport.CaptureFailure("ambient_session_auth")
    transport.check_ca()
    requested, begun = journal.now(), time.monotonic()
    try:
        with session.get(
            url,
            headers={"Accept": "application/json", "Authorization": "Bearer " + token},
            timeout=10.0,
            verify=str(transport.CA_PATH),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200 or response.url != url:
                raise ValueError("status or redirect")
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > core.MAX_BYTES or time.monotonic() - begun > 10:
                    raise ValueError("response limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
        received = journal.now()
        if time.monotonic() - begun > 10 or not raw or token.encode() in raw:
            raise ValueError("deadline, empty or secret reflection")
        if current_window(activation) != window:
            raise ValueError("calendar request crossed day boundary")
        page = core.Page(start, requested, received, raw)
        normalized = core.parse_page(page, window)
        return dict(
            start=start,
            day=window.first.isoformat(),
            url=url,
            requested_at=requested.isoformat(),
            received_at=received.isoformat(),
            validated_at=journal.now().isoformat(),
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            raw_base64=base64.b64encode(raw).decode("ascii"),
            normalized=normalized,
        )
    except Exception:
        raise transport.CaptureFailure("calendar_fetch") from None


def replay_step(
    step: dict, activation: VerifiedActivation
) -> tuple[core.Page, core.CalendarWindow]:
    requested = source._stamp(step["requested_at"])
    received = source._stamp(step["received_at"])
    validated = source._stamp(step["validated_at"])
    scope = source.market.RequestWindow(activation.future_start, requested)
    window = core.CalendarWindow(date.fromisoformat(scope.day), date.fromisoformat(scope.day))
    if (
        step["day"] != scope.day
        or step["url"] != core.request_url(window, step["start"])
        or not requested <= received <= validated
        or source.market.RequestWindow(activation.future_start, validated).day != scope.day
    ):
        raise ValueError("calendar receipt scope/chronology")
    if not isinstance(step["raw_base64"], str) or len(step["raw_base64"]) > core.MAX_BYTES * 2:
        raise ValueError("calendar encoded byte limit")
    raw = base64.b64decode(step["raw_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != step["raw_sha256"]:
        raise ValueError("calendar raw hash mismatch")
    page = core.Page(step["start"], requested, received, raw)
    if journal.encode(core.parse_page(page, window)) != journal.encode(step["normalized"]):
        raise ValueError("calendar raw normalization mismatch")
    return page, window


def collect(session, root: Path, key: str, activation: VerifiedActivation, *, token: str) -> dict:
    ready(activation)
    window = current_window(activation)
    journal._key("source", key)
    if len(key) > 60:
        raise ValueError("calendar key too long")
    journal.publish(
        root,
        kind="source",
        key=key + "_started",
        future_start=activation.future_start,
        payload=dict(protocol_id=PROTOCOL, state="STARTED", day=window.first.isoformat()),
    )
    refs, pages = [], []
    try:
        for index in range(2):
            step = fetch(session, activation, token=token, start=index)
            page, actual_window = replay_step(step, activation)
            if actual_window != window:
                raise ValueError("calendar collection crossed day")
            refs.append(
                journal.publish(
                    root,
                    kind="source",
                    key=f"{key}_p{index}",
                    future_start=activation.future_start,
                    payload=dict(protocol_id=PROTOCOL, state="RESPONSE", step=step),
                )
            )
            pages.append(page)
            if index == 0:
                time.sleep(0.5)
        result = core.replay(tuple(pages), window, observed_at=journal.now())
        ready(activation)
        return journal.publish(
            root,
            kind="source",
            key=key,
            future_start=activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                state="COMPLETE",
                steps=refs,
                activation_sha256=activation.activation_sha256,
                day=window.first.isoformat(),
                replay_sha256=result["replay_sha256"],
                execution_admitted=False,
            ),
        )
    except Exception:
        journal.publish(
            root,
            kind="source",
            key=key + "_failed",
            future_start=activation.future_start,
            payload=dict(protocol_id=PROTOCOL, state="FAILED", completed_responses=len(refs)),
        )
        raise transport.CaptureFailure("calendar_collection") from None


def observe(root: Path, reference: dict, activation: VerifiedActivation) -> dict:
    ready(activation)
    if reference["kind"] != "source":
        raise ValueError("calendar source reference required")

    def read(ref):
        if ref["kind"] != "source":
            raise ValueError("calendar source reference kind")
        return journal.observe(
            root,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=activation.future_start,
        )

    event = read(reference)
    payload = event["payload"]
    if (
        payload["protocol_id"] != PROTOCOL
        or payload["state"] != "COMPLETE"
        or payload["activation_sha256"] != activation.activation_sha256
        or payload["execution_admitted"] is not False
        or len(payload["steps"]) != 2
    ):
        raise ValueError("calendar publication identity")
    pages, previous = [], activation.future_start
    for index, ref in enumerate(payload["steps"]):
        if ref["key"] != f"{reference['key']}_p{index}":
            raise ValueError("calendar page reference key")
        part = read(ref)
        if part["payload"]["protocol_id"] != PROTOCOL or part["payload"]["state"] != "RESPONSE":
            raise ValueError("calendar response identity")
        step = part["payload"]["step"]
        page, window = replay_step(step, activation)
        durable = source._stamp(part["durable_payload_at"])
        if (
            step["day"] != payload["day"]
            or step["start"] != index
            or page.requested_at < previous
            or source._stamp(step["validated_at"]) > durable
            or durable > source._stamp(event["durable_payload_at"])
        ):
            raise ValueError("calendar durable chronology")
        previous = durable
        pages.append(page)
    result = core.replay(tuple(pages), window, observed_at=journal.now())
    if result["replay_sha256"] != payload["replay_sha256"]:
        raise ValueError("calendar publication replay mismatch")
    return dict(
        **result,
        state="OBSERVED_CALENDAR_NOT_REPORT_ADMITTED",
        durable_payload_at=event["durable_payload_at"],
        source_observation=dict(
            kind="source",
            key=reference["key"],
            record_sha256=reference["record_sha256"],
            observed_at=journal.now().isoformat(),
        ),
    )
