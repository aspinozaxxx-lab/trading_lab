"""Read-only causal readiness for official MOEX futures-calendar snapshots."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import pandas as pd

from market_lab.futures import moex_forward_futures_calendar_source_v1 as source

MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")


def _timestamp(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    timestamp = pd.Timestamp(value if value is not None else datetime.now(UTC))
    if timestamp.tzinfo is None:
        raise ValueError("calendar readiness timestamp must include a timezone")
    return timestamp.tz_convert("UTC")


def _scan(output_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    snapshots = sorted(
        path for path in output_root.resolve().glob("snapshot_*") if path.is_dir()
    )
    for snapshot in snapshots:
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"calendar raw replay failed: {', '.join(failed)}")
            valid.append(
                {
                    "snapshot": str(snapshot),
                    "snapshot_name": snapshot.name,
                    "retrieved_at_utc": _timestamp(manifest["retrieved_at_utc"]),
                    "rows": int(manifest["processed"]["rows"]),
                    "unknown_dates": int(manifest["processed"]["unknown_dates"]),
                }
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})
    return valid, invalid


def _latest_causal(
    valid: list[dict[str, Any]], decision_at: pd.Timestamp
) -> dict[str, Any] | None:
    eligible = [item for item in valid if item["retrieved_at_utc"] <= decision_at]
    if not eligible:
        return None
    return max(eligible, key=lambda item: item["retrieved_at_utc"])


def _calendar(snapshot: dict[str, Any]) -> pd.DataFrame:
    return pd.read_parquet(Path(snapshot["snapshot"]) / "calendar.parquet").sort_values(
        "tradedate", kind="stable", ignore_index=True
    )


def _next_six_session_support(
    calendar: pd.DataFrame, decision_at: pd.Timestamp
) -> tuple[bool, str | None, int, str | None]:
    decision_date = decision_at.tz_convert(MOSCOW).tz_localize(None).normalize()
    future = calendar.loc[calendar["tradedate"].gt(decision_date)].copy()
    known_sessions = 0
    known_through: str | None = None
    first_unknown: str | None = None
    for row in future.itertuples(index=False):
        date_value = pd.Timestamp(row.tradedate).date().isoformat()
        if pd.isna(row.is_traded):
            first_unknown = date_value
            break
        known_through = date_value
        if int(row.is_traded) == 1:
            known_sessions += 1
            if known_sessions >= 6:
                return True, known_through, known_sessions, None
    return False, known_through, known_sessions, first_unknown


def calendar_for_roll(
    decision_at: str | datetime | pd.Timestamp,
    expiration_date: str | datetime | pd.Timestamp,
    output_root: Path = source.DEFAULT_OUTPUT_ROOT,
) -> pd.DatetimeIndex:
    """Return only a causally known calendar sufficient to decide the five-session rule."""
    decision = _timestamp(decision_at)
    expiration = pd.Timestamp(expiration_date)
    if expiration.tzinfo is not None:
        expiration = expiration.tz_convert(MOSCOW).tz_localize(None)
    expiration = expiration.normalize()
    decision_date = decision.tz_convert(MOSCOW).tz_localize(None).normalize()
    if expiration <= decision_date:
        raise ValueError("roll expiration must be after the decision date")
    valid, invalid = _scan(output_root)
    if invalid:
        raise ValueError("invalid MOEX calendar snapshot present")
    selected = _latest_causal(valid, decision)
    if selected is None:
        raise ValueError("no MOEX calendar snapshot was available before decision")
    calendar = _calendar(selected)
    horizon = calendar.loc[
        calendar["tradedate"].gt(decision_date)
        & calendar["tradedate"].le(expiration)
    ].copy()
    expected = pd.date_range(decision_date + pd.Timedelta(days=1), expiration, freq="D")
    if not pd.DatetimeIndex(horizon["tradedate"]).equals(expected):
        raise ValueError("MOEX calendar lacks a date before expiration")
    known: list[pd.Timestamp] = []
    for row in horizon.itertuples(index=False):
        if pd.isna(row.is_traded):
            raise ValueError("MOEX calendar contains unknown state before roll is decidable")
        if int(row.is_traded) == 1:
            known.append(pd.Timestamp(row.tradedate))
            if len(known) >= 6:
                break
    if len(known) < 6 and horizon["tradedate"].max() != expiration:
        raise ValueError("MOEX calendar does not reach expiration")
    return pd.DatetimeIndex(known)


def assess(
    output_root: Path = source.DEFAULT_OUTPUT_ROOT,
    *,
    as_of_utc: str | datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    source.load_config()
    as_of = _timestamp(as_of_utc)
    valid, invalid = _scan(output_root)
    selected = _latest_causal(valid, as_of)
    supported = False
    known_through = None
    known_sessions = 0
    first_unknown = None
    if selected is not None:
        supported, known_through, known_sessions, first_unknown = _next_six_session_support(
            _calendar(selected), as_of
        )
    blockers: list[str] = []
    if invalid:
        blockers.append("invalid_calendar_snapshot_present")
    if selected is None:
        blockers.append("no_causal_official_calendar_snapshot")
    elif not supported:
        blockers.append("next_six_futures_sessions_not_fully_known")
    ready = not blockers
    return {
        "protocol_id": source.load_config()["protocol_id"],
        "config_sha256": source.CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "as_of_utc": as_of.isoformat(),
        "output_root": str(output_root.resolve()),
        "valid_snapshot_count": len(valid),
        "invalid_snapshot_count": len(invalid),
        "invalid_snapshots": invalid,
        "latest_causal_snapshot": selected["snapshot_name"] if selected else None,
        "latest_causal_retrieved_at_utc": (
            selected["retrieved_at_utc"].isoformat() if selected else None
        ),
        "next_six_trading_sessions_known": supported,
        "known_trading_sessions_before_unknown": known_sessions,
        "calendar_known_through_date": known_through,
        "first_unknown_date": first_unknown,
        "calendar_source_ready_for_five_session_fallback": ready,
        "contains_return_label_signal_target_prediction_equity_or_pnl": False,
        "blockers": blockers,
        "live_trading_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--as-of-utc")
    args = parser.parse_args()
    print(
        json.dumps(
            assess(args.output_root, as_of_utc=args.as_of_utc),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
