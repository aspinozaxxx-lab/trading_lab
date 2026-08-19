"""Testy zapechatannoi futures-v6 metriki i selection bez real'nyh cen."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.v6_evaluation import (
    V6_CANDIDATES,
    V6_FOLD_YEARS,
    V6_PRIMARY_SCENARIO,
    V6_SELECTION_SCENARIO,
    build_v6_fold_metrics,
    evaluate_v6_gates,
    fixed_v6_scenarios,
    select_v6_candidate,
)


def _constant_growth_ledger() -> pd.DataFrame:
    """Stroit synthetic continuous cash curve po semi sessiyam kazhdogo goda."""
    dates: list[pd.Timestamp] = []
    for year in V6_FOLD_YEARS:
        dates.extend(pd.bdate_range(f"{year}-01-04", periods=7).tolist())
    cash = 1_000_000.0 * np.cumprod(np.full(len(dates), 1.01))
    return pd.DataFrame(
        {
            "session_date": dates,
            "ending_cash": cash,
            "intraday_adverse_equity": cash,
        }
    )


def _passing_scenario_metrics() -> pd.DataFrame:
    """Stroit polnuyu 4x12 tablicu s prohodyashchimi aggregate metrikami."""
    rows: list[dict[str, object]] = []
    for candidate in V6_CANDIDATES:
        for scenario in fixed_v6_scenarios():
            cagr = 0.16 if scenario.scenario_id == V6_PRIMARY_SCENARIO else 0.05
            if scenario.scenario_id == V6_SELECTION_SCENARIO:
                cagr = 0.03
            rows.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario.scenario_id,
                    "cagr": cagr,
                    "sharpe": 1.1,
                    "maximum_drawdown": 0.12,
                    "intraday_adverse_drawdown": 0.14,
                    "critical_failure_count": 0,
                    "unresolved_halt_count": 0,
                    "execution_complete": True,
                }
            )
    return pd.DataFrame(rows)


def _passing_fold_metrics() -> pd.DataFrame:
    """Stroit pyat' folds na candidate i primary/selection scenarii."""
    rows: list[dict[str, object]] = []
    for candidate_index, candidate in enumerate(V6_CANDIDATES):
        for scenario_id in (V6_PRIMARY_SCENARIO, V6_SELECTION_SCENARIO):
            for fold_index, year in enumerate(V6_FOLD_YEARS):
                cagr = -0.05 if fold_index == 0 else 0.10
                sharpe = 0.9 - 0.1 * candidate_index
                rows.append(
                    {
                        "candidate_id": candidate,
                        "scenario_id": scenario_id,
                        "fold_year": year,
                        "cagr": cagr,
                        "sharpe": sharpe,
                    }
                )
    return pd.DataFrame(rows)


def test_fixed_scenarios_cover_exact_cartesian_grid() -> None:
    """Proveryaet 12 unikal'nyh stressov i immutable selection id."""
    scenarios = fixed_v6_scenarios()
    assert len(scenarios) == 12
    assert len({scenario.scenario_id for scenario in scenarios}) == 12
    assert V6_PRIMARY_SCENARIO in {scenario.scenario_id for scenario in scenarios}
    assert V6_SELECTION_SCENARIO in {scenario.scenario_id for scenario in scenarios}


def test_fold_metrics_purge_first_five_sessions_and_annualize() -> None:
    """Proveryaet granicy purge i annualizaciyu tolko scored returns."""
    metrics = build_v6_fold_metrics(_constant_growth_ledger(), 1_000_000.0)
    assert metrics["fold_year"].tolist() == list(V6_FOLD_YEARS)
    assert metrics["session_count"].eq(2).all()
    expected_starts = (
        _constant_growth_ledger()
        .assign(fold_year=lambda frame: frame["session_date"].dt.year)
        .groupby("fold_year")["session_date"]
        .nth(5)
        .dt.date.astype(str)
        .tolist()
    )
    assert metrics["score_start"].tolist() == expected_starts
    assert metrics["total_return"].to_numpy() == pytest.approx(np.full(5, 1.01**2 - 1.0))
    assert metrics["cagr"].to_numpy() == pytest.approx(np.full(5, 1.01**252 - 1.0))


def test_selection_uses_only_stress_fold_metrics_and_stable_tie_break() -> None:
    """Dokazyvaet chto primary ili aggregate result ne mozhet pomenyat' selection."""
    folds = _passing_fold_metrics()
    folds.loc[
        folds["candidate_id"].eq("macro_overlay")
        & folds["scenario_id"].eq(V6_SELECTION_SCENARIO),
        "sharpe",
    ] = 2.0
    folds.loc[
        folds["candidate_id"].eq("base_moe")
        & folds["scenario_id"].eq(V6_PRIMARY_SCENARIO),
        "sharpe",
    ] = 99.0
    selected, ranking = select_v6_candidate(folds)
    assert selected == "macro_overlay"
    assert ranking.iloc[0]["candidate_id"] == "macro_overlay"


def test_gates_pass_without_claiming_fifty_percent_stretch() -> None:
    """Proveryaet razdelenie minimal'nogo GO i ambicioznoi stretch-celi."""
    decision = evaluate_v6_gates(
        "base_moe",
        _passing_scenario_metrics(),
        _passing_fold_metrics(),
    )
    assert decision.passed
    assert not decision.stretch_50_reached
    assert all(decision.checks.values())


def test_any_incomplete_execution_scenario_forces_no_go() -> None:
    """Zapreshchaet skryt' neispolnimost' nevybrannogo kandidata ili stressa."""
    scenarios = _passing_scenario_metrics()
    scenarios.loc[
        scenarios["candidate_id"].eq("macro_confirmation")
        & scenarios["scenario_id"].eq("portfolio_s4_f2"),
        "execution_complete",
    ] = False
    decision = evaluate_v6_gates("base_moe", scenarios, _passing_fold_metrics())
    assert not decision.passed
    assert not decision.checks["all_execution_complete"]


def test_missing_candidate_scenario_pair_forces_no_go() -> None:
    """Trebuet reporta vsego sealed Cartesian nabora bez survivorship."""
    scenarios = _passing_scenario_metrics().iloc[:-1].copy()
    decision = evaluate_v6_gates("base_moe", scenarios, _passing_fold_metrics())
    assert not decision.passed
    assert not decision.checks["complete_candidate_scenario_matrix"]


def test_ruined_continuous_path_is_reported_instead_of_crashing() -> None:
    """Prevrashchaet nol' kapitala v konechnyi fail-score dlya vseh sleduyushchih folds."""
    ledger = _constant_growth_ledger()
    ruin_index = ledger.index[ledger["session_date"].dt.year.eq(2023)][5]
    ledger.loc[ruin_index:, "ending_cash"] = 0.0
    ledger.loc[ruin_index:, "intraday_adverse_equity"] = 0.0
    metrics = build_v6_fold_metrics(ledger, 1_000_000.0)
    safe = metrics.loc[metrics["fold_year"].lt(2023)]
    ruined = metrics.loc[metrics["fold_year"].ge(2023)]
    assert not safe["ruined"].astype(bool).any()
    assert ruined["ruined"].astype(bool).all()
    assert ruined["cagr"].eq(-1.0).all()


def test_explicit_critical_counter_cannot_be_hidden_by_complete_flag() -> None:
    """Proveryaet nezavisimyi zero-gate po critical execution counters."""
    scenarios = _passing_scenario_metrics()
    scenarios.loc[0, "critical_failure_count"] = 1
    decision = evaluate_v6_gates("base_moe", scenarios, _passing_fold_metrics())
    assert not decision.passed
    assert not decision.checks["maximum_critical_execution_events"]
