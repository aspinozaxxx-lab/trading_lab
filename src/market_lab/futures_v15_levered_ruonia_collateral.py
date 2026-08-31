"""Sealed V15 2x frozen-V12 trend plus causal RUONIA collateral income."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab.futures import portfolio_ledger as ledger_engine
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v15_levered_ruonia_collateral.yaml"
CONFIG_SHA256: Final[str] = (
    "8cbcf30712684607e16cde27a9bca333e4740bd3bdb119646890d0b28d00a50d"
)
V12_PROTOCOL_SHA256: Final[str] = v12.CONFIG_SHA256
V12_METRICS_SHA256: Final[str] = (
    "c989377f7de65c3ef0a8dd52a1f5fcbf11c6ad8048119ea0a7b4402f47b23288"
)
V12_PRIMARY_REFERENCE: Final[dict[str, float]] = {
    "total_return": 0.451113922334873,
    "cagr": 0.07731837008966158,
    "sharpe": 0.7624477569712388,
    "maximum_drawdown": 0.14152584161232418,
    "positive_years": 4.0,
    "worst_year": -0.026317846517727284,
    "total_cost_rub": 13387.28160116245,
}
LEVERAGE_MULTIPLIER: Final[float] = 2.0
MAXIMUM_GROSS: Final[float] = 2.0
MARGIN_BUFFER_MULTIPLIER: Final[float] = 2.0
RUONIA_APPLIED_FRACTION: Final[float] = 0.50
OPERATIONAL_BUFFER_FRACTION: Final[float] = 0.10
DAY_COUNT_DENOMINATOR: Final[float] = 365.0
RUONIA_COLUMNS: Final[tuple[str, ...]] = (
    "source",
    "series_id",
    "observation_date",
    "publication_date",
    "available_at",
    "value",
    "availability_rule",
)
RUONIA_ROWS: Final[int] = 1963
MOSCOW_TIMEZONE: Final[str] = "Europe/Moscow"


@dataclass(frozen=True, slots=True)
class LeveredLedgerConfig:
    """Structural ledger settings that retain all V12 checks but permit gross up to 2x."""

    initial_cash: float = v12.INITIAL_CASH
    expected_assets: tuple[str, ...] = v12.ASSETS
    maximum_gross_notional_multiple: float = MAXIMUM_GROSS
    initial_margin_buffer_multiplier: float = MARGIN_BUFFER_MULTIPLIER
    maximum_participation: float = v12.MAXIMUM_PARTICIPATION
    slippage_ticks: Literal[1, 2, 4] = 1
    fee_multiplier: Literal[1.0, 2.0] = 1.0
    execution_atomicity: Literal["portfolio", "asset"] = "asset"
    terminal_policy: Literal["carry"] = "carry"

    def __post_init__(self) -> None:
        if self.initial_cash != v12.INITIAL_CASH:
            raise ValueError("V15 initial cash drift")
        if self.expected_assets != v12.ASSETS:
            raise ValueError("V15 asset universe drift")
        if self.maximum_gross_notional_multiple != MAXIMUM_GROSS:
            raise ValueError("V15 maximum gross drift")
        if self.initial_margin_buffer_multiplier != MARGIN_BUFFER_MULTIPLIER:
            raise ValueError("V15 margin buffer drift")
        if self.maximum_participation != v12.MAXIMUM_PARTICIPATION:
            raise ValueError("V15 participation drift")
        if self.slippage_ticks not in {1, 2, 4}:
            raise ValueError("V15 slippage must be 1, 2 or 4 ticks")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("V15 fee multiplier must be 1 or 2")
        if self.execution_atomicity != "asset" or self.terminal_policy != "carry":
            raise ValueError("V15 execution semantics drift")


@dataclass(frozen=True, slots=True)
class RuoniaVerification:
    """Causally verified RUONIA observations from the filtered official CBR panel."""

    frame: pd.DataFrame
    checks: dict[str, bool]


@dataclass(frozen=True, slots=True)
class CollateralEvaluation:
    """Interest accrual audit, combined equity ledger and combined metrics."""

    audit: pd.DataFrame
    combined_ledger: pd.DataFrame
    metrics: dict[str, Any]


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and the single V15 capital-efficiency specification."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V15 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V15 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V15 protocol must be a mapping")
    parent = protocol["parent_v12"]
    signal = protocol["signal"]
    leverage = protocol["leverage"]
    collateral = protocol["collateral_income"]
    execution = protocol["execution"]
    reference = {str(key): float(value) for key, value in parent["primary_reference"].items()}
    if (
        protocol.get("protocol_id") != "futures_v15_levered_ruonia_collateral_v1"
        or protocol.get("status") != "predeclared_before_v15_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != v12.ASSETS
        or parent["protocol_sha256"] != V12_PROTOCOL_SHA256
        or parent["metrics_sha256"] != V12_METRICS_SHA256
        or reference != V12_PRIMARY_REFERENCE
        or tuple(protocol["inputs"]["cbr_panel"]["allowed_columns"]) != RUONIA_COLUMNS
        or tuple(int(value) for value in signal["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(signal["volatility_lookback_sessions"]) != v12.VOLATILITY_LOOKBACK
        or int(signal["annualization_sessions"]) != v12.ANNUALIZATION
        or float(signal["volatility_floor_annualized"]) != v12.VOLATILITY_FLOOR
        or signal["score_implementation"] != "imported_frozen_v12"
        or float(leverage["target_weight_multiplier"]) != LEVERAGE_MULTIPLIER
        or float(leverage["maximum_gross_notional_multiple"]) != MAXIMUM_GROSS
        or float(leverage["initial_margin_buffer_multiple"]) != MARGIN_BUFFER_MULTIPLIER
        or float(collateral["applied_rate_fraction"]) != RUONIA_APPLIED_FRACTION
        or collateral["day_count"] != "ACT_365_calendar_days"
        or float(collateral["operational_buffer_fraction_of_conservative_equity"])
        != OPERATIONAL_BUFFER_FRACTION
        or collateral["reinvested_into_contract_sizing"] is not False
        or collateral["compounded_into_future_eligible_balance"] is not False
        or collateral["principal_double_counted"] is not False
        or float(execution["maximum_gross_notional_multiple"]) != MAXIMUM_GROSS
        or float(execution["initial_margin_buffer_multiple"]) != MARGIN_BUFFER_MULTIPLIER
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["initial_cash_rub"]) != v12.INITIAL_CASH
        or execution["execution_atomicity"] != "asset"
    ):
        raise ValueError("sealed V15 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V15 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Reuse V12 identity/date preflight and make the V15 seal explicit."""
    verified = v12.verify_inputs(protocol)
    checks = dict(verified.checks)
    checks["v12_parent_protocol_seal"] = checks.pop("protocol_seal")
    checks["v15_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    if not all(checks.values()):
        raise ValueError(f"V15 input identity preflight failed: {checks}")
    return v12.VerifiedInputs(
        paths=verified.paths,
        checks=checks,
        metadata=verified.metadata,
    )


def verify_ruonia(frame: pd.DataFrame) -> RuoniaVerification:
    """Fail closed unless the filtered official RUONIA panel has exact causal timing."""
    required = set(RUONIA_COLUMNS)
    if missing := required - set(frame.columns):
        raise ValueError(f"V15 RUONIA source lacks columns: {sorted(missing)}")
    ruonia = frame.loc[:, RUONIA_COLUMNS].copy()
    if len(ruonia) != RUONIA_ROWS:
        raise ValueError("V15 RUONIA row identity drift")
    if not ruonia["source"].astype("string").eq("cbr").all():
        raise ValueError("V15 RUONIA provider drift")
    if not ruonia["series_id"].astype("string").eq("ruonia").all():
        raise ValueError("V15 parquet predicate admitted another CBR series")
    for column in ("observation_date", "publication_date"):
        values = pd.to_datetime(ruonia[column], errors="raise")
        if values.dt.tz is not None:
            values = values.dt.tz_convert("UTC").dt.tz_localize(None)
        ruonia[column] = values.dt.normalize()
    ruonia["available_at"] = pd.to_datetime(
        ruonia["available_at"], errors="raise", utc=True
    )
    protected_utc = pd.Timestamp("2026-01-01", tz=MOSCOW_TIMEZONE).tz_convert("UTC")
    if ruonia["available_at"].ge(protected_utc).any():
        raise ValueError("V15 RUONIA touches the protected 2026 boundary")
    if ruonia.duplicated("observation_date").any():
        raise ValueError("V15 RUONIA has duplicate observation dates")
    if not ruonia["publication_date"].gt(ruonia["observation_date"]).all():
        raise ValueError("V15 RUONIA publication must be after observation")
    expected_available = (
        (ruonia["publication_date"] + pd.Timedelta(days=1))
        .dt.tz_localize(MOSCOW_TIMEZONE)
        .dt.tz_convert("UTC")
    )
    if not ruonia["available_at"].equals(expected_available):
        raise ValueError("V15 RUONIA conservative available_at drift")
    if not ruonia["availability_rule"].astype("string").eq(
        "publication_date_plus_one_calendar_day"
    ).all():
        raise ValueError("V15 RUONIA availability rule drift")
    rate = pd.to_numeric(ruonia["value"], errors="coerce").astype(float)
    if rate.isna().any() or not np.isfinite(rate).all() or rate.le(0.0).any():
        raise ValueError("V15 RUONIA rate must be finite and positive")
    ruonia["ruonia_percent"] = rate
    if ruonia["observation_date"].min() != pd.Timestamp("2018-01-09") or ruonia[
        "observation_date"
    ].max() != pd.Timestamp("2025-12-29"):
        raise ValueError("V15 RUONIA observation boundary drift")
    checks = {
        "ruonia_filtered_series_only": True,
        "ruonia_rows_and_dates_exact": True,
        "ruonia_publication_after_observation": True,
        "ruonia_available_at_conservative_and_exact": True,
        "ruonia_has_no_2026_available_rows": True,
        "ruonia_rate_finite_positive": True,
    }
    return RuoniaVerification(
        frame=ruonia.sort_values("available_at", kind="mergesort", ignore_index=True),
        checks=checks,
    )


def build_levered_weights(weekly_weights: pd.DataFrame) -> pd.DataFrame:
    """Double every frozen V12 target without changing relative composition or missingness."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(weekly_weights.columns):
        raise ValueError(f"V15 weekly weights lack columns: {sorted(missing)}")
    output = weekly_weights.copy()
    output["v12_target_weight"] = pd.to_numeric(
        output["target_weight"], errors="raise"
    ).astype(float)
    output["target_weight"] = output["v12_target_weight"] * LEVERAGE_MULTIPLIER
    output["provenance"] = (
        output["provenance"].astype("string") + "|sealed_two_times_capital_efficiency"
    )
    gross = output.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if gross.gt(MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V15 levered target exceeds sealed gross two")
    return output.sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )


def _annual_level_returns(
    dates: pd.Series,
    levels: pd.Series,
) -> dict[str, float]:
    ordered = pd.DataFrame(
        {
            "date": pd.to_datetime(dates, errors="raise").dt.normalize(),
            "level": pd.to_numeric(levels, errors="raise").astype(float),
        }
    ).sort_values("date", kind="mergesort")
    output: dict[str, float] = {}
    for year in range(2021, 2026):
        start = pd.Timestamp(f"{year}-01-01")
        end = pd.Timestamp(f"{year}-12-31")
        before = ordered.loc[ordered["date"].lt(start), "level"]
        within = ordered.loc[ordered["date"].between(start, end), "level"]
        if within.empty:
            continue
        starting_level = float(before.iloc[-1]) if not before.empty else v12.INITIAL_CASH
        output[str(year)] = float(within.iloc[-1] / starting_level - 1.0)
    return output


def evaluate_collateral_income(
    result: FuturesPortfolioLedgerResult,
    ruonia: RuoniaVerification,
) -> CollateralEvaluation:
    """Accrue haircutted RUONIA between factual sessions without changing trade sizing."""
    required = {
        "session_date",
        "ending_cash",
        "intraday_adverse_equity",
        "modeled_initial_margin",
    }
    if missing := required - set(result.ledger.columns):
        raise ValueError(f"V15 ledger lacks collateral fields: {sorted(missing)}")
    ledger = result.ledger.sort_values("session_date", kind="mergesort").reset_index(drop=True)
    if ledger.empty:
        raise ValueError("V15 collateral evaluation requires a nonempty ledger")
    dates = pd.to_datetime(ledger["session_date"], errors="raise").dt.normalize()
    if dates.ge(v12.PROTECTED_FROM).any() or dates.duplicated().any():
        raise ValueError("V15 collateral ledger date boundary or uniqueness failed")
    session_start_utc = dates.dt.tz_localize(MOSCOW_TIMEZONE).dt.tz_convert("UTC")
    sessions = pd.DataFrame(
        {"session_number": np.arange(len(ledger)), "session_start_utc": session_start_utc}
    ).sort_values("session_start_utc", kind="mergesort")
    source = ruonia.frame.loc[
        :, ["observation_date", "available_at", "ruonia_percent"]
    ].sort_values("available_at", kind="mergesort")
    if source.empty:
        raise ValueError("V15 missing causal RUONIA for positive accrual intervals")
    lookup = pd.merge_asof(
        sessions,
        source,
        left_on="session_start_utc",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("session_number", kind="mergesort")
    if lookup["available_at"].gt(lookup["session_start_utc"]).fillna(False).any():
        raise ValueError("V15 RUONIA lookup used a future publication")

    cumulative = np.zeros(len(ledger), dtype=float)
    credited = np.zeros(len(ledger), dtype=float)
    audit_rows: list[dict[str, Any]] = []
    for index in range(len(ledger) - 1):
        raw_start = pd.Timestamp(dates.iloc[index])
        accrual_start = max(raw_start, v12.OOS_START)
        accrual_end = pd.Timestamp(dates.iloc[index + 1])
        days = max((accrual_end - accrual_start).days, 0)
        rate = lookup.iloc[index]["ruonia_percent"]
        available_at = lookup.iloc[index]["available_at"]
        observation_date = lookup.iloc[index]["observation_date"]
        if days > 0 and (pd.isna(rate) or pd.isna(available_at)):
            raise ValueError("V15 missing causal RUONIA for a positive accrual interval")
        ending_cash = float(ledger.iloc[index]["ending_cash"])
        adverse_equity = float(ledger.iloc[index]["intraday_adverse_equity"])
        margin = float(ledger.iloc[index]["modeled_initial_margin"])
        conservative_equity = max(min(ending_cash, adverse_equity), 0.0)
        operational_buffer = conservative_equity * OPERATIONAL_BUFFER_FRACTION
        eligible = max(
            conservative_equity
            - MARGIN_BUFFER_MULTIPLIER * max(margin, 0.0)
            - operational_buffer,
            0.0,
        )
        applied_percent = (
            float(rate) * RUONIA_APPLIED_FRACTION if days > 0 else 0.0
        )
        interest = (
            eligible * applied_percent / 100.0 * float(days) / DAY_COUNT_DENOMINATOR
        )
        cumulative[index + 1] = cumulative[index] + interest
        credited[index + 1] = interest
        audit_rows.append(
            {
                "accrual_start_session": raw_start,
                "accrual_start_clipped": accrual_start,
                "accrual_end_session": accrual_end,
                "calendar_days": days,
                "ruonia_observation_date": observation_date,
                "ruonia_available_at": available_at,
                "ruonia_percent": None if pd.isna(rate) else float(rate),
                "applied_percent": applied_percent,
                "conservative_equity": conservative_equity,
                "modeled_initial_margin": margin,
                "margin_reserve": MARGIN_BUFFER_MULTIPLIER * max(margin, 0.0),
                "operational_buffer": operational_buffer,
                "eligible_balance": eligible,
                "interest_rub": interest,
                "cumulative_interest_rub": cumulative[index + 1],
            }
        )
    audit = pd.DataFrame(audit_rows)
    positive_intervals = audit["calendar_days"].gt(0)
    if audit.loc[positive_intervals, "ruonia_percent"].isna().any():
        raise ValueError("V15 RUONIA coverage is incomplete")
    combined = ledger.copy()
    combined["collateral_interest_credited"] = credited
    combined["cumulative_collateral_interest"] = cumulative
    combined["combined_ending_equity"] = combined["ending_cash"].astype(float) + cumulative
    performance = ledger_engine._performance_metrics(
        combined["combined_ending_equity"],
        combined["session_date"],
        v12.INITIAL_CASH,
    )
    annual = _annual_level_returns(
        combined["session_date"], combined["combined_ending_equity"]
    )
    metrics: dict[str, Any] = {
        **performance,
        "annual_returns": annual,
        "positive_years": int(sum(value > 0.0 for value in annual.values())),
        "worst_year": min(annual.values()) if annual else None,
        "collateral_income_rub": float(cumulative[-1]),
        "collateral_return_contribution": float(cumulative[-1] / v12.INITIAL_CASH),
        "accrual_interval_count": int(positive_intervals.sum()),
        "accrual_calendar_days": int(audit.loc[positive_intervals, "calendar_days"].sum()),
        "ruonia_covered_interval_count": int(
            audit.loc[positive_intervals, "ruonia_percent"].notna().sum()
        ),
        "mean_eligible_balance_rub": float(
            audit.loc[positive_intervals, "eligible_balance"].mean()
        ),
        "maximum_eligible_balance_rub": float(
            audit.loc[positive_intervals, "eligible_balance"].max()
        ),
        "applied_rate_fraction": RUONIA_APPLIED_FRACTION,
        "operational_buffer_fraction": OPERATIONAL_BUFFER_FRACTION,
        "day_count_denominator": DAY_COUNT_DENOMINATOR,
        "interest_reinvested_into_sizing": False,
        "interest_compounded_into_eligible_balance": False,
        "metrics_valid": bool(result.execution_complete),
    }
    return CollateralEvaluation(audit=audit, combined_ledger=combined, metrics=metrics)


def _scenario_payload(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
    ruonia: RuoniaVerification,
) -> tuple[dict[str, Any], CollateralEvaluation]:
    futures = v12.scenario_metrics(result, market, settings)
    collateral = evaluate_collateral_income(result, ruonia)
    combined = dict(collateral.metrics)
    reserve = futures["terminal_exit_cost_reserve"]
    combined["post_terminal_reserve_total_return"] = (
        None
        if reserve is None
        else (
            float(result.metrics["ending_cash"])
            + float(collateral.metrics["collateral_income_rub"])
            - float(reserve)
        )
        / v12.INITIAL_CASH
        - 1.0
    )
    combined["maximum_post_mark_gross_leverage"] = float(
        result.ledger["gross_leverage"].max()
    )
    combined["maximum_2x_margin_to_starting_cash"] = float(
        (
            MARGIN_BUFFER_MULTIPLIER
            * result.ledger["modeled_initial_margin"]
            / result.ledger["starting_cash"]
        ).max()
    )
    return (
        {
            "settings": settings,
            "futures_only": futures,
            "collateral": {
                key: value
                for key, value in collateral.metrics.items()
                if key
                in {
                    "collateral_income_rub",
                    "collateral_return_contribution",
                    "accrual_interval_count",
                    "accrual_calendar_days",
                    "ruonia_covered_interval_count",
                    "mean_eligible_balance_rub",
                    "maximum_eligible_balance_rub",
                    "applied_rate_fraction",
                    "operational_buffer_fraction",
                    "day_count_denominator",
                    "interest_reinvested_into_sizing",
                    "interest_compounded_into_eligible_balance",
                }
            },
            "combined": combined,
        },
        collateral,
    )


def _comparison(primary: dict[str, Any]) -> dict[str, Any]:
    combined = primary["combined"]
    return {
        "reference_protocol_sha256": V12_PROTOCOL_SHA256,
        "reference_metrics_sha256": V12_METRICS_SHA256,
        "reference": V12_PRIMARY_REFERENCE,
        "delta": {
            "total_return": float(combined["total_return"])
            - V12_PRIMARY_REFERENCE["total_return"],
            "cagr": float(combined["cagr"]) - V12_PRIMARY_REFERENCE["cagr"],
            "sharpe": float(combined["sharpe"]) - V12_PRIMARY_REFERENCE["sharpe"],
            "maximum_drawdown_reduction": V12_PRIMARY_REFERENCE["maximum_drawdown"]
            - float(combined["maximum_drawdown"]),
            "worst_year_improvement": float(combined["worst_year"])
            - V12_PRIMARY_REFERENCE["worst_year"],
        },
    }


def _promotion(
    results: dict[str, dict[str, Any]], checks: dict[str, bool]
) -> dict[str, Any]:
    primary = results["primary"]
    combined = primary["combined"]
    conditions = {
        "every_input_ruonia_accrual_and_temporal_check_true": all(checks.values()),
        "all_scenarios_execution_and_combined_metrics_complete": all(
            bool(value["futures_only"]["execution_complete"])
            and bool(value["combined"]["metrics_valid"])
            for value in results.values()
        ),
        "zero_critical_failures_and_unresolved_halts": all(
            int(value["futures_only"]["critical_failure_count"]) == 0
            and int(value["futures_only"]["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "primary_combined_cagr_at_least_0_20": float(combined["cagr"]) >= 0.20,
        "primary_combined_maximum_drawdown_at_most_0_25": float(
            combined["maximum_drawdown"]
        )
        <= 0.25,
        "primary_combined_positive_years_at_least_4_of_5": int(
            combined["positive_years"]
        )
        >= 4
        and len(combined["annual_returns"]) == 5,
        "doubled_combined_total_return_positive": float(
            results["doubled"]["combined"]["total_return"]
        )
        > 0.0,
        "stress_combined_total_return_positive": float(
            results["stress"]["combined"]["total_return"]
        )
        > 0.0,
        "no_order_time_gross_participation_or_margin_breach": all(
            float(value["futures_only"]["maximum_participation"])
            <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(value["futures_only"]["gross_limit_rejection_count"]) == 0
            and int(value["futures_only"]["initial_margin_rejection_count"]) == 0
            and float(value["futures_only"]["ending_cash"]) > 0.0
            for value in results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_UNSEEN_VALIDATION" if passed else "NO_GO",
        "live_trading_allowed": False,
        "independent_confirmation_required": True,
    }


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V15 2x frozen V12 plus causal RUONIA collateral income",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        "This is one adaptive 2021-2025 feasibility test, not independent confirmation.",
        "",
        (
            "| Scenario | Futures CAGR | Combined CAGR | Combined Sharpe | Combined MDD | "
            "Collateral RUB | Costs RUB |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        futures = item["futures_only"]
        combined = item["combined"]
        lines.append(
            f"| {name} | {futures['cagr']:.4%} | {combined['cagr']:.4%} | "
            f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
            f"{combined['collateral_income_rub']:.2f} | {futures['total_cost']:.2f} |"
        )
    lines.extend(["", "## Primary combined annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["combined"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    primary = payload["scenarios"]["primary"]
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Capital efficiency and execution",
            "",
            f"- Combined total return: {primary['combined']['total_return']:.4%}",
            f"- Futures-only total return: {primary['futures_only']['total_return']:.4%}",
            (
                "- Collateral contribution: "
                f"{primary['collateral']['collateral_return_contribution']:.4%}"
            ),
            f"- RUONIA coverage: {primary['collateral']['ruonia_covered_interval_count']}/"
            f"{primary['collateral']['accrual_interval_count']} intervals",
            (
                "- Mean eligible collateral: "
                f"{primary['collateral']['mean_eligible_balance_rub']:.2f} RUB"
            ),
            f"- Weekly decisions: {counts['weekly_decisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Non-zero targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Interest is not reinvested into sizing or future eligible balance. The 50% RUONIA "
            "haircut is a research proxy for taxes, fees, tracking, liquidity and access.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V15 capital-efficiency feasibility run."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    panel = pd.read_parquet(
        verified.paths["panel"], columns=protocol["inputs"]["panel"]["allowed_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    ruonia = verify_ruonia(ruonia_frame)
    checks = {**verified.checks, **ruonia.checks}
    scores = v12.build_trend_scores(panel)
    weekly_weights = v12.build_weekly_weights(panel, scores)
    levered_weights = build_levered_weights(weekly_weights)
    target_build = v12.build_execution_targets(levered_weights, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(
            predecessor, v12.OOS_END
        )
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_outputs: dict[str, CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol).items():
        result = ledger_engine.run_futures_portfolio_ledger(
            execution_market,
            target_build.targets,
            LeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = _scenario_payload(
            result, execution_market, settings, ruonia
        )

    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "source_ruonia_rows": int(len(ruonia.frame)),
        "score_rows": int(len(scores)),
        "finite_score_rows": int(scores["candidate_score"].notna().sum()),
        "weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": int(
            target_build.targets["target_weight"].abs().gt(1e-12).sum()
        ),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    comparison = _comparison(scenario_results["primary"])
    promotion = _promotion(scenario_results, checks)
    code_paths = {
        "v15_implementation": Path(__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "portfolio_construction": PROJECT_ROOT
        / "src/market_lab/futures/portfolio_construction.py",
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
        "info_radar": PROJECT_ROOT / "src/market_lab/futures/info_radar.py",
        "spec_proxy": PROJECT_ROOT / "src/market_lab/futures/spec_proxy.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v12_protocol_sha256": V12_PROTOCOL_SHA256,
        "parent_v12_metrics_sha256": V12_METRICS_SHA256,
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in protocol["inputs"].items()
        },
        "code_sha256": {name: v12.sha256_file(path) for name, path in code_paths.items()},
        "protected_from": v12.PROTECTED_FROM.date().isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_period": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "comparison_to_v12": comparison,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v15_levered_ruonia_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V15 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_weights.parquet", weekly_weights)
        v12._write_parquet(temporary / "levered_weights.parquet", levered_weights)
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
            v12._write_parquet(
                temporary / f"collateral_{name}.parquet", collateral_outputs[name].audit
            )
            v12._write_parquet(
                temporary / f"combined_ledger_{name}.parquet",
                collateral_outputs[name].combined_ledger,
            )
        report_path = temporary / "report.md"
        report_path.write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": v12.sha256_file(path),
            }
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(v12._json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        identity_path = temporary / "identity.json"
        identity_path.write_text(
            json.dumps(
                v12._json_safe(
                    {**identity, "metrics_sha256": v12.sha256_file(metrics_path)}
                ),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs",
        help="External immutable runs root; a unique V15 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
