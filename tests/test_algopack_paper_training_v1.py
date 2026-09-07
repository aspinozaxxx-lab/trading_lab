"""Synthetic projection/coverage/closure tests. No credentials or market data."""

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import algopack_paper_training_v1 as runner
from market_lab.futures.algopack_paper_model_v1 import FLOW_COLUMNS, PRICE_COLUMNS, TARGET_COLUMNS


def flow_fixture(tmp_path, **changes):
    row = dict(
        dataset="tradestats",
        requested_asset_code="BR",
        secid="BRM5",
        tradedate="2025-06-02",
        tradetime="11:00:00",
        trades_b=3,
        trades_s=1,
        vol_b=6,
        vol_s=2,
        forbidden_target="SHOULD_NOT_BE_PROJECTED",
    )
    row.update(changes)
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    source = dict(path=path.name, bytes=path.stat().st_size, rows=1, sha256=runner.digest(path))
    job = dict(
        dataset="tradestats",
        asset_code="BR",
        secid="BRM5",
        **{"from": "2025-06-02", "till": "2025-06-02"},
    )
    return dict(rows_path=path, job=job, entry=dict(normalized=source))


def test_projection_clock_identity_and_schema(tmp_path):
    record = flow_fixture(tmp_path)
    key = ("tradestats", "BR", "BRM5", datetime(2025, 6, 2, 8, tzinfo=UTC))
    before = runner.now()
    result, provenance, catalog = runner.project_flow(record, {key})
    assert result[key].values == (3.0, 1.0, 6.0, 2.0)
    assert result[key].available_at >= before
    assert result[key].version_sha256 == provenance[0]["version_sha256"]
    assert provenance[0]["row_number"] == 0
    assert catalog["selected_rows"] == 1
    empty, _, catalog = runner.project_flow(record, set())
    assert empty == {} and catalog["projected_rows"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        dict(tradedate="2026-01-01"),
        dict(secid="OTHER"),
        dict(tradetime="11:02:00"),
        dict(dataset="obstats"),
    ],
)
def test_flow_metadata_rejected_before_numeric_projection(tmp_path, monkeypatch, changes):
    record = flow_fixture(tmp_path, **changes)
    calls = []
    original = runner.arrow_json.open_json

    def observed(*args, **kwargs):
        calls.append(kwargs["parse_options"].explicit_schema)
        return original(*args, **kwargs)

    monkeypatch.setattr(runner.arrow_json, "open_json", observed)
    with pytest.raises(ValueError):
        runner.project_flow(record, set())
    assert len(calls) == 1  # Only the all-string metadata schema was materialized.
    assert all(runner.arrow.types.is_string(field.type) for field in calls[0])


def test_flow_changed_bytes_fail(tmp_path):
    record = flow_fixture(tmp_path)
    record["rows_path"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        runner.project_flow(record, set())


def test_flow_missing_numeric_preserved(tmp_path):
    record = flow_fixture(tmp_path, vol_b=None)
    key = ("tradestats", "BR", "BRM5", datetime(2025, 6, 2, 8, tzinfo=UTC))
    result, _, _ = runner.project_flow(record, {key})
    assert result[key].values[2] is None


def test_coverage_keeps_price_only_requests_when_flow_or_label_absent():
    index = pd.DatetimeIndex(
        ["2025-06-02T08:00:00Z", "2025-06-02T08:10:00Z", "2025-06-02T08:20:00Z"]
    )
    candidates = pd.DataFrame(index=index)
    features = pd.DataFrame(1.0, index=index, columns=list((*PRICE_COLUMNS, *FLOW_COLUMNS)))
    labels = pd.DataFrame(1.0, index=index, columns=list(TARGET_COLUMNS))
    features.loc[index[0], FLOW_COLUMNS[0]] = np.nan
    labels.loc[index[1], TARGET_COLUMNS[0]] = np.nan
    counts, mask = runner.coverage(candidates, features, labels)
    assert counts["candidate_rows"] == counts["price_feature_rows"] == 3
    assert counts["full_feature_rows"] == counts["four_target_rows"] == 2
    assert counts["joint_training_rows"] == 1
    assert mask.tolist() == [False, False, True]
    assert counts["by_year"]["2020"]["candidates"] == 0


def test_write_new_never_overwrites(tmp_path):
    path = tmp_path / "manifest.json"
    runner.write_new(path, {"status": "original"})
    with pytest.raises(FileExistsError):
        runner.write_new(path, {"status": "replacement"})
    assert json.loads(path.read_bytes())["status"] == "original"


def test_wrong_seal_stops_before_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "PROJECT", tmp_path)
    (tmp_path / "configs").mkdir()
    (tmp_path / runner.SEAL).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="seal mismatch"):
        runner.verify_code("0" * 64)
