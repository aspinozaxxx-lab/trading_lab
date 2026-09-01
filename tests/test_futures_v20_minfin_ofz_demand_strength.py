"""Tests for the sealed V20 Minfin OFZ-PD demand-strength experiment."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v20_minfin_ofz_demand_strength as v20


def _market() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", "2021-05-31", freq="D")
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
                "contract_id": f"{asset}H1",
                "plan_tradable": True,
                "roll": False,
            }
            for current, following in zip(dates[:-1], dates[1:], strict=True)
        )
    return pd.DataFrame(panel_rows), pd.DataFrame(active_rows)


def _signal(date_value: str, score: float) -> dict[str, object]:
    publication = pd.Timestamp(date_value)
    available = (
        publication.tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).tz_convert("UTC")
    return {
        "publication_date": publication,
        "available_at": available,
        "result_count": 2,
        "document_ids": "[1,2]",
        "total_demand_bln_rub": 200.0,
        "total_placed_bln_rub": 100.0,
        "same_day_bid_to_cover": 2.0,
        "history_count": 26,
        "history_min_publication_date": publication - pd.Timedelta(days=180),
        "history_max_publication_date": publication - pd.Timedelta(days=7),
        "bid_to_cover_percentile": 0.8,
        "placed_volume_percentile": 0.8,
        "score": score,
        "signal_status": "scored",
    }


def test_protocol_is_byte_sealed_and_has_no_threshold() -> None:
    protocol = v20.load_protocol()

    assert protocol["signal"]["rank_window_prior_auction_days"] == 26
    assert protocol["signal"]["minimum_prior_auction_days"] == 13
    assert protocol["signal"]["score_threshold"] == "none"
    assert protocol["signal"]["economic_signs"] == {
        "RI": 1,
        "MIX": 1,
        "SI": -1,
        "BR": 0,
    }
    assert protocol["signal"]["expiry_calendar_days"] == 7
    assert hashlib.sha256(v20.CONFIG_PATH.read_bytes()).hexdigest() == v20.CONFIG_SHA256


def test_real_source_preflight_and_prior_only_signal_counts() -> None:
    protocol = v20.load_protocol()
    verified = v20.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["minfin_ofz_auction_events"],
        columns=protocol["inputs"]["minfin_ofz_auction_events"]["allowed_columns"],
    )

    events = v20.normalize_events(raw)
    signals = v20.build_source_signals(events)
    scored = signals.loc[signals["signal_status"].eq("scored")]

    assert all(verified.checks.values())
    assert len(events) == 410
    assert len(signals) == 179
    assert len(scored) == 166
    assert scored["score"].gt(0.0).sum() == 82
    assert scored["score"].lt(0.0).sum() == 76
    assert scored["score"].eq(0.0).sum() == 8
    assert scored["history_max_publication_date"].lt(scored["publication_date"]).all()


def test_empirical_percentile_uses_strict_lower_and_half_ties() -> None:
    history = np.array([1.0, 2.0, 2.0, 4.0])

    assert v20._empirical_percentile(history, 2.0) == 0.5
    assert v20._empirical_percentile(history, 0.0) == 0.0
    assert v20._empirical_percentile(history, 5.0) == 1.0


def test_build_decisions_maps_fixed_basket_and_seven_day_expiry() -> None:
    signals = pd.DataFrame(
        [
            _signal("2021-04-01", 0.6),
            _signal("2021-04-20", -0.4),
        ]
    )
    panel, active = _market()

    result = v20.build_source_decisions(signals, panel, active)

    assert result.expiry_state_count == 2
    assert result.same_session_collisions == 0
    assert not result.weights.duplicated(["decision_date", "asset"]).any()
    first = result.weights.loc[
        result.weights["decision_date"].eq(pd.Timestamp("2021-04-01"))
    ].set_index("asset")["target_weight"]
    assert first["RI"] > 0.0
    assert first["MIX"] > 0.0
    assert first["SI"] < 0.0
    assert first["BR"] == 0.0
    expiry = result.weights.loc[
        result.weights["decision_date"].eq(pd.Timestamp("2021-04-08")), "target_weight"
    ]
    assert expiry.eq(0.0).all()
    assert result.weights.groupby("decision_date")["target_weight"].apply(
        lambda values: float(values.abs().sum())
    ).le(1.0).all()


def test_normalize_rejects_early_availability() -> None:
    protocol = v20.load_protocol()
    verified = v20.verify_inputs(protocol)
    raw = pd.read_parquet(
        verified.paths["minfin_ofz_auction_events"],
        columns=protocol["inputs"]["minfin_ofz_auction_events"]["allowed_columns"],
    )
    raw.loc[0, "available_at"] = pd.Timestamp("2021-01-13T10:00:00Z")

    with pytest.raises(ValueError, match="availability drifted"):
        v20.normalize_events(raw)
