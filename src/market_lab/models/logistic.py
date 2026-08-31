"""Deterministichnaya logisticheskaya strategiya dlya CPU."""

from __future__ import annotations

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class LogisticStrategy:
    """Obuchaet skalirovannuyu Logistic Regression i vydait ekspoziciyu."""

    def __init__(self, c_value: float, threshold: float, allow_short: bool, seed: int) -> None:
        """Sozdaet odno-potochnyi vosproizvodimyi sklearn pipeline."""
        if c_value <= 0:
            raise ValueError("C dolzhen byt polozhitelnym")
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold dolzhen byt mezhdu 0 i 1")
        self.c_value = float(c_value)
        self.threshold = float(threshold)
        self.allow_short = allow_short
        self.seed = seed
        self.pipeline = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        C=self.c_value,
                        random_state=seed,
                        solver="liblinear",
                        max_iter=1000,
                    ),
                ),
            ]
        )

    def fit(self, features: pd.DataFrame, labels: pd.Series) -> LogisticStrategy:
        """Obuchaet model tolko na polnyh strokah i dvuh klassah."""
        joined = features.join(labels).dropna()
        if joined.empty:
            raise ValueError("Net polnyh strok dlya obucheniya modeli")
        clean_labels = joined[labels.name].astype(int)
        if clean_labels.nunique() < 2:
            raise ValueError("Dlya Logistic Regression nuzhny oba klassa")
        self.pipeline.fit(joined[features.columns], clean_labels)
        return self

    def predict_targets(self, features: pd.DataFrame) -> pd.Series:
        """Prevrashchaet veroyatnost rosta v dlinnuyu, korotkuyu ili nulevuyu poziciyu."""
        targets = pd.Series(0.0, index=features.index, name="target_position")
        valid = features.dropna()
        if valid.empty:
            return targets
        probabilities = self.pipeline.predict_proba(valid)[:, 1]
        predicted = pd.Series(0.0, index=valid.index)
        predicted.loc[probabilities >= self.threshold] = 1.0
        if self.allow_short:
            predicted.loc[probabilities <= 1.0 - self.threshold] = -1.0
        targets.loc[valid.index] = predicted
        return targets
