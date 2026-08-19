"""Zamorozhennaya ocenka futures-v6 bez vybora porogov po rezultatu."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Final, Literal

import numpy as np
import pandas as pd

from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

V6_CANDIDATES: Final[tuple[str, ...]] = (  # Konechnyi spisok do development PnL.
    "base_moe",
    "macro_overlay",
    "macro_confirmation",
    "specialist_router",
)
V6_FOLD_YEARS: Final[tuple[int, ...]] = (  # Expanding OOS gody development-perioda.
    2021,
    2022,
    2023,
    2024,
    2025,
)
V6_PURGE_SESSIONS: Final[int] = 5  # Pervye sessii goda ne vhodyat v fold score.
V6_TRADING_SESSIONS: Final[int] = 252  # Fiksirovannaya annualizaciya fold returns.
V6_PRIMARY_SCENARIO: Final[str] = "asset_s1_f1"  # Bazovaya model' ispolneniya.
V6_SELECTION_SCENARIO: Final[str] = "asset_s2_f2"  # Stress dlya vybora kandidata.
V6_STRETCH_CAGR: Final[float] = 0.50  # Aspiracionnaya cel', ne objective i ne gate.
V6_GATE_AGGREGATE_CAGR: Final[float] = 0.12  # Minimal'nyi development CAGR.
V6_GATE_AGGREGATE_SHARPE: Final[float] = 0.80  # Minimal'nyi development Sharpe.
V6_GATE_MAXIMUM_DRAWDOWN: Final[float] = 0.25  # Predel close/intraday prosadki.
V6_GATE_POSITIVE_FOLDS: Final[int] = 4  # Minimal'noe chislo polozhitel'nyh let.
V6_GATE_WORST_FOLD_CAGR: Final[float] = -0.10  # Predel hudshego goda.
V6_GATE_STRESS_CAGR: Final[float] = 0.0  # Double-cost CAGR dolzhen byt' >= 0.
V6_METRIC_TOLERANCE: Final[float] = 1e-12  # Chislovoi dopusk proverok granic.
V6_RUIN_SHARPE: Final[float] = -1_000_000.0  # Konechnyi fail-score posle ruin.


@dataclass(frozen=True, slots=True)
class V6ScenarioSpec:
    """Fiksiruet odin execution stress bez skrytyh parametrov."""

    atomicity: Literal["asset", "portfolio"]
    slippage_ticks: Literal[1, 2, 4]
    fee_multiplier: Literal[1.0, 2.0]

    @property
    def scenario_id(self) -> str:
        """Vozvrashchaet stabil'nyi identifikator scenariya."""
        fee = int(self.fee_multiplier)
        return f"{self.atomicity}_s{self.slippage_ticks}_f{fee}"

    def ledger_config(self, initial_cash: float) -> FuturesPortfolioLedgerConfig:
        """Prevrashchaet sealed scenario v konfiguraciyu exact ledger."""
        return FuturesPortfolioLedgerConfig(
            initial_cash=initial_cash,
            slippage_ticks=self.slippage_ticks,
            fee_multiplier=self.fee_multiplier,
            execution_atomicity=self.atomicity,
        )


@dataclass(frozen=True, slots=True)
class V6GateDecision:
    """Hranit machine-readable rezultat vseh precommitted gates."""

    passed: bool
    stretch_50_reached: bool
    selected_candidate: str
    checks: Mapping[str, bool]
    observed: Mapping[str, float | int | bool | str]


def fixed_v6_scenarios() -> tuple[V6ScenarioSpec, ...]:
    """Stroit polnyi Cartesian nabor 2 atomicity x 3 slip x 2 fee."""
    return tuple(
        V6ScenarioSpec(atomicity=atomicity, slippage_ticks=slippage, fee_multiplier=fee)
        for atomicity in ("asset", "portfolio")
        for slippage in (1, 2, 4)
        for fee in (1.0, 2.0)
    )


def _normalize_ledger(ledger: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    """Proveryaet daily cash curve do rascheta fold returns."""
    required = {"session_date", "ending_cash", "intraday_adverse_equity"}
    if missing := required - set(ledger.columns):
        raise ValueError(f"Ledger ne soderzhit kolonok: {sorted(missing)}")
    if not np.isfinite(initial_cash) or initial_cash <= 0.0:
        raise ValueError("initial_cash dolzhen byt' konechnym i > 0")
    frame = ledger.loc[:, sorted(required)].copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise")
    if frame["session_date"].dt.tz is not None:
        frame["session_date"] = frame["session_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    frame["session_date"] = frame["session_date"].dt.normalize()
    if frame["session_date"].duplicated().any():
        raise ValueError("Ledger soderzhit povtornuyu session_date")
    frame = frame.sort_values("session_date", kind="mergesort").reset_index(drop=True)
    for column in ("ending_cash", "intraday_adverse_equity"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        if (~np.isfinite(frame[column])).any():
            raise ValueError(f"Ledger {column} dolzhen byt' konechnym")
    previous = frame["ending_cash"].shift(1, fill_value=float(initial_cash))
    valid_return = previous.gt(0.0) & frame["ending_cash"].gt(0.0)
    frame["daily_return"] = np.where(
        valid_return,
        frame["ending_cash"] / previous - 1.0,
        np.nan,
    )
    frame["ruined"] = (~valid_return) | frame["intraday_adverse_equity"].le(0.0)
    return frame


def _fold_statistics(frame: pd.DataFrame) -> dict[str, float | int]:
    """Schitaet fold metriki tolko po peredannym OOS sessiyam."""
    returns = frame["daily_return"].astype(float)
    session_count = len(returns)
    if session_count < 2:
        raise ValueError("Fold dolzhen soderzhat' minimum dve scored sessii")
    total_growth = float(np.prod(1.0 + returns.to_numpy(dtype=float)))
    total_return = total_growth - 1.0
    cagr = total_growth ** (V6_TRADING_SESSIONS / session_count) - 1.0
    deviation = float(returns.std(ddof=1))
    sharpe = (
        float(np.sqrt(V6_TRADING_SESSIONS) * returns.mean() / deviation)
        if deviation > V6_METRIC_TOLERANCE
        else 0.0
    )
    normalized_equity = np.r_[1.0, np.cumprod(1.0 + returns.to_numpy(dtype=float))]
    peaks = np.maximum.accumulate(normalized_equity)
    close_drawdown = float(np.max(1.0 - normalized_equity / peaks))
    first_previous_cash = float(frame.iloc[0]["ending_cash"] / (1.0 + returns.iloc[0]))
    absolute_peaks = np.maximum.accumulate(
        np.r_[first_previous_cash, frame["ending_cash"].to_numpy(dtype=float)]
    )[:-1]
    adverse_drawdown = float(
        np.max(
            1.0
            - frame["intraday_adverse_equity"].to_numpy(dtype=float)
            / np.maximum(absolute_peaks, V6_METRIC_TOLERANCE)
        )
    )
    return {
        "session_count": session_count,
        "ruined": False,
        "total_return": total_return,
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maximum_drawdown": max(0.0, close_drawdown, adverse_drawdown),
    }


def build_v6_fold_metrics(
    ledger: pd.DataFrame,
    initial_cash: float,
    *,
    fold_years: tuple[int, ...] = V6_FOLD_YEARS,
    purge_sessions: int = V6_PURGE_SESSIONS,
) -> pd.DataFrame:
    """Rezhit odin continuous deployment path na purged calendar-year folds."""
    if purge_sessions < 0:
        raise ValueError("purge_sessions ne mozhet byt' otricatel'nym")
    if not fold_years or len(set(fold_years)) != len(fold_years):
        raise ValueError("fold_years dolzhny byt' nepustymi i unikal'nymi")
    frame = _normalize_ledger(ledger, initial_cash)
    rows: list[dict[str, float | int | str]] = []
    for year in fold_years:
        annual = frame.loc[frame["session_date"].dt.year.eq(year)].reset_index(drop=True)
        if len(annual) <= purge_sessions + 1:
            raise ValueError(f"Fold {year} ne imeet dostatochno sessii posle purge")
        scored = annual.iloc[purge_sessions:].copy()
        ruined_before_end = bool(
            frame.loc[frame["session_date"].le(scored["session_date"].iloc[-1]), "ruined"].any()
        )
        if ruined_before_end:
            statistics: dict[str, float | int | bool] = {
                "session_count": len(scored),
                "ruined": True,
                "total_return": -1.0,
                "cagr": -1.0,
                "sharpe": V6_RUIN_SHARPE,
                "maximum_drawdown": 1.0,
            }
        else:
            statistics = _fold_statistics(scored)
        rows.append(
            {
                "fold_year": int(year),
                "purge_sessions": int(purge_sessions),
                "score_start": scored["session_date"].iloc[0].date().isoformat(),
                "score_end": scored["session_date"].iloc[-1].date().isoformat(),
                **statistics,
            }
        )
    return pd.DataFrame(rows)


def run_v6_scenarios(
    market: pd.DataFrame,
    targets_by_candidate: Mapping[str, pd.DataFrame],
    *,
    initial_cash: float = 1_000_000.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[tuple[str, str], FuturesPortfolioLedgerResult]]:
    """Vypolnyaet vse sealed candidates/scenarios po odnomu continuous puti."""
    if tuple(targets_by_candidate) != V6_CANDIDATES:
        raise ValueError("Poryadok i sostav v6 candidates dolzhen sovpadat' s seal")
    scenario_rows: list[dict[str, object]] = []
    fold_frames: list[pd.DataFrame] = []
    results: dict[tuple[str, str], FuturesPortfolioLedgerResult] = {}
    for candidate in V6_CANDIDATES:
        targets = targets_by_candidate[candidate]
        for scenario in fixed_v6_scenarios():
            result = run_futures_portfolio_ledger(
                market,
                targets,
                scenario.ledger_config(initial_cash),
            )
            results[(candidate, scenario.scenario_id)] = result
            risk_drawdown = max(
                float(result.metrics["maximum_drawdown"]),
                float(result.metrics["intraday_adverse_drawdown"]),
            )
            scenario_rows.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario.scenario_id,
                    **asdict(scenario),
                    **result.metrics,
                    "risk_drawdown": risk_drawdown,
                }
            )
            folds = build_v6_fold_metrics(result.ledger, initial_cash)
            folds.insert(0, "scenario_id", scenario.scenario_id)
            folds.insert(0, "candidate_id", candidate)
            fold_frames.append(folds)
    return (
        pd.DataFrame(scenario_rows),
        pd.concat(fold_frames, ignore_index=True),
        results,
    )


def select_v6_candidate(fold_metrics: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Vybirayet po median Sharpe stress-scenariya s zapechatannym tie-break."""
    required = {"candidate_id", "scenario_id", "fold_year", "cagr", "sharpe"}
    if missing := required - set(fold_metrics.columns):
        raise ValueError(f"Fold metrics ne soderzhit kolonok: {sorted(missing)}")
    selected = fold_metrics.loc[
        fold_metrics["scenario_id"].eq(V6_SELECTION_SCENARIO)
    ].copy()
    counts = selected.groupby("candidate_id")["fold_year"].nunique()
    if set(counts.index) != set(V6_CANDIDATES) or not counts.eq(len(V6_FOLD_YEARS)).all():
        raise ValueError("Selection scenario ne pokryvaet vse kandidaty i folds")
    ranking = (
        selected.groupby("candidate_id", as_index=False)
        .agg(
            median_fold_sharpe=("sharpe", "median"),
            worst_fold_cagr=("cagr", "min"),
        )
        .sort_values(
            ["median_fold_sharpe", "worst_fold_cagr", "candidate_id"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    ranking.insert(0, "rank", np.arange(1, len(ranking) + 1))
    return str(ranking.iloc[0]["candidate_id"]), ranking


def evaluate_v6_gates(
    selected_candidate: str,
    scenario_metrics: pd.DataFrame,
    fold_metrics: pd.DataFrame,
) -> V6GateDecision:
    """Primenyayet tolko precommitted gates i otdel'no reportit 50% stretch."""
    if selected_candidate not in V6_CANDIDATES:
        raise ValueError("Neizvestnyi selected candidate")
    required_scenarios = {scenario.scenario_id for scenario in fixed_v6_scenarios()}
    expected_pairs = {
        (candidate, scenario)
        for candidate in V6_CANDIDATES
        for scenario in required_scenarios
    }
    actual_pairs = set(
        scenario_metrics[["candidate_id", "scenario_id"]].itertuples(
            index=False,
            name=None,
        )
    )
    complete_matrix = actual_pairs == expected_pairs and not scenario_metrics.duplicated(
        ["candidate_id", "scenario_id"]
    ).any()
    selected_scenarios = scenario_metrics.loc[
        scenario_metrics["candidate_id"].eq(selected_candidate)
    ].set_index("scenario_id")
    if V6_PRIMARY_SCENARIO not in selected_scenarios.index:
        raise ValueError("Net primary scenario dlya selected candidate")
    if V6_SELECTION_SCENARIO not in selected_scenarios.index:
        raise ValueError("Net stress scenario dlya selected candidate")
    primary = selected_scenarios.loc[V6_PRIMARY_SCENARIO]
    stress = selected_scenarios.loc[V6_SELECTION_SCENARIO]
    selected_folds = fold_metrics.loc[
        fold_metrics["candidate_id"].eq(selected_candidate)
        & fold_metrics["scenario_id"].eq(V6_PRIMARY_SCENARIO)
    ]
    if set(selected_folds["fold_year"].astype(int)) != set(V6_FOLD_YEARS):
        raise ValueError("Primary folds ne pokryvayut vsyu development istoriyu")
    positive_folds = int(selected_folds["cagr"].gt(0.0).sum())
    worst_fold_cagr = float(selected_folds["cagr"].min())
    all_execution_complete = bool(
        complete_matrix
        and scenario_metrics["execution_complete"].astype(bool).all()
    )
    if not {"critical_failure_count", "unresolved_halt_count"} <= set(
        scenario_metrics.columns
    ):
        raise ValueError("Scenario metrics ne soderzhat execution failure counters")
    maximum_critical_failures = int(scenario_metrics["critical_failure_count"].max())
    maximum_unresolved_halts = int(scenario_metrics["unresolved_halt_count"].max())
    primary_drawdown = max(
        float(primary["maximum_drawdown"]),
        float(primary["intraday_adverse_drawdown"]),
    )
    checks = {
        "complete_candidate_scenario_matrix": complete_matrix,
        "all_execution_complete": all_execution_complete,
        "maximum_critical_execution_events": maximum_critical_failures == 0,
        "maximum_unresolved_halt_events": maximum_unresolved_halts == 0,
        "aggregate_cagr": float(primary["cagr"]) + V6_METRIC_TOLERANCE
        >= V6_GATE_AGGREGATE_CAGR,
        "aggregate_sharpe": float(primary["sharpe"]) + V6_METRIC_TOLERANCE
        >= V6_GATE_AGGREGATE_SHARPE,
        "maximum_drawdown": primary_drawdown
        <= V6_GATE_MAXIMUM_DRAWDOWN + V6_METRIC_TOLERANCE,
        "positive_fold_count": positive_folds >= V6_GATE_POSITIVE_FOLDS,
        "worst_fold_cagr": worst_fold_cagr + V6_METRIC_TOLERANCE
        >= V6_GATE_WORST_FOLD_CAGR,
        "double_cost_cagr": float(stress["cagr"]) + V6_METRIC_TOLERANCE
        >= V6_GATE_STRESS_CAGR,
    }
    observed: dict[str, float | int | bool | str] = {
        "primary_scenario": V6_PRIMARY_SCENARIO,
        "selection_scenario": V6_SELECTION_SCENARIO,
        "primary_cagr": float(primary["cagr"]),
        "primary_sharpe": float(primary["sharpe"]),
        "primary_risk_drawdown": primary_drawdown,
        "positive_fold_count": positive_folds,
        "worst_fold_cagr": worst_fold_cagr,
        "double_cost_cagr": float(stress["cagr"]),
        "scenario_count": len(actual_pairs),
        "expected_scenario_count": len(expected_pairs),
        "maximum_critical_failure_count": maximum_critical_failures,
        "maximum_unresolved_halt_count": maximum_unresolved_halts,
    }
    return V6GateDecision(
        passed=all(checks.values()),
        stretch_50_reached=float(primary["cagr"]) + V6_METRIC_TOLERANCE
        >= V6_STRETCH_CAGR,
        selected_candidate=selected_candidate,
        checks=checks,
        observed=observed,
    )


__all__ = [
    "V6_CANDIDATES",
    "V6_FOLD_YEARS",
    "V6_PRIMARY_SCENARIO",
    "V6_SELECTION_SCENARIO",
    "V6GateDecision",
    "V6ScenarioSpec",
    "build_v6_fold_metrics",
    "evaluate_v6_gates",
    "fixed_v6_scenarios",
    "run_v6_scenarios",
    "select_v6_candidate",
]
