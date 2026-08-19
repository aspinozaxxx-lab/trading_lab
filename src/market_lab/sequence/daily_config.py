"""Strogaya konfiguraciya daily residual-TCN eksperimenta v3."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.config import PACKAGE_PROJECT_ROOT, PathsConfig, resolve_project_storage_path
from market_lab.io_utils import TEXT_ENCODING
from market_lab.sequence.config import SequenceModelConfig


class DailyUniverseConfig(BaseModel):
    """Razdelyaet development i dva zapechatannyh holdout-strata."""

    model_config = ConfigDict(extra="forbid")

    development: list[str] = Field(min_length=20)
    mature_holdout: list[str] = Field(min_length=5)
    recent_holdout: list[str] = Field(min_length=3)
    board: str = Field(default="TQBR", min_length=1)

    @model_validator(mode="after")
    def validate_universes(self) -> DailyUniverseConfig:
        """Normalizuet tickery i zapreshchaet povtory/peresecheniya."""
        fields = ("development", "mature_holdout", "recent_holdout")
        normalized: dict[str, list[str]] = {}
        for field in fields:
            tickers = [str(value).upper() for value in getattr(self, field)]
            if len(tickers) != len(set(tickers)):
                raise ValueError(f"{field} soderzhit povtory")
            normalized[field] = tickers
            setattr(self, field, tickers)
        sets = [set(normalized[field]) for field in fields]
        if any(sets[left] & sets[right] for left in range(3) for right in range(left + 1, 3)):
            raise ValueError("Daily-universumy ne dolzhny peresekat'sya")
        return self

    @property
    def frozen_holdout(self) -> list[str]:
        """Vozvrashchaet polnyi zapechatannyi asset-transfer holdout."""
        return [*self.mature_holdout, *self.recent_holdout]


class DailyFoldConfig(BaseModel):
    """Zadaet odin nested expanding temporal fold."""

    model_config = ConfigDict(extra="forbid")

    train_end: date
    inner_start: date
    inner_end: date
    outer_start: date
    outer_end: date

    @model_validator(mode="after")
    def validate_dates(self) -> DailyFoldConfig:
        """Trebuet strogo posledovatel'nye train, inner i outer intervaly."""
        if not (
            self.train_end < self.inner_start <= self.inner_end < self.outer_start <= self.outer_end
        ):
            raise ValueError("Daily fold-granicy zadany ne po vozrastaniyu")
        return self


class DailyProtocolConfig(BaseModel):
    """Fiksiruet istoriyu, folds, target i zapechatannyi period."""

    model_config = ConfigDict(extra="forbid")

    data_start: date
    development_end: date
    sequence_length: int = Field(default=128, ge=20, le=512)
    horizon_sessions: int = Field(default=5, ge=5, le=5)
    embargo_sessions: int = Field(default=5, ge=5, le=60)
    beta_window_sessions: int = Field(default=60, ge=20, le=252)
    beta_min_periods: int = Field(default=20, ge=10, le=252)
    folds: list[DailyFoldConfig] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_protocol(self) -> DailyProtocolConfig:
        """Proveryaet poryadok outer-fold i beta-okna."""
        if self.data_start >= self.development_end:
            raise ValueError("Daily data_start dolzhen byt ran'she development_end")
        if self.beta_min_periods > self.beta_window_sessions:
            raise ValueError("beta_min_periods ne mozhet prevyshat beta_window_sessions")
        outer_starts = [fold.outer_start for fold in self.folds]
        if outer_starts != sorted(outer_starts) or len(outer_starts) != len(set(outer_starts)):
            raise ValueError("Daily folds dolzhny byt hronologicheskimi")
        if self.folds[-1].outer_end > self.development_end:
            raise ValueError("Outer fold vyhodit za development_end")
        return self


class DailyModelConfig(BaseModel):
    """Obedinyaet TCN-parametry i nevybiraemyi seed-ensemble."""

    model_config = ConfigDict(extra="forbid")

    network: SequenceModelConfig
    seeds: list[int] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_seeds(self) -> DailyModelConfig:
        """Trebuet unikal'nye bezopasnye seed bez vybora po kachestvu."""
        if len(self.seeds) != len(set(self.seeds)):
            raise ValueError("Daily seeds soderzhat povtory")
        if any(seed < 0 or seed > 2**32 - 1 for seed in self.seeds):
            raise ValueError("Daily seed vyhodit za uint32")
        if self.network.ranking_weight <= 0.0:
            raise ValueError("Daily v3 trebuet polozhitel'nyi ranking_weight")
        return self


class DailyPortfolioConfig(BaseModel):
    """Zadaet konservativnye izderzhki i zamorozhennoe pravilo vybora."""

    model_config = ConfigDict(extra="forbid")

    initial_capital: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    short_borrow_rate_annual: float = Field(default=0.20, ge=0, le=2)
    stock_gross_leverage: float = Field(default=1.0, gt=0, le=1)
    top_k: int = Field(default=3, ge=1, le=10)
    keep_rank: int = Field(default=6, ge=1, le=20)
    minimum_score_bps: float = Field(default=0.0, ge=0, le=500)
    staggered_sleeves: int = Field(default=5, ge=5, le=5)

    @model_validator(mode="after")
    def validate_rule(self) -> DailyPortfolioConfig:
        """Trebuet hysteresis-rank ne men'she portfolio-razmera."""
        if self.keep_rank < self.top_k:
            raise ValueError("Daily keep_rank ne mozhet byt men'she top_k")
        return self


class DailyGatesConfig(BaseModel):
    """Fiksiruet research-gates do otkrytiya asset holdout."""

    model_config = ConfigDict(extra="forbid")

    minimum_mean_rank_ic: float = 0.03
    minimum_positive_ic_folds: int = Field(default=3, ge=1)
    minimum_aggregate_sharpe: float = 1.0
    minimum_median_fold_sharpe: float = 0.8
    minimum_worst_fold_sharpe: float = -0.25
    maximum_drawdown: float = Field(default=0.20, gt=0, le=1)
    target_cagr: float = Field(default=0.50, gt=0)


class DailyExperimentConfig(BaseModel):
    """Obedinyaet vse parametry daily residual-TCN v3."""

    model_config = ConfigDict(extra="forbid")

    paths: PathsConfig
    universe: DailyUniverseConfig
    protocol: DailyProtocolConfig
    model: DailyModelConfig
    portfolio: DailyPortfolioConfig
    gates: DailyGatesConfig

    @model_validator(mode="after")
    def validate_joint_limits(self) -> DailyExperimentConfig:
        """Sveriaet portfolio-razmer s kazhdym universumom i folds."""
        smallest = min(
            len(self.universe.development),
            len(self.universe.mature_holdout),
            len(self.universe.recent_holdout),
        )
        if 2 * self.portfolio.top_k > smallest:
            raise ValueError("Daily long-short top_k slishkom velik dlya universuma")
        if self.gates.minimum_positive_ic_folds > len(self.protocol.folds):
            raise ValueError("minimum_positive_ic_folds prevyshaet chislo folds")
        return self


def load_daily_experiment_config(path: Path) -> DailyExperimentConfig:
    """Chitaet daily YAML i strogo razreshaet lokal'nye katalogi."""
    config_path = path.resolve()
    with config_path.open("r", encoding=TEXT_ENCODING) as stream:
        raw = yaml.safe_load(stream)
    config = DailyExperimentConfig.model_validate(raw)
    root = (config_path.parent / config.paths.root).resolve()
    if root != PACKAGE_PROJECT_ROOT:
        raise ValueError(f"Koren konfiguracii dolzhen byt {PACKAGE_PROJECT_ROOT}, polucheno {root}")
    paths = config.paths.model_copy(
        update={
            "root": root,
            "raw_data_dir": resolve_project_storage_path(
                root, root / config.paths.raw_data_dir, "raw"
            ),
            "processed_data_dir": resolve_project_storage_path(
                root, root / config.paths.processed_data_dir, "processed"
            ),
            "runs_dir": resolve_project_storage_path(
                root, root / config.paths.runs_dir, "runs"
            ),
        }
    )
    return config.model_copy(update={"paths": paths})


def daily_config_as_dict(config: DailyExperimentConfig) -> dict[str, object]:
    """Preobrazuet daily-config v stabil'nyi JSON/YAML-slovar'."""
    return config.model_dump(mode="json")
