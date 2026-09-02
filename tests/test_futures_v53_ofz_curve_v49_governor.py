from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from market_lab import futures_v53_ofz_curve_v49_governor as v53


def _config() -> dict:
    return yaml.safe_load(
        (Path(__file__).parents[1] / "configs/v53_ofz_curve_v49_governor_v1.yaml").read_text(
            encoding="utf-8-sig"
        )
    )


def test_curve_state_uses_month_end_prior_liquidity_and_sign_only() -> None:
    config = _config()
    dates = pd.bdate_range("2021-01-01", periods=22)
    definitions = {
        "SU262S1": (3.0, 10.0),
        "SU262S2": (3.5, 12.0),
        "SU262L1": (5.5, 8.0),
        "SU262L2": (6.5, 9.0),
    }
    rows: list[dict] = []
    for security, (years, yield_value) in definitions.items():
        for date in dates:
            rows.append(
                {
                    "trade_date": date,
                    "security_id": security,
                    "currency_id": "SUR",
                    "face_unit": "RUB",
                    "maturity_date": date + pd.Timedelta(days=int(years * 365.25)),
                    "available_at_utc": pd.Timestamp(date, tz="UTC")
                    + pd.Timedelta(days=1),
                    "value_rub": 20_000_000.0,
                    "yield_at_wap_pct": yield_value,
                }
            )
    states = v53.build_curve_states(pd.DataFrame(rows), config)
    valid = states.loc[states["curve_state"].ne("missing")].iloc[-1]
    assert valid["short_count"] == 2
    assert valid["long_count"] == 2
    assert valid["short_median_yield_pct"] == pytest.approx(11.0)
    assert valid["long_median_yield_pct"] == pytest.approx(8.5)
    assert valid["curve_state"] == "inverted"
    assert valid["risk_factor"] == 1.25
    assert valid["effective_date"] > valid["decision_date"]


def test_governor_applies_latest_available_state_without_same_day_backfill() -> None:
    config = _config()
    states = pd.DataFrame(
        {
            "effective_date": pd.to_datetime(["2021-02-01"]),
            "decision_date": pd.to_datetime(["2021-01-29"]),
            "curve_state": ["inverted"],
            "risk_factor": [1.25],
        }
    )
    dates = pd.to_datetime(["2021-01-29", "2021-02-01", "2021-02-02"])
    v49 = pd.DataFrame({"session_date": dates})
    for column in config["scenario_columns"].values():
        v49[column] = [100.0, 110.0, 121.0]
    ledger = v53.apply_governor(states, v49, config)
    primary = ledger.loc[ledger["scenario"].eq("primary")].reset_index(drop=True)
    assert primary.loc[0, "curve_state"] == "missing"
    assert primary.loc[0, "risk_factor"] == 0.0
    assert primary.loc[1, "governed_return"] == pytest.approx(0.125)
    assert primary.loc[2, "governed_return"] == pytest.approx(0.125)
