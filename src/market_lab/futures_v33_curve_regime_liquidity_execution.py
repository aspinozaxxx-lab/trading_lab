"""V33 execution-only repair for the byte-pinned V32 target weights.

V32 stopped on a one-contract de-risking order when one percent of the factual
ten-minute volume rounded down to zero.  V33 never refits or changes a signal.  It
uses the exact V32 target artifacts, clips every order to factual capacity, splits
reversals into close-first/open-second legs, and retries the scheduled daily flat for
six exact buckets before failing closed.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet
import yaml

from market_lab import futures_v32_curve_regime_intraday as v32
from market_lab.futures.curve_regime_intraday import (
    ASSETS,
    LEDGER_COLUMNS,
    MODEL_FULL_MLP,
    MODEL_FULL_RIDGE,
    MODEL_IDS,
    MODEL_MARKET_MLP,
    ORDER_COLUMNS,
    PROTECTED_FROM,
    TEN_MINUTES,
    UNRESOLVED_COLUMNS,
    LedgerSettings,
    SimulationResult,
    _as_utc,
    _ledger_metrics,
    _long_market,
    _require_columns,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v33_curve_regime_liquidity_execution.yaml"
)
SIDECAR_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v33_curve_regime_liquidity_execution.sha256"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
PROTOCOL_ID: Final[str] = "futures_v33_curve_regime_liquidity_execution_v1"
V33_ORDER_COLUMNS: Final[tuple[str, ...]] = (
    *ORDER_COLUMNS,
    "phase",
    "desired_quantity",
    "residual_quantity_delta",
    "forced_flat",
    "flat_retry_index",
)
V33_LEDGER_COLUMNS: Final[tuple[str, ...]] = (
    *LEDGER_COLUMNS,
    "target_event",
    "forced_flat_event",
    "flat_retry_index",
)


@dataclass(frozen=True, slots=True)
class RetrySettings:
    """Frozen bounded retry semantics selected after the V32 execution halt."""

    maximum_flat_retry_bars: int = 6
    de_risk_capacity_policy: str = "partial_fill_then_carry"
    reversal_policy: str = "close_first_then_open_with_remaining_capacity"
    risk_increase_capacity_policy: str = "partial_fill_no_queue"

    def __post_init__(self) -> None:
        if self.maximum_flat_retry_bars != 6:
            raise ValueError("V33 daily-flat retry count is frozen at six exact buckets")
        if self.de_risk_capacity_policy != "partial_fill_then_carry":
            raise ValueError("V33 de-risk policy drifted")
        if self.reversal_policy != "close_first_then_open_with_remaining_capacity":
            raise ValueError("V33 reversal policy drifted")
        if self.risk_increase_capacity_policy != "partial_fill_no_queue":
            raise ValueError("V33 risk-increase policy drifted")


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
        raise ValueError("V33 config sidecar is malformed")
    return token


def _repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"V33 path must be repo-relative: {relative}")
    return PROJECT_ROOT / candidate


def _verify_file(record: dict[str, Any], label: str) -> Path:
    path = _repo_path(str(record["path"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} byte count drift")
    if sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"{label} SHA-256 drift")
    if (
        record.get("rows") is not None
        and path.suffix.lower() == ".parquet"
        and parquet.ParquetFile(path).metadata.num_rows != int(record["rows"])
    ):
        raise ValueError(f"{label} row count drift")
    return path


def load_protocol() -> dict[str, Any]:
    expected = _sidecar_hash()
    if sha256_file(CONFIG_PATH) != expected:
        raise ValueError("sealed V33 protocol byte drift")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V33 protocol must be a mapping")
    if (
        protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("status") != "sealed_after_v32_execution_halt_before_v33_economics"
        or protocol.get("post_outcome_adaptive") is not True
        or protocol.get("signals_models_and_target_weights_changed") is not False
        or protocol.get("live_trading_allowed") is not False
    ):
        raise ValueError("V33 protocol invariants were weakened")
    if sha256_file(MODULE_PATH) != str(protocol["implementation"]["module_sha256"]):
        raise ValueError("V33 implementation byte drift")

    parent = protocol["parent_v32"]
    config_path = _verify_file(parent["config"], "V32 config")
    _verify_file(parent["config_sidecar"], "V32 config sidecar")
    _verify_file(parent["core"], "V32 core")
    _verify_file(parent["runner"], "V32 runner")
    metrics_path = _verify_file(parent["metrics"], "V32 metrics")
    identity_path = _verify_file(parent["identity"], "V32 identity")
    parent_protocol = v32.load_protocol()
    if (
        sha256_file(config_path) != str(parent["protocol_sha256"])
        or parent_protocol["protocol_id"] != "futures_v32_curve_regime_intraday_cross_asset_v1"
    ):
        raise ValueError("V32 protocol binding drift")
    metrics = _read_json(metrics_path)
    identity = _read_json(identity_path)
    if (
        identity.get("metrics_sha256") != sha256_file(metrics_path)
        or metrics.get("promotion", {}).get("verdict") != "NO_GO"
        or metrics.get("promotion", {})
        .get("conditions", {})
        .get("all_primary_cost_ledgers_complete")
        is not False
    ):
        raise ValueError("V32 execution-halt diagnosis binding drift")
    return protocol


def _parent_run_path(protocol: dict[str, Any]) -> Path:
    return _repo_path(str(protocol["parent_v32"]["run_path"]))


def _load_parent_targets(protocol: dict[str, Any]) -> dict[str, pd.DataFrame]:
    parent_metrics = _read_json(_verify_file(protocol["parent_v32"]["metrics"], "V32 metrics"))
    frames: dict[str, pd.DataFrame] = {}
    for model_id, record in protocol["target_artifacts"].items():
        if model_id not in MODEL_IDS:
            raise ValueError(f"unknown V33 parent target model: {model_id}")
        path = _verify_file(record, f"V32 target {model_id}")
        parent_record = parent_metrics["artifacts"].get(path.name)
        if not isinstance(parent_record, dict) or any(
            str(parent_record[key]) != str(record[key]) for key in ("bytes", "sha256", "rows")
        ):
            raise ValueError(f"V32 metrics target binding drift: {model_id}")
        frame = pd.read_parquet(path)
        frame["entry_at"] = _as_utc(frame["entry_at"], f"{model_id}.entry_at")
        if "decision_at" in frame:
            frame["decision_at"] = _as_utc(frame["decision_at"], f"{model_id}.decision_at")
        if set(frame["model_id"].astype(str)) != {model_id}:
            raise ValueError(f"V32 target model identity drift: {model_id}")
        if frame.duplicated(["entry_at", "asset"]).any():
            raise ValueError(f"V32 target duplicates timestamp/asset: {model_id}")
        frames[model_id] = frame.sort_values(["entry_at", "asset"], kind="stable").reset_index(
            drop=True
        )
    if set(frames) != set(MODEL_IDS):
        raise ValueError("V33 requires the exact three V32 target artifacts")
    return frames


def _load_v32_failure_diagnosis(protocol: dict[str, Any]) -> list[dict[str, object]]:
    root = _parent_run_path(protocol)
    expected = protocol["v32_failure_diagnosis"]
    records: list[dict[str, object]] = []
    for name in expected["unresolved_artifacts"]:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path)
        records.extend(frame.to_dict("records"))
    normalized = [
        {
            "timestamp": pd.Timestamp(item["timestamp"]).isoformat(),
            "asset": str(item["asset"]),
            "reason": str(item["reason"]),
        }
        for item in records
    ]
    if len(normalized) != int(expected["record_count"]):
        raise ValueError("V32 unresolved diagnosis count drift")
    if {item["reason"] for item in normalized} != {"insufficient_exit_capacity"}:
        raise ValueError("V32 unresolved diagnosis reason drift")
    return normalized


def metadata_preflight(protocol: dict[str, Any]) -> dict[str, Any]:
    parent_audit = v32.audit_run(_parent_run_path(protocol))
    targets = _load_parent_targets(protocol)
    diagnosis = _load_v32_failure_diagnosis(protocol)
    expected = protocol["pre_outcome_metadata_seal"]
    counts = {
        "parent_audit_checks": int(len(parent_audit["checks"])),
        "parent_unresolved_records": int(len(diagnosis)),
        "target_artifacts": int(len(targets)),
        "target_rows_each": sorted({int(len(frame)) for frame in targets.values()}),
        "target_timestamps_each": sorted(
            {int(frame["entry_at"].nunique()) for frame in targets.values()}
        ),
        "forced_flat_rows_each": sorted(
            {int(frame["forced_flat"].astype(bool).sum()) for frame in targets.values()}
        ),
        "forced_flat_days_each": sorted(
            {
                int(
                    frame.loc[frame["forced_flat"].astype(bool), "entry_at"]
                    .dt.normalize()
                    .nunique()
                )
                for frame in targets.values()
            }
        ),
    }
    checks = {
        "parent_run_audit_all_true": all(parent_audit["checks"].values()),
        "parent_failure_is_only_insufficient_exit_capacity": all(
            item["reason"] == "insufficient_exit_capacity" for item in diagnosis
        ),
        "exact_three_parent_target_artifacts": set(targets) == set(MODEL_IDS),
        "all_parent_target_assets_exact": all(
            set(frame["asset"].astype(str)) == set(ASSETS) for frame in targets.values()
        ),
        "all_parent_targets_before_2026": all(
            frame["entry_at"].lt(PROTECTED_FROM).all() for frame in targets.values()
        ),
        "expected_target_rows": counts["target_rows_each"] == [int(expected["target_rows_each"])],
        "expected_target_timestamps": counts["target_timestamps_each"]
        == [int(expected["target_timestamps_each"])],
        "expected_forced_flat_rows": counts["forced_flat_rows_each"]
        == [int(expected["forced_flat_rows_each"])],
        "expected_forced_flat_days": counts["forced_flat_days_each"]
        == [int(expected["forced_flat_days_each"])],
        "signals_models_and_target_weights_not_recomputed": True,
    }
    if not all(checks.values()):
        raise ValueError(f"V33 metadata preflight failed: {checks}")
    return {
        "scope": "parent_identity_targets_and_execution_diagnosis_only",
        "counts": counts,
        "diagnosis": diagnosis,
        "checks": checks,
    }


def _expand_flat_retries(targets: pd.DataFrame, settings: RetrySettings) -> pd.DataFrame:
    output = targets.copy()
    output["flat_retry_index"] = 0
    forced = output.loc[output["forced_flat"].astype(bool)].copy()
    retries: list[pd.DataFrame] = []
    for retry_index in range(1, settings.maximum_flat_retry_bars + 1):
        retry = forced.copy()
        retry["entry_at"] = retry["entry_at"] + retry_index * TEN_MINUTES
        if "decision_at" in retry:
            retry["decision_at"] = retry["entry_at"]
        retry["flat_retry_index"] = retry_index
        retries.append(retry)
    expanded = pd.concat((output, *retries), ignore_index=True)
    if expanded.duplicated(["entry_at", "asset"]).any():
        raise ValueError("V33 retry schedule duplicates target timestamp/asset")
    return expanded.sort_values(["entry_at", "asset"], kind="stable").reset_index(drop=True)


def _order_phases(current: int, desired: int) -> list[tuple[int, int, bool]]:
    """Return phase, quantity delta, and whether a reversal leg requires flat first."""

    if current == desired:
        return []
    if current == 0:
        return [(1, desired, False)]
    if desired == 0:
        return [(0, -current, False)]
    if np.sign(current) == np.sign(desired):
        phase = 0 if abs(desired) < abs(current) else 1
        return [(phase, desired - current, False)]
    return [(0, -current, False), (1, desired, True)]


def simulate_retry_portfolio(
    common_panel: pd.DataFrame,
    targets: pd.DataFrame,
    ledger_settings: LedgerSettings | None = None,
    retry_settings: RetrySettings | None = None,
) -> SimulationResult:
    """Follow exact V32 targets with bounded partial de-risking and daily-flat retries."""

    ledger_settings = ledger_settings or LedgerSettings()
    retry_settings = retry_settings or RetrySettings()
    if targets.empty:
        ledger = pd.DataFrame(columns=V33_LEDGER_COLUMNS)
        orders = pd.DataFrame(columns=V33_ORDER_COLUMNS)
        unresolved_frame = pd.DataFrame(columns=UNRESOLVED_COLUMNS)
        metrics = _ledger_metrics(ledger, orders, unresolved_frame, ledger_settings)
        return SimulationResult(ledger, orders, unresolved_frame, metrics, True)
    required = {
        "entry_at",
        "asset",
        "contract_id",
        "target_weight",
        "signal_volume",
        "sizing_notional",
        "sizing_point_value",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "modeled_initial_margin",
        "forced_flat",
    }
    _require_columns(targets, required, "V33 targets")
    target = targets.copy()
    target["entry_at"] = _as_utc(target["entry_at"], "V33 targets.entry_at")
    if target["entry_at"].max() >= PROTECTED_FROM:
        raise ValueError("V33 targets touch protected 2026")
    target = _expand_flat_retries(target, retry_settings)
    market = _long_market(common_panel)
    start = target["entry_at"].min() - TEN_MINUTES
    end = target["entry_at"].max()
    market = market.loc[market["timestamp"].between(start, end)].copy()
    market_by_time = {
        timestamp: group.set_index("asset") for timestamp, group in market.groupby("timestamp")
    }
    targets_by_time = {
        timestamp: group.set_index("asset") for timestamp, group in target.groupby("entry_at")
    }
    positions = {asset: 0 for asset in ASSETS}
    contracts: dict[str, str | None] = {asset: None for asset in ASSETS}
    point_values = {asset: float("nan") for asset in ASSETS}
    last_opens = {asset: float("nan") for asset in ASSETS}
    equity = float(ledger_settings.initial_cash)
    previous_timestamp: pd.Timestamp | None = None
    ledger_records: list[dict[str, object]] = []
    order_records: list[dict[str, object]] = []
    unresolved_records: list[dict[str, object]] = []

    def unresolved(timestamp: pd.Timestamp, asset: str, reason: str) -> None:
        unresolved_records.append({"timestamp": timestamp, "asset": asset, "reason": reason})

    for timestamp in sorted(market_by_time):
        rows = market_by_time[timestamp]
        if set(rows.index) != set(ASSETS):
            continue
        open_position = any(quantity != 0 for quantity in positions.values())
        if (
            previous_timestamp is not None
            and timestamp - previous_timestamp != TEN_MINUTES
            and open_position
        ):
            unresolved(timestamp, "PORTFOLIO", "missing_exact_mark_successor")
            break
        bar_pnl = 0.0
        for asset in ASSETS:
            quantity = positions[asset]
            if quantity == 0:
                continue
            row = rows.loc[asset]
            if str(row["contract_id"]) != contracts[asset]:
                unresolved(timestamp, asset, "contract_changed_while_open")
                break
            current_open = float(row["open"])
            if not np.isfinite(current_open) or current_open <= 0.0:
                unresolved(timestamp, asset, "missing_factual_open_mark")
                break
            bar_pnl += quantity * (current_open - last_opens[asset]) * point_values[asset]
        if unresolved_records:
            break
        equity += bar_pnl
        bar_cost = 0.0
        target_rows = targets_by_time.get(timestamp)
        forced_flat_event = False
        flat_retry_index = 0
        if target_rows is not None:
            if set(target_rows.index) != set(ASSETS):
                unresolved(timestamp, "PORTFOLIO", "incomplete_four_asset_target")
                break
            forced_flat_event = bool(target_rows["forced_flat"].astype(bool).all())
            flat_retry_index = int(target_rows["flat_retry_index"].max())
            specifications: dict[str, pd.Series] = {}
            desired_positions: dict[str, int] = {}
            capacity_remaining: dict[str, int] = {}
            planned: list[tuple[int, str, int, bool]] = []
            for asset in ASSETS:
                specification = target_rows.loc[asset]
                market_row = rows.loc[asset]
                if str(specification["contract_id"]) != str(market_row["contract_id"]):
                    unresolved(timestamp, asset, "target_contract_mismatch")
                    break
                notional = float(specification["sizing_notional"])
                signal_volume = float(specification["signal_volume"])
                factual_volume = float(market_row["volume"])
                if (
                    not np.isfinite(notional)
                    or notional <= 0.0
                    or not np.isfinite(signal_volume)
                    or signal_volume < 0.0
                    or not np.isfinite(factual_volume)
                    or factual_volume < 0.0
                ):
                    unresolved(timestamp, asset, "missing_causal_or_factual_capacity_dependency")
                    break
                desired = math.trunc(equity * float(specification["target_weight"]) / notional)
                signal_cap = max(
                    math.floor(ledger_settings.signal_participation * signal_volume), 0
                )
                desired = int(np.clip(desired, -signal_cap, signal_cap))
                specifications[asset] = specification
                desired_positions[asset] = desired
                capacity_remaining[asset] = max(
                    math.floor(ledger_settings.factual_participation_cap * factual_volume), 0
                )
                for phase, delta, requires_flat in _order_phases(positions[asset], desired):
                    planned.append((phase, asset, delta, requires_flat))
            if unresolved_records:
                break
            for phase, asset, requested_delta, requires_flat in sorted(planned):
                specification = specifications[asset]
                market_row = rows.loc[asset]
                if requires_flat and positions[asset] != 0:
                    order_records.append(
                        {
                            "timestamp": timestamp,
                            "asset": asset,
                            "contract_id": str(market_row["contract_id"]),
                            "requested_quantity_delta": requested_delta,
                            "filled_quantity_delta": 0,
                            "participation": 0.0,
                            "commission_cost": 0.0,
                            "slippage_cost": 0.0,
                            "total_cost": 0.0,
                            "capacity_clipped": True,
                            "filled": False,
                            "reason": "awaiting_reversal_flat",
                            "phase": phase,
                            "desired_quantity": desired_positions[asset],
                            "residual_quantity_delta": requested_delta,
                            "forced_flat": forced_flat_event,
                            "flat_retry_index": flat_retry_index,
                        }
                    )
                    continue
                capacity = capacity_remaining[asset]
                delta = int(np.sign(requested_delta) * min(abs(requested_delta), capacity))
                capacity_clipped = abs(delta) < abs(requested_delta)
                if delta == 0:
                    order_records.append(
                        {
                            "timestamp": timestamp,
                            "asset": asset,
                            "contract_id": str(market_row["contract_id"]),
                            "requested_quantity_delta": requested_delta,
                            "filled_quantity_delta": 0,
                            "participation": 0.0,
                            "commission_cost": 0.0,
                            "slippage_cost": 0.0,
                            "total_cost": 0.0,
                            "capacity_clipped": capacity_clipped,
                            "filled": False,
                            "reason": "zero_factual_capacity",
                            "phase": phase,
                            "desired_quantity": desired_positions[asset],
                            "residual_quantity_delta": requested_delta,
                            "forced_flat": forced_flat_event,
                            "flat_retry_index": flat_retry_index,
                        }
                    )
                    continue
                candidate_positions = positions.copy()
                candidate_positions[asset] += delta
                if phase == 0 and abs(candidate_positions[asset]) > abs(positions[asset]):
                    unresolved(timestamp, asset, "de_risk_phase_increased_absolute_position")
                    break
                gross = 0.0
                buffered_margin = 0.0
                for candidate_asset in ASSETS:
                    candidate_row = rows.loc[candidate_asset]
                    candidate_notional = float(candidate_row["sizing_notional"])
                    candidate_margin = float(candidate_row["modeled_initial_margin"])
                    if (
                        not np.isfinite(candidate_notional)
                        or candidate_notional <= 0.0
                        or not np.isfinite(candidate_margin)
                        or candidate_margin <= 0.0
                    ):
                        unresolved(timestamp, candidate_asset, "missing_factual_risk_dependency")
                        break
                    gross += abs(candidate_positions[candidate_asset]) * candidate_notional
                    buffered_margin += (
                        abs(candidate_positions[candidate_asset])
                        * candidate_margin
                        * ledger_settings.margin_buffer_multiple
                    )
                if unresolved_records:
                    break
                if phase == 1 and gross > ledger_settings.maximum_gross * max(equity, 1e-12) + 1e-9:
                    unresolved(timestamp, asset, "gross_limit_breach_at_order")
                    break
                if phase == 1 and buffered_margin > equity + 1e-9:
                    unresolved(timestamp, asset, "buffered_margin_breach_at_order")
                    break
                tick_cash = float(specification["sizing_tick_cash_value"])
                fee = float(specification["conservative_fee_per_side"])
                point_value = float(specification["sizing_point_value"])
                if (
                    not np.isfinite(tick_cash)
                    or tick_cash <= 0.0
                    or not np.isfinite(fee)
                    or fee < 0.0
                    or not np.isfinite(point_value)
                    or point_value <= 0.0
                ):
                    unresolved(timestamp, asset, "missing_cost_dependency")
                    break
                commission = abs(delta) * ledger_settings.fee_multiplier * fee
                slippage = abs(delta) * ledger_settings.slippage_ticks * tick_cash
                total_cost = commission + slippage
                equity -= total_cost
                bar_cost += total_cost
                positions[asset] += delta
                capacity_remaining[asset] -= abs(delta)
                if positions[asset] == 0:
                    contracts[asset] = None
                    point_values[asset] = float("nan")
                    last_opens[asset] = float("nan")
                else:
                    contracts[asset] = str(market_row["contract_id"])
                    point_values[asset] = point_value
                    last_opens[asset] = float(market_row["open"])
                factual_volume = float(market_row["volume"])
                order_records.append(
                    {
                        "timestamp": timestamp,
                        "asset": asset,
                        "contract_id": str(market_row["contract_id"]),
                        "requested_quantity_delta": requested_delta,
                        "filled_quantity_delta": delta,
                        "participation": abs(delta) / max(factual_volume, 1.0),
                        "commission_cost": commission,
                        "slippage_cost": slippage,
                        "total_cost": total_cost,
                        "capacity_clipped": capacity_clipped,
                        "filled": True,
                        "reason": "filled_partial_capacity" if capacity_clipped else "filled",
                        "phase": phase,
                        "desired_quantity": desired_positions[asset],
                        "residual_quantity_delta": requested_delta - delta,
                        "forced_flat": forced_flat_event,
                        "flat_retry_index": flat_retry_index,
                    }
                )
            if unresolved_records:
                break
            if (
                forced_flat_event
                and flat_retry_index == retry_settings.maximum_flat_retry_bars
                and any(quantity != 0 for quantity in positions.values())
            ):
                unresolved(timestamp, "PORTFOLIO", "flat_retry_exhausted")
                break
        for asset in ASSETS:
            if positions[asset] != 0:
                last_opens[asset] = float(rows.loc[asset, "open"])
                contracts[asset] = str(rows.loc[asset, "contract_id"])
        gross = sum(
            abs(positions[asset]) * float(rows.loc[asset, "sizing_notional"]) for asset in ASSETS
        )
        buffered_margin = sum(
            abs(positions[asset])
            * float(rows.loc[asset, "modeled_initial_margin"])
            * ledger_settings.margin_buffer_multiple
            for asset in ASSETS
        )
        ledger_records.append(
            {
                "timestamp": timestamp,
                "local_date": pd.Timestamp(rows.iloc[0]["local_date"]),
                "bar_pnl": bar_pnl,
                "bar_cost": bar_cost,
                "equity": equity,
                "gross_notional": gross,
                "gross_multiple": gross / max(equity, 1e-12),
                "buffered_margin": buffered_margin,
                "buffered_margin_multiple": buffered_margin / max(equity, 1e-12),
                **{f"position_{asset.lower()}": positions[asset] for asset in ASSETS},
                "target_event": target_rows is not None,
                "forced_flat_event": forced_flat_event,
                "flat_retry_index": flat_retry_index,
            }
        )
        previous_timestamp = timestamp
    if not unresolved_records and any(quantity != 0 for quantity in positions.values()):
        unresolved_records.append(
            {
                "timestamp": previous_timestamp,
                "asset": "PORTFOLIO",
                "reason": "terminal_position_not_flat",
            }
        )
    ledger = pd.DataFrame(ledger_records, columns=V33_LEDGER_COLUMNS)
    orders = pd.DataFrame(order_records, columns=V33_ORDER_COLUMNS)
    unresolved_frame = pd.DataFrame(unresolved_records, columns=UNRESOLVED_COLUMNS)
    metrics = _ledger_metrics(ledger, orders, unresolved_frame, ledger_settings)
    metrics["partial_capacity_fills"] = (
        int(orders["reason"].eq("filled_partial_capacity").sum()) if len(orders) else 0
    )
    metrics["zero_capacity_retries"] = (
        int(orders["reason"].eq("zero_factual_capacity").sum()) if len(orders) else 0
    )
    metrics["reversal_waits"] = (
        int(orders["reason"].eq("awaiting_reversal_flat").sum()) if len(orders) else 0
    )
    return SimulationResult(
        ledger=ledger,
        orders=orders,
        unresolved=unresolved_frame,
        metrics=metrics,
        execution_complete=unresolved_frame.empty,
    )


def _ledger_settings(protocol: dict[str, Any], scenario: str) -> LedgerSettings:
    execution = protocol["execution"]
    record = execution["scenarios"][scenario]
    return LedgerSettings(
        initial_cash=float(execution["initial_cash_rub"]),
        slippage_ticks=int(record["slippage_ticks"]),
        fee_multiplier=float(record["fee_multiplier"]),
        signal_participation=float(execution["signal_participation"]),
        factual_participation_cap=float(execution["factual_participation_cap"]),
        maximum_gross=float(execution["maximum_gross"]),
        margin_buffer_multiple=float(execution["margin_buffer_multiple"]),
    )


def _promotion(
    protocol: dict[str, Any],
    results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
) -> dict[str, Any]:
    primary = results[f"{MODEL_FULL_MLP}:primary"]
    doubled = results[f"{MODEL_FULL_MLP}:doubled"]
    stress = results[f"{MODEL_FULL_MLP}:stress"]
    market = results[f"{MODEL_MARKET_MLP}:primary"]
    ridge = results[f"{MODEL_FULL_RIDGE}:primary"]
    gates = protocol["promotion_rule"]
    baseline_cagr = max(float(market["cagr"]), float(ridge["cagr"]))
    baseline_sharpe = max(float(market["annualized_sharpe"]), float(ridge["annualized_sharpe"]))
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
        "incremental_cagr_over_best_baseline": float(primary["cagr"])
        >= baseline_cagr + float(gates["minimum_cagr_advantage_over_baseline"]),
        "incremental_sharpe_over_best_baseline": float(primary["annualized_sharpe"])
        >= baseline_sharpe + float(gates["minimum_sharpe_advantage_over_baseline"]),
        "zero_unresolved": int(primary["unresolved_count"]) == 0,
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
        "verdict": (
            "ADAPTIVE_EXECUTION_REPAIRED_LEAD_REQUIRES_FORWARD_VALIDATION"
            if support_20
            else "NO_GO"
        ),
        "post_outcome_adaptive": True,
        "independent_confirmation": False,
        "live_trading_allowed": False,
    }


def _artifact_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix == ".parquet":
        record["rows"] = parquet.ParquetFile(path).metadata.num_rows
    return record


def _report_text(payload: dict[str, Any]) -> str:
    results = payload["results"]

    def result_row(label: str, result: dict[str, Any]) -> str:
        return (
            f"| {label} | {result['cagr']:.4%} | {result['annualized_sharpe']:.3f} | "
            f"{result['maximum_drawdown']:.4%} | {result['total_return']:.4%} | "
            f"{result['execution_complete']} | {result['unresolved_count']} |"
        )

    primary = results[f"{MODEL_FULL_MLP}:primary"]
    return "\n".join(
        (
            "# V33 curve-regime liquidity execution repair",
            "",
            f"Verdict: **{payload['promotion']['verdict']}**. Live trading: **forbidden**.",
            "",
            "V33 reuses exact V32 target artifacts. It changes no feature, model, seed,",
            "threshold, sign or target weight. De-risking is capacity-clipped and carried;",
            "reversals close first; the 18:30 flat gets six exact ten-minute retries.",
            "",
            "| Variant | CAGR | Sharpe | MDD | Total return | Complete | Unresolved |",
            "|---|---:|---:|---:|---:|---|---:|",
            result_row("full MLP primary", primary),
            result_row("full MLP doubled", results[f"{MODEL_FULL_MLP}:doubled"]),
            result_row("full MLP stress", results[f"{MODEL_FULL_MLP}:stress"]),
            result_row("market-only MLP primary", results[f"{MODEL_MARKET_MLP}:primary"]),
            result_row("full Ridge primary", results[f"{MODEL_FULL_RIDGE}:primary"]),
            "",
            f"Primary calendar returns: `{primary['annual_returns']}`.",
            (
                f"Filled legs: {primary['filled_order_legs']}; partial capacity fills: "
                f"{primary['partial_capacity_fills']}; zero-capacity retries: "
                f"{primary['zero_capacity_retries']}; total costs: "
                f"{primary['total_cost']:.2f} RUB."
            ),
            "",
            "This is a post-V32 adaptive execution repair, not independent evidence.",
            "Even a passing result requires a new sealed forward/paper period.",
            "",
        )
    )


def run_experiment(output_root: Path) -> Path:
    protocol = load_protocol()
    preflight = metadata_preflight(protocol)
    targets = _load_parent_targets(protocol)
    parent_protocol = v32.load_protocol()
    common, _, provenance = v32.load_economic_inputs(parent_protocol)
    retry_settings = RetrySettings(**protocol["retry"])
    simulations: dict[str, SimulationResult] = {}
    results: dict[str, dict[str, Any]] = {}
    for model_id in MODEL_IDS:
        scenarios = ("primary", "doubled", "stress") if model_id == MODEL_FULL_MLP else ("primary",)
        for scenario in scenarios:
            key = f"{model_id}:{scenario}"
            result = simulate_retry_portfolio(
                common,
                targets[model_id],
                _ledger_settings(protocol, scenario),
                retry_settings,
            )
            simulations[key] = result
            results[key] = dict(result.metrics)
    checks = {
        "metadata_preflight_all_true": all(preflight["checks"].values()),
        "exact_parent_target_models": set(targets) == set(MODEL_IDS),
        "all_parent_targets_before_2026": all(
            frame["entry_at"].lt(PROTECTED_FROM).all() for frame in targets.values()
        ),
        "retry_schedule_is_exact_ten_minutes": retry_settings.maximum_flat_retry_bars == 6,
        "signals_models_and_target_weights_unchanged": protocol[
            "signals_models_and_target_weights_changed"
        ]
        is False,
        "post_outcome_adaptive_disclosed": protocol["post_outcome_adaptive"] is True,
        "no_live_trading_claim": protocol["live_trading_allowed"] is False,
    }
    counts = {
        **{key: int(value) for key, value in provenance.items()},
        "parent_target_rows_each": int(next(iter(targets.values())).shape[0]),
        "forced_flat_days": int(
            next(iter(targets.values()))
            .loc[lambda frame: frame["forced_flat"].astype(bool), "entry_at"]
            .dt.normalize()
            .nunique()
        ),
        "total_filled_order_legs": int(
            sum(int(result.metrics["filled_order_legs"]) for result in simulations.values())
        ),
        "total_partial_capacity_fills": int(
            sum(int(result.metrics["partial_capacity_fills"]) for result in simulations.values())
        ),
        "total_zero_capacity_retries": int(
            sum(int(result.metrics["zero_capacity_retries"]) for result in simulations.values())
        ),
    }
    promotion = _promotion(protocol, results, checks)
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": _sidecar_hash(),
        "created_at_utc": datetime.now(UTC),
        "research_only": True,
        "post_outcome_adaptive": True,
        "independent_confirmation": False,
        "live_trading_allowed": False,
        "parent_v32": protocol["parent_v32"],
        "retry_settings": asdict(retry_settings),
        "preflight": preflight,
        "counts": counts,
        "checks": checks,
        "results": results,
        "promotion": promotion,
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v33_curve_regime_liquidity_{timestamp}_{_sidecar_hash()[:8]}"
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        (temporary / "resolved_protocol.yaml").write_bytes(CONFIG_PATH.read_bytes())
        _write_json(temporary / "preflight.json", preflight)
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
            "module_sha256": sha256_file(MODULE_PATH),
            "parent_metrics_sha256": protocol["parent_v32"]["metrics"]["sha256"],
            "metrics_sha256": sha256_file(temporary / "metrics.json"),
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
        raise ValueError("V33 metrics SHA drift")
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
        raise ValueError(f"V33 run audit failed: {checks}")
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
    "MODULE_PATH",
    "PROJECT_ROOT",
    "PROTOCOL_ID",
    "RetrySettings",
    "audit_run",
    "load_protocol",
    "main",
    "metadata_preflight",
    "run_experiment",
    "sha256_file",
    "simulate_retry_portfolio",
]
