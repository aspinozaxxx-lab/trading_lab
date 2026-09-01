"""Tests for the sealed V23 CBR household confirmation experiment."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v23_cbr_household_confirmation_regime as v23


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
    regime: str,
) -> dict[str, object]:
    release = pd.Timestamp(release_month)
    return {
        "release_month": release,
        "available_at": pd.Timestamp(available_at),
        "expected_inflation_exact": 10.0 - direction,
        "previous_expected_inflation_exact": 10.0,
        "expected_inflation_delta": -direction,
        "consumer_sentiment_index_exact": 100.0 + direction,
        "previous_consumer_sentiment_index_exact": 100.0,
        "consumer_sentiment_delta": direction,
        "regime": regime,
        "regime_direction": direction,
        "SI_signal": -direction,
        "RI_signal": direction,
        "BR_signal": 0.0,
        "MIX_signal": direction,
        "signal_status": "scored",
    }


def test_protocol_is_byte_sealed_and_has_fixed_confirmation_regime() -> None:
    protocol = v23.load_protocol()

    assert protocol["information_set"]["selected_values"] == [
        "exact_release_specific_XLSX_expected_inflation_12m_median",
        "exact_release_specific_XLSX_consumer_sentiment_index",
    ]
    assert protocol["information_set"]["observed_inflation"] == (
        "archived_for_audit_forbidden_in_v23_signal"
    )
    assert protocol["signal"]["mixed_or_zero_pair"] == "cash"
    assert protocol["signal"]["threshold"] == "none"
    assert protocol["signal"]["expiry_calendar_days"] == 45
    assert protocol["portfolio"]["active_signal_assets"] == ["SI", "RI", "MIX"]
    assert protocol["portfolio"]["equal_absolute_risk_budget_each_active_asset"] == (
        1.0 / 3.0
    )
    assert hashlib.sha256(v23.CONFIG_PATH.read_bytes()).hexdigest() == v23.CONFIG_SHA256


def test_real_source_preflight_and_sealed_confirmation_counts() -> None:
    protocol = v23.load_protocol()
    verified = v23.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["cbr_household_releases"],
        columns=protocol["inputs"]["cbr_household_releases"]["allowed_columns"],
    )

    releases = v23.normalize_releases(raw)
    signals = v23.build_source_signals(releases)
    scored = signals.loc[signals["signal_status"].eq("scored")]

    assert all(verified.checks.values())
    assert len(releases) == 48
    assert len(scored) == 47
    assert scored["regime"].value_counts().to_dict() == {
        "risk_off": 17,
        "risk_on": 16,
        "mixed_or_zero": 14,
    }
    assert scored["SI_signal"].ne(0.0).sum() == 33
    assert scored["RI_signal"].ne(0.0).sum() == 33
    assert scored["BR_signal"].eq(0.0).all()
    assert scored["MIX_signal"].ne(0.0).sum() == 33
    assert signals["available_at"].lt(v23.PROTECTED_FROM).all()


def test_page_chart_audit_decimals_do_not_change_the_signal() -> None:
    protocol = v23.load_protocol()
    verified = v23.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["cbr_household_releases"],
        columns=protocol["inputs"]["cbr_household_releases"]["allowed_columns"],
    )
    releases = v23.normalize_releases(raw)
    baseline = v23.build_source_signals(releases)
    changed = releases.copy()
    changed["expected_inflation_chart_exact"] = changed["expected_inflation_exact"]
    changed["observed_inflation_chart_exact"] = changed["observed_inflation_exact"]

    rebuilt = v23.build_source_signals(changed)

    pd.testing.assert_series_equal(
        rebuilt["expected_inflation_delta"], baseline["expected_inflation_delta"]
    )
    pd.testing.assert_series_equal(
        rebuilt["consumer_sentiment_delta"], baseline["consumer_sentiment_delta"]
    )
    for asset in v12.ASSETS:
        pd.testing.assert_series_equal(rebuilt[f"{asset}_signal"], baseline[f"{asset}_signal"])


def test_decisions_apply_expiry_keep_latest_and_rewrite_provenance() -> None:
    signals = pd.DataFrame(
        [
            _signal(
                "2021-01-01",
                "2021-01-31T20:59:59Z",
                direction=1.0,
                regime="risk_on",
            ),
            _signal(
                "2021-03-01",
                "2021-04-30T20:59:59Z",
                direction=-1.0,
                regime="risk_off",
            ),
            _signal(
                "2021-04-01",
                "2021-04-30T20:59:59Z",
                direction=1.0,
                regime="risk_on",
            ),
        ]
    )
    panel, active = _market()

    result = v23.build_source_decisions(signals, panel, active)

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
    provenance = json.loads(result.weights.iloc[0]["provenance"])
    assert provenance["version"] == "futures_v23_cbr_household_confirmation_regime_v1"
    assert "business_climate" not in result.weights.iloc[0]["provenance"]
    assert result.weights["target_weight"].abs().le(v23.RISK_BUDGET + 1e-12).all()
    assert result.weights.groupby("decision_date")["asset"].nunique().eq(4).all()
