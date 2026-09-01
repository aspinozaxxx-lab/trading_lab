"""Synthetic tests for the sealed V19 CBR Minfin-FX persistence experiment."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v19_cbr_minfin_fx_persistence as v19


def _factors() -> pd.DataFrame:
    observations = pd.date_range("2021-01-11", "2025-12-30", periods=1238).normalize()
    assert observations.is_unique
    rows = []
    for index, observation in enumerate(observations):
        publication = observation + pd.Timedelta(days=1)
        available = (
            publication.tz_localize("Europe/Moscow")
            + pd.Timedelta(hours=10, minutes=31)
        ).tz_convert("UTC")
        value = (100.0, -100.0, 0.0)[index % 3]
        rows.append(
            {
                "observation_date": observation,
                "publication_date": publication,
                "available_at": available,
                "minfin_fx_operations_bln_rub": value,
                "source_url": "https://www.cbr.ru/statistics/flikvid/?x",
                "raw_sha256": v19.CBR_RAW_HTML_SHA256,
                "current_vintage_historical_record": True,
                "original_publication_bytes_available": False,
                "historical_values_may_be_revised": True,
            }
        )
    frame = pd.DataFrame(rows)
    frame.loc[:, "minfin_fx_operations_bln_rub"] = np.concatenate(
        [np.ones(249), -np.ones(690), np.zeros(299)]
    )
    return frame


def _market() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    panel_rows = []
    active_rows = []
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
                "contract_id": f"{asset}H5",
                "plan_tradable": True,
                "roll": False,
            }
            for current, following in zip(dates[:-1], dates[1:], strict=True)
        )
    return pd.DataFrame(panel_rows), pd.DataFrame(active_rows)


def test_protocol_is_byte_sealed_and_single_signal() -> None:
    protocol = v19.load_protocol()

    assert protocol["signal"]["economic_sign_to_SI"] == 1
    assert protocol["signal"]["trade_threshold"] == "none"
    assert protocol["signal"]["amount_scaling"] == "none"
    assert protocol["signal"]["smoothing"] == "none"
    assert protocol["portfolio"]["non_SI_targets"] == "zero"
    assert hashlib.sha256(v19.CONFIG_PATH.read_bytes()).hexdigest() == v19.CONFIG_SHA256


def test_normalize_factors_derives_only_the_predeclared_sign() -> None:
    normalized = v19.normalize_factors(_factors())

    assert len(normalized) == 1238
    assert normalized["direction"].value_counts().to_dict() == {
        -1.0: 690,
        0.0: 299,
        1.0: 249,
    }
    assert normalized["available_at"].max() < v19.PROTECTED_FROM
    tampered = _factors()
    tampered.loc[0, "available_at"] = pd.Timestamp("2021-01-12T06:00:00Z")
    with pytest.raises(ValueError, match="availability drifted"):
        v19.normalize_factors(tampered)


def test_build_decisions_only_trades_si_and_resolves_collisions_latest() -> None:
    factors = _factors()
    panel, active = _market()
    removed = pd.to_datetime(active["decision_date"]).between("2022-03-01", "2022-03-20")
    active = active.loc[~removed].copy()

    result = v19.build_source_decisions(factors, panel, active)

    assert result.mapped_source_count > 1000
    assert result.same_session_collisions > 0
    assert not result.weights.duplicated(["decision_date", "asset"]).any()
    mapped = result.decisions.loc[
        result.decisions["decision_status"].eq("mapped")
        & result.decisions["target_weight"].ne(0.0)
    ].iloc[0]
    snapshot = result.weights.loc[
        result.weights["decision_date"].eq(mapped["decision_date"])
    ].set_index("asset")["target_weight"]
    assert snapshot["SI"] != 0.0
    assert snapshot.drop("SI").eq(0.0).all()
    candidates = result.decisions.loc[
        result.decisions["decision_date"].eq(pd.Timestamp("2022-03-21"))
        & result.decisions["decision_status"].isin(
            {"mapped", "superseded_same_decision_session"}
        )
    ]
    if len(candidates) > 1:
        selected = candidates.loc[candidates["decision_status"].eq("mapped")].iloc[0]
        assert selected["source_observation_date"] == candidates[
            "source_observation_date"
        ].max()


def test_missing_minfin_factor_fails_closed() -> None:
    factors = _factors()
    factors.loc[100, "minfin_fx_operations_bln_rub"] = np.nan

    with pytest.raises(ValueError, match="must be finite"):
        v19.normalize_factors(factors)
