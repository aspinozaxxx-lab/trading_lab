"""Sealed V58 CFTC WTI positioning-flow test on MOEX Brent futures."""

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
from typing import Any, Final, Literal

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab.futures import portfolio_ledger as ledger_engine
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v58_cftc_wti_positioning_br.yaml"
CONFIG_SHA256: Final[str] = "637eb6c44991b8f07b5c74cd844fa4178c8d4f0cc5fe3378c2dc11ebbb26fc31"
ASSET: Final[str] = "BR"
CFTC_MARKET: Final[str] = "WTI"
LOOKBACK_REPORTS: Final[int] = 13
VOLATILITY_LOOKBACK: Final[int] = 20
TREND_LOOKBACK: Final[int] = 63
ANNUALIZATION: Final[int] = 252
VOLATILITY_TARGET: Final[float] = 0.30
MAXIMUM_TARGET: Final[float] = 2.0
MAXIMUM_SOURCE_AGE_DAYS: Final[int] = 14
INITIAL_CASH: Final[float] = 1_000_000.0
MAXIMUM_PARTICIPATION: Final[float] = 0.01
MARGIN_BUFFER: Final[float] = 2.0
EVALUATION_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
EVALUATION_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-30")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
_BASE_TARGET_NORMALIZER = ledger_engine._normalize_targets


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _resolved(relative_value: str, *, first: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V58 path: {relative_value}")
    if relative.parts[0].lower() != first:
        raise ValueError(f"V58 path must be below {first}: {relative_value}")
    resolved = (PROJECT_ROOT / relative).resolve()
    root = (PROJECT_ROOT / first).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"V58 path escapes {first}: {relative_value}")
    return resolved


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V58 protocol byte drift")
    stated = config_path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V58 protocol sidecar drift")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("V58 protocol must be a mapping")
    signal = protocol["signal"]
    risk = protocol["risk"]
    execution = protocol["execution"]
    gates = protocol["promotion_gates"]
    if (
        protocol.get("protocol_id") != "futures_v58_cftc_wti_positioning_br_v1"
        or protocol.get("status") != "sealed_after_cftc_source_audit_before_any_v58_br_outcome"
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["protected_from"]) != "2026-01-01"
        or signal["target_asset"] != ASSET
        or signal["cftc_market"] != CFTC_MARKET
        or int(signal["lookback_admitted_reports"]) != LOOKBACK_REPORTS
        or int(signal["maximum_source_age_calendar_days"]) != MAXIMUM_SOURCE_AGE_DAYS
        or signal["direction"] != "positive_long_negative_short_exact_zero_cash"
        or int(risk["BR_log_return_volatility_lookback_sessions"]) != VOLATILITY_LOOKBACK
        or float(risk["annual_volatility_target"]) != VOLATILITY_TARGET
        or float(risk["maximum_absolute_target"]) != MAXIMUM_TARGET
        or protocol["baseline"]["price_only_63_session_trend"]["signal"]
        != "sign_of_current_BR_close_div_BR_close_63_sessions_ago_minus_1"
        or float(execution["maximum_participation_of_prior_contract_volume"])
        != MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != MAXIMUM_TARGET
        or float(execution["initial_margin_buffer_multiple"]) != MARGIN_BUFFER
        or float(execution["initial_cash_rub"]) != INITIAL_CASH
        or float(gates["all_scenarios_cagr_gte"]) != 0.20
        or float(gates["primary_sharpe_gte"]) != 1.0
        or float(gates["all_scenarios_maximum_drawdown_lte"]) != 0.30
        or int(gates["primary_positive_calendar_years_gte"]) != 4
    ):
        raise ValueError("sealed V58 economics drifted")
    expected_scenarios = {
        "primary": {"slippage_ticks_per_leg": 1, "conservative_fee_multiplier": 1.0},
        "doubled": {"slippage_ticks_per_leg": 2, "conservative_fee_multiplier": 2.0},
        "stress": {"slippage_ticks_per_leg": 4, "conservative_fee_multiplier": 2.0},
    }
    if execution["scenarios"] != expected_scenarios:
        raise ValueError("V58 cost scenarios drifted")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify every identity and date boundary before loading market values."""
    checks: dict[str, bool] = {"protocol_seal": sha256_file(CONFIG_PATH) == CONFIG_SHA256}
    paths: dict[str, Path] = {}
    metadata: dict[str, Any] = {}
    file_inputs = (
        "cftc_positions",
        "cftc_manifest",
        "cftc_raw",
        "cftc_audit",
        "panel",
        "active_contract_map",
        "contract_observations",
        "spec_proxy",
    )
    for name in file_inputs:
        declaration = protocol["inputs"][name]
        path = _resolved(str(declaration["path"]), first="data")
        paths[name] = path
        exists = path.is_file()
        actual_hash = sha256_file(path) if exists else None
        checks[f"{name}_exists"] = exists
        checks[f"{name}_sha256"] = exists and actual_hash == declaration["sha256"]
        if "bytes" in declaration:
            checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        metadata[name] = {
            "path": declaration["path"],
            "bytes": path.stat().st_size if exists else None,
            "sha256": actual_hash,
        }
        if exists and path.suffix == ".parquet":
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_schema"] = set(declaration["allowed_columns"]) <= set(
                parquet.schema_arrow.names
            )
    for name, declaration in protocol["inputs"]["inherited_code"].items():
        path = _resolved(str(declaration["path"]), first="src")
        paths[f"code_{name}"] = path
        checks[f"code_{name}_sha256"] = (
            path.is_file() and sha256_file(path) == declaration["sha256"]
        )
    if not all(checks.values()):
        raise ValueError(f"V58 identity preflight failed: {checks}")

    manifest = json.loads(paths["cftc_manifest"].read_text(encoding="utf-8-sig"))
    audit = json.loads(paths["cftc_audit"].read_text(encoding="utf-8-sig"))
    checks.update(
        {
            "cftc_protocol_exact": manifest["protocol_sha256"]
            == protocol["inputs"]["cftc_protocol_sha256"],
            "cftc_implementation_exact": manifest["implementation_sha256"]
            == protocol["inputs"]["cftc_implementation_sha256"],
            "cftc_source_only": manifest["source_only"] is True,
            "cftc_outcomes_absent": manifest[
                "contains_moex_price_return_target_signal_trade_or_pnl"
            ]
            is False,
            "cftc_audit_all_true": audit["all_true"] is True and all(audit["checks"].values()),
        }
    )
    date_specs = {
        "cftc_positions": ("report_date", "minimum_report_date", "maximum_report_date"),
        "panel": ("trade_date", "minimum_timestamp", "maximum_timestamp"),
        "contract_observations": ("trade_date", "minimum_timestamp", "maximum_timestamp"),
        "spec_proxy": ("session_date", "minimum_timestamp", "maximum_timestamp"),
    }
    for name, (column, minimum_key, maximum_key) in date_specs.items():
        dates = pd.to_datetime(
            pd.read_parquet(paths[name], columns=[column])[column], errors="raise"
        )
        declaration = protocol["inputs"][name]
        checks[f"{name}_date_min"] = dates.min() == pd.Timestamp(declaration[minimum_key])
        checks[f"{name}_date_max"] = dates.max() == pd.Timestamp(declaration[maximum_key])
        checks[f"{name}_protected"] = bool(dates.lt(PROTECTED_FROM).all())
    active_dates = pd.read_parquet(
        paths["active_contract_map"], columns=["decision_date", "effective_date"]
    )
    decision = pd.to_datetime(active_dates["decision_date"], errors="coerce")
    effective = pd.to_datetime(active_dates["effective_date"], errors="raise")
    active_spec = protocol["inputs"]["active_contract_map"]
    checks["active_decision_max"] = decision.max() == pd.Timestamp(
        active_spec["decision_maximum_timestamp"]
    )
    checks["active_effective_max"] = effective.max() == pd.Timestamp(
        active_spec["effective_maximum_timestamp"]
    )
    checks["active_protected"] = bool(
        decision.dropna().lt(PROTECTED_FROM).all() and effective.lt(PROTECTED_FROM).all()
    )
    if not all(checks.values()):
        raise ValueError(f"V58 temporal/source preflight failed: {checks}")
    return VerifiedInputs(paths=paths, checks=checks, metadata=metadata)


def _normalize_br_panel(panel: pd.DataFrame) -> pd.DataFrame:
    normalized = v12.normalize_signal_panel(panel)
    br = normalized.loc[normalized["asset"].eq(ASSET), ["trade_date", "close"]].copy()
    if br.empty or br["trade_date"].duplicated().any():
        raise ValueError("V58 BR panel is empty or duplicated")
    return br.sort_values("trade_date", kind="mergesort", ignore_index=True)


def _normalize_cftc(cftc: pd.DataFrame) -> pd.DataFrame:
    required = {
        "report_date",
        "available_at_utc",
        "logical_market",
        "open_interest",
        "managed_money_long",
        "managed_money_short",
    }
    if missing := required - set(cftc.columns):
        raise ValueError(f"V58 CFTC frame lacks: {sorted(missing)}")
    frame = cftc.loc[:, sorted(required)].copy()
    frame = frame.loc[frame["logical_market"].astype("string").eq(CFTC_MARKET)].copy()
    frame["report_date"] = pd.to_datetime(frame["report_date"], errors="raise").dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(frame["available_at_utc"], errors="raise", utc=True)
    for column in ("open_interest", "managed_money_long", "managed_money_short"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    if (
        frame.empty
        or frame["report_date"].ge(PROTECTED_FROM).any()
        or frame.duplicated("report_date").any()
        or not frame["open_interest"].gt(0.0).all()
        or frame[["managed_money_long", "managed_money_short"]].lt(0.0).any(axis=None)
    ):
        raise ValueError("V58 WTI CFTC source failed structural validation")
    frame = frame.sort_values("report_date", kind="mergesort", ignore_index=True)
    frame["net_share"] = (frame["managed_money_long"] - frame["managed_money_short"]) / frame[
        "open_interest"
    ]
    frame["net_share_lag_13"] = frame["net_share"].shift(LOOKBACK_REPORTS)
    frame["position_change_13"] = frame["net_share"] - frame["net_share_lag_13"]
    return frame


def build_weekly_signals(panel: pd.DataFrame, cftc: pd.DataFrame) -> pd.DataFrame:
    """Create the one sealed weekly candidate and its price-only baseline."""
    br = _normalize_br_panel(panel).set_index("trade_date")
    log_close = np.log(br["close"])
    br["annualized_log_volatility_20"] = log_close.diff().rolling(
        VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK
    ).std(ddof=1) * np.sqrt(float(ANNUALIZATION))
    br["trend_63"] = log_close - log_close.shift(TREND_LOOKBACK)
    all_dates = pd.DatetimeIndex(br.index)
    weekly_dates = pd.DatetimeIndex(
        pd.Series(all_dates, index=all_dates).groupby(all_dates.to_period("W-SUN")).max().to_numpy()
    )
    positions = _normalize_cftc(cftc)
    rows: list[dict[str, Any]] = []
    for decision_date in weekly_dates:
        local = pd.Timestamp(decision_date).tz_localize("Europe/Moscow") + pd.Timedelta(
            hours=23, minutes=59, seconds=59
        )
        decision_at_utc = local.tz_convert("UTC")
        admitted = positions.loc[positions["available_at_utc"].le(decision_at_utc)]
        latest = admitted.iloc[-1] if not admitted.empty else None
        source_age = (
            int((decision_date - pd.Timestamp(latest["report_date"])).days)
            if latest is not None
            else None
        )
        current = br.loc[decision_date]
        volatility = float(current["annualized_log_volatility_20"])
        usable_risk = math.isfinite(volatility) and volatility > 0.0
        absolute_target = (
            min(MAXIMUM_TARGET, VOLATILITY_TARGET / volatility) if usable_risk else 0.0
        )
        feature = (
            float(latest["position_change_13"])
            if latest is not None and pd.notna(latest["position_change_13"])
            else math.nan
        )
        source_fresh = source_age is not None and 0 <= source_age <= MAXIMUM_SOURCE_AGE_DAYS
        candidate_sign = float(np.sign(feature)) if source_fresh and math.isfinite(feature) else 0.0
        trend = float(current["trend_63"])
        baseline_sign = float(np.sign(trend)) if math.isfinite(trend) else 0.0
        rows.append(
            {
                "decision_date": decision_date,
                "decision_at_utc": decision_at_utc,
                "cftc_report_date": pd.Timestamp(latest["report_date"])
                if latest is not None
                else pd.NaT,
                "cftc_available_at_utc": latest["available_at_utc"]
                if latest is not None
                else pd.NaT,
                "cftc_source_age_days": source_age,
                "wti_net_share": float(latest["net_share"]) if latest is not None else math.nan,
                "wti_net_share_lag_13": float(latest["net_share_lag_13"])
                if latest is not None and pd.notna(latest["net_share_lag_13"])
                else math.nan,
                "position_change_13": feature,
                "br_close": float(current["close"]),
                "br_annualized_log_volatility_20": volatility,
                "br_trend_63": trend,
                "candidate_sign": candidate_sign,
                "candidate_target_weight": candidate_sign * absolute_target,
                "baseline_sign": baseline_sign,
                "baseline_target_weight": baseline_sign * absolute_target,
                "source_fresh": source_fresh,
                "risk_usable": usable_risk,
            }
        )
    output = pd.DataFrame(rows)
    if output["decision_date"].ge(PROTECTED_FROM).any():
        raise ValueError("V58 weekly signal touches protected date")
    used = output["candidate_sign"].ne(0.0)
    if output.loc[used, "cftc_available_at_utc"].gt(
        output.loc[used, "decision_at_utc"]
    ).any() or output[["candidate_target_weight", "baseline_target_weight"]].abs().gt(
        MAXIMUM_TARGET + 1e-12
    ).any(axis=None):
        raise ValueError("V58 signal violates timing or target cap")
    return output.sort_values("decision_date", kind="mergesort", ignore_index=True)


@dataclass(frozen=True, slots=True)
class TargetBuild:
    targets: pd.DataFrame
    decision_audit: pd.DataFrame
    weekly_decisions: int
    roll_decisions: int


def build_execution_targets(
    signals: pd.DataFrame,
    active_map: pd.DataFrame,
    target_column: str,
    *,
    evaluation_start: pd.Timestamp = EVALUATION_START,
    evaluation_end: pd.Timestamp = EVALUATION_END,
) -> TargetBuild:
    if target_column not in {"candidate_target_weight", "baseline_target_weight"}:
        raise ValueError("unknown V58 target column")
    active = v12.normalize_active_map(active_map)
    active = active.loc[active["asset"].eq(ASSET)].copy()
    weights = signals.loc[:, ["decision_date", target_column]].copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    weights = weights.drop_duplicates("decision_date").set_index("decision_date")[target_column]
    active_dates = pd.DatetimeIndex(active["decision_date"].drop_duplicates().sort_values())
    carried = weights.reindex(active_dates).ffill().fillna(0.0)
    active_indexed = active.set_index("decision_date").reindex(active_dates)
    contracts = active_indexed["contract_id"]
    changed = contracts.ne(contracts.shift(1)) & contracts.notna() & contracts.shift(1).notna()
    roll_needed = (active_indexed["roll"].astype(bool) | changed) & carried.abs().gt(1e-12)
    weekly_event = pd.Series(active_dates.isin(weights.index), index=active_dates)
    selected_dates = active_dates[weekly_event | roll_needed]
    selected = active_indexed.loc[selected_dates].reset_index()
    selected["target_weight"] = carried.reindex(selected_dates).to_numpy(dtype=float)
    unavailable = ~selected["tradable"] | selected["contract_id"].isna()
    selected.loc[unavailable, "target_weight"] = 0.0
    selected.loc[selected["target_weight"].abs().le(1e-12), "contract_id"] = pd.NA
    targets = selected.loc[
        :, ["effective_date", "decision_date", "observed_through", "contract_id", "target_weight"]
    ].copy()
    targets["asset_code"] = ASSET
    targets["provenance"] = target_column
    targets = targets.loc[targets["effective_date"].between(evaluation_start, evaluation_end)]
    targets = targets.sort_values("effective_date", kind="mergesort", ignore_index=True)
    audit = pd.DataFrame(
        {
            "decision_date": selected_dates,
            "weekly_rebalance": weekly_event.reindex(selected_dates).to_numpy(dtype=bool),
            "roll_required": roll_needed.reindex(selected_dates).to_numpy(dtype=bool),
        }
    )
    effective_lookup = active_indexed["effective_date"]
    audit["effective_date"] = audit["decision_date"].map(effective_lookup)
    audit = audit.loc[
        audit["effective_date"].between(evaluation_start, evaluation_end)
    ].reset_index(drop=True)
    if targets["target_weight"].abs().gt(MAXIMUM_TARGET + 1e-12).any():
        raise ValueError("V58 mapped target exceeds 2x")
    return TargetBuild(
        targets=targets,
        decision_audit=audit,
        weekly_decisions=int(audit["weekly_rebalance"].sum()),
        roll_decisions=int((~audit["weekly_rebalance"] & audit["roll_required"]).sum()),
    )


@dataclass(frozen=True, slots=True)
class V58LedgerConfig:
    initial_cash: float = INITIAL_CASH
    expected_assets: tuple[str, ...] = (ASSET,)
    maximum_gross_notional_multiple: float = MAXIMUM_TARGET
    initial_margin_buffer_multiplier: float = MARGIN_BUFFER
    maximum_participation: float = MAXIMUM_PARTICIPATION
    slippage_ticks: Literal[1, 2, 4] = 1
    fee_multiplier: Literal[1.0, 2.0] = 1.0
    execution_atomicity: Literal["asset"] = "asset"
    terminal_policy: Literal["carry"] = "carry"
    unexecutable_target_policy: Literal["retry"] = "retry"

    def __post_init__(self) -> None:
        if (
            self.initial_cash != INITIAL_CASH
            or self.expected_assets != (ASSET,)
            or self.maximum_gross_notional_multiple != MAXIMUM_TARGET
            or self.initial_margin_buffer_multiplier != MARGIN_BUFFER
            or self.maximum_participation != MAXIMUM_PARTICIPATION
            or self.slippage_ticks not in {1, 2, 4}
            or self.fee_multiplier not in {1.0, 2.0}
        ):
            raise ValueError("V58 ledger config drift")


def _normalize_levered_targets(
    targets: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    expected_assets: tuple[str, ...],
) -> pd.DataFrame:
    scaled = targets.copy()
    scaled["target_weight"] = (
        pd.to_numeric(scaled["target_weight"], errors="raise") / MAXIMUM_TARGET
    )
    normalized = _BASE_TARGET_NORMALIZER(scaled, calendar, expected_assets)
    normalized["target_weight"] *= MAXIMUM_TARGET
    return normalized


def run_v58_ledger(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    config: V58LedgerConfig,
) -> FuturesPortfolioLedgerResult:
    original = ledger_engine._normalize_targets
    if original is not _BASE_TARGET_NORMALIZER:
        raise RuntimeError("V58 refuses a nested target-normalizer replacement")
    ledger_engine._normalize_targets = _normalize_levered_targets
    try:
        return ledger_engine.run_futures_portfolio_ledger(market, targets, config)
    finally:
        ledger_engine._normalize_targets = original


def _scenario_settings(protocol: dict[str, Any]) -> dict[str, dict[str, float]]:
    return {
        name: {
            "slippage_ticks": int(values["slippage_ticks_per_leg"]),
            "fee_multiplier": float(values["conservative_fee_multiplier"]),
        }
        for name, values in protocol["execution"]["scenarios"].items()
    }


def _promotion(results: dict[str, dict[str, Any]], checks: dict[str, bool]) -> dict[str, Any]:
    primary = results["primary"]
    conditions = {
        "all_input_and_temporal_checks_true": all(checks.values()),
        "all_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in results.values()
        ),
        "all_scenarios_cagr_at_least_0_20": all(
            float(value["cagr"]) >= 0.20 for value in results.values()
        ),
        "primary_sharpe_at_least_1_0": float(primary["sharpe"]) >= 1.0,
        "all_scenarios_maximum_drawdown_at_most_0_30": all(
            float(value["maximum_drawdown"]) <= 0.30 for value in results.values()
        ),
        "primary_positive_years_at_least_4": int(primary["positive_years"]) >= 4,
        "zero_critical_failures_and_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0 and int(value["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed_minimum_20_percent_gate": passed,
        "aspirational_primary_50_percent_reached": float(primary["cagr"]) >= 0.50,
        "verdict": "PROMISING_REQUIRES_UNSEEN_CONFIRMATION" if passed else "NO_GO",
        "live_trading_allowed": False,
    }


@dataclass(frozen=True, slots=True)
class Computation:
    signals: pd.DataFrame
    candidate_targets: TargetBuild
    baseline_targets: TargetBuild
    execution_market: pd.DataFrame
    candidate_outputs: dict[str, FuturesPortfolioLedgerResult]
    baseline_outputs: dict[str, FuturesPortfolioLedgerResult]
    metrics: dict[str, Any]


def compute(protocol: dict[str, Any], verified: VerifiedInputs) -> Computation:
    panel = pd.read_parquet(
        verified.paths["panel"], columns=protocol["inputs"]["panel"]["allowed_columns"]
    )
    cftc = pd.read_parquet(
        verified.paths["cftc_positions"],
        columns=protocol["inputs"]["cftc_positions"]["allowed_columns"],
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
        verified.paths["spec_proxy"], columns=protocol["inputs"]["spec_proxy"]["allowed_columns"]
    )
    signals = build_weekly_signals(panel, cftc)
    candidate_targets = build_execution_targets(signals, active, "candidate_target_weight")
    baseline_targets = build_execution_targets(signals, active, "baseline_target_weight")
    market = v12.build_execution_market(observations, specs)
    market = market.loc[market["asset_code"].eq(ASSET)].copy()
    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < EVALUATION_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, EVALUATION_END)
    ].copy()
    candidate_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    baseline_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    candidate_results: dict[str, dict[str, Any]] = {}
    baseline_results: dict[str, dict[str, Any]] = {}
    for name, settings in _scenario_settings(protocol).items():
        config = V58LedgerConfig(
            slippage_ticks=int(settings["slippage_ticks"]),
            fee_multiplier=float(settings["fee_multiplier"]),
        )
        candidate = run_v58_ledger(execution_market, candidate_targets.targets, config)
        baseline = run_v58_ledger(execution_market, baseline_targets.targets, config)
        candidate_outputs[name] = candidate
        baseline_outputs[name] = baseline
        candidate_results[name] = v12.scenario_metrics(candidate, execution_market, settings)
        baseline_results[name] = v12.scenario_metrics(baseline, execution_market, settings)
    promotion = _promotion(candidate_results, verified.checks)
    comparisons = {
        name: {
            "candidate_minus_price_baseline_cagr": float(candidate_results[name]["cagr"])
            - float(baseline_results[name]["cagr"]),
            "candidate_minus_price_baseline_sharpe": float(candidate_results[name]["sharpe"])
            - float(baseline_results[name]["sharpe"]),
        }
        for name in candidate_results
    }
    metrics = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
        "checks": verified.checks,
        "input_metadata": verified.metadata,
        "counts": {
            "weekly_signal_rows": int(len(signals)),
            "evaluation_weekly_decisions": candidate_targets.weekly_decisions,
            "candidate_roll_decisions": candidate_targets.roll_decisions,
            "candidate_nonzero_targets": int(
                candidate_targets.targets["target_weight"].abs().gt(1e-12).sum()
            ),
            "baseline_nonzero_targets": int(
                baseline_targets.targets["target_weight"].abs().gt(1e-12).sum()
            ),
        },
        "always_cash": {"cagr": 0.0, "sharpe": 0.0, "maximum_drawdown": 0.0},
        "candidate": candidate_results,
        "price_only_baseline": baseline_results,
        "comparisons": comparisons,
        "promotion": promotion,
        "limitations": protocol["limitations"],
    }
    return Computation(
        signals=signals,
        candidate_targets=candidate_targets,
        baseline_targets=baseline_targets,
        execution_market=execution_market,
        candidate_outputs=candidate_outputs,
        baseline_outputs=baseline_outputs,
        metrics=metrics,
    )


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False, compression="zstd")


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V58 CFTC WTI positioning → MOEX BR",
        "",
        f"Verdict: **{metrics['promotion']['verdict']}**.",
        "",
        "| Scenario | Candidate CAGR | Sharpe | MDD | Price baseline CAGR |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        candidate = metrics["candidate"][name]
        baseline = metrics["price_only_baseline"][name]
        lines.append(
            f"| {name} | {candidate['cagr']:.4%} | {candidate['sharpe']:.4f} | "
            f"{candidate['maximum_drawdown']:.4%} | {baseline['cagr']:.4%} |"
        )
    lines.extend(
        [
            "",
            "The run is adaptive historical research, uses no 2026+ market outcome, and does not "
            "authorize live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    computed = compute(protocol, verified)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v58_cftc_wti_positioning_br_v1_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"immutable V58 run exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "signals.parquet", computed.signals)
        _write_parquet(temporary / "candidate_targets.parquet", computed.candidate_targets.targets)
        _write_parquet(temporary / "baseline_targets.parquet", computed.baseline_targets.targets)
        computed.candidate_targets.decision_audit.to_csv(
            temporary / "candidate_decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        computed.baseline_targets.decision_audit.to_csv(
            temporary / "baseline_decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        for arm, outputs in (
            ("candidate", computed.candidate_outputs),
            ("baseline", computed.baseline_outputs),
        ):
            for scenario, result in outputs.items():
                _write_parquet(temporary / f"{arm}_ledger_{scenario}.parquet", result.ledger)
                _write_parquet(temporary / f"{arm}_orders_{scenario}.parquet", result.orders)
                _write_parquet(temporary / f"{arm}_positions_{scenario}.parquet", result.positions)
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(_json_safe(computed.metrics), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "report.md").write_text(_report(computed.metrics), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            entry: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        manifest = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": sha256_file(Path(__file__)),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "contains_2026_prices_returns_targets_or_pnl": False,
            "artifacts": artifacts,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
        )
        (temporary / "manifest.sha256").write_text(
            f"{sha256_file(temporary / 'manifest.json')}  manifest.json\n", encoding="utf-8-sig"
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    audit = audit_run(final, replay=computed)
    (final / "audit.json").write_text(
        json.dumps(_json_safe(audit), ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
    )
    if not audit["all_true"]:
        raise ValueError("V58 run audit failed")
    return final


def audit_run(run_root: Path, *, replay: Computation | None = None) -> dict[str, Any]:
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    computed = replay or compute(protocol, verified)
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "protocol_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == sha256_file(Path(__file__)),
        "manifest_sidecar_exact": (run_root / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == sha256_file(manifest_path),
        "protected_outcomes_absent": manifest["contains_2026_prices_returns_targets_or_pnl"]
        is False,
        "artifacts_exact": all(
            (run_root / name).is_file() and sha256_file(run_root / name) == declaration["sha256"]
            for name, declaration in manifest["artifacts"].items()
        ),
    }
    expected_frames = {
        "signals.parquet": computed.signals,
        "candidate_targets.parquet": computed.candidate_targets.targets,
        "baseline_targets.parquet": computed.baseline_targets.targets,
    }
    for arm, outputs in (
        ("candidate", computed.candidate_outputs),
        ("baseline", computed.baseline_outputs),
    ):
        for scenario, result in outputs.items():
            expected_frames[f"{arm}_ledger_{scenario}.parquet"] = result.ledger
            expected_frames[f"{arm}_orders_{scenario}.parquet"] = result.orders
            expected_frames[f"{arm}_positions_{scenario}.parquet"] = result.positions
    for name, expected in expected_frames.items():
        try:
            pd.testing.assert_frame_equal(
                pd.read_parquet(run_root / name), expected, check_dtype=False, check_like=False
            )
            checks[f"replay_{name}"] = True
        except AssertionError:
            checks[f"replay_{name}"] = False
    metrics = json.loads((run_root / "metrics.json").read_text(encoding="utf-8-sig"))
    checks["metrics_replay_exact"] = _json_safe(computed.metrics) == metrics
    checks["signal_dates_protected"] = bool(
        pd.read_parquet(run_root / "signals.parquet", columns=["decision_date"])["decision_date"]
        .lt(PROTECTED_FROM)
        .all()
    )
    return {"checks": checks, "all_true": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.audit:
        audit = audit_run(args.audit)
        print(json.dumps(audit, indent=2, sort_keys=True))
        raise SystemExit(0 if audit["all_true"] else 1)
    print(run_experiment(args.output_root))


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "CONFIG_SHA256",
    "V58LedgerConfig",
    "audit_run",
    "build_execution_targets",
    "build_weekly_signals",
    "load_protocol",
    "run_experiment",
    "run_v58_ledger",
]
