"""Replay-audit componentized V27 forward sources and report causal readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_lab.futures import moex_v27_forward_component_source as source


def phase_progress(
    decision_dates: int,
    execution_dates: int,
    fred_snapshots: int,
    cbr_snapshots: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    rules = config["readiness"]
    warmup_required = int(rules["price_warmup_common_official_CLOSE_sessions"])
    evaluation_required = int(rules["unseen_evaluation_sessions"])
    warmup = min(decision_dates, warmup_required)
    evaluation = min(max(decision_dates - warmup_required, 0), evaluation_required)
    macro_ready = fred_snapshots > 0 and cbr_snapshots > 0
    paper_ready = warmup == warmup_required and macro_ready and execution_dates > 0
    if warmup < warmup_required:
        phase = "price_warmup"
    elif not macro_ready:
        phase = "macro_wait"
    elif evaluation < evaluation_required:
        phase = "unseen_evaluation"
    else:
        phase = "independent_review"
    return {
        "current_phase": phase,
        "price_warmup": {"complete": warmup, "required": warmup_required},
        "unseen_evaluation": {
            "complete": evaluation,
            "required": evaluation_required,
        },
        "execution_observation_unique_dates": execution_dates,
        "FRED_component_available": fred_snapshots > 0,
        "CBR_component_available": cbr_snapshots > 0,
        "macro_state_ready": macro_ready,
        "remaining_to_first_paper_decision": max(warmup_required - decision_dates, 0),
        "paper_economics_may_start": paper_ready,
        "evaluation_complete": evaluation == evaluation_required and macro_ready,
        "annualization_allowed": evaluation == evaluation_required and macro_ready,
        "live_trading_allowed": False,
    }


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = source.load_config()
    root = output_root.resolve()
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    market_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)
    macro: dict[str, list[dict[str, Any]]] = {"macro_fred": [], "macro_cbr": []}
    for snapshot in sorted(path for path in root.glob("snapshot_*") if path.is_dir()):
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"component replay audit failed: {', '.join(failed)}")
            component = str(manifest["component"])
            item = {
                "component": component,
                "snapshot": snapshot.name,
                "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
                "source_dates": list(manifest["source_dates"]),
                "rows": int(manifest["processed"]["rows"]),
            }
            valid.append(item)
            if component.startswith("market_"):
                if len(item["source_dates"]) != 1:
                    raise ValueError("market component must expose exactly one source date")
                identity = (component, str(item["source_dates"][0]))
                label = f"{identity[0]}:{identity[1]}"
                if identity in market_by_identity:
                    duplicates[label].extend(
                        [market_by_identity[identity]["snapshot"], snapshot.name]
                    )
                    del market_by_identity[identity]
                elif label in duplicates:
                    duplicates[label].append(snapshot.name)
                else:
                    market_by_identity[identity] = item
            else:
                macro[component].append(item)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})

    decision = sorted(
        (
            item
            for (component, _), item in market_by_identity.items()
            if component == "market_decision"
        ),
        key=lambda item: item["source_dates"][0],
    )
    execution = sorted(
        (
            item
            for (component, _), item in market_by_identity.items()
            if component == "market_execution"
        ),
        key=lambda item: item["source_dates"][0],
    )
    macro_times = {
        component: sorted(pd.Timestamp(item["retrieved_at_utc"]) for item in items)
        for component, items in macro.items()
    }
    joinable: list[str] = []
    for item in decision:
        decision_at = pd.Timestamp(item["retrieved_at_utc"])
        if all(
            any(retrieved_at <= decision_at for retrieved_at in macro_times[component])
            for component in ("macro_fred", "macro_cbr")
        ):
            joinable.append(str(item["source_dates"][0]))
    progress = phase_progress(
        len(decision),
        len(execution),
        len(macro["macro_fred"]),
        len(macro["macro_cbr"]),
        config,
    )
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": source.CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "snapshot_count": len(valid) + len(invalid),
        "valid_snapshot_count": len(valid),
        "invalid_snapshot_count": len(invalid),
        "valid_market_execution_dates": len(execution),
        "valid_market_decision_dates": len(decision),
        "valid_macro_FRED_snapshots": len(macro["macro_fred"]),
        "valid_macro_CBR_snapshots": len(macro["macro_cbr"]),
        "causally_joinable_decision_dates": len(joinable),
        "joinable_source_dates": joinable,
        "duplicate_market_component_dates": {
            key: sorted(set(value)) for key, value in duplicates.items()
        },
        "invalid_snapshots": invalid,
        "valid_snapshots": valid,
        "contains_signal_return_target_prediction_or_pnl": False,
        "progress": progress,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
