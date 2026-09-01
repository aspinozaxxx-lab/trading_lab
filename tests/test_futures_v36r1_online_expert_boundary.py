"""Outcome-free tests for the sealed V36-R1 source-boundary repair."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v36_online_expert_ensemble as parent
from market_lab import futures_v36r1_online_expert_boundary as runner
from market_lab.futures import online_expert_ensemble as core


def test_config_is_sealed_and_economics_match_parent_v36() -> None:
    config = runner.load_config()
    parent_config = parent.load_config()

    assert config["protocol_id"] == "futures_v36r1_online_expert_boundary_v1"
    assert tuple(config["experts"]["ordered"]) == core.EXPERTS
    assert config["hypothesis"] == parent_config["hypothesis"]
    assert config["features"] == parent_config["features"]
    assert config["experts"] == parent_config["experts"]
    assert config["portfolio"] == parent_config["portfolio"]
    assert config["execution"]["scenarios"] == parent_config["execution"]["scenarios"]


def test_bridge_selection_is_exact_and_outcome_independent() -> None:
    config = runner.load_config()
    selected, checks = runner._bridge_source(config)

    assert all(checks.values())
    assert len(selected) == 45
    assert pd.to_datetime(selected["trade_date"]).nunique() == 15
    assert set(selected["canonical_contract_id"]) == set(
        config["inputs"]["boundary_bridge"]["exact_contracts"].values()
    )
    assert config["inputs"]["boundary_bridge"][
        "strategy_positions_or_pnl_used_for_selection"
    ] is False


def test_bridge_observations_and_specs_restore_only_post_december_first() -> None:
    observations, specs, checks = runner._build_bridge_inputs(runner.load_config())

    assert all(checks.values())
    assert len(observations) == len(specs) == 42
    assert pd.to_datetime(observations["trade_date"]).min() == pd.Timestamp("2017-12-04")
    assert pd.to_datetime(observations["trade_date"]).max() == pd.Timestamp("2017-12-21")
    assert specs["sizing_usable"].all()
    assert set(observations["logical_asset"]) == {"SI", "RI", "MIX"}


def test_expiry_flat_is_exact_and_does_not_inspect_positions() -> None:
    columns = [
        "effective_date",
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "target_weight",
        "provenance",
        "risk_multiplier",
        "active_fraction",
        "pre_restoration_target_weight",
    ]
    targets = pd.DataFrame(
        [
            {
                "effective_date": pd.Timestamp("2017-12-01"),
                "decision_date": pd.Timestamp("2017-11-30"),
                "observed_through": pd.Timestamp("2017-11-30"),
                "asset_code": "SI",
                "contract_id": "example",
                "target_weight": 0.25,
                "provenance": "synthetic",
                "risk_multiplier": 1.0,
                "active_fraction": 1.0,
                "pre_restoration_target_weight": 0.25,
            }
        ],
        columns=columns,
    )

    repaired = runner.inject_expiry_flat_targets(targets, runner.load_config())
    flat = repaired.loc[pd.to_datetime(repaired["effective_date"]).eq("2017-12-21")]

    assert tuple(flat["asset_code"]) == core.ASSETS
    assert flat["contract_id"].isna().all()
    assert flat["target_weight"].eq(0.0).all()
    assert flat["decision_date"].eq(pd.Timestamp("2017-12-20")).all()
    assert flat["provenance"].str.contains("position_or_pnl_dependent=false").all()


def test_expiry_flat_rejects_collision() -> None:
    row = pd.DataFrame(
        {
            "effective_date": [pd.Timestamp("2017-12-21")],
            "decision_date": [pd.Timestamp("2017-12-20")],
            "observed_through": [pd.Timestamp("2017-12-20")],
            "asset_code": ["SI"],
            "contract_id": [None],
            "target_weight": [0.0],
            "provenance": ["collision"],
            "risk_multiplier": [0.0],
            "active_fraction": [0.0],
            "pre_restoration_target_weight": [0.0],
        }
    )
    with pytest.raises(ValueError, match="collides"):
        runner.inject_expiry_flat_targets(row, runner.load_config())


def test_combined_market_contains_the_exact_bridge_without_duplicates() -> None:
    _, _, observations, specs = runner._read_inputs(runner.load_config())
    market = v12.build_execution_market(observations, specs)
    bridge = market.loc[
        pd.to_datetime(market["session_date"]).between("2017-12-04", "2017-12-21")
    ]

    assert len(bridge) == 42
    assert bridge["session_date"].nunique() == 14
    assert not market.duplicated(["session_date", "asset_code", "contract_id"]).any()


def test_preflight_verifies_parent_sources_and_boundary_bridge() -> None:
    result = runner.preflight(runner.load_config())

    assert all(result["checks"].values())
    assert result["checks"]["bridge_appended_rows_exact"]
    assert result["checks"]["bridge_specs_lag_one_usable"]
