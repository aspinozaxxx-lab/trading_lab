"""Single-attempt forecast slot orchestration; durable attempts, no broker execution."""

from datetime import timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_capture_v1 as capture
from market_lab.futures import algopack_paper_coverage_v1 as coverage
from market_lab.futures import algopack_paper_mark_refresh_v1 as marks
from market_lab.futures import algopack_paper_predictor_v1 as predictor
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE
from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, MOSCOW, utc

bridge, journal = marks.bridge, marks.journal
PROTOCOL = "algopack_paper_slot_runner_v1"


def ready(activation):
    marks.ready(activation)
    predictor._ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_slot_runner_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("slot runner absent from complete activation")


def run(runtime, session, attempts: Path, *, information_end, token, flow_reference=None):
    activation = runtime.account.activation
    ready(activation)
    end = utc(information_end)
    if end not in coverage.slots(end.astimezone(MOSCOW).date()) or end < activation.future_start:
        raise ValueError("invalid forward slot")
    if not end + timedelta(minutes=3) <= journal.now() < end + timedelta(minutes=10):
        return dict(status="OUTSIDE_SLOT_WINDOW", execution_admitted=False)
    if attempts in (runtime.market_root, runtime.account.control, runtime.account.ledger):
        raise ValueError("dedicated attempt journal required")
    key = "slot_" + end.strftime("%Y%m%dT%H%M%SZ")

    def record(suffix, **payload):
        return journal.publish(
            attempts,
            kind="source",
            key=key + suffix,
            future_start=activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                information_end=end.isoformat(),
                activation_sha256=activation.activation_sha256,
                execution_admitted=False,
                **payload,
            ),
        )

    with bridge.anchors.transaction(attempts):
        start = attempts / "source" / (key + "_started")
        if start.exists() or start.is_symlink():
            return dict(status="EXISTING_ATTEMPT_NOT_REEXECUTED", execution_admitted=False)
        record("_started", state="STARTED")
        phase = "capture"
        try:
            market = capture.capture_packet(
                session,
                activation=activation,
                root=runtime.market_root,
                key=key + "_market",
                token=token,
            )
            phase = "predict"
            forecast = predictor.predict_slot(
                runtime.market_root,
                activation=activation,
                information_end=end,
                market_reference=market,
                flow_reference=flow_reference,
            )
            phase = "consume"
            consumed = journal.consume_forecast(
                runtime.market_root, forecast, activation.future_start
            )
            record(
                "_consumed",
                state="CONSUMED",
                forecast=forecast,
                observed_at=consumed["observed_at"],
                arm_status={arm: row["status"] for arm, row in consumed["payload"]["arms"].items()},
            )
            phase = "calendar"
            if journal.now() >= end + timedelta(minutes=10):
                raise ValueError("slot deadline passed before execution sources")
            calendar = bridge.source.collect(
                session,
                runtime.market_root,
                key=key + "_calendar",
                activation=activation,
                kind="calendar",
                token=token,
            )
            phase = "mark"
            references = {}
            for index, (position, row) in enumerate(
                sorted(runtime.account.snapshot()["positions"].items())
            ):
                if row["entry"] is not None:
                    references[position] = bridge.source.collect(
                        session,
                        runtime.market_root,
                        key=key + f"_mark{index}",
                        activation=activation,
                        kind="quote",
                        token=token,
                        asset=row["intent"]["asset"],
                        secid=row["intent"]["secid"],
                    )
            marks.refresh(runtime, references)
            phase = "decisions"
            assets = {row["asset"]: row for row in consumed["payload"]["assets"]}
            outcomes = []
            for asset in ASSETS:
                if journal.now() >= end + timedelta(minutes=10):
                    raise ValueError("slot decision deadline passed")
                quote = bridge.source.collect(
                    session,
                    runtime.market_root,
                    key=key + "_" + asset,
                    activation=activation,
                    kind="quote",
                    token=token,
                    asset=asset,
                    secid=assets[asset]["secid"],
                )
                for arm in journal.MODEL_SHA:
                    suffix = "_" + arm + "_" + asset
                    record(suffix + "_started", state="DECISION_STARTED", arm=arm, asset=asset)
                    result = runtime.reserve(
                        asset=asset,
                        arm=arm,
                        forecast_reference=forecast,
                        quote_reference=quote,
                        calendar_reference=calendar,
                    )
                    record(
                        suffix + "_finished",
                        state="DECISION_FINISHED",
                        arm=arm,
                        asset=asset,
                        result=result,
                    )
                    outcomes.append(dict(arm=arm, asset=asset, status=result["status"]))
            record("_finished", state="COMPLETE", outcomes=outcomes)
            return dict(status="COMPLETE", outcomes=outcomes, execution_admitted=False)
        except Exception:
            # Publication failures propagate if even the failure journal cannot be saved.
            record("_failed", state="FAILED", phase=phase)
            return dict(status="FAILED", phase=phase, execution_admitted=False)
