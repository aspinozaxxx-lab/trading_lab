"""Causal continuous-futures features and fixed structural strategy family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_CONTRACT_COLUMNS = frozenset(
    {
        "asset_code",
        "contract_id",
        "secid",
        "trade_date",
        "expiration_date",
        "close",
        "value",
        "volume",
    }
)


def _require_columns(frame: pd.DataFrame, required: frozenset[str], label: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def validate_contract_rows(frame: pd.DataFrame, forbidden_from: pd.Timestamp) -> pd.DataFrame:
    """Normalize official daily rows and fail closed on duplicates or future dates."""
    _require_columns(frame, REQUIRED_CONTRACT_COLUMNS, "contract rows")
    output = frame.copy()
    for column in ("trade_date", "expiration_date"):
        output[column] = pd.to_datetime(output[column], errors="raise").dt.normalize()
    if output["trade_date"].isna().any() or output["expiration_date"].isna().any():
        raise ValueError("missing contract date")
    if (output["trade_date"] >= forbidden_from).any():
        raise ValueError("protected 2026+ row in contract history")
    for column in ("close", "value", "volume"):
        output[column] = pd.to_numeric(output[column], errors="coerce")
    if (output["close"].dropna() <= 0.0).any():
        raise ValueError("non-positive futures close is unsupported by this proxy")
    key = ["asset_code", "contract_id", "trade_date"]
    duplicates = output.duplicated(key, keep=False)
    if duplicates.any():
        grouped = output.loc[duplicates].groupby(key, observed=True)
        for _, rows in grouped:
            closes = rows["close"].dropna().to_numpy(dtype=float)
            if closes.size > 1 and not np.allclose(closes, closes[0], rtol=1e-10, atol=1e-10):
                raise ValueError("conflicting aliases for the same canonical contract")
        output = output.sort_values(
            key + ["value", "volume", "secid"],
            ascending=[True, True, True, False, False, True],
            na_position="last",
        ).drop_duplicates(key, keep="first")
    return output.sort_values(key, ignore_index=True)


def _active_contract_for_day(rows: pd.DataFrame, roll_buffer_days: int) -> pd.Series | None:
    date = pd.Timestamp(rows.name)
    eligible = rows.loc[
        (rows["expiration_date"] >= date + pd.Timedelta(days=roll_buffer_days))
        & rows["close"].notna()
    ].copy()
    if eligible.empty:
        return None
    eligible["value_rank"] = eligible["value"].fillna(0.0)
    eligible["volume_rank"] = eligible["volume"].fillna(0.0)
    return eligible.sort_values(
        ["value_rank", "volume_rank", "expiration_date", "contract_id"],
        ascending=[False, False, True, True],
    ).iloc[0]


def _curve_for_day(rows: pd.DataFrame, minimum_gap_days: int, maximum_abs: float) -> float:
    date = pd.Timestamp(rows.name)
    eligible = rows.loc[
        (rows["expiration_date"] > date) & rows["close"].notna() & rows["value"].fillna(0.0).gt(0.0)
    ].copy()
    if len(eligible) < 2:
        return np.nan
    liquid = eligible.sort_values(
        ["value", "volume", "expiration_date", "contract_id"],
        ascending=[False, False, True, True],
    ).head(2)
    liquid = liquid.sort_values(["expiration_date", "contract_id"])
    front, next_contract = liquid.iloc[0], liquid.iloc[1]
    gap = int((next_contract["expiration_date"] - front["expiration_date"]).days)
    if gap < minimum_gap_days:
        return np.nan
    annualized = float(np.log(front["close"] / next_contract["close"]) * 365.0 / gap)
    if not np.isfinite(annualized) or abs(annualized) > maximum_abs:
        return np.nan
    return annualized


def build_continuous_asset(
    rows: pd.DataFrame,
    *,
    roll_buffer_days: int,
    carry_minimum_gap_days: int,
    carry_maximum_abs: float,
) -> pd.DataFrame:
    """Build a return chain selected only with information known at the prior close."""
    assets = rows["asset_code"].dropna().unique()
    if len(assets) != 1:
        raise ValueError("build_continuous_asset expects exactly one asset")
    asset_code = str(assets[0])
    rows = rows.sort_values(["trade_date", "contract_id"]).copy()
    active_candidates = rows.loc[
        rows["expiration_date"].ge(rows["trade_date"] + pd.to_timedelta(roll_buffer_days, unit="D"))
        & rows["close"].notna()
    ].copy()
    active_candidates["value_rank"] = active_candidates["value"].fillna(0.0)
    active_candidates["volume_rank"] = active_candidates["volume"].fillna(0.0)
    active = active_candidates.sort_values(
        [
            "trade_date",
            "value_rank",
            "volume_rank",
            "expiration_date",
            "contract_id",
        ],
        ascending=[True, False, False, True, True],
    ).drop_duplicates("trade_date", keep="first")
    if active.empty:
        return pd.DataFrame()
    selected = (
        active.rename(
            columns={
                "contract_id": "active_contract",
                "expiration_date": "active_expiration",
                "close": "active_close",
                "value": "active_value",
                "volume": "active_volume",
            }
        )[
            [
                "trade_date",
                "active_contract",
                "active_expiration",
                "active_close",
                "active_value",
                "active_volume",
            ]
        ]
        .set_index("trade_date")
        .sort_index()
    )
    curve_candidates = rows.loc[
        rows["expiration_date"].gt(rows["trade_date"])
        & rows["close"].notna()
        & rows["value"].fillna(0.0).gt(0.0)
    ].copy()
    top_two = (
        curve_candidates.sort_values(
            ["trade_date", "value", "volume", "expiration_date", "contract_id"],
            ascending=[True, False, False, True, True],
        )
        .groupby("trade_date", sort=False)
        .head(2)
        .sort_values(["trade_date", "expiration_date", "contract_id"])
    )
    top_two["leg"] = top_two.groupby("trade_date", sort=False).cumcount()
    curve_wide = top_two.pivot(
        index="trade_date", columns="leg", values=["close", "expiration_date"]
    )
    if ("close", 1) in curve_wide and ("expiration_date", 1) in curve_wide:
        gap = (
            pd.to_datetime(curve_wide[("expiration_date", 1)])
            - pd.to_datetime(curve_wide[("expiration_date", 0)])
        ).dt.days
        front_close = pd.to_numeric(curve_wide[("close", 0)], errors="coerce")
        next_close = pd.to_numeric(curve_wide[("close", 1)], errors="coerce")
        annualized_carry = np.log(front_close / next_close) * 365.0 / gap
        annualized_carry = annualized_carry.where(gap.ge(carry_minimum_gap_days))
        annualized_carry = annualized_carry.where(annualized_carry.abs().le(carry_maximum_abs))
    else:
        annualized_carry = pd.Series(dtype=float)
    closes = rows.pivot(index="trade_date", columns="contract_id", values="close").sort_index()
    contract_returns = closes.ffill().pct_change(fill_method=None)
    held_contract = selected["active_contract"].shift(1)
    return_lookup = contract_returns.stack(future_stack=True)
    return_keys = pd.MultiIndex.from_arrays(
        [selected.index, held_contract], names=["trade_date", "contract_id"]
    )
    selected["asset_return"] = return_lookup.reindex(return_keys).to_numpy(dtype=float)
    selected["curve_carry"] = annualized_carry.reindex(selected.index)
    selected["roll_flag"] = selected["active_contract"].ne(selected["active_contract"].shift(1))
    selected.iloc[0, selected.columns.get_loc("roll_flag")] = False
    selected["asset_code"] = asset_code
    selected["log_return"] = np.log1p(selected["asset_return"])
    return selected.reset_index()


def _rolling_log_momentum(log_return: pd.Series, horizon: int) -> pd.Series:
    return log_return.rolling(horizon, min_periods=horizon).sum()


def build_asset_panel(contract_rows: pd.DataFrame, config: Mapping[str, Any]) -> pd.DataFrame:
    """Build all causal signals using a fixed formula shared by every asset."""
    forbidden = pd.Timestamp(config["dates"]["forbidden_from"])
    rows = validate_contract_rows(contract_rows, forbidden)
    eligibility = config["eligibility"]
    signals = config["signals"]
    frames = []
    for _, asset_rows in rows.groupby("asset_code", sort=True):
        built = build_continuous_asset(
            asset_rows,
            roll_buffer_days=int(eligibility["roll_buffer_calendar_days"]),
            carry_minimum_gap_days=int(signals["carry_minimum_tenor_gap_days"]),
            carry_maximum_abs=float(signals["carry_maximum_absolute_annualized"]),
        )
        if not built.empty:
            frames.append(built)
    if not frames:
        raise ValueError("no continuous assets could be built")
    panel = pd.concat(frames, ignore_index=True).sort_values(
        ["asset_code", "trade_date"], ignore_index=True
    )
    lookback = int(signals["volatility_lookback_sessions"])
    annualization = float(config["portfolio"]["annualization_sessions"])
    grouped = panel.groupby("asset_code", sort=False, group_keys=False)
    panel["volatility"] = grouped["asset_return"].transform(
        lambda x: x.rolling(lookback, min_periods=lookback).std(ddof=1) * np.sqrt(annualization)
    )
    panel["trailing_median_value"] = grouped["active_value"].transform(
        lambda x: x.rolling(
            int(eligibility["trailing_liquidity_days"]),
            min_periods=int(eligibility["trailing_liquidity_days"]),
        ).median()
    )
    panel["return_observations"] = grouped["asset_return"].transform(lambda x: x.notna().cumsum())
    panel["eligible"] = (
        panel["return_observations"].ge(int(eligibility["minimum_return_observations"]))
        & panel["trailing_median_value"].ge(float(eligibility["minimum_trailing_median_value_rub"]))
        & panel["volatility"].notna()
    )
    horizons = [int(value) for value in signals["momentum_horizons_sessions"]]
    momentum_columns = []
    for horizon in horizons:
        column = f"momentum_{horizon}"
        panel[column] = grouped["log_return"].transform(
            lambda x, h=horizon: _rolling_log_momentum(x, h)
        )
        momentum_columns.append(column)
    sign_columns = []
    for horizon, column in zip(horizons, momentum_columns, strict=True):
        sign_column = f"signal_tsmom_{horizon}"
        panel[sign_column] = np.sign(panel[column]).where(panel[column].notna())
        sign_columns.append(sign_column)
    panel["signal_tsmom_multi"] = panel[sign_columns].mean(axis=1, skipna=False)
    vol_floor = float(signals["volatility_floor_annualized"])
    daily_vol = panel["volatility"].clip(lower=vol_floor) / np.sqrt(annualization)
    risk_adjusted = []
    for horizon, column in zip(horizons, momentum_columns, strict=True):
        scaled = panel[column] / (daily_vol * np.sqrt(float(horizon)))
        risk_adjusted.append(scaled.clip(-2.0, 2.0) / 2.0)
    panel["signal_risk_adjusted_momentum"] = pd.concat(risk_adjusted, axis=1).mean(
        axis=1, skipna=False
    )
    panel["signal_curve_carry"] = np.sign(panel["curve_carry"]).where(panel["curve_carry"].notna())
    agreement = np.sign(panel["signal_tsmom_multi"]) == panel["signal_curve_carry"]
    panel["signal_carry_momentum_confirmation"] = panel["signal_curve_carry"].where(agreement, 0.0)
    return panel


def build_synchronized_panel(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Export one point-in-time row per date with explicit asset availability masks."""
    required = frozenset(
        {
            "trade_date",
            "asset_code",
            "active_contract",
            "asset_return",
            "volatility",
            "curve_carry",
            "eligible",
        }
    )
    _require_columns(panel, required, "asset panel")
    if panel.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("duplicate date/asset in synchronized panel input")
    features = [
        "asset_return",
        "volatility",
        "curve_carry",
        "signal_tsmom_21",
        "signal_tsmom_63",
        "signal_tsmom_126",
        "signal_tsmom_252",
        "signal_tsmom_multi",
        "signal_risk_adjusted_momentum",
        "signal_curve_carry",
        "signal_carry_momentum_confirmation",
    ]
    assets = sorted(panel["asset_code"].astype(str).unique())
    dates = pd.DatetimeIndex(sorted(panel["trade_date"].unique()), name="trade_date")
    output_columns: dict[str, pd.Series] = {}
    for asset in assets:
        rows = panel.loc[panel["asset_code"].astype(str).eq(asset)].set_index("trade_date")
        output_columns[f"{asset}__observed"] = (
            rows["active_contract"].notna().reindex(dates, fill_value=False).astype(bool)
        )
        output_columns[f"{asset}__return_available"] = (
            rows["asset_return"].notna().reindex(dates, fill_value=False).astype(bool)
        )
        output_columns[f"{asset}__eligible"] = (
            rows["eligible"].astype(bool).reindex(dates, fill_value=False)
        )
        output_columns[f"{asset}__active_contract"] = rows["active_contract"].reindex(dates)
        for feature in features:
            output_columns[f"{asset}__{feature}"] = rows[feature].reindex(dates)
    synchronized = pd.DataFrame(output_columns, index=dates)
    synchronized.insert(0, "asof_date", dates)
    schema = {
        "api": "build_synchronized_panel(panel) -> (frame, schema)",
        "row_key": "trade_date",
        "asof_semantics": "official_daily_close_proxy_known_after_the_same_trade_date_close",
        "asset_order": assets,
        "column_pattern": "{asset_code}__{field}",
        "mask_fields": {
            "observed": "an active pre-expiry contract was selected at this close",
            "return_available": "same-asset held-contract return is observed for this date",
            "eligible": "252 observations, 60-session volatility and trailing liquidity pass",
        },
        "numeric_feature_fields": features,
        "string_fields": ["active_contract"],
        "target_columns": [],
        "point_in_time_universe": True,
    }
    return synchronized.reset_index(), schema


def _strategy_signal_columns(config: Mapping[str, Any]) -> dict[str, str]:
    horizons = [int(value) for value in config["signals"]["momentum_horizons_sessions"]]
    mapping = {
        f"tsmom_{label}": f"signal_tsmom_{horizon}"
        for label, horizon in zip(("1m", "3m", "6m", "12m"), horizons, strict=True)
    }
    mapping.update(
        {
            "tsmom_multi": "signal_tsmom_multi",
            "risk_adjusted_momentum": "signal_risk_adjusted_momentum",
            "curve_carry": "signal_curve_carry",
            "carry_momentum_confirmation": "signal_carry_momentum_confirmation",
        }
    )
    declared = [str(item["id"]) for item in config["strategy_family"]]
    if declared != list(mapping):
        raise ValueError("strategy implementation does not match predeclared ordered family")
    return mapping


def _daily_target_weights(
    day: pd.DataFrame,
    signal_column: str,
    config: Mapping[str, Any],
) -> pd.Series:
    valid = day["eligible"] & day[signal_column].notna() & day["volatility"].gt(0.0)
    output = pd.Series(0.0, index=day["asset_code"].astype(str), dtype=float)
    if int(valid.sum()) < int(config["eligibility"]["minimum_daily_assets"]):
        return output
    selected = day.loc[valid]
    raw = selected[signal_column].astype(float) / selected["volatility"].astype(float)
    gross = float(raw.abs().sum())
    if gross <= 0.0:
        return output
    raw /= gross
    cap = float(config["portfolio"]["single_asset_cap"])
    raw = raw.clip(-cap, cap)
    estimated_vol = float(
        np.sqrt(np.square(raw.to_numpy() * selected["volatility"].to_numpy()).sum())
    )
    target_vol = float(config["portfolio"]["volatility_target_annualized"])
    if estimated_vol > target_vol:
        raw *= target_vol / estimated_vol
    gross_cap = float(config["portfolio"]["gross_cap"])
    final_gross = float(raw.abs().sum())
    if final_gross > gross_cap:
        raw *= gross_cap / final_gross
    output.loc[selected["asset_code"].astype(str)] = raw.to_numpy()
    return output


def _metrics(returns: pd.Series) -> dict[str, Any]:
    values = returns.dropna().astype(float)
    if values.empty:
        return {"observations": 0}
    equity = (1.0 + values).cumprod()
    elapsed_days = max((values.index[-1] - values.index[0]).days, 1)
    cagr = float(equity.iloc[-1] ** (365.25 / elapsed_days) - 1.0)
    volatility = float(values.std(ddof=1) * np.sqrt(252.0))
    sharpe = (
        float(values.mean() / values.std(ddof=1) * np.sqrt(252.0))
        if values.std(ddof=1) > 0
        else np.nan
    )
    drawdown = equity / equity.cummax() - 1.0
    annual_returns = {
        str(int(year)): float((1.0 + group).prod() - 1.0)
        for year, group in values.groupby(values.index.year)
    }
    return {
        "observations": int(len(values)),
        "total_return": float(equity.iloc[-1] - 1.0),
        "cagr": cagr,
        "sharpe": sharpe,
        "annualized_volatility": volatility,
        "max_drawdown": float(drawdown.min()),
        "year_returns": annual_returns,
        "positive_years": int(sum(value > 0.0 for value in annual_returns.values())),
        "worst_year": float(min(annual_returns.values())),
    }


def backtest_strategy(
    panel: pd.DataFrame,
    signal_column: str,
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run weekly close decisions with next-session returns and explicit roll costs."""
    observed_counts = panel.groupby("trade_date")["asset_code"].nunique()
    minimum_assets = int(config["eligibility"]["minimum_daily_assets"])
    dates = pd.DatetimeIndex(sorted(observed_counts.loc[observed_counts.ge(minimum_assets)].index))
    assets = sorted(panel["asset_code"].astype(str).unique())
    target = pd.DataFrame(0.0, index=dates, columns=assets)
    for trade_date, day in panel.groupby("trade_date", sort=True):
        day_target = _daily_target_weights(day, signal_column, config)
        target.loc[pd.Timestamp(trade_date)] = day_target.reindex(assets, fill_value=0.0).to_numpy()
    week = target.index.to_period("W-SUN")
    rebalance_dates = pd.Series(target.index, index=target.index).groupby(week).max().to_numpy()
    desired = target.copy()
    desired.loc[~desired.index.isin(rebalance_dates), :] = np.nan
    desired = desired.ffill().fillna(0.0)
    held = desired.shift(1).fillna(0.0)
    returns = panel.pivot(index="trade_date", columns="asset_code", values="asset_return").reindex(
        index=dates, columns=assets
    )
    observed = (
        panel.assign(observed=True)
        .pivot(index="trade_date", columns="asset_code", values="observed")
        .reindex(index=dates, columns=assets, fill_value=False)
        .eq(True)
    )
    roll = (
        panel.pivot(index="trade_date", columns="asset_code", values="roll_flag")
        .reindex(index=dates, columns=assets)
        .eq(True)
    )
    exposed_missing = (held.abs() * returns.isna() * observed.astype(float)).sum(axis=1)
    gross_return = (held * returns.fillna(0.0)).sum(axis=1)
    regular_turnover_at_close = desired.diff().abs().sum(axis=1).fillna(desired.abs().sum(axis=1))
    roll_turnover_at_close = (2.0 * desired.abs() * roll.astype(float)).sum(axis=1)
    turnover = (regular_turnover_at_close + roll_turnover_at_close).shift(1).fillna(0.0)
    primary_bps = float(config["costs"]["primary_one_way_bps"])
    primary_cost = turnover * primary_bps / 10_000.0
    stressed_cost = primary_cost * float(config["costs"]["stressed_multiplier"])
    ledger = pd.DataFrame(
        {
            "gross_return": gross_return,
            "turnover": turnover,
            "primary_cost": primary_cost,
            "primary_net_return": gross_return - primary_cost,
            "stressed_net_return": gross_return - stressed_cost,
            "gross_exposure": held.abs().sum(axis=1),
            "net_exposure": held.sum(axis=1),
            "positions": held.ne(0.0).sum(axis=1),
            "missing_exposure": exposed_missing,
        },
        index=dates,
    )
    start = pd.Timestamp(config["dates"]["development_start"])
    end = pd.Timestamp(config["dates"]["development_end"])
    ledger = ledger.loc[(ledger.index >= start) & (ledger.index <= end)].copy()
    metrics = {
        "gross": _metrics(ledger["gross_return"]),
        "primary": _metrics(ledger["primary_net_return"]),
        "stressed": _metrics(ledger["stressed_net_return"]),
        "average_turnover": float(ledger["turnover"].mean()),
        "annualized_turnover": float(ledger["turnover"].mean() * 252.0),
        "average_gross": float(ledger["gross_exposure"].mean()),
        "average_positions": float(ledger["positions"].mean()),
        "maximum_gross": float(ledger["gross_exposure"].max()),
        "missing_exposure_sessions": int(ledger["missing_exposure"].gt(0.0).sum()),
        "maximum_missing_exposure": float(ledger["missing_exposure"].max()),
    }
    return ledger, metrics


def evaluate_strategy_family(
    panel: pd.DataFrame,
    config: Mapping[str, Any],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Evaluate exactly the predeclared family and return all metrics without selection."""
    ledgers: dict[str, pd.DataFrame] = {}
    metrics: dict[str, Any] = {}
    for strategy_id, signal_column in _strategy_signal_columns(config).items():
        ledger, strategy_metrics = backtest_strategy(panel, signal_column, config)
        ledgers[strategy_id] = ledger
        metrics[strategy_id] = strategy_metrics
    primary_returns = pd.DataFrame(
        {key: value["primary_net_return"] for key, value in ledgers.items()}
    )
    correlations = primary_returns.corr().round(6).to_dict()
    development_panel = panel.loc[
        panel["trade_date"].between(
            pd.Timestamp(config["dates"]["development_start"]),
            pd.Timestamp(config["dates"]["development_end"]),
        )
    ]
    observed_counts = development_panel.groupby("trade_date")["asset_code"].nunique()
    market_dates = observed_counts.loc[
        observed_counts.ge(int(config["eligibility"]["minimum_daily_assets"]))
    ].index
    breadth = (
        development_panel.loc[development_panel["trade_date"].isin(market_dates)]
        .groupby("trade_date")["eligible"]
        .sum()
    )
    summary = {
        "strategies": metrics,
        "strategy_primary_return_correlations": correlations,
        "breadth": {
            "candidate_assets": int(panel["asset_code"].nunique()),
            "average_eligible_assets": float(breadth.mean()),
            "minimum_eligible_assets": int(breadth.min()),
            "maximum_eligible_assets": int(breadth.max()),
            "sessions": int(len(breadth)),
        },
    }
    return ledgers, summary


def truncate_contract_rows(frame: pd.DataFrame, end_date: pd.Timestamp) -> pd.DataFrame:
    """Explicit causal boundary used by production and future-mutation tests."""
    dates = pd.to_datetime(frame["trade_date"], errors="raise")
    return frame.loc[dates <= end_date].copy()
