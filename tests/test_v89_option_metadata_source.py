"""Synthetic NULL-mask selection and reference-preserving metadata acquisition."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from market_lab.futures import v89_option_metadata_source as source


def metadata():
    return pd.DataFrame(
        {
            "tradedate": ["2021-01-08", "2021-01-15", "2025-01-03", "2025-01-03"],
            "logical_asset": ["SI", "SI", "SI", "RI"],
            "secid": ["Si100000BC1", "Si100000BC1", "Si100.5CA5B", "RI100000BA5"],
            "boardid": ["ROPD"] * 4,
        }
    )


def test_bitmap_does_not_compare_magnitudes_or_replace_nan_with_null():
    values = pa.array([None, float("nan"), -123, 0, 1e99], from_pandas=False)
    assert source.presence_only(values).tolist() == [False, True, True, True, True]
    changed = pa.array([None, 9, 9, 9, 9])
    np.testing.assert_array_equal(source.presence_only(values), source.presence_only(changed))


def test_chunked_bitmap_alignment():
    column = pa.chunked_array([pa.array([None, 1]), pa.array([2, None])])
    assert source.presence_only(column).tolist() == [False, True, True, False]


def test_all_null_contracts_retained_and_first_report_is_not_first_seen():
    plan, years, quality = source.inventory(metadata(), np.array([False, True, False, True]))
    assert len(plan) == 3 and quality["needed_descriptions"] == 2
    assert quality["source_rows"] == 4 and quality["null_rows"] == 2
    assert quality["all_null_securities_retained"] == 1
    bycode = plan.set_index("secid")
    assert bycode.loc["Si100000BC1", "first_seen"] == pd.Timestamp("2021-01-08")
    assert bycode.loc["Si100000BC1", "first_reported"] == pd.Timestamp("2021-01-15")
    assert pd.isna(bycode.loc["Si100.5CA5B", "first_reported"])
    assert not bycode.loc["Si100.5CA5B", "needs_description"]
    assert years.source_rows.sum() == 4 and years.nonnull_rows.sum() == 2
    assert not quality["oi_magnitudes_read"] and not quality["market_prices_or_pnl_read"]


@pytest.mark.parametrize("change", ["protected", "duplicate", "asset", "secid_asset_conflict"])
def test_inventory_scope_fails_closed(change):
    d = metadata()
    if change == "protected":
        d.loc[0, "tradedate"] = "2026-01-01"
    elif change == "duplicate":
        d.loc[1, "tradedate"] = d.loc[0, "tradedate"]
    elif change == "asset":
        d.loc[0, "logical_asset"] = "not-declared"
    else:
        d.loc[1, "logical_asset"] = "RI"
    with pytest.raises(ValueError):
        source.inventory(d, np.array([True] * len(d)))


def test_bitmap_length_and_type_enforced():
    with pytest.raises(ValueError):
        source.inventory(metadata(), np.array([True]))
    with pytest.raises(ValueError):
        source.inventory(metadata(), np.array([0, 1, 0, 1]))


def raw(code):
    fields = {
        "SECID": code,
        "LSTDELDATE": "2025-01-16",
        "LSTTRADE": "2025-01-16",
        "FRSTTRADE": "2024-10-11",
        "SERIES_NAME": "synthetic-series",
        "CONTRACTNAME": "synthetic-contract",
        "LAST": "never-interpret",
    }
    return json.dumps(
        {"description": {"columns": ["name", "value"], "data": list(map(list, fields.items()))}}
    ).encode()


def test_new_static_fields_do_not_create_implied_underlying_or_price():
    cfg = json.loads(source.CONFIG.read_text(encoding="utf-8-sig"))
    result = source.parse_description(
        raw("RI100000BA5"), {"kind": "description", "identity": {"secid": "RI100000BA5"}}, cfg
    )
    assert result["static_fields"]["SERIES_NAME"] == "synthetic-series"
    assert "LAST" not in result["static_fields"]
    assert result["static_date_fields"]["LSTDELDATE"] == "2025-01-16"
    assert not result["exact_underlying_execution_mapping_admitted"]


def test_synthetic_collection_reuses_old_bytes_and_records_http_gap(tmp_path, monkeypatch):
    cfg = json.loads(source.CONFIG.read_text(encoding="utf-8-sig"))
    census_root, output = tmp_path / "census", tmp_path / "output"
    census_root.mkdir()
    output.mkdir()
    cfg.update(census_root=str(census_root), output_root=str(output))
    cfg["transport"].update(minimum_free_bytes=0, minimum_between_requests_seconds=0)
    codes = ["RI100000BA1", "RI100000BA5", "Si100.5CA5B", "Si100000BC1"]
    plan = pd.DataFrame(
        {
            "logical_asset": ["RI", "RI", "SI", "SI"],
            "secid": codes,
            "needs_description": [True, True, True, False],
        }
    )
    plan.to_parquet(census_root / "contracts.parquet", index=False)
    manifest = {
        "seal_sha256": "sealed",
        "quality": {"needed_descriptions": 3},
        "artifacts": {"contracts.parquet": source.base.sha(census_root / "contracts.parquet")},
    }
    (census_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    census_sha = source.base.sha(census_root / "manifest.json")
    previous = tmp_path / "prior.raw"
    previous.write_bytes(raw(codes[0]))
    cache = {
        codes[0]: (
            previous.read_bytes(),
            {
                "path": str(previous),
                "sha256": source.base.sha(previous),
                "bytes": previous.stat().st_size,
                "attempts": [{"http_status": 200}],
            },
        )
    }
    monkeypatch.setattr(source, "reused", lambda _: cache)
    monkeypatch.setattr(source, "prepared", lambda text: Path(text))
    monkeypatch.setattr(source, "verify", lambda _: cfg)
    calls = []

    def fetch(session, item, settings):
        code = item["identity"]["secid"]
        calls.append(code)
        return raw(code), [{"http_status": 200 if code == codes[1] else 404}]

    monkeypatch.setattr(source.parent, "fetch", fetch)
    source.collect(cfg, "sealed", census_sha)
    result = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert calls == codes[1:3]
    assert result["processed"] == 3 and result["reused"] == 1 and result["requested"] == 2
    assert result["exact_descriptions"] == 2 and result["unavailable"] == 1
    assert result["status"] == "COMPLETE_WITH_SOURCE_GAPS"
    assert not result["economic_admission"]
    first = json.loads((output / "record_000000.json").read_text(encoding="utf-8-sig"))
    assert first["reference_reused"] and first["raw"]["path"] == str(previous)
    assert not (output / "response_000000.raw").exists()
    status = json.loads((output / "status.json").read_text(encoding="utf-8-sig"))
    assert status["status"] == "COMPLETE_WITH_SOURCE_GAPS"
