"""Offline numerical forecast reproduction from raw sources and pinned model bytes."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_predictor_v1 as predictor
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE

journal, inference, market = predictor.journal, predictor.inference, predictor.market
PROTOCOL = "algopack_paper_forecast_audit_v1"


def ready(activation):
    predictor._ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_forecast_audit_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("forecast audit absent from complete activation")


def original_observation(root, reference, activation, cutoff):
    if reference["kind"] != "source":
        raise ValueError("forecast requires source observation")
    record = journal.observe(
        root,
        kind="source",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    observed = market._stamp(reference["observed_at"])
    if (
        not activation.future_start
        <= market._stamp(record["durable_payload_at"])
        <= observed
        <= cutoff
    ):
        raise ValueError("original forecast input observation chronology mismatch")
    return observed


def audit(root: Path, reference: dict, activation):
    ready(activation)
    if reference["kind"] != "forecast":
        raise ValueError("forecast reference required")
    record = journal.observe(
        root,
        kind="forecast",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    candidate = record["payload"]
    end, cutoff, completed = (
        market._stamp(candidate[name])
        for name in ("information_end", "input_cutoff", "completed_at")
    )
    if (
        journal.forecast_key(candidate) != reference["key"]
        or candidate["future_start"] != activation.future_start.isoformat()
        or completed > market._stamp(record["durable_payload_at"])
    ):
        raise ValueError("forecast publication identity/clock mismatch")
    refs = candidate["source_observations"]
    if len(refs) not in (1, 2):
        raise ValueError("fixed market plus optional flow source list required")
    observed = [original_observation(root, ref, activation, cutoff) for ref in refs]
    current = market.model_inputs(market.observe_packet(root, refs[0], activation))
    # New immutable copies reconstruct original evidence; live observations stay current.
    plans = tuple(replace(row, available_at=observed[0]) for row in current["plans"])
    bars = tuple(replace(row, available_at=observed[0]) for row in current["bars"])
    versions = ()
    if len(refs) == 2:
        replayed = predictor.observe_flow(root, refs[1], activation)
        versions = tuple(replace(row, available_at=observed[1]) for row in replayed["versions"])
    prepared = inference.prepare_features(
        information_end=end,
        input_cutoff=cutoff,
        future_start=activation.future_start,
        plans=plans,
        bars=bars,
        flow=versions,
    )
    models = inference.load_fixed_models(predictor.MODEL_ROOT)  # No fit, labels or model selection.
    expected = inference.predict_prepared(prepared, models)
    # Reconstruct the original completion gate; never backdate a new forecast.
    if completed >= end + timedelta(minutes=10):
        for arm in expected["arms"].values():
            arm["status"], arm["prediction"] = "MISSED_PUBLICATION_DEADLINE", None
    expected.update(
        state="COMPUTED_NOT_PERSISTED",
        completed_at=completed.isoformat(),
        planned_entry_at=(end + timedelta(minutes=10)).isoformat(),
        target_exit_at=(end + timedelta(minutes=70)).isoformat(),
        execution_admitted=False,
        source_observations=refs,
    )
    if journal.encode(expected) != journal.encode(candidate):
        raise ValueError("saved forecast differs from fixed-model source reconstruction")
    return dict(
        protocol_id=PROTOCOL,
        status="FORECAST_RECOMPUTED",
        forecast_recomputed=True,
        forecast_sha256=reference["record_sha256"],
        audited_at=journal.now().isoformat(),
        model_sha256=dict(inference.MODEL_SHA),
        execution_admitted=False,
        target_income_verified=False,
    )
