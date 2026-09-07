"""Synthetic planning and metadata/domain tests for the historical FO source core."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import yaml

from market_lab.futures import algopack_fo_history_core_v1 as core


def _job(dataset: str = "tradestats") -> dict:
    return {"job_id": f"{dataset}_SI_SiH0_2020-01-03_2020-01-06", "dataset": dataset,
            "asset_code": "SI", "secid": "SiH0", "from": "2020-01-03", "till": "2020-01-06",
            "expected_dates": ["2020-01-03", "2020-01-06"]}


def _row(dataset: str = "tradestats", **changes: object) -> list:
    row = {"tradedate": "2020-01-03", "tradetime": "10:05:00", "secid": "SiH0",
           "asset_code": "Si", "SYSTIME": "2026-09-07 10:06:00",
           **{field: 1 for field in core.FIELDS[dataset]}, **changes}
    return [row[column] for column in core.EXPECTED_CONFIG["columns"][dataset]]


def _page(dataset: str = "tradestats", rows: list | None = None, *, index: int = 0,
          total: int | None = None, size: int = 2) -> bytes:
    rows = [_row(dataset)] if rows is None else rows
    return json.dumps({
        "data": {"columns": core.EXPECTED_CONFIG["columns"][dataset], "data": rows},
        "data.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"],
                        "data": [[index, len(rows) if total is None else total, size]]},
    }).encode()


def _frame() -> pd.DataFrame:
    rows = []
    for day, contract in (("2019-12-30", "SiZ9"), ("2020-01-03", "SiH0"),
                          ("2020-01-06", "SiH0"), ("2020-01-07", "SiM0"),
                          ("2020-01-08", "SiU0")):
        effective = pd.Timestamp(day)
        prior = effective - pd.Timedelta(days=1)
        rows.append({"effective_date": effective, "decision_date": prior,
                     "observed_through": prior, "asset_code": "SI",
                     "contract_id": f"SI:{contract}", "secid": contract})
    return pd.DataFrame(rows, columns=core.EXPECTED_CONFIG["active_map"]["columns"])


def test_config_matches_authoritative_file() -> None:
    raw = (core.PROJECT_ROOT / core.CONFIG_RELATIVE).read_text(encoding="utf-8-sig")
    config = yaml.safe_load(raw)
    assert config == core.EXPECTED_CONFIG


def test_plan_is_deterministic_and_preserves_separate_contract_spans() -> None:
    jobs = core._plan_from_frame(_frame().sample(frac=1, random_state=4))
    assert jobs == core._plan_from_frame(_frame())
    assert len(jobs) == 6
    assert [job["dataset"] for job in jobs] == ["tradestats"] * 3 + ["obstats"] * 3
    assert jobs[0] == _job()
    assert jobs[1]["secid"] == "SiM0"
    assert jobs[2]["secid"] == "SiU0"
    assert jobs[0]["till"] == "2020-01-06"
    assert jobs[2]["from"] == "2020-01-08"
    assert all("2019" not in job["job_id"] for job in jobs)


def test_noncontiguous_exchange_contract_cannot_become_multiple_jobs() -> None:
    frame = _frame()
    frame.loc[4, ["contract_id", "secid"]] = ["SI:SiH0", "SiH0"]
    with pytest.raises(ValueError, match="noncontiguous"):
        core._plan_from_frame(frame)


def test_exchange_contract_cannot_change_internal_identity() -> None:
    frame = _frame()
    frame.loc[2, "contract_id"] = "SI:DIFFERENT"
    with pytest.raises(ValueError, match="identity is inconsistent"):
        core._plan_from_frame(frame)


def test_initial_2018_null_priors_and_contracts_are_outside_fixed_history() -> None:
    frame = _frame()
    frame.loc[0, "effective_date"] = pd.Timestamp("2018-01-03")
    frame.loc[0, ["decision_date", "observed_through"]] = pd.NaT
    frame.loc[0, ["contract_id", "secid"]] = None
    assert core._plan_from_frame(frame) == core._plan_from_frame(_frame().iloc[1:].copy())


@pytest.mark.parametrize("column", ["decision_date", "observed_through", "contract_id", "secid"])
def test_same_null_metadata_inside_selected_history_still_fails(column: str) -> None:
    frame = _frame()
    frame.loc[1, column] = None
    with pytest.raises(ValueError, match="selected active-map metadata is missing"):
        core._plan_from_frame(frame)


@pytest.mark.parametrize("effective", [None, "unknown-date", "2018-01-03 12:00:00"])
def test_unknown_or_invalid_effective_date_cannot_be_discarded(effective: object) -> None:
    frame = _frame()
    frame["effective_date"] = frame["effective_date"].astype(object)
    frame.loc[0, "effective_date"] = effective
    with pytest.raises(ValueError):
        core._plan_from_frame(frame)


@pytest.mark.parametrize("column,value", [
    ("observed_through", pd.Timestamp("2020-01-01")),
    ("decision_date", pd.Timestamp("2020-01-03")),
    ("effective_date", pd.Timestamp("2026-01-01")),
    ("secid", None), ("contract_id", ""), ("asset_code", "UNKNOWN"),
])
def test_invalid_plan_metadata_and_causality_fail(column: str, value: object) -> None:
    frame = _frame()
    frame.loc[1, column] = value
    with pytest.raises(ValueError):
        core._plan_from_frame(frame)


def test_duplicate_active_dates_fail() -> None:
    frame = _frame()
    with pytest.raises(ValueError):
        core._plan_from_frame(pd.concat([frame, frame.iloc[[1]]], ignore_index=True))


def test_build_plan_reads_only_six_metadata_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = json.loads(json.dumps(core.EXPECTED_CONFIG))
    frame = _frame()
    frame["forbidden_price"] = 999
    path = tmp_path / "synthetic.parquet"
    frame.to_parquet(path, index=False)
    config["active_map"].update(path=path.name, bytes=path.stat().st_size,
                                sha256=core.sha(path.read_bytes()), rows=len(frame))
    config["assets"] = ["SI"]
    config["expected_plan"] = {"asset_days": 4, "dates": 4, "contracts": 3, "jobs": 6}
    monkeypatch.setattr(core, "EXPECTED_CONFIG", config)
    original = core.parquet.ParquetFile
    reads = []

    class ProjectionSpy:
        def __init__(self, file_path: Path) -> None:
            self.file = original(file_path)
            self.metadata = self.file.metadata

        def read(self, *, columns: list):
            reads.append(columns)
            return self.file.read(columns=columns)

    monkeypatch.setattr(core.parquet, "ParquetFile", ProjectionSpy)
    assert len(core.build_plan(tmp_path)) == 6
    assert reads == [config["active_map"]["columns"]]
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="byte identity"):
        core.build_plan(tmp_path)


def test_historical_url_has_bounded_full_range_and_closed_schema() -> None:
    parsed = urlparse(core.request_url(_job(), 1000))
    query = parse_qs(parsed.query)
    assert parsed.netloc == "apim.moex.com"
    assert parsed.path.endswith("/tradestats/SiH0.json")
    assert query["from"] == ["2020-01-03"] and query["till"] == ["2020-01-06"]
    assert query["latest"] == ["0"] and query["start"] == ["1000"]
    assert query["data.columns"] == [",".join(core.EXPECTED_CONFIG["columns"]["tradestats"])]


@pytest.mark.parametrize("changes", [
    {"till": "2026-01-01"}, {"from": "2019-12-31"}, {"job_id": "../outside"},
    {"secid": "SiH0?token=bad"}, {"expected_dates": ["2020-01-06", "2020-01-03"]},
])
def test_request_job_cannot_escape_frozen_bounds(changes: dict) -> None:
    with pytest.raises(ValueError):
        core.request_url({**_job(), **changes}, 0)


def test_nonactive_date_inside_span_is_retained_and_flagged() -> None:
    rows, cursor = core.parse_page(_page(rows=[_row(tradedate="2020-01-04")]), _job(), 0)
    assert cursor["TOTAL"] == 1 and len(rows) == 1
    assert rows[0]["is_expected_active_date"] is False
    summary = core.summarize_rows(rows, _job())
    assert summary["extra_dates"] == ["2020-01-04"]
    assert summary["extra_active_date_rows"] == 1
    assert summary["source_date_coverage_admitted"] is False


@pytest.mark.parametrize("changes", [
    {"tradedate": "2026-01-01"}, {"tradedate": "2020-01-07"}, {"secid": "SiM0"},
    {"tradetime": "25:00:00"}, {"SYSTIME": "2020-01-03 09:00:00"},
    {"SYSTIME": "2020-01-03T10:06:00+03:00"}, {"asset_code": 0},
])
def test_malformed_returned_identity_or_clock_fails(changes: dict) -> None:
    with pytest.raises(ValueError):
        core.parse_page(_page(rows=[_row(**changes)]), _job(), 0)


@pytest.mark.parametrize("value", [None, ""])
def test_missing_asset_code_preserved_not_aliased(value: object) -> None:
    rows, _ = core.parse_page(_page(rows=[_row(asset_code=value)]), _job(), 0)
    assert rows[0]["asset_code"] == value
    assert rows[0]["asset_code_missing"] is True
    assert core.summarize_rows(rows, _job())["missing_asset_code_rows"] == 1


@pytest.mark.parametrize("dataset,field,value", [
    ("tradestats", "trades", None), ("tradestats", "vol", 0),
    ("tradestats", "trades", 2.0), ("tradestats", "disb", -0.5),
    ("obstats", "spread_l1", -0.01), ("obstats", "levels_b", 1.5),
])
def test_valid_numeric_types_and_signed_values_remain_literal(
    dataset: str, field: str, value: object,
) -> None:
    rows, _ = core.parse_page(_page(dataset, [_row(dataset, **{field: value})]), _job(dataset), 0)
    assert rows[0][field] == value and type(rows[0][field]) is type(value)


@pytest.mark.parametrize("dataset,field,value", [
    ("tradestats", "trades", True), ("tradestats", "trades", "2"),
    ("tradestats", "vol", 1.5), ("tradestats", "val", -1),
    ("obstats", "levels_s", -1), ("obstats", "spread_l10", float("inf")),
    ("obstats", "vol_b_l1", float("nan")),
])
def test_invalid_numeric_types_and_domains_fail(dataset: str, field: str, value: object) -> None:
    with pytest.raises(ValueError):
        core.parse_page(_page(dataset, [_row(dataset, **{field: value})]), _job(dataset), 0)


def test_duplicate_observations_json_keys_wrong_schema_and_bad_cursor_fail() -> None:
    for raw in (_page(rows=[_row(), _row()]), _page(index=1), _page(total=3),
                b'{"data": {}, "data": {}, "data.cursor": {}}', b"<html>Error</html>"):
        with pytest.raises(ValueError):
            core.parse_page(raw, _job(), 0)
    payload = json.loads(_page())
    payload["data"]["columns"].append("price")
    payload["data"]["data"][0].append(999)
    with pytest.raises(ValueError):
        core.parse_page(json.dumps(payload).encode(), _job(), 0)


def test_summary_distinguishes_empty_dates_nulls_zeros_and_alias_mismatch() -> None:
    rows, _ = core.parse_page(_page(rows=[
        _row(trades=None, vol=0, disb=-0.5),
        _row(tradedate="2020-01-06", asset_code="WRONG"),
    ]), _job(), 0)
    result = core.summarize_rows(rows, _job())
    assert result["missing_dates"] == [] and result["asset_alias_mismatch_rows"] == 1
    assert result["field_counts"]["trades"] == {"null": 1, "zero": 0, "negative": 0}
    assert result["field_counts"]["vol"]["zero"] == 1
    assert result["field_counts"]["disb"]["negative"] == 1
    assert result["source_date_coverage_admitted"] is False
    empty = core.summarize_rows([], _job())
    assert empty["missing_dates"] == _job()["expected_dates"]
    assert empty["rows"] == 0 and empty["source_date_coverage_admitted"] is False


def test_parent_sample_audit_uses_exact_pinned_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def callback(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(core.parent_source, "audit", callback)
    assert core.verify_parent_sample(tmp_path) == {"ok": True}
    expected = core.EXPECTED_CONFIG["parent_sample"]
    assert calls == [((tmp_path / expected["path"]).resolve(), tmp_path,
                      expected["seal_sha256"], expected["manifest_sha256"])]


def test_invalid_seal_rejected_before_any_parent_dependency_read() -> None:
    with pytest.raises(ValueError, match="invalid history seal"):
        core.verify_seal("not-a-sha")
