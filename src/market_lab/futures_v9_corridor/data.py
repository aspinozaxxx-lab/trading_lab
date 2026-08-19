"""Verified raw-data loader and causal feature construction for corridor-v9.

The synchronized intraday array API at the bottom is intentionally target-free and
is reusable by a later every-ten-minute timing model.  Missing assets remain NaN
and are represented by masks; they are never silently replaced with zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from hashlib import sha256
from math import isfinite, log, pi, sqrt
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

from market_lab.futures.cftc_radar import (
    build_causal_cftc_asset_scores,
    build_causal_cftc_features,
    official_development_release_overrides,
)
from market_lab.futures_v8.context_run import (
    _load_active_contract_sources,
    _verified_raw_parquet_records,
    verify_main_session_manifest_tree,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs" / "futures_v9_corridor.yaml"
DEFAULT_CONFIG_SHA256: Final[str] = (
    "aeb3b24fbb21b9400a6643815a9ad9488b91ef714358ea880cdb71c83c952053"
)
ASSETS: Final[tuple[str, ...]] = ("BR", "MIX", "RI", "SI")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
PROTECTED_AT: Final[pd.Timestamp] = pd.Timestamp("2026-01-01", tz="UTC")


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into one giant byte string."""
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset_id(value: object) -> str:
    normalized = str(value).upper()
    aliases = {"BR": "BR", "MIX": "MIX", "RTS": "RI", "RI": "RI", "SI": "SI"}
    if normalized not in aliases:
        raise ValueError(f"unknown asset alias: {value!r}")
    return aliases[normalized]


def _decision_at(day: object) -> datetime:
    normalized = pd.Timestamp(day).date()
    return datetime.combine(normalized, time(18, 50), MOSCOW).astimezone(UTC)


def load_protocol(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and verify the immutable pre-outcome protocol and its sidecar."""
    resolved = path.resolve()
    if resolved != DEFAULT_CONFIG_PATH.resolve():
        raise ValueError("only the sealed default corridor protocol is accepted")
    actual = sha256_file(resolved)
    if actual != DEFAULT_CONFIG_SHA256:
        raise ValueError("corridor protocol byte identity drift")
    sidecar = resolved.with_suffix(".sha256")
    tokens = sidecar.read_text(encoding="utf-8-sig").strip().split()
    if tokens != [actual, resolved.name]:
        raise ValueError("corridor protocol sidecar mismatch")
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("corridor protocol must be a YAML object")
    if payload.get("protected_holdout_start") != date(2026, 1, 1):
        raise ValueError("protected holdout boundary drift")
    return payload


def verify_protocol_sources(protocol: dict[str, Any]) -> dict[str, Path]:
    """Verify every pinned source before any parquet is parsed."""
    output: dict[str, Path] = {}
    for name, record in protocol["sources"].items():
        path = (PROJECT_ROOT / str(record["path"])).resolve()
        if not path.is_relative_to(PROJECT_ROOT) or not path.is_file():
            raise ValueError(f"source path escapes project or is missing: {name}")
        if sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"source hash mismatch: {name}")
        output[str(name)] = path
    return output


@dataclass(frozen=True, slots=True)
class ContractBarStore:
    """All verified bars for contracts that were causally planned on a decision date."""

    bars: pd.DataFrame
    by_contract: dict[str, pd.DataFrame]
    parquet_sha256s: tuple[str, ...]

    def exact_bar(self, contract_id: str, opened_at: datetime) -> pd.Series | None:
        frame = self.by_contract.get(contract_id)
        if frame is None:
            return None
        target = pd.Timestamp(opened_at).tz_convert("UTC").value
        positions = np.flatnonzero(frame["timestamp_ns"].to_numpy(dtype=np.int64) == target)
        if len(positions) != 1:
            return None
        return frame.iloc[int(positions[0])]

    def between(
        self,
        contract_id: str,
        opened_at_inclusive: datetime,
        opened_at_exclusive: datetime,
    ) -> pd.DataFrame:
        frame = self.by_contract.get(contract_id)
        if frame is None:
            return pd.DataFrame(columns=self.bars.columns)
        values = frame["timestamp_ns"].to_numpy(dtype=np.int64)
        lower = pd.Timestamp(opened_at_inclusive).tz_convert("UTC").value
        upper = pd.Timestamp(opened_at_exclusive).tz_convert("UTC").value
        left = int(np.searchsorted(values, lower, side="left"))
        right = int(np.searchsorted(values, upper, side="left"))
        return frame.iloc[left:right]


@dataclass(frozen=True, slots=True)
class CorridorSourceBundle:
    """Target-free causal features, contract plan, and post-decision raw bars."""

    protocol: dict[str, Any]
    source_paths: dict[str, Path]
    decisions: tuple[datetime, ...]
    features: pd.DataFrame
    planned_contracts: pd.DataFrame
    active_map: pd.DataFrame
    spec_proxy: pd.DataFrame
    bar_store: ContractBarStore
    raw_tree_bundle_sha256: str


def _calendar_from_active_map(frame: pd.DataFrame) -> tuple[datetime, ...]:
    working = frame.copy()
    working["effective_date"] = pd.to_datetime(working["effective_date"], errors="coerce").dt.date
    working["asset"] = working["asset_code"].map(_asset_id)
    counts = working.dropna(subset=["effective_date"]).groupby("effective_date")["asset"].nunique()
    days = tuple(sorted(counts[counts == len(ASSETS)].index))
    decisions = tuple(_decision_at(day) for day in days)
    if not decisions or decisions[-1] >= PROTECTED_AT.to_pydatetime():
        raise ValueError("decision calendar is empty or touches protected holdout")
    return decisions


def _build_market_feature_frame(
    decisions: tuple[datetime, ...],
    session_contracts: tuple[Any, ...],
    bar_store: ContractBarStore,
) -> pd.DataFrame:
    """Vectorized equivalent of the v2 raw-10m causal daily feature contract."""
    contracts = {(item.decision_at, item.asset_id): item for item in session_contracts}
    base_rows: list[dict[str, object]] = []
    for decision_at in decisions:
        local_day = decision_at.astimezone(MOSCOW).date()
        for asset in ASSETS:
            observation = contracts.get((decision_at, asset))
            record: dict[str, object] = {
                "decision_at": pd.Timestamp(decision_at),
                "decision_date": local_day,
                "asset": asset,
                "market_valid": False,
                "raw_close": np.nan,
                "adjusted_open": np.nan,
                "adjusted_high": np.nan,
                "adjusted_low": np.nan,
                "adjusted_close": np.nan,
                "main_session_bucket_count": 0,
                "session_rv": np.nan,
                "session_volume": np.nan,
                "daily_base_valid": False,
                "session_ratio_valid": False,
            }
            if observation is None:
                base_rows.append(record)
                continue
            interval = bar_store.between(
                observation.contract_id,
                observation.previous_decision_at,
                observation.decision_at,
            )
            if interval.empty or interval.duplicated("timestamp_ns").any():
                base_rows.append(record)
                continue
            local = interval["timestamp"].dt.tz_convert(MOSCOW)
            minute = local.dt.hour * 60 + local.dt.minute
            main = interval[(local.dt.date == local_day) & minute.between(600, 1120)].copy()
            record["main_session_bucket_count"] = len(main)
            exact_close = main[
                (main["timestamp"].dt.tz_convert(MOSCOW).dt.hour == 18)
                & (main["timestamp"].dt.tz_convert(MOSCOW).dt.minute == 40)
            ]
            if len(exact_close) != 1:
                base_rows.append(record)
                continue
            raw_close = float(exact_close.iloc[0]["close"])
            adjustment = float(observation.forward_additive_adjustment)
            adjusted = (
                float(interval.iloc[0]["open"]) + adjustment,
                float(interval["high"].max()) + adjustment,
                float(interval["low"].min()) + adjustment,
                raw_close + adjustment,
            )
            main_close = main["close"].astype(float).to_numpy()
            returns = np.diff(np.log(main_close)) if len(main_close) >= 2 else np.asarray([])
            duplicate_main = main.duplicated("timestamp_ns").any()
            session_ratio_valid = len(main) >= 48 and not duplicate_main and returns.size >= 1
            daily_valid = min(adjusted) > 0.0
            record.update(
                {
                    "raw_close": raw_close,
                    "adjusted_open": adjusted[0],
                    "adjusted_high": adjusted[1],
                    "adjusted_low": adjusted[2],
                    "adjusted_close": adjusted[3],
                    "session_rv": (
                        float(np.sqrt(np.sum(returns**2))) if returns.size else np.nan
                    ),
                    "session_volume": float(main["volume"].astype(float).sum()),
                    "daily_base_valid": daily_valid,
                    "session_ratio_valid": session_ratio_valid,
                }
            )
            if len(main) >= 2:
                first_end = min(6, len(main) - 1)
                last_start = max(0, len(main) - 7)
                total_range = float(main["high"].max() - main["low"].min())
                rms = float(np.sqrt(np.mean(returns**2))) if returns.size else np.nan
                record.update(
                    {
                        "intraday_return": float(
                            log(float(main.iloc[-1]["close"]))
                            - log(float(main.iloc[0]["open"]))
                        ),
                        "first_hour_return": float(
                            log(float(main.iloc[first_end]["close"]))
                            - log(float(main.iloc[0]["open"]))
                        ),
                        "last_hour_return": float(
                            log(float(main.iloc[-1]["close"]))
                            - log(float(main.iloc[last_start]["open"]))
                        ),
                        "close_location": (
                            float(
                                (float(main.iloc[-1]["close"]) - float(main["low"].min()))
                                / total_range
                            )
                            if total_range > 0.0
                            else np.nan
                        ),
                        "up_bar_fraction": float(np.mean(returns > 0.0)),
                        "max_abs_bar_return": float(np.max(np.abs(returns))),
                        "intraday_return_skew": (
                            float(np.mean((returns - returns.mean()) ** 3) / rms**3)
                            if returns.size >= 3 and rms > 0.0
                            else np.nan
                        ),
                    }
                )
            base_rows.append(record)
    frame = pd.DataFrame(base_rows).sort_values(["asset", "decision_at"], kind="stable")
    metric_columns = (
        "atr_20",
        "daily_volatility_20",
        "momentum_20",
        "range_position_20",
        "volatility_ratio_20",
        "volume_ratio_20",
        "momentum_1",
        "momentum_5",
        "overnight_gap",
    )
    for name in metric_columns:
        frame[name] = np.nan
    for _asset, indices in frame.groupby("asset", sort=False).groups.items():
        ordered = frame.loc[indices].sort_values("decision_at", kind="stable")
        index_values = ordered.index.to_numpy()
        close = ordered["adjusted_close"].astype(float)
        frame.loc[index_values, "momentum_1"] = np.log(close).diff().to_numpy()
        frame.loc[index_values, "momentum_5"] = np.log(close).diff(5).to_numpy()
        frame.loc[index_values, "overnight_gap"] = (
            np.log(ordered["adjusted_open"].astype(float)) - np.log(close.shift(1))
        ).to_numpy()
        valid = ordered["daily_base_valid"].astype(bool).to_numpy()
        ratio_valid = ordered["session_ratio_valid"].astype(bool).to_numpy()
        values = ordered.reset_index(drop=True)
        for position, original_index in enumerate(index_values):
            if position >= 20 and valid[position - 20 : position + 1].all():
                window = values.iloc[position - 20 : position + 1]
                previous_close = window["adjusted_close"].astype(float).to_numpy()[:-1]
                high = window["adjusted_high"].astype(float).to_numpy()[1:]
                low = window["adjusted_low"].astype(float).to_numpy()[1:]
                true_range = np.maximum.reduce(
                    [high - low, np.abs(high - previous_close), np.abs(low - previous_close)]
                )
                close_values = window["adjusted_close"].astype(float).to_numpy()
                returns = np.diff(np.log(close_values))
                frame.at[original_index, "atr_20"] = float(np.mean(true_range))
                frame.at[original_index, "daily_volatility_20"] = float(np.std(returns, ddof=0))
                frame.at[original_index, "momentum_20"] = float(
                    log(close_values[-1]) - log(close_values[0])
                )
            if position >= 20 and valid[position] and valid[position - 20 : position].all():
                prior = values.iloc[position - 20 : position]
                lower = float(prior["adjusted_low"].min())
                upper = float(prior["adjusted_high"].max())
                if upper > lower:
                    frame.at[original_index, "range_position_20"] = float(
                        (values.iloc[position]["adjusted_close"] - lower) / (upper - lower)
                    )
            if position >= 20 and ratio_valid[position - 20 : position].all():
                prior = values.iloc[position - 20 : position]
                baseline_rv = float(prior["session_rv"].mean())
                baseline_volume = float(prior["session_volume"].mean())
                if baseline_rv > 0.0 and pd.notna(values.iloc[position]["session_rv"]):
                    frame.at[original_index, "volatility_ratio_20"] = float(
                        values.iloc[position]["session_rv"] / baseline_rv
                    )
                if baseline_volume > 0.0 and pd.notna(values.iloc[position]["session_volume"]):
                    frame.at[original_index, "volume_ratio_20"] = float(
                        values.iloc[position]["session_volume"] / baseline_volume
                    )
    required = [
        "atr_20",
        "daily_volatility_20",
        "momentum_20",
        "range_position_20",
        "volatility_ratio_20",
        "volume_ratio_20",
    ]
    frame["market_valid"] = (
        frame["daily_base_valid"].astype(bool)
        & frame["session_ratio_valid"].astype(bool)
        & frame[required].notna().all(axis=1)
        & frame["daily_volatility_20"].gt(0.0)
    )
    return frame.sort_values(["decision_at", "asset"], kind="stable").reset_index(drop=True)


def _expanding_snapshot_z(values: pd.Series, minimum: int = 60) -> pd.Series:
    output = np.full(len(values), np.nan, dtype=np.float64)
    history: list[float] = []
    for index, raw in enumerate(values.to_numpy()):
        if pd.isna(raw) or not isfinite(float(raw)):
            continue
        if len(history) >= minimum:
            scale = pstdev(history)
            if scale > 0.0:
                output[index] = float(np.clip((float(raw) - fmean(history)) / scale, -5.0, 5.0))
        history.append(float(raw))
    return pd.Series(output, index=values.index)


def _append_carry(frame: pd.DataFrame, daily_curve_path: Path) -> pd.DataFrame:
    curve = pd.read_parquet(
        daily_curve_path,
        columns=["trade_date", "asset_code", "roll_yield", "curve_valid"],
    )
    curve["decision_date"] = pd.to_datetime(curve["trade_date"]).dt.date
    curve["asset"] = curve["asset_code"].map(_asset_id)
    curve["carry_raw"] = curve["roll_yield"].where(curve["curve_valid"].fillna(False))
    merged = frame.merge(
        curve[["decision_date", "asset", "carry_raw"]],
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    merged["carry_z"] = np.nan
    for _asset, indices in merged.groupby("asset", sort=False).groups.items():
        ordered = merged.loc[indices].sort_values("decision_at", kind="stable")
        causal_raw = ordered["carry_raw"].shift(1)
        merged.loc[ordered.index, "carry_raw"] = causal_raw.to_numpy()
        merged.loc[ordered.index, "carry_z"] = _expanding_snapshot_z(causal_raw)
    return merged


def _z_by_unique_release(
    values: pd.Series,
    identities: pd.Series,
    *,
    minimum: int = 60,
) -> pd.Series:
    output = np.full(len(values), np.nan, dtype=np.float64)
    history: list[float] = []
    cached: dict[str, float] = {}
    for index, (raw, identity) in enumerate(zip(values, identities, strict=True)):
        if pd.isna(raw) or pd.isna(identity):
            continue
        key = str(identity)
        if key not in cached:
            value = np.nan
            if len(history) >= minimum:
                scale = pstdev(history)
                if scale > 0.0:
                    value = float(np.clip((float(raw) - fmean(history)) / scale, -5.0, 5.0))
            cached[key] = value
            history.append(float(raw))
        output[index] = cached[key]
    return pd.Series(output, index=values.index)


def _append_cftc(
    frame: pd.DataFrame,
    cftc_path: Path,
    decisions: tuple[datetime, ...],
) -> pd.DataFrame:
    history = pd.read_parquet(cftc_path)
    causal = build_causal_cftc_features(
        history,
        pd.DatetimeIndex(decisions),
        release_overrides=official_development_release_overrides(),
    )
    scores = build_causal_cftc_asset_scores(causal)
    scores["asset"] = scores["asset_symbol"].map(_asset_id)
    scores["decision_at"] = pd.to_datetime(scores["decision_at"], utc=True)
    def release_identity(row: pd.Series) -> str:
        required = tuple(str(row["required_channels"]).split(","))
        return "|".join(
            f"{channel}:{row[f'{channel}_report_date']}:{row[f'{channel}_available_at']}"
            for channel in required
        )

    scores["release_identity"] = scores.apply(release_identity, axis=1)
    scores = scores.sort_values(["asset", "decision_at"], kind="stable")
    scores["cftc_z"] = np.nan
    for _asset, indices in scores.groupby("asset", sort=False).groups.items():
        ordered = scores.loc[indices].sort_values("decision_at", kind="stable")
        scores.loc[ordered.index, "cftc_z"] = _z_by_unique_release(
            ordered["score"], ordered["release_identity"]
        )
    return frame.merge(
        scores[["decision_at", "asset", "score", "cftc_z"]].rename(
            columns={"score": "cftc_raw"}
        ),
        on=["decision_at", "asset"],
        how="left",
        validate="one_to_one",
    )


def _append_cbr(
    frame: pd.DataFrame,
    cbr_path: Path,
    decisions: tuple[datetime, ...],
) -> pd.DataFrame:
    cbr = pd.read_parquet(
        cbr_path,
        columns=["series_id", "observation_date", "available_at", "value"],
    )
    cbr["available_at"] = pd.to_datetime(cbr["available_at"], errors="raise", utc=True)
    if (cbr["available_at"] >= PROTECTED_AT).any():
        raise ValueError("CBR source touches protected holdout")
    fx = cbr[cbr["series_id"].astype(str) == "usd_rub_official"].sort_values(
        "available_at", kind="stable"
    )
    fx = fx.drop_duplicates("available_at", keep="last").copy()
    fx["fx_return_raw"] = np.log(fx["value"].astype(float)).diff()
    fx["release_identity"] = (
        fx["observation_date"].astype(str) + "|" + fx["available_at"].astype(str)
    )
    decision_frame = pd.DataFrame({"decision_at": pd.to_datetime(decisions, utc=True)})
    asof = pd.merge_asof(
        decision_frame.sort_values("decision_at"),
        fx[["available_at", "fx_return_raw", "release_identity"]].dropna(
            subset=["fx_return_raw"]
        ),
        left_on="decision_at",
        right_on="available_at",
        direction="backward",
    )
    asof["usd_rub_return_z"] = _z_by_unique_release(
        asof["fx_return_raw"], asof["release_identity"]
    )
    merged = frame.merge(
        asof[["decision_at", "fx_return_raw", "usd_rub_return_z"]],
        on="decision_at",
        how="left",
        validate="many_to_one",
    )
    merged["key_rate_sleeping"] = 1.0
    return merged


def _append_regime(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    probability_rows: list[dict[str, object]] = []
    for decision_at, group in output.groupby("decision_at", sort=True):
        valid = group[["momentum_20", "momentum_5", "daily_volatility_20"]].dropna()
        if valid.empty:
            probabilities = (np.nan, np.nan, np.nan)
        else:
            scale = max(float(valid["daily_volatility_20"].median()), 1e-12)
            trend_logit = float(np.median(np.abs(valid["momentum_20"]))) / (
                scale * sqrt(20.0)
            ) - 1.0
            crash_logit = -float(valid["momentum_5"].median()) / (scale * sqrt(5.0)) - 1.5
            logits = np.asarray([0.0, trend_logit, crash_logit], dtype=np.float64)
            exponent = np.exp(np.clip(logits - logits.max(), -30.0, 30.0))
            probabilities = tuple((exponent / exponent.sum()).tolist())
        probability_rows.append(
            {
                "decision_at": decision_at,
                "regime_normal_probability": probabilities[0],
                "regime_trend_probability": probabilities[1],
                "regime_crash_probability": probabilities[2],
            }
        )
    return output.merge(pd.DataFrame(probability_rows), on="decision_at", validate="many_to_one")


def _load_contract_bar_store(
    records: tuple[tuple[Path, str], ...],
    contract_ids: set[str],
) -> ContractBarStore:
    frames: list[pd.DataFrame] = []
    columns = [
        "timestamp",
        "end_timestamp",
        "asset_code",
        "canonical_contract_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    used_sha: list[str] = []
    for path, source_sha in records:
        part = pd.read_parquet(path, columns=columns)
        part = part[part["canonical_contract_id"].astype(str).isin(contract_ids)].copy()
        if part.empty:
            continue
        part["source_sha256"] = source_sha
        frames.append(part)
        used_sha.append(source_sha)
    if not frames:
        raise ValueError("no planned-contract 10m bars were loaded")
    bars = pd.concat(frames, ignore_index=True)
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], errors="raise", utc=True)
    bars["end_timestamp"] = pd.to_datetime(bars["end_timestamp"], errors="raise", utc=True)
    if (bars["timestamp"] >= PROTECTED_AT).any() or (bars["end_timestamp"] >= PROTECTED_AT).any():
        raise ValueError("raw bar store touches protected holdout")
    bars["asset"] = bars["asset_code"].map(_asset_id)
    bars["contract_id"] = bars["canonical_contract_id"].astype(str)
    bars["timestamp_ns"] = bars["timestamp"].astype("int64")
    if bars.duplicated(["contract_id", "timestamp_ns"]).any():
        raise ValueError("raw bar store contains duplicate contract timestamps")
    bars = bars.sort_values(["contract_id", "timestamp_ns"], kind="stable").reset_index(drop=True)
    by_contract = {
        str(contract): group.reset_index(drop=True)
        for contract, group in bars.groupby("contract_id", sort=False)
    }
    return ContractBarStore(
        bars=bars,
        by_contract=by_contract,
        parquet_sha256s=tuple(sorted(set(used_sha))),
    )


def load_corridor_source_bundle() -> CorridorSourceBundle:
    """Build the full target-free source bundle from verified 2018-2025 bytes."""
    protocol = load_protocol()
    paths = verify_protocol_sources(protocol)
    active = pd.read_parquet(paths["active_contract_map"])
    decisions = _calendar_from_active_map(active)
    full_decisions, session_contracts, planned, active_whitelist, _columns = (
        _load_active_contract_sources(
            paths["active_contract_map"],
            protocol["sources"]["active_contract_map"]["sha256"],
            decisions,
        )
    )
    if tuple(full_decisions) != decisions:
        raise RuntimeError("active-map calendar reconstruction drift")
    tree = verify_main_session_manifest_tree(paths["raw_10m_manifest"])
    records = _verified_raw_parquet_records(paths["raw_10m_manifest"], tree)
    planned_frame = pd.DataFrame(
        [
            {
                "decision_at": pd.Timestamp(item.decision_at),
                "decision_date": item.decision_at.astimezone(MOSCOW).date(),
                "asset": item.asset_id,
                "contract_id": item.contract_id,
                "contract_code": item.contract_code,
            }
            for item in planned
        ]
    ).sort_values(["decision_at", "asset"], kind="stable")
    if planned_frame.duplicated(["decision_at", "asset"]).any():
        raise ValueError("planned contract frame contains duplicate keys")
    contract_ids = set(planned_frame["contract_id"].astype(str)) | {
        item.contract_id for item in session_contracts
    }
    bar_store = _load_contract_bar_store(records, contract_ids)
    features = _build_market_feature_frame(full_decisions, session_contracts, bar_store)
    features = _append_carry(features, paths["daily_curve"])
    features = _append_cftc(features, paths["cftc"], decisions)
    features = _append_cbr(features, paths["cbr"], decisions)
    features = _append_regime(features)
    spec = pd.read_parquet(paths["spec_proxy"])
    spec["session_date"] = pd.to_datetime(spec["session_date"], errors="raise").dt.date
    if len(features) != len(decisions) * len(ASSETS):
        raise RuntimeError("feature frame is not exact calendar x four assets")
    return CorridorSourceBundle(
        protocol=protocol,
        source_paths=paths,
        decisions=decisions,
        features=features,
        planned_contracts=planned_frame,
        active_map=active_whitelist,
        spec_proxy=spec,
        bar_store=bar_store,
        raw_tree_bundle_sha256=tree.child_bundle_sha256,
    )


@dataclass(frozen=True, slots=True)
class SynchronizedIntradayArrays:
    """Same-timestamp BR/MIX/RI/SI tensor with explicit input/execution masks."""

    decision_times_ns: np.ndarray
    execution_open_times_ns: np.ndarray
    asset_ids: tuple[str, ...]
    feature_names: tuple[str, ...]
    features: np.ndarray
    feature_mask: np.ndarray
    asset_mask: np.ndarray
    contract_ids: np.ndarray
    execution_ohlcv: np.ndarray
    execution_mask: np.ndarray


def build_synchronized_intraday_arrays(
    bars: pd.DataFrame,
    planned_contracts: pd.DataFrame,
    *,
    start: date,
    end: date,
) -> SynchronizedIntradayArrays:
    """Create target-free features through completed bar ``t`` and factual bar ``t+1``.

    The returned feature cube is ``[timestamp, asset, feature]`` in exact ``ASSETS``
    order.  NaNs are preserved and every consumer must use both masks.
    """
    if not start <= end < date(2026, 1, 1):
        raise ValueError("intraday interval must remain inside development history")
    required_bars = {
        "timestamp",
        "asset",
        "contract_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if not required_bars.issubset(bars.columns):
        raise ValueError("bars are missing synchronized-loader columns")
    plan = planned_contracts[["decision_date", "asset", "contract_id"]].copy()
    plan["local_date"] = pd.to_datetime(plan["decision_date"]).dt.date
    working = bars.copy()
    working["timestamp"] = pd.to_datetime(working["timestamp"], errors="raise", utc=True)
    working["local_date"] = working["timestamp"].dt.tz_convert(MOSCOW).dt.date
    working = working[(working["local_date"] >= start) & (working["local_date"] <= end)]
    working = working.merge(
        plan,
        on=["local_date", "asset", "contract_id"],
        how="inner",
        validate="many_to_one",
    )
    timestamps = np.sort(working["timestamp"].drop_duplicates().astype("int64").to_numpy())
    if timestamps.size == 0:
        raise ValueError("no synchronized intraday timestamps in requested interval")
    feature_names = (
        "log_return_1",
        "log_return_3",
        "realized_volatility_6",
        "realized_volatility_36",
        "log_volume",
        "bar_range_fraction",
        "close_location",
        "time_sin",
        "time_cos",
    )
    feature_cube = np.full((len(timestamps), len(ASSETS), len(feature_names)), np.nan)
    contract_cube = np.full((len(timestamps), len(ASSETS)), "", dtype="U128")
    execution = np.full((len(timestamps), len(ASSETS), 5), np.nan)
    asset_mask = np.zeros((len(timestamps), len(ASSETS)), dtype=bool)
    execution_mask = np.zeros((len(timestamps), len(ASSETS)), dtype=bool)
    timestamp_index = pd.Index(timestamps)
    for asset_index, asset in enumerate(ASSETS):
        subset = working[working["asset"] == asset].sort_values("timestamp", kind="stable")
        if subset.duplicated("timestamp").any():
            raise ValueError(f"active synchronized bars duplicate timestamp for {asset}")
        series = subset.set_index(subset["timestamp"].astype("int64")).reindex(timestamp_index)
        close_values = series["close"].astype(float)
        log_close = np.log(close_values)
        returns = log_close.diff()
        minutes = pd.to_datetime(timestamps, utc=True).tz_convert(MOSCOW)
        minute_of_day = minutes.hour * 60 + minutes.minute
        values = np.column_stack(
            [
                returns.to_numpy(),
                log_close.diff(3).to_numpy(),
                returns.rolling(6, min_periods=6).std(ddof=0).to_numpy(),
                returns.rolling(36, min_periods=36).std(ddof=0).to_numpy(),
                np.log1p(series["volume"].astype(float)).to_numpy(),
                ((series["high"] - series["low"]) / series["close"]).to_numpy(),
                (
                    (series["close"] - series["low"])
                    / (series["high"] - series["low"]).replace(0.0, np.nan)
                ).to_numpy(),
                np.sin(2.0 * pi * minute_of_day / 1440.0),
                np.cos(2.0 * pi * minute_of_day / 1440.0),
            ]
        )
        present = series["close"].notna().to_numpy()
        feature_cube[:, asset_index, :] = values
        asset_mask[:, asset_index] = present
        feature_mask = np.isfinite(values) & present[:, None]
        raw_contract = series["contract_id"].fillna("").astype(str).to_numpy(dtype="U128")
        contract_cube[:, asset_index] = raw_contract
        next_exact = np.r_[np.diff(timestamps) == 600_000_000_000, False]
        same_contract = np.r_[raw_contract[:-1] == raw_contract[1:], False]
        next_present = np.r_[present[1:], False]
        valid_next = present & next_present & next_exact & same_contract
        next_ohlcv = series[["open", "high", "low", "close", "volume"]].shift(-1).to_numpy()
        execution[:, asset_index, :] = np.where(valid_next[:, None], next_ohlcv, np.nan)
        execution_mask[:, asset_index] = valid_next
        if asset_index == 0:
            complete_feature_mask = np.zeros_like(feature_cube, dtype=bool)
        complete_feature_mask[:, asset_index, :] = feature_mask
    return SynchronizedIntradayArrays(
        decision_times_ns=timestamps + 600_000_000_000,
        execution_open_times_ns=timestamps + 600_000_000_000,
        asset_ids=ASSETS,
        feature_names=feature_names,
        features=feature_cube,
        feature_mask=complete_feature_mask,
        asset_mask=asset_mask,
        contract_ids=contract_cube,
        execution_ohlcv=execution,
        execution_mask=execution_mask,
    )


__all__ = [
    "ASSETS",
    "ContractBarStore",
    "CorridorSourceBundle",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CONFIG_SHA256",
    "SynchronizedIntradayArrays",
    "build_synchronized_intraday_arrays",
    "load_corridor_source_bundle",
    "load_protocol",
    "sha256_file",
    "verify_protocol_sources",
]
