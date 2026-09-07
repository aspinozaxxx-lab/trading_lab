"""Activation-gated market packet capture, immutable per-response evidence and full replay."""

from __future__ import annotations

import base64
import hashlib
import math
import time
from datetime import date, datetime
from pathlib import Path

from market_lab.futures import algopack_fo_witnessed_core_v1 as discovery
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures import algopack_paper_market_core_v1 as market
from market_lab.futures import algopack_paper_market_transport_v1 as transport
from market_lab.futures import moex_algopack_fo_witnessed_v1 as metadata_transport
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation
from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, utc
from market_lab.futures.algopack_paper_inference_v1 import ContractPlan
from market_lab.futures.algopack_paper_model_v1 import PriceBar

PROTOCOL = "algopack_paper_capture_v1"
MAX_SECONDS = 120
SPACING_SECONDS = 0.5
MAX_STEPS = 22  # Two metadata + four assets * (three candle pages + book + specs).


def _stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if utc(stamp).isoformat() != value:
        raise ValueError("packet receipt timestamp must be canonical UTC")
    return stamp


def stored_response(response: dict) -> dict:
    if (
        response["state"] != "VALIDATED_NOT_PERSISTED"
        or response["available_at"] is not None
        or response["execution_admitted"] is not False
    ):
        raise ValueError("wrong transport result state")
    return dict(
        raw_base64=base64.b64encode(response["raw"]).decode("ascii"),
        normalized=response["normalized"],
        receipt=response["receipt"],
    )


def replay_response(step: dict, future_start: datetime) -> tuple[bytes, object]:
    response, kind = step["response"], step["kind"]
    receipt = response["receipt"]
    raw = base64.b64decode(response["raw_base64"], validate=True)
    if (
        len(raw) > transport.MAX_BYTES
        or type(receipt["raw_bytes"]) is not int
        or len(raw) != receipt["raw_bytes"]
        or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]
    ):
        raise ValueError("packet raw byte identity mismatch")
    started, completed, validated = (
        _stamp(receipt[name])
        for name in ("request_started_at", "response_completed_at", "validation_completed_at")
    )
    window = market.RequestWindow(future_start, started)
    if not started <= completed <= validated:
        raise ValueError("packet receipt chronology mismatch")
    elapsed = receipt["request_elapsed_seconds"]
    if (
        type(elapsed) not in (int, float)
        or not math.isfinite(elapsed)
        or elapsed < 0
        or abs((completed - started).total_seconds() - elapsed) > 2
        or receipt["http_status"] != 200
    ):
        raise ValueError("packet transport receipt mismatch")
    if kind in discovery.metadata_urls():
        if receipt["url"] != discovery.metadata_urls()[kind]:
            raise ValueError("metadata request scope mismatch")
        expected_columns = discovery.RFUD_COLUMNS if kind == "rfud" else discovery.SERIES_COLUMNS
        block = "securities" if kind == "rfud" else "series"
        payload = discovery._decode(raw)
        if set(payload) != {block}:
            raise ValueError("unexpected metadata block")
        normalized = discovery._block(payload, block, expected_columns)
    else:
        if receipt["url"] != market.request_url(
            kind, step["asset"], step["secid"], window, step["start"]
        ):
            raise ValueError("market request scope mismatch")
        parser = {
            "candles": market.parse_candles,
            "orderbook": market.parse_orderbook,
            "specs": market.parse_specs,
        }[kind]
        normalized = parser(
            raw, asset=step["asset"], secid=step["secid"], window=window, received_at=completed
        )
    if journal.encode(normalized) != journal.encode(response["normalized"]):
        raise ValueError("packet normalization differs from raw replay")
    return raw, normalized


def replay_packet(steps: list[dict], *, future_start: datetime, completed_at: datetime) -> dict:
    if not 14 <= len(steps) <= MAX_STEPS:
        raise ValueError("packet requires metadata and four complete asset groups")
    if [step["kind"] for step in steps[:2]] != ["rfud", "series"]:
        raise ValueError("metadata must precede market values")
    replayed = []
    previous = utc(future_start)
    day = None
    for step in steps:
        receipt = step["response"]["receipt"]
        started, validated = (
            _stamp(receipt["request_started_at"]),
            _stamp(receipt["validation_completed_at"]),
        )
        window = market.RequestWindow(future_start, started)
        if day is None:
            day = window.day
        if window.day != day or not previous <= started <= validated <= utc(completed_at):
            raise ValueError("packet step date/order mismatch")
        previous = validated
        replayed.append(replay_response(step, future_start))
    selected = discovery.select_contracts(replayed[0][0], replayed[1][0], day)
    plans = [next(row for row in selected if row["asset_code"] == asset) for asset in ASSETS]
    assets, number = [], 2
    for plan in plans:
        pages, cursor = [], 0
        for _ in range(3):
            if number >= len(steps):
                raise ValueError("missing candle terminal page")
            step = steps[number]
            if (
                step["kind"] != "candles"
                or step["asset"] != plan["asset_code"]
                or step["secid"] != plan["secid"]
                or step["start"] != cursor
            ):
                raise ValueError("packet candle cursor/identity mismatch")
            page = replayed[number][1]
            pages.append(page)
            number += 1
            cursor += len(page)
            if not page:
                break
        candles = market.finish_candle_pages(pages)
        parts = {}
        for kind in ("orderbook", "specs"):
            if number >= len(steps):
                raise ValueError("missing packet market response")
            step = steps[number]
            if (
                step["kind"] != kind
                or step["asset"] != plan["asset_code"]
                or step["secid"] != plan["secid"]
                or step["start"] != 0
            ):
                raise ValueError("packet market group mismatch")
            parts[kind] = replayed[number][1]
            number += 1
        if parts["specs"]["values"]["LASTTRADEDATE"] != plan["last_trade_date"]:
            raise ValueError("spec expiry differs from discovery plan")
        assets.append(dict(plan=plan, candles=candles, **parts))
    if number != len(steps):
        raise ValueError("unexpected trailing packet steps")
    return dict(
        day=day,
        assets=assets,
        vendor_atomic_snapshot_proven=False,
        available_at=None,
        execution_admitted=False,
    )


def capture_packet(
    session, *, activation: VerifiedActivation, root: Path, key: str, token: str
) -> dict:
    if not isinstance(activation, VerifiedActivation):
        raise ValueError("verified activation is required")
    activation.request_ready()
    journal._key("source", key)
    if len(key) > 64:
        raise ValueError("packet key too long")
    start = activation.future_start
    deadline = time.monotonic() + MAX_SECONDS
    begun = journal.now()
    journal.publish(
        root,
        kind="source",
        key=key + "_started",
        future_start=start,
        payload=dict(
            protocol_id=PROTOCOL,
            packet_state="STARTED",
            packet_key=key,
            activation_sha256=activation.activation_sha256,
        ),
    )
    refs, steps = [], []

    def save(step):
        replay_response(step, start)
        ref = journal.publish(
            root,
            kind="source",
            key=f"{key}_p{len(steps):03d}",
            future_start=start,
            payload=dict(protocol_id=PROTOCOL, packet_state="RESPONSE", step=step),
        )
        refs.append(ref)
        steps.append(step)

    try:
        metadata_raw = {}
        for kind, url in discovery.metadata_urls().items():
            activation.request_ready()
            raw, receipt = metadata_transport._fetch(session, url, token, deadline)
            block = "securities" if kind == "rfud" else "series"
            columns = discovery.RFUD_COLUMNS if kind == "rfud" else discovery.SERIES_COLUMNS
            decoded = discovery._decode(raw)
            if set(decoded) != {block}:
                raise ValueError("unexpected discovery blocks")
            normalized = discovery._block(decoded, block, columns)
            receipt = dict(
                **receipt,
                validation_completed_at=journal.now().isoformat(),
                raw_bytes=len(raw),
                raw_sha256=hashlib.sha256(raw).hexdigest(),
            )
            save(
                dict(
                    kind=kind,
                    response=dict(
                        raw_base64=base64.b64encode(raw).decode("ascii"),
                        normalized=normalized,
                        receipt=receipt,
                    ),
                )
            )
            metadata_raw[kind] = raw
            time.sleep(SPACING_SECONDS)
        day = market.RequestWindow(start, begun).day
        selected = discovery.select_contracts(metadata_raw["rfud"], metadata_raw["series"], day)
        plans = [next(row for row in selected if row["asset_code"] == asset) for asset in ASSETS]
        for plan in plans:
            cursor = 0
            for _ in range(3):
                activation.request_ready()
                response = transport.capture_response(
                    session,
                    kind="candles",
                    asset=plan["asset_code"],
                    secid=plan["secid"],
                    future_start=start,
                    token=token,
                    deadline=deadline,
                    start=cursor,
                )
                save(
                    dict(
                        kind="candles",
                        asset=plan["asset_code"],
                        secid=plan["secid"],
                        start=cursor,
                        response=stored_response(response),
                    )
                )
                count = len(response["normalized"])
                cursor += count
                time.sleep(SPACING_SECONDS)
                if not count:
                    break
            else:
                raise ValueError("candle pagination did not terminate")
            for kind in ("orderbook", "specs"):
                activation.request_ready()
                response = transport.capture_response(
                    session,
                    kind=kind,
                    asset=plan["asset_code"],
                    secid=plan["secid"],
                    future_start=start,
                    token=token,
                    deadline=deadline,
                )
                save(
                    dict(
                        kind=kind,
                        asset=plan["asset_code"],
                        secid=plan["secid"],
                        start=0,
                        response=stored_response(response),
                    )
                )
                time.sleep(SPACING_SECONDS)
        reread = []
        for ref in refs:
            event = journal.observe(
                root,
                kind="source",
                key=ref["key"],
                record_sha256=ref["record_sha256"],
                future_start=start,
            )
            reread.append(event["payload"]["step"])
        completed = journal.now()
        normalized = replay_packet(reread, future_start=start, completed_at=completed)
        activation.request_ready()
        if time.monotonic() > deadline:
            raise ValueError("capture deadline")
        return journal.publish(
            root,
            kind="source",
            key=key,
            future_start=start,
            payload=dict(
                protocol_id=PROTOCOL,
                packet_state="COMPLETE",
                activation_sha256=activation.activation_sha256,
                started_at=begun.isoformat(),
                completed_at=completed.isoformat(),
                steps=refs,
                normalized=normalized,
                execution_admitted=False,
            ),
        )
    except Exception:
        journal.publish(
            root,
            kind="source",
            key=key + "_failed",
            future_start=start,
            payload=dict(
                protocol_id=PROTOCOL,
                packet_state="FAILED",
                packet_key=key,
                validated_responses=len(refs),
                phase="capture_or_replay",
                execution_admitted=False,
            ),
        )
        raise transport.CaptureFailure("capture_or_replay") from None


def observe_packet(root: Path, reference: dict, activation: VerifiedActivation) -> dict:
    activation.request_ready()
    event = journal.observe(
        root,
        kind="source",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    packet = event["payload"]
    if (
        packet["protocol_id"] != PROTOCOL
        or packet["packet_state"] != "COMPLETE"
        or packet["activation_sha256"] != activation.activation_sha256
        or packet["execution_admitted"] is not False
    ):
        raise ValueError("packet is not a complete admitted source capture")
    steps = []
    for ref in packet["steps"]:
        step = journal.observe(
            root,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=activation.future_start,
        )
        if (
            step["payload"]["protocol_id"] != PROTOCOL
            or step["payload"]["packet_state"] != "RESPONSE"
            or _stamp(step["durable_payload_at"]) > _stamp(packet["completed_at"])
        ):
            raise ValueError("invalid packet response reference")
        steps.append(step["payload"]["step"])
    normalized = replay_packet(
        steps, future_start=activation.future_start, completed_at=_stamp(packet["completed_at"])
    )
    if journal.encode(normalized) != journal.encode(packet["normalized"]):
        raise ValueError("packet aggregate differs from replay")
    observed = journal.now()
    if observed < _stamp(event["observed_at"]):
        raise ValueError("packet observation clock reversed")
    return dict(
        normalized=normalized,
        available_at=observed.isoformat(),
        source_observation=dict(
            kind="source",
            key=reference["key"],
            record_sha256=reference["record_sha256"],
            observed_at=observed.isoformat(),
        ),
        execution_admitted=False,
    )


def model_inputs(observed_packet: dict) -> dict:
    """Adapt only a fully replayed observed packet; actual availability is never backdated."""
    available = _stamp(observed_packet["available_at"])
    reference = observed_packet["source_observation"]
    normalized = observed_packet["normalized"]
    if (
        observed_packet["execution_admitted"] is not False
        or reference["kind"] != "source"
        or reference["observed_at"] != available.isoformat()
        or normalized["available_at"] is not None
        or [row["plan"]["asset_code"] for row in normalized["assets"]] != list(ASSETS)
    ):
        raise ValueError("invalid observed packet assembly")
    plans, bars = [], []
    for group in normalized["assets"]:
        row = group["plan"]
        asset, secid = row["asset_code"], row["secid"]
        contract = f"{asset}:{secid}:{row['last_trade_date']}"
        expiry = min(row["last_trade_date"], row["expiration_date"])
        plans.append(
            ContractPlan(
                asset,
                secid,
                contract,
                date.fromisoformat(normalized["day"]),
                date.fromisoformat(expiry),
                available,
                reference["record_sha256"],
            )
        )
        for candle in group["candles"]:
            if (
                candle["asset"] != asset
                or candle["secid"] != secid
                or candle["available_at"] is not None
            ):
                raise ValueError("packet candle identity/availability mismatch")
            bars.append(
                PriceBar(
                    asset,
                    secid,
                    contract,
                    _stamp(candle["begin"]),
                    _stamp(candle["end"]),
                    available,
                    reference["record_sha256"],
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                )
            )
    return dict(plans=tuple(plans), bars=tuple(bars), source_observation=reference)
