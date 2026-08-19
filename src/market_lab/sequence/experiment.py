"""Zapechatannyi end-to-end GPU-eksperiment causal-TCN."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from market_lab.logging_config import configure_logging
from market_lab.reporting.artifacts import ArtifactWriter, create_run_directory
from market_lab.sequence.backtest import (
    IntradayBacktest,
    IntradayStrategySpec,
    evaluate_strategy,
    validation_objective,
)
from market_lab.sequence.config import (
    SequenceExperimentConfig,
    sequence_config_as_dict,
)
from market_lab.sequence.dataset import (
    SequenceSamples,
    build_sequence_store,
    load_sequence_panel,
    robust_target_scale,
    select_sequence_samples,
)
from market_lab.sequence.features import FEATURE_COLUMNS, fit_feature_scaler
from market_lab.sequence.model import CausalTCN, model_architecture
from market_lab.sequence.training import (
    fit_fixed_epochs,
    fit_with_early_stopping,
    mean_cross_section_ic,
    predict_sequence_scores,
)

LOGGER = logging.getLogger(__name__)  # Logger polnogo sequence-eksperimenta.
COST_STRESS_MULTIPLIERS = (1.0, 2.0, 3.0)  # Fiksirovannye stress-mnozhiteli izderzhek.


def _prediction_frame(samples: SequenceSamples, predictions: np.ndarray) -> pd.DataFrame:
    """Obedinyaet audit-metadannye s prognozom v ishodnom poryadke."""
    if len(samples) != len(predictions):
        raise ValueError("Chislo TCN-prognozov ne sovpadaet s vyborkoi")
    frame = samples.metadata.copy()
    frame["prediction"] = predictions
    return frame


def _candidate_specs(config: SequenceExperimentConfig) -> list[IntradayStrategySpec]:
    """Stroit konechnyi validation-search bez test-zavisimyh variantov."""
    specs: list[IntradayStrategySpec] = []
    candidates = product(
        config.portfolio.top_k_candidates,
        config.portfolio.minimum_score_bps_candidates,
        config.portfolio.keep_rank_candidates,
        config.portfolio.position_mode_candidates,
    )
    for top_k, minimum_bps, keep_rank, position_mode in candidates:
        regime_filters = (
            [False]
            if position_mode == "long_short"
            else config.portfolio.regime_filter_candidates
        )
        for regime_filter in regime_filters:
            name = (
                f"tcn_{position_mode}_k{top_k}_min{minimum_bps:.0f}bps_"
                f"keep{keep_rank}_regime{int(regime_filter)}"
            )
            specs.append(
                IntradayStrategySpec(
                    name=name,
                    top_k=top_k,
                    minimum_score=minimum_bps / 10_000.0,
                    keep_rank=keep_rank,
                    regime_filter=regime_filter,
                    leverage=config.portfolio.core_leverage,
                    position_mode=position_mode,
                )
            )
    return specs


def _validation_search(
    predictions: pd.DataFrame,
    config: SequenceExperimentConfig,
) -> tuple[pd.DataFrame, IntradayStrategySpec, IntradayBacktest]:
    """Ocenivaet TCN-kandidaty i baseline tol'ko na validation-periode."""
    rows: list[dict[str, object]] = []
    results: dict[str, IntradayBacktest] = {}
    specs = _candidate_specs(config)
    baseline_specs = [
        IntradayStrategySpec(
            name="momentum_24bar_top1",
            top_k=1,
            minimum_score=0.0,
            keep_rank=3,
            regime_filter=True,
            leverage=config.portfolio.core_leverage,
            score_column="momentum_score",
        ),
        IntradayStrategySpec(
            name="equal_weight_all",
            top_k=len(config.universe.development),
            minimum_score=0.0,
            keep_rank=len(config.universe.development),
            regime_filter=False,
            leverage=config.portfolio.core_leverage,
            score_column="equal_score",
        ),
    ]
    evaluated = predictions.copy()
    evaluated["equal_score"] = 1.0
    for spec in [*specs, *baseline_specs]:
        result = evaluate_strategy(evaluated, spec, config.portfolio)
        results[spec.name] = result
        eligible = result.metrics["trade_count"] >= config.portfolio.minimum_trades
        score = validation_objective(result) if eligible else -np.inf
        rows.append(
            {
                "candidate": spec.name,
                "kind": "tcn" if spec in specs else "baseline",
                "validation_score": score,
                "eligible": eligible,
                **result.metrics,
                "parameters": json.dumps(spec.as_dict(), sort_keys=True),
            }
        )
    leaderboard = pd.DataFrame(rows).sort_values(
        ["validation_score", "candidate"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    tcn_rows = leaderboard.loc[(leaderboard["kind"] == "tcn") & leaderboard["eligible"]]
    if tcn_rows.empty:
        raise RuntimeError("Ni odin TCN-kandidat ne proshel minimum_trades")
    selected_name = str(tcn_rows.iloc[0]["candidate"])
    selected = next(spec for spec in specs if spec.name == selected_name)
    leaderboard["selected"] = leaderboard["candidate"].eq(selected_name)
    return leaderboard, selected, results[selected_name]


def _selection_seal(
    config: SequenceExperimentConfig,
    selected: IntradayStrategySpec,
    validation_result: IntradayBacktest,
    best_epoch: int,
    validation_ic: float,
) -> dict[str, object]:
    """Fiksiruet vse resheniya posle strategy-validation, do otkrytiya testov."""
    core = {
        "architecture": config.model.model_dump(mode="json"),
        "strategy": selected.as_dict(),
        "best_epoch": best_epoch,
        "validation_ic": validation_ic,
        "validation_metrics": validation_result.metrics,
        "development_universe": config.universe.development,
        "holdout_universe": config.universe.holdout,
        "strategy_validation_period": [
            config.protocol.calibration_start.isoformat(),
            config.protocol.calibration_end.isoformat(),
        ],
        "test_period": [
            config.protocol.test_start.isoformat(),
            config.protocol.test_end.isoformat(),
        ],
        "model_validation_end": config.protocol.validation_end.isoformat(),
        "selection_data_end": config.protocol.calibration_end.isoformat(),
        "evaluation_status": "post_diagnostic_asset_and_time_holdout",
    }
    canonical = json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        **core,
        "selection_sha256": hashlib.sha256(canonical).hexdigest(),
        "sealed_at_utc": datetime.now(UTC).isoformat(),
    }


def _atomic_torch_save(path: Path, payload: dict[str, Any]) -> None:
    """Atomarno sohranyaet PyTorch checkpoint ryadom s celevym failom."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        torch.save(payload, temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _checkpoint_payload(
    model: CausalTCN,
    config: SequenceExperimentConfig,
    scaler: object,
    target_scale: float,
    selected: IntradayStrategySpec,
    architecture: dict[str, Any],
) -> dict[str, Any]:
    """Sobiraet samodostatochnyi CPU-checkpoint final'noi seti."""
    state = {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}
    return {
        "state_dict": state,
        "architecture": architecture,
        "model_config": config.model.model_dump(mode="json"),
        "protocol": config.protocol.model_dump(mode="json"),
        "universe_metadata": {
            "engine": config.universe.engine,
            "market": config.universe.market,
            "board": config.universe.board,
            "timeframe": config.universe.timeframe,
            "timezone": "Europe/Moscow",
            "session_start": "09:50",
        },
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_scaler": scaler.as_dict(),
        "target_scale": target_scale,
        "selected_strategy": selected.as_dict(),
        "training_period": [
            config.protocol.data_start.isoformat(),
            config.protocol.calibration_end.isoformat(),
        ],
        "torch_version": torch.__version__,
    }


def _risk_scenarios(
    predictions: pd.DataFrame,
    selected: IntradayStrategySpec,
    config: SequenceExperimentConfig,
) -> tuple[pd.DataFrame, dict[float, IntradayBacktest]]:
    """Schitaet zafiksirovannye leverage-scenarii bez novogo podbora."""
    rows: list[dict[str, object]] = []
    results: dict[float, IntradayBacktest] = {}
    for leverage in config.portfolio.risk_scenarios:
        spec = IntradayStrategySpec(
            **{
                **selected.as_dict(),
                "name": f"{selected.name}_{leverage:.1f}x",
                "leverage": leverage,
            }
        )
        result = evaluate_strategy(predictions, spec, config.portfolio)
        results[leverage] = result
        rows.append({"gross_leverage": leverage, **result.metrics})
    return pd.DataFrame(rows), results


def _cost_stress(
    predictions: pd.DataFrame,
    selected: IntradayStrategySpec,
    config: SequenceExperimentConfig,
) -> pd.DataFrame:
    """Povtoryaet core-backtest pri uvelichennyh izderzhkah."""
    rows: list[dict[str, object]] = []
    for multiplier in COST_STRESS_MULTIPLIERS:
        result = evaluate_strategy(
            predictions,
            selected,
            config.portfolio,
            cost_multiplier=multiplier,
        )
        rows.append({"cost_multiplier": multiplier, **result.metrics})
    return pd.DataFrame(rows)


def _deployment_decision(
    config: SequenceExperimentConfig,
    development_test: IntradayBacktest,
    holdout_test: IntradayBacktest,
) -> dict[str, object]:
    """Primenaet predvaritel'no obyavlennye bar'ery bez obeshchaniya pribyli."""
    checks = {
        "development_execution_complete": bool(
            development_test.metrics["execution_complete"]
        ),
        "holdout_execution_complete": bool(holdout_test.metrics["execution_complete"]),
        "development_test_positive": development_test.metrics["annualized_return"] > 0,
        "holdout_test_positive": holdout_test.metrics["annualized_return"] > 0,
        "development_test_sharpe_above_1": development_test.metrics["sharpe"] >= 1.0,
        "holdout_test_sharpe_above_1": holdout_test.metrics["sharpe"] >= 1.0,
        "development_drawdown_within_limit": development_test.metrics["max_drawdown"]
        <= config.portfolio.maximum_core_drawdown,
        "holdout_drawdown_within_limit": holdout_test.metrics["max_drawdown"]
        <= config.portfolio.maximum_core_drawdown,
        "target_cagr_on_both_tests": development_test.metrics["annualized_return"]
        >= config.portfolio.target_cagr
        and holdout_test.metrics["annualized_return"] >= config.portfolio.target_cagr,
    }
    return {
        "status": "RESEARCH_GATE_PASSED" if all(checks.values()) else "NO_GO_FOR_LIVE_TRADING",
        "checks": checks,
        "target_cagr": config.portfolio.target_cagr,
        "warning": (
            "Historical backtest is not a profit guarantee and is not live-trading approval."
        ),
    }


def _report(
    architecture: dict[str, Any],
    seal: dict[str, object],
    development_test: IntradayBacktest,
    holdout_test: IntradayBacktest,
    decision: dict[str, object],
) -> str:
    """Formiruet kratkii otchet s chestnym statusom vnevyborochnyh proverok."""
    return "\n".join(
        [
            "# RTX 5090 causal-TCN report",
            "",
            "Сеть получает 192 исторических 10-минутных бара и прогнозирует доходность "
            "между следующим open и open через 24 бара. Позиции не переносятся на ночь.",
            "",
            f"Параметров: {architecture['trainable_parameter_count']:,}; "
            f"residual-блоков: {architecture['residual_blocks']}; "
            f"каналов: {architecture['channels']}.",
            "",
            f"Selection seal: `{seal['selection_sha256']}`.",
            "",
            "## Независимые результаты core 1x",
            "",
            f"Development time-test: CAGR {development_test.metrics['annualized_return']:.2%}, "
            f"Sharpe {development_test.metrics['sharpe']:.3f}, "
            f"max DD {development_test.metrics['max_drawdown']:.2%}.",
            "",
            f"Unseen-instrument holdout: CAGR {holdout_test.metrics['annualized_return']:.2%}, "
            f"Sharpe {holdout_test.metrics['sharpe']:.3f}, "
            f"max DD {holdout_test.metrics['max_drawdown']:.2%}.",
            "",
            "Execution completeness: development "
            f"{bool(development_test.metrics['execution_complete'])} "
            f"(missing exits: {development_test.metrics['missing_exit_count']}), holdout "
            f"{bool(holdout_test.metrics['execution_complete'])} "
            f"(missing exits: {holdout_test.metrics['missing_exit_count']}). "
            "Synthetic missing-exit return is stress accounting, not an executable fill.",
            "",
            f"Итоговый шлюз: **{decision['status']}**.",
            "",
            "В свечах присутствуют OHLC, объём бумаг и денежный оборот. Количество сделок, "
            "лента и стакан отсутствуют: платный AlgoPack не использовался.",
            "",
            "Это исследовательский исторический результат, а не гарантия прибыли.",
            "",
        ]
    )


def execute_sequence_experiment(config: SequenceExperimentConfig) -> Path:
    """Vypolnyaet train, selection-seal, final fit i dva testa na RTX 5090."""
    run_dir = create_run_directory(config.paths.runs_dir)
    writer = ArtifactWriter(run_dir)
    configure_logging(run_dir / "run.log")
    writer.write_yaml("resolved_config.yaml", sequence_config_as_dict(config))
    LOGGER.info("Sequence: zagruzka tol'ko development do calibration_end")
    pretest_panel, pretest_manifest = load_sequence_panel(
        config,
        config.universe.development,
        config.protocol.calibration_end,
        partition="pretest",
    )
    writer.write_frame("pretest_data_manifest.csv", pretest_manifest)
    selection_scaler = fit_feature_scaler(pretest_panel, config.protocol.train_end)
    selection_store = build_sequence_store(
        pretest_panel,
        selection_scaler,
        config.protocol.sequence_length,
    )
    train_samples = select_sequence_samples(
        selection_store,
        config.protocol.data_start,
        config.protocol.train_end,
        config.protocol.train_stride_bars,
    )
    model_validation_samples = select_sequence_samples(
        selection_store,
        config.protocol.validation_start,
        config.protocol.validation_end,
        stride_bars=1,
        embargo_bars=config.protocol.embargo_bars,
        allowed_slots=config.protocol.evaluation_decision_slots,
        require_target=False,
    )
    target_scale = robust_target_scale(train_samples)
    LOGGER.info(
        "Sequence selection fit: train=%s validation=%s target_scale=%.8f",
        len(train_samples),
        len(model_validation_samples),
        target_scale,
    )
    outcome = fit_with_early_stopping(
        selection_store,
        train_samples,
        model_validation_samples,
        target_scale,
        config.model,
        config.seed,
    )
    model_validation_scores = predict_sequence_scores(
        outcome.model,
        selection_store,
        model_validation_samples,
        target_scale,
        config.model,
    )
    model_validation_predictions = _prediction_frame(
        model_validation_samples,
        model_validation_scores,
    )
    strategy_validation_samples = select_sequence_samples(
        selection_store,
        config.protocol.calibration_start,
        config.protocol.calibration_end,
        stride_bars=1,
        embargo_bars=config.protocol.embargo_bars,
        allowed_slots=config.protocol.evaluation_decision_slots,
        require_target=False,
    )
    strategy_validation_scores = predict_sequence_scores(
        outcome.model,
        selection_store,
        strategy_validation_samples,
        target_scale,
        config.model,
    )
    strategy_validation_predictions = _prediction_frame(
        strategy_validation_samples,
        strategy_validation_scores,
    )
    leaderboard, selected, validation_result = _validation_search(
        strategy_validation_predictions,
        config,
    )
    seal = _selection_seal(
        config,
        selected,
        validation_result,
        outcome.best_epoch,
        outcome.best_validation_ic,
    )
    writer.write_frame("training_history.csv", outcome.history)
    writer.write_frame("model_validation_predictions.csv", model_validation_predictions)
    writer.write_frame("strategy_validation_predictions.csv", strategy_validation_predictions)
    writer.write_frame("strategy_validation_leaderboard.csv", leaderboard)
    writer.write_json("selection_scaler.json", selection_scaler.as_dict())
    writer.write_json("selection_seal.json", seal)
    LOGGER.info("Sequence selection zapechatan: %s", seal["selection_sha256"])
    LOGGER.info("Sequence final fit do calibration_end, epochs=%s", outcome.best_epoch)
    final_scaler = fit_feature_scaler(pretest_panel, config.protocol.calibration_end)
    final_store = build_sequence_store(
        pretest_panel,
        final_scaler,
        config.protocol.sequence_length,
    )
    final_samples = select_sequence_samples(
        final_store,
        config.protocol.data_start,
        config.protocol.calibration_end,
        config.protocol.train_stride_bars,
    )
    final_target_scale = robust_target_scale(final_samples)
    final_model, final_history = fit_fixed_epochs(
        final_store,
        final_samples,
        final_target_scale,
        config.model,
        outcome.best_epoch,
        config.seed,
    )
    architecture = model_architecture(final_model, config.model)
    architecture.update(
        {
            "feature_count": len(FEATURE_COLUMNS),
            "selection_training_samples": len(train_samples),
            "final_training_samples": len(final_samples),
            "selection_best_epoch": outcome.best_epoch,
            "selection_validation_ic": outcome.best_validation_ic,
            "selection_elapsed_seconds": outcome.elapsed_seconds,
            "gpu": torch.cuda.get_device_name(0),
            "cuda_runtime": torch.version.cuda,
        }
    )
    writer.write_frame("final_training_history.csv", final_history)
    writer.write_json("model_architecture.json", architecture)
    writer.write_json("feature_list.json", list(FEATURE_COLUMNS))
    writer.write_json("final_scaler.json", final_scaler.as_dict())
    _atomic_torch_save(
        run_dir / "model.pt",
        _checkpoint_payload(
            final_model,
            config,
            final_scaler,
            final_target_scale,
            selected,
            architecture,
        ),
    )
    del pretest_panel, selection_store, final_store
    LOGGER.info("Sequence seal gotov; teper' odin raz otkryvaetsya 2025+ development-test")
    development_panel, development_manifest = load_sequence_panel(
        config,
        config.universe.development,
        config.protocol.test_end,
        partition="test",
    )
    development_store = build_sequence_store(
        development_panel,
        final_scaler,
        config.protocol.sequence_length,
    )
    development_samples = select_sequence_samples(
        development_store,
        config.protocol.test_start,
        config.protocol.test_end,
        stride_bars=1,
        embargo_bars=config.protocol.embargo_bars,
        allowed_slots=config.protocol.evaluation_decision_slots,
        require_target=False,
    )
    development_scores = predict_sequence_scores(
        final_model,
        development_store,
        development_samples,
        final_target_scale,
        config.model,
    )
    development_predictions = _prediction_frame(development_samples, development_scores)
    development_scenarios, development_results = _risk_scenarios(
        development_predictions,
        selected,
        config,
    )
    writer.write_frame("development_test_manifest.csv", development_manifest)
    writer.write_frame("development_test_predictions.csv", development_predictions)
    writer.write_frame("development_test_risk_scenarios.csv", development_scenarios)
    LOGGER.info("Sequence: teper' odin raz otkryvaetsya unseen instrument-holdout")
    holdout_panel, holdout_manifest = load_sequence_panel(
        config,
        config.universe.holdout,
        config.protocol.test_end,
        partition="test",
    )
    holdout_store = build_sequence_store(
        holdout_panel,
        final_scaler,
        config.protocol.sequence_length,
    )
    holdout_samples = select_sequence_samples(
        holdout_store,
        config.protocol.test_start,
        config.protocol.test_end,
        stride_bars=1,
        embargo_bars=config.protocol.embargo_bars,
        allowed_slots=config.protocol.evaluation_decision_slots,
        require_target=False,
    )
    holdout_scores = predict_sequence_scores(
        final_model,
        holdout_store,
        holdout_samples,
        final_target_scale,
        config.model,
    )
    holdout_predictions = _prediction_frame(holdout_samples, holdout_scores)
    holdout_scenarios, holdout_results = _risk_scenarios(
        holdout_predictions,
        selected,
        config,
    )
    writer.write_frame("holdout_test_manifest.csv", holdout_manifest)
    writer.write_frame("holdout_test_predictions.csv", holdout_predictions)
    writer.write_frame("holdout_test_risk_scenarios.csv", holdout_scenarios)
    writer.write_frame(
        "holdout_cost_stress.csv",
        _cost_stress(holdout_predictions, selected, config),
    )
    core_leverage = config.portfolio.core_leverage
    development_core = development_results[core_leverage]
    holdout_core = holdout_results[core_leverage]
    decision = _deployment_decision(
        config,
        development_core,
        holdout_core,
    )
    writer.write_frame("development_test_equity.csv", development_core.ledger.reset_index())
    writer.write_frame("holdout_test_equity.csv", holdout_core.ledger.reset_index())
    writer.write_frame("holdout_test_weights.csv", holdout_core.weights.reset_index())
    writer.write_equity_plot(
        "holdout_equity_curve.png",
        holdout_core.ledger["equity"],
        width=11,
        height=5,
        title="RTX 5090 causal-TCN: unseen-instrument holdout",
    )
    writer.write_json(
        "metrics.json",
        {
            "evaluation_status": "post_diagnostic_asset_and_time_holdout",
            "selection": seal,
            "strategy_validation": validation_result.metrics,
            "development_test_core": development_core.metrics,
            "holdout_test_core": holdout_core.metrics,
            "development_test_ic": mean_cross_section_ic(
                development_predictions, development_scores
            ),
            "holdout_test_ic": mean_cross_section_ic(holdout_predictions, holdout_scores),
        },
    )
    writer.write_json("deployment_decision.json", decision)
    writer.write_text(
        "report.md",
        _report(
            architecture,
            seal,
            development_core,
            holdout_core,
            decision,
        ),
    )
    LOGGER.info("Sequence-eksperiment zavershen: %s", run_dir)
    return run_dir
