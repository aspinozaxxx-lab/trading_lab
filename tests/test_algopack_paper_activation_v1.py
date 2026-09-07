"""Synthetic activation registry only; no real F, economic code or market requests."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from market_lab.futures import algopack_paper_activation_v1 as activation

START = datetime(2099, 9, 7, 21, tzinfo=UTC)
PUBLISHED = START - timedelta(hours=1)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return activation.digest(raw)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(activation, "now", lambda: START + timedelta(hours=1))
    for name in activation.REQUIRED:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic dependency only")
    config = dict(
        protocol_id=activation.PROTOCOL,
        paper_only=True,
        live_trading_allowed=False,
        future_start=None,
        execution_protocol_id="algopack_paper_execution_v1",
        evaluation_protocol_id="algopack_paper_evaluation_v1",
    )
    config_sha = write(tmp_path / activation.CONFIG, config)
    (tmp_path / f"configs/{activation.PROTOCOL}.sha256").write_text(config_sha)
    for name, attr in (
        (activation.TRAINING_SEAL, "TRAINING_SEAL_SHA"),
        (activation.WITNESSED_SEAL, "WITNESSED_SEAL_SHA"),
    ):
        # Fake parent closure is explicitly substituted only in this fixture.
        monkeypatch.setattr(activation, attr, write(tmp_path / name, dict(files={})))
    files = {
        name: activation.digest((tmp_path / name).read_bytes()) for name in activation.REQUIRED
    }
    bundle = dict(
        protocol_id=activation.PROTOCOL,
        live_trading_allowed=False,
        declared_at_utc=(PUBLISHED - timedelta(minutes=1)).isoformat(),
        files=files,
    )
    bundle_sha = write(tmp_path / activation.BUNDLE, bundle)
    value = dict(
        protocol_id=activation.PROTOCOL,
        future_start=START.isoformat(),
        published_at=PUBLISHED.isoformat(),
        bundle_sha256=bundle_sha,
        model_manifest_sha256=activation.TRAINING_MANIFEST_SHA,
        live_trading_allowed=False,
    )
    sha = write(tmp_path / activation.ACTIVATION, value)
    return tmp_path, sha, value, bundle


def test_complete_identity_registry_and_per_request_revalidation(registry):
    root, sha, _, _ = registry
    checked = activation.load_activation(root, sha)
    checked.request_ready()
    (root / "src/market_lab/futures/algopack_paper_execution_v1.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="dependency"):
        checked.request_ready()


def test_no_activation_file_no_admission(tmp_path):
    with pytest.raises(FileNotFoundError):
        activation.load_activation(tmp_path, "a" * 64)


def test_before_f_only_nonrequest_inspection_allowed(registry, monkeypatch):
    root, sha, _, _ = registry
    monkeypatch.setattr(activation, "now", lambda: PUBLISHED + timedelta(minutes=1))
    checked = activation.load_activation(root, sha, require_started=False)
    with pytest.raises(ValueError, match="WAIT_FUTURE_BOUNDARY"):
        checked.request_ready()


@pytest.mark.parametrize(
    "changes",
    [
        dict(live_trading_allowed=True),
        dict(model_manifest_sha256="0" * 64),
        dict(future_start=(START + timedelta(minutes=1)).isoformat()),
        dict(published_at=START.isoformat()),
    ],
)
def test_invalid_scope_or_chronology(registry, changes):
    root, _, value, _ = registry
    sha = write(root / activation.ACTIVATION, {**value, **changes})
    with pytest.raises(ValueError):
        activation.load_activation(root, sha)


def test_missing_economic_dependency_rejected_even_with_fresh_hash(registry):
    root, _, value, bundle = registry
    del bundle["files"]["src/market_lab/futures/algopack_paper_evaluation_v1.py"]
    value["bundle_sha256"] = write(root / activation.BUNDLE, bundle)
    sha = write(root / activation.ACTIVATION, value)
    with pytest.raises(ValueError, match="execution/evaluation"):
        activation.load_activation(root, sha)


def test_backdated_f_rejected_by_actual_file_timestamp(registry):
    import os

    root, sha, _, _ = registry
    path = root / "src/market_lab/futures/algopack_paper_runtime_v1.py"
    os.utime(path, (START.timestamp() + 1, START.timestamp() + 1))
    with pytest.raises(ValueError, match="actual deployment"):
        activation.load_activation(root, sha)
