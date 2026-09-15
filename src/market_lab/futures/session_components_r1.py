"""V93 R1: price-unit diagnostics; daily estimated cash multipliers are not exact specs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import session_components as base

CONFIG = base.ROOT / "configs/v93_session_components_r1.json"
SEAL = base.ROOT / "configs/v93_session_components_r1.seal.json"


def price_unit_specs(specs: pd.DataFrame) -> pd.DataFrame:
    """Convert each known fee/tick amount to quote points, NOT to fictitious RUB.

    Estimated p(t) = VALUE/(VOLUME*WAPRICE), lagged, is not a contract change.
    Gross price return is dimensionless. Tick costs and fee estimates are divided
    by their own strictly-prior p(t); no tolerance is fitted to market outcomes.
    """
    base.spec_index(specs)
    result = specs.copy()
    point = pd.to_numeric(result.sizing_point_value, errors="raise")
    valid = np.isfinite(point) & point.gt(0)
    for field in ("sizing_tick_cash_value", "conservative_fee_per_side"):
        result.loc[valid, field] = result.loc[valid, field] / point.loc[valid]
    result.loc[valid, "sizing_point_value"] = 1.0
    return result


def calculate(requests: pd.DataFrame, market, specs: pd.DataFrame, cfg: dict) -> tuple:
    normalized = price_unit_specs(specs)
    # Original requests still use original prior data. No entry/exit clock or capacity changed.
    pairs = pd.concat(
        [base.evaluate(requests, market, normalized, cfg, cost) for cost in cfg["costs"]],
        ignore_index=True,
    )
    report = base.report(pairs, cfg)
    for item in report["results"].values():
        item.pop("costs_cash_observed_pairs")
        item["interpretation"] = (
            "conditional price-return component with normalized fee proxies; no RUB cash PnL"
        )
        item["mean_cost_bp"] = item["mean_gross_bp"] - item["mean_net_bp"]
    pairs = pairs.rename(
        columns={
            "gross_cash": "gross_quote_points",
            "costs_cash": "costs_quote_points",
            "net_cash": "net_quote_points",
            "entry_notional": "entry_price_quote_points",
        }
    )
    return pairs, report


def run(expected_seal: str) -> dict:
    if os.name == "nt" or os.geteuid() != 999:
        raise RuntimeError("server UID999 required")
    if base.sha(SEAL) != expected_seal:
        raise ValueError("R1 seal drift")
    for name, expected in base.read_json(SEAL)["files"].items():
        if base.sha(base.ROOT / name) != expected:
            raise ValueError(f"R1 file drift: {name}")
    card = base.read_json(CONFIG)
    if base.sha(base.SEAL) != card["parent_seal_sha256"]:
        raise ValueError("parent seal drift")
    for name, expected in base.read_json(base.SEAL)["files"].items():
        if base.sha(base.ROOT / name) != expected:
            raise ValueError(f"parent file drift: {name}")
    cfg = base.read_json(base.CONFIG)
    parent_path = base.ROOT / cfg["source_config"]
    if base.sha(parent_path) != cfg["source_config_sha256"]:
        raise ValueError("source config drift")
    parent = yaml.safe_load(parent_path.read_text(encoding="utf-8-sig"))
    artifacts, plan, sessions, evidence = base.sources(Path(cfg["source_root"]), parent)
    spec_path = Path(evidence["spec_proxy"]["path"])
    dates = pd.read_parquet(spec_path, columns=["session_date", "sizing_observed_session_date"])
    if any(pd.to_datetime(dates[c]).ge(pd.Timestamp("2026-01-01")).any() for c in dates):
        raise ValueError("protected spec dates")
    output = Path("/srv/trading_lab_data/runs") / f"v93_session_components_r1_{expected_seal[:12]}"
    output.mkdir(exist_ok=False)
    base.write_json(output / "started.json", dict(at=datetime.now(UTC), seal_sha256=expected_seal))
    market = base.load_market(
        [a for a in artifacts if a["asset"] == cfg["asset"]],
        plan.loc[plan.asset.eq(cfg["asset"])],
        sessions,
    )
    specs = pd.read_parquet(spec_path, columns=base.SPEC_COLUMNS)
    candidates = base.requests(market, specs, cfg)
    candidates.to_parquet(output / "requests.parquet", index=False)
    pairs, result = calculate(candidates, market, specs, cfg)
    pairs.to_parquet(output / "pairs.parquet", index=False)
    result.update(
        protocol_id=card["protocol_id"],
        output=str(output),
        completed_at=datetime.now(UTC),
        seal_sha256=expected_seal,
        parent_config_sha256=base.sha(base.CONFIG),
        correction=(
            "post-control-observation price-unit correction; "
            "no original overnight net results existed"
        ),
    )
    base.write_json(output / "metrics.json", result)
    base.write_json(
        output / "manifest.json",
        dict(
            source=evidence,
            seal_sha256=expected_seal,
            completed_at=datetime.now(UTC),
            artifacts={
                p.name: dict(bytes=p.stat().st_size, sha256=base.sha(p))
                for p in sorted(output.iterdir())
                if p.is_file()
            },
        ),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-sha", required=True)
    args = parser.parse_args()
    result = run(args.seal_sha)
    print(json.dumps({"output": result["output"], "verdict": result["verdict"]}), flush=True)


if __name__ == "__main__":
    main()
