"""Synthetic tests for the sealed V51 audit of all V42R2 curves."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v51_v42r2_robustness as subject


def test_real_protocol_requires_all_nine_fixed_scenarios() -> None:
    protocol = subject.load_protocol()

    assert protocol["scenario_order"] == list(subject.SCENARIOS)
    assert protocol["analysis"]["block_sessions"] == [5, 21, 63, 126]
    assert protocol["analysis"]["bootstrap_total_paths"] == 900_000
    assert protocol["analysis"]["all_nine_scenarios_required"] is True
    assert protocol["analysis"]["strategy_parameter_search"] is False
    assert protocol["live_trading_allowed"] is False


def _synthetic_protocol(root: Path, *, include_2026: bool = False) -> dict[str, object]:
    run = root / "synthetic_v42r2"
    run.mkdir()
    dates = pd.to_datetime(
        ["2025-12-24", "2025-12-25", "2025-12-26", "2025-12-29", "2026-01-05"]
        if include_2026
        else ["2025-12-23", "2025-12-24", "2025-12-25", "2025-12-26", "2025-12-29"]
    )
    mask = [False, True, True, False, True]
    frame = pd.DataFrame({"date": dates, "is_v39_session": mask})
    combinations: dict[str, object] = {}
    expected: dict[str, object] = {}
    selected_dates = pd.DatetimeIndex(dates[mask])
    for index, scenario in enumerate(subject.SCENARIOS):
        nav = pd.Series(
            [1.0, 1.0 + 0.002 * (index + 1), 1.0 + 0.004 * (index + 1)],
            index=selected_dates,
        )
        frame[subject.NAV_COLUMNS[scenario]] = [nav.iloc[0], *nav, nav.iloc[-1]][:5]
        metrics = subject._performance_metrics(nav)
        combinations[scenario] = {"combined": metrics}
        expected[scenario] = metrics
    frame.to_parquet(run / "daily_ledger.parquet", index=False)
    (run / "metrics.json").write_text(
        json.dumps(
            {
                "verdict": "ROBUST_TO_DECLARED_IDLE_COST_STRESSES",
                "same_history_post_result_diagnostic": True,
                "fund_selection_allowed": False,
                "live_trading_allowed": False,
                "combinations": combinations,
            }
        ),
        encoding="utf-8-sig",
    )
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "protocol_sha256": "a" * 64,
                "implementation_sha256": "b" * 64,
                "shared_engine_sha256": "c" * 64,
            }
        ),
        encoding="utf-8-sig",
    )
    (run / "audit.json").write_text(
        json.dumps({"checks": {"synthetic": True}}), encoding="utf-8-sig"
    )
    artifacts = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": subject._sha(path),
        }
        for path in run.iterdir()
    }
    return {
        "parent_v42r2": {
            "protocol_sha256": "a" * 64,
            "implementation_sha256": "b" * 64,
            "shared_engine_sha256": "c" * 64,
            "metrics_sha256": artifacts["metrics.json"]["sha256"],
            "expected_combined_metrics": expected,
        },
        "input": {
            "canonical_run_directory": run.name,
            "expected_full_rows": 5,
            "expected_rows": 3,
            "allowed_columns": [
                "date",
                "is_v39_session",
                *(subject.NAV_COLUMNS[name] for name in subject.SCENARIOS),
            ],
            "artifacts": artifacts,
        },
        "dates": {
            "expected_minimum_session": selected_dates[0].date().isoformat(),
            "expected_maximum_session": selected_dates[-1].date().isoformat(),
            "forbidden_from": "2026-01-01",
        },
        "analysis": {"metric_replay_absolute_tolerance": 1e-12},
    }


def test_verify_curves_reads_only_masked_nav_and_dates(tmp_path: Path) -> None:
    verified = subject.verify_curves(_synthetic_protocol(tmp_path), tmp_path)

    assert set(verified.returns) == set(subject.SCENARIOS)
    assert all(verified.checks.values())
    assert verified.identity["selected_v39_sessions"] == 3
    assert verified.identity["contains_prices_targets_orders_or_positions"] is False


def test_verify_curves_rejects_protected_date(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="curve verification failed"):
        subject.verify_curves(_synthetic_protocol(tmp_path, include_2026=True), tmp_path)


def test_assessment_uses_worst_of_all_nine_scenarios() -> None:
    rows = []
    rolling = {}
    leave_rows = []
    for index, scenario in enumerate(subject.SCENARIOS):
        value = 0.10 if index == len(subject.SCENARIOS) - 1 else 0.25
        rows.append(
            {
                "scenario": scenario,
                "block_sessions": 21,
                "probability_cagr_ge_0_20_and_mdd_le_0_30": 0.80,
                "probability_cagr_ge_0_50_and_mdd_le_0_30": 0.20,
                "cagr_q05": value,
                "cagr_q50": 0.30,
            }
        )
        rolling[scenario] = {
            "252": {"fraction_cagr_ge_0_20": 0.70},
            "504": {"fraction_cagr_ge_0_20": 0.80},
        }
        leave_rows.append({"scenario": scenario, "excluded_year": 2022, "cagr": 0.22})
    protocol = {
        "diagnostic_gates": {
            "minimum_20": {
                "minimum_joint_20_30_frequency": 0.75,
                "minimum_q05_cagr": 0.20,
                "minimum_252d_fraction_cagr_ge_20": 0.65,
                "minimum_504d_fraction_cagr_ge_20": 0.75,
                "every_leave_year_out_cagr_ge": 0.20,
            },
            "aspirational_50": {
                "minimum_joint_50_30_frequency": 0.50,
                "minimum_median_cagr": 0.50,
            },
        }
    }

    result = subject._assessment(protocol, pd.DataFrame(rows), rolling, pd.DataFrame(leave_rows))

    assert result["minimum_20_supported_internally"] is False
    assert result["worst_bootstrap_q05_cagr"]["scenario"].startswith("stress__")
    assert result["minimum_20_conditions"]["all_scenarios_q05_cagr"] is False
