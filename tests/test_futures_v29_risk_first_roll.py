"""Tests for the sealed post-V28 risk-first roll-capacity correction."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v29_risk_first_roll as v29
from market_lab.futures import portfolio_ledger as ledger_engine


def _indexed_market(*rows: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(rows).set_index(
        ["session_date", "asset_code", "contract_id"]
    )


def _roll_state(
    *,
    old_volume: float = 8_451.0,
    new_volume: float | None = 137.0,
) -> tuple[
    dict[str, tuple[str | None, int, pd.Series | None]],
    dict[str, ledger_engine._PortfolioPosition],
    pd.DataFrame,
]:
    session = pd.Timestamp("2014-05-12")
    old_contract = "BR:BRK4:2014-05-16"
    new_contract = "BR:BRM4:2014-06-16"
    rows: list[dict[str, Any]] = [
        {
            "session_date": session,
            "asset_code": "BR",
            "contract_id": old_contract,
            "open": 108.0,
            "lagged_volume": old_volume,
        }
    ]
    if new_volume is not None:
        rows.append(
            {
                "session_date": session,
                "asset_code": "BR",
                "contract_id": new_contract,
                "open": 109.0,
                "lagged_volume": new_volume,
            }
        )
    indexed = _indexed_market(*rows)
    desired_row = (
        indexed.loc[(session, "BR", new_contract)] if new_volume is not None else None
    )
    desired = {"BR": (new_contract, 25, desired_row)}
    positions = {
        "BR": ledger_engine._PortfolioPosition(
            contract_id=old_contract,
            contracts=14,
            previous_settle=107.0,
        )
    }
    return desired, positions, indexed


def test_real_protocol_seal_and_parent_identity_are_exact() -> None:
    protocol = v29.load_protocol()

    assert (
        protocol.config_sha256
        == "d92f8cf2dbc1576dfbbb8b3d6ff83aa9dba44de7e514d8ec93ddae242c695c22"
    )
    assert protocol.parent.config_sha256 == v29.PARENT_V28_CONFIG_SHA256
    assert v29.v12.sha256_file(protocol.parent_metrics_path) == (
        v29.PARENT_V28_METRICS_SHA256
    )
    assert protocol.payload["validation"]["independent_confirmation"] is False


def test_risk_first_roll_exits_old_and_clips_new_entry_independently() -> None:
    desired, positions, indexed = _roll_state()
    counters = ledger_engine._PortfolioCounters()

    fitted, cancelled, clipped = v29.risk_first_capacity_admission(
        desired,
        positions,
        indexed,
        pd.Timestamp("2014-05-12"),
        v26.CapacityAwareLeveredLedgerConfig(),
        counters,
    )

    assert fitted["BR"][:2] == ("BR:BRM4:2014-06-16", 1)
    assert cancelled == set()
    assert clipped == {"BR"}
    assert counters.participation_clip_count == 1
    assert counters.target_cancel_roll_capacity_count == 0


def test_missing_new_leg_exits_old_and_holds_cash() -> None:
    desired, positions, indexed = _roll_state(new_volume=None)
    counters = ledger_engine._PortfolioCounters()

    fitted, cancelled, clipped = v29.risk_first_capacity_admission(
        desired,
        positions,
        indexed,
        pd.Timestamp("2014-05-12"),
        v26.CapacityAwareLeveredLedgerConfig(),
        counters,
    )

    assert fitted["BR"] == (None, 0, None)
    assert cancelled == set()
    assert clipped == {"BR"}
    assert counters.participation_clip_count == 1
    assert counters.target_cancel_roll_capacity_count == 0


def test_insufficient_old_leg_capacity_retains_position_and_fails_closed() -> None:
    desired, positions, indexed = _roll_state(old_volume=1_000.0)
    counters = ledger_engine._PortfolioCounters()

    fitted, cancelled, clipped = v29.risk_first_capacity_admission(
        desired,
        positions,
        indexed,
        pd.Timestamp("2014-05-12"),
        v26.CapacityAwareLeveredLedgerConfig(),
        counters,
    )

    assert fitted["BR"][:2] == ("BR:BRK4:2014-05-16", 14)
    assert cancelled == {"BR"}
    assert clipped == set()
    assert counters.target_cancel_roll_capacity_count == 1


def test_transactional_patch_is_restored_when_ledger_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ledger_engine._fit_capacity_admission

    def fail_while_patched(*_args: object, **_kwargs: object) -> None:
        assert ledger_engine._fit_capacity_admission is v29.risk_first_capacity_admission
        raise RuntimeError("synthetic ledger failure")

    monkeypatch.setattr(v29.v15, "run_levered_portfolio_ledger", fail_while_patched)

    with pytest.raises(RuntimeError, match="synthetic ledger failure"):
        v29.run_risk_first_portfolio_ledger(
            pd.DataFrame(),
            pd.DataFrame(),
            v26.CapacityAwareLeveredLedgerConfig(),
        )
    assert ledger_engine._fit_capacity_admission is original


def _scenario(cagr: float) -> dict[str, object]:
    return {
        "futures_only": {
            "execution_complete": True,
            "critical_failure_count": 0,
            "unresolved_halt_count": 0,
            "maximum_participation": 0.01,
            "gross_limit_rejection_count": 0,
            "initial_margin_rejection_count": 0,
            "ending_cash": 2_000_000.0,
        },
        "combined": {
            "cagr": cagr,
            "maximum_drawdown": 0.20,
            "sharpe": 1.0,
            "worst_year": -0.05,
            "positive_years": 4,
            "annual_returns": {str(year): 0.1 for year in range(2013, 2018)},
        },
    }


def test_assessment_is_explicitly_post_v28_and_not_independent() -> None:
    scenarios = {name: _scenario(0.25) for name in ("primary", "doubled", "stress")}

    result = v29._assessment(scenarios, {"sealed": True})

    assert result["verdict"] == "PASS_POST_V28_20_RESEARCH_ONLY"
    assert result["post_V28_adaptive_execution_correction"] is True
    assert result["unseen_market_period_external_validation"] is False
    assert result["independent_confirmation"] is False
    assert result["live_trading_allowed"] is False
