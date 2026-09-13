"""Synthetic checks for the isolated, non-economic V71 assembly correction."""

import json

import pandas as pd
import pytest

from market_lab import futures_v71_scope_repair as repair


def frames():
    observations = pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2021-01-04"]),
            "asset_code": ["SI"],
            "contract_id": ["SI-SYNTH"],
        }
    )
    specs = pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2021-01-04", "2021-01-04", "2020-12-30"]),
            "asset_symbol": ["SI", "BR", "SI"],
            "contract_id": ["SI-SYNTH", "BR-SYNTH", "SI-SYNTH"],
            "value": [11.0, 22.0, 33.0],
        }
    )
    return observations, specs


def test_only_the_frozen_asset_and_period_filter_changes():
    obs, spec = frames()
    selected = repair.select_specs(obs, spec)
    pd.testing.assert_frame_equal(selected, spec.iloc[:1])
    assert len(spec) == 3 and len(obs) == 1


def test_unmatched_same_scope_contract_not_silently_dropped():
    obs, spec = frames()
    extra = spec.iloc[:1].copy()
    extra["contract_id"] = "SI-UNMATCHED"
    selected = repair.select_specs(obs, pd.concat([spec, extra], ignore_index=True))
    assert len(selected) == 2
    with pytest.raises(ValueError, match="key mismatch"):
        repair.assembly._exact_key_match(
            obs, selected.rename(columns={"asset_symbol": "asset_code"}), "synthetic"
        )


@pytest.mark.parametrize("fault", ["asset", "date"])
def test_scope_expansion_fails(fault):
    obs, spec = frames()
    if fault == "asset":
        obs["asset_code"] = "BR"
    else:
        obs["session_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):
        repair.select_specs(obs, spec)


def test_context_restores_shared_functions_even_after_failure():
    builder, seal = repair.base.build_portfolio_market, repair.v1.SEAL
    with pytest.raises(RuntimeError), repair.repaired_runtime():
        assert repair.base.build_portfolio_market is repair.aligned_market
        assert repair.v1.SEAL == repair.SEAL
        raise RuntimeError("synthetic failure")
    assert repair.base.build_portfolio_market is builder and seal == repair.v1.SEAL


def test_original_strict_builder_is_used(monkeypatch):
    obs, spec = frames()
    seen = []

    def builder(left, right):
        pd.testing.assert_frame_equal(left, obs)
        pd.testing.assert_frame_equal(right, spec.iloc[:1])
        seen.append(True)
        return "synthetic"

    monkeypatch.setattr(repair.assembly, "build_portfolio_market", builder)
    assert repair.aligned_market(obs, spec) == "synthetic" and seen == [True]


def test_v1_economics_remain_the_only_parent_definition():
    cfg = json.loads(repair.CONFIG.read_text(encoding="utf-8-sig"))
    assert (
        cfg["parent_v1_seal_sha256"]
        == "ed9b8bc813579e2af40f0039b1f6044428129c73b3a0c796fdc4ca780b6f2e4a"
    )
    assert not cfg["failed_parent"]["simulation_started"]
    assert set(cfg["failed_parent"]["files"]) == {
        "inputs.json",
        "liquidity_surprise_states.parquet",
    }
    assert not any(key in cfg for key in ("signal", "execution", "screen_gates"))
