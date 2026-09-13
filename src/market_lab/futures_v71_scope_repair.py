"""Sealed V71 input-scope repair; unchanged frozen experiment and exact-key checks."""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from market_lab import futures_v71_liquidity_surprise as v1
from market_lab.futures import execution_dataset as assembly

base = v1.base
CONFIG = base.PROJECT / "configs/v71_cbr_liquidity_surprise_r1.json"
SEAL = base.PROJECT / "configs/v71_cbr_liquidity_surprise_r1.seal.json"


def load(expected):
    base.require(base.sha(SEAL) == expected, "R1 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "R1 file drift")
    repair = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    cfg, parent = v1.load(repair["parent_v1_seal_sha256"])
    base.require(
        not repair["goal_verified"] and not repair["live_trading_allowed"], "research only"
    )
    return {**cfg, "protocol_id": repair["protocol_id"]}, parent, repair


def select_specs(observations, specs):
    dates = pd.to_datetime(observations.session_date)
    base.require(observations.asset_code.eq("SI").all(), "unexpected observation universe")
    base.require(
        dates.notna().all() and dates.between("2021-01-01", "2025-12-31").all(),
        "unexpected observation dates",
    )
    spec_dates = pd.to_datetime(specs.session_date)
    return specs.loc[
        specs.asset_symbol.eq("SI") & spec_dates.between("2021-01-01", "2025-12-31")
    ].copy()


def aligned_market(observations, specs):
    return assembly.build_portfolio_market(observations, select_specs(observations, specs))


@contextmanager
def repaired_runtime():
    """Process-local adapter; never alter the sealed V1 files or shared implementation."""
    old_builder, old_seal = base.build_portfolio_market, v1.SEAL
    base.build_portfolio_market, v1.SEAL = aligned_market, SEAL
    try:
        yield
    finally:
        base.build_portfolio_market, v1.SEAL = old_builder, old_seal


def verify_failed_parent(repair, storage):
    spec = repair["failed_parent"]
    root = base.safe(storage, spec["root"])
    base.require(
        {p.name for p in root.iterdir()} == set(spec["files"]),
        "parent acquired economic outputs or changed",
    )
    for name, digest in spec["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "failed parent drift")


def audit(output, cfg, repair, storage):
    verify_failed_parent(repair, storage)
    for name, digest in repair["failed_parent"]["files"].items():
        base.require(base.sha(output / name) == digest, "inherited inputs/states changed")
    with repaired_runtime():
        result = v1.audit(output, cfg, storage)
    return {**result, "unchanged_parent_inputs_and_states": True, "new_hypothesis": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, parent, repair = load(args.seal_sha)
    verify_failed_parent(repair, args.storage_root)
    if args.audit:
        print(json.dumps(audit(args.audit, cfg, repair, args.storage_root)))
    else:
        with repaired_runtime():
            v1.run(cfg, parent, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
