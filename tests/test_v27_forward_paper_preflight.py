"""Tests for the sealed fail-closed V27 forward paper preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_lab.futures import v27_forward_paper_preflight as preflight


def _decision_snapshot(root: Path, name: str, source_date: str) -> Path:
    snapshot = root / name
    snapshot.mkdir()
    rows = []
    for index, asset in enumerate(preflight.ASSETS):
        rows.append(
            {
                "source_date": pd.Timestamp(source_date),
                "logical_asset": asset,
                "secid": f"{asset}X6",
                "last_trade_date": pd.Timestamp("2026-12-17"),
                "official_open": 100.0 + index,
                "official_high": 102.0 + index,
                "official_low": 99.0 + index,
                "official_close": 101.0 + index,
                "official_settle": 101.0 + index,
                "official_volume": 1000.0,
                "official_open_interest": 5000.0,
            }
        )
    pd.DataFrame(rows).to_parquet(snapshot / "market.parquet", index=False)
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_kind": "decision_eod",
                "counts": {"source_dates": [source_date]},
            }
        ),
        encoding="utf-8-sig",
    )
    return snapshot


def test_config_pins_source_and_253_price_sessions() -> None:
    config = preflight.load_config()

    assert config["source_contract"]["protocol_sha256"].startswith("f4a7d016")
    assert (
        config["signal_and_decision_timing"][
            "required_common_price_sessions_before_first_finite_252_return_signal"
        ]
        == 253
    )
    assert config["roll"]["calendar_provider"] == "MOEX_machine_readable_calendar"


def test_mapping_uses_only_official_history_fields(tmp_path: Path) -> None:
    snapshot = _decision_snapshot(tmp_path, "snapshot_decision_001", "2026-09-02")
    observations = preflight.build_decision_observations(
        [snapshot], preflight.load_config()
    )

    assert tuple(observations.columns) == preflight.OBSERVATION_COLUMNS
    assert observations["close"].tolist() == [103.0, 104.0, 102.0, 101.0]
    assert preflight.common_price_dates(observations) == ["2026-09-02"]
    assert not {"return", "target", "prediction", "pnl"} & set(observations.columns)


def test_preflight_blocks_warmup_and_missing_official_calendar_auth(
    tmp_path: Path, monkeypatch
) -> None:
    _decision_snapshot(tmp_path, "snapshot_decision_001", "2026-09-02")
    monkeypatch.setattr(preflight.source, "audit", lambda snapshot: {"exact": True})
    monkeypatch.delenv("MOEX_ALGOPACK_TOKEN", raising=False)

    report = preflight.assess(tmp_path)

    assert report["common_official_close_date_count"] == 1
    assert report["remaining_common_price_sessions"] == 252
    assert report["paper_economics_may_start"] is False
    assert report["contains_return_target_prediction_or_pnl"] is False
    assert report["blockers"] == [
        "signal_warmup_incomplete",
        "official_future_session_calendar_authorization_missing",
    ]


def test_duplicate_kind_date_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    _decision_snapshot(tmp_path, "snapshot_decision_001", "2026-09-02")
    _decision_snapshot(tmp_path, "snapshot_decision_002", "2026-09-02")
    monkeypatch.setattr(preflight.source, "audit", lambda snapshot: {"exact": True})

    report = preflight.assess(tmp_path)

    assert "duplicate_kind_source_date" in report["blockers"]
    assert report["duplicate_kind_source_dates"] == {
        "decision_eod:2026-09-02": [
            "snapshot_decision_001",
            "snapshot_decision_002",
        ]
    }
