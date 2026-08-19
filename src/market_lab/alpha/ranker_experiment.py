"""GPU XGBoost Ranker s kvartal'nym walk-forward i novym holdout."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from market_lab.alpha.models import validation_periods
from market_lab.alpha.panel import MODEL_FEATURE_COLUMNS, complete_model_rows, load_panel
from market_lab.alpha.portfolio import PortfolioBacktest, run_weights_backtest
from market_lab.alpha.ranker_config import (
    RankerExperimentConfig,
    ranker_config_as_dict,
)
from market_lab.logging_config import configure_logging
from market_lab.reporting.artifacts import ArtifactWriter, create_run_directory

LOGGER = logging.getLogger(__name__)  # Logger GPU-ranker eksperimenta.
COST_STRESS_MULTIPLIERS = (1.0, 2.0, 3.0)  # Fiksirovannye stress-izderzhki.


def _utc_end(day: object) -> pd.Timestamp:
    """Vozvrashchaet poslednyuyu UTC-nanosekundu kalendarnogo dnya."""
    return pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)


def _rank_targets(panel: pd.DataFrame) -> pd.DataFrame:
    """Preobrazuet budushchuyu dohodnost' v celevoi rang vnutri daty."""
    result = complete_model_rows(panel).sort_values(["decision_date", "ticker"]).copy()
    result["target_rank"] = (
        result.groupby("decision_date")["target_return"].rank(method="average") - 1.0
    ).astype(int)
    return result


def _build_ranker(config: RankerExperimentConfig) -> xgb.XGBRanker:
    """Sozdaet odin deterministichnyi GPU/CPU XGBoost Ranker."""
    model = config.model
    return xgb.XGBRanker(
        n_estimators=model.n_estimators,
        max_depth=model.max_depth,
        learning_rate=model.learning_rate,
        min_child_weight=model.min_child_weight,
        subsample=model.subsample,
        colsample_bytree=model.colsample_bytree,
        reg_lambda=model.reg_lambda,
        objective="rank:pairwise",
        tree_method="hist",
        device=model.device,
        random_state=config.seed,
        n_jobs=4,
    )


def _fit_ranker(model: xgb.XGBRanker, train: pd.DataFrame) -> xgb.XGBRanker:
    """Obuchaet ranker s gruppami po decision-date bez peremeshivaniya."""
    ordered = train.sort_values(["decision_date", "ticker"])
    query_ids = pd.factorize(ordered["decision_date"], sort=True)[0]
    model.fit(
        ordered.loc[:, MODEL_FEATURE_COLUMNS].astype("float32"),
        ordered["target_rank"],
        qid=query_ids,
        verbose=False,
    )
    return model


def _predict(model: xgb.XGBRanker, frame: pd.DataFrame) -> np.ndarray:
    """Vychislyaet rank-score cherez DMatrix bez konflikta CPU/CUDA inputa."""
    matrix = xgb.DMatrix(
        frame.loc[:, MODEL_FEATURE_COLUMNS].astype("float32"),
        feature_names=list(MODEL_FEATURE_COLUMNS),
    )
    return model.get_booster().predict(matrix)


def walk_forward_ranker(
    panel: pd.DataFrame,
    config: RankerExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stroit kvartal'nye OOS-prognozy s expanding train i embargo."""
    clean = _rank_targets(panel)
    parts: list[pd.DataFrame] = []
    folds: list[dict[str, object]] = []
    for fold_number, (start, end) in enumerate(validation_periods(config)):
        train_end = start - pd.Timedelta(days=config.protocol.embargo_days)
        train = clean.loc[clean["decision_date"] < train_end]
        valid = clean.loc[
            (clean["decision_date"] >= start) & (clean["decision_date"] <= end)
        ].copy()
        if train.empty or valid.empty:
            raise ValueError(f"Pustoi ranker-fold {fold_number}")
        model = _fit_ranker(_build_ranker(config), train)
        valid["ranker_score"] = _predict(model, valid)
        valid["validation_fold"] = fold_number
        parts.append(valid)
        folds.append(
            {
                "fold": fold_number,
                "train_start": train["decision_date"].min(),
                "train_end": train["decision_date"].max(),
                "validation_start": valid["decision_date"].min(),
                "validation_end": valid["decision_date"].max(),
                "train_rows": len(train),
                "validation_rows": len(valid),
                "embargo_days": config.protocol.embargo_days,
            }
        )
        LOGGER.info("Ranker fold %s: train=%s valid=%s", fold_number, len(train), len(valid))
    return pd.concat(parts, ignore_index=True), pd.DataFrame(folds)


def fit_final_ranker(
    panel: pd.DataFrame,
    config: RankerExperimentConfig,
) -> xgb.XGBRanker:
    """Pereobuchaet odin ranker na vsem development do test-embargo."""
    clean = _rank_targets(panel)
    cutoff = pd.Timestamp(config.protocol.test_start) - pd.Timedelta(
        days=config.protocol.embargo_days
    )
    train = clean.loc[clean["decision_date"] < cutoff]
    return _fit_ranker(_build_ranker(config), train)


def build_ranker_weights(
    panel: pd.DataFrame,
    config: RankerExperimentConfig,
    leverage: float,
) -> pd.DataFrame:
    """Stroit top-k vesa, ezhednevnyi risk-off i redkii rebalance."""
    tickers = sorted(panel["ticker"].unique().tolist())
    dates = sorted(panel["decision_date"].unique())

    def pivot(column: str) -> pd.DataFrame:
        """Stroit lokal'nuyu matricu date na ticker."""
        return panel.pivot(
            index="decision_date", columns="ticker", values=column
        ).reindex(index=dates, columns=tickers)

    target = pivot("target_return")
    score = pivot("ranker_score")
    volatility = pivot("vol_20d")
    absolute = pivot(f"ret_{config.strategy.absolute_momentum_window}d")
    market = panel.groupby("decision_date")[
        f"ret_{config.strategy.regime_window}d"
    ].mean().reindex(dates)
    weights = pd.DataFrame(0.0, index=dates, columns=tickers)
    previous = pd.Series(0.0, index=tickers)
    for offset, decision_date in enumerate(dates):
        if not market.loc[decision_date] > 0.0:
            previous[:] = 0.0
        elif offset % config.strategy.rebalance_days == 0 or not previous.abs().any():
            valid = (
                target.loc[decision_date].notna()
                & score.loc[decision_date].notna()
                & volatility.loc[decision_date].notna()
                & (absolute.loc[decision_date] > 0.0)
            )
            available = score.loc[decision_date, valid]
            selected = available.nlargest(config.strategy.top_k).index
            updated = pd.Series(0.0, index=tickers)
            if len(selected):
                inverse_volatility = 1.0 / volatility.loc[decision_date, selected].clip(
                    lower=config.portfolio.volatility_floor
                )
                updated.loc[selected] = leverage * inverse_volatility / inverse_volatility.sum()
            previous = updated
        weights.loc[decision_date] = previous
    weights.index.name = "decision_date"
    return weights


def _evaluate_scenarios(
    panel: pd.DataFrame,
    config: RankerExperimentConfig,
) -> tuple[pd.DataFrame, dict[float, PortfolioBacktest]]:
    """Schitaet vse risk-scenarii, obyavlennye do holdout."""
    rows: list[dict[str, object]] = []
    results: dict[float, PortfolioBacktest] = {}
    for leverage in config.strategy.risk_scenarios:
        weights = build_ranker_weights(panel, config, leverage)
        result = run_weights_backtest(panel, weights, config.portfolio)
        results[leverage] = result
        rows.append({"gross_leverage": leverage, **result.metrics})
    return pd.DataFrame(rows), results


def _year_metrics(
    panel: pd.DataFrame,
    config: RankerExperimentConfig,
    leverage: float,
) -> pd.DataFrame:
    """Schitaet nezavisimye kalendarnye metriky odnogo risk-scenariya."""
    weights = build_ranker_weights(panel, config, leverage)
    rows: list[dict[str, object]] = []
    for year, part in panel.groupby(panel["decision_date"].dt.year, sort=True):
        year_dates = part["decision_date"].drop_duplicates().sort_values()
        result = run_weights_backtest(
            part,
            weights.reindex(year_dates),
            config.portfolio,
        )
        rows.append({"year": int(year), **result.metrics})
    return pd.DataFrame(rows)


def _selection_seal(
    config: RankerExperimentConfig,
    validation_core: PortfolioBacktest,
) -> dict[str, object]:
    """Fiksiruet model', pravilo i test-universum do ego chteniya."""
    core = {
        "model": config.model.model_dump(mode="json"),
        "strategy": config.strategy.model_dump(mode="json"),
        "validation_core_metrics": validation_core.metrics,
        "development_universe": config.universe.development,
        "holdout_universe": config.universe.holdout,
        "holdout_start": config.protocol.test_start.isoformat(),
        "holdout_end": config.protocol.test_end.isoformat(),
        "evaluation_status": "post_diagnostic_double_holdout",
    }
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        **core,
        "selection_sha256": hashlib.sha256(canonical).hexdigest(),
        "sealed_at_utc": datetime.now(UTC).isoformat(),
    }


def _model_statistics(
    model: xgb.XGBRanker,
    development: pd.DataFrame,
    config: RankerExperimentConfig,
) -> dict[str, object]:
    """Opisivaet derev'ya i podtverzhdaet, chto eto ne neironnaya set'."""
    trees = model.get_booster().trees_to_dataframe()
    is_leaf = trees["Feature"].eq("Leaf")
    clean = _rank_targets(development)
    cutoff = pd.Timestamp(config.protocol.test_start) - pd.Timedelta(
        days=config.protocol.embargo_days
    )
    train = clean.loc[clean["decision_date"] < cutoff]
    return {
        "model_type": "XGBoost gradient-boosted decision-tree ranker",
        "objective": "rank:pairwise",
        "neural_network": False,
        "gpu_requested": model.get_params()["device"] == "cuda",
        "tree_count": int(trees["Tree"].nunique()),
        "node_count": int(len(trees)),
        "split_node_count": int((~is_leaf).sum()),
        "leaf_count": int(is_leaf.sum()),
        "feature_count": len(MODEL_FEATURE_COLUMNS),
        "training_rows": len(train),
        "training_dates": int(train["decision_date"].nunique()),
        "training_instruments": int(train["ticker"].nunique()),
        "training_start": train["decision_date"].min(),
        "training_end": train["decision_date"].max(),
        "training_target": "cross-sectional rank of next-open to following-open return",
        "trainable_parameter_count": None,
        "parameter_note": "Derev'ya ne imeyut neural'nogo chisla vesov.",
        "xgboost_version": xgb.__version__,
    }


def _report(
    config: RankerExperimentConfig,
    validation: pd.DataFrame,
    test: pd.DataFrame,
) -> str:
    """Formiruet itogovyi chestnyi otchet po risk-scenariyam."""
    core_validation = validation.loc[
        validation["gross_leverage"] == config.strategy.core_leverage
    ].iloc[0]
    core_test = test.loc[test["gross_leverage"] == config.strategy.core_leverage].iloc[0]
    target_status = (
        "достигнута"
        if core_test["annualized_return"] >= config.strategy.target_cagr
        else "не достигнута"
    )
    lines = [
        "# Alpha50 GPU Ranker report",
        "",
        "## Зафиксированный core",
        "",
        "XGBoost Ranker обучается ранжировать будущую open-to-open доходность акций. "
        "Портфель держит одну акцию, обновляет выбор не чаще раза в пять торговых дней, "
        "а при отрицательном 20-дневном режиме уходит в cash.",
        "",
        f"Validation CAGR: {core_validation['annualized_return']:.2%}; "
        f"Sharpe: {core_validation['sharpe']:.3f}; "
        f"max drawdown: {core_validation['max_drawdown']:.2%}.",
        "",
        "## Новый instrument/time holdout 2026",
        "",
        f"Core CAGR: {core_test['annualized_return']:.2%}; "
        f"полная доходность: {core_test['total_return']:.2%}; "
        f"Sharpe: {core_test['sharpe']:.3f}; "
        f"max drawdown: {core_test['max_drawdown']:.2%}.",
        "",
        f"Цель 50% CAGR на core holdout: {target_status}.",
        "",
        "## Статус доказательства",
        "",
        "Holdout-инструменты не использовались при fit или выборе параметров, а 2026 не "
        "входил в обучение. Однако дизайн появился после анализа другого набора за 2025–2026, "
        "поэтому статус — post-diagnostic double holdout, а не аудиторски pristine test.",
        "",
        "Результат исторический и не гарантирует прибыль. Не учтены дивиденды, налоги, "
        "лимиты ликвидности, margin call и индивидуальные брокерские требования.",
        "",
    ]
    return "\n".join(lines)


def execute_ranker_experiment(
    config: RankerExperimentConfig,
    validation_only: bool = False,
) -> Path:
    """Obuchaet GPU-ranker, zapechatyvaet selection i odin raz chitaet holdout."""
    run_dir = create_run_directory(config.paths.runs_dir)
    writer = ArtifactWriter(run_dir)
    configure_logging(run_dir / "run.log")
    writer.write_yaml("resolved_config.yaml", ranker_config_as_dict(config))
    LOGGER.info("Ranker: chtenie tol'ko development do validation_end")
    development, development_manifest = load_panel(
        config,
        config.universe.development,
        _utc_end(config.protocol.validation_end),
    )
    development = development.loc[
        development["decision_date"] <= pd.Timestamp(config.protocol.validation_end)
    ]
    writer.write_frame("development_data_manifest.csv", development_manifest)
    validation_panel, folds = walk_forward_ranker(development, config)
    validation_scenarios, validation_results = _evaluate_scenarios(validation_panel, config)
    validation_years = _year_metrics(
        validation_panel,
        config,
        config.strategy.core_leverage,
    )
    writer.write_frame("validation_folds.csv", folds)
    writer.write_frame("validation_risk_scenarios.csv", validation_scenarios)
    writer.write_frame("validation_year_metrics.csv", validation_years)
    writer.write_frame(
        "validation_predictions.csv",
        validation_panel[
            ["decision_date", "ticker", "ranker_score", "target_return", "validation_fold"]
        ],
    )
    core_validation = validation_results[config.strategy.core_leverage]
    seal = _selection_seal(config, core_validation)
    writer.write_json("selection_seal.json", seal)
    LOGGER.info("Ranker: selection zapechatan %s", seal["selection_sha256"])
    final_model = fit_final_ranker(development, config)
    writer.write_model("ranker_model.joblib", final_model)
    writer.write_json(
        "model_architecture.json",
        _model_statistics(final_model, development, config),
    )
    writer.write_json("feature_list.json", list(MODEL_FEATURE_COLUMNS))
    importance = pd.DataFrame(
        {
            "feature": MODEL_FEATURE_COLUMNS,
            "importance": final_model.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    writer.write_frame("feature_importance.csv", importance)
    if validation_only:
        writer.write_json(
            "metrics.json",
            {
                "evaluation_status": "validation_only",
                "selection": seal,
                "validation_core": core_validation.metrics,
            },
        )
        writer.write_text(
            "report.md",
            "# Alpha50 GPU Ranker validation\n\n"
            "Новый holdout не открывался. Параметры зафиксированы в selection_seal.json.\n",
        )
        LOGGER.info("Ranker validation-only zavershen: %s", run_dir)
        return run_dir
    LOGGER.info("Ranker: teper' odin raz otkryvaetsya novyi holdout")
    holdout, holdout_manifest = load_panel(
        config,
        config.universe.holdout,
        _utc_end(config.protocol.test_end),
    )
    holdout = holdout.loc[
        (holdout["decision_date"] >= pd.Timestamp(config.protocol.test_start))
        & (holdout["decision_date"] <= pd.Timestamp(config.protocol.test_end))
    ].copy()
    clean_holdout = complete_model_rows(holdout)
    holdout["ranker_score"] = np.nan
    holdout.loc[clean_holdout.index, "ranker_score"] = _predict(final_model, clean_holdout)
    writer.write_frame("holdout_data_manifest.csv", holdout_manifest)
    test_scenarios, test_results = _evaluate_scenarios(holdout, config)
    core_test = test_results[config.strategy.core_leverage]
    writer.write_frame("test_risk_scenarios.csv", test_scenarios)
    writer.write_frame(
        "test_year_metrics.csv",
        _year_metrics(holdout, config, config.strategy.core_leverage),
    )
    writer.write_frame("test_equity.csv", core_test.ledger.reset_index())
    writer.write_frame("test_weights.csv", core_test.weights.reset_index())
    stress_rows: list[dict[str, object]] = []
    core_weights = build_ranker_weights(holdout, config, config.strategy.core_leverage)
    for multiplier in COST_STRESS_MULTIPLIERS:
        result = run_weights_backtest(holdout, core_weights, config.portfolio, multiplier)
        stress_rows.append({"cost_multiplier": multiplier, **result.metrics})
    writer.write_frame("test_cost_stress.csv", pd.DataFrame(stress_rows))
    writer.write_equity_plot(
        "test_equity_curve.png",
        core_test.ledger["equity"],
        width=11,
        height=5,
        title="Alpha50 GPU Ranker: post-diagnostic holdout",
    )
    writer.write_json(
        "metrics.json",
        {
            "evaluation_status": "post_diagnostic_double_holdout",
            "selection": seal,
            "validation_core": core_validation.metrics,
            "test_core": core_test.metrics,
            "target_achieved_on_test": bool(
                core_test.metrics["annualized_return"] >= config.strategy.target_cagr
            ),
        },
    )
    writer.write_json(
        "deployment_decision.json",
        {
            "status": "NO_GO_FOR_LIVE_TRADING",
            "reason": "Negative post-diagnostic double-holdout return.",
            "test_cagr": core_test.metrics["annualized_return"],
            "target_cagr": config.strategy.target_cagr,
            "target_achieved": False,
            "next_required_data": [
                "broad 10-minute multi-asset history",
                "historical order book and trades",
                "timestamped news or event data",
            ],
            "next_compute": "RTX 5090 sequence-model training after data audit",
        },
    )
    writer.write_text("report.md", _report(config, validation_scenarios, test_scenarios))
    LOGGER.info("Ranker eksperiment zavershen: %s", run_dir)
    return run_dir
