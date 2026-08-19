"""Strogaya konfiguraciya causal multi-resolution modeli futures-v7."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.io_utils import TEXT_ENCODING

DEFAULT_V7_CONFIG_SHA256 = (  # Byte-seal bazovogo development-config v7.
    "bc49f6b52ee99d7e692ae699d63ff3a69bdd3f1257664dab7eb402de9710bb9f"
)
V7_BAR_FEATURES = (  # Fiksirovannye causal-priznaki kazhdoi 10m svechi.
    "log_return_1",
    "log_return_3",
    "log_return_6",
    "range_log",
    "body_log",
    "close_location",
    "log1p_volume",
    "relative_volume_36",
    "realized_volatility_6",
    "realized_volatility_36",
    "session_phase_sin",
    "session_phase_cos",
)
V7_DAILY_FEATURES = (  # Fiksirovannyi PIT-kontekst carry, OI, CBR i CFTC.
    "daily_return_1",
    "daily_return_5",
    "daily_return_20",
    "daily_volatility_20",
    "roll_yield",
    "days_to_expiry_scaled",
    "open_interest_change_1",
    "open_interest_change_5",
    "physical_net_share_lag_1",
    "legal_net_share_lag_1",
    "cbr_key_rate_level",
    "cbr_key_rate_change",
    "cbr_ruonia_spread",
    "cbr_usdrub_return_1",
    "cftc_primary_score",
    "cftc_cross_asset_score",
)
V7_DILATIONS = (1, 2, 4, 8, 16, 32, 64, 128)  # Fiksirovannye masshtaby 10m TCN.
V7_SSL_HORIZONS = (1, 6, 24, 72)  # Gorizonty SSL-return i SSL-vol v barah.
V7_SEEDS = (1729, 2718, 3141)  # Tri zaranee zafiksirovannyh ensemble-seed.
V7_ASSETS = ("BR", "MIX", "RI", "SI")  # Kanonicheskii poryadok bez embeddings.
V7_EXPECTED_PARAMETER_COUNT = 2_245_161  # Tochnoe chislo parametrov fiks-modeli.
V6_FROZEN_CONFIG_SHA256 = (  # Byte-seal benchmark, kotoryi v7 ne izmenyaet.
    "73bc4cba13c65530ae446b0174f14987d0f55d74fdc45e10a8f93b6c6bdcdee9"
)


class V7ModelConfig(BaseModel):
    """Fiksiruet arhitekturu do lyubogo rascheta metrik."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: Literal["causal_multiresolution_tcn_attention_v7"]
    bar_feature_names: tuple[str, ...]
    daily_feature_names: tuple[str, ...]
    sequence_bars: int = Field(ge=128)
    width: int = Field(ge=32)
    temporal_blocks: int = Field(ge=1)
    kernel_size: int = Field(ge=2)
    dilations: tuple[int, ...]
    attention_heads: int = Field(ge=1)
    feedforward_multiplier: int = Field(ge=1)
    dropout: float = Field(ge=0.0, lt=1.0)
    ssl_horizons: tuple[int, ...]
    prediction_target: Literal["next_open_to_next_open_log_return"]
    ticker_embeddings: Literal[False]
    cross_asset_attention_timing: Literal["same_decision_timestamp_only"]
    daily_conditioning: Literal["masked_gated_carry_oi_cbr_cftc"]
    expected_parameter_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_frozen_architecture(self) -> V7ModelConfig:
        """Otkazyvaetsya zagruzhat' lyuboi nezapechatannyi variant arhitektury."""
        expected = {
            "bar_feature_names": V7_BAR_FEATURES,
            "daily_feature_names": V7_DAILY_FEATURES,
            "sequence_bars": 512,
            "width": 192,
            "temporal_blocks": 8,
            "kernel_size": 3,
            "dilations": V7_DILATIONS,
            "attention_heads": 6,
            "feedforward_multiplier": 2,
            "dropout": 0.10,
            "ssl_horizons": V7_SSL_HORIZONS,
            "expected_parameter_count": V7_EXPECTED_PARAMETER_COUNT,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"Architecture drift v7: {field_name}")
        if self.width % self.attention_heads:
            raise ValueError("width dolzhen delit'sya na attention_heads")
        return self


class V7TrainingConfig(BaseModel):
    """Fiksiruet train-only pretraining i supervised schedule bez OOS tuning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seeds: tuple[int, ...]
    deterministic_algorithms: Literal[True]
    accelerator: Literal["single_nvidia_rtx_5090"]
    precision: Literal["bfloat16"]
    optimizer: Literal["adamw"]
    normalization: Literal["train_fold_robust_median_iqr"]
    ssl_epochs: int = Field(ge=1)
    supervised_epochs: int = Field(ge=1)
    ssl_learning_rate: float = Field(gt=0.0)
    supervised_learning_rate: float = Field(gt=0.0)
    weight_decay: float = Field(ge=0.0)
    gradient_clip_norm: float = Field(gt=0.0)
    freeze_first_temporal_blocks: int = Field(ge=0)
    early_stopping: Literal[False]
    seed_aggregation: Literal["arithmetic_mean_prediction"]
    oos_hyperparameter_tuning: Literal[False]

    @model_validator(mode="after")
    def validate_frozen_training(self) -> V7TrainingConfig:
        """Zapreshchaet tihuju smenu schedule posle prosmotra OOS."""
        expected = {
            "seeds": V7_SEEDS,
            "ssl_epochs": 40,
            "supervised_epochs": 25,
            "ssl_learning_rate": 3e-4,
            "supervised_learning_rate": 1e-4,
            "weight_decay": 1e-2,
            "gradient_clip_norm": 1.0,
            "freeze_first_temporal_blocks": 6,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"Training drift v7: {field_name}")
        return self


class V7FoldConfig(BaseModel):
    """Opisivaet odin expanding outer-fold bez peresecheniya targetov."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    train_start: date
    train_end: date
    score_start: date
    score_end: date

    @model_validator(mode="after")
    def validate_order(self) -> V7FoldConfig:
        """Proveryaet hronologicheskii poryadok train i OOS-intervala."""
        if not self.train_start <= self.train_end < self.score_start <= self.score_end:
            raise ValueError(f"Nekorrektnyi expanding fold {self.name}")
        return self


class V7ExecutionProtocolConfig(BaseModel):
    """Nasleduet bez izmenenii ledger i cost-grid zapechatannogo v6."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ledger: Literal["futures_v6_integer_contract_continuous_ledger"]
    initial_capital_rub: float = Field(gt=0.0)
    integer_contracts: Literal[True]
    atomicity_scenarios: tuple[Literal["asset", "portfolio"], ...]
    primary_atomicity: Literal["asset"]
    stress_atomicity: Literal["portfolio"]
    slippage_ticks: tuple[int, ...]
    fee_multipliers: tuple[float, ...]
    maximum_participation: float
    initial_margin_buffer_multiplier: float

    @model_validator(mode="after")
    def validate_v6_execution_identity(self) -> V7ExecutionProtocolConfig:
        """Otkazyvaetsya ot lichnogo cost-grid, otlichnogo ot benchmark v6."""
        expected = {
            "initial_capital_rub": 1_000_000.0,
            "atomicity_scenarios": ("asset", "portfolio"),
            "slippage_ticks": (1, 2, 4),
            "fee_multipliers": (1.0, 2.0),
            "maximum_participation": 0.01,
            "initial_margin_buffer_multiplier": 2.0,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"Execution drift v7: {field_name}")
        return self


class V7DevelopmentProtocolConfig(BaseModel):
    """Fiksiruet development-foldy, purge, benchmark i zakrytyi holdout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assets: tuple[str, ...]
    development_start: date
    development_end: date
    continuous_ledger_start: date
    continuous_ledger_end: date
    positions_reset_between_folds: Literal[False]
    folds: tuple[V7FoldConfig, ...]
    purge_sessions: int = Field(ge=0)
    decision_timezone: Literal["Europe/Moscow"]
    decision_local_time: Literal["18:50:00"]
    intraday_alignment: Literal["exact_same_decision_timestamp"]
    entry_rule: Literal["first_factual_tradable_10m_open_after_decision"]
    exit_rule: Literal["first_factual_tradable_open_of_subsequent_trade_session"]
    scaler_fit_scope: Literal["current_train_fold_only"]
    ssl_label_boundary: Literal["future_horizon_must_end_inside_train_fold"]
    benchmark_name: Literal["futures_v6_frozen_base"]
    benchmark_config_path: Literal["configs/futures_v6_experiment.yaml"]
    benchmark_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_selection: Literal["fixed_architecture_three_seed_mean_no_oos_tuning"]
    protected_holdout_start: date
    protected_holdout_status: Literal["locked_untouched"]
    protected_holdout_local_read_allowed: Literal[False]
    protected_holdout_network_download_allowed: Literal[False]
    protected_holdout_evaluation_budget: Literal[1]

    @model_validator(mode="after")
    def validate_development_seal(self) -> V7DevelopmentProtocolConfig:
        """Proveryaet tochno pyat' expanding-foldov 2021--2025 i lock 2026."""
        expected_years = tuple(range(2021, 2026))
        if self.assets != V7_ASSETS:
            raise ValueError("Universe drift v7")
        if self.development_start != date(2018, 1, 1):
            raise ValueError("Development start drift v7")
        if self.development_end != date(2025, 12, 31):
            raise ValueError("Development end drift v7")
        if (
            self.continuous_ledger_start != date(2021, 1, 1)
            or self.continuous_ledger_end != date(2025, 12, 31)
        ):
            raise ValueError("Continuous ledger boundary drift v7")
        if self.purge_sessions != 5:
            raise ValueError("Purge drift v7")
        if self.benchmark_config_sha256 != V6_FROZEN_CONFIG_SHA256:
            raise ValueError("V6 benchmark seal drift v7")
        if len(self.folds) != len(expected_years):
            raise ValueError("V7 trebuet pyat' outer-foldov")
        for fold, year in zip(self.folds, expected_years, strict=True):
            if fold != V7FoldConfig(
                name=f"outer_{year}",
                train_start=date(2018, 1, 1),
                train_end=date(year - 1, 12, 31),
                score_start=date(year, 1, 1),
                score_end=date(year, 12, 31),
            ):
                raise ValueError(f"Fold drift v7: outer_{year}")
        if self.protected_holdout_start != date(2026, 1, 1):
            raise ValueError("Holdout start drift v7")
        return self


class V7ResearchConfig(BaseModel):
    """Obedinyaet zapechatannye model, training i development protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_name: Literal["futures-v7-causal-multiresolution"]
    protocol_version: Literal[7]
    research_status: Literal["development_only_no_pnl_no_holdout_access"]
    model: V7ModelConfig
    training: V7TrainingConfig
    development: V7DevelopmentProtocolConfig
    execution: V7ExecutionProtocolConfig


def byte_sha256(path: Path) -> str:
    """Vychislyaet SHA-256 tochnyh baitov config bez normalizacii."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_v7_research_config(
    path: Path,
    expected_sha256: str | None = DEFAULT_V7_CONFIG_SHA256,
) -> V7ResearchConfig:
    """Proveryaet byte-seal do YAML-parse i validiruet vse semantic constants."""
    resolved = path.resolve()
    if expected_sha256 is not None:
        actual_sha256 = byte_sha256(resolved)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                "Futures-v7 config seal mismatch: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
    payload = yaml.safe_load(resolved.read_text(encoding=TEXT_ENCODING))
    return V7ResearchConfig.model_validate(payload)
