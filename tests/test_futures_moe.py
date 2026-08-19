"""Testy causal'noi daily futures mixture-of-experts bez seti."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.moe import (
    EXPERT_NAMES,
    CausalDailyMixtureOfExperts,
    CausalMoEConfig,
    build_causal_moe_targets,
)


def _causal_panel(periods: int = 150) -> pd.DataFrame:
    """Stroit chetyre raznyh, no polnost'yu determinirovannyh futures-ryada."""
    dates = pd.bdate_range("2023-01-02", periods=periods)
    settings = {
        "SI": (70_000.0, 0.00010, 0.0018),
        "RI": (95_000.0, 0.00035, 0.0027),
        "BR": (75.0, 0.00020, 0.0021),
        "MIX": (3_200.0, 0.00030, 0.0024),
    }
    rows: list[dict[str, object]] = []
    for asset_index, (asset_code, values) in enumerate(settings.items()):
        start, drift, amplitude = values
        close = start
        previous_close = start
        for index, trade_date in enumerate(dates):
            cycle = amplitude * np.sin((index + 3 * asset_index) / 7.0)
            shock = 0.0035 * np.cos((index + 5 * asset_index) / 19.0)
            return_value = drift + cycle + shock
            close *= 1.0 + return_value
            open_price = previous_close * (1.0 + 0.0004 * np.sin(index / 5.0))
            high = max(open_price, close) * 1.004
            low = min(open_price, close) * 0.996
            physical_long = 1_000.0 + 3.0 * index + 25.0 * np.sin(index / 8.0)
            physical_short = 950.0 + 2.0 * index - 20.0 * np.sin(index / 8.0)
            legal_long = 1_400.0 + 2.5 * index - 30.0 * np.sin(index / 9.0)
            legal_short = 1_300.0 + 2.0 * index + 22.0 * np.sin(index / 9.0)
            rows.append(
                {
                    "trade_date": trade_date,
                    "asset_code": asset_code,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 20_000.0 + 60.0 * index + 500.0 * np.sin(index / 6.0),
                    "open_interest": 100_000.0
                    + 100.0 * index
                    + 1_000.0 * np.cos(index / 11.0),
                    "roll_yield": 0.025 * np.sin(index / 17.0 + asset_index),
                    "physical_long": physical_long,
                    "physical_short": physical_short,
                    "legal_long": legal_long,
                    "legal_short": legal_short,
                }
            )
            previous_close = close
    return pd.DataFrame(rows)


def _sort_output(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet rezultat odinakovo dlya strogogo sravneniya batch-zapuskov."""
    return frame.sort_values(["trade_date", "asset_code"]).reset_index(drop=True)


def _prelagged_participant_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Prevrashchaet raw participant snapshot v exact previous-common-session panel'."""
    frame = panel.sort_values(["trade_date", "asset_code"]).reset_index(drop=True).copy()
    participant_columns = [
        "physical_long",
        "physical_short",
        "legal_long",
        "legal_short",
    ]
    frame[participant_columns] = frame.groupby("asset_code", sort=False)[
        participant_columns
    ].shift(1)
    dates = pd.DatetimeIndex(frame["trade_date"].drop_duplicates().sort_values())
    previous_by_date = {
        pd.Timestamp(dates[index]): pd.Timestamp(dates[index - 1])
        for index in range(1, len(dates))
    }
    frame["participant_source_date"] = frame["trade_date"].map(previous_by_date)
    available = frame["participant_source_date"].notna()
    frame["participant_lag_sessions"] = np.where(available, 1.0, np.nan)
    frame["participant_snapshot_complete"] = available
    return frame


def test_moe_emits_eight_experts_common_gate_and_next_session_targets() -> None:
    """Proveryaet polnyi nabor ekspertov, normirovku gate i portfolio targeta."""
    result = build_causal_moe_targets(_causal_panel())
    assert {f"expert_{name}" for name in EXPERT_NAMES} <= set(result.columns)
    assert {f"weight_{name}" for name in EXPERT_NAMES} <= set(result.columns)
    assert (result["target_session_offset"] == 1).all()
    valid = result.loc[result["signal_valid"]]
    assert not valid.empty
    assert valid["target_score"].between(-1.0, 1.0).all()
    latest = valid["trade_date"].max()
    day = valid.loc[valid["trade_date"] == latest]
    np.testing.assert_allclose(day["target_weight"].abs().sum(), 1.0)
    np.testing.assert_allclose(
        day[[f"weight_{name}" for name in EXPERT_NAMES]].sum(axis=1),
        1.0,
    )
    assert all(day[f"weight_{name}"].nunique() == 1 for name in EXPERT_NAMES)
    assert day[[f"weight_{name}" for name in EXPERT_NAMES]].std(axis=1).max() > 0.0


def test_future_mutation_cannot_change_scores_or_gate_before_cutoff() -> None:
    """Proveryaet, chto ceny i OI budushchego ne perepisyvayut proshlye resheniya."""
    panel = _causal_panel()
    dates = sorted(panel["trade_date"].unique())
    cutoff = pd.Timestamp(dates[110])
    baseline = build_causal_moe_targets(panel)
    changed = panel.copy()
    future = changed["trade_date"] > cutoff
    changed.loc[future, ["open", "high", "low", "close"]] *= 1.17
    changed.loc[future, ["volume", "open_interest"]] *= 3.0
    changed.loc[future, "roll_yield"] *= -5.0
    revised = build_causal_moe_targets(changed)
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"] <= cutoff].reset_index(drop=True),
        revised.loc[revised["trade_date"] <= cutoff].reset_index(drop=True),
    )


def test_gate_feedback_matches_two_lag_factual_open_to_open_interval() -> None:
    """Proveryaet signal D-2 -> open D-1 -> open D bez close-target podmeny."""
    panel = _causal_panel()
    dates = [pd.Timestamp(value) for value in sorted(panel["trade_date"].unique())]
    decision_index = 110
    current_date = dates[decision_index]
    signal_date = dates[decision_index - 2]
    entry_date = dates[decision_index - 1]
    config = CausalMoEConfig(risk_threshold=100.0, crisis_threshold=100.0)
    baseline = build_causal_moe_targets(panel, config)
    close_changed = panel.copy()
    current_si = (close_changed["trade_date"] == current_date) & close_changed[
        "asset_code"
    ].eq("SI")
    old_close = float(close_changed.loc[current_si, "close"].iloc[0])
    open_price = float(close_changed.loc[current_si, "open"].iloc[0])
    close_changed.loc[current_si, "close"] = (old_close + open_price) / 2.0
    close_result = build_causal_moe_targets(close_changed, config)
    loss_columns = [f"realized_loss_{name}" for name in EXPERT_NAMES]
    weight_columns = [f"weight_{name}" for name in EXPERT_NAMES]
    baseline_day = baseline.loc[baseline["trade_date"] == current_date].reset_index(drop=True)
    close_day = close_result.loc[
        close_result["trade_date"] == current_date
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(baseline_day[loss_columns], close_day[loss_columns])
    pd.testing.assert_frame_equal(baseline_day[weight_columns], close_day[weight_columns])
    assert (baseline_day["feedback_signal_date"] == signal_date).all()
    assert (baseline_day["feedback_entry_date"] == entry_date).all()
    assert (baseline_day["feedback_exit_date"] == current_date).all()
    assert (baseline_day["feedback_holding_interval"] == "open_to_open").all()
    delayed_date = dates[decision_index + 2]
    delayed_base = baseline.loc[baseline["trade_date"] == delayed_date, loss_columns]
    delayed_close = close_result.loc[
        close_result["trade_date"] == delayed_date,
        loss_columns,
    ]
    assert not np.allclose(delayed_base, delayed_close, equal_nan=True)
    open_changed = panel.copy()
    previous_open = float(
        open_changed.loc[
            (open_changed["trade_date"] == entry_date)
            & open_changed["asset_code"].eq("SI"),
            "open",
        ].iloc[0]
    )
    baseline_open = float(open_changed.loc[current_si, "open"].iloc[0])
    changed_open = previous_open * (0.95 if baseline_open >= previous_open else 1.05)
    open_changed.loc[current_si, "open"] = changed_open
    open_changed.loc[current_si, "high"] = np.maximum(
        open_changed.loc[current_si, "high"],
        changed_open * 1.001,
    )
    open_changed.loc[current_si, "low"] = np.minimum(
        open_changed.loc[current_si, "low"],
        changed_open * 0.999,
    )
    open_result = build_causal_moe_targets(open_changed, config)
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"] < current_date].reset_index(drop=True),
        open_result.loc[open_result["trade_date"] < current_date].reset_index(drop=True),
    )
    open_day = open_result.loc[open_result["trade_date"] == current_date, loss_columns]
    assert not np.allclose(baseline_day[loss_columns], open_day, equal_nan=True)


def test_appending_new_sessions_is_byte_stable_for_existing_output() -> None:
    """Proveryaet append-only invariant bez poiska target_date v budushchem."""
    panel = _causal_panel()
    dates = sorted(panel["trade_date"].unique())
    cutoff = pd.Timestamp(dates[119])
    prefix = panel.loc[panel["trade_date"] <= cutoff].copy()
    prefix_result = build_causal_moe_targets(prefix)
    full_result = build_causal_moe_targets(panel)
    pd.testing.assert_frame_equal(
        prefix_result,
        full_result.loc[full_result["trade_date"] <= cutoff].reset_index(drop=True),
    )


def test_moe_is_deterministic_and_independent_of_input_row_order() -> None:
    """Proveryaet chistyi batch-raschet bez RNG i skrytogo fitted sostoyaniya."""
    panel = _causal_panel()
    model = CausalDailyMixtureOfExperts()
    first = model.predict(panel)
    second = model.predict(panel.sample(frac=1.0, random_state=42))
    pd.testing.assert_frame_equal(_sort_output(first), _sort_output(second))


def test_missing_schema_or_feature_value_fails_closed() -> None:
    """Proveryaet yavnyi otkaz skhemy i nulevoi target pri lokal'nom propuske."""
    panel = _causal_panel()
    with pytest.raises(ValueError, match="roll_yield"):
        build_causal_moe_targets(panel.drop(columns="roll_yield"))
    damaged = panel.copy()
    dates = sorted(damaged["trade_date"].unique())
    missing_date = pd.Timestamp(dates[100])
    missing = (damaged["trade_date"] == missing_date) & damaged["asset_code"].eq("RI")
    damaged.loc[missing, "close"] = np.nan
    result = build_causal_moe_targets(damaged)
    row = result.loc[(result["trade_date"] == missing_date) & result["asset_code"].eq("RI")]
    assert len(row) == 1
    assert not bool(row.iloc[0]["signal_valid"])
    assert row.iloc[0]["target_score"] == 0.0
    assert row.iloc[0]["target_weight"] == 0.0


def test_participant_crowding_uses_a_full_session_lag() -> None:
    """Proveryaet, chto tekushchii participant snapshot ne vhodit v ego zhe signal."""
    panel = _causal_panel()
    dates = sorted(panel["trade_date"].unique())
    cutoff = pd.Timestamp(dates[105])
    next_date = pd.Timestamp(dates[106])
    baseline = build_causal_moe_targets(panel)
    changed = panel.copy()
    current = (changed["trade_date"] == cutoff) & changed["asset_code"].eq("SI")
    changed.loc[current, "physical_long"] *= 8.0
    changed.loc[current, "legal_short"] *= 8.0
    revised = build_causal_moe_targets(changed)
    key = ["trade_date", "asset_code"]
    baseline_indexed = baseline.set_index(key)
    revised_indexed = revised.set_index(key)
    column = "expert_participant_crowding"
    assert baseline_indexed.loc[(cutoff, "SI"), column] == revised_indexed.loc[
        (cutoff, "SI"), column
    ]
    assert baseline_indexed.loc[(next_date, "SI"), column] != revised_indexed.loc[
        (next_date, "SI"), column
    ]


def test_prelagged_participant_uses_exactly_one_total_session_lag() -> None:
    """Proveryaet ravenstvo legacy shift i dokazannogo pre-lag bez vtorogo sdviga."""
    raw = _causal_panel()
    prelagged = _prelagged_participant_panel(raw)
    raw_result = build_causal_moe_targets(raw)
    prelagged_result = build_causal_moe_targets(prelagged)
    column = "expert_participant_crowding"
    np.testing.assert_allclose(
        raw_result[column],
        prelagged_result[column],
        equal_nan=True,
    )
    assert raw_result["participant_timing_mode"].eq("raw_current_shift_one").all()
    assert prelagged_result["participant_timing_mode"].eq(
        "pre_lagged_exact_one"
    ).all()


def test_prelagged_timing_requires_exact_previous_common_session_and_proof() -> None:
    """Proveryaet hard-error dlya D-2 source, nepolnoi skhemy i lozhnoi dostupnosti."""
    panel = _prelagged_participant_panel(_causal_panel())
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    damaged = panel.copy()
    row = damaged["trade_date"].eq(dates[20]) & damaged["asset_code"].eq("SI")
    damaged.loc[row, "participant_source_date"] = dates[18]
    with pytest.raises(ValueError, match="predydushchei factual common session"):
        build_causal_moe_targets(damaged)
    with pytest.raises(ValueError, match="Nepolnoe participant timing proof"):
        build_causal_moe_targets(panel.drop(columns="participant_lag_sessions"))
    unavailable = panel.copy()
    unavailable.loc[row, "participant_snapshot_complete"] = False
    with pytest.raises(ValueError, match="availability proof"):
        build_causal_moe_targets(unavailable)


def test_prelagged_future_mutation_and_append_are_stable() -> None:
    """Proveryaet future-mutation i append-only invariant pre-lagged vetki."""
    panel = _prelagged_participant_panel(_causal_panel())
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    cutoff = pd.Timestamp(dates[119])
    baseline = build_causal_moe_targets(panel)
    changed = panel.copy()
    future = changed["trade_date"] > cutoff
    changed.loc[future, ["physical_long", "legal_short"]] *= 7.0
    revised = build_causal_moe_targets(changed)
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"] <= cutoff].reset_index(drop=True),
        revised.loc[revised["trade_date"] <= cutoff].reset_index(drop=True),
    )
    prefix = panel.loc[panel["trade_date"] <= cutoff].copy()
    prefix_result = build_causal_moe_targets(prefix)
    pd.testing.assert_frame_equal(
        prefix_result,
        baseline.loc[baseline["trade_date"] <= cutoff].reset_index(drop=True),
    )


def test_missing_cross_asset_row_flattens_whole_date() -> None:
    """Proveryaet fail-closed pri nepolnom risk-on/off snapshot chetyreh aktivov."""
    panel = _causal_panel()
    dates = sorted(panel["trade_date"].unique())
    damaged_date = pd.Timestamp(dates[120])
    damaged = panel.loc[
        ~((panel["trade_date"] == damaged_date) & panel["asset_code"].eq("BR"))
    ].copy()
    result = build_causal_moe_targets(damaged)
    day = result.loc[result["trade_date"] == damaged_date]
    assert not day["signal_valid"].any()
    assert (day[["target_score", "target_weight"]] == 0.0).all().all()
