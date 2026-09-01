"""Synthetic tests for the sealed V18 CBR forward-liquidity experiment."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v18_cbr_liquidity_forecast as v18


def _forecasts() -> pd.DataFrame:
    publications = pd.date_range("2017-01-10", "2025-12-30", periods=458).normalize()
    assert publications.is_unique
    rows = []
    for index, publication in enumerate(publications):
        available = (
            publication.tz_localize("Europe/Moscow")
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        ).tz_convert("UTC")
        rows.append(
            {
                "publication_date": publication,
                "available_at": available,
                "forecast_period_start": publication,
                "forecast_period_end": publication + pd.Timedelta(days=6),
                "government_accounts_change_bln_rub": 100.0 if index % 2 == 0 else -100.0,
                "source_schema": (
                    "archive_2012_2020" if publication.year <= 2020 else "current_2021_plus"
                ),
                "raw_sha256": f"{index:064x}"[-64:],
                "release_keyed_historical_record": True,
            }
        )
    return pd.DataFrame(rows)


def _market() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2016-10-01", "2025-12-31", freq="D")
    panel_rows = []
    active_rows = []
    for asset_index, asset in enumerate(v12.ASSETS):
        returns = 0.001 * np.sin(np.arange(len(dates)) / (5.0 + asset_index))
        closes = (100.0 + asset_index * 10.0) * np.exp(np.cumsum(returns))
        panel_rows.extend(
            {
                "trade_date": current,
                "asset_code": asset,
                "close": close,
            }
            for current, close in zip(dates, closes, strict=True)
        )
        active_rows.extend(
            {
                "decision_date": current,
                "effective_date": following,
                "observed_through": current,
                "asset_code": asset,
                "contract_id": f"{asset}H5",
                "plan_tradable": True,
                "roll": False,
            }
            for current, following in zip(dates[:-1], dates[1:], strict=True)
        )
    return pd.DataFrame(panel_rows), pd.DataFrame(active_rows)


def test_protocol_is_byte_sealed_and_single_signal() -> None:
    protocol = v18.load_protocol()

    assert protocol["signal"]["economic_sign_to_SI"] == 1
    assert protocol["signal"]["trade_threshold"] == "none"
    assert protocol["signal"]["expiry_without_successor"] == (
        "zero_target_at_end_of_printed_period"
    )
    assert protocol["portfolio"]["non_SI_targets"] == "zero"
    assert hashlib.sha256(v18.CONFIG_PATH.read_bytes()).hexdigest() == v18.CONFIG_SHA256


def test_normalize_forecasts_derives_only_the_predeclared_sign() -> None:
    normalized = v18.normalize_forecasts(_forecasts())

    assert len(normalized) == 458
    assert normalized["direction"].iloc[:4].tolist() == [1.0, -1.0, 1.0, -1.0]
    assert normalized["available_at"].max() < v18.PROTECTED_FROM
    tampered = _forecasts()
    tampered.loc[0, "available_at"] = pd.Timestamp("2017-01-10T12:00:00Z")
    with pytest.raises(ValueError, match="availability drifted"):
        v18.normalize_forecasts(tampered)


def test_build_decisions_flattens_expired_forecast_and_only_trades_si() -> None:
    forecasts = _forecasts()
    panel, active = _market()

    result = v18.build_source_decisions(forecasts, panel, active)

    assert result.mapped_release_count >= 457
    assert result.required_expiry_count > 0
    assert result.mapped_expiry_count > 0
    assert result.same_session_collisions == 0
    mapped_expiry = result.decisions.loc[
        result.decisions["event_type"].eq("expiry")
        & result.decisions["decision_status"].eq("mapped")
    ].iloc[0]
    snapshot = result.weights.loc[
        result.weights["decision_date"].eq(mapped_expiry["decision_date"])
    ]
    assert snapshot["target_weight"].eq(0.0).all()
    mapped_release = result.decisions.loc[
        result.decisions["event_type"].eq("release")
        & result.decisions["decision_status"].eq("mapped")
        & result.decisions["target_weight"].ne(0.0)
    ].iloc[0]
    release_snapshot = result.weights.loc[
        result.weights["decision_date"].eq(mapped_release["decision_date"])
    ].set_index("asset")["target_weight"]
    assert release_snapshot["SI"] != 0.0
    assert release_snapshot.drop("SI").eq(0.0).all()


def test_missing_government_forecast_fails_closed() -> None:
    forecasts = _forecasts()
    forecasts.loc[100, "government_accounts_change_bln_rub"] = np.nan

    with pytest.raises(ValueError, match="must be finite"):
        v18.normalize_forecasts(forecasts)
