"""Read-only accounting and concentration diagnostic of five frozen capital curves.

No market-source prices, target generation, fitting, parameter selection or execution
replay is performed. In particular, V49/V60 exact_futures_nav is NOT pure futures NAV.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT / "configs/v63_frozen_profit_attribution_v1.yaml"
SCENARIOS = ("primary", "doubled", "stress")
YEARS = tuple(range(2021, 2026))
CASH_MAP = dict(primary="primary", doubled="doubled", stress="zero_cashflow_stress")
CAPITAL = 1_000_000.0
START = pd.Timestamp("2020-12-30")
END = pd.Timestamp("2025-12-30")
BOUNDARY = pd.Timestamp("2026-01-01")
COMPONENTS = (
    "futures_gross_pnl",
    "futures_commissions",
    "futures_slippage",
    "modeled_futures_idle_income",
    "cash_carry_net_pnl",
    "modeled_cash_sleeve_idle_income",
)
LEDGER_COLS = [
    "session_date",
    "starting_cash",
    "ending_cash",
    "variation_margin",
    "commission_cost",
    "slippage_cost",
    "collateral_interest_credited",
    "cumulative_collateral_interest",
    "combined_ending_equity",
]
ORDER_COLS = [
    "session_date",
    "scenario",
    "commission_cost",
    "slippage_cost",
    "filled",
    "gross_notional",
    "participation",
]
POSITION_COLS = ["session_date", "scenario", "contracts"]


def require(condition: Any, message: str) -> None:
    if not bool(condition):
        raise ValueError(message)


def close(actual: Any, expected: Any, message: str) -> None:
    require(np.allclose(actual, expected, rtol=1e-10, atol=1e-6), message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "unsafe relative path")
    result = (root / rel).resolve()
    require(result.is_relative_to(root.resolve()), "resolved path escapes storage")
    return result


def dated(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    result = frame.copy()
    dates = pd.to_datetime(result[column], errors="raise")
    require(dates.notna().all(), "missing date")
    require(dates.dt.tz is None, "unexpected timezone")
    require(dates.lt(BOUNDARY).all(), "protected date")
    require(dates.between(START, END).all(), "date outside declared development interval")
    result[column] = dates
    return result


def file_specs(role: str) -> dict[str, tuple[list[str], int]]:
    if role == "v39":
        return {f"combined_ledger_{s}.parquet": (LEDGER_COLS, 1272) for s in SCENARIOS}
    if role == "cash":
        cols = ["date"] + [
            c for s in CASH_MAP.values() for c in (f"overlay_{s}_nav", f"{s}_cumulative_interest")
        ]
        return {"daily_ledger.parquet": (cols, 1827)}
    if role == "v41":
        cols = ["session_date"] + [
            c
            for s in SCENARIOS
            for c in (
                f"v39_{s}_nav",
                f"cash_carry_ruonia_{s}_nav",
                f"combined_{s}_nav",
            )
        ]
        return {"combined_ledger.parquet": (cols, 1272)}
    mode = "double_risk" if role == "v49" else "equity_trend_risk"
    cols = ["session_date"] + [
        c
        for s in (*SCENARIOS, "execution_stress")
        for c in (
            f"{mode}_{s}_combined_nav",
            f"{mode}_{s}_exact_futures_nav",
        )
    ]
    return {
        "combined_ledger.parquet": (cols, 1272),
        "orders.parquet": (ORDER_COLS, 2001 if role == "v49" else 1956),
        "positions.parquet": (POSITION_COLS, 15264),
    }


def protocol(path: Path = CONFIG) -> dict[str, Any]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    require(
        sha(path) == path.with_suffix(".sha256").read_text(encoding="utf-8-sig").strip(),
        "config seal mismatch",
    )
    require(cfg["protocol_id"] == "v63_frozen_profit_attribution_v1", "wrong protocol")
    require(cfg["implementation_sha256"] == sha(Path(__file__)), "implementation drift")
    require(
        cfg["live_trading_allowed"] is False and cfg["parameter_search"] is False,
        "research-only invariant",
    )
    require(set(cfg["inputs"]) == {"v39", "cash", "v41", "v49", "v60"}, "input set drift")
    cfg["config_sha256"] = sha(path)
    return cfg


def admit(cfg: dict[str, Any], storage: Path) -> tuple[dict[str, dict[str, Path]], dict[str, Any]]:
    """Hash every selected artifact, then inspect only date columns before any NAV load."""
    paths: dict[str, dict[str, Path]] = {}
    evidence: dict[str, Any] = {}
    for role, source in cfg["inputs"].items():
        root = safe_path(storage, source["root"])
        catalog_path = safe_path(root, source["catalog"])
        require(sha(catalog_path) == source["catalog_sha256"], f"{role} catalog drift")
        catalog = read_json(catalog_path)
        declarations = {v.get("file", k): v for k, v in catalog["artifacts"].items()}
        selected = {"metrics.json": ([], None), **file_specs(role)}
        paths[role], evidence[role] = {}, {}
        for filename, (columns, rows) in selected.items():
            p = safe_path(root, filename)
            digest = sha(p)
            if p != catalog_path:
                d = declarations[filename]
                require(
                    digest == d["sha256"] and p.stat().st_size == d["bytes"],
                    f"{role}/{filename} artifact drift",
                )
            item = dict(sha256=digest, bytes=p.stat().st_size, path=str(p))
            if rows is not None:
                pf = pq.ParquetFile(p)
                require(pf.metadata.num_rows == rows, f"{role}/{filename} row drift")
                require(set(columns) <= set(pf.schema_arrow.names), "missing declared columns")
                date_col = "date" if role == "cash" else "session_date"
                dates = dated(pf.read(columns=[date_col]).to_pandas(), date_col)[date_col]
                if filename not in {"orders.parquet", "positions.parquet"}:
                    require(
                        not dates.duplicated().any() and dates.is_monotonic_increasing,
                        "NAV calendar duplicate or unordered",
                    )
                    require(
                        dates.iloc[0] == START and dates.iloc[-1] == END,
                        "NAV calendar endpoints drift",
                    )
                item.update(
                    rows=rows,
                    columns=columns,
                    minimum_date=str(dates.min()),
                    maximum_date=str(dates.max()),
                )
            paths[role][filename], evidence[role][filename] = p, item
        evidence[role]["catalog"] = dict(path=str(catalog_path), sha256=sha(catalog_path))
    return paths, evidence


def load_frame(paths: dict[str, dict[str, Path]], role: str, filename: str) -> pd.DataFrame:
    columns, _ = file_specs(role)[filename]
    frame = pd.read_parquet(paths[role][filename], columns=columns)
    return dated(frame, "date" if role == "cash" else "session_date")


def validate_nav(nav: pd.Series) -> None:
    require(nav.index.is_unique and nav.index.is_monotonic_increasing, "NAV dates invalid")
    require(np.isfinite(nav).all() and nav.gt(0).all(), "invalid NAV")
    close(float(nav.iloc[0]), 1.0, "NAV initial anchor is not one")


def performance(nav: pd.Series, year_days: float = 365.25) -> dict[str, Any]:
    validate_nav(nav)
    ret = nav.pct_change(fill_method=None).fillna(0.0)
    years = (nav.index[-1] - nav.index[0]).days / year_days
    require(years > 0, "empty time interval")
    baseline = nav.loc[nav.index.year == 2020]
    annual, previous = {}, float(baseline.iloc[-1] if len(baseline) else nav.iloc[0])
    for year in YEARS:
        part = nav.loc[nav.index.year == year]
        require(not part.empty, "missing calendar year")
        ending = float(part.iloc[-1])
        annual[str(year)], previous = ending / previous - 1, ending
    std = float(ret.std(ddof=1))
    return dict(
        total_return=float(nav.iloc[-1] - 1),
        cagr=float(nav.iloc[-1] ** (1 / years) - 1),
        sharpe=float(ret.mean() / std * math.sqrt(252)) if std > 0 else 0.0,
        maximum_drawdown=float((1 - nav / nav.cummax()).max()),
        annual_returns=annual,
        worst_year=min(annual.values()),
    )


def annual_futures_account(
    nav: pd.Series,
    futures: dict[str, Any],
    orders: pd.DataFrame,
) -> pd.DataFrame:
    """Reconstruct year-end *accounting*, never new trades or alternative risk sizing."""
    validate_nav(nav)
    require(set(futures["annual_returns"]) == {str(y) for y in YEARS}, "annual coverage")
    close(futures["starting_cash"], CAPITAL, "initial futures cash differs")
    require(
        futures["execution_complete"]
        and not futures["critical_failure_count"]
        and not futures["unresolved_halt_count"],
        "incomplete parent execution",
    )
    filled = orders.loc[orders["filled"].eq(True)].copy()  # noqa: E712
    require(orders["filled"].notna().all(), "missing fill flag")
    for cost in ("commission_cost", "slippage_cost"):
        require(np.isfinite(filled[cost]).all() and filled[cost].ge(0).all(), "invalid cost")
        close(filled[cost].sum(), futures[cost], f"order/{cost} conservation")
    require(len(filled) == int(futures["filled_leg_count"]), "filled-leg count drift")
    close(
        futures["commission_cost"] + futures["slippage_cost"],
        futures["total_cost"],
        "total cost conservation",
    )
    close(
        futures["ending_cash"] - CAPITAL,
        futures["variation_margin"] - futures["total_cost"],
        "futures cash conservation",
    )
    previous_futures, previous_combined, previous_interest = CAPITAL, CAPITAL, 0.0
    close(
        nav.loc[nav.index.year == 2020],
        np.ones(sum(nav.index.year == 2020)),
        "futures parent has unexpected pre-2021 income",
    )
    rows = [dict(year=2020, **dict.fromkeys((*COMPONENTS, "total_pnl"), 0.0))]
    for year in YEARS:
        f_end = previous_futures * (1 + float(futures["annual_returns"][str(year)]))
        c_end = CAPITAL * float(nav.loc[nav.index.year == year].iloc[-1])
        interest = c_end - f_end
        require(interest >= previous_interest - 1e-5, "negative inferred collateral credit")
        yearly_orders = filled.loc[filled["session_date"].dt.year == year]
        fee, slip = (float(yearly_orders[c].sum()) for c in ("commission_cost", "slippage_cost"))
        rows.append(
            dict(
                year=year,
                futures_gross_pnl=f_end - previous_futures + fee + slip,
                futures_commissions=-fee,
                futures_slippage=-slip,
                modeled_futures_idle_income=interest - previous_interest,
                cash_carry_net_pnl=0.0,
                modeled_cash_sleeve_idle_income=0.0,
                total_pnl=c_end - previous_combined,
            )
        )
        previous_futures, previous_combined, previous_interest = f_end, c_end, interest
    close(previous_futures, futures["ending_cash"], "annual futures terminal replay")
    return pd.DataFrame(rows).set_index("year")


def annual_from_cumulative(frame: pd.DataFrame) -> pd.DataFrame:
    previous = pd.Series(0.0, index=frame.columns)
    rows = []
    close(
        frame.iloc[0].to_numpy(dtype=float),
        np.zeros(len(frame.columns)),
        "initial attribution is not zero",
    )
    for year in (2020, *YEARS):
        ending = frame.loc[frame.index.year == year].iloc[-1]
        row = (ending - previous).to_dict()
        row["year"] = year
        rows.append(row)
        previous = ending
    return pd.DataFrame(rows).set_index("year")


def concentration(nav: pd.Series) -> dict[str, Any]:
    logs = np.log(nav).diff().fillna(0.0)
    logs = logs.loc[logs.index.year >= 2021]
    yearly = logs.groupby(logs.index.year).sum()
    positive = float(logs.clip(lower=0).sum())
    total = float(logs.sum())
    top = float(logs.loc[logs.gt(0)].nlargest(10).sum())
    return dict(
        annual_log_profit={str(y): float(v) for y, v in yearly.items()},
        largest_log_profit_year=int(yearly.idxmax()),
        largest_year_share_of_net_log_profit=float(yearly.max() / total) if total > 0 else None,
        top_10_positive_sessions_share_of_positive_log_profit=top / positive
        if positive > 0
        else None,
        top_10_positive_sessions_share_of_net_log_profit=top / total if total > 0 else None,
        negative_sessions=int(logs.lt(0).sum()),
        diagnostic_only_not_a_tradeable_filter=True,
    )


def summarize(
    nav: pd.Series,
    annual: pd.DataFrame,
    canonical: dict[str, Any],
    canonical_year_days: float = 365.25,
) -> dict[str, Any]:
    replay = performance(nav, canonical_year_days)
    for key in ("total_return", "cagr", "sharpe", "maximum_drawdown"):
        close(replay[key], canonical[key], f"canonical metric replay: {key}")
    for year, value in replay["annual_returns"].items():
        close(value, canonical["annual_returns"][year], f"canonical annual replay {year}")
    close(
        annual[list(COMPONENTS)].sum(axis=1), annual["total_pnl"], "annual attribution conservation"
    )
    close(
        annual["total_pnl"].sum(), (nav.iloc[-1] - 1) * CAPITAL, "terminal attribution conservation"
    )
    result = dict(
        common_clock_metrics=performance(nav),
        canonical_metrics=replay,
        canonical_year_days=canonical_year_days,
        terminal_pnl_rub={k: float(v) for k, v in annual.sum().items()},
        annual_pnl_rub={str(y): {k: float(v) for k, v in r.items()} for y, r in annual.iterrows()},
        concentration=concentration(nav),
    )
    return result


def build(paths: dict[str, dict[str, Path]]) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics = {role: read_json(p["metrics.json"]) for role, p in paths.items()}
    cash = load_frame(paths, "cash", "daily_ledger.parquet").set_index("date")
    v41 = load_frame(paths, "v41", "combined_ledger.parquet").set_index("session_date")
    output: dict[str, Any] = {r: {} for r in ("v39", "v41", "v49", "v60", "cash")}
    curves = pd.DataFrame(index=v41.index)
    for scenario in SCENARIOS:
        ledger = load_frame(paths, "v39", f"combined_ledger_{scenario}.parquet").set_index(
            "session_date"
        )
        require(ledger.index.equals(v41.index), "V39/V41 calendar mismatch")
        close(
            ledger.iloc[0][["starting_cash", "ending_cash", "combined_ending_equity"]].to_numpy(
                dtype=float
            ),
            np.full(3, CAPITAL),
            "V39 initial cash anchor",
        )
        close(
            ledger["ending_cash"],
            ledger["starting_cash"]
            + ledger["variation_margin"]
            - ledger["commission_cost"]
            - ledger["slippage_cost"],
            "V39 daily accounting",
        )
        close(
            ledger["starting_cash"].iloc[1:], ledger["ending_cash"].iloc[:-1], "V39 cash continuity"
        )
        close(
            ledger["collateral_interest_credited"].cumsum(),
            ledger["cumulative_collateral_interest"],
            "V39 collateral accumulation",
        )
        close(
            ledger["ending_cash"] + ledger["cumulative_collateral_interest"],
            ledger["combined_ending_equity"],
            "V39 combined accounting",
        )
        futures_summary = metrics["v39"]["scenarios"][scenario]["futures_only"]
        require(
            futures_summary["execution_complete"]
            and not futures_summary["critical_failure_count"]
            and not futures_summary["unresolved_halt_count"],
            "V39 execution incomplete",
        )
        close(ledger["ending_cash"].iloc[-1], futures_summary["ending_cash"], "V39 terminal")
        for component in ("variation_margin", "commission_cost", "slippage_cost"):
            close(ledger[component].sum(), futures_summary[component], "V39 summary accounting")
        cumul = pd.DataFrame(0.0, index=ledger.index, columns=(*COMPONENTS, "total_pnl"))
        cumul["futures_gross_pnl"] = ledger["variation_margin"].cumsum()
        cumul["futures_commissions"] = -ledger["commission_cost"].cumsum()
        cumul["futures_slippage"] = -ledger["slippage_cost"].cumsum()
        cumul["modeled_futures_idle_income"] = ledger["cumulative_collateral_interest"]
        cumul["total_pnl"] = ledger["combined_ending_equity"] - CAPITAL
        nav = ledger["combined_ending_equity"] / CAPITAL
        output["v39"][scenario] = summarize(
            nav,
            annual_from_cumulative(cumul),
            metrics["v39"]["scenarios"][scenario]["combined"],
            365.2425,
        )
        output["v39"][scenario]["execution"] = metrics["v39"]["scenarios"][scenario]["futures_only"]
        curves[f"v39_{scenario}"] = nav
        cash_scenario = CASH_MAP[scenario]
        cash_nav = cash[f"overlay_{cash_scenario}_nav"].reindex(nav.index)
        interest = cash[f"{cash_scenario}_cumulative_interest"].reindex(nav.index) * CAPITAL
        validate_nav(cash_nav)
        original_cash = performance(cash[f"overlay_{cash_scenario}_nav"])
        declared_cash = metrics["cash"]["scenarios"][cash_scenario]["overlay"]
        for key in ("total_return", "cagr", "maximum_drawdown"):
            close(original_cash[key], declared_cash[key], f"cash original calendar {key}")
        close(
            original_cash["sharpe"] * math.sqrt(365.25 / 252),
            declared_cash["sharpe"],
            "cash original calendar Sharpe",
        )
        require(
            interest.notna().all() and interest.diff().dropna().ge(-1e-10).all(),
            "cash income invalid",
        )
        cash_cumul = pd.DataFrame(0.0, index=nav.index, columns=cumul.columns)
        cash_cumul["modeled_cash_sleeve_idle_income"] = interest
        cash_cumul["total_pnl"] = (cash_nav - 1) * CAPITAL
        cash_cumul["cash_carry_net_pnl"] = cash_cumul["total_pnl"] - interest
        # Cash daily-clock Sharpe differs from session-clock Sharpe: do not equate them.
        output["cash"][scenario] = summarize(
            cash_nav, annual_from_cumulative(cash_cumul), performance(cash_nav)
        )
        output["cash"][scenario]["execution"] = dict(
            frozen_parent_trade_count=15,
            investor_integer_execution_proved=False,
            costs_embedded_in_cash_carry_net_component=True,
            cash_trade_component_includes_overlay_compounding=True,
        )
        curves[f"cash_{scenario}"] = cash_nav
        close(v41[f"v39_{scenario}_nav"], nav, "V41 V39 parent replay")
        close(v41[f"cash_carry_ruonia_{scenario}_nav"], cash_nav, "V41 cash parent replay")
        combined = 0.8 * nav + 0.2 * cash_nav
        close(v41[f"combined_{scenario}_nav"], combined, "V41 fixed-weight replay")
        output["v41"][scenario] = summarize(
            combined,
            annual_from_cumulative(0.8 * cumul + 0.2 * cash_cumul),
            metrics["v41"]["scenarios"][scenario]["combined"],
        )
        output["v41"][scenario]["execution"] = dict(
            futures_parent_filled_legs=metrics["v39"]["scenarios"][scenario]["futures_only"][
                "filled_leg_count"
            ],
            cash_parent_trades=15,
            investor_integer_execution_proved=False,
        )
        curves[f"v41_{scenario}"] = combined
    for role, mode in (("v49", "double_risk"), ("v60", "equity_trend_risk")):
        ledger = load_frame(paths, role, "combined_ledger.parquet").set_index("session_date")
        require(ledger.index.equals(curves.index), "leader calendar mismatch")
        orders = load_frame(paths, role, "orders.parquet")
        positions = load_frame(paths, role, "positions.parquet")
        require(set(orders["scenario"]) == set(SCENARIOS), "orders scenario set")
        require(set(positions["scenario"]) == set(SCENARIOS), "positions scenario set")
        require(orders["session_date"].dt.year.ge(2021).all(), "orders before initial cash anchor")
        initial_positions = positions.loc[positions["session_date"].eq(START)]
        require(
            initial_positions.groupby("scenario").size().to_dict() == dict.fromkeys(SCENARIOS, 4),
            "initial position coverage",
        )
        require(initial_positions["contracts"].eq(0).all(), "initial position is nonflat")
        for scenario in SCENARIOS:
            nav = ledger[f"{mode}_{scenario}_combined_nav"]
            close(
                nav,
                ledger[f"{mode}_{scenario}_exact_futures_nav"],
                "historical column semantics drift",
            )
            parent = metrics[role]["scenarios"][scenario]
            frame = annual_futures_account(
                nav, parent["futures"], orders.loc[orders["scenario"].eq(scenario)]
            )
            output[role][scenario] = summarize(nav, frame, parent["combined"])
            output[role][scenario]["execution"] = parent["futures"]
            output[role][scenario]["attribution_resolution"] = (
                "annual_from_frozen_futures_summary_and_order_costs"
            )
            output[role][scenario]["misnamed_exact_futures_nav_contains_collateral"] = True
            curves[f"{role}_{scenario}"] = nav
        close(
            ledger[f"{mode}_stress_combined_nav"],
            ledger[f"{mode}_execution_stress_combined_nav"],
            "execution_stress must equal frozen stress; not independent evidence",
        )
    monthly_levels = curves.resample("ME").last()
    monthly = monthly_levels.pct_change(fill_method=None).loc["2021-01-01":]
    require(len(monthly) == 60 and monthly.notna().all().all(), "monthly aligned coverage")
    comparisons = {}
    for scenario in SCENARIOS:
        names = [f"{r}_{scenario}" for r in output]
        part = monthly[names]
        bad = part[f"v49_{scenario}"].lt(0)

        def nullable(value: float) -> float | None:
            return float(value) if np.isfinite(value) else None

        comparisons[scenario] = dict(
            monthly_return_correlation={
                k: {j: nullable(v) for j, v in col.items()}
                for k, col in part.corr().to_dict().items()
            },
            v49_negative_months=int(bad.sum()),
            observed_mean_return_in_v49_negative_months={
                k: nullable(v) for k, v in part.loc[bad].mean().items()
            },
            paired_terminal_pnl_differences={
                "v49_minus_v39": output["v49"][scenario]["terminal_pnl_rub"]["total_pnl"]
                - output["v39"][scenario]["terminal_pnl_rub"]["total_pnl"],
                "v60_minus_v49": output["v60"][scenario]["terminal_pnl_rub"]["total_pnl"]
                - output["v49"][scenario]["terminal_pnl_rub"]["total_pnl"],
            },
            conditional_sample_is_ex_post_not_a_trading_rule=True,
            leverage_difference_is_not_an_independent_profit_engine=True,
        )
    return dict(
        curves=output,
        comparisons=comparisons,
        verdict="ATTRIBUTION_ONLY_NO_NEW_PROFITABILITY_OR_INDEPENDENT_VALIDATION",
        live_trading_allowed=False,
        parameter_search=False,
        protected_market_outcomes_read=False,
    ), curves


def report_text(result: dict[str, Any]) -> str:
    lines = [
        "# V63 frozen profit attribution",
        "",
        result["verdict"],
        "",
        "Reference capital: RUB 1,000,000. Accounting decomposition, not a new zero-cost backtest.",
        "V41/cash are normalized constructions; investor-specific execution remains unproved.",
        "",
        "| Curve / costs | CAGR | Futures gross | Futures costs | Futures idle "
        "| Cash net | Cash idle | Total PnL |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for role, scenarios in result["curves"].items():
        for scenario, item in scenarios.items():
            p = item["terminal_pnl_rub"]
            lines.append(
                f"| {role}/{scenario} | {item['common_clock_metrics']['cagr']:.4%} | "
                f"{p['futures_gross_pnl']:.2f} | "
                f"{p['futures_commissions'] + p['futures_slippage']:.2f} | "
                f"{p['modeled_futures_idle_income']:.2f} | {p['cash_carry_net_pnl']:.2f} | "
                f"{p['modeled_cash_sleeve_idle_income']:.2f} | {p['total_pnl']:.2f} |"
            )
    lines += [
        "",
        "V49/V60 exact_futures_nav includes collateral and must not be counted "
        "as a separate pure-futures curve.",
        "Annual V49/V60 components use frozen yearly futures returns "
        "and actual recorded order costs.",
        "Gross/net decomposition holds the recorded sizes fixed, "
        "and does not re-optimize or recompute fills.",
        "Correlations and bad-month conditional summaries are descriptive "
        "and cannot select a trading filter.",
        "All terminal equity is marked equity; this does not prove liquidation "
        "at those prices or broker-exact costs.",
    ]
    return "\n".join(lines) + "\n"


def run(
    cfg: dict[str, Any], paths: dict[str, dict[str, Path]], evidence: dict[str, Any], output: Path
) -> None:
    require(not output.exists(), "immutable output already exists")
    result, curves = build(paths)
    output.mkdir(parents=False, exist_ok=False)
    curves.rename_axis("session_date").reset_index().to_parquet(
        output / "aligned_curves.parquet", index=False
    )
    (output / "metrics.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8-sig"
    )
    (output / "report.md").write_text(report_text(result), encoding="utf-8-sig")
    identity = dict(
        protocol_sha256=cfg["config_sha256"],
        implementation_sha256=sha(Path(__file__)),
        inputs=evidence,
        checks_completed=True,
        artifacts={
            p.name: dict(sha256=sha(p), bytes=p.stat().st_size) for p in sorted(output.iterdir())
        },
    )
    (output / "identity.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8-sig"
    )


def audit(output: Path, cfg: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    identity = read_json(output / "identity.json")
    require(identity["protocol_sha256"] == cfg["config_sha256"], "audit config drift")
    require(identity["implementation_sha256"] == sha(Path(__file__)), "audit code drift")
    require(identity["inputs"] == evidence, "audit input identity drift")
    require(
        set(identity["artifacts"]) == {"aligned_curves.parquet", "metrics.json", "report.md"},
        "audit artifact set drift",
    )
    checks = 0
    for name, declaration in identity["artifacts"].items():
        p = safe_path(output, name)
        require(
            sha(p) == declaration["sha256"] and p.stat().st_size == declaration["bytes"],
            "output drift",
        )
        checks += 1
    result = read_json(output / "metrics.json")
    date_only = pd.read_parquet(output / "aligned_curves.parquet", columns=["session_date"])
    dated(date_only, "session_date")
    curves = pd.read_parquet(output / "aligned_curves.parquet").set_index("session_date")
    for role, scenarios in result["curves"].items():
        for scenario, item in scenarios.items():
            annual = item["annual_pnl_rub"]
            p = item["terminal_pnl_rub"]
            close(sum(p[c] for c in COMPONENTS), p["total_pnl"], "audit component sum")
            for component in (*COMPONENTS, "total_pnl"):
                close(sum(y[component] for y in annual.values()), p[component], "audit annual sum")
                checks += 1
            nav = curves[f"{role}_{scenario}"].to_numpy(dtype=float)
            close(CAPITAL * (nav[-1] - nav[0]), p["total_pnl"], "audit NAV conservation")
            returns = np.r_[0.0, nav[1:] / nav[:-1] - 1]
            std = float(np.std(returns, ddof=1))
            replay = dict(
                cagr=float(
                    (nav[-1] / nav[0]) ** (365.25 / (curves.index[-1] - curves.index[0]).days) - 1
                ),
                sharpe=float(np.mean(returns) / std * math.sqrt(252)) if std else 0.0,
                maximum_drawdown=float(max(1 - nav / np.maximum.accumulate(nav))),
            )
            for key, value in replay.items():
                close(value, item["common_clock_metrics"][key], "audit independent metric replay")
                checks += 1
            checks += 2
    return dict(
        all_passed=True,
        checks=checks,
        metrics_sha256=sha(output / "metrics.json"),
        identity_sha256=sha(output / "identity.json"),
        live_trading_allowed=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    require(os.name == "posix", "historical diagnostics run only on gpu-mlserver")
    cfg = protocol()
    paths, evidence = admit(cfg, Path("/srv/trading_lab_data"))
    output = (
        Path("/srv/trading_lab_data/runs")
        / f"v63_frozen_profit_attribution_v1_{cfg['config_sha256'][:8]}"
    )
    if args.preflight:
        print(json.dumps(dict(all_passed=True, inputs=evidence, outcomes_read=False)))
    elif args.run:
        run(cfg, paths, evidence, output)
        print(json.dumps(dict(output=str(output), audit=audit(output, cfg, evidence))))
    else:
        require(
            args.audit_directory.resolve() == output.resolve(), "wrong canonical audit directory"
        )
        print(json.dumps(audit(output, cfg, evidence)))


if __name__ == "__main__":
    main()
