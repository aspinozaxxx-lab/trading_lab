"""Synthetic tests for the frozen V27 robustness audit."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v27_robustness as audit


def test_performance_metrics_replay_level_convention() -> None:
    dates = pd.Series(pd.to_datetime(["2020-12-30", "2021-12-30", "2022-12-30"]))
    levels = pd.Series([100.0, 121.0, 133.1])
    metrics = audit.performance_metrics(levels, dates, initial_cash=100.0)

    assert metrics["total_return"] == pytest.approx(0.331)
    assert metrics["maximum_drawdown"] == pytest.approx(0.0)
    assert metrics["cagr"] > 0.15
    assert metrics["sharpe"] > 0.0


def test_circular_block_bootstrap_is_deterministic_and_path_aware() -> None:
    returns = np.array([0.01, -0.02, 0.03, -0.01, 0.005, 0.0], dtype=float)
    first = audit.circular_block_bootstrap(
        returns,
        replications=64,
        block_sessions=3,
        seed=27021,
        elapsed_years=1.0,
        batch_size=11,
    )
    second = audit.circular_block_bootstrap(
        returns,
        replications=64,
        block_sessions=3,
        seed=27021,
        elapsed_years=1.0,
        batch_size=17,
    )

    pd.testing.assert_frame_equal(first, second)
    assert first["replication"].tolist() == list(range(64))
    assert first["maximum_drawdown"].between(0.0, 1.0).all()
    summary = audit.summarize_bootstrap(first, quantiles=(0.05, 0.5, 0.95))
    assert summary["replications"] == 64.0
    assert 0.0 <= summary["probability_cagr_ge_0_20"] <= 1.0
    assert summary["cagr_q05"] <= summary["cagr_q50"] <= summary["cagr_q95"]


def test_rolling_and_leave_one_year_out_keep_path_semantics() -> None:
    dates = pd.bdate_range("2021-01-01", periods=520)
    returns = pd.Series(np.full(len(dates), 0.0005), index=dates)
    rolling = audit.rolling_windows(returns, window_sessions=252)
    leave = audit.leave_one_year_out(returns, years=(2021, 2022))

    assert len(rolling) == len(returns) - 252 + 1
    assert rolling["cagr"].gt(0.0).all()
    assert rolling["maximum_drawdown"].eq(0.0).all()
    assert leave["excluded_year"].tolist() == [2021, 2022]
    assert leave["cagr"].gt(0.0).all()


def _write_synthetic_parent(
    root: Path,
    *,
    include_2026: bool,
) -> tuple[dict[str, object], Path]:
    run = root / "synthetic_v27"
    run.mkdir()
    dates = pd.to_datetime(
        ["2020-12-30", "2021-01-04", "2026-01-05"]
        if include_2026
        else ["2020-12-30", "2021-01-04", "2021-01-05"]
    )
    levels_by_scenario = {
        "primary": [100.0, 101.0, 100.5],
        "doubled": [100.0, 100.8, 100.2],
        "stress": [100.0, 100.6, 99.9],
    }
    expected_metrics: dict[str, dict[str, float]] = {}
    for scenario, levels in levels_by_scenario.items():
        frame = pd.DataFrame(
            {"session_date": dates, "combined_ending_equity": levels, "forbidden": 7.0}
        )
        frame.to_parquet(run / f"combined_ledger_{scenario}.parquet", index=False)
        expected_metrics[scenario] = audit.performance_metrics(
            frame["combined_ending_equity"], frame["session_date"], initial_cash=100.0
        )
    metrics = {
        "protocol_sha256": "a" * 64,
        "checks": {"synthetic": True},
        "live_trading_allowed": False,
        "independent_holdout_confirmation": False,
        "scenarios": {
            scenario: {"combined": values} for scenario, values in expected_metrics.items()
        },
    }
    metrics_path = run / "metrics.json"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8-sig")
    metrics_hash = audit.sha256_file(metrics_path)
    identity_path = run / "identity.json"
    identity_path.write_text(
        json.dumps({"metrics_sha256": metrics_hash}), encoding="utf-8-sig"
    )
    artifacts: dict[str, dict[str, object]] = {}
    for path in run.iterdir():
        artifacts[path.name] = {
            "bytes": path.stat().st_size,
            "sha256": audit.sha256_file(path),
        }
    protocol: dict[str, object] = {
        "parent_v27": {
            "protocol_sha256": "a" * 64,
            "metrics_sha256": metrics_hash,
            "expected_combined_metrics": expected_metrics,
        },
        "input": {
            "canonical_run_directory": run.name,
            "expected_rows_per_scenario": 3,
            "allowed_columns": list(audit.EQUITY_COLUMNS),
            "artifacts": artifacts,
        },
        "analysis": {
            "initial_cash_rub": 100.0,
            "metric_replay_absolute_tolerance": 1e-12,
        },
        "dates": {
            "forbidden_from": "2026-01-01",
            "expected_minimum_session": "2020-12-30",
            "expected_maximum_session": dates[-1].date().isoformat(),
        },
    }
    return protocol, run


def test_verify_v27_curves_reads_only_allowed_columns(tmp_path: Path) -> None:
    protocol, _ = _write_synthetic_parent(tmp_path, include_2026=False)
    verified = audit.verify_v27_curves(protocol, runs_root=tmp_path)

    assert set(verified.levels) == set(audit.SCENARIOS)
    assert list(verified.levels["primary"].columns) == list(audit.EQUITY_COLUMNS)
    assert all(verified.checks.values())
    assert verified.input_identity["contains_prices_targets_or_positions"] is False


def test_verify_v27_curves_rejects_protected_dates(tmp_path: Path) -> None:
    protocol, _ = _write_synthetic_parent(tmp_path, include_2026=True)
    with pytest.raises(ValueError, match="curve validation failed"):
        audit.verify_v27_curves(protocol, runs_root=tmp_path)


def test_real_protocol_is_byte_sealed_and_keeps_v27_frozen() -> None:
    protocol = audit.load_protocol()

    assert protocol["parent_v27"]["protocol_sha256"].startswith("7a9a44cf")
    assert protocol["parent_v27"]["metrics_sha256"].startswith("5fc1f271")
    assert protocol["analysis"]["block_sessions"] == [5, 21, 63]
    assert protocol["diagnostic_gates"]["minimum_20"][
        "minimum_stress_joint_20_30_frequency"
    ] == 0.5
    assert protocol["limitations"]["independent_holdout"] is False
