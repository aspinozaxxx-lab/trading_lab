"""Synthetic testy orchestration helperov futures-v6 bez PnL i real data."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures.v6_experiment import (
    _active_rows_for_weights,
    _evaluation_market,
    _portfolio_market_panel,
    _report_text,
)


def test_portfolio_market_panel_uses_forward_adjusted_close_column() -> None:
    """Proveryaet odnoznachnoe pereimenovanie causal panel dlya risk-layer."""
    panel = pd.DataFrame(
        {
            "trade_date": ["2020-12-30"],
            "asset_code": ["SI"],
            "close": [75_000.0],
            "future_noise": [999.0],
        }
    )
    result = _portfolio_market_panel(panel)
    assert list(result.columns) == ["session_date", "asset", "adjusted_close"]
    assert result.iloc[0].to_dict() == {
        "session_date": "2020-12-30",
        "asset": "SI",
        "adjusted_close": 75_000.0,
    }


def test_evaluation_market_physically_excludes_training_and_holdout() -> None:
    """Trebuet tolko 2021-2025 rows pered continuous ledger."""
    market = pd.DataFrame(
        {
            "session_date": ["2020-12-30", "2021-01-04", "2025-12-30", "2026-01-05"],
            "asset_code": ["SI"] * 4,
        }
    )
    result = _evaluation_market(market)
    assert pd.to_datetime(result["session_date"]).dt.year.tolist() == [2021, 2025]


def test_active_rows_require_four_assets_for_each_weight_decision() -> None:
    """Zapreshchaet tikhuyu poteryu contract mapping odnogo asset."""
    assets = ["SI", "RI", "BR", "MIX"]
    decisions = pd.to_datetime(["2020-12-30", "2021-01-04"])
    weights = pd.DataFrame(
        [
            {"decision_date": decision, "asset": asset, "target_weight": 0.0}
            for decision in decisions
            for asset in assets
        ]
    )
    active = pd.DataFrame(
        [
            {"decision_date": decision, "asset_code": asset}
            for decision in decisions
            for asset in assets
        ]
    )
    assert len(_active_rows_for_weights(active, weights)) == 8
    with pytest.raises(ValueError, match="ne pokryvaet"):
        _active_rows_for_weights(active.iloc[:-1], weights)


def test_report_keeps_fifty_percent_as_non_guaranteed_stretch() -> None:
    """Proveryaet chestnyi NO_GO tekst pri nedostignutom gate."""
    report = _report_text(
        "synthetic",
        "base_moe",
        {"cagr": 0.10, "sharpe": 0.5, "risk_drawdown": 0.2},
        {"cagr": 0.01},
        {"passed": False, "stretch_50_reached": False},
    )
    assert "NO_GO" in report
    assert "50% CAGR stretch reached: no" in report
    assert "not a profit guarantee" in report
