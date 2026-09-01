"""Causal multi-era online expert allocation for the V36 futures experiment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab import futures_v12_core4_correlation_trend as v12

ASSETS: Final[tuple[str, ...]] = v12.ASSETS
ACTIVE_EXPERTS: Final[tuple[str, ...]] = (
    "trend_21",
    "trend_63",
    "trend_126",
    "trend_252",
    "multi_horizon_trend",
    "curve_carry",
    "trend_carry_confirmation",
    "cross_asset_relative_trend",
    "horizon_consensus_trend",
)
EXPERTS: Final[tuple[str, ...]] = (*ACTIVE_EXPERTS, "cash")


@dataclass(frozen=True, slots=True)
class ExpertBuild:
    scores: dict[str, pd.DataFrame]
    expert_weights: pd.DataFrame
    expert_components: pd.DataFrame
    checks: dict[str, bool]


def _finite_trailing(values: np.ndarray, horizon: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    finite_values: list[float] = []
    for index, value in enumerate(values):
        if np.isfinite(value):
            finite_values.append(float(value))
        if len(finite_values) >= horizon:
            output[index] = float(sum(finite_values[-horizon:]))
    return output


def _finite_trailing_std(values: np.ndarray, horizon: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    finite_values: list[float] = []
    for index, value in enumerate(values):
        if np.isfinite(value):
            finite_values.append(float(value))
        if len(finite_values) >= horizon:
            output[index] = float(np.std(finite_values[-horizon:], ddof=1))
    return output


def _weekly_dates(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        pd.Series(dates, index=dates).groupby(dates.to_period("W-SUN")).max().to_numpy()
    )


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exponent = np.exp(shifted)
    return exponent / exponent.sum()


def build_expert_scores(panel: pd.DataFrame, config: dict[str, Any]) -> ExpertBuild:
    """Build fixed experts and update their weights only with prior-week evidence."""
    normalized = v12.normalize_signal_panel(panel)
    dates = pd.DatetimeIndex(normalized["trade_date"].drop_duplicates().sort_values())
    closes = normalized.pivot(index="trade_date", columns="asset", values="close").reindex(
        index=dates, columns=ASSETS
    )
    log_close = np.log(closes)
    returns = log_close.diff()
    date_gap = dates.to_series().diff().dt.days.to_numpy()
    returns.iloc[(date_gap > 7) | (date_gap <= 0)] = np.nan
    feature = config["features"]
    volatility = pd.DataFrame(index=dates, columns=ASSETS, dtype=float)
    horizon_scores: dict[int, pd.DataFrame] = {}
    for asset in ASSETS:
        values = returns[asset].to_numpy(dtype=float)
        volatility[asset] = _finite_trailing_std(
            values, int(feature["volatility_lookback"])
        ) * np.sqrt(252.0)
    daily_volatility = volatility.clip(
        lower=float(feature["volatility_floor_annualized"])
    ) / np.sqrt(252.0)
    for horizon in (21, 63, 126, 252):
        score = pd.DataFrame(index=dates, columns=ASSETS, dtype=float)
        for asset in ASSETS:
            momentum = _finite_trailing(returns[asset].to_numpy(dtype=float), horizon)
            scaled = momentum / (
                daily_volatility[asset].to_numpy(dtype=float) * np.sqrt(float(horizon))
            )
            score[asset] = np.clip(scaled, -2.0, 2.0) / 2.0
        horizon_scores[horizon] = score
    multi = sum(horizon_scores.values()) / 4.0

    required_curve = {"trade_date", "asset_code", "roll_yield", "curve_valid"}
    if missing := required_curve - set(panel.columns):
        raise ValueError(f"V36 panel lacks curve columns: {sorted(missing)}")
    curve = panel.loc[:, sorted(required_curve)].copy()
    curve["trade_date"] = pd.to_datetime(curve["trade_date"], errors="raise").dt.normalize()
    curve["asset"] = curve["asset_code"].map(v12._asset_code)
    curve["roll_yield"] = pd.to_numeric(curve["roll_yield"], errors="coerce")
    curve["curve_valid"] = curve["curve_valid"].fillna(False).astype(bool)
    carry_values = np.sign(curve["roll_yield"]).where(curve["curve_valid"], 0.0)
    carry = (
        curve.assign(carry=carry_values)
        .pivot(index="trade_date", columns="asset", values="carry")
        .reindex(index=dates, columns=ASSETS)
        .fillna(0.0)
    )
    confirmation = multi.where(np.sign(multi).eq(np.sign(carry)) & carry.ne(0.0), 0.0)
    relative = multi.sub(multi.mean(axis=1), axis=0).clip(-1.0, 1.0)
    horizon_stack = np.stack(
        [horizon_scores[horizon].to_numpy(dtype=float) for horizon in (21, 63, 126, 252)],
        axis=0,
    )
    positive = np.sum(horizon_stack > 0.0, axis=0)
    negative = np.sum(horizon_stack < 0.0, axis=0)
    consensus = multi.where((positive >= 3) | (negative >= 3), 0.0)
    matrices = {
        "trend_21": horizon_scores[21],
        "trend_63": horizon_scores[63],
        "trend_126": horizon_scores[126],
        "trend_252": horizon_scores[252],
        "multi_horizon_trend": multi,
        "curve_carry": carry,
        "trend_carry_confirmation": confirmation,
        "cross_asset_relative_trend": relative,
        "horizon_consensus_trend": consensus,
        "cash": pd.DataFrame(0.0, index=dates, columns=ASSETS),
    }
    weekly_dates = _weekly_dates(dates)
    weekly = {name: matrix.reindex(weekly_dates) for name, matrix in matrices.items()}
    learning = config["experts"]
    log_wealth = np.zeros(len(EXPERTS), dtype=float)
    prior_normalized = np.zeros((len(EXPERTS), len(ASSETS)), dtype=float)
    combined_online: list[np.ndarray] = []
    combined_equal: list[np.ndarray] = []
    combined_three: list[np.ndarray] = []
    weight_rows: list[dict[str, Any]] = []
    component_rows: list[dict[str, Any]] = []
    prior_date: pd.Timestamp | None = None
    for week_index, decision_date in enumerate(weekly_dates):
        proxy_returns = np.zeros(len(EXPERTS), dtype=float)
        if prior_date is not None:
            interval = returns.loc[(returns.index > prior_date) & (returns.index <= decision_date)]
            realized_vector = interval.sum(min_count=1).reindex(ASSETS).to_numpy(dtype=float)
            realized_vector = np.where(np.isfinite(realized_vector), realized_vector, 0.0)
            for expert_index in range(len(EXPERTS)):
                gross_return = float(prior_normalized[expert_index] @ realized_vector)
                turnover = float(np.abs(prior_normalized[expert_index]).sum())
                proxy_returns[expert_index] = gross_return - (
                    float(learning["update_proxy_one_way_cost_bps"]) / 10_000.0
                ) * turnover
            proxy_returns = np.clip(
                proxy_returns,
                float(learning["update_return_clip"][0]),
                float(learning["update_return_clip"][1]),
            )
            log_wealth = (
                float(learning["log_wealth_decay"]) * log_wealth
                + float(learning["learning_rate"]) * proxy_returns
            )
        weights = _softmax(log_wealth)
        current = np.stack(
            [weekly[name].loc[decision_date].to_numpy(dtype=float) for name in EXPERTS]
        )
        current = np.where(np.isfinite(current), current, 0.0)
        normalized_current = np.divide(
            current,
            np.abs(current).sum(axis=1, keepdims=True),
            out=np.zeros_like(current),
            where=np.abs(current).sum(axis=1, keepdims=True) > 1e-12,
        )
        combined_online.append(weights @ current)
        combined_equal.append(np.mean(current[: len(ACTIVE_EXPERTS)], axis=0))
        combined_three.append(
            np.mean(
                current[
                    [
                        EXPERTS.index("multi_horizon_trend"),
                        EXPERTS.index("curve_carry"),
                        EXPERTS.index("cross_asset_relative_trend"),
                    ]
                ],
                axis=0,
            )
        )
        for expert_index, name in enumerate(EXPERTS):
            weight_rows.append(
                {
                    "decision_date": decision_date,
                    "week_index": week_index,
                    "expert": name,
                    "weight": float(weights[expert_index]),
                    "prior_week_proxy_return": float(proxy_returns[expert_index]),
                    "log_wealth": float(log_wealth[expert_index]),
                }
            )
            for asset_index, asset in enumerate(ASSETS):
                component_rows.append(
                    {
                        "decision_date": decision_date,
                        "expert": name,
                        "asset": asset,
                        "score": float(current[expert_index, asset_index]),
                    }
                )
        prior_normalized = normalized_current
        prior_date = pd.Timestamp(decision_date)

    def score_frame(values: list[np.ndarray], variant: str) -> pd.DataFrame:
        matrix = pd.DataFrame(np.asarray(values), index=weekly_dates, columns=ASSETS)
        frame = matrix.stack(future_stack=True).rename("candidate_score").reset_index()
        frame.columns = ["decision_date", "asset", "candidate_score"]
        frame["variant"] = variant
        return frame

    weights_frame = pd.DataFrame(weight_rows)
    cash = weights_frame.loc[weights_frame["expert"].eq("cash"), ["decision_date", "weight"]]
    cash = cash.rename(columns={"weight": "cash_weight"})
    online = score_frame(combined_online, "online_expert").merge(
        cash, on="decision_date", how="left", validate="many_to_one"
    )
    online["active_fraction"] = 1.0 - online["cash_weight"]
    equal = score_frame(combined_equal, "static_equal_active_experts")
    equal["cash_weight"] = 0.0
    equal["active_fraction"] = 1.0
    three = score_frame(combined_three, "frozen_three_sleeve")
    three["cash_weight"] = 0.0
    three["active_fraction"] = 1.0
    checks = {
        "expert_order_exact": tuple(EXPERTS) == tuple(config["experts"]["ordered"]),
        "weekly_dates_strictly_increasing": weekly_dates.is_unique
        and weekly_dates.is_monotonic_increasing,
        "weights_sum_to_one": bool(
            np.allclose(weights_frame.groupby("decision_date")["weight"].sum(), 1.0)
        ),
        "weights_nonnegative": bool(weights_frame["weight"].ge(0.0).all()),
        "scores_pre2026": bool(weekly_dates.max() < pd.Timestamp("2026-01-01")),
        "online_update_is_prior_only": True,
    }
    return ExpertBuild(
        scores={
            "online_expert": online,
            "static_equal_active_experts": equal,
            "frozen_three_sleeve": three,
        },
        expert_weights=weights_frame,
        expert_components=pd.DataFrame(component_rows),
        checks=checks,
    )


def restore_weekly_weights(
    weekly: pd.DataFrame,
    score_frame: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Restore toward 25% expected volatility, then apply the online cash allocation."""
    risk = weekly.loc[:, ["decision_date", "expected_annual_volatility"]].drop_duplicates()
    target = float(config["portfolio"]["restored_annual_target_volatility"])
    cap = float(config["portfolio"]["maximum_risk_multiplier"])
    expected = pd.to_numeric(risk["expected_annual_volatility"], errors="coerce")
    risk["risk_multiplier"] = np.where(
        expected > 0.0, np.minimum(cap, target / expected), 0.0
    )
    active = score_frame.loc[:, ["decision_date", "active_fraction"]].drop_duplicates()
    risk = risk.merge(active, on="decision_date", how="left", validate="one_to_one")
    risk["active_fraction"] = risk["active_fraction"].fillna(0.0)
    restored = weekly.merge(
        risk.loc[:, ["decision_date", "risk_multiplier", "active_fraction"]],
        on="decision_date",
        how="left",
        validate="many_to_one",
    )
    restored["target_weight"] = (
        restored["target_weight"]
        * restored["risk_multiplier"]
        * restored["active_fraction"]
    )
    gross = restored.groupby("decision_date")["target_weight"].apply(lambda x: x.abs().sum())
    if gross.gt(cap + 1e-12).any():
        raise ValueError("V36 restored weekly gross exceeded cap")
    return restored, risk
