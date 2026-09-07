"""Metadata-only quality report; never a substitute for the historical raw replay audit."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath

import pyarrow as arrow
import pyarrow.json as arrow_json

from market_lab.futures import algopack_fo_history_core_v1 as core

PROTOCOL = "algopack_fo_history_quality_v1"
METADATA_COLUMNS = ["dataset", "requested_asset_code", "secid", "tradedate", "tradetime"]
FLAGS = {
    "source_only": True,
    "current_vintage": True,
    "historical_model_eligible": False,
    "original_version_verified": False,
    "live_trading_allowed": False,
}


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()


def _ordinary(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("quality input is not an ordinary file or directory")


def _safe(root: Path, relative: str, *, directory: bool = False) -> Path:
    if not isinstance(relative, str):
        raise ValueError("quality input path is not a string")
    parsed = PurePosixPath(relative)
    if (
        "\\" in relative
        or ":" in relative
        or "\x00" in relative
        or parsed.is_absolute()
        or not parsed.parts
        or any(part in {".", ".."} for part in relative.split("/"))
        or parsed.as_posix() != relative
    ):
        raise ValueError("quality input path is not canonical")
    path = root
    _ordinary(path, directory=True)
    for number, part in enumerate(parsed.parts):
        path = path / part
        _ordinary(path, directory=directory or number < len(parsed.parts) - 1)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("quality input escaped source directory")
    return path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_bytes(), object_pairs_hook=core._json_pairs)


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("quality count is not a nonnegative integer")
    return value


def _verified(root: Path, relative: str, identity: dict) -> Path:
    path = _safe(root, relative)
    if (
        identity.get("path") != path.name
        or _count(identity.get("bytes")) != path.stat().st_size
        or not isinstance(identity.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]) is None
        or _hash(path) != identity["sha256"]
    ):
        raise ValueError("quality input byte identity differs")
    return path


def _flags(manifest: dict) -> None:
    if manifest.get("protocol_id") != core.PROTOCOL or manifest.get("status") != "complete":
        raise ValueError("quality source protocol or completion differs")
    if any(manifest.get(key) is not value for key, value in FLAGS.items()):
        raise ValueError("quality source safety flags differ")


def _preflight(root: Path, expected_sha: str, *, jobs: int, pairs: int) -> tuple[dict, list[dict]]:
    if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        raise ValueError("quality source manifest SHA is invalid")
    path = _safe(root, "manifest.json")
    if _hash(path) != expected_sha:
        raise ValueError("quality source manifest SHA differs")
    manifest = _load(path)
    _flags(manifest)
    if _json(manifest["parent_sample"]) != _json(core.EXPECTED_CONFIG["parent_sample"]):
        raise ValueError("quality fixed parent sample identity differs")
    plan_path = _verified(root, "plan.json", manifest["plan"])
    plan = _load(plan_path)
    if (
        not isinstance(plan, list)
        or len(plan) != jobs
        or _count(manifest["plan"]["jobs"]) != jobs
        or _count(manifest["job_count"]) != jobs
        or len(manifest["jobs"]) != jobs
    ):
        raise ValueError("quality fixed job count differs")
    pair_jobs = defaultdict(dict)
    records, seen = [], set()
    for job, entry in zip(plan, manifest["jobs"], strict=True):
        core.request_url(job, 0)  # Pure validation; never a request.
        job_id = job["job_id"]
        pair = job["asset_code"], job["secid"]
        if job_id in seen or entry["job_id"] != job_id or job["dataset"] in pair_jobs[pair]:
            raise ValueError("quality job or pair identity collision")
        seen.add(job_id)
        pair_jobs[pair][job["dataset"]] = job
        base = f"jobs/{job_id}/result"
        job_path = _verified(root, f"{base}/manifest.json", entry["manifest"])
        selected = _load(job_path)
        _flags(selected)
        if _json(selected["job"]) != _json(job):
            raise ValueError("quality job differs from pinned plan")
        normalized = selected["normalized"]
        rows_path = _verified(root, f"{base}/rows.jsonl", normalized)
        count = _count(normalized["rows"])
        pages = selected["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 200:
            raise ValueError("quality page count invalid")
        attempts = sum(_count(page["request_attempts"]) for page in pages)
        if any(page["request_attempts"] < 1 or page["request_attempts"] > 4 for page in pages):
            raise ValueError("quality attempt count invalid")
        if sum(_count(page["rows"]) for page in pages) != count:
            raise ValueError("quality page row totals differ")
        summary = selected["summary"]
        expected = {
            "job_id": job_id,
            "manifest": entry["manifest"],
            "normalized": normalized,
            "pages": len(pages),
            "rows": count,
            "committed_page_request_attempts": attempts,
            "committed_page_retry_attempts": attempts - len(pages),
            "source_date_coverage_admitted": summary["source_date_coverage_admitted"],
        }
        if _json(entry) != _json(expected):
            raise ValueError("quality global job aggregate differs")
        records.append({"job": job, "entry": entry, "summary": summary, "rows_path": rows_path})
    if len(pair_jobs) != pairs:
        raise ValueError("quality fixed contract pair count differs")
    for datasets in pair_jobs.values():
        if set(datasets) != {"tradestats", "obstats"}:
            raise ValueError("quality contract lacks a source dataset")
        first, second = datasets["tradestats"], datasets["obstats"]
        if any(first[key] != second[key] for key in ("from", "till", "expected_dates")):
            raise ValueError("quality paired active date plans differ")
    for field in (
        "rows",
        "pages",
        "committed_page_request_attempts",
        "committed_page_retry_attempts",
    ):
        if _count(manifest[field]) != sum(record["entry"][field] for record in records):
            raise ValueError("quality global aggregate differs")
    admitted = all(record["summary"]["source_date_coverage_admitted"] for record in records)
    if manifest["source_date_coverage_admitted"] is not admitted:
        raise ValueError("quality global coverage flag differs")
    return manifest, records


def _metadata(path: Path):
    """Arrow projects only named strings; all numeric/unlisted fields are ignored."""
    if path.stat().st_size == 0:
        return
    schema = arrow.schema([(column, arrow.string()) for column in METADATA_COLUMNS])
    options = arrow_json.ParseOptions(explicit_schema=schema, unexpected_field_behavior="ignore")
    with arrow_json.open_json(path, parse_options=options) as reader:
        for batch in reader:
            if batch.schema != schema:
                raise ValueError("quality metadata projection drifted")
            yield from batch.to_pylist()


def _keys(path: Path, job: dict) -> tuple[set[tuple[str, str]], dict, dict, Counter]:
    keys, duplicates, off_grid, dates = set(), Counter(), Counter(), Counter()
    for row in _metadata(path):
        if (
            set(row) != set(METADATA_COLUMNS)
            or any(not isinstance(value, str) for value in row.values())
            or row["dataset"] != job["dataset"]
            or row["requested_asset_code"] != job["asset_code"]
            or row["secid"] != job["secid"]
        ):
            raise ValueError("quality metadata row identity differs")
        day = core._date(row["tradedate"])
        if not job["from"] <= day <= job["till"]:
            raise ValueError("quality metadata observation escaped historical bounds")
        clock = datetime.strptime(row["tradetime"], "%H:%M:%S")
        if clock.strftime("%H:%M:%S") != row["tradetime"]:
            raise ValueError("quality metadata clock is not exact")
        key = day, row["tradetime"]
        year = day[:4]
        duplicates[year] += int(key in keys)
        off_grid[year] += int(clock.minute % 5 != 0 or clock.second != 0)
        dates[day] += 1
        keys.add(key)
    return keys, dict(duplicates), dict(off_grid), dates


def _summary(record: dict, dates: Counter) -> None:
    job, summary = record["job"], record["summary"]
    expected, observed = set(job["expected_dates"]), set(dates)
    if (
        _count(summary["rows"]) != sum(dates.values())
        or summary["rows"] != record["entry"]["rows"]
        or summary["expected_dates"] != job["expected_dates"]
        or summary["observed_dates"] != sorted(observed)
        or summary["missing_dates"] != sorted(expected - observed)
        or summary["extra_dates"] != sorted(observed - expected)
        or _json(summary["date_counts"]) != _json(dict(dates))
    ):
        raise ValueError("quality date summary differs from metadata rows")
    if summary["historical_model_eligible"] is not False:
        raise ValueError("quality summary has unsafe eligibility")
    for field in ("missing_asset_code_rows", "asset_alias_mismatch_rows", "extra_active_date_rows"):
        if _count(summary[field]) > summary["rows"]:
            raise ValueError("quality diagnostic exceeds row count")
    if summary["extra_active_date_rows"] != sum(dates[day] for day in observed - expected):
        raise ValueError("quality extra active-date row count differs")
    admitted = bool(dates) and not (
        expected ^ observed
        or summary["missing_asset_code_rows"]
        or summary["asset_alias_mismatch_rows"]
    )
    if summary["source_date_coverage_admitted"] is not admitted:
        raise ValueError("quality date coverage flag differs")
    if set(summary["field_counts"]) != set(core.FIELDS[job["dataset"]]):
        raise ValueError("quality diagnostic field schema differs")
    for counts in summary["field_counts"].values():
        if (
            set(counts) != {"null", "zero", "negative"}
            or sum(_count(v) for v in counts.values()) > summary["rows"]
        ):
            raise ValueError("quality field counts invalid")


def _join_pair(asset: str, datasets: dict, joins: dict, expected_years: set[str]) -> None:
    trade, order = datasets["tradestats"], datasets["obstats"]
    years = expected_years | {day[:4] for keyset, _, _ in datasets.values() for day, _ in keyset}
    for year in sorted(years):
        target = joins.setdefault(
            f"{asset}:{year}",
            {
                "asset_code": asset,
                "year": year,
                "both": 0,
                "tradestats_only": 0,
                "obstats_only": 0,
                "tradestats_duplicate_rows": 0,
                "obstats_duplicate_rows": 0,
                "tradestats_off_five_minute_grid_rows": 0,
                "obstats_off_five_minute_grid_rows": 0,
            },
        )
        first, second = (
            {key for key in item[0] if key[0].startswith(year)} for item in (trade, order)
        )
        target["both"] += len(first & second)
        target["tradestats_only"] += len(first - second)
        target["obstats_only"] += len(second - first)
        for dataset, (_, duplicate, off_grid) in datasets.items():
            target[f"{dataset}_duplicate_rows"] += duplicate.get(year, 0)
            target[f"{dataset}_off_five_minute_grid_rows"] += off_grid.get(year, 0)


def _aggregate(records: list[dict]) -> dict:
    groups, years, joins, anomalies = {}, {}, {}, []
    paired = defaultdict(dict)
    # Only one contract's two keysets survive at a time, regardless of source length.
    for record in sorted(
        records,
        key=lambda row: (row["job"]["asset_code"], row["job"]["secid"], row["job"]["dataset"]),
    ):
        job, entry, summary = record["job"], record["entry"], record["summary"]
        keys, duplicate, off_grid, dates = _keys(record["rows_path"], job)
        _summary(record, dates)
        pair = job["asset_code"], job["secid"]
        paired[pair][job["dataset"]] = (keys, duplicate, off_grid)
        if len(paired[pair]) == 2:
            _join_pair(
                job["asset_code"],
                paired.pop(pair),
                joins,
                {day[:4] for day in job["expected_dates"]},
            )
        name = f"{job['dataset']}:{job['asset_code']}"
        group = groups.setdefault(
            name,
            {
                "dataset": job["dataset"],
                "asset_code": job["asset_code"],
                "jobs": 0,
                "rows": 0,
                "pages": 0,
                "empty_jobs": 0,
                "nonadmitted_jobs": 0,
                "missing_asset_code_rows": 0,
                "asset_alias_mismatch_rows": 0,
                "extra_active_date_rows": 0,
                "field_counts": {
                    field: {"null": 0, "zero": 0, "negative": 0}
                    for field in core.FIELDS[job["dataset"]]
                },
            },
        )
        group["jobs"] += 1
        for field in ("rows", "pages"):
            group[field] += entry[field]
        group["empty_jobs"] += int(entry["rows"] == 0)
        group["nonadmitted_jobs"] += int(not summary["source_date_coverage_admitted"])
        for field in (
            "missing_asset_code_rows",
            "asset_alias_mismatch_rows",
            "extra_active_date_rows",
        ):
            group[field] += summary[field]
        for field, counts in summary["field_counts"].items():
            for kind, count in counts.items():
                group["field_counts"][field][kind] += count
        if not summary["source_date_coverage_admitted"]:
            anomalies.append(
                {
                    "job_id": job["job_id"],
                    "empty": entry["rows"] == 0,
                    **{
                        key: summary[key]
                        for key in (
                            "missing_dates",
                            "extra_dates",
                            "missing_asset_code_rows",
                            "asset_alias_mismatch_rows",
                            "extra_active_date_rows",
                        )
                    },
                }
            )
        for year in sorted({day[:4] for day in job["expected_dates"]} | {day[:4] for day in dates}):
            selected = years.setdefault(
                f"{name}:{year}",
                {
                    "dataset": job["dataset"],
                    "asset_code": job["asset_code"],
                    "year": year,
                    "rows": 0,
                    "expected": set(),
                    "observed": set(),
                    "contracts": set(),
                    "jobs": set(),
                },
            )
            selected["jobs"].add(job["job_id"])
            selected["contracts"].add(job["secid"])
            selected["rows"] += sum(count for day, count in dates.items() if day.startswith(year))
            selected["expected"].update(
                (job["asset_code"], job["secid"], day)
                for day in job["expected_dates"]
                if day.startswith(year)
            )
            selected["observed"].update(
                (job["asset_code"], job["secid"], day) for day in dates if day.startswith(year)
            )
    if paired:
        raise ValueError("quality metadata pairing incomplete")
    coverage = []
    for value in years.values():
        expected, observed = value["expected"], value["observed"]
        observed_dates = sorted(key[2] for key in observed)
        coverage.append(
            {key: value[key] for key in ("dataset", "asset_code", "year", "rows")}
            | {
                "expected_active_contract_date_keys": len(expected),
                "observed_date_keys": len(observed),
                "observed_expected_keys": len(expected & observed),
                "missing_expected_keys": len(expected - observed),
                "extra_date_keys": len(observed - expected),
                "contracts_touching_year": len(value["contracts"]),
                "jobs_touching_year": len(value["jobs"]),
                "first_observed_date": observed_dates[0] if observed_dates else None,
                "last_observed_date": observed_dates[-1] if observed_dates else None,
            }
        )
    metrics = [
        "both",
        "tradestats_only",
        "obstats_only",
        "tradestats_duplicate_rows",
        "obstats_duplicate_rows",
        "tradestats_off_five_minute_grid_rows",
        "obstats_off_five_minute_grid_rows",
    ]
    return {
        "by_dataset_asset": [groups[key] for key in sorted(groups)],
        "by_dataset_asset_year": sorted(
            coverage, key=lambda row: (row["dataset"], row["asset_code"], row["year"])
        ),
        "nonadmitted_jobs": anomalies,
        "join_by_asset_year": [joins[key] for key in sorted(joins)],
        "join_totals": {field: sum(row[field] for row in joins.values()) for field in metrics},
    }


def build_report(source_dir: Path, expected_manifest_sha: str) -> dict:
    """Verify inputs, then report metadata; caller must independently run history.audit."""
    root = Path(source_dir).absolute()
    manifest, records = _preflight(root, expected_manifest_sha, jobs=294, pairs=147)
    if {record["job"]["asset_code"] for record in records} != set(core.EXPECTED_CONFIG["assets"]):
        raise ValueError("quality fixed asset universe differs")
    report = _aggregate(records)
    # A canonical source is immutable; nevertheless detect input mutation during projection.
    for record in records:
        base = f"jobs/{record['job']['job_id']}/result"
        _verified(root, f"{base}/manifest.json", record["entry"]["manifest"])
        _verified(root, f"{base}/rows.jsonl", record["entry"]["normalized"])
    _verified(root, "plan.json", manifest["plan"])
    if _hash(_safe(root, "manifest.json")) != expected_manifest_sha:
        raise ValueError("quality source manifest changed during projection")
    return {
        "protocol_id": PROTOCOL,
        "status": "metadata_report_complete",
        "source_protocol_id": core.PROTOCOL,
        "source_manifest_sha256": expected_manifest_sha,
        "source_closure": manifest["closure"],
        "source_plan": manifest["plan"],
        "source_parent_sample": manifest["parent_sample"],
        "inputs": [
            {
                "job_id": record["job"]["job_id"],
                "manifest": record["entry"]["manifest"],
                "normalized": record["entry"]["normalized"],
            }
            for record in records
        ],
        "totals": {
            key: manifest[key]
            for key in (
                "job_count",
                "rows",
                "pages",
                "committed_page_request_attempts",
                "committed_page_retry_attempts",
                "source_date_coverage_admitted",
            )
        },
        "metadata_columns_read": METADATA_COLUMNS,
        "full_raw_replay_performed": False,
        "requires_separate_history_audit": True,
        "field_counts_replayed_from_numeric_rows": False,
        "limitations": [
            "Date coverage is against the active map, not verified trading sessions.",
            "Date coverage is not complete five-minute-grid coverage or TS/OB key alignment.",
            "Null/zero/negative counts are pinned diagnostics, not numeric-row recomputations.",
            "Annual field counts are unavailable; cross-year jobs are not allocated by year.",
            "Year-touching contract/job counts are nonadditive; pages are not assigned to years.",
            "Missing observations are not zero; matching timestamps do not prove availability.",
            "These checks do not prove original-vintage PIT, atomic vendor snapshot or fills.",
        ],
        **report,
        **FLAGS,
    }
