"""Causal builders and evaluator for the sparse Event Alpha V1 challenger."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from market_lab.futures.cftc_radar import (
    CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS,
    CFTC_RELEASE_SCHEDULE_URL,
    nominal_cftc_release_at,
    official_development_release_overrides,
)

EVENT_ALPHA_VERSION: Final = "event-alpha-v1"
PROTECTED_FROM: Final = pd.Timestamp("2026-01-01", tz="UTC")
DEVELOPMENT_FROM: Final = pd.Timestamp("2018-01-01", tz="UTC")
NUMERIC_FEATURES: Final = (
    "innovation_z",
    "innovation_raw",
    "level",
    "prior_innovation_raw",
    "direction",
    "absolute_innovation_z",
    "prior_asset_momentum_20",
    "prior_asset_volatility_20",
)
CATEGORICAL_FEATURES: Final = ("event_family", "asset")
FORBIDDEN_TEXT_FIELDS: Final = frozenset(
    {"price", "prices", "return", "returns", "target", "targets", "label", "labels", "pnl"}
)
ALLOWED_TEXT_FIELDS: Final = frozenset(
    {
        "metric",
        "value",
        "unit",
        "scale",
        "accounting_standard",
        "reporting_scope",
        "page_evidence",
        "text_fact",
    }
)
EVENT_COLUMNS: Final = (
    "event_id",
    "event_family",
    "source",
    "available_at",
    "observation_at",
    "asset",
    "innovation_z",
    "innovation_raw",
    "level",
    "prior_innovation_raw",
    "direction",
    "absolute_innovation_z",
    "release_source",
    "source_revision_id",
    "pit_grade",
)


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    """Holds verified source frames whose bytes match the frozen protocol."""

    cbr: pd.DataFrame
    cftc: pd.DataFrame
    prices: pd.DataFrame
    input_evidence: tuple[dict[str, object], ...]


def sha256_file(path: Path) -> str:
    """Returns a streaming SHA-256 digest without normalizing source bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen_protocol(path: Path) -> tuple[dict[str, Any], str]:
    """Loads a BOM YAML protocol and verifies its adjacent immutable digest."""
    path = Path(path).resolve()
    digest = sha256_file(path)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.exists():
        raise FileNotFoundError(f"Missing protocol digest sidecar: {sidecar}")
    declared = sidecar.read_text(encoding="utf-8-sig").strip().split()[0]
    if declared != digest:
        raise ValueError("Event Alpha protocol digest does not match its sidecar")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not payload.get("sealed_before_return_analysis"):
        raise ValueError("Event Alpha protocol is not frozen before return analysis")
    if payload.get("protected_holdout_start") != date(2026, 1, 1):
        raise ValueError("Protected holdout boundary must remain 2026-01-01")
    return payload, digest


def load_verified_inputs(project_root: Path, protocol: Mapping[str, Any]) -> VerifiedInputs:
    """Verifies every source byte hash before parsing and rejects protected rows."""
    root = Path(project_root).resolve()
    evidence: list[dict[str, object]] = []

    def verified_path(spec: Mapping[str, Any], key: str = "path") -> Path:
        relative = Path(str(spec[key]))
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Input path escapes the project root")
        actual = sha256_file(resolved)
        expected_key = "sha256" if key == "path" else "manifest_sha256"
        expected = str(spec[expected_key])
        if actual != expected:
            raise ValueError(f"Frozen input digest mismatch: {relative.as_posix()}")
        evidence.append(
            {
                "role": key,
                "path": relative.as_posix(),
                "sha256": actual,
                "bytes": resolved.stat().st_size,
            }
        )
        return resolved

    inputs = protocol["inputs"]
    for source in inputs.values():
        verified_path(source, "manifest_path")
    cbr_path = verified_path(inputs["cbr_panel"])
    cftc_path = verified_path(inputs["cftc_panel"])
    prices_path = verified_path(inputs["causal_daily_execution_panel"])
    cbr = pd.read_parquet(cbr_path)
    cftc = pd.read_parquet(cftc_path)
    prices = pd.read_parquet(prices_path)
    _assert_no_protected_rows(cbr, ("observation_date", "effective_date", "available_at"))
    _assert_no_protected_rows(cftc, ("report_date",))
    _assert_no_protected_rows(
        prices,
        ("trade_date", "conservative_open_at", "event_interval_end_at"),
    )
    return VerifiedInputs(cbr=cbr, cftc=cftc, prices=prices, input_evidence=tuple(evidence))


def expanding_prior_z(values: Sequence[float], minimum_history: int) -> np.ndarray:
    """Computes a z-score from earlier finite observations only, with ddof=0."""
    if minimum_history <= 1:
        raise ValueError("minimum_history must exceed one")
    array = np.asarray(values, dtype=np.float64)
    output = np.full(array.shape, np.nan, dtype=np.float64)
    history: list[float] = []
    for index, value in enumerate(array):
        if np.isfinite(value) and len(history) >= minimum_history:
            prior = np.asarray(history, dtype=np.float64)
            scale = float(np.std(prior, ddof=0))
            if scale > 0.0:
                output[index] = (float(value) - float(np.mean(prior))) / scale
        if np.isfinite(value):
            history.append(float(value))
    return output


def build_cbr_events(
    cbr: pd.DataFrame, protocol: Mapping[str, Any], source_sha: str
) -> pd.DataFrame:
    """Builds conservative CBR release events without daily forward filling."""
    required = {"series_id", "observation_date", "available_at", "value"}
    missing = required - set(cbr.columns)
    if missing:
        raise ValueError(f"CBR panel misses columns: {sorted(missing)}")
    frame = cbr.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="raise")
    _assert_no_protected_rows(frame, ("available_at", "observation_date"))
    if frame.duplicated(["series_id", "observation_date"]).any():
        raise ValueError("CBR panel contains duplicate series/observation events")
    families = protocol["event_families"]
    rows: list[dict[str, object]] = []

    def emit(
        group: pd.DataFrame,
        family: str,
        assets: Sequence[str],
        innovation: np.ndarray,
        z_values: np.ndarray,
        mask: np.ndarray,
    ) -> None:
        levels = group["value"].to_numpy(dtype=np.float64)
        for position in np.flatnonzero(mask):
            value = float(innovation[position])
            z_value = float(z_values[position])
            if not (math.isfinite(value) and math.isfinite(z_value)):
                continue
            available_at = pd.Timestamp(group.iloc[position]["available_at"])
            observed_at = pd.Timestamp(group.iloc[position]["observation_date"])
            base_id = _event_id("cbr", family, observed_at.isoformat(), available_at.isoformat())
            prior_value = float(innovation[position - 1]) if position > 0 else float("nan")
            for asset in assets:
                rows.append(
                    _event_mapping(
                        event_id=base_id,
                        family=family,
                        source="cbr",
                        available_at=available_at,
                        observation_at=observed_at,
                        asset=asset,
                        innovation_z=z_value,
                        innovation_raw=value,
                        level=float(levels[position]),
                        prior_innovation_raw=prior_value,
                        release_source=str(
                            group.iloc[position].get("availability_rule", "cbr_conservative_lag")
                        ),
                        source_revision_id=source_sha,
                        pit_grade="conservative_official_current_vintage",
                    )
                )

    key_spec = families["cbr_key_rate_change"]
    key_daily = _series_group(frame, key_spec["series_id"])
    key_values_daily = key_daily["value"].to_numpy(dtype=np.float64)
    level_changed = np.r_[True, np.diff(key_values_daily) != 0.0]
    key = key_daily.loc[level_changed].reset_index(drop=True)
    key_values = key["value"].to_numpy(dtype=np.float64)
    key_delta = np.r_[np.nan, np.diff(key_values)]
    key_z = expanding_prior_z(key_delta, int(key_spec["minimum_prior_releases"]))
    key_mask = np.isfinite(key_delta) & (key_delta != 0.0) & np.isfinite(key_z)
    emit(key, "cbr_key_rate_change", key_spec["assets"], key_delta, key_z, key_mask)

    ruonia_spec = families["cbr_ruonia_tail"]
    ruonia = _series_group(frame, ruonia_spec["series_id"])
    ruonia_values = ruonia["value"].to_numpy(dtype=np.float64)
    ruonia_delta = np.r_[np.nan, np.diff(ruonia_values)]
    ruonia_z = expanding_prior_z(ruonia_delta, int(ruonia_spec["minimum_prior_releases"]))
    ruonia_mask = np.abs(ruonia_z) >= float(ruonia_spec["threshold"])
    emit(ruonia, "cbr_ruonia_tail", ruonia_spec["assets"], ruonia_delta, ruonia_z, ruonia_mask)

    fx_spec = families["cbr_usd_rub_tail"]
    fx = _series_group(frame, fx_spec["series_id"])
    fx_values = fx["value"].to_numpy(dtype=np.float64)
    if (fx_values <= 0.0).any():
        raise ValueError("CBR USD/RUB values must be strictly positive")
    fx_delta = np.r_[np.nan, np.diff(np.log(fx_values))]
    fx_z = expanding_prior_z(fx_delta, int(fx_spec["minimum_prior_releases"]))
    fx_mask = np.abs(fx_z) >= float(fx_spec["threshold"])
    emit(fx, "cbr_usd_rub_tail", fx_spec["assets"], fx_delta, fx_z, fx_mask)
    return _finalize_events(rows)


def build_cftc_events(
    cftc: pd.DataFrame,
    protocol: Mapping[str, Any],
    source_sha: str,
) -> pd.DataFrame:
    """Builds tail events from complete same-report CFTC composites and release times."""
    required = {
        "report_date",
        "market_id",
        "category",
        "net_share_oi",
        "revision_id",
    }
    missing = required - set(cftc.columns)
    if missing:
        raise ValueError(f"CFTC panel misses columns: {sorted(missing)}")
    frame = cftc.copy()
    frame["report_date"] = pd.to_datetime(frame["report_date"], errors="raise")
    _assert_no_protected_rows(frame, ("report_date",))
    if frame.duplicated(["report_date", "market_id", "category"]).any():
        raise ValueError("CFTC panel contains duplicate report/market/category events")
    overrides = official_development_release_overrides()
    families = protocol["event_families"]
    rows: list[dict[str, object]] = []
    for family in ("cftc_energy_tail", "cftc_equity_risk_tail", "cftc_usd_tail"):
        spec = families[family]
        selected = frame[
            frame["market_id"].isin(spec["markets"]) & frame["category"].isin(spec["categories"])
        ].copy()
        expected = len(spec["markets"]) * len(spec["categories"])
        counts = selected.groupby("report_date", sort=True).size()
        selected = selected[selected["report_date"].isin(counts[counts == expected].index)]
        if selected.empty:
            continue
        composite = (
            selected.groupby("report_date", sort=True)
            .agg(
                level=("net_share_oi", "mean"),
                revision_count=("revision_id", "nunique"),
                revision_ids=("revision_id", lambda values: "|".join(sorted(set(values)))),
            )
            .reset_index()
        )
        release_times: list[pd.Timestamp] = []
        for day in composite["report_date"]:
            report_day = day.date()
            if report_day in overrides:
                release_times.append(overrides[report_day])
            else:
                if report_day.weekday() != 1:
                    raise ValueError(
                        "Non-Tuesday CFTC report requires an official release override"
                    )
                release_times.append(nominal_cftc_release_at(report_day))
        composite["available_at"] = release_times
        composite = composite.sort_values(
            ["available_at", "report_date"], kind="stable"
        ).reset_index(drop=True)
        levels = composite["level"].to_numpy(dtype=np.float64)
        innovation = np.r_[np.nan, np.diff(levels)]
        z_values = expanding_prior_z(innovation, int(spec["minimum_prior_releases"]))
        mask = np.abs(z_values) >= float(spec["threshold"])
        for position in np.flatnonzero(mask):
            value = float(innovation[position])
            z_value = float(z_values[position])
            if not (math.isfinite(value) and math.isfinite(z_value)):
                continue
            report_at = pd.Timestamp(composite.iloc[position]["report_date"])
            available_at = pd.Timestamp(composite.iloc[position]["available_at"])
            if available_at >= PROTECTED_FROM:
                continue
            revision_material = str(composite.iloc[position]["revision_ids"])
            revision_id = hashlib.sha256(f"{source_sha}|{revision_material}".encode()).hexdigest()
            source_url = CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS.get(
                report_at.date(),
                CFTC_RELEASE_SCHEDULE_URL,
            )
            rows.append(
                _event_mapping(
                    event_id=_event_id(
                        "cftc",
                        family,
                        report_at.isoformat(),
                        available_at.isoformat(),
                    ),
                    family=family,
                    source="cftc",
                    available_at=available_at,
                    observation_at=report_at,
                    asset=str(spec["asset"]),
                    innovation_z=z_value,
                    innovation_raw=value,
                    level=float(levels[position]),
                    prior_innovation_raw=float(innovation[position - 1]),
                    release_source=source_url,
                    source_revision_id=revision_id,
                    pit_grade="official_schedule_frozen_current_vintage_revision_risk",
                )
            )
    return _finalize_events(rows)


def prepare_price_panel(prices: pd.DataFrame) -> pd.DataFrame:
    """Selects exact active raw opens and rejects duplicates, adjustments and holdout rows."""
    required = {
        "asset_code",
        "contract_id",
        "conservative_open_at",
        "open",
        "is_active_contract",
        "exact_open_available",
    }
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price panel misses columns: {sorted(missing)}")
    frame = prices[prices["is_active_contract"] & prices["exact_open_available"]].copy()
    frame["conservative_open_at"] = pd.to_datetime(
        frame["conservative_open_at"], utc=True, errors="raise"
    )
    frame["open"] = pd.to_numeric(frame["open"], errors="raise")
    _assert_no_protected_rows(frame, ("conservative_open_at",))
    if (frame["open"] <= 0.0).any() or (~np.isfinite(frame["open"])).any():
        raise ValueError("Exact active raw opens must be finite and positive")
    if frame.duplicated(["asset_code", "conservative_open_at"]).any():
        raise ValueError("Price panel contains duplicate active asset/open time")
    return frame.sort_values(["asset_code", "conservative_open_at"], kind="stable").reset_index(
        drop=True
    )


def attach_causal_targets(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Attaches prior-only context and same-contract next-open targets."""
    _validate_unique_events(events)
    panel = prepare_price_panel(prices)
    rows: list[dict[str, object]] = []
    for asset, asset_events in events.groupby("asset", sort=True):
        asset_prices = panel[panel["asset_code"] == asset].reset_index(drop=True)
        if asset_prices.empty:
            continue
        times = pd.DatetimeIndex(asset_prices["conservative_open_at"])
        time_values = times.asi8
        opens = asset_prices["open"].to_numpy(dtype=np.float64)
        contracts = asset_prices["contract_id"].astype(str).to_numpy()
        for event in asset_events.itertuples(index=False):
            available_at = _utc_timestamp(event.available_at)
            prior_end = int(np.searchsorted(time_values, available_at.value, side="left"))
            if prior_end < 21:
                continue
            context_slice = slice(prior_end - 21, prior_end)
            context_contracts = contracts[context_slice]
            if len(set(context_contracts)) != 1:
                continue
            context_opens = opens[context_slice]
            context_returns = np.diff(np.log(context_opens))
            if len(context_returns) != 20 or not np.isfinite(context_returns).all():
                continue
            momentum = float(np.log(context_opens[-1] / context_opens[0]))
            volatility = float(np.std(context_returns, ddof=0) * math.sqrt(252.0))
            entry_index = int(np.searchsorted(time_values, available_at.value, side="right"))
            if entry_index >= len(asset_prices):
                continue
            for horizon in horizons:
                if horizon <= 0:
                    raise ValueError("Target horizon must be positive")
                exit_index = entry_index + int(horizon)
                if exit_index >= len(asset_prices):
                    continue
                if contracts[entry_index] != contracts[exit_index]:
                    continue
                entry_at = times[entry_index]
                exit_at = times[exit_index]
                if not (available_at < entry_at < exit_at < PROTECTED_FROM):
                    raise ValueError("Target timing violates the event/entry/exit causal order")
                row = event._asdict()
                row.update(
                    {
                        "prior_asset_momentum_20": momentum,
                        "prior_asset_volatility_20": volatility,
                        "horizon_sessions": int(horizon),
                        "entry_at": entry_at,
                        "exit_at": exit_at,
                        "contract_id": contracts[entry_index],
                        "entry_open": float(opens[entry_index]),
                        "exit_open": float(opens[exit_index]),
                        "target_log_return": float(np.log(opens[exit_index] / opens[entry_index])),
                        "target_simple_return": float(opens[exit_index] / opens[entry_index] - 1.0),
                    }
                )
                rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result.sort_values(
        ["entry_at", "event_id", "asset", "horizon_sessions"], kind="stable"
    ).reset_index(drop=True)
    if result.duplicated(["event_id", "asset", "horizon_sessions"]).any():
        raise ValueError("Target dataset contains duplicate event/asset/horizon")
    _assert_feature_completeness(result)
    _assert_no_protected_rows(result, ("available_at", "entry_at", "exit_at"))
    return result


def evaluate_expanding_folds(
    dataset: pd.DataFrame,
    protocol: Mapping[str, Any],
) -> pd.DataFrame:
    """Produces deterministic OOS predictions for purged expanding calendar folds."""
    if dataset.empty:
        return pd.DataFrame()
    _assert_feature_completeness(dataset)
    model_spec = protocol["model"]
    validation = protocol["validation"]
    cost = float(protocol["portfolio"]["round_trip_cost_bps"]) / 10_000.0
    output: list[pd.DataFrame] = []
    for _horizon, horizon_frame in dataset.groupby("horizon_sessions", sort=True):
        for year in validation["evaluation_years"]:
            fold_start = pd.Timestamp(f"{int(year)}-01-01", tz="UTC")
            fold_end = min(pd.Timestamp(f"{int(year) + 1}-01-01", tz="UTC"), PROTECTED_FROM)
            train = horizon_frame[horizon_frame["exit_at"] < fold_start].copy()
            test = horizon_frame[
                (horizon_frame["entry_at"] >= fold_start)
                & (horizon_frame["entry_at"] < fold_end)
                & (horizon_frame["exit_at"] < PROTECTED_FROM)
            ].copy()
            if len(train) < int(validation["minimum_train_events"]) or test.empty:
                continue
            estimator = _ridge_pipeline(float(model_spec["alpha"]))
            estimator.fit(
                train.loc[:, [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]], train["target_log_return"]
            )
            train_prediction = estimator.predict(
                train.loc[:, [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]]
            )
            threshold = max(
                float(
                    np.quantile(
                        np.abs(train_prediction),
                        float(model_spec["confidence_quantile"]),
                        method=str(model_spec["confidence_quantile_method"]),
                    )
                ),
                cost * float(model_spec["minimum_edge_multiple_of_round_trip_cost"]),
            )
            prediction = estimator.predict(test.loc[:, [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]])
            fold = test.copy()
            fold["prediction"] = prediction
            fold["absolute_prediction"] = np.abs(prediction)
            fold["confidence_threshold"] = threshold
            fold["selected_by_confidence"] = fold["absolute_prediction"] >= threshold
            fold["direction_prediction"] = np.sign(prediction).astype(np.int8)
            fold["fold_year"] = int(year)
            fold["train_event_count"] = len(train)
            fold["train_last_exit_at"] = train["exit_at"].max()
            fold["model_kind"] = "ridge_regression"
            fold["model_alpha"] = float(model_spec["alpha"])
            fold["round_trip_cost"] = cost
            if not (fold["train_last_exit_at"] < fold_start).all():
                raise ValueError("Purged fold contains a training label crossing test start")
            output.append(fold)
    if not output:
        return pd.DataFrame()
    result = pd.concat(output, ignore_index=True)
    result = result.sort_values(
        ["entry_at", "horizon_sessions", "event_id", "asset"], kind="stable"
    ).reset_index(drop=True)
    if result.duplicated(["event_id", "asset", "horizon_sessions"]).any():
        raise ValueError("An event received more than one OOS prediction")
    return result


def select_nonoverlapping_trades(
    predictions: pd.DataFrame,
    protocol: Mapping[str, Any],
) -> pd.DataFrame:
    """Applies confidence, deterministic tie-breaking, overlap and gross-cap rules."""
    if predictions.empty:
        return predictions.copy()
    allocation = float(protocol["portfolio"]["allocation_per_trade"])
    maximum_gross = float(protocol["portfolio"]["maximum_concurrent_gross"])
    candidates = predictions[predictions["selected_by_confidence"]].copy()
    candidates = candidates.sort_values(
        ["entry_at", "asset", "absolute_prediction", "event_id"],
        ascending=[True, True, False, True],
        kind="stable",
    )
    candidates = candidates.drop_duplicates(["entry_at", "asset"], keep="first")
    last_asset_exit: dict[str, pd.Timestamp] = {}
    active_exits: list[pd.Timestamp] = []
    accepted: list[int] = []
    for index, row in candidates.iterrows():
        entry_at = _utc_timestamp(row["entry_at"])
        exit_at = _utc_timestamp(row["exit_at"])
        active_exits = [value for value in active_exits if value > entry_at]
        asset = str(row["asset"])
        if asset in last_asset_exit and last_asset_exit[asset] > entry_at:
            continue
        if (len(active_exits) + 1) * allocation > maximum_gross + 1e-12:
            continue
        accepted.append(index)
        active_exits.append(exit_at)
        last_asset_exit[asset] = exit_at
    trades = candidates.loc[accepted].copy()
    if trades.empty:
        return trades
    cost = float(protocol["portfolio"]["round_trip_cost_bps"]) / 10_000.0
    trades["gross_trade_return"] = trades["direction_prediction"] * trades["target_simple_return"]
    trades["net_trade_return"] = trades["gross_trade_return"] - cost
    trades["allocated_net_return"] = allocation * trades["net_trade_return"]
    trades["allocated_cost_return"] = allocation * cost
    return trades.sort_values(["exit_at", "event_id", "asset"], kind="stable").reset_index(
        drop=True
    )


def compute_metrics(
    predictions: pd.DataFrame,
    protocol: Mapping[str, Any],
    *,
    sleeve: str,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    """Computes net sparse-event metrics on a daily zero-filled development ledger."""
    evaluation_start = pd.Timestamp(str(protocol["evaluation_start"]), tz="UTC")
    evaluation_end = pd.Timestamp(str(protocol["development_end"]), tz="UTC")
    selected = _sleeve_filter(predictions, sleeve)
    trades = select_nonoverlapping_trades(selected, protocol)
    calendar = pd.date_range(evaluation_start, evaluation_end, freq="B", tz="UTC")
    daily = pd.DataFrame({"date": calendar, "gross_return": 0.0, "cost_return": 0.0})
    if not trades.empty:
        realized = trades.copy()
        realized["date"] = pd.to_datetime(realized["exit_at"], utc=True).dt.normalize()
        grouped = realized.groupby("date", sort=True).agg(
            gross_return=(
                "gross_trade_return",
                lambda values: (
                    float(np.sum(values)) * float(protocol["portfolio"]["allocation_per_trade"])
                ),
            ),
            cost_return=("allocated_cost_return", "sum"),
        )
        daily = daily.set_index("date")
        common = daily.index.intersection(grouped.index)
        daily.loc[common, ["gross_return", "cost_return"]] = grouped.loc[
            common, ["gross_return", "cost_return"]
        ]
        daily = daily.reset_index()
    daily["net_return"] = daily["gross_return"] - daily["cost_return"]
    daily["equity"] = (
        float(protocol["portfolio"]["initial_capital_rub"]) * (1.0 + daily["net_return"]).cumprod()
    )
    daily["peak"] = daily["equity"].cummax()
    daily["drawdown"] = daily["equity"] / daily["peak"] - 1.0
    days = max((evaluation_end - evaluation_start).days, 1)
    terminal_ratio = float(daily["equity"].iloc[-1]) / float(
        protocol["portfolio"]["initial_capital_rub"]
    )
    cagr = terminal_ratio ** (365.25 / days) - 1.0 if terminal_ratio > 0.0 else -1.0
    daily_std = float(daily["net_return"].std(ddof=1))
    sharpe = (
        float(daily["net_return"].mean()) / daily_std * math.sqrt(252.0) if daily_std > 0.0 else 0.0
    )
    yearly = (
        daily.assign(year=daily["date"].dt.year)
        .groupby("year", sort=True)["net_return"]
        .apply(lambda values: float(np.prod(1.0 + values) - 1.0))
    )
    fold_metrics: list[dict[str, object]] = []
    for year in protocol["validation"]["evaluation_years"]:
        year_daily = daily[daily["date"].dt.year == int(year)]
        year_trades = (
            trades[pd.to_datetime(trades.get("exit_at"), utc=True).dt.year == int(year)]
            if not trades.empty
            else trades
        )
        year_std = float(year_daily["net_return"].std(ddof=1))
        fold_metrics.append(
            {
                "year": int(year),
                "eligible_events": int((selected["fold_year"] == int(year)).sum()),
                "trades": len(year_trades),
                "annual_return": float(yearly.get(int(year), 0.0)),
                "sharpe": float(year_daily["net_return"].mean()) / year_std * math.sqrt(252.0)
                if year_std > 0.0
                else 0.0,
                "hit_rate": float((year_trades["net_trade_return"] > 0.0).mean())
                if not year_trades.empty
                else 0.0,
            }
        )
    initial = float(protocol["portfolio"]["initial_capital_rub"])
    costs_rub = float((daily["cost_return"] * daily["equity"].shift(fill_value=initial)).sum())
    metrics: dict[str, object] = {
        "sleeve": sleeve,
        "horizon_sessions": int(selected["horizon_sessions"].iloc[0])
        if not selected.empty
        else None,
        "eligible_event_count": len(selected),
        "selected_confidence_count": int(selected["selected_by_confidence"].sum())
        if not selected.empty
        else 0,
        "trade_count": len(trades),
        "coverage": len(trades) / len(selected) if len(selected) else 0.0,
        "net_costs_rub": costs_rub,
        "terminal_equity_rub": float(daily["equity"].iloc[-1]),
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(daily["drawdown"].min()),
        "hit_rate": float((trades["net_trade_return"] > 0.0).mean()) if not trades.empty else 0.0,
        "worst_year": float(yearly.min()) if not yearly.empty else 0.0,
        "yearly_returns": {str(int(key)): float(value) for key, value in yearly.items()},
        "fold_metrics": fold_metrics,
    }
    return metrics, trades, daily


def validate_text_fact_payload(payload: Mapping[str, Any]) -> None:
    """Rejects market labels and requires page evidence for every Qwen-derived fact."""
    keys = {str(key).lower() for key in payload}
    forbidden = keys & FORBIDDEN_TEXT_FIELDS
    if forbidden:
        raise ValueError(
            f"Text extractor payload contains forbidden market fields: {sorted(forbidden)}"
        )
    unknown = keys - ALLOWED_TEXT_FIELDS
    if unknown:
        raise ValueError(f"Text extractor payload contains undeclared fields: {sorted(unknown)}")
    evidence = payload.get("page_evidence")
    if not isinstance(evidence, str) or not evidence.strip() or "page=" not in evidence.lower():
        raise ValueError("Every extracted corporate fact requires page evidence")
    if "value" in payload:
        value = float(payload["value"])
        if not math.isfinite(value):
            raise ValueError("Extracted numeric fact must be finite")


def _ridge_pipeline(alpha: float) -> Pipeline:
    """Creates the fixed regularized linear model with train-fold-only scaling."""
    transformer = ColumnTransformer(
        [
            ("numeric", StandardScaler(), list(NUMERIC_FEATURES)),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        remainder="drop",
    )
    return Pipeline([("features", transformer), ("ridge", Ridge(alpha=alpha, fit_intercept=True))])


def _series_group(frame: pd.DataFrame, series_id: str) -> pd.DataFrame:
    """Returns one strictly ordered CBR release series without imputing missing days."""
    group = frame[frame["series_id"] == series_id].copy()
    if group.empty:
        raise ValueError(f"Missing CBR series: {series_id}")
    group = group.sort_values(["available_at", "observation_date"], kind="stable").reset_index(
        drop=True
    )
    if group["available_at"].duplicated().any():
        raise ValueError(f"CBR series {series_id} contains duplicate availability timestamps")
    values = pd.to_numeric(group["value"], errors="raise")
    if (~np.isfinite(values)).any():
        raise ValueError(f"CBR series {series_id} contains non-finite values")
    group["value"] = values
    return group


def _event_mapping(
    *,
    event_id: str,
    family: str,
    source: str,
    available_at: pd.Timestamp,
    observation_at: pd.Timestamp,
    asset: str,
    innovation_z: float,
    innovation_raw: float,
    level: float,
    prior_innovation_raw: float,
    release_source: str,
    source_revision_id: str,
    pit_grade: str,
) -> dict[str, object]:
    """Creates one typed event row and no price, return or text-label field."""
    return {
        "event_id": event_id,
        "event_family": family,
        "source": source,
        "available_at": _utc_timestamp(available_at),
        "observation_at": pd.Timestamp(observation_at),
        "asset": asset,
        "innovation_z": innovation_z,
        "innovation_raw": innovation_raw,
        "level": level,
        "prior_innovation_raw": prior_innovation_raw,
        "direction": float(np.sign(innovation_raw)),
        "absolute_innovation_z": abs(innovation_z),
        "release_source": release_source,
        "source_revision_id": source_revision_id,
        "pit_grade": pit_grade,
    }


def _finalize_events(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Sorts event rows and enforces causal timestamps and revision-aware uniqueness."""
    if not rows:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    result = pd.DataFrame(rows).loc[:, EVENT_COLUMNS]
    result["available_at"] = pd.to_datetime(result["available_at"], utc=True, errors="raise")
    _assert_no_protected_rows(result, ("available_at", "observation_at"))
    _validate_unique_events(result)
    return result.sort_values(["available_at", "event_id", "asset"], kind="stable").reset_index(
        drop=True
    )


def _validate_unique_events(events: pd.DataFrame) -> None:
    """Rejects duplicate or revision-conflicting event/asset observations."""
    required = {"event_id", "asset", "source_revision_id", "available_at"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Event dataset misses columns: {sorted(missing)}")
    if events.duplicated(["event_id", "asset"]).any():
        raise ValueError("Duplicate event_id/asset is forbidden")
    revision_key = ["source", "event_family", "observation_at", "asset"]
    if set(revision_key).issubset(events.columns) and events.duplicated(revision_key).any():
        raise ValueError("Revision conflict: one source observation produced multiple events")


def _assert_feature_completeness(frame: pd.DataFrame) -> None:
    """Fails instead of imputing a missing shared feature or target."""
    required = {*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, "target_log_return"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Event target dataset misses columns: {sorted(missing)}")
    numeric = frame.loc[:, [*NUMERIC_FEATURES, "target_log_return"]].to_numpy(dtype=np.float64)
    if not np.isfinite(numeric).all():
        raise ValueError(
            "Event target dataset contains missing/non-finite values; imputation forbidden"
        )


def _assert_no_protected_rows(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    """Physically rejects any development input carrying a 2026 timestamp."""
    for column in columns:
        if column not in frame.columns:
            continue
        values = pd.to_datetime(frame[column], errors="raise", utc=True)
        finite = values[values.notna()]
        if not finite.empty and (finite >= PROTECTED_FROM).any():
            raise ValueError(f"Protected 2026 row found in {column}")


def _sleeve_filter(predictions: pd.DataFrame, sleeve: str) -> pd.DataFrame:
    """Returns the predeclared pooled or source-family diagnostic sleeve."""
    if sleeve == "all_macro":
        return predictions.copy()
    if sleeve == "cbr":
        return predictions[predictions["source"] == "cbr"].copy()
    if sleeve == "cftc":
        return predictions[predictions["source"] == "cftc"].copy()
    if sleeve.startswith("family:"):
        family = sleeve.split(":", 1)[1]
        return predictions[predictions["event_family"] == family].copy()
    raise ValueError(f"Unknown Event Alpha sleeve: {sleeve}")


def _event_id(*parts: str) -> str:
    """Builds a stable content ID without market data or target labels."""
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_timestamp(value: object) -> pd.Timestamp:
    """Normalizes one aware timestamp to UTC and rejects naive values."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError("Event timestamp must be timezone-aware")
    return timestamp.tz_convert("UTC")
