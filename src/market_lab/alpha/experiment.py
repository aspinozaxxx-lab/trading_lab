"""Orkestraciya validation-selection i odnokratnogo double-holdout testa."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from market_lab.alpha.config import AlphaConfig, alpha_config_as_dict
from market_lab.alpha.models import fit_final_extra_trees, walk_forward_predictions
from market_lab.alpha.panel import MODEL_FEATURE_COLUMNS, complete_model_rows, load_panel
from market_lab.alpha.portfolio import (
    PortfolioBacktest,
    StrategySpec,
    run_portfolio_backtest,
)
from market_lab.logging_config import configure_logging
from market_lab.reporting.artifacts import ArtifactWriter, create_run_directory

LOGGER = logging.getLogger(__name__)  # Logger alpha-eksperimenta.
STRESS_MULTIPLIERS = (1.0, 2.0, 3.0)  # Scenarii uvelicheniya torgovyh izderzhek.


def _utc_end(day: object) -> pd.Timestamp:
    """Preobrazuet kalendarnyi den' v poslednyuyu UTC-nanosekundu."""
    return pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)


def _candidate_specs(config: AlphaConfig) -> list[StrategySpec]:
    """Razvorachivaet zaranee zadannyi konechnyi validation-poisk."""
    specs = [
        StrategySpec(
            name="buy_hold_equal_weight",
            kind="buy_hold",
            score_column=None,
            top_k=len(config.universe.development),
            gross_leverage=1.0,
            regime_filter=False,
        )
    ]
    for window in config.search.momentum_windows:
        for regime_filter in config.search.regime_filters:
            for top_k in config.search.top_k:
                for leverage in config.search.gross_leverages:
                    specs.append(
                        StrategySpec(
                            name=(
                                f"momentum_{window}d_top{top_k}_L{leverage:g}_"
                                f"regime{int(regime_filter)}"
                            ),
                            kind="momentum",
                            score_column=f"ret_{window}d",
                            top_k=top_k,
                            gross_leverage=leverage,
                            regime_filter=regime_filter,
                        )
                    )
    for model_name, score_column in (
        ("ridge", "prediction_ridge"),
        ("extra_trees", "prediction_extra_trees"),
    ):
        specs.append(
            StrategySpec(
                name=f"ml_{model_name}",
                kind="model",
                score_column=score_column,
                top_k=config.model.comparison_top_k,
                gross_leverage=config.model.comparison_leverage,
                regime_filter=True,
            )
        )
    return specs


def _fold_statistics(
    panel: pd.DataFrame,
    spec: StrategySpec,
    config: AlphaConfig,
) -> tuple[pd.DataFrame, float]:
    """Schitaet nezavisimye metriki i dolyu polozhitel'nyh validation-foldov."""
    rows: list[dict[str, object]] = []
    for fold_number, fold in panel.groupby("validation_fold", sort=True):
        result = run_portfolio_backtest(fold, spec, config.portfolio)
        rows.append(
            {
                "candidate": spec.name,
                "fold": int(fold_number),
                "return": result.metrics["total_return"],
                "cagr": result.metrics["annualized_return"],
                "sharpe": result.metrics["sharpe"],
                "max_drawdown": result.metrics["max_drawdown"],
            }
        )
    frame = pd.DataFrame(rows)
    positive_fraction = float((frame["return"] > 0.0).mean())
    return frame, positive_fraction


def _evaluate_validation(
    panel: pd.DataFrame,
    config: AlphaConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, PortfolioBacktest], list[StrategySpec]]:
    """Ocenivaet vse kandidaty tol'ko po obedinennoi OOS-validation."""
    rows: list[dict[str, object]] = []
    all_folds: list[pd.DataFrame] = []
    backtests: dict[str, PortfolioBacktest] = {}
    specs = _candidate_specs(config)
    for spec in specs:
        result = run_portfolio_backtest(panel, spec, config.portfolio)
        stress = run_portfolio_backtest(
            panel,
            spec,
            config.portfolio,
            cost_multiplier=config.selection.stress_cost_multiplier,
        )
        fold_frame, positive_fraction = _fold_statistics(panel, spec, config)
        all_folds.append(fold_frame)
        metrics = result.metrics
        target_met = bool(metrics["annualized_return"] >= config.selection.target_cagr)
        eligible = bool(
            target_met
            and metrics["max_drawdown"] <= config.selection.maximum_drawdown
            and metrics["sharpe"] >= config.selection.minimum_sharpe
            and positive_fraction >= config.selection.minimum_positive_fold_fraction
            and stress.metrics["annualized_return"] >= config.selection.minimum_stress_cagr
        )
        rows.append(
            {
                "candidate": spec.name,
                "kind": spec.kind,
                "validation_score": metrics["sharpe"],
                "validation_cagr": metrics["annualized_return"],
                "validation_return": metrics["total_return"],
                "validation_sharpe": metrics["sharpe"],
                "validation_max_drawdown": metrics["max_drawdown"],
                "validation_turnover": metrics["turnover"],
                "validation_trade_count": metrics["trade_count"],
                "validation_cost": metrics["total_cost"],
                "positive_fold_fraction": positive_fraction,
                "stress_cost_multiplier": config.selection.stress_cost_multiplier,
                "stress_cagr": stress.metrics["annualized_return"],
                "stress_sharpe": stress.metrics["sharpe"],
                "stress_max_drawdown": stress.metrics["max_drawdown"],
                "target_met": target_met,
                "eligible": eligible,
                "parameters": json.dumps(spec.as_dict(), sort_keys=True),
            }
        )
        backtests[spec.name] = result
    leaderboard = pd.DataFrame(rows).sort_values(
        ["eligible", "validation_score", "stress_cagr", "candidate"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )
    return leaderboard.reset_index(drop=True), pd.concat(all_folds), backtests, specs


def _select_candidate(
    leaderboard: pd.DataFrame,
    specs: list[StrategySpec],
) -> tuple[StrategySpec, bool]:
    """Vybiraet pobeditelya bez kakogo-libo dostupa k test-metrikam."""
    eligible = leaderboard.loc[leaderboard["eligible"]]
    selection_pool = eligible if not eligible.empty else leaderboard
    selected_name = str(selection_pool.iloc[0]["candidate"])
    by_name = {spec.name: spec for spec in specs}
    return by_name[selected_name], not eligible.empty


def _selection_payload(
    selected: StrategySpec,
    row: pd.Series,
    target_qualified: bool,
    config: AlphaConfig,
) -> dict[str, object]:
    """Formiruet canonical payload, kotoryi zapisyvaetsya do holdout-read."""
    core = {
        "selected_strategy": selected.as_dict(),
        "target_qualified_on_validation": target_qualified,
        "validation_metrics": {
            "cagr": float(row["validation_cagr"]),
            "sharpe": float(row["validation_sharpe"]),
            "max_drawdown": float(row["validation_max_drawdown"]),
            "stress_cagr": float(row["stress_cagr"]),
            "positive_fold_fraction": float(row["positive_fold_fraction"]),
        },
        "test_universe": config.universe.holdout,
        "test_start": config.protocol.test_start.isoformat(),
        "test_end": config.protocol.test_end.isoformat(),
        "selection_rule": "eligible_then_validation_sharpe_then_stress_cagr",
    }
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        **core,
        "selection_sha256": hashlib.sha256(canonical).hexdigest(),
        "sealed_at_utc": datetime.now(UTC).isoformat(),
    }


def _add_model_prediction(
    panel: pd.DataFrame,
    selected: StrategySpec,
    model: object,
) -> pd.DataFrame:
    """Dobavlyaet predskazanie finalnoi modeli, esli vybran ML-kandidat."""
    if selected.kind != "model" or selected.score_column is None:
        return panel
    clean = complete_model_rows(panel)
    result = panel.copy()
    prediction = model.predict(clean.loc[:, MODEL_FEATURE_COLUMNS])
    predicted = pd.Series(prediction, index=clean.index)
    result[selected.score_column] = predicted.reindex(result.index)
    return result


def _stress_table(
    panel: pd.DataFrame,
    selected: StrategySpec,
    config: AlphaConfig,
) -> pd.DataFrame:
    """Schitaet odin i tot zhe zamorozhennyi kandidat pri treh izderzhkah."""
    rows: list[dict[str, object]] = []
    for multiplier in STRESS_MULTIPLIERS:
        result = run_portfolio_backtest(panel, selected, config.portfolio, multiplier)
        rows.append({"cost_multiplier": multiplier, **result.metrics})
    return pd.DataFrame(rows)


def _period_table(
    panel: pd.DataFrame,
    selected: StrategySpec,
    config: AlphaConfig,
) -> pd.DataFrame:
    """Pokazyvaet stabil'nost' final'nogo testa po kalendarnym godam."""
    rows: list[dict[str, object]] = []
    for year, part in panel.groupby(panel["decision_date"].dt.year, sort=True):
        result = run_portfolio_backtest(part, selected, config.portfolio)
        rows.append({"year": int(year), **result.metrics})
    return pd.DataFrame(rows)


def _report_text(
    selected: StrategySpec,
    validation_metrics: dict[str, object],
    test: PortfolioBacktest | None,
    benchmark: PortfolioBacktest | None,
    target_qualified: bool,
    config: AlphaConfig,
) -> str:
    """Formiruet kratkii otchet s chestnym statusom celi i ogranicheniyami."""
    test_section = "Финальный holdout не открывался (validation-only запуск)."
    if test is not None and benchmark is not None:
        achieved = test.metrics["annualized_return"] >= config.selection.target_cagr
        test_section = (
            f"- CAGR стратегии: {test.metrics['annualized_return']:.2%}\n"
            f"- Полная доходность: {test.metrics['total_return']:.2%}\n"
            f"- Sharpe: {test.metrics['sharpe']:.3f}\n"
            f"- Max drawdown: {test.metrics['max_drawdown']:.2%}\n"
            f"- Все издержки: {test.metrics['total_cost']:.2f} RUB\n"
            f"- Buy-and-hold CAGR: {benchmark.metrics['annualized_return']:.2%}\n"
            f"- Цель 50% CAGR на holdout: {'достигнута' if achieved else 'не достигнута'}"
        )
    return (
        "# Alpha50 research report\n\n"
        "## Что зафиксировано до теста\n\n"
        f"Победитель: `{selected.name}`. Параметры: `{selected.as_dict()}`.\n\n"
        f"Validation CAGR: {validation_metrics['annualized_return']:.2%}; "
        f"Sharpe: {validation_metrics['sharpe']:.3f}; "
        f"max drawdown: {validation_metrics['max_drawdown']:.2%}. "
        f"Validation-gate 50%: {'пройден' if target_qualified else 'не пройден'}.\n\n"
        "## Финальный double holdout\n\n"
        f"{test_section}\n\n"
        "Test использует одновременно новый период и три акции, не участвовавшие в "
        "обучении или выборе правила. После чтения test автоматического повторного подбора нет.\n\n"
        "## Ограничения\n\n"
        "Это исторический исследовательский результат, а не обещание прибыли. Модель не "
        "учитывает лимиты ликвидности, margin call, дивиденды, корпоративные действия, "
        "налоги и индивидуальные брокерские требования. Плечо 2x требует реальной "
        "маржинальной доступности; в расчёте заложено 20% годового финансирования.\n"
    )


def execute_alpha_experiment(config: AlphaConfig, validation_only: bool = False) -> Path:
    """Vypolnyaet selection, fiksiruet ego i lish' zatem otkryvaet holdout."""
    run_dir = create_run_directory(config.paths.runs_dir)
    writer = ArtifactWriter(run_dir)
    configure_logging(run_dir / "run.log")
    LOGGER.info("Alpha50: zagruzka tol'ko development-universuma")
    writer.write_yaml("resolved_config.yaml", alpha_config_as_dict(config))
    development, development_manifest = load_panel(
        config,
        config.universe.development,
        _utc_end(config.protocol.validation_end),
    )
    development = development.loc[
        development["decision_date"] <= pd.Timestamp(config.protocol.validation_end)
    ]
    writer.write_frame("development_data_manifest.csv", development_manifest)
    LOGGER.info("Alpha50: walk-forward sravnenie modelei")
    model_validation = walk_forward_predictions(development, config)
    writer.write_frame("validation_folds.csv", model_validation.folds)
    leaderboard, fold_metrics, backtests, specs = _evaluate_validation(
        model_validation.predictions,
        config,
    )
    selected, target_qualified = _select_candidate(leaderboard, specs)
    selected_row = leaderboard.loc[leaderboard["candidate"] == selected.name].iloc[0]
    leaderboard["selected"] = leaderboard["candidate"].eq(selected.name)
    writer.write_frame("validation_candidates.csv", leaderboard)
    writer.write_frame("validation_fold_metrics.csv", fold_metrics)
    selection = _selection_payload(selected, selected_row, target_qualified, config)
    writer.write_json("selection_seal.json", selection)
    selected_validation = backtests[selected.name]
    writer.write_frame("validation_equity.csv", selected_validation.ledger.reset_index())
    writer.write_frame("validation_weights.csv", selected_validation.weights.reset_index())
    LOGGER.info("Alpha50: vybran %s; selection zapечатан", selected.name)
    final_model = fit_final_extra_trees(development, config)
    writer.write_model("research_extra_trees.joblib", final_model)
    importance = pd.DataFrame(
        {
            "feature": MODEL_FEATURE_COLUMNS,
            "importance": final_model.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    writer.write_frame("model_feature_importance.csv", importance)
    writer.write_json("feature_list.json", list(MODEL_FEATURE_COLUMNS))
    writer.write_json(
        "compute.json",
        {
            "selected_engine": "deterministic_rule" if selected.kind != "model" else "sklearn",
            "comparison_model": "ExtraTreesRegressor",
            "neural_network_trained": False,
            "gpu_used": False,
            "reason": "Validation rule prevzoshel tablichnye modeli; dannyh malo dlya NN.",
        },
    )
    test_result: PortfolioBacktest | None = None
    benchmark_result: PortfolioBacktest | None = None
    metrics_payload: dict[str, object] = {
        "evaluation_status": "validation_only" if validation_only else "double_holdout",
        "selection": selection,
        "validation": selected_validation.metrics,
    }
    if not validation_only:
        LOGGER.info("Alpha50: selection zafiksirovan, teper' otkryvaetsya holdout-universum")
        holdout, holdout_manifest = load_panel(
            config,
            config.universe.holdout,
            _utc_end(config.protocol.test_end),
        )
        holdout = holdout.loc[
            (holdout["decision_date"] >= pd.Timestamp(config.protocol.test_start))
            & (holdout["decision_date"] <= pd.Timestamp(config.protocol.test_end))
        ].copy()
        holdout = _add_model_prediction(holdout, selected, final_model)
        writer.write_frame("holdout_data_manifest.csv", holdout_manifest)
        test_result = run_portfolio_backtest(holdout, selected, config.portfolio)
        benchmark_spec = StrategySpec(
            name="buy_hold_equal_weight",
            kind="buy_hold",
            score_column=None,
            top_k=len(config.universe.holdout),
            gross_leverage=1.0,
            regime_filter=False,
        )
        benchmark_result = run_portfolio_backtest(holdout, benchmark_spec, config.portfolio)
        writer.write_frame("test_equity.csv", test_result.ledger.reset_index())
        writer.write_frame("test_weights.csv", test_result.weights.reset_index())
        writer.write_frame("test_cost_stress.csv", _stress_table(holdout, selected, config))
        writer.write_frame("test_year_metrics.csv", _period_table(holdout, selected, config))
        writer.write_equity_plot(
            "test_equity_curve.png",
            test_result.ledger["equity"],
            width=11,
            height=5,
            title=f"Alpha50 double holdout: {selected.name}",
        )
        metrics_payload["test"] = test_result.metrics
        metrics_payload["test_buy_hold"] = benchmark_result.metrics
        metrics_payload["target_achieved_on_test"] = bool(
            test_result.metrics["annualized_return"] >= config.selection.target_cagr
        )
    writer.write_json("metrics.json", metrics_payload)
    writer.write_text(
        "report.md",
        _report_text(
            selected,
            selected_validation.metrics,
            test_result,
            benchmark_result,
            target_qualified,
            config,
        ),
    )
    LOGGER.info("Alpha50 zavershen: %s", run_dir)
    return run_dir
