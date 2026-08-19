"""Walk-forward sravnenie tablichnyh modelei na development-universume."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from market_lab.alpha.config import AlphaConfig
from market_lab.alpha.panel import MODEL_FEATURE_COLUMNS, complete_model_rows


@dataclass(frozen=True)
class ModelValidationResult:
    """Hranit OOS-prognozy, foldy i poslednie obuchennye modeli."""

    predictions: pd.DataFrame
    folds: pd.DataFrame
    ridge: Pipeline
    extra_trees: ExtraTreesRegressor


def validation_periods(config: AlphaConfig) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Delaet posledovatel'nye polugodovye ili inye kalendarnye foldy."""
    start = pd.Timestamp(config.protocol.validation_start)
    final_end = pd.Timestamp(config.protocol.validation_end)
    periods: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    while start <= final_end:
        end = min(
            start
            + pd.DateOffset(months=config.protocol.validation_fold_months)
            - pd.Timedelta(days=1),
            final_end,
        )
        periods.append((start, end))
        start = end + pd.Timedelta(days=1)
    return periods


def _build_ridge(config: AlphaConfig) -> Pipeline:
    """Sozdaet deterministichnuyu lineinuyu model' so standartizaciei."""
    return make_pipeline(
        StandardScaler(),
        Ridge(alpha=config.model.ridge_alpha, solver="cholesky"),
    )


def _build_extra_trees(config: AlphaConfig) -> ExtraTreesRegressor:
    """Sozdaet deterministichnyi nelineinyi ansambl' sravneniya."""
    return ExtraTreesRegressor(
        n_estimators=config.model.extra_trees_estimators,
        max_features=config.model.extra_trees_max_features,
        min_samples_leaf=config.model.extra_trees_min_samples_leaf,
        n_jobs=-1,
        random_state=config.seed,
    )


def walk_forward_predictions(panel: pd.DataFrame, config: AlphaConfig) -> ModelValidationResult:
    """Obuchaet modeli tol'ko na proshlom i obedinyaet OOS-prognozy."""
    clean = complete_model_rows(panel)
    prediction_parts: list[pd.DataFrame] = []
    fold_rows: list[dict[str, object]] = []
    last_ridge: Pipeline | None = None
    last_extra: ExtraTreesRegressor | None = None
    for fold_number, (start, end) in enumerate(validation_periods(config)):
        embargo_cutoff = start - pd.Timedelta(days=config.protocol.embargo_days)
        train = clean.loc[clean["decision_date"] < embargo_cutoff]
        valid = clean.loc[
            (clean["decision_date"] >= start) & (clean["decision_date"] <= end)
        ].copy()
        if train.empty or valid.empty:
            raise ValueError(
                f"Pustoi alpha-fold {fold_number}: train={len(train)}, valid={len(valid)}"
            )
        ridge = _build_ridge(config)
        extra = _build_extra_trees(config)
        ridge.fit(train.loc[:, MODEL_FEATURE_COLUMNS], train["target_return"])
        extra.fit(train.loc[:, MODEL_FEATURE_COLUMNS], train["target_return"])
        valid["prediction_ridge"] = ridge.predict(valid.loc[:, MODEL_FEATURE_COLUMNS])
        valid["prediction_extra_trees"] = extra.predict(
            valid.loc[:, MODEL_FEATURE_COLUMNS]
        )
        valid["validation_fold"] = fold_number
        prediction_parts.append(valid)
        fold_rows.append(
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
        last_ridge = ridge
        last_extra = extra
    if last_ridge is None or last_extra is None:
        raise ValueError("Ne udalos' postroit' ni odnogo validation-folda")
    predictions = pd.concat(prediction_parts, ignore_index=True)
    return ModelValidationResult(
        predictions=predictions,
        folds=pd.DataFrame(fold_rows),
        ridge=last_ridge,
        extra_trees=last_extra,
    )


def fit_final_extra_trees(panel: pd.DataFrame, config: AlphaConfig) -> ExtraTreesRegressor:
    """Pereobuchaet sravnitel'nyi ansambl' na vsem pre-test development."""
    clean = complete_model_rows(panel)
    cutoff = pd.Timestamp(config.protocol.test_start) - pd.Timedelta(
        days=config.protocol.embargo_days
    )
    train = clean.loc[clean["decision_date"] < cutoff]
    model = _build_extra_trees(config)
    model.fit(train.loc[:, MODEL_FEATURE_COLUMNS], train["target_return"])
    return model
