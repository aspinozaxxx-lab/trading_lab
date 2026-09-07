"""Synthetic three-vintage comparisons; no actual source data or outcomes."""

import copy
import gzip
import json
from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

from market_lab.futures import algopack_fo_witnessed_quality_v1 as quality


def row(dataset="tradestats", clock="10:00:00"):
    return {"dataset": dataset, "requested_asset_code": "SI", "secid": "SiU6",
            "tradedate": "2026-09-07", "tradetime": clock, "asset_code": "Si",
            "SYSTIME": "2026-09-07 10:01:00", "asset_code_missing": False,
            "asset_code_mismatch": False,
            **dict.fromkeys(quality.source.core.FIELDS[dataset], 1)}


def capture(number, rows):
    return ({"capture_id": f"synthetic-{number}",
             "available_at": f"2026-09-07T12:{number:02d}:00+00:00"}, rows)


def test_identical_reobservations_are_not_new_samples():
    report, versions = quality.summarize([capture(1, [row()]), capture(2, [row()])])
    assert report["unique_keys"] == 1
    assert report["version_observations"] == 2
    assert report["reobservations"] == 1
    assert report["feature_revision_events"] == report["systime_only_events"] == 0
    assert versions[1]["first_observed_available_at"] == versions[0]["available_at"]
    assert versions[1]["available_at"] > versions[0]["available_at"]
    assert not report["prediction_eligible"]


@pytest.mark.parametrize("change,field", [("feature", "feature_revision_events"),
                                         ("systime", "systime_only_events")])
def test_revision_categories(change, field):
    before, after = row(), row()
    after["vol_b" if change == "feature" else "SYSTIME"] = (
        2 if change == "feature" else "2026-09-07 12:00:00")
    report, versions = quality.summarize([capture(1, [before]), capture(2, [after])])
    assert report[field] == 1
    assert versions[0]["vendor_sha256"] != versions[1]["vendor_sha256"]
    assert before["vol_b"] == 1


def test_metadata_change_separate_from_feature_revision():
    after = row()
    after["asset_code"] = None
    after["asset_code_missing"] = True
    report, _ = quality.summarize([capture(1, [row()]), capture(2, [after])])
    assert report["feature_revision_events"] == report["systime_only_events"] == 0
    assert report["captures"][1]["other_metadata_changes"] == 1
    assert report["captures"][1]["missing_asset_rows"] == 1


def test_disappearance_reappearance_not_zero_fill():
    report, versions = quality.summarize([capture(1, [row()]), capture(2, []), capture(3, [row()])])
    assert report["captures"][1]["dropped_from_previous_capture"] == 1
    assert report["captures"][2]["reappeared_keys"] == 1
    assert report["unique_keys"] == 1 and len(versions) == 2


def test_ts_ob_exact_matching_and_field_masks():
    ob = row("obstats")
    ob["spread_l1"], ob["spread_l10"], ob["vol_b_l1"] = None, -1, 0
    report, _ = quality.summarize([capture(1, [row(), ob, row("obstats", "10:05:00")])])
    result = report["captures"][0]
    assert result["shared_ts_ob_keys"] == result["ob_only_keys"] == 1
    assert result["ts_only_keys"] == 0
    counts = result["field_counts"]["obstats"]
    assert counts["spread_l1"]["null"] == 1
    assert counts["spread_l10"]["negative"] == 1
    assert counts["vol_b_l1"]["zero"] == 1


def test_duplicate_keys_and_backward_availability_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        quality.summarize([capture(1, [row(), row()])])
    with pytest.raises(ValueError, match="increasing"):
        quality.summarize([capture(2, [row()]), capture(1, [row()])])


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    config = copy.deepcopy(quality.EXPECTED_CONFIG)
    for index, (name, clock) in enumerate([
        (config["first_capture"], "11:56:59"), (config["second_capture"], "12:03:00"),
        ("20260907T121300000000Z_synthetic", "12:13:00")
    ]):
        directory = tmp_path / name
        directory.mkdir()
        raw = quality.source._json({"capture_id": name, "seal_sha256": quality.PARENT_SHA,
                                    "started_at": f"2026-09-07T{clock}+00:00",
                                    "available_at": f"2026-09-07T{clock}+00:00"})
        (directory / "manifest.json").write_bytes(raw)
        if index < 2:
            config[("first", "second")[index] + "_manifest_sha256"] = quality.source.sha(raw)
    monkeypatch.setattr(quality, "EXPECTED_CONFIG", config)
    return tmp_path, config


def test_fixed_cohort_selection(cohort):
    root, _ = cohort
    assert len(quality.select_inputs(root)) == 3


@pytest.mark.parametrize("defect", ["known_hash", "missing", "ambiguous", "late", "wrong_seal"])
def test_cohort_fail_closed(cohort, defect):
    root, config = cohort
    third = root / "20260907T121300000000Z_synthetic" / "manifest.json"
    if defect == "known_hash":
        config["first_manifest_sha256"] = "0" * 64
    elif defect == "missing":
        third.unlink()
    elif defect == "ambiguous":
        value = json.loads(third.read_bytes())
        value["capture_id"] = "20260907T121301000000Z_second"
        parent = root / value["capture_id"]
        parent.mkdir()
        (parent / "manifest.json").write_bytes(quality.source._json(value))
    else:
        value = json.loads(third.read_bytes())
        value["available_at" if defect == "late" else "seal_sha256"] = (
            "2026-09-07T12:14:00+00:00" if defect == "late" else "0" * 64)
        third.write_bytes(quality.source._json(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        quality.select_inputs(root)


def test_actual_seal():
    path = quality.PROJECT_ROOT / f"configs/{quality.PROTOCOL}.seal.json"
    raw = path.read_bytes()
    quality.verify_seal(quality.source.sha(raw))
    with pytest.raises(ValueError):
        quality.verify_seal("0" * 64)


def test_acquisition_cutoff_before_output_creation(tmp_path, monkeypatch):
    class EarlyClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 7, 12, 13, tzinfo=UTC)

    monkeypatch.setattr(quality, "verify_seal", lambda _: None)
    monkeypatch.setattr(quality, "datetime", EarlyClock)
    with pytest.raises(ValueError, match="not finished"):
        quality.run(tmp_path, "a" * 64)
    assert not list(tmp_path.iterdir())


def test_canonical_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(quality, "verify_seal", lambda _: None)
    monkeypatch.setattr(quality, "select_inputs", lambda _: [])
    monkeypatch.setattr(quality.source, "_lock", lambda _: nullcontext())
    config = dict(quality.EXPECTED_CONFIG, capture_completion_cutoff="2026-01-01T00:00:00+00:00")
    monkeypatch.setattr(quality, "EXPECTED_CONFIG", config)
    canonical = tmp_path / (quality.PROTOCOL + "_" + "a" * 12)
    canonical.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        quality.run(tmp_path, "a" * 64)
    assert list(tmp_path.iterdir()) == [canonical]


def test_report_end_to_end_with_synthetic_audited_inputs(cohort, monkeypatch):
    root, config = cohort
    config["source_root"] = str(root)
    config["capture_completion_cutoff"] = "2026-09-07T12:14:00+00:00"
    output = root / "output"
    output.mkdir()
    names = [config["first_capture"], config["second_capture"],
             "20260907T121300000000Z_synthetic"]
    for index, name in enumerate(names):
        path = root / name
        normalized = gzip.compress(quality.source._json([row()]), mtime=0)
        identity = quality.source._write(path / "normalized.json.gz", normalized)
        manifest = json.loads((path / "manifest.json").read_bytes())
        manifest.update(jobs=[{"normalized": identity}], rows=1)
        raw = quality.source._json(manifest)
        (path / "manifest.json").write_bytes(raw)
        if index < 2:
            config[("first", "second")[index] + "_manifest_sha256"] = quality.source.sha(raw)

    class LateClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 7, 12, 15, tzinfo=UTC)

    monkeypatch.setattr(quality, "datetime", LateClock)
    monkeypatch.setattr(quality, "verify_seal", lambda _: None)
    monkeypatch.setattr(quality.source, "_lock", lambda _: nullcontext())
    monkeypatch.setattr(quality.source, "audit", lambda path, digest: {
        "manifest_sha256": quality.source.sha((path / "manifest.json").read_bytes()),
        "passed": True})
    result = quality.run(output, "a" * 64)
    assert result["captures"] == result["version_observations"] == 3
    assert result["unique_keys"] == 1 and result["feature_revision_events"] == 0
    report_path = output / (quality.PROTOCOL + "_" + "a" * 12)
    manifest_raw = (report_path / "manifest.json").read_bytes()
    assert quality.source.sha(manifest_raw) == result["manifest_sha256"]
    for artifact in json.loads(manifest_raw)["artifacts"]:
        quality.source._artifact(report_path, artifact)
