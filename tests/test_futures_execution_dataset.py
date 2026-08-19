"""Testy fail-closed execution dataset do lyubogo PnL ili returns."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.execution_dataset import (
    EXECUTION_ASSETS,
    audit_active_execution_coverage,
    build_portfolio_market,
    map_decision_weights_to_next_open,
)
from market_lab.futures.spec_proxy import SPEC_PROXY_VERSION

# Pervaya synthetic decision-date do protected holdout.
FIRST_DECISION = pd.Timestamp("2024-01-02")
# Vtoraya synthetic decision-date s roll resheniem.
SECOND_DECISION = pd.Timestamp("2024-01-03")
# Pervyi factual next-open trade date.
FIRST_EFFECTIVE = pd.Timestamp("2024-01-03")
# Vtoroi factual next-open trade date.
SECOND_EFFECTIVE = pd.Timestamp("2024-01-04")


def _contract_row(
    session_date: str,
    asset: str,
    contract_id: str,
    open_price: float,
) -> dict[str, object]:
    """Stroit odnu raw contract stroku bez synthetic specs."""
    return {
        "trade_date": session_date,
        "asset": asset,
        "canonical_contract_id": contract_id,
        "open": open_price,
        "high": open_price + 2.0,
        "low": open_price - 1.0,
        "close": open_price + 1.0,
        "settle": open_price + 0.5,
        "volume": 1_000.0,
    }


def _spec_row(
    session_date: str,
    asset: str,
    contract_id: str,
    point_value: float,
    usable: bool = True,
) -> dict[str, object]:
    """Stroit odnu causal research-only spec-proxy stroku."""
    observed = pd.Timestamp(session_date) - pd.Timedelta(days=1) if usable else pd.NaT
    selected_point = point_value if usable else np.nan
    return {
        "session_date": session_date,
        "asset_symbol": asset,
        "contract_id": contract_id,
        "sizing_point_value": selected_point,
        "sizing_observed_session_date": observed,
        "sizing_lag_sessions": 1,
        "sizing_usable": usable,
        "realized_accounting_point_value": selected_point,
        "realized_available_after_session": usable,
        "tick_size": 1.0 if asset == "SI" else 0.01,
        "conservative_fee_per_side": 4.0 if asset == "SI" else 10.0,
        "modeled_initial_margin": selected_point * 100.0 if usable else np.nan,
        "spec_proxy_version": SPEC_PROXY_VERSION,
        "approximate": True,
        "research_only": True,
        "historical_exchange_exact": False,
        "broker_exact": False,
    }


def _market_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stroit raw/spec nabor s odnim fakticheskim rolom SI."""
    observations = pd.DataFrame(
        [
            _contract_row("2024-01-03", "SI", "Si:SiH4:2024-03-21", 100.0),
            _contract_row("2024-01-03", "BR", "BR:BRG4:2024-02-01", 75.0),
            _contract_row("2024-01-04", "SI", "Si:SiM4:2024-06-20", 105.0),
            _contract_row("2024-01-04", "BR", "BR:BRG4:2024-02-01", 76.0),
        ]
    )
    specs = pd.DataFrame(
        [
            _spec_row("2024-01-03", "SI", "Si:SiH4:2024-03-21", 2.0),
            _spec_row("2024-01-03", "BR", "BR:BRG4:2024-02-01", 10.0),
            _spec_row("2024-01-04", "SI", "Si:SiM4:2024-06-20", 2.1),
            _spec_row("2024-01-04", "BR", "BR:BRG4:2024-02-01", 10.1),
        ]
    )
    return observations, specs


def _weights() -> pd.DataFrame:
    """Stroit dva polnyh portfolio weight snapshots."""
    values = {
        FIRST_DECISION: {"SI": 0.4, "RI": 0.0, "BR": -0.2, "MIX": 0.0},
        SECOND_DECISION: {"SI": 0.3, "RI": 0.0, "BR": -0.1, "MIX": 0.0},
    }
    return pd.DataFrame(
        [
            {
                "decision_date": decision_date,
                "asset": asset,
                "target_weight": weights[asset],
                "provenance": f"score-{decision_date.date()}-{asset}",
            }
            for decision_date, weights in values.items()
            for asset in EXECUTION_ASSETS
        ]
    )


def _timing() -> pd.DataFrame:
    """Stroit exact D -> next factual trade-date mapping."""
    return pd.DataFrame(
        {
            "trade_date": [FIRST_DECISION, SECOND_DECISION],
            "effective_date": [FIRST_EFFECTIVE, SECOND_EFFECTIVE],
            "timing_regime": [
                "legacy_evening_belongs_to_next_trade_date",
                "legacy_evening_belongs_to_next_trade_date",
            ],
        }
    )


def _active_map() -> pd.DataFrame:
    """Stroit polnyi active snapshot s SI roll i flat MIX."""
    contracts = {
        FIRST_DECISION: {
            "SI": "Si:SiH4:2024-03-21",
            "RI": "RTS:RIH4:2024-03-21",
            "BR": "BR:BRG4:2024-02-01",
            "MIX": None,
        },
        SECOND_DECISION: {
            "SI": "Si:SiM4:2024-06-20",
            "RI": "RTS:RIH4:2024-03-21",
            "BR": "BR:BRG4:2024-02-01",
            "MIX": None,
        },
    }
    effective = {FIRST_DECISION: FIRST_EFFECTIVE, SECOND_DECISION: SECOND_EFFECTIVE}
    return pd.DataFrame(
        [
            {
                "decision_date": decision_date,
                "effective_date": effective[decision_date],
                "observed_through": decision_date,
                "asset": asset,
                "position_contract_id": snapshot[asset],
                "tradable": snapshot[asset] is not None,
            }
            for decision_date, snapshot in contracts.items()
            for asset in EXECUTION_ASSETS
        ]
    )


def test_builds_exact_market_and_preserves_raw_values_without_imputation() -> None:
    """Proveryaet one-to-one raw/spec join i ledger-compatible imena."""
    observations, specs = _market_inputs()
    observations.loc[0, "close"] = np.nan
    market = build_portfolio_market(observations, specs)

    assert len(market) == 4
    assert market.duplicated(["session_date", "asset_code", "contract_id"]).sum() == 0
    first = market.loc[
        market["contract_id"].eq("Si:SiH4:2024-03-21")
    ].iloc[0]
    assert pd.isna(first["close"])
    assert first["open"] == 100.0
    assert first["sizing_point_value"] == 2.0
    assert first["accounting_point_value"] == 2.0
    assert first["fee_per_contract"] == 4.0
    assert first["initial_margin"] == 200.0
    assert first["spec_proxy_version"] == SPEC_PROXY_VERSION
    assert bool(first["research_only"])
    assert not bool(first["historical_exchange_exact"])
    provenance = json.loads(first["provenance"])
    assert provenance["imputation"] is False
    assert provenance["contains_pnl_or_returns"] is False


def test_maps_weights_to_exact_next_open_roll_and_removes_zero_contracts() -> None:
    """Proveryaet SI roll, full snapshot i contract NA dlya zero target."""
    mapped = map_decision_weights_to_next_open(_weights(), _timing(), _active_map())

    assert len(mapped) == 8
    assert mapped.groupby("effective_date").size().eq(4).all()
    first_si = mapped.loc[
        mapped["effective_date"].eq(FIRST_EFFECTIVE) & mapped["asset_code"].eq("SI")
    ].iloc[0]
    second_si = mapped.loc[
        mapped["effective_date"].eq(SECOND_EFFECTIVE) & mapped["asset_code"].eq("SI")
    ].iloc[0]
    assert first_si["contract_id"] == "Si:SiH4:2024-03-21"
    assert second_si["contract_id"] == "Si:SiM4:2024-06-20"
    zero = mapped["target_weight"].eq(0.0)
    assert mapped.loc[zero, "contract_id"].isna().all()
    assert (mapped["observed_through"] <= mapped["decision_date"]).all()
    assert (mapped["decision_date"] < mapped["effective_date"]).all()
    provenance = json.loads(second_si["provenance"])
    assert provenance["mapping"] == "decision_close_to_next_factual_trade_date_open"
    assert provenance["contains_pnl_or_returns"] is False


def test_audit_validates_every_nonflat_roll_and_rebalance_row() -> None:
    """Proveryaet exact market coverage vseh chetyreh non-flat target rows."""
    observations, specs = _market_inputs()
    market = build_portfolio_market(observations, specs)
    mapped = map_decision_weights_to_next_open(_weights(), _timing(), _active_map())
    audit = audit_active_execution_coverage(market, mapped)

    assert audit.active_rows == 4
    assert audit.covered_rows == 4
    assert audit.exact_join
    assert audit.sizing_available_rows == 4
    assert audit.accounting_available_rows == 4
    assert audit.tick_available_rows == 4
    assert audit.fee_available_rows == 4
    assert audit.initial_margin_available_rows == 4
    assert audit.coverage[list(audit.coverage.columns[-5:])].all().all()


def test_build_market_rejects_mismatch_duplicate_flags_and_future() -> None:
    """Fail-closed otklonyaet key mismatch, duplicate, oslablenie flagov i 2026."""
    observations, specs = _market_inputs()
    with pytest.raises(ValueError, match="key mismatch"):
        build_portfolio_market(observations, specs.iloc[:-1])
    duplicated = pd.concat([specs, specs.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        build_portfolio_market(observations, duplicated)
    weakened = specs.copy()
    weakened.loc[0, "research_only"] = False
    with pytest.raises(ValueError, match="research_only"):
        build_portfolio_market(observations, weakened)
    future = observations.copy()
    future.loc[0, "trade_date"] = "2026-01-05"
    with pytest.raises(ValueError, match="holdout"):
        build_portfolio_market(future, specs)


def test_mapping_rejects_timing_causality_contract_and_snapshot_mismatches() -> None:
    """Fail-closed otklonyaet mismatch timing, leakage, missing contract i nepolnyi snapshot."""
    bad_effective = _active_map()
    bad_effective.loc[0, "effective_date"] = SECOND_EFFECTIVE
    with pytest.raises(ValueError, match="effective_date ne sootvetstvuet"):
        map_decision_weights_to_next_open(_weights(), _timing(), bad_effective)

    leaked = _active_map()
    leaked.loc[0, "observed_through"] = SECOND_EFFECTIVE
    with pytest.raises(ValueError, match="observed_through"):
        map_decision_weights_to_next_open(_weights(), _timing(), leaked)

    no_contract = _active_map()
    mask = no_contract["decision_date"].eq(FIRST_DECISION) & no_contract["asset"].eq("SI")
    no_contract.loc[mask, "position_contract_id"] = None
    no_contract.loc[mask, "tradable"] = False
    with pytest.raises(ValueError, match="ne imeet active contract"):
        map_decision_weights_to_next_open(_weights(), _timing(), no_contract)

    incomplete = _weights().iloc[:-1]
    with pytest.raises(ValueError, match="Nepolnyi weight snapshot"):
        map_decision_weights_to_next_open(incomplete, _timing(), _active_map())

    future_timing = _timing()
    future_timing.loc[1, "effective_date"] = "2026-01-05"
    with pytest.raises(ValueError, match="holdout"):
        map_decision_weights_to_next_open(_weights(), future_timing, _active_map())


def test_audit_rejects_missing_or_incomplete_active_market_rows() -> None:
    """Fail-closed otklonyaet missing exact join, NaN spec i future execution row."""
    observations, specs = _market_inputs()
    market = build_portfolio_market(observations, specs)
    mapped = map_decision_weights_to_next_open(_weights(), _timing(), _active_map())

    missing = market.loc[~market["contract_id"].eq("Si:SiM4:2024-06-20")]
    with pytest.raises(ValueError, match="exact market row"):
        audit_active_execution_coverage(missing, mapped)

    incomplete = market.copy()
    mask = incomplete["contract_id"].eq("Si:SiH4:2024-03-21")
    incomplete.loc[mask, "initial_margin"] = np.nan
    with pytest.raises(ValueError, match="specs incomplete"):
        audit_active_execution_coverage(incomplete, mapped)

    unavailable = market.copy()
    unavailable.loc[mask, "sizing_usable"] = False
    with pytest.raises(ValueError, match="specs incomplete"):
        audit_active_execution_coverage(unavailable, mapped)

    free_execution = market.copy()
    free_execution.loc[mask, "fee_per_contract"] = 0.0
    with pytest.raises(ValueError, match="specs incomplete"):
        audit_active_execution_coverage(free_execution, mapped)

    future = mapped.copy()
    future.loc[0, "effective_date"] = "2026-01-05"
    with pytest.raises(ValueError, match="holdout"):
        audit_active_execution_coverage(market, future)
