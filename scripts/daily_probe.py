"""Bystryi development-probe daily residual-TCN bez otkrytiya holdout."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab.sequence.context import load_daily_context
from market_lab.sequence.daily import (
    build_daily_panel,
    build_daily_sequence_store,
    daily_feature_columns,
    fit_daily_feature_scaler,
    select_daily_sequence_samples,
)
from market_lab.sequence.daily_config import load_daily_experiment_config
from market_lab.sequence.dataset import robust_target_scale
from market_lab.sequence.training import (
    fit_fixed_epochs,
    fit_with_early_stopping,
    mean_cross_section_ic,
    predict_sequence_scores,
)


def _load_market_series(root: Path) -> pd.Series:
    """Agregiruet IMOEX do close osnovnoi sessii."""
    path = next((root / "data/processed/sequence_context").glob("IMOEX_*.parquet"))
    frame = pd.read_parquet(path)
    local = frame.index.tz_convert("Europe/Moscow")
    minute = local.hour * 60 + local.minute
    main = frame.loc[(minute >= 9 * 60 + 50) & (minute <= 18 * 60 + 40)].copy()
    main["date"] = pd.to_datetime(main.index.tz_convert("Europe/Moscow").date)
    return main.groupby("date")["close"].last()


def _load_development_frames(root: Path, tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Chitaet tol'ko uzhe ispol'zovannyi development-universum."""
    frames: dict[str, pd.DataFrame] = {}
    cache = root / "data/processed/sequence_10m"
    for ticker in tickers:
        path = next(cache.glob(f"{ticker}_TQBR_10m_*.parquet"))
        frames[ticker] = pd.read_parquet(path)
    return frames


def _portfolio_proxies(metadata: pd.DataFrame, short_borrow_rate: float) -> list[dict[str, float]]:
    """Schitaet konservativnye alpha-proksi do gotovnosti event-ledger."""
    cohorts: list[dict[str, float | pd.Timestamp]] = []
    for entry, group in metadata.groupby("entry_time"):
        ranked = group.dropna(subset=["target_return", "model_target", "score"]).sort_values(
            "score"
        )
        if len(ranked) < 6:
            continue
        top = ranked.tail(3)
        bottom = ranked.head(3)
        cohorts.append(
            {
                "entry": pd.Timestamp(entry),
                "raw_ls": 0.5
                * (top["target_return"].mean() - bottom["target_return"].mean()),
                "res_ls": 0.5
                * (top["model_target"].mean() - bottom["model_target"].mean()),
                "res_long": top["model_target"].mean(),
                "raw_long": top["target_return"].mean(),
            }
        )
    frame = pd.DataFrame(cohorts)
    short_cost = 0.0014 + 0.5 * short_borrow_rate * 7.0 / 365.25
    results: list[dict[str, float]] = []
    for column, cost in (
        ("raw_ls", short_cost),
        ("res_ls", short_cost),
        ("res_long", 0.0018),
        ("raw_long", 0.0014),
    ):
        daily = (frame[column] - cost) / 5.0
        results.append(
            {
                "portfolio": column,
                "cohorts": float(len(frame)),
                "cohort_gross": float(frame[column].mean()),
                "cagr_proxy": float(np.prod(1.0 + daily) ** (252.0 / len(daily)) - 1.0),
                "sharpe_proxy": float(daily.mean() / daily.std(ddof=1) * np.sqrt(252.0)),
            }
        )
    return results


def run_probe(root: Path, fold_numbers: list[int], seeds: list[int]) -> None:
    """Obuchaet fiksirovannyi seed-ensemble na development-fold."""
    config = load_daily_experiment_config(root / "configs/sequence_5090_daily_v3.yaml")
    frames = _load_development_frames(root, config.universe.development)
    context = load_daily_context(
        root / "data/processed",
        config.protocol.data_start,
        config.protocol.development_end,
    )
    panel = build_daily_panel(
        frames,
        residual_method="beta",
        market_series=_load_market_series(root),
        external_context=context,
        beta_window=config.protocol.beta_window_sessions,
        beta_min_periods=config.protocol.beta_min_periods,
    )
    features = daily_feature_columns(panel)
    print(f"PANEL rows={len(panel)} features={len(features)}", flush=True)
    for fold_number in fold_numbers:
        fold = config.protocol.folds[fold_number]
        selection_scaler = fit_daily_feature_scaler(panel, fold.train_end, features)
        selection_store = build_daily_sequence_store(
            panel, selection_scaler, config.protocol.sequence_length
        )
        train = select_daily_sequence_samples(
            selection_store,
            config.protocol.data_start,
            fold.train_end,
            purge_exit_before=fold.inner_start,
        )
        inner = select_daily_sequence_samples(
            selection_store,
            fold.inner_start,
            fold.inner_end,
            embargo_sessions=config.protocol.embargo_sessions,
        )
        target_scale = robust_target_scale(train)
        print(
            f"FOLD {fold_number} train={len(train)} inner={len(inner)} "
            f"target_scale={target_scale:.8f}",
            flush=True,
        )
        final_scaler = fit_daily_feature_scaler(panel, fold.inner_end, features)
        final_store = build_daily_sequence_store(
            panel, final_scaler, config.protocol.sequence_length
        )
        final_train = select_daily_sequence_samples(
            final_store,
            config.protocol.data_start,
            fold.inner_end,
            purge_exit_before=fold.outer_start,
        )
        outer = select_daily_sequence_samples(
            final_store,
            fold.outer_start,
            fold.outer_end,
            embargo_sessions=config.protocol.embargo_sessions,
            require_target=False,
        )
        final_scale = robust_target_scale(final_train)
        score_parts: list[np.ndarray] = []
        best_epochs: list[int] = []
        for seed in seeds:
            outcome = fit_with_early_stopping(
                selection_store,
                train,
                inner,
                target_scale,
                config.model.network,
                seed,
            )
            model, _ = fit_fixed_epochs(
                final_store,
                final_train,
                final_scale,
                config.model.network,
                outcome.best_epoch,
                seed,
            )
            score_parts.append(
                predict_sequence_scores(
                    model,
                    final_store,
                    outer,
                    final_scale,
                    config.model.network,
                )
            )
            best_epochs.append(outcome.best_epoch)
            print(
                f"SEED fold={fold_number} seed={seed} best_epoch={outcome.best_epoch} "
                f"inner_ic={outcome.best_validation_ic:.6f}",
                flush=True,
            )
        scores = np.mean(np.stack(score_parts), axis=0)
        metadata = outer.metadata.copy()
        metadata["score"] = scores
        residual_ic = mean_cross_section_ic(
            metadata, scores, target_column="model_target"
        )
        raw_ic = mean_cross_section_ic(metadata, scores, target_column="target_return")
        for result in _portfolio_proxies(
            metadata, config.portfolio.short_borrow_rate_annual
        ):
            print(
                "RESULT "
                f"year={fold.outer_start.year} seeds={seeds} best_epochs={best_epochs} "
                f"ic_residual={residual_ic:.6f} ic_raw={raw_ic:.6f} "
                + " ".join(f"{key}={value}" for key, value in result.items()),
                flush=True,
            )


def main() -> None:
    """Chitaet CLI-argumenty i zapuskaet development-only probe."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--fold", type=int, nargs="+", default=[2, 3])
    parser.add_argument("--seed", type=int, nargs="+", default=[11, 23, 42, 71, 101])
    arguments = parser.parse_args()
    run_probe(arguments.root.resolve(), arguments.fold, arguments.seed)


if __name__ == "__main__":
    main()
