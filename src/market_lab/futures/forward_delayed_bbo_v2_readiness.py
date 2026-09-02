"""Report source-only readiness of delayed public-ISS cross and carry BBO V2."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from market_lab.futures import moex_forward_broad_stock_futures_carry_source_v2 as broad
from market_lab.futures import moex_forward_cross_market_bbo_source_v2 as cross


def _one(
    source,
    root: Path,
    *,
    complete_status: str,
    minimum_key: str,
) -> dict[str, Any]:
    config = source.load_config()
    snapshots = sorted(root.glob("snapshot_*")) if root.exists() else []
    manifests: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    statuses: Counter[str] = Counter()
    for snapshot in snapshots:
        try:
            checks = source.audit(snapshot)
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            statuses[str(manifest.get("status", "missing"))] += 1
            if all(checks.values()):
                manifests.append(manifest)
            else:
                invalid.append({"snapshot": snapshot.name, "reason": "audit_false"})
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": type(error).__name__})
    complete = [item for item in manifests if item.get("status") == complete_status]
    by_session = Counter(str(item["source_date"]) for item in complete)
    minimum = int(config["readiness"][minimum_key])
    complete_sessions = sorted(
        source_date for source_date, count in by_session.items() if count >= minimum
    )
    discovery_required = int(config["readiness"]["discovery_sessions_source_only"])
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": source.CONFIG_SHA256,
        "source_root": str(root),
        "source_only": True,
        "delayed_bbo_only": True,
        "depth_realtime_size_queue_fill_unresolved": True,
        "return_signal_trade_or_pnl_computed": False,
        "live_trading_allowed": False,
        "counts": {
            "snapshot_directories": len(snapshots),
            "audited_snapshots": len(manifests),
            "quote_complete_snapshots": len(complete),
            "invalid_or_unreadable_snapshots": len(invalid),
            "complete_sessions": len(complete_sessions),
        },
        "status_counts": dict(sorted(statuses.items())),
        "complete_snapshots_by_session": dict(sorted(by_session.items())),
        "complete_session_dates": complete_sessions,
        "invalid": invalid,
        "gates": {
            "minimum_quote_complete_snapshots_per_session": minimum,
            "discovery_sessions": {
                "complete": len(complete_sessions),
                "required": discovery_required,
                "ready": len(complete_sessions) >= discovery_required,
            },
            "separate_economic_protocol_sealed": False,
            "annualization_allowed": False,
            "realtime_or_depth_promotion_allowed": False,
            "live_allowed": False,
        },
    }


def readiness(
    cross_root: Path | None = None, broad_root: Path | None = None
) -> dict[str, Any]:
    cross_config = cross.load_config()
    broad_config = broad.load_config()
    resolved_cross = (
        cross_root.resolve()
        if cross_root is not None
        else cross._safe_output_root(str(cross_config["output"]["root"])).resolve()
    )
    resolved_broad = (
        broad_root.resolve()
        if broad_root is not None
        else broad._safe_output_root(str(broad_config["output"]["root"])).resolve()
    )
    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "cross_market": _one(
            cross,
            resolved_cross,
            complete_status="complete_core_quotes",
            minimum_key="minimum_complete_core_snapshots_per_session",
        ),
        "broad_carry": _one(
            broad,
            resolved_broad,
            complete_status="complete_30_pair_quotes",
            minimum_key="minimum_complete_snapshots_per_session",
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cross-root", type=Path)
    parser.add_argument("--broad-root", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            readiness(args.cross_root, args.broad_root),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
