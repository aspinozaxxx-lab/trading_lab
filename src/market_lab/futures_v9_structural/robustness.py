"""Independent, parameter-frozen robustness audit for the V9 structural proxy."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
import yaml


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def return_metrics(returns: pd.Series, *, observations_clock: bool = False) -> dict[str, float]:
    values = returns.dropna().astype(float)
    if values.empty:
        return {"observations": 0}
    equity = (1.0 + values).cumprod()
    if observations_clock:
        years = len(values) / 252.0
    else:
        years = max((values.index[-1] - values.index[0]).days / 365.25, 1.0 / 365.25)
    standard_deviation = float(values.std(ddof=1))
    drawdown = equity / equity.cummax() - 1.0
    return {
        "observations": int(len(values)),
        "total_return": float(equity.iloc[-1] - 1.0),
        "cagr": float(equity.iloc[-1] ** (1.0 / years) - 1.0),
        "sharpe": float(values.mean() / standard_deviation * np.sqrt(252.0))
        if standard_deviation > 0.0
        else math.nan,
        "annualized_volatility": standard_deviation * np.sqrt(252.0),
        "max_drawdown": float(drawdown.min()),
    }


class FrozenReplay:
    """Vectorized replay of the sealed portfolio equations on a fixed calendar."""

    def __init__(self, panel: pd.DataFrame, config: dict[str, Any]):
        self.panel = panel.copy()
        self.config = config
        minimum_assets = int(config["eligibility"]["minimum_daily_assets"])
        observed_counts = self.panel.groupby("trade_date")["asset_code"].nunique()
        self.dates = pd.DatetimeIndex(
            sorted(observed_counts.loc[observed_counts.ge(minimum_assets)].index)
        )
        self.assets = sorted(self.panel["asset_code"].astype(str).unique())
        self.volatility = self._wide("volatility")
        self.eligible = self._wide("eligible").eq(True)
        self.returns = self._wide("asset_return")
        self.observed = self._wide("active_contract").notna()
        self.roll = self._wide("roll_flag").eq(True)
        horizons = [int(value) for value in config["signals"]["momentum_horizons_sessions"]]
        self.signal_columns = {
            f"tsmom_{label}": f"signal_tsmom_{horizon}"
            for label, horizon in zip(("1m", "3m", "6m", "12m"), horizons, strict=True)
        }
        self.signal_columns.update(
            {
                "tsmom_multi": "signal_tsmom_multi",
                "risk_adjusted_momentum": "signal_risk_adjusted_momentum",
                "curve_carry": "signal_curve_carry",
                "carry_momentum_confirmation": "signal_carry_momentum_confirmation",
            }
        )
        self.signals = {
            strategy: self._wide(column) for strategy, column in self.signal_columns.items()
        }
        self.development_mask = (
            self.dates.to_series()
            .between(
                pd.Timestamp(config["dates"]["development_start"]),
                pd.Timestamp(config["dates"]["development_end"]),
            )
            .to_numpy()
        )

    def _wide(self, column: str) -> pd.DataFrame:
        return self.panel.pivot(index="trade_date", columns="asset_code", values=column).reindex(
            index=self.dates, columns=self.assets
        )

    def run(
        self,
        strategy: str,
        *,
        excluded_assets: tuple[str, ...] = (),
        execution_lag: int = 1,
        one_way_bps: float | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if execution_lag < 1:
            raise ValueError("execution_lag must preserve next-session causality")
        signal = self.signals[strategy].copy()
        eligible = self.eligible.copy()
        if excluded_assets:
            signal.loc[:, list(excluded_assets)] = np.nan
            eligible.loc[:, list(excluded_assets)] = False
        valid = eligible & signal.notna() & self.volatility.gt(0.0)
        raw = (signal / self.volatility).where(valid)
        raw_gross = raw.abs().sum(axis=1)
        target = raw.div(raw_gross.replace(0.0, np.nan), axis=0).clip(
            -float(self.config["portfolio"]["single_asset_cap"]),
            float(self.config["portfolio"]["single_asset_cap"]),
        )
        target = target.fillna(0.0)
        estimated_volatility = np.sqrt(np.square(target * self.volatility.fillna(0.0)).sum(axis=1))
        volatility_scale = (
            (
                float(self.config["portfolio"]["volatility_target_annualized"])
                / estimated_volatility.replace(0.0, np.nan)
            )
            .clip(upper=1.0)
            .fillna(1.0)
        )
        target = target.mul(volatility_scale, axis=0)
        target_gross = target.abs().sum(axis=1)
        gross_scale = (
            (float(self.config["portfolio"]["gross_cap"]) / target_gross.replace(0.0, np.nan))
            .clip(upper=1.0)
            .fillna(1.0)
        )
        target = target.mul(gross_scale, axis=0)
        target.loc[
            valid.sum(axis=1).lt(int(self.config["eligibility"]["minimum_daily_assets"])), :
        ] = 0.0
        weeks = target.index.to_period("W-SUN")
        rebalance_dates = (
            pd.Series(target.index, index=target.index).groupby(weeks).max().to_numpy()
        )
        desired = target.copy()
        desired.loc[~desired.index.isin(rebalance_dates), :] = np.nan
        desired = desired.ffill().fillna(0.0)
        held = desired.shift(execution_lag).fillna(0.0)
        gross_contribution = held * self.returns.fillna(0.0)
        regular_turnover = desired.diff().abs().fillna(0.0)
        roll_turnover = 2.0 * desired.abs() * self.roll.astype(float)
        asset_turnover = (regular_turnover + roll_turnover).shift(execution_lag).fillna(0.0)
        bps = (
            float(self.config["costs"]["primary_one_way_bps"])
            if one_way_bps is None
            else float(one_way_bps)
        )
        net_contribution = gross_contribution - asset_turnover * bps / 10_000.0
        silent_missing = held.abs() * self.returns.isna()
        ledger = pd.DataFrame(
            {
                "gross_return": gross_contribution.sum(axis=1),
                "turnover": asset_turnover.sum(axis=1),
                "cost": asset_turnover.sum(axis=1) * bps / 10_000.0,
                "net_return": net_contribution.sum(axis=1),
                "gross_exposure": held.abs().sum(axis=1),
                "net_exposure": held.sum(axis=1),
                "positions": held.ne(0.0).sum(axis=1),
                "silent_missing_exposure": silent_missing.sum(axis=1),
            },
            index=self.dates,
        )
        return (
            ledger.loc[self.development_mask].copy(),
            net_contribution.loc[self.development_mask].copy(),
            asset_turnover.loc[self.development_mask].copy(),
        )


def block_bootstrap(
    returns: np.ndarray,
    *,
    replications: int,
    block_sessions: int,
    seed: int,
    elapsed_years: float,
) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    n = len(values)
    blocks = int(math.ceil(n / block_sessions))
    rng = np.random.default_rng(seed)
    cagr_values = np.empty(replications, dtype=float)
    sharpe_values = np.empty(replications, dtype=float)
    completed = 0
    batch_size = 500
    offsets = np.arange(block_sessions, dtype=np.int64)
    while completed < replications:
        size = min(batch_size, replications - completed)
        starts = rng.integers(0, n, size=(size, blocks, 1), dtype=np.int64)
        indices = (starts + offsets.reshape(1, 1, -1)) % n
        samples = values[indices.reshape(size, -1)[:, :n]]
        log_growth = np.log1p(samples).sum(axis=1)
        cagr_values[completed : completed + size] = np.expm1(log_growth / elapsed_years)
        standard_deviation = samples.std(axis=1, ddof=1)
        sharpe_values[completed : completed + size] = (
            samples.mean(axis=1) / standard_deviation * np.sqrt(252.0)
        )
        completed += size
    return {
        "cagr_ci_low": float(np.quantile(cagr_values, 0.025)),
        "cagr_ci_high": float(np.quantile(cagr_values, 0.975)),
        "sharpe_ci_low": float(np.quantile(sharpe_values, 0.025)),
        "sharpe_ci_high": float(np.quantile(sharpe_values, 0.975)),
        "probability_sharpe_lte_zero": float(np.mean(sharpe_values <= 0.0)),
    }


def deflated_sharpe_probability(returns: pd.Series, trials: int) -> dict[str, float]:
    values = returns.to_numpy(dtype=float)
    n = len(values)
    daily_sharpe = float(values.mean() / values.std(ddof=1))
    euler_gamma = 0.5772156649015329
    normal = NormalDist()
    expected_max_z = (1.0 - euler_gamma) * normal.inv_cdf(1.0 - 1.0 / trials) + (
        euler_gamma * normal.inv_cdf(1.0 - 1.0 / (trials * math.e))
    )
    benchmark = expected_max_z / math.sqrt(n - 1.0)
    skewness = float(pd.Series(values).skew())
    pearson_kurtosis = float(pd.Series(values).kurt()) + 3.0
    denominator = math.sqrt(
        max(
            1.0 - skewness * daily_sharpe + ((pearson_kurtosis - 1.0) / 4.0) * daily_sharpe**2,
            1e-12,
        )
    )
    z_score = (daily_sharpe - benchmark) * math.sqrt(n - 1.0) / denominator
    return {
        "expected_max_null_sharpe_annualized": benchmark * math.sqrt(252.0),
        "deflated_sharpe_probability": normal.cdf(z_score),
        "deflated_sharpe_z": z_score,
    }


def cscv_warning(return_frame: pd.DataFrame, segments: int) -> dict[str, Any]:
    blocks = np.array_split(np.arange(len(return_frame)), segments)
    strategies = list(return_frame.columns)
    below_median = []
    selected_oos_nonpositive = []
    selected_oos_sharpes = []
    selections = {strategy: 0 for strategy in strategies}
    for chosen in itertools.combinations(range(segments), segments // 2):
        in_sample = np.concatenate([blocks[index] for index in chosen])
        out_sample = np.concatenate(
            [blocks[index] for index in range(segments) if index not in chosen]
        )
        train = return_frame.iloc[in_sample]
        test = return_frame.iloc[out_sample]
        train_sharpe = train.mean() / train.std(ddof=1) * np.sqrt(252.0)
        test_sharpe = test.mean() / test.std(ddof=1) * np.sqrt(252.0)
        winner = str(train_sharpe.idxmax())
        selections[winner] += 1
        winner_oos = float(test_sharpe[winner])
        selected_oos_sharpes.append(winner_oos)
        below_median.append(winner_oos <= float(test_sharpe.median()))
        selected_oos_nonpositive.append(winner_oos <= 0.0)
    return {
        "splits": len(below_median),
        "pbo_style_probability_selected_below_candidate_median": float(np.mean(below_median)),
        "probability_selected_oos_sharpe_lte_zero": float(np.mean(selected_oos_nonpositive)),
        "median_selected_oos_sharpe": float(np.median(selected_oos_sharpes)),
        "selection_counts": selections,
        "warning": (
            "CSCV reuses the same 2021-2025 development sample; it is not an independent holdout."
        ),
    }


def exact_terminal_contributions(net_contribution: pd.DataFrame) -> pd.Series:
    portfolio_return = net_contribution.sum(axis=1)
    prior_equity = (1.0 + portfolio_return).cumprod().shift(1).fillna(1.0)
    return net_contribution.mul(prior_equity, axis=0).sum(axis=0)


def run_audit(audit_config_path: Path, output_root: Path) -> Path:
    audit_config = yaml.safe_load(audit_config_path.read_text(encoding="utf-8-sig"))
    run_dir = Path(audit_config["canonical_run"]).resolve()
    canonical = json.loads((run_dir / "results.json").read_text(encoding="utf-8-sig"))
    identity = json.loads((run_dir / "run_identity.json").read_text(encoding="utf-8-sig"))
    project_root = Path.cwd().resolve()
    config_path = project_root / "configs/futures_v9_structural.yaml"
    source_manifest_path = Path(canonical["source_manifest"])
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, Any] = {
        "config": sha256_file(config_path) == identity["config_sha256"],
        "source_manifest": sha256_file(source_manifest_path) == identity["source_manifest_sha256"],
        "history": sha256_file(Path(source_manifest["artifacts"]["contract_history"]["path"]))
        == identity["history_sha256"],
    }
    for name, expected in identity["implementation_sha256"].items():
        checks[f"implementation_{name}"] = (
            sha256_file(project_root / "src/market_lab/futures_v9_structural" / name) == expected
        )
    checks["panel"] = (
        sha256_file(run_dir / canonical["panel"]["path"]) == canonical["panel"]["sha256"]
    )
    for strategy, record in canonical["ledgers"].items():
        checks[f"ledger_{strategy}"] = sha256_file(run_dir / record["path"]) == record["sha256"]
    if not all(checks.values()):
        raise ValueError(f"canonical identity mismatch: {checks}")
    panel = pd.read_parquet(run_dir / canonical["panel"]["path"])
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    forbidden = pd.Timestamp(audit_config["forbidden_from"])
    if panel["trade_date"].ge(forbidden).any():
        raise ValueError("audit input contains 2026+")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    replay = FrozenReplay(panel, config)
    tolerance = float(audit_config["replay_absolute_tolerance"])
    strategies = list(replay.signal_columns)
    families = {key: tuple(value) for key, value in audit_config["families"].items()}
    configured_assets = sorted(asset for assets in families.values() for asset in assets)
    if configured_assets != replay.assets:
        raise ValueError("audit family map does not exactly cover the canonical universe")

    base_ledgers: dict[str, pd.DataFrame] = {}
    base_contributions: dict[str, pd.DataFrame] = {}
    attribution_records: list[dict[str, Any]] = []
    year_records: list[dict[str, Any]] = []
    year_asset_records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    bootstrap_records: list[dict[str, Any]] = []
    return_frame = pd.DataFrame(index=replay.dates[replay.development_mask])
    for strategy_index, strategy in enumerate(strategies):
        ledger, net_contribution, asset_turnover = replay.run(strategy)
        stored = pd.read_parquet(run_dir / canonical["ledgers"][strategy]["path"]).set_index(
            "trade_date"
        )
        stored.index = pd.to_datetime(stored.index)
        replay_error = {
            "gross_return": float((ledger["gross_return"] - stored["gross_return"]).abs().max()),
            "turnover": float((ledger["turnover"] - stored["turnover"]).abs().max()),
            "primary_net_return": float(
                (ledger["net_return"] - stored["primary_net_return"]).abs().max()
            ),
        }
        if max(replay_error.values()) > tolerance:
            raise ValueError(f"independent replay mismatch for {strategy}: {replay_error}")
        base_ledgers[strategy] = ledger
        base_contributions[strategy] = net_contribution
        return_frame[strategy] = ledger["net_return"]
        terminal = exact_terminal_contributions(net_contribution)
        family_terminal = {
            family: float(terminal.loc[list(assets)].sum()) for family, assets in families.items()
        }
        positive_total = float(terminal.clip(lower=0.0).sum())
        absolute_total = float(terminal.abs().sum())
        top_asset = str(terminal.idxmax())
        top_family = max(family_terminal, key=family_terminal.get)
        ruble_energy = tuple(audit_config["ruble_energy_scope"])
        ruble_energy_contribution = float(terminal.loc[list(ruble_energy)].sum())
        metrics = return_metrics(ledger["net_return"])
        without_2022 = return_metrics(
            ledger.loc[ledger.index.year != 2022, "net_return"], observations_clock=True
        )
        without_each_year = {
            str(year): return_metrics(
                ledger.loc[ledger.index.year != year, "net_return"],
                observations_clock=True,
            )
            for year in sorted(set(ledger.index.year))
        }
        total_cost = float(ledger["cost"].sum())
        gross_metrics = return_metrics(ledger["gross_return"])
        cost_drag_cagr = gross_metrics["cagr"] - metrics["cagr"]
        active_assets = [
            asset for asset in replay.assets if float(asset_turnover[asset].sum()) > 1e-14
        ]
        summary[strategy] = {
            "canonical_primary": metrics,
            "replay_max_absolute_error": replay_error,
            "gross_cagr": gross_metrics["cagr"],
            "cost_drag_cagr": cost_drag_cagr,
            "total_cost_arithmetic": total_cost,
            "annualized_turnover": float(ledger["turnover"].mean() * 252.0),
            "average_gross": float(ledger["gross_exposure"].mean()),
            "average_net": float(ledger["net_exposure"].mean()),
            "assets_with_nonzero_turnover": len(active_assets),
            "assets_never_traded": sorted(set(replay.assets) - set(active_assets)),
            "silent_missing_sessions": int(ledger["silent_missing_exposure"].gt(0.0).sum()),
            "maximum_silent_missing_exposure": float(ledger["silent_missing_exposure"].max()),
            "without_2022": without_2022,
            "without_each_year": without_each_year,
            "top_asset": top_asset,
            "top_asset_terminal_contribution": float(terminal[top_asset]),
            "top_asset_share_of_positive_contribution": float(terminal[top_asset] / positive_total)
            if positive_total > 0.0
            else math.nan,
            "top_asset_share_of_absolute_contribution": float(
                abs(terminal[top_asset]) / absolute_total
            )
            if absolute_total > 0.0
            else math.nan,
            "top_family": top_family,
            "top_family_terminal_contribution": family_terminal[top_family],
            "top_family_share_of_positive_contribution": float(
                family_terminal[top_family]
                / sum(max(value, 0.0) for value in family_terminal.values())
            ),
            "ruble_energy_scope": list(ruble_energy),
            "ruble_energy_terminal_contribution": ruble_energy_contribution,
            "ruble_energy_share_of_positive_contribution": float(
                ruble_energy_contribution / positive_total
            )
            if positive_total > 0.0
            else math.nan,
        }
        for asset in replay.assets:
            attribution_records.append(
                {
                    "strategy": strategy,
                    "asset": asset,
                    "family": next(
                        family for family, members in families.items() if asset in members
                    ),
                    "terminal_net_contribution": float(terminal[asset]),
                    "arithmetic_net_contribution": float(net_contribution[asset].sum()),
                    "gross_contribution": float(
                        (net_contribution[asset] + asset_turnover[asset] * 5.0 / 10_000.0).sum()
                    ),
                    "allocated_cost": float(asset_turnover[asset].sum() * 5.0 / 10_000.0),
                }
            )
        for year, group in net_contribution.groupby(net_contribution.index.year):
            year_terminal = exact_terminal_contributions(group)
            year_return = float((1.0 + group.sum(axis=1)).prod() - 1.0)
            year_records.append(
                {
                    "strategy": strategy,
                    "year": int(year),
                    "compounded_return": year_return,
                    "sum_asset_contributions": float(year_terminal.sum()),
                }
            )
            for asset in replay.assets:
                year_asset_records.append(
                    {
                        "strategy": strategy,
                        "year": int(year),
                        "asset": asset,
                        "family": next(
                            family for family, members in families.items() if asset in members
                        ),
                        "compounded_return_contribution": float(year_terminal[asset]),
                    }
                )
        elapsed_years = max((ledger.index[-1] - ledger.index[0]).days / 365.25, 1.0 / 365.25)
        bootstrap_records.append(
            {
                "strategy": strategy,
                **block_bootstrap(
                    ledger["net_return"].to_numpy(),
                    replications=int(audit_config["bootstrap"]["replications"]),
                    block_sessions=int(audit_config["bootstrap"]["block_sessions"]),
                    seed=int(audit_config["bootstrap"]["seed"]) + strategy_index,
                    elapsed_years=elapsed_years,
                ),
                **deflated_sharpe_probability(
                    ledger["net_return"], int(audit_config["cscv"]["fixed_candidates"])
                ),
            }
        )

    leave_asset_records = []
    for strategy in strategies:
        baseline = summary[strategy]["canonical_primary"]
        for asset in replay.assets:
            ledger, _, _ = replay.run(strategy, excluded_assets=(asset,))
            metrics = return_metrics(ledger["net_return"])
            leave_asset_records.append(
                {
                    "strategy": strategy,
                    "excluded_asset": asset,
                    **metrics,
                    "cagr_delta": metrics["cagr"] - baseline["cagr"],
                    "sharpe_delta": metrics["sharpe"] - baseline["sharpe"],
                }
            )
    leave_family_records = []
    for strategy in strategies:
        baseline = summary[strategy]["canonical_primary"]
        for family, assets in families.items():
            ledger, _, _ = replay.run(strategy, excluded_assets=assets)
            metrics = return_metrics(ledger["net_return"])
            leave_family_records.append(
                {
                    "strategy": strategy,
                    "excluded_family": family,
                    "excluded_assets": ",".join(assets),
                    **metrics,
                    "cagr_delta": metrics["cagr"] - baseline["cagr"],
                    "sharpe_delta": metrics["sharpe"] - baseline["sharpe"],
                }
            )

    scenario_records = []
    for strategy in strategies:
        delayed, _, _ = replay.run(
            strategy,
            execution_lag=1 + int(audit_config["extra_execution_delay_sessions"]),
        )
        stressed, _, _ = replay.run(
            strategy, one_way_bps=float(audit_config["cost_stress_one_way_bps"])
        )
        for scenario, ledger in (("one_session_delayed", delayed), ("20bps_one_way", stressed)):
            scenario_records.append(
                {"strategy": strategy, "scenario": scenario, **return_metrics(ledger["net_return"])}
            )

    correlations = return_frame.corr()
    cscv = cscv_warning(return_frame, int(audit_config["cscv"]["contiguous_segments"]))
    attribution = pd.DataFrame(attribution_records)
    leave_asset = pd.DataFrame(leave_asset_records)
    leave_family = pd.DataFrame(leave_family_records)
    scenarios = pd.DataFrame(scenario_records)
    bootstrap = pd.DataFrame(bootstrap_records)
    years = pd.DataFrame(year_records)
    year_assets = pd.DataFrame(year_asset_records)

    audit_identity = {
        "canonical_run_id": canonical["run_id"],
        "canonical_results_sha256": sha256_file(run_dir / "results.json"),
        "audit_config_sha256": sha256_file(audit_config_path),
        "audit_implementation_sha256": sha256_file(Path(__file__)),
    }
    audit_run_id = hashlib.sha256(canonical_json(audit_identity)).hexdigest()[:16]
    output = output_root / f"robustness_{audit_run_id}"
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "asset_attribution.csv": attribution,
        "year_attribution.csv": years,
        "year_asset_attribution.csv": year_assets,
        "leave_one_asset.csv": leave_asset,
        "leave_one_family.csv": leave_family,
        "scenarios.csv": scenarios,
        "bootstrap.csv": bootstrap,
        "correlations.csv": correlations.reset_index(names="strategy"),
    }
    artifact_records = {}
    for name, frame in artifacts.items():
        path = output / name
        frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.12g")
        artifact_records[name] = {"sha256": sha256_file(path), "rows": len(frame)}
    result = {
        "research_only": True,
        "verdict_scope": "promotion to exact-execution validation only, never live trading",
        "identity": audit_identity,
        "canonical_checks": checks,
        "input_maximum_date": str(panel["trade_date"].max()),
        "input_has_2026_or_later": False,
        "strategies": summary,
        "correlations": correlations.round(6).to_dict(),
        "cscv": cscv,
        "artifacts": artifact_records,
        "limitations": [
            (
                "Signals use the official close and the proxy earns the immediately following "
                "close-to-close return, which assumes an unattainable same-close fill after the "
                "signal is known."
            ),
            (
                "Daily close/settlement data cannot represent intraday limit locks, bid-ask "
                "spread, queue priority, partial fills, or evening-session timing."
            ),
            (
                "Costs are flat bps on fractional notional; contract multipliers, ticks, integer "
                "lots, margin, collateral yield, commissions, and market impact are absent."
            ),
            "The union-of-observations calendar is not an exact exchange/session calendar.",
            (
                "Missing held-asset returns are filled with zero; the canonical missing-exposure "
                "check ignores rows where the current active contract itself is absent."
            ),
            (
                "CSCV and the deflated Sharpe calculation reuse the 2021-2025 development sample "
                "and are warnings, not independent confirmation."
            ),
        ],
    }
    result_path = output / "audit.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    artifact_records["audit.json"] = {"sha256": sha256_file(result_path)}
    identity_path = output / "audit_identity.json"
    identity_path.write_text(
        json.dumps(
            {**audit_identity, "audit_json_sha256": sha256_file(result_path)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output
