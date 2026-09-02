"""Replay-audit V39 option/V27 forward sources and report joint readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab import futures_v39_option_oi_tail_governor as v39
from market_lab.futures import forward_option_readiness as option_readiness
from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_validation_source as v27_source
from market_lab.futures import v27_forward_transport_compatibility as v27_transport
from market_lab.futures import v27_forward_validation_readiness as v27_readiness

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v39_forward_validation_v1.yaml"
CONFIG_SHA256: Final[str] = "3677bcca775da78089d0cfc81b92f0634b72eab777c040ad57e552da75bc6305"


def _sha(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config() -> dict[str, Any]:
    if _sha(CONFIG_PATH) != CONFIG_SHA256:
        raise ValueError("V39 forward protocol byte drift")
    if (
        CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
        != CONFIG_SHA256
    ):
        raise ValueError("V39 forward sidecar mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    v27_transport.assert_compatible(config["futures_source"]["implementation_sha256"])
    if (
        config["protocol_id"] != "futures_v39_forward_validation_v1"
        or config["live_trading_allowed"] is not False
        or config["development_candidate"]["protocol_sha256"] != v39.CONFIG_SHA256
        or config["development_candidate"]["implementation_sha256"] != _sha(Path(v39.__file__))
        or config["option_source"]["protocol_sha256"] != option_source.CONFIG_SHA256
        or config["option_source"]["implementation_sha256"] != _sha(Path(option_source.__file__))
        or config["futures_source"]["protocol_sha256"] != v27_source.CONFIG_SHA256
    ):
        raise ValueError("V39 forward identity invariants drifted")
    return config


def joint_progress(
    option_week_dates: list[date], futures_decision_dates: list[date], config: dict[str, Any]
) -> dict[str, Any]:
    option_required = int(config["warmup"]["option_unique_weekly_levels_required"])
    futures_required = int(config["warmup"]["futures_common_official_CLOSE_levels_required"])
    evaluation_required = int(config["evaluation"]["minimum_futures_sessions"])
    weekly_required = int(config["evaluation"]["minimum_weekly_decisions"])
    option_complete = len(option_week_dates) >= option_required
    futures_complete = len(futures_decision_dates) >= futures_required
    boundary: date | None = None
    if option_complete and futures_complete:
        boundary = max(
            option_week_dates[option_required - 1], futures_decision_dates[futures_required - 1]
        )
    evaluation_dates = [value for value in futures_decision_dates if boundary and value > boundary]
    evaluation_weeks = sorted({value.isocalendar()[:2] for value in evaluation_dates})
    if not option_complete or not futures_complete:
        phase = "joint_warmup"
    elif len(evaluation_dates) < evaluation_required or len(evaluation_weeks) < weekly_required:
        phase = "unseen_evaluation"
    else:
        phase = "independent_review"
    return {
        "current_phase": phase,
        "option_weekly_levels": {
            "complete": min(len(option_week_dates), option_required),
            "required": option_required,
        },
        "option_weekly_changes_available": max(len(option_week_dates) - 1, 0),
        "option_strictly_prior_changes_for_latest": max(len(option_week_dates) - 2, 0),
        "futures_close_levels": {
            "complete": min(len(futures_decision_dates), futures_required),
            "required": futures_required,
        },
        "joint_warmup_complete": option_complete and futures_complete,
        "joint_warmup_boundary": boundary.isoformat() if boundary else None,
        "evaluation_futures_sessions": {
            "complete": min(len(evaluation_dates), evaluation_required),
            "required": evaluation_required,
        },
        "evaluation_weekly_decisions": {
            "complete": min(len(evaluation_weeks), weekly_required),
            "required": weekly_required,
        },
        "paper_economics_may_start": option_complete and futures_complete,
        "evaluation_complete": len(evaluation_dates) >= evaluation_required
        and len(evaluation_weeks) >= weekly_required,
        "cagr_reporting_allowed": len(evaluation_dates) >= evaluation_required
        and len(evaluation_weeks) >= weekly_required,
        "second_unseen_confirmation_still_required": True,
        "live_trading_allowed": False,
    }


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    futures_root: Path = v27_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    option_report = option_readiness.assess(option_root)
    futures_report = v27_readiness.assess(futures_root)
    valid_option_dates: dict[str, list[str]] = defaultdict(list)
    invalid_v39_option: list[dict[str, str]] = []
    for item in option_report["valid_snapshots"]:
        snapshot = option_root.resolve() / item["snapshot"]
        try:
            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
            frame = pd.read_parquet(
                snapshot / manifest["processed"]["path"],
                columns=["source_date", "asset_code", "option_type", "open_interest"],
            )
            frame["open_interest"] = pd.to_numeric(frame["open_interest"], errors="coerce")
            source_dates = pd.to_datetime(frame["source_date"], errors="raise").dt.date.unique()
            if len(source_dates) != 1 or source_dates[0].isoformat() != item["source_date"]:
                raise ValueError("processed source date mismatch")
            if set(frame["asset_code"]) != {"SI", "RI", "BR", "MIX"}:
                raise ValueError("four-asset option universe incomplete")
            totals = frame.groupby(["asset_code", "option_type"])["open_interest"].sum(min_count=1)
            for asset in ("SI", "RI", "BR", "MIX"):
                if (
                    float(totals.get((asset, "C"), 0.0)) <= 0.0
                    or float(totals.get((asset, "P"), 0.0)) <= 0.0
                ):
                    raise ValueError(f"nonpositive call/put OI for {asset}")
            valid_option_dates[item["source_date"]].append(item["snapshot"])
        except (KeyError, OSError, TypeError, ValueError) as error:
            invalid_v39_option.append({"snapshot": item["snapshot"], "reason": str(error)})
    unique_option_dates = sorted(date.fromisoformat(value) for value in valid_option_dates)
    week_to_dates: dict[tuple[int, int], list[date]] = defaultdict(list)
    for value in unique_option_dates:
        iso = value.isocalendar()
        week_to_dates[(iso.year, iso.week)].append(value)
    weekly_state_dates = sorted(max(values) for values in week_to_dates.values())
    futures_dates = sorted(
        date.fromisoformat(item["source_date"])
        for item in futures_report["valid_snapshots"]
        if item["snapshot_kind"] == "decision_eod"
    )
    progress = joint_progress(weekly_state_dates, sorted(set(futures_dates)), config)
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "option_root": str(option_root.resolve()),
        "futures_root": str(futures_root.resolve()),
        "valid_option_daily_dates": len(unique_option_dates),
        "valid_option_weekly_levels": len(weekly_state_dates),
        "first_option_weekly_level": weekly_state_dates[0].isoformat()
        if weekly_state_dates
        else None,
        "last_option_weekly_level": weekly_state_dates[-1].isoformat()
        if weekly_state_dates
        else None,
        "invalid_v39_option_snapshots": invalid_v39_option,
        "option_source_invalid_snapshot_count": option_report["invalid_snapshot_count"],
        "futures_source_invalid_snapshot_count": futures_report["invalid_snapshot_count"],
        "valid_futures_decision_dates": len(set(futures_dates)),
        "valid_futures_execution_dates": futures_report["valid_unique_execution_date_count"],
        "contains_signal_return_or_pnl": False,
        "progress": progress,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--futures-root", type=Path, default=v27_source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.option_root, args.futures_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
