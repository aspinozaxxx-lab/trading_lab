"""Verified development-only synchronized BR/MIX/RI/SI ten-minute data.

The loader deliberately refuses timestamps in 2026, verifies the pre-2026 V7
manifest chain, keeps a full regular ten-minute clock, and represents missing
bars with explicit masks.  Targets are built only across exact same-contract
successors; scheduled gaps and rolls are never bridged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
TOP_MANIFEST: Final[Path] = (
    PROJECT_ROOT / "data/processed/futures_v7_10m/manifest_2018-01-01_2025-12-31.json"
)
TOP_MANIFEST_SHA256: Final[str] = (
    "f620ff77a5368c93d6415fc1b5785f9eaaba6cef873a4425fcd98e9b69f3ba01"
)
ACTIVE_MAP: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/futures_v5/development_panel_2018_2025_active_contract_map.parquet"
)
ACTIVE_MAP_SHA256: Final[str] = (
    "40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823"
)
SPEC_PROXY: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/futures_v5_specs_v1"
    / "spec_proxy_2018-01-01_2025-12-31_87372f337a75eeb4/spec_proxy.parquet"
)
SPEC_PROXY_SHA256: Final[str] = (
    "8494235f8782a258ed86d448c1c57adf2d313062da06845211991bda2f76d682"
)
ASSETS: Final[tuple[str, ...]] = ("BR", "MIX", "RI", "SI")
SOURCE_ASSETS: Final[dict[str, str]] = {"BR": "BR", "MIX": "MIX", "RTS": "RI", "Si": "SI"}
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
TEN_MINUTES_NS: Final[int] = 600_000_000_000
PROTECTED_NS: Final[int] = pd.Timestamp("2026-01-01", tz="UTC").value
FEATURE_NAMES: Final[tuple[str, ...]] = (
    "log_close_return",
    "log_open_to_close",
    "log_high_low_range",
    "log_volume_change",
    "realized_volatility_6",
    "realized_volatility_18",
    "realized_volatility_72",
    "range_zscore_72",
    "volume_zscore_72",
    "minute_sin",
    "minute_cos",
    "weekday_sin",
    "weekday_cos",
)
HORIZONS: Final[tuple[int, ...]] = (3, 6, 18)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError(f"manifest is not an object: {path}")
    return payload


def _resolve_declared(relative: str) -> Path:
    path = (PROJECT_ROOT / "data" / relative).resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    if not path.is_relative_to(data_root):
        raise ValueError(f"manifest path escapes data root: {relative}")
    return path


def _verified_parquet_records() -> tuple[tuple[Path, str, str], ...]:
    if sha256_file(TOP_MANIFEST) != TOP_MANIFEST_SHA256:
        raise ValueError("pre-2026 top 10m manifest byte drift")
    top = _read_json(TOP_MANIFEST)
    if (
        top.get("requested_end") != "2025-12-31"
        or top.get("protected_from") != "2026-01-01"
        or top.get("research_status") != "development_only_holdout_untouched"
    ):
        raise ValueError("top manifest does not prove the protected boundary")
    records: list[tuple[Path, str, str]] = []
    seen_assets: set[str] = set()
    for asset_record in top.get("assets", []):
        if not isinstance(asset_record, dict):
            raise TypeError("malformed asset manifest record")
        source_asset = str(asset_record["asset_code"])
        if source_asset not in SOURCE_ASSETS:
            raise ValueError(f"unexpected source asset: {source_asset}")
        asset_path = _resolve_declared(str(asset_record["path"]))
        expected_asset_hash = str(asset_record["sha256"])
        if sha256_file(asset_path) != expected_asset_hash:
            raise ValueError(f"asset manifest byte drift: {source_asset}")
        manifest = _read_json(asset_path)
        if manifest.get("requested_end") != "2025-12-31":
            raise ValueError(f"asset manifest reaches outside development: {source_asset}")
        seen_assets.add(source_asset)
        for segment_record in manifest.get("segment_manifests", []):
            if not isinstance(segment_record, dict):
                raise TypeError("malformed segment manifest record")
            if int(segment_record.get("rows", 0)) == 0:
                continue
            segment_path = _resolve_declared(str(segment_record["path"]))
            if sha256_file(segment_path) != str(segment_record["sha256"]):
                raise ValueError(f"segment manifest byte drift: {segment_path.name}")
            segment = _read_json(segment_path)
            if segment.get("status") != "complete":
                raise ValueError(f"incomplete segment: {segment_path.name}")
            artifacts = segment.get("artifacts")
            if not isinstance(artifacts, dict) or not isinstance(artifacts.get("parquet"), dict):
                raise ValueError(f"segment parquet declaration absent: {segment_path.name}")
            parquet = artifacts["parquet"]
            parquet_path = _resolve_declared(str(parquet["path"]))
            expected = str(parquet["sha256"])
            if sha256_file(parquet_path) != expected:
                raise ValueError(f"segment parquet byte drift: {parquet_path.name}")
            records.append((parquet_path, expected, SOURCE_ASSETS[source_asset]))
    if seen_assets != set(SOURCE_ASSETS):
        raise ValueError("manifest does not contain the exact four-source universe")
    return tuple(records)


def _load_plan() -> pd.DataFrame:
    if sha256_file(ACTIVE_MAP) != ACTIVE_MAP_SHA256:
        raise ValueError("active contract map byte drift")
    columns = [
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "plan_tradable",
        "execution_open_available",
    ]
    frame = pd.read_parquet(ACTIVE_MAP, columns=columns)
    frame["local_date"] = pd.to_datetime(frame["decision_date"], errors="coerce").dt.date
    observed = pd.to_datetime(frame["observed_through"], errors="coerce").dt.date
    frame["asset"] = frame["asset_code"].astype(str).str.upper().replace({"RTS": "RI"})
    usable = (
        frame["local_date"].notna()
        & observed.eq(frame["local_date"])
        & frame["plan_tradable"].fillna(False).astype(bool)
        & frame["execution_open_available"].fillna(False).astype(bool)
        & frame["contract_id"].notna()
        & frame["asset"].isin(ASSETS)
    )
    plan = frame.loc[usable, ["local_date", "asset", "contract_id"]].copy()
    plan["contract_id"] = plan["contract_id"].astype(str)
    if plan.duplicated(["local_date", "asset"]).any():
        raise ValueError("point-in-time plan duplicates date/asset")
    if max(plan["local_date"]) >= date(2026, 1, 1):
        raise ValueError("active plan touches protected holdout")
    return plan


def _load_active_bars(plan: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    planned_ids = set(plan["contract_id"])
    frames: list[pd.DataFrame] = []
    used_hashes: list[str] = []
    columns = [
        "timestamp",
        "asset_code",
        "canonical_contract_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    for path, source_hash, normalized_asset in _verified_parquet_records():
        part = pd.read_parquet(path, columns=columns)
        part = part[part["canonical_contract_id"].astype(str).isin(planned_ids)].copy()
        if part.empty:
            continue
        part["asset"] = normalized_asset
        part["contract_id"] = part["canonical_contract_id"].astype(str)
        frames.append(part)
        used_hashes.append(source_hash)
    if not frames:
        raise ValueError("no active planned bars were found")
    bars = pd.concat(frames, ignore_index=True)
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], errors="raise", utc=True)
    if (bars["timestamp"].astype("int64") >= PROTECTED_NS).any():
        raise ValueError("loaded bars touch protected 2026 holdout")
    bars["local_date"] = bars["timestamp"].dt.tz_convert(MOSCOW).dt.date
    bars = bars.merge(
        plan,
        on=["local_date", "asset", "contract_id"],
        how="inner",
        validate="many_to_one",
    )
    bars["timestamp_ns"] = bars["timestamp"].astype("int64")
    if bars.duplicated(["timestamp_ns", "asset"]).any():
        raise ValueError("active bars duplicate timestamp/asset")
    bars = bars.sort_values(["timestamp_ns", "asset"], kind="stable").reset_index(drop=True)
    numeric = ["open", "high", "low", "close", "volume"]
    bars[numeric] = bars[numeric].apply(pd.to_numeric, errors="coerce")
    valid_ohlc = (
        bars[numeric].notna().all(axis=1)
        & bars["open"].gt(0)
        & bars["high"].ge(bars[["open", "close"]].max(axis=1))
        & bars["low"].le(bars[["open", "close"]].min(axis=1))
        & bars["volume"].ge(0)
    )
    bars = bars.loc[valid_ohlc].reset_index(drop=True)
    return bars, tuple(sorted(set(used_hashes)))


@dataclass(frozen=True, slots=True)
class TimingArrays:
    timestamps_ns: np.ndarray
    features: np.ndarray
    feature_mask: np.ndarray
    asset_mask: np.ndarray
    contract_ids: np.ndarray
    current_ohlcv: np.ndarray
    execution_ohlcv: np.ndarray
    execution_mask: np.ndarray
    target_values: np.ndarray
    target_mask: np.ndarray
    fee_per_side: np.ndarray
    point_value: np.ndarray
    notional: np.ndarray
    sizing_mask: np.ndarray
    source_hashes: tuple[str, ...]


def _rolling_z(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=window).mean()
    std = values.rolling(window, min_periods=window).std(ddof=0)
    return (values - mean) / std.replace(0.0, np.nan)


def _build_features_for_asset(frame: pd.DataFrame, timestamps: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    index = pd.Index(timestamps)
    # Rolling windows count completed market bars, while one-bar changes still
    # refuse to cross a clock gap or a contract boundary.  Reindexing happens
    # only after those causal bar-count features have been calculated.
    series = frame.sort_values("timestamp_ns", kind="stable").set_index("timestamp_ns")
    present = series["close"].notna()
    contract = series["contract_id"].fillna("").astype(str)
    timestamp_series = pd.Series(series.index.to_numpy(dtype=np.int64), index=series.index)
    exact_previous = (
        present
        & timestamp_series.diff().eq(TEN_MINUTES_NS)
        & contract.eq(contract.shift(1))
    )
    close = series["close"].astype(float)
    open_ = series["open"].astype(float)
    high = series["high"].astype(float)
    low = series["low"].astype(float)
    volume = series["volume"].astype(float)
    log_close = np.log(close)
    log_return = log_close.diff().where(exact_previous)
    log_volume = np.log1p(volume)
    log_volume_change = log_volume.diff().where(exact_previous)
    bar_range = np.log(high / low)
    local = pd.to_datetime(series.index.to_numpy(dtype=np.int64), utc=True).tz_convert(MOSCOW)
    minute = local.hour * 60 + local.minute
    weekday = local.weekday
    dense_values = np.column_stack(
        [
            log_return.to_numpy(),
            np.log(close / open_).to_numpy(),
            bar_range.to_numpy(),
            log_volume_change.to_numpy(),
            log_return.rolling(6, min_periods=6).std(ddof=0).to_numpy(),
            log_return.rolling(18, min_periods=18).std(ddof=0).to_numpy(),
            log_return.rolling(72, min_periods=72).std(ddof=0).to_numpy(),
            _rolling_z(bar_range, 72).to_numpy(),
            _rolling_z(log_volume, 72).to_numpy(),
            np.sin(2.0 * np.pi * minute / 1440.0),
            np.cos(2.0 * np.pi * minute / 1440.0),
            np.sin(2.0 * np.pi * weekday / 7.0),
            np.cos(2.0 * np.pi * weekday / 7.0),
        ]
    ).astype(np.float32)
    dense = pd.DataFrame(dense_values, index=series.index).reindex(index)
    values = dense.to_numpy(dtype=np.float32)
    reindexed = series.reindex(index)
    present_grid = reindexed["close"].notna().to_numpy()
    mask = np.isfinite(values) & present_grid[:, None]
    ohlcv = reindexed[["open", "high", "low", "close", "volume"]].to_numpy(dtype=np.float64)
    return values, mask, ohlcv


def _join_specs(
    timestamps: np.ndarray,
    contract_ids: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if sha256_file(SPEC_PROXY) != SPEC_PROXY_SHA256:
        raise ValueError("spec proxy byte drift")
    columns = [
        "session_date",
        "contract_id",
        "asset_symbol",
        "sizing_point_value",
        "sizing_notional",
        "conservative_fee_per_side",
        "sizing_usable",
    ]
    spec = pd.read_parquet(SPEC_PROXY, columns=columns)
    spec["local_date"] = pd.to_datetime(spec["session_date"], errors="raise").dt.date
    spec["asset"] = spec["asset_symbol"].astype(str).str.upper().replace({"RTS": "RI"})
    spec["contract_id"] = spec["contract_id"].astype(str)
    spec = spec.drop_duplicates(["local_date", "asset", "contract_id"], keep="last")
    local_dates = pd.to_datetime(timestamps, utc=True).tz_convert(MOSCOW).date
    shape = contract_ids.shape
    fee = np.full(shape, np.nan, dtype=np.float64)
    point = np.full(shape, np.nan, dtype=np.float64)
    notional = np.full(shape, np.nan, dtype=np.float64)
    usable = np.zeros(shape, dtype=bool)
    for asset_index, asset in enumerate(ASSETS):
        left = pd.DataFrame(
            {
                "row": np.arange(len(timestamps)),
                "local_date": local_dates,
                "asset": asset,
                "contract_id": contract_ids[:, asset_index],
            }
        )
        merged = left.merge(
            spec[
                [
                    "local_date",
                    "asset",
                    "contract_id",
                    "sizing_point_value",
                    "sizing_notional",
                    "conservative_fee_per_side",
                    "sizing_usable",
                ]
            ],
            on=["local_date", "asset", "contract_id"],
            how="left",
            validate="many_to_one",
        ).sort_values("row")
        fee[:, asset_index] = merged["conservative_fee_per_side"].to_numpy(float)
        point[:, asset_index] = merged["sizing_point_value"].to_numpy(float)
        notional[:, asset_index] = merged["sizing_notional"].to_numpy(float)
        usable[:, asset_index] = (
            merged["sizing_usable"].astype("boolean").fillna(False).to_numpy(dtype=bool)
            & np.isfinite(fee[:, asset_index])
            & np.isfinite(point[:, asset_index])
            & np.isfinite(notional[:, asset_index])
            & (point[:, asset_index] > 0)
            & (notional[:, asset_index] > 0)
        )
    return fee, point, notional, usable


def build_timing_arrays() -> TimingArrays:
    plan = _load_plan()
    bars, hashes = _load_active_bars(plan)
    minimum = int(bars["timestamp_ns"].min())
    maximum = int(bars["timestamp_ns"].max())
    minimum -= minimum % TEN_MINUTES_NS
    maximum -= maximum % TEN_MINUTES_NS
    timestamps = np.arange(minimum, maximum + TEN_MINUTES_NS, TEN_MINUTES_NS, dtype=np.int64)
    if timestamps[-1] >= PROTECTED_NS:
        raise ValueError("regular grid touches protected holdout")
    count = len(timestamps)
    features = np.full((count, len(ASSETS), len(FEATURE_NAMES)), np.nan, dtype=np.float32)
    feature_mask = np.zeros(features.shape, dtype=bool)
    current = np.full((count, len(ASSETS), 5), np.nan, dtype=np.float64)
    contract_ids = np.full((count, len(ASSETS)), "", dtype="U32")
    asset_mask = np.zeros((count, len(ASSETS)), dtype=bool)
    for asset_index, asset in enumerate(ASSETS):
        subset = bars[bars["asset"] == asset].copy()
        values, mask, ohlcv = _build_features_for_asset(subset, timestamps)
        features[:, asset_index] = values
        feature_mask[:, asset_index] = mask
        current[:, asset_index] = ohlcv
        present = np.isfinite(ohlcv[:, 3])
        asset_mask[:, asset_index] = present
        mapping = subset.set_index("timestamp_ns")["contract_id"]
        contract_ids[:, asset_index] = mapping.reindex(pd.Index(timestamps)).fillna("").astype(str)
    execution = np.roll(current, -1, axis=0)
    execution[-1] = np.nan
    exact_next = np.roll(asset_mask, -1, axis=0)
    exact_next[-1] = False
    same_contract = contract_ids == np.roll(contract_ids, -1, axis=0)
    same_contract[-1] = False
    execution_mask = asset_mask & exact_next & same_contract
    execution[~execution_mask] = np.nan
    fee, point, notional, sizing_mask = _join_specs(timestamps, contract_ids)
    targets = np.full((count, len(ASSETS), len(HORIZONS), 2), np.nan, dtype=np.float32)
    target_mask = np.zeros(targets.shape, dtype=bool)
    entry_high = execution[:, :, 1]
    entry_low = execution[:, :, 2]
    round_trip_fraction = np.where(sizing_mask, 2.0 * fee / notional, 0.001)
    for horizon_index, horizon in enumerate(HORIZONS):
        offset = horizon - 1
        exit_low = np.roll(execution[:, :, 2], -offset, axis=0)
        exit_high = np.roll(execution[:, :, 1], -offset, axis=0)
        if offset:
            exit_low[-offset:] = np.nan
            exit_high[-offset:] = np.nan
        path_valid = execution_mask.copy()
        for step in range(1, horizon):
            shifted = np.roll(execution_mask, -step, axis=0)
            shifted[-step:] = False
            same_path = contract_ids == np.roll(contract_ids, -step, axis=0)
            same_path[-step:] = False
            path_valid &= shifted & same_path
        long_value = exit_low / entry_high - 1.0 - round_trip_fraction
        short_value = entry_low / exit_high - 1.0 - round_trip_fraction
        valid = (
            path_valid
            & np.isfinite(long_value)
            & np.isfinite(short_value)
            & (entry_high > 0)
            & (entry_low > 0)
        )
        targets[:, :, horizon_index, 0] = np.where(valid, long_value, np.nan)
        targets[:, :, horizon_index, 1] = np.where(valid, short_value, np.nan)
        target_mask[:, :, horizon_index, 0] = valid
        target_mask[:, :, horizon_index, 1] = valid
    return TimingArrays(
        timestamps_ns=timestamps,
        features=features,
        feature_mask=feature_mask,
        asset_mask=asset_mask,
        contract_ids=contract_ids,
        current_ohlcv=current,
        execution_ohlcv=execution,
        execution_mask=execution_mask,
        target_values=targets,
        target_mask=target_mask,
        fee_per_side=fee,
        point_value=point,
        notional=notional,
        sizing_mask=sizing_mask,
        source_hashes=hashes,
    )


def save_timing_arrays(arrays: TimingArrays, path: Path) -> Path:
    """Persist a compact immutable training/evaluation tensor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    unique_contracts = sorted(set(arrays.contract_ids.ravel()) - {""})
    code_by_contract = {name: index + 1 for index, name in enumerate(unique_contracts)}
    contract_codes = np.zeros(arrays.contract_ids.shape, dtype=np.int16)
    for name, code in code_by_contract.items():
        contract_codes[arrays.contract_ids == name] = code
    np.savez_compressed(
        path,
        timestamps_ns=arrays.timestamps_ns,
        features=arrays.features,
        feature_mask=arrays.feature_mask,
        asset_mask=arrays.asset_mask,
        contract_codes=contract_codes,
        contract_names=np.asarray([""] + unique_contracts, dtype="U32"),
        execution_ohlcv=arrays.execution_ohlcv.astype(np.float32),
        execution_mask=arrays.execution_mask,
        target_values=arrays.target_values,
        target_mask=arrays.target_mask,
        fee_per_side=arrays.fee_per_side.astype(np.float32),
        point_value=arrays.point_value.astype(np.float32),
        notional=arrays.notional.astype(np.float32),
        sizing_mask=arrays.sizing_mask,
        source_hashes=np.asarray(arrays.source_hashes, dtype="U64"),
    )
    return path


def load_timing_arrays(path: Path) -> TimingArrays:
    """Load a compact tensor while retaining explicit masks and contract identity."""
    with np.load(path, allow_pickle=False) as payload:
        names = payload["contract_names"]
        codes = payload["contract_codes"]
        contract_ids = names[codes]
        empty_current = np.full((*payload["asset_mask"].shape, 5), np.nan, dtype=np.float64)
        return TimingArrays(
            timestamps_ns=payload["timestamps_ns"].copy(),
            features=payload["features"].copy(),
            feature_mask=payload["feature_mask"].copy(),
            asset_mask=payload["asset_mask"].copy(),
            contract_ids=contract_ids,
            current_ohlcv=empty_current,
            execution_ohlcv=payload["execution_ohlcv"].astype(np.float64),
            execution_mask=payload["execution_mask"].copy(),
            target_values=payload["target_values"].copy(),
            target_mask=payload["target_mask"].copy(),
            fee_per_side=payload["fee_per_side"].astype(np.float64),
            point_value=payload["point_value"].astype(np.float64),
            notional=payload["notional"].astype(np.float64),
            sizing_mask=payload["sizing_mask"].copy(),
            source_hashes=tuple(str(item) for item in payload["source_hashes"]),
        )


__all__ = [
    "ASSETS",
    "FEATURE_NAMES",
    "HORIZONS",
    "TimingArrays",
    "build_timing_arrays",
    "load_timing_arrays",
    "save_timing_arrays",
    "sha256_file",
]
