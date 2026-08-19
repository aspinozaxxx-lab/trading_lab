"""Regression-testy fakticheskogo position state causal'nogo futures-rolla."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import (
    RollPlannerConfig,
    build_causal_forward_adjusted_series,
    plan_causal_rolls,
)


def _contract_row(
    trading_date: str,
    secid: str,
    expiration: str,
    volume: float,
    open_interest: float,
    settle: float,
    asset_code: str = "Si",
) -> dict[str, object]:
    """Stroit odno dnevnoe nablyudenie kontrakta dlya regression-testov."""
    return {
        "trade_date": trading_date,
        "asset_code": asset_code,
        "secid": secid,
        "expiration_date": expiration,
        "volume": volume,
        "open_interest": open_interest,
        "settle": settle,
        "open": settle,
    }


def _missing_overlap_panel() -> pd.DataFrame:
    """Stroit panel s propushchennym settle novogo kontrakta v tochke rolla."""
    dates = pd.date_range("2024-03-11", periods=6, freq="B")
    rows: list[dict[str, object]] = []
    for index, trading_date in enumerate(dates):
        day = trading_date.strftime("%Y-%m-%d")
        rows.append(
            _contract_row(
                day,
                "SiH4",
                "2024-03-21",
                [100, 100, 80, 60, 40, 20][index],
                [1000, 1000, 800, 600, 400, 200][index],
                100.0 + index,
            )
        )
        rows.append(
            _contract_row(
                day,
                "SiM4",
                "2024-06-20",
                [10, 20, 90, 100, 120, 130][index],
                [100, 200, 900, 1000, 1200, 1300][index],
                np.nan if index == 3 else 110.0 + index,
            )
        )
    return pd.DataFrame(rows)


def test_roll_planner_rejects_mixed_assets() -> None:
    """Proveryaet hard-error vmesto skrytogo smesheniya dvuh bazovyh aktivov."""
    panel = pd.DataFrame(
        [
            _contract_row("2024-01-02", "SiH4", "2024-03-21", 10, 100, 90),
            _contract_row(
                "2024-01-02",
                "RIH4",
                "2024-03-21",
                10,
                100,
                110000,
                asset_code="RTS",
            ),
        ]
    )
    with pytest.raises(ValueError, match="odin asset_code"):
        plan_causal_rolls(panel)


def test_missing_overlap_forces_flat_then_explicit_reentry() -> None:
    """Proveryaet flat boundary i zapret phantom hold posle neudachnogo rolla."""
    plan = plan_causal_rolls(_missing_overlap_panel())
    skipped = plan.loc[plan["reason"] == "missing_roll_overlap"].iloc[0]
    assert skipped["effective_date"] == pd.Timestamp("2024-03-15")
    assert skipped["action"] == "flat_skip"
    assert not bool(skipped["tradable"])
    assert pd.isna(skipped["position_contract_id"])
    following = plan.loc[plan["effective_date"] > skipped["effective_date"]].iloc[0]
    assert following["action"] == "enter"
    assert bool(following["tradable"])
    assert following["position_contract_id"] == following["requested_contract_id"]
    assert "SiM4" in str(following["secid"])


def test_hard_fallback_without_next_never_reopens_retiring_contract() -> None:
    """Proveryaet, chto vyvedennyi front ne stanovitsya novym enter na sleduyushchii den'."""
    dates = pd.date_range("2024-01-08", periods=5, freq="B")
    panel = pd.DataFrame(
        [
            _contract_row(
                value.strftime("%Y-%m-%d"),
                "SiF4",
                "2024-01-12",
                100,
                1000,
                90.0 + index,
            )
            for index, value in enumerate(dates)
        ]
    )
    plan = plan_causal_rolls(
        panel,
        RollPlannerConfig(hard_fallback_sessions=3),
        session_calendar=dates,
    )
    forced = plan.loc[plan["reason"] == "hard_fallback_without_next_contract"]
    assert len(forced) == 1
    after = plan.loc[plan["effective_date"] >= forced.iloc[0]["effective_date"]]
    assert (~after["tradable"]).all()
    assert not (after["action"] == "enter").any()
    assert after["position_contract_id"].isna().all()


def test_invalid_effective_settle_requires_new_enter_decision() -> None:
    """Proveryaet, chto net validnogo enter/hold bez fakticheskoi execution ceny."""
    panel = pd.DataFrame(
        [
            _contract_row("2024-02-01", "SiH4", "2024-03-21", 100, 1000, 90.0),
            _contract_row("2024-02-02", "SiH4", "2024-03-21", 100, 1000, np.nan),
            _contract_row("2024-02-05", "SiH4", "2024-03-21", 100, 1000, 92.0),
            _contract_row("2024-02-06", "SiH4", "2024-03-21", 100, 1000, 93.0),
        ]
    )
    plan = plan_causal_rolls(panel)
    failed = plan.loc[plan["effective_date"] == pd.Timestamp("2024-02-02")].iloc[0]
    assert failed["action"] == "flat_skip"
    assert failed["reason"] == "missing_effective_price"
    assert not bool(failed["tradable"])
    recovered = plan.loc[plan["effective_date"] == pd.Timestamp("2024-02-05")].iloc[0]
    assert recovered["action"] == "enter"
    assert recovered["execution_price"] == 92.0
    assert bool(recovered["tradable"])


def test_hard_fallback_counts_explicit_sessions_instead_of_calendar_days() -> None:
    """Proveryaet session-based fallback na kalendare s dlinnoi prazdnichnoi pauzoi."""
    calendar = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-08", "2024-01-09"])
    panel = pd.DataFrame(
        [
            _contract_row("2024-01-02", "SiF4", "2024-01-09", 100, 1000, 90.0),
            _contract_row("2024-01-03", "SiF4", "2024-01-09", 100, 1000, 91.0),
            _contract_row("2024-01-08", "SiF4", "2024-01-09", 100, 1000, 92.0),
            _contract_row("2024-01-09", "SiF4", "2024-01-09", 100, 1000, 93.0),
        ]
    )
    plan = plan_causal_rolls(
        panel,
        RollPlannerConfig(hard_fallback_sessions=2),
        session_calendar=calendar,
    )
    forced = plan.loc[plan["reason"] == "hard_fallback_without_next_contract"].iloc[0]
    assert forced["decision_date"] == pd.Timestamp("2024-01-03")
    assert forced["effective_date"] == pd.Timestamp("2024-01-08")
    changed = panel.copy()
    changed.loc[changed["trade_date"] > "2024-01-03", "settle"] = np.nan
    revised = plan_causal_rolls(
        changed,
        RollPlannerConfig(hard_fallback_sessions=2),
        session_calendar=calendar,
    )
    revised_forced = revised.loc[
        revised["reason"] == "hard_fallback_without_next_contract"
    ].iloc[0]
    assert revised_forced["decision_date"] == forced["decision_date"]
    assert revised_forced["effective_date"] == forced["effective_date"]


def test_legacy_hard_fallback_days_maps_to_session_count() -> None:
    """Proveryaet obratnuyu sovmestimost' imeni bez vozvrata k calendar'nym dnyam."""
    settings = RollPlannerConfig(hard_fallback_days=7)
    assert settings.hard_fallback_sessions == 7


def test_explicit_calendar_rejects_missing_observed_session() -> None:
    """Proveryaet fail-closed vmesto perenosa ordera cherez propushchennuyu sessiyu."""
    calendar = pd.to_datetime(["2024-02-01", "2024-02-02", "2024-02-05"])
    panel = pd.DataFrame(
        [
            _contract_row("2024-02-01", "SiH4", "2024-03-21", 100, 1000, 90.0),
            _contract_row("2024-02-05", "SiH4", "2024-03-21", 100, 1000, 92.0),
        ]
    )
    with pytest.raises(ValueError, match="session_calendar"):
        plan_causal_rolls(panel, session_calendar=calendar)


def test_appending_future_sessions_does_not_rewrite_existing_plan() -> None:
    """Proveryaet append-only invariant dlya uzhe ispolnennyh effective sessions."""
    full = _missing_overlap_panel()
    cutoff = pd.Timestamp("2024-03-15")
    prefix = full.loc[pd.to_datetime(full["trade_date"]) <= cutoff].copy()
    prefix_plan = plan_causal_rolls(prefix)
    full_plan = plan_causal_rolls(full)
    columns = [
        "effective_date",
        "decision_date",
        "requested_contract_id",
        "position_contract_id",
        "action",
        "reason",
        "tradable",
    ]
    pd.testing.assert_frame_equal(
        prefix_plan[columns].reset_index(drop=True),
        full_plan.loc[full_plan["effective_date"] <= cutoff, columns].reset_index(drop=True),
    )


def test_roll_requires_both_old_exit_and_new_entry_open() -> None:
    """Proveryaet, chto otsutstvie staroi nogi ne sozdaet fiktivnyi roll."""
    panel = _missing_overlap_panel()
    panel.loc[
        (pd.to_datetime(panel["trade_date"]) == pd.Timestamp("2024-03-14"))
        & (panel["secid"] == "SiM4"),
        "settle",
    ] = 113.0
    panel.loc[
        (pd.to_datetime(panel["trade_date"]) == pd.Timestamp("2024-03-15"))
        & (panel["secid"] == "SiH4"),
        "open",
    ] = np.nan
    plan = plan_causal_rolls(panel)
    failed = plan.loc[plan["effective_date"] == pd.Timestamp("2024-03-15")].iloc[0]
    assert failed["action"] == "carry_unfilled_roll"
    assert failed["reason"] == "missing_roll_execution_leg"
    assert "SiH4" in str(failed["position_contract_id"])
    assert pd.isna(failed["exit_execution_price"])
    assert failed["entry_execution_price"] == 114.0
    assert not bool(failed["tradable"])
    with pytest.raises(ValueError, match="carry-poziciyu"):
        build_causal_forward_adjusted_series(panel, plan)


def test_future_expiry_is_horizon_censored_but_current_open_roll_is_allowed() -> None:
    """Proveryaet roll v dal'nii kontrakt bez cen i session calendar sleduyushchego goda."""
    calendar = pd.to_datetime(
        [
            "2025-12-10",
            "2025-12-11",
            "2025-12-12",
            "2025-12-15",
            "2025-12-16",
            "2025-12-17",
            "2025-12-18",
            "2025-12-19",
        ]
    )
    rows: list[dict[str, object]] = []
    for index, trading_date in enumerate(calendar):
        day = trading_date.strftime("%Y-%m-%d")
        rows.append(
            _contract_row(day, "SiZ5", "2025-12-18", 1_000, 10_000, 80_000 + index)
        )
        rows.append(
            _contract_row(day, "SiH6", "2026-03-19", 100, 1_000, 81_000 + index)
        )
    plan = plan_causal_rolls(
        pd.DataFrame(rows),
        RollPlannerConfig(hard_fallback_sessions=3),
        session_calendar=calendar,
    )
    rolled = plan.loc[plan["action"] == "roll"]
    assert len(rolled) == 1
    assert rolled.iloc[0]["effective_date"] == pd.Timestamp("2025-12-16")
    assert "SiH6" in str(rolled.iloc[0]["position_contract_id"])
    assert rolled.iloc[0]["entry_execution_price"] == 81_004.0
    held = plan.loc[plan["reason"] == "front_retained_horizon_censored"]
    assert not held.empty
    assert held["expiry_horizon_censored"].all()
    assert held["tradable"].all()
    assert not plan["action"].astype(str).str.startswith("carry_").any()
    assert (plan["effective_date"] < pd.Timestamp("2026-01-01")).all()
