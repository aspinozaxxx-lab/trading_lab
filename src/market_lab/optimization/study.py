"""Izolirovannyi zapusk Optuna s sohraneniem prichin oshibok."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import optuna
import pandas as pd

from market_lab.config import OptimizationConfig, SearchSpace

LOGGER = logging.getLogger(__name__)  # Logger optimizatora.


@dataclass(frozen=True)
class TrialOutcome:
    """Hranit validation-score i chislo sdelok odnogo trial."""

    score: float
    trade_count: int


@dataclass(frozen=True)
class StudyResult:
    """Hranit study, tablicu trials i parametry luchshego trial."""

    study: optuna.Study
    trials: pd.DataFrame
    best_params: dict[str, float] | None


def _suggest_value(trial: optuna.Trial, name: str, space: SearchSpace) -> float:
    """Preobrazuet deklarativnyi diapazon v vyzov Optuna suggest."""
    if space.kind == "int":
        return float(trial.suggest_int(name, int(space.low), int(space.high), log=space.log))
    return float(trial.suggest_float(name, space.low, space.high, log=space.log))


def _trial_table(study: optuna.Study) -> pd.DataFrame:
    """Stroit stabilnuyu tablicu vseh COMPLETE, PRUNED i FAIL trials."""
    rows: list[dict[str, Any]] = []
    for trial in study.trials:
        resolved_params = trial.user_attrs.get("resolved_params", trial.params)
        rows.append(
            {
                "number": trial.number,
                "state": trial.state.name,
                "validation_score": trial.value,
                "trade_count": trial.user_attrs.get("trade_count"),
                "params": json.dumps(resolved_params, ensure_ascii=False, sort_keys=True),
                "error_type": trial.user_attrs.get("error_type"),
                "error_message": trial.user_attrs.get("error_message"),
                "prune_reason": trial.user_attrs.get("prune_reason"),
                "datetime_start": trial.datetime_start,
                "datetime_complete": trial.datetime_complete,
                "duration_seconds": (
                    trial.duration.total_seconds() if trial.duration is not None else None
                ),
            }
        )
    return pd.DataFrame(rows)


def run_study(
    database_path: Path,
    study_name: str,
    config: OptimizationConfig,
    seed: int,
    evaluator: Callable[[dict[str, float]], TrialOutcome],
    fixed_params: dict[str, float] | None = None,
) -> StudyResult:
    """Zapuskaet study, izoliruet oshibki i vozvrashchaet vse trials."""
    storage = f"sqlite:///{database_path.resolve().as_posix()}"
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        sampler=sampler,
        direction="maximize",
        load_if_exists=False,
    )

    def objective(trial: optuna.Trial) -> float:
        """Vychislyaet tolko validation objective i annotiruet trial."""
        if fixed_params is None:
            parameters = {
                name: _suggest_value(trial, name, space)
                for name, space in config.search_space.items()
            }
        else:
            parameters = {name: float(value) for name, value in fixed_params.items()}
        trial.set_user_attr("resolved_params", parameters)
        try:
            outcome = evaluator(parameters)
            trial.set_user_attr("trade_count", outcome.trade_count)
            if outcome.trade_count < config.min_trades:
                reason = (
                    f"Nedostatochno sdelok: {outcome.trade_count} < {config.min_trades}"
                )
                trial.set_user_attr("prune_reason", reason)
                raise optuna.TrialPruned(reason)
            if not math.isfinite(outcome.score):
                raise ValueError("Objective ne yavlyaetsya konechnym chislom")
            return float(outcome.score)
        except optuna.TrialPruned:
            raise
        except Exception as error:
            trial.set_user_attr("error_type", type(error).__name__)
            trial.set_user_attr("error_message", str(error))
            LOGGER.exception("Trial %s zavershilsya oshibkoi", trial.number)
            raise

    trial_count = 1 if fixed_params is not None else config.n_trials
    study.optimize(objective, n_trials=trial_count, n_jobs=1, catch=(Exception,))
    completed = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    best_params: dict[str, float] | None = None
    if completed:
        raw_params = study.best_trial.user_attrs.get("resolved_params", study.best_trial.params)
        best_params = {name: float(value) for name, value in raw_params.items()}
    return StudyResult(study=study, trials=_trial_table(study), best_params=best_params)
