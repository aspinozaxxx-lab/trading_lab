"""Fail-closed proverki byte-sealed futures-v8 development protocola."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from market_lab.futures_v8.config import (
    DEFAULT_V8_CONFIG_SHA256,
    V8_PURGE_SESSIONS,
    assert_v8_pre_io_development_range,
    byte_sha256,
    load_v8_research_config,
    read_v8_config_sidecar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V8_CONFIG_PATH = PROJECT_ROOT / "configs" / "futures_v8_development_protocol.yaml"


def test_v8_protocol_is_bom_sealed_and_loads_with_exact_sidecar() -> None:
    """Svyazyvaet exact YAML baiti, BOM sidecar i typed sealed config."""
    sidecar = V8_CONFIG_PATH.with_suffix(".sha256")
    assert V8_CONFIG_PATH.read_bytes().startswith(b"\xef\xbb\xbf")
    assert sidecar.read_bytes().startswith(b"\xef\xbb\xbf")
    assert byte_sha256(V8_CONFIG_PATH) == DEFAULT_V8_CONFIG_SHA256
    assert read_v8_config_sidecar(V8_CONFIG_PATH) == DEFAULT_V8_CONFIG_SHA256

    config = load_v8_research_config(V8_CONFIG_PATH)
    assert config.development.purge_sessions == V8_PURGE_SESSIONS == 10
    assert config.development.protected_holdout_start == date(2026, 1, 1)


def test_v8_protocol_seals_ssl_fold_cutoff_target_and_completed_pov_v2() -> None:
    """Proveryaet fresh fold-local SSL, purge-10, target i factual 19:20--19:30."""
    config = load_v8_research_config(V8_CONFIG_PATH)

    assert config.training.ssl_universe == "current_purged_train_fold_only"
    assert config.training.fresh_ssl_per_fold is True
    assert (
        config.training.ssl_input_bar_cutoff
        == "all_input_bars_strictly_before_purged_effective_train_cutoff"
    )
    assert (
        config.training.ssl_label_end_cutoff
        == "every_6_24_72_144_horizon_label_end_strictly_before_purged_effective_train_cutoff"
    )
    assert config.development.pre_io_date_guard == "reject_2026_or_later_before_any_data_io"
    assert config.supervised_target.horizon_common_sessions == 5
    assert (
        config.supervised_target.horizon_interval_definition
        == "five_complete_common_session_intervals_from_entry"
    )
    assert (
        config.supervised_target.exit_timestamp
        == "per_asset_analogous_execution_window_close_after_d_plus_5_common_sessions"
    )
    assert config.supervised_target.same_contract_required is True
    assert config.supervised_target.cash_when_same_contract_target_impossible is True
    assert (
        "missing_or_nonpositive_19_00_19_10_capacity_or_19_20_19_30_execution_window_volume"
        in config.supervised_target.mask_conditions
    )
    assert config.execution.execution_version == "futures-v8-completed-window-pov-v2"
    assert config.execution.order_live_local_time == "19:20:00"
    assert config.execution.execution_window_open_time == "19:20:00"
    assert config.execution.execution_window_close_time == "19:30:00"
    assert (
        config.execution.primary_order_price_policy
        == "market_order_research_fill_at_adverse_high_or_low_of_19_20_19_30_window"
    )


def test_v8_portfolio_protocol_has_exact_non_tunable_rules() -> None:
    """Fiksiruet factor/residual sleeves, cash abstention i whole-contract handoff."""
    portfolio = load_v8_research_config(V8_CONFIG_PATH).portfolio

    assert portfolio.holding_sleeve_count == 5
    assert portfolio.sleeve_weight == 0.20
    assert portfolio.factor_gross_budget == 0.35
    assert portfolio.residual_gross_budget == 0.65
    assert portfolio.combined_gross_cap == 1.0
    assert portfolio.factor_snr_definition == "factor_location_divided_by_factor_scale"
    assert portfolio.factor_common_exposure == "sign_of_factor_snr_if_not_abstained"
    assert portfolio.factor_asset_allocation == "inverse_ex_ante_volatility_across_eligible_assets"
    assert portfolio.factor_abstain_rule == "cash_when_absolute_factor_snr_below_1"
    assert portfolio.residual_score_source == "residual_decision_score"
    assert portfolio.residual_demeaning == "cross_section_demean_across_eligible_assets"
    assert portfolio.residual_inverse_volatility == "inverse_ex_ante_volatility_after_demeaning"
    assert (
        portfolio.residual_net_notional_neutralization
        == "rescale_long_and_short_legs_to_equal_absolute_notional"
    )
    assert (
        portfolio.inference_contract_eligibility
        == "decision_time_current_contract_nominal_maturity_and_session_calendar_only"
    )
    assert (
        portfolio.new_sleeve_cash_condition
        == "cash_only_when_decision_time_known_contract_cannot_span_five_common_sessions"
    )
    assert (
        portfolio.selected_contract_binding
        == "lock_decision_time_contract_for_all_five_sessions"
    )
    assert (
        portfolio.post_entry_contract_failure
        == "carry_and_record_execution_failure_not_hindsight_cash_filter"
    )
    assert portfolio.uncertainty_abstain_position == "cash"
    assert portfolio.minimum_trade_delta_contracts == 1
    assert portfolio.integer_contract_rounding == "truncate_toward_zero_after_allocation"
    assert portfolio.selection_tuning is False


def test_v8_evaluation_is_fixed_report_contract_not_a_post_pnl_selection_surface() -> None:
    """Zapechatyvaet scenarios, gates i adaptive-only status 2021--2025."""
    config = load_v8_research_config(V8_CONFIG_PATH)
    evaluation = config.evaluation

    assert config.development.development_backtest_score_years == (2021, 2022, 2023, 2024, 2025)
    assert (
        config.development.development_backtest_status
        == "adaptive_development_backtest_not_fresh_oos"
    )
    assert evaluation.same_trained_predictions_for_every_scenario is True
    assert evaluation.scenario_selection is False
    assert evaluation.scenarios == {
        "primary": "adverse_high_low_factual_execution_window",
        "doubled_cost": "two_x_fee_and_two_x_slippage",
        "delay_stress": "next_factual_10m_execution_window_only_when_complete",
    }
    assert evaluation.gates.critical_execution_failure_count == 0
    assert evaluation.gates.unresolved_or_carried_positions_at_terminal == 0
    assert evaluation.gates.realized_fill_capacity_maximum_bps == 100
    assert evaluation.gates.unknown_capacity_count == 0
    assert evaluation.gates.primary_net_cagr_minimum == 0.08
    assert evaluation.gates.primary_sharpe_minimum == 0.50
    assert evaluation.gates.primary_max_drawdown_maximum == 0.25
    assert evaluation.gates.positive_calendar_year_fold_count_minimum == 4
    assert evaluation.gates.doubled_cost_cagr_must_be_positive is True
    assert evaluation.gates.worst_calendar_year_return_minimum == -0.10
    assert evaluation.stretch_report_only.primary_net_cagr_minimum == 0.50
    assert evaluation.stretch_report_only.used_for_selection is False
    assert evaluation.stretch_report_only.used_for_holdout_access is False
    assert evaluation.protected_holdout_access == "locked_until_all_fixed_gates_pass"


def test_v8_config_rejects_byte_and_sidecar_drift_before_yaml_use(tmp_path: Path) -> None:
    """Ne dopuskaet ni pravku YAML, ni storonnii sidecar pod sealed default hash."""
    config_path = tmp_path / V8_CONFIG_PATH.name
    sidecar_path = config_path.with_suffix(".sha256")
    shutil.copyfile(V8_CONFIG_PATH, config_path)
    shutil.copyfile(V8_CONFIG_PATH.with_suffix(".sha256"), sidecar_path)
    config_path.write_bytes(config_path.read_bytes() + b"# drift\n")

    with pytest.raises(ValueError, match="config seal mismatch"):
        load_v8_research_config(config_path)

    shutil.copyfile(V8_CONFIG_PATH, config_path)
    sidecar_path.write_bytes(
        b"\xef\xbb\xbf" + ("0" * 64 + "  " + config_path.name + "\n").encode("ascii")
    )
    with pytest.raises(ValueError, match="sidecar seal mismatch"):
        load_v8_research_config(config_path)


def test_v8_pre_io_guard_rejects_holdout_and_invalid_ranges() -> None:
    """Fail-closed date check runs before caller may request any market-data I/O."""
    config = load_v8_research_config(V8_CONFIG_PATH)
    assert_v8_pre_io_development_range(date(2018, 1, 1), date(2025, 12, 31), config)

    with pytest.raises(ValueError, match="2026 holdout"):
        assert_v8_pre_io_development_range(date(2025, 12, 31), date(2026, 1, 1), config)
    with pytest.raises(ValueError, match="nachinaetsia do development"):
        assert_v8_pre_io_development_range(date(2017, 12, 31), date(2025, 1, 1), config)
    with pytest.raises(ValueError, match="start posle end"):
        assert_v8_pre_io_development_range(date(2025, 2, 1), date(2025, 1, 1), config)
