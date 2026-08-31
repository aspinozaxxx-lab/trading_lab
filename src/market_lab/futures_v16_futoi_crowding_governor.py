"""Sealed V16 frozen trend with FUTOI crowding risk and causal collateral income."""

from __future__ import annotations

import argparse
import json
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
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v16_futoi_crowding_governor.yaml"
CONFIG_SHA256: Final[str] = (
    "d04617756a8226ecc2900a0f3f4036e5891903a65bb722608b276908d803c070"
)
V12_PROTOCOL_SHA256: Final[str] = v12.CONFIG_SHA256
V12_METRICS_SHA256: Final[str] = v15.V12_METRICS_SHA256
V15_PROTOCOL_SHA256: Final[str] = v15.CONFIG_SHA256
V15_METRICS_SHA256: Final[str] = (
    "3f882e0b74e1b58fced362c3f4713f6c7641e7577964b51625d1b18d471298c4"
)
FUTOI_ROWS: Final[int] = 11_744
FUTOI_MIN_DATE: Final[pd.Timestamp] = pd.Timestamp("2020-05-04")
FUTOI_MAX_DATE: Final[pd.Timestamp] = pd.Timestamp("2025-12-30")
FUTOI_CLIENT_GROUP: Final[str] = "FIZ"
FUTOI_STALENESS_DAYS: Final[int] = 7
INVALIDATED_FUTOI_PIT_STATES: Final[int] = 932
TOTAL_FUTOI_OOS_STATES: Final[int] = 1_044
INVALIDATION_REASON: Final[str] = (
    "V16 invalidated: 932/1044 FUTOI states were not available by decision time; "
    "historical current-vintage SYSTIME was treated as if source_date proved availability"
)
ROBUST_Z_THRESHOLD: Final[float] = 1.0
AGGRESSIVE_MULTIPLIER: Final[float] = 2.0
DEFENSIVE_MULTIPLIER: Final[float] = 1.0
ROBUST_MAD_FACTOR: Final[float] = 1.4826
WARMUP_ROWS_PER_ASSET: Final[int] = 168
WARMUP_PARAMETERS: Final[dict[str, dict[str, float]]] = {
    "BR": {
        "median": 0.5920820972252733,
        "mad": 0.1116891258539566,
        "robust_scale": 0.16559029799107605,
    },
    "MIX": {
        "median": -0.3933774816785691,
        "mad": 0.09388476511449442,
        "robust_scale": 0.13919355275874942,
    },
    "RI": {
        "median": -0.3175171362049746,
        "mad": 0.12224024389835232,
        "robust_scale": 0.18123338560369714,
    },
    "SI": {
        "median": 0.527738756793166,
        "mad": 0.11931488089307662,
        "robust_scale": 0.17689624241207538,
    },
}
FUTOI_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "source_time",
    "observed_at",
    "published_at_moscow",
    "published_at",
    "available_at",
    "ticker",
    "asset_code",
    "client_group",
    "sess_id",
    "seqnum",
    "net_position",
    "long_position",
    "short_position",
    "long_accounts",
    "short_accounts",
    "reported_pair_net_imbalance",
    "reported_pair_balance_ratio",
    "reported_pair_balance_exact",
    "availability_rule",
    "provider",
    "contains_prices_returns_targets_or_pnl",
    "current_vintage_snapshot",
)


@dataclass(frozen=True, slots=True)
class CapacityAwareLeveredLedgerConfig:
    """V16 ledger settings with sealed 2x risk and causal capacity admission."""

    initial_cash: float = v12.INITIAL_CASH
    expected_assets: tuple[str, ...] = v12.ASSETS
    maximum_gross_notional_multiple: float = v15.MAXIMUM_GROSS
    initial_margin_buffer_multiplier: float = v15.MARGIN_BUFFER_MULTIPLIER
    maximum_participation: float = v12.MAXIMUM_PARTICIPATION
    slippage_ticks: Literal[1, 2, 4] = 1
    fee_multiplier: Literal[1.0, 2.0] = 1.0
    execution_atomicity: Literal["asset"] = "asset"
    terminal_policy: Literal["carry"] = "carry"
    unexecutable_target_policy: Literal["cancel_and_clip"] = "cancel_and_clip"

    def __post_init__(self) -> None:
        if (
            self.initial_cash != v12.INITIAL_CASH
            or self.expected_assets != v12.ASSETS
            or self.maximum_gross_notional_multiple != v15.MAXIMUM_GROSS
            or self.initial_margin_buffer_multiplier != v15.MARGIN_BUFFER_MULTIPLIER
            or self.maximum_participation != v12.MAXIMUM_PARTICIPATION
            or self.execution_atomicity != "asset"
            or self.terminal_policy != "carry"
            or self.unexecutable_target_policy != "cancel_and_clip"
        ):
            raise ValueError("V16 capacity-aware ledger settings drift")
        if self.slippage_ticks not in {1, 2, 4}:
            raise ValueError("V16 slippage must be 1, 2 or 4 ticks")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("V16 fee multiplier must be 1 or 2")


@dataclass(frozen=True, slots=True)
class FutoiVerification:
    """Identity- and time-checked target-free daily-last FUTOI source."""

    frame: pd.DataFrame
    checks: dict[str, bool]


@dataclass(frozen=True, slots=True)
class GovernorBuild:
    """Weekly FUTOI states and governed V12 weights."""

    frame: pd.DataFrame
    checks: dict[str, bool]


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every decision that cannot move after V16 PnL."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V16 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V16 sidecar does not match the code-pinned seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V16 protocol must be a mapping")
    parents = protocol["parents"]
    governor = protocol["futoi_governor"]
    collateral = protocol["collateral_income"]
    execution = protocol["execution"]
    declared_parameters = {
        str(asset): {str(key): float(value) for key, value in values.items()}
        for asset, values in governor["parameters"].items()
    }
    if (
        protocol.get("protocol_id") != "futures_v16_futoi_crowding_governor_v1"
        or protocol.get("status") != "predeclared_before_v16_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != v12.ASSETS
        or parents["v12_protocol_sha256"] != V12_PROTOCOL_SHA256
        or parents["v12_metrics_sha256"] != V12_METRICS_SHA256
        or parents["v15_protocol_sha256"] != V15_PROTOCOL_SHA256
        or parents["v15_metrics_sha256"] != V15_METRICS_SHA256
        or tuple(protocol["inputs"]["futoi_panel"]["allowed_columns"])
        != FUTOI_REQUIRED_COLUMNS
        or tuple(int(value) for value in protocol["signal"]["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(protocol["signal"]["volatility_lookback_sessions"])
        != v12.VOLATILITY_LOOKBACK
        or float(protocol["signal"]["volatility_floor_annualized"])
        != v12.VOLATILITY_FLOOR
        or governor["client_group"] != FUTOI_CLIENT_GROUP
        or int(governor["warmup_rows_per_asset"]) != WARMUP_ROWS_PER_ASSET
        or float(governor["robust_z_threshold"]) != ROBUST_Z_THRESHOLD
        or float(governor["aggressive_multiplier"]) != AGGRESSIVE_MULTIPLIER
        or float(governor["crowded_multiplier"]) != DEFENSIVE_MULTIPLIER
        or float(governor["missing_or_stale_multiplier"]) != DEFENSIVE_MULTIPLIER
        or declared_parameters != WARMUP_PARAMETERS
        or int(protocol["information_set"]["maximum_futoi_staleness_calendar_days"])
        != FUTOI_STALENESS_DAYS
        or float(collateral["applied_rate_fraction"]) != v15.RUONIA_APPLIED_FRACTION
        or float(collateral["operational_buffer_fraction_of_conservative_equity"])
        != v15.OPERATIONAL_BUFFER_FRACTION
        or collateral["day_count"] != "ACT_365_calendar_days"
        or collateral["reinvested_into_contract_sizing"] is not False
        or collateral["compounded_into_future_eligible_balance"] is not False
        or execution["unexecutable_target_policy"] != "cancel_and_clip"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(execution["initial_margin_buffer_multiple"])
        != v15.MARGIN_BUFFER_MULTIPLIER
    ):
        raise ValueError("sealed V16 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V16 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Verify all byte identities before price columns or outcomes are loaded."""
    verified = v12.verify_inputs(protocol)
    checks = dict(verified.checks)
    checks["v12_parent_protocol_seal"] = checks.pop("protocol_seal")
    checks["v16_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    manifest = json.loads(
        verified.paths["futoi_manifest"].read_text(encoding="utf-8-sig")
    )
    raw = manifest["artifacts"]["raw_archive"]
    declaration = protocol["inputs"]["futoi_manifest"]
    checks.update(
        {
            "futoi_manifest_source_id": manifest["source_id"]
            == "official-moex-futoi-current-vintage-2020-2025-v1",
            "futoi_manifest_request_count": int(manifest["request_count"])
            == int(declaration["request_count"]),
            "futoi_manifest_raw_sha256": raw["sha256"]
            == declaration["transitive_raw_sha256"],
            "futoi_manifest_raw_bytes": int(raw["bytes"])
            == int(declaration["transitive_raw_bytes"]),
            "futoi_manifest_target_free": manifest["temporal_semantics"][
                "contains_prices_returns_targets_or_pnl"
            ]
            is False,
            "futoi_manifest_not_full_intraday": manifest["temporal_semantics"][
                "full_intraday_history_downloaded"
            ]
            is False,
        }
    )
    if not all(checks.values()):
        raise ValueError(f"V16 input identity preflight failed: {checks}")
    return v12.VerifiedInputs(
        paths=verified.paths,
        checks=checks,
        metadata=verified.metadata,
    )


def _retail_imbalance(frame: pd.DataFrame) -> pd.Series:
    gross = frame["long_position"].astype(float) + frame["short_position"].astype(
        float
    ).abs()
    if gross.le(0.0).any() or not np.isfinite(gross).all():
        raise ValueError("V16 FUTOI retail gross position must be positive")
    return frame["net_position"].astype(float) / gross


def verify_futoi(frame: pd.DataFrame) -> FutoiVerification:
    """Fail closed on source identity, pairing, availability and warmup statistics."""
    if missing := set(FUTOI_REQUIRED_COLUMNS) - set(frame.columns):
        raise ValueError(f"V16 FUTOI lacks columns: {sorted(missing)}")
    source = frame.loc[:, list(FUTOI_REQUIRED_COLUMNS)].copy()
    if len(source) != FUTOI_ROWS:
        raise ValueError("V16 FUTOI row identity drift")
    source["source_date"] = pd.to_datetime(
        source["source_date"], errors="raise"
    ).dt.normalize()
    if (
        source["source_date"].min() != FUTOI_MIN_DATE
        or source["source_date"].max() != FUTOI_MAX_DATE
        or source["source_date"].ge(v12.PROTECTED_FROM).any()
    ):
        raise ValueError("V16 FUTOI source date boundary drift")
    for column in ("observed_at", "published_at", "available_at"):
        source[column] = pd.to_datetime(source[column], errors="raise", utc=True)
    protected_utc = pd.Timestamp("2026-01-01", tz=v15.MOSCOW_TIMEZONE).tz_convert("UTC")
    if source["available_at"].ge(protected_utc).any():
        raise ValueError("V16 FUTOI availability touches protected 2026")
    if source["published_at"].lt(source["observed_at"]).any() or not (
        source["available_at"] - source["published_at"]
    ).eq(pd.Timedelta(minutes=1)).all():
        raise ValueError("V16 FUTOI publication or delivery timing drift")
    if source.duplicated(["source_date", "asset_code", "client_group"]).any():
        raise ValueError("V16 FUTOI has duplicate daily asset/client rows")
    if set(source["asset_code"].astype(str)) != set(v12.ASSETS):
        raise ValueError("V16 FUTOI asset universe drift")
    paired = source.groupby(["source_date", "asset_code"], observed=True)
    if paired["client_group"].nunique().ne(2).any():
        raise ValueError("V16 FUTOI daily point lacks FIZ/YUR pair")
    if not source["provider"].astype("string").eq("MOEX ISS FUTOI").all():
        raise ValueError("V16 FUTOI provider drift")
    if not source["availability_rule"].astype("string").eq(
        "official_systime_plus_one_minute_delivery_buffer"
    ).all():
        raise ValueError("V16 FUTOI availability rule drift")
    if not source["contains_prices_returns_targets_or_pnl"].eq(False).all():  # noqa: E712
        raise ValueError("V16 FUTOI target-free flag drift")
    if not source["current_vintage_snapshot"].eq(True).all():  # noqa: E712
        raise ValueError("V16 FUTOI vintage flag drift")
    reported = paired["net_position"].transform("sum")
    if not reported.astype(float).eq(
        source["reported_pair_net_imbalance"].astype(float)
    ).all():
        raise ValueError("V16 FUTOI reported pair imbalance drift")

    retail = source.loc[source["client_group"].eq(FUTOI_CLIENT_GROUP)].copy()
    retail["retail_imbalance"] = _retail_imbalance(retail)
    warmup = retail.loc[retail["source_date"].le(pd.Timestamp("2020-12-31"))]
    for asset in v12.ASSETS:
        values = warmup.loc[warmup["asset_code"].eq(asset), "retail_imbalance"]
        if len(values) != WARMUP_ROWS_PER_ASSET:
            raise ValueError("V16 FUTOI warmup row identity drift")
        median = float(values.median())
        mad = float((values - median).abs().median())
        calculated = {
            "median": median,
            "mad": mad,
            "robust_scale": ROBUST_MAD_FACTOR * mad,
        }
        if any(
            not np.isclose(calculated[key], WARMUP_PARAMETERS[asset][key], rtol=0.0, atol=1e-15)
            for key in calculated
        ):
            raise ValueError(f"V16 FUTOI warmup parameters drift for {asset}")
    checks = {
        "futoi_rows_dates_and_schema_exact": True,
        "futoi_daily_pairs_unique": True,
        "futoi_publication_and_delivery_causal": True,
        "futoi_no_protected_availability": True,
        "futoi_target_free_current_vintage": True,
        "futoi_reported_imbalance_preserved": True,
        "futoi_warmup_parameters_exact": True,
    }
    return FutoiVerification(
        frame=source.sort_values(
            ["source_date", "asset_code", "client_group"],
            kind="mergesort",
            ignore_index=True,
        ),
        checks=checks,
    )


def build_futoi_governor(
    weekly_weights: pd.DataFrame,
    scores: pd.DataFrame,
    futoi: FutoiVerification,
) -> GovernorBuild:
    """Join strictly prior FUTOI and apply the one sealed asset-level risk state."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(weekly_weights.columns):
        raise ValueError(f"V16 weekly weights lack columns: {sorted(missing)}")
    weekly_scores = v12.weekly_score_snapshots(scores).loc[
        :, ["decision_date", "asset", "candidate_score"]
    ]
    base = weekly_weights.merge(
        weekly_scores,
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    base["decision_date"] = pd.to_datetime(
        base["decision_date"], errors="raise"
    ).dt.normalize()
    retail = futoi.frame.loc[
        futoi.frame["client_group"].eq(FUTOI_CLIENT_GROUP)
    ].copy()
    retail["retail_imbalance"] = _retail_imbalance(retail)
    rows: list[pd.DataFrame] = []
    for asset in v12.ASSETS:
        left = base.loc[base["asset"].eq(asset)].sort_values("decision_date")
        right = retail.loc[retail["asset_code"].eq(asset), [
            "source_date",
            "available_at",
            "retail_imbalance",
            "reported_pair_balance_exact",
        ]].sort_values("source_date")
        joined = pd.merge_asof(
            left,
            right,
            left_on="decision_date",
            right_on="source_date",
            direction="backward",
            allow_exact_matches=False,
        )
        joined["futoi_staleness_days"] = (
            joined["decision_date"] - joined["source_date"]
        ).dt.days
        observed = joined["source_date"].notna() & joined[
            "futoi_staleness_days"
        ].le(FUTOI_STALENESS_DAYS)
        parameters = WARMUP_PARAMETERS[asset]
        joined["retail_robust_z"] = (
            joined["retail_imbalance"] - parameters["median"]
        ) / parameters["robust_scale"]
        finite_score = np.isfinite(joined["candidate_score"].astype(float))
        joined["trend_sign"] = np.sign(joined["candidate_score"].astype(float))
        joined["trend_aligned_retail_z"] = (
            joined["trend_sign"] * joined["retail_robust_z"]
        )
        eligible = observed & finite_score & joined["trend_sign"].ne(0.0)
        joined["crowded_state"] = eligible & joined[
            "trend_aligned_retail_z"
        ].ge(ROBUST_Z_THRESHOLD)
        joined["futoi_observed_and_fresh"] = observed
        joined["risk_multiplier"] = np.where(
            ~eligible,
            DEFENSIVE_MULTIPLIER,
            np.where(
                joined["crowded_state"],
                DEFENSIVE_MULTIPLIER,
                AGGRESSIVE_MULTIPLIER,
            ),
        )
        joined["v12_target_weight"] = joined["target_weight"].astype(float)
        joined["target_weight"] = (
            joined["v12_target_weight"] * joined["risk_multiplier"]
        )
        joined["provenance"] = (
            joined["provenance"].astype("string")
            + "|sealed_prior_futoi_retail_crowding_governor"
        )
        rows.append(joined)
    output = pd.concat(rows, ignore_index=True).sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )
    if output["source_date"].notna().any() and not output.loc[
        output["source_date"].notna(), "source_date"
    ].lt(output.loc[output["source_date"].notna(), "decision_date"]).all():
        raise ValueError("V16 FUTOI join used same-day or future source")
    if not set(output["risk_multiplier"].unique()) <= {
        DEFENSIVE_MULTIPLIER,
        AGGRESSIVE_MULTIPLIER,
    }:
        raise ValueError("V16 FUTOI governor emitted an undeclared multiplier")
    gross = output.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if gross.gt(v15.MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V16 FUTOI governed weekly gross exceeds two")
    checks = {
        "governor_uses_strictly_prior_source_date": True,
        "governor_multiplier_set_exact": True,
        "governor_missing_or_stale_is_base_risk": bool(
            output.loc[~output["futoi_observed_and_fresh"], "risk_multiplier"]
            .eq(DEFENSIVE_MULTIPLIER)
            .all()
        ),
        "governor_weekly_gross_at_most_two": True,
    }
    if not all(checks.values()):
        raise ValueError(f"V16 governor checks failed: {checks}")
    return GovernorBuild(frame=output, checks=checks)


def build_execution_targets(
    weekly_weights: pd.DataFrame,
    governor: GovernorBuild,
    active_map: pd.DataFrame,
) -> v12.TargetBuild:
    """Reuse V12 mapping and carry the last weekly FUTOI risk state through rolls."""
    base = v12.build_execution_targets(weekly_weights, active_map)
    rows: list[pd.DataFrame] = []
    for asset in v12.ASSETS:
        left = base.targets.loc[base.targets["asset_code"].eq(asset)].sort_values(
            "decision_date"
        )
        right = governor.frame.loc[
            governor.frame["asset"].eq(asset),
            ["decision_date", "risk_multiplier", "crowded_state", "source_date"],
        ].sort_values("decision_date")
        joined = pd.merge_asof(
            left,
            right,
            on="decision_date",
            direction="backward",
            allow_exact_matches=True,
        )
        rows.append(joined)
    targets = pd.concat(rows, ignore_index=True)
    if targets["risk_multiplier"].isna().any():
        raise ValueError("V16 roll target lacks a carried weekly risk state")
    targets["v12_target_weight"] = targets["target_weight"].astype(float)
    targets["target_weight"] = (
        targets["v12_target_weight"] * targets["risk_multiplier"]
    )
    gross = targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if targets["target_weight"].abs().gt(v15.MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V16 individual mapped target exceeds two")
    if gross.gt(v15.MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V16 mapped target snapshot exceeds gross two")
    return v12.TargetBuild(
        targets=targets.sort_values(
            ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
        ),
        decision_audit=base.decision_audit,
        weekly_decisions=base.weekly_decisions,
        roll_decisions=base.roll_decisions,
    )


def _scenario_payload(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
    ruonia: v15.RuoniaVerification,
) -> tuple[dict[str, Any], v15.CollateralEvaluation]:
    return v15._scenario_payload(result, market, settings, ruonia)


def _promotion(
    results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
) -> dict[str, Any]:
    combined = results["primary"]["combined"]
    conditions = {
        "every_input_futoi_ruonia_and_temporal_check_true": all(checks.values()),
        "all_three_scenarios_execution_and_combined_metrics_complete": all(
            bool(value["futures_only"]["execution_complete"])
            and bool(value["combined"]["metrics_valid"])
            for value in results.values()
        ),
        "zero_critical_failures_unresolved_halts_and_rejected_legs": all(
            int(value["futures_only"]["critical_failure_count"]) == 0
            and int(value["futures_only"]["unresolved_halt_count"]) == 0
            and int(value["futures_only"]["rejected_leg_count"]) == 0
            for value in results.values()
        ),
        "primary_combined_cagr_at_least_0_20": float(combined["cagr"]) >= 0.20,
        "primary_combined_maximum_drawdown_at_most_0_25": float(
            combined["maximum_drawdown"]
        )
        <= 0.25,
        "primary_combined_positive_years_at_least_4_of_5": int(
            combined["positive_years"]
        )
        >= 4
        and len(combined["annual_returns"]) == 5,
        "doubled_combined_total_return_positive": float(
            results["doubled"]["combined"]["total_return"]
        )
        > 0.0,
        "stress_combined_total_return_positive": float(
            results["stress"]["combined"]["total_return"]
        )
        > 0.0,
        "no_order_time_gross_participation_or_margin_breach": all(
            float(value["futures_only"]["maximum_participation"])
            <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(value["futures_only"]["participation_rejection_count"]) == 0
            and int(value["futures_only"]["gross_limit_rejection_count"]) == 0
            and int(value["futures_only"]["initial_margin_rejection_count"]) == 0
            and float(value["futures_only"]["ending_cash"]) > 0.0
            for value in results.values()
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


def _comparisons(primary: dict[str, Any]) -> dict[str, Any]:
    combined = primary["combined"]
    v15_reference = {
        "total_return": 1.6287025663069512,
        "cagr": 0.21327167662258972,
        "sharpe": 0.8826497601427579,
        "maximum_drawdown": 0.34482347022508963,
        "worst_year": -0.15253455335968313,
    }
    return {
        "v15_protocol_sha256": V15_PROTOCOL_SHA256,
        "v15_metrics_sha256": V15_METRICS_SHA256,
        "v15_reference": v15_reference,
        "delta_to_v15": {
            "total_return": float(combined["total_return"])
            - v15_reference["total_return"],
            "cagr": float(combined["cagr"]) - v15_reference["cagr"],
            "sharpe": float(combined["sharpe"]) - v15_reference["sharpe"],
            "maximum_drawdown_reduction": v15_reference["maximum_drawdown"]
            - float(combined["maximum_drawdown"]),
            "worst_year_improvement": float(combined["worst_year"])
            - v15_reference["worst_year"],
        },
    }


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V16 FUTOI retail-crowding risk governor",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        "This is one adaptive 2021-2025 feasibility test, not independent confirmation.",
        "",
        "| Scenario | Futures CAGR | Combined CAGR | Combined Sharpe | Combined MDD | Costs RUB |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        futures = item["futures_only"]
        combined = item["combined"]
        lines.append(
            f"| {name} | {futures['cagr']:.4%} | {combined['cagr']:.4%} | "
            f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
            f"{futures['total_cost']:.2f} |"
        )
    counts = payload["counts"]
    primary = payload["scenarios"]["primary"]
    lines.extend(
        [
            "",
            "## FUTOI states and execution",
            "",
            f"- Fresh weekly asset states: {counts['fresh_weekly_asset_states']}",
            f"- Crowded 1x states: {counts['crowded_weekly_asset_states']}",
            f"- Aggressive 2x states: {counts['aggressive_weekly_asset_states']}",
            f"- Missing/stale base-risk states: {counts['missing_or_stale_weekly_asset_states']}",
            "- Fresh neutral/invalid base-risk states: "
            f"{counts['fresh_neutral_or_invalid_weekly_asset_states']}",
            f"- Capacity clips: {primary['futures_only']['participation_clip_count']}",
            f"- No-open cancels: {primary['futures_only']['target_cancel_no_open_count']}",
            "- No-liquidity cancels: "
            f"{primary['futures_only']['target_cancel_no_liquidity_count']}",
            "- Roll-capacity cancels: "
            f"{primary['futures_only']['target_cancel_roll_capacity_count']}",
            "",
            "## Primary combined annual returns",
            "",
        ]
    )
    for year, value in primary["combined"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute the single immutable V16 FUTOI-governed capital-efficiency run."""
    raise RuntimeError(INVALIDATION_REASON)
    protocol = load_protocol()
    verified = verify_inputs(protocol)
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
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    futoi_frame = pd.read_parquet(
        verified.paths["futoi_panel"],
        columns=protocol["inputs"]["futoi_panel"]["allowed_columns"],
    )
    ruonia = v15.verify_ruonia(ruonia_frame)
    futoi = verify_futoi(futoi_frame)
    scores = v12.build_trend_scores(panel)
    weekly_weights = v12.build_weekly_weights(panel, scores)
    governor = build_futoi_governor(weekly_weights, scores, futoi)
    target_build = build_execution_targets(weekly_weights, governor, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)
    checks = {
        **verified.checks,
        **ruonia.checks,
        **futoi.checks,
        **governor.checks,
    }

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(
            predecessor, v12.OOS_END
        )
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_outputs: dict[str, v15.CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol).items():
        result = v15.run_levered_portfolio_ledger(
            execution_market,
            target_build.targets,
            CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = _scenario_payload(
            result, execution_market, settings, ruonia
        )

    oos_governor = governor.frame.loc[
        governor.frame["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_futoi_rows": int(len(futoi.frame)),
        "source_ruonia_rows": int(len(ruonia.frame)),
        "score_rows": int(len(scores)),
        "weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
        "fresh_weekly_asset_states": int(oos_governor["futoi_observed_and_fresh"].sum()),
        "crowded_weekly_asset_states": int(oos_governor["crowded_state"].sum()),
        "aggressive_weekly_asset_states": int(
            oos_governor["risk_multiplier"].eq(AGGRESSIVE_MULTIPLIER).sum()
        ),
        "missing_or_stale_weekly_asset_states": int(
            (~oos_governor["futoi_observed_and_fresh"]).sum()
        ),
        "fresh_neutral_or_invalid_weekly_asset_states": int(
            (
                oos_governor["futoi_observed_and_fresh"]
                & ~oos_governor["crowded_state"]
                & oos_governor["risk_multiplier"].eq(DEFENSIVE_MULTIPLIER)
            ).sum()
        ),
    }
    state_count = sum(
        counts[name]
        for name in (
            "crowded_weekly_asset_states",
            "aggressive_weekly_asset_states",
            "missing_or_stale_weekly_asset_states",
            "fresh_neutral_or_invalid_weekly_asset_states",
        )
    )
    if state_count != len(oos_governor):
        raise ValueError("V16 weekly FUTOI state accounting is incomplete")
    checks["governor_weekly_state_accounting_complete"] = True
    promotion = _promotion(scenario_results, checks)
    code_paths = {
        "v16_implementation": Path(__file__).resolve(),
        "v15_collateral_parent": Path(v15.__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "portfolio_construction": PROJECT_ROOT
        / "src/market_lab/futures/portfolio_construction.py",
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
        "futoi_source": PROJECT_ROOT / "src/market_lab/futures/futoi_source.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v12_protocol_sha256": V12_PROTOCOL_SHA256,
        "parent_v15_protocol_sha256": V15_PROTOCOL_SHA256,
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in protocol["inputs"].items()
        },
        "code_sha256": {name: v12.sha256_file(path) for name, path in code_paths.items()},
        "protected_from": v12.PROTECTED_FROM.date().isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_period": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "comparison_to_v15": _comparisons(scenario_results["primary"]),
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v16_futoi_governor_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V16 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_weights.parquet", weekly_weights)
        v12._write_parquet(temporary / "futoi_governor.parquet", governor.frame)
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
            v12._write_parquet(
                temporary / f"collateral_{name}.parquet", collateral_outputs[name].audit
            )
            v12._write_parquet(
                temporary / f"combined_ledger_{name}.parquet",
                collateral_outputs[name].combined_ledger,
            )
        (temporary / "report.md").write_text(
            _report_text(payload), encoding="utf-8-sig"
        )
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": v12.sha256_file(path),
            }
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(v12._json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
            json.dumps(
                v12._json_safe(
                    {**identity, "metrics_sha256": v12.sha256_file(metrics_path)}
                ),
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
        help="External immutable runs root; a unique V16 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
