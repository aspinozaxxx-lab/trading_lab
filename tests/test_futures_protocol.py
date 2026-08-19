"""Proverki zapechatannogo futures-v5 protocola bez rynochnyh dannyh."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from market_lab.futures.protocol import (
    EXPECTED_FUTURES_V5_SEMANTICS,
    FUTURES_V5_PROTOCOL_SHA256,
    futures_protocol_sha256,
    load_futures_v5_protocol,
    validate_futures_v5_protocol,
    verify_futures_protocol_seal,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren testov zapechatannogo protocola.
PROTOCOL_PATH = (  # Kanonicheskii futures-v5 YAML bez svyazi s katalogami dannyh.
    PROJECT_ROOT / "configs" / "futures_v5_protocol.yaml"
)


def _canonical_payload() -> dict[str, object]:
    """Kopiruet etalon, chtoby mutation-test ne menyal globalnyi seal."""
    return deepcopy(EXPECTED_FUTURES_V5_SEMANTICS)


def test_sealed_protocol_loads_without_accessing_holdout_data() -> None:
    """Proveryaet mapping instrumentov i yavnye zaprety holdout I/O."""
    protocol = load_futures_v5_protocol(PROTOCOL_PATH)
    mapping = {
        item.logical_symbol: (item.asset_code, item.security_prefix)
        for item in protocol.universe.instruments
    }
    assert mapping == {
        "Si": ("Si", "Si"),
        "RI": ("RTS", "RI"),
        "BR": ("BR", "BR"),
        "MIX": ("MIX", "MX"),
    }
    assert protocol.periods.development_start.isoformat() == "2018-01-01"
    assert protocol.periods.development_end.isoformat() == "2025-12-31"
    assert protocol.periods.holdout.start.isoformat() == "2026-01-01"
    assert protocol.periods.holdout.end.isoformat() == "2026-07-31"
    assert protocol.periods.holdout.evaluation_budget == 1
    assert protocol.periods.holdout.status == "untouched"
    assert protocol.periods.holdout.network_download_allowed is False
    assert protocol.periods.holdout.local_read_allowed is False


def test_outer_folds_are_exactly_expanding_2021_through_2025() -> None:
    """Proveryaet pyat' godovyh outer-fold s edinym startom i purge=5."""
    protocol = load_futures_v5_protocol(PROTOCOL_PATH)
    assert protocol.validation.purge_sessions == 5
    assert [fold.outer_start.year for fold in protocol.validation.folds] == list(
        range(2021, 2026)
    )
    for fold in protocol.validation.folds:
        assert fold.train_start.isoformat() == "2018-01-01"
        assert fold.train_end.year == fold.outer_start.year - 1
        assert fold.train_end.month == 12
        assert fold.train_end.day == 31
        assert fold.outer_end.year == fold.outer_start.year


def test_causal_roll_feature_timing_and_forward_adjustment_are_frozen() -> None:
    """Proveryaet dva podtverzhdeniya, next-open, OI-lag i zapret back-adjust."""
    protocol = load_futures_v5_protocol(PROTOCOL_PATH)
    assert protocol.roll.ranking_inputs == [
        "session_volume",
        "contract_open_interest",
    ]
    assert protocol.roll.dominance_sessions == 2
    assert protocol.roll.dominance_ratio == 1.0
    assert protocol.roll.hard_fallback_sessions_before_expiry == 5
    assert protocol.roll.execution_time == "next_session_open"
    assert protocol.roll.adjustment_direction == "forward_only"
    assert protocol.roll.adjustment_method == "additive"
    assert protocol.roll.adjustment_anchor == "settle"
    assert protocol.roll.execution_failure_policy == "carry_position_and_invalidate_run"
    assert protocol.roll.backward_adjustment_allowed is False
    participant_oi = protocol.feature_timing.participant_open_interest
    assert participant_oi.availability_lag_sessions == 1
    assert participant_oi.usable_from == "next_session"
    assert participant_oi.same_session_use_allowed is False


def test_execution_cost_stresses_and_stretch_only_goal_are_frozen() -> None:
    """Proveryaet integer sizing, risk-limity i rol CAGR tolko kak stretch."""
    protocol = load_futures_v5_protocol(PROTOCOL_PATH)
    execution = protocol.execution
    assert execution.integer_contracts is True
    assert execution.maximum_gross_leverage == 1.0
    assert execution.initial_margin_buffer_multiplier == 2.0
    assert execution.maximum_participation == 0.01
    assert execution.costs.tick_stress_scenarios == [1, 2, 4]
    assert execution.costs.fee_multiplier_scenarios == [1.0, 2.0]
    gates = protocol.pre_holdout_gates
    assert gates.minimum_positive_outer_folds == 4
    assert gates.minimum_aggregate_net_cagr == 0.12
    assert gates.minimum_aggregate_net_sharpe == 0.80
    assert gates.maximum_aggregate_drawdown == 0.25
    assert gates.minimum_double_cost_net_cagr == 0.0
    assert gates.maximum_failed_execution_events == 0
    assert gates.model_and_feature_seal_required is True
    assert protocol.research_limits.broker_executable_pnl_claim_allowed is False
    assert protocol.stretch_gate.minimum_net_cagr == 0.50
    assert protocol.stretch_gate.role == "stretch_only"
    assert protocol.stretch_gate.used_for_model_selection is False
    assert protocol.stretch_gate.used_for_holdout_access is False
    assert protocol.stretch_gate.guarantee is False
    assert protocol.stretch_gate.live_trading_allowed is False


@pytest.mark.parametrize(
    ("section", "field", "drifted_value"),
    [
        ("roll", "dominance_sessions", 1),
        ("roll", "backward_adjustment_allowed", True),
        ("execution", "maximum_gross_leverage", 1.01),
        ("stretch_gate", "used_for_model_selection", True),
    ],
)
def test_validator_rejects_semantic_drift(
    section: str,
    field: str,
    drifted_value: object,
) -> None:
    """Proveryaet fail-closed otklonenie ekonomicheski znachimoi podmeny."""
    payload = _canonical_payload()
    nested = payload[section]
    assert isinstance(nested, dict)
    nested[field] = drifted_value
    with pytest.raises(ValidationError, match="Semantic drift futures-v5"):
        validate_futures_v5_protocol(payload)


def test_validator_rejects_holdout_unlock_and_instrument_remap() -> None:
    """Proveryaet zapret tikhogo chteniya holdout i podmeny RI asset_code."""
    holdout_drift = _canonical_payload()
    periods = holdout_drift["periods"]
    assert isinstance(periods, dict)
    holdout = periods["holdout"]
    assert isinstance(holdout, dict)
    holdout["local_read_allowed"] = True
    with pytest.raises(ValidationError, match="Semantic drift futures-v5"):
        validate_futures_v5_protocol(holdout_drift)

    mapping_drift = _canonical_payload()
    universe = mapping_drift["universe"]
    assert isinstance(universe, dict)
    instruments = universe["instruments"]
    assert isinstance(instruments, list)
    instruments[1]["asset_code"] = "RI"
    with pytest.raises(ValidationError, match="Semantic drift futures-v5"):
        validate_futures_v5_protocol(mapping_drift)


def test_sha256_helper_binds_exact_protocol_bytes(tmp_path: Path) -> None:
    """Proveryaet kanonicheskii seal i otkaz posle odnotovoi byte-podmeny."""
    assert futures_protocol_sha256(PROTOCOL_PATH) == FUTURES_V5_PROTOCOL_SHA256
    assert verify_futures_protocol_seal(PROTOCOL_PATH) == FUTURES_V5_PROTOCOL_SHA256
    changed = tmp_path / "futures_v5_protocol.yaml"
    changed.write_bytes(PROTOCOL_PATH.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="seal mismatch"):
        verify_futures_protocol_seal(changed)
