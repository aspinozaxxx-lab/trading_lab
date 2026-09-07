"""Witnessed-flow bridge and target-free forecast publication; no orders or scheduler."""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime
from pathlib import Path

from market_lab.futures import algopack_paper_capture_v1 as market
from market_lab.futures import algopack_paper_inference_v1 as inference
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures import moex_algopack_fo_witnessed_v1 as source
from market_lab.futures.algopack_paper_activation_v1 import (
    BUNDLE,
    WITNESSED_SEAL_SHA,
    VerifiedActivation,
)
from market_lab.futures.algopack_paper_alignment_v1 import FIELDS, FIVE, FlowVersion, bucket_end

PROTOCOL = "algopack_paper_predictor_v1"
FLOW_ROOT = Path("/srv/trading_lab_data/data/forward/algopack-fo-witnessed-v1")
MODEL_ROOT = Path(
    "/srv/trading_lab_data/runs/algopack-paper-training/algopack_paper_training_v1_bb95784a169f"
)
CAPTURE_ID = re.compile(r"[0-9]{8}T[0-9]{12}Z_[0-9a-f]{12}")


def _ready(activation: VerifiedActivation) -> None:
    if not isinstance(activation, VerifiedActivation):
        raise ValueError("verified activation required")
    activation.request_ready()
    # Added after the parent verifier: require this bridge in the same checked closure.
    bundle = source.core._decode(source._read(activation.project / BUNDLE))
    name = "src/market_lab/futures/algopack_paper_predictor_v1.py"
    if bundle["files"].get(name) != source.sha(source._read(Path(__file__))):
        raise ValueError("predictor absent or different in activated closure")


def load_flow(capture_id: str, manifest_sha256: str, activation: VerifiedActivation) -> dict:
    """Replay the sealed flow-only source; pre-F captures rejected before artifact IO."""
    _ready(activation)
    if not isinstance(capture_id, str) or CAPTURE_ID.fullmatch(capture_id) is None:
        raise ValueError("invalid witnessed capture identity")
    inference.sha(manifest_sha256)
    path = FLOW_ROOT / capture_id
    source._ordinary(FLOW_ROOT, directory=True)
    source._ordinary(path, directory=True)
    raw = source._read(path / "manifest.json")
    manifest = source.core._decode(raw)
    started = source._stamp(manifest["started_at"])
    available = source._stamp(manifest["available_at"])
    if (
        source.sha(raw) != manifest_sha256
        or manifest["capture_id"] != capture_id
        or manifest["protocol_id"] != source.PROTOCOL
        or manifest["seal_sha256"] != WITNESSED_SEAL_SHA
        or not activation.future_start <= started <= available <= journal.now()
    ):
        raise ValueError("flow manifest identity or prospective boundary mismatch")
    audit = source.audit(path, WITNESSED_SEAL_SHA)
    if audit["manifest_sha256"] != manifest_sha256 or audit["passed"] is not True:
        raise ValueError("flow source replay failed")
    rows, total, excluded = [], 0, 0
    for job in manifest["jobs"]:
        values = json.loads(
            gzip.decompress(source._artifact(path, job["normalized"])),
            object_pairs_hook=source.core._pairs,
            parse_constant=source.core._constant,
        )
        if not isinstance(values, list) or len(values) != job["rows"]:
            raise ValueError("flow normalized count drift")
        for index, row in enumerate(values):
            total += 1
            end = bucket_end(row["tradedate"], row["tradetime"])
            # Current collector may include prior days or forward vendor labels.
            # These are flow-only permitted archives, but not post-F completed features.
            if end - FIVE < activation.future_start or end > available:
                excluded += 1
                continue
            dataset, asset, secid = source.core.row_key(row)[:3]
            if (dataset, asset, secid) != tuple(
                job["job"][key] for key in ("dataset", "asset_code", "secid")
            ):
                raise ValueError("flow job identity drift")
            masked = row["asset_code_missing"] or row["asset_code_mismatch"]
            version = source.sha(
                f"{manifest_sha256}:{job['normalized']['sha256']}:{index}".encode()
            )
            projected = [None if masked else row[field] for field in FIELDS[dataset]]
            # Validate the exact model projection now, before publication.
            FlowVersion(
                dataset,
                asset,
                secid,
                row["tradedate"],
                row["tradetime"],
                available,
                version,
                tuple(projected),
            )
            rows.append(
                dict(
                    dataset=dataset,
                    asset=asset,
                    secid=secid,
                    tradedate=row["tradedate"],
                    tradetime=row["tradetime"],
                    version_sha256=version,
                    values=projected,
                )
            )
    if total != manifest["rows"] or source._read(path / "manifest.json") != raw:
        raise ValueError("flow source changed during assembly")
    if journal.now() < available:
        raise ValueError("flow observation clock reversed")
    return dict(
        capture_id=capture_id,
        manifest_sha256=manifest_sha256,
        source_available_at=available.isoformat(),
        rows=rows,
        excluded_uncompleted_or_pre_F=excluded,
    )


def import_flow(
    root: Path, capture_id: str, manifest_sha256: str, activation: VerifiedActivation
) -> dict:
    projection = load_flow(capture_id, manifest_sha256, activation)
    _ready(activation)
    return journal.publish(
        root,
        kind="source",
        key="flow_" + capture_id,
        future_start=activation.future_start,
        payload=dict(
            protocol_id=PROTOCOL,
            source_type="witnessed_flow",
            activation_sha256=activation.activation_sha256,
            projection=projection,
            execution_admitted=False,
        ),
    )


def observe_flow(root: Path, reference: dict, activation: VerifiedActivation) -> dict:
    _ready(activation)
    if reference["kind"] != "source":
        raise ValueError("flow source reference required")
    event = journal.observe(
        root,
        kind="source",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    payload = event["payload"]
    if (
        payload["protocol_id"] != PROTOCOL
        or payload["source_type"] != "witnessed_flow"
        or payload["activation_sha256"] != activation.activation_sha256
        or payload["execution_admitted"] is not False
    ):
        raise ValueError("invalid flow publication")
    saved = payload["projection"]
    projection = load_flow(saved["capture_id"], saved["manifest_sha256"], activation)
    if (
        journal.encode(projection) != journal.encode(saved)
        or reference["key"] != "flow_" + saved["capture_id"]
    ):
        raise ValueError("flow publication differs from witnessed replay")
    available = journal.now()
    if available < source._stamp(event["observed_at"]):
        raise ValueError("flow observation clock reversed")
    versions = tuple(
        FlowVersion(
            row["dataset"],
            row["asset"],
            row["secid"],
            row["tradedate"],
            row["tradetime"],
            available,
            row["version_sha256"],
            tuple(row["values"]),
        )
        for row in projection["rows"]
    )
    return dict(
        versions=versions,
        source_observation=dict(
            kind="source",
            key=reference["key"],
            record_sha256=reference["record_sha256"],
            observed_at=available.isoformat(),
        ),
    )


def predict_slot(
    root: Path,
    *,
    activation: VerifiedActivation,
    information_end: datetime,
    market_reference: dict,
    flow_reference: dict | None,
) -> dict:
    """Consume verified sources, compute once and publish; no future labels are accepted.

    None flow is an explicit missing-source observation: baseline may still predict.
    A corrupt supplied flow source fails, rather than silently masquerading as missing.
    """
    _ready(activation)
    inputs = market.model_inputs(market.observe_packet(root, market_reference, activation))
    versions = ()
    references = [inputs["source_observation"]]
    if flow_reference is not None:
        flow = observe_flow(root, flow_reference, activation)
        versions = flow["versions"]
        references.append(flow["source_observation"])
    models = inference.load_fixed_models(MODEL_ROOT)
    cutoff = journal.now()
    prepared = inference.prepare_features(
        information_end=information_end,
        input_cutoff=cutoff,
        future_start=activation.future_start,
        plans=inputs["plans"],
        bars=inputs["bars"],
        flow=versions,
    )
    result = inference.predict_prepared(prepared, models)
    candidate = inference.complete_forecast(result, completed_at=journal.now())
    candidate["source_observations"] = references
    _ready(activation)
    return journal.publish_forecast(root, candidate)
