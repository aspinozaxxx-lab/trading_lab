"""Tests for the presealed joint V41 depth and synchronization gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_lab.futures import v41_forward_execution_admission as admission


def _quote_payload(secid: str, board: str, bid_depth: float, offer_depth: float) -> dict:
    securities_columns = ["SECID", "BOARDID", "LOTSIZE"]
    return {
        "securities": {
            "columns": securities_columns,
            "data": [[secid, board, 10]],
        },
        "marketdata": {
            "columns": ["SECID", "BOARDID", "BIDDEPTH", "OFFERDEPTH"],
            "data": [[secid, board, bid_depth, offer_depth]],
        },
    }


def _stock_snapshot(path: Path, *, weak_spot: bool = False) -> Path:
    path.mkdir()
    config = admission.stock_source.load_protocol().payload
    records = []
    for index, asset in enumerate(config["universe"]["logical_assets"]):
        spot = config["universe"]["spot_secids"][asset]
        spot_depth = 9 if weak_spot and index == 0 else 10
        records.append(
            {
                "kind": "marketdata_spot",
                "logical_asset": asset,
                "secid": spot,
                "payload": _quote_payload(spot, "TQBR", spot_depth, 10),
            }
        )
        future = f"{asset}TEST"
        records.append(
            {
                "kind": "marketdata_futures",
                "logical_asset": asset,
                "secid": future,
                "payload": _quote_payload(future, "RFUD", 1, 2),
            }
        )
    raw = path / "raw.jsonl.gz"
    raw.write_bytes(admission.stock_source.daily_source._raw_bytes(records))
    (path / "manifest.json").write_text(
        json.dumps({"artifacts": {"raw": {"file": raw.name}}}),
        encoding="utf-8-sig",
    )
    return path


def _lqdt_snapshot(path: Path) -> Path:
    path.mkdir()
    raw = path / "raw.jsonl.gz"
    raw.write_bytes(
        admission.stock_source.daily_source._raw_bytes(
            [
                {
                    "payload": _quote_payload("LQDT", "TQBR", 1000, 1200),
                }
            ]
        )
    )
    (path / "manifest.json").write_text(
        json.dumps({"artifacts": {"raw": {"file": raw.name}}}),
        encoding="utf-8-sig",
    )
    return path


def test_config_seal_and_phase_are_exact() -> None:
    config = admission.load_config()
    progress = admission.phase_progress(61, config["readiness"])

    assert admission._sha(admission.CONFIG_PATH) == admission.CONFIG_SHA256
    assert progress["current_phase"] == "calibration"
    assert progress["discovery"] == {"complete": 60, "required": 60}
    assert progress["calibration"] == {"complete": 1, "required": 20}


def test_depth_gate_requires_one_covered_unit_and_positive_lqdt(tmp_path: Path) -> None:
    config = admission.load_config()
    strong = _stock_snapshot(tmp_path / "strong")
    weak = _stock_snapshot(tmp_path / "weak", weak_spot=True)
    lqdt = _lqdt_snapshot(tmp_path / "lqdt")

    result = admission._stock_depth(strong, config)
    assert result["minimum_coverage_multiple"] == 1.0
    assert admission._lqdt_depth(lqdt) == {
        "bid_depth_units": 1000.0,
        "offer_depth_units": 1200.0,
    }
    with pytest.raises(ValueError, match="below one covered unit"):
        admission._stock_depth(weak, config)


def test_joint_gate_enforces_thirty_second_skew(tmp_path: Path, monkeypatch) -> None:
    stock_entries = {}
    lqdt_entries = {}
    for stage, stock_time, lqdt_time in (
        ("decision", "2026-09-02T12:49:00Z", "2026-09-02T12:49:20Z"),
        ("fill", "2026-09-02T12:59:00Z", "2026-09-02T12:59:25Z"),
    ):
        key = ("2026-09-02", stage)
        stock_entries[key] = {
            "snapshot": tmp_path / f"stock_{stage}",
            "manifest": {"retrieved_at_utc": stock_time},
        }
        lqdt_entries[key] = {
            "snapshot": tmp_path / f"lqdt_{stage}",
            "manifest": {"retrieved_at_utc": lqdt_time},
        }

    def fake_entries(root: Path, audit_function: object):
        entries = (
            stock_entries
            if audit_function is admission.stock_source.audit
            else lqdt_entries
        )
        return entries, [], {}

    monkeypatch.setattr(admission, "_parent_entries", fake_entries)
    monkeypatch.setattr(
        admission,
        "_stock_depth",
        lambda snapshot, config: {"minimum_coverage_multiple": 2.0},
    )
    monkeypatch.setattr(
        admission,
        "_lqdt_depth",
        lambda snapshot: {"bid_depth_units": 100.0, "offer_depth_units": 110.0},
    )

    report = admission.assess(tmp_path / "stock", tmp_path / "lqdt")

    assert report["joint_date_count"] == 1
    assert report["rejected_joint_date_count"] == 0
    assert report["progress"]["remaining_to_economic_protocol_seal"] == 59
    assert report["paper_economics_allowed"] is False
