"""Tests for the sealed V22 CBR Business Climate Index experiment."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v22_cbr_business_climate_regime as v22


def _market() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    panel_rows: list[dict[str, object]] = []
    active_rows: list[dict[str, object]] = []
    for asset_index, asset in enumerate(v12.ASSETS):
        returns = 0.001 * np.sin(np.arange(len(dates)) / (5.0 + asset_index))
        closes = (100.0 + asset_index * 10.0) * np.exp(np.cumsum(returns))
        panel_rows.extend(
            {"trade_date": current, "asset_code": asset, "close": close}
            for current, close in zip(dates, closes, strict=True)
        )
        active_rows.extend(
            {
                "decision_date": current,
                "effective_date": following,
                "observed_through": current,
                "asset_code": asset,
                "contract_id": f"{asset}H1",
                "plan_tradable": True,
                "roll": False,
            }
            for current, following in zip(dates[:-1], dates[1:], strict=True)
        )
    return pd.DataFrame(panel_rows), pd.DataFrame(active_rows)


def _signal(
    release_month: str,
    available_at: str,
    *,
    direction: float,
) -> dict[str, object]:
    release = pd.Timestamp(release_month)
    return {
        "release_month": release,
        "observation_month": release,
        "available_at": pd.Timestamp(available_at),
        "bci_value": 5.0 + direction,
        "previous_bci_value": 5.0,
        "bci_delta": direction,
        "direction": direction,
        "SI_signal": -direction,
        "RI_signal": direction,
        "BR_signal": 0.0,
        "MIX_signal": direction,
        "signal_status": "scored",
    }


def test_protocol_is_byte_sealed_and_has_fixed_direct_regime() -> None:
    protocol = v22.load_protocol()

    assert protocol["information_set"]["selected_value"] == (
        "printed_one_decimal_composite_BCI_endpoint_only"
    )
    assert protocol["information_set"]["chart_exact_decimals"] == (
        "audit_only_forbidden_in_signal"
    )
    assert protocol["signal"]["threshold"] == "none"
    assert protocol["signal"]["expiry_calendar_days"] == 45
    assert protocol["portfolio"]["active_signal_assets"] == ["SI", "RI", "MIX"]
    assert protocol["portfolio"]["equal_absolute_risk_budget_each_active_asset"] == (
        1.0 / 3.0
    )
    assert hashlib.sha256(v22.CONFIG_PATH.read_bytes()).hexdigest() == v22.CONFIG_SHA256


def test_real_source_preflight_and_sealed_signal_counts() -> None:
    protocol = v22.load_protocol()
    verified = v22.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["cbr_bci_releases"],
        columns=protocol["inputs"]["cbr_bci_releases"]["allowed_columns"],
    )

    releases = v22.normalize_releases(raw)
    signals = v22.build_source_signals(releases)
    scored = signals.loc[signals["signal_status"].eq("scored")]

    assert all(verified.checks.values())
    assert len(releases) == 44
    assert len(scored) == 43
    assert scored["bci_delta"].gt(0.0).sum() == 21
    assert scored["bci_delta"].lt(0.0).sum() == 18
    assert scored["bci_delta"].eq(0.0).sum() == 4
    assert scored["SI_signal"].ne(0.0).sum() == 39
    assert scored["RI_signal"].ne(0.0).sum() == 39
    assert scored["BR_signal"].eq(0.0).all()
    assert scored["MIX_signal"].ne(0.0).sum() == 39
    assert signals["available_at"].lt(v22.PROTECTED_FROM).all()


def test_chart_exact_decimals_do_not_change_the_signal() -> None:
    protocol = v22.load_protocol()
    verified = v22.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["cbr_bci_releases"],
        columns=protocol["inputs"]["cbr_bci_releases"]["allowed_columns"],
    )
    releases = v22.normalize_releases(raw)
    baseline = v22.build_source_signals(releases)
    changed = releases.copy()
    changed["bci_chart_exact"] = changed["bci_value"] + 0.04

    rebuilt = v22.build_source_signals(changed)

    pd.testing.assert_series_equal(rebuilt["bci_delta"], baseline["bci_delta"])
    for asset in v12.ASSETS:
        pd.testing.assert_series_equal(rebuilt[f"{asset}_signal"], baseline[f"{asset}_signal"])


def test_decisions_apply_expiry_and_keep_latest_same_time_release() -> None:
    signals = pd.DataFrame(
        [
            _signal("2021-01-01", "2021-01-31T20:59:59Z", direction=1.0),
            _signal("2021-03-01", "2021-04-30T20:59:59Z", direction=-1.0),
            _signal("2021-04-01", "2021-04-30T20:59:59Z", direction=1.0),
        ]
    )
    panel, active = _market()

    result = v22.build_source_decisions(signals, panel, active)

    assert result.expiry_state_count == 2
    assert result.same_session_collisions == 1
    first = result.weights.loc[
        result.weights["decision_date"].eq(pd.Timestamp("2021-01-31"))
    ].set_index("asset")["target_weight"]
    assert first["SI"] < 0.0
    assert first["RI"] > 0.0
    assert first["MIX"] > 0.0
    assert first["BR"] == 0.0
    expiry = result.weights.loc[
        result.weights["decision_date"].eq(pd.Timestamp("2021-03-17")),
        "target_weight",
    ]
    assert expiry.eq(0.0).all()
    latest = result.decisions.loc[
        result.decisions["source_release_month"].eq(pd.Timestamp("2021-04-01"))
        & result.decisions["state_kind"].eq("signal")
    ].iloc[0]
    superseded = result.decisions.loc[
        result.decisions["source_release_month"].eq(pd.Timestamp("2021-03-01"))
        & result.decisions["state_kind"].eq("signal")
    ].iloc[0]
    assert latest["decision_status"] == "mapped"
    assert superseded["decision_status"] == "superseded_same_decision_session"
    assert result.weights["target_weight"].abs().le(v22.RISK_BUDGET + 1e-12).all()
    assert result.weights.groupby("decision_date")["asset"].nunique().eq(4).all()
