"""Tests for sealed V26 capital efficiency and capacity-aware execution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26


def test_real_protocol_and_target_free_sources_are_exact() -> None:
    protocol = v26.load_protocol()
    verified = v26.verify_inputs(protocol)
    stlfsi = v26.v25.verify_stlfsi_bundle(protocol, verified)
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    ruonia = v26.v15.verify_ruonia(ruonia_frame)

    assert all(verified.checks.values())
    assert all(stlfsi.checks.values())
    assert all(ruonia.checks.values())
    assert stlfsi.raw_records == 1
    assert len(stlfsi.frame) == 417
    assert len(ruonia.frame) == v26.v15.RUONIA_ROWS


def _governed_weights() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_date": pd.Timestamp("2021-01-08"),
                "asset": asset,
                "target_weight": value,
                "v12_target_weight": value,
                "risk_scale": 1.0,
                "governor_state": "pass_normal_or_below",
                "provenance": "synthetic_v25",
            }
            for asset, value in zip(v26.v12.ASSETS, (0.25, -0.25, 0.10, -0.10), strict=True)
        ]
        + [
            {
                "decision_date": pd.Timestamp("2021-01-15"),
                "asset": asset,
                "target_weight": 0.0,
                "v12_target_weight": value,
                "risk_scale": 0.0,
                "governor_state": "cash_above_average_stress",
                "provenance": "synthetic_v25_cash",
            }
            for asset, value in zip(v26.v12.ASSETS, (0.25, -0.25, 0.10, -0.10), strict=True)
        ]
    )


def test_leverage_is_exactly_after_governor_and_preserves_cash() -> None:
    result = v26.build_levered_governed_weights(_governed_weights())
    first = result.loc[result["decision_date"].eq(pd.Timestamp("2021-01-08"))]
    cash = result.loc[result["decision_date"].eq(pd.Timestamp("2021-01-15"))]

    assert first.set_index("asset")["target_weight"].reindex(v26.v12.ASSETS).tolist() == (
        pytest.approx([0.50, -0.50, 0.20, -0.20])
    )
    assert first["target_weight"].abs().sum() == pytest.approx(1.40)
    assert cash["target_weight"].eq(0.0).all()
    assert cash["v12_target_weight"].abs().sum() == pytest.approx(0.70)
    assert result["provenance"].str.endswith("sealed_two_times_after_v25_governor").all()


def test_capacity_aware_settings_are_fail_closed() -> None:
    settings = v26.CapacityAwareLeveredLedgerConfig()

    assert settings.maximum_gross_notional_multiple == pytest.approx(2.0)
    assert settings.initial_margin_buffer_multiplier == pytest.approx(2.0)
    assert settings.unexecutable_target_policy == "cancel_and_clip"
    assert settings.execution_atomicity == "asset"
    with pytest.raises(ValueError, match="settings drift"):
        v26.CapacityAwareLeveredLedgerConfig(maximum_participation=0.02)


def _scenario(*, cagr: float = 0.21, mdd: float = 0.29) -> dict[str, object]:
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
            "metrics_valid": True,
            "cagr": cagr,
            "maximum_drawdown": mdd,
            "sharpe": 0.90,
            "worst_year": -0.10,
            "positive_years": 4,
            "annual_returns": {str(year): 0.01 for year in range(2021, 2026)},
        },
    }


def test_promotion_requires_twenty_percent_in_every_cost_scenario() -> None:
    checks = {
        "weekly_governor_all_state_counts_exact": True,
        "weekly_governor_oos_state_counts_exact": True,
        "another_check": True,
    }
    passing = {name: _scenario() for name in ("primary", "doubled", "stress")}
    failing = {**passing, "stress": _scenario(cagr=0.1999)}

    assert v26._promotion(passing, checks)["passed"] is True
    verdict = v26._promotion(failing, checks)
    assert verdict["passed"] is False
    assert verdict["conditions"]["all_scenarios_combined_cagr_at_least_0_20"] is False


def test_protocol_has_one_fixed_variant_and_external_inputs() -> None:
    protocol = v26.load_protocol()

    assert protocol["validation"]["number_of_oos_variants"] == 1
    assert protocol["validation"]["protected_2026_market_read"] == "forbidden"
    assert protocol["capital_efficiency"]["target_weight_multiplier_after_governor"] == 2.0
    assert protocol["collateral_income"]["applied_rate_fraction"] == 0.50
    assert protocol["execution"]["unexecutable_target_policy"] == "cancel_and_clip"
    for declaration in protocol["inputs"].values():
        path = Path(str(declaration["path"]))
        assert not path.is_absolute()
        assert path.parts[0] == "data"
        assert ".." not in path.parts


def test_sidecar_names_the_sealed_protocol() -> None:
    digest, name = v26.CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()

    assert digest == v26.CONFIG_SHA256
    assert name == v26.CONFIG_PATH.name
