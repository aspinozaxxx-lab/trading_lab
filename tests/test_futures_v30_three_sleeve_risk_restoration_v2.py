"""Tests for the V30-D2 pre-execution boolean-polarity correction."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab import futures_v30_three_sleeve_risk_restoration as v1
from market_lab import futures_v30_three_sleeve_risk_restoration_v2 as source


def _proof_objects() -> tuple[v1.VerifiedInputs, v1.SignalBuild, v1.TargetBuild]:
    verified = v1.VerifiedInputs(
        paths={},
        checks={f"source_{index}": True for index in range(62)},
        metadata={},
    )
    signal = v1.SignalBuild(
        scores=pd.DataFrame(),
        components=pd.DataFrame(),
        checks={f"signal_{index}": True for index in range(14)},
        counts={},
    )
    restored = pd.DataFrame({"target_weight": [0.5]})
    targets = v1.TargetBuild(
        weekly_weights=pd.DataFrame(),
        risk_audit=pd.DataFrame(),
        unscaled_targets=pd.DataFrame(),
        restored_targets=restored,
        hard_2x_targets=pd.DataFrame(),
        decision_audit=pd.DataFrame(),
        weekly_decisions=0,
        roll_decisions=0,
        checks={f"target_{index}": True for index in range(6)},
    )
    return verified, signal, targets


def test_protocol_pins_immutable_failed_parent_and_changes_only_gate() -> None:
    protocol = source.load_protocol()
    correction = protocol.payload["correction_lineage"]

    assert correction["parent_V1_config_sha256"] == source.PARENT_CONFIG_SHA256
    assert correction["failed_V1_attempt"]["output_published"] is False
    assert correction["only_changed_behavior"][
        "source_signal_target_risk_execution_costs_or_gates_changed"
    ] is False
    assert protocol.payload["signal"]["component_weights"] == [1.0 / 3.0] * 3


def test_corrected_aggregation_has_86_true_checks_and_positive_proof() -> None:
    verified, signal, targets = _proof_objects()

    checks = source.corrected_pre_execution_checks(
        verified,
        signal,
        targets,
        predecessor=v1.EXPECTED_PREDECESSOR,
        execution_session_count=1225,
        coverage_rows=1,
    )

    assert len(checks) == 86
    assert all(checks.values())
    assert checks["pre2012_outcomes_not_read_by_V30"] is True
    assert "pre2012_outcomes_read_by_V30" not in checks


def test_corrected_aggregation_rejects_proof_count_drift() -> None:
    verified, signal, targets = _proof_objects()
    verified.checks.pop("source_0")

    with pytest.raises(ValueError, match="aggregated check count drifted"):
        source.corrected_pre_execution_checks(
            verified,
            signal,
            targets,
            predecessor=v1.EXPECTED_PREDECESSOR,
            execution_session_count=1225,
            coverage_rows=1,
        )
