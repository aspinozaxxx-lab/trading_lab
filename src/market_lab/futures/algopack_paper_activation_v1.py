"""Verify the complete future-paper activation before any market HTTP request.

The production activation/config/bundle do not exist until execution/evaluation are ready.
This verifier never creates them or chooses F; no environment, network or market values.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures.algopack_paper_inference_v1 import TRAINED_AT, TRAINING_MANIFEST_SHA
from market_lab.futures.algopack_paper_inputs_v1 import _pairs, safe
from market_lab.futures.algopack_paper_market_core_v1 import RequestWindow

PROTOCOL = "algopack_paper_forward_v1"
ACTIVATION = f"configs/{PROTOCOL}.activation.json"
BUNDLE = f"configs/{PROTOCOL}.seal.json"
CONFIG = f"configs/{PROTOCOL}.json"
TRAINING_SEAL = "configs/algopack_paper_training_v1.seal.json"
TRAINING_SEAL_SHA = "bb95784a169fd4c163c5df4ada231404321ea6e8bf5b8271425e0c869b7ebca2"
WITNESSED_SEAL = "configs/algopack_fo_witnessed_v1.seal.json"
WITNESSED_SEAL_SHA = "67a11050689b42802b1f33797a98c47ef9974249803de72601c2b8dffb099c26"
REQUIRED = {
    CONFIG,
    f"configs/{PROTOCOL}.sha256",
    TRAINING_SEAL,
    WITNESSED_SEAL,
    "docs/ALGOPACK_PAPER_AUTHORIZATION_20260907.md",
} | {
    f"src/market_lab/futures/algopack_paper_{name}_v1.py"
    for name in (
        "activation",
        "capture",
        "market_core",
        "market_transport",
        "journal",
        "inference",
        "model",
        "alignment",
        "execution",
        "evaluation",
        "runtime",
    )
}


def now() -> datetime:
    return datetime.now(UTC)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo != UTC or result.isoformat() != value:
        raise ValueError("activation timestamp must be canonical UTC")
    return result


def decode(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=_pairs)
    json.dumps(value, allow_nan=False)
    if not isinstance(value, dict):
        raise ValueError("activation document must be a mapping")
    return value


@dataclass(frozen=True)
class VerifiedActivation:
    project: Path
    activation_sha256: str
    future_start: datetime
    bundle_sha256: str

    def request_ready(self) -> None:
        # Revalidate pinned code/config plus actual clock for EVERY request, not once per service.
        checked = load_activation(self.project, self.activation_sha256, require_started=True)
        if checked != self:
            raise ValueError("activation changed during capture")


def load_activation(
    project: Path, expected_sha: str, *, require_started: bool = True
) -> VerifiedActivation:
    path = safe(project, ACTIVATION)
    raw = path.read_bytes()
    if digest(raw) != expected_sha:
        raise ValueError("activation byte identity mismatch")
    activation = decode(raw)
    if (
        set(activation)
        != {
            "protocol_id",
            "future_start",
            "published_at",
            "bundle_sha256",
            "model_manifest_sha256",
            "live_trading_allowed",
        }
        or activation["protocol_id"] != PROTOCOL
        or activation["model_manifest_sha256"] != TRAINING_MANIFEST_SHA
        or activation["live_trading_allowed"] is not False
    ):
        raise ValueError("activation scope mismatch")
    start, published = stamp(activation["future_start"]), stamp(activation["published_at"])
    observed = now()
    RequestWindow(start, max(start, observed))  # Also enforces post-training Moscow midnight F.
    if not TRAINED_AT < published < start or published > observed:
        raise ValueError("activation publication clock mismatch")
    bundle_path = safe(project, BUNDLE)
    bundle_raw = bundle_path.read_bytes()
    if digest(bundle_raw) != activation["bundle_sha256"]:
        raise ValueError("future bundle identity mismatch")
    bundle = decode(bundle_raw)
    if (
        bundle["protocol_id"] != PROTOCOL
        or bundle["live_trading_allowed"] is not False
        or not TRAINED_AT < stamp(bundle["declared_at_utc"]) <= published
        or not set(bundle["files"]) >= REQUIRED
    ):
        raise ValueError("incomplete future execution/evaluation closure")
    paths = [path, bundle_path]
    for name, expected in bundle["files"].items():
        dependency = safe(project, name)
        if digest(dependency.read_bytes()) != expected:
            raise ValueError("future code/config dependency mismatch")
        paths.append(dependency)
    # Immutable training dependency closure must survive transitively, not just its manifest name.
    for parent_path, parent_sha in (
        (TRAINING_SEAL, TRAINING_SEAL_SHA),
        (WITNESSED_SEAL, WITNESSED_SEAL_SHA),
    ):
        if bundle["files"][parent_path] != parent_sha:
            raise ValueError("wrong parent source/model seal")
        parent = decode(safe(project, parent_path).read_bytes())
        if any(bundle["files"].get(name) != sha for name, sha in parent["files"].items()):
            raise ValueError("missing/changed transitive parent dependency")
    config_raw = safe(project, CONFIG).read_bytes()
    sidecar = safe(project, f"configs/{PROTOCOL}.sha256").read_text(encoding="utf-8-sig")
    if sidecar.strip() != digest(config_raw):
        raise ValueError("future config sidecar mismatch")
    config = decode(config_raw)
    if (
        config["protocol_id"] != PROTOCOL
        or config["paper_only"] is not True
        or config["live_trading_allowed"] is not False
        or config["future_start"] is not None
        or config["execution_protocol_id"] != "algopack_paper_execution_v1"
        or config["evaluation_protocol_id"] != "algopack_paper_evaluation_v1"
    ):
        raise ValueError("future config safety/protocol mismatch")
    # Reject even byte-identical late deployment: a declared old timestamp alone is not proof.
    if any(max(item.stat().st_mtime, item.stat().st_ctime) >= start.timestamp() for item in paths):
        raise ValueError("future boundary precedes actual deployment")
    if require_started and observed < start:
        raise ValueError("WAIT_FUTURE_BOUNDARY")
    return VerifiedActivation(project, expected_sha, start, activation["bundle_sha256"])
