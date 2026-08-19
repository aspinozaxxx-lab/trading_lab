"""Skvoznoi vosproizvodimyi konveier eksperimenta."""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from market_lab.backtest.engine import BacktestResult, aggregate_backtests, run_backtest
from market_lab.config import AppConfig, config_as_dict
from market_lab.data import FixtureSource, MoexIssSource, load_cached_data, save_market_data
from market_lab.features import MarketFeatureBuilder, make_direction_labels
from market_lab.logging_config import configure_logging
from market_lab.models import LogisticStrategy
from market_lab.optimization import TrialOutcome, run_study
from market_lab.reporting.artifacts import (
    ArtifactWriter,
    create_run_directory,
    format_parameters,
    sort_leaderboard,
)
from market_lab.strategies import (
    buy_and_hold_targets,
    hysteresis_trend_targets,
    long_union_targets,
    regime_trend_targets,
    sma_crossover_targets,
)
from market_lab.validation import WalkForwardPlan, make_walk_forward_plan

LOGGER = logging.getLogger(__name__)  # Logger eksperimentalnogo konveiera.
ExperimentMode = Literal["run", "optimize", "demo"]


@dataclass(frozen=True)
class CandidateEvaluation:
    """Hranit validation i test rezultaty odnogo kandidata."""

    validation: BacktestResult
    validation_fold_returns: tuple[float, ...]
    test: BacktestResult
    parameters: dict[str, Any]


def seed_everything(seed: int) -> None:
    """Fiksiruet dostupnye istochniki sluchainosti i odin CPU-potok."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    random.seed(seed)
    np.random.seed(seed)


def download_data(config: AppConfig) -> Path:
    """Zagruzhaet MOEX i sohranyaet syroi i normalizovannyi kesh."""
    if config.data.source != "moex":
        raise ValueError("Komanda download podderzhivaet istochnik moex")
    bundle = MoexIssSource(config.data).load()
    target = save_market_data(config, bundle)
    LOGGER.info("Sohraneno %s svechei v %s", len(bundle.frame), target)
    return target


def _objective_score(result: BacktestResult, config: AppConfig) -> float:
    """Izvlekaet skalyarnuyu validation-metriku iz rezultata."""
    metric_name = "sharpe" if config.optimization.objective == "validation_sharpe" else "calmar"
    return float(result.metrics[metric_name])


def _run_segments(
    frame: pd.DataFrame,
    targets: pd.Series,
    segments: list[np.ndarray],
    config: AppConfig,
) -> list[BacktestResult]:
    """Zapuskaet nezavisimye backtesty po ukazannym OOS-segmentam."""
    return [
        run_backtest(
            frame.iloc[segment],
            targets.iloc[segment],
            config.portfolio,
            config.report.annualization_factor,
        )
        for segment in segments
    ]


def _aggregate_results(
    results: list[BacktestResult],
    config: AppConfig,
) -> BacktestResult:
    """Agregiruet spisok OOS-rezultatov s edinym nachalnym kapitalom."""
    return aggregate_backtests(
        results,
        initial_capital=config.portfolio.initial_capital,
        annualization_factor=config.report.annualization_factor,
    )


def _fold_returns(results: list[BacktestResult]) -> tuple[float, ...]:
    """Izvlekaet dohodnosti fold v stabilnom hronologicheskom poryadke."""
    return tuple(float(result.metrics["total_return"]) for result in results)


def _run_ml_validation_folds(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    labels: pd.Series,
    plan: WalkForwardPlan,
    parameters: dict[str, float],
    config: AppConfig,
    overlay_targets: pd.Series | None = None,
) -> list[BacktestResult]:
    """Obuchaet model na kazhdom fold i opcionalno dobavlyaet trend-signal."""
    fold_results: list[BacktestResult] = []
    for fold in plan.folds:
        model = LogisticStrategy(
            c_value=parameters["C"],
            threshold=parameters["threshold"],
            allow_short=config.portfolio.allow_short,
            seed=config.seed,
        )
        model.fit(features.iloc[fold.train], labels.iloc[fold.train])
        fold_features = features.iloc[fold.validation]
        targets = model.predict_targets(fold_features)
        if overlay_targets is not None:
            targets = long_union_targets(
                targets,
                overlay_targets.iloc[fold.validation],
            )
        fold_results.append(
            run_backtest(
                frame.iloc[fold.validation],
                targets,
                config.portfolio,
                config.report.annualization_factor,
            )
        )
    return fold_results


def _evaluate_ml_validation(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    labels: pd.Series,
    plan: WalkForwardPlan,
    parameters: dict[str, float],
    config: AppConfig,
    overlay_targets: pd.Series | None = None,
) -> BacktestResult:
    """Agregiruet expanding validation modeli ili ee trenda-gibrida."""
    results = _run_ml_validation_folds(
        frame,
        features,
        labels,
        plan,
        parameters,
        config,
        overlay_targets,
    )
    return _aggregate_results(results, config)


def _fit_and_test_ml(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    labels: pd.Series,
    plan: WalkForwardPlan,
    parameters: dict[str, float],
    config: AppConfig,
) -> tuple[LogisticStrategy, BacktestResult]:
    """Pereobuchaet luchshuyu model na pre-test i odin raz ocenivaet test."""
    model = LogisticStrategy(
        c_value=parameters["C"],
        threshold=parameters["threshold"],
        allow_short=config.portfolio.allow_short,
        seed=config.seed,
    )
    model.fit(features.iloc[plan.refit], labels.iloc[plan.refit])
    test_features = features.iloc[plan.test]
    targets = model.predict_targets(test_features)
    result = run_backtest(
        frame.iloc[plan.test],
        targets,
        config.portfolio,
        config.report.annualization_factor,
    )
    return model, result


def _run_rule_validation_folds(
    frame: pd.DataFrame,
    targets: pd.Series,
    plan: WalkForwardPlan,
    config: AppConfig,
) -> list[BacktestResult]:
    """Ocenivaet fiksirovannoe pravilo po otdelnym validation-foldam."""
    return _run_segments(
        frame,
        targets,
        [fold.validation for fold in plan.folds],
        config,
    )


def _evaluate_rule_test(
    frame: pd.DataFrame,
    targets: pd.Series,
    plan: WalkForwardPlan,
    config: AppConfig,
) -> BacktestResult:
    """Ocenivaet ran'she zafiksirovannoe pravilo tolko na test."""
    return run_backtest(
        frame.iloc[plan.test],
        targets.iloc[plan.test],
        config.portfolio,
        config.report.annualization_factor,
    )


def _is_validation_eligible(
    result: BacktestResult,
    fold_returns: tuple[float, ...],
    config: AppConfig,
) -> bool:
    """Proveryaet vse validation-barery bez obrashcheniya k test-metrikam."""
    if not fold_returns:
        return False
    validation_metrics = result.metrics
    selection = config.strategy.selection
    positive_fraction = sum(value > 0.0 for value in fold_returns) / len(fold_returns)
    return bool(
        _objective_score(result, config) > selection.minimum_validation_score
        and float(validation_metrics["total_return"])
        > selection.minimum_validation_return
        and float(validation_metrics["max_drawdown"])
        <= selection.maximum_validation_drawdown
        and int(validation_metrics["trade_count"])
        >= config.optimization.min_trades
        and int(validation_metrics["trade_count"])
        <= selection.maximum_validation_trade_count
        and positive_fraction >= selection.minimum_positive_fold_fraction
        and fold_returns[-1] > selection.minimum_recent_fold_return
    )


def _leaderboard_row(
    candidate: str,
    kind: str,
    evaluation: CandidateEvaluation,
    config: AppConfig,
) -> dict[str, Any]:
    """Preobrazuet kandidata v publichnuyu stroku leaderboard."""
    validation_metrics = evaluation.validation.metrics
    test_metrics = evaluation.test.metrics
    validation_score = _objective_score(evaluation.validation, config)
    positive_fraction = sum(
        value > 0.0 for value in evaluation.validation_fold_returns
    ) / len(evaluation.validation_fold_returns)
    return {
        "candidate": candidate,
        "kind": kind,
        "validation_score": validation_score,
        "validation_return": validation_metrics["total_return"],
        "validation_sharpe": validation_metrics["sharpe"],
        "validation_calmar": validation_metrics["calmar"],
        "validation_max_drawdown": validation_metrics["max_drawdown"],
        "validation_trade_count": validation_metrics["trade_count"],
        "validation_positive_fold_fraction": positive_fraction,
        "validation_recent_fold_return": evaluation.validation_fold_returns[-1],
        "validation_worst_fold_return": min(evaluation.validation_fold_returns),
        "test_return": test_metrics["total_return"],
        "test_sharpe": test_metrics["sharpe"],
        "test_calmar": test_metrics["calmar"],
        "test_max_drawdown": test_metrics["max_drawdown"],
        "test_turnover": test_metrics["turnover"],
        "test_trade_count": test_metrics["trade_count"],
        "test_costs": test_metrics["total_cost"],
        "parameters": format_parameters(evaluation.parameters),
        "eligible": _is_validation_eligible(
            evaluation.validation,
            evaluation.validation_fold_returns,
            config,
        ),
        "selected": False,
    }


def select_candidate_name(leaderboard: pd.DataFrame) -> str:
    """Vybiraet pervogo dopushchennogo kandidata ili bezopasnyi cash."""
    eligible = leaderboard.loc[leaderboard["eligible"].astype(bool)]
    if eligible.empty:
        return "cash"
    return str(eligible.iloc[0]["candidate"])


def _build_report(
    run_id: str,
    mode: ExperimentMode,
    offline: bool,
    leaderboard: pd.DataFrame,
    metrics: dict[str, Any],
) -> str:
    """Formiruet kratkii tekstovyi otchet bez investicionnyh zayavlenii."""
    winner = str(metrics["selected_candidate"])
    score = float(metrics["selected_validation_score"])
    test_return = float(metrics["selected_test_metrics"]["total_return"])
    fold_fraction = float(metrics["selected_positive_fold_fraction"])
    recent_return = float(metrics["selected_recent_fold_return"])
    evaluation_status = str(metrics["evaluation_status"])
    accepted = "yes" if metrics["selection_accepted"] else "no"
    evaluation_warning = (
        "\nВажно: test-период уже использовался при выборе правила, поэтому "
        "его метрики являются исследовательскими, а не независимым holdout.\n"
        if evaluation_status == "post_selection_exploratory"
        else ""
    )
    return (
        f"# Отчёт Market Lab\n\n"
        f"- Run ID: `{run_id}`\n"
        f"- Режим: `{mode}`\n"
        f"- Источник: `{'fixture' if offline else 'moex/cache'}`\n"
        f"- Objective: `{metrics['objective']}`\n"
        f"- Статус оценки: `{evaluation_status}`\n"
        f"- Выбран по validation: `{winner}` ({score:.6f})\n"
        f"- Validation-gate пройден: `{accepted}`\n"
        f"- Доля положительных validation-fold: `{fold_fraction:.2%}`\n"
        f"- Доходность последнего validation-fold: `{recent_return:.6%}`\n"
        f"- Test return выбранного кандидата: `{test_return:.6%}`\n"
        f"- Лучший ML trial: `{metrics['best_trial_number']}`\n"
        f"- Число trials: `{metrics['trial_count']}`\n\n"
        "Test-метрики не участвуют в сортировке или validation-gate. "
        "Результаты предназначены для исследования и не являются инвестиционной рекомендацией.\n"
        f"{evaluation_warning}"
    )


def execute_experiment(
    config: AppConfig,
    mode: ExperimentMode,
    offline: bool = False,
) -> Path:
    """Vypolnyaet polnyi konveier i vozvrashchaet katalog artefaktov."""
    seed_everything(config.seed)
    run_dir = create_run_directory(config.paths.runs_dir)
    configure_logging(run_dir / "run.log")
    writer = ArtifactWriter(run_dir)
    writer.write_yaml("resolved_config.yaml", config_as_dict(config))
    writer.write_json(
        "seed.json",
        {
            "seed": config.seed,
            "python_hash_seed": os.environ["PYTHONHASHSEED"],
            "omp_num_threads": os.environ["OMP_NUM_THREADS"],
            "numpy_seed": config.seed,
            "optuna_sampler": "TPESampler",
        },
    )
    LOGGER.info("Nachat eksperiment %s v %s", mode, run_dir)
    if offline or config.data.source == "fixture":
        bundle = FixtureSource(config.data).load()
    elif mode == "demo":
        bundle = MoexIssSource(config.data).load()
        save_market_data(config, bundle)
    else:
        bundle = load_cached_data(config)
    frame = bundle.frame
    plan = make_walk_forward_plan(len(frame), config.validation)
    development_end = int(plan.test[0])
    development_frame = frame.iloc[:development_end]
    feature_builder = MarketFeatureBuilder(config.features)
    features = feature_builder.build(development_frame)
    labels = make_direction_labels(development_frame)
    hybrid_trend_parameters = {
        "sma_window": config.strategy.hybrid_trend.sma_window,
        "momentum_window": config.strategy.hybrid_trend.momentum_window,
        "entry_band": config.strategy.hybrid_trend.entry_band,
    }
    hybrid_development_trend = regime_trend_targets(
        development_frame["close"],
        **hybrid_trend_parameters,
    )
    optimization_overlay = hybrid_development_trend

    def evaluator(parameters: dict[str, float]) -> TrialOutcome:
        """Ocenivaet odin nabor parametrov tolko na walk-forward validation."""
        result = _evaluate_ml_validation(
            frame,
            features,
            labels,
            plan,
            parameters,
            config,
            optimization_overlay,
        )
        return TrialOutcome(
            score=_objective_score(result, config),
            trade_count=int(result.metrics["trade_count"]),
        )

    fixed = config.strategy.parameters if mode == "run" else None
    study_result = run_study(
        database_path=run_dir / "study.sqlite3",
        study_name=run_dir.name,
        config=config.optimization,
        seed=config.seed,
        evaluator=evaluator,
        fixed_params=fixed,
    )
    writer.write_frame("trials.csv", study_result.trials)
    if study_result.best_params is None:
        writer.write_json(
            "metrics.json",
            {
                "status": "failed",
                "reason": "Net zavershennyh trials",
                "trial_count": len(study_result.trials),
            },
        )
        raise RuntimeError(f"V {run_dir} net uspeshnyh Optuna trials")
    best_params = study_result.best_params
    optimized_fold_results = _run_ml_validation_folds(
        frame,
        features,
        labels,
        plan,
        best_params,
        config,
        optimization_overlay,
    )
    best_validation = _aggregate_results(optimized_fold_results, config)
    pure_ml_fold_results = _run_ml_validation_folds(
        frame,
        features,
        labels,
        plan,
        best_params,
        config,
    )
    pure_ml_validation = _aggregate_results(pure_ml_fold_results, config)
    sma_parameters = {
        "fast_window": config.strategy.baselines.sma_fast,
        "slow_window": config.strategy.baselines.sma_slow,
    }
    regime_parameters = {
        "sma_window": config.strategy.regime_trend.sma_window,
        "momentum_window": config.strategy.regime_trend.momentum_window,
        "entry_band": config.strategy.regime_trend.entry_band,
    }
    robust_parameters = {
        "sma_window": config.strategy.robust_trend.sma_window,
        "momentum_window": config.strategy.robust_trend.momentum_window,
        "entry_band": config.strategy.robust_trend.entry_band,
        "exit_band": config.strategy.robust_trend.exit_band,
    }
    hybrid_parameters = {**best_params, **hybrid_trend_parameters}
    parameters_by_candidate: dict[str, dict[str, Any]] = {
        "buy_and_hold": {"position": 1.0},
        "sma_crossover": sma_parameters,
        "logistic_regression": best_params,
        "hybrid_trend_logistic": hybrid_parameters,
        "regime_trend": regime_parameters,
        "robust_trend": robust_parameters,
        "cash": {"position": 0.0},
    }
    kinds_by_candidate = {
        "buy_and_hold": "baseline",
        "sma_crossover": "baseline",
        "logistic_regression": "model_component",
        "hybrid_trend_logistic": "optimized",
        "regime_trend": "rule",
        "robust_trend": "rule",
        "cash": "safety",
    }
    development_targets = {
        "buy_and_hold": buy_and_hold_targets(development_frame.index),
        "sma_crossover": sma_crossover_targets(
            development_frame["close"],
            fast_window=config.strategy.baselines.sma_fast,
            slow_window=config.strategy.baselines.sma_slow,
            allow_short=config.portfolio.allow_short,
        ),
        "regime_trend": regime_trend_targets(
            development_frame["close"],
            sma_window=config.strategy.regime_trend.sma_window,
            momentum_window=config.strategy.regime_trend.momentum_window,
            entry_band=config.strategy.regime_trend.entry_band,
        ),
        "robust_trend": hysteresis_trend_targets(
            development_frame["close"],
            **robust_parameters,
        ),
        "cash": pd.Series(
            0.0,
            index=development_frame.index,
            name="target_position",
        ),
    }
    validation_fold_results = {
        "hybrid_trend_logistic": optimized_fold_results,
        "logistic_regression": pure_ml_fold_results,
    }
    validation_fold_results.update(
        {
            candidate: _run_rule_validation_folds(frame, targets, plan, config)
            for candidate, targets in development_targets.items()
        }
    )
    validation_results = {
        candidate: _aggregate_results(results, config)
        for candidate, results in validation_fold_results.items()
    }
    validation_fold_returns = {
        candidate: _fold_returns(results)
        for candidate, results in validation_fold_results.items()
    }
    selection_frame = pd.DataFrame(
        [
            {
                "candidate": candidate,
                "validation_score": _objective_score(result, config),
                "eligible": _is_validation_eligible(
                    result,
                    validation_fold_returns[candidate],
                    config,
                ),
            }
            for candidate, result in validation_results.items()
        ]
    ).sort_values(
        by=["validation_score", "candidate"],
        ascending=[False, True],
        na_position="last",
        kind="mergesort",
    )
    selected_name = select_candidate_name(selection_frame)
    selected_validation = validation_results[selected_name]
    writer.write_json(
        "selected_strategy.json",
        {
            "candidate": selected_name,
            "parameters": parameters_by_candidate[selected_name],
            "accepted": selected_name != "cash",
            "selection_metric": config.optimization.objective,
            "validation_score": _objective_score(selected_validation, config),
            "validation_fold_returns": validation_fold_returns[selected_name],
        },
    )
    LOGGER.info("Strategiya %s zafiksirovana do ocenki test", selected_name)

    full_features = feature_builder.build(frame)
    best_model, best_test = _fit_and_test_ml(
        frame, full_features, labels, plan, best_params, config
    )
    full_hybrid_trend = regime_trend_targets(
        frame["close"],
        **hybrid_trend_parameters,
    )
    test_ml_targets = best_model.predict_targets(full_features.iloc[plan.test])
    test_hybrid_targets = long_union_targets(
        test_ml_targets,
        full_hybrid_trend.iloc[plan.test],
    )
    hybrid_test = run_backtest(
        frame.iloc[plan.test],
        test_hybrid_targets,
        config.portfolio,
        config.report.annualization_factor,
    )
    full_targets = {
        "buy_and_hold": buy_and_hold_targets(frame.index),
        "sma_crossover": sma_crossover_targets(
            frame["close"],
            fast_window=config.strategy.baselines.sma_fast,
            slow_window=config.strategy.baselines.sma_slow,
            allow_short=config.portfolio.allow_short,
        ),
        "regime_trend": regime_trend_targets(
            frame["close"],
            sma_window=config.strategy.regime_trend.sma_window,
            momentum_window=config.strategy.regime_trend.momentum_window,
            entry_band=config.strategy.regime_trend.entry_band,
        ),
        "robust_trend": hysteresis_trend_targets(
            frame["close"],
            **robust_parameters,
        ),
        "cash": pd.Series(0.0, index=frame.index, name="target_position"),
    }
    test_results = {
        "hybrid_trend_logistic": hybrid_test,
        "logistic_regression": best_test,
    }
    test_results.update(
        {
            candidate: _evaluate_rule_test(frame, targets, plan, config)
            for candidate, targets in full_targets.items()
        }
    )
    evaluations = {
        candidate: CandidateEvaluation(
            validation=validation_results[candidate],
            validation_fold_returns=validation_fold_returns[candidate],
            test=test_results[candidate],
            parameters=parameters_by_candidate[candidate],
        )
        for candidate in validation_results
    }
    leaderboard = sort_leaderboard(
        pd.DataFrame(
            [
                _leaderboard_row(
                    candidate,
                    kinds_by_candidate[candidate],
                    evaluation,
                    config,
                )
                for candidate, evaluation in evaluations.items()
            ]
        )
    )
    leaderboard.loc[leaderboard["candidate"] == selected_name, "selected"] = True
    selected_evaluation = evaluations[selected_name]
    best_trial_number = study_result.study.best_trial.number
    metrics = {
        "status": "complete",
        "run_id": run_dir.name,
        "mode": mode,
        "offline": offline,
        "evaluation_status": config.report.evaluation_status,
        "objective": config.optimization.objective,
        "best_trial_number": best_trial_number,
        "best_trial_validation_score": _objective_score(best_validation, config),
        "best_trial_validation_metrics": best_validation.metrics,
        "best_trial_test_metrics": hybrid_test.metrics,
        "best_ml_validation_score": _objective_score(pure_ml_validation, config),
        "best_ml_validation_metrics": pure_ml_validation.metrics,
        "best_ml_test_metrics": best_test.metrics,
        "selected_candidate": selected_name,
        "selection_accepted": selected_name != "cash",
        "selected_validation_score": _objective_score(selected_evaluation.validation, config),
        "selected_validation_metrics": selected_evaluation.validation.metrics,
        "selected_validation_fold_returns": selected_evaluation.validation_fold_returns,
        "selected_positive_fold_fraction": sum(
            value > 0.0 for value in selected_evaluation.validation_fold_returns
        )
        / len(selected_evaluation.validation_fold_returns),
        "selected_recent_fold_return": selected_evaluation.validation_fold_returns[-1],
        "selected_test_metrics": selected_evaluation.test.metrics,
        "best_validation_score": _objective_score(selected_evaluation.validation, config),
        "best_validation_metrics": selected_evaluation.validation.metrics,
        "best_test_metrics": selected_evaluation.test.metrics,
        "leaderboard_winner": leaderboard.iloc[0]["candidate"],
        "trial_count": len(study_result.trials),
        "data": bundle.metadata,
    }
    writer.write_json("metrics.json", metrics)
    writer.write_frame("leaderboard.csv", leaderboard)
    writer.write_frame("trades.csv", selected_evaluation.test.trades)
    writer.write_frame("equity_curve.csv", selected_evaluation.test.equity_curve, index=True)
    writer.write_frame("target_positions.csv", selected_evaluation.test.positions, index=True)
    writer.write_json("best_trial_params.json", best_params)
    writer.write_model("model.joblib", best_model)
    writer.write_json("feature_list.json", config.features.names)
    writer.write_text(
        "report.md",
        _build_report(run_dir.name, mode, offline, leaderboard, metrics),
    )
    writer.write_equity_plot(
        "equity_curve.png",
        selected_evaluation.test.equity_curve["equity"],
        width=config.report.plot_width,
        height=config.report.plot_height,
        title=f"Equity curve: selected {selected_name}",
    )
    LOGGER.info("Eksperiment zavershen; artefakty: %s", run_dir)
    return run_dir
