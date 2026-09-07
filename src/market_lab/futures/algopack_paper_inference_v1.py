"""Pure future-paper inference assembly, not source admission or an execution ledger."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from market_lab.futures.algopack_paper_alignment_v1 import (
    ASSETS,
    FIVE,
    MOSCOW,
    TEN,
    FlowVersion,
    bucket_end,
    select_flow,
    utc,
)
from market_lab.futures.algopack_paper_inputs_v1 import safe
from market_lab.futures.algopack_paper_model_v1 import (
    FLOW_COLUMNS,
    PRICE_COLUMNS,
    TARGET_COLUMNS,
    PriceBar,
    predict_serialized,
    price_state,
)

MODEL_SHA = {
    "price_only": "2053be47dc3649904154816dc635a76c156df3d25aa647354cc0730c4d9ed5d5",
    "price_flow": "6d39dc55178bf3d893eaff91b18ab23066ca2ceed9b1db2c950587838fcb41aa",
}
TRAINED_AT = datetime.fromisoformat("2026-09-07T17:46:26.964097+00:00")
TRAINING_MANIFEST_SHA = "028b2cead7111868ef345987e696be2d70aadd8bbaa0a8233ff676dd38fd7527"


def sha(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid provenance SHA")


@dataclass(frozen=True)
class ContractPlan:
    asset: str
    secid: str
    contract_id: str
    effective_day: date
    expiration_day: date
    available_at: datetime
    source_sha256: str

    def __post_init__(self) -> None:
        if self.asset not in ASSETS or not self.secid or not self.contract_id:
            raise ValueError("invalid plan identity")
        if type(self.effective_day) is not date or type(self.expiration_day) is not date:
            raise ValueError("plan requires calendar dates")
        utc(self.available_at)
        sha(self.source_sha256)


@dataclass(frozen=True)
class AssetState:
    asset: str
    secid: str | None
    contract_id: str | None
    plan_sha256: str | None
    price_status: str
    flow_status: str
    price_values: tuple[float, ...] | None
    flow_values: tuple[float, ...] | None
    price_sources: tuple[str, ...]
    flow_versions: tuple[str, ...]


@dataclass(frozen=True)
class PreparedForecast:
    information_end: datetime
    input_cutoff: datetime
    future_start: datetime
    status: str
    assets: tuple[AssetState, ...]


def select_plan(
    plans: tuple[ContractPlan, ...], asset: str, end: datetime, cutoff: datetime
) -> ContractPlan | None:
    day = end.astimezone(MOSCOW).date()
    candidates = [
        row
        for row in plans
        if row.asset == asset and row.effective_day == day and utc(row.available_at) <= cutoff
    ]
    if not candidates:
        return None
    latest = max(utc(row.available_at) for row in candidates)
    tied = set(row for row in candidates if utc(row.available_at) == latest)
    if len(tied) != 1:
        raise ValueError("conflicting as-of contract plans")
    selected = tied.pop()
    return selected if selected.expiration_day > day else None


def select_prices(
    bars: tuple[PriceBar, ...], end: datetime, cutoff: datetime, future_start: datetime
) -> dict:
    """No backward revision replacement; invalid latest version is NOT bypassed."""
    selected = {}
    for bar in bars:
        begin, available = utc(bar.begin), utc(bar.available_at)
        # Defense in depth only. The future reader MUST gate paths/request times before IO.
        if begin < future_start:
            raise ValueError("pre-F price input is forbidden")
        if available > cutoff or begin >= end:
            continue
        key = bar.asset, bar.contract_id, begin
        previous = selected.get(key)
        if previous is None or utc(previous.available_at) < available:
            selected[key] = bar
        elif utc(previous.available_at) == available and previous != bar:
            raise ValueError("conflicting price versions at the same receipt")
    return selected


def prepare_features(
    *,
    information_end: datetime,
    input_cutoff: datetime,
    future_start: datetime,
    plans: tuple[ContractPlan, ...],
    bars: tuple[PriceBar, ...],
    flow: tuple[FlowVersion, ...],
) -> PreparedForecast:
    """No labels/targets accepted. Caller still owes source/calendar/execution admission."""
    end, cutoff, start = utc(information_end), utc(input_cutoff), utc(future_start)
    if start <= TRAINED_AT or end < start or cutoff < end:
        raise ValueError("invalid future boundary or input clock")
    if end.minute % 10 or end.second or end.microsecond:
        raise ValueError("information end must be a ten-minute grid point")
    local = end.astimezone(MOSCOW)
    status = "READY"
    if local.weekday() >= 5 or not (10, 10) <= (local.hour, local.minute) <= (17, 0):
        status = "OUTSIDE_FIXED_WINDOW"
    elif cutoff >= end + TEN:
        status = "MISSED_INPUT_DEADLINE"
    prices = select_prices(bars, end, cutoff, start)
    post_start_flow = tuple(
        row
        for row in flow
        if utc(row.available_at) >= start
        and bucket_end(row.tradedate, row.tradetime) - FIVE >= start
    )
    states = []
    for asset in ASSETS:
        plan = select_plan(plans, asset, end, cutoff)
        price_status = flow_status = "NO_ELIGIBLE_PLAN" if plan is None else status
        price_values = flow_values = None
        price_sources = flow_versions = ()
        if plan is not None and status == "READY":
            price_status, price_values, price_sources = price_state(
                prices,
                asset=asset,
                contract=plan.contract_id,
                secid=plan.secid,
                information_end=end,
                available_cutoff=cutoff,
            )
            selected = select_flow(
                post_start_flow,
                asset=asset,
                secid=plan.secid,
                information_end=end,
                decision_at=cutoff,
            )
            flow_status, flow_values, flow_versions = (
                selected.status,
                selected.features,
                selected.version_ids,
            )
        states.append(
            AssetState(
                asset,
                None if plan is None else plan.secid,
                None if plan is None else plan.contract_id,
                None if plan is None else plan.source_sha256,
                price_status,
                flow_status,
                price_values,
                flow_values,
                price_sources,
                flow_versions,
            )
        )
    return PreparedForecast(end, cutoff, start, status, tuple(states))


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate frozen model key")
        result[key] = value
    return result


def decode_model(raw: bytes, arm: str) -> dict:
    if arm not in MODEL_SHA or not isinstance(raw, bytes):
        raise ValueError("invalid frozen model arm/bytes")
    if hashlib.sha256(raw).hexdigest() != MODEL_SHA[arm]:
        raise ValueError("frozen model byte identity mismatch")
    model = json.loads(raw, object_pairs_hook=_pairs)
    columns = list(PRICE_COLUMNS if arm == "price_only" else (*PRICE_COLUMNS, *FLOW_COLUMNS))
    if (
        model["feature_names"] != columns
        or model["target_names"] != list(TARGET_COLUMNS)
        or model["alpha"] != 10.0
        or model["solver"] != "svd"
        or model["training_rows"] != 56996
    ):
        raise ValueError("frozen model declaration mismatch")
    predict_serialized(model, np.zeros((1, len(columns))))  # Shape/numeric validation, no target.
    return model


def load_fixed_models(root: Path) -> dict[str, bytes]:
    """Read only the pinned training manifest and two models, no features/labels/prices."""
    raw = safe(root, "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRAINING_MANIFEST_SHA:
        raise ValueError("training manifest identity mismatch")
    manifest = json.loads(raw, object_pairs_hook=_pairs)
    if (
        manifest["status"] != "TRAINED_NOT_EVALUATED"
        or utc(datetime.fromisoformat(manifest["completed_at"])) != TRAINED_AT
        or manifest["live_trading_allowed"] is not False
    ):
        raise ValueError("training manifest state mismatch")
    result = {}
    for arm, expected in MODEL_SHA.items():
        name = f"{arm}.model.json"
        record = manifest["files"][name]
        content = safe(root, name).read_bytes()
        if (
            record["path"] != name
            or record["sha256"] != expected
            or record["bytes"] != len(content)
        ):
            raise ValueError("model differs from pinned manifest")
        decode_model(content, arm)
        result[arm] = content
    return result


def predict_prepared(prepared: PreparedForecast, model_bytes: dict[str, bytes]) -> dict:
    """Pure calculation. Output is UNPUBLISHED until the actual completion clock is attached."""
    if set(model_bytes) != set(MODEL_SHA):
        raise ValueError("both fixed models are required")
    if tuple(row.asset for row in prepared.assets) != ASSETS:
        raise ValueError("prepared asset schema mismatch")
    result = {}
    price_ready = all(
        row.price_status == "READY" and row.price_values is not None for row in prepared.assets
    )
    flow_ready = all(
        row.flow_status == "READY" and row.flow_values is not None for row in prepared.assets
    )
    for arm in MODEL_SHA:
        model = decode_model(model_bytes[arm], arm)
        prediction = None
        status = prepared.status
        if status == "READY":
            status = (
                "READY"
                if price_ready and (arm == "price_only" or flow_ready)
                else "SLEEP_MISSING_FEATURES"
            )
        if status == "READY":
            values = tuple(value for row in prepared.assets for value in row.price_values)
            if arm == "price_flow":
                values += tuple(value for row in prepared.assets for value in row.flow_values)
            prediction = predict_serialized(model, np.asarray([values]))[0].tolist()
        result[arm] = dict(status=status, model_sha256=MODEL_SHA[arm], prediction=prediction)
    return dict(
        state="UNPUBLISHED",
        information_end=prepared.information_end.isoformat(),
        input_cutoff=prepared.input_cutoff.isoformat(),
        future_start=prepared.future_start.isoformat(),
        arms=result,
        assets=[asdict(row) for row in prepared.assets],
        target_names=list(TARGET_COLUMNS),
        live_trading_allowed=False,
    )


def complete_forecast(result: dict, *, completed_at: datetime) -> dict:
    """Actual post-calculation clock, not a schedule label. Persistence receipt is still owed."""
    # Copy prevents the returned committed candidate sharing mutable lists with the caller.
    output = json.loads(json.dumps(result, allow_nan=False))
    if output["state"] != "UNPUBLISHED":
        raise ValueError("forecast was already finalized")
    end = utc(datetime.fromisoformat(output["information_end"]))
    cutoff = utc(datetime.fromisoformat(output["input_cutoff"]))
    completed = utc(completed_at)
    if completed < cutoff:
        raise ValueError("completion precedes input snapshot")
    missed = completed >= end + TEN
    if missed:
        for arm in output["arms"].values():
            arm["status"], arm["prediction"] = "MISSED_PUBLICATION_DEADLINE", None
    output.update(
        state="COMPUTED_NOT_PERSISTED",
        completed_at=completed.isoformat(),
        planned_entry_at=(end + TEN).isoformat(),
        target_exit_at=(end + 7 * TEN).isoformat(),
        execution_admitted=False,
    )
    return output
