"""Tests for the sealed V21 CBR macro-revision experiment."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v21_cbr_macro_revision_breadth as v21


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
    survey_month: str,
    available_at: str,
    *,
    si: float,
    ri: float,
    br: float,
) -> dict[str, object]:
    survey = pd.Timestamp(survey_month)
    return {
        "survey_month": survey,
        "available_at": pd.Timestamp(available_at),
        "forecast_year": survey.year + 1,
        "usd_rub_revision": si,
        "gdp_revision": ri,
        "oil_indicator": "brent_price_usd_bbl" if br else None,
        "oil_revision": br if br else np.nan,
        "SI_signal": float(np.sign(si)),
        "RI_signal": float(np.sign(ri)),
        "BR_signal": float(np.sign(br)),
        "MIX_signal": float(np.sign(ri)),
        "oil_component_status": (
            "same_series_revision_available"
            if br
            else "component_unavailable_target_zero"
        ),
        "signal_status": "scored",
    }


def test_protocol_is_byte_sealed_and_has_fixed_independent_channels() -> None:
    protocol = v21.load_protocol()

    assert protocol["information_set"]["oil_series_priority"] == [
        "oil_tax_price_usd_bbl",
        "brent_price_usd_bbl",
        "urals_price_usd_bbl",
    ]
    assert protocol["information_set"]["oil_cross_series_bridge"] == "forbidden"
    assert protocol["signal"]["threshold"] == "none"
    assert protocol["signal"]["expiry_calendar_days"] == 70
    assert protocol["portfolio"]["equal_absolute_risk_budget_each_asset"] == 0.25
    assert protocol["portfolio"]["unused_component_budget_reallocated"] is False
    assert hashlib.sha256(v21.CONFIG_PATH.read_bytes()).hexdigest() == v21.CONFIG_SHA256


def test_real_source_preflight_and_sealed_revision_counts() -> None:
    protocol = v21.load_protocol()
    verified = v21.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["cbr_macro_forecasts"],
        columns=protocol["inputs"]["cbr_macro_forecasts"]["allowed_columns"],
    )

    forecasts = v21.normalize_forecasts(raw)
    signals = v21.build_source_signals(forecasts)
    scored = signals.loc[signals["signal_status"].eq("scored")]

    assert all(verified.checks.values())
    assert len(forecasts) == 11787
    assert len(signals) == 36
    assert len(scored) == 35
    assert scored["SI_signal"].ne(0.0).sum() == 34
    assert scored["RI_signal"].ne(0.0).sum() == 28
    assert scored["BR_signal"].ne(0.0).sum() == 12
    assert scored["MIX_signal"].ne(0.0).sum() == 28
    assert signals["available_at"].lt(v21.PROTECTED_FROM).all()


def test_revisions_never_cross_target_year_or_oil_series() -> None:
    common = {
        "statistic": "median",
        "available_at": pd.Timestamp("2023-03-31T20:59:59Z"),
    }
    rows = [
        {
            **common,
            "survey_month": pd.Timestamp("2022-12-01"),
            "indicator": v21.USD_INDICATOR,
            "forecast_year": 2023,
            "value": 80.0,
        },
        {
            **common,
            "survey_month": pd.Timestamp("2022-12-01"),
            "indicator": v21.USD_INDICATOR,
            "forecast_year": 2024,
            "value": 90.0,
        },
        {
            **common,
            "survey_month": pd.Timestamp("2023-02-01"),
            "indicator": v21.USD_INDICATOR,
            "forecast_year": 2024,
            "value": 95.0,
        },
        {
            **common,
            "survey_month": pd.Timestamp("2022-12-01"),
            "indicator": "urals_price_usd_bbl",
            "forecast_year": 2024,
            "value": 60.0,
        },
        {
            **common,
            "survey_month": pd.Timestamp("2023-02-01"),
            "indicator": "urals_price_usd_bbl",
            "forecast_year": 2024,
            "value": 65.0,
        },
        {
            **common,
            "survey_month": pd.Timestamp("2023-02-01"),
            "indicator": "brent_price_usd_bbl",
            "forecast_year": 2024,
            "value": 75.0,
        },
    ]

    revisions = v21._next_year_revisions(pd.DataFrame(rows))
    usd_2024 = revisions.loc[
        revisions["indicator"].eq(v21.USD_INDICATOR)
        & revisions["survey_month"].eq(pd.Timestamp("2023-02-01"))
    ].iloc[0]
    urals = revisions.loc[
        revisions["indicator"].eq("urals_price_usd_bbl")
        & revisions["survey_month"].eq(pd.Timestamp("2023-02-01"))
    ].iloc[0]
    brent = revisions.loc[
        revisions["indicator"].eq("brent_price_usd_bbl")
        & revisions["survey_month"].eq(pd.Timestamp("2023-02-01"))
    ].iloc[0]

    assert usd_2024["previous_value"] == 90.0
    assert usd_2024["revision"] == 5.0
    assert urals["revision"] == 5.0
    assert pd.isna(brent["previous_value"])
    assert pd.isna(brent["revision"])


def test_decisions_keep_missing_budget_unused_and_apply_70_day_expiry() -> None:
    signals = pd.DataFrame(
        [
            _signal(
                "2021-01-01",
                "2021-02-28T20:59:59Z",
                si=1.0,
                ri=-1.0,
                br=0.0,
            ),
            _signal(
                "2021-05-01",
                "2021-06-30T20:59:59Z",
                si=-1.0,
                ri=1.0,
                br=1.0,
            ),
        ]
    )
    panel, active = _market()

    result = v21.build_source_decisions(signals, panel, active)

    assert result.expiry_state_count == 2
    assert result.same_session_collisions == 0
    first = result.weights.loc[
        result.weights["decision_date"].eq(pd.Timestamp("2021-02-28"))
    ].set_index("asset")["target_weight"]
    assert first["SI"] > 0.0
    assert first["RI"] < 0.0
    assert first["MIX"] < 0.0
    assert first["BR"] == 0.0
    assert float(first.abs().sum()) <= 0.75 + 1e-12
    first_expiry = result.weights.loc[
        result.weights["decision_date"].eq(pd.Timestamp("2021-05-09")),
        "target_weight",
    ]
    assert first_expiry.eq(0.0).all()
    assert result.weights["target_weight"].abs().le(0.25 + 1e-12).all()
    assert result.weights.groupby("decision_date")["asset"].nunique().eq(4).all()
