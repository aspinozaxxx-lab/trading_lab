"""Fixed A/B/C long-only execution test for the sealed v1 momentum score."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
import yaml

from market_lab.market_graph_v1.portfolio import (
    PortfolioResult,
    run_five_sleeve_backtest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = PROJECT_ROOT / "configs/market_graph_v2_long_only.yaml"
PROTOCOL_SHA256 = "50ff5688535b852a16b40e34aaf630935c9425259bdf45b3677d496aee554a01"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionInputs:
    """Target-free score and execution panel."""

    dates: np.ndarray
    tickers: tuple[str, ...]
    scores: np.ndarray
    current_mask: np.ndarray
    raw_open: np.ndarray


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    path = path.resolve()
    if path != PROTOCOL_PATH.resolve():
        raise ValueError("v2 accepts only its canonical sealed protocol")
    actual = sha256_file(path)
    if actual != PROTOCOL_SHA256:
        raise ValueError(f"v2 protocol SHA mismatch: {actual}")
    declared = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if declared != actual:
        raise ValueError("v2 protocol sidecar mismatch")
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def load_execution_inputs(config: dict[str, Any]) -> ExecutionInputs:
    """Read only the sealed score and target-free execution columns."""
    sealed = config["sealed_inputs"]
    score_path = (PROJECT_ROOT / sealed["score_path"]).resolve()
    manifest_path = (PROJECT_ROOT / sealed["source_v1_manifest_path"]).resolve()
    panel_path = (PROJECT_ROOT / sealed["execution_panel_path"]).resolve()
    identities = (
        (score_path, sealed["score_sha256"]),
        (manifest_path, sealed["source_v1_manifest_sha256"]),
        (panel_path, sealed["execution_panel_sha256"]),
    )
    for path, expected in identities:
        if sha256_file(path) != expected:
            raise ValueError(f"sealed input SHA mismatch: {path}")
    score = pd.read_parquet(
        score_path,
        columns=["session_date", "ticker", sealed["score_column"]],
    )
    panel = pd.read_parquet(
        panel_path,
        columns=["session_date", "ticker", "raw_open", "daily_available"],
    )
    for frame in (score, panel):
        frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        if frame.duplicated(["session_date", "ticker"]).any():
            raise ValueError("duplicate session_date/ticker in v2 input")
    dates = np.array(sorted(panel["session_date"].unique()), dtype="datetime64[ns]")
    tickers = tuple(sorted(panel["ticker"].unique()))
    if dates[-1] >= np.datetime64("2026-01-01"):
        raise ValueError("v2 execution panel crossed protected 2026 boundary")
    full_index = pd.MultiIndex.from_product(
        [pd.to_datetime(dates), tickers], names=["session_date", "ticker"]
    )
    ordered_panel = panel.set_index(["session_date", "ticker"]).reindex(full_index)
    shape = (len(dates), len(tickers))
    raw_open = pd.to_numeric(ordered_panel["raw_open"], errors="coerce").to_numpy()
    raw_open = raw_open.reshape(shape).astype(np.float64)
    current_mask = ordered_panel["daily_available"].eq(1.0).to_numpy().reshape(shape)
    score_matrix = np.full(shape, np.nan, dtype=np.float64)
    date_lookup = {pd.Timestamp(value): index for index, value in enumerate(dates)}
    ticker_lookup = {ticker: index for index, ticker in enumerate(tickers)}
    for row in score.itertuples(index=False):
        score_matrix[date_lookup[pd.Timestamp(row.session_date)], ticker_lookup[row.ticker]] = (
            float(getattr(row, sealed["score_column"]))
        )
    minimum = np.datetime64(sealed["minimum_oos_date"])
    maximum = np.datetime64(sealed["maximum_date"])
    populated_dates = np.flatnonzero(np.isfinite(score_matrix).any(axis=1))
    if dates[populated_dates[0]] != minimum or dates[populated_dates[-1]] != maximum:
        raise ValueError("sealed score OOS date boundary mismatch")
    return ExecutionInputs(
        dates=dates,
        tickers=tickers,
        scores=score_matrix,
        current_mask=current_mask,
        raw_open=raw_open,
    )


def build_long_only_weights(
    inputs: ExecutionInputs,
    *,
    start_index: int,
    top_k: int | None,
    keep_rank: int | None,
) -> tuple[np.ndarray, dict[str, float]]:
    """Build five phase-specific target selections without reading returns or targets."""
    days, assets = inputs.scores.shape
    weights = np.zeros((days, assets), dtype=np.float64)
    phase_holdings: list[set[int]] = [set() for _ in range(5)]
    terminal_last_signal = days - 7
    signal_holding_counts: list[int] = []
    signal_hhi: list[float] = []
    for day in range(start_index, days):
        phase = (day - start_index) % 5
        valid = inputs.current_mask[day] & np.isfinite(inputs.scores[day])
        if day > terminal_last_signal:
            selected: list[int] = []
        elif top_k is None:
            selected = np.flatnonzero(valid).tolist()
        else:
            ranked = np.flatnonzero(valid)
            ranked = ranked[np.argsort(-inputs.scores[day, ranked], kind="mergesort")]
            rank_map = {int(asset): rank + 1 for rank, asset in enumerate(ranked)}
            retained = sorted(
                (
                    asset
                    for asset in phase_holdings[phase]
                    if asset in rank_map and rank_map[asset] <= int(keep_rank)
                ),
                key=rank_map.get,
            )
            selected = retained[:top_k]
            for asset in ranked:
                asset = int(asset)
                if len(selected) >= top_k:
                    break
                if asset not in selected:
                    selected.append(asset)
        phase_holdings[phase] = set(selected)
        if selected:
            allocation_count = len(selected) if top_k is None else top_k
            weights[day, selected] = 1.0 / allocation_count
            signal_holding_counts.append(len(selected))
            signal_hhi.append(float(np.square(weights[day]).sum()))
    return weights, {
        "average_signal_holdings": float(np.mean(signal_holding_counts)),
        "average_signal_hhi": float(np.mean(signal_hhi)),
        "maximum_signal_weight": float(np.max(weights)),
    }


def _realized_concentration(
    result: PortfolioResult,
    inputs: ExecutionInputs,
    stock_limit: float,
) -> dict[str, float]:
    """Replay net orders to measure realized aggregate holdings and HHI."""
    date_lookup = {pd.Timestamp(value): index for index, value in enumerate(inputs.dates)}
    ticker_lookup = {ticker: index for index, ticker in enumerate(inputs.tickers)}
    grouped = {
        pd.Timestamp(date): part for date, part in result.orders.groupby("session_date", sort=False)
    }
    quantities = np.zeros(len(inputs.tickers), dtype=np.float64)
    last_price = np.full(len(inputs.tickers), np.nan, dtype=np.float64)
    counts: list[int] = []
    hhi_values: list[float] = []
    maximum_tradable_weight = 0.0
    maximum_locked_weight = 0.0
    tradable_breaches = 0
    locked_breaches = 0
    equity_lookup = result.ledger.set_index("session_date")["equity"].astype(float)
    for date in pd.to_datetime(result.ledger["session_date"]):
        index = date_lookup[pd.Timestamp(date)]
        current = inputs.raw_open[index]
        available = np.isfinite(current) & (current > 0.0)
        last_price[available] = current[available]
        orders = grouped.get(pd.Timestamp(date))
        if orders is not None:
            for row in orders.itertuples(index=False):
                asset = ticker_lookup[row.ticker]
                quantities[asset] += float(row.signed_notional) / current[asset]
        values = np.where(np.isfinite(last_price), quantities * last_price, 0.0)
        absolute = np.abs(values)
        gross = float(absolute.sum())
        equity = float(equity_lookup.loc[pd.Timestamp(date)])
        stock_weights = absolute / equity
        if available.any():
            maximum_tradable_weight = max(
                maximum_tradable_weight, float(stock_weights[available].max())
            )
            tradable_breaches += int(
                np.count_nonzero(stock_weights[available] > stock_limit + 1e-8)
            )
        if (~available).any():
            maximum_locked_weight = max(
                maximum_locked_weight, float(stock_weights[~available].max())
            )
            locked_breaches += int(np.count_nonzero(stock_weights[~available] > stock_limit + 1e-8))
        counts.append(int(np.count_nonzero(absolute > 1e-6)))
        hhi_values.append(float(np.square(absolute / gross).sum()) if gross > 0.0 else 0.0)
    return {
        "average_realized_holdings": float(np.mean(counts)),
        "maximum_realized_holdings": int(max(counts)),
        "average_realized_hhi": float(np.mean(hhi_values)),
        "maximum_realized_hhi": float(max(hhi_values)),
        "maximum_tradable_stock_weight": maximum_tradable_weight,
        "maximum_locked_stock_weight": maximum_locked_weight,
        "tradable_stock_cap_breach_count": tradable_breaches,
        "locked_untradable_stock_cap_breach_count": locked_breaches,
    }


def _passive_relationship(
    candidate: PortfolioResult,
    passive: PortfolioResult,
) -> dict[str, Any]:
    candidate_returns = candidate.ledger.set_index("session_date")["net_return"].astype(float)
    passive_returns = passive.ledger.set_index("session_date")["net_return"].astype(float)
    aligned = pd.concat(
        [candidate_returns.rename("candidate"), passive_returns.rename("passive")], axis=1
    ).dropna()
    passive_variance = float(aligned["passive"].var(ddof=1))
    covariance = float(aligned.cov().loc["candidate", "passive"])
    beta = covariance / passive_variance if passive_variance > 1e-16 else 0.0
    correlation = float(aligned.corr().loc["candidate", "passive"])
    yearly_excess = {
        year: float(candidate.yearly_returns.get(year, 0.0) - passive.yearly_returns.get(year, 0.0))
        for year in sorted(set(candidate.yearly_returns) | set(passive.yearly_returns))
    }
    return {
        "passive_beta": beta,
        "passive_correlation": correlation,
        "excess_cagr_vs_passive": float(
            candidate.metrics["net_cagr"] - passive.metrics["net_cagr"]
        ),
        "yearly_excess_vs_passive": yearly_excess,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _manifest(run_dir: Path) -> dict[str, Any]:
    return {
        "files": {
            path.relative_to(run_dir).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        }
    }


def run_experiment(output: Path | None = None) -> Path:
    """Run all and only the three sealed execution candidates."""
    started = perf_counter()
    config = load_protocol()
    inputs = load_execution_inputs(config)
    oos = np.isfinite(inputs.scores).any(axis=1)
    first_oos = int(np.flatnonzero(oos)[0])
    run_id = datetime.now(UTC).strftime("market_graph_v2_long_only_%Y%m%dT%H%M%SZ")
    run_dir = (output or PROJECT_ROOT / "runs" / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(
        run_dir / "preflight.json",
        {
            "protocol_sha256": PROTOCOL_SHA256,
            "score_sha256": config["sealed_inputs"]["score_sha256"],
            "execution_panel_sha256": config["sealed_inputs"]["execution_panel_sha256"],
            "score_training_or_modification": False,
            "score_columns_read": ["session_date", "ticker", "relative_momentum_score"],
            "target_columns_read": [],
            "minimum_oos_date": str(pd.Timestamp(inputs.dates[first_oos]).date()),
            "maximum_date": str(pd.Timestamp(inputs.dates[-1]).date()),
            "protected_2026_read": False,
            "candidates": [candidate["name"] for candidate in config["candidates"]],
        },
    )

    portfolio_dir = run_dir / "portfolio"
    portfolio_dir.mkdir()
    weights_by_name: dict[str, np.ndarray] = {}
    concentration_by_name: dict[str, dict[str, float]] = {}
    for candidate in config["candidates"]:
        name = candidate["name"]
        if name == "passive_all_valid_equal_weight":
            top_k = None
            keep_rank = None
        elif name == "relative_momentum_long_top5_keep10":
            top_k, keep_rank = 5, 10
        elif name == "relative_momentum_long_top10_keep15":
            top_k, keep_rank = 10, 15
        else:
            raise ValueError(f"unexpected sealed candidate: {name}")
        weights, concentration = build_long_only_weights(
            inputs,
            start_index=first_oos,
            top_k=top_k,
            keep_rank=keep_rank,
        )
        weights_by_name[name] = weights
        concentration_by_name[name] = concentration
        np.save(portfolio_dir / f"{name}_signal_weights.npy", weights.astype(np.float32))

    execution = config["execution"]
    results: dict[str, dict[str, PortfolioResult]] = {}
    for name, weights in weights_by_name.items():
        results[name] = {}
        maximum = next(
            float(candidate["maximum_single_stock_absolute_weight"])
            for candidate in config["candidates"]
            if candidate["name"] == name
        )
        for label, multiplier in (
            ("base_cost", 1.0),
            ("double_cost", float(execution["stress_cost_multiplier"])),
        ):
            result = run_five_sleeve_backtest(
                inputs.dates,
                inputs.tickers,
                inputs.raw_open,
                weights,
                start_index=first_oos,
                initial_capital=float(execution["initial_capital_rub"]),
                one_way_cost_bps=float(execution["one_way_commission_bps"])
                + float(execution["one_way_slippage_bps"]),
                short_borrow_rate_annual=0.0,
                cost_multiplier=multiplier,
                maximum_stock_weight=maximum,
            )
            results[name][label] = result
            result.ledger.to_csv(portfolio_dir / f"{name}_{label}_ledger.csv", index=False)
            result.orders.to_csv(portfolio_dir / f"{name}_{label}_orders.csv", index=False)

    passive_name = "passive_all_valid_equal_weight"
    metrics: dict[str, Any] = {}
    for name, cost_results in results.items():
        metrics[name] = {}
        maximum = next(
            float(candidate["maximum_single_stock_absolute_weight"])
            for candidate in config["candidates"]
            if candidate["name"] == name
        )
        for label, result in cost_results.items():
            passive = results[passive_name][label]
            relation = _passive_relationship(result, passive)
            concentration = {
                **concentration_by_name[name],
                **_realized_concentration(result, inputs, maximum),
            }
            corrected_metrics = dict(result.metrics)
            corrected_metrics["signal_weight_limit_breach"] = bool(
                concentration["maximum_signal_weight"] > maximum + 1e-8
            )
            corrected_metrics["configured_stock_weight_limit"] = maximum
            corrected_metrics["tradable_stock_limit_breach"] = bool(
                concentration["tradable_stock_cap_breach_count"] > 0
            )
            corrected_metrics["locked_untradable_stock_limit_breach"] = bool(
                concentration["locked_untradable_stock_cap_breach_count"] > 0
            )
            rejected = False
            reasons: list[str] = []
            if name != passive_name:
                if float(result.metrics["net_cagr"]) <= 0.0:
                    rejected = True
                    reasons.append("net_cagr_not_positive")
                if relation["passive_beta"] >= 0.80 and relation["excess_cagr_vs_passive"] <= 0.0:
                    rejected = True
                    reasons.append("passive_beta_without_positive_excess_cagr")
            metrics[name][label] = {
                **corrected_metrics,
                "yearly_returns": result.yearly_returns,
                **relation,
                **concentration,
                "rejected": rejected,
                "rejection_reasons": reasons,
            }
    payload = {
        "research_status": "POST_IC_EXPLORATORY_NO_SELECTION_CLAIM_NO_LIVE_TRADING",
        "score_retrained_or_modified": False,
        "oos_dates": int(oos.sum()),
        "candidates": metrics,
        "elapsed_seconds": perf_counter() - started,
    }
    _write_json(run_dir / "metrics.json", payload)
    _write_json(
        run_dir / "code_identity.json",
        {
            "experiment.py": sha256_file(Path(__file__)),
            "reused_strict_portfolio.py": sha256_file(
                PROJECT_ROOT / "src/market_lab/market_graph_v1/portfolio.py"
            ),
        },
    )
    _write_json(run_dir / "manifest.json", _manifest(run_dir))
    print(json.dumps({"run_dir": str(run_dir), "metrics": payload}, default=str))
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sealed long-only market-graph v2")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_experiment(output=args.output)


if __name__ == "__main__":
    main()
