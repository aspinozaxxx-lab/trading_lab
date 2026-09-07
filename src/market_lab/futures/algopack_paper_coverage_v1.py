"""Complete fixed-slot forecast publication coverage, not execution or profit evidence."""

from datetime import date, datetime, time, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_execution_bridge_v1 as bridge
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

journal = bridge.journal
PROTOCOL = "algopack_paper_coverage_v1"


def ready(activation):
    bridge.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_coverage_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("coverage module absent from complete activation")


def slots(day: date) -> tuple:
    if type(day) is not date or day.weekday() >= 5:
        raise ValueError("weekday evaluation date required")
    first = datetime.combine(day, time(10, 10), MOSCOW)
    return tuple(utc(first + timedelta(minutes=10 * index)) for index in range(42))


def build(root: Path, activation, day: date) -> dict:
    ready(activation)
    ends = slots(day)
    at = journal.now()
    journal._boundary(activation.future_start, at)
    if ends[0] < activation.future_start or at < ends[-1] + timedelta(minutes=10):
        raise ValueError("pre-boundary or immature coverage day")
    journal._ordinary(root, directory=True)
    parent = root / "forecast"
    if parent.exists() or parent.is_symlink():
        journal._ordinary(parent, directory=True)
    counts = {
        arm: dict.fromkeys(("ready", "sleep", "failed", "missing"), 0) for arm in journal.MODEL_SHA
    }
    rows = []
    for end in ends:
        key = end.strftime("%Y%m%dT%H%M%SZ")
        path = root / "forecast" / key
        categories = dict.fromkeys(journal.MODEL_SHA, "missing")
        observation, reason = None, "MISSING_PUBLICATION"
        if path.exists() or path.is_symlink():
            categories = dict.fromkeys(journal.MODEL_SHA, "failed")
            reason = "INVALID_OR_INCOMPLETE_PUBLICATION"
            try:
                marker = journal._decode(journal._read(path / "COMMITTED.json"))
                record = journal.observe(
                    root,
                    kind="forecast",
                    key=key,
                    record_sha256=marker["record_sha256"],
                    future_start=activation.future_start,
                )
                value = record["payload"]
                if (
                    journal.forecast_key(value) != key
                    or value["future_start"] != utc(activation.future_start).isoformat()
                    or bridge.source._stamp(value["completed_at"])
                    > bridge.source._stamp(record["durable_payload_at"])
                ):
                    raise ValueError("forecast identity/chronology mismatch")
                # Recheck prior durable source references. This is not a raw-source audit.
                for ref in value["source_observations"]:
                    source = journal.observe(
                        root,
                        kind="source",
                        key=ref["key"],
                        record_sha256=ref["record_sha256"],
                        future_start=activation.future_start,
                    )
                    if bridge.source._stamp(source["durable_payload_at"]) > bridge.source._stamp(
                        ref["observed_at"]
                    ):
                        raise ValueError("source unavailable at declared observation")
                observation = {
                    name: record[name]
                    for name in (
                        "kind",
                        "key",
                        "record_sha256",
                        "observed_at",
                        "durable_payload_at",
                    )
                }
                if bridge.source._stamp(record["durable_payload_at"]) >= end + timedelta(
                    minutes=10
                ):
                    reason = "LATE_PUBLICATION"
                else:
                    reason = "OBSERVED_PUBLICATION"
                    for arm, row in value["arms"].items():
                        categories[arm] = {"READY": "ready", "SLEEP_MISSING_FEATURES": "sleep"}.get(
                            row["status"], "failed"
                        )
            except (OSError, ValueError, KeyError, TypeError):
                categories = dict.fromkeys(journal.MODEL_SHA, "failed")
                observation, reason = None, "INVALID_OR_INCOMPLETE_PUBLICATION"
        for arm, category in categories.items():
            counts[arm][category] += 4
        rows.append(
            dict(
                information_end=end.isoformat(),
                categories=categories,
                reason=reason,
                observation=observation,
            )
        )
    return dict(
        protocol_id=PROTOCOL,
        state="COVERAGE_NOT_PERSISTED",
        day=day.isoformat(),
        activation_sha256=activation.activation_sha256,
        source_root=str(root),
        observed_at=journal.now().isoformat(),
        expected_slots=42,
        expected_asset_decisions_per_arm=168,
        arms=counts,
        slots=rows,
        execution_admitted=False,
        forecast_consumption_verified=False,
    )


def publish(root: Path, reports: Path, activation, day: date) -> dict:
    if root == reports:
        raise ValueError("separate coverage report root required")
    result = build(root, activation, day)
    return journal.publish(
        reports,
        kind="source",
        key="coverage_" + day.strftime("%Y%m%d"),
        future_start=activation.future_start,
        payload=result,
    )
