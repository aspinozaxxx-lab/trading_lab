"""Fixed paired training core; explicit feature/label tables, no IO or trading ledger."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from market_lab.futures.algopack_paper_alignment_v1 import (
    ASSETS,
    MOSCOW,
    TEN,
    OpenObservation,
    mature_label,
    select_training_flow,
    utc,
)

PRICE_NAMES = ("return_1", "return_3", "return_6", "body", "range")
FLOW_NAMES = ("trade_imbalance", "volume_imbalance", "depth_l1", "depth_l10", "pressure")
PRICE_COLUMNS = tuple(f"{asset}_{name}" for asset in ASSETS for name in PRICE_NAMES)
FLOW_COLUMNS = tuple(f"{asset}_{name}" for asset in ASSETS for name in FLOW_NAMES)
TARGET_COLUMNS = tuple(f"{asset}_target" for asset in ASSETS)
MINIMUM_ROWS = 5000


@dataclass(frozen=True)
class PriceBar:
    asset: str
    secid: str
    contract_id: str
    begin: datetime
    end: datetime
    available_at: datetime
    source_sha256: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None

    def __post_init__(self) -> None:
        if self.asset not in ASSETS or not self.secid or not self.contract_id:
            raise ValueError("invalid price identity")
        begin, end, available = utc(self.begin), utc(self.end), utc(self.available_at)
        if begin.minute % 10 or begin.second or begin.microsecond:
            raise ValueError("non-grid price begin")
        if end < begin or end > begin + TEN or available < begin:
            raise ValueError("invalid price clock")
        if re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None:
            raise ValueError("invalid price provenance")


def training_boundary(end: datetime, decision: datetime) -> datetime:
    end, decision = utc(end), utc(decision)
    local = end.astimezone(MOSCOW)
    if (
        not 2020 <= end.year <= 2025
        or not 2020 <= local.year <= 2025
        or end.minute % 10
        or end.second
        or end.microsecond
        or decision != end + timedelta(minutes=4)
        or local.weekday() >= 5
        or not (10, 10) <= (local.hour, local.minute) <= (17, 0)
    ):
        raise ValueError("invalid/protected training calendar")
    return end


def calendar(plan: pd.DataFrame) -> pd.DataFrame:
    """Calendar depends solely on admitted plan metadata, never price or target coverage."""
    if plan.duplicated(["effective_date", "asset"]).any():
        raise ValueError("duplicate plan identity")
    indexed = plan.set_index(["effective_date", "asset"])
    rows = []
    for day in sorted(plan["effective_date"].unique()):
        day = pd.Timestamp(day)
        if not pd.Timestamp("2020-01-01") <= day < pd.Timestamp("2026-01-01"):
            continue
        if day.weekday() >= 5:
            continue
        for stamp in pd.date_range(
            day + pd.Timedelta(hours=10, minutes=10),
            day + pd.Timedelta(hours=17),
            freq="10min",
            tz=MOSCOW,
        ):
            end = stamp.tz_convert("UTC")
            item = dict(
                information_end=end,
                decision_at=end + pd.Timedelta(minutes=4),
                local_date=day.date().isoformat(),
            )
            for asset in ASSETS:
                key = day, asset
                row = indexed.loc[key] if key in indexed.index else None
                eligible = row is not None and bool(row["plan_eligible"])
                item[f"{asset}_plan_eligible"] = eligible
                item[f"{asset}_secid"] = None if row is None else row["secid"]
                item[f"{asset}_contract_id"] = None if row is None else row["contract_id"]
            rows.append(item)
    if not rows:
        raise ValueError("empty permitted candidate calendar")
    return pd.DataFrame(rows).set_index("information_end", verify_integrity=True)


def price_index(bars: list[PriceBar]) -> dict:
    result = {}
    for bar in bars:
        key = bar.asset, bar.contract_id, utc(bar.begin)
        if key in result:
            raise ValueError("duplicate price bar key")
        result[key] = bar
    return result


def price_state(
    index: dict,
    *,
    asset: str,
    contract: str,
    secid: str,
    information_end: datetime,
    available_cutoff: datetime,
) -> tuple:
    """Seven exact past bars only; caller chooses a training or actual inference cutoff."""
    end, cutoff = utc(information_end), utc(available_cutoff)
    if end > cutoff or end.minute % 10 or end.second or end.microsecond:
        raise ValueError("invalid information boundary")
    bars = []
    for offset in range(7, 0, -1):
        begin = end - offset * TEN
        bar = index.get((asset, contract, begin))
        if bar is None:
            return "MISSING_PRICE_LOOKBACK", None, ()
        if (
            bar.secid != secid
            or utc(bar.available_at) > cutoff
            or utc(bar.end) < begin
            or utc(bar.end) > begin + TEN
            or utc(bar.available_at) < begin + TEN
            or begin.astimezone(MOSCOW).date() != end.astimezone(MOSCOW).date()
        ):
            return "UNAVAILABLE_PRICE_LOOKBACK", None, ()
        values = (bar.open, bar.high, bar.low, bar.close)
        if any(v is None or isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in values):
            return "INVALID_OHLC", None, ()
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            return "INVALID_OHLC", None, ()
        bars.append(bar)
    close = math.log(bars[-1].close)
    features = tuple(close - math.log(bars[-1 - lag].close) for lag in (1, 3, 6))
    features += (close - math.log(bars[-1].open), math.log(bars[-1].high) - math.log(bars[-1].low))
    sources = tuple(sorted({bar.source_sha256 for bar in bars}))
    return "READY", features, sources


def build_features(
    candidates: pd.DataFrame, prices: dict, flow: dict, training_cutoff: datetime
) -> pd.DataFrame:
    """No target input. Full candidate index is retained, including sleep rows."""
    cutoff = utc(training_cutoff)
    records = []
    for end, row in candidates.iterrows():
        end = training_boundary(end.to_pydatetime(), row["decision_at"].to_pydatetime())
        output = {}
        for asset in ASSETS:
            plan_ok = bool(row[f"{asset}_plan_eligible"])
            secid, contract = row[f"{asset}_secid"], row[f"{asset}_contract_id"]
            status, values, sources = ("PLAN_INELIGIBLE", None, ())
            if plan_ok:
                status, values, sources = price_state(
                    prices,
                    asset=asset,
                    contract=contract,
                    secid=secid,
                    information_end=end,
                    available_cutoff=cutoff,
                )
            output[f"{asset}_price_status"] = status
            output[f"{asset}_price_sources"] = json.dumps(sources)
            for name, value in zip(PRICE_NAMES, values or (np.nan,) * 5, strict=True):
                output[f"{asset}_{name}"] = value
            flow_values, ids, flow_status = None, (), "PLAN_INELIGIBLE"
            if plan_ok:
                pair = []
                for dataset in ("tradestats", "obstats"):
                    for target_end in (end - timedelta(minutes=5), end):
                        version = flow.get((dataset, asset, secid, target_end))
                        if version is not None:
                            pair.append(version)
                selection = select_training_flow(
                    tuple(pair),
                    asset=asset,
                    secid=secid,
                    information_end=end,
                    training_cutoff=cutoff,
                )
                flow_values, ids, flow_status = (
                    selection.features,
                    selection.version_ids,
                    selection.status,
                )
            output[f"{asset}_flow_status"] = flow_status
            output[f"{asset}_flow_versions"] = json.dumps(ids)
            for name, value in zip(FLOW_NAMES, flow_values or (np.nan,) * 5, strict=True):
                output[f"{asset}_{name}"] = value
        records.append(output)
    return pd.DataFrame(records, index=candidates.index)


def build_labels(candidates: pd.DataFrame, prices: dict, training_cutoff: datetime) -> pd.DataFrame:
    """Label construction is independent of features; target path cannot prune calendar."""
    records = []
    for end, row in candidates.iterrows():
        output = {}
        decision = row["decision_at"].to_pydatetime()
        end = training_boundary(end.to_pydatetime(), decision)
        for asset in ASSETS:
            target, status = np.nan, "PLAN_INELIGIBLE"
            sources = set()
            if row[f"{asset}_plan_eligible"]:
                secid, contract = row[f"{asset}_secid"], row[f"{asset}_contract_id"]
                observations = []
                for offset in range(1, 8):
                    begin = end + offset * TEN
                    bar = prices.get((asset, contract, begin))
                    if bar is not None:
                        if (
                            utc(bar.begin) >= datetime(2026, 1, 1, tzinfo=utc(bar.begin).tzinfo)
                            or utc(bar.end).astimezone(MOSCOW).year >= 2026
                        ):
                            raise ValueError("protected training label")
                        observations.append(
                            OpenObservation(asset, bar.secid, bar.begin, bar.available_at, bar.open)
                        )
                        sources.add(bar.source_sha256)
                label = mature_label(
                    tuple(observations),
                    asset=asset,
                    secid=secid,
                    decision_at=decision,
                    evaluated_at=training_cutoff,
                )
                status = label.status
                if label.log_return is not None:
                    target = label.log_return
            output[f"{asset}_target"] = target
            output[f"{asset}_label_status"] = status
            output[f"{asset}_label_sources"] = json.dumps(sorted(sources))
        records.append(output)
    return pd.DataFrame(records, index=candidates.index)


def fit_pair(features: pd.DataFrame, labels: pd.DataFrame) -> tuple[dict, pd.Series]:
    if not features.index.equals(labels.index) or not features.index.is_unique:
        raise ValueError("feature/label calendar identity mismatch")
    full_columns = (*PRICE_COLUMNS, *FLOW_COLUMNS)
    if not features.columns.is_unique or not labels.columns.is_unique:
        raise ValueError("duplicate model columns")
    x = features.loc[:, list(full_columns)].to_numpy(dtype=float)
    y = labels.loc[:, list(TARGET_COLUMNS)].to_numpy(dtype=float)
    mask = np.isfinite(x).all(axis=1) & np.isfinite(y).all(axis=1)
    valid = pd.Series(mask, index=features.index, name="training_eligible")
    if int(mask.sum()) < MINIMUM_ROWS:
        raise ValueError("FAILED_TRAINING_COVERAGE: fewer than 5000 joint rows")
    models = {}
    for arm, columns in (("price_only", PRICE_COLUMNS), ("price_flow", full_columns)):
        selected = features.loc[valid, list(columns)].to_numpy(dtype=float)
        scaler = StandardScaler(with_mean=True, with_std=True)
        transformed = scaler.fit_transform(selected)
        model = Ridge(alpha=10.0, fit_intercept=True, solver="svd")
        model.fit(transformed, y[mask])
        models[arm] = dict(
            feature_names=list(columns),
            target_names=list(TARGET_COLUMNS),
            mean=scaler.mean_.tolist(),
            scale=scaler.scale_.tolist(),
            coefficients=model.coef_.tolist(),
            intercept=model.intercept_.tolist(),
            training_rows=int(mask.sum()),
            alpha=10.0,
            solver="svd",
        )
    return models, valid


def predict_serialized(model: dict, features: np.ndarray) -> np.ndarray:
    """Inference needs only the frozen model and feature matrix, never future targets."""
    values = np.asarray(features, dtype=float)
    names = model["feature_names"]
    if names not in (list(PRICE_COLUMNS), list((*PRICE_COLUMNS, *FLOW_COLUMNS))):
        raise ValueError("invalid frozen feature schema")
    if model["target_names"] != list(TARGET_COLUMNS):
        raise ValueError("invalid frozen target schema")
    mean, scale = np.asarray(model["mean"]), np.asarray(model["scale"])
    coefficients, intercept = np.asarray(model["coefficients"]), np.asarray(model["intercept"])
    if (
        mean.shape != (len(names),)
        or scale.shape != mean.shape
        or coefficients.shape != (4, len(names))
        or intercept.shape != (4,)
        or not np.isfinite(coefficients).all()
        or not np.isfinite(intercept).all()
    ):
        raise ValueError("invalid frozen model shape/values")
    if values.ndim != 2 or values.shape[1] != len(mean) or not np.isfinite(values).all():
        raise ValueError("invalid inference matrix")
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError("invalid frozen scaler")
    result = ((values - mean) / scale) @ coefficients.T
    result += intercept
    if result.shape != (len(values), 4) or not np.isfinite(result).all():
        raise ValueError("invalid frozen model output")
    return result
