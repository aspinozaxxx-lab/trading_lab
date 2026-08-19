"""Proverki aggregate metrik i development-only pre-holdout gates."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab.sequence.daily_config import load_daily_experiment_config
from market_lab.sequence.daily_experiment import (
    REQUIRED_DEVELOPMENT_ARTIFACTS,
    _config_protocol_correspondence,
    _config_seal,
    _protocol_seal,
    aggregate_daily_returns,
    evaluate_pre_holdout_gates,
    validate_development_artifacts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren daily experiment-testov.


def _config():
    """Zagruzhaet frozen daily-config bez chteniya rynochnyh dannyh."""
    return load_daily_experiment_config(
        PROJECT_ROOT / "configs" / "sequence_5090_daily_v3.yaml"
    )


def _ledger(dates: list[str], returns: list[float]) -> pd.DataFrame:
    """Stroit minimalnyi fold-ledger dlya proverki compounding."""
    return pd.DataFrame(
        {
            "session_date": pd.to_datetime(dates),
            "net_return": returns,
            "turnover": [0.2] * len(dates),
            "trade_count": [2] * len(dates),
            "commission_cost": [10.0] * len(dates),
            "slippage_cost": [4.0] * len(dates),
            "financing_cost": [0.0] * len(dates),
            "short_borrow_cost": [1.0] * len(dates),
        }
    )


def test_aggregate_daily_returns_compounds_nonoverlapping_folds() -> None:
    """Proveryaet hronologicheskoe compounding outer daily returns."""
    combined, metrics = aggregate_daily_returns(
        {
            "fold_01": _ledger(["2022-01-10", "2022-01-11"], [0.10, -0.05]),
            "fold_02": _ledger(["2023-01-10"], [0.02]),
        },
        initial_capital=1_000_000.0,
    )
    expected = 1_000_000.0 * 1.10 * 0.95 * 1.02
    assert combined.iloc[-1]["equity"] == pytest.approx(expected)
    assert metrics["final_equity"] == pytest.approx(expected)
    assert metrics["trade_count"] == 6
    assert metrics["short_borrow_cost"] == pytest.approx(3.0)
    assert metrics["total_cost"] == pytest.approx(45.0)


def test_failed_pre_holdout_gate_is_no_go_and_keeps_holdout_untouched() -> None:
    """Proveryaet fail-closed status bez kakogo-libo holdout-loadera."""
    fold_metrics = pd.DataFrame(
        {
            "outer_ic": [-0.02, 0.01, -0.01, 0.0],
            "diagnostic_long_short_sharpe": [-1.0, 0.1, -0.5, 0.0],
            "diagnostic_long_short_execution_complete": [True] * 4,
            "diagnostic_double_cost_execution_complete": [True] * 4,
            "diagnostic_delayed_entry_execution_complete": [True] * 4,
            "diagnostic_long_short_maximum_participation": [0.001] * 4,
            "diagnostic_double_cost_maximum_participation": [0.001] * 4,
            "diagnostic_delayed_entry_maximum_participation": [0.001] * 4,
            "diagnostic_long_short_invalid_participation_count": [0] * 4,
            "diagnostic_double_cost_invalid_participation_count": [0] * 4,
            "diagnostic_delayed_entry_invalid_participation_count": [0] * 4,
        }
    )
    weak = {
        "annualized_return": -0.10,
        "sharpe": -0.5,
        "max_drawdown": 0.30,
    }
    decision = evaluate_pre_holdout_gates(
        _config(),
        fold_metrics,
        {
            "diagnostic_long_short": weak,
            "diagnostic_double_cost": weak,
            "diagnostic_delayed_entry": weak,
        },
    )
    assert decision["status"] == "NO_GO_FOR_LIVE_TRADING"
    assert decision["all_pre_holdout_checks_passed"] is False
    assert decision["holdout_accessed"] is False
    assert decision["holdout_untouched"] is True


def test_passing_pre_holdout_gate_only_allows_one_time_review() -> None:
    """Proveryaet chto pass ne stanovitsya live-trading razresheniem."""
    fold_metrics = pd.DataFrame(
        {
            "outer_ic": [0.04, 0.05, 0.02, 0.06],
            "diagnostic_long_short_sharpe": [0.9, 1.0, 0.8, 1.1],
            "diagnostic_long_short_execution_complete": [True] * 4,
            "diagnostic_double_cost_execution_complete": [True] * 4,
            "diagnostic_delayed_entry_execution_complete": [True] * 4,
            "diagnostic_long_short_maximum_participation": [0.001] * 4,
            "diagnostic_double_cost_maximum_participation": [0.002] * 4,
            "diagnostic_delayed_entry_maximum_participation": [0.003] * 4,
            "diagnostic_long_short_invalid_participation_count": [0] * 4,
            "diagnostic_double_cost_invalid_participation_count": [0] * 4,
            "diagnostic_delayed_entry_invalid_participation_count": [0] * 4,
        }
    )
    diagnostic = {"annualized_return": 0.20, "sharpe": 1.2, "max_drawdown": 0.10}
    stress = {"annualized_return": 0.02, "sharpe": 0.2, "max_drawdown": 0.15}
    diagnostic_decision = evaluate_pre_holdout_gates(
        _config(),
        fold_metrics,
        {
            "diagnostic_long_short": diagnostic,
            "diagnostic_double_cost": stress,
            "diagnostic_delayed_entry": stress,
        },
    )
    assert diagnostic_decision["status"] == "NO_GO_FOR_LIVE_TRADING"
    decision = evaluate_pre_holdout_gates(
        _config(),
        fold_metrics,
        {
            "diagnostic_long_short": diagnostic,
            "diagnostic_double_cost": stress,
            "diagnostic_delayed_entry": stress,
        },
        protocol_conformity={"hypothetical_primary": True},
        config_protocol_correspondence={"hypothetical_sealed_config": True},
    )
    assert decision["status"] == "READY_FOR_ONE_TIME_HOLDOUT"
    assert decision["holdout_accessed"] is False
    assert decision["holdout_untouched"] is True


def test_frozen_config_seal_rejects_runtime_parameter_change() -> None:
    """Proveryaet cryptographic bind protiv podmeny top-k v runtime-config."""
    config = _config()
    _config_seal(config, PROJECT_ROOT)
    changed = config.model_copy(
        update={"portfolio": config.portfolio.model_copy(update={"top_k": 2})}
    )
    with pytest.raises(ValueError, match="Runtime daily config"):
        _config_seal(changed, PROJECT_ROOT)


def test_sealed_config_corresponds_to_verified_protocol() -> None:
    """Proveryaet semanticheskuyu svyaz config s hash-proverennym protocol."""
    config = _config()
    seal = _protocol_seal(PROJECT_ROOT)
    checks = _config_protocol_correspondence(config, seal)
    assert checks
    assert all(checks.values())


def test_required_development_artifact_set_is_enforced(tmp_path: Path) -> None:
    """Proveryaet fail-closed kontrol polnogo atomarnogo artifact-seta."""
    for name in REQUIRED_DEVELOPMENT_ARTIFACTS:
        (tmp_path / name).write_bytes(b"test")
    validate_development_artifacts(tmp_path)
    (tmp_path / "report.md").unlink()
    with pytest.raises(RuntimeError, match="report.md"):
        validate_development_artifacts(tmp_path)
