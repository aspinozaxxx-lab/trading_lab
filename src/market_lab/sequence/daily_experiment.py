"""Development-only orchestration daily residual-TCN bez dostupa k holdout."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from market_lab.backtest.metrics import calculate_metrics
from market_lab.data.moex import validate_market_frame
from market_lab.io_utils import TEXT_ENCODING
from market_lab.logging_config import configure_logging
from market_lab.reporting.artifacts import ArtifactWriter, create_run_directory
from market_lab.sequence.context import DEFAULT_CONTEXT_SPECS, load_daily_context
from market_lab.sequence.daily import (
    MAIN_SESSION_LAST_BAR_MINUTE,
    MAIN_SESSION_START_MINUTE,
    MOSCOW_TIMEZONE,
    build_daily_panel,
    build_daily_sequence_store,
    daily_feature_columns,
    fit_daily_feature_scaler,
    select_daily_sequence_samples,
)
from market_lab.sequence.daily_backtest import (
    DailyBacktestConfig,
    DailyBacktestResult,
    DailyStrategySpec,
    run_staggered_daily_backtest,
)
from market_lab.sequence.daily_config import (
    DailyExperimentConfig,
    DailyFoldConfig,
    daily_config_as_dict,
    load_daily_experiment_config,
)
from market_lab.sequence.dataset import SequenceSamples, robust_target_scale

LOGGER = logging.getLogger(__name__)  # Logger development-only daily-eksperimenta.
TRADING_DAYS_PER_YEAR = 252  # Baza annualizacii aggregate daily returns.
ORIGINAL_DEVELOPMENT = (  # Edinstvennyi razreshennyi universum etoi komandy.
    "SBER",
    "GAZP",
    "LKOH",
    "NVTK",
    "ROSN",
    "TATN",
    "MOEX",
    "VTBR",
    "CHMF",
    "PHOR",
    "RUAL",
    "ALRS",
    "MAGN",
    "NLMK",
    "SNGS",
    "MGNT",
    "GMKN",
    "PLZL",
    "SBERP",
    "TATNP",
    "AFKS",
    "AFLT",
    "BSPB",
    "CBOM",
    "ENPG",
    "IRAO",
    "MTSS",
    "RTKM",
    "SNGSP",
    "TRNFP",
)
REQUIRED_DEVELOPMENT_ARTIFACTS = frozenset(  # Minimal'nyi proveriaemyi nabor run-a.
    {
        "resolved_config.yaml",
        "frozen_protocol_sha256.json",
        "frozen_protocol_sha256.txt",
        "frozen_config_sha256.json",
        "frozen_config_sha256.txt",
        "development_data_manifest.csv",
        "context_data_manifest.csv",
        "model_architecture.json",
        "feature_list.json",
        "scaler_manifests.json",
        "training_histories.csv",
        "training_summary.csv",
        "ensemble_predictions.csv",
        "fold_metrics.csv",
        "ledgers.csv",
        "orders.csv",
        "weights.csv",
        "stress_ledgers.csv",
        "aggregate_equity.csv",
        "aggregate_metrics.json",
        "protocol_conformity.json",
        "pre_holdout_gates.json",
        "report.md",
        "equity_curve.png",
        "run.log",
        "seed.json",
    }
)
DIAGNOSTIC_PROTOCOL_CONFORMITY = {  # Fail-closed razryv s frozen primary-portfolio.
    "primary_long_top3_implemented": False,
    "beta_hedge_implemented": False,
    "volatility_target_implemented": False,
}


@dataclass(frozen=True)
class DevelopmentInputs:
    """Hranit tol'ko development-panel i proveriaemye manifesty ego istochnikov."""

    panel: pd.DataFrame
    data_manifest: pd.DataFrame
    context_manifest: pd.DataFrame


@dataclass(frozen=True)
class FoldOutcome:
    """Hranit ensemble-prognoz i tri diagnostic L/S scenariya outer-fold."""

    predictions: pd.DataFrame
    diagnostic_long_short: DailyBacktestResult
    diagnostic_double_cost: DailyBacktestResult
    diagnostic_delayed_entry: DailyBacktestResult
    outer_ic: float


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 faila bez ego izmeneniya."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _assert_development_universe(config: DailyExperimentConfig) -> None:
    """Zapreshchaet podmenu original30 ili sluchainyi dostup k frozen holdout."""
    if tuple(config.universe.development) != ORIGINAL_DEVELOPMENT:
        raise ValueError("sequence-daily-development trebuet tochnyi original30 universum")
    forbidden = set(config.universe.frozen_holdout)
    overlap = forbidden & set(ORIGINAL_DEVELOPMENT)
    if overlap:
        raise ValueError(f"Frozen holdout peresekaetsya s development: {sorted(overlap)}")


def _protocol_seal(project_root: Path) -> dict[str, object]:
    """Proveryaet frozen YAML po zafiksirovannomu SHA do chteniya kotirovok."""
    protocol_path = project_root / "configs" / "sequence_v3_protocol.yaml"
    declared_path = project_root / "configs" / "sequence_v3_protocol.sha256"
    if not protocol_path.exists() or not declared_path.exists():
        raise FileNotFoundError("Net frozen daily protocol ili ego SHA-faila")
    declared_line = declared_path.read_text(encoding=TEXT_ENCODING).strip()
    declared = declared_line.split()[0].lower() if declared_line else ""
    computed = _sha256_file(protocol_path)
    if declared != computed:
        raise ValueError(
            f"Frozen protocol SHA ne sovpal: declared={declared}, computed={computed}"
        )
    return {
        "protocol_path": str(protocol_path),
        "declared_sha256": declared,
        "computed_sha256": computed,
        "verified": True,
        "holdout_accessed": False,
    }


def _config_seal(
    config: DailyExperimentConfig,
    project_root: Path,
) -> dict[str, object]:
    """Privyazyvaet runtime-config k exact zapechatannomu daily YAML."""
    config_path = project_root / "configs" / "sequence_5090_daily_v3.yaml"
    declared_path = project_root / "configs" / "sequence_5090_daily_v3.sha256"
    if not config_path.exists() or not declared_path.exists():
        raise FileNotFoundError("Net frozen daily config ili ego SHA-faila")
    declared_line = declared_path.read_text(encoding=TEXT_ENCODING).strip()
    declared = declared_line.split()[0].lower() if declared_line else ""
    computed = _sha256_file(config_path)
    if declared != computed:
        raise ValueError(
            f"Frozen daily config SHA ne sovpal: declared={declared}, computed={computed}"
        )
    sealed_config = load_daily_experiment_config(config_path)
    if daily_config_as_dict(config) != daily_config_as_dict(sealed_config):
        raise ValueError("Runtime daily config ne sovpadaet s zapechatannym config")
    return {
        "config_path": str(config_path),
        "declared_sha256": declared,
        "computed_sha256": computed,
        "verified": True,
        "runtime_config_matches": True,
        "holdout_accessed": False,
    }


def _read_sealed_protocol(seal: Mapping[str, object]) -> dict[str, Any]:
    """Povtorno proveriaet hash i chitaet imenno zapechatannyi protocol."""
    path = Path(str(seal["protocol_path"]))
    raw = path.read_bytes()
    computed = hashlib.sha256(raw).hexdigest()
    if computed != str(seal["computed_sha256"]):
        raise ValueError("Frozen protocol izmenilsya posle pervonachal'noi proverki")
    document = yaml.safe_load(raw.decode(TEXT_ENCODING))
    if not isinstance(document, dict):
        raise ValueError("Frozen protocol dolzhen byt YAML-mapping")
    return document


def _expected_fold_boundaries(document: Mapping[str, Any]) -> list[dict[str, date]]:
    """Preobrazuet frozen godovye fold-opisaniya v tochnye kalendarnye granicy."""
    result: list[dict[str, date]] = []
    for item in document.get("development_folds", []):
        if not isinstance(item, Mapping):
            return []
        try:
            train_end_year = int(str(item["train"]).split("-")[-1])
            inner_year = int(str(item["inner"]))
            outer_year = int(str(item["outer"]))
        except (KeyError, TypeError, ValueError):
            return []
        result.append(
            {
                "train_end": date(train_end_year, 12, 31),
                "inner_start": date(inner_year, 1, 1),
                "inner_end": date(inner_year, 12, 31),
                "outer_start": date(outer_year, 1, 1),
                "outer_end": date(outer_year, 12, 31),
            }
        )
    return result


def _config_protocol_correspondence(
    config: DailyExperimentConfig,
    seal: Mapping[str, object],
) -> dict[str, bool]:
    """Sveriaet mutable config s semantikoi proverennogo frozen protocol."""
    document = _read_sealed_protocol(seal)
    data = document.get("data", {})
    target = document.get("target", {})
    model = document.get("model", {})
    portfolio = document.get("portfolio", {})
    frozen_gates = document.get("pre_holdout_gates", {})
    stretch = document.get("stretch_gate", {})
    expected_folds = _expected_fold_boundaries(document)
    actual_folds = [fold.model_dump() for fold in config.protocol.folds]
    expected_holdout = list(data.get("frozen_asset_holdout", []))
    configured_holdout = config.universe.frozen_holdout

    def same_number(actual: float, expected: object) -> bool:
        """Sravnivaet chisla bez dopuska prakticheski znachimoi podmeny."""
        try:
            return bool(np.isclose(float(actual), float(expected), rtol=0.0, atol=1e-12))
        except (TypeError, ValueError):
            return False

    return {
        "verified_protocol_reloaded": bool(seal.get("verified")),
        "development_universe": list(config.universe.development)
        == list(data.get("development", [])),
        "frozen_holdout_universe": set(configured_holdout) == set(expected_holdout)
        and len(configured_holdout) == len(expected_holdout),
        "data_start": config.protocol.data_start
        == date.fromisoformat(str(data.get("start"))),
        "development_end": config.protocol.development_end
        == date.fromisoformat(str(data.get("development_end"))),
        "fold_boundaries": actual_folds == expected_folds,
        "fold_count": len(actual_folds) == int(frozen_gates.get("fold_count", -1)),
        "sequence_length": config.protocol.sequence_length
        == int(model.get("daily_sequence_sessions", -1)),
        "holding_sessions": config.protocol.horizon_sessions
        == int(target.get("holding_sessions", -1)),
        "embargo_sessions": config.protocol.embargo_sessions
        == int(target.get("holding_sessions", -1)),
        "beta_window_sessions": config.protocol.beta_window_sessions
        == int(target.get("beta_window_sessions", -1)),
        "beta_residual_target": target.get("kind")
        == "rolling_beta_market_residual_open_to_open"
        and target.get("benchmark") == "IMOEX",
        "seed_ensemble": list(config.model.seeds) == list(model.get("seeds", [])),
        "arithmetic_mean_ensemble": model.get("ensemble")
        == "arithmetic_mean_without_seed_selection",
        "top_k": config.portfolio.top_k == int(portfolio.get("long_top_k", -1)),
        "keep_rank": config.portfolio.keep_rank
        == int(portfolio.get("long_keep_rank", -1)),
        "staggered_sleeves": config.portfolio.staggered_sleeves
        == int(portfolio.get("staggered_sleeves", -1)),
        "gross_leverage": same_number(
            config.portfolio.stock_gross_leverage,
            portfolio.get("stock_gross_leverage"),
        ),
        "commission_bps": same_number(
            config.portfolio.commission_bps,
            portfolio.get("commission_bps"),
        ),
        "slippage_bps": same_number(
            config.portfolio.slippage_bps,
            portfolio.get("slippage_bps"),
        ),
        "diagnostic_borrow_rate": same_number(
            config.portfolio.short_borrow_rate_annual,
            0.20,
        ),
        "diagnostic_minimum_score": same_number(
            config.portfolio.minimum_score_bps,
            0.0,
        ),
        "minimum_mean_rank_ic": same_number(
            config.gates.minimum_mean_rank_ic,
            frozen_gates.get("minimum_mean_rank_ic"),
        ),
        "minimum_positive_ic_folds": config.gates.minimum_positive_ic_folds
        == int(frozen_gates.get("minimum_positive_ic_folds", -1)),
        "minimum_aggregate_sharpe": same_number(
            config.gates.minimum_aggregate_sharpe,
            frozen_gates.get("minimum_aggregate_net_sharpe"),
        ),
        "minimum_median_fold_sharpe": same_number(
            config.gates.minimum_median_fold_sharpe,
            frozen_gates.get("minimum_median_fold_sharpe"),
        ),
        "minimum_worst_fold_sharpe": same_number(
            config.gates.minimum_worst_fold_sharpe,
            frozen_gates.get("minimum_worst_fold_sharpe"),
        ),
        "maximum_drawdown": same_number(
            config.gates.maximum_drawdown,
            frozen_gates.get("maximum_drawdown"),
        ),
        "target_cagr": same_number(
            config.gates.target_cagr,
            stretch.get("minimum_core_cagr"),
        ),
    }


def _development_cache_path(config: DailyExperimentConfig, ticker: str) -> Path:
    """Stroit exact put tol'ko dlya razreshennogo development-tickera."""
    normalized = ticker.upper()
    if normalized not in ORIGINAL_DEVELOPMENT:
        raise PermissionError(f"Zapreshchen non-development ticker: {normalized}")
    protocol = config.protocol
    stem = (
        f"{normalized}_{config.universe.board}_10m_"
        f"{protocol.data_start.isoformat()}_{protocol.development_end.isoformat()}.parquet"
    )
    return config.paths.processed_data_dir / "sequence_10m" / stem


def _context_cache_path(config: DailyExperimentConfig, ticker: str, board: str) -> Path:
    """Stroit exact put razreshennogo obshcherynochnogo context-kesha."""
    protocol = config.protocol
    stem = (
        f"{ticker}_{board}_10m_"
        f"{protocol.data_start.isoformat()}_{protocol.development_end.isoformat()}.parquet"
    )
    return config.paths.processed_data_dir / "sequence_context" / stem


def _local_date_mask(index: pd.DatetimeIndex, end_date: date) -> np.ndarray:
    """Ogranichivaet frame po moskovskoi date bez UTC-off-by-one."""
    local_dates = index.tz_convert(MOSCOW_TIMEZONE).tz_localize(None).normalize()
    return np.asarray(local_dates <= pd.Timestamp(end_date), dtype=bool)


def _load_development_frames(
    config: DailyExperimentConfig,
    end_date: date,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Chitaet exact original30 cache-path i nikogda ne enumeriruet holdout."""
    frames: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for ticker in ORIGINAL_DEVELOPMENT:
        path = _development_cache_path(config, ticker)
        if not path.exists():
            raise FileNotFoundError(f"Net development-kesha dlya {ticker}: {path}")
        full = validate_market_frame(pd.read_parquet(path))
        used = full.loc[_local_date_mask(full.index, end_date)]
        if used.empty:
            raise ValueError(f"Pustoi development-kesh dlya {ticker}")
        frames[ticker] = used
        rows.append(
            {
                "ticker": ticker,
                "path": str(path),
                "sha256": _sha256_file(path),
                "rows_used": len(used),
                "first_timestamp_used": used.index.min(),
                "last_timestamp_used": used.index.max(),
            }
        )
    return frames, pd.DataFrame(rows)


def _load_imoex_market_series(
    config: DailyExperimentConfig,
    end_date: date,
) -> pd.Series:
    """Stroit daily IMOEX open iz razreshennogo context-kesha."""
    spec = next(item for item in DEFAULT_CONTEXT_SPECS if item.ticker == "IMOEX")
    path = _context_cache_path(config, spec.ticker, spec.board)
    if not path.exists():
        raise FileNotFoundError(f"Net IMOEX context-kesha: {path}")
    frame = pd.read_parquet(path)
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("IMOEX context-kesh dolzhen imet timezone-aware index")
    frame = frame.loc[_local_date_mask(frame.index, end_date)]
    local = frame.index.tz_convert(MOSCOW_TIMEZONE)
    minute = local.hour * 60 + local.minute
    main = frame.loc[
        (minute >= MAIN_SESSION_START_MINUTE) & (minute <= MAIN_SESSION_LAST_BAR_MINUTE)
    ].copy()
    main["session_date"] = local[
        (minute >= MAIN_SESSION_START_MINUTE) & (minute <= MAIN_SESSION_LAST_BAR_MINUTE)
    ].tz_localize(None).normalize()
    market = main.groupby("session_date", sort=True)["open"].first().astype(float)
    if market.empty or (market <= 0.0).any():
        raise ValueError("IMOEX daily market-series pust ili nevaliden")
    return market


def _load_context_inputs(
    config: DailyExperimentConfig,
    end_date: date,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Chitaet tol'ko frozen context-instrumenty i ih audit-manifest."""
    context = load_daily_context(
        config.paths.processed_data_dir,
        config.protocol.data_start,
        config.protocol.development_end,
    )
    context_local_dates = context.index.tz_convert(MOSCOW_TIMEZONE).tz_localize(
        None
    ).normalize()
    context = context.loc[context_local_dates <= pd.Timestamp(end_date)]
    rows: list[dict[str, object]] = []
    for spec in DEFAULT_CONTEXT_SPECS:
        path = _context_cache_path(config, spec.ticker, spec.board)
        if not path.exists():
            raise FileNotFoundError(f"Net context-kesha dlya {spec.ticker}: {path}")
        rows.append(
            {
                "ticker": spec.ticker,
                "board": spec.board,
                "path": str(path),
                "sha256": _sha256_file(path),
            }
        )
    return context, _load_imoex_market_series(config, end_date), pd.DataFrame(rows)


def load_development_inputs(config: DailyExperimentConfig) -> DevelopmentInputs:
    """Stroit beta-residual panel tol'ko iz original30 i publichnogo context."""
    _assert_development_universe(config)
    panel_end = config.protocol.folds[-1].outer_end
    frames, data_manifest = _load_development_frames(config, panel_end)
    context, market_series, context_manifest = _load_context_inputs(config, panel_end)
    panel = build_daily_panel(
        frames,
        horizon_sessions=config.protocol.horizon_sessions,
        residual_method="beta",
        market_series=market_series,
        external_context=context,
        beta_window=config.protocol.beta_window_sessions,
        beta_min_periods=config.protocol.beta_min_periods,
    )
    return DevelopmentInputs(
        panel=panel,
        data_manifest=data_manifest,
        context_manifest=context_manifest,
    )


def _exclusive_end_boundary(day: date) -> date:
    """Vozvrashchaet kalendarnuyu exclusive-granicu posle poslednego dnya fold."""
    return day + timedelta(days=1)


def _prediction_frame(samples: SequenceSamples, scores: np.ndarray) -> pd.DataFrame:
    """Obedinyaet causal sample-metadannye s odnim vektorom score."""
    if len(samples) != len(scores):
        raise ValueError("Chislo daily-score ne sovpadaet s outer-samples")
    result = samples.metadata.copy()
    signal = pd.to_datetime(result["timestamp"], utc=True).dt.tz_convert(MOSCOW_TIMEZONE)
    result["session_date"] = signal.dt.tz_localize(None).dt.normalize()
    result["prediction"] = scores
    return result


def _daily_strategy(config: DailyExperimentConfig) -> DailyStrategySpec:
    """Stroit zafiksirovannyi diagnostic long-short top3/bottom3."""
    return DailyStrategySpec(
        position_mode="long_short",
        top_k=config.portfolio.top_k,
        minimum_score=config.portfolio.minimum_score_bps / 10_000.0,
        keep_rank=config.portfolio.keep_rank,
    )


def _backtest_config(
    config: DailyExperimentConfig,
    cost_multiplier: float,
) -> DailyBacktestConfig:
    """Sopostavlyaet frozen portfolio-parametry s event-driven dvizhkom."""
    if cost_multiplier <= 0.0:
        raise ValueError("cost_multiplier dolzhen byt polozhitel'nym")
    return DailyBacktestConfig(
        initial_capital=config.portfolio.initial_capital,
        commission_bps=config.portfolio.commission_bps * cost_multiplier,
        slippage_bps=config.portfolio.slippage_bps * cost_multiplier,
        financing_rate_annual=0.0,
        short_borrow_rate_annual=config.portfolio.short_borrow_rate_annual,
        target_gross_leverage=config.portfolio.stock_gross_leverage,
        maximum_gross_leverage=config.portfolio.stock_gross_leverage,
    )


def delay_predictions_one_session(
    predictions: pd.DataFrame,
    execution_panel: pd.DataFrame,
    horizon_sessions: int = 5,
) -> pd.DataFrame:
    """Sdvigaet frozen signal na odnu session i otbrasyvaet nezakryvaemyi hvost."""
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(execution_panel["session_date"]).unique()))
    next_session = {
        pd.Timestamp(calendar[position]): pd.Timestamp(calendar[position + 1])
        for position in range(len(calendar) - 1)
    }
    last_signal_position = len(calendar) - horizon_sessions - 2
    allowed = set(calendar[: max(last_signal_position + 1, 0)])
    delayed = predictions.copy()
    delayed["original_session_date"] = pd.to_datetime(delayed["session_date"])
    delayed["session_date"] = delayed["original_session_date"].map(next_session)
    delayed = delayed.loc[delayed["session_date"].isin(allowed)].copy()
    return delayed.reset_index(drop=True)


def _execution_panel(
    panel: pd.DataFrame,
    fold: DailyFoldConfig,
) -> pd.DataFrame:
    """Ostavlyaet factual execution-calendar tol'ko tekushchego outer-fold."""
    sessions = pd.to_datetime(panel["session_date"])
    mask = sessions.between(pd.Timestamp(fold.outer_start), pd.Timestamp(fold.outer_end))
    result = panel.loc[mask].copy()
    if result.empty:
        raise ValueError(f"Pustoi execution-panel za {fold.outer_start}..{fold.outer_end}")
    return result


def _run_fold_backtests(
    predictions: pd.DataFrame,
    panel: pd.DataFrame,
    fold: DailyFoldConfig,
    config: DailyExperimentConfig,
) -> tuple[DailyBacktestResult, DailyBacktestResult, DailyBacktestResult]:
    """Schitaet diagnostic L/S, 2x costs i zaderzhku bez podbora."""
    execution = _execution_panel(panel, fold)
    spec = _daily_strategy(config)
    diagnostic = run_staggered_daily_backtest(
        predictions,
        execution,
        spec,
        _backtest_config(config, 1.0),
    )
    double_cost = run_staggered_daily_backtest(
        predictions,
        execution,
        spec,
        _backtest_config(config, 2.0),
    )
    delayed = delay_predictions_one_session(
        predictions,
        execution,
        horizon_sessions=config.protocol.horizon_sessions,
    )
    delayed_result = run_staggered_daily_backtest(
        delayed,
        execution,
        spec,
        _backtest_config(config, 1.0),
    )
    return diagnostic, double_cost, delayed_result


def aggregate_daily_returns(
    ledgers: Mapping[str, pd.DataFrame],
    initial_capital: float,
) -> tuple[pd.DataFrame, dict[str, float | int | bool]]:
    """Posledovatel'no compaundit neperesekayushchiesya outer daily returns."""
    if not ledgers:
        raise ValueError("Net fold-ledger dlya aggregate")
    parts: list[pd.DataFrame] = []
    for fold_name, ledger in ledgers.items():
        required = {
            "session_date",
            "net_return",
            "turnover",
            "trade_count",
            "commission_cost",
            "slippage_cost",
            "financing_cost",
            "short_borrow_cost",
        }
        missing = required - set(ledger.columns)
        if missing:
            raise ValueError(f"Fold-ledger ne soderzhit kolonki: {sorted(missing)}")
        part = ledger.copy()
        part["fold"] = fold_name
        parts.append(part)
    combined = pd.concat(parts, ignore_index=True).sort_values(
        "session_date", kind="mergesort"
    )
    if combined["session_date"].duplicated().any():
        raise ValueError("Outer fold-ledgers peresekayutsya po session_date")
    returns = pd.to_numeric(combined["net_return"], errors="raise").astype(float)
    combined["equity"] = initial_capital * (1.0 + returns).cumprod()
    first_date = pd.Timestamp(combined["session_date"].min()) - pd.Timedelta(days=1)
    equity = pd.concat(
        [
            pd.Series([initial_capital], index=[first_date], dtype=float),
            combined.set_index("session_date")["equity"],
        ]
    )
    commission = float(combined["commission_cost"].sum())
    slippage = float(combined["slippage_cost"].sum())
    financing = float(combined["financing_cost"].sum())
    borrow = float(combined["short_borrow_cost"].sum())
    metrics = calculate_metrics(
        equity=equity,
        returns=returns,
        initial_capital=initial_capital,
        annualization_factor=TRADING_DAYS_PER_YEAR,
        turnover=float(combined["turnover"].sum()),
        trade_count=int(combined["trade_count"].sum()),
        commission_cost=commission,
        slippage_cost=slippage,
    )
    metrics.update(
        {
            "financing_cost": financing,
            "short_borrow_cost": borrow,
            "total_cost": commission + slippage + financing + borrow,
            "daily_observations": len(returns),
        }
    )
    return combined.reset_index(drop=True), metrics


def evaluate_pre_holdout_gates(
    config: DailyExperimentConfig,
    fold_metrics: pd.DataFrame,
    aggregate_metrics: Mapping[str, Mapping[str, Any]],
    protocol_conformity: Mapping[str, bool] | None = None,
    config_protocol_correspondence: Mapping[str, bool] | None = None,
) -> dict[str, object]:
    """Primenaet frozen gates i nikogda ne vyzyvaet holdout-loader."""
    required_scenarios = {
        "diagnostic_long_short",
        "diagnostic_double_cost",
        "diagnostic_delayed_entry",
    }
    if required_scenarios - set(aggregate_metrics):
        raise ValueError("Aggregate metrics ne soderzhat vse stress-scenarii")
    if fold_metrics.empty:
        raise ValueError("Fold metrics pusty")
    outer_ic = pd.to_numeric(fold_metrics["outer_ic"], errors="coerce")
    fold_sharpe = pd.to_numeric(
        fold_metrics["diagnostic_long_short_sharpe"], errors="coerce"
    )
    diagnostic = aggregate_metrics["diagnostic_long_short"]
    double_cost = aggregate_metrics["diagnostic_double_cost"]
    delayed = aggregate_metrics["diagnostic_delayed_entry"]
    conformity = dict(protocol_conformity or DIAGNOSTIC_PROTOCOL_CONFORMITY)
    correspondence = dict(config_protocol_correspondence or {})
    participation_columns = [
        "diagnostic_long_short_maximum_participation",
        "diagnostic_double_cost_maximum_participation",
        "diagnostic_delayed_entry_maximum_participation",
    ]
    invalid_participation_columns = [
        "diagnostic_long_short_invalid_participation_count",
        "diagnostic_double_cost_invalid_participation_count",
        "diagnostic_delayed_entry_invalid_participation_count",
    ]
    participation = fold_metrics[participation_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    invalid_participation = fold_metrics[invalid_participation_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    gates = config.gates
    checks = {
        "mean_rank_ic": float(outer_ic.mean()) >= gates.minimum_mean_rank_ic,
        "positive_ic_fold_count": int(outer_ic.gt(0.0).sum())
        >= gates.minimum_positive_ic_folds,
        "diagnostic_aggregate_sharpe": float(diagnostic["sharpe"])
        >= gates.minimum_aggregate_sharpe,
        "median_fold_sharpe": float(fold_sharpe.median())
        >= gates.minimum_median_fold_sharpe,
        "worst_fold_sharpe": float(fold_sharpe.min())
        >= gates.minimum_worst_fold_sharpe,
        "positive_diagnostic_return": float(diagnostic["annualized_return"]) > 0.0,
        "diagnostic_maximum_drawdown": float(diagnostic["max_drawdown"])
        <= gates.maximum_drawdown,
        "positive_diagnostic_double_cost_return": float(
            double_cost["annualized_return"]
        )
        > 0.0,
        "positive_diagnostic_delayed_entry_return": float(
            delayed["annualized_return"]
        )
        > 0.0,
        "all_execution_complete": bool(
            fold_metrics[
                [
                    "diagnostic_long_short_execution_complete",
                    "diagnostic_double_cost_execution_complete",
                    "diagnostic_delayed_entry_execution_complete",
                ]
            ]
            .astype(bool)
            .to_numpy()
            .all()
        ),
        "all_participation_known": bool(
            np.isfinite(participation.to_numpy(dtype=float)).all()
            and invalid_participation.eq(0.0).to_numpy().all()
        ),
        "diagnostic_maximum_participation": float(participation.max().max())
        <= 0.01,
        "config_matches_verified_protocol": bool(correspondence)
        and all(correspondence.values()),
        "primary_protocol_conformity": bool(conformity)
        and all(conformity.values()),
    }
    passed = all(checks.values())
    stretch = {
        "diagnostic_cagr_at_least_target": float(diagnostic["annualized_return"])
        >= gates.target_cagr,
        "diagnostic_sharpe_at_least_1_5": float(diagnostic["sharpe"]) >= 1.5,
        "diagnostic_drawdown_at_most_25pct": float(diagnostic["max_drawdown"])
        <= 0.25,
        "double_cost_positive": float(double_cost["annualized_return"]) > 0.0,
    }
    return {
        "status": (
            "READY_FOR_ONE_TIME_HOLDOUT" if passed else "NO_GO_FOR_LIVE_TRADING"
        ),
        "checks": checks,
        "all_pre_holdout_checks_passed": passed,
        "stretch_checks": stretch,
        "stretch_passed": all(stretch.values()),
        "protocol_conformity": conformity,
        "config_protocol_correspondence": correspondence,
        "holdout_accessed": False,
        "holdout_untouched": True,
        "next_action": (
            "Separate one-time holdout command may be authorized after reviewing this seal."
            if passed
            else "Do not access frozen holdout; improve only on development data."
        ),
    }


def validate_development_artifacts(run_dir: Path) -> None:
    """Trebuet polnyi atomarno zapisannyi development artifact-set."""
    missing = sorted(
        name for name in REQUIRED_DEVELOPMENT_ARTIFACTS if not (run_dir / name).exists()
    )
    if missing:
        raise RuntimeError(f"Daily development run ne polon: {missing}")


def _metrics_row(
    fold_number: int,
    fold: DailyFoldConfig,
    outcome: FoldOutcome,
) -> dict[str, object]:
    """Upakovyvaet tri scenariya i IC v odnu stroku fold-table."""
    row: dict[str, object] = {
        "fold": fold_number,
        "outer_start": fold.outer_start,
        "outer_end": fold.outer_end,
        "outer_ic": outcome.outer_ic,
    }
    for name, result in (
        ("diagnostic_long_short", outcome.diagnostic_long_short),
        ("diagnostic_double_cost", outcome.diagnostic_double_cost),
        ("diagnostic_delayed_entry", outcome.diagnostic_delayed_entry),
    ):
        for metric, value in result.metrics.items():
            row[f"{name}_{metric}"] = value
        row[f"{name}_execution_complete"] = result.execution_complete
    return row


def _with_labels(frame: pd.DataFrame, **labels: object) -> pd.DataFrame:
    """Dobavlyaet audit-labels k kopii artifact-frame."""
    result = frame.copy()
    for column, value in reversed(tuple(labels.items())):
        result.insert(0, column, value)
    return result


def _train_fold(
    panel: pd.DataFrame,
    fold_number: int,
    fold: DailyFoldConfig,
    config: DailyExperimentConfig,
) -> tuple[FoldOutcome, dict[str, object], list[pd.DataFrame], list[dict[str, object]]]:
    """Obuchaet vse frozen seeds, refit i ocenivaet odin outer-fold."""
    import torch

    from market_lab.sequence.training import (
        fit_fixed_epochs,
        fit_with_early_stopping,
        mean_cross_section_ic,
        predict_sequence_scores,
    )

    features = daily_feature_columns(panel)
    scaler = fit_daily_feature_scaler(panel, fold.train_end, features)
    store = build_daily_sequence_store(panel, scaler, config.protocol.sequence_length)
    train_samples = select_daily_sequence_samples(
        store,
        config.protocol.data_start,
        fold.train_end,
        require_target=True,
        purge_exit_before=fold.inner_start,
    )
    inner_samples = select_daily_sequence_samples(
        store,
        fold.inner_start,
        fold.inner_end,
        embargo_sessions=config.protocol.embargo_sessions,
        require_target=False,
        purge_exit_before=fold.outer_start,
    )
    refit_samples = select_daily_sequence_samples(
        store,
        config.protocol.data_start,
        fold.inner_end,
        require_target=True,
        purge_exit_before=fold.outer_start,
    )
    outer_samples = select_daily_sequence_samples(
        store,
        fold.outer_start,
        fold.outer_end,
        embargo_sessions=config.protocol.embargo_sessions,
        require_target=False,
        purge_exit_before=_exclusive_end_boundary(fold.outer_end),
    )
    target_scale = robust_target_scale(train_samples)
    seed_scores: list[np.ndarray] = []
    histories: list[pd.DataFrame] = []
    summaries: list[dict[str, object]] = []
    prediction_frame: pd.DataFrame | None = None
    for seed in config.model.seeds:
        LOGGER.info("Daily fold=%s seed=%s: early stop", fold_number, seed)
        selection = fit_with_early_stopping(
            store,
            train_samples,
            inner_samples,
            target_scale,
            config.model.network,
            seed,
        )
        histories.append(
            _with_labels(
                selection.history,
                fold=fold_number,
                seed=seed,
                stage="early_stop",
            )
        )
        LOGGER.info(
            "Daily fold=%s seed=%s: refit epochs=%s",
            fold_number,
            seed,
            selection.best_epoch,
        )
        model, refit_history = fit_fixed_epochs(
            store,
            refit_samples,
            target_scale,
            config.model.network,
            selection.best_epoch,
            seed,
        )
        histories.append(
            _with_labels(
                refit_history,
                fold=fold_number,
                seed=seed,
                stage="refit",
            )
        )
        scores = predict_sequence_scores(
            model,
            store,
            outer_samples,
            target_scale,
            config.model.network,
        )
        seed_scores.append(scores)
        if prediction_frame is None:
            prediction_frame = _prediction_frame(outer_samples, scores)
            prediction_frame = prediction_frame.drop(columns="prediction")
        prediction_frame[f"prediction_seed_{seed}"] = scores
        summaries.append(
            {
                "fold": fold_number,
                "seed": seed,
                "train_samples": len(train_samples),
                "inner_samples": len(inner_samples),
                "refit_samples": len(refit_samples),
                "outer_samples": len(outer_samples),
                "target_scale": target_scale,
                "best_epoch": selection.best_epoch,
                "inner_ic": selection.best_validation_ic,
                "selection_elapsed_seconds": selection.elapsed_seconds,
            }
        )
        del selection, model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    if prediction_frame is None:
        raise RuntimeError("Daily ensemble ne sozdal outer predictions")
    ensemble = np.mean(np.stack(seed_scores, axis=0), axis=0)
    prediction_frame["prediction"] = ensemble
    outer_ic = mean_cross_section_ic(
        prediction_frame,
        ensemble,
        target_column="model_target",
    )
    diagnostic, double_cost, delayed = _run_fold_backtests(
        prediction_frame,
        panel,
        fold,
        config,
    )
    scaler_manifest = {
        "fold": fold_number,
        "train_end": fold.train_end.isoformat(),
        "feature_count": len(features),
        "scaler": scaler.as_dict(),
    }
    return (
        FoldOutcome(
            predictions=prediction_frame,
            diagnostic_long_short=diagnostic,
            diagnostic_double_cost=double_cost,
            diagnostic_delayed_entry=delayed,
            outer_ic=outer_ic,
        ),
        scaler_manifest,
        histories,
        summaries,
    )


def _report(
    gates: Mapping[str, object],
    aggregate: Mapping[str, Mapping[str, Any]],
    fold_metrics: pd.DataFrame,
    protocol_sha: str,
) -> str:
    """Formiruet chestnyi development-report bez utverzhdeniya o pribyli."""
    diagnostic = aggregate["diagnostic_long_short"]
    double_cost = aggregate["diagnostic_double_cost"]
    delayed = aggregate["diagnostic_delayed_entry"]
    return "\n".join(
        [
            "# Daily residual-TCN: development-only report",
            "",
            f"Frozen protocol SHA-256: `{protocol_sha}`.",
            "",
            "Использованы только 30 ранее открытых development-инструментов. "
            "Frozen asset holdout не загружался и не читался.",
            "",
            f"Outer folds: {len(fold_metrics)}; mean rank IC "
            f"{fold_metrics['outer_ic'].mean():.4f}.",
            "",
            "Frozen primary long-top3 + beta hedge + volatility target пока не "
            "реализован; protocol-conformity намеренно не пройден.",
            "",
            f"Diagnostic long-short: CAGR {diagnostic['annualized_return']:.2%}, "
            f"Sharpe {diagnostic['sharpe']:.3f}, "
            f"max DD {diagnostic['max_drawdown']:.2%}.",
            "",
            f"2x costs: CAGR {double_cost['annualized_return']:.2%}; "
            f"one-session delay: CAGR {delayed['annualized_return']:.2%}.",
            "",
            f"Gate status: **{gates['status']}**.",
            "",
            "Даже READY_FOR_ONE_TIME_HOLDOUT не является разрешением live trading: "
            "эта команда принципиально завершает работу до holdout.",
            "",
            "Long-short результат диагностический: исторические borrow availability, "
            "recalls и индивидуальные borrow rates отсутствуют.",
            "",
        ]
    )


def execute_daily_development_experiment(config: DailyExperimentConfig) -> Path:
    """Vypolnyaet chetyre outer-fold i ostanavlivaetsya pered frozen holdout."""
    from market_lab.sequence.model import build_causal_tcn, model_architecture

    _assert_development_universe(config)
    config_seal = _config_seal(config, config.paths.root)
    seal = _protocol_seal(config.paths.root)
    config_correspondence = _config_protocol_correspondence(config, seal)
    run_dir = create_run_directory(config.paths.runs_dir)
    writer = ArtifactWriter(run_dir)
    configure_logging(run_dir / "run.log")
    writer.write_yaml("resolved_config.yaml", daily_config_as_dict(config))
    writer.write_json("frozen_protocol_sha256.json", seal)
    writer.write_text("frozen_protocol_sha256.txt", f"{seal['computed_sha256']}\n")
    writer.write_json("frozen_config_sha256.json", config_seal)
    writer.write_text(
        "frozen_config_sha256.txt",
        f"{config_seal['computed_sha256']}\n",
    )
    writer.write_json("seed.json", {"seeds": config.model.seeds, "selection": "mean_all"})
    LOGGER.info("Daily development: zagruzka tol'ko original30")
    inputs = load_development_inputs(config)
    writer.write_frame("development_data_manifest.csv", inputs.data_manifest)
    writer.write_frame("context_data_manifest.csv", inputs.context_manifest)
    features = daily_feature_columns(inputs.panel)
    architecture_model = build_causal_tcn(len(features), config.model.network)
    architecture = model_architecture(architecture_model, config.model.network)
    architecture.update(
        {
            "input_layout": "batch x 128 causal daily sessions x features",
            "receptive_field_sessions": architecture.pop("receptive_field_bars"),
            "feature_count": len(features),
            "ensemble_seeds": config.model.seeds,
            "target": (
                "5-session beta-residual next-open to first factual open "
                "at or after scheduled exit"
            ),
        }
    )
    del architecture_model
    writer.write_json("model_architecture.json", architecture)
    writer.write_json("feature_list.json", list(features))

    fold_rows: list[dict[str, object]] = []
    scaler_manifests: list[dict[str, object]] = []
    history_parts: list[pd.DataFrame] = []
    training_rows: list[dict[str, object]] = []
    prediction_parts: list[pd.DataFrame] = []
    diagnostic_ledgers: dict[str, pd.DataFrame] = {}
    diagnostic_double_ledgers: dict[str, pd.DataFrame] = {}
    diagnostic_delayed_ledgers: dict[str, pd.DataFrame] = {}
    ledger_parts: list[pd.DataFrame] = []
    stress_parts: list[pd.DataFrame] = []
    order_parts: list[pd.DataFrame] = []
    weight_parts: list[pd.DataFrame] = []

    for fold_number, fold in enumerate(config.protocol.folds, start=1):
        LOGGER.info("Daily development: outer fold %s", fold_number)
        outcome, scaler_manifest, histories, summaries = _train_fold(
            inputs.panel,
            fold_number,
            fold,
            config,
        )
        fold_name = f"fold_{fold_number:02d}"
        fold_rows.append(_metrics_row(fold_number, fold, outcome))
        scaler_manifests.append(scaler_manifest)
        history_parts.extend(histories)
        training_rows.extend(summaries)
        prediction_parts.append(_with_labels(outcome.predictions, fold=fold_number))
        diagnostic_ledgers[fold_name] = outcome.diagnostic_long_short.ledger
        diagnostic_double_ledgers[fold_name] = outcome.diagnostic_double_cost.ledger
        diagnostic_delayed_ledgers[fold_name] = outcome.diagnostic_delayed_entry.ledger
        ledger_parts.append(
            _with_labels(
                outcome.diagnostic_long_short.ledger,
                fold=fold_number,
                scenario="diagnostic_long_short",
            )
        )
        order_parts.append(
            _with_labels(
                outcome.diagnostic_long_short.orders,
                fold=fold_number,
                scenario="diagnostic_long_short",
            )
        )
        weight_parts.append(
            _with_labels(
                outcome.diagnostic_long_short.weights,
                fold=fold_number,
                scenario="diagnostic_long_short",
            )
        )
        for scenario, result in (
            ("diagnostic_double_cost", outcome.diagnostic_double_cost),
            ("diagnostic_delayed_entry", outcome.diagnostic_delayed_entry),
        ):
            stress_parts.append(
                _with_labels(result.ledger, fold=fold_number, scenario=scenario)
            )

    fold_metrics = pd.DataFrame(fold_rows)
    diagnostic_equity, diagnostic_metrics = aggregate_daily_returns(
        diagnostic_ledgers, config.portfolio.initial_capital
    )
    double_equity, double_metrics = aggregate_daily_returns(
        diagnostic_double_ledgers, config.portfolio.initial_capital
    )
    delayed_equity, delayed_metrics = aggregate_daily_returns(
        diagnostic_delayed_ledgers, config.portfolio.initial_capital
    )
    aggregate_metrics = {
        "diagnostic_long_short": diagnostic_metrics,
        "diagnostic_double_cost": double_metrics,
        "diagnostic_delayed_entry": delayed_metrics,
    }
    gates = evaluate_pre_holdout_gates(
        config,
        fold_metrics,
        aggregate_metrics,
        protocol_conformity=DIAGNOSTIC_PROTOCOL_CONFORMITY,
        config_protocol_correspondence=config_correspondence,
    )

    writer.write_json("scaler_manifests.json", scaler_manifests)
    writer.write_frame("training_histories.csv", pd.concat(history_parts, ignore_index=True))
    writer.write_frame("training_summary.csv", pd.DataFrame(training_rows))
    writer.write_frame("ensemble_predictions.csv", pd.concat(prediction_parts, ignore_index=True))
    writer.write_frame("fold_metrics.csv", fold_metrics)
    writer.write_frame("ledgers.csv", pd.concat(ledger_parts, ignore_index=True))
    writer.write_frame("orders.csv", pd.concat(order_parts, ignore_index=True))
    writer.write_frame("weights.csv", pd.concat(weight_parts, ignore_index=True))
    writer.write_frame("stress_ledgers.csv", pd.concat(stress_parts, ignore_index=True))
    aggregate_equity = pd.concat(
        [
            _with_labels(
                diagnostic_equity,
                scenario="diagnostic_long_short",
            ),
            _with_labels(double_equity, scenario="diagnostic_double_cost"),
            _with_labels(delayed_equity, scenario="diagnostic_delayed_entry"),
        ],
        ignore_index=True,
    )
    writer.write_frame("aggregate_equity.csv", aggregate_equity)
    writer.write_json("aggregate_metrics.json", aggregate_metrics)
    writer.write_json(
        "protocol_conformity.json",
        {
            "implementation_checks": DIAGNOSTIC_PROTOCOL_CONFORMITY,
            "config_protocol_correspondence": config_correspondence,
            "conforms_to_frozen_primary": False,
            "implemented_portfolio": "diagnostic_long_short_top3_bottom3",
            "frozen_primary_portfolio": "long_top3_beta_hedged_volatility_targeted",
        },
    )
    writer.write_json("pre_holdout_gates.json", gates)
    writer.write_text(
        "report.md",
        _report(gates, aggregate_metrics, fold_metrics, str(seal["computed_sha256"])),
    )
    writer.write_equity_plot(
        "equity_curve.png",
        diagnostic_equity.set_index("session_date")["equity"],
        width=11,
        height=5,
        title="Daily residual-TCN diagnostic long-short outer folds",
    )
    validate_development_artifacts(run_dir)
    LOGGER.info(
        "Daily development zavershen: status=%s, holdout_accessed=False, run=%s",
        gates["status"],
        run_dir,
    )
    return run_dir
