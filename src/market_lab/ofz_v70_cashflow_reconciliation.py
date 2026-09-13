"""Resolve zero-entitlement source flags without rerunning V70 trading decisions."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import ofz_v70_relative_curve as parent

base = parent.base
CONFIG = base.PROJECT / "configs/v70_ofz_relative_curve_r1.json"
SEAL = base.PROJECT / "configs/v70_ofz_relative_curve_r1.seal.json"


def load(expected):
    base.require(base.sha(SEAL) == expected, "R1 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "R1 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    return cfg, parent.load(cfg["parent_seal_sha256"])


def prepare_metadata(positions, trades, ledger):
    """Absence means zero only in a proved complete, fully enumerated position book."""
    positions, trades, ledger = positions.copy(), trades.copy(), ledger.copy()
    for frame, name in ((positions, "date"), (trades, "execution_date"), (ledger, "date")):
        frame[name] = pd.to_datetime(frame[name])
        base.require(frame[name].notna().all(), "missing date")
        base.require(frame[name].lt(base.BOUNDARY).all(), "protected outcome date")
    base.require(not ledger.empty and not ledger.date.duplicated().any(), "invalid calendar")
    base.require(ledger.mark_complete.eq(True).all(), "incomplete marks")  # noqa: E712
    base.require(not positions.duplicated(["date", "security_id"]).any(), "duplicate position")
    base.require(positions.security_id.notna().all(), "missing position identity")
    base.require(trades.security_id.notna().all(), "missing trade identity")
    base.require(
        positions.date.isin(ledger.date).all() and trades.execution_date.isin(ledger.date).all(),
        "incomplete calendar",
    )
    base.require(
        np.isfinite(positions.quantity).all() and positions.quantity.gt(0).all(),
        "unknown or nonpositive holding",
    )
    counted = positions.groupby("date").size().reindex(ledger.date, fill_value=0).to_numpy()
    base.require(np.array_equal(counted, ledger.held_security_count.to_numpy()), "missing holdings")
    return positions, trades, ledger.sort_values("date").reset_index(drop=True)


def resolve(schedule, positions, trades, ledger, evidence, expected_missing):
    """No guessed dates, no zero-imputed amounts, no release while entitlement is uncertain."""
    missing = schedule.loc[schedule.record_date.isna() | schedule.value_rub.isna()].copy()
    base.require(len(missing) == expected_missing, "unexpected unresolved event count")
    base.require(
        not missing.duplicated(["security_id", "event_date"]).any(), "duplicate missing event"
    )
    facts = {(e["security_id"], pd.Timestamp(e["event_date"])): e for e in evidence}
    base.require(len(facts) == len(evidence), "duplicate evidence")
    missing_keys = set(zip(missing.security_id, missing.event_date, strict=True))
    base.require(set(facts) <= missing_keys, "unused or mismatched evidence")
    proof = []
    for event in missing.itertuples():
        base.require(
            event.event_kind == "amortization"
            and pd.isna(event.record_date)
            and np.isfinite(event.value_rub)
            and event.value_rub > 0,
            "unresolved coupon or amount; no permission to impute",
        )
        base.require(
            ledger.date.min() <= event.event_date <= ledger.date.max(),
            "event outside complete calendar",
        )
        held = positions.loc[positions.security_id.eq(event.security_id)]
        orders = trades.loc[trades.security_id.eq(event.security_id)]
        fact = facts.get((event.security_id, event.event_date))
        record_date, reference = None, None
        if held.empty and orders.empty:
            method = "NEVER_HELD_OR_TRADED"
        else:
            base.require(fact is not None, "missing exact record-date evidence")
            day = pd.Timestamp(fact["record_date"])
            base.require(day < event.event_date and day in set(ledger.date), "invalid record date")
            base.require(held.loc[held.date.eq(day)].empty, "positive entitlement")
            # A conservative settlement guard, not a replacement for the exact record date.
            start = event.event_date - pd.Timedelta(days=365)
            base.require(
                held.loc[held.date.ge(start)].empty
                and orders.loc[orders.execution_date.ge(start)].empty,
                "recent or subsequent exposure; immutable zero-credit repair not allowed",
            )
            record_date, reference = fact["record_date"], fact["reference"]
            method = "EXACT_REDEMPTION_RECORD_DATE_ZERO_ENTITLEMENT"
        proof.append(
            {
                "security_id": event.security_id,
                "event_date": str(event.event_date.date()),
                "record_date_evidence": record_date,
                "source_reference": reference,
                "resolution": method,
                "entitlement_quantity": 0.0,
                "cash_change_rub": 0.0,
            }
        )
    return proof


def verify_existing_credits(schedule, positions, ledger):
    """Independently replay known schedule credits; resolved unknowns are separately proved zero."""
    days = pd.DatetimeIndex(ledger.date)
    cash = pd.Series(0.0, index=days)
    quantity = positions.set_index(["date", "security_id"]).quantity
    for event in schedule.itertuples():
        if pd.isna(event.record_date) or pd.isna(event.value_rub):
            continue
        credit_days = days[days >= event.event_date]
        if len(credit_days) == 0:
            continue
        credit_day = credit_days[0]
        prior = days[(days <= event.record_date) & (days < credit_day)]
        held = float(quantity.get((prior[-1], event.security_id), 0.0)) if len(prior) else 0.0
        cash.loc[credit_day] += held * event.value_rub
    base.require(
        np.allclose(cash.to_numpy(), ledger.cashflow_credit_rub.to_numpy(), rtol=1e-12, atol=1e-7),
        "existing cashflow credit drift",
    )


def preflight(cfg, original, storage):
    checks = parent.preflight(original, storage)
    root = base.safe(storage, cfg["parent_run"])
    base.require(
        base.sha(root / "identity.json") == cfg["parent_identity_sha256"], "parent identity"
    )
    base.require(base.sha(root / "metrics.json") == cfg["parent_metrics_sha256"], "parent metrics")
    identity = json.loads((root / "identity.json").read_text(encoding="utf-8-sig"))
    base.require(identity["seal_sha256"] == cfg["parent_seal_sha256"], "parent run seal")
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "parent artifact drift")
    evidence_root = base.safe(storage, cfg["evidence_root"])
    for name, spec in cfg["documents"].items():
        path = base.safe(evidence_root, name)
        base.require(
            path.stat().st_size == spec["bytes"] and base.sha(path) == spec["sha256"],
            "accounting evidence drift",
        )
    checks.update(parent_artifacts=len(identity["files"]), evidence_documents=len(cfg["documents"]))
    return root, checks


def evaluate(cfg, original, storage):
    root, checks = preflight(cfg, original, storage)
    previous = json.loads((root / "metrics.json").read_text(encoding="utf-8-sig"))
    base.require(
        previous["assessment"]["verdict"] == "INVALID_INCOMPLETE_ACCOUNTING",
        "not an accounting-only parent",
    )
    schedule = parent.engine._schedule(
        pd.read_parquet(
            base.safe(storage, original["inputs"]["bondization"]["path"]),
            columns=list(parent.engine.SCHEDULE_COLUMNS),
        ),
        original,
    )
    staged, proofs = {}, []
    # Prove every arm/cost complete before reading any NAV or publishing any performance.
    for arm in parent.ARMS:
        for scenario in original["cost_scenarios"]:
            old = previous["metrics"][arm][scenario]
            base.require(
                old["performance"] is None
                and old["marked_sessions"] == old["total_sessions"]
                and old["unresolved_rebalances"] == 0
                and old["unresolved_cashflows"] == cfg["expected_unresolved_each_scenario"],
                "parent has other incomplete accounting",
            )
            positions = pd.read_parquet(
                root / f"positions_{arm}_{scenario}.parquet",
                columns=["date", "security_id", "quantity"],
            )
            trades = pd.read_parquet(
                root / f"trades_{arm}_{scenario}.parquet",
                columns=["execution_date", "security_id"],
            )
            meta = pd.read_parquet(
                root / f"ledger_{arm}_{scenario}.parquet",
                columns=["date", "mark_complete", "held_security_count"],
            )
            positions, trades, meta = prepare_metadata(positions, trades, meta)
            base.require(len(meta) == old["total_sessions"], "missing calendar rows")
            proof = resolve(
                schedule,
                positions,
                trades,
                meta,
                cfg["record_date_evidence"],
                cfg["expected_unresolved_each_scenario"],
            )
            proofs.extend({"arm": arm, "costs": scenario, **row} for row in proof)
            staged[arm, scenario] = old
    metrics, valuations = {arm: {} for arm in parent.ARMS}, {}
    for (arm, scenario), old in staged.items():
        trades = pd.read_parquet(root / f"trades_{arm}_{scenario}.parquet")
        positions = pd.read_parquet(root / f"positions_{arm}_{scenario}.parquet")
        ledger = pd.read_parquet(root / f"ledger_{arm}_{scenario}.parquet")
        positions, trades, ledger = prepare_metadata(positions, trades, ledger)
        verify_existing_credits(schedule, positions, ledger)
        result = parent.engine.SimulationResult(
            trades,
            positions,
            ledger,
            old["completed_rebalances"],
            0,
            0,
            old["marked_sessions"],
            old["total_sessions"],
        )
        summary, valuation = parent.summarize(result, original, scenario)
        for key in (
            "trade_legs",
            "turnover_rub",
            "trading_cost_rub",
            "coupon_and_amortization_credit_rub",
        ):
            base.require(np.isclose(summary[key], old[key]), "original accounting changed")
        metrics[arm][scenario] = {
            **summary,
            "sourcewide_missing_record_dates": old["unresolved_cashflows"],
            "resolved_zero_entitlement": cfg["expected_unresolved_each_scenario"],
        }
        valuations[arm, scenario] = valuation
    return (
        {
            "protocol_id": cfg["protocol_id"],
            "parent_run": cfg["parent_run"],
            "parent_identity_sha256": cfg["parent_identity_sha256"],
            "input_checks": checks,
            "metrics": metrics,
            "counts": previous["counts"],
            "assessment": parent.assess(metrics, previous["counts"], original),
            "strategy_simulations_rerun": 0,
            "original_artifacts_modified": 0,
            "limitations": original["limitations"] + cfg["limitations"],
            "goal_verified": False,
        },
        pd.DataFrame(proofs),
        valuations,
    )


def run(cfg, original, storage, expected):
    base.require(os.name == "posix", "server-only accounting evaluation")
    output = base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing canonical correction; no repeat")
    started = time.monotonic()
    payload, proof, valuations = evaluate(cfg, original, storage)
    output.mkdir(parents=True, exist_ok=False)
    payload.update(seal_sha256=expected, runtime_seconds=time.monotonic() - started)
    proof.to_parquet(output / "zero_entitlement_proof.parquet", index=False)
    for (arm, scenario), frame in valuations.items():
        frame.to_parquet(output / f"valuation_{arm}_{scenario}.parquet", index=False)
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": expected,
            "files": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)


def audit(cfg, original, storage, output, expected):
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    base.require(identity["seal_sha256"] == expected, "correction identity seal")
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(output, name)) == digest, "correction artifact drift")
    saved = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    base.require(saved["seal_sha256"] == expected, "correction report seal")
    replay, proof, valuations = evaluate(cfg, original, storage)
    for key, value in replay.items():
        base.require(saved[key] == value, "correction replay drift: " + key)
    pd.testing.assert_frame_equal(proof, pd.read_parquet(output / "zero_entitlement_proof.parquet"))
    for (arm, scenario), frame in valuations.items():
        pd.testing.assert_frame_equal(
            frame, pd.read_parquet(output / f"valuation_{arm}_{scenario}.parquet")
        )
    return {
        "all_true": True,
        "artifact_hashes": len(identity["files"]),
        "proof_rows": len(proof),
        "metric_and_credit_replays": len(valuations),
        "parent_artifacts": replay["input_checks"]["parent_artifacts"],
        "strategy_simulations_rerun": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, original = load(args.seal_sha)
    if args.audit:
        print(json.dumps(audit(cfg, original, args.storage_root, args.audit, args.seal_sha)))
    else:
        run(cfg, original, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
