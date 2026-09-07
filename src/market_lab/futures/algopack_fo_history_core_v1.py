"""Outcome-free planning, parsing and structural audit for historical FO sources."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import pyarrow.parquet as parquet
import yaml

from market_lab.futures import moex_algopack_fo_flow_depth_sample_v1 as parent_source

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = "moex_algopack_fo_history_v1"
CORE_RELATIVE = "src/market_lab/futures/algopack_fo_history_core_v1.py"
COLLECTOR_RELATIVE = f"src/market_lab/futures/{PROTOCOL}.py"
CONFIG_RELATIVE = f"configs/{PROTOCOL}.yaml"
COMMON = ["tradedate", "tradetime", "secid", "asset_code", "SYSTIME"]
FIELDS = {
    "tradestats": ["trades", "trades_b", "trades_s", "vol", "vol_b", "vol_s",
                   "val", "val_b", "val_s", "disb"],
    "obstats": ["spread_l1", "spread_l10", "levels_b", "levels_s",
                "vol_b_l1", "vol_s_l1", "vol_b_l10", "vol_s_l10"],
}
COUNT_FIELDS = {"trades", "trades_b", "trades_s", "vol", "vol_b", "vol_s"}
SIGNED_FIELDS = {"disb", "spread_l1", "spread_l10"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
EXPECTED_CONFIG = {
    "protocol_id": PROTOCOL, "start_date": "2020-01-01", "end_date": "2025-12-31",
    "assets": ["BR", "MIX", "RI", "SI"],
    "columns": {dataset: COMMON + fields for dataset, fields in FIELDS.items()},
    "active_map": {
        "path": "data/processed/futures_v5/development_panel_2018_2025_active_contract_map.parquet",
        "sha256": "40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823",
        "bytes": 500949, "rows": 8100,
        "columns": ["effective_date", "decision_date", "observed_through",
                    "asset_code", "contract_id", "secid"],
    },
    "expected_plan": {"asset_days": 6076, "dates": 1519, "contracts": 147, "jobs": 294},
    "expected_asset_aliases": {"BR": "BR", "MIX": "MIX", "RI": "RTS", "SI": "Si"},
    "parent_sample": {
        "path": "data/processed/algopack/moex_algopack_fo_flow_depth_sample_v1_49502b17c35a",
        "seal_sha256": "49502b17c35a3739b24000c5ef0bed7fd6795cbc024f6cbd263f1b55914bd33d",
        "manifest_sha256": "6a14b3f9c724725375e99363e2ed26ae247b9e52e6bb1d4a9523e7ac11749502",
    },
    "max_pages_per_job": 200, "request_interval_seconds": 0.5,
    "retry_delays_seconds": [5, 15, 45], "protected_holdout_start": "2026-01-01",
    "asset_code_missing_policy": "preserve_null_or_empty_and_flag",
    "source_only": True, "current_vintage": True,
    "historical_model_eligible": False, "live_trading_allowed": False,
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify_seal(seal_sha: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{64}", seal_sha) is None:
        raise ValueError("invalid history seal identity")
    raw = (PROJECT_ROOT / f"configs/{PROTOCOL}.seal.json").read_bytes()
    if sha(raw) != seal_sha:
        raise ValueError("history seal identity mismatch")
    seal = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_json_pairs)
    files = seal.get("files", {})
    parent_seal_relative = f"configs/{parent_source.PROTOCOL}.seal.json"
    parent_raw = (PROJECT_ROOT / parent_seal_relative).read_bytes()
    if sha(parent_raw) != EXPECTED_CONFIG["parent_sample"]["seal_sha256"]:
        raise ValueError("parent sample seal identity mismatch")
    parent_files = json.loads(parent_raw.decode("utf-8-sig"))["files"]
    required = {CORE_RELATIVE, COLLECTOR_RELATIVE, CONFIG_RELATIVE,
                f"configs/{PROTOCOL}.sha256", parent_seal_relative,
                "tests/test_algopack_fo_history_core_v1.py", f"tests/test_{PROTOCOL}.py"}
    if (seal.get("protocol_id") != PROTOCOL or not (required | set(parent_files)).issubset(files)
            or any(files.get(path) != digest for path, digest in parent_files.items())):
        raise ValueError("history closure is incomplete or parent dependency differs")
    for relative, digest in files.items():
        path = (PROJECT_ROOT / relative).resolve()
        if not path.is_relative_to(PROJECT_ROOT.resolve()) or sha(path.read_bytes()) != digest:
            raise ValueError("history dependency hash mismatch")
    path = PROJECT_ROOT / CONFIG_RELATIVE
    config_raw = path.read_bytes()
    sidecar = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if (sidecar != sha(config_raw)
            or yaml.safe_load(config_raw.decode("utf-8-sig")) != EXPECTED_CONFIG):
        raise ValueError("history configuration drift")
    return {"seal_sha256": seal_sha, "config_sha256": sha(config_raw), "files": files}


def verify_parent_sample(storage_root: Path) -> dict:
    parent = EXPECTED_CONFIG["parent_sample"]
    path = (storage_root / parent["path"]).resolve()
    if not path.is_relative_to(storage_root.resolve()):
        raise ValueError("parent sample escaped storage root")
    return parent_source.audit(path, storage_root, parent["seal_sha256"], parent["manifest_sha256"])


def _plan_from_frame(frame: pd.DataFrame) -> list[dict]:
    allowed = EXPECTED_CONFIG["active_map"]["columns"]
    if list(frame.columns) != allowed or frame.empty:
        raise ValueError("active-map metadata schema or presence mismatch")
    frame = frame.copy()
    effective = pd.to_datetime(frame["effective_date"], errors="raise", format="ISO8601")
    if (effective.dt.tz is not None or effective.isna().any()
            or not effective.eq(effective.dt.normalize()).all()
            or effective.ge(pd.Timestamp(EXPECTED_CONFIG["protected_holdout_start"])).any()):
        raise ValueError("active-map effective date invalid or protected")
    frame["effective_date"] = effective
    # Initial rows outside the declared history can lack a prior decision/contract.
    # Only a known valid effective date permits classifying them as out of scope.
    frame = frame.loc[effective.between(
        EXPECTED_CONFIG["start_date"], EXPECTED_CONFIG["end_date"]
    )].copy()
    if frame.empty or frame.isna().any().any():
        raise ValueError("selected active-map metadata is missing")
    for column in ("decision_date", "observed_through"):
        values = pd.to_datetime(frame[column], errors="raise")
        if (values.dt.tz is not None or values.isna().any()
                or not values.eq(values.dt.normalize()).all()
                or values.ge(pd.Timestamp(EXPECTED_CONFIG["protected_holdout_start"])).any()):
            raise ValueError("active-map date metadata invalid or protected")
        frame[column] = values
    for column in ("asset_code", "contract_id", "secid"):
        present = frame[column].map(lambda value: isinstance(value, str) and bool(value.strip()))
        if not present.all():
            raise ValueError("active-map identity missing or malformed")
    if (not frame["asset_code"].isin(EXPECTED_CONFIG["assets"]).all()
            or not frame["secid"].map(lambda value: bool(IDENTIFIER.fullmatch(value))).all()):
        raise ValueError("active-map asset or exchange identity invalid")
    if (not frame["decision_date"].eq(frame["observed_through"]).all()
            or not frame["decision_date"].lt(frame["effective_date"]).all()
            or frame.duplicated(["asset_code", "effective_date"]).any()
            or frame.duplicated(["asset_code", "decision_date"]).any()):
        raise ValueError("active-map causality or uniqueness failed")
    if frame.groupby(["asset_code", "secid"])["contract_id"].nunique().ne(1).any():
        raise ValueError("active-map contract identity is inconsistent for exchange SECID")
    selected = frame.sort_values(["asset_code", "effective_date"], kind="stable")
    spans, seen_contracts = [], set()
    for asset, group in selected.groupby("asset_code", sort=True):
        previous = None
        for row in group.itertuples(index=False):
            identity = (row.contract_id, row.secid)
            day = row.effective_date.date().isoformat()
            if identity != previous:
                if (asset, row.secid) in seen_contracts:
                    raise ValueError("active-map exchange contract has noncontiguous spans")
                seen_contracts.add((asset, row.secid))
                spans.append({"asset_code": asset, "secid": row.secid,
                              "from": day, "till": day, "expected_dates": [day]})
            else:
                spans[-1]["till"] = day
                spans[-1]["expected_dates"].append(day)
            previous = identity
    jobs = []
    for dataset in EXPECTED_CONFIG["columns"]:
        ordered = sorted(spans, key=lambda item: (item["asset_code"], item["from"], item["secid"]))
        for span in ordered:
            parts = dataset, span["asset_code"], span["secid"], span["from"], span["till"]
            job_id = "_".join(parts)
            jobs.append({"job_id": job_id, "dataset": dataset, **span})
    if len({job["job_id"] for job in jobs}) != len(jobs):
        raise ValueError("active-map plan job identity collision")
    return jobs


def build_plan(storage_root: Path) -> list[dict]:
    source = EXPECTED_CONFIG["active_map"]
    path = (storage_root / source["path"]).resolve()
    if (not path.is_relative_to(storage_root.resolve()) or path.stat().st_size != source["bytes"]
            or sha(path.read_bytes()) != source["sha256"]):
        raise ValueError("active-map pinned byte identity mismatch")
    file = parquet.ParquetFile(path)
    if file.metadata.num_rows != source["rows"]:
        raise ValueError("active-map row count mismatch")
    # Never load volume, prices, targets or other columns from the parent map.
    frame = file.read(columns=source["columns"]).to_pandas()
    jobs = _plan_from_frame(frame)
    spans = [job for job in jobs if job["dataset"] == next(iter(EXPECTED_CONFIG["columns"]))]
    observed = {"asset_days": sum(len(job["expected_dates"]) for job in spans),
                "dates": len({day for job in spans for day in job["expected_dates"]}),
                "contracts": len({(job["asset_code"], job["secid"]) for job in spans}),
                "jobs": len(jobs)}
    if (observed != EXPECTED_CONFIG["expected_plan"]
            or {job["asset_code"] for job in jobs} != set(EXPECTED_CONFIG["assets"])):
        raise ValueError("active-map declared plan counts mismatch")
    return jobs


def _date(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("history date is not a string")
    parsed = datetime.strptime(value, "%Y-%m-%d")
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError("history date is not exact ISO")
    return value


def _validate_job(job: dict) -> None:
    if (job["dataset"] not in FIELDS or job["asset_code"] not in EXPECTED_CONFIG["assets"]
            or not isinstance(job["secid"], str) or not IDENTIFIER.fullmatch(job["secid"])):
        raise ValueError("history job identity invalid")
    start, end = _date(job["from"]), _date(job["till"])
    if not EXPECTED_CONFIG["start_date"] <= start <= end <= EXPECTED_CONFIG["end_date"]:
        raise ValueError("history job escaped protected bounds")
    dates = job["expected_dates"]
    if (not isinstance(dates, list) or not dates or dates != sorted(set(dates))
            or any(not start <= _date(day) <= end for day in dates)):
        raise ValueError("history expected active dates invalid")
    if dates[0] != start or dates[-1] != end:
        raise ValueError("history bounds do not match active span")
    expected_id = "_".join((job["dataset"], job["asset_code"], job["secid"], start, end))
    if job["job_id"] != expected_id:
        raise ValueError("history job ID mismatch")


def request_url(job: dict, start: int) -> str:
    _validate_job(job)
    if type(start) is not int or start < 0:
        raise ValueError("history cursor is not a nonnegative integer")
    query = urlencode({"from": job["from"], "till": job["till"], "latest": 0, "start": start,
                       "iss.meta": "off", "iss.only": "data,data.cursor",
                       "data.columns": ",".join(EXPECTED_CONFIG["columns"][job["dataset"]])})
    return (f"https://apim.moex.com/iss/datashop/algopack/fo/{job['dataset']}/"
            f"{job['secid']}.json?{query}")


def parse_page(raw: bytes, job: dict, start: int) -> tuple[list[dict], dict]:
    request_url(job, start)
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_json_pairs)
        if set(payload) != {"data", "data.cursor"}:
            raise ValueError("unexpected history blocks")
        data, cursor = payload["data"], payload["data.cursor"]
        columns = EXPECTED_CONFIG["columns"][job["dataset"]]
        if (set(data) != {"columns", "data"} or set(cursor) != {"columns", "data"}
                or data["columns"] != columns or cursor["columns"] != ["INDEX", "TOTAL", "PAGESIZE"]
                or len(cursor["data"]) != 1 or len(cursor["data"][0]) != 3):
            raise ValueError("history response schema mismatch")
        index, total, size = cursor["data"][0]
        if (any(type(number) is not int for number in (index, total, size))
                or index != start or total < index or size <= 0
                or not isinstance(data["data"], list)
                or len(data["data"]) != min(size, total - index)):
            raise ValueError("history cursor completeness failed")
        rows, seen = [], set()
        expected_dates = set(job["expected_dates"])
        for values in data["data"]:
            if not isinstance(values, list) or len(values) != len(columns):
                raise ValueError("history row width mismatch")
            row = dict(zip(columns, values, strict=True))
            day = _date(row["tradedate"])
            if not job["from"] <= day <= job["till"] or row["secid"] != job["secid"]:
                raise ValueError("history row escaped date or contract")
            clock = datetime.strptime(row["tradetime"], "%H:%M:%S")
            if clock.strftime("%H:%M:%S") != row["tradetime"]:
                raise ValueError("history observation clock invalid")
            observed = datetime.fromisoformat(day + " " + row["tradetime"])
            system = datetime.fromisoformat(row["SYSTIME"])
            if system.tzinfo is not None or system < observed:
                raise ValueError("history system clock invalid")
            missing = row["asset_code"] is None or row["asset_code"] == ""
            if not missing and (not isinstance(row["asset_code"], str)
                                or not IDENTIFIER.fullmatch(row["asset_code"])):
                raise ValueError("history asset metadata invalid")
            for field in FIELDS[job["dataset"]]:
                value = row[field]
                if value is not None and (type(value) not in (int, float)
                        or not math.isfinite(value)
                        or (field not in SIGNED_FIELDS and value < 0)
                        or (field in COUNT_FIELDS and value != math.trunc(value))):
                    raise ValueError("history numeric domain invalid")
            key = (day, row["tradetime"], row["secid"])
            if key in seen:
                raise ValueError("duplicate history observation")
            seen.add(key)
            rows.append({**row, "dataset": job["dataset"],
                         "requested_asset_code": job["asset_code"], "asset_code_missing": missing,
                         "is_expected_active_date": day in expected_dates})
        return rows, {"INDEX": index, "TOTAL": total, "PAGESIZE": size}
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("invalid historical source response") from None


def summarize_rows(rows: list[dict], job: dict) -> dict:
    _validate_job(job)
    dates = sorted({row["tradedate"] for row in rows})
    expected = set(job["expected_dates"])
    missing = sum(row["asset_code_missing"] for row in rows)
    alias = EXPECTED_CONFIG["expected_asset_aliases"][job["asset_code"]]
    mismatches = sum(not row["asset_code_missing"] and row["asset_code"] != alias for row in rows)
    missing_dates, extra_dates = sorted(expected - set(dates)), sorted(set(dates) - expected)
    return {
        "rows": len(rows), "observed_dates": dates, "expected_dates": job["expected_dates"],
        "missing_dates": missing_dates, "extra_dates": extra_dates,
        "date_counts": {day: sum(row["tradedate"] == day for row in rows) for day in dates},
        "missing_asset_code_rows": missing, "asset_alias_mismatch_rows": mismatches,
        "extra_active_date_rows": sum(not row["is_expected_active_date"] for row in rows),
        "field_counts": {field: {
            "null": sum(row[field] is None for row in rows),
            "zero": sum(row[field] == 0 for row in rows),
            "negative": sum(row[field] is not None and row[field] < 0 for row in rows),
        } for field in FIELDS[job["dataset"]]},
        "source_date_coverage_admitted": bool(rows) and not (
            missing_dates or extra_dates or missing or mismatches
        ),
        "historical_model_eligible": False,
    }
