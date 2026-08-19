"""Obshchie pytest-fixtures dlya lokalnoi laboratorii."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab.config import AppConfig, load_config
from market_lab.data.moex import FixtureSource

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren testiruemogo proekta.
CONFIG_PATH = PROJECT_ROOT / "configs" / "mvp.yaml"  # Osnovnoi MVP-konfig.


@pytest.fixture
def app_config() -> AppConfig:
    """Zagruzhaet razreshennuyu MVP-konfiguraciyu."""
    return load_config(CONFIG_PATH)


@pytest.fixture
def market_frame(app_config: AppConfig) -> pd.DataFrame:
    """Vozvrashchaet lokalnye svechi bez setevogo dostupa."""
    return FixtureSource(app_config.data).load().frame

