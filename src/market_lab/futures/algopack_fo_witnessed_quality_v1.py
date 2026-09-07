"""Fixed three-capture source diagnostic, never prediction or economic admission."""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures import moex_algopack_fo_witnessed_v1 as source

PROTOCOL = "algopack_fo_witnessed_quality_v1"
PARENT_SHA = "67a11050689b42802b1f33797a98c47ef9974249803de72601c2b8dffb099c26"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_CONFIG = {
    "protocol_id": PROTOCOL,
    "source_seal_sha256": PARENT_SHA,
    "source_root": "/srv/trading_lab_data/data/forward/algopack-fo-witnessed-v1",
    "first_capture": "20260907T115659545856Z_b813c3346d94",
    "first_manifest_sha256": "d0e031f1e03599aa72cb0d9d1d84a78742e373bb574195918693363cd596d740",
    "second_capture": "20260907T120300520961Z_f925ca4d538a",
    "second_manifest_sha256": "de98c9d66227585abc9148f22b07c3086fadf853857079ccc8e6fd0bd2bedba4",
    "third_start_from": "2026-09-07T12:13:00+00:00",
    "third_start_before": "2026-09-07T12:14:00+00:00",
    "capture_completion_cutoff": "2026-09-07T12:14:00+00:00",
    "expected_captures": 3,
    "source_only": True,
    "historical_model_eligible": False,
    "prediction_eligible": False,
    "live_trading_allowed": False,
    "original_version_verified": False,
}
OWN_FILES = {f"src/market_lab/futures/{PROTOCOL}.py", f"tests/test_{PROTOCOL}.py",
             f"configs/{PROTOCOL}.json", f"configs/{PROTOCOL}.sha256"}
REQUIRED_FILES = OWN_FILES | source.REQUIRED_FILES | {f"configs/{source.PROTOCOL}.seal.json"}


def verify_seal(digest: str) -> None:
    source.verify_seal(PARENT_SHA)
    raw = source._read(PROJECT_ROOT / f"configs/{PROTOCOL}.seal.json")
    seal = source.core._decode(raw)
    if (source.sha(raw) != digest or seal.get("protocol_id") != PROTOCOL
            or set(seal.get("files", {})) != REQUIRED_FILES):
        raise ValueError("quality closure mismatch")
    for relative, expected in seal["files"].items():
        if source.sha(source._read(PROJECT_ROOT / relative)) != expected:
            raise ValueError("quality dependency drift")
    config = source._read(PROJECT_ROOT / f"configs/{PROTOCOL}.json")
    sidecar = source._read(PROJECT_ROOT / f"configs/{PROTOCOL}.sha256").decode("utf-8-sig")
    if source.core._decode(config) != EXPECTED_CONFIG or sidecar.split() != [source.sha(config)]:
        raise ValueError("quality config drift")


def select_inputs(root: Path) -> list[dict]:
    """Select only manifest metadata. Bind exact bytes before opening numeric source rows."""
    source._ordinary(root, directory=True)
    config, selected = EXPECTED_CONFIG, []
    cutoff = source._stamp(config["capture_completion_cutoff"])
    for name in (config["first_capture"], config["second_capture"]):
        raw = source._read(root / name / "manifest.json")
        selected.append({"capture_id": name, "manifest_sha256": source.sha(raw)})
    if [row["manifest_sha256"] for row in selected] != [
        config["first_manifest_sha256"], config["second_manifest_sha256"]
    ]:
        raise ValueError("known capture identity drift")
    lower, upper = (source._stamp(config[key])
                    for key in ("third_start_from", "third_start_before"))
    candidates = []
    for path in sorted(root.iterdir()):
        if not path.name.startswith("20260907T1213"):
            continue
        raw = source._read(path / "manifest.json")
        manifest = source.core._decode(raw)
        if (manifest["capture_id"] != path.name or manifest["seal_sha256"] != PARENT_SHA
                or not lower <= source._stamp(manifest["started_at"]) < upper
                or source._stamp(manifest["available_at"]) >= cutoff):
            raise ValueError("third capture outside fixed cohort")
        candidates.append({"capture_id": path.name, "manifest_sha256": source.sha(raw)})
    if len(candidates) != 1:
        raise ValueError("third scheduled cohort missing or ambiguous")
    return selected + candidates


def summarize(captures: list[tuple[dict, list[dict]]]) -> tuple[dict, list[dict]]:
    """Content hashes distinguish re-observation, feature revisions and SYSTIME churn."""
    seen, previous_keys, versions, summaries = {}, set(), [], []
    previous_available = None
    for manifest, rows in captures:
        available = source._stamp(manifest["available_at"])
        if previous_available is not None and available <= previous_available:
            raise ValueError("captures not strictly increasing in receipt availability")
        previous_available = available
        keys, paired = set(), {dataset: set() for dataset in source.core.FIELDS}
        counts = dict.fromkeys(("new_keys", "reobserved_keys", "feature_changes",
                              "systime_only_changes", "other_metadata_changes", "reappeared_keys",
                              "missing_asset_rows", "alias_mismatch_rows"), 0)
        field_counts = {dataset: {field: {"null": 0, "zero": 0, "negative": 0}
                                  for field in fields}
                        for dataset, fields in source.core.FIELDS.items()}
        for row in rows:
            key = source.core.row_key(row)
            if key in keys:
                raise ValueError("duplicate normalized source key")
            keys.add(key)
            dataset = row["dataset"]
            paired[dataset].add(key[1:])
            fields = source.core.FIELDS[dataset]
            features = source.sha(source._json({name: row[name] for name in fields}))
            content = source.sha(source._json({
                name: row[name] for name in source.core.COMMON + fields if name != "SYSTIME"
            }))
            vendor = source.sha(source._json({name: row[name]
                                              for name in source.core.COMMON + fields}))
            prior = seen.get(key)
            counts["new_keys" if prior is None else "reobserved_keys"] += 1
            if prior is not None:
                counts["reappeared_keys"] += key not in previous_keys
                counts["feature_changes"] += prior["feature_sha256"] != features
                counts["systime_only_changes"] += (
                    prior["content_sha256"] == content and prior["vendor_sha256"] != vendor)
                counts["other_metadata_changes"] += (
                    prior["feature_sha256"] == features and prior["content_sha256"] != content)
            counts["missing_asset_rows"] += row["asset_code_missing"]
            counts["alias_mismatch_rows"] += row["asset_code_mismatch"]
            for field in fields:
                value = row[field]
                field_counts[dataset][field]["null"] += value is None
                field_counts[dataset][field]["zero"] += value == 0
                field_counts[dataset][field]["negative"] += value is not None and value < 0
            version = {"key": list(key), "capture_id": manifest["capture_id"],
                       "available_at": manifest["available_at"],
                       "first_observed_available_at": (prior["first_observed_available_at"]
                                                       if prior else manifest["available_at"]),
                       "feature_sha256": features, "content_sha256": content,
                       "vendor_sha256": vendor}
            versions.append(version)
            seen[key] = version
        ts, ob = paired["tradestats"], paired["obstats"]
        summaries.append({"capture_id": manifest["capture_id"], "rows": len(rows), **counts,
                          "dropped_from_previous_capture": len(previous_keys - keys),
                          "shared_ts_ob_keys": len(ts & ob), "ts_only_keys": len(ts - ob),
                          "ob_only_keys": len(ob - ts), "field_counts": field_counts,
                          "available_at": manifest["available_at"]})
        previous_keys = keys
    report = {"captures": summaries, "unique_keys": len(seen),
              "version_observations": len(versions),
              "reobservations": sum(row["reobserved_keys"] for row in summaries),
              "feature_revision_events": sum(row["feature_changes"] for row in summaries),
              "systime_only_events": sum(row["systime_only_changes"] for row in summaries),
              "source_only": True, "prediction_eligible": False,
              "historical_model_eligible": False, "original_version_verified": False,
              "live_trading_allowed": False, "vendor_atomic_snapshot_proven": False}
    return report, versions


def run(output_root: Path, seal_sha256: str) -> dict:
    verify_seal(seal_sha256)
    if datetime.now(UTC) < source._stamp(EXPECTED_CONFIG["capture_completion_cutoff"]):
        raise ValueError("fixed cohort acquisition interval not finished")
    input_root = Path(EXPECTED_CONFIG["source_root"])
    bindings = select_inputs(input_root)
    name = PROTOCOL + "_" + seal_sha256[:12]
    with source._lock(output_root):
        canonical, staging = output_root / name, output_root / (".incomplete_" + name)
        if canonical.exists() or canonical.is_symlink():
            raise ValueError("quality canonical already exists")
        staging.mkdir(mode=0o700)
        try:
            binding_id = source._write(staging / "inputs.json", source._json(bindings))
            loaded, audits = [], []
            for binding in bindings:
                path = input_root / binding["capture_id"]
                audit = source.audit(path, PARENT_SHA)
                if audit["manifest_sha256"] != binding["manifest_sha256"]:
                    raise ValueError("input changed after binding")
                manifest = source.core._decode(source._read(path / "manifest.json"))
                rows = []
                for job in manifest["jobs"]:
                    raw_rows = gzip.decompress(source._artifact(path, job["normalized"]))
                    rows.extend(json.loads(raw_rows))
                if len(rows) != manifest["rows"]:
                    raise ValueError("normalized count mismatch")
                audits.append(audit)
                loaded.append((manifest, rows))
            report, versions = summarize(loaded)
            for binding in bindings:
                raw = source._read(input_root / binding["capture_id"] / "manifest.json")
                if source.sha(raw) != binding["manifest_sha256"]:
                    raise ValueError("source manifest changed during report")
            artifacts = [binding_id,
                         source._write(staging / "quality.json", source._json(report)),
                         source._write(staging / "versions.json.gz",
                                       gzip.compress(source._json(versions), mtime=0))]
            for artifact in artifacts:
                source._artifact(staging, artifact)
            manifest = {"protocol_id": PROTOCOL, "seal_sha256": seal_sha256,
                        "created_at": datetime.now(UTC).isoformat(), "artifacts": artifacts,
                        "input_audits": audits, "source_only": True,
                        "prediction_eligible": False, "live_trading_allowed": False}
            identity = source._write(staging / "manifest.json", source._json(manifest))
            staging.rename(canonical)
            return {"path": str(canonical), "manifest_sha256": identity["sha256"],
                    "captures": len(loaded), "unique_keys": report["unique_keys"],
                    "version_observations": len(versions),
                    "feature_revision_events": report["feature_revision_events"],
                    "source_only": True, "prediction_eligible": False}
        except Exception:
            source._write(staging / "failure.json", source._json({"phase": "quality_failed"}))
            raise ValueError("quality failed; immutable staging retained") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.output_root, args.seal_sha256), sort_keys=True))
    except Exception:
        print('{"passed":false,"phase":"witnessed_quality_failed"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
