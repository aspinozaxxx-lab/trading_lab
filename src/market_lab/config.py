"""Strogaya schema i zagruzka YAML-konfiguracii."""

from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.io_utils import TEXT_ENCODING

PACKAGE_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # Koren iz raspolozheniya src-paketa.


class PathsConfig(BaseModel):
    """Zadaet vse katalogi strogo vnutri kornya proekta."""

    model_config = ConfigDict(extra="forbid")

    root: Path = Path("..")
    raw_data_dir: Path = Path("data/raw")
    processed_data_dir: Path = Path("data/processed")
    runs_dir: Path = Path("runs")


class DataConfig(BaseModel):
    """Zadaet istochnik i diapazon rynochnyh svechei."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["moex", "fixture"] = "moex"
    instrument: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    market: str = Field(min_length=1)
    board: str = Field(min_length=1)
    trading_mode: str = Field(min_length=1)
    timeframe: Literal["10m", "1h", "1d"] = "1d"
    start: date
    end: date
    fixture_path: Path
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=10)
    page_size: int = Field(default=500, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_dates(self) -> DataConfig:
        """Proveryaet vozrastanie granic zaprashivaemogo perioda."""
        if self.start >= self.end:
            raise ValueError("data.start dolzhen byt ran'she data.end")
        return self


class PortfolioConfig(BaseModel):
    """Zadaet kapital i model torgovyh izderzhek."""

    model_config = ConfigDict(extra="forbid")

    initial_capital: float = Field(gt=0)
    commission_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    allow_short: bool = False


class FeaturesConfig(BaseModel):
    """Zadaet yavnyi spisok vklyuchennyh priznakov."""

    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(min_length=1)


class BaselinesConfig(BaseModel):
    """Zadaet parametry bazovoi SMA-strategii."""

    model_config = ConfigDict(extra="forbid")

    sma_fast: int = Field(default=5, ge=2)
    sma_slow: int = Field(default=20, ge=3)

    @model_validator(mode="after")
    def validate_windows(self) -> BaselinesConfig:
        """Trebuet chtoby bystroe okno bylo koroche medlennogo."""
        if self.sma_fast >= self.sma_slow:
            raise ValueError("sma_fast dolzhen byt men'she sma_slow")
        return self


class RegimeTrendConfig(BaseModel):
    """Zadaet medlennyi trend i momentum dlya rezhimnogo filtra."""

    model_config = ConfigDict(extra="forbid")

    sma_window: int = Field(default=75, ge=20)
    momentum_window: int = Field(default=60, ge=5)
    entry_band: float = Field(default=0.0, ge=0.0, le=0.25)


class HysteresisTrendConfig(BaseModel):
    """Zadaet razdelnye porogi vhoda i vyhoda dlya ustoychivogo trenda."""

    model_config = ConfigDict(extra="forbid")

    sma_window: int = Field(default=150, ge=20)
    momentum_window: int = Field(default=20, ge=5)
    entry_band: float = Field(default=0.01, ge=0.0, le=0.25)
    exit_band: float = Field(default=0.02, ge=0.0, le=0.25)


class SelectionConfig(BaseModel):
    """Zadaet validation-barery dlya razresheniya torgovli."""

    model_config = ConfigDict(extra="forbid")

    minimum_validation_score: float = 0.0
    minimum_validation_return: float = 0.0
    maximum_validation_drawdown: float = Field(default=0.25, gt=0.0, le=1.0)
    maximum_validation_trade_count: int = Field(default=40, ge=1)
    minimum_positive_fold_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    minimum_recent_fold_return: float = Field(default=-1.0, ge=-1.0)


class StrategyConfig(BaseModel):
    """Zadaet osnovnuyu ML-strategiyu i bazovye sravneniya."""

    model_config = ConfigDict(extra="forbid")

    name: Literal["hybrid_trend_logistic"] = "hybrid_trend_logistic"
    parameters: dict[str, float] = Field(default_factory=lambda: {"C": 1.0, "threshold": 0.5})
    baselines: BaselinesConfig = Field(default_factory=BaselinesConfig)
    regime_trend: RegimeTrendConfig = Field(default_factory=RegimeTrendConfig)
    robust_trend: HysteresisTrendConfig = Field(default_factory=HysteresisTrendConfig)
    hybrid_trend: RegimeTrendConfig = Field(
        default_factory=lambda: RegimeTrendConfig(
            sma_window=200,
            momentum_window=120,
            entry_band=0.03,
        )
    )
    selection: SelectionConfig = Field(default_factory=SelectionConfig)

    @model_validator(mode="after")
    def validate_parameters(self) -> StrategyConfig:
        """Proveryaet parametry logisticheskoi strategii."""
        c_value = float(self.parameters.get("C", 1.0))
        threshold = float(self.parameters.get("threshold", 0.5))
        if c_value <= 0:
            raise ValueError("strategy.parameters.C dolzhen byt polozhitelnym")
        if not 0.0 < threshold < 1.0:
            raise ValueError("strategy.parameters.threshold dolzhen byt mezhdu 0 i 1")
        return self


class SearchSpace(BaseModel):
    """Opisyvaet odin chislovoi diapazon Optuna."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["float", "int"]
    low: float
    high: float
    log: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> SearchSpace:
        """Proveryaet granicy i logarifmicheskii diapazon."""
        if self.low >= self.high:
            raise ValueError("search-space low dolzhen byt men'she high")
        if self.log and self.low <= 0:
            raise ValueError("logarifmicheskii search-space dolzhen byt polozhitelnym")
        return self


class OptimizationConfig(BaseModel):
    """Zadaet study, objective i ogranichenie po sdelkam."""

    model_config = ConfigDict(extra="forbid")

    n_trials: int = Field(default=5, ge=1, le=10000)
    objective: Literal["validation_sharpe", "validation_calmar"] = "validation_sharpe"
    min_trades: int = Field(default=5, ge=0)
    search_space: dict[str, SearchSpace]

    @model_validator(mode="after")
    def validate_known_parameters(self) -> OptimizationConfig:
        """Zapreshchaet neizvestnye parametry dlya pervogo MVP."""
        unknown = set(self.search_space) - {"C", "threshold"}
        if unknown:
            raise ValueError(f"Neizvestnye Optuna-parametry: {sorted(unknown)}")
        return self


class ValidationConfig(BaseModel):
    """Zadaet hronologicheskii split, embargo i walk-forward."""

    model_config = ConfigDict(extra="forbid")

    train_fraction: float = Field(gt=0, lt=1)
    validation_fraction: float = Field(gt=0, lt=1)
    test_fraction: float = Field(gt=0, lt=1)
    gap_bars: int = Field(default=2, ge=2)
    walk_forward_folds: int = Field(default=3, ge=1, le=20)

    @model_validator(mode="after")
    def validate_fractions(self) -> ValidationConfig:
        """Trebuet polnoe razbienie bez peresechenii po dolyam."""
        total = self.train_fraction + self.validation_fraction + self.test_fraction
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("Doli train/validation/test dolzhny davat 1.0")
        return self


class ReportConfig(BaseModel):
    """Zadaet annualizaciyu i razmer grafika."""

    model_config = ConfigDict(extra="forbid")

    annualization_factor: int = Field(default=252, ge=1)
    plot_width: float = Field(default=10, gt=0)
    plot_height: float = Field(default=5, gt=0)
    evaluation_status: Literal["unseen_holdout", "post_selection_exploratory"] = (
        "unseen_holdout"
    )


class AppConfig(BaseModel):
    """Obedinyaet vse parametry vosproizvodimogo eksperimenta."""

    model_config = ConfigDict(extra="forbid")

    paths: PathsConfig
    data: DataConfig
    portfolio: PortfolioConfig
    features: FeaturesConfig
    strategy: StrategyConfig
    optimization: OptimizationConfig
    validation: ValidationConfig
    report: ReportConfig
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def resolve_project_storage_path(root: Path, candidate: Path, label: str) -> Path:
    """Razreshaet proektnyi put ili ego yavno razreshennyi external storage."""
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(root):
        raise ValueError(f"Put {label} vyhodit za koren proekta: {lexical}")

    resolved = candidate.resolve()
    if resolved.is_relative_to(root):
        return lexical

    configured_storage = os.environ.get("MARKET_LAB_STORAGE_ROOT")
    storage_root = (
        Path(configured_storage).expanduser()
        if configured_storage
        else root.parent / f"{root.name}_data"
    ).resolve()
    if resolved.is_relative_to(storage_root):
        return lexical
    raise ValueError(
        f"Put {label} ssylayetsya vne proekta i external storage: {resolved}"
    )


def _resolve_inside(root: Path, candidate: Path, label: str) -> Path:
    """Razreshaet obychnyi put i zapreshchaet vyhod za koren proekta."""
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Put {label} vyhodit za koren proekta: {resolved}")
    return resolved


def load_config(path: Path) -> AppConfig:
    """Chitaet YAML, zapolnyaet defaulty i razreshaet bezopasnye puti."""
    config_path = path.resolve()
    with config_path.open("r", encoding=TEXT_ENCODING) as stream:
        raw = yaml.safe_load(stream)
    config = AppConfig.model_validate(raw)
    project_root = (config_path.parent / config.paths.root).resolve()
    if project_root != PACKAGE_PROJECT_ROOT:
        raise ValueError(
            f"Koren konfiguracii dolzhen byt {PACKAGE_PROJECT_ROOT}, polucheno {project_root}"
        )
    raw_dir = resolve_project_storage_path(
        project_root, project_root / config.paths.raw_data_dir, "raw"
    )
    processed_dir = resolve_project_storage_path(
        project_root, project_root / config.paths.processed_data_dir, "processed"
    )
    runs_dir = resolve_project_storage_path(
        project_root, project_root / config.paths.runs_dir, "runs"
    )
    fixture = _resolve_inside(project_root, project_root / config.data.fixture_path, "fixture")
    resolved_paths = config.paths.model_copy(
        update={
            "root": project_root,
            "raw_data_dir": raw_dir,
            "processed_data_dir": processed_dir,
            "runs_dir": runs_dir,
        }
    )
    resolved_data = config.data.model_copy(update={"fixture_path": fixture})
    return config.model_copy(update={"paths": resolved_paths, "data": resolved_data})


def config_as_dict(config: AppConfig) -> dict[str, object]:
    """Preobrazuet razreshennuyu konfiguraciyu v serializuemyi slovar."""
    return config.model_dump(mode="json")
