from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v9_corridor.data import (
    ASSETS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONFIG_SHA256,
    build_synchronized_intraday_arrays,
    load_protocol,
    sha256_file,
)
from market_lab.futures_v9_corridor.labels import (
    PRIMARY_CORRIDOR,
    CorridorEvent,
    Direction,
    PriceBar,
    evaluate_corridor,
)
from market_lab.futures_v9_corridor.model import fit_expanding_corridor_models


def _bar(
    minute: int,
    *,
    open_price: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    day: int = 2,
) -> PriceBar:
    opened = datetime(2025, 1, day, 16, minute, tzinfo=UTC)
    return PriceBar(
        opened_at=opened,
        closed_at=opened + timedelta(minutes=10),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
    )


def test_protocol_is_bom_sealed_and_has_exact_economics() -> None:
    assert DEFAULT_CONFIG_PATH.read_bytes().startswith(b"\xef\xbb\xbf")
    assert sha256_file(DEFAULT_CONFIG_PATH) == DEFAULT_CONFIG_SHA256
    protocol = load_protocol()
    assert protocol["corridors"]["primary"]["take_profit_atr"] == 0.8
    assert protocol["corridors"]["primary"]["stop_loss_atr"] == 2.8
    assert protocol["execution"]["same_bar_precedence"] == "stop_before_take_profit"
    assert protocol["portfolio"]["entry_capacity_fraction"] == 0.01


def test_long_same_bar_collision_is_stop_first() -> None:
    entry = _bar(20, high=100.0, low=99.0, close=99.5)
    collision = _bar(30, open_price=100.0, high=101.0, low=96.0, close=100.0)
    exit_bar = _bar(20, day=9)
    outcome = evaluate_corridor(
        entry_bar=entry,
        monitoring_bars=(collision,),
        time_exit_bar=exit_bar,
        atr=1.0,
        direction=Direction.LONG,
        spec=PRIMARY_CORRIDOR,
    )
    assert outcome.event is CorridorEvent.STOP_LOSS
    assert outcome.same_bar_collision is True
    assert outcome.exit_price == pytest.approx(97.2)


def test_short_same_bar_collision_and_gap_are_stop_first() -> None:
    entry = _bar(20, high=101.0, low=100.0, close=100.5)
    collision = _bar(30, open_price=104.0, high=104.5, low=98.0, close=101.0)
    exit_bar = _bar(20, day=9)
    outcome = evaluate_corridor(
        entry_bar=entry,
        monitoring_bars=(collision,),
        time_exit_bar=exit_bar,
        atr=1.0,
        direction=Direction.SHORT,
        spec=PRIMARY_CORRIDOR,
    )
    assert outcome.event is CorridorEvent.STOP_LOSS
    assert outcome.same_bar_collision is True
    assert outcome.exit_price == 104.0
    assert outcome.gross_price_pnl == -4.0


def test_entry_and_time_exit_are_directionally_adverse() -> None:
    entry = _bar(20, high=102.0, low=98.0, close=100.0)
    exit_bar = _bar(20, open_price=105.0, high=107.0, low=103.0, close=105.0, day=9)
    long = evaluate_corridor(
        entry_bar=entry,
        monitoring_bars=(),
        time_exit_bar=exit_bar,
        atr=10.0,
        direction="long",
        spec=PRIMARY_CORRIDOR,
    )
    short = evaluate_corridor(
        entry_bar=entry,
        monitoring_bars=(),
        time_exit_bar=exit_bar,
        atr=10.0,
        direction="short",
        spec=PRIMARY_CORRIDOR,
    )
    assert (long.entry_price, long.exit_price, long.gross_price_pnl) == (102.0, 103.0, 1.0)
    assert (short.entry_price, short.exit_price, short.gross_price_pnl) == (98.0, 107.0, -9.0)


def test_unsorted_monitoring_bars_fail_closed() -> None:
    with pytest.raises(ValueError, match="sorted"):
        evaluate_corridor(
            entry_bar=_bar(20),
            monitoring_bars=(_bar(40), _bar(30)),
            time_exit_bar=_bar(20, day=9),
            atr=1.0,
            direction="long",
            spec=PRIMARY_CORRIDOR,
        )


def test_price_bar_rejects_protected_2026() -> None:
    with pytest.raises(ValueError, match="protected"):
        PriceBar(
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            closed_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
        )


def test_synchronized_intraday_arrays_keep_masks_and_exact_t_plus_one() -> None:
    rows: list[dict[str, object]] = []
    starts = pd.date_range("2025-01-02 07:00:00+00:00", periods=4, freq="10min")
    for asset in ASSETS:
        for index, opened in enumerate(starts):
            if asset == "RI" and index == 1:
                continue
            rows.append(
                {
                    "timestamp": opened,
                    "asset": asset,
                    "contract_id": f"{asset}:H5",
                    "open": 100.0 + index,
                    "high": 101.0 + index,
                    "low": 99.0 + index,
                    "close": 100.5 + index,
                    "volume": 1_000.0,
                }
            )
    bars = pd.DataFrame(rows)
    plan = pd.DataFrame(
        {
            "decision_date": [date(2025, 1, 2)] * 4,
            "asset": ASSETS,
            "contract_id": [f"{asset}:H5" for asset in ASSETS],
        }
    )
    arrays = build_synchronized_intraday_arrays(
        bars,
        plan,
        start=date(2025, 1, 2),
        end=date(2025, 1, 2),
    )
    assert arrays.features.shape[:2] == (4, 4)
    ri = ASSETS.index("RI")
    assert not arrays.asset_mask[1, ri]
    assert not arrays.feature_mask[1, ri].any()
    assert not arrays.execution_mask[0, ri]
    assert arrays.execution_mask[0, ASSETS.index("BR")]
    assert arrays.execution_ohlcv[0, ASSETS.index("BR"), 0] == 101.0


def _synthetic_model_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    for year in range(2018, 2026):
        for day_index in range(1, 25):
            decision = pd.Timestamp(datetime(year, 2, day_index, 15, 50, tzinfo=UTC))
            for asset_index, asset in enumerate(ASSETS):
                base = 0.001 * (day_index + asset_index)
                feature_rows.append(
                    {
                        "decision_at": decision,
                        "decision_date": decision.date(),
                        "asset": asset,
                        "market_valid": True,
                        "adjusted_close": 100.0 + asset_index,
                        "atr_20": 2.0,
                        "daily_volatility_20": 0.01 + base,
                        "momentum_1": base,
                        "momentum_5": 2 * base,
                        "momentum_20": 3 * base,
                        "overnight_gap": -base,
                        "intraday_return": base,
                        "first_hour_return": base / 2,
                        "last_hour_return": -base / 3,
                        "range_position_20": 0.5,
                        "volatility_ratio_20": 1.0 + base,
                        "volume_ratio_20": 1.0,
                        "close_location": 0.6,
                        "up_bar_fraction": 0.5,
                        "max_abs_bar_return": base,
                        "intraday_return_skew": 0.0,
                        "carry_z": base,
                        "cftc_z": -base,
                        "usd_rub_return_z": base / 2,
                        "key_rate_sleeping": 1.0,
                        "regime_normal_probability": 0.5,
                        "regime_trend_probability": 0.3,
                        "regime_crash_probability": 0.2,
                        "main_session_bucket_count": 53,
                    }
                )
                for direction_index, direction in enumerate(("long", "short")):
                    event = (day_index + asset_index + direction_index) % 3
                    event_name = ("take_profit", "stop_loss", "time_exit")[event]
                    for corridor in ("primary", "safer_diagnostic"):
                        label_rows.append(
                            {
                                "decision_at": decision,
                                "decision_date": decision.date(),
                                "asset": asset,
                                "direction": direction,
                                "corridor_id": corridor,
                                "contract_id": f"{asset}:H{year % 10}",
                                "event_type": event_name,
                                "event_at": decision + pd.Timedelta(days=1),
                                "entry_price": 100.0,
                                "exit_price": 101.0,
                                "gross_price_pnl": 1.0 if event == 0 else -1.0,
                                "entry_volume": 10_000.0,
                                "same_bar_collision": False,
                                "atr_20": 2.0,
                                "label_resolved": True,
                            }
                        )
    return pd.DataFrame(feature_rows), pd.DataFrame(label_rows)


def test_oos_label_mutation_cannot_change_fold_probability() -> None:
    features, labels = _synthetic_model_inputs()
    first = fit_expanding_corridor_models(features, labels).predictions
    poisoned = labels.copy()
    mask = pd.to_datetime(poisoned["decision_at"], utc=True).dt.year == 2025
    poisoned.loc[mask, "event_type"] = "stop_loss"
    second = fit_expanding_corridor_models(features, poisoned).predictions
    key = ["corridor_id", "decision_at", "asset", "direction"]
    left = first[pd.to_datetime(first["decision_at"], utc=True).dt.year == 2025].sort_values(key)
    right = second[pd.to_datetime(second["decision_at"], utc=True).dt.year == 2025].sort_values(key)
    np.testing.assert_array_equal(
        left["calibrated_tp_probability"].to_numpy(),
        right["calibrated_tp_probability"].to_numpy(),
    )


def test_all_new_source_files_have_utf8_bom() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "configs" / "futures_v9_corridor.yaml",
        root / "configs" / "futures_v9_corridor.sha256",
        *sorted((root / "src" / "market_lab" / "futures_v9_corridor").glob("*.py")),
    ]
    assert paths
    assert all(path.read_bytes().startswith(b"\xef\xbb\xbf") for path in paths)
