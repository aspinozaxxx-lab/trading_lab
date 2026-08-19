"""Proverki izolyacii trial i validation-sortirovki."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_lab.backtest import BacktestResult
from market_lab.config import AppConfig
from market_lab.experiments.runner import _is_validation_eligible, select_candidate_name
from market_lab.optimization import TrialOutcome, run_study
from market_lab.reporting.artifacts import sort_leaderboard


def test_failed_trial_does_not_stop_study(tmp_path: Path, app_config: AppConfig) -> None:
    """Proveryaet sohranenie prichiny FAIL i prodolzhenie poiska."""
    calls = 0

    def evaluator(_parameters: dict[str, float]) -> TrialOutcome:
        """Padaet tolko na pervom vyzove."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("namerennaia oshibka")
        return TrialOutcome(score=1.0, trade_count=10)

    optimization = app_config.optimization.model_copy(update={"n_trials": 2, "min_trades": 1})
    result = run_study(
        tmp_path / "study.sqlite3",
        "failure-isolation",
        optimization,
        42,
        evaluator,
    )
    assert result.trials["state"].tolist() == ["FAIL", "COMPLETE"]
    assert result.trials.iloc[0]["error_type"] == "RuntimeError"
    assert result.best_params is not None


def test_insufficient_trades_are_pruned(tmp_path: Path, app_config: AppConfig) -> None:
    """Proveryaet PRUNED pri narushenii minimalnogo chisla sdelok."""
    optimization = app_config.optimization.model_copy(update={"n_trials": 1, "min_trades": 5})
    result = run_study(
        tmp_path / "pruned.sqlite3",
        "pruned-trial",
        optimization,
        42,
        lambda _parameters: TrialOutcome(score=3.0, trade_count=2),
    )
    assert result.trials.iloc[0]["state"] == "PRUNED"
    assert "Nedostatochno" in result.trials.iloc[0]["prune_reason"]


def test_leaderboard_ignores_test_metrics_for_sorting() -> None:
    """Proveryaet chto ogromnyi test-return ne menyaet validation-rang."""
    frame = pd.DataFrame(
        [
            {
                "candidate": "low_validation",
                "kind": "test",
                "validation_score": 1.0,
                "validation_return": 0.1,
                "validation_sharpe": 1.0,
                "validation_calmar": 1.0,
                "validation_max_drawdown": 0.1,
                "validation_trade_count": 10,
                "validation_positive_fold_fraction": 1.0,
                "validation_recent_fold_return": 0.1,
                "validation_worst_fold_return": 0.1,
                "test_return": 100.0,
                "test_sharpe": 100.0,
                "test_calmar": 100.0,
                "test_max_drawdown": 0.0,
                "test_turnover": 0.0,
                "test_trade_count": 0,
                "test_costs": 0.0,
                "parameters": "{}",
                "eligible": True,
                "selected": False,
            },
            {
                "candidate": "high_validation",
                "kind": "test",
                "validation_score": 2.0,
                "validation_return": 0.2,
                "validation_sharpe": 2.0,
                "validation_calmar": 2.0,
                "validation_max_drawdown": 0.1,
                "validation_trade_count": 10,
                "validation_positive_fold_fraction": 1.0,
                "validation_recent_fold_return": 0.1,
                "validation_worst_fold_return": 0.1,
                "test_return": -1.0,
                "test_sharpe": -1.0,
                "test_calmar": -1.0,
                "test_max_drawdown": 1.0,
                "test_turnover": 1.0,
                "test_trade_count": 1,
                "test_costs": 1.0,
                "parameters": "{}",
                "eligible": True,
                "selected": False,
            },
        ]
    )
    sorted_frame = sort_leaderboard(frame)
    assert sorted_frame.iloc[0]["candidate"] == "high_validation"


def test_selection_gate_falls_back_to_cash() -> None:
    """Proveryaet otkaz ot torgovli kogda vse aktivnye kandidaty otkloneny."""
    frame = pd.DataFrame(
        [
            {"candidate": "weak_model", "validation_score": -0.1, "eligible": False},
            {"candidate": "cash", "validation_score": 0.0, "eligible": False},
        ]
    ).sort_values("validation_score", ascending=False)
    assert select_candidate_name(frame) == "cash"


def test_selection_gate_rejects_unstable_recent_fold(app_config: AppConfig) -> None:
    """Proveryaet barery po dole uspeshnyh fold i poslednemu periodu."""
    result = BacktestResult(
        metrics={
            "sharpe": 1.0,
            "calmar": 1.0,
            "total_return": 0.2,
            "max_drawdown": 0.1,
            "trade_count": 10,
        },
        trades=pd.DataFrame(),
        equity_curve=pd.DataFrame(),
        positions=pd.DataFrame(),
        returns=pd.Series(dtype=float),
    )
    stable = (0.1, -0.01, 0.1, 0.1, -0.01, 0.1, -0.01, 0.1)
    unstable_recent = (*stable[:-1], -0.01)
    strict_config = app_config.model_copy(
        update={
            "strategy": app_config.strategy.model_copy(
                update={
                    "selection": app_config.strategy.selection.model_copy(
                        update={"minimum_recent_fold_return": 0.0}
                    )
                }
            )
        }
    )
    assert _is_validation_eligible(result, stable, strict_config)
    assert not _is_validation_eligible(result, unstable_recent, strict_config)
