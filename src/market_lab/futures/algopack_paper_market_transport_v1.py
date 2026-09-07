"""Bounded transport primitive; callable only by a future sealed activation runtime.

No CLI, environment loading, timer, persistence, retry, or implicit source admission.
This primitive is not itself permission to fetch prices before all future-paper seals.
"""

from __future__ import annotations

import hashlib
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures import algopack_paper_market_core_v1 as core

CA_PATH = Path("/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem")
CA_SHA = "aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399"
MAX_BYTES = 2 * 1024 * 1024


class CaptureFailure(Exception):
    """Only an enumerated phase is exposed, never HTTP bodies, headers, or tokens."""


def now() -> datetime:
    return datetime.now(UTC)


def check_ca() -> None:
    if (
        CA_PATH.resolve() != CA_PATH.absolute()
        or CA_PATH.is_symlink()
        or not CA_PATH.is_file()
        or hashlib.sha256(CA_PATH.read_bytes()).hexdigest() != CA_SHA
    ):
        raise CaptureFailure("ca_identity")


def capture_response(
    session,
    *,
    kind: str,
    asset: str,
    secid: str,
    future_start: datetime,
    token: str,
    deadline: float,
    start: int = 0,
) -> dict:
    """The caller must verify the full activation seal BEFORE entering this function."""
    try:
        window = core.RequestWindow(future_start, now())
        url = core.request_url(kind, asset, secid, window, start)
    except (ValueError, TypeError, AttributeError):
        raise CaptureFailure("request_scope_or_future_boundary") from None
    if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
        raise CaptureFailure("credential")
    check_ca()
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise CaptureFailure("deadline")
    mono_start = time.monotonic()
    remaining = deadline - mono_start
    if remaining <= 0:
        raise CaptureFailure("deadline")
    try:
        # requests-style session: redirects disabled, pinned application CA, no fallback host.
        with session.get(
            url,
            headers={"Accept": "application/json", "Authorization": "Bearer " + token},
            timeout=min(30.0, remaining),
            allow_redirects=False,
            stream=True,
            verify=str(CA_PATH),
        ) as response:
            if response.status_code != 200 or response.url != url:
                raise CaptureFailure("http_status_or_redirect")
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > MAX_BYTES:
                    raise CaptureFailure("response_limit")
                if time.monotonic() > deadline:
                    raise CaptureFailure("deadline")
                chunks.append(chunk)
            raw = b"".join(chunks)
        completed = now()
        elapsed = time.monotonic() - mono_start
        if not raw or token.encode() in raw:
            raise CaptureFailure("empty_or_secret_reflection")
        if (
            completed < window.requested_at
            or abs((completed - window.requested_at).total_seconds() - elapsed) > 2
        ):
            raise CaptureFailure("clock_discontinuity")
        parser = {
            "candles": core.parse_candles,
            "orderbook": core.parse_orderbook,
            "specs": core.parse_specs,
        }[kind]
        try:
            normalized = parser(raw, asset=asset, secid=secid, window=window, received_at=completed)
        except Exception:
            raise CaptureFailure("schema_or_source_time") from None
        validated = now()
        if validated < completed:
            raise CaptureFailure("clock_discontinuity")
        if time.monotonic() > deadline:
            raise CaptureFailure("deadline")
        return dict(
            raw=raw,
            normalized=normalized,
            receipt=dict(
                url=url,
                http_status=200,
                request_started_at=window.requested_at.isoformat(),
                response_completed_at=completed.isoformat(),
                validation_completed_at=validated.isoformat(),
                request_elapsed_seconds=elapsed,
                raw_bytes=len(raw),
                raw_sha256=hashlib.sha256(raw).hexdigest(),
            ),
            state="VALIDATED_NOT_PERSISTED",
            available_at=None,
            execution_admitted=False,
        )
    except CaptureFailure:
        raise
    except Exception:
        raise CaptureFailure("transport") from None
