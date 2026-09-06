"""Synthetic accounting, temporal admission and immutable-output checks for V63."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v63_profit_attribution as v63


def test_sealed_protocol_identity_and_closed_input_set():
    config = v63.protocol()
    assert config["implementation_sha256"] == v63.sha(Path(v63.__file__))
    assert set(config["inputs"]) == {"v39", "cash", "v41", "v49", "v60"}
    assert config["live_trading_allowed"] is False
    assert config["parameter_search"] is False


@pytest.fixture
def synthetic(monkeypatch):
    dates = pd.bdate_range(v63.START, v63.END)
    cash_dates = pd.date_range(v63.START, v63.END)
    frames, metrics = {}, {r: {"scenarios": {}} for r in ("v39", "cash", "v41", "v49", "v60")}
    paths = {r: {"metrics.json": Path(r)} for r in metrics}
    base_returns = np.where(
        dates.year >= 2021, 0.0004 + 0.003 * np.sin(np.arange(len(dates)) / 24), 0
    )
    v41_frame, cash_frame = pd.DataFrame(index=dates), pd.DataFrame(index=cash_dates)
    leader_frames = {r: pd.DataFrame(index=dates) for r in ("v49", "v60")}
    leader_orders = {r: [] for r in leader_frames}
    leader_positions = {r: [] for r in leader_frames}
    for i, scenario in enumerate(v63.SCENARIOS):
        v39_combined = None
        for role, scale in (("v39", 1.0), ("v49", 2.0), ("v60", 1.5)):
            pure = pd.Series(np.cumprod(1 + base_returns * scale) * v63.CAPITAL, index=dates)
            net_change = pure.diff().fillna(0.0)
            fees, slip = pd.Series(0.0, index=dates), pd.Series(0.0, index=dates)
            fees.loc["2021-01-04"], slip.loc["2021-01-04"] = i + 1, 2 * (i + 1)
            income = pd.Series(np.where(dates.year >= 2021, 25.0 / scale, 0), index=dates)
            nav = (pure + income.cumsum()) / v63.CAPITAL
            futures = dict(
                starting_cash=v63.CAPITAL,
                ending_cash=float(pure.iloc[-1]),
                annual_returns=v63.performance(pure / v63.CAPITAL)["annual_returns"],
                variation_margin=float(net_change.sum() + fees.sum() + slip.sum()),
                commission_cost=float(fees.sum()),
                slippage_cost=float(slip.sum()),
                total_cost=float(fees.sum() + slip.sum()),
                filled_leg_count=1,
                execution_complete=True,
                critical_failure_count=0,
                unresolved_halt_count=0,
            )
            if role == "v39":
                frame = pd.DataFrame(
                    dict(
                        starting_cash=pure.shift().fillna(v63.CAPITAL),
                        ending_cash=pure,
                        variation_margin=net_change + fees + slip,
                        commission_cost=fees,
                        slippage_cost=slip,
                        collateral_interest_credited=income,
                        cumulative_collateral_interest=income.cumsum(),
                        combined_ending_equity=nav * v63.CAPITAL,
                    )
                )
                frames[(role, f"combined_ledger_{scenario}.parquet")] = frame.rename_axis(
                    "session_date"
                ).reset_index()
                metrics[role]["scenarios"][scenario] = dict(
                    combined=v63.performance(nav, 365.2425), futures_only=futures
                )
                v39_combined = nav
            else:
                mode = "double_risk" if role == "v49" else "equity_trend_risk"
                leader_frames[role][f"{mode}_{scenario}_combined_nav"] = nav
                leader_frames[role][f"{mode}_{scenario}_exact_futures_nav"] = nav
                if scenario == "stress":
                    leader_frames[role][f"{mode}_execution_stress_combined_nav"] = nav
                    leader_frames[role][f"{mode}_execution_stress_exact_futures_nav"] = nav
                leader_orders[role].append(
                    dict(
                        session_date=pd.Timestamp("2021-01-04"),
                        scenario=scenario,
                        filled=True,
                        commission_cost=i + 1,
                        slippage_cost=2 * (i + 1),
                        gross_notional=1000.0,
                        participation=0.001,
                    )
                )
                leader_positions[role].extend(
                    dict(session_date=v63.START, scenario=scenario, contracts=0) for _ in range(4)
                )
                metrics[role]["scenarios"][scenario] = dict(
                    combined=v63.performance(nav), futures=futures
                )
        cash_name = v63.CASH_MAP[scenario]
        ordinal = np.arange(len(cash_dates))
        cash_nav = pd.Series(1 + ordinal * 0.000015, index=cash_dates)
        cash_frame[f"overlay_{cash_name}_nav"] = cash_nav
        cash_frame[f"{cash_name}_cumulative_interest"] = ordinal * 0.00001
        cash_metrics = v63.performance(cash_nav)
        cash_metrics["sharpe"] *= np.sqrt(365.25 / 252)
        metrics["cash"]["scenarios"][cash_name] = dict(overlay=cash_metrics)
        v41_frame[f"v39_{scenario}_nav"] = v39_combined
        v41_frame[f"cash_carry_ruonia_{scenario}_nav"] = cash_nav.reindex(dates)
        combined = 0.8 * v39_combined + 0.2 * cash_nav.reindex(dates)
        v41_frame[f"combined_{scenario}_nav"] = combined
        metrics["v41"]["scenarios"][scenario] = dict(combined=v63.performance(combined))
    frames[("cash", "daily_ledger.parquet")] = cash_frame.rename_axis("date").reset_index()
    frames[("v41", "combined_ledger.parquet")] = v41_frame.rename_axis("session_date").reset_index()
    for role in leader_frames:
        frames[(role, "combined_ledger.parquet")] = (
            leader_frames[role].rename_axis("session_date").reset_index()
        )
        frames[(role, "orders.parquet")] = pd.DataFrame(leader_orders[role])
        frames[(role, "positions.parquet")] = pd.DataFrame(leader_positions[role])
    monkeypatch.setattr(
        v63, "load_frame", lambda _paths, role, filename: frames[(role, filename)].copy()
    )
    original = v63.read_json
    monkeypatch.setattr(
        v63,
        "read_json",
        lambda path: metrics[str(path)] if str(path) in metrics else original(path),
    )
    return paths, frames, metrics


def test_full_accounting_run_and_independent_audit(synthetic, tmp_path):
    paths, _, _ = synthetic
    output = tmp_path / "result"
    cfg, evidence = {"config_sha256": "a" * 64}, {"synthetic": True}
    v63.run(cfg, paths, evidence, output)
    audit = v63.audit(output, cfg, evidence)
    assert audit["all_passed"] and audit["checks"] == 183
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    assert payload["live_trading_allowed"] is False
    for role in ("v49", "v60"):
        item = payload["curves"][role]["primary"]
        assert item["misnamed_exact_futures_nav_contains_collateral"]
        assert item["terminal_pnl_rub"]["modeled_futures_idle_income"] > 0
    assert payload["curves"]["cash"]["primary"]["annual_pnl_rub"]["2020"]["total_pnl"] > 0
    with pytest.raises(ValueError, match="immutable"):
        v63.run(cfg, paths, evidence, output)
    (output / "report.md").write_text("changed", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="output drift"):
        v63.audit(output, cfg, evidence)


@pytest.mark.parametrize("role", ["v39", "v49", "v60"])
def test_corrupt_canonical_metrics_rejected(synthetic, role):
    paths, _, metrics = synthetic
    metrics[role]["scenarios"]["primary"]["combined"]["cagr"] += 0.01
    with pytest.raises(ValueError, match="canonical metric replay"):
        v63.build(paths)


def test_wrong_futures_terminal_summary_rejected(synthetic):
    paths, _, metrics = synthetic
    summary = metrics["v49"]["scenarios"]["primary"]["futures"]
    summary["ending_cash"] += 100
    with pytest.raises(ValueError, match="futures cash conservation"):
        v63.build(paths)


def test_missing_initial_flat_position_rejected(synthetic):
    paths, frames, _ = synthetic
    frames[("v49", "positions.parquet")] = frames[("v49", "positions.parquet")].iloc[1:]
    with pytest.raises(ValueError, match="initial position coverage"):
        v63.build(paths)


def test_v41_cash_weight_cannot_drift(synthetic):
    paths, frames, _ = synthetic
    frame = frames[("v41", "combined_ledger.parquet")]
    frame.loc[20, "combined_primary_nav"] += 0.01
    with pytest.raises(ValueError, match="fixed-weight replay"):
        v63.build(paths)


def test_recorded_costs_must_match_summary(synthetic):
    paths, frames, _ = synthetic
    frames[("v60", "orders.parquet")].loc[0, "commission_cost"] += 1
    with pytest.raises(ValueError, match="conservation"):
        v63.build(paths)


def test_annual_components_include_pre2021_cash_income(synthetic):
    paths, _, _ = synthetic
    result, curves = v63.build(paths)
    for role in ("cash", "v41"):
        item = result["curves"][role]["primary"]
        assert item["annual_pnl_rub"]["2020"]["modeled_cash_sleeve_idle_income"] > 0
        year_2020_end = curves.loc[curves.index.year == 2020, f"{role}_primary"].iloc[-1]
        year_2021_end = curves.loc[curves.index.year == 2021, f"{role}_primary"].iloc[-1]
        assert item["canonical_metrics"]["annual_returns"]["2021"] == pytest.approx(
            year_2021_end / year_2020_end - 1
        )


@pytest.mark.parametrize("bad_date", ["2026-01-01", "2027-01-01"])
def test_protected_dates_rejected(bad_date):
    with pytest.raises(ValueError, match="protected"):
        v63.dated(pd.DataFrame({"date": [bad_date]}), "date")


def test_missing_dates_and_nav_rejected():
    with pytest.raises(ValueError, match="missing date"):
        v63.dated(pd.DataFrame({"date": [pd.NaT]}), "date")
    with pytest.raises(ValueError, match="invalid NAV"):
        v63.validate_nav(pd.Series([1.0, np.nan], index=pd.date_range("2021-01-01", periods=2)))


def test_path_escape_rejected(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        v63.safe_path(tmp_path, "../outside")


def test_preflight_rejects_2026_before_reading_nav(tmp_path, monkeypatch):
    dates = pd.bdate_range(end="2026-01-01", periods=1272)
    frame = pd.DataFrame({c: 99.0 for c in v63.LEDGER_COLS}, index=range(1272))
    frame["session_date"] = dates
    path = tmp_path / "combined_ledger_primary.parquet"
    frame.to_parquet(path, index=False)
    catalog = tmp_path / "metrics.json"
    catalog.write_text(
        json.dumps(
            {
                "artifacts": {
                    path.name: {
                        "sha256": v63.sha(path),
                        "bytes": path.stat().st_size,
                        "rows": 1272,
                    }
                }
            }
        ),
        encoding="utf-8-sig",
    )
    cfg = {
        "inputs": {
            "v39": {"root": ".", "catalog": catalog.name, "catalog_sha256": v63.sha(catalog)}
        }
    }
    original, reads = v63.pq.ParquetFile, []

    class Observed:
        def __init__(self, p):
            self.inner = original(p)
            self.metadata, self.schema_arrow = self.inner.metadata, self.inner.schema_arrow

        def read(self, *, columns):
            reads.append(columns)
            return self.inner.read(columns=columns)

    monkeypatch.setattr(v63.pq, "ParquetFile", Observed)
    with pytest.raises(ValueError, match="protected"):
        v63.admit(cfg, tmp_path)
    assert reads == [["session_date"]]
    altered = copy.deepcopy(cfg)
    altered["inputs"]["v39"]["catalog_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="catalog drift"):
        v63.admit(altered, tmp_path)
