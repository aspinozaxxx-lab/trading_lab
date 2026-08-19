"""Tipizirovannye interfeisy rasshireniya laboratorii."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class DataSource(Protocol):
    """Opisyvaet istochnik normalizovannyh rynochnyh dannyh."""

    def load(self) -> Any:
        """Zagruzhaet dannye i metadannye istochnika."""


class FeatureBuilder(Protocol):
    """Opisyvaet postroitel priznakov bez zaglyadyvaniya v budushchee."""

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Stroit tablicu priznakov s tem zhe vremennym indeksom."""


class StrategyPipeline(Protocol):
    """Opisyvaet obuchaemuyu strategiyu formirovaniya celevyh pozicii."""

    def fit(self, features: pd.DataFrame, labels: pd.Series) -> StrategyPipeline:
        """Obuchaet strategiyu na peredannom vremennom otseke."""

    def predict_targets(self, features: pd.DataFrame) -> pd.Series:
        """Vozvrashchaet celevye pozicii dlya kazhdogo bara."""


class TemporalSplitter(Protocol):
    """Opisyvaet hronologicheskoe razbienie vyborki."""

    def split(self, length: int) -> Any:
        """Vozvrashchaet train, validation i test indeksy."""


class Objective(Protocol):
    """Opisyvaet celu optimizacii po validation-metrikam."""

    def __call__(self, metrics: dict[str, float]) -> float:
        """Vychislyaet skalyarnoe znachenie objective."""


class Reporter(Protocol):
    """Opisyvaet sohranenie otcheta i artefaktov eksperimenta."""

    def write(self, run_dir: Path, payload: Any) -> None:
        """Sohranyaet otchet v katalog zapuska."""

