"""Sealed V17 EIA physical-balance direction experiment for BR futures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v17_eia_supply_demand.yaml"
CONFIG_SHA256: Final[str] = (
    "1d8eee3f7aa99aff5798aeaf6a946d110cfa4e4b451b57580b1d9ef6cd17b37a"
)
EIA_SOURCE_MANIFEST_SHA256: Final[str] = (
    "aac389628b61df446616cd171084af81482d09a7d4b403337a8332b5373c142b"
)
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
OOS_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
NORMALIZATION_WINDOW: Final[int] = 156
MINIMUM_HISTORY: Final[int] = 104
Z_CLIP: Final[float] = 3.0
STD_FLOOR: Final[float] = 1.0e-12
VOLATILITY_LOOKBACK: Final[int] = 60
ANNUALIZATION: Final[int] = 252
VOLATILITY_FLOOR: Final[float] = 0.10
TARGET_VOLATILITY: Final[float] = 0.20
MAXIMUM_ABSOLUTE_WEIGHT: Final[float] = 1.0
INITIAL_CASH: Final[float] = 1_000_000.0
MAXIMUM_PARTICIPATION: Final[float] = 0.01


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    section: str
    item: str
    economic_sign: int


COMPONENTS: Final[tuple[Component, ...]] = (
    Component("commercial_crude_stocks", "Stocks", "Commercial (Excluding SPR)", -1),
    Component("motor_gasoline_stocks", "Stocks", "Total Motor Gasoline", -1),
    Component("distillate_stocks", "Stocks", "Distillate Fuel Oil", -1),
    Component("domestic_crude_production", "Crude Oil Supply", "Domestic Production", -1),
    Component(
        "net_crude_imports",
        "Crude Oil Supply",
        "Net Imports (Including SPR)",
        -1,
    ),
    Component(
        "crude_refinery_inputs",
        "Crude Oil Supply",
        "Crude Oil Input to Refineries",
        1,
    ),
    Component("products_supplied", "Products Supplied", "Total", 1),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    return v12._json_safe(value)


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every V17 economic invariant before outcome access."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V17 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V17 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V17 protocol must be a mapping")
    components = tuple(
        (str(item["section"]), str(item["item"]), int(item["economic_sign"]))
        for item in protocol["signal"]["components"]
    )
    expected_components = tuple(
        (item.section, item.item, item.economic_sign) for item in COMPONENTS
    )
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    if (
        protocol.get("protocol_id") != "futures_v17_eia_supply_demand_v1"
        or protocol.get("status") != "sealed_before_any_v17_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or components != expected_components
        or int(signal["normalization_window_prior_releases"]) != NORMALIZATION_WINDOW
        or int(signal["minimum_prior_releases"]) != MINIMUM_HISTORY
        or tuple(float(value) for value in signal["per_component_z_clip"])
        != (-Z_CLIP, Z_CLIP)
        or float(signal["standard_deviation_floor"]) != STD_FLOOR
        or signal["trade_threshold"] != "none"
        or int(portfolio["BR_daily_volatility_lookback_sessions"])
        != VOLATILITY_LOOKBACK
        or int(portfolio["annualization_sessions"]) != ANNUALIZATION
        or float(portfolio["annualized_volatility_floor"]) != VOLATILITY_FLOOR
        or float(portfolio["annual_target_volatility"]) != TARGET_VOLATILITY
        or float(portfolio["BR_absolute_weight_cap"]) != MAXIMUM_ABSOLUTE_WEIGHT
        or float(portfolio["gross_cap"]) != 1.0
        or float(execution["initial_cash_rub"]) != INITIAL_CASH
        or float(execution["maximum_participation"]) != MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != 1.0
        or float(execution["initial_margin_buffer_multiple"]) != 2.0
    ):
        raise ValueError("sealed V17 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]
    parent_protocol: dict[str, Any]


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify target-free EIA artifacts and parent market identities before price reads."""
    parent_protocol = v12.load_protocol()
    parent_verified = v12.verify_inputs(parent_protocol)
    checks = {f"parent_{key}": value for key, value in parent_verified.checks.items()}
    paths = {
        name: parent_verified.paths[name]
        for name in ("panel", "active_contract_map", "contract_observations", "spec_proxy")
    }
    for name in paths:
        declaration = protocol["inputs"][name]
        parent = parent_protocol["inputs"][name]
        checks[f"{name}_matches_parent_hash"] = declaration["sha256"] == parent["sha256"]
        checks[f"{name}_matches_parent_bytes"] = int(declaration["bytes"]) == int(
            parent["bytes"]
        )
        checks[f"{name}_matches_parent_schema"] = tuple(
            declaration["allowed_columns"]
        ) == tuple(parent["allowed_columns"])

    metadata: dict[str, Any] = {"parent_v12": parent_verified.metadata}
    for name in ("eia_table1", "eia_coverage", "eia_manifest"):
        declaration = protocol["inputs"][name]
        path = v12._resolved_input(str(declaration["path"]))
        paths[name] = path
        exists = path.is_file()
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha256"] = exists and sha256_file(path) == declaration["sha256"]
        metadata[name] = {
            "path": declaration["path"],
            "bytes": path.stat().st_size if exists else None,
            "sha256": sha256_file(path) if exists else None,
        }
        if name != "eia_manifest" and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_schema"] = set(declaration["allowed_columns"]) <= set(
                parquet.schema_arrow.names
            )
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
    if not all(checks.values()):
        raise ValueError(f"V17 byte/schema preflight failed: {checks}")

    manifest = json.loads(paths["eia_manifest"].read_text(encoding="utf-8-sig"))
    processed = manifest["artifacts"]["processed"]
    checks["eia_manifest_identity"] = (
        sha256_file(paths["eia_manifest"]) == EIA_SOURCE_MANIFEST_SHA256
    )
    checks["eia_manifest_processed_hash"] = (
        processed["sha256"] == protocol["inputs"]["eia_table1"]["sha256"]
    )
    checks["eia_manifest_processed_rows"] = int(processed["rows"]) == int(
        protocol["inputs"]["eia_table1"]["rows"]
    )
    checks["eia_release_count"] = int(manifest["release_count"]) == 728
    checks["eia_processed_release_count"] = int(manifest["processed_release_count"]) == 727
    checks["eia_excluded_release_count"] = int(manifest["excluded_release_count"]) == 1
    checks["eia_target_free"] = (
        manifest["temporal_semantics"]["contains_prices_returns_targets_labels_or_pnl"]
        is False
    )
    checks["eia_development_admissible"] = (
        manifest["temporal_semantics"]["historical_development_backtest_admissible"]
        is True
    )
    coverage = pd.read_parquet(
        paths["eia_coverage"],
        columns=protocol["inputs"]["eia_coverage"]["allowed_columns"],
    )
    excluded = coverage.loc[~coverage["admissible"].astype(bool)]
    checks["eia_exact_stale_exclusion"] = bool(
        len(excluded) == 1
        and pd.Timestamp(excluded.iloc[0]["release_date"]) == pd.Timestamp("2019-07-03")
        and excluded.iloc[0]["exclusion_reason"] == "duplicate_stale_archive_file"
    )
    metadata["eia_manifest_payload"] = manifest
    metadata["eia_coverage_counts"] = {
        "total": len(coverage),
        "admissible": int(coverage["admissible"].sum()),
        "excluded": int((~coverage["admissible"]).sum()),
    }
    if not all(checks.values()):
        raise ValueError(f"V17 source semantic preflight failed: {checks}")
    return VerifiedInputs(
        paths=paths,
        checks=checks,
        metadata=metadata,
        parent_protocol=parent_protocol,
    )


def build_source_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Build seven signed z-scores using only releases strictly earlier than each row."""
    required = {
        "release_date",
        "available_at",
        "data_week_ending",
        "section",
        "item",
        "reported_weekly_change",
        "raw_sha256",
        "release_specific_archive",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V17 EIA source lacks columns: {sorted(missing)}")
    source = frame.loc[:, sorted(required)].copy()
    source["release_date"] = pd.to_datetime(source["release_date"], errors="raise").dt.normalize()
    source["data_week_ending"] = pd.to_datetime(
        source["data_week_ending"], errors="raise"
    ).dt.normalize()
    source["available_at"] = pd.to_datetime(source["available_at"], utc=True, errors="raise")
    if source["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("V17 EIA source touches protected 2026+")
    if not source["release_specific_archive"].astype(bool).all():
        raise ValueError("V17 EIA source contains a non-release-specific row")
    source["reported_weekly_change"] = pd.to_numeric(
        source["reported_weekly_change"], errors="coerce"
    )
    keys = {(component.section, component.item): component for component in COMPONENTS}
    selected = source.loc[
        pd.MultiIndex.from_frame(source[["section", "item"]]).isin(keys)
    ].copy()
    if selected.duplicated(["release_date", "section", "item"]).any():
        raise ValueError("V17 EIA selected components contain duplicate release rows")
    observed_keys = set(map(tuple, selected[["section", "item"]].drop_duplicates().to_numpy()))
    if observed_keys != set(keys):
        raise ValueError("V17 EIA selected component schema is incomplete")
    release_meta = selected.groupby("release_date", sort=True).agg(
        available_at=("available_at", "first"),
        available_at_count=("available_at", "nunique"),
        data_week_ending=("data_week_ending", "first"),
        data_week_count=("data_week_ending", "nunique"),
        raw_hash_count=("raw_sha256", "nunique"),
        component_rows=("item", "size"),
    )
    if (
        release_meta["available_at_count"].ne(1).any()
        or release_meta["data_week_count"].ne(1).any()
        or release_meta["raw_hash_count"].ne(1).any()
        or release_meta["component_rows"].gt(len(COMPONENTS)).any()
    ):
        raise ValueError("V17 EIA release metadata/component coverage is inconsistent")
    selected["component"] = [
        keys[(section, item)].name
        for section, item in selected[["section", "item"]].itertuples(index=False, name=None)
    ]
    values = selected.pivot(
        index="release_date", columns="component", values="reported_weekly_change"
    ).reindex(columns=[component.name for component in COMPONENTS])
    output = release_meta.loc[
        :, ["available_at", "data_week_ending", "component_rows"]
    ].copy()
    z_columns: list[str] = []
    for component in COMPONENTS:
        series = values[component.name]
        prior = series.shift(1)
        mean = prior.rolling(NORMALIZATION_WINDOW, min_periods=MINIMUM_HISTORY).mean()
        std = prior.rolling(NORMALIZATION_WINDOW, min_periods=MINIMUM_HISTORY).std(ddof=1)
        z = (series - mean) / std.where(std.gt(STD_FLOOR))
        z_column = f"z_{component.name}"
        output[z_column] = z.clip(-Z_CLIP, Z_CLIP)
        z_columns.append(z_column)
    complete = output[z_columns].notna().all(axis=1)
    signs = np.array([component.economic_sign for component in COMPONENTS], dtype=float)
    signed = output[z_columns].to_numpy(dtype=float) * signs
    composite = np.nansum(signed, axis=1) / float(len(COMPONENTS))
    output["eligible"] = complete
    output["composite"] = np.where(complete, composite, np.nan)
    output["direction"] = np.where(complete, np.sign(composite), np.nan)
    output["normalization_history_count"] = np.arange(len(output), dtype=int)
    return output.reset_index().sort_values("release_date", kind="mergesort", ignore_index=True)


@dataclass(frozen=True, slots=True)
class ReleaseDecisionBuild:
    decisions: pd.DataFrame
    weights: pd.DataFrame
    mapped_release_count: int
    same_session_collisions: int


def build_release_decisions(
    scores: pd.DataFrame,
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
) -> ReleaseDecisionBuild:
    """Wait for a complete MOEX decision session, then form a BR risk target."""
    market = v12.normalize_signal_panel(panel)
    br = market.loc[market["asset"].eq("BR")].set_index("trade_date")["close"]
    br_volatility = (
        np.log(br)
        .diff()
        .rolling(VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK)
        .std(ddof=1)
        * math.sqrt(float(ANNUALIZATION))
    )
    active = v12.normalize_active_map(active_map)
    active_dates = pd.DatetimeIndex(active["decision_date"].drop_duplicates().sort_values())
    decision_rows: list[dict[str, Any]] = []
    for row in scores.itertuples(index=False):
        if not bool(row.eligible):
            continue
        available_at = pd.Timestamp(row.available_at)
        local_date = available_at.tz_convert(MOSCOW).tz_localize(None).normalize()
        location = int(active_dates.searchsorted(local_date, side="left"))
        if location >= len(active_dates):
            decision_rows.append(
                {
                    **row._asdict(),
                    "decision_date": pd.NaT,
                    "decision_at": pd.NaT,
                    "annualized_br_volatility": np.nan,
                    "target_weight": np.nan,
                    "decision_status": "no_future_active_decision_session",
                }
            )
            continue
        decision_date = pd.Timestamp(active_dates[location])
        decision_at = (
            decision_date.tz_localize(MOSCOW)
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        ).tz_convert("UTC")
        if available_at > decision_at:
            raise ValueError("V17 release mapped before conservative availability")
        volatility = br_volatility.get(decision_date, np.nan)
        if pd.isna(volatility) or not math.isfinite(float(volatility)):
            target = np.nan
            status = "missing_prior_60_session_BR_volatility"
        else:
            risk_scale = min(
                MAXIMUM_ABSOLUTE_WEIGHT,
                TARGET_VOLATILITY / max(float(volatility), VOLATILITY_FLOOR),
            )
            target = float(row.direction) * risk_scale
            status = "mapped"
        decision_rows.append(
            {
                **row._asdict(),
                "decision_date": decision_date,
                "decision_at": decision_at,
                "annualized_br_volatility": volatility,
                "target_weight": target,
                "decision_status": status,
            }
        )
    decisions = pd.DataFrame(decision_rows).sort_values(
        ["decision_date", "available_at"], kind="mergesort", na_position="last"
    )
    mapped = decisions.loc[decisions["decision_status"].eq("mapped")].copy()
    collisions = int(mapped.duplicated("decision_date", keep="last").sum())
    mapped = mapped.drop_duplicates("decision_date", keep="last")
    weight_rows: list[dict[str, Any]] = []
    for row in mapped.itertuples(index=False):
        provenance = json.dumps(
            {
                "version": "v17_eia_supply_demand_v1",
                "release_date": row.release_date.date().isoformat(),
                "available_at": row.available_at.isoformat(),
                "decision_at": row.decision_at.isoformat(),
                "composite": float(row.composite),
                "annualized_br_volatility": float(row.annualized_br_volatility),
                "contains_prices_returns_targets_or_pnl_from_2026": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for asset in v12.ASSETS:
            weight_rows.append(
                {
                    "decision_date": row.decision_date,
                    "asset": asset,
                    "target_weight": float(row.target_weight) if asset == "BR" else 0.0,
                    "provenance": provenance,
                }
            )
    weights = pd.DataFrame(weight_rows)
    if not weights.empty and weights.groupby("decision_date")["asset"].nunique().ne(
        len(v12.ASSETS)
    ).any():
        raise ValueError("V17 release weights are not complete four-asset snapshots")
    return ReleaseDecisionBuild(
        decisions=decisions.reset_index(drop=True),
        weights=weights.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        mapped_release_count=len(mapped),
        same_session_collisions=collisions,
    )


def _scenario_settings(protocol: dict[str, Any]) -> dict[str, dict[str, float]]:
    output = {
        str(name): {
            "slippage_ticks": int(values["slippage_ticks_per_leg"]),
            "fee_multiplier": float(values["conservative_fee_multiplier"]),
        }
        for name, values in protocol["execution"]["scenarios"].items()
    }
    expected = {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }
    if output != expected:
        raise ValueError("V17 cost scenarios drifted from the seal")
    return output


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    decision_counts_by_year: dict[str, int],
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    release_count = sum(decision_counts_by_year.values())
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "at_least_250_release_decisions_and_45_each_oos_year": release_count >= 250
        and all(decision_counts_by_year.get(str(year), 0) >= 45 for year in range(2021, 2026)),
        "all_three_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in scenario_results.values()
        ),
        "zero_critical_failures_and_zero_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0
            and int(value["unresolved_halt_count"]) == 0
            for value in scenario_results.values()
        ),
        "primary_cagr_at_least_0_05": float(primary["cagr"]) >= 0.05,
        "primary_sharpe_at_least_0_75": float(primary["sharpe"]) >= 0.75,
        "primary_maximum_drawdown_at_most_0_20": float(primary["maximum_drawdown"]) <= 0.20,
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "doubled_total_return_positive": float(scenario_results["doubled"]["total_return"])
        > 0.0,
        "stress_total_return_positive": float(scenario_results["stress"]["total_return"])
        > 0.0,
        "no_gross_participation_or_margin_breach": all(
            float(value["maximum_participation"]) <= MAXIMUM_PARTICIPATION + 1e-12
            and float(value["ending_cash"]) > 0.0
            for value in scenario_results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_UNSEEN_VALIDATION" if passed else "NO_GO",
        "live_trading_allowed": False,
        "independent_confirmation_required": True,
    }


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False, compression="zstd")


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V17 EIA physical-balance direction",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "This is a new release-vintage information family but the same previously seen "
            "2021-2025 market period, not an independent holdout."
        ),
        "",
        "| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        lines.append(
            f"| {name} | {item['total_return']:.4%} | {item['cagr']:.4%} | "
            f"{item['sharpe']:.3f} | {item['maximum_drawdown']:.4%} | "
            f"{item['positive_years']}/5 | {item['total_cost']:.2f} | "
            f"{item['execution_complete']} |"
        )
    lines.extend(["", "## Primary annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Signal and execution",
            "",
            f"- Eligible EIA releases: {counts['eligible_source_releases']}",
            f"- OOS release decisions by year: {counts['release_decisions_by_year']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Non-zero target dependencies: {counts['nonzero_targets']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "The EIA timestamp is conservatively delayed to end-of-release-day New York; "
            "the signal then waits for a completed MOEX decision session and enters at the "
            "following factual open.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V17 run after all source and protocol identities pass."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    eia = pd.read_parquet(
        verified.paths["eia_table1"],
        columns=protocol["inputs"]["eia_table1"]["allowed_columns"],
    )
    source_scores = build_source_scores(eia)
    panel = pd.read_parquet(
        verified.paths["panel"], columns=protocol["inputs"]["panel"]["allowed_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    release_build = build_release_decisions(source_scores, panel, active)
    if release_build.weights.empty:
        raise ValueError("V17 produced no mapped release weights")
    target_build = v12.build_execution_targets(release_build.weights, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, OOS_END)
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in _scenario_settings(protocol).items():
        result = run_futures_portfolio_ledger(
            execution_market,
            target_build.targets,
            FuturesPortfolioLedgerConfig(
                initial_cash=INITIAL_CASH,
                expected_assets=v12.ASSETS,
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=MAXIMUM_PARTICIPATION,
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
                execution_atomicity="asset",
                terminal_policy="carry",
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name] = v12.scenario_metrics(result, execution_market, settings)

    decisions = release_build.decisions.loc[
        release_build.decisions["decision_status"].eq("mapped")
        & pd.to_datetime(release_build.decisions["decision_date"]).between(OOS_START, OOS_END)
    ].copy()
    decision_counts_by_year = {
        str(key): int(value)
        for key, value in pd.to_datetime(decisions["decision_date"]).dt.year.value_counts().items()
    }
    checks = dict(verified.checks)
    checks["source_scores_available_before_2026"] = bool(
        pd.to_datetime(source_scores["available_at"], utc=True).lt(PROTECTED_FROM).all()
    )
    checks["mapped_decisions_after_availability"] = bool(
        (
            pd.to_datetime(release_build.decisions.loc[decisions.index, "available_at"], utc=True)
            <= pd.to_datetime(release_build.decisions.loc[decisions.index, "decision_at"], utc=True)
        ).all()
    )
    checks["no_same_session_collisions"] = release_build.same_session_collisions == 0
    checks["all_selected_components_present"] = bool(
        source_scores.loc[source_scores["eligible"], "component_rows"].eq(len(COMPONENTS)).all()
    )
    counts = {
        "eia_source_rows": len(eia),
        "eia_source_releases": int(source_scores["release_date"].nunique()),
        "eligible_source_releases": int(source_scores["eligible"].sum()),
        "mapped_release_decisions_all_dates": release_build.mapped_release_count,
        "same_session_collisions": release_build.same_session_collisions,
        "release_decisions_by_year": decision_counts_by_year,
        "weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": len(target_build.targets),
        "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    promotion = _promotion(scenario_results, checks, decision_counts_by_year)
    code_paths = {
        "v17_implementation": Path(__file__).resolve(),
        "eia_source": PROJECT_ROOT / "src/market_lab/futures/eia_wpsr_source.py",
        "v12_parent": Path(v12.__file__).resolve(),
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v12_protocol_sha256": v12.CONFIG_SHA256,
        "input_sha256": {
            name: declaration["sha256"]
            for name, declaration in protocol["inputs"].items()
        },
        "code_sha256": {name: sha256_file(path) for name, path in code_paths.items()},
        "protected_from": PROTECTED_FROM.isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_market_period": True,
        "new_release_vintage_information_family": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v17_eia_supply_demand_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V17 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "source_scores.parquet", source_scores)
        _write_parquet(temporary / "release_decisions.parquet", release_build.decisions)
        _write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            _write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            _write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            _write_parquet(temporary / f"positions_{name}.parquet", result.positions)
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
            json.dumps(
                _json_safe({**identity, "metrics_sha256": sha256_file(metrics_path)}),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs",
        help="External immutable runs root; a unique V17 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
