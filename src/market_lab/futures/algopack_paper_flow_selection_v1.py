"""Fixed latest-completed witnessed-flow selection without price or outcome inspection."""

from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures import algopack_paper_predictor_v1 as predictor
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, WITNESSED_SEAL_SHA
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW

journal, source = predictor.journal, predictor.source
PROTOCOL = "algopack_paper_flow_selection_v1"


def ready(activation):
    predictor._ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_flow_selection_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("flow selector absent from complete activation")


def select(activation):
    ready(activation)
    cutoff = journal.now()
    journal._boundary(activation.future_start, cutoff)
    source._ordinary(predictor.FLOW_ROOT, directory=True)
    candidates = []
    for path in predictor.FLOW_ROOT.iterdir():
        if predictor.CAPTURE_ID.fullmatch(path.name) is None:
            continue  # Includes .incomplete_*: never import an unfinished collection.
        started = datetime.strptime(path.name.split("_")[0], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
        if (
            not activation.future_start <= started <= cutoff
            or started.astimezone(MOSCOW).date() != cutoff.astimezone(MOSCOW).date()
        ):
            continue  # No pre-F/prior-day manifest or artifact reads.
        source._ordinary(path, directory=True)
        raw = source._read(path / "manifest.json")
        manifest = source.core._decode(raw)
        available = source._stamp(manifest["available_at"])
        if (
            manifest["capture_id"] != path.name
            or manifest["protocol_id"] != source.PROTOCOL
            or manifest["seal_sha256"] != WITNESSED_SEAL_SHA
            or source._stamp(manifest["started_at"]) != started
            or available < started
        ):
            raise ValueError("candidate flow metadata identity/clock mismatch")
        if available <= cutoff:
            candidates.append((available, path.name, source.sha(raw)))
    chosen = max(candidates) if candidates else None
    return dict(
        protocol_id=PROTOCOL,
        state="SELECTED_NOT_IMPORTED" if chosen else "MISSING_FLOW",
        selection_cutoff=cutoff.isoformat(),
        metadata_observed_at=journal.now().isoformat(),
        capture_id=chosen[1] if chosen else None,
        manifest_sha256=chosen[2] if chosen else None,
        source_available_at=chosen[0].isoformat() if chosen else None,
        candidate_count=len(candidates),
        execution_admitted=False,
    )


def select_and_import(root: Path, activation):
    selection = select(activation)
    if selection["capture_id"] is None:
        return dict(selection=selection, reference=None)
    key = "flow_" + selection["capture_id"]
    event_path = root / "source" / key
    if event_path.exists() or event_path.is_symlink():
        marker = journal._decode(journal._read(event_path / "COMMITTED.json"))
        reference = dict(kind="source", key=key, record_sha256=marker["record_sha256"])
        observed = predictor.observe_flow(root, reference, activation)
        # observe_flow verifies the saved projection and current manifest by full replay.
        record = journal.observe(
            root,
            kind="source",
            key=key,
            record_sha256=reference["record_sha256"],
            future_start=activation.future_start,
        )
        if record["payload"]["projection"]["manifest_sha256"] != selection["manifest_sha256"]:
            raise ValueError("selected manifest differs from previously imported flow")
        if observed["source_observation"]["key"] != key:
            raise ValueError("flow observation identity mismatch")
    else:
        reference = predictor.import_flow(
            root, selection["capture_id"], selection["manifest_sha256"], activation
        )
    return dict(selection=selection, reference=reference)
