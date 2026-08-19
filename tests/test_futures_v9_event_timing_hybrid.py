from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab.futures_v9_event_timing_hybrid import (
    calibrate_v1_thresholds,
    eligible_decisions,
    paired_improvement,
)


def test_prior_tail_calibration_is_strictly_before_outer_year() -> None:
    timestamps = pd.date_range("2021-09-03", periods=1100, freq="2h", tz="UTC")
    rows = []
    for variant in ("attention", "independent"):
        for timestamp in timestamps:
            row = {"timestamp": timestamp, "variant": variant}
            for side in ("long", "short"):
                for horizon in (3, 6, 18):
                    row[f"{side}_value_{horizon}"] = 0.1
                    row[f"{side}_value_{horizon}_uncertainty"] = 0.2
                row[f"{side}_score"] = 0.5
            rows.append(row)
    frame = pd.DataFrame(rows)
    thresholds = calibrate_v1_thresholds(frame)
    assert thresholds[("attention", 2021, 1)]["threshold"] is None
    assert thresholds[("attention", 2022, 1)]["threshold"] == 0.5
    assert thresholds[("attention", 2022, 1)]["rows"] >= 1000


def test_eligible_decisions_counts_only_complete_exact_execution_rows() -> None:
    class Tiny:
        timestamps_ns = np.arange(8, dtype=np.int64) * 600_000_000_000
        asset_mask = np.ones((8, 1), dtype=bool)
        execution_mask = np.array([[0], [1], [0], [1], [1], [1], [1], [1]], dtype=bool)
        sizing_mask = np.ones((8, 1), dtype=bool)

    assert eligible_decisions(Tiny(), asset_index=0, available_ns=0, maximum=3) == [1, 3, 4]


def test_paired_skip_is_zero_not_a_fallback_trade() -> None:
    baseline = pd.DataFrame(
        {
            "event_key": ["a|SI", "b|SI"],
            "exit_time": pd.to_datetime(["2022-01-03", "2022-01-04"], utc=True),
            "entry_notional": [1000.0, 1000.0],
            "pnl_1x": [10.0, -5.0],
            "pnl_2x": [8.0, -7.0],
        }
    )
    timed = pd.DataFrame(
        {
            "event_key": ["a|SI"],
            "pnl_1x": [15.0],
            "pnl_2x": [12.0],
            "delay_bars": [2],
        }
    )
    result = paired_improvement(baseline, timed)
    assert result["timed_matched_trades"] == 1
    assert result["incremental_pnl_1x_rub"] == 10.0
    assert result["average_matched_delay_bars"] == 2.0
