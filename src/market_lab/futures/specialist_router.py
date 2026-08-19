"""Causal'nyi sleeping-experts router dlya daily futures signalov."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

ROUTER_ASSETS: Final[tuple[str, ...]] = (  # Fiksirovannyi development universe.
    "SI",
    "RI",
    "BR",
    "MIX",
)
SPECIALIST_NAMES: Final[tuple[str, ...]] = (  # Stabil'nyi poryadok expert weights.
    "base",
    "cbr_macro",
    "cftc",
    "filings",
    "news",
)
SPECIALIST_SCORE_COLUMNS: Final[dict[str, str]] = {  # Vhodnye score columns ekspertov.
    "base": "target_score",
    "cbr_macro": "cbr_macro_score",
    "cftc": "cftc_score",
    "filings": "filings_score",
    "news": "news_score",
}
ROUTER_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(  # Minimal'naya skhema.
    {
        "trade_date",
        "asset_code",
        "open",
        "target_score",
        "cbr_macro_score",
    }
)
MANDATORY_SPECIALISTS: Final[frozenset[str]] = frozenset(  # Nikogda ne sleeping experts.
    {"base", "cbr_macro"}
)
SCORE_TOLERANCE: Final[float] = 1e-12  # Dopusk granic score i gross targeta.


@dataclass(frozen=True, slots=True)
class SpecialistRouterConfig:
    """Zadaet fiksirovannyi exponential update i portfolio gross cap."""

    learning_rate: float = 2.0
    exploration: float = 0.04
    maximum_gross: float = 1.0

    def __post_init__(self) -> None:
        """Proveryaet parametry router do vremennogo prohoda."""
        if not np.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("learning_rate dolzhen byt' konechnym i > 0")
        if not np.isfinite(self.exploration) or not 0.0 <= self.exploration < 1.0:
            raise ValueError("exploration dolzhen byt' v [0, 1)")
        if not np.isfinite(self.maximum_gross) or not 0.0 < self.maximum_gross <= 1.0:
            raise ValueError("maximum_gross dolzhen byt' v (0, 1]")


def _asset_code(value: object) -> str:
    """Privodit logical ticker k canonical upper-case kodu i RTS alias k RI."""
    normalized = str(value).strip().upper()
    return "RI" if normalized == "RTS" else normalized


def _score_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Chitaet score kak float, razreshaya tol'ko finite ili sleeping NaN."""
    try:
        values = pd.to_numeric(frame[column], errors="raise").astype(float)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Nekorrektnyi specialist score: {column}") from error
    if np.isinf(values.to_numpy()).any():
        raise ValueError(f"Beskonechnyi specialist score: {column}")
    outside = values.notna() & (
        (values < -1.0 - SCORE_TOLERANCE) | (values > 1.0 + SCORE_TOLERANCE)
    )
    if outside.any():
        raise ValueError(f"Specialist score vyshel iz [-1, 1]: {column}")
    return values.clip(-1.0, 1.0)


def _normalize_router_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet polnyi common-session panel i dobavlyaet sleeping columns."""
    if missing := ROUTER_REQUIRED_COLUMNS - set(panel.columns):
        raise ValueError(f"V specialist router panel net kolonok: {sorted(missing)}")
    frame = panel.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if frame["trade_date"].dt.tz is not None:
        frame["trade_date"] = frame["trade_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    frame["trade_date"] = frame["trade_date"].dt.normalize()
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    if frame["asset_code"].eq("").any():
        raise ValueError("Pustoi asset_code v specialist router")
    if frame.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("Povtor asset/date v specialist router")
    try:
        frame["open"] = pd.to_numeric(frame["open"], errors="raise").astype(float)
    except (TypeError, ValueError) as error:
        raise ValueError("Nekorrektnyi factual open v specialist router") from error
    known_open = frame["open"].notna()
    invalid_open = known_open & (
        ~np.isfinite(frame["open"]) | (frame["open"] <= 0.0)
    )
    if invalid_open.any():
        raise ValueError("Izvestnyi factual open dolzhen byt' konechnym i > 0")
    for specialist, column in SPECIALIST_SCORE_COLUMNS.items():
        if column not in frame:
            if specialist in MANDATORY_SPECIALISTS:
                raise ValueError(f"Net obyazatel'nogo specialist column: {column}")
            frame[column] = np.nan
        frame[column] = _score_series(frame, column)
        if specialist in MANDATORY_SPECIALISTS and frame[column].isna().any():
            raise ValueError(f"Obyazatel'nyi specialist sleeping: {specialist}")
    expected_assets = frozenset(ROUTER_ASSETS)
    for trading_date, snapshot in frame.groupby("trade_date", sort=True):
        if frozenset(snapshot["asset_code"]) != expected_assets:
            raise ValueError(f"Nepolnyi router asset snapshot: {trading_date}")
    return frame.sort_values(["trade_date", "asset_code"], kind="mergesort").reset_index(
        drop=True
    )


def _global_probabilities(log_weights: np.ndarray, exploration: float) -> np.ndarray:
    """Prevrashchaet log-vesa v stabil'nye probabilities s fiksirovannym floor."""
    centered = log_weights - np.max(log_weights)
    probabilities = np.exp(centered)
    probabilities /= probabilities.sum()
    count = float(len(probabilities))
    return (1.0 - exploration) * probabilities + exploration / count


def _sleeping_weights(
    probabilities: np.ndarray,
    available: np.ndarray,
) -> np.ndarray:
    """Obnulyaet sleeping experts i perenormiruet tol'ko dostupnye vesy."""
    if not available[0]:
        raise RuntimeError("Base specialist ne mozhet byt' sleeping")
    selected = probabilities * available.astype(float)
    total = float(selected.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise RuntimeError("Net dostupnyh specialist weights")
    return selected / total


def _feedback_losses(
    evaluated: pd.DataFrame,
    entered: pd.DataFrame,
    current: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """Schitaet loss signal D-2 na strogom open D-1 -> open D bez mostov."""
    evaluated_by_asset = evaluated.set_index("asset_code")
    entry_open = entered.set_index("asset_code")["open"]
    exit_open = current.set_index("asset_code")["open"]
    valid_interval = entry_open.notna() & exit_open.notna()
    realized_direction = np.sign(exit_open / entry_open - 1.0)
    losses = np.full(len(SPECIALIST_NAMES), np.nan, dtype=float)
    observations = np.zeros(len(SPECIALIST_NAMES), dtype=int)
    for index, specialist in enumerate(SPECIALIST_NAMES):
        score_column = SPECIALIST_SCORE_COLUMNS[specialist]
        predictions = evaluated_by_asset[score_column]
        valid = valid_interval & predictions.notna()
        assets = valid.index[valid.to_numpy()]
        observations[index] = len(assets)
        if len(assets) == 0:
            continue
        errors = predictions.loc[assets] - realized_direction.loc[assets]
        losses[index] = float(np.mean(np.square(errors)) / 4.0)
    return losses, observations


def _route_panel(frame: pd.DataFrame, config: SpecialistRouterConfig) -> pd.DataFrame:
    """Vypolnyaet expanding feedback update i current-close sleeping smeshivanie."""
    log_weights = np.zeros(len(SPECIALIST_NAMES), dtype=float)
    cumulative_observations = np.zeros(len(SPECIALIST_NAMES), dtype=int)
    history: list[pd.DataFrame] = []
    output_rows: list[pd.DataFrame] = []
    for _, current in frame.groupby("trade_date", sort=True):
        losses = np.full(len(SPECIALIST_NAMES), np.nan, dtype=float)
        loss_observations = np.zeros(len(SPECIALIST_NAMES), dtype=int)
        feedback_signal_date = pd.NaT
        feedback_entry_date = pd.NaT
        feedback_exit_date = pd.NaT
        if len(history) >= 2:
            evaluated = history[-2]
            entered = history[-1]
            losses, loss_observations = _feedback_losses(evaluated, entered, current)
            learned = np.isfinite(losses)
            log_weights[learned] -= config.learning_rate * losses[learned]
            cumulative_observations += loss_observations
            feedback_signal_date = evaluated["trade_date"].iloc[0]
            feedback_entry_date = entered["trade_date"].iloc[0]
            feedback_exit_date = current["trade_date"].iloc[0]
        probabilities = _global_probabilities(log_weights, config.exploration)
        dated = current.copy()
        routed_scores: list[float] = []
        weight_matrix = np.zeros((len(dated), len(SPECIALIST_NAMES)), dtype=float)
        availability_matrix = np.zeros(
            (len(dated), len(SPECIALIST_NAMES)),
            dtype=bool,
        )
        for row_index, (_, row) in enumerate(dated.iterrows()):
            scores = np.array(
                [row[SPECIALIST_SCORE_COLUMNS[name]] for name in SPECIALIST_NAMES],
                dtype=float,
            )
            available = np.isfinite(scores)
            weights = _sleeping_weights(probabilities, available)
            score = float(np.dot(weights[available], scores[available]))
            routed_scores.append(float(np.clip(score, -1.0, 1.0)))
            weight_matrix[row_index] = weights
            availability_matrix[row_index] = available
        dated["router_target_score"] = routed_scores
        gross = float(np.abs(dated["router_target_score"]).sum())
        scale = min(1.0, config.maximum_gross / gross) if gross > 0.0 else 0.0
        dated["target_weight"] = dated["router_target_score"] * scale
        dated["target_session_offset"] = 1
        dated["router_observed_through"] = dated["trade_date"]
        dated["router_feedback_signal_date"] = feedback_signal_date
        dated["router_feedback_entry_date"] = feedback_entry_date
        dated["router_feedback_exit_date"] = feedback_exit_date
        dated["router_feedback_interval"] = "open_to_open"
        for index, specialist in enumerate(SPECIALIST_NAMES):
            dated[f"router_score_{specialist}"] = dated[
                SPECIALIST_SCORE_COLUMNS[specialist]
            ]
            dated[f"router_available_{specialist}"] = availability_matrix[:, index]
            dated[f"router_weight_{specialist}"] = weight_matrix[:, index]
            dated[f"router_loss_{specialist}"] = losses[index]
            dated[f"router_loss_observations_{specialist}"] = loss_observations[index]
            dated[f"router_cumulative_observations_{specialist}"] = (
                cumulative_observations[index]
            )
        output_rows.append(dated)
        history.append(current)
    return pd.concat(output_rows, ignore_index=True)


def _finalize_router_output(frame: pd.DataFrame) -> pd.DataFrame:
    """Vozvrashchaet stabil'nuyu target/provenance skhemu bez lishnih vhodnyh polei."""
    provenance: list[str] = []
    for specialist in SPECIALIST_NAMES:
        provenance.extend(
            [
                f"router_score_{specialist}",
                f"router_available_{specialist}",
                f"router_weight_{specialist}",
                f"router_loss_{specialist}",
                f"router_loss_observations_{specialist}",
                f"router_cumulative_observations_{specialist}",
            ]
        )
    columns = [
        "trade_date",
        "asset_code",
        "router_target_score",
        "target_weight",
        "target_session_offset",
        "router_observed_through",
        "router_feedback_signal_date",
        "router_feedback_entry_date",
        "router_feedback_exit_date",
        "router_feedback_interval",
        *provenance,
    ]
    return frame[columns].sort_values(
        ["trade_date", "asset_code"], kind="mergesort"
    ).reset_index(drop=True)


class CausalSleepingSpecialistRouter:
    """Obedinyaet base MoE i vneshnie specialisty obshchimi expanding vesami."""

    def __init__(self, config: SpecialistRouterConfig | None = None) -> None:
        """Sohranyaet fiksirovannye parametry bez fitted ili RNG sostoyaniya."""
        self.config = config or SpecialistRouterConfig()

    def transform(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Stroit next-open targety i polnyi causal'nyi weight/loss provenance."""
        normalized = _normalize_router_panel(panel)
        routed = _route_panel(normalized, self.config)
        return _finalize_router_output(routed)

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Predostavlyaet sklearn-podobnyi alias chistogo transform."""
        return self.transform(panel)


def build_causal_specialist_targets(
    panel: pd.DataFrame,
    config: SpecialistRouterConfig | None = None,
) -> pd.DataFrame:
    """Vypolnyaet determinirovannyi router odnoi batch-funkciei."""
    return CausalSleepingSpecialistRouter(config).transform(panel)
