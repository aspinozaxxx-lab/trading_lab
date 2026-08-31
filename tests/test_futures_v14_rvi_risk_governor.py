"""Tests for the sealed V14 previous-session RVI risk governor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v14_rvi_risk_governor as v14


def _panel(dates: list[str]) -> pd.DataFrame:
    rows = []
    for trading_date in dates:
        for asset in v14.v12.ASSETS:
            rows.append(
                {
                    "trade_date": pd.Timestamp(trading_date),
                    "asset_code": asset,
                    "close": 100.0,
                }
            )
    return pd.DataFrame(rows)


def _weights(dates: list[str]) -> pd.DataFrame:
    rows = []
    for trading_date in dates:
        for asset in v14.v12.ASSETS:
            rows.append(
                {
                    "decision_date": pd.Timestamp(trading_date),
                    "asset": asset,
                    "target_weight": 0.10,
                    "provenance": "synthetic_v12",
                }
            )
    return pd.DataFrame(rows)


def _verified_rvi(rows: list[tuple[str, float]]) -> v14.RviVerification:
    frame = pd.DataFrame(
        {
            "source_date": [pd.Timestamp(date) for date, _ in rows],
            "close": [value for _, value in rows],
            "conservative_available_from_date": [
                pd.Timestamp(date) + pd.Timedelta(days=1) for date, _ in rows
            ],
        }
    )
    return v14.RviVerification(
        frame=frame,
        checks={"synthetic": True},
        calibration_rows=1,
        calibration_median=v14.RVI_FROZEN_MEDIAN,
    )


def test_protocol_is_byte_sealed_and_rvi_never_increases_risk() -> None:
    protocol = v14.load_protocol()

    assert protocol["protocol_id"] == "futures_v14_rvi_risk_governor_v1"
    assert protocol["research_only"] is True
    assert protocol["live_trading_allowed"] is False
    assert protocol["information_set"]["rvi_same_day"] == "forbidden"
    assert protocol["risk_governor"]["scale_can_increase_v12_risk"] is False
    assert v14.v12.sha256_file(v14.CONFIG_PATH) == v14.CONFIG_SHA256


def test_governor_uses_exact_previous_panel_session_and_proportional_scale() -> None:
    panel = _panel(["2020-12-28", "2020-12-29", "2020-12-30", "2020-12-31"])
    weights = _weights(["2020-12-30", "2020-12-31"])
    rvi = _verified_rvi(
        [
            ("2020-12-29", v14.RVI_FROZEN_MEDIAN / 2.0),
            ("2020-12-30", v14.RVI_FROZEN_MEDIAN * 2.0),
        ]
    )

    result = v14.apply_rvi_governor(panel, weights, rvi)
    audit = result.governor.set_index("decision_date")
    governed = result.weights.set_index(["decision_date", "asset"])

    assert audit.loc[pd.Timestamp("2020-12-30"), "rvi_source_date"] == pd.Timestamp(
        "2020-12-29"
    )
    assert audit.loc[pd.Timestamp("2020-12-30"), "risk_scale"] == pytest.approx(1.0)
    assert audit.loc[pd.Timestamp("2020-12-31"), "risk_scale"] == pytest.approx(0.5)
    assert governed.loc[(pd.Timestamp("2020-12-30"), "SI"), "target_weight"] == pytest.approx(
        0.10
    )
    assert governed.loc[(pd.Timestamp("2020-12-31"), "SI"), "target_weight"] == pytest.approx(
        0.05
    )


def test_same_day_rvi_is_not_used_and_missingness_goes_to_explicit_cash() -> None:
    panel = _panel(["2020-12-29", "2020-12-30", "2020-12-31"])
    weights = _weights(["2020-12-31"])
    same_day_only = _verified_rvi([("2020-12-31", 50.0)])

    result = v14.apply_rvi_governor(panel, weights, same_day_only)

    assert not result.governor.loc[0, "risk_scale_available"]
    assert pd.isna(result.governor.loc[0, "risk_scale"])
    assert result.weights["target_weight"].eq(0.0).all()
    assert result.weights["v12_target_weight"].eq(0.10).all()
    assert result.weights["provenance"].str.contains("missing_previous_session_rvi_cash").all()


def test_rvi_identity_checks_calibration_and_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2018-01-03", "2025-12-30", periods=2014).normalize()
    assert len(dates.unique()) == 2014
    frame = pd.DataFrame(
        {
            "source_date": dates,
            "close": 20.0,
            "conservative_available_from_date": dates + pd.Timedelta(days=1),
            "availability_rule": (
                "use_only_when_source_date_strictly_before_decision_date"
            ),
            "provider": "MOEX ISS",
            "current_vintage_snapshot": True,
        }
    )
    calibration_rows = int(
        frame["source_date"].between(
            v14.RVI_CALIBRATION_START, v14.RVI_CALIBRATION_END
        ).sum()
    )
    monkeypatch.setattr(v14, "RVI_CALIBRATION_ROWS", calibration_rows)
    monkeypatch.setattr(v14, "RVI_FROZEN_MEDIAN", 20.0)

    verified = v14.verify_rvi_source(frame)

    assert verified.calibration_rows == calibration_rows
    assert verified.calibration_median == pytest.approx(20.0)
    assert all(verified.checks.values())

    broken = frame.copy()
    broken.loc[0, "conservative_available_from_date"] = broken.loc[0, "source_date"]
    with pytest.raises(ValueError, match="availability"):
        v14.verify_rvi_source(broken)


def test_sidecar_names_the_sealed_protocol() -> None:
    sidecar = Path(v14.CONFIG_PATH).with_suffix(".sha256")
    digest, name = sidecar.read_text(encoding="utf-8-sig").split()

    assert digest == v14.CONFIG_SHA256
    assert name == v14.CONFIG_PATH.name
