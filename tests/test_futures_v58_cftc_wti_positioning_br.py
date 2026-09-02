"""Synthetic-only tests for the sealed V58 CFTC-to-BR experiment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from market_lab import futures_v58_cftc_wti_positioning_br as v58


def _panel(periods: int = 180) -> pd.DataFrame:
    dates = pd.bdate_range("2022-07-01", periods=periods)
    rows: list[dict[str, object]] = []
    aliases = {"SI": "Si", "RI": "RTS", "BR": "BR", "MIX": "MIX"}
    for asset, alias in aliases.items():
        steps = np.arange(periods, dtype=float)
        slope = 0.001 if asset == "BR" else 0.0002
        close = 100.0 * np.exp(slope * steps + 0.01 * np.sin(steps / 4.0))
        for date, value in zip(dates, close, strict=True):
            rows.append({"trade_date": date, "asset_code": alias, "close": value})
    return pd.DataFrame(rows)


def _cftc(periods: int = 35) -> pd.DataFrame:
    reports = pd.date_range("2022-06-07", periods=periods, freq="W-TUE")
    rows = []
    for index, report in enumerate(reports):
        rows.append(
            {
                "report_date": report,
                "available_at_utc": (report + pd.Timedelta(days=8)).tz_localize("UTC"),
                "logical_market": "WTI",
                "open_interest": 1_000.0,
                "managed_money_long": 300.0 + index * 5.0,
                "managed_money_short": 200.0,
            }
        )
        rows.append(
            {
                "report_date": report,
                "available_at_utc": (report + pd.Timedelta(days=8)).tz_localize("UTC"),
                "logical_market": "GOLD",
                "open_interest": 2_000.0,
                "managed_money_long": 400.0,
                "managed_money_short": 350.0,
            }
        )
    return pd.DataFrame(rows)


def _active_map(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for index, decision in enumerate(dates):
        for asset in ("SI", "RI", "BR", "MIX"):
            rows.append(
                {
                    "decision_date": decision,
                    "effective_date": decision + pd.offsets.BDay(1),
                    "observed_through": decision,
                    "asset_code": asset,
                    "contract_id": f"{asset}:H3" if index < 2 else f"{asset}:M3",
                    "plan_tradable": True,
                    "roll": index == 2,
                }
            )
    return pd.DataFrame(rows)


def test_protocol_is_byte_sealed_and_keeps_single_candidate() -> None:
    assert v58.sha256_file(v58.CONFIG_PATH) == v58.CONFIG_SHA256
    protocol = v58.load_protocol()
    assert protocol["signal"]["lookback_admitted_reports"] == 13
    assert protocol["risk"]["annual_volatility_target"] == 0.30
    assert protocol["risk"]["maximum_absolute_target"] == 2.0
    assert protocol["live_trading_allowed"] is False


def test_weekly_signal_uses_only_available_wti_and_fixed_positive_direction() -> None:
    signals = v58.build_weekly_signals(_panel(), _cftc())
    active = signals.loc[signals["candidate_sign"].ne(0.0)]

    assert not active.empty
    assert active["candidate_sign"].eq(1.0).all()
    assert active["candidate_target_weight"].between(0.0, 2.0).all()
    assert active["cftc_available_at_utc"].le(active["decision_at_utc"]).all()
    assert active["cftc_source_age_days"].between(0, 14).all()


def test_future_mutations_do_not_change_prior_signals() -> None:
    panel = _panel()
    cftc = _cftc()
    baseline = v58.build_weekly_signals(panel, cftc)
    cutoff = pd.Timestamp("2022-12-30")
    revised_panel = panel.copy()
    revised_panel.loc[revised_panel["trade_date"].gt(cutoff), "close"] *= 20.0
    revised_cftc = cftc.copy()
    future = pd.to_datetime(revised_cftc["available_at_utc"], utc=True).gt(
        cutoff.tz_localize("Europe/Moscow").tz_convert("UTC")
    )
    revised_cftc.loc[future, "managed_money_long"] *= 50.0
    revised = v58.build_weekly_signals(revised_panel, revised_cftc)
    columns = [
        "decision_date",
        "cftc_report_date",
        "position_change_13",
        "candidate_target_weight",
        "baseline_target_weight",
    ]
    pdt.assert_frame_equal(
        baseline.loc[baseline["decision_date"].le(cutoff), columns].reset_index(drop=True),
        revised.loc[revised["decision_date"].le(cutoff), columns].reset_index(drop=True),
    )


def test_target_mapping_adds_nonweekly_roll_with_carried_weight() -> None:
    dates = pd.bdate_range("2023-01-09", periods=4)
    signals = pd.DataFrame(
        {
            "decision_date": [dates[0], dates[3]],
            "candidate_target_weight": [1.5, -1.25],
        }
    )
    built = v58.build_execution_targets(
        signals,
        _active_map(dates),
        "candidate_target_weight",
        evaluation_start=pd.Timestamp("2023-01-01"),
        evaluation_end=pd.Timestamp("2023-12-31"),
    )

    assert built.weekly_decisions == 2
    assert built.roll_decisions == 1
    roll = built.targets.loc[built.targets["decision_date"].eq(dates[2])].iloc[0]
    assert roll["contract_id"] == "BR:M3"
    assert roll["target_weight"] == 1.5


def test_levered_target_normalizer_preserves_two_x_after_validation() -> None:
    effective = pd.Timestamp("2023-01-10")
    targets = pd.DataFrame(
        {
            "effective_date": [effective],
            "decision_date": [pd.Timestamp("2023-01-09")],
            "asset_code": ["BR"],
            "contract_id": ["BR:H3"],
            "target_weight": [2.0],
        }
    )
    normalized = v58._normalize_levered_targets(targets, pd.DatetimeIndex([effective]), ("BR",))

    assert normalized["target_weight"].iloc[0] == 2.0
