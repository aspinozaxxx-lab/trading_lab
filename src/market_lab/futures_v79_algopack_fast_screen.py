"""Conditional AlgoPack event screen: no fit, no actual fills, no portfolio CAGR."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PROTOCOL = "v79_algopack_fast_screen_v1"
REPO = Path(__file__).resolve().parents[2]
CONFIG = f"configs/{PROTOCOL}.json"
FIELDS = ("return_1", "trade_imbalance", "volume_imbalance", "depth_l1", "depth_l10", "pressure")
ASSETS = ("BR", "MIX", "RI", "SI")
ARMS = ("pressure", "absorption", "depth_change", "price_momentum")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value: dict) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False) + "\n").encode("utf-8-sig")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify(seal_sha: str) -> dict:
    seal_path = REPO / f"configs/{PROTOCOL}.seal.json"
    if digest(seal_path) != seal_sha:
        raise ValueError("screen seal changed")
    seal = json.loads(seal_path.read_bytes())
    required = {CONFIG, "src/market_lab/futures_v79_algopack_fast_screen.py",
                "tests/test_futures_v79_algopack_fast_screen.py",
                "docs/V79_ALGOPACK_FAST_SCREEN.md",
                "docs/ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md",
                "configs/algopack_paper_training_v1.seal.json"}
    if seal["protocol_id"] != PROTOCOL or not required.issubset(seal["files"]):
        raise ValueError("incomplete screen closure")
    for relative, expected in seal["files"].items():
        path = (REPO / relative).resolve()
        if not path.is_relative_to(REPO.resolve()) or digest(path) != expected:
            raise ValueError("screen dependency changed")
    config = json.loads((REPO / CONFIG).read_bytes())
    parent = REPO / "configs/algopack_paper_training_v1.seal.json"
    if digest(parent) != config["parent_training_seal"]:
        raise ValueError("training closure changed")
    for relative, expected in json.loads(parent.read_bytes())["files"].items():
        path = (REPO / relative).resolve()
        if not path.is_relative_to(REPO.resolve()) or digest(path) != expected:
            raise ValueError("training dependency changed")
    return config


def checked_index(path: Path) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pq.read_table(path, columns=["information_end"])
                             .column("information_end").to_pandas())
    if (index.empty or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing
            or str(index.tz) != "UTC" or index.min() < pd.Timestamp("2020-01-01", tz="UTC")
            or index.max() + pd.Timedelta(minutes=70) >= pd.Timestamp("2026-01-01", tz="UTC")):
        raise ValueError("invalid or protected input dates")
    return index


def preflight(config: dict) -> pd.DatetimeIndex:
    root = Path(config["input_root"])
    if (root.resolve() != root.absolute()
            or digest(root / "manifest.json") != config["manifest_sha256"]):
        raise ValueError("input root or manifest changed")
    manifest = json.loads((root / "manifest.json").read_bytes())
    indices = []
    for name, expected in config["inputs"].items():
        path = root / name
        if (path.resolve().parent != root or digest(path) != expected
                or manifest["files"][name]["sha256"] != expected
                or path.stat().st_size != manifest["files"][name]["bytes"]):
            raise ValueError("input artifact changed")
        if name.endswith(".parquet"):
            indices.append(checked_index(path))
    if any(not index.equals(indices[0]) for index in indices[1:]):
        raise ValueError("feature label calendar differs")
    return indices[0]


def make_signals(calendar: pd.DataFrame, features: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Accepts NO labels, target masks, model/scaler or future quotes."""
    if not calendar.index.equals(features.index):
        raise ValueError("feature/calendar mismatch")
    if any("target" in name or "label" in name for name in features.columns):
        raise ValueError("label column in inference")
    rows = []
    for asset in ASSETS:
        f = features[[f"{asset}_{name}" for name in FIELDS]].copy()
        f.columns = FIELDS
        previous = f.shift(1)
        valid = (calendar[f"{asset}_plan_eligible"].fillna(False)
                 & features[f"{asset}_price_status"].eq("READY")
                 & features[f"{asset}_flow_status"].eq("READY")
                 & np.isfinite(f).all(axis=1))
        consecutive = (calendar.index.to_series().diff().eq(pd.Timedelta(minutes=10))
                       & calendar["local_date"].eq(calendar["local_date"].shift(1))
                       & calendar[f"{asset}_contract_id"].eq(
                           calendar[f"{asset}_contract_id"].shift(1)))
        eligible = valid & valid.shift(1, fill_value=False) & consecutive
        volume_sign = np.sign(f["volume_imbalance"])
        strong = f["volume_imbalance"].abs().ge(config["minimum_volume_imbalance"])
        pressure = (strong & f["pressure"].abs().ge(math.asinh(config["minimum_flow_to_depth"]))
                    & np.sign(f["trade_imbalance"]).eq(volume_sign)
                    & np.sign(f["depth_l10"]).eq(volume_sign))
        absorption = (strong & np.sign(f["return_1"]).eq(-volume_sign)
                      & np.sign(f["depth_l10"]).eq(-volume_sign))
        change = f["depth_l10"] - previous["depth_l10"]
        depth = (change.abs().ge(config["minimum_depth_change"])
                 & np.sign(f["depth_l1"] - previous["depth_l1"]).eq(np.sign(change)))
        directions = {
            "pressure": volume_sign.where(pressure, 0),
            "absorption": (-volume_sign).where(absorption, 0),
            "depth_change": np.sign(change).where(depth, 0),
            "price_momentum": np.sign(f["return_1"]),
        }
        for arm, direction in directions.items():
            values = direction.where(eligible, 0).fillna(0).astype(int)
            part = pd.DataFrame({"information_end": calendar.index, "asset": asset,
                                 "arm": arm, "eligible": eligible.to_numpy(),
                                 "direction": values.to_numpy(),
                                 "contract_id": calendar[f"{asset}_contract_id"].to_numpy()})
            rows.append(part)
    return pd.concat(rows, ignore_index=True)


def choose_events(signals: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, group in signals.groupby(["arm", "asset"], sort=True):
        last_exit = None
        chosen = []
        for row in group.itertuples(index=False):
            if not row.direction:
                continue
            entry = row.information_end + pd.Timedelta(minutes=10)
            if last_exit is not None and entry < last_exit:
                continue
            last_exit = entry + pd.Timedelta(minutes=60)
            chosen.append({**row._asdict(), "entry_at": entry, "exit_at": last_exit})
        if chosen:
            parts.append(pd.DataFrame(chosen))
    if parts:
        return pd.concat(parts, ignore_index=True)
    return pd.DataFrame(columns=[*signals.columns, "entry_at", "exit_at"])


def attach_outcomes(events: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    result["gross_bps"] = np.nan
    result["label_status"] = "MISSING_LABEL"
    for asset in ASSETS:
        mask = result["asset"].eq(asset)
        index = pd.DatetimeIndex(result.loc[mask, "information_end"])
        selected = labels.reindex(index)
        result.loc[mask, "label_status"] = selected[f"{asset}_label_status"].fillna(
            "MISSING_LABEL").to_numpy()
        values = selected[f"{asset}_target"].to_numpy(float)
        directions = result.loc[mask, "direction"].to_numpy(float)
        result.loc[mask, "gross_bps"] = directions * np.expm1(values) * 10000
    result["complete"] = np.isfinite(result["gross_bps"])
    result["year"] = pd.DatetimeIndex(result["information_end"]).year
    for multiplier, one_way in enumerate((5.0, 10.0), 1):
        result[f"net_{multiplier}x_bps"] = result["gross_bps"] - 2 * one_way
    return result


def stats(events: pd.DataFrame) -> dict:
    complete = events.loc[events["complete"]]
    report = {"selected_events": len(events), "completed_events": len(complete),
              "unresolved_events": len(events) - len(complete),
              "evaluation_coverage": len(complete) / len(events) if len(events) else None,
              "mean_gross_bps": None, "break_even_one_way_cost_bps": None,
              "CAGR": None, "Sharpe": None, "MDD": None,
              "portfolio_metrics_reason": "event assay; no capital, sizing, fills or MTM ledger"}
    if len(complete):
        report["mean_gross_bps"] = float(complete["gross_bps"].mean())
        report["break_even_one_way_cost_bps"] = report["mean_gross_bps"] / 2
    for cost in (1, 2):
        values = complete[f"net_{cost}x_bps"]
        report[f"cost_{cost}x"] = {
            "mean_net_bps": float(values.mean()) if len(values) else None,
            "median_net_bps": float(values.median()) if len(values) else None,
            "positive_fraction": float(values.gt(0).mean()) if len(values) else None,
        }
    return report


def summarize(events: pd.DataFrame, signals: pd.DataFrame, config: dict) -> dict:
    result = {}
    for arm in ARMS:
        selected = events.loc[events["arm"].eq(arm)]
        sig = signals.loc[signals["arm"].eq(arm)]
        item = stats(selected)
        item["calendar_opportunities"] = len(sig)
        item["eligible_opportunities"] = int(sig["eligible"].sum())
        item["nonzero_signals"] = int(sig["direction"].ne(0).sum())
        item["by_year"] = {str(year): stats(selected.loc[selected["year"].eq(year)])
                           for year in range(2020, 2026)}
        item["by_asset"] = {asset: stats(selected.loc[selected["asset"].eq(asset)])
                            for asset in ASSETS}
        annual = [v["cost_2x"]["mean_net_bps"] for v in item["by_year"].values()]
        thresholds = config["gates"]
        item["gates"] = {
            "events": item["completed_events"] >= thresholds["minimum_completed_events"],
            "complete": item["unresolved_events"] <= thresholds["maximum_unresolved_events"],
            "double_cost_edge": item["cost_2x"]["mean_net_bps"] is not None and
            item["cost_2x"]["mean_net_bps"] >= thresholds["minimum_mean_double_cost_bps"],
            "positive_years": sum(v is not None and v > 0 for v in annual) >=
            thresholds["minimum_positive_years_double_cost"],
            "worst_year": all(
                v is not None and v >= thresholds["minimum_worst_year_mean_double_cost_bps"]
                for v in annual),
        }
        item["verdict"] = "REJECT_STAGE1"
        if all(item["gates"].values()):
            item["verdict"] = "STAGE2_CANDIDATE_CONDITIONAL"
        elif item["gates"]["double_cost_edge"] and not item["gates"]["complete"]:
            item["verdict"] = "INCOMPLETE_NO_PROMOTION"
        if arm == "price_momentum":
            item["verdict"] = "CONTROL_ONLY"
        result[arm] = item
    return result


def run(seal_sha: str) -> dict:
    config = verify(seal_sha)
    if os.name != "posix" or os.getuid() != 999 or os.environ.get("MOEX_ALGOPACK_TOKEN"):
        raise ValueError("server-only economic run without authentication")
    root = Path(config["input_root"])
    expected_index = preflight(config)
    output = Path(config["output_parent"]) / f"{PROTOCOL}_{seal_sha[:12]}"
    if output.resolve() != output.absolute():
        raise ValueError("output path is not ordinary")
    output.mkdir(mode=0o750, exist_ok=False)
    started = time.monotonic()
    write_new(output / "STARTED.json", {"seal_sha256": seal_sha, "goal_verified": False})
    calendar = pd.read_parquet(root / "calendar.parquet")
    columns = [f"{asset}_{name}" for asset in ASSETS
               for name in (*FIELDS, "price_status", "flow_status")]
    features = pd.read_parquet(root / "features.parquet", columns=columns)
    if not calendar.index.equals(expected_index) or not features.index.equals(expected_index):
        raise ValueError("numeric projection index changed")
    signals = make_signals(calendar, features, config)
    intents = choose_events(signals)
    signals.to_parquet(output / "signals.parquet", index=False)
    intents.to_parquet(output / "intents.parquet", index=False)
    print("SIGNALS_AND_INTENTS_SAVED_BEFORE_LABEL_READ", flush=True)
    labels = pd.read_parquet(root / "labels.parquet",
                             columns=[f"{asset}_{name}" for asset in ASSETS
                                      for name in ("target", "label_status")])
    if not labels.index.equals(expected_index):
        raise ValueError("label index changed")
    events = attach_outcomes(intents, labels)
    events.to_parquet(output / "events.parquet", index=False)
    arms = summarize(events, signals, config)
    verify(seal_sha)
    for name, expected in config["inputs"].items():
        if digest(root / name) != expected:
            raise ValueError("input changed during economic screen")
    report = {"protocol_id": PROTOCOL, "seal_sha256": seal_sha, "arms": arms,
              "runtime_seconds": time.monotonic() - started,
              "input_manifest_sha256": config["manifest_sha256"],
              "source_original_version_verified": False, "model_fit": False,
              "portfolio_evaluation": False, "goal_verified": False,
              "live_trading_allowed": False, "conditional_current_vintage_only": True,
              "artifacts": {path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
                            for path in sorted(output.iterdir()) if path.is_file()}}
    write_new(output / "metrics.json", report)
    print(json.dumps({"output": str(output), "metrics_sha256": digest(output / "metrics.json"),
                      "verdicts": {k: v["verdict"] for k, v in arms.items()}}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    run(args.seal_sha256)


if __name__ == "__main__":
    main()
