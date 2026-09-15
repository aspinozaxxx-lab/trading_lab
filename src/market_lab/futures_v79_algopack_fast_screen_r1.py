"""V79 source-tag correction only; all economic rules remain in frozen parent."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from market_lab import futures_v79_algopack_fast_screen as parent

PROTOCOL = "v79_algopack_fast_screen_r1"
CONFIG = f"configs/{PROTOCOL}.json"
FLOW_STATUS = "READY_ARCHIVE_ASSUMPTION"


def verify(seal_sha: str) -> tuple[dict, dict]:
    path = parent.REPO / f"configs/{PROTOCOL}.seal.json"
    if parent.digest(path) != seal_sha:
        raise ValueError("R1 seal changed")
    seal = json.loads(path.read_bytes())
    required = {CONFIG, "src/market_lab/futures_v79_algopack_fast_screen_r1.py",
                "tests/test_futures_v79_algopack_fast_screen_r1.py",
                "docs/V79_ALGOPACK_FAST_SCREEN_R1.md",
                "configs/v79_algopack_fast_screen_v1.seal.json"}
    if seal["protocol_id"] != PROTOCOL or not required.issubset(seal["files"]):
        raise ValueError("R1 closure incomplete")
    for relative, expected in seal["files"].items():
        item = (parent.REPO / relative).resolve()
        if not item.is_relative_to(parent.REPO.resolve()) or parent.digest(item) != expected:
            raise ValueError("R1 dependency changed")
    config = json.loads((parent.REPO / CONFIG).read_bytes())
    if config["admitted_flow_status"] != FLOW_STATUS:
        raise ValueError("R1 status policy changed")
    return config, parent.verify(config["parent_seal_sha256"])


def make_signals(calendar: pd.DataFrame, features: pd.DataFrame, config: dict) -> pd.DataFrame:
    projected = features.copy(deep=False)
    for asset in parent.ASSETS:
        column = f"{asset}_flow_status"
        projected[column] = features[column].eq(FLOW_STATUS).map(
            {True: "READY", False: "NOT_ARCHIVE_READY"})
    return parent.make_signals(calendar, projected, config)


def run(seal_sha: str) -> dict:
    correction, config = verify(seal_sha)
    if os.name != "posix" or os.getuid() != 999 or os.environ.get("MOEX_ALGOPACK_TOKEN"):
        raise ValueError("server-only economic run without authentication")
    root = Path(config["input_root"])
    index = parent.preflight(config)
    output = Path(config["output_parent"]) / f"{PROTOCOL}_{seal_sha[:12]}"
    if output.resolve() != output.absolute():
        raise ValueError("output path is not ordinary")
    output.mkdir(mode=0o750, exist_ok=False)
    started = time.monotonic()
    parent.write_new(output / "STARTED.json", {"seal_sha256": seal_sha, "goal_verified": False})
    try:
        calendar = pd.read_parquet(root / "calendar.parquet")
        columns = [f"{asset}_{name}" for asset in parent.ASSETS
                   for name in (*parent.FIELDS, "price_status", "flow_status")]
        features = pd.read_parquet(root / "features.parquet", columns=columns)
        if not calendar.index.equals(index) or not features.index.equals(index):
            raise ValueError("numeric projection index changed")
        status_counts = {column: features[column].value_counts(dropna=False).to_dict()
                         for column in columns if column.endswith("status")}
        signals = make_signals(calendar, features, config)
        if int(signals["eligible"].sum()) < correction["minimum_feature_eligible_opportunities"]:
            raise ValueError("NO_FEATURE_ELIGIBILITY_NOT_AN_ECONOMIC_REJECTION")
        intents = parent.choose_events(signals)
        signals.to_parquet(output / "signals.parquet", index=False)
        intents.to_parquet(output / "intents.parquet", index=False)
        print("R1_SIGNALS_AND_INTENTS_SAVED_BEFORE_LABEL_READ", flush=True)
        labels = pd.read_parquet(root / "labels.parquet",
                                 columns=[f"{asset}_{name}" for asset in parent.ASSETS
                                          for name in ("target", "label_status")])
        if not labels.index.equals(index):
            raise ValueError("label index changed")
        events = parent.attach_outcomes(intents, labels)
        events.to_parquet(output / "events.parquet", index=False)
        arms = parent.summarize(events, signals, config)
        verify(seal_sha)
        for name, expected in config["inputs"].items():
            if parent.digest(root / name) != expected:
                raise ValueError("input changed during economic screen")
        report = {"protocol_id": PROTOCOL, "seal_sha256": seal_sha, "arms": arms,
                  "runtime_seconds": time.monotonic() - started,
                  "input_manifest_sha256": config["manifest_sha256"],
                  "original_feature_status_counts": status_counts,
                  "source_original_version_verified": False, "model_fit": False,
                  "portfolio_evaluation": False, "goal_verified": False,
                  "live_trading_allowed": False, "conditional_current_vintage_only": True,
                  "artifacts": {path.name: {"sha256": parent.digest(path),
                                            "bytes": path.stat().st_size}
                                for path in sorted(output.iterdir()) if path.is_file()}}
        parent.write_new(output / "metrics.json", report)
        print(json.dumps({"output": str(output),
                          "metrics_sha256": parent.digest(output / "metrics.json"),
                          "verdicts": {k: v["verdict"] for k, v in arms.items()}}), flush=True)
        return report
    except Exception as error:
        parent.write_new(output / "FAILED.json", {"error_type": type(error).__name__,
                                                   "goal_verified": False})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    run(args.seal_sha256)


if __name__ == "__main__":
    main()
