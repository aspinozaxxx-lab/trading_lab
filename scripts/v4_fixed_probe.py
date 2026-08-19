"""Vosproizvodimyi development-only probe pyatnadcati fiksirovannyh pravil v4."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from market_lab.io_utils import atomic_write_text, write_json
from market_lab.sequence.daily import MOSCOW_TIMEZONE, REGULAR_SESSION_OPEN_MINUTE
from market_lab.sequence.daily_backtest import (
    DailyBacktestConfig,
    DailyBacktestResult,
    DailyStrategySpec,
    run_staggered_daily_backtest,
)
from market_lab.sequence.daily_config import DailyExperimentConfig, load_daily_experiment_config
from market_lab.sequence.daily_experiment import load_development_inputs

RULE_DEFINITIONS = {  # Tochno zafiksirovannye formuly development-probe v4.
    "mom20": "return_20",
    "mom60": "return_60",
    "mom120": "return_120",
    "mom_blend": "0.50*return_20 + 0.30*return_60 + 0.20*return_120",
    "mom60_skip5": "(1+return_60)/(1+return_5)-1",
    "quality_momentum": "return_60/volatility_60",
    "relative_momentum": (
        "mean cross-sectional percentile rank of return_20/60/120, centered at zero"
    ),
    "reversal1": "-return_1",
    "reversal5": "-return_5",
    "low_vol20": "negative centered cross-sectional rank of volatility_20",
    "volume_momentum": "return_20*(1+clip(volume_z_20,-1,3))",
    "breakout60": "raw_close/previous_60_session_high-1",
    "blend_imoex_gate": "mom_blend only when as-of IMOEX return_20 > 0",
    "blend_rvi_gate": "mom_blend only when as-of RVI return_20 <= 0",
    "blend_imoex_rvi_gate": "mom_blend only when both fixed gates are active",
}
EXPECTED_FOLD_YEARS = (2022, 2023, 2024, 2025)  # Zafiksirovannye outer-gody probe.
COST_MULTIPLIERS = (1.0, 2.0)  # Bazovye i udvoennye torgovye izderzhki.
TOP_K = 3  # Chislo odnovremenno vybrannyh long-aktivov v kazhdom sleeve.
KEEP_RANK = 6  # Granica actual-fill hysteresis bez znaniya budushchih cen.
TARGET_GROSS_LEVERAGE = 1.0  # Zhestkii gross-limit bez leverage-podgonki.
ANNUALIZATION_FACTOR = 252.0  # Chislo torgovyh sessii dlya annualizacii.
RULE_COUNT = 15  # Zafiksirovannoe chislo pravil bez rasshireniya posle prosmotra rezultata.
SELECTION_WARNING = (  # Obyazatel'noe preduprezhdenie o multiple-testing.
    "All rules were inspected on the same four development folds; selecting the winner is "
    "multiple-testing overfit and is not independent evidence."
)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    """Preobrazuet odnu causal-kolonku v chisla s NaN vmesto oshibok."""
    if column not in frame.columns:
        raise ValueError(f"Net kolonki dlya v4-pravila: {column}")
    return pd.to_numeric(frame[column], errors="coerce")


def _cross_section_rank(values: pd.Series, session_dates: pd.Series) -> pd.Series:
    """Schitaet tol'ko odnovremennyi percentile-rank i centriruet ego okolo nulya."""
    return values.groupby(session_dates).rank(method="average", pct=True) - 0.5


def build_fixed_rule_scores(panel: pd.DataFrame) -> dict[str, pd.Series]:
    """Stroit rovno pyatnadcat causal-score iz istorii, dostupnoi k close tekushchei sessii."""
    ordered = panel.sort_values(["ticker", "session_date"], kind="mergesort").reset_index(
        drop=True
    )
    session_dates = pd.to_datetime(ordered["session_date"], errors="raise")
    return_1 = _numeric(ordered, "return_1")
    return_5 = _numeric(ordered, "return_5")
    return_20 = _numeric(ordered, "return_20")
    return_60 = _numeric(ordered, "return_60")
    return_120 = _numeric(ordered, "return_120")
    volatility_20 = _numeric(ordered, "volatility_20")
    volatility_60 = _numeric(ordered, "volatility_60")
    volume_z_20 = _numeric(ordered, "volume_z_20").clip(-1.0, 3.0)
    blend = 0.50 * return_20 + 0.30 * return_60 + 0.20 * return_120
    safe_return_5 = (1.0 + return_5).where((1.0 + return_5).abs() > 1e-9)
    skip_5 = (1.0 + return_60) / safe_return_5 - 1.0
    quality = return_60 / volatility_60.where(volatility_60 > 1e-8)
    relative = (
        _cross_section_rank(return_20, session_dates)
        + _cross_section_rank(return_60, session_dates)
        + _cross_section_rank(return_120, session_dates)
    ) / 3.0
    low_volatility = -_cross_section_rank(volatility_20, session_dates)
    volume_momentum = return_20 * (1.0 + volume_z_20)
    prior_high_60 = ordered.groupby("ticker", sort=False)["raw_high"].transform(
        lambda values: values.shift(1).rolling(60, min_periods=60).max()
    )
    breakout_60 = _numeric(ordered, "raw_close") / prior_high_60 - 1.0
    imoex_gate = _numeric(ordered, "context_ctx_imoex_ret_20") > 0.0
    rvi_gate = _numeric(ordered, "context_ctx_rvi_ret_20") <= 0.0
    scores = {
        "mom20": return_20,
        "mom60": return_60,
        "mom120": return_120,
        "mom_blend": blend,
        "mom60_skip5": skip_5,
        "quality_momentum": quality,
        "relative_momentum": relative,
        "reversal1": -return_1,
        "reversal5": -return_5,
        "low_vol20": low_volatility,
        "volume_momentum": volume_momentum,
        "breakout60": breakout_60,
        "blend_imoex_gate": blend.where(imoex_gate),
        "blend_rvi_gate": blend.where(rvi_gate),
        "blend_imoex_rvi_gate": blend.where(imoex_gate & rvi_gate),
    }
    if tuple(scores) != tuple(RULE_DEFINITIONS) or len(scores) != RULE_COUNT:
        raise RuntimeError("Nabor v4-pravil otklonilsya ot zafiksirovannogo protokola")
    return scores


def build_fixed_predictions(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Upakovyvaet causal-score v minimal'nuyu skhemu exact daily-backtestera."""
    ordered = panel.sort_values(["ticker", "session_date"], kind="mergesort").reset_index(
        drop=True
    )
    base = ordered.loc[:, ["session_date", "ticker"]]
    predictions: dict[str, pd.DataFrame] = {}
    for rule, score in build_fixed_rule_scores(ordered).items():
        frame = base.copy()
        frame["prediction"] = pd.to_numeric(score, errors="coerce").to_numpy()
        predictions[rule] = frame
    return predictions


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno sohranyaet binarnyi panel v tom zhe kataloge, chto i cel'evyi fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".parquet", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        frame.to_parquet(temporary_path, index=False)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load_or_build_panel(config: DailyExperimentConfig, cache_path: Path) -> pd.DataFrame:
    """Chitaet odin development-cache ili odin raz stroit ego bez asset-holdout."""
    if cache_path.exists():
        panel = pd.read_parquet(cache_path)
    else:
        inputs = load_development_inputs(config)
        panel = inputs.panel
        _atomic_write_parquet(cache_path, panel)
    if panel.empty:
        raise ValueError("Development panel dlya v4-probe pust")
    if int(panel["ticker"].nunique()) != len(config.universe.development):
        raise ValueError("V4-cache ne sootvetstvuet zafiksirovannomu development-universumu")
    return panel.sort_values(["ticker", "session_date"], kind="mergesort").reset_index(
        drop=True
    )


def _validate_fixed_folds(config: DailyExperimentConfig) -> None:
    """Zapreshchaet nezametno menyat' chetyre outer-goda posle prosmotra metrik."""
    years = tuple(fold.outer_start.year for fold in config.protocol.folds)
    if years != EXPECTED_FOLD_YEARS:
        raise ValueError(f"V4 probe trebuet outer-gody {EXPECTED_FOLD_YEARS}, polucheno {years}")


def _backtest_config(
    config: DailyExperimentConfig,
    cost_multiplier: float,
) -> DailyBacktestConfig:
    """Masshtabiruet tol'ko commission i slippage, ne menyaia leverage ili pravilo."""
    return DailyBacktestConfig(
        initial_capital=config.portfolio.initial_capital,
        commission_bps=config.portfolio.commission_bps * cost_multiplier,
        slippage_bps=config.portfolio.slippage_bps * cost_multiplier,
        financing_rate_annual=0.0,
        short_borrow_rate_annual=config.portfolio.short_borrow_rate_annual,
        target_gross_leverage=TARGET_GROSS_LEVERAGE,
        maximum_gross_leverage=TARGET_GROSS_LEVERAGE,
    )


def outer_fold_masks(panel: pd.DataFrame, fold: Any) -> tuple[pd.Series, pd.Series]:
    """Ostavlyaet ves execution-calendar, no purgit signaly bez vyhoda vnutri fold."""
    session_dates = pd.to_datetime(panel["session_date"], errors="raise")
    execution_mask = session_dates.between(
        pd.Timestamp(fold.outer_start), pd.Timestamp(fold.outer_end)
    )
    if "exit_time" not in panel.columns:
        raise ValueError("V4 panel ne soderzhit exit_time dlya terminal purge")
    boundary = (
        (pd.Timestamp(fold.outer_end) + pd.Timedelta(days=1))
        .tz_localize(MOSCOW_TIMEZONE)
        + pd.Timedelta(minutes=REGULAR_SESSION_OPEN_MINUTE)
    ).tz_convert("UTC")
    exit_times = pd.to_datetime(panel["exit_time"], utc=True, errors="coerce")
    signal_mask = execution_mask & exit_times.lt(boundary)
    return execution_mask, signal_mask


def _fold_metric_row(
    rule: str,
    cost_multiplier: float,
    fold_number: int,
    fold: Any,
    result: DailyBacktestResult,
) -> dict[str, Any]:
    """Preobrazuet odin event-driven rezultat v stabil'nuyu stroku fold-tablicy."""
    metrics = result.metrics
    return {
        "rule": rule,
        "cost_multiplier": cost_multiplier,
        "fold": fold_number,
        "outer_start": str(fold.outer_start),
        "outer_end": str(fold.outer_end),
        "cagr": metrics["annualized_return"],
        "sharpe": metrics["sharpe"],
        "max_drawdown": metrics["max_drawdown"],
        "total_return": metrics["total_return"],
        "turnover": metrics["turnover"],
        "trade_count": metrics["trade_count"],
        "total_cost": metrics["total_cost"],
        "maximum_participation": metrics["maximum_participation"],
        "execution_complete": bool(metrics["execution_complete"]),
        "missing_entry_count": metrics["missing_entry_count"],
        "missing_rebalance_count": metrics["missing_rebalance_count"],
        "missing_exit_count": metrics["missing_exit_count"],
        "unresolved_exit_count": metrics["unresolved_exit_count"],
        "open_position_count": metrics["open_position_count"],
    }


def _aggregate_metrics(
    rule: str,
    cost_multiplier: float,
    results: Sequence[DailyBacktestResult],
    initial_capital: float,
) -> dict[str, Any]:
    """Posledovatel'no compoudit out-of-sample fold-returns bez perenosa pozicii."""
    returns = np.concatenate(
        [
            pd.to_numeric(result.ledger["net_return"], errors="coerce")
            .fillna(0.0)
            .to_numpy(dtype=float)
            for result in results
        ]
    )
    equity = initial_capital * np.cumprod(1.0 + returns)
    curve = np.concatenate(([initial_capital], equity))
    running_peak = np.maximum.accumulate(curve)
    final_ratio = float(equity[-1] / initial_capital)
    standard_deviation = float(np.std(returns, ddof=1)) if len(returns) >= 2 else 0.0
    sharpe = (
        float(np.sqrt(ANNUALIZATION_FACTOR) * np.mean(returns) / standard_deviation)
        if standard_deviation > 1e-12
        else 0.0
    )
    sum_keys = (
        "turnover",
        "trade_count",
        "total_cost",
        "missing_entry_count",
        "missing_rebalance_count",
        "missing_exit_count",
        "unresolved_exit_count",
        "invalid_participation_count",
        "open_position_count",
    )
    totals = {
        key: sum(float(result.metrics[key]) for result in results) for key in sum_keys
    }
    return {
        "rule": rule,
        "cost_multiplier": cost_multiplier,
        "cagr": final_ratio ** (ANNUALIZATION_FACTOR / max(len(returns), 1)) - 1.0,
        "sharpe": sharpe,
        "max_drawdown": float(np.max(1.0 - curve / running_peak)),
        "total_return": final_ratio - 1.0,
        "periods": len(returns),
        "turnover": totals["turnover"],
        "trade_count": int(totals["trade_count"]),
        "total_cost": totals["total_cost"],
        "maximum_participation": max(
            float(result.metrics["maximum_participation"]) for result in results
        ),
        "execution_complete": all(result.execution_complete for result in results)
        and totals["open_position_count"] == 0.0,
        "missing_entry_count": int(totals["missing_entry_count"]),
        "missing_rebalance_count": int(totals["missing_rebalance_count"]),
        "missing_exit_count": int(totals["missing_exit_count"]),
        "unresolved_exit_count": int(totals["unresolved_exit_count"]),
        "invalid_participation_count": int(totals["invalid_participation_count"]),
        "open_position_count": int(totals["open_position_count"]),
    }


def _sha256(path: Path) -> str:
    """Vozvrashchaet polnyi SHA-256 dlya audit-svyazi skripta, config i cache."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_fixed_probe(config_path: Path, cache_path: Path, output_dir: Path) -> None:
    """Vypolnyaet konechnyi nabor exact long-only backtestov i atomarno pishet artefakty."""
    started = time.perf_counter()
    config = load_daily_experiment_config(config_path)
    _validate_fixed_folds(config)
    panel = _load_or_build_panel(config, cache_path)
    predictions_by_rule = build_fixed_predictions(panel)
    strategy = DailyStrategySpec(
        position_mode="long_only",
        top_k=TOP_K,
        keep_rank=KEEP_RANK,
        minimum_score=0.0,
    )
    fold_rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    equity_parts: list[pd.DataFrame] = []
    for rule, all_predictions in predictions_by_rule.items():
        for cost_multiplier in COST_MULTIPLIERS:
            results: list[DailyBacktestResult] = []
            for fold_number, fold in enumerate(config.protocol.folds):
                execution_mask, signal_mask = outer_fold_masks(panel, fold)
                result = run_staggered_daily_backtest(
                    all_predictions.loc[signal_mask].copy(),
                    panel.loc[execution_mask].copy(),
                    strategy,
                    _backtest_config(config, cost_multiplier),
                )
                results.append(result)
                fold_rows.append(
                    _fold_metric_row(rule, cost_multiplier, fold_number, fold, result)
                )
                equity = result.ledger.loc[:, ["session_date", "equity"]].copy()
                equity["rule"] = rule
                equity["cost_multiplier"] = cost_multiplier
                equity["fold"] = fold_number
                equity_parts.append(equity)
            aggregate_rows.append(
                _aggregate_metrics(
                    rule,
                    cost_multiplier,
                    results,
                    config.portfolio.initial_capital,
                )
            )
        print(f"completed {rule}", flush=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    fold_frame = pd.DataFrame(fold_rows)
    aggregate_frame = pd.DataFrame(aggregate_rows).sort_values(
        ["cost_multiplier", "sharpe", "cagr"],
        ascending=[True, False, False],
        kind="mergesort",
    )
    equity_frame = pd.concat(equity_parts, ignore_index=True)
    atomic_write_text(output_dir / "long_only_fold_metrics.csv", fold_frame.to_csv(index=False))
    atomic_write_text(
        output_dir / "long_only_aggregate_metrics.csv", aggregate_frame.to_csv(index=False)
    )
    atomic_write_text(
        output_dir / "long_only_fold_equities.csv", equity_frame.to_csv(index=False)
    )
    write_json(
        output_dir / "probe_manifest.json",
        {
            "script_sha256": _sha256(Path(__file__).resolve()),
            "config_sha256": _sha256(config_path),
            "panel_sha256": _sha256(cache_path),
            "panel_rows": len(panel),
            "panel_columns": len(panel.columns),
            "development_tickers": int(panel["ticker"].nunique()),
            "rules_checked": len(RULE_DEFINITIONS),
            "backtests_run": len(RULE_DEFINITIONS)
            * len(config.protocol.folds)
            * len(COST_MULTIPLIERS),
            "position_mode": "long_only",
            "top_k": TOP_K,
            "keep_rank": KEEP_RANK,
            "gross_leverage": TARGET_GROSS_LEVERAGE,
            "base_commission_bps": config.portfolio.commission_bps,
            "base_slippage_bps": config.portfolio.slippage_bps,
            "cost_multipliers": COST_MULTIPLIERS,
            "fold_years": EXPECTED_FOLD_YEARS,
            "definitions": RULE_DEFINITIONS,
            "selection_warning": SELECTION_WARNING,
            "elapsed_seconds": time.perf_counter() - started,
        },
    )


def main() -> None:
    """Chitaet obyazatel'nye config/cache/output argumenty i zapuskaet fixed probe."""
    parser = argparse.ArgumentParser(
        description="Development-only exact probe pyatnadcati zafiksirovannyh pravil."
    )
    parser.add_argument("--config", type=Path, required=True, help="Put k daily v3 YAML.")
    parser.add_argument(
        "--cache",
        type=Path,
        required=True,
        help="Put k development_panel.parquet; pri otsutstvii stroitsya odin raz.",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Katalog atomarnyh CSV/JSON rezultatov."
    )
    arguments = parser.parse_args()
    run_fixed_probe(
        arguments.config.resolve(),
        arguments.cache.resolve(),
        arguments.output.resolve(),
    )


if __name__ == "__main__":
    main()
