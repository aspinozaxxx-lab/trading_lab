"""Synthetic manifest trees only; prove protected rows fail before price projection."""

from __future__ import annotations

import hashlib
import json
import os

import pandas as pd
import pytest

from market_lab.futures import algopack_paper_inputs_v1 as inputs


def identity(root, path, **extra):
    raw = path.read_bytes()
    return dict(
        path=path.relative_to(root).as_posix(),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        **extra,
    )


def write_manifest(root, name, value, **extra):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return identity(root, path, **extra)


def source(
    root,
    *,
    protected=False,
    wrong_contract=False,
    duplicate_time=False,
    bad_end=False,
    requested_end="2025-12-31",
    empty=True,
):
    assets = []
    for index, asset in enumerate(inputs.ALIASES):
        n = 0 if empty and index == 3 else 1
        if duplicate_time and index == 0:
            n = 2
        contract = f"{asset}:{asset}U5:2025-09-18"
        begin = pd.Timestamp("2026-01-01" if protected else "2025-09-08", tz="UTC")
        end = begin + pd.Timedelta(minutes=-1 if bad_end else 9)
        frame = pd.DataFrame(
            {
                "timestamp": pd.Series([begin] * n, dtype="datetime64[ns, UTC]"),
                "end_timestamp": pd.Series([end] * n, dtype="datetime64[ns, UTC]"),
                "canonical_contract_id": pd.Series(
                    ["WRONG" if wrong_contract else contract] * n, dtype="string"
                ),
                **{key: pd.Series([100.0] * n, dtype="float64") for key in inputs.PRICE_COLUMNS},
            }
        )
        parquet = root / f"{asset}.parquet"
        frame.to_parquet(parquet, index=False)
        raw = root / f"{asset}.raw"
        raw.write_bytes(b"synthetic opaque raw artifact")
        artifacts = {
            "raw": identity(root, raw, rows=n, pages=1),
            "parquet": identity(root, parquet, rows=n, pages=1),
        }
        counts = dict(segments=1, empty_segments=int(n == 0), rows=n, pages=1)
        status = "complete" if n else "complete_empty"
        segment = dict(
            asset=dict(asset_code=asset),
            segment=dict(
                canonical_segment_id=asset,
                canonical_contract_id=contract,
                secid=f"{asset}U5",
                board_id="RFUD",
                requested_start="2018-01-01",
                requested_end=requested_end,
            ),
            status=status,
            counts=dict(rows=n, pages=1),
            artifacts=artifacts,
        )
        ref = write_manifest(
            root,
            f"{asset}.segment.json",
            segment,
            rows=n,
            pages=1,
            canonical_segment_id=asset,
            status=status,
        )
        asset_manifest = dict(
            asset=dict(asset_code=asset),
            requested_end="2025-12-31",
            protected_from="2026-01-01",
            counts=counts,
            segment_manifests=[ref],
        )
        assets.append(
            write_manifest(root, f"{asset}.asset.json", asset_manifest, asset_code=asset, **counts)
        )
    totals = {
        key: sum(asset[key] for asset in assets)
        for key in ("segments", "empty_segments", "rows", "pages")
    }
    return write_manifest(
        root,
        "top.json",
        dict(
            namespace="futures_v7_10m",
            requested_end="2025-12-31",
            protected_from="2026-01-01",
            assets=assets,
            totals=dict(assets=4, **totals),
        ),
    )


def test_complete_transitive_preflight_is_metadata_only(tmp_path, monkeypatch):
    ref = source(tmp_path)
    reads = []
    original = inputs.pd.read_parquet

    def watched(*args, **kwargs):
        reads.append(kwargs["columns"])
        return original(*args, **kwargs)

    monkeypatch.setattr(inputs.pd, "read_parquet", watched)
    report, artifacts = inputs.inspect_intraday(tmp_path, ref)
    assert report["totals"] == dict(assets=4, segments=4, empty_segments=1, rows=3, pages=4)
    assert report["prices_read"] is False and report["semantic_raw_replay"] is False
    assert len(report["identities"]) == 17
    assert len(artifacts) == 4
    assert all(columns == inputs.TIME_COLUMNS for columns in reads)


@pytest.mark.parametrize("option", ["protected", "wrong_contract", "duplicate_time", "bad_end"])
def test_bad_times_or_contract_rejected_before_price_read(tmp_path, monkeypatch, option):
    ref = source(tmp_path, **{option: True})
    original = inputs.pd.read_parquet

    def guarded(*args, **kwargs):
        assert kwargs["columns"] == inputs.TIME_COLUMNS
        return original(*args, **kwargs)

    monkeypatch.setattr(inputs.pd, "read_parquet", guarded)
    with pytest.raises(ValueError):
        inputs.inspect_intraday(tmp_path, ref)


def test_requested_future_boundary_rejected_even_for_empty_source(tmp_path):
    ref = source(tmp_path, requested_end="2026-01-01")
    with pytest.raises(ValueError, match="boundary"):
        inputs.inspect_intraday(tmp_path, ref)


@pytest.mark.parametrize(
    "name", ["top.json", "Si.asset.json", "Si.segment.json", "Si.raw", "Si.parquet"]
)
def test_any_transitive_mutation_rejected(tmp_path, name):
    ref = source(tmp_path)
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="identity"):
        inputs.inspect_intraday(tmp_path, ref)


@pytest.mark.parametrize("relative", ["../x", "/x", "x//y", "./x", "C:/x", "x\\y", ""])
def test_unsafe_paths_rejected(tmp_path, relative):
    with pytest.raises(ValueError):
        inputs.safe(tmp_path, relative)


@pytest.mark.skipif(os.name == "nt", reason="Linux deploy must exercise symlink refusal")
def test_symlink_file_and_root_rejected(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "real").write_bytes(b"test")
    (directory / "link").symlink_to(directory / "real")
    (tmp_path / "alias").symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError):
        inputs.safe(directory, "link")
    with pytest.raises(ValueError):
        inputs.safe(tmp_path / "alias", "real")


def test_explicit_price_load_rechecks_metadata_and_identity(tmp_path, monkeypatch):
    ref = source(tmp_path)
    _, artifacts = inputs.inspect_intraday(tmp_path, ref)
    reads = []
    original = inputs.pd.read_parquet

    def watched(*args, **kwargs):
        reads.append(kwargs["columns"])
        return original(*args, **kwargs)

    monkeypatch.setattr(inputs.pd, "read_parquet", watched)
    frame = inputs.load_price_artifact(tmp_path, artifacts[0])
    assert frame["asset"].tolist() == ["SI"]
    assert reads == [inputs.TIME_COLUMNS, inputs.TIME_COLUMNS + inputs.PRICE_COLUMNS]
    path = tmp_path / artifacts[0]["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        inputs.load_price_artifact(tmp_path, artifacts[0])


@pytest.mark.parametrize(
    "field,value", [("asset", "BR"), ("secid", "SiZ5"), ("contract_id", "WRONG")]
)
def test_derived_asset_or_contract_cannot_be_forged(tmp_path, field, value):
    ref = source(tmp_path)
    _, artifacts = inputs.inspect_intraday(tmp_path, ref)
    with pytest.raises(ValueError, match="identity"):
        inputs.load_price_artifact(tmp_path, {**artifacts[0], field: value})


def test_missing_raw_not_ignored(tmp_path):
    ref = source(tmp_path)
    (tmp_path / "Si.raw").unlink()
    with pytest.raises(FileNotFoundError):
        inputs.inspect_intraday(tmp_path, ref)


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_bytes(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="duplicate"):
        inputs.read_manifest(tmp_path, identity(tmp_path, path))


def test_asset_totals_reconciled(tmp_path):
    ref = source(tmp_path)
    path = tmp_path / "top.json"
    top = json.loads(path.read_bytes())
    top["totals"]["rows"] += 1
    ref = write_manifest(tmp_path, "top.json", top)
    with pytest.raises(ValueError, match="aggregate"):
        inputs.inspect_intraday(tmp_path, ref)


def active_map(root, **overrides):
    row = dict(
        effective_date=pd.Timestamp("2025-09-08"),
        decision_date=pd.Timestamp("2025-09-05"),
        observed_through=pd.Timestamp("2025-09-05"),
        asset_code="RTS",
        contract_id="RTS:RIU5:2025-09-18",
        secid="RIU5",
        plan_tradable=True,
    )
    row.update(overrides)
    path = root / "plan.parquet"
    pd.DataFrame([row]).to_parquet(path, index=False)
    return identity(root, path, rows=1)


def test_active_map_uses_effective_date_not_decision_date(tmp_path):
    plan = inputs.load_active_plan(tmp_path, active_map(tmp_path))
    assert plan.iloc[0].asset == "RI"
    assert plan.iloc[0].effective_date == pd.Timestamp("2025-09-08")
    assert plan.iloc[0].plan_eligible


@pytest.mark.parametrize(
    "overrides",
    [
        dict(plan_tradable=False),
        dict(observed_through=pd.Timestamp("2025-09-06")),
        dict(decision_date=pd.Timestamp("2025-09-08")),
    ],
)
def test_ineligible_plan_rows_not_deleted(tmp_path, overrides):
    plan = inputs.load_active_plan(tmp_path, active_map(tmp_path, **overrides))
    assert len(plan) == 1 and not plan.iloc[0].plan_eligible


def test_protected_active_map_rejected(tmp_path):
    ref = active_map(tmp_path, effective_date=pd.Timestamp("2026-01-05"))
    with pytest.raises(ValueError, match="protected"):
        inputs.load_active_plan(tmp_path, ref)
