"""Synthetic publication timestamps; deliberately no market outcomes."""

import copy
import json
from datetime import datetime, timedelta

import pytest

from market_lab.futures import algopack_fo_publication_metadata_v1 as publication


def fixture_row():
    return {"dataset": "tradestats", "requested_asset_code": "SI", "secid": "SiZ4",
            "tradedate": "2024-10-15", "tradetime": "10:00:00",
            "SYSTIME": "2024-10-15 10:05:01"}


def fixture_job():
    return {"dataset": "tradestats", "asset_code": "SI", "secid": "SiZ4",
            "from": "2024-10-15", "till": "2024-10-15"}


@pytest.mark.parametrize("seconds,bucket", [(-1, "negative"), (0, "[0,60)"),
    (59.999, "[0,60)"), (60, "[60,300)"), (299, "[60,300)"), (300, "[300,600)"),
    (599, "[300,600)"), (600, "[600,3600)"), (3599, "[600,3600)"),
    (3600, "[3600,86400)"), (86399, "[3600,86400)"), (86400, ">=86400")])
def test_fixed_bucket_boundaries(seconds, bucket):
    assert publication._bucket(seconds) == bucket


def test_post_2025_publication_metadata_allowed_not_market_outcomes():
    row = fixture_row()
    row["SYSTIME"] = "2026-09-07 12:00:00"
    label, system = publication._parse(row, fixture_job())
    group = publication._empty()
    publication._add(group, label, system)
    assert group["publication_in_or_after_2026"] == 1
    assert group["later_calendar_date"] == 1
    assert group["publication_years"] == {"2026": 1}
    assert not publication.CONFIG["historical_model_eligible"]


@pytest.mark.parametrize("field,value", [("dataset", "obstats"), ("requested_asset_code", "RI"),
    ("secid", "RIZ4"), ("tradedate", "2026-01-01"), ("tradedate", "2024-1-15"),
    ("tradetime", "1:00:00"), ("SYSTIME", None), ("SYSTIME", "2024-10-15"),
    ("SYSTIME", "2024-10-15T12:00:00+00:00"), ("SYSTIME", "not a clock")])
def test_parse_strict_metadata(field, value):
    row = fixture_row()
    row[field] = value
    with pytest.raises(ValueError):
        publication._parse(row, fixture_job())


def test_label_gap_not_event_latency_and_earlier_labels_counted():
    group = publication._empty()
    label = datetime(2024, 10, 15, 10)
    for seconds in (-86401, 0, 60, 301, 86400):
        publication._add(group, label, label + timedelta(seconds=seconds))
    assert group["rows"] == sum(group["label_gap_bins"].values()) == 5
    assert group["earlier_calendar_date"] == group["later_calendar_date"] == 1
    assert group["same_calendar_date"] == 3
    assert group["minimum_label_gap_seconds"] == -86401
    assert group["maximum_label_gap_seconds"] == 86400
    assert not publication.CONFIG["label_gap_is_measured_delivery_latency"]


def test_arrow_projects_only_six_strings(tmp_path):
    row = fixture_row()
    row.update(close={"forbidden": "must never be materialized"}, target=[1, 2, 3])
    path = tmp_path / "synthetic.jsonl"
    path.write_bytes((json.dumps(row) + "\n").encode())
    assert list(publication._metadata(path)) == [fixture_row()]


def test_empty_input_projection(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_bytes(b"")
    assert list(publication._metadata(path)) == []


def test_report_groups_reconcile_synthetic_manifest(tmp_path, monkeypatch):
    path = tmp_path / "rows.jsonl"
    row = fixture_row()
    path.write_bytes((json.dumps(row) + "\n").encode())
    job = dict(fixture_job(), job_id="synthetic")
    records = [{"job": job, "rows_path": path,
                "entry": {"rows": 1, "normalized": publication.history._identity(path)}}]
    monkeypatch.setattr(publication.quality, "_preflight", lambda *a, **k: ({"pages": 1}, records))
    monkeypatch.setattr(publication.quality, "_hash", lambda _: publication.SOURCE_MANIFEST)
    monkeypatch.setattr(publication.quality, "_safe", lambda root, relative: root / relative)
    config = dict(publication.CONFIG, expected_rows=1, expected_pages=1)
    monkeypatch.setattr(publication, "CONFIG", config)
    report = publication.build_report(tmp_path)
    assert set(report["groups"]) == {"ALL", "tradestats", "tradestats/2024", "tradestats/SI/2024"}
    assert all(group["rows"] == 1 for group in report["groups"].values())
    assert report["jobs"][0]["label_gap_bins"]["[300,600)"] == 1
    assert not report["original_version_verified"]


def test_changed_input_or_row_count_rejected(tmp_path, monkeypatch):
    path = tmp_path / "rows.jsonl"
    path.write_bytes((json.dumps(fixture_row()) + "\n").encode())
    records = [{"job": dict(fixture_job(), job_id="synthetic"),
                "rows_path": path,
                "entry": {"rows": 2, "normalized": publication.history._identity(path)}}]
    monkeypatch.setattr(publication.quality, "_preflight", lambda *a, **k: ({"pages": 1}, records))
    with pytest.raises(ValueError, match="row count"):
        publication.build_report(tmp_path)


def test_actual_closure_and_wrong_digest():
    path = publication.PROJECT_ROOT / f"configs/{publication.PROTOCOL}.seal.json"
    raw = path.read_bytes()
    assert len(publication.verify_seal(publication.core.sha(raw))["files"]) == 34
    with pytest.raises(ValueError):
        publication.verify_seal("0" * 64)


def test_no_model_admission_in_configuration():
    config = copy.deepcopy(publication.CONFIG)
    for field in ("historical_model_eligible", "original_version_verified",
                  "live_trading_allowed", "publication_clock_timezone_verified"):
        assert config[field] is False


def test_failed_parent_audit_blocks_metadata_projection(tmp_path, monkeypatch):
    for relative in (publication.CONFIG["source_path"], publication.CONFIG["output_parent"]):
        (tmp_path / relative).mkdir(parents=True)
    monkeypatch.setattr(publication, "verify_seal", lambda _: {})
    monkeypatch.setattr(publication.history, "audit", lambda *args: {"status": "FAIL"})
    calls = []
    monkeypatch.setattr(publication, "build_report", lambda _: calls.append(True))
    with pytest.raises(ValueError, match="replay did not pass"):
        publication.run(tmp_path, "a" * 64)
    assert not calls
    parent = tmp_path / publication.CONFIG["output_parent"]
    assert not any(path.is_dir() for path in parent.iterdir())
