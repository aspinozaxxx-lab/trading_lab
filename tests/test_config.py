"""Proverki strogoi konfiguracii i bezopasnyh putei."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from market_lab.config import AppConfig, load_config


def test_config_resolves_all_storage_inside_project(app_config: AppConfig) -> None:
    """Proveryaet chto dannye i runs ostayutsya vnutri kornya."""
    root = Path(__file__).resolve().parents[1]
    assert app_config.paths.root == root
    assert app_config.paths.raw_data_dir == root / "data" / "raw"
    assert app_config.paths.processed_data_dir == root / "data" / "processed"
    assert app_config.paths.runs_dir == root / "runs"
    assert app_config.data.fixture_path.is_relative_to(root)


def test_config_rejects_path_outside_root(tmp_path: Path, app_config: AppConfig) -> None:
    """Proveryaet blokirovku vyhoda puti za koren konfiguracii."""
    document = app_config.model_dump(mode="json")
    document["paths"]["root"] = "."
    document["paths"]["runs_dir"] = "../outside"
    document["data"]["fixture_path"] = "fixture.json"
    config_path = tmp_path / "unsafe.yaml"
    config_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8-sig",
    )
    with pytest.raises(ValueError, match="Koren konfiguracii"):
        load_config(config_path)


def test_config_rejects_short_gap(app_config: AppConfig) -> None:
    """Proveryaet minimalnyi gap dlya dvuhbarnoi metki."""
    payload = app_config.model_dump(mode="json")
    payload["validation"]["gap_bars"] = 1
    with pytest.raises(ValueError):
        AppConfig.model_validate(payload)
