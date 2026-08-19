"""Causal'naya daily mixture-of-experts dlya futures bez hindsight-vybora."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

EXPERT_NAMES: Final[tuple[str, ...]] = (  # Stabil'nyi poryadok ekonomicheskih ekspertov.
    "multi_horizon_trend",
    "short_term_reversal",
    "volatility_breakout",
    "curve_carry",
    "contract_participation",
    "participant_crowding",
    "cross_asset_risk",
    "crisis_convexity",
)
REQUIRED_ASSETS: Final[tuple[str, ...]] = (  # Cross-asset nabor bez hindsight-zamen.
    "SI",
    "RI",
    "BR",
    "MIX",
)
BASE_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(  # Minimal'naya daily skhema.
    {
        "trade_date",
        "asset_code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
    }
)
RISK_SENSITIVITY: Final[dict[str, float]] = {  # Fiksirovannaya makro-napravlennost'.
    "SI": -1.0,
    "RI": 1.0,
    "BR": 0.6,
    "MIX": 1.0,
}
CRISIS_SENSITIVITY: Final[dict[str, float]] = {  # Fiksirovannaya krizisnaya vypuklost'.
    "SI": 1.0,
    "RI": -1.0,
    "BR": -0.25,
    "MIX": -1.0,
}
REGIME_NAMES: Final[tuple[str, ...]] = (  # Dopustimye causal'nye rezhimy gate.
    "neutral",
    "risk_on",
    "risk_off",
    "crisis",
)
NUMERIC_BASE_COLUMNS: Final[tuple[str, ...]] = (  # Chislovye polya strogogo vhoda.
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
)
PARTICIPANT_PROOF_COLUMNS: Final[frozenset[str]] = frozenset(  # As-of dokazatel'stvo.
    {
        "participant_source_date",
        "participant_lag_sessions",
        "participant_snapshot_complete",
    }
)
PARTICIPANT_WIDE_COLUMNS: Final[tuple[str, ...]] = (  # Wide polya participant OI.
    "physical_long",
    "physical_short",
    "legal_long",
    "legal_short",
)
PARTICIPANT_NET_COLUMNS: Final[tuple[str, ...]] = (  # Gotovye ogranichennye net polya.
    "physical_net",
    "legal_net",
)
EPSILON: Final[float] = 1e-12  # Zashchita deleniya bez sozdaniya signala iz propuska.


@dataclass(frozen=True, slots=True)
class CausalMoEConfig:
    """Zadaet fiksirovannye okna ekspertov i expanding exponential gate."""

    trend_horizons: tuple[int, int, int] = (5, 20, 60)
    volatility_lookback: int = 20
    long_volatility_lookback: int = 60
    breakout_lookback: int = 20
    participation_lookback: int = 20
    learning_rate: float = 2.0
    regime_shrinkage: float = 24.0
    exploration: float = 0.04
    risk_threshold: float = 0.25
    crisis_threshold: float = 0.75

    def __post_init__(self) -> None:
        """Proveryaet parametry do rascheta, chtoby gate ne stal nestabil'nym."""
        if len(self.trend_horizons) != 3 or any(
            horizon < 1 for horizon in self.trend_horizons
        ):
            raise ValueError("trend_horizons dolzhny soderzhat' tri polozhitel'nyh okna")
        if tuple(sorted(self.trend_horizons)) != self.trend_horizons:
            raise ValueError("trend_horizons dolzhny vozrastat'")
        for name in (
            "volatility_lookback",
            "long_volatility_lookback",
            "breakout_lookback",
            "participation_lookback",
        ):
            if int(getattr(self, name)) < 2:
                raise ValueError(f"{name} dolzhen byt' >= 2")
        if self.long_volatility_lookback < self.volatility_lookback:
            raise ValueError("long_volatility_lookback ne mozhet byt' koroche volatility")
        if self.learning_rate <= 0.0:
            raise ValueError("learning_rate dolzhen byt' > 0")
        if self.regime_shrinkage <= 0.0:
            raise ValueError("regime_shrinkage dolzhen byt' > 0")
        if not 0.0 <= self.exploration < 1.0:
            raise ValueError("exploration dolzhen byt' v [0, 1)")
        if self.risk_threshold <= 0.0 or self.crisis_threshold <= 0.0:
            raise ValueError("Porogi rezhimov dolzhny byt' > 0")


def _normalize_asset_code(value: object) -> str:
    """Privodit simvol k ekonomicheskomu kodu i yavno svyazyvaet RTS s RI."""
    code = str(value).strip().upper()
    return "RI" if code == "RTS" else code


def _finite_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    """Preobrazuet kolonku v float, ostavlyaya nekorrektnye stroki fail-closed."""
    values = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return values.where(np.isfinite(values), np.nan)


def _normalize_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet long daily panel i zapreshchaet dvusmyslennye nablyudeniya."""
    if missing := BASE_REQUIRED_COLUMNS - set(panel.columns):
        raise ValueError(f"V causal panel net kolonok: {sorted(missing)}")
    frame = panel.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if frame["trade_date"].dt.tz is not None:
        frame["trade_date"] = frame["trade_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    frame["trade_date"] = frame["trade_date"].dt.normalize()
    frame["asset_code"] = frame["asset_code"].map(_normalize_asset_code)
    if (frame["asset_code"] == "").any():
        raise ValueError("Pustoi asset_code v causal panel")
    for column in NUMERIC_BASE_COLUMNS:
        frame[column] = _finite_numeric(frame, column)
    if (frame[["open", "high", "low", "close"]].dropna() <= 0.0).any().any():
        raise ValueError("Izvestnye OHLC dolzhny byt' polozhitel'nymi")
    if (frame[["volume", "open_interest"]].dropna() < 0.0).any().any():
        raise ValueError("Volume i open_interest ne mogut byt' otricatel'nymi")
    complete_ohlc = frame[["open", "high", "low", "close"]].notna().all(axis=1)
    invalid_ohlc = complete_ohlc & (
        (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
        | (frame["high"] < frame["low"])
    )
    if invalid_ohlc.any():
        raise ValueError("Narushen OHLC-invariant v causal panel")
    if frame.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("Povtor asset_code v odnu trade_date")
    return frame.sort_values(["trade_date", "asset_code"], kind="stable").reset_index(drop=True)


def _derive_curve_yield(frame: pd.DataFrame) -> pd.Series:
    """Chitaet gotovyi roll yield ili schitaet ego iz odnovremennogo near/far snapshot."""
    if "roll_yield" in frame:
        return _finite_numeric(frame, "roll_yield")
    near_name = "front_settle" if "front_settle" in frame else "near_settle"
    far_name = "next_settle" if "next_settle" in frame else "far_settle"
    if near_name not in frame or far_name not in frame:
        raise ValueError("Net roll_yield ili odnovremennyh front/next settle")
    near = _finite_numeric(frame, near_name)
    far = _finite_numeric(frame, far_name)
    if "front_days_to_expiry" in frame and "next_days_to_expiry" in frame:
        near_days = _finite_numeric(frame, "front_days_to_expiry")
        far_days = _finite_numeric(frame, "next_days_to_expiry")
        distance = far_days - near_days
    else:
        distance = pd.Series(90.0, index=frame.index, dtype=float)
    valid = (near > 0.0) & (far > 0.0) & (distance > 0.0)
    result = ((near / far) - 1.0) * (365.0 / distance)
    return result.where(valid, np.nan)


def _normalized_net(long_values: pd.Series, short_values: pd.Series) -> pd.Series:
    """Schitaet ogranichennyi net OI bez deleniya nulevogo obshchego OI."""
    total = long_values + short_values
    result = (long_values - short_values) / total.where(total > 0.0)
    return result.clip(-1.0, 1.0)


def _derive_participant_nets(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Stroit fizicheskii i yuridicheskii net iz wide causal participant snapshot."""
    if {"physical_net", "legal_net"} <= set(frame.columns):
        physical = _finite_numeric(frame, "physical_net")
        legal = _finite_numeric(frame, "legal_net")
        return physical.where(physical.abs() <= 1.0), legal.where(legal.abs() <= 1.0)
    required = {"physical_long", "physical_short", "legal_long", "legal_short"}
    if missing := required - set(frame.columns):
        raise ValueError(f"Net participant OI kolonok: {sorted(missing)}")
    values = {column: _finite_numeric(frame, column) for column in sorted(required)}
    if any((series.dropna() < 0.0).any() for series in values.values()):
        raise ValueError("Participant OI ne mozhet byt' otricatel'nym")
    return (
        _normalized_net(values["physical_long"], values["physical_short"]),
        _normalized_net(values["legal_long"], values["legal_short"]),
    )


def _participant_timing_mode(frame: pd.DataFrame) -> tuple[str, pd.Series]:
    """Razlichaet raw current snapshot i dokazannyi exact-one-session pre-lag."""
    present_proof = PARTICIPANT_PROOF_COLUMNS & set(frame.columns)
    if not present_proof:
        return "raw_current_shift_one", pd.Series(True, index=frame.index, dtype=bool)
    if present_proof != PARTICIPANT_PROOF_COLUMNS:
        missing = PARTICIPANT_PROOF_COLUMNS - present_proof
        raise ValueError(f"Nepolnoe participant timing proof: {sorted(missing)}")
    for trading_date, snapshot in frame.groupby("trade_date", sort=True):
        assets = frozenset(snapshot["asset_code"])
        if assets != frozenset(REQUIRED_ASSETS):
            raise ValueError(
                f"Pre-lagged participant proof trebuet common asset snapshot: {trading_date}"
            )
    source_dates = pd.to_datetime(frame["participant_source_date"], errors="raise")
    if source_dates.dt.tz is not None:
        source_dates = source_dates.dt.tz_convert("UTC").dt.tz_localize(None)
    source_dates = source_dates.dt.normalize()
    lag_sessions = pd.to_numeric(frame["participant_lag_sessions"], errors="coerce")
    raw_complete = frame["participant_snapshot_complete"]
    if not raw_complete.dropna().map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError("participant_snapshot_complete dolzhen byt' boolean")
    complete = raw_complete.fillna(False).astype(bool)
    if set(PARTICIPANT_NET_COLUMNS) <= set(frame.columns):
        participant_columns = PARTICIPANT_NET_COLUMNS
    elif set(PARTICIPANT_WIDE_COLUMNS) <= set(frame.columns):
        participant_columns = PARTICIPANT_WIDE_COLUMNS
    else:
        raise ValueError("Pre-lagged panel ne soderzhit participant value columns")
    any_value = frame[list(participant_columns)].notna().any(axis=1)
    all_values = frame[list(participant_columns)].notna().all(axis=1)
    if (any_value & ~complete).any() or (complete & ~all_values).any():
        raise ValueError("Participant availability proof ne sovpadaet s value columns")
    common_dates = pd.DatetimeIndex(frame["trade_date"].drop_duplicates().sort_values())
    previous_by_date = {
        pd.Timestamp(common_dates[index]): pd.Timestamp(common_dates[index - 1])
        for index in range(1, len(common_dates))
    }
    expected_source = frame["trade_date"].map(previous_by_date)
    has_source = source_dates.notna()
    if (has_source & source_dates.ne(expected_source)).any():
        raise ValueError("participant_source_date ne ravna predydushchei factual common session")
    if (has_source & lag_sessions.ne(1.0)).any():
        raise ValueError("Pre-lagged participant_lag_sessions dolzhen byt' rovno 1")
    if (~has_source & lag_sessions.notna()).any():
        raise ValueError("participant_lag_sessions bez participant_source_date")
    if (complete & ~has_source).any():
        raise ValueError("Dostupnyi participant snapshot trebuet source_date proof")
    return "pre_lagged_exact_one", complete


def _past_scale(values: pd.Series, assets: pd.Series, window: int) -> pd.Series:
    """Schitaet medianu absolyutnyh proshlyh znachenii, ne vklyuchaya tekushchee."""
    return values.groupby(assets, sort=False).transform(
        lambda series: series.abs().shift(1).rolling(window, min_periods=window).median()
    )


def _expert_features(
    frame: pd.DataFrame,
    config: CausalMoEConfig,
    participant_timing_mode: str,
) -> pd.DataFrame:
    """Stroit vosem' causal'nyh expert scores tol'ko iz dostupnogo close i lagov."""
    features = frame.copy()
    grouped = features.groupby("asset_code", sort=False, group_keys=False)
    features["_return_1"] = grouped["close"].pct_change(fill_method=None)
    for horizon in config.trend_horizons:
        features[f"_return_{horizon}"] = grouped["close"].pct_change(
            periods=horizon,
            fill_method=None,
        )
    features["_return_3"] = grouped["close"].pct_change(periods=3, fill_method=None)
    features["_volatility"] = grouped["_return_1"].transform(
        lambda series: series.rolling(
            config.volatility_lookback,
            min_periods=config.volatility_lookback,
        ).std(ddof=0)
    )
    features["_long_volatility"] = grouped["_return_1"].transform(
        lambda series: series.rolling(
            config.long_volatility_lookback,
            min_periods=config.long_volatility_lookback,
        ).std(ddof=0)
    )
    horizons = config.trend_horizons
    trend_raw = (
        0.45
        * features[f"_return_{horizons[0]}"]
        / (features["_volatility"] * np.sqrt(horizons[0])).clip(lower=EPSILON)
        + 0.35
        * features[f"_return_{horizons[1]}"]
        / (features["_volatility"] * np.sqrt(horizons[1])).clip(lower=EPSILON)
        + 0.20
        * features[f"_return_{horizons[2]}"]
        / (features["_volatility"] * np.sqrt(horizons[2])).clip(lower=EPSILON)
    )
    features["expert_multi_horizon_trend"] = np.tanh(trend_raw)
    reversal_raw = -(
        0.7 * features["_return_1"] + 0.3 * features["_return_3"] / np.sqrt(3.0)
    ) / features["_volatility"].clip(lower=EPSILON)
    features["expert_short_term_reversal"] = np.tanh(reversal_raw)
    past_high = grouped["high"].transform(
        lambda series: series.shift(1).rolling(
            config.breakout_lookback,
            min_periods=config.breakout_lookback,
        ).max()
    )
    past_low = grouped["low"].transform(
        lambda series: series.shift(1).rolling(
            config.breakout_lookback,
            min_periods=config.breakout_lookback,
        ).min()
    )
    up_break = (features["close"] / past_high - 1.0).clip(lower=0.0)
    down_break = (features["close"] / past_low - 1.0).clip(upper=0.0)
    compression = (
        1.0
        - (
            features["_volatility"]
            / features["_long_volatility"].clip(lower=EPSILON)
        ).clip(0.0, 2.0)
        / 2.0
    )
    breakout_raw = (up_break + down_break) / features["_volatility"].clip(lower=EPSILON)
    features["expert_volatility_breakout"] = np.tanh(
        breakout_raw * (1.0 + compression)
    )
    curve_lag = grouped["_curve_yield"].shift(1)
    curve_scale = _past_scale(
        curve_lag,
        features["asset_code"],
        config.participation_lookback,
    ).clip(lower=1e-4)
    features["expert_curve_carry"] = np.tanh(curve_lag / curve_scale)
    volume_lag = grouped["volume"].shift(1)
    oi_lag = grouped["open_interest"].shift(1)
    log_volume = np.log1p(volume_lag)
    log_oi = np.log1p(oi_lag)
    volume_change = log_volume.groupby(features["asset_code"], sort=False).diff()
    oi_change = log_oi.groupby(features["asset_code"], sort=False).diff()
    volume_scale = _past_scale(
        volume_change,
        features["asset_code"],
        config.participation_lookback,
    ).clip(lower=1e-4)
    oi_scale = _past_scale(
        oi_change,
        features["asset_code"],
        config.participation_lookback,
    ).clip(lower=1e-4)
    volume_impulse = volume_change / volume_scale
    oi_impulse = oi_change / oi_scale
    participation_raw = features["expert_multi_horizon_trend"] * (
        1.0 + 0.5 * np.tanh(volume_impulse) + 0.5 * np.tanh(oi_impulse)
    )
    features["expert_contract_participation"] = np.tanh(participation_raw)
    if participant_timing_mode == "pre_lagged_exact_one":
        physical_lag = features["_physical_net"]
        legal_lag = features["_legal_net"]
    elif participant_timing_mode == "raw_current_shift_one":
        physical_lag = grouped["_physical_net"].shift(1)
        legal_lag = grouped["_legal_net"].shift(1)
    else:
        raise RuntimeError("Neizvestnyi participant_timing_mode")
    features["expert_participant_crowding"] = np.tanh(
        2.0 * (legal_lag - physical_lag)
    )
    return _add_cross_asset_experts(features, config)


def _add_cross_asset_experts(
    frame: pd.DataFrame,
    config: CausalMoEConfig,
) -> pd.DataFrame:
    """Dobavlyaet obshchii risk regime i krizisnyi ekspert iz SI/RI/BR/MIX."""
    features = frame.copy()
    trend = features.pivot(
        index="trade_date",
        columns="asset_code",
        values="expert_multi_horizon_trend",
    ).reindex(columns=REQUIRED_ASSETS)
    vol_ratio = (
        features.assign(
            _vol_ratio=features["_volatility"]
            / features["_long_volatility"].clip(lower=EPSILON)
        )
        .pivot(index="trade_date", columns="asset_code", values="_vol_ratio")
        .reindex(columns=REQUIRED_ASSETS)
    )
    complete = trend.notna().all(axis=1) & vol_ratio.notna().all(axis=1)
    risk_raw = (
        0.35 * trend["RI"]
        + 0.25 * trend["MIX"]
        + 0.20 * trend["BR"]
        - 0.20 * trend["SI"]
    ).where(complete)
    stress = (vol_ratio[["RI", "MIX"]].mean(axis=1) - 1.0).clip(lower=0.0)
    crisis_raw = (
        0.35 * (-trend["RI"]).clip(lower=0.0)
        + 0.25 * (-trend["MIX"]).clip(lower=0.0)
        + 0.20 * trend["SI"].clip(lower=0.0)
        + 0.20 * stress
    ).where(complete)
    risk_by_date = features["trade_date"].map(risk_raw)
    crisis_by_date = features["trade_date"].map(crisis_raw)
    risk_sensitivity = features["asset_code"].map(RISK_SENSITIVITY)
    crisis_sensitivity = features["asset_code"].map(CRISIS_SENSITIVITY)
    features["expert_cross_asset_risk"] = np.tanh(risk_by_date) * risk_sensitivity
    features["expert_crisis_convexity"] = np.tanh(crisis_by_date) * crisis_sensitivity
    features["_risk_raw"] = risk_by_date
    features["_crisis_raw"] = crisis_by_date
    features["_regime"] = "neutral"
    features.loc[risk_by_date > config.risk_threshold, "_regime"] = "risk_on"
    features.loc[risk_by_date < -config.risk_threshold, "_regime"] = "risk_off"
    features.loc[crisis_by_date > config.crisis_threshold, "_regime"] = "crisis"
    features.loc[~complete.reindex(features["trade_date"]).to_numpy(), "_regime"] = "neutral"
    return features


def _normalized_weights(log_weights: np.ndarray, exploration: float) -> np.ndarray:
    """Prevrashchaet log-vesa v stabil'nuyu veroyatnost' s exploration floor."""
    centered = log_weights - np.max(log_weights)
    probabilities = np.exp(centered)
    probabilities /= probabilities.sum()
    count = float(len(probabilities))
    return (1.0 - exploration) * probabilities + exploration / count


def _date_gate(
    features: pd.DataFrame,
    config: CausalMoEConfig,
) -> pd.DataFrame:
    """Ocenivaet signal D-2 po factual open(D)/open(D-1) k close D."""
    output = features.copy()
    global_log = np.zeros(len(EXPERT_NAMES), dtype=float)
    regime_log = {name: np.zeros(len(EXPERT_NAMES), dtype=float) for name in REGIME_NAMES}
    regime_counts = {name: 0 for name in REGIME_NAMES}
    gate_observations = 0
    decision_history: list[tuple[pd.DataFrame, str]] = []
    weight_rows: list[pd.DataFrame] = []
    for _, current in output.groupby("trade_date", sort=True):
        losses = np.full(len(EXPERT_NAMES), np.nan, dtype=float)
        feedback_signal_date = pd.NaT
        feedback_entry_date = pd.NaT
        feedback_exit_date = pd.NaT
        if len(decision_history) >= 2:
            evaluated, evaluated_regime = decision_history[-2]
            entered, _ = decision_history[-1]
            current_open = current.set_index("asset_code")["open"]
            entered_open = entered.set_index("asset_code")["open"]
            common_open = current_open.index.intersection(entered_open.index)
            realized = (
                current_open.reindex(common_open) / entered_open.reindex(common_open) - 1.0
            )
            outcome = np.sign(realized).replace(0.0, 0.0)
            evaluated_by_asset = evaluated.set_index("asset_code")
            observation_count = 0
            for expert_index, expert_name in enumerate(EXPERT_NAMES):
                prediction = evaluated_by_asset[f"expert_{expert_name}"]
                common = prediction.index.intersection(outcome.dropna().index)
                valid = prediction.reindex(common).notna() & outcome.reindex(common).notna()
                valid_assets = common[valid.to_numpy()]
                if len(valid_assets) == 0:
                    continue
                error = prediction.loc[valid_assets] - outcome.loc[valid_assets]
                losses[expert_index] = float(np.mean(np.square(error)) / 4.0)
                observation_count = max(observation_count, len(valid_assets))
            available = np.isfinite(losses)
            if available.any():
                global_log[available] -= config.learning_rate * losses[available]
                regime_log[evaluated_regime][available] -= (
                    config.learning_rate * losses[available]
                )
                gate_observations += observation_count
                regime_counts[evaluated_regime] += observation_count
                feedback_signal_date = evaluated["trade_date"].iloc[0]
                feedback_entry_date = entered["trade_date"].iloc[0]
                feedback_exit_date = current["trade_date"].iloc[0]
        current_regime = str(current["_regime"].iloc[0])
        global_weights = _normalized_weights(global_log, config.exploration)
        local_weights = _normalized_weights(
            regime_log[current_regime],
            config.exploration,
        )
        local_count = regime_counts[current_regime]
        local_fraction = local_count / (local_count + config.regime_shrinkage)
        weights = (1.0 - local_fraction) * global_weights + local_fraction * local_weights
        dated = current.copy()
        for expert_index, expert_name in enumerate(EXPERT_NAMES):
            dated[f"weight_{expert_name}"] = weights[expert_index]
            dated[f"realized_loss_{expert_name}"] = losses[expert_index]
        dated["gate_observations"] = gate_observations
        dated["regime_observations"] = local_count
        dated["feedback_signal_date"] = feedback_signal_date
        dated["feedback_entry_date"] = feedback_entry_date
        dated["feedback_exit_date"] = feedback_exit_date
        dated["feedback_holding_interval"] = "open_to_open"
        weight_rows.append(dated)
        decision_history.append((current, current_regime))
    return pd.concat(weight_rows, ignore_index=True)


def _finalize_targets(frame: pd.DataFrame) -> pd.DataFrame:
    """Smeshivaet ekspertov i obnulyaet ves' target pri lyubom propuske vhoda."""
    output = frame.copy()
    expert_columns = [f"expert_{name}" for name in EXPERT_NAMES]
    weight_columns = [f"weight_{name}" for name in EXPERT_NAMES]
    base_complete = output[list(NUMERIC_BASE_COLUMNS)].notna().all(axis=1)
    expert_complete = output[expert_columns].notna().all(axis=1)
    output["signal_valid"] = base_complete & expert_complete
    weighted = sum(
        output[expert_column] * output[weight_column]
        for expert_column, weight_column in zip(
            expert_columns,
            weight_columns,
            strict=True,
        )
    )
    output["target_score"] = np.tanh(weighted).where(output["signal_valid"], 0.0)
    gross = output["target_score"].abs().groupby(output["trade_date"]).transform("sum")
    output["target_weight"] = (
        output["target_score"] / gross.where(gross > EPSILON)
    ).fillna(0.0)
    output["target_session_offset"] = 1
    output["regime"] = output["_regime"]
    output["gate_observed_through"] = output["trade_date"]
    selected = [
        "trade_date",
        "asset_code",
        "target_session_offset",
        "signal_valid",
        "target_score",
        "target_weight",
        "regime",
        "gate_observed_through",
        "participant_timing_mode",
        "gate_observations",
        "regime_observations",
        "feedback_signal_date",
        "feedback_entry_date",
        "feedback_exit_date",
        "feedback_holding_interval",
        *expert_columns,
        *weight_columns,
        *[f"realized_loss_{name}" for name in EXPERT_NAMES],
    ]
    return output[selected].sort_values(["trade_date", "asset_code"]).reset_index(drop=True)


class CausalDailyMixtureOfExperts:
    """Vychislyaet ticker-agnostic expanding gate i next-session futures targets."""

    def __init__(self, config: CausalMoEConfig | None = None) -> None:
        """Sohranyaet tol'ko fiksirovannuyu konfiguraciyu bez fitted hindsight-state."""
        self.config = config or CausalMoEConfig()

    def transform(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Vozvrashchaet causal'nye scores i portfolio weights dlya sleduyushchei sessii."""
        frame = _normalize_panel(panel)
        frame["_curve_yield"] = _derive_curve_yield(frame)
        timing_mode, participant_available = _participant_timing_mode(frame)
        physical, legal = _derive_participant_nets(frame)
        frame["_physical_net"] = physical.where(participant_available)
        frame["_legal_net"] = legal.where(participant_available)
        frame["participant_timing_mode"] = timing_mode
        features = _expert_features(frame, self.config, timing_mode)
        gated = _date_gate(features, self.config)
        return _finalize_targets(gated)

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Predostavlyaet privychnyi alias transform dlya issledovatel'skogo pipeline."""
        return self.transform(panel)


def build_causal_moe_targets(
    panel: pd.DataFrame,
    config: CausalMoEConfig | None = None,
) -> pd.DataFrame:
    """Stroit next-session targety chistoi batch-funkciei bez skrytogo sostoyaniya."""
    return CausalDailyMixtureOfExperts(config).transform(panel)
