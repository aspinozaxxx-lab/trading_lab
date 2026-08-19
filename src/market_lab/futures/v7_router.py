"""Fair causal sleeping-specialist router dlya futures-v7."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from market_lab.futures.specialist_router import (
    SPECIALIST_NAMES,
    SPECIALIST_SCORE_COLUMNS,
    _feedback_losses,
    _finalize_router_output,
    _normalize_router_panel,
)

# Versiya fair sleeping-expert update bez vliyaniya nedostupnyh kanalov.
V7_ROUTER_VERSION: Final[str] = "futures-v7-fair-sleeping-hedge-v1"


@dataclass(frozen=True, slots=True)
class V7SpecialistRouterConfig:
    """Fiksiruet causal Hedge update, active-only exploration i gross cap."""

    learning_rate: float = 2.0
    exploration: float = 0.04
    maximum_gross: float = 1.0

    def __post_init__(self) -> None:
        """Proveryaet netuniruemye parametry do chteniya vremennogo ryada."""
        if not np.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("learning_rate dolzhen byt konechnym i > 0")
        if not np.isfinite(self.exploration) or not 0.0 <= self.exploration < 1.0:
            raise ValueError("exploration dolzhen byt v [0, 1)")
        if not np.isfinite(self.maximum_gross) or not 0.0 < self.maximum_gross <= 1.0:
            raise ValueError("maximum_gross dolzhen byt v (0, 1]")


def _fair_activation(
    log_weights: np.ndarray,
    activated: np.ndarray,
    available_any: np.ndarray,
) -> None:
    """Inicializiruet prosnuvshiisya kanal tekushchim srednim active prior."""
    waking = available_any & ~activated
    if not waking.any():
        return
    reference = activated & available_any
    if not reference.any():
        reference = activated
    initial = float(np.mean(log_weights[reference])) if reference.any() else 0.0
    log_weights[waking] = initial
    activated[waking] = True


def _active_probabilities(
    log_weights: np.ndarray,
    available: np.ndarray,
    exploration: float,
) -> np.ndarray:
    """Normalizuet Hedge i exploration tolko po dostupnym tekushchim ekspertam."""
    indices = np.flatnonzero(available)
    if len(indices) == 0 or not available[0]:
        raise RuntimeError("Base specialist ne mozhet byt sleeping")
    selected = log_weights[indices]
    centered = selected - np.max(selected)
    probabilities = np.exp(centered)
    probabilities /= probabilities.sum()
    probabilities = (1.0 - exploration) * probabilities + exploration / len(indices)
    output = np.zeros(len(log_weights), dtype=float)
    output[indices] = probabilities
    return output


def _route_v7(frame: pd.DataFrame, config: V7SpecialistRouterConfig) -> pd.DataFrame:
    """Vypolnyaet fair expanding feedback i active-only sleeping smeshivanie."""
    count = len(SPECIALIST_NAMES)
    log_weights = np.zeros(count, dtype=float)
    activated = np.zeros(count, dtype=bool)
    cumulative_observations = np.zeros(count, dtype=int)
    history: list[pd.DataFrame] = []
    output_rows: list[pd.DataFrame] = []
    for _, current in frame.groupby("trade_date", sort=True):
        losses = np.full(count, np.nan, dtype=float)
        observations = np.zeros(count, dtype=int)
        feedback_signal_date = pd.NaT
        feedback_entry_date = pd.NaT
        feedback_exit_date = pd.NaT
        if len(history) >= 2:
            evaluated = history[-2]
            entered = history[-1]
            losses, observations = _feedback_losses(evaluated, entered, current)
            learned = np.isfinite(losses) & activated
            log_weights[learned] -= config.learning_rate * losses[learned]
            cumulative_observations += observations
            feedback_signal_date = evaluated["trade_date"].iloc[0]
            feedback_entry_date = entered["trade_date"].iloc[0]
            feedback_exit_date = current["trade_date"].iloc[0]
        score_matrix = current.loc[
            :, [SPECIALIST_SCORE_COLUMNS[name] for name in SPECIALIST_NAMES]
        ].to_numpy(dtype=float)
        availability = np.isfinite(score_matrix)
        _fair_activation(log_weights, activated, availability.any(axis=0))
        weights_matrix = np.zeros_like(score_matrix, dtype=float)
        routed_scores = np.zeros(len(current), dtype=float)
        for row_index in range(len(current)):
            weights = _active_probabilities(
                log_weights,
                availability[row_index],
                config.exploration,
            )
            weights_matrix[row_index] = weights
            routed_scores[row_index] = float(
                np.dot(
                    weights[availability[row_index]],
                    score_matrix[row_index, availability[row_index]],
                )
            )
        dated = current.copy()
        dated["router_target_score"] = np.clip(routed_scores, -1.0, 1.0)
        gross = float(np.abs(dated["router_target_score"]).sum())
        scale = min(1.0, config.maximum_gross / gross) if gross > 0.0 else 0.0
        dated["target_weight"] = dated["router_target_score"] * scale
        dated["target_session_offset"] = 1
        dated["router_observed_through"] = dated["trade_date"]
        dated["router_feedback_signal_date"] = feedback_signal_date
        dated["router_feedback_entry_date"] = feedback_entry_date
        dated["router_feedback_exit_date"] = feedback_exit_date
        dated["router_feedback_interval"] = "open_to_open"
        dated["router_version"] = V7_ROUTER_VERSION
        for index, specialist in enumerate(SPECIALIST_NAMES):
            dated[f"router_score_{specialist}"] = dated[
                SPECIALIST_SCORE_COLUMNS[specialist]
            ]
            dated[f"router_available_{specialist}"] = availability[:, index]
            dated[f"router_weight_{specialist}"] = weights_matrix[:, index]
            dated[f"router_loss_{specialist}"] = losses[index]
            dated[f"router_loss_observations_{specialist}"] = observations[index]
            dated[f"router_cumulative_observations_{specialist}"] = (
                cumulative_observations[index]
            )
        output_rows.append(dated)
        history.append(current)
    return pd.concat(output_rows, ignore_index=True)


class CausalFairSleepingSpecialistRouter:
    """Obedinyaet dostupnye kanaly bez floor-razmytiya ot sleeping ekspertov."""

    def __init__(self, config: V7SpecialistRouterConfig | None = None) -> None:
        """Sohranyaet fiksirovannuyu konfiguraciyu bez fitted state mezhdu vyzovami."""
        self.config = config or V7SpecialistRouterConfig()

    def transform(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Stroit causal next-open targety s polnym weight/loss provenance."""
        normalized = _normalize_router_panel(panel)
        routed = _route_v7(normalized, self.config)
        finalized = _finalize_router_output(routed)
        finalized["router_version"] = V7_ROUTER_VERSION
        return finalized

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Predostavlyaet sklearn-podobnyi alias chistogo transform."""
        return self.transform(panel)


def build_causal_v7_specialist_targets(
    panel: pd.DataFrame,
    config: V7SpecialistRouterConfig | None = None,
) -> pd.DataFrame:
    """Vypolnyaet determinirovannyi fair sleeping router odnim vyzovom."""
    return CausalFairSleepingSpecialistRouter(config).transform(panel)


__all__ = [
    "CausalFairSleepingSpecialistRouter",
    "V7SpecialistRouterConfig",
    "V7_ROUTER_VERSION",
    "build_causal_v7_specialist_targets",
]
