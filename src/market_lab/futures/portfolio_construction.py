"""Fiksirovannoe causal postroenie futures-portfelya iz daily candidate scores."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# Zamorozhennyi poryadok polnogo snapshot iz chetyreh logical assets.
PORTFOLIO_ASSETS = ("SI", "RI", "BR", "MIX")
# Span causal EWMA annualized volatility iz adjusted close.
EWMA_VOLATILITY_SPAN = 20
# Chislo factual return-sessii dlya sample covariance.
COVARIANCE_SESSIONS = 60
# Predseal target annual volatility s uchetom 1x gross i stretch-goal.
ANNUAL_TARGET_VOLATILITY = 0.20
# Zhestkii predel summy absolyutnyh target weights.
PORTFOLIO_GROSS_CAP = 1.0
# Chislo ravnyh causal sleeves dlya kontrolya oborota.
TURNOVER_SLEEVES = 5
# Fiksirovannoe chislo torgovyh sessii dlya annualization.
TRADING_SESSIONS_PER_YEAR = 252
# Audit-versiya neoptimiziruemogo portfolio constructor.
PORTFOLIO_CONSTRUCTION_VERSION = "futures-causal-risk-portfolio-v1"
# Obyazatel'nye polya factual market panel bez budushchih cen.
MARKET_COLUMNS = frozenset({"session_date", "asset", "adjusted_close"})
# Obyazatel'nye polya causal candidate score snapshots.
SCORE_COLUMNS = frozenset({"decision_date", "asset", "candidate_score"})
# Stabil'naya skhema polnogo output snapshot.
OUTPUT_COLUMNS = (
    "decision_date",
    "asset",
    "target_weight",
    "gross",
    "expected_annual_volatility",
    "provenance",
)


@dataclass(frozen=True, slots=True)
class _RawSnapshot:
    """Hranit raw weights, eligibility i covariance odnoi decision-date."""

    decision_date: pd.Timestamp
    raw_weights: pd.Series
    eligible: pd.Series
    reasons: dict[str, str]
    covariance: pd.DataFrame


def _normalize_dates(values: pd.Series, label: str) -> pd.Series:
    """Normalizuet daty bez smeshcheniya causal cutoff v budushchee."""
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.isna().any():
        raise ValueError(f"{label} soderzhit propusk daty")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return parsed.dt.normalize()


def _normalize_asset(values: pd.Series, label: str) -> pd.Series:
    """Trebuet tolko chetyre zamorozhennyh logical asset bez aliases."""
    normalized = values.astype("string").str.strip().str.upper()
    if normalized.isna().any() or normalized.eq("").any():
        raise ValueError(f"{label} soderzhit pustoi asset")
    unknown = sorted(set(normalized) - set(PORTFOLIO_ASSETS))
    if unknown:
        raise ValueError(f"{label} soderzhit neizvestnye assets: {unknown}")
    return normalized


def _normalize_market(market_panel: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet factual adjusted close i ostavlyaet missing kak cash-signal."""
    if missing := MARKET_COLUMNS - set(market_panel.columns):
        raise ValueError(f"Market panel ne soderzhit kolonok: {sorted(missing)}")
    market = market_panel.loc[:, sorted(MARKET_COLUMNS)].copy()
    market["session_date"] = _normalize_dates(market["session_date"], "market_panel")
    market["asset"] = _normalize_asset(market["asset"], "market_panel")
    market["adjusted_close"] = pd.to_numeric(market["adjusted_close"], errors="coerce")
    finite_positive = np.isfinite(market["adjusted_close"].fillna(np.nan)) & market[
        "adjusted_close"
    ].gt(0.0)
    market.loc[~finite_positive, "adjusted_close"] = np.nan
    if market.duplicated(["session_date", "asset"]).any():
        raise ValueError("Market panel soderzhit duplicate session/asset")
    return market.sort_values(["session_date", "asset"], kind="mergesort").reset_index(
        drop=True
    )


def _normalize_scores(score_frame: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet candidate scores i sohranyaet NaN kak yavnyi cash."""
    if missing := SCORE_COLUMNS - set(score_frame.columns):
        raise ValueError(f"Score frame ne soderzhit kolonok: {sorted(missing)}")
    scores = score_frame.loc[:, sorted(SCORE_COLUMNS)].copy()
    scores["decision_date"] = _normalize_dates(scores["decision_date"], "score_frame")
    scores["asset"] = _normalize_asset(scores["asset"], "score_frame")
    scores["candidate_score"] = pd.to_numeric(scores["candidate_score"], errors="coerce")
    scores.loc[~np.isfinite(scores["candidate_score"].fillna(np.nan)), "candidate_score"] = (
        np.nan
    )
    if scores.duplicated(["decision_date", "asset"]).any():
        raise ValueError("Score frame soderzhit duplicate decision/asset")
    return scores.sort_values(["decision_date", "asset"], kind="mergesort").reset_index(
        drop=True
    )


def _market_matrices(market: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stroit causal close, simple returns i annualized EWMA volatility."""
    closes = (
        market.pivot(index="session_date", columns="asset", values="adjusted_close")
        .reindex(columns=PORTFOLIO_ASSETS)
        .sort_index()
    )
    returns = closes.pct_change(fill_method=None)
    volatility = returns.ewm(
        span=EWMA_VOLATILITY_SPAN,
        adjust=False,
        min_periods=EWMA_VOLATILITY_SPAN,
    ).std(bias=False) * np.sqrt(TRADING_SESSIONS_PER_YEAR)
    return closes, returns, volatility


def _current_score(scores: pd.DataFrame, decision_date: pd.Timestamp) -> pd.Series:
    """Vozvrashchaet polnyi score snapshot, zapolnyaya otsutstvuyushchii asset NaN."""
    selected = scores.loc[scores["decision_date"].eq(decision_date)]
    return selected.set_index("asset")["candidate_score"].reindex(PORTFOLIO_ASSETS)


def _eligibility_snapshot(
    decision_date: pd.Timestamp,
    current_score: pd.Series,
    closes: pd.DataFrame,
    returns: pd.DataFrame,
    volatility: pd.DataFrame,
) -> tuple[pd.Series, dict[str, str], pd.Series, pd.DataFrame]:
    """Opredelyaet causal eligibility i 60-session covariance na cutoff D."""
    eligible = pd.Series(False, index=PORTFOLIO_ASSETS, dtype=bool)
    reasons: dict[str, str] = {}
    current_volatility = pd.Series(np.nan, index=PORTFOLIO_ASSETS, dtype=float)
    if decision_date not in closes.index:
        return (
            eligible,
            {asset: "missing_current_market_session" for asset in PORTFOLIO_ASSETS},
            current_volatility,
            pd.DataFrame(np.nan, index=PORTFOLIO_ASSETS, columns=PORTFOLIO_ASSETS),
        )
    historical_returns = returns.loc[returns.index <= decision_date].tail(COVARIANCE_SESSIONS)
    if decision_date in volatility.index:
        current_volatility = volatility.loc[decision_date].reindex(PORTFOLIO_ASSETS)
    for asset in PORTFOLIO_ASSETS:
        if not np.isfinite(current_score[asset]):
            reasons[asset] = "missing_candidate_score"
            continue
        if not np.isfinite(closes.at[decision_date, asset]):
            reasons[asset] = "missing_current_adjusted_close"
            continue
        asset_volatility = current_volatility[asset]
        if not np.isfinite(asset_volatility) or asset_volatility <= 0.0:
            reasons[asset] = "insufficient_ewma_volatility"
            continue
        if (
            len(historical_returns) < COVARIANCE_SESSIONS
            or historical_returns[asset].isna().any()
        ):
            reasons[asset] = "insufficient_covariance_history"
            continue
        eligible[asset] = True
        reasons[asset] = "eligible"
    covariance = historical_returns.cov() * TRADING_SESSIONS_PER_YEAR
    covariance = covariance.reindex(index=PORTFOLIO_ASSETS, columns=PORTFOLIO_ASSETS)
    eligible_assets = eligible.index[eligible].tolist()
    if eligible_assets and not np.isfinite(
        covariance.loc[eligible_assets, eligible_assets].to_numpy(dtype=float)
    ).all():
        for asset in eligible_assets:
            eligible[asset] = False
            reasons[asset] = "invalid_covariance_matrix"
    return eligible, reasons, current_volatility, covariance


def _expected_volatility(weights: pd.Series, covariance: pd.DataFrame) -> float:
    """Schitaet annual portfolio volatility tolko po nonzero weights."""
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


def _raw_target(
    current_score: pd.Series,
    current_volatility: pd.Series,
    eligible: pd.Series,
    covariance: pd.DataFrame,
) -> pd.Series:
    """Stroit inverse-vol score portfolio s target-vol i gross cap bez tuning."""
    weights = pd.Series(0.0, index=PORTFOLIO_ASSETS, dtype=float)
    active = eligible.index[eligible].tolist()
    if not active:
        return weights
    inverse_volatility_signal = current_score.loc[active] / current_volatility.loc[active]
    if not np.isfinite(inverse_volatility_signal.to_numpy(dtype=float)).all():
        return weights
    weights.loc[active] = inverse_volatility_signal
    unscaled_volatility = _expected_volatility(weights, covariance)
    if not np.isfinite(unscaled_volatility) or unscaled_volatility <= 0.0:
        return pd.Series(0.0, index=PORTFOLIO_ASSETS, dtype=float)
    weights *= ANNUAL_TARGET_VOLATILITY / unscaled_volatility
    gross = float(weights.abs().sum())
    if gross > PORTFOLIO_GROSS_CAP:
        weights *= PORTFOLIO_GROSS_CAP / gross
    weights.loc[weights.abs().lt(1e-15)] = 0.0
    return weights


def _build_raw_snapshots(
    scores: pd.DataFrame,
    closes: pd.DataFrame,
    returns: pd.DataFrame,
    volatility: pd.DataFrame,
) -> list[_RawSnapshot]:
    """Stroit vse raw snapshots bez chteniya market posle kazhdoi decision D."""
    snapshots: list[_RawSnapshot] = []
    for decision_date in scores["decision_date"].drop_duplicates().sort_values():
        current_score = _current_score(scores, decision_date)
        eligible, reasons, current_volatility, covariance = _eligibility_snapshot(
            decision_date,
            current_score,
            closes,
            returns,
            volatility,
        )
        raw_weights = _raw_target(
            current_score,
            current_volatility,
            eligible,
            covariance,
        )
        snapshots.append(
            _RawSnapshot(
                decision_date=decision_date,
                raw_weights=raw_weights,
                eligible=eligible,
                reasons=reasons,
                covariance=covariance,
            )
        )
    return snapshots


def _causal_sleeve_average(raw_history: list[pd.Series]) -> pd.Series:
    """Usrednyaet current i chetyre proshlyh raw target, missing sleeves kak cash."""
    selected = raw_history[-TURNOVER_SLEEVES:]
    total = sum(selected, start=pd.Series(0.0, index=PORTFOLIO_ASSETS, dtype=float))
    return total / TURNOVER_SLEEVES


def _finalize_snapshot(
    sleeved: pd.Series,
    snapshot: _RawSnapshot,
) -> tuple[pd.Series, float, float, float]:
    """Obnulyaet current-ineligible assets i primenyaet tolko downward risk caps."""
    target = sleeved.where(snapshot.eligible, 0.0).astype(float)
    gross = float(target.abs().sum())
    if gross > PORTFOLIO_GROSS_CAP:
        target *= PORTFOLIO_GROSS_CAP / gross
    expected = _expected_volatility(target, snapshot.covariance)
    risk_scale = 1.0
    if np.isfinite(expected) and expected > ANNUAL_TARGET_VOLATILITY:
        risk_scale = ANNUAL_TARGET_VOLATILITY / expected
        target *= risk_scale
        expected = _expected_volatility(target, snapshot.covariance)
    if not np.isfinite(expected):
        target[:] = 0.0
        expected = 0.0
        risk_scale = 0.0
    target.loc[target.abs().lt(1e-15)] = 0.0
    gross = float(target.abs().sum())
    return target, gross, float(expected), risk_scale


def _provenance(
    snapshot: _RawSnapshot,
    asset: str,
    sleeved_weight: float,
    risk_scale: float,
) -> str:
    """Serializuet determinirovannyi per-row audit bez global future metadata."""
    payload: dict[str, Any] = {
        "version": PORTFOLIO_CONSTRUCTION_VERSION,
        "market_cutoff": snapshot.decision_date.date().isoformat(),
        "ewma_volatility_span": EWMA_VOLATILITY_SPAN,
        "covariance_sessions": COVARIANCE_SESSIONS,
        "annual_target_volatility": ANNUAL_TARGET_VOLATILITY,
        "gross_cap": PORTFOLIO_GROSS_CAP,
        "turnover_sleeves": TURNOVER_SLEEVES,
        "current_input_eligible": bool(snapshot.eligible[asset]),
        "cash_reason": snapshot.reasons[asset],
        "raw_target_weight": float(snapshot.raw_weights[asset]),
        "sleeved_weight_before_current_guards": float(sleeved_weight),
        "final_downward_risk_scale": float(risk_scale),
        "intended_execution": "next_factual_trade_date_open",
        "uses_future_prices_or_labels": False,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_causal_portfolio_targets(
    market_panel: pd.DataFrame,
    score_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Prevrashchaet daily scores v polnye causal target-weight snapshots."""
    market = _normalize_market(market_panel)
    scores = _normalize_scores(score_frame)
    if scores.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    closes, returns, volatility = _market_matrices(market)
    snapshots = _build_raw_snapshots(scores, closes, returns, volatility)
    rows: list[dict[str, Any]] = []
    raw_history: list[pd.Series] = []
    for snapshot in snapshots:
        raw_history.append(snapshot.raw_weights)
        sleeved = _causal_sleeve_average(raw_history)
        target, gross, expected, risk_scale = _finalize_snapshot(sleeved, snapshot)
        for asset in PORTFOLIO_ASSETS:
            rows.append(
                {
                    "decision_date": snapshot.decision_date,
                    "asset": asset,
                    "target_weight": float(target[asset]),
                    "gross": gross,
                    "expected_annual_volatility": expected,
                    "provenance": _provenance(
                        snapshot,
                        asset,
                        float(sleeved[asset]),
                        risk_scale,
                    ),
                }
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
