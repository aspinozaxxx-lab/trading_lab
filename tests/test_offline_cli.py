"""Skvoznye proverki offline-demo, artefaktov i deterministichnosti."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import yaml
from typer.testing import CliRunner

from market_lab.cli import app
from market_lab.config import AppConfig, load_config
from market_lab.experiments import execute_experiment

REQUIRED_ARTIFACTS = {  # Minimalnyi kontrakt artefaktov demo.
    "resolved_config.yaml",
    "metrics.json",
    "leaderboard.csv",
    "trades.csv",
    "equity_curve.csv",
    "target_positions.csv",
    "best_trial_params.json",
    "trials.csv",
    "study.sqlite3",
    "model.joblib",
    "selected_strategy.json",
    "feature_list.json",
    "seed.json",
    "report.md",
    "equity_curve.png",
    "run.log",
}


def test_offline_cli_never_creates_network_session(
    monkeypatch: object, tmp_path: Path, app_config: AppConfig
) -> None:
    """Proveryaet CLI i polnyi nabor artefaktov bez seti."""
    project_root = Path(__file__).resolve().parents[1]
    document = app_config.model_dump(mode="json")
    document["paths"] = {
        "root": os.path.relpath(project_root, tmp_path),
        "raw_data_dir": "data/raw",
        "processed_data_dir": "data/processed",
        "runs_dir": (tmp_path / "runs").relative_to(project_root).as_posix(),
    }
    document["data"]["fixture_path"] = "tests/fixtures/moex_sber_daily.json"
    config_path = tmp_path / "mvp-offline.yaml"
    config_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8-sig",
    )
    isolated_config = load_config(config_path)
    before = (
        set(isolated_config.paths.runs_dir.glob("*"))
        if isolated_config.paths.runs_dir.exists()
        else set()
    )

    def forbidden_session() -> None:
        """Padaet pri lyuboi popytke inicializirovat HTTP-sessiyu."""
        raise AssertionError("network session is forbidden")

    monkeypatch.setattr("market_lab.data.moex.requests.Session", forbidden_session)  # type: ignore[attr-defined]
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["demo", "--offline", "--config", str(config_path)],
    )
    assert result.exit_code == 0, result.output
    after = set(isolated_config.paths.runs_dir.glob("*"))
    created = sorted(after - before)
    assert len(created) == 1
    assert {path.name for path in created[0].iterdir()} >= REQUIRED_ARTIFACTS


def test_repeated_seed_produces_same_normalized_results(
    tmp_path: Path, app_config: AppConfig
) -> None:
    """Proveryaet ravnye trials i leaderboard pri odnom seed."""
    config = app_config.model_copy(
        update={
            "paths": app_config.paths.model_copy(update={"runs_dir": tmp_path / "runs"}),
            "optimization": app_config.optimization.model_copy(
                update={"n_trials": 2, "min_trades": 0}
            ),
        }
    )
    first = execute_experiment(config, mode="demo", offline=True)
    second = execute_experiment(config, mode="demo", offline=True)
    first_trials = pd.read_csv(first / "trials.csv", encoding="utf-8-sig")
    second_trials = pd.read_csv(second / "trials.csv", encoding="utf-8-sig")
    volatile_columns = ["datetime_start", "datetime_complete", "duration_seconds"]
    pd.testing.assert_frame_equal(
        first_trials.drop(columns=volatile_columns),
        second_trials.drop(columns=volatile_columns),
    )
    pd.testing.assert_frame_equal(
        pd.read_csv(first / "leaderboard.csv", encoding="utf-8-sig"),
        pd.read_csv(second / "leaderboard.csv", encoding="utf-8-sig"),
    )
    first_metrics = json.loads((first / "metrics.json").read_text(encoding="utf-8-sig"))
    second_metrics = json.loads((second / "metrics.json").read_text(encoding="utf-8-sig"))
    first_metrics.pop("run_id")
    second_metrics.pop("run_id")
    assert first_metrics == second_metrics
