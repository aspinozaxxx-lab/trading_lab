"""Causal'noe obedinenie market-MoE s novostnymi i makro shokami."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

FUSION_ASSETS: Final[tuple[str, ...]] = (  # Fiksirovannyi futures-universe.
    "SI",
    "RI",
    "BR",
    "MIX",
)
FUSION_CANDIDATES: Final[tuple[str, ...]] = (  # Konechnyi spisok do OOS-rascheta.
    "base_moe",
    "information_overlay",
    "information_confirmation",
)
MACRO_CANDIDATES: Final[tuple[str, ...]] = (  # CBR-only kandidaty pri external 429.
    "base_moe",
    "macro_overlay",
    "macro_confirmation",
)
RISK_CHANNELS: Final[tuple[str, ...]] = (  # Novostnye kanaly obshchego risk-off.
    "sanctions_russia",
    "geopolitics_russia",
    "russian_credit",
    "global_risk",
)
ENERGY_CHANNELS: Final[tuple[str, ...]] = (  # Novostnye kanaly nefti i gaza.
    "oil_supply",
    "gas_europe",
)
FUSION_REQUIRED_BASE: Final[frozenset[str]] = frozenset(  # Skhema market-targetov.
    {
        "trade_date",
        "asset_code",
        "target_score",
        "target_weight",
        "signal_valid",
        "target_session_offset",
    }
)
INFORMATION_SENSITIVITY: Final[dict[str, dict[str, float]]] = {  # Ekonomicheskie osi.
    "currency_stress": {"SI": 1.0, "RI": -0.35, "BR": 0.0, "MIX": -0.35},
    "risk_off": {"SI": 0.85, "RI": -1.0, "BR": -0.25, "MIX": -1.0},
    "energy_supply": {"SI": 0.0, "RI": 0.15, "BR": 1.0, "MIX": 0.10},
    "monetary_tightening": {"SI": -0.60, "RI": -0.60, "BR": 0.0, "MIX": -0.60},
}
FUSION_EPSILON: Final[float] = 1e-12  # Dopusk normirovki i znakov.


@dataclass(frozen=True, slots=True)
class CausalInformationFusionConfig:
    """Fiksiruet silu overlay i cash-gate bez podbora po OOS returns."""

    information_budget: float = 0.35
    strong_event_threshold: float = 0.65
    conflict_gross_scale: float = 0.25
    confirmation_boost: float = 1.15
    cbr_scale_lookback: int = 60
    cbr_minimum_history: int = 20
    shock_clip: float = 3.0

    def __post_init__(self) -> None:
        """Proveryaet bounded parametry do dostupa k information frame."""
        if not 0.0 < self.information_budget < 0.5:
            raise ValueError("information_budget dolzhen byt' v (0, 0.5)")
        if not 0.0 < self.strong_event_threshold <= 1.0:
            raise ValueError("strong_event_threshold dolzhen byt' v (0, 1]")
        if not 0.0 <= self.conflict_gross_scale <= 1.0:
            raise ValueError("conflict_gross_scale dolzhen byt' v [0, 1]")
        if not 1.0 <= self.confirmation_boost <= 1.5:
            raise ValueError("confirmation_boost dolzhen byt' v [1, 1.5]")
        if self.cbr_scale_lookback < 20 or self.cbr_minimum_history < 10:
            raise ValueError("CBR scale trebuet dostatochnuyu proshluyu istoriyu")
        if self.cbr_minimum_history > self.cbr_scale_lookback:
            raise ValueError("cbr_minimum_history ne mozhet prevyshat' lookback")
        if self.shock_clip <= 0.0:
            raise ValueError("shock_clip dolzhen byt' polozhitel'nym")


def _asset_code(value: object) -> str:
    """Privodit RTS k ekonomicheskomu RI i ostal'nye simvoly k upper-case."""
    code = str(value).strip().upper()
    return "RI" if code == "RTS" else code


def _normalize_base(base_targets: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet polnyi market-MoE snapshot bez dostupa k returns."""
    if missing := FUSION_REQUIRED_BASE - set(base_targets.columns):
        raise ValueError(f"V base targets net kolonok: {sorted(missing)}")
    frame = base_targets.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    frame["target_score"] = pd.to_numeric(frame["target_score"], errors="raise")
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="raise")
    if (~np.isfinite(frame[["target_score", "target_weight"]])).any().any():
        raise ValueError("Base score i weight dolzhny byt' konechnymi")
    if (frame["target_score"].abs() > 1.0 + FUSION_EPSILON).any():
        raise ValueError("Base target_score dolzhen byt' v [-1, 1]")
    if not frame["target_session_offset"].eq(1).all():
        raise ValueError("Fusion podderzhivaet tol'ko next-session target")
    if frame.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("Povtor asset v base snapshot")
    expected = frozenset(FUSION_ASSETS)
    for trade_date, snapshot in frame.groupby("trade_date", sort=False):
        if frozenset(snapshot["asset_code"]) != expected:
            raise ValueError(f"Nepolnyi base snapshot na {trade_date.date()}")
        if snapshot["target_weight"].abs().sum() > 1.0 + FUSION_EPSILON:
            raise ValueError("Base gross target prevyshaet 1x")
    return frame.sort_values(["trade_date", "asset_code"]).reset_index(drop=True)


def _normalize_decision_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    """Svyazyvaet session-date s factual timezone-aware momentom resheniya."""
    required = {"trade_date", "decision_at"}
    if missing := required - set(calendar.columns):
        raise ValueError(f"V decision calendar net kolonok: {sorted(missing)}")
    frame = calendar.loc[:, ["trade_date", "decision_at"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
    if frame.duplicated("trade_date").any() or frame.duplicated("decision_at").any():
        raise ValueError("Decision calendar dolzhen byt' odnoznachnym")
    return frame.sort_values("trade_date").reset_index(drop=True)


def _normalize_information(information: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet odin causal information snapshot na kazhdyi decision timestamp."""
    if "decision_at" not in information:
        raise ValueError("Information frame trebuet decision_at")
    frame = information.copy()
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
    if frame.duplicated("decision_at").any():
        raise ValueError("Povtor decision_at v information frame")
    for column in frame.columns:
        if column.endswith("available_at"):
            frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
            future = frame[column].notna() & (frame[column] > frame["decision_at"])
            if future.any():
                raise ValueError(f"Budushchaya informaciya v {column}")
    return frame.sort_values("decision_at").reset_index(drop=True)


def _required_information_columns() -> frozenset[str]:
    """Vozvrashchaet zapechatannyi minimum novostnyh i makro priznakov."""
    channels = (
        *RISK_CHANNELS,
        *ENERGY_CHANNELS,
        "ruble_attention",
        "russian_monetary",
    )
    gdelt = {
        f"gdelt_{channel}_{suffix}"
        for channel in channels
        for suffix in ("attention_surprise", "tone_surprise")
    }
    return frozenset(
        gdelt
        | {
            "cbr_ruonia_change",
            "cbr_key_rate_change",
            "cbr_usd_rub_official_change",
        }
    )


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    """Chitaet finite float, ostavlyaya otsutstvie kak sleeping signal."""
    values = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return values.where(np.isfinite(values), np.nan)


def _news_event(frame: pd.DataFrame, channel: str, clip: float) -> pd.Series:
    """Prevrashchaet vspysk vnimaniya i ton v napravlennyi bounded event."""
    attention = _numeric(frame, f"gdelt_{channel}_attention_surprise").clip(0.0, clip)
    tone = _numeric(frame, f"gdelt_{channel}_tone_surprise").clip(-clip, clip)
    intensity = attention / clip
    direction = np.tanh(-tone / max(clip / 2.0, FUSION_EPSILON))
    return (intensity * direction).where(attention.notna() & tone.notna())


def _causal_robust_z(
    values: pd.Series,
    lookback: int,
    minimum_history: int,
    clip: float,
) -> pd.Series:
    """Masshtabiruet tekushchii makro-shok tol'ko po proshlym nablyudeniyam."""
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    past = numeric.shift(1).rolling(lookback, min_periods=minimum_history)
    median = past.median()
    absolute_deviation = (numeric - median).abs()
    mad = absolute_deviation.shift(1).rolling(
        lookback,
        min_periods=minimum_history,
    ).median()
    scaled = (numeric - median) / (1.4826 * mad).replace(0.0, np.nan)
    return scaled.clip(-clip, clip) / clip


def _information_state(
    frame: pd.DataFrame,
    config: CausalInformationFusionConfig,
) -> pd.DataFrame:
    """Stroit chetyre sleeping shock-axis bez price ili return label."""
    if missing := _required_information_columns() - set(frame.columns):
        raise ValueError(f"V information frame net zapechatannyh kolonok: {sorted(missing)}")
    output = frame[["decision_at"]].copy()
    risk_events = pd.concat(
        [_news_event(frame, channel, config.shock_clip) for channel in RISK_CHANNELS],
        axis=1,
    )
    energy_events = pd.concat(
        [_news_event(frame, channel, config.shock_clip) for channel in ENERGY_CHANNELS],
        axis=1,
    )
    ruble_event = _news_event(frame, "ruble_attention", config.shock_clip)
    monetary_event = _news_event(frame, "russian_monetary", config.shock_clip)
    risk_off = risk_events.mean(axis=1, skipna=True)
    energy_supply = energy_events.mean(axis=1, skipna=True)
    usd_rub = _causal_robust_z(
        _numeric(frame, "cbr_usd_rub_official_change"),
        config.cbr_scale_lookback,
        config.cbr_minimum_history,
        config.shock_clip,
    )
    key_rate = _causal_robust_z(
        _numeric(frame, "cbr_key_rate_change"),
        config.cbr_scale_lookback,
        config.cbr_minimum_history,
        config.shock_clip,
    )
    ruonia = _causal_robust_z(
        _numeric(frame, "cbr_ruonia_change"),
        config.cbr_scale_lookback,
        config.cbr_minimum_history,
        config.shock_clip,
    )
    output["shock_risk_off"] = risk_off.fillna(0.0).clip(-1.0, 1.0)
    output["shock_energy_supply"] = energy_supply.fillna(0.0).clip(-1.0, 1.0)
    output["shock_currency_stress"] = (
        0.45 * ruble_event.fillna(0.0)
        + 0.35 * usd_rub.fillna(0.0)
        + 0.20 * output["shock_risk_off"]
    ).clip(-1.0, 1.0)
    output["shock_monetary_tightening"] = (
        0.50 * key_rate.fillna(0.0)
        + 0.25 * ruonia.fillna(0.0)
        + 0.25 * monetary_event.fillna(0.0)
    ).clip(-1.0, 1.0)
    shock_columns = [column for column in output if column.startswith("shock_")]
    output["information_activation"] = output[shock_columns].abs().max(axis=1)
    output["information_available"] = frame[list(_required_information_columns())].notna().any(
        axis=1
    )
    output["information_source_mode"] = "full_gdelt_cbr"
    return output


def _macro_information_state(
    frame: pd.DataFrame,
    config: CausalInformationFusionConfig,
) -> pd.DataFrame:
    """Stroit yavno CBR-only state bez synthetic ili skryto propushchennyh news."""
    required = {
        "cbr_ruonia_change",
        "cbr_key_rate_change",
        "cbr_usd_rub_official_change",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V CBR-only frame net kolonok: {sorted(missing)}")
    output = frame[["decision_at"]].copy()
    usd_rub = _causal_robust_z(
        _numeric(frame, "cbr_usd_rub_official_change"),
        config.cbr_scale_lookback,
        config.cbr_minimum_history,
        config.shock_clip,
    )
    key_rate = _causal_robust_z(
        _numeric(frame, "cbr_key_rate_change"),
        config.cbr_scale_lookback,
        config.cbr_minimum_history,
        config.shock_clip,
    )
    ruonia = _causal_robust_z(
        _numeric(frame, "cbr_ruonia_change"),
        config.cbr_scale_lookback,
        config.cbr_minimum_history,
        config.shock_clip,
    )
    output["shock_currency_stress"] = usd_rub.fillna(0.0).clip(-1.0, 1.0)
    output["shock_risk_off"] = 0.0
    output["shock_energy_supply"] = 0.0
    output["shock_monetary_tightening"] = (
        0.65 * key_rate.fillna(0.0) + 0.35 * ruonia.fillna(0.0)
    ).clip(-1.0, 1.0)
    shock_columns = [column for column in output if column.startswith("shock_")]
    output["information_activation"] = output[shock_columns].abs().max(axis=1)
    output["information_available"] = frame[list(required)].notna().any(axis=1)
    output["information_source_mode"] = "cbr_only"
    return output


def _asset_information_score(state: pd.DataFrame, asset_code: str) -> pd.Series:
    """Proeciruet chetyre ekonomicheskie osi v score odnogo futures asset."""
    score = pd.Series(0.0, index=state.index, dtype=float)
    for axis, sensitivities in INFORMATION_SENSITIVITY.items():
        score += state[f"shock_{axis}"] * sensitivities[asset_code]
    return np.tanh(score)


def _normalize_candidate_weights(frame: pd.DataFrame, gross_scale: pd.Series) -> pd.Series:
    """Normalizuet score v bounded gross i razreshaet cash pri konflikte."""
    denominator = frame["candidate_score"].abs().groupby(frame["trade_date"]).transform("sum")
    normalized = frame["candidate_score"] / denominator.where(denominator > FUSION_EPSILON)
    return normalized.fillna(0.0) * gross_scale.clip(0.0, 1.0)


def _candidate_frames(
    merged: pd.DataFrame,
    config: CausalInformationFusionConfig,
    candidate_ids: tuple[str, str, str] = FUSION_CANDIDATES,
) -> pd.DataFrame:
    """Vypuskaet vse tri zapechatannyh kandidata, ne vybiraya po rezultatam."""
    base = merged.copy()
    base["candidate_id"] = candidate_ids[0]
    base["candidate_score"] = base["target_score"]
    base["candidate_weight"] = base["target_weight"]
    base["gross_scale"] = base["target_weight"].abs().groupby(base["trade_date"]).transform(
        "sum"
    )

    overlay = merged.copy()
    overlay["candidate_id"] = candidate_ids[1]
    active_budget = config.information_budget * overlay["information_activation"]
    overlay["candidate_score"] = (
        (1.0 - active_budget) * overlay["target_score"]
        + active_budget * overlay["information_score"]
    )
    overlay["gross_scale"] = 1.0
    overlay["candidate_weight"] = _normalize_candidate_weights(
        overlay,
        overlay["gross_scale"],
    )

    confirmation = merged.copy()
    confirmation["candidate_id"] = candidate_ids[2]
    active = confirmation["information_activation"] >= config.strong_event_threshold
    signs_disagree = (
        np.sign(confirmation["target_score"])
        * np.sign(confirmation["information_score"])
        < 0.0
    )
    signs_agree = (
        np.sign(confirmation["target_score"])
        * np.sign(confirmation["information_score"])
        > 0.0
    )
    confirmation["candidate_score"] = confirmation["target_score"]
    confirmation["candidate_score"] = confirmation["candidate_score"].where(
        ~(active & signs_agree),
        (confirmation["candidate_score"] * config.confirmation_boost).clip(-1.0, 1.0),
    )
    confirmation["gross_scale"] = np.where(
        active & signs_disagree,
        config.conflict_gross_scale,
        1.0,
    )
    confirmation["candidate_weight"] = _normalize_candidate_weights(
        confirmation,
        confirmation["gross_scale"],
    )
    output = pd.concat([base, overlay, confirmation], ignore_index=True)
    output.loc[~output["signal_valid"], ["candidate_score", "candidate_weight"]] = 0.0
    selected = [
        "candidate_id",
        "trade_date",
        "decision_at",
        "asset_code",
        "target_session_offset",
        "signal_valid",
        "candidate_score",
        "candidate_weight",
        "gross_scale",
        "information_score",
        "information_activation",
        "information_available",
        "information_source_mode",
        "shock_currency_stress",
        "shock_risk_off",
        "shock_energy_supply",
        "shock_monetary_tightening",
    ]
    selected_output = output[selected].copy()
    selected_output["_candidate_order"] = selected_output["candidate_id"].map(
        {candidate: index for index, candidate in enumerate(candidate_ids)}
    )
    return selected_output.sort_values(
        ["_candidate_order", "trade_date", "asset_code"]
    ).drop(columns="_candidate_order").reset_index(drop=True)


class CausalInformationFusion:
    """Obedinyaet market-MoE i dostupnye information shocks bez obucheniya na OOS."""

    def __init__(self, config: CausalInformationFusionConfig | None = None) -> None:
        """Fiksiruet konfiguraciyu do peredachi feature frames."""
        self.config = config or CausalInformationFusionConfig()

    def transform(
        self,
        base_targets: pd.DataFrame,
        information_features: pd.DataFrame,
        decision_calendar: pd.DataFrame,
    ) -> pd.DataFrame:
        """Stroit vse kandidaty po exact decision timestamp bez chteniya returns."""
        base = _normalize_base(base_targets)
        calendar = _normalize_decision_calendar(decision_calendar)
        information = _normalize_information(information_features)
        missing_dates = set(base["trade_date"]) - set(calendar["trade_date"])
        if missing_dates:
            raise ValueError("Decision calendar ne pokryvaet vse base dates")
        dated = base.merge(calendar, on="trade_date", how="left", validate="many_to_one")
        joined = dated.merge(
            information,
            on="decision_at",
            how="left",
            validate="many_to_one",
        )
        unique_information = joined.drop_duplicates("decision_at").sort_values("decision_at")
        state = _information_state(unique_information, self.config)
        joined = joined.merge(state, on="decision_at", how="left", validate="many_to_one")
        joined["information_score"] = np.nan
        for asset in FUSION_ASSETS:
            mask = joined["asset_code"] == asset
            joined.loc[mask, "information_score"] = _asset_information_score(
                joined.loc[mask],
                asset,
            ).to_numpy()
        joined["information_score"] = joined["information_score"].fillna(0.0)
        return _candidate_frames(joined, self.config)


class CausalMacroFusion:
    """Obedinyaet market-MoE tol'ko s factual CBR pri nedostupnom news API."""

    def __init__(self, config: CausalInformationFusionConfig | None = None) -> None:
        """Fiksiruet tu zhe bounded konfiguraciyu do CBR-only frame."""
        self.config = config or CausalInformationFusionConfig()

    def transform(
        self,
        base_targets: pd.DataFrame,
        cbr_features: pd.DataFrame,
        decision_calendar: pd.DataFrame,
    ) -> pd.DataFrame:
        """Stroit base/macro kandidaty i yavno markiruet otsutstvie GDELT."""
        base = _normalize_base(base_targets)
        calendar = _normalize_decision_calendar(decision_calendar)
        information = _normalize_information(cbr_features)
        missing_dates = set(base["trade_date"]) - set(calendar["trade_date"])
        if missing_dates:
            raise ValueError("Decision calendar ne pokryvaet vse base dates")
        dated = base.merge(calendar, on="trade_date", how="left", validate="many_to_one")
        joined = dated.merge(
            information,
            on="decision_at",
            how="left",
            validate="many_to_one",
        )
        unique_information = joined.drop_duplicates("decision_at").sort_values("decision_at")
        state = _macro_information_state(unique_information, self.config)
        joined = joined.merge(state, on="decision_at", how="left", validate="many_to_one")
        joined["information_score"] = np.nan
        for asset in FUSION_ASSETS:
            mask = joined["asset_code"] == asset
            joined.loc[mask, "information_score"] = _asset_information_score(
                joined.loc[mask],
                asset,
            ).to_numpy()
        joined["information_score"] = joined["information_score"].fillna(0.0)
        return _candidate_frames(joined, self.config, MACRO_CANDIDATES)


def build_information_conditioned_targets(
    base_targets: pd.DataFrame,
    information_features: pd.DataFrame,
    decision_calendar: pd.DataFrame,
    config: CausalInformationFusionConfig | None = None,
) -> pd.DataFrame:
    """Predostavlyaet chistuyu batch-funkciyu dlya zapechatannogo eksperimenta."""
    return CausalInformationFusion(config).transform(
        base_targets,
        information_features,
        decision_calendar,
    )


def build_macro_conditioned_targets(
    base_targets: pd.DataFrame,
    cbr_features: pd.DataFrame,
    decision_calendar: pd.DataFrame,
    config: CausalInformationFusionConfig | None = None,
) -> pd.DataFrame:
    """Predostavlyaet yavno CBR-only batch-funkciyu bez maskirovki GDELT 429."""
    return CausalMacroFusion(config).transform(
        base_targets,
        cbr_features,
        decision_calendar,
    )


__all__ = [
    "FUSION_CANDIDATES",
    "MACRO_CANDIDATES",
    "CausalInformationFusion",
    "CausalInformationFusionConfig",
    "CausalMacroFusion",
    "build_information_conditioned_targets",
    "build_macro_conditioned_targets",
]
