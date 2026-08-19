"""Konfiguraciya GPU-rankera s novym instrument-holdout."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.alpha.config import (
    AlphaPortfolioConfig,
    AlphaProtocolConfig,
    AlphaUniverseConfig,
)
from market_lab.config import PACKAGE_PROJECT_ROOT, PathsConfig, resolve_project_storage_path
from market_lab.io_utils import TEXT_ENCODING


class RankerModelConfig(BaseModel):
    """Zadaet odnu zafiksirovannuyu arhitekturu XGBoost Ranker."""

    model_config = ConfigDict(extra="forbid")

    n_estimators: int = Field(default=400, ge=20, le=3000)
    max_depth: int = Field(default=3, ge=1, le=12)
    learning_rate: float = Field(default=0.03, gt=0, le=1)
    min_child_weight: float = Field(default=50.0, gt=0)
    subsample: float = Field(default=0.8, gt=0, le=1)
    colsample_bytree: float = Field(default=0.8, gt=0, le=1)
    reg_lambda: float = Field(default=20.0, ge=0)
    device: str = Field(default="cuda", pattern=r"^(cuda|cpu)$")


class RankerStrategyConfig(BaseModel):
    """Zadaet konservativnoe pravilo iz OOS-rangov."""

    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=1, ge=1)
    rebalance_days: int = Field(default=5, ge=1, le=60)
    regime_window: int = Field(default=20, ge=2, le=252)
    absolute_momentum_window: int = Field(default=60, ge=2, le=252)
    core_leverage: float = Field(default=1.0, gt=0, le=2)
    risk_scenarios: list[float] = Field(default_factory=lambda: [1.0, 1.5, 2.0])
    target_cagr: float = Field(default=0.5, gt=0)
    maximum_core_drawdown: float = Field(default=0.25, gt=0, le=1)

    @model_validator(mode="after")
    def validate_scenarios(self) -> RankerStrategyConfig:
        """Proveryaet nalichie core i unikal'nost' risk-scenariev."""
        if self.core_leverage not in self.risk_scenarios:
            raise ValueError("core_leverage dolzhen vhodit' v risk_scenarios")
        if len(self.risk_scenarios) != len(set(self.risk_scenarios)):
            raise ValueError("risk_scenarios soderzhat povtory")
        if any(value <= 0 or value > 2 for value in self.risk_scenarios):
            raise ValueError("risk_scenarios dolzhny byt v diapazone (0, 2]")
        return self


class RankerExperimentConfig(BaseModel):
    """Obedinyaet protokol post-diagnostic instrument-holdout."""

    model_config = ConfigDict(extra="forbid")

    paths: PathsConfig
    universe: AlphaUniverseConfig
    protocol: AlphaProtocolConfig
    portfolio: AlphaPortfolioConfig
    model: RankerModelConfig
    strategy: RankerStrategyConfig
    seed: int = Field(default=42, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def validate_joint_limits(self) -> RankerExperimentConfig:
        """Sveriaet top-k i plecho s razmerom universuma i risk-limitom."""
        if self.strategy.top_k > min(
            len(self.universe.development), len(self.universe.holdout)
        ):
            raise ValueError("top_k prevyshaet razmer universuma")
        if max(self.strategy.risk_scenarios) > self.portfolio.maximum_gross_leverage:
            raise ValueError("Risk-scenarii prevyshayut maximum_gross_leverage")
        return self


def load_ranker_config(path: Path) -> RankerExperimentConfig:
    """Chitaet ranker-YAML i razreshaet tol'ko proektnye katalogi."""
    config_path = path.resolve()
    with config_path.open("r", encoding=TEXT_ENCODING) as stream:
        raw = yaml.safe_load(stream)
    config = RankerExperimentConfig.model_validate(raw)
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


def ranker_config_as_dict(config: RankerExperimentConfig) -> dict[str, object]:
    """Preobrazuet ranker-konfiguraciyu v JSON/YAML-sovmestimy slovar'."""
    return config.model_dump(mode="json")
