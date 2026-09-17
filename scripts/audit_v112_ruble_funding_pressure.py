"""Read-only post-outcome integrity/source/target/cash replay; no economic rerun."""

import argparse
import json
from pathlib import Path

import pandas as pd

from market_lab import futures_v112_ruble_funding_pressure as screen

SEAL = "2461c10932fa2cbcd85fe885690bdbe923aaaee0534827a625011d71692ea669"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--storage", type=Path, required=True)
    args = cli.parse_args()
    b = screen.base
    cfg, parent = screen.load(SEAL)
    root = b.safe(args.storage, "runs/" + cfg["protocol_id"] + "_" + SEAL[:12])
    manifest = screen.prior.read_json(root / "manifest.json")
    b.require(
        manifest["status"] == "COMPLETE" and manifest["seal_sha256"] == SEAL,
        "run manifest identity",
    )
    for name, digest in manifest["files"].items():
        b.require(b.sha(b.safe(root, name)) == digest, "run artifact drift")
    raw, monetary, _ = screen.source(cfg, args.storage)
    state = screen.states(screen.records(raw, monetary, cfg, numeric=True))
    pd.testing.assert_frame_equal(state, pd.read_parquet(root / "source_states.parquet"))
    checked = b.preflight(parent, args.storage)
    declared = b.declarations(parent)["recent"]
    active = pd.read_parquet(
        b.safe(args.storage, declared["active_map"]["path"]), columns=b.ACTIVE_COLS
    )
    signals = screen.targets(active, state, cfg)
    metrics = screen.prior.read_json(root / "metrics.json")
    case = metrics["case"]
    audit = screen.prior.audit_case(root / "case", case, signals)
    b.require(audit == metrics["audit"], "audit result drift")
    b.require(
        screen.engine.adapter.assess(case["metrics"], case["source_quality"], cfg)
        == case["assessment"],
        "assessment drift",
    )
    details = {}
    for arm in ("primary", "control"):
        s = signals[arm]
        exposed = s.target_weight.ne(0)
        detail = {
            "target_episodes": int((exposed & ~exposed.shift(fill_value=False)).sum()),
            "joint_ready_fraction": float(
                (~(s.feature_unavailable | s.stale_at_fill | s.source_unavailable)).mean()
            ),
        }
        for cost in ("base", "double"):
            orders = pd.read_parquet(root / "case" / f"orders_{arm}_{cost}.parquet")
            ledger = pd.read_parquet(root / "case" / f"ledger_{arm}_{cost}.parquet")
            categorical = {}
            for col in ("leg", "reason", "rejection_class"):
                if col in orders:
                    categorical[col] = {
                        str(k): int(v) for k, v in orders[col].value_counts().items()
                    }
            flagged = ledger.status.str.contains("cancel|block|reject", case=False)
            flagged |= ledger.critical_blocked_asset_count.gt(0)
            flagged |= ledger.factual_halt_asset_count.gt(0)
            columns = [
                "session_date",
                "status",
                "critical_blocked_asset_count",
                "factual_halt_asset_count",
                "gross_leverage",
            ]
            days = ledger.loc[flagged, columns]
            detail[cost] = {
                "orders": categorical,
                "capacity_or_halt_days": days.to_dict("records"),
                "metric_critical_failure_count": case["metrics"][arm][cost][
                    "critical_failure_count"
                ],
                "metric_gross_limit_rejection_count": case["metrics"][arm][cost][
                    "gross_limit_rejection_count"
                ],
            }
        details[arm] = detail
    print(
        json.dumps(
            {
                "status": "PASS",
                "manifest_sha256": b.sha(root / "manifest.json"),
                "metrics_sha256": b.sha(root / "metrics.json"),
                "verified_artifacts": len(manifest["files"]),
                "futures_checks": len(checked["checks"]),
                "source_state_rows": len(state),
                "audit": audit,
                "counts": case["counts"],
                "details": details,
                "assessment": case["assessment"],
                "no_economic_rerun": True,
            },
            default=str,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
