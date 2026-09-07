"""Real readiness traversal over an isolated synthetic activation, no market/model IO."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from market_lab.futures import algopack_paper_activation_v1 as activation
from market_lab.futures import algopack_paper_runtime_v2 as runtime

pytestmark = pytest.mark.skipif(os.name != "posix", reason="actual Linux readiness")


def test_full_readiness_cost_and_tamper_detection(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[1]
    start = datetime(2099, 9, 7, 21, tzinfo=UTC)
    published = start - timedelta(hours=1)
    monkeypatch.setattr(activation, "now", lambda: start + timedelta(hours=1))

    def write(name, raw):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return activation.digest(raw)

    def document(name, value):
        return write(name, json.dumps(value, sort_keys=True).encode())

    # Copy only code/config/doc closure. Production models/data/activation never read.
    names = set(activation.REQUIRED)
    for parent in (activation.TRAINING_SEAL, activation.WITNESSED_SEAL):
        names.update(activation.decode((project / parent).read_bytes())["files"])
    names.update(
        path.relative_to(project).as_posix()
        for path in (project / "src/market_lab/futures").glob("algopack_paper_*.py")
    )
    names -= {activation.CONFIG, f"configs/{activation.PROTOCOL}.sha256"}
    files = {name: write(name, (project / name).read_bytes()) for name in sorted(names)}
    config_sha = document(
        activation.CONFIG,
        dict(
            protocol_id=activation.PROTOCOL,
            paper_only=True,
            live_trading_allowed=False,
            future_start=None,
            execution_protocol_id="algopack_paper_execution_v1",
            evaluation_protocol_id="algopack_paper_evaluation_v1",
            runtime_protocol=runtime.PROTOCOL,
        ),
    )
    files[activation.CONFIG] = config_sha
    files[f"configs/{activation.PROTOCOL}.sha256"] = write(
        f"configs/{activation.PROTOCOL}.sha256", config_sha.encode()
    )
    bundle_sha = document(
        activation.BUNDLE,
        dict(
            protocol_id=activation.PROTOCOL,
            live_trading_allowed=False,
            declared_at_utc=(published - timedelta(minutes=1)).isoformat(),
            files=files,
        ),
    )
    identity = document(
        activation.ACTIVATION,
        dict(
            protocol_id=activation.PROTOCOL,
            future_start=start.isoformat(),
            published_at=published.isoformat(),
            bundle_sha256=bundle_sha,
            model_manifest_sha256=activation.TRAINING_MANIFEST_SHA,
            live_trading_allowed=False,
        ),
    )
    checked = activation.load_activation(tmp_path, identity)
    original = activation.load_activation
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(activation, "load_activation", counted)
    samples = []
    for _ in range(3):
        before = calls
        begin = time.perf_counter()
        runtime.ready(checked)
        samples.append(dict(seconds=time.perf_counter() - begin, full_checks=calls - before))
    assert samples[0]["full_checks"] > 0
    assert len({row["full_checks"] for row in samples}) == 1
    print(json.dumps(dict(synthetic_only=True, closure_files=len(files), samples=samples)))
    # No cached success may hide a subsequent dependency mutation.
    write("src/market_lab/futures/algopack_paper_execution_v1.py", b"synthetic mutation")
    with pytest.raises(ValueError, match="dependency mismatch"):
        runtime.ready(checked)
