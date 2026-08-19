"""Strogaya konfiguraciya GPU-eksperimenta na 10-minutnyh svechah."""

from __future__ import annotations

from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.config import PACKAGE_PROJECT_ROOT, PathsConfig, resolve_project_storage_path
from market_lab.io_utils import TEXT_ENCODING


class SequenceUniverseConfig(BaseModel):
    """Razdelyaet development i zapechatannyi instrument-holdout."""

    model_config = ConfigDict(extra="forbid")

    development: list[str] = Field(min_length=8)
    holdout: list[str] = Field(min_length=5)
    engine: str = Field(default="stock", min_length=1)
    market: str = Field(default="shares", min_length=1)
    board: str = Field(default="TQBR", min_length=1)
    timeframe: Literal["10m"] = "10m"

    @model_validator(mode="after")
    def validate_universes(self) -> SequenceUniverseConfig:
        """Normalizuet tickery i zapreshchaet povtory ili peresecheniya."""
        development = [ticker.upper() for ticker in self.development]
        holdout = [ticker.upper() for ticker in self.holdout]
        if len(development) != len(set(development)):
            raise ValueError("development soderzhit povtory")
        if len(holdout) != len(set(holdout)):
            raise ValueError("holdout soderzhit povtory")
        if set(development) & set(holdout):
            raise ValueError("development i holdout ne dolzhny peresekat'sya")
        self.development = development
        self.holdout = holdout
        return self


class SequenceProtocolConfig(BaseModel):
    """Fiksiruet hronologiyu train, validation, calibration i testa."""

    model_config = ConfigDict(extra="forbid")

    data_start: date
    train_end: date
    validation_start: date
    validation_end: date
    calibration_start: date
    calibration_end: date
    test_start: date
    test_end: date
    sequence_length: int = Field(default=192, ge=24, le=512)
    horizon_bars: int = Field(default=24, ge=1, le=72)
    train_stride_bars: int = Field(default=6, ge=1, le=24)
    evaluation_decision_slots: list[int] = Field(
        default_factory=lambda: [0, 24, 48], min_length=1
    )
    embargo_bars: int = Field(default=48, ge=1, le=400)

    @model_validator(mode="after")
    def validate_dates_and_steps(self) -> SequenceProtocolConfig:
        """Trebuet strogo posledovatel'nye period i neperesekayushchiesya sdelki."""
        if not (
            self.data_start
            < self.train_end
            < self.validation_start
            <= self.validation_end
            < self.calibration_start
            <= self.calibration_end
            < self.test_start
            <= self.test_end
        ):
            raise ValueError("Granicy sequence-protokola zadany ne po vozrastaniyu")
        if len(self.evaluation_decision_slots) != len(set(self.evaluation_decision_slots)):
            raise ValueError("evaluation_decision_slots soderzhit povtory")
        slots = sorted(self.evaluation_decision_slots)
        if slots != self.evaluation_decision_slots or slots[0] < 0:
            raise ValueError("evaluation_decision_slots dolzhny vozrastat' ot nulya")
        if any(right - left < self.horizon_bars for left, right in pairwise(slots)):
            raise ValueError("Torgovye decision-slots ne dolzhny perekryvat' targety")
        return self


class SequenceDownloadConfig(BaseModel):
    """Zadaet ogranicheniya vezhlivogo i vosproizvodimogo klienta ISS."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=4, ge=0, le=10)
    max_workers: int = Field(default=3, ge=1, le=8)
    page_size: int = Field(default=500, ge=100, le=5000)
    request_pause_seconds: float = Field(default=0.03, ge=0, le=2)


class SequenceModelConfig(BaseModel):
    """Zadaet odnu zafiksirovannuyu causal-TCN arhitekturu."""

    model_config = ConfigDict(extra="forbid")

    channels: int = Field(default=128, ge=16, le=512)
    blocks: int = Field(default=6, ge=2, le=10)
    kernel_size: int = Field(default=3, ge=2, le=9)
    dropout: float = Field(default=0.10, ge=0, le=0.7)
    learning_rate: float = Field(default=0.0003, gt=0, le=0.1)
    weight_decay: float = Field(default=0.0001, ge=0, le=0.1)
    batch_size: int = Field(default=512, ge=32, le=8192)
    epochs: int = Field(default=15, ge=1, le=200)
    patience: int = Field(default=4, ge=1, le=50)
    classification_weight: float = Field(default=0.25, ge=0, le=10)
    ranking_weight: float = Field(default=0.0, ge=0)
    ranking_temperature: float = Field(default=1.0, gt=0)
    gradient_clip: float = Field(default=1.0, gt=0, le=100)
    workers: int = Field(default=8, ge=0, le=32)
    precision: Literal["bf16", "fp16", "fp32"] = "bf16"
    target_mode: Literal["absolute", "cross_section_residual"] = "absolute"


class SequencePortfolioConfig(BaseModel):
    """Fiksiruet izderzhki, leverage i konechnyi validation-poisk."""

    model_config = ConfigDict(extra="forbid")

    initial_capital: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    financing_rate_annual: float = Field(default=0.20, ge=0, le=2)
    short_borrow_rate_annual: float = Field(default=0.0, ge=0, le=2)
    missing_exit_return: float = Field(default=-0.05, ge=-1, le=0)
    position_mode_candidates: list[Literal["long_only", "long_short"]] = Field(
        default_factory=lambda: ["long_only"], min_length=1
    )
    top_k_candidates: list[int] = Field(default_factory=lambda: [1, 2, 3], min_length=1)
    minimum_score_bps_candidates: list[float] = Field(
        default_factory=lambda: [7.0, 10.0, 14.0, 20.0], min_length=1
    )
    keep_rank_candidates: list[int] = Field(default_factory=lambda: [1, 3, 5], min_length=1)
    regime_filter_candidates: list[bool] = Field(
        default_factory=lambda: [True, False], min_length=1
    )
    core_leverage: float = Field(default=1.0, gt=0, le=2)
    risk_scenarios: list[float] = Field(default_factory=lambda: [1.0, 1.5, 2.0])
    target_cagr: float = Field(default=0.50, gt=0)
    maximum_core_drawdown: float = Field(default=0.30, gt=0, le=1)
    minimum_trades: int = Field(default=100, ge=1)

    @model_validator(mode="after")
    def validate_search_space(self) -> SequencePortfolioConfig:
        """Proveryaet unikal'nost' i bezopasnye granicy portfolio-kandidatov."""
        collections = (
            self.top_k_candidates,
            self.minimum_score_bps_candidates,
            self.keep_rank_candidates,
            self.regime_filter_candidates,
            self.position_mode_candidates,
            self.risk_scenarios,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("Sequence search-space soderzhit povtory")
        if any(value < 0 or value > 100 for value in self.minimum_score_bps_candidates):
            raise ValueError("minimum_score_bps_candidates dolzhny byt v diapazone [0, 100]")
        if any(value < 1 for value in self.keep_rank_candidates):
            raise ValueError("keep_rank_candidates dolzhny byt polozhitel'nymi")
        if any(value <= 0 or value > 2 for value in self.risk_scenarios):
            raise ValueError("risk_scenarios dolzhny byt v diapazone (0, 2]")
        if self.core_leverage not in self.risk_scenarios:
            raise ValueError("core_leverage dolzhen vhodit' v risk_scenarios")
        return self


class SequenceExperimentConfig(BaseModel):
    """Obedinyaet vse parametry izolirovannogo servernogo eksperimenta."""

    model_config = ConfigDict(extra="forbid")

    paths: PathsConfig
    universe: SequenceUniverseConfig
    protocol: SequenceProtocolConfig
    download: SequenceDownloadConfig
    model: SequenceModelConfig
    portfolio: SequencePortfolioConfig
    seed: int = Field(default=42, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def validate_joint_limits(self) -> SequenceExperimentConfig:
        """Sveriaet top-k s oboimi universumami."""
        smallest = min(len(self.universe.development), len(self.universe.holdout))
        if max(self.portfolio.top_k_candidates) > smallest:
            raise ValueError("top_k prevyshaet razmer men'shego universuma")
        if (
            "long_short" in self.portfolio.position_mode_candidates
            and 2 * max(self.portfolio.top_k_candidates) > smallest
        ):
            raise ValueError("long_short trebuet ne men'she 2 * top_k instrumentov")
        return self


def load_sequence_config(path: Path) -> SequenceExperimentConfig:
    """Chitaet YAML i bezopasno razreshaet vse servernye katalogi."""
    config_path = path.resolve()
    with config_path.open("r", encoding=TEXT_ENCODING) as stream:
        raw = yaml.safe_load(stream)
    config = SequenceExperimentConfig.model_validate(raw)
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


def sequence_config_as_dict(config: SequenceExperimentConfig) -> dict[str, object]:
    """Preobrazuet konfiguraciyu v stabil'no serializuemyi slovar'."""
    return config.model_dump(mode="json")
