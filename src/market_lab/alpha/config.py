"""Strogaya konfiguraciya nezavisimogo alpha-eksperimenta."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.config import PACKAGE_PROJECT_ROOT, PathsConfig, resolve_project_storage_path
from market_lab.io_utils import TEXT_ENCODING


class AlphaUniverseConfig(BaseModel):
    """Zadaet razdelennye development i holdout-universumy."""

    model_config = ConfigDict(extra="forbid")

    development: list[str] = Field(min_length=3)
    holdout: list[str] = Field(min_length=3)
    board: str = Field(default="TQBR", min_length=1)
    timeframe: Literal["1h"] = "1h"

    @model_validator(mode="after")
    def validate_universes(self) -> AlphaUniverseConfig:
        """Zapreshchaet povtory i peresechenie dvuh universumov."""
        development = [item.upper() for item in self.development]
        holdout = [item.upper() for item in self.holdout]
        if len(development) != len(set(development)):
            raise ValueError("development soderzhit povtory")
        if len(holdout) != len(set(holdout)):
            raise ValueError("holdout soderzhit povtory")
        if set(development) & set(holdout):
            raise ValueError("development i holdout ne dolzhny peresekat'sya")
        self.development = development
        self.holdout = holdout
        return self


class AlphaProtocolConfig(BaseModel):
    """Fiksiruet hronologiyu train, validation i finalnogo testa."""

    model_config = ConfigDict(extra="forbid")

    data_start: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date
    validation_fold_months: int = Field(default=6, ge=1, le=24)
    embargo_days: int = Field(default=2, ge=1, le=20)

    @model_validator(mode="after")
    def validate_dates(self) -> AlphaProtocolConfig:
        """Trebuet posledovatel'nye neperesekayushchiesya vremennye uchastki."""
        if not (
            self.data_start
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ValueError("Granicy alpha-protokola zadany ne po vozrastaniyu")
        return self


class AlphaPortfolioConfig(BaseModel):
    """Zadaet izderzhki, finansirovanie i predel plecha."""

    model_config = ConfigDict(extra="forbid")

    initial_capital: float = Field(gt=0)
    commission_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    financing_rate_annual: float = Field(ge=0, le=1)
    maximum_gross_leverage: float = Field(ge=1, le=2)
    volatility_floor: float = Field(default=0.003, gt=0, le=0.1)


class AlphaSearchConfig(BaseModel):
    """Zadaet konechnyi i proveriaemyi nabor validation-kandidatov."""

    model_config = ConfigDict(extra="forbid")

    momentum_windows: list[int] = Field(min_length=1)
    top_k: list[int] = Field(min_length=1)
    gross_leverages: list[float] = Field(min_length=1)
    regime_filters: list[bool] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_search_space(self) -> AlphaSearchConfig:
        """Proveryaet unikal'nost' i bezopasnye granicy kandidatov."""
        if any(window < 2 or window > 252 for window in self.momentum_windows):
            raise ValueError("momentum_windows dolzhny byt mezhdu 2 i 252")
        if any(value < 1 for value in self.top_k):
            raise ValueError("top_k dolzhen byt polozhitel'nym")
        if any(value < 0.1 for value in self.gross_leverages):
            raise ValueError("gross_leverages dolzhny byt polozhitel'nymi")
        fields = (
            self.momentum_windows,
            self.top_k,
            self.gross_leverages,
            self.regime_filters,
        )
        if any(len(values) != len(set(values)) for values in fields):
            raise ValueError("Alpha search-space soderzhit povtory")
        return self


class AlphaSelectionConfig(BaseModel):
    """Zadaet porogi dlya celi CAGR bez podbora po testu."""

    model_config = ConfigDict(extra="forbid")

    target_cagr: float = Field(default=0.5, gt=0)
    maximum_drawdown: float = Field(default=0.25, gt=0, le=1)
    minimum_sharpe: float = Field(default=1.0)
    minimum_positive_fold_fraction: float = Field(default=0.75, ge=0, le=1)
    stress_cost_multiplier: float = Field(default=2.0, ge=1, le=10)
    minimum_stress_cagr: float = Field(default=0.25)


class AlphaModelConfig(BaseModel):
    """Zadaet sravnitel'nye tablichnye modeli bez podbora po testu."""

    model_config = ConfigDict(extra="forbid")

    ridge_alpha: float = Field(default=100.0, gt=0)
    extra_trees_estimators: int = Field(default=160, ge=20, le=2000)
    extra_trees_max_features: float = Field(default=0.7, gt=0, le=1)
    extra_trees_min_samples_leaf: int = Field(default=30, ge=2, le=1000)
    comparison_top_k: int = Field(default=3, ge=1)
    comparison_leverage: float = Field(default=1.0, gt=0, le=2)


class AlphaConfig(BaseModel):
    """Obedinyaet vse parametry zapechatannogo alpha-eksperimenta."""

    model_config = ConfigDict(extra="forbid")

    paths: PathsConfig
    universe: AlphaUniverseConfig
    protocol: AlphaProtocolConfig
    portfolio: AlphaPortfolioConfig
    search: AlphaSearchConfig
    selection: AlphaSelectionConfig
    model: AlphaModelConfig
    seed: int = Field(default=42, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def validate_joint_limits(self) -> AlphaConfig:
        """Proveryaet poiskovye granicy protiv universuma i portfelya."""
        smallest_universe = min(len(self.universe.development), len(self.universe.holdout))
        if max(self.search.top_k) > smallest_universe:
            raise ValueError("top_k prevyshaet razmer men'shego universuma")
        if max(self.search.gross_leverages) > self.portfolio.maximum_gross_leverage:
            raise ValueError("Poisk zaprashivaet plecho vyshe maximum_gross_leverage")
        if self.model.comparison_top_k > smallest_universe:
            raise ValueError("model.comparison_top_k prevyshaet razmer universuma")
        if self.model.comparison_leverage > self.portfolio.maximum_gross_leverage:
            raise ValueError("Model' zaprashivaet slishkom bol'shoe plecho")
        return self


def load_alpha_config(path: Path) -> AlphaConfig:
    """Chitaet alpha-YAML i bezopasno razreshaet katalogi."""
    config_path = path.resolve()
    with config_path.open("r", encoding=TEXT_ENCODING) as stream:
        raw = yaml.safe_load(stream)
    config = AlphaConfig.model_validate(raw)
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


def alpha_config_as_dict(config: AlphaConfig) -> dict[str, object]:
    """Preobrazuet alpha-konfiguraciyu v serializuemyi slovar'."""
    return config.model_dump(mode="json")
