"""Synthetic tests for the sealed V50 audit of canonical V49 curves."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v27_robustness as robust
from market_lab import futures_v50_v49_robustness as subject


def test_real_protocol_is_sealed_without_strategy_search() -> None:
    protocol = subject.load_protocol()

    assert protocol["parent_v49"]["protocol_sha256"].startswith("37b4fcb0")
    assert protocol["analysis"]["block_sessions"] == [5, 21, 63, 126]
    assert protocol["analysis"]["bootstrap_total_paths"] == 300_000
    assert protocol["analysis"]["strategy_parameter_search"] is False
    assert protocol["limitations"]["independent_holdout"] is False
    assert protocol["live_trading_allowed"] is False


def _synthetic_protocol(root: Path, include_2026: bool = False) -> dict[str, object]:
    run = root / "synthetic_v49"
    run.mkdir()
    dates = pd.to_datetime(
        ["2025-12-29", "2025-12-30", "2026-01-05"]
        if include_2026
        else ["2025-12-26", "2025-12-29", "2025-12-30"]
    )
    navs = {
        "primary": [1.0, 1.01, 1.02],
        "doubled": [1.0, 1.008, 1.015],
        "stress": [1.0, 1.005, 1.01],
    }
    ledger = pd.DataFrame({"session_date": dates})
    expected: dict[str, dict[str, float]] = {}
    for scenario, nav in navs.items():
        ledger[subject.NAV_COLUMNS[scenario]] = nav
        expected[scenario] = robust.performance_metrics(
            pd.Series(nav), pd.Series(dates), initial_cash=1.0
        )
    ledger.to_parquet(run / "combined_ledger.parquet", index=False)
    metrics = {
        "verdict": "NO_GO",
        "adaptive_same_history": True,
        "live_trading_allowed": False,
        "scenarios": {scenario: {"combined": values} for scenario, values in expected.items()},
    }
    (run / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8-sig")
    (run / "manifest.json").write_text(
        json.dumps({"protocol_sha256": "a" * 64}), encoding="utf-8-sig"
    )
    (run / "audit.json").write_text(
        json.dumps({"checks": {"synthetic": True}}), encoding="utf-8-sig"
    )
    artifacts = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": robust.sha256_file(path),
        }
        for path in run.iterdir()
    }
    return {
        "parent_v49": {
            "protocol_sha256": "a" * 64,
            "metrics_sha256": artifacts["metrics.json"]["sha256"],
            "expected_combined_metrics": expected,
        },
        "input": {
            "canonical_run_directory": run.name,
            "expected_rows": 3,
            "allowed_columns": [
                "session_date",
                *(subject.NAV_COLUMNS[name] for name in subject.SCENARIOS),
            ],
            "artifacts": artifacts,
        },
        "dates": {
            "expected_minimum_session": dates[0].date().isoformat(),
            "expected_maximum_session": dates[-1].date().isoformat(),
            "forbidden_from": "2026-01-01",
        },
        "analysis": {"metric_replay_absolute_tolerance": 1e-12},
    }


def test_verify_curves_reads_only_nav_and_dates(tmp_path: Path) -> None:
    verified = subject.verify_curves(_synthetic_protocol(tmp_path), tmp_path)

    assert set(verified.returns) == set(subject.SCENARIOS)
    assert all(verified.checks.values())
    assert verified.identity["contains_prices_targets_orders_or_positions"] is False


def test_verify_curves_rejects_protected_date(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="curve verification failed"):
        subject.verify_curves(_synthetic_protocol(tmp_path, include_2026=True), tmp_path)


def test_bootstrap_40_summary_keeps_predeclared_thresholds() -> None:
    samples = robust.circular_block_bootstrap(
        np.array([0.01, -0.005, 0.008, 0.0, 0.004]),
        replications=32,
        block_sessions=2,
        seed=50,
        elapsed_years=1.0,
        batch_size=7,
    )

    summary = subject.summarize_bootstrap_40(samples, (0.05, 0.5, 0.95))

    assert 0.0 <= summary["probability_cagr_ge_0_20_and_mdd_le_0_40"] <= 1.0
    assert 0.0 <= summary["probability_cagr_ge_0_50_and_mdd_le_0_40"] <= 1.0
    assert summary["cagr_q05"] <= summary["cagr_q50"] <= summary["cagr_q95"]
