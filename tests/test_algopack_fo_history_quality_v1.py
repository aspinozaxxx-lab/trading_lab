"""Synthetic metadata-only reporting tests; no actual market data or API access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from market_lab.futures import algopack_fo_history_quality_v1 as quality


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(quality._json(value))


def _identity(path: Path) -> dict:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _job(dataset: str, *, days: list[str] | None = None) -> dict:
    days = days or ["2024-10-15"]
    return {
        "job_id": f"{dataset}_SI_SiZ4_{days[0]}_{days[-1]}",
        "dataset": dataset,
        "asset_code": "SI",
        "secid": "SiZ4",
        "from": days[0],
        "till": days[-1],
        "expected_dates": days,
    }


def _row(dataset: str, stamp: str = "10:00:00", day: str = "2024-10-15") -> dict:
    return {
        "dataset": dataset,
        "requested_asset_code": "SI",
        "secid": "SiZ4",
        "tradedate": day,
        "tradetime": stamp,
        "vol": {"do_not_materialize": [912345678, "ignored nested data"]},
        "available_at": None,
        "historical_model_eligible": False,
    }


def _record(root: Path, job: dict, rows: list[dict]) -> dict:
    directory = root / "jobs" / job["job_id"] / "result"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "rows.jsonl"
    path.write_bytes(b"".join(quality._json(row) + b"\n" for row in rows))
    dates = {
        day: sum(row["tradedate"] == day for row in rows)
        for day in sorted({row["tradedate"] for row in rows})
    }
    expected, observed = set(job["expected_dates"]), set(dates)
    admitted = bool(rows) and observed == expected
    summary = {
        "rows": len(rows),
        "observed_dates": sorted(observed),
        "expected_dates": job["expected_dates"],
        "missing_dates": sorted(expected - observed),
        "extra_dates": sorted(observed - expected),
        "date_counts": dates,
        "missing_asset_code_rows": 0,
        "asset_alias_mismatch_rows": 0,
        "extra_active_date_rows": sum(dates[day] for day in observed - expected),
        "field_counts": {
            field: {"null": 0, "zero": 0, "negative": 0}
            for field in quality.core.FIELDS[job["dataset"]]
        },
        "source_date_coverage_admitted": admitted,
        "historical_model_eligible": False,
    }
    normalized = {**_identity(path), "rows": len(rows)}
    manifest = {
        "protocol_id": quality.core.PROTOCOL,
        "status": "complete",
        "job": job,
        "pages": [{"page": "p000000", "rows": len(rows), "request_attempts": 1}],
        "normalized": normalized,
        "summary": summary,
        **quality.FLAGS,
    }
    _write(directory / "manifest.json", manifest)
    entry = {
        "job_id": job["job_id"],
        "manifest": _identity(directory / "manifest.json"),
        "normalized": normalized,
        "pages": 1,
        "rows": len(rows),
        "committed_page_request_attempts": 1,
        "committed_page_retry_attempts": 0,
        "source_date_coverage_admitted": admitted,
    }
    return {"job": job, "entry": entry, "summary": summary, "rows_path": path}


def _bundle(root: Path) -> str:
    records = [
        _record(root, _job(dataset), [_row(dataset)]) for dataset in ("tradestats", "obstats")
    ]
    _write(root / "plan.json", [record["job"] for record in records])
    manifest = {
        "protocol_id": quality.core.PROTOCOL,
        "status": "complete",
        "plan": {**_identity(root / "plan.json"), "jobs": 2},
        "job_count": 2,
        "jobs": [record["entry"] for record in records],
        "rows": 2,
        "pages": 2,
        "committed_page_request_attempts": 2,
        "committed_page_retry_attempts": 0,
        "source_date_coverage_admitted": True,
        "closure": {"seal_sha256": "c" * 64},
        "parent_sample": quality.core.EXPECTED_CONFIG["parent_sample"],
        **quality.FLAGS,
    }
    _write(root / "manifest.json", manifest)
    return _identity(root / "manifest.json")["sha256"]


def _small(root: Path, sha: str) -> tuple[dict, list[dict]]:
    return quality._preflight(root, sha, jobs=2, pairs=1)


def test_metadata_projection_materializes_only_five_fields(tmp_path: Path) -> None:
    record = _record(tmp_path, _job("tradestats"), [_row("tradestats")])
    rows = list(quality._metadata(record["rows_path"]))
    assert list(rows[0]) == quality.METADATA_COLUMNS
    assert "vol" not in rows[0] and "912345678" not in json.dumps(rows)


def test_arrow_projection_explicit_schema_and_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path, _job("tradestats"), [_row("tradestats")])
    original = quality.arrow_json.open_json

    def checked(path: Path, *, parse_options: object) -> object:
        assert parse_options.explicit_schema.names == quality.METADATA_COLUMNS
        assert parse_options.unexpected_field_behavior == "ignore"
        return original(path, parse_options=parse_options)

    monkeypatch.setattr(quality.arrow_json, "open_json", checked)
    assert len(list(quality._metadata(record["rows_path"]))) == 1


def test_small_structural_bundle_validates_then_aggregates(tmp_path: Path) -> None:
    sha = _bundle(tmp_path)
    manifest, records = _small(tmp_path, sha)
    report = quality._aggregate(records)
    assert manifest["rows"] == 2
    assert report["join_totals"]["both"] == 1
    assert sum(row["rows"] for row in report["by_dataset_asset_year"]) == 2


def test_production_requires_all_294_jobs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="job count"):
        quality.build_report(tmp_path, _bundle(tmp_path))


def test_matching_keys_not_equal_row_count_inference(tmp_path: Path) -> None:
    first = _record(
        tmp_path,
        _job("tradestats"),
        [_row("tradestats", "10:00:00"), _row("tradestats", "10:05:00")],
    )
    second = _record(
        tmp_path, _job("obstats"), [_row("obstats", "10:05:00"), _row("obstats", "10:10:00")]
    )
    report = quality._aggregate([first, second])
    assert {
        key: report["join_totals"][key] for key in ("both", "tradestats_only", "obstats_only")
    } == {"both": 1, "tradestats_only": 1, "obstats_only": 1}


def test_duplicate_and_off_grid_are_reported_not_silently_removed(tmp_path: Path) -> None:
    first = _record(tmp_path, _job("tradestats"), [_row("tradestats", "10:01:00")] * 2)
    second = _record(tmp_path, _job("obstats"), [_row("obstats", "10:05:01")])
    report = quality._aggregate([first, second])["join_totals"]
    assert report["tradestats_duplicate_rows"] == 1
    assert report["tradestats_off_five_minute_grid_rows"] == 2
    assert report["obstats_off_five_minute_grid_rows"] == 1


def test_empty_jobs_preserve_expected_date_denominator(tmp_path: Path) -> None:
    records = [_record(tmp_path, _job(dataset), []) for dataset in ("tradestats", "obstats")]
    report = quality._aggregate(records)
    assert len(report["nonadmitted_jobs"]) == 2
    assert all(row["missing_expected_keys"] == 1 for row in report["by_dataset_asset_year"])
    assert all(row["first_observed_date"] is None for row in report["by_dataset_asset_year"])
    assert report["join_totals"]["both"] == 0


def test_cross_year_rows_split_but_field_counts_not_allocated(tmp_path: Path) -> None:
    records = []
    for dataset in ("tradestats", "obstats"):
        job = _job(dataset, days=["2024-12-30", "2025-01-03"])
        rows = [_row(dataset, day=day) for day in job["expected_dates"]]
        record = _record(tmp_path, job, rows)
        record["summary"]["field_counts"][quality.core.FIELDS[dataset][0]]["null"] = 1
        records.append(record)
    report = quality._aggregate(records)
    assert len(report["by_dataset_asset_year"]) == 4
    assert all(
        row["rows"] == 1 and "field_counts" not in row for row in report["by_dataset_asset_year"]
    )
    assert all(row["jobs_touching_year"] == 1 for row in report["by_dataset_asset_year"])


def test_missing_extra_dates_use_exact_contract_keys(tmp_path: Path) -> None:
    records = []
    for dataset in ("tradestats", "obstats"):
        job = _job(dataset, days=["2024-10-14", "2024-10-16"])
        records.append(_record(tmp_path, job, [_row(dataset, day="2024-10-15")]))
    report = quality._aggregate(records)
    assert all(
        row["missing_expected_keys"] == 2 and row["extra_date_keys"] == 1
        for row in report["by_dataset_asset_year"]
    )
    assert len(report["nonadmitted_jobs"]) == 2


@pytest.mark.parametrize("artifact", ["manifest.json", "plan.json", "job_manifest", "normalized"])
def test_hash_tamper_fails_before_metadata_projection(
    tmp_path: Path, artifact: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = _bundle(tmp_path)
    directory = tmp_path / "jobs" / _job("tradestats")["job_id"] / "result"
    path = {
        "manifest.json": tmp_path / "manifest.json",
        "plan.json": tmp_path / "plan.json",
        "job_manifest": directory / "manifest.json",
        "normalized": directory / "rows.jsonl",
    }[artifact]
    path.write_bytes(b"tampered")

    def denied(_: Path) -> None:
        pytest.fail("metadata must not be projected before identities pass")

    monkeypatch.setattr(quality, "_metadata", denied)
    with pytest.raises(ValueError):
        _small(tmp_path, sha)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rows", 3),
        ("pages", 3),
        ("committed_page_request_attempts", 5),
        ("committed_page_retry_attempts", 1),
        ("historical_model_eligible", True),
        ("source_date_coverage_admitted", False),
    ],
)
def test_pinned_global_inconsistency_rejected(tmp_path: Path, field: str, value: object) -> None:
    _bundle(tmp_path)
    manifest = quality._load(tmp_path / "manifest.json")
    manifest[field] = value
    _write(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError):
        _small(tmp_path, _identity(tmp_path / "manifest.json")["sha256"])


@pytest.mark.parametrize(
    "relative", ["../elsewhere", "/absolute", "jobs/../plan.json", "jobs\\escape", "./plan.json"]
)
def test_path_traversal_rejected(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        quality._safe(tmp_path, relative)


def test_symlink_input_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"do not read")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit synthetic symlinks")
    with pytest.raises(ValueError):
        quality._safe(tmp_path, "link")


@pytest.mark.parametrize(
    "changes",
    [
        {"tradedate": "2026-01-01"},
        {"dataset": "unknown"},
        {"requested_asset_code": "RI"},
        {"secid": "SiZ5"},
        {"tradetime": "25:00:00"},
        {"tradetime": None},
    ],
)
def test_metadata_bounds_and_identities_strict(tmp_path: Path, changes: dict) -> None:
    row = {**_row("tradestats"), **changes}
    record = _record(tmp_path, _job("tradestats"), [row])
    with pytest.raises((ValueError, quality.arrow.ArrowInvalid)):
        quality._keys(record["rows_path"], record["job"])


def test_manifest_date_summary_is_recomputed_from_metadata(tmp_path: Path) -> None:
    first = _record(tmp_path, _job("tradestats"), [_row("tradestats")])
    second = _record(tmp_path, _job("obstats"), [_row("obstats")])
    first["summary"]["date_counts"]["2024-10-15"] = 2
    with pytest.raises(ValueError, match="date summary"):
        quality._aggregate([first, second])


def test_manifest_field_counts_checked_without_numeric_recomputation(tmp_path: Path) -> None:
    records = [
        _record(tmp_path, _job(dataset), [_row(dataset)]) for dataset in ("tradestats", "obstats")
    ]
    records[0]["summary"]["field_counts"]["vol"]["null"] = 1
    report = quality._aggregate(records)
    trade = next(row for row in report["by_dataset_asset"] if row["dataset"] == "tradestats")
    assert trade["field_counts"]["vol"]["null"] == 1
    records[0]["summary"]["field_counts"]["vol"]["zero"] = 1
    with pytest.raises(ValueError, match="field counts"):
        quality._aggregate(records)


def test_duplicate_json_manifest_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"protocol_id":"one","protocol_id":"two"}')
    with pytest.raises(ValueError, match="duplicate"):
        quality._load(path)


def _public_small(monkeypatch: pytest.MonkeyPatch) -> None:
    original = quality._preflight

    def reduced(root: Path, sha: str, *, jobs: int, pairs: int) -> tuple[dict, list[dict]]:
        assert jobs == 294 and pairs == 147  # Public production contract stays fixed.
        return original(root, sha, jobs=2, pairs=1)

    monkeypatch.setattr(quality, "_preflight", reduced)
    monkeypatch.setattr(
        quality.core, "EXPECTED_CONFIG", {**quality.core.EXPECTED_CONFIG, "assets": ["SI"]}
    )


def test_public_report_preserves_scope_flags_and_input_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = _bundle(tmp_path)
    _public_small(monkeypatch)
    report = quality.build_report(tmp_path, sha)
    assert report["source_manifest_sha256"] == sha and len(report["inputs"]) == 2
    assert report["metadata_columns_read"] == quality.METADATA_COLUMNS
    assert report["full_raw_replay_performed"] is False
    assert report["requires_separate_history_audit"] is True
    assert report["field_counts_replayed_from_numeric_rows"] is False
    assert all(report[key] is value for key, value in quality.FLAGS.items())
    assert "912345678" not in json.dumps(report)
    assert report["status"] == "metadata_report_complete"


def test_mutation_during_projection_fails_final_identity_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = _bundle(tmp_path)
    _public_small(monkeypatch)
    original = quality._metadata

    def changed(path: Path):
        yield from original(path)
        path.write_bytes(path.read_bytes() + b" ")

    monkeypatch.setattr(quality, "_metadata", changed)
    with pytest.raises(ValueError, match="byte identity"):
        quality.build_report(tmp_path, sha)


def test_exact_contract_pair_count_checked(tmp_path: Path) -> None:
    sha = _bundle(tmp_path)
    with pytest.raises(ValueError, match="pair count"):
        quality._preflight(tmp_path, sha, jobs=2, pairs=2)


def test_fixed_parent_binding_checked(tmp_path: Path) -> None:
    _bundle(tmp_path)
    manifest = quality._load(tmp_path / "manifest.json")
    manifest["parent_sample"] = {**manifest["parent_sample"], "manifest_sha256": "f" * 64}
    _write(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="parent sample"):
        _small(tmp_path, _identity(tmp_path / "manifest.json")["sha256"])


@pytest.mark.parametrize(
    "relative", ["C:/outside", "plan.json:stream", "jobs/C:relative", "nul\x00file"]
)
def test_windows_drive_ads_nul_rejected_before_filesystem_access(
    tmp_path: Path, relative: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid relative path must be rejected before filesystem access")

    monkeypatch.setattr(quality, "_ordinary", denied)
    with pytest.raises(ValueError):
        quality._safe(tmp_path, relative)


def test_keysets_joined_before_next_contract_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = []
    for dataset in ("tradestats", "obstats"):
        for secid in ("SiH5", "SiZ4"):
            job = _job(dataset)
            job["secid"] = secid
            job["job_id"] = job["job_id"].replace("SiZ4", secid)
            records.append(_record(tmp_path, job, [{**_row(dataset), "secid": secid}]))
    original_join, original_keys = quality._join_pair, quality._keys
    joined = []

    def join(asset: str, datasets: dict, joins: dict, years: set[str]) -> None:
        original_join(asset, datasets, joins, years)
        joined.append(True)

    def keys(path: Path, job: dict) -> tuple:
        if job["secid"] == "SiZ4":
            assert len(joined) == 1
        return original_keys(path, job)

    monkeypatch.setattr(quality, "_join_pair", join)
    monkeypatch.setattr(quality, "_keys", keys)
    assert quality._aggregate(records)["join_totals"]["both"] == 2
    assert len(joined) == 2


def test_same_timestamp_different_contracts_never_cross_match(tmp_path: Path) -> None:
    records = []
    for dataset in ("tradestats", "obstats"):
        for secid in ("SiH5", "SiZ4"):
            job = _job(dataset)
            job["secid"] = secid
            job["job_id"] = job["job_id"].replace("SiZ4", secid)
            present = (dataset == "tradestats") == (secid == "SiH5")
            rows = [{**_row(dataset), "secid": secid}] if present else []
            records.append(_record(tmp_path, job, rows))
    totals = quality._aggregate(records)["join_totals"]
    assert totals["both"] == 0 and totals["tradestats_only"] == totals["obstats_only"] == 1
