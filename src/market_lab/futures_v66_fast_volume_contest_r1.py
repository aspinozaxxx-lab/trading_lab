"""Versioned nullable-counting repair; preserve every V66 signal and ledger byte."""

import argparse
import json
from pathlib import Path

from market_lab import futures_v66_fast_volume_contest as original

base = original.base
CONFIG = original.PROJECT / "configs/v66_fast_volume_contest_r1.json"
SEAL = original.PROJECT / "configs/v66_fast_volume_contest_r1.seal.json"
ORIGINAL_COUNTER = original.position_counts


def position_counts(positions):
    normalized = positions.copy()
    normalized["contract_id"] = normalized.contract_id.fillna("__FLAT__").astype(str)
    return ORIGINAL_COUNTER(normalized)


def load(expected):
    base.require(base.sha(SEAL) == expected, "R1 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(original.PROJECT, name)) == digest, "R1 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    base.require(not cfg["economic_rules_changed"], "not a reporting-only repair")
    parent_cfg, parent_inputs = original.load(cfg["parent_v66_seal_sha256"])
    return {**parent_cfg, "protocol_id": cfg["protocol_id"]}, parent_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg, parent = load(args.seal_sha)
    # Explicit, process-scoped reporting hook: no signal, ledger, fee or gate changes.
    original.position_counts = position_counts
    try:
        if args.audit:
            print(json.dumps(original.audit(args.audit)))
        else:
            original.run(cfg, parent, args.storage_root, args.seal_sha)
    finally:
        original.position_counts = ORIGINAL_COUNTER


if __name__ == "__main__":
    main()
