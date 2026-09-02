"""Tests for the sealed non-economic option-surface V2 quality diagnostic."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_forward_option_surface_quality_v1 as quality


def _frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    second_quotes = {
        "BR": (10.0, None),
        "MIX": (None, None),
        "RI": (10.0, 10.0),
        "SI": (11.0, 10.0),
    }
    for asset_index, asset in enumerate(("BR", "MIX", "RI", "SI")):
        for strike_index, strike in enumerate((100.0, 110.0)):
            bid, offer = (9.0, 10.0) if strike_index == 0 else second_quotes[asset]
            rows.append(
                {
                    "source_date": pd.Timestamp("2026-09-03"),
                    "retrieved_at_utc": "2026-09-03T07:00:30Z",
                    "asset_code": asset,
                    "last_trade_date": pd.Timestamp("2026-09-17"),
                    "option_type": "C",
                    "strike": strike,
                    "bid": bid,
                    "offer": offer,
                    "exchange_sequence_number": 1000 + asset_index * 10 + strike_index,
                    "initial_margin_non_covered": 1000.0,
                    "initial_margin_sell": 900.0,
                    "initial_margin_buy": 800.0,
                    "initial_margin_exchange_time": "2026-09-03 09:50:00",
                    "market_update_time": "09:59:30",
                    "last_trade_time": "09:55:00",
                }
            )
    return pd.DataFrame(rows)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {nested for item in value.values() for nested in _all_keys(item)}
    if isinstance(value, list):
        return {nested for item in value for nested in _all_keys(item)}
    return set()


def test_config_is_sealed_before_quality_values() -> None:
    config = quality.load_config()
    assert config["parent_source"]["quality_values_read_before_seal"] is False
    assert config["clock_diagnostics"]["thresholds_are_descriptive_not_strategy_selection"]
    assert config["live_trading_allowed"] is False


def test_summary_reports_only_counts_and_clock_lags() -> None:
    report = quality.summarize_frame(_frame())
    assert report["row_count"] == 8
    assert report["rows_by_asset"] == {"BR": 2, "MIX": 2, "RI": 2, "SI": 2}
    assert report["quote_states_by_asset"]["BR"]["one_sided_positive"] == 1
    assert report["quote_states_by_asset"]["MIX"]["no_positive_quote"] == 1
    assert report["quote_states_by_asset"]["RI"]["locked"] == 1
    assert report["quote_states_by_asset"]["SI"]["crossed"] == 1
    assert report["adjacent_two_sided_pairs_by_asset"] == {
        "BR": 0,
        "MIX": 0,
        "RI": 1,
        "SI": 1,
    }
    assert report["clock_lag_summaries"]["market_update_time"]["lag_minutes"]["q50"] == 1.0
    forbidden = set(quality.load_config()["forbidden_outputs"])
    assert not (forbidden & _all_keys(report))


def test_negative_exchange_clock_lag_fails_closed() -> None:
    frame = _frame()
    frame.loc[0, "market_update_time"] = "10:01:00"
    with pytest.raises(ValueError, match="negative exchange-clock lag"):
        quality.summarize_frame(frame)


def test_publish_and_replay_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = tmp_path / "snapshot_20260903T070030000000Z"
    snapshot.mkdir()
    processed = snapshot / "option_surface.parquet"
    _frame().to_parquet(processed, index=False)
    manifest = {
        "retrieved_at_utc": "2026-09-03T07:00:30Z",
        "processed": {"path": processed.name, "sha256": quality._sha(processed)},
    }
    quality._write_json(snapshot / "manifest.json", manifest)
    monkeypatch.setattr(quality.source, "audit", lambda _: {"synthetic_parent": True})

    result = quality.publish(snapshot, tmp_path / "quality")
    checks = quality.audit(result)
    identity = json.loads((result / "identity.json").read_text(encoding="utf-8-sig"))
    assert all(checks.values())
    assert identity[quality.IDENTITY_ECONOMIC_FLAG] is False
    assert (result / "audit.json").is_file()
