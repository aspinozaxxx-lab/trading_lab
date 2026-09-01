"""Tests for the sealed calendar-spread economic experiment."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from market_lab.futures import calendar_spread_v1 as subject


def _active_frame(rows_per_asset: int = 50) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    dates = pd.bdate_range("2021-01-04", periods=rows_per_asset)
    for asset_index, asset in enumerate(subject.ASSETS):
        midpoint = 100.0 + 10.0 * asset_index + np.arange(rows_per_asset, dtype=float)
        for index, trade_date in enumerate(dates):
            records.append(
                {
                    "trade_date": trade_date,
                    "available_at": (trade_date + pd.Timedelta(days=1)).tz_localize(
                        "Europe/Moscow"
                    ),
                    "spread_id": f"{asset}:TEST",
                    "logical_asset": asset,
                    "near_contract_id": f"{asset}:{asset}N:2021-06-01",
                    "far_contract_id": f"{asset}:{asset}F:2021-09-01",
                    "near_expiration": pd.Timestamp("2021-06-01"),
                    "far_expiration": pd.Timestamp("2021-09-01"),
                    "last": midpoint[index],
                    "bid": midpoint[index] - 0.5,
                    "ask": midpoint[index] + 0.5,
                    "amount": 100.0 + index,
                    "volume": 10_000.0 + index,
                    "num_trades": 100.0 + index,
                    "days_to_near_expiration": 100 - index,
                    "calendar_tenor_days": 92,
                    "quote_width": 1.0,
                    "quote_midpoint": midpoint[index],
                    "strict_positive_quote_width": True,
                    "zero_locked_quote": False,
                    "last_outside_range": False,
                    "both_sizing_usable": True,
                    "spec_observations_strictly_prior": True,
                }
            )
    return pd.DataFrame.from_records(records)


def test_feature_baseline_is_prior_only_and_cross_asset_same_date() -> None:
    frame = _active_frame()
    features = subject.build_feature_frame(frame)
    si = features.loc[features["logical_asset"].eq("SI")].reset_index(drop=True)
    expected_mean = float(np.arange(100.0, 120.0).mean())
    expected_std = float(np.arange(100.0, 120.0).std(ddof=1))
    assert si.loc[20, "mean20"] == pytest.approx(expected_mean)
    assert si.loc[20, "std20"] == pytest.approx(expected_std)
    assert si.loc[20, "z20"] == pytest.approx((120.0 - expected_mean) / expected_std)
    assert si.loc[20, "cross_z20_SI"] == pytest.approx(si.loc[20, "z20"])
    assert features["trade_date"].max() < subject.PROTECTED_FROM


def test_mlp_training_labels_end_strictly_before_refit() -> None:
    active = _active_frame(rows_per_asset=90)
    oscillation = np.sin(np.arange(len(active), dtype=float) / 3.0)
    active["quote_midpoint"] = active["quote_midpoint"] + oscillation
    active["last"] = active["quote_midpoint"]
    active["bid"] = active["quote_midpoint"] - 0.5
    active["ask"] = active["quote_midpoint"] + 0.5
    features = subject.build_feature_frame(active)
    settings = {
        "target_clip": [-3.0, 3.0],
        "minimum_training_samples": 40,
        "hidden_layer_sizes": [4],
        "activation": "tanh",
        "solver": "adam",
        "alpha": 0.01,
        "learning_rate_init": 0.001,
        "maximum_iterations": 10,
        "random_state": 1729,
        "shuffle": False,
        "early_stopping": False,
    }
    predicted = subject.build_mlp_predictions(features, settings)
    available = predicted["mlp_prediction"].notna()
    assert available.any()
    assert (
        predicted.loc[available, "mlp_train_max_target_date"]
        < predicted.loc[available, "mlp_refit_date"]
    ).all()


def test_equal_quantity_pair_cash_move_has_official_far_minus_near_sign() -> None:
    pnl = subject._pair_move(
        direction=1,
        quantity=2,
        near_from=100.0,
        near_to=103.0,
        near_point_value=10.0,
        far_from=110.0,
        far_to=115.0,
        far_point_value=12.0,
    )
    assert pnl == pytest.approx(60.0)
    assert subject._pair_move(-1, 2, 100.0, 103.0, 10.0, 110.0, 115.0, 12.0) == pytest.approx(-60.0)


def test_pair_ledger_fills_equal_quantity_and_exits_after_decision() -> None:
    dates = pd.to_datetime(["2021-02-01", "2021-02-02"])
    records: list[dict[str, object]] = []
    for date, near_open, far_open in zip(
        dates, (100.0, 101.0), (110.0, 113.0), strict=True
    ):
        for asset, contract, open_price in (
            ("SI", "SI:N", near_open),
            ("SI", "SI:F", far_open),
        ):
            records.append(
                {
                    "session_date": date,
                    "asset_code": asset,
                    "contract_id": contract,
                    "open": open_price,
                    "settle": open_price,
                    "volume": 10_000.0,
                    "lagged_volume": 10_000.0,
                    "sizing_point_value": 10.0,
                    "accounting_point_value": 10.0,
                    "tick_size": 1.0,
                    "fee_per_contract": 0.0,
                    "initial_margin": 100.0,
                }
            )
    market = pd.DataFrame.from_records(records)
    plans = pd.DataFrame(
        [
            {
                "plan_id": "test-plan",
                "strategy_id": "volatile_corridor_far_stop",
                "asset": "SI",
                "spread_id": "SI:TEST",
                "direction": 1,
                "near_contract_id": "SI:N",
                "far_contract_id": "SI:F",
                "entry_decision_date": pd.Timestamp("2021-01-29"),
                "entry_execution_date": pd.Timestamp("2021-02-01"),
                "exit_decision_date": pd.Timestamp("2021-02-01"),
                "entry_reason": "test",
                "exit_reason": "test",
            }
        ]
    )
    config = yaml.safe_load(
        (subject.PROJECT_ROOT / "configs/calendar_spread_v1.yaml").read_text(
            encoding="utf-8-sig"
        )
    )
    result = subject.simulate_strategy(
        "volatile_corridor_far_stop", plans, market, config, "primary"
    )
    completed = result.trades.loc[result.trades["status"].eq("completed")].iloc[0]
    assert completed["quantity"] == 100
    assert completed["exit_execution_date"] == pd.Timestamp("2021-02-02")
    assert completed["gross_pnl"] == pytest.approx(2_000.0)
    assert result.diagnostics["execution_complete"] is True


def test_trade_plan_far_stop_and_terminal_exit_are_causal() -> None:
    features = subject.build_feature_frame(_active_frame())
    for column in ("z10", "z20", "z40", "momentum5", "zero_convergence_score"):
        features[column] = np.nan
    features["cross_asset_residual"] = np.nan
    features["mlp_prediction"] = np.nan
    features["high_volatility"] = True
    si_index = features.index[features["logical_asset"].eq("SI")]
    features.loc[si_index[25], "z20"] = 2.0
    features.loc[si_index[26], "z20"] = 4.2
    features.loc[si_index[25:27], "std20"] = 5.0
    config = yaml.safe_load(
        (subject.PROJECT_ROOT / "configs/calendar_spread_v1.yaml").read_text(encoding="utf-8-sig")
    )
    plans = subject.build_trade_plans(features, config)
    primary = plans.loc[
        plans["strategy_id"].eq("volatile_corridor_far_stop") & plans["asset"].eq("SI")
    ]
    assert len(primary) == 1
    assert primary.iloc[0]["direction"] == -1
    assert primary.iloc[0]["exit_reason"] == "distant_score_stop"
    assert primary.iloc[0]["entry_decision_date"] < primary.iloc[0]["exit_decision_date"]


def test_real_protocol_is_sha_sealed_and_external() -> None:
    protocol = subject.load_protocol()
    assert protocol.config_sha256 == (
        "e74dab97ab65a28d4fc16f0061952545606ccccd1df7a8c677a8c8bc2af2b3bc"
    )
    assert protocol.output_directory == (
        subject.PROJECT_ROOT / "runs/calendar_spread_economic_2021_2025_v1"
    )
    assert not protocol.payload["live_trading_allowed"]
    assert len(protocol.payload["strategies"]) == 10
    assert Path(protocol.payload["output"]["directory"]).parts[0] == "runs"
