"""Testy corrected warmup, execution audit i fixed gates futures-v7."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import market_lab.futures_v7.evaluation as evaluation
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    run_futures_portfolio_ledger,
)
from market_lab.futures_v7.evaluation import (
    V7_DOUBLE_COST_SCENARIO,
    V7_PRIMARY_SCENARIO,
    V7ExecutionCoverageError,
    audit_v7_lagged_liquidity,
    build_v7_execution_failure_events,
    build_v7_score_metrics,
    evaluate_v7_gates,
    fixed_v7_scenarios,
    run_v7_scenarios,
)


def _market(*, warmup_volume: float = 10_000.0, include_warmup: bool = True) -> pd.DataFrame:
    """Stroit odnoaktivnyi factual market s predshestvuyushchei liquidity sessiei."""
    dates = list(pd.bdate_range("2021-01-04", periods=4))
    if include_warmup:
        dates.insert(0, pd.Timestamp("2020-12-31"))
    rows: list[dict[str, object]] = []
    for index, session_date in enumerate(dates):
        price = 100.0 + index
        volume = warmup_volume if session_date == pd.Timestamp("2020-12-31") else 10_000.0
        rows.append(
            {
                "session_date": session_date,
                "asset_code": "SI",
                "contract_id": "SiH1",
                "open": price,
                "high": price + 2.0,
                "low": price - 1.0,
                "settle": price + 1.0,
                "volume": volume,
                "sizing_point_value": 10.0,
                "accounting_point_value": 10.0,
                "tick_size": 0.5,
                "fee_per_contract": 2.0,
                "initial_margin": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _targets() -> pd.DataFrame:
    """Stroit odin non-flat next-open target v nachale scored perioda."""
    return pd.DataFrame(
        [
            {
                "effective_date": "2021-01-04",
                "decision_date": "2020-12-31",
                "asset_code": "SI",
                "contract_id": "SiH1",
                "target_weight": 0.5,
            }
        ]
    )


def _passing_scenarios() -> pd.DataFrame:
    """Stroit prohodyashchuyu synthetic 12-scenario matricu."""
    rows: list[dict[str, object]] = []
    for scenario in fixed_v7_scenarios():
        rows.append(
            {
                "candidate_id": "causal_multiresolution_ensemble",
                "scenario_id": scenario.scenario_id,
                "cagr": 0.15 if scenario.scenario_id == V7_PRIMARY_SCENARIO else 0.03,
                "sharpe": 1.0,
                "maximum_drawdown": 0.10,
                "intraday_adverse_drawdown": 0.12,
                "execution_complete": True,
                "critical_execution_event_count": 0,
                "unresolved_halt_event_count": 0,
            }
        )
    return pd.DataFrame(rows)


def _passing_folds() -> pd.DataFrame:
    """Stroit chetyre polozhitel'nyh i odin dopustimyi otricatel'nyi fold."""
    return pd.DataFrame(
        [
            {
                "candidate_id": "causal_multiresolution_ensemble",
                "scenario_id": V7_PRIMARY_SCENARIO,
                "fold_year": year,
                "cagr": -0.05 if year == 2021 else 0.08,
            }
            for year in range(2021, 2026)
        ]
    )


def test_fixed_v7_scenarios_are_exact_cartesian_grid() -> None:
    """Proveryaet rovno dvenadcat' unikal'nyh execution stressov."""
    scenarios = fixed_v7_scenarios()
    assert len(scenarios) == 12
    assert len({scenario.scenario_id for scenario in scenarios}) == 12
    assert {scenario.atomicity for scenario in scenarios} == {"asset", "portfolio"}
    assert {scenario.slippage_ticks for scenario in scenarios} == {1, 2, 4}
    assert {scenario.fee_multiplier for scenario in scenarios} == {1.0, 2.0}


def test_warmup_contract_volume_covers_first_scored_target() -> None:
    """Dokazyvaet chto granica score ne sozdaet lozhnyi unknown lagged volume."""
    audit = audit_v7_lagged_liquidity(
        _market(),
        _targets(),
        score_start="2021-01-01",
        score_end="2021-01-31",
        expected_assets=("SI",),
    )
    assert audit.complete
    assert audit.warmup_session_count == 1
    assert audit.target_order_key_count == 1
    assert audit.covered_order_key_count == 1
    row = audit.coverage.iloc[0]
    assert row["liquidity_source_date"] == pd.Timestamp("2020-12-31")
    assert row["lagged_volume"] == pytest.approx(10_000.0)


def test_missing_real_lagged_liquidity_fails_before_any_pnl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zapreshchaet ledger run pri factual zero-volume source vmesto podstanovki."""
    called = False

    def _forbidden(*args: object, **kwargs: object) -> None:
        """Fiksiruet nedopustimyi vyzov ledger posle failed pre-audit."""
        nonlocal called
        called = True
        raise AssertionError("PnL ne dolzhen zapuskat'sya")

    monkeypatch.setattr(evaluation, "run_futures_portfolio_ledger", _forbidden)
    with pytest.raises(V7ExecutionCoverageError) as captured:
        run_v7_scenarios(
            _market(warmup_volume=0.0),
            _targets(),
            score_start="2021-01-01",
            score_end="2021-01-31",
            initial_cash=10_000.0,
            expected_assets=("SI",),
            fold_years=(2021,),
            purge_sessions=0,
        )
    assert not called
    assert captured.value.audit.failures["reason"].tolist() == [
        "nonpositive_or_unknown_lagged_volume"
    ]


def test_score_metrics_exclude_warmup_growth_without_losing_previous_cash() -> None:
    """Schitaet tolko dve scored returns posle bol'shogo warmup skachka."""
    ledger = pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2020-12-31", "2021-01-04", "2021-01-05"]),
            "starting_cash": [1_000_000.0, 2_000_000.0, 2_020_000.0],
            "ending_cash": [2_000_000.0, 2_020_000.0, 2_040_200.0],
            "intraday_adverse_equity": [2_000_000.0, 2_020_000.0, 2_040_200.0],
        }
    )
    metrics, scored = build_v7_score_metrics(
        ledger,
        1_000_000.0,
        score_start="2021-01-01",
        score_end="2021-12-31",
    )
    assert metrics["warmup_session_count"] == 1
    assert metrics["starting_cash"] == pytest.approx(2_000_000.0)
    assert metrics["total_return"] == pytest.approx(1.01**2 - 1.0)
    assert scored["daily_return"].to_numpy() == pytest.approx([0.01, 0.01])


def test_all_scenarios_share_one_continuous_position_path() -> None:
    """Proveryaet warmup entry coverage i otsutstvie fold reset v resultate."""
    scenarios, folds, results = run_v7_scenarios(
        _market(),
        _targets(),
        score_start="2021-01-01",
        score_end="2021-01-31",
        initial_cash=10_000.0,
        expected_assets=("SI",),
        fold_years=(2021,),
        purge_sessions=0,
    )
    assert len(scenarios) == 12
    assert len(folds) == 12
    assert scenarios["execution_complete"].astype(bool).all()
    primary = results[V7_PRIMARY_SCENARIO]
    positions = primary.raw.positions.set_index(["session_date", "asset_code"])
    assert positions.loc[(pd.Timestamp("2020-12-31"), "SI"), "contracts"] == 0
    assert positions.loc[(pd.Timestamp("2021-01-04"), "SI"), "contracts"] > 0
    assert positions.loc[(pd.Timestamp("2021-01-07"), "SI"), "contracts"] > 0
    assert primary.metrics["warmup_session_count"] == 1
    assert primary.metrics["positions_reset_between_folds"] is False


def test_unique_failure_event_does_not_double_count_category_and_atomic_rejection() -> None:
    """Szhimaet unknown liquidity plus atomic counter v odno logical sobytie."""
    market = _market(include_warmup=False)
    raw = run_futures_portfolio_ledger(
        market,
        _targets(),
        FuturesPortfolioLedgerConfig(
            initial_cash=10_000.0,
            expected_assets=("SI",),
            execution_atomicity="asset",
        ),
    )
    assert raw.metrics["unknown_liquidity_count"] == 1
    assert raw.metrics["atomic_rejection_count"] == 1
    assert raw.metrics["critical_failure_count"] == 2
    events = build_v7_execution_failure_events(raw, fixed_v7_scenarios()[0])
    critical = events.loc[events["event_type"].eq("critical_execution")]
    assert len(critical) == 1
    assert critical["event_id"].is_unique
    assert "unknown_lagged_volume" in critical.iloc[0]["reason_tokens"]


def test_fixed_gates_pass_but_fifty_percent_remains_report_only() -> None:
    """Proveryaet fiksirovannye porogi i otdel'nyi stretch flag."""
    decision = evaluate_v7_gates(_passing_scenarios(), _passing_folds())
    assert decision.passed
    assert not decision.stretch_50_reached
    assert all(decision.checks.values())
    assert decision.observed["stretch_target_cagr"] == pytest.approx(0.50)


def test_one_unique_execution_failure_forces_no_go() -> None:
    """Zapreshchaet prohod gates pri odnom unique event v lyubom stresse."""
    scenarios = _passing_scenarios()
    broken = scenarios["scenario_id"].eq(V7_DOUBLE_COST_SCENARIO)
    scenarios.loc[broken, "critical_execution_event_count"] = 1
    scenarios.loc[broken, "execution_complete"] = False
    decision = evaluate_v7_gates(scenarios, _passing_folds())
    assert not decision.passed
    assert not decision.checks["zero_critical_execution_events"]
    assert not decision.checks["all_execution_complete"]


def test_missing_scenario_or_fold_forces_no_go() -> None:
    """Trebuet polnye 12 stressov i vse pyat' OOS folds bez survivorship."""
    missing_scenario = evaluate_v7_gates(_passing_scenarios().iloc[:-1], _passing_folds())
    assert not missing_scenario.passed
    assert not missing_scenario.checks["complete_execution_scenario_grid"]

    missing_fold = evaluate_v7_gates(_passing_scenarios(), _passing_folds().iloc[:-1])
    assert not missing_fold.passed
    assert not missing_fold.checks["complete_fold_set"]


def test_score_return_product_matches_explicit_numpy_calculation() -> None:
    """Proveryaet chislovuyu deterministichnost score-only compounded return."""
    returns = np.array([0.01, -0.02, 0.03], dtype=float)
    endings = 1_000_000.0 * np.cumprod(1.0 + returns)
    starts = np.r_[1_000_000.0, endings[:-1]]
    ledger = pd.DataFrame(
        {
            "session_date": pd.bdate_range("2021-01-04", periods=3),
            "starting_cash": starts,
            "ending_cash": endings,
            "intraday_adverse_equity": endings,
        }
    )
    metrics, _ = build_v7_score_metrics(
        ledger,
        1_000_000.0,
        score_start="2021-01-01",
        score_end="2021-12-31",
    )
    assert metrics["total_return"] == pytest.approx(np.prod(1.0 + returns) - 1.0)
