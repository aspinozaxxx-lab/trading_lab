"""Causality, calibration, risk and ledger tests for the sealed V32 family."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v32_curve_regime_intraday as runner
from market_lab.futures.curve_regime_intraday import (
    ASSETS,
    MODEL_FULL_MLP,
    LedgerSettings,
    ModelSettings,
    build_learning_frame,
    build_weight_targets,
    market_feature_columns,
    risk_covariance_columns,
    select_threshold_multiple,
    simulate_next_open_portfolio,
    source_feature_columns,
)


def _curve_context() -> pd.DataFrame:
    row: dict[str, object] = {
        "event_at": pd.Timestamp("2025-01-02 07:00:00+00:00"),
        "available_at": pd.Timestamp("2025-01-02 07:00:00+00:00"),
    }
    row.update(
        {column: (index + 1) / 100.0 for index, column in enumerate(source_feature_columns())}
    )
    return pd.DataFrame([row])


def _learning_panel() -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01 18:00:00+00:00", periods=160, freq="10min")
    scheduled_end = timestamps + pd.Timedelta(minutes=10)
    local_date = scheduled_end.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    frame = pd.DataFrame({"timestamp": timestamps, "local_date": local_date})
    index = np.arange(len(frame), dtype=float)
    for asset_index, asset in enumerate(ASSETS):
        close = 100.0 + 20.0 * asset_index + 0.04 * index + 0.1 * np.sin(index / 5.0)
        opened = close - 0.02 * np.cos(index / 7.0)
        frame[f"{asset}_contract_id"] = f"{asset}:H5"
        frame[f"{asset}_source_end_timestamp"] = scheduled_end
        frame[f"{asset}_open"] = opened
        frame[f"{asset}_high"] = np.maximum(opened, close) + 0.2
        frame[f"{asset}_low"] = np.minimum(opened, close) - 0.2
        frame[f"{asset}_close"] = close
        frame[f"{asset}_volume"] = 100_000.0 + index
        frame[f"{asset}_sizing_notional"] = 10_000.0
        frame[f"{asset}_sizing_tick_cash_value"] = 1.0
        frame[f"{asset}_conservative_fee_per_side"] = 1.0
        frame[f"{asset}_sizing_point_value"] = 1.0
        frame[f"{asset}_modeled_initial_margin"] = 1_000.0
        frame[f"{asset}_sizing_usable"] = True
    return frame


def _execution_panel(*, final_si_volume: float = 100_000.0) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-02 07:00:00+00:00", periods=3, freq="10min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "local_date": pd.Timestamp("2025-01-02"),
        }
    )
    for asset in ASSETS:
        opened = [100.0, 101.0, 103.0] if asset == "SI" else [100.0, 100.0, 100.0]
        frame[f"{asset}_contract_id"] = f"{asset}:H5"
        frame[f"{asset}_open"] = opened
        frame[f"{asset}_volume"] = [100_000.0, 100_000.0, 100_000.0]
        frame[f"{asset}_sizing_point_value"] = 1.0
        frame[f"{asset}_sizing_tick_cash_value"] = 1.0
        frame[f"{asset}_conservative_fee_per_side"] = 1.0
        frame[f"{asset}_modeled_initial_margin"] = 100.0
        frame[f"{asset}_sizing_notional"] = 1_000.0
    frame.loc[2, "SI_volume"] = final_si_volume
    return frame


def _execution_targets() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for entry_at, forced_flat in (
        (pd.Timestamp("2025-01-02 07:10:00+00:00"), False),
        (pd.Timestamp("2025-01-02 07:20:00+00:00"), True),
    ):
        for asset in ASSETS:
            records.append(
                {
                    "entry_at": entry_at,
                    "asset": asset,
                    "contract_id": f"{asset}:H5",
                    "target_weight": 0.1 if asset == "SI" and not forced_flat else 0.0,
                    "signal_volume": 100_000.0,
                    "sizing_notional": 1_000.0,
                    "sizing_point_value": 1.0,
                    "sizing_tick_cash_value": 1.0,
                    "conservative_fee_per_side": 1.0,
                    "modeled_initial_margin": 100.0,
                    "forced_flat": forced_flat,
                }
            )
    return pd.DataFrame(records)


def test_frozen_feature_dimensions_are_stable() -> None:
    assert len(source_feature_columns()) == 92
    assert len(market_feature_columns()) == 47
    assert len(risk_covariance_columns()) == 16


def test_protocol_is_byte_sealed_and_forbids_live_trading() -> None:
    expected = runner.SIDECAR_PATH.read_text(encoding="utf-8-sig").split()[0]

    assert runner.sha256_file(runner.CONFIG_PATH) == expected
    protocol = runner.load_protocol()
    assert protocol["sealed_before_outcomes"] is True
    assert protocol["live_trading_allowed"] is False
    assert protocol["boundaries"]["protected_from"] == "2026-01-01"


def test_learning_features_are_causal_and_future_mutation_is_inert() -> None:
    panel = _learning_panel()
    baseline = build_learning_frame(panel, _curve_context())
    cutoff = pd.Timestamp("2025-01-02 09:00:00+00:00")
    mutated = panel.copy()
    future = mutated["timestamp"].gt(cutoff)
    for asset in ASSETS:
        for field in ("open", "high", "low", "close"):
            mutated.loc[future, f"{asset}_{field}"] *= 3.0
        mutated.loc[future, f"{asset}_volume"] *= 5.0
    replay = build_learning_frame(mutated, _curve_context())
    columns = [*source_feature_columns(), *market_feature_columns(), *risk_covariance_columns()]
    baseline_prior = baseline.loc[baseline["decision_at"].le(cutoff), columns]
    replay_prior = replay.loc[replay["decision_at"].le(cutoff), columns]

    pd.testing.assert_frame_equal(
        baseline_prior.reset_index(drop=True),
        replay_prior.reset_index(drop=True),
    )
    assert baseline["decision_at"].ge(baseline["source_available_at"]).all()
    assert baseline["entry_at"].eq(baseline["decision_at"]).all()
    assert baseline["target_end_at"].sub(baseline["entry_at"]).eq(pd.Timedelta(hours=1)).all()


def test_incomplete_source_bar_fails_closed() -> None:
    panel = _learning_panel()
    panel.loc[80, "SI_source_end_timestamp"] = panel.loc[80, "timestamp"] + pd.Timedelta(minutes=11)

    with pytest.raises(ValueError, match="not complete"):
        build_learning_frame(panel, _curve_context())


def test_exact_label_path_never_bridges_a_missing_bucket() -> None:
    panel = _learning_panel()
    missing_timestamp = pd.Timestamp("2025-01-02 09:00:00+00:00")
    panel = panel.loc[panel["timestamp"].ne(missing_timestamp)].reset_index(drop=True)
    learning = build_learning_frame(panel, _curve_context())

    assert not learning["entry_at"].eq(missing_timestamp).any()


def test_calibration_selects_only_a_predeclared_cost_multiple() -> None:
    count = 240
    timestamps = pd.date_range("2025-01-02 07:00:00+00:00", periods=count, freq="8h")
    calibration = pd.DataFrame({"decision_at": timestamps})
    prediction = np.empty((count, len(ASSETS)), dtype=float)
    for asset_index, asset in enumerate(ASSETS):
        sign = np.where((np.arange(count) + asset_index) % 2 == 0, 1.0, -1.0)
        prediction[:, asset_index] = sign * 0.006
        variation = 0.0002 * ((np.arange(count) % 7) - 3)
        calibration[f"target_{asset.lower()}_return"] = sign * (0.004 + variation)
        calibration[f"stress_roundtrip_cost_{asset.lower()}"] = 0.001

    selected, candidates = select_threshold_multiple(
        calibration,
        prediction,
        ModelSettings(),
    )

    assert selected == 4.0
    assert {item["threshold_multiple"] for item in candidates} == {1.5, 2.5, 4.0}
    assert all(item["eligible"] for item in candidates)


def test_risk_targets_are_bounded_and_force_same_day_flat() -> None:
    learning = build_learning_frame(_learning_panel(), _curve_context())
    learning = learning.loc[learning[list(risk_covariance_columns())].notna().all(axis=1)].head(2)
    records: list[dict[str, object]] = []
    for row in learning.itertuples(index=False):
        for index, asset in enumerate(ASSETS):
            records.append(
                {
                    "decision_at": row.decision_at,
                    "model_id": MODEL_FULL_MLP,
                    "asset": asset,
                    "score": 2.0 if index % 2 == 0 else -2.0,
                }
            )
    targets = build_weight_targets(pd.DataFrame(records), learning, MODEL_FULL_MLP)

    live = targets.loc[~targets["forced_flat"]]
    flat = targets.loc[targets["forced_flat"]]
    assert live.groupby("entry_at")["target_weight"].apply(lambda x: x.abs().sum()).le(1.6).all()
    assert live["target_weight"].abs().le(0.6).all()
    assert flat["target_weight"].eq(0.0).all()
    assert set(flat["entry_at"].dt.tz_convert("Europe/Moscow").dt.strftime("%H:%M")) == {"18:30"}


def test_next_open_ledger_marks_pnl_and_charges_both_sides() -> None:
    result = simulate_next_open_portfolio(
        _execution_panel(),
        _execution_targets(),
        LedgerSettings(),
    )

    assert result.execution_complete
    assert result.orders["filled"].sum() == 2
    assert result.orders["total_cost"].sum() == pytest.approx(400.0)
    assert result.ledger.loc[
        result.ledger["timestamp"].eq(pd.Timestamp("2025-01-02 07:20Z")), "bar_pnl"
    ].iloc[0] == pytest.approx(200.0)
    assert result.metrics["ending_equity"] == pytest.approx(999_800.0)


def test_exit_capacity_failure_is_explicit_no_go() -> None:
    result = simulate_next_open_portfolio(
        _execution_panel(final_si_volume=100.0),
        _execution_targets(),
        LedgerSettings(),
    )

    assert not result.execution_complete
    assert result.unresolved.iloc[0]["reason"] == "insufficient_exit_capacity"


def test_effective_contract_uses_only_a_strictly_prior_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "active.parquet"
    pd.DataFrame(
        {
            "effective_date": ["2025-01-03", "2025-01-03"],
            "decision_date": ["2025-01-02", "2025-01-03"],
            "observed_through": ["2025-01-02", "2025-01-03"],
            "asset_code": ["SI", "RI"],
            "contract_id": ["SI:H5", "RI:H5"],
            "plan_tradable": [True, True],
        }
    ).to_parquet(path, index=False)
    monkeypatch.setattr(runner, "_verify_file", lambda *_: path)

    plan = runner._load_causal_active_plan({"inputs": {"active_contract_map": {}}})

    assert plan[["asset", "contract_id"]].to_dict("records") == [
        {"asset": "SI", "contract_id": "SI:H5"}
    ]


def test_ledger_rejects_protected_2026_targets() -> None:
    targets = _execution_targets()
    targets["entry_at"] = targets["entry_at"] + pd.DateOffset(years=1)

    with pytest.raises(ValueError, match="protected"):
        simulate_next_open_portfolio(_execution_panel(), targets)
