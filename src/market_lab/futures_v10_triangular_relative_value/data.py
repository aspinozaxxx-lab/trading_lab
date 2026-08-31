"""Verified pre-2026 data assembly for the sealed V10 triangular experiment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from .core import PROTECTED_FROM, TEN_MINUTES

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v10_triangular_relative_value.yaml"
)
CONFIG_SHA256: Final[str] = (
    "4ff5c4cb84e5ecd608d69f5673a0e8af6e4f8103cea8f9cb348530e525e6103c"
)
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
ASSETS: Final[tuple[str, ...]] = ("RI", "MIX", "SI")
SOURCE_ASSETS: Final[dict[str, str]] = {"RTS": "RI", "MIX": "MIX", "Si": "SI"}


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError(f"manifest must be an object: {path}")
    return payload


def _resolve_data_path(relative: str) -> Path:
    data_root = (PROJECT_ROOT / "data").resolve()
    path = (data_root / relative).resolve()
    if not path.is_relative_to(data_root):
        raise ValueError(f"manifest path escapes the data root: {relative}")
    return path


def load_protocol() -> dict[str, Any]:
    if sha256_file(CONFIG_PATH) != CONFIG_SHA256:
        raise ValueError("sealed V10 protocol byte drift")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V10 protocol must be a mapping")
    if (
        protocol.get("protocol_id") != "futures_v10_triangular_relative_value_v1"
        or protocol.get("status") != "sealed_before_any_v10_outcome_read"
        or protocol.get("frozen_before_development_outcome_read") is not True
        or str(protocol["boundaries"]["protected_from"]) != "2026-01-01"
    ):
        raise ValueError("sealed V10 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class RawArtifact:
    path: str
    sha256: str
    asset: str
    rows: int


@dataclass(frozen=True, slots=True)
class LoadedPanel:
    panel: pd.DataFrame
    raw_artifacts: tuple[RawArtifact, ...]
    source_hashes: dict[str, str]
    counts: dict[str, int]


def _verified_raw_artifacts() -> tuple[RawArtifact, ...]:
    if sha256_file(TOP_MANIFEST) != TOP_MANIFEST_SHA256:
        raise ValueError("pre-2026 top 10m manifest byte drift")
    top = _read_json(TOP_MANIFEST)
    if (
        top.get("requested_end") != "2025-12-31"
        or top.get("protected_from") != "2026-01-01"
        or top.get("research_status") != "development_only_holdout_untouched"
    ):
        raise ValueError("top manifest does not prove the protected boundary")
    records: list[RawArtifact] = []
    seen: set[str] = set()
    for asset_record in top.get("assets", []):
        if not isinstance(asset_record, dict):
            raise TypeError("malformed top-level asset record")
        source_asset = str(asset_record["asset_code"])
        if source_asset not in SOURCE_ASSETS:
            continue
        asset = SOURCE_ASSETS[source_asset]
        seen.add(asset)
        asset_manifest_path = _resolve_data_path(str(asset_record["path"]))
        if sha256_file(asset_manifest_path) != str(asset_record["sha256"]):
            raise ValueError(f"asset manifest byte drift: {source_asset}")
        asset_manifest = _read_json(asset_manifest_path)
        if asset_manifest.get("requested_end") != "2025-12-31":
            raise ValueError(f"asset manifest reaches protected data: {source_asset}")
        for segment_record in asset_manifest.get("segment_manifests", []):
            if not isinstance(segment_record, dict):
                raise TypeError("malformed segment manifest record")
            rows = int(segment_record.get("rows", 0))
            if rows == 0:
                continue
            segment_manifest_path = _resolve_data_path(str(segment_record["path"]))
            if sha256_file(segment_manifest_path) != str(segment_record["sha256"]):
                raise ValueError(f"segment manifest byte drift: {segment_manifest_path.name}")
            segment = _read_json(segment_manifest_path)
            if segment.get("status") != "complete":
                raise ValueError(f"incomplete segment: {segment_manifest_path.name}")
            parquet_record = segment.get("artifacts", {}).get("parquet", {})
            if not isinstance(parquet_record, dict) or "path" not in parquet_record:
                raise ValueError(f"segment parquet declaration absent: {segment_manifest_path}")
            parquet_path = _resolve_data_path(str(parquet_record["path"]))
            expected = str(parquet_record["sha256"])
            if sha256_file(parquet_path) != expected:
                raise ValueError(f"segment parquet byte drift: {parquet_path.name}")
            records.append(
                RawArtifact(
                    path=str(parquet_path),
                    sha256=expected,
                    asset=asset,
                    rows=int(parquet_record.get("rows", rows)),
                )
            )
    if seen != set(ASSETS):
        raise ValueError("manifest does not contain the exact V10 source universe")
    return tuple(records)


def _load_active_plan() -> pd.DataFrame:
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
    frame["local_date"] = pd.to_datetime(frame["decision_date"], errors="raise").dt.normalize()
    observed = pd.to_datetime(frame["observed_through"], errors="coerce").dt.normalize()
    frame["asset"] = frame["asset_code"].astype(str).str.upper().replace({"RTS": "RI"})
    usable = (
        observed.eq(frame["local_date"])
        & frame["plan_tradable"].fillna(False).astype(bool)
        & frame["execution_open_available"].fillna(False).astype(bool)
        & frame["contract_id"].notna()
        & frame["asset"].isin(ASSETS)
    )
    plan = frame.loc[usable, ["local_date", "asset", "contract_id"]].copy()
    plan["contract_id"] = plan["contract_id"].astype(str)
    if plan.duplicated(["local_date", "asset"]).any():
        raise ValueError("active plan duplicates local date and asset")
    if plan.empty or plan["local_date"].dt.date.max() >= date(2026, 1, 1):
        raise ValueError("active plan is empty or touches protected 2026")
    return plan


def _load_active_bars(
    plan: pd.DataFrame, artifacts: tuple[RawArtifact, ...]
) -> tuple[pd.DataFrame, set[str], dict[str, int]]:
    contract_sets = {
        asset: set(plan.loc[plan["asset"].eq(asset), "contract_id"].astype(str))
        for asset in ASSETS
    }
    columns = [
        "timestamp",
        "end_timestamp",
        "canonical_contract_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    frames: list[pd.DataFrame] = []
    used_hashes: set[str] = set()
    for artifact in artifacts:
        part = pd.read_parquet(artifact.path, columns=columns)
        selected = part["canonical_contract_id"].astype(str).isin(contract_sets[artifact.asset])
        part = part.loc[selected].copy()
        if part.empty:
            continue
        part["asset"] = artifact.asset
        part["contract_id"] = part["canonical_contract_id"].astype(str)
        frames.append(part)
        used_hashes.add(artifact.sha256)
    if not frames:
        raise ValueError("no V10 active intraday bars were found")
    bars = pd.concat(frames, ignore_index=True)
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], errors="raise", utc=True)
    bars["end_timestamp"] = pd.to_datetime(bars["end_timestamp"], errors="raise", utc=True)
    if (
        bars["timestamp"].ge(PROTECTED_FROM).any()
        or bars["end_timestamp"].gt(PROTECTED_FROM).any()
    ):
        raise ValueError("raw V10 bars touch protected 2026")
    scheduled_end = bars["timestamp"] + TEN_MINUTES
    factual_end_in_bucket = bars["end_timestamp"].gt(bars["timestamp"]) & bars[
        "end_timestamp"
    ].le(scheduled_end)
    excluded_out_of_bucket_end = int((~factual_end_in_bucket).sum())
    bars = bars.loc[factual_end_in_bucket].copy()
    if bars.empty:
        raise ValueError("no valid ten-minute V10 buckets remain")
    # ISS `end` is the timestamp of the final factual trade in the bucket, not
    # the scheduled decision boundary.  Keep both without inventing a trade.
    bars = bars.rename(columns={"end_timestamp": "source_end_timestamp"})
    bars["end_timestamp"] = bars["timestamp"] + TEN_MINUTES
    bars["local_date"] = (
        bars["end_timestamp"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    )
    bars = bars.merge(
        plan,
        on=["local_date", "asset", "contract_id"],
        how="inner",
        validate="many_to_one",
    )
    if bars.duplicated(["timestamp", "asset"]).any():
        raise ValueError("active V10 bars duplicate timestamp and asset")
    numeric = ["open", "high", "low", "close", "volume"]
    bars[numeric] = bars[numeric].apply(pd.to_numeric, errors="coerce")
    valid = (
        bars[numeric].notna().all(axis=1)
        & bars["open"].gt(0.0)
        & bars["close"].gt(0.0)
        & bars["low"].gt(0.0)
        & bars["high"].ge(bars[["open", "close"]].max(axis=1))
        & bars["low"].le(bars[["open", "close"]].min(axis=1))
        & bars["volume"].ge(0.0)
    )
    if not valid.all():
        raise ValueError("active V10 source contains invalid OHLCV")
    return (
        bars.sort_values(["timestamp", "asset"], kind="stable"),
        used_hashes,
        {"excluded_out_of_bucket_source_end_bars": excluded_out_of_bucket_end},
    )


def _build_common_panel(bars: pd.DataFrame) -> pd.DataFrame:
    merge_keys = ["timestamp", "end_timestamp", "local_date"]
    values = [
        "source_end_timestamp",
        "contract_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    common: pd.DataFrame | None = None
    for asset in ASSETS:
        subset = bars.loc[bars["asset"].eq(asset), merge_keys + values].copy()
        subset = subset.rename(columns={field: f"{asset}_{field}" for field in values})
        if common is None:
            common = subset
        else:
            common = common.merge(subset, on=merge_keys, how="inner", validate="one_to_one")
    if common is None or common.empty:
        raise ValueError("V10 has no exact common RI/MIX/SI bars")
    common = common.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if common["timestamp"].duplicated().any():
        raise ValueError("common V10 panel duplicates timestamps")
    return common


def _join_specs(panel: pd.DataFrame) -> pd.DataFrame:
    if sha256_file(SPEC_PROXY) != SPEC_PROXY_SHA256:
        raise ValueError("spec proxy byte drift")
    columns = [
        "session_date",
        "contract_id",
        "asset_symbol",
        "sizing_observed_session_date",
        "sizing_point_value",
        "sizing_notional",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "sizing_usable",
        "approximate",
        "research_only",
        "historical_exchange_exact",
        "broker_exact",
    ]
    spec = pd.read_parquet(SPEC_PROXY, columns=columns)
    spec["local_date"] = pd.to_datetime(spec["session_date"], errors="raise").dt.normalize()
    spec["asset"] = spec["asset_symbol"].astype(str).str.upper().replace({"RTS": "RI"})
    spec["contract_id"] = spec["contract_id"].astype(str)
    spec = spec.loc[spec["asset"].isin(ASSETS)].copy()
    if spec.duplicated(["local_date", "asset", "contract_id"]).any():
        raise ValueError("spec proxy duplicates contract/session rows")
    flags_valid = (
        spec["approximate"].astype("boolean").fillna(False)
        & spec["research_only"].astype("boolean").fillna(False)
        & ~spec["historical_exchange_exact"].astype("boolean").fillna(True)
        & ~spec["broker_exact"].astype("boolean").fillna(True)
    )
    if not flags_valid.all():
        raise ValueError("spec proxy research limitations were weakened")
    output = panel.copy()
    value_columns = [
        "sizing_observed_session_date",
        "sizing_point_value",
        "sizing_notional",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "sizing_usable",
    ]
    for asset in ASSETS:
        selected = spec.loc[
            spec["asset"].eq(asset), ["local_date", "contract_id", *value_columns]
        ].rename(
            columns={
                "contract_id": f"{asset}_contract_id",
                **{field: f"{asset}_{field}" for field in value_columns},
            }
        )
        output = output.merge(
            selected,
            on=["local_date", f"{asset}_contract_id"],
            how="left",
            validate="many_to_one",
        )
        usable_column = f"{asset}_sizing_usable"
        output[usable_column] = output[usable_column].astype("boolean").fillna(False)
        observed_column = f"{asset}_sizing_observed_session_date"
        observed = pd.to_datetime(output[observed_column], errors="coerce").dt.normalize()
        causal = observed.lt(output["local_date"])
        if (output[usable_column] & ~causal.fillna(False)).any():
            raise ValueError(f"{asset} sizing proxy is not strictly lagged")
    return output


def load_verified_panel() -> LoadedPanel:
    """Verify the manifest chain and return exact common active bars with lagged specs."""

    load_protocol()
    artifacts = _verified_raw_artifacts()
    plan = _load_active_plan()
    bars, used_hashes, filter_counts = _load_active_bars(plan, artifacts)
    common = _join_specs(_build_common_panel(bars))
    counts = {
        "active_plan_rows": int(len(plan)),
        "active_bar_rows": int(len(bars)),
        "common_bar_rows": int(len(common)),
        "raw_artifacts_verified": int(len(artifacts)),
        "raw_artifacts_used": int(sum(item.sha256 in used_hashes for item in artifacts)),
        **filter_counts,
    }
    return LoadedPanel(
        panel=common,
        raw_artifacts=tuple(item for item in artifacts if item.sha256 in used_hashes),
        source_hashes={
            "protocol": CONFIG_SHA256,
            "raw_10m_manifest": TOP_MANIFEST_SHA256,
            "active_contract_map": ACTIVE_MAP_SHA256,
            "spec_proxy": SPEC_PROXY_SHA256,
        },
        counts=counts,
    )


__all__ = [
    "ASSETS",
    "CONFIG_PATH",
    "CONFIG_SHA256",
    "LoadedPanel",
    "RawArtifact",
    "load_protocol",
    "load_verified_panel",
    "sha256_file",
]
