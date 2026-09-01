"""Build causal 10-minute constant-maturity features from MOEX curve parameters."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import moex_volatility_curve_source as source_v1
from market_lab.futures import moex_volatility_curve_source_v3 as source_v3
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = source_v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_volatility_curve_features_v1.yaml"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSETS: Final[tuple[str, ...]] = ("RI", "MIX", "SI", "BR")
TARGET_DAYS: Final[tuple[int, ...]] = (30, 90)
GRID_FREQUENCY_MINUTES: Final[int] = 10
GRID_START: Final[str] = "10:10:00"
GRID_END: Final[str] = "23:50:00"
MAXIMUM_FRESHNESS_MINUTES: Final[int] = 20
EXPECTED_EVENT_DATES: Final[int] = 18
EXPECTED_GRID_PER_DATE: Final[int] = 83
EXPECTED_PANEL_ROWS: Final[int] = EXPECTED_EVENT_DATES * EXPECTED_GRID_PER_DATE * len(ASSETS)
SECONDS_PER_YEAR: Final[float] = 365.0 * 24.0 * 60.0 * 60.0
MINIMUM_OVERALL_COVERAGE: Final[float] = 0.85
MINIMUM_ASSET_COVERAGE: Final[float] = 0.80
FORBIDDEN_COLUMNS: Final[frozenset[str]] = frozenset(
    {"return", "returns", "target", "label", "signal", "pnl", "equity"}
)
ANALYTIC_COLUMNS: Final[tuple[str, ...]] = (
    "atm_volatility_pct",
    "atm_skew_per_x",
    "atm_curvature_per_x2",
)


@dataclass(frozen=True, slots=True)
class FeatureProtocol:
    """Verified outcome-free feature contract and byte-pinned source paths."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    source_root: Path
    source_manifest_path: Path
    source_panel_path: Path
    output_directory: Path


@dataclass(frozen=True, slots=True)
class FeatureBuild:
    """Event analytics, 10-minute panel and quality evidence."""

    event_features: pd.DataFrame
    panel: pd.DataFrame
    checks: dict[str, bool]
    counts: dict[str, Any]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX curve features {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX curve feature sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _manifest_payload_sha(manifest: Mapping[str, Any]) -> str:
    core = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    return hashlib.sha256(_canonical_json(core)).hexdigest()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> FeatureProtocol:
    """Verify config, implementation and source identities before reading coefficients."""
    path = config_path.resolve()
    config_sha = source_v1.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX curve feature protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX curve feature protocol must be a YAML object")
    source = _mapping(payload.get("source"), "source")
    formula = _mapping(payload.get("formula"), "formula")
    grid = _mapping(payload.get("decision_grid"), "grid")
    interpolation = _mapping(payload.get("constant_maturity"), "constant maturity")
    quality = _mapping(payload.get("quality_gates"), "quality gates")
    output = _mapping(payload.get("output"), "output")
    if (
        payload.get("protocol_id") != "moex_volatility_curve_features_v1"
        or payload.get("status") != "sealed_before_first_curve_feature_value"
        or payload.get("scope") != "source_derived_no_market_returns_no_strategy_no_pnl"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or source.get("source_id")
        != "official-moex-volatility-curve-core4-pilot-2021-01-v3"
        or source.get("manifest_sha256")
        != "992f34b6345dc0fee767d16c3148ad1cc7b6405966305f85223fc7f8d7c20b48"
        or source.get("processed_sha256")
        != "2c0e435eff3493ebf0f1a682666b214e7db78d74975875bee1617389857bcfea"
        or int(source["processed_rows"]) != source_v3.EXPECTED_CORE_ROWS
        or tuple(payload["universe"]["exact_order"]) != ASSETS
        or formula.get("regime") != "post_2017_02_27"
        or formula.get("y") != "x_minus_s_divided_by_sqrt_T"
        or formula.get("curve")
        != "a_plus_b_times_1_minus_exp_minus_c_y2_plus_d_times_atan_e_y_div_e"
        or formula.get("analytic_point") != "forward_ATM_x_equals_zero"
        or int(grid["frequency_minutes"]) != GRID_FREQUENCY_MINUTES
        or grid.get("start") != GRID_START
        or grid.get("end") != GRID_END
        or int(grid["maximum_source_freshness_minutes"]) != MAXIMUM_FRESHNESS_MINUTES
        or grid.get("admission") != "available_at_not_after_decision_at"
        or tuple(int(value) for value in interpolation["target_calendar_days"])
        != TARGET_DAYS
        or interpolation.get("method") != "linear_in_effective_years_to_expiry"
        or interpolation.get("extrapolation") != "forbidden_missing"
        or interpolation.get("nonpositive_T") != "ineligible"
        or float(quality["minimum_overall_complete_30d_90d_fraction"])
        != MINIMUM_OVERALL_COVERAGE
        or float(quality["minimum_each_asset_complete_30d_90d_fraction"])
        != MINIMUM_ASSET_COVERAGE
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX curve feature protocol invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source_v1.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"MOEX curve feature dependency drift: {relative}")
    source_root = (PROJECT_ROOT / str(source["directory"])).resolve()
    manifest_path = source_root / str(source["manifest_path"])
    panel_path = source_root / str(source["processed_path"])
    return FeatureProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        source_root=source_root,
        source_manifest_path=manifest_path,
        source_panel_path=panel_path,
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def verify_source(protocol: FeatureProtocol) -> tuple[dict[str, Any], dict[str, bool]]:
    """Verify source bytes and metadata before loading any coefficient values."""
    source = protocol.payload["source"]
    checks = {
        "source_manifest_exists": protocol.source_manifest_path.is_file(),
        "source_processed_exists": protocol.source_panel_path.is_file(),
    }
    if not all(checks.values()):
        raise FileNotFoundError(f"MOEX curve feature source is missing: {checks}")
    checks.update(
        {
            "source_manifest_bytes": protocol.source_manifest_path.stat().st_size
            == int(source["manifest_bytes"]),
            "source_manifest_sha256": source_v1.sha256_file(protocol.source_manifest_path)
            == source["manifest_sha256"],
            "source_processed_bytes": protocol.source_panel_path.stat().st_size
            == int(source["processed_bytes"]),
            "source_processed_sha256": source_v1.sha256_file(protocol.source_panel_path)
            == source["processed_sha256"],
        }
    )
    manifest = json.loads(protocol.source_manifest_path.read_text(encoding="utf-8-sig"))
    checks.update(
        {
            "source_manifest_payload": _manifest_payload_sha(manifest)
            == manifest["manifest_payload_sha256"],
            "source_id": manifest["source_id"] == source["source_id"],
            "source_rows": manifest["artifacts"]["processed"]["rows"]
            == int(source["processed_rows"]),
            "source_artifact_identity": manifest["artifacts"]["processed"]["sha256"]
            == source["processed_sha256"],
            "source_outcome_free": manifest["temporal_semantics"]
            ["contains_returns_targets_labels_or_pnl"]
            is False,
            "source_before_protected_boundary": pd.Timestamp(
                manifest["artifacts"]["processed"]["maximum_event_at"]
            ).tz_localize(None)
            < PROTECTED_FROM,
        }
    )
    if not all(checks.values()):
        raise ValueError(f"MOEX curve feature source verification failed: {checks}")
    return manifest, checks


def evaluate_curve_at_forward_atm(frame: pd.DataFrame, T: pd.Series | None = None) -> pd.DataFrame:
    """Evaluate level and first two x-derivatives at x=0 using the post-2017 formula."""
    required = {"s", "a", "b", "c", "d", "e", "years_to_expiry"}
    if missing := required - set(frame.columns):
        raise ValueError(f"MOEX curve analytic frame lacks columns: {sorted(missing)}")
    maturity = (
        pd.to_numeric(T, errors="coerce").astype(float)
        if T is not None
        else pd.to_numeric(frame["years_to_expiry"], errors="coerce").astype(float)
    )
    values = {
        column: pd.to_numeric(frame[column], errors="coerce").astype(float)
        for column in ("s", "a", "b", "c", "d", "e")
    }
    valid = maturity.gt(0.0) & np.isfinite(maturity)
    for series in values.values():
        valid &= series.notna() & np.isfinite(series)
    result = pd.DataFrame(index=frame.index)
    result["atm_normalized_y"] = np.nan
    for column in ANALYTIC_COLUMNS:
        result[column] = np.nan
    if not valid.any():
        result["curve_analytic_valid"] = False
        return result
    index = valid.index[valid]
    t = maturity.loc[index].to_numpy(dtype=float)
    s = values["s"].loc[index].to_numpy(dtype=float)
    a = values["a"].loc[index].to_numpy(dtype=float)
    b = values["b"].loc[index].to_numpy(dtype=float)
    c = values["c"].loc[index].to_numpy(dtype=float)
    d = values["d"].loc[index].to_numpy(dtype=float)
    e = values["e"].loc[index].to_numpy(dtype=float)
    y = -s / np.sqrt(t)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        exponential = np.exp(-c * np.square(y))
        atan_ratio = np.empty_like(y)
        nonzero_e = np.abs(e) > 1e-14
        atan_ratio[nonzero_e] = np.arctan(e[nonzero_e] * y[nonzero_e]) / e[nonzero_e]
        atan_ratio[~nonzero_e] = y[~nonzero_e]
        level = a + b * (1.0 - exponential) + d * atan_ratio
        skew = 2.0 * b * c * y * exponential + d / (1.0 + np.square(e * y))
        curvature = (
            2.0 * b * c * exponential * (1.0 - 2.0 * c * np.square(y))
            - 2.0 * d * np.square(e) * y / np.square(1.0 + np.square(e * y))
        )
    finite = np.isfinite(y) & np.isfinite(level) & np.isfinite(skew) & np.isfinite(curvature)
    if not finite.all():
        raise ValueError("MOEX curve analytic formula produced a non-finite value")
    result.loc[index, "atm_normalized_y"] = y
    result.loc[index, "atm_volatility_pct"] = level
    result.loc[index, "atm_skew_per_x"] = skew
    result.loc[index, "atm_curvature_per_x2"] = curvature
    result["curve_analytic_valid"] = valid
    return result


def build_event_features(source: pd.DataFrame) -> pd.DataFrame:
    """Attach formula outputs at each factual source event without dropping audit rows."""
    required = {
        "full_name",
        "small_name",
        "event_at",
        "available_at",
        "asset",
        "source_root",
        "years_to_expiry",
        "curve_feature_eligible",
        "s",
        "a",
        "b",
        "c",
        "d",
        "e",
    }
    if missing := required - set(source.columns):
        raise ValueError(f"MOEX curve source lacks columns: {sorted(missing)}")
    frame = source.copy()
    frame["event_at"] = pd.to_datetime(frame["event_at"], errors="raise")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise")
    if frame["event_at"].dt.tz is None or frame["available_at"].dt.tz is None:
        raise ValueError("MOEX curve events must retain timezone-aware timestamps")
    if frame["event_at"].dt.tz_convert("Europe/Moscow").dt.tz is None:
        raise ValueError("MOEX curve event timezone conversion failed")
    if frame["available_at"].lt(frame["event_at"]).any():
        raise ValueError("MOEX curve availability precedes an event")
    analytics = evaluate_curve_at_forward_atm(frame)
    for column in analytics:
        frame[column] = analytics[column]
    expected_valid = frame["curve_feature_eligible"].astype(bool)
    if not frame["curve_analytic_valid"].eq(expected_valid).all():
        raise ValueError("MOEX curve analytic mask disagrees with source eligibility")
    columns = [
        "full_name",
        "small_name",
        "asset",
        "source_root",
        "event_at",
        "available_at",
        "years_to_expiry",
        "s",
        "a",
        "b",
        "c",
        "d",
        "e",
        "atm_normalized_y",
        *ANALYTIC_COLUMNS,
        "curve_analytic_valid",
    ]
    return frame.loc[:, columns].sort_values(
        ["event_at", "asset", "full_name"],
        kind="mergesort",
        ignore_index=True,
    )


def build_decision_grid(event_features: pd.DataFrame) -> pd.DataFrame:
    """Create a fixed 10-minute Moscow grid for each factual source event date."""
    dates = pd.Series(
        event_features["event_at"].dt.tz_convert("Europe/Moscow").dt.date
    ).drop_duplicates()
    grids: list[pd.DataFrame] = []
    for value in sorted(dates):
        day = pd.Timestamp(value).tz_localize("Europe/Moscow")
        start = pd.Timestamp(f"{value} {GRID_START}").tz_localize("Europe/Moscow")
        end = pd.Timestamp(f"{value} {GRID_END}").tz_localize("Europe/Moscow")
        decisions = pd.date_range(start, end, freq=f"{GRID_FREQUENCY_MINUTES}min")
        if len(decisions) != EXPECTED_GRID_PER_DATE:
            raise ValueError(f"unexpected MOEX curve grid length for {day}: {len(decisions)}")
        grids.append(pd.DataFrame({"decision_at": decisions}))
    grid = pd.concat(grids, ignore_index=True)
    grid["decision_date"] = grid["decision_at"].dt.tz_localize(None).dt.normalize()
    return grid


def _latest_series_states(
    event_features: pd.DataFrame,
    grid: pd.DataFrame,
) -> pd.DataFrame:
    """As-of join each series with strict availability and a fixed freshness mask."""
    states: list[pd.DataFrame] = []
    value_columns = [
        "full_name",
        "small_name",
        "asset",
        "source_root",
        "event_at",
        "available_at",
        "years_to_expiry",
        "s",
        "a",
        "b",
        "c",
        "d",
        "e",
        "curve_analytic_valid",
    ]
    for full_name, series in event_features.groupby("full_name", sort=True):
        ordered = series.loc[:, value_columns].sort_values("available_at", kind="mergesort")
        joined = pd.merge_asof(
            grid.loc[:, ["decision_at", "decision_date"]].sort_values("decision_at"),
            ordered,
            left_on="decision_at",
            right_on="available_at",
            direction="backward",
            allow_exact_matches=True,
        )
        joined["full_name"] = joined["full_name"].fillna(str(full_name))
        joined["source_age_minutes"] = (
            joined["decision_at"] - joined["available_at"]
        ).dt.total_seconds() / 60.0
        joined["fresh"] = (
            joined["available_at"].notna()
            & joined["available_at"].le(joined["decision_at"])
            & joined["source_age_minutes"].between(0.0, MAXIMUM_FRESHNESS_MINUTES)
            & joined["curve_analytic_valid"].fillna(False).astype(bool)
        )
        elapsed_years = (
            (joined["decision_at"] - joined["event_at"]).dt.total_seconds()
            / SECONDS_PER_YEAR
        )
        joined["effective_years_to_expiry"] = joined["years_to_expiry"] - elapsed_years
        joined["fresh"] &= joined["effective_years_to_expiry"].gt(0.0)
        states.append(joined)
    output = pd.concat(states, ignore_index=True)
    valid = output["fresh"]
    analytics = evaluate_curve_at_forward_atm(
        output.loc[valid],
        output.loc[valid, "effective_years_to_expiry"],
    )
    for column in ("atm_normalized_y", *ANALYTIC_COLUMNS):
        output[f"decision_{column}"] = np.nan
        output.loc[valid, f"decision_{column}"] = analytics[column].to_numpy(dtype=float)
    return output.sort_values(
        ["decision_at", "asset", "effective_years_to_expiry", "full_name"],
        kind="mergesort",
        ignore_index=True,
    )


def _interpolate_metric(
    states: pd.DataFrame,
    target_years: float,
) -> dict[str, object]:
    valid = states.loc[
        states["fresh"]
        & states["effective_years_to_expiry"].gt(0.0)
        & states[[f"decision_{column}" for column in ANALYTIC_COLUMNS]].notna().all(axis=1)
    ].copy()
    valid = valid.sort_values(
        ["effective_years_to_expiry", "available_at", "full_name"],
        kind="mergesort",
    )
    lower = valid.loc[valid["effective_years_to_expiry"].le(target_years)].tail(1)
    upper = valid.loc[valid["effective_years_to_expiry"].ge(target_years)].head(1)
    result: dict[str, object] = {
        "available": False,
        "lower_full_name": None,
        "upper_full_name": None,
        "lower_T": np.nan,
        "upper_T": np.nan,
        "observed_through": pd.NaT,
        "available_through": pd.NaT,
        "maximum_source_age_minutes": np.nan,
    }
    for column in ANALYTIC_COLUMNS:
        result[column] = np.nan
    if lower.empty or upper.empty:
        return result
    low = lower.iloc[0]
    high = upper.iloc[0]
    low_t = float(low["effective_years_to_expiry"])
    high_t = float(high["effective_years_to_expiry"])
    if high_t < low_t:
        raise ValueError("MOEX curve interpolation bracket is reversed")
    weight = 0.0 if np.isclose(high_t, low_t) else (target_years - low_t) / (high_t - low_t)
    if not -1e-12 <= weight <= 1.0 + 1e-12:
        raise ValueError("MOEX curve interpolation attempted extrapolation")
    weight = float(np.clip(weight, 0.0, 1.0))
    result.update(
        {
            "available": True,
            "lower_full_name": str(low["full_name"]),
            "upper_full_name": str(high["full_name"]),
            "lower_T": low_t,
            "upper_T": high_t,
            "observed_through": max(low["event_at"], high["event_at"]),
            "available_through": max(low["available_at"], high["available_at"]),
            "maximum_source_age_minutes": max(
                float(low["source_age_minutes"]),
                float(high["source_age_minutes"]),
            ),
        }
    )
    for column in ANALYTIC_COLUMNS:
        low_value = float(low[f"decision_{column}"])
        high_value = float(high[f"decision_{column}"])
        result[column] = low_value + weight * (high_value - low_value)
    return result


def build_constant_maturity_panel(
    event_features: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build per-asset 30/90-day states and a same-bucket cross-asset context."""
    grid = build_decision_grid(event_features)
    states = _latest_series_states(event_features, grid)
    rows: list[dict[str, object]] = []
    for decision_at in grid["decision_at"]:
        snapshot = states.loc[states["decision_at"].eq(decision_at)]
        for asset in ASSETS:
            asset_states = snapshot.loc[snapshot["asset"].eq(asset)]
            row: dict[str, object] = {
                "decision_at": decision_at,
                "decision_date": decision_at.tz_localize(None).normalize(),
                "asset": asset,
                "known_series": int(asset_states["full_name"].nunique()),
                "fresh_series": int(asset_states["fresh"].sum()),
            }
            for days in TARGET_DAYS:
                interpolated = _interpolate_metric(asset_states, days / 365.0)
                suffix = f"{days}d"
                row[f"available_{suffix}"] = bool(interpolated["available"])
                row[f"lower_full_name_{suffix}"] = interpolated["lower_full_name"]
                row[f"upper_full_name_{suffix}"] = interpolated["upper_full_name"]
                row[f"lower_T_{suffix}"] = interpolated["lower_T"]
                row[f"upper_T_{suffix}"] = interpolated["upper_T"]
                row[f"observed_through_{suffix}"] = interpolated["observed_through"]
                row[f"available_through_{suffix}"] = interpolated["available_through"]
                row[f"maximum_source_age_minutes_{suffix}"] = interpolated[
                    "maximum_source_age_minutes"
                ]
                row[f"volatility_{suffix}"] = interpolated["atm_volatility_pct"]
                row[f"skew_{suffix}"] = interpolated["atm_skew_per_x"]
                row[f"curvature_{suffix}"] = interpolated["atm_curvature_per_x2"]
            row["complete_30d_90d"] = bool(row["available_30d"] and row["available_90d"])
            row["term_spread_90d_minus_30d"] = (
                float(row["volatility_90d"]) - float(row["volatility_30d"])
                if row["complete_30d_90d"]
                else np.nan
            )
            observed = [
                value
                for value in (row["observed_through_30d"], row["observed_through_90d"])
                if pd.notna(value)
            ]
            available = [
                value
                for value in (row["available_through_30d"], row["available_through_90d"])
                if pd.notna(value)
            ]
            row["source_observed_through"] = max(observed) if observed else pd.NaT
            row["source_available_through"] = max(available) if available else pd.NaT
            rows.append(row)
    panel = pd.DataFrame(rows)
    panel["_asset_order"] = panel["asset"].map(
        {asset: order for order, asset in enumerate(ASSETS)}
    )
    panel = (
        panel.sort_values(
            ["decision_at", "_asset_order"], kind="mergesort", ignore_index=True
        )
        .drop(columns="_asset_order")
    )
    context_metrics = (
        "volatility_30d",
        "skew_30d",
        "curvature_30d",
        "volatility_90d",
        "skew_90d",
        "curvature_90d",
        "term_spread_90d_minus_30d",
    )
    context = panel.loc[:, ["decision_at", "asset", *context_metrics]].copy()
    for metric in context_metrics:
        pivot = context.pivot(index="decision_at", columns="asset", values=metric)
        for asset in ASSETS:
            panel[f"context_{asset.lower()}_{metric}"] = panel["decision_at"].map(
                pivot[asset]
            )
    panel["cross_asset_volatility_30d_count"] = panel.groupby("decision_at")[
        "volatility_30d"
    ].transform("count")
    panel["cross_asset_volatility_30d_median"] = panel.groupby("decision_at")[
        "volatility_30d"
    ].transform("median")
    panel["cross_asset_volatility_30d_dispersion"] = panel.groupby("decision_at")[
        "volatility_30d"
    ].transform("std")
    panel["cross_asset_skew_30d_median"] = panel.groupby("decision_at")[
        "skew_30d"
    ].transform("median")
    return panel, states


def build_features(source: pd.DataFrame) -> FeatureBuild:
    """Build the complete outcome-free pilot and enforce temporal/coverage gates."""
    event_features = build_event_features(source)
    panel, states = build_constant_maturity_panel(event_features)
    complete_fraction = float(panel["complete_30d_90d"].mean())
    per_asset = panel.groupby("asset")["complete_30d_90d"].mean().to_dict()
    complete = panel.loc[panel["complete_30d_90d"]]
    no_future_observed = bool(
        complete["source_observed_through"].le(complete["decision_at"]).all()
    )
    no_future_available = bool(
        complete["source_available_through"].le(complete["decision_at"]).all()
    )
    checks = {
        "event_rows_preserved": len(event_features) == len(source),
        "event_analytic_mask_exact": bool(
            event_features["curve_analytic_valid"].sum()
            == source["curve_feature_eligible"].sum()
        ),
        "event_analytics_finite_when_valid": bool(
            np.isfinite(
                event_features.loc[
                    event_features["curve_analytic_valid"], ANALYTIC_COLUMNS
                ].to_numpy(dtype=float)
            ).all()
        ),
        "exact_panel_rows": len(panel) == EXPECTED_PANEL_ROWS,
        "unique_decision_asset": not panel.duplicated(["decision_at", "asset"]).any(),
        "exact_assets": tuple(panel["asset"].drop_duplicates()) == ASSETS,
        "no_future_observed": no_future_observed,
        "no_future_available": no_future_available,
        "freshness_cap": bool(
            states.loc[states["fresh"], "source_age_minutes"].le(
                MAXIMUM_FRESHNESS_MINUTES
            ).all()
        ),
        "nonpositive_effective_T_excluded": not bool(
            states.loc[states["fresh"], "effective_years_to_expiry"].le(0.0).any()
        ),
        "overall_coverage_gate": complete_fraction >= MINIMUM_OVERALL_COVERAGE,
        "each_asset_coverage_gate": all(
            float(per_asset.get(asset, 0.0)) >= MINIMUM_ASSET_COVERAGE for asset in ASSETS
        ),
        "no_extrapolation_30d": bool(
            complete["lower_T_30d"].le(30.0 / 365.0).all()
            and complete["upper_T_30d"].ge(30.0 / 365.0).all()
        ),
        "no_extrapolation_90d": bool(
            complete["lower_T_90d"].le(90.0 / 365.0).all()
            and complete["upper_T_90d"].ge(90.0 / 365.0).all()
        ),
        "forbidden_columns_absent": not bool(
            (set(event_features.columns.str.lower()) | set(panel.columns.str.lower()))
            & FORBIDDEN_COLUMNS
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"MOEX volatility curve feature gates failed: {checks}")
    counts: dict[str, Any] = {
        "source_events": len(source),
        "analytic_events": int(event_features["curve_analytic_valid"].sum()),
        "event_dates": int(event_features["event_at"].dt.date.nunique()),
        "decision_grid_points": int(panel["decision_at"].nunique()),
        "panel_rows": len(panel),
        "complete_rows": int(panel["complete_30d_90d"].sum()),
        "complete_fraction": complete_fraction,
        "complete_fraction_by_asset": {key: float(value) for key, value in per_asset.items()},
        "fresh_state_rows": int(states["fresh"].sum()),
    }
    return FeatureBuild(event_features, panel, checks, counts)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_feature_source(
    config_path: Path = DEFAULT_CONFIG,
    output_directory: Path | None = None,
    *,
    built_at_utc: str | None = None,
) -> Path:
    """Build one immutable source-derived feature pilot without market outcomes."""
    protocol = load_protocol(config_path)
    source_manifest, source_checks = verify_source(protocol)
    source = pd.read_parquet(protocol.source_panel_path)
    result = build_features(source)
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX curve feature output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        event_path = temporary / "curve_event_features.parquet"
        panel_path = temporary / "constant_maturity_10m.parquet"
        _atomic_parquet(event_path, result.event_features)
        _atomic_parquet(panel_path, result.panel)
        audit_path = temporary / "feature_audit.json"
        write_json(
            audit_path,
            {
                "schema_version": 1,
                "source_checks": source_checks,
                "feature_checks": result.checks,
                "counts": result.counts,
            },
        )
        built_at = built_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "moex-volatility-curve-features-pilot-2021-01-v1",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "built_at_utc": built_at,
            "parent": {
                "source_id": source_manifest["source_id"],
                "manifest_path": protocol.source_manifest_path.relative_to(
                    PROJECT_ROOT
                ).as_posix(),
                "manifest_sha256": source_v1.sha256_file(protocol.source_manifest_path),
                "processed_sha256": source_v1.sha256_file(protocol.source_panel_path),
            },
            "information_contract": {
                "curve_formula_regime": "post-2017-02-27",
                "decision_grid": "10 minutes, 10:10 through 23:50 Europe/Moscow",
                "availability": "event_at plus one minute not after decision_at",
                "maximum_freshness_minutes": MAXIMUM_FRESHNESS_MINUTES,
                "constant_maturity_days": list(TARGET_DAYS),
                "interpolation": "linear in effective years to expiry, no extrapolation",
                "nonpositive_T": "preserved in parent, excluded from features",
                "contains_market_returns_targets_labels_or_pnl": False,
            },
            "counts": result.counts,
            "artifacts": {
                "event_features": {
                    "path": event_path.name,
                    "bytes": event_path.stat().st_size,
                    "sha256": source_v1.sha256_file(event_path),
                    "rows": len(result.event_features),
                    "columns": result.event_features.columns.tolist(),
                },
                "constant_maturity_panel": {
                    "path": panel_path.name,
                    "bytes": panel_path.stat().st_size,
                    "sha256": source_v1.sha256_file(panel_path),
                    "rows": len(result.panel),
                    "columns": result.panel.columns.tolist(),
                    "minimum_decision_at": result.panel["decision_at"].min().isoformat(),
                    "maximum_decision_at": result.panel["decision_at"].max().isoformat(),
                },
                "audit": {
                    "path": audit_path.name,
                    "bytes": audit_path.stat().st_size,
                    "sha256": source_v1.sha256_file(audit_path),
                },
            },
        }
        manifest = {
            **manifest_core,
            "manifest_payload_sha256": hashlib.sha256(_canonical_json(manifest_core)).hexdigest(),
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        manifest_sha = source_v1.sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_existing_features(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Rebuild from the byte-pinned parent and verify both feature artifacts."""
    protocol = load_protocol(config_path)
    verify_source(protocol)
    root = (output_directory or protocol.output_directory).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "manifest_payload_sha256": _manifest_payload_sha(manifest)
        == manifest["manifest_payload_sha256"],
        "manifest_sidecar_sha256": (root / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == source_v1.sha256_file(manifest_path),
        "protocol_identity": manifest["protocol"]["sha256"] == protocol.config_sha256,
    }
    for name, artifact in manifest["artifacts"].items():
        path = root / artifact["path"]
        checks[f"{name}_exists"] = path.is_file()
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == artifact["bytes"]
        checks[f"{name}_sha256"] = path.is_file() and source_v1.sha256_file(path) == artifact[
            "sha256"
        ]
    rebuilt = build_features(pd.read_parquet(protocol.source_panel_path))
    stored_events = pd.read_parquet(root / manifest["artifacts"]["event_features"]["path"])
    stored_panel = pd.read_parquet(
        root / manifest["artifacts"]["constant_maturity_panel"]["path"]
    )
    try:
        pd.testing.assert_frame_equal(stored_events, rebuilt.event_features, check_like=False)
        checks["event_replay_exact"] = True
    except AssertionError:
        checks["event_replay_exact"] = False
    try:
        pd.testing.assert_frame_equal(stored_panel, rebuilt.panel, check_like=False)
        checks["panel_replay_exact"] = True
    except AssertionError:
        checks["panel_replay_exact"] = False
    if not all(checks.values()):
        raise ValueError(f"MOEX curve feature existing audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "checks": checks,
        "counts": manifest["counts"],
        "manifest_sha256": source_v1.sha256_file(manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.audit_only:
        print(
            json.dumps(
                audit_existing_features(arguments.output_directory, arguments.config),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(build_feature_source(arguments.config, arguments.output_directory))


if __name__ == "__main__":
    main()
