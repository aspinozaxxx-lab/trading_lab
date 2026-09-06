"""One-shot, server-only V62 runner with source and implementation seals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
import yaml

from market_lab.futures.opening_execution_v2 import SCENARIOS, simulate
from market_lab.futures.opening_regime_v2 import (
    ASSETS,
    PROTECTED,
    Market,
    build_candidates,
    build_labels,
    walk_forward,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/futures_v62_opening_causal_admission_v2.yaml"
PARENT = ROOT / "configs/futures_v62_cross_market_opening_regime_v1.yaml"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(clean(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8-sig",
    )


def load_protocol() -> tuple[dict, dict]:
    expected = CONFIG.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if sha(CONFIG) != expected:
        raise ValueError("V62 admission SHA mismatch")
    admission = yaml.safe_load(CONFIG.read_text(encoding="utf-8-sig"))
    if sha(PARENT) != admission["parent_sha256"]:
        raise ValueError("V62 parent SHA mismatch")
    if admission["live_trading_allowed"] or not admission["sealed_before_outcomes"]:
        raise ValueError("V62 boundaries changed")
    for record in admission["implementation"]:
        if sha(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"implementation drift: {record['path']}")
    return yaml.safe_load(PARENT.read_text(encoding="utf-8-sig")), admission


def safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("source path escape")
    return candidate


def sources(root: Path, parent: dict) -> tuple[list[dict], pd.DataFrame, pd.DatetimeIndex, dict]:
    source = parent["source"]
    verified = {}
    for key in ("top_manifest", "active_map", "spec_proxy"):
        path = safe_path(root, source[f"{key}_relative_path"])
        if sha(path) != source[f"{key}_sha256"]:
            raise ValueError(f"source identity drift: {key}")
        verified[key] = dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path))
    top = read_json(Path(verified["top_manifest"]["path"]))
    if top["requested_end"] != "2025-12-31" or top["protected_from"] != "2026-01-01":
        raise ValueError("manifest temporal boundary drift")
    artifacts = []
    for item in top["assets"]:
        asset = source["source_asset_aliases"][item["asset_code"]]
        asset_path = safe_path(root / "data", item["path"])
        if sha(asset_path) != item["sha256"]:
            raise ValueError("asset manifest drift")
        manifest = read_json(asset_path)
        if manifest["requested_end"] != "2025-12-31":
            raise ValueError("asset boundary drift")
        for segment in manifest["segment_manifests"]:
            if not segment["rows"]:
                continue
            path = safe_path(root / "data", segment["path"])
            if sha(path) != segment["sha256"]:
                raise ValueError("segment manifest drift")
            payload = read_json(path)
            if payload["status"] != "complete":
                raise ValueError("incomplete segment")
            artifact = payload["artifacts"]["parquet"]
            path = safe_path(root / "data", artifact["path"])
            if (
                sha(path) != artifact["sha256"]
                or pq.ParquetFile(path).metadata.num_rows != artifact["rows"]
            ):
                raise ValueError("parquet identity drift")
            # Physically inspect only time/identity columns before admitting price-bearing load.
            metadata = pd.read_parquet(
                path, columns=["timestamp", "end_timestamp", "canonical_contract_id"]
            )
            begin = pd.to_datetime(metadata["timestamp"], utc=True)
            end = pd.to_datetime(metadata["end_timestamp"], utc=True)
            if (
                begin.isna().any()
                or end.isna().any()
                or begin.ge(PROTECTED).any()
                or end.ge(PROTECTED).any()
            ):
                raise ValueError("protected or missing source time")
            artifacts.append(
                dict(
                    path=str(path),
                    asset=asset,
                    sha256=artifact["sha256"],
                    rows=len(metadata),
                    minimum=begin.min(),
                    maximum=end.max(),
                )
            )
    if sum(record["rows"] for record in artifacts) != top["totals"]["rows"]:
        raise ValueError("top-level source row mismatch")
    columns = [
        "effective_date",
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "plan_tradable",
    ]
    plan = pd.read_parquet(verified["active_map"]["path"], columns=columns)
    for column in ("effective_date", "decision_date", "observed_through"):
        plan[column] = pd.to_datetime(plan[column]).dt.normalize()
    plan["local_date"] = plan["effective_date"]
    plan["asset"] = plan["asset_code"].str.upper().replace({"RTS": "RI"})
    sessions = pd.DatetimeIndex(plan["local_date"].dropna().unique()).sort_values()
    if sessions.max() >= pd.Timestamp("2026-01-01"):
        raise ValueError("plan reaches protected 2026")
    usable = (
        plan["plan_tradable"].fillna(False)
        & plan["contract_id"].notna()
        & plan["decision_date"].lt(plan["local_date"])
        & plan["observed_through"].le(plan["decision_date"])
        & plan["asset"].isin(ASSETS)
    )
    plan = plan.loc[usable, ["local_date", "asset", "contract_id"]].copy()
    if plan.duplicated(["local_date", "asset"]).any():
        raise ValueError("multiple causal contracts per asset/date")
    verified.update(
        raw_artifacts=artifacts,
        sessions=len(sessions),
        causal_plan_rows=len(plan),
        metadata_only=True,
        market_values_read=False,
    )
    return artifacts, plan, sessions, verified


def load_market(artifacts: list[dict], plan: pd.DataFrame, sessions: pd.DatetimeIndex) -> Market:
    parts = []
    planned = set(plan["contract_id"])
    for artifact in artifacts:
        frame = pd.read_parquet(
            artifact["path"],
            columns=[
                "timestamp",
                "end_timestamp",
                "canonical_contract_id",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )
        frame = frame.rename(columns={"canonical_contract_id": "contract_id"})
        frame = frame.loc[frame["contract_id"].isin(planned)].copy()
        frame["end_timestamp"] = pd.to_datetime(frame["end_timestamp"], utc=True)
        frame["asset"] = artifact["asset"]
        parts.append(frame)
    return Market(pd.concat(parts, ignore_index=True), plan, sessions)


def promotion(results: dict) -> dict:
    primary = results["mlp_primary"]
    baselines = [
        results[f"{name}_primary"] for name in ("logistic", "gap_fade", "gap_continuation")
    ]
    gates = dict(
        all_ledgers_valid=all(r["economic_metrics_valid"] for r in results.values()),
        primary_cagr=primary.get("cagr", -1) >= 0.20,
        doubled_cagr=results["mlp_doubled"].get("cagr", -1) >= 0.20,
        stress_cagr=results["mlp_stress"].get("cagr", -1) >= 0.15,
        primary_sharpe=primary.get("sharpe", -100) >= 1.0,
        primary_mdd=primary.get("maximum_drawdown", 1) <= 0.30,
        primary_intraday_mdd=(primary.get("intraday_mark_maximum_drawdown") or 0) <= 0.30,
        worst_year=primary.get("worst_year", -1) >= 0,
        positive_years=primary.get("positive_years", 0) >= 4,
        trade_count=primary["trade_count"] >= 250,
        cagr_advantage=all(primary.get("cagr", -1) >= b.get("cagr", 100) + 0.02 for b in baselines),
        sharpe_advantage=all(
            primary.get("sharpe", -100) >= b.get("sharpe", 100) + 0.10 for b in baselines
        ),
    )
    return dict(
        checks=gates,
        passed=all(gates.values()),
        verdict="DEVELOPMENT_LEAD_REQUIRES_FORWARD" if all(gates.values()) else "NO_GO",
        live_trading_allowed=False,
        predictable_20_percent_proven=False,
    )


def run(source_root: Path, output: Path, preflight_only: bool = False) -> dict:
    if os.name == "nt":
        raise RuntimeError("real source loading and economics are server-only")
    parent, admission = load_protocol()
    artifacts, plan, sessions, evidence = sources(source_root.resolve(), parent)
    if preflight_only:
        summary = dict(
            artifacts=len(artifacts),
            rows=sum(a["rows"] for a in artifacts),
            sessions=len(sessions),
            causal_plan_rows=len(plan),
            metadata_only=True,
            all_hashes_verified=True,
            protected_rows=0,
        )
        print(json.dumps(summary), flush=True)
        return summary
    output = output.resolve()
    if not output.is_relative_to(Path("/srv/trading_lab_data/runs")):
        raise ValueError("economic run outputs must be external server runs")
    output.mkdir(parents=False, exist_ok=False)
    write_json(
        output / "started.json",
        dict(started_at=datetime.now(UTC), pid=os.getpid(), config_sha256=sha(CONFIG)),
    )
    print(
        "V62: source identities and temporal boundaries verified; loading admitted market",
        flush=True,
    )
    market = load_market(artifacts, plan, sessions)
    candidates = build_candidates(market)
    candidates.to_parquet(output / "candidates.parquet", index=False)
    print(f"V62: {len(candidates)} causal candidate rows; constructing separate labels", flush=True)
    labels = build_labels(candidates, market)
    labels.to_parquet(output / "labels.parquet", index=False)
    predictions, folds, models = walk_forward(candidates, labels, sessions)
    predictions.to_parquet(output / "predictions.parquet", index=False)
    joblib.dump(models, output / "models.joblib")
    write_json(output / "folds.json", folds)
    print(
        "V62: expanding-year inference complete; executing all four arms and three costs",
        flush=True,
    )
    spec_path = Path(evidence["spec_proxy"]["path"])
    specs = pd.read_parquet(
        spec_path,
        columns=[
            "session_date",
            "contract_id",
            "sizing_usable",
            "sizing_observed_session_date",
            "sizing_point_value",
            "sizing_tick_cash_value",
            "conservative_fee_per_side",
            "approximate",
            "research_only",
            "historical_exchange_exact",
            "broker_exact",
        ],
    )
    specs["local_date"] = pd.to_datetime(specs["session_date"]).dt.normalize()
    specs["sizing_observed_session_date"] = pd.to_datetime(specs["sizing_observed_session_date"])
    if (
        specs["local_date"].ge(pd.Timestamp("2026-01-01")).any()
        or specs.duplicated(["local_date", "contract_id"]).any()
    ):
        raise ValueError("specs duplicate or touch protected boundary")
    if not (
        specs["approximate"].all()
        and specs["research_only"].all()
        and not specs["historical_exchange_exact"].any()
        and not specs["broker_exact"].any()
    ):
        raise ValueError("spec proxy limitations changed")
    results = {}
    for model_id in ("mlp", "logistic", "gap_fade", "gap_continuation"):
        selected = predictions.loc[predictions["model_id"].eq(model_id)]
        for scenario in SCENARIOS:
            prefix = f"{model_id}_{scenario}"
            trades, equity, orders, details = simulate(selected, market, specs, scenario)
            for name, frame in (
                ("trades", trades),
                ("equity", equity),
                ("orders", orders),
                ("marks", details["marks"]),
            ):
                frame.to_parquet(output / f"{prefix}_{name}.parquet", index=False)
            results[prefix] = details["metrics"]
    verdict = promotion(results)
    report = dict(
        protocol=admission["protocol_id"],
        config_sha256=sha(CONFIG),
        candidate_count=len(candidates),
        valid_labels=int(labels["valid"].sum()),
        missing_labels=int((~labels["valid"]).sum()),
        prediction_count=len(predictions),
        folds=folds,
        results=results,
        promotion=verdict,
        limitations=[
            "development history previously examined by other families",
            "anonymous archive is current delivery, not original vintage",
            "same-boundary next-open execution is a zero-latency research proxy",
            "bar volume bounds fills but does not prove queue position",
            "contract monetary units and fees are lagged research proxies",
            "modeled initial margin 25%, buffer 2x; no broker-exact history",
            "no collateral income or taxes; no live capital authorized",
        ],
    )
    write_json(output / "metrics.json", report)
    rows = [
        "# V62 opening regime V2",
        "",
        f"Verdict: {verdict['verdict']}",
        "",
        "| Arm / cost | CAGR | Sharpe | MDD | Trades | Valid |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, r in results.items():
        rows.append(
            f"| {name} | {r.get('cagr', float('nan')):.2%} | "
            f"{r.get('sharpe', float('nan')):.3f} | "
            f"{r.get('maximum_drawdown', float('nan')):.2%} | "
            f"{r['trade_count']} | {r['economic_metrics_valid']} |"
        )
    (output / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
    identity = dict(
        created_at=datetime.now(UTC),
        source=evidence,
        implementation=admission["implementation"],
        config_sha256=sha(CONFIG),
        parent_sha256=sha(PARENT),
        environment=dict(
            python=platform.python_version(),
            numpy=np.__version__,
            pandas=pd.__version__,
            sklearn=sklearn.__version__,
        ),
        artifacts=[
            dict(name=p.name, bytes=p.stat().st_size, sha256=sha(p))
            for p in sorted(output.iterdir())
            if p.is_file()
        ],
    )
    write_json(output / "identity.json", identity)
    print(
        json.dumps(clean(dict(output=str(output), promotion=verdict, results=results))), flush=True
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if not args.preflight and args.output is None:
        parser.error("--output is required for the single economic run")
    run(args.source_root, args.output or Path("/srv/trading_lab_data/runs"), args.preflight)


if __name__ == "__main__":
    main()
