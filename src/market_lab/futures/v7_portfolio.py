"""Causal post-sleeve risk targeting dlya futures-v7."""

from __future__ import annotations

import json
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures.portfolio_construction import (
    COVARIANCE_SESSIONS,
    PORTFOLIO_ASSETS,
    build_causal_portfolio_targets,
)

# Fiksirovannaya annual target volatility posle agregacii vseh sleeves.
V7_ANNUAL_TARGET_VOLATILITY: Final[float] = 0.20
# Zhestkii predel gross notional bez ispolzovaniya leverage dlya stretch-celi.
V7_GROSS_CAP: Final[float] = 1.0
# Chislo sessii v annualization covariance.
V7_TRADING_SESSIONS: Final[int] = 252
# Versiya netuniruemogo causal risk overlay.
V7_PORTFOLIO_VERSION: Final[str] = "futures-v7-post-sleeve-vol-target-v1"


def _normalize_market_returns(market_panel: pd.DataFrame) -> pd.DataFrame:
    """Stroit simple returns iz factual closes bez zapolneniya propuskov."""
    required = {"session_date", "asset", "adjusted_close"}
    if missing := required - set(market_panel.columns):
        raise ValueError(f"Market panel ne soderzhit kolonok: {sorted(missing)}")
    frame = market_panel.loc[:, sorted(required)].copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise")
    if frame["session_date"].dt.tz is not None:
        frame["session_date"] = (
            frame["session_date"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
        )
    frame["session_date"] = frame["session_date"].dt.normalize()
    frame["asset"] = frame["asset"].astype("string").str.strip().str.upper()
    unknown = sorted(set(frame["asset"].dropna()) - set(PORTFOLIO_ASSETS))
    if unknown:
        raise ValueError(f"Market panel soderzhit neizvestnye assets: {unknown}")
    if frame.duplicated(["session_date", "asset"]).any():
        raise ValueError("Market panel soderzhit duplicate session/asset")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    valid = np.isfinite(frame["adjusted_close"]) & frame["adjusted_close"].gt(0.0)
    frame.loc[~valid, "adjusted_close"] = np.nan
    closes = (
        frame.pivot(index="session_date", columns="asset", values="adjusted_close")
        .reindex(columns=PORTFOLIO_ASSETS)
        .sort_index()
    )
    return closes.pct_change(fill_method=None)


def _causal_covariance(returns: pd.DataFrame, decision_date: pd.Timestamp) -> pd.DataFrame:
    """Schitaet sample covariance tolko po poslednim factual returns <= D."""
    history = returns.loc[returns.index <= decision_date].tail(COVARIANCE_SESSIONS)
    if len(history) < COVARIANCE_SESSIONS:
        return pd.DataFrame(np.nan, index=PORTFOLIO_ASSETS, columns=PORTFOLIO_ASSETS)
    covariance = history.cov() * V7_TRADING_SESSIONS
    return covariance.reindex(index=PORTFOLIO_ASSETS, columns=PORTFOLIO_ASSETS)


def _expected_volatility(weights: pd.Series, covariance: pd.DataFrame) -> float:
    """Vozvrashchaet annual volatility dlya factual nonzero portfolio legs."""
    active = weights.index[weights.abs().gt(0.0)].tolist()
    if not active:
        return 0.0
    matrix = covariance.loc[active, active].to_numpy(dtype=float)
    vector = weights.loc[active].to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        return float("nan")
    variance = float(vector @ matrix @ vector)
    if not np.isfinite(variance) or variance < -1e-12:
        return float("nan")
    return float(np.sqrt(max(variance, 0.0)))


def _rescale_snapshot(
    snapshot: pd.DataFrame,
    covariance: pd.DataFrame,
) -> tuple[pd.Series, float, float, float, str]:
    """Masshtabiruet gotovye sleeves vverh ili vniz do risk-target i gross cap."""
    weights = snapshot.set_index("asset")["target_weight"].reindex(PORTFOLIO_ASSETS)
    weights = pd.to_numeric(weights, errors="raise").astype(float)
    if not np.isfinite(weights.to_numpy()).all():
        raise ValueError("Base target weights dolzhny byt konechnymi")
    gross_before = float(weights.abs().sum())
    expected_before = _expected_volatility(weights, covariance)
    if gross_before <= 0.0:
        return weights, 0.0, 0.0, 0.0, "all_cash_base_target"
    if not np.isfinite(expected_before) or expected_before <= 0.0:
        return weights * 0.0, 0.0, 0.0, 0.0, "invalid_causal_covariance"
    volatility_scale = V7_ANNUAL_TARGET_VOLATILITY / expected_before
    gross_scale = V7_GROSS_CAP / gross_before
    scale = float(min(volatility_scale, gross_scale))
    weights *= scale
    weights.loc[weights.abs().lt(1e-15)] = 0.0
    gross_after = float(weights.abs().sum())
    expected_after = _expected_volatility(weights, covariance)
    if not np.isfinite(expected_after):
        return weights * 0.0, 0.0, 0.0, 0.0, "invalid_scaled_risk"
    reason = "gross_cap" if gross_scale < volatility_scale else "volatility_target"
    return weights, gross_after, float(expected_after), scale, reason


def _v7_provenance(
    base_payload: str,
    *,
    gross_before: float,
    expected_before: float,
    scale: float,
    scale_reason: str,
) -> str:
    """Rasshiryaet base provenance stabilnym causal post-sleeve audit."""
    try:
        payload: dict[str, Any] = json.loads(base_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Base provenance dolzhen byt valid JSON") from exc
    payload.update(
        {
            "v7_portfolio_version": V7_PORTFOLIO_VERSION,
            "post_sleeve_annual_target_volatility": V7_ANNUAL_TARGET_VOLATILITY,
            "post_sleeve_gross_cap": V7_GROSS_CAP,
            "post_sleeve_gross_before": gross_before,
            "post_sleeve_expected_volatility_before": expected_before,
            "post_sleeve_scale": scale,
            "post_sleeve_scale_reason": scale_reason,
            "post_sleeve_bidirectional_scaling": True,
            "uses_future_prices_or_labels": False,
        }
    )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_causal_v7_portfolio_targets(
    market_panel: pd.DataFrame,
    score_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Stroit v7 targets s causal vol-targeting posle agregacii pyati sleeves."""
    base = build_causal_portfolio_targets(market_panel, score_frame)
    if base.empty:
        return base
    returns = _normalize_market_returns(market_panel)
    rows: list[dict[str, Any]] = []
    for decision_date, snapshot in base.groupby("decision_date", sort=True):
        ordered = snapshot.set_index("asset").reindex(PORTFOLIO_ASSETS).reset_index()
        if ordered["provenance"].isna().any():
            raise ValueError("Base portfolio ne soderzhit polnyi asset snapshot")
        covariance = _causal_covariance(returns, pd.Timestamp(decision_date))
        base_weights = ordered.set_index("asset")["target_weight"].astype(float)
        gross_before = float(base_weights.abs().sum())
        expected_before = _expected_volatility(base_weights, covariance)
        weights, gross, expected, scale, reason = _rescale_snapshot(ordered, covariance)
        for record in ordered.to_dict("records"):
            asset = str(record["asset"])
            rows.append(
                {
                    "decision_date": pd.Timestamp(decision_date),
                    "asset": asset,
                    "target_weight": float(weights[asset]),
                    "gross": gross,
                    "expected_annual_volatility": expected,
                    "provenance": _v7_provenance(
                        str(record["provenance"]),
                        gross_before=gross_before,
                        expected_before=float(expected_before),
                        scale=scale,
                        scale_reason=reason,
                    ),
                }
            )
    return pd.DataFrame(rows, columns=base.columns)


__all__ = [
    "V7_ANNUAL_TARGET_VOLATILITY",
    "V7_GROSS_CAP",
    "V7_PORTFOLIO_VERSION",
    "build_causal_v7_portfolio_targets",
]
