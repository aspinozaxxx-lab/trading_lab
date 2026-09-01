"""Sealed V32 curve-regime cross-asset intraday economic experiment."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet
import sklearn
import yaml

from market_lab.futures.curve_regime_intraday import (
    ASSETS,
    MODEL_FULL_MLP,
    MODEL_FULL_RIDGE,
    MODEL_IDS,
    MODEL_MARKET_MLP,
    FeatureSettings,
    LedgerSettings,
    ModelSettings,
    RiskSettings,
    build_learning_frame,
    build_weight_targets,
    run_monthly_walk_forward,
    simulate_next_open_portfolio,
    source_feature_columns,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v32_curve_regime_intraday.yaml"
SIDECAR_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v32_curve_regime_intraday.sha256"
CORE_MODULE_PATH: Final[Path] = PROJECT_ROOT / "src/market_lab/futures/curve_regime_intraday.py"
RUNNER_MODULE_PATH: Final[Path] = Path(__file__).resolve()
PROTECTED_FROM_DATE: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSET_ALIASES: Final[dict[str, str]] = {
    "SI": "SI",
    "RI": "RI",
    "RTS": "RI",
    "BR": "BR",
    "MIX": "MIX",
}
SOURCE_ASSET_ALIASES: Final[dict[str, str]] = {"Si": "SI", "RTS": "RI", "BR": "BR", "MIX": "MIX"}


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value) and not isinstance(value, (str, bytes)):
        return None
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def _sidecar_hash() -> str:
    text = SIDECAR_PATH.read_text(encoding="utf-8-sig").strip()
    token = text.split()[0].lower() if text else ""
    if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
        raise ValueError("V32 config sidecar is malformed")
    return token


def _repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"V32 input path must be repo-relative: {relative}")
    return PROJECT_ROOT / candidate


def _data_relative_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"manifest data path is unsafe: {relative}")
    return PROJECT_ROOT / "data" / candidate


def load_protocol() -> dict[str, Any]:
    expected = _sidecar_hash()
    actual = sha256_file(CONFIG_PATH)
    if actual != expected:
        raise ValueError("sealed V32 protocol byte drift")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V32 protocol must be a mapping")
    if (
        protocol.get("protocol_id") != "futures_v32_curve_regime_intraday_cross_asset_v1"
        or protocol.get("status") != "sealed_before_first_v32_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["boundaries"]["protected_from"]) != "2026-01-01"
    ):
        raise ValueError("V32 protocol invariants were weakened")
    implementation = protocol["implementation"]
    if sha256_file(CORE_MODULE_PATH) != str(implementation["core_sha256"]):
        raise ValueError("V32 core implementation byte drift")
    if sha256_file(RUNNER_MODULE_PATH) != str(implementation["runner_sha256"]):
        raise ValueError("V32 runner implementation byte drift")
    return protocol


def _verify_file(record: dict[str, Any], label: str) -> Path:
    path = _repo_path(str(record["path"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} byte count drift")
    if sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"{label} SHA-256 drift")
    expected_rows = record.get("rows")
    if (
        expected_rows is not None
        and path.suffix.lower() == ".parquet"
        and parquet.ParquetFile(path).metadata.num_rows != int(expected_rows)
    ):
        raise ValueError(f"{label} row count drift")
    return path


def _verified_raw_artifacts(protocol: dict[str, Any]) -> list[dict[str, object]]:
    top_record = protocol["inputs"]["intraday_top_manifest"]
    top_path = _verify_file(top_record, "intraday top manifest")
    top = _read_json(top_path)
    if (
        top.get("requested_end") != "2025-12-31"
        or top.get("protected_from") != "2026-01-01"
        or int(top.get("totals", {}).get("rows", -1)) != int(top_record["declared_market_rows"])
    ):
        raise ValueError("intraday top manifest boundary/count drift")
    records: list[dict[str, object]] = []
    seen_assets: set[str] = set()
    for asset_record in top.get("assets", []):
        if not isinstance(asset_record, dict):
            raise TypeError("intraday asset record is malformed")
        source_asset = str(asset_record["asset_code"])
        if source_asset not in SOURCE_ASSET_ALIASES:
            continue
        asset = SOURCE_ASSET_ALIASES[source_asset]
        seen_assets.add(asset)
        asset_manifest_path = _data_relative_path(str(asset_record["path"]))
        if sha256_file(asset_manifest_path) != str(asset_record["sha256"]):
            raise ValueError(f"intraday asset manifest drift: {source_asset}")
        asset_manifest = _read_json(asset_manifest_path)
        if asset_manifest.get("requested_end") != "2025-12-31":
            raise ValueError(f"intraday asset boundary drift: {source_asset}")
        for segment_record in asset_manifest.get("segment_manifests", []):
            if not isinstance(segment_record, dict):
                raise TypeError("intraday segment record is malformed")
            if int(segment_record.get("rows", 0)) == 0:
                continue
            segment_manifest_path = _data_relative_path(str(segment_record["path"]))
            if sha256_file(segment_manifest_path) != str(segment_record["sha256"]):
                raise ValueError(f"intraday segment manifest drift: {segment_manifest_path.name}")
            segment = _read_json(segment_manifest_path)
            if segment.get("status") != "complete":
                raise ValueError(f"intraday segment incomplete: {segment_manifest_path.name}")
            parquet_record = segment.get("artifacts", {}).get("parquet")
            if not isinstance(parquet_record, dict):
                raise ValueError("intraday parquet record is missing")
            path = _data_relative_path(str(parquet_record["path"]))
            expected_hash = str(parquet_record["sha256"])
            if sha256_file(path) != expected_hash:
                raise ValueError(f"intraday parquet drift: {path.name}")
            if parquet.ParquetFile(path).metadata.num_rows != int(parquet_record["rows"]):
                raise ValueError(f"intraday parquet row drift: {path.name}")
            records.append(
                {
                    "asset": asset,
                    "path": path,
                    "sha256": expected_hash,
                    "rows": int(parquet_record["rows"]),
                }
            )
    if seen_assets != set(ASSETS):
        raise ValueError("intraday manifest does not contain the exact four assets")
    return records


def _load_causal_active_plan(protocol: dict[str, Any]) -> pd.DataFrame:
    path = _verify_file(protocol["inputs"]["active_contract_map"], "active contract map")
    columns = [
        "effective_date",
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "plan_tradable",
    ]
    frame = pd.read_parquet(path, columns=columns)
    frame["local_date"] = pd.to_datetime(frame["effective_date"], errors="raise").dt.normalize()
    decision = pd.to_datetime(frame["decision_date"], errors="raise").dt.normalize()
    observed = pd.to_datetime(frame["observed_through"], errors="raise").dt.normalize()
    frame["asset"] = frame["asset_code"].astype(str).str.upper().map(ASSET_ALIASES)
    usable = (
        frame["asset"].isin(ASSETS)
        & frame["plan_tradable"].fillna(False).astype(bool)
        & frame["contract_id"].notna()
        & observed.le(decision)
        & decision.lt(frame["local_date"])
    )
    plan = frame.loc[usable, ["local_date", "asset", "contract_id"]].copy()
    plan["contract_id"] = plan["contract_id"].astype(str)
    if plan.duplicated(["local_date", "asset"]).any():
        raise ValueError("causal active plan duplicates local date/asset")
    if plan.empty or plan["local_date"].max() >= PROTECTED_FROM_DATE:
        raise ValueError("causal active plan is empty or touches protected 2026")
    return plan.sort_values(["local_date", "asset"], kind="stable").reset_index(drop=True)


def _load_active_bars(
    plan: pd.DataFrame,
    artifacts: list[dict[str, object]],
    *,
    metadata_only: bool,
) -> pd.DataFrame:
    contract_sets = {
        asset: set(plan.loc[plan["asset"].eq(asset), "contract_id"].astype(str)) for asset in ASSETS
    }
    columns = ["timestamp", "end_timestamp", "canonical_contract_id"]
    if not metadata_only:
        columns.extend(("open", "high", "low", "close", "volume"))
    frames: list[pd.DataFrame] = []
    for artifact in artifacts:
        part = pd.read_parquet(Path(str(artifact["path"])), columns=columns)
        asset = str(artifact["asset"])
        part = part.loc[part["canonical_contract_id"].astype(str).isin(contract_sets[asset])].copy()
        if part.empty:
            continue
        part["asset"] = asset
        part["contract_id"] = part["canonical_contract_id"].astype(str)
        part["timestamp"] = pd.to_datetime(part["timestamp"], errors="raise", utc=True)
        factual_end = pd.to_datetime(part["end_timestamp"], errors="raise", utc=True)
        scheduled_end = part["timestamp"] + pd.Timedelta(minutes=10)
        part = part.loc[factual_end.gt(part["timestamp"]) & factual_end.le(scheduled_end)].copy()
        part["source_end_timestamp"] = factual_end.loc[part.index]
        part["local_date"] = (
            scheduled_end.loc[part.index]
            .dt.tz_convert("Europe/Moscow")
            .dt.tz_localize(None)
            .dt.normalize()
        )
        part = part.merge(plan, on=["local_date", "asset", "contract_id"], validate="many_to_one")
        frames.append(part)
    if not frames:
        raise ValueError("no active intraday bars found")
    bars = pd.concat(frames, ignore_index=True)
    if bars.duplicated(["timestamp", "asset"]).any():
        duplicates = bars.loc[bars.duplicated(["timestamp", "asset"], keep=False)]
        if duplicates.duplicated(["timestamp", "asset", "contract_id"], keep=False).any():
            raise ValueError("active intraday source duplicates timestamp/asset")
        raise ValueError("multiple active contracts were admitted for timestamp/asset")
    if bars["timestamp"].ge(pd.Timestamp("2026-01-01", tz="UTC")).any():
        raise ValueError("active intraday bars touch protected 2026")
    if not metadata_only:
        numeric = ["open", "high", "low", "close", "volume"]
        bars[numeric] = bars[numeric].apply(pd.to_numeric, errors="coerce")
        valid = (
            bars[numeric].notna().all(axis=1)
            & bars["open"].gt(0.0)
            & bars["high"].ge(bars[["open", "close"]].max(axis=1))
            & bars["low"].gt(0.0)
            & bars["low"].le(bars[["open", "close"]].min(axis=1))
            & bars["volume"].ge(0.0)
        )
        if not valid.all():
            raise ValueError("active intraday source contains invalid OHLCV")
    return bars.sort_values(["timestamp", "asset"], kind="stable").reset_index(drop=True)


def _build_common_panel(bars: pd.DataFrame, *, metadata_only: bool) -> pd.DataFrame:
    keys = ["timestamp", "local_date"]
    values = ["contract_id"]
    if not metadata_only:
        values.extend(("source_end_timestamp", "open", "high", "low", "close", "volume"))
    common: pd.DataFrame | None = None
    for asset in ASSETS:
        selected = bars.loc[bars["asset"].eq(asset), [*keys, *values]].rename(
            columns={field: f"{asset}_{field}" for field in values}
        )
        common = (
            selected
            if common is None
            else common.merge(selected, on=keys, how="inner", validate="one_to_one")
        )
    if common is None or common.empty:
        raise ValueError("there are no exact common four-asset intraday bars")
    return common.sort_values("timestamp", kind="stable").reset_index(drop=True)


def _join_specs(
    common: pd.DataFrame,
    protocol: dict[str, Any],
) -> pd.DataFrame:
    path = _verify_file(protocol["inputs"]["spec_proxy"], "spec proxy")
    columns = [
        "session_date",
        "contract_id",
        "asset_symbol",
        "sizing_observed_session_date",
        "sizing_point_value",
        "sizing_notional",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "modeled_initial_margin",
        "sizing_usable",
        "approximate",
        "research_only",
        "historical_exchange_exact",
        "broker_exact",
    ]
    spec = pd.read_parquet(path, columns=columns)
    spec["local_date"] = pd.to_datetime(spec["session_date"], errors="raise").dt.normalize()
    spec["asset"] = spec["asset_symbol"].astype(str).str.upper().map(ASSET_ALIASES)
    spec["contract_id"] = spec["contract_id"].astype(str)
    spec = spec.loc[spec["asset"].isin(ASSETS)].copy()
    if spec.duplicated(["local_date", "asset", "contract_id"]).any():
        raise ValueError("spec proxy duplicates local date/asset/contract")
    limitations = (
        spec["approximate"].astype("boolean").fillna(False)
        & spec["research_only"].astype("boolean").fillna(False)
        & ~spec["historical_exchange_exact"].astype("boolean").fillna(True)
        & ~spec["broker_exact"].astype("boolean").fillna(True)
    )
    if not limitations.all():
        raise ValueError("spec proxy research limitations were weakened")
    output = common.copy()
    value_columns = [
        "sizing_observed_session_date",
        "sizing_point_value",
        "sizing_notional",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "modeled_initial_margin",
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
        usable = output[f"{asset}_sizing_usable"].astype("boolean").fillna(False)
        observed = pd.to_datetime(
            output[f"{asset}_sizing_observed_session_date"], errors="coerce"
        ).dt.normalize()
        if (usable & ~observed.lt(output["local_date"]).fillna(False)).any():
            raise ValueError(f"{asset} sizing proxy is not strictly prior")
    return output


def _load_curve_context(protocol: dict[str, Any], *, metadata_only: bool) -> pd.DataFrame:
    manifest_path = _verify_file(protocol["inputs"]["curve_manifest"], "curve manifest")
    manifest = _read_json(manifest_path)
    information = manifest.get("information_contract", {})
    if (
        information.get("settlement_price_open_loaded_or_used") is not False
        or information.get("contains_returns_targets_labels_or_pnl") is not False
        or int(manifest.get("counts", {}).get("events", -1)) != 686
    ):
        raise ValueError("curve source information contract drift")
    path = _verify_file(protocol["inputs"]["curve_wide_context"], "curve wide context")
    columns = ["event_at", "available_at"]
    if not metadata_only:
        columns.extend(source_feature_columns())
    context = pd.read_parquet(path, columns=columns)
    context["event_at"] = pd.to_datetime(context["event_at"], errors="raise", utc=True)
    context["available_at"] = pd.to_datetime(context["available_at"], errors="raise", utc=True)
    if (
        context["event_at"].duplicated().any()
        or context["available_at"].lt(context["event_at"]).any()
    ):
        raise ValueError("curve event identity/availability drift")
    if context["available_at"].ge(pd.Timestamp("2026-01-01", tz="UTC")).any():
        raise ValueError("curve source touches protected 2026")
    return context.sort_values("event_at", kind="stable").reset_index(drop=True)


def _verify_spec_boundary(protocol: dict[str, Any]) -> None:
    """Verify the proxy identity and date boundary before any economic field is read."""

    path = _verify_file(protocol["inputs"]["spec_proxy"], "spec proxy")
    dates = pd.read_parquet(path, columns=["session_date"])
    session_date = pd.to_datetime(dates["session_date"], errors="raise").dt.normalize()
    if session_date.empty or session_date.max() >= PROTECTED_FROM_DATE:
        raise ValueError("spec proxy is empty or touches protected 2026")


def metadata_preflight(protocol: dict[str, Any]) -> dict[str, Any]:
    """Inspect only hashes, schemas, timestamps, contracts and source availability."""

    artifacts = _verified_raw_artifacts(protocol)
    plan = _load_causal_active_plan(protocol)
    bars = _load_active_bars(plan, artifacts, metadata_only=True)
    common = _build_common_panel(bars, metadata_only=True)
    context = _load_curve_context(protocol, metadata_only=True)
    _verify_spec_boundary(protocol)
    timestamps = pd.to_datetime(common["timestamp"], utc=True)
    exact = pd.Series(True, index=common.index, dtype=bool)
    for offset in range(1, 8):
        exact &= timestamps.shift(-offset).eq(timestamps + pd.Timedelta(minutes=10 * offset))
    same_contract = pd.Series(True, index=common.index, dtype=bool)
    for asset in ASSETS:
        contract = common[f"{asset}_contract_id"].astype(str)
        for offset in range(1, 8):
            same_contract &= contract.shift(-offset).eq(contract)
    decisions = pd.DataFrame(
        {
            "decision_at": timestamps + pd.Timedelta(minutes=10),
            "structural": exact & same_contract,
        }
    )
    decisions["local_date"] = (
        decisions["decision_at"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    )
    decisions["local_time"] = decisions["decision_at"].dt.tz_convert("Europe/Moscow").dt.time
    source = context.copy()
    source["local_date"] = (
        source["available_at"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    )
    joined = decisions.merge(
        source[["local_date", "event_at", "available_at"]], on="local_date", how="inner"
    )
    window = (
        joined["structural"]
        & joined["available_at"].le(joined["decision_at"])
        & joined["local_time"].ge(pd.Timestamp("10:10:00").time())
        & joined["local_time"].le(pd.Timestamp("17:30:00").time())
    )
    admitted = joined.loc[window]
    counts = {
        "raw_artifacts_verified": len(artifacts),
        "active_plan_rows": int(len(plan)),
        "active_bar_rows": int(len(bars)),
        "common_four_bars": int(len(common)),
        "curve_events": int(len(context)),
        "events_with_structural_decisions": int(admitted["event_at"].nunique()),
        "events_without_structural_decisions": int(len(context) - admitted["event_at"].nunique()),
        "structural_decisions": int(len(admitted)),
    }
    expected = protocol["pre_outcome_metadata_seal"]
    checks = {
        "active_contract_selected_on_prior_decision_for_effective_date": True,
        "no_price_return_target_label_or_pnl_column_loaded": True,
        "all_four_assets_present": set(bars["asset"]) == set(ASSETS),
        "maximum_timestamp_before_2026": bool(
            timestamps.max() < pd.Timestamp("2026-01-01", tz="UTC")
        ),
        "curve_availability_causal": bool(context["available_at"].ge(context["event_at"]).all()),
        "expected_active_bar_rows": counts["active_bar_rows"] == int(expected["active_bar_rows"]),
        "expected_common_four_bars": counts["common_four_bars"]
        == int(expected["common_four_bars"]),
        "expected_curve_events": counts["curve_events"] == int(expected["curve_events"]),
        "expected_events_with_decisions": counts["events_with_structural_decisions"]
        == int(expected["events_with_structural_decisions"]),
        "expected_structural_decisions": counts["structural_decisions"]
        == int(expected["structural_decisions"]),
    }
    if not all(checks.values()):
        raise ValueError(f"V32 metadata preflight failed: {checks}")
    return {
        "scope": "metadata_only_no_market_values",
        "counts": counts,
        "minimum_common_timestamp": timestamps.min(),
        "maximum_common_timestamp": timestamps.max(),
        "minimum_curve_event": context["event_at"].min(),
        "maximum_curve_event": context["event_at"].max(),
        "checks": checks,
    }


def load_economic_inputs(
    protocol: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    _verify_spec_boundary(protocol)
    artifacts = _verified_raw_artifacts(protocol)
    plan = _load_causal_active_plan(protocol)
    bars = _load_active_bars(plan, artifacts, metadata_only=False)
    common = _join_specs(_build_common_panel(bars, metadata_only=False), protocol)
    context = _load_curve_context(protocol, metadata_only=False)
    provenance = {
        "raw_artifacts_verified": len(artifacts),
        "raw_artifact_rows_declared": int(sum(int(item["rows"]) for item in artifacts)),
        "active_plan_rows": len(plan),
        "active_bar_rows": len(bars),
        "common_four_bars": len(common),
        "curve_events": len(context),
    }
    return common, context, provenance


def _settings(protocol: dict[str, Any]) -> tuple[FeatureSettings, ModelSettings, RiskSettings]:
    feature_payload = dict(protocol["features"]["settings"])
    for key in ("return_lookbacks", "realized_volatility_lookbacks"):
        feature_payload[key] = tuple(feature_payload[key])
    model_payload = dict(protocol["validation_and_model"])
    for key in ("threshold_cost_multiples", "hidden_layers", "seeds"):
        model_payload[key] = tuple(model_payload[key])
    feature = FeatureSettings(**feature_payload)
    model = ModelSettings(**model_payload)
    risk = RiskSettings(**protocol["portfolio"])
    return feature, model, risk


def _scenario_settings(protocol: dict[str, Any], scenario: str) -> LedgerSettings:
    execution = protocol["execution"]
    scenario_record = execution["scenarios"][scenario]
    return LedgerSettings(
        initial_cash=float(execution["initial_cash_rub"]),
        slippage_ticks=int(scenario_record["slippage_ticks"]),
        fee_multiplier=float(scenario_record["fee_multiplier"]),
        signal_participation=float(execution["signal_participation"]),
        factual_participation_cap=float(execution["factual_participation_cap"]),
        maximum_gross=float(protocol["portfolio"]["maximum_gross"]),
        margin_buffer_multiple=float(execution["margin_buffer_multiple"]),
    )


def _promotion(
    protocol: dict[str, Any],
    results: dict[str, dict[str, Any]],
    counts: dict[str, int],
    checks: dict[str, bool],
) -> dict[str, Any]:
    primary = results[f"{MODEL_FULL_MLP}:primary"]
    doubled = results[f"{MODEL_FULL_MLP}:doubled"]
    stress = results[f"{MODEL_FULL_MLP}:stress"]
    market = results[f"{MODEL_MARKET_MLP}:primary"]
    ridge = results[f"{MODEL_FULL_RIDGE}:primary"]
    best_baseline_cagr = max(float(market["cagr"]), float(ridge["cagr"]))
    best_baseline_sharpe = max(
        float(market["annualized_sharpe"]), float(ridge["annualized_sharpe"])
    )
    gates = protocol["promotion_rule"]
    conditions = {
        "all_integrity_and_temporal_checks_true": all(checks.values()),
        "all_primary_cost_ledgers_complete": all(
            bool(results[f"{MODEL_FULL_MLP}:{name}"]["execution_complete"])
            for name in ("primary", "doubled", "stress")
        ),
        "minimum_filled_order_legs": int(primary["filled_order_legs"])
        >= int(gates["minimum_filled_order_legs"]),
        "all_cost_cagr_at_least_20_percent": min(
            float(primary["cagr"]), float(doubled["cagr"]), float(stress["cagr"])
        )
        >= float(gates["minimum_cagr"]),
        "primary_sharpe_at_least_one": float(primary["annualized_sharpe"])
        >= float(gates["minimum_sharpe"]),
        "primary_maximum_drawdown_at_most_25_percent": float(primary["maximum_drawdown"])
        <= float(gates["maximum_drawdown"]),
        "all_three_calendar_segments_positive": int(primary["positive_years"])
        >= int(gates["minimum_positive_calendar_segments"]),
        "incremental_cagr_over_best_market_baseline": float(primary["cagr"])
        >= best_baseline_cagr + float(gates["minimum_cagr_advantage_over_baseline"]),
        "incremental_sharpe_over_best_market_baseline": float(primary["annualized_sharpe"])
        >= best_baseline_sharpe + float(gates["minimum_sharpe_advantage_over_baseline"]),
        "zero_unresolved": int(primary["unresolved_count"]) == 0,
        "coverage_nonempty": counts["prediction_rows"] > 0 and counts["active_primary_signals"] > 0,
    }
    support_20 = bool(all(conditions.values()))
    support_50 = bool(
        support_20
        and min(float(primary["cagr"]), float(doubled["cagr"]), float(stress["cagr"]))
        >= float(gates["aspirational_cagr"])
    )
    return {
        "conditions": conditions,
        "supports_20_percent_cagr": support_20,
        "supports_50_percent_cagr": support_50,
        "verdict": ("ADAPTIVE_LEAD_REQUIRES_NEW_FORWARD_VALIDATION" if support_20 else "NO_GO"),
        "live_trading_allowed": False,
    }


def _report_text(payload: dict[str, Any]) -> str:
    results = payload["results"]
    promotion = payload["promotion"]
    primary = results[f"{MODEL_FULL_MLP}:primary"]
    doubled = results[f"{MODEL_FULL_MLP}:doubled"]
    stress = results[f"{MODEL_FULL_MLP}:stress"]
    market = results[f"{MODEL_MARKET_MLP}:primary"]
    ridge = results[f"{MODEL_FULL_RIDGE}:primary"]

    def result_row(label: str, result: dict[str, Any]) -> str:
        return (
            f"| {label} | {result['cagr']:.4%} | "
            f"{result['annualized_sharpe']:.3f} | "
            f"{result['maximum_drawdown']:.4%} | "
            f"{result['total_return']:.4%} | {result['execution_complete']} |"
        )

    return "\n".join(
        (
            "# V32 curve-regime cross-asset intraday",
            "",
            f"Verdict: **{promotion['verdict']}**. Live trading: **forbidden**.",
            "",
            "The model makes a new decision after every completed ten-minute bucket on an",
            "official coefficient-event day. The full MLP sees all four markets and the",
            "maturity-agnostic MOEX coefficient context; its market-only twin and Ridge are",
            "fixed ablations, not candidates selected on the reported test months.",
            "",
            "| Variant | CAGR | Sharpe | MDD | Total return | Complete |",
            "|---|---:|---:|---:|---:|---|",
            result_row("full MLP primary", primary),
            result_row("full MLP doubled", doubled),
            result_row("full MLP stress", stress),
            result_row("market-only MLP primary", market),
            result_row("full Ridge primary", ridge),
            "",
            f"Primary calendar returns: `{primary['annual_returns']}`.",
            (
                f"Predictions: {payload['counts']['prediction_rows']}; active full-MLP "
                f"signals: {payload['counts']['active_primary_signals']}."
            ),
            (
                f"Filled primary legs: {primary['filled_order_legs']}; costs: "
                f"{primary['total_cost']:.2f} RUB; unresolved: "
                f"{primary['unresolved_count']}."
            ),
            "",
            "This is adaptive development evidence. The MOEX coefficient archive does not",
            "prove original live delivery vintages, and intraday fills/specifications remain",
            "conservative research proxies. A positive result would still require a sealed",
            "forward collector and paper/shadow validation.",
            "",
        )
    )


def _artifact_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix == ".parquet":
        record["rows"] = parquet.ParquetFile(path).metadata.num_rows
    return record


def run_experiment(output_root: Path) -> Path:
    protocol = load_protocol()
    preflight = metadata_preflight(protocol)
    common, context, provenance = load_economic_inputs(protocol)
    feature_settings, model_settings, risk_settings = _settings(protocol)
    learning = build_learning_frame(common, context, feature_settings)
    walk = run_monthly_walk_forward(learning, model_settings)
    if walk.predictions.empty:
        raise ValueError("V32 walk-forward produced no predictions")
    targets: dict[str, pd.DataFrame] = {
        model_id: build_weight_targets(
            walk.predictions, learning, model_id, feature_settings, risk_settings
        )
        for model_id in MODEL_IDS
    }
    simulations: dict[str, Any] = {}
    results: dict[str, dict[str, Any]] = {}
    for model_id in MODEL_IDS:
        scenario_names = (
            ("primary", "doubled", "stress") if model_id == MODEL_FULL_MLP else ("primary",)
        )
        for scenario in scenario_names:
            key = f"{model_id}:{scenario}"
            simulation = simulate_next_open_portfolio(
                common,
                targets[model_id],
                _scenario_settings(protocol, scenario),
            )
            simulations[key] = simulation
            results[key] = dict(simulation.metrics)
    fold_causality = True
    if not walk.folds.empty and "status" in walk.folds:
        predicted_folds = walk.folds.loc[
            walk.folds["status"].isin(["predicted", "sleep_calibration_gate"])
        ]
        for row in predicted_folds.to_dict("records"):
            if row.get("core_max_target_end_at") is None:
                continue
            fold_causality &= bool(
                pd.Timestamp(row["core_max_target_end_at"])
                < pd.Timestamp(row["calibration_min_decision_at"])
                and pd.Timestamp(row["calibration_max_target_end_at"])
                < pd.Timestamp(row["test_min_decision_at"])
            )
    checks = {
        "metadata_preflight_all_true": all(preflight["checks"].values()),
        "learning_decisions_after_source_availability": bool(
            learning["decision_at"].ge(learning["source_available_at"]).all()
        ),
        "learning_target_ends_before_2026": bool(
            learning["target_end_at"].lt(pd.Timestamp("2026-01-01", tz="UTC")).all()
        ),
        "monthly_core_calibration_test_are_purged": fold_causality,
        "all_three_model_ids_reported": set(walk.predictions["model_id"]) == set(MODEL_IDS),
        "primary_targets_next_open_only": bool(
            targets[MODEL_FULL_MLP]["entry_at"].ge(targets[MODEL_FULL_MLP]["decision_at"]).all()
        ),
        "primary_weight_gross_within_cap": bool(
            targets[MODEL_FULL_MLP]
            .groupby("entry_at")["target_weight"]
            .apply(lambda values: values.abs().sum())
            .le(risk_settings.maximum_gross + 1e-9)
            .all()
        ),
        "no_live_trading_claim": protocol["live_trading_allowed"] is False,
        "source_original_delivery_vintage_not_claimed": protocol["source_limitations"][
            "original_live_delivery_vintage_proved"
        ]
        is False,
    }
    counts = {
        **{key: int(value) for key, value in provenance.items()},
        "learning_rows": int(len(learning)),
        "learning_source_events": int(learning["source_event_date"].nunique()),
        "prediction_rows": int(len(walk.predictions)),
        "active_primary_signals": int(
            walk.predictions.loc[
                walk.predictions["model_id"].eq(MODEL_FULL_MLP), "active_signal"
            ].sum()
        ),
        "primary_target_rows": int(len(targets[MODEL_FULL_MLP])),
        "fold_records": int(len(walk.folds)),
    }
    promotion = _promotion(protocol, results, counts, checks)
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": _sidecar_hash(),
        "created_at_utc": datetime.now(UTC),
        "research_only": True,
        "live_trading_allowed": False,
        "source_limitations": protocol["source_limitations"],
        "runtime": {
            "python": os.sys.version,
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "settings": {
            "features": asdict(feature_settings),
            "model": asdict(model_settings),
            "risk": asdict(risk_settings),
        },
        "preflight": preflight,
        "counts": counts,
        "checks": checks,
        "results": results,
        "promotion": promotion,
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v32_curve_regime_intraday_{timestamp}_{_sidecar_hash()[:8]}"
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        (temporary / "resolved_protocol.yaml").write_bytes(CONFIG_PATH.read_bytes())
        _write_json(temporary / "preflight.json", preflight)
        audit_columns = [
            "decision_at",
            "entry_at",
            "target_end_at",
            "source_event_at",
            "source_available_at",
            "source_event_date",
            *[f"target_{asset.lower()}_return" for asset in ASSETS],
            *[f"stress_roundtrip_cost_{asset.lower()}" for asset in ASSETS],
        ]
        learning.loc[:, audit_columns].to_parquet(temporary / "learning_audit.parquet", index=False)
        predictions_to_write = walk.predictions.copy()
        predictions_to_write.to_parquet(temporary / "predictions.parquet", index=False)
        folds_to_write = walk.folds.copy()
        if "threshold_candidates" in folds_to_write:
            folds_to_write["threshold_candidates"] = folds_to_write["threshold_candidates"].map(
                lambda value: (
                    json.dumps(_json_safe(value), sort_keys=True)
                    if isinstance(value, list)
                    else None
                )
            )
        folds_to_write.to_parquet(temporary / "folds.parquet", index=False)
        for model_id, frame in targets.items():
            frame.to_parquet(temporary / f"targets_{model_id}.parquet", index=False)
        for key, simulation in simulations.items():
            safe = key.replace(":", "_")
            simulation.ledger.to_parquet(temporary / f"ledger_{safe}.parquet", index=False)
            simulation.orders.to_parquet(temporary / f"orders_{safe}.parquet", index=False)
            simulation.unresolved.to_parquet(temporary / f"unresolved_{safe}.parquet", index=False)
        artifact_paths = sorted(
            path
            for path in temporary.iterdir()
            if path.name not in {"metrics.json", "identity.json"}
        )
        payload["artifacts"] = {path.name: _artifact_record(path) for path in artifact_paths}
        _write_json(temporary / "metrics.json", payload)
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        payload["artifacts"]["report.md"] = _artifact_record(temporary / "report.md")
        _write_json(temporary / "metrics.json", payload)
        identity = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": _sidecar_hash(),
            "core_sha256": sha256_file(CORE_MODULE_PATH),
            "runner_sha256": sha256_file(RUNNER_MODULE_PATH),
            "metrics_sha256": sha256_file(temporary / "metrics.json"),
            "declared_input_sha256": {
                key: value["sha256"]
                for key, value in protocol["inputs"].items()
                if isinstance(value, dict) and "sha256" in value
            },
            "artifact_names": sorted(path.name for path in temporary.iterdir()),
        }
        _write_json(temporary / "identity.json", identity)
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_run(run_path: Path) -> dict[str, Any]:
    identity = _read_json(run_path / "identity.json")
    metrics_path = run_path / "metrics.json"
    if sha256_file(metrics_path) != str(identity["metrics_sha256"]):
        raise ValueError("V32 metrics SHA drift")
    metrics = _read_json(metrics_path)
    checks: dict[str, bool] = {}
    for name, record in metrics["artifacts"].items():
        path = run_path / name
        checks[f"artifact:{name}"] = bool(
            path.is_file()
            and path.stat().st_size == int(record["bytes"])
            and sha256_file(path) == str(record["sha256"])
        )
        if checks[f"artifact:{name}"] and path.suffix == ".parquet":
            checks[f"rows:{name}"] = parquet.ParquetFile(path).metadata.num_rows == int(
                record["rows"]
            )
    checks["recorded_checks_all_true"] = all(metrics["checks"].values())
    checks["exact_recorded_directory_members"] = set(path.name for path in run_path.iterdir()) == {
        *identity["artifact_names"],
        "identity.json",
    }
    if not all(checks.values()):
        raise ValueError(f"V32 run audit failed: {checks}")
    return {"run": str(run_path), "checks": checks, "metrics_sha256": identity["metrics_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit-run", type=Path)
    arguments = parser.parse_args()
    protocol = load_protocol()
    if arguments.preflight_only:
        print(json.dumps(_json_safe(metadata_preflight(protocol)), ensure_ascii=False, indent=2))
        return
    if arguments.audit_run is not None:
        print(json.dumps(_json_safe(audit_run(arguments.audit_run)), ensure_ascii=False, indent=2))
        return
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "PROJECT_ROOT",
    "audit_run",
    "load_economic_inputs",
    "load_protocol",
    "main",
    "metadata_preflight",
    "run_experiment",
    "sha256_file",
]
