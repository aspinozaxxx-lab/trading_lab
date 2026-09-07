"""Pure, prospective AlgoPack alignment; no IO, fitting, orders, or admission override."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
FIVE = timedelta(minutes=5)
TEN = timedelta(minutes=10)
ASSETS = ("BR", "MIX", "RI", "SI")
FIELDS = {
    "tradestats": ("trades_b", "trades_s", "vol_b", "vol_s"),
    "obstats": ("vol_b_l1", "vol_s_l1", "vol_b_l10", "vol_s_l10"),
}


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an aware timestamp is required")
    return value.astimezone(UTC)


def bucket_end(tradedate: str, tradetime: str) -> datetime:
    """SDK end-label interpretation; Moscow is an explicit protocol assumption."""
    text = f"{tradedate} {tradetime}"
    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != text:
        raise ValueError("noncanonical vendor timestamp")
    if parsed.minute % 5 or parsed.second:
        raise ValueError("vendor label is not a five-minute boundary")
    return parsed.replace(tzinfo=MOSCOW).astimezone(UTC)


def next_entry_boundary(decision_at: datetime) -> datetime:
    """Strictly later ten-minute open; no fill at a just-completed decision boundary."""
    stamp = utc(decision_at)
    floor = stamp.replace(minute=(stamp.minute // 10) * 10, second=0, microsecond=0)
    return floor + TEN


@dataclass(frozen=True)
class FlowVersion:
    dataset: Literal["tradestats", "obstats"]
    asset: str
    secid: str
    tradedate: str
    tradetime: str
    available_at: datetime
    version_sha256: str
    # Order is fixed by FIELDS, not the incoming JSON field order. Missing stays None.
    values: tuple[float | None, float | None, float | None, float | None]

    def __post_init__(self) -> None:
        if self.dataset not in FIELDS or self.asset not in ASSETS or not self.secid:
            raise ValueError("invalid flow identity")
        if re.fullmatch(r"[0-9a-f]{64}", self.version_sha256) is None:
            raise ValueError("invalid version digest")
        utc(self.available_at)
        bucket_end(self.tradedate, self.tradetime)
        if not isinstance(self.values, tuple) or len(self.values) != 4:
            raise ValueError("invalid projected value tuple")
        for value in self.values:
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or value < 0
            ):
                raise ValueError("invalid nonnegative projected field")


@dataclass(frozen=True)
class FlowSelection:
    status: str
    version_ids: tuple[str, ...]
    # trade imbalance, volume imbalance, L1/L10 depth imbalance, signed flow/depth.
    features: tuple[float, ...] | None
    available_at: datetime | None


def select_flow(
    versions: tuple[FlowVersion, ...],
    *,
    asset: str,
    secid: str,
    information_end: datetime,
    decision_at: datetime,
) -> FlowSelection:
    """Select exactly two completed 5m buckets, by actual receipt, without future labels.

    The caller must supply audited, permitted inputs and an admitted timestamp mapping.
    This core is not a historical-source or future-price admission mechanism.
    """
    end, decision = utc(information_end), utc(decision_at)
    if asset not in ASSETS or not secid:
        raise ValueError("invalid requested identity")
    if end.minute % 10 or end.second or end.microsecond or end > decision:
        raise ValueError("invalid completed ten-minute information boundary")
    if decision - end >= TEN:
        return FlowSelection("STALE_INFORMATION", (), None, None)
    local = end.astimezone(MOSCOW)
    if local.weekday() >= 5 or local.date() != decision.astimezone(MOSCOW).date():
        return FlowSelection("UNRESOLVED_SESSION", (), None, None)
    return _select_pair(versions, asset, secid, end, decision)


def select_training_flow(
    versions: tuple[FlowVersion, ...],
    *,
    asset: str,
    secid: str,
    information_end: datetime,
    training_cutoff: datetime,
) -> FlowSelection:
    """User-authorized <=2025 current-vintage training, NEVER historical inference.

    Preserve actual available_at; only the training clock differs. No backtest return
    is produced, and READY_ARCHIVE_ASSUMPTION cannot be confused with online READY.
    Input authorization, hashes and label boundary remain the future runner's duty.
    """
    end, cutoff = utc(information_end), utc(training_cutoff)
    if asset not in ASSETS or not secid:
        raise ValueError("invalid training identity")
    if end.minute % 10 or end.second or end.microsecond or end > cutoff:
        raise ValueError("invalid training information boundary")
    if not datetime(2020, 1, 1, tzinfo=UTC) <= end < datetime(2026, 1, 1, tzinfo=UTC):
        raise ValueError("training source outside authorized 2020-2025 boundary")
    local = end.astimezone(MOSCOW)
    if local.year > 2025:
        raise ValueError("training vendor date touches protected 2026")
    if local.weekday() >= 5:
        return FlowSelection("UNRESOLVED_SESSION", (), None, None)
    result = _select_pair(versions, asset, secid, end, cutoff)
    return (
        replace(result, status="READY_ARCHIVE_ASSUMPTION") if result.status == "READY" else result
    )


def _select_pair(
    versions: tuple[FlowVersion, ...], asset: str, secid: str, end: datetime, cutoff: datetime
) -> FlowSelection:

    selected: list[FlowVersion] = []
    for dataset in FIELDS:
        for target_end in (end - FIVE, end):
            candidates = [
                row
                for row in versions
                if row.dataset == dataset
                and row.asset == asset
                and row.secid == secid
                and utc(row.available_at) <= cutoff
                and bucket_end(row.tradedate, row.tradetime) == target_end
            ]
            if not candidates:
                return FlowSelection("MISSING_BUCKET", (), None, None)
            latest = max(utc(row.available_at) for row in candidates)
            tied = [row for row in candidates if utc(row.available_at) == latest]
            if len({(row.version_sha256, row.values) for row in tied}) != 1:
                raise ValueError("conflicting versions at the same available_at")
            row = tied[0]
            if utc(row.available_at) < target_end:
                return FlowSelection("LABEL_RECEIPT_CONFLICT", (), None, None)
            selected.append(row)

    ids = tuple(row.version_sha256 for row in selected)
    available = max(utc(row.available_at) for row in selected)
    if any(value is None for row in selected for value in row.values):
        return FlowSelection("MISSING_FIELD", ids, None, available)
    ts = tuple(sum(float(row.values[i]) for row in selected[:2]) for i in range(4))
    ob = tuple(sum(float(row.values[i]) for row in selected[2:]) / 2 for i in range(4))
    pairs = ((ts[0], ts[1]), (ts[2], ts[3]), (ob[0], ob[1]), (ob[2], ob[3]))
    if any(not math.isfinite(buy + sell) for buy, sell in pairs):
        return FlowSelection("NUMERIC_OVERFLOW", ids, None, available)
    if any(buy + sell == 0 for buy, sell in pairs):
        return FlowSelection("UNDEFINED_RATIO", ids, None, available)
    imbalances = tuple((buy - sell) / (buy + sell) for buy, sell in pairs)
    pressure = (ts[2] - ts[3]) / (ob[2] + ob[3])
    if not math.isfinite(pressure):
        return FlowSelection("NUMERIC_OVERFLOW", ids, None, available)
    return FlowSelection("READY", ids, (*imbalances, math.asinh(pressure)), available)


@dataclass(frozen=True)
class OpenObservation:
    """Label-side only: an actual 10m bar open with separate completed-bar availability."""

    asset: str
    secid: str
    begin: datetime
    available_at: datetime
    open_price: float | None


@dataclass(frozen=True)
class MatureLabel:
    status: str
    entry_at: datetime
    exit_at: datetime
    log_return: float | None


def mature_label(
    observations: tuple[OpenObservation, ...],
    *,
    asset: str,
    secid: str,
    decision_at: datetime,
    evaluated_at: datetime,
) -> MatureLabel:
    """60m exact-contract label, NEVER an inference eligibility filter or a fill ledger."""
    if asset not in ASSETS or not secid:
        raise ValueError("invalid label identity")
    decision, evaluated = utc(decision_at), utc(evaluated_at)
    if evaluated < decision:
        raise ValueError("evaluation precedes decision")
    entry = next_entry_boundary(decision)
    exit_at = entry + 6 * TEN
    if evaluated < exit_at + TEN:
        return MatureLabel("NOT_MATURE", entry, exit_at, None)
    selected: list[OpenObservation] = []
    for offset in range(7):
        begin = entry + offset * TEN
        matching = [
            row
            for row in observations
            if row.asset == asset
            and row.secid == secid
            and utc(row.begin) == begin
            and utc(row.available_at) <= evaluated
        ]
        if not matching:
            return MatureLabel("MISSING_EXACT_PATH", entry, exit_at, None)
        if len(matching) != 1:
            raise ValueError("duplicate label-side open; upstream must pin one version")
        row = matching[0]
        if utc(row.available_at) < begin + TEN:
            return MatureLabel("INCOMPLETE_BAR_RECEIPT", entry, exit_at, None)
        price = row.open_price
        if price is None or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
            return MatureLabel("INVALID_OPEN", entry, exit_at, None)
        selected.append(row)
    value = math.log(selected[-1].open_price) - math.log(selected[0].open_price)
    return MatureLabel("READY", entry, exit_at, value)
