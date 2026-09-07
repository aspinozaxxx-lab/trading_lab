"""Publication-label metadata diagnostic; timestamps never grant version or model admission."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as arrow
import pyarrow.json as arrow_json

from market_lab.futures import algopack_fo_history_core_v1 as core
from market_lab.futures import algopack_fo_history_quality_v1 as quality
from market_lab.futures import moex_algopack_fo_history_v1 as history

PROTOCOL = "algopack_fo_publication_metadata_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PARENT_SEAL = "configs/algopack_fo_history_quality_v1.seal.json"
PARENT_SHA = "b57b9b226d63842dd0a3c09bafcd98746bcd48f383324f53e0b1bb4558f260ba"
SOURCE_SEAL = "c5fb0b96b12d77f5c01b1625b0b9b7ab582ed82d09117dc6217d577de33751d1"
SOURCE_MANIFEST = "f50fa60a6986070d45f6a69555076df1f5748d09b70407131591740e77425fb4"
COLUMNS = ["dataset", "requested_asset_code", "secid", "tradedate", "tradetime", "SYSTIME"]
BINS = ["negative", "[0,60)", "[60,300)", "[300,600)", "[600,3600)",
        "[3600,86400)", ">=86400"]
CONFIG = {
    "protocol_id": PROTOCOL,
    "source_path": "data/processed/algopack/moex_algopack_fo_history_v1_c5fb0b96b12d",
    "source_seal_sha256": SOURCE_SEAL, "source_manifest_sha256": SOURCE_MANIFEST,
    "expected_rows": 2067949, "expected_jobs": 294, "expected_pairs": 147,
    "expected_pages": 2198, "columns": COLUMNS, "label_gap_seconds_bins": BINS,
    "publication_holdout_boundary": "2026-01-01",
    "output_parent": "data/processed/algopack_quality",
    "vendor_statement": "SYSTIME is publication time; per-version correction policy unresolved",
    "evidence_doc": "docs/ALGOPACK_VENDOR_REPLY_20260907.md",
    "publication_clock_timezone_verified": False,
    "label_gap_is_measured_delivery_latency": False,
    **quality.FLAGS,
}
OWN_FILES = {f"src/market_lab/futures/{PROTOCOL}.py", f"tests/test_{PROTOCOL}.py",
             f"configs/{PROTOCOL}.json", f"configs/{PROTOCOL}.sha256", CONFIG["evidence_doc"]}


def verify_seal(digest: str) -> dict:
    parent_raw = quality._safe(PROJECT_ROOT, PARENT_SEAL).read_bytes()
    if core.sha(parent_raw) != PARENT_SHA:
        raise ValueError("publication parent closure differs")
    parent = quality._load(PROJECT_ROOT / PARENT_SEAL)
    raw = quality._safe(PROJECT_ROOT, f"configs/{PROTOCOL}.seal.json").read_bytes()
    seal = json.loads(raw, object_pairs_hook=core._json_pairs)
    if (core.sha(raw) != digest or seal.get("protocol_id") != PROTOCOL
            or set(seal.get("files", {})) != set(parent["files"]) | OWN_FILES | {PARENT_SEAL}
            or any(seal["files"].get(path) != value for path, value in parent["files"].items())
            or seal["files"][PARENT_SEAL] != PARENT_SHA):
        raise ValueError("publication source closure differs")
    for name, expected in seal["files"].items():
        if quality._hash(quality._safe(PROJECT_ROOT, name)) != expected:
            raise ValueError("publication dependency drift")
    config_raw = quality._safe(PROJECT_ROOT, f"configs/{PROTOCOL}.json").read_bytes()
    sidecar = quality._safe(PROJECT_ROOT, f"configs/{PROTOCOL}.sha256")
    if (json.loads(config_raw) != CONFIG
            or sidecar.read_text(encoding="utf-8-sig").split() != [core.sha(config_raw)]):
        raise ValueError("publication fixed config differs")
    core.verify_seal(SOURCE_SEAL)
    return seal


def _metadata(path: Path):
    schema = arrow.schema([(column, arrow.string()) for column in COLUMNS])
    options = arrow_json.ParseOptions(explicit_schema=schema, unexpected_field_behavior="ignore")
    if path.stat().st_size == 0:
        return
    with arrow_json.open_json(path, parse_options=options) as reader:
        for batch in reader:
            if batch.schema != schema:
                raise ValueError("publication projection schema drift")
            yield from batch.to_pylist()


def _bucket(seconds: float) -> str:
    for bound, label in zip((0, 60, 300, 600, 3600, 86400), BINS[:-1], strict=True):
        if seconds < bound:
            return label
    return BINS[-1]


def _empty() -> dict:
    return {"rows": 0, "same_calendar_date": 0, "later_calendar_date": 0,
            "earlier_calendar_date": 0, "publication_in_or_after_2026": 0,
            "minimum_systime": None, "maximum_systime": None,
            "minimum_label_gap_seconds": None, "maximum_label_gap_seconds": None,
            "label_gap_bins": dict.fromkeys(BINS, 0), "publication_years": {}}


def _parse(row: dict, job: dict) -> tuple[datetime, datetime]:
    if (set(row) != set(COLUMNS) or any(not isinstance(value, str) for value in row.values())
            or row["dataset"] != job["dataset"] or row["requested_asset_code"] != job["asset_code"]
            or row["secid"] != job["secid"]):
        raise ValueError("publication metadata identity differs")
    day = core._date(row["tradedate"])
    if not job["from"] <= day <= job["till"] < "2026-01-01":
        raise ValueError("publication label escaped development boundary")
    clock = datetime.strptime(row["tradetime"], "%H:%M:%S")
    if clock.strftime("%H:%M:%S") != row["tradetime"]:
        raise ValueError("publication label clock malformed")
    label = datetime.fromisoformat(day + " " + row["tradetime"])
    if len(row["SYSTIME"]) < 19 or row["SYSTIME"][10] not in (" ", "T"):
        raise ValueError("publication system timestamp lacks date and clock")
    system = datetime.fromisoformat(row["SYSTIME"])
    if system.tzinfo is not None:
        raise ValueError("publication source clock unexpectedly timezone-aware")
    return label, system


def _add(group: dict, label: datetime, system: datetime) -> None:
    seconds = (system - label).total_seconds()
    stamp = system.isoformat(sep=" ")
    group["rows"] += 1
    group["same_calendar_date"] += system.date() == label.date()
    group["later_calendar_date"] += system.date() > label.date()
    group["earlier_calendar_date"] += system.date() < label.date()
    group["publication_in_or_after_2026"] += system >= datetime(2026, 1, 1)
    group["label_gap_bins"][_bucket(seconds)] += 1
    year = str(system.year)
    group["publication_years"][year] = group["publication_years"].get(year, 0) + 1
    for field, value, operation in (("minimum_systime", stamp, min),
                                    ("maximum_systime", stamp, max),
                                    ("minimum_label_gap_seconds", seconds, min),
                                    ("maximum_label_gap_seconds", seconds, max)):
        group[field] = value if group[field] is None else operation(group[field], value)


def build_report(root: Path) -> dict:
    manifest, records = quality._preflight(root, SOURCE_MANIFEST, jobs=294, pairs=147)
    groups, jobs = {}, []
    for record in records:
        job, path = record["job"], record["rows_path"]
        counter = _empty()
        before = history._identity(path)
        if any(before[key] != record["entry"]["normalized"][key] for key in before):
            raise ValueError("publication input no longer matches pinned normalized identity")
        for row in _metadata(path):
            label, system = _parse(row, job)
            _add(counter, label, system)
            for key in ("ALL", job["dataset"], f"{job['dataset']}/{label.year}",
                        f"{job['dataset']}/{job['asset_code']}/{label.year}"):
                if key not in groups:
                    groups[key] = _empty()
                _add(groups[key], label, system)
        if (counter["rows"] != record["entry"]["rows"] or history._identity(path) != before):
            raise ValueError("publication input changed or row count differs")
        jobs.append({"job_id": job["job_id"], **counter})
    if (groups["ALL"]["rows"] != CONFIG["expected_rows"]
            or manifest["pages"] != CONFIG["expected_pages"]
            or quality._hash(quality._safe(root, "manifest.json")) != SOURCE_MANIFEST):
        raise ValueError("publication source aggregate or manifest drift")
    return {"protocol_id": PROTOCOL, "groups": groups, "jobs": jobs,
            "metadata_columns_read": COLUMNS, "source_manifest_sha256": SOURCE_MANIFEST,
            "label_gap_is_measured_delivery_latency": False,
            "publication_clock_timezone_verified": False,
            "parent_parser_already_requires_systime_ge_label": True,
            **quality.FLAGS}


def run(storage_root: Path, seal_sha256: str) -> Path:
    closure = verify_seal(seal_sha256)
    if not storage_root.is_absolute():
        raise ValueError("absolute storage root required")
    for path in reversed((storage_root, *storage_root.parents)):
        quality._ordinary(path, directory=True)
    source = quality._safe(storage_root, CONFIG["source_path"], directory=True)
    parent = quality._safe(storage_root, CONFIG["output_parent"], directory=True)
    destination = parent / (PROTOCOL + "_" + seal_sha256[:12])
    lock = parent / ("." + destination.name + ".lock")
    with history._exclusive_lock(lock):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("publication canonical already exists")
        print('{"phase":"full_raw_replay"}', flush=True)
        audit = history.audit(source, storage_root, SOURCE_SEAL, SOURCE_MANIFEST)
        if (audit.get("status") != "PASS" or audit.get("manifest_sha256") != SOURCE_MANIFEST
                or audit.get("jobs") != 294 or audit.get("rows") != CONFIG["expected_rows"]
                or audit.get("pages") != 2198
                or any(audit.get(key) is not value for key, value in quality.FLAGS.items())):
            raise ValueError("publication parent replay did not pass")
        print('{"phase":"six_column_projection"}', flush=True)
        report = build_report(source)
        if verify_seal(seal_sha256) != closure:
            raise ValueError("publication closure changed during run")
        staging = Path(tempfile.mkdtemp(prefix="." + destination.name + ".staging-", dir=parent))
        artifacts = {}
        for name, value in (("audit.json", audit), ("publication.json", report)):
            raw = history._json(value)
            history._write(staging / name, raw)
            if (staging / name).read_bytes() != raw:
                raise ValueError("publication staged bytes differ")
            artifacts[name] = history._identity(staging / name)
        manifest = {"protocol_id": PROTOCOL, "seal_sha256": seal_sha256,
                    "source_manifest_sha256": SOURCE_MANIFEST, "artifacts": artifacts,
                    "created_at_utc": datetime.now(UTC).isoformat(), **quality.FLAGS}
        history._write(staging / "manifest.json", history._json(manifest))
        if {path.name for path in staging.iterdir()} != {*artifacts, "manifest.json"}:
            raise ValueError("publication unexpected staged files")
        if ((staging / "manifest.json").read_bytes() != history._json(manifest)
                or any(history._identity(staging / name) != identity
                       for name, identity in artifacts.items())):
            raise ValueError("publication staged artifacts changed")
        history._publish(staging, destination)
        return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    try:
        path = run(args.storage_root, args.seal_sha256)
        print(json.dumps({"status": "PASS", "path": str(path),
                          "manifest_sha256": history._identity(path / "manifest.json")["sha256"],
                          **quality.FLAGS}, sort_keys=True))
    except Exception:
        print(json.dumps({"status": "FAIL", "protocol_id": PROTOCOL, **quality.FLAGS}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
