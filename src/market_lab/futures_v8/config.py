"""Zapechatannaia arhitektura i train-budget robustnogo futures-v8 alpha."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.io_utils import TEXT_ENCODING

V8_BAR_FEATURES = (
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
V8_DAILY_FEATURES = (
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
V8_ASSETS = ("BR", "MIX", "RI", "SI")
V8_SEEDS = (1729, 2718, 3141)
V8_SSL_HORIZONS = (6, 24, 72, 144)
V8_EXPECTED_PARAMETER_COUNT = 2_694_086  # Exact count sealed before any v8 evaluation.
V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT = 149_534
DEFAULT_V8_CONFIG_SHA256 = "e0175b0e02d5a304d90f33f61bd77ed5649005e91e6af50662d4545dc070035d"
V8_CONFIG_SIDECAR_SUFFIX = ".sha256"
V8_PURGE_SESSIONS = 10
V8_PARTICIPATION_BPS = 100
V8_TARGET_HORIZON_COMMON_SESSIONS = 5
V8_DAILY_VOLATILITY_FLOOR = 0.01
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class V8ModelConfig(BaseModel):
    """Fiksiruet patch-state-space alpha-set do lyuboi OOS ocenki."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: Literal["causal_patch_state_space_regime_alpha_v8"]
    bar_feature_names: tuple[str, ...]
    daily_feature_names: tuple[str, ...]
    sequence_bars: Literal[512]
    patch_size_bars: Literal[8]
    width: Literal[160]
    state_space_blocks: Literal[6]
    attention_heads: Literal[5]
    feedforward_multiplier: Literal[3]
    dropout: Literal[0.10]
    regime_experts: Literal[3]
    crash_expert_index: Literal[2]
    contrastive_projection_width: Literal[64]
    ssl_horizons: tuple[int, ...]
    target_scale: Literal["train_fold_cross_asset_iqr"]
    abstain_z_threshold: Literal[1.0]
    abstain_temperature: Literal[0.25]
    scale_floor_iqr: Literal[0.05]
    ticker_embeddings: Literal[False]
    temporal_attention: Literal["causal_patch_only"]
    cross_asset_attention_timing: Literal["same_decision_timestamp_only"]
    daily_conditioning: Literal["masked_gated_carry_oi_cbr_cftc"]
    expected_parameter_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_seal(self) -> V8ModelConfig:
        """Otkazyvaet drift kanala, razmera ili number specialistov."""
        expected = {
            "bar_feature_names": V8_BAR_FEATURES,
            "daily_feature_names": V8_DAILY_FEATURES,
            "ssl_horizons": V8_SSL_HORIZONS,
            "expected_parameter_count": V8_EXPECTED_PARAMETER_COUNT,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"Architecture drift v8: {field_name}")
        if self.width % self.attention_heads:
            raise ValueError("width dolzhen delit'sia na attention_heads")
        if self.sequence_bars % self.patch_size_bars:
            raise ValueError("sequence_bars dolzhen delit'sia na patch_size_bars")
        if not 0 <= self.crash_expert_index < self.regime_experts:
            raise ValueError("crash_expert_index vne specialistov")
        return self


class V8TrainingConfig(BaseModel):
    """Fiksiruet bol'shoi SSL i malyi supervised budget bez OOS podbora."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seeds: tuple[int, ...]
    deterministic_algorithms: Literal[True]
    accelerator: Literal["single_nvidia_rtx_5090"]
    precision: Literal["bfloat16"]
    optimizer: Literal["adamw"]
    ssl_universe: Literal["current_purged_train_fold_only"]
    fresh_ssl_per_fold: Literal[True]
    ssl_input_bar_cutoff: Literal[
        "all_input_bars_strictly_before_purged_effective_train_cutoff"
    ]
    ssl_label_end_cutoff: Literal[
        "every_6_24_72_144_horizon_label_end_strictly_before_purged_effective_train_cutoff"
    ]
    feature_scaler_fit_scope: Literal["target_valid_current_purged_train_fold_only"]
    ssl_epochs: Literal[48]
    supervised_epochs: Literal[32]
    ssl_learning_rate: Literal[0.0003]
    supervised_learning_rate: Literal[0.00015]
    weight_decay: Literal[0.02]
    gradient_clip_norm: Literal[1.0]
    supervised_encoder: Literal["frozen_ssl_patch_state_space"]
    supervised_trainable_parameter_count: Literal[149534]
    return_loss: Literal["iqr_scaled_residual_gaussian_nll"]
    auxiliary_direction_loss: Literal["separate_residual_direction_bce"]
    cost_aware_loss: Literal["differentiable_turnover_penalized_residual_utility"]
    contrastive_loss: Literal["causal_two_view_infonce"]
    direction_loss_weight: Literal[0.05]
    crash_loss_weight: Literal[0.05]
    regime_balance_weight: Literal[0.01]
    cost_aware_loss_weight: Literal[0.10]
    one_way_cost_proxy_version: Literal["futures-conservative-spec-proxy-v1"]
    one_way_cost_spec_manifest_path: Literal[
        "data/processed/futures_v5_specs_v1/"
        "spec_proxy_2018-01-01_2025-12-31_87372f337a75eeb4/manifest.json"
    ]
    one_way_cost_spec_manifest_sha256: Literal[
        "b1cada60c44296641062bb6ca7c45d12fa4c5b261810e4bb100edae458eb20d3"
    ]
    one_way_cost_formula: Literal[
        "((conservative_fee_per_side+1*sizing_tick_cash_value)/sizing_notional)"
        "/(max(d_known_daily_volatility_20,0.01)*sqrt(5)*train_target_iqr)"
    ]
    one_way_cost_join: Literal[
        "entry_effective_date_same_contract_asset_spec_proxy_row"
    ]
    one_way_cost_asof_rule: Literal[
        "sizing_observed_session_date_equals_decision_d"
    ]
    one_way_cost_fee_side_multiplier: Literal[1]
    one_way_cost_slippage_ticks: Literal[1]
    unknown_one_way_cost_policy: Literal[
        "fail_every_residual_valid_row_no_zero_no_skip"
    ]
    crash_label_threshold_iqr: Literal[2.5]
    oos_hyperparameter_tuning: Literal[False]
    early_stopping: Literal[False]
    max_wall_clock_minutes: Literal[90]

    @model_validator(mode="after")
    def validate_seal(self) -> V8TrainingConfig:
        """Proveryaet fixed RTX5090 budget i razdelenie location/logit golov."""
        expected = {
            "seeds": V8_SEEDS,
            "ssl_epochs": 48,
            "supervised_epochs": 32,
            "ssl_learning_rate": 3e-4,
            "supervised_learning_rate": 1.5e-4,
            "weight_decay": 2e-2,
            "gradient_clip_norm": 1.0,
            "supervised_trainable_parameter_count": V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"Training drift v8: {field_name}")
        if not self.fresh_ssl_per_fold:
            raise ValueError("V8 SSL dolzhen byt' svezhe obuchen v kazhdom fold")
        return self


class V8FoldConfig(BaseModel):
    """Opisivaet expanding-fold s zakrytym targetom do score perioda."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    train_start: date
    train_end: date
    score_start: date
    score_end: date

    @model_validator(mode="after")
    def validate_order(self) -> V8FoldConfig:
        """Trebuet strogoe chronologicheskoe razdelenie train i score."""
        if not self.train_start <= self.train_end < self.score_start <= self.score_end:
            raise ValueError(f"Nekorrektnyi expanding fold {self.name}")
        return self


class V8DevelopmentConfig(BaseModel):
    """Fiksiruet tol'ko development do 2025 i purged fold granicy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assets: tuple[str, ...]
    development_start: date
    development_end: date
    protected_holdout_start: date
    development_backtest_score_years: tuple[int, ...]
    development_backtest_status: Literal["adaptive_development_backtest_not_fresh_oos"]
    folds: tuple[V8FoldConfig, ...]
    purge_sessions: Literal[10]
    decision_timezone: Literal["Europe/Moscow"]
    decision_local_time: Literal["18:50:00"]
    intraday_alignment: Literal["exact_same_decision_timestamp"]
    effective_train_cutoff: Literal["fold_train_end_minus_10_sessions"]
    supervised_target_end_cutoff: Literal[
        "target_exit_window_close_strictly_before_purged_effective_train_cutoff"
    ]
    pre_io_date_guard: Literal["reject_2026_or_later_before_any_data_io"]
    channels: tuple[str, ...]
    sleeping_channels: tuple[str, ...]
    protected_holdout_local_read_allowed: Literal[False]
    protected_holdout_network_download_allowed: Literal[False]

    @model_validator(mode="after")
    def validate_seal(self) -> V8DevelopmentConfig:
        """Fail-closed zapreshchaet 2026, neodobrennye kanaly i time drift."""
        if self.assets != V8_ASSETS:
            raise ValueError("Universe drift v8")
        if self.development_start != date(2018, 1, 1):
            raise ValueError("Development start drift v8")
        if self.development_end != date(2025, 12, 31):
            raise ValueError("Development end drift v8")
        if self.protected_holdout_start != date(2026, 1, 1):
            raise ValueError("Holdout boundary drift v8")
        if self.development_backtest_score_years != tuple(range(2021, 2026)):
            raise ValueError("V8 development backtest score-year drift")
        if self.purge_sessions != V8_PURGE_SESSIONS:
            raise ValueError("Purge drift v8")
        if self.channels != (
            "10m_ohlcv",
            "daily_open_interest_numtrades",
            "participant_open_interest",
            "cbr",
            "cftc",
            "carry",
        ):
            raise ValueError("Information-channel drift v8")
        if self.sleeping_channels != ("filings", "news"):
            raise ValueError("Filings/news dolzhny ostavat'sia sleeping")
        expected_years = tuple(range(2021, 2026))
        if len(self.folds) != len(expected_years):
            raise ValueError("V8 trebuet pyat' expanding outer-foldov")
        for fold, year in zip(self.folds, expected_years, strict=True):
            expected = V8FoldConfig(
                name=f"outer_{year}",
                train_start=date(2018, 1, 1),
                train_end=date(year - 1, 12, 31),
                score_start=date(year, 1, 1),
                score_end=date(year, 12, 31),
            )
            if fold != expected:
                raise ValueError(f"Fold drift v8: outer_{year}")
        return self


class V8ExecutionProtocolConfig(BaseModel):
    """Opisivaet tol'ko completed-window POV v2, a ne ozhidaemyi queue fill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_version: Literal["futures-v8-completed-window-pov-v2"]
    decision_timezone: Literal["Europe/Moscow"]
    decision_local_time: Literal["18:50:00"]
    capacity_observation_window_open_time: Literal["19:00:00"]
    capacity_observation_window_close_time: Literal["19:10:00"]
    mandatory_order_latency_minutes: Literal[10]
    order_live_local_time: Literal["19:20:00"]
    execution_window_open_time: Literal["19:20:00"]
    execution_window_close_time: Literal["19:30:00"]
    max_observed_bar_participation_bps: Literal[100]
    max_realized_execution_window_participation_bps: Literal[100]
    primary_order_price_policy: Literal[
        "market_order_research_fill_at_adverse_high_or_low_of_19_20_19_30_window"
    ]
    adverse_hl_ledger: Literal["buy_high_sell_low_of_factual_execution_window"]
    provenance: Literal["research_only_not_queue_exact"]
    paired_roll_policy: Literal["paired_research_fill_broker_atomicity_not_proven"]

    @model_validator(mode="after")
    def validate_seal(self) -> V8ExecutionProtocolConfig:
        """Trebuet 10m observe, 10m latency i polnyi 19:20--19:30 POV window."""
        if (
            self.max_observed_bar_participation_bps != V8_PARTICIPATION_BPS
            or self.max_realized_execution_window_participation_bps != V8_PARTICIPATION_BPS
        ):
            raise ValueError("V8 POV dolzhen byt' ravno 1 procentu oboih factual volumes")
        return self


class V8SupervisedTargetConfig(BaseModel):
    """Fiksiruet PIT 5-session target po odnomu factual contract bez roll-skleyki."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_target: Literal["direction_independent_log_return"]
    primary_formula: Literal["log_exit_window_close_over_entry_window_close"]
    horizon_common_sessions: Literal[5]
    horizon_interval_definition: Literal["five_complete_common_session_intervals_from_entry"]
    entry_timestamp: Literal["per_asset_factual_19_20_19_30_window_close"]
    exit_timestamp: Literal[
        "per_asset_analogous_execution_window_close_after_d_plus_5_common_sessions"
    ]
    label_available_after: Literal["per_asset_exit_window_close_only"]
    volatility_scale: Literal[
        "max_ex_ante_d_known_daily_volatility_20_or_floor_times_sqrt_5"
    ]
    daily_volatility_floor: Literal[0.01]
    factor_definition: Literal["cross_asset_mean_of_valid_primary_targets"]
    residual_definition: Literal["primary_target_minus_same_timestamp_cross_asset_factor"]
    residual_minimum_valid_assets: Literal[2]
    auxiliary_direction_target: Literal["sign_of_residual_target"]
    train_iqr_fit_scope: Literal["target_valid_current_purged_train_fold_only"]
    mask_conditions: tuple[str, ...]
    same_contract_required: Literal[True]
    cash_when_same_contract_target_impossible: Literal[True]

    @model_validator(mode="after")
    def validate_seal(self) -> V8SupervisedTargetConfig:
        """Zapreshchaet target s rollom, budushchim exit ili ne-PIT volatility."""
        if self.horizon_common_sessions != V8_TARGET_HORIZON_COMMON_SESSIONS:
            raise ValueError("V8 target horizon drift")
        if self.daily_volatility_floor != V8_DAILY_VOLATILITY_FLOOR:
            raise ValueError("V8 daily volatility floor drift")
        expected_mask_conditions = (
            "missing_or_incomplete_factual_entry_or_exit_window",
            "missing_or_nonpositive_19_00_19_10_capacity_or_19_20_19_30_execution_window_volume",
            "active_contract_change_or_roll_within_horizon",
            "unpriced_carry",
            "exit_window_close_not_strictly_before_fold_cutoff",
        )
        if self.mask_conditions != expected_mask_conditions:
            raise ValueError("V8 target mask drift")
        return self


class V8PortfolioProtocolConfig(BaseModel):
    """Fiksiruet pyat' sleeves, factor/residual budgety i cash abstention bez tuning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holding_sleeve_count: Literal[5]
    sleeve_weight: Literal[0.20]
    new_sleeve_cadence: Literal["each_common_session"]
    sleeve_entry: Literal["factual_19_20_19_30_execution_window"]
    sleeve_exit: Literal["analogous_execution_window_after_d_plus_5_common_sessions"]
    factor_gross_budget: Literal[0.35]
    residual_gross_budget: Literal[0.65]
    combined_gross_cap: Literal[1.0]
    factor_snr_definition: Literal["factor_location_divided_by_factor_scale"]
    factor_common_exposure: Literal["sign_of_factor_snr_if_not_abstained"]
    factor_asset_allocation: Literal["inverse_ex_ante_volatility_across_eligible_assets"]
    factor_abstain_z_threshold: Literal[1.0]
    factor_abstain_rule: Literal["cash_when_absolute_factor_snr_below_1"]
    residual_score_source: Literal["residual_decision_score"]
    residual_demeaning: Literal["cross_section_demean_across_eligible_assets"]
    residual_inverse_volatility: Literal["inverse_ex_ante_volatility_after_demeaning"]
    residual_net_notional_neutralization: Literal[
        "rescale_long_and_short_legs_to_equal_absolute_notional"
    ]
    residual_neutrality: Literal["net_notional_neutral_only_no_beta_claim"]
    inference_contract_eligibility: Literal[
        "decision_time_current_contract_nominal_maturity_and_session_calendar_only"
    ]
    new_sleeve_cash_condition: Literal[
        "cash_only_when_decision_time_known_contract_cannot_span_five_common_sessions"
    ]
    selected_contract_binding: Literal["lock_decision_time_contract_for_all_five_sessions"]
    post_entry_contract_failure: Literal[
        "carry_and_record_execution_failure_not_hindsight_cash_filter"
    ]
    invalid_or_same_contract_impossible_position: Literal["cash"]
    uncertainty_abstain_position: Literal["cash"]
    no_leverage_above_one: Literal[True]
    minimum_trade_delta_contracts: Literal[1]
    minimum_trade_rule: Literal[
        "no_trade_if_absolute_desired_delta_less_than_one_contract"
    ]
    integer_contract_rounding: Literal["truncate_toward_zero_after_allocation"]
    costs_and_initial_margin: Literal["handled_by_ledger"]
    selection_tuning: Literal[False]

    @model_validator(mode="after")
    def validate_seal(self) -> V8PortfolioProtocolConfig:
        """Trebuet sealed sleeves, gross-cap, abstention i integer executor handoff."""
        if self.holding_sleeve_count != V8_TARGET_HORIZON_COMMON_SESSIONS:
            raise ValueError("V8 holding sleeve count drift")
        if self.sleeve_weight * self.holding_sleeve_count != 1.0:
            raise ValueError("V8 sleeve weights dolzhny summirovat'sia v 1")
        if self.factor_gross_budget + self.residual_gross_budget != self.combined_gross_cap:
            raise ValueError("V8 factor/residual gross budget drift")
        return self


class V8EvaluationGatesConfig(BaseModel):
    """Fiksiruet edinstvennye gates dlia otkrytiya zablokirovannogo 2026 holdout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    critical_execution_failure_count: Literal[0]
    unresolved_or_carried_positions_at_terminal: Literal[0]
    realized_fill_capacity_maximum_bps: Literal[100]
    unknown_capacity_count: Literal[0]
    primary_net_cagr_minimum: Literal[0.08]
    primary_sharpe_minimum: Literal[0.50]
    primary_max_drawdown_maximum: Literal[0.25]
    positive_calendar_year_fold_count_minimum: Literal[4]
    doubled_cost_cagr_must_be_positive: Literal[True]
    worst_calendar_year_return_minimum: Literal[-0.10]


class V8StretchReportOnlyConfig(BaseModel):
    """Otmechaet nedostizhimo vysokii CAGR kak report-only, ne selection gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_net_cagr_minimum: Literal[0.50]
    used_for_selection: Literal[False]
    used_for_holdout_access: Literal[False]


class V8EvaluationProtocolConfig(BaseModel):
    """Fiksiruet scenarios i gates do lyubogo PnL bez adaptive vybora."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    same_trained_predictions_for_every_scenario: Literal[True]
    scenario_selection: Literal[False]
    scenarios: dict[
        Literal["primary", "doubled_cost", "delay_stress"],
        Literal[
            "adverse_high_low_factual_execution_window",
            "two_x_fee_and_two_x_slippage",
            "next_factual_10m_execution_window_only_when_complete",
        ],
    ]
    gates: V8EvaluationGatesConfig
    stretch_report_only: V8StretchReportOnlyConfig
    protected_holdout_access: Literal["locked_until_all_fixed_gates_pass"]

    @model_validator(mode="after")
    def validate_seal(self) -> V8EvaluationProtocolConfig:
        """Otkazyvaet propusk scenario, replacement or PnL-adaptive gate drift."""
        expected = {
            "primary": "adverse_high_low_factual_execution_window",
            "doubled_cost": "two_x_fee_and_two_x_slippage",
            "delay_stress": "next_factual_10m_execution_window_only_when_complete",
        }
        if self.scenarios != expected:
            raise ValueError("V8 evaluation scenario drift")
        return self


class V8ResearchConfig(BaseModel):
    """Obedinyaet sealed v8 architecture, training i causal development rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_name: Literal["futures-v8-regime-residual-alpha"]
    protocol_version: Literal[8]
    research_status: Literal["architecture_fixed_no_pnl_no_holdout_access"]
    model: V8ModelConfig
    training: V8TrainingConfig
    development: V8DevelopmentConfig
    execution: V8ExecutionProtocolConfig
    supervised_target: V8SupervisedTargetConfig
    portfolio: V8PortfolioProtocolConfig
    evaluation: V8EvaluationProtocolConfig

    @model_validator(mode="after")
    def validate_cross_section_seal(self) -> V8ResearchConfig:
        """Svyazyvaet decision, target i fold rules v odin fail-closed contract."""
        if (
            self.development.decision_timezone != self.execution.decision_timezone
            or self.development.decision_local_time != self.execution.decision_local_time
        ):
            raise ValueError("V8 decision timing drift mezhdu development i execution")
        if self.training.feature_scaler_fit_scope != self.supervised_target.train_iqr_fit_scope:
            raise ValueError("V8 IQR/scaler fit scope drift")
        if self.portfolio.factor_abstain_z_threshold != self.model.abstain_z_threshold:
            raise ValueError("V8 factor i model abstain threshold drift")
        return self


def byte_sha256(path: Path) -> str:
    """Vychisliaet SHA-256 exact baitov config bez text-normalizacii."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def v8_config_sidecar_path(path: Path) -> Path:
    """Vozvrashchaet obligatory byte-seal sidecar dlia konkretnogo YAML."""
    return path.with_suffix(V8_CONFIG_SIDECAR_SUFFIX)


def read_v8_config_sidecar(path: Path) -> str:
    """Chitaet exact ``sha256  filename`` sidecar s BOM i otkazyvaet drift imeni."""
    resolved = path.resolve()
    sidecar = v8_config_sidecar_path(resolved)
    try:
        content = sidecar.read_text(encoding=TEXT_ENCODING)
    except FileNotFoundError as exc:
        raise ValueError(f"Futures-v8 config sidecar missing: {sidecar}") from exc
    match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)\r?\n?", content)
    if match is None or match.group(2) != resolved.name:
        raise ValueError(f"Futures-v8 config sidecar invalid: {sidecar}")
    return match.group(1)


def assert_v8_pre_io_development_range(
    start: date,
    end: date,
    config: V8ResearchConfig | V8DevelopmentConfig,
) -> None:
    """Fail-closed date guard, kotoryi vyzyvaetsya do chteniya market-data."""
    if not isinstance(start, date) or not isinstance(end, date):
        raise TypeError("V8 pre-I/O date range dolzhen soderzhat' date")
    if start > end:
        raise ValueError("V8 pre-I/O date range imeet start posle end")
    development = config.development if isinstance(config, V8ResearchConfig) else config
    if start < development.development_start:
        raise ValueError("V8 pre-I/O date range nachinaetsia do development perioda")
    if end >= development.protected_holdout_start:
        raise ValueError("V8 pre-I/O guard zapreshchaet 2026 holdout")


def load_v8_research_config(
    path: Path,
    expected_sha256: str = DEFAULT_V8_CONFIG_SHA256,
) -> V8ResearchConfig:
    """Proveryaet sidecar i byte-seal prezhde YAML semantic validation v8."""
    resolved = path.resolve()
    if not isinstance(expected_sha256, str) or _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise ValueError("Futures-v8 expected config SHA-256 invalid")
    sidecar_sha256 = read_v8_config_sidecar(resolved)
    if sidecar_sha256 != expected_sha256:
        raise ValueError(
            "Futures-v8 config sidecar seal mismatch: "
            f"expected {expected_sha256}, got {sidecar_sha256}"
        )
    actual_sha256 = byte_sha256(resolved)
    if actual_sha256 != sidecar_sha256:
        raise ValueError(
            "Futures-v8 config seal mismatch: "
            f"sidecar {sidecar_sha256}, got {actual_sha256}"
        )
    with resolved.open("r", encoding=TEXT_ENCODING) as stream:
        payload = yaml.safe_load(stream)
    return V8ResearchConfig.model_validate(payload)


__all__ = [
    "V8_ASSETS",
    "V8_BAR_FEATURES",
    "V8_DAILY_FEATURES",
    "V8_EXPECTED_PARAMETER_COUNT",
    "V8_SEEDS",
    "V8_SSL_HORIZONS",
    "V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT",
    "V8_PURGE_SESSIONS",
    "V8_PARTICIPATION_BPS",
    "V8_TARGET_HORIZON_COMMON_SESSIONS",
    "V8_DAILY_VOLATILITY_FLOOR",
    "DEFAULT_V8_CONFIG_SHA256",
    "V8DevelopmentConfig",
    "V8EvaluationGatesConfig",
    "V8EvaluationProtocolConfig",
    "V8ExecutionProtocolConfig",
    "V8FoldConfig",
    "V8ModelConfig",
    "V8PortfolioProtocolConfig",
    "V8ResearchConfig",
    "V8SupervisedTargetConfig",
    "V8StretchReportOnlyConfig",
    "V8TrainingConfig",
    "assert_v8_pre_io_development_range",
    "byte_sha256",
    "load_v8_research_config",
    "read_v8_config_sidecar",
    "v8_config_sidecar_path",
]
