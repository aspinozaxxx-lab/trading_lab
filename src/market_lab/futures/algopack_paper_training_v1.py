"""One sealed server-only archive fit, no network, PnL, or future-period admission."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as arrow
import pyarrow.json as arrow_json

from market_lab.futures import algopack_fo_history_quality_v1 as history
from market_lab.futures.algopack_paper_alignment_v1 import (
    ASSETS,
    FIELDS,
    FIVE,
    MOSCOW,
    TEN,
    FlowVersion,
    bucket_end,
)
from market_lab.futures.algopack_paper_inputs_v1 import (
    _pairs,
    _time_frame,
    digest,
    read_manifest,
    safe,
    verified,
)
from market_lab.futures.algopack_paper_inputs_v2 import (
    inspect_intraday,
    load_active_plan,
    load_price_artifact,
)
from market_lab.futures.algopack_paper_model_v1 import (
    FLOW_COLUMNS,
    MINIMUM_ROWS,
    PRICE_COLUMNS,
    TARGET_COLUMNS,
    PriceBar,
    build_features,
    build_labels,
    calendar,
    fit_pair,
    predict_serialized,
)

PROTOCOL = "algopack_paper_training_v1"
PROJECT = Path(__file__).resolve().parents[3]
CONFIG = f"configs/{PROTOCOL}.json"
SEAL = f"configs/{PROTOCOL}.seal.json"


def now() -> datetime:
    return datetime.now(UTC)


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, indent=2).encode() + b"\n"


def write_new(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())


def identity(path: Path) -> dict:
    return dict(path=path.name, bytes=path.stat().st_size, sha256=digest(path))


def verify_code(expected_sha: str) -> tuple[dict, dict]:
    seal_path = safe(PROJECT, SEAL)
    if digest(seal_path) != expected_sha:
        raise ValueError("training seal mismatch")
    seal = json.loads(seal_path.read_bytes(), object_pairs_hook=_pairs)
    if seal["protocol_id"] != PROTOCOL:
        raise ValueError("wrong training protocol")
    required = {
        CONFIG,
        f"configs/{PROTOCOL}.sha256",
        "src/market_lab/futures/algopack_paper_model_v1.py",
        "src/market_lab/futures/algopack_paper_training_v1.py",
        "src/market_lab/futures/algopack_paper_alignment_v1.py",
        "src/market_lab/futures/algopack_paper_inputs_v1.py",
        "src/market_lab/futures/algopack_paper_inputs_v2.py",
        "docs/ALGOPACK_PAPER_AUTHORIZATION_20260907.md",
        "docs/ALGOPACK_PAPER_TRAINING_SPEC_V1.md",
    }
    if not required <= set(seal["files"]):
        raise ValueError("incomplete training closure")
    for name, expected in seal["files"].items():
        if digest(safe(PROJECT, name)) != expected:
            raise ValueError("training closure byte mismatch")
    config_path = safe(PROJECT, CONFIG)
    sidecar = safe(PROJECT, f"configs/{PROTOCOL}.sha256").read_text(encoding="utf-8-sig")
    if sidecar.strip() != digest(config_path):
        raise ValueError("config sidecar mismatch")
    config = json.loads(config_path.read_bytes(), object_pairs_hook=_pairs)
    expected = dict(
        protocol_id=PROTOCOL,
        training_information_start="2020-01-01",
        training_information_end="2025-12-31",
        minimum_joint_rows=MINIMUM_ROWS,
        ridge_alpha=10.0,
        ridge_solver="svd",
        archive_transferability_assumption=True,
        historical_economic_evaluation=False,
        future_boundary=None,
        live_trading_allowed=False,
        history_jobs=294,
        history_pairs=147,
    )
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("fixed training configuration differs")
    return config, seal


def needed_keys(candidates: pd.DataFrame) -> tuple[set, set]:
    prices, flow = set(), set()
    for end, row in candidates.iterrows():
        end = end.to_pydatetime()
        for asset in ASSETS:
            if not row[f"{asset}_plan_eligible"]:
                continue
            contract, secid = row[f"{asset}_contract_id"], row[f"{asset}_secid"]
            for offset in (*range(-7, 0), *range(1, 8)):
                prices.add((asset, contract, end + offset * TEN))
            for dataset in FIELDS:
                for stamp in (end - FIVE, end):
                    flow.add((dataset, asset, secid, stamp))
    return prices, flow


def check_flow_metadata(row: dict, job: dict) -> datetime:
    if (
        row["dataset"] != job["dataset"]
        or row["requested_asset_code"] != job["asset_code"]
        or row["secid"] != job["secid"]
        or not "2020-01-01" <= row["tradedate"] <= "2025-12-31"
        or not job["from"] <= row["tradedate"] <= job["till"]
    ):
        raise ValueError("flow identity/protected date mismatch")
    stamp = bucket_end(row["tradedate"], row["tradetime"])
    if not 2020 <= stamp.year <= 2025:
        raise ValueError("flow protected UTC boundary")
    return stamp


def project_flow(record: dict, needed: set) -> tuple[dict, list[dict], dict]:
    path, job = record["rows_path"], record["job"]
    source = record["entry"]["normalized"]
    if digest(path) != source["sha256"]:
        raise ValueError("flow changed before projection")
    count = 0
    seen = set()
    for row in history._metadata(path):
        stamp = check_flow_metadata(row, job)
        if stamp in seen:
            raise ValueError("duplicate flow source key")
        seen.add(stamp)
        count += 1
    if count != source["rows"] or digest(path) != source["sha256"]:
        raise ValueError("flow metadata count/hash mismatch")
    fields = FIELDS[job["dataset"]]
    schema = arrow.schema(
        [(name, arrow.string()) for name in history.METADATA_COLUMNS]
        + [(name, arrow.float64()) for name in fields]
    )
    options = arrow_json.ParseOptions(explicit_schema=schema, unexpected_field_behavior="ignore")
    selected = []
    number = 0
    if count:
        with arrow_json.open_json(path, parse_options=options) as reader:
            for batch in reader:
                if batch.schema != schema:
                    raise ValueError("flow projection schema mismatch")
                for row in batch.to_pylist():
                    stamp = check_flow_metadata(row, job)
                    key = job["dataset"], job["asset_code"], job["secid"], stamp
                    if key in needed:
                        selected.append((key, number, row))
                    number += 1
    if number != count or digest(path) != source["sha256"]:
        raise ValueError("flow changed during value projection")
    available = now()  # Conservative actual verified clock, NEVER historical decision time.
    result, provenance = {}, []
    for key, number, row in selected:
        version = hashlib.sha256(f"{source['sha256']}:{number}".encode()).hexdigest()
        result[key] = FlowVersion(
            job["dataset"],
            job["asset_code"],
            job["secid"],
            row["tradedate"],
            row["tradetime"],
            available,
            version,
            tuple(row[name] for name in fields),
        )
        provenance.append(
            dict(
                version_sha256=version,
                source_sha256=source["sha256"],
                row_number=number,
                available_at=available,
                dataset=key[0],
                asset=key[1],
                secid=key[2],
                information_end=key[3],
            )
        )
    return (
        result,
        provenance,
        dict(
            job=job,
            normalized=source,
            available_at=available.isoformat(),
            projected_rows=number,
            selected_rows=len(result),
        ),
    )


def project_prices(root: Path, artifacts: list[dict], needed: set) -> tuple[dict, list[dict]]:
    prices, catalog = {}, []
    for record in artifacts:
        path = verified(root, record)
        times = _time_frame(path, record, record["contract_id"])
        if (
            times["begin"].dt.tz_convert(MOSCOW).dt.year.ge(2026).any()
            or times["end"].dt.tz_convert(MOSCOW).dt.year.ge(2026).any()
        ):
            raise ValueError("price protected vendor date before value projection")
        frame = load_price_artifact(root, record)
        available = now()
        selected = 0
        for row in frame.itertuples(index=False):
            begin = pd.Timestamp(row.timestamp).tz_convert("UTC").to_pydatetime()
            key = record["asset"], record["contract_id"], begin
            if key not in needed:
                continue
            if key in prices:
                raise ValueError("duplicate projected price identity")
            values = tuple(
                None if pd.isna(value) else float(value)
                for value in (row.open, row.high, row.low, row.close)
            )
            prices[key] = PriceBar(
                record["asset"],
                record["secid"],
                record["contract_id"],
                begin,
                pd.Timestamp(row.end_timestamp).tz_convert("UTC").to_pydatetime(),
                available,
                record["sha256"],
                *values,
            )
            selected += 1
        if digest(path) != record["sha256"]:
            raise ValueError("price changed after projection")
        catalog.append(dict(**record, available_at=available.isoformat(), selected_rows=selected))
    return prices, catalog


def coverage(
    candidates: pd.DataFrame, features: pd.DataFrame, labels: pd.DataFrame
) -> tuple[dict, pd.Series]:
    price = np.isfinite(features.loc[:, list(PRICE_COLUMNS)].to_numpy(float)).all(axis=1)
    full = price & np.isfinite(features.loc[:, list(FLOW_COLUMNS)].to_numpy(float)).all(axis=1)
    target = np.isfinite(labels.loc[:, list(TARGET_COLUMNS)].to_numpy(float)).all(axis=1)
    mask = pd.Series(full & target, index=candidates.index, name="training_eligible")
    result = dict(
        candidate_rows=len(candidates),
        price_feature_rows=int(price.sum()),
        full_feature_rows=int(full.sum()),
        four_target_rows=int(target.sum()),
        joint_training_rows=int(mask.sum()),
        by_year={},
        reasons={},
    )
    for year in range(2020, 2026):
        selected = candidates.index.year == year
        result["by_year"][str(year)] = dict(
            candidates=int(selected.sum()),
            price_features=int((selected & price).sum()),
            full_features=int((selected & full).sum()),
            four_targets=int((selected & target).sum()),
            joint=int((selected & mask).sum()),
        )
    for frame in (features, labels):
        for column in frame.columns:
            if column.endswith("_status"):
                result["reasons"][column] = {
                    str(k): int(v) for k, v in frame[column].value_counts().items()
                }
    return result, mask


def run(seal_sha: str) -> dict:
    config, seal = verify_code(seal_sha)
    if platform.system() != "Linux" or os.getuid() != 999:
        raise ValueError("run only as trading-lab on Linux server")
    if os.environ.get("MOEX_ALGOPACK_TOKEN"):
        raise ValueError("training must not inherit authentication")
    versions = {
        name: importlib.metadata.version(name)
        for name in ("numpy", "pandas", "pyarrow", "scikit-learn")
    }
    if versions != {
        "numpy": "2.3.3",
        "pandas": "2.3.3",
        "pyarrow": "23.0.1",
        "scikit-learn": "1.8.0",
    }:
        raise ValueError("training runtime version mismatch")
    parent = Path(config["output_parent"])
    if parent.resolve() != parent.absolute() or not parent.is_dir():
        raise ValueError("output parent must be a precreated ordinary directory")
    output = parent / f"{PROTOCOL}_{seal_sha[:12]}"
    output.mkdir(mode=0o700, exist_ok=False)
    started = now()
    write_new(
        output / "STARTED.json",
        dict(
            seal_sha256=seal_sha,
            started_at=started.isoformat(),
            future_boundary=None,
            live_trading_allowed=False,
        ),
    )
    try:
        price_root = Path(config["price_root"])
        assembly = read_manifest(price_root, config["assembly"])
        preflight, artifacts = inspect_intraday(price_root, assembly["top_manifest"])
        if preflight != assembly["preflight"]:
            raise ValueError("price assembly preflight changed")
        plan = load_active_plan(Path(config["storage_root"]), assembly["active_map_identity"])
        candidates = calendar(plan)
        candidates.to_parquet(output / "calendar.parquet")
        price_needed, flow_needed = needed_keys(candidates)
        source_root = Path(config["history_root"])
        if source_root.resolve() != source_root.absolute():
            raise ValueError("history root symlink")
        _, records = history._preflight(
            source_root,
            config["history_manifest_sha256"],
            jobs=config["history_jobs"],
            pairs=config["history_pairs"],
        )
        print("INPUT_IDENTITIES_PASS; beginning authorized <=2025 projections", flush=True)
        prices, price_catalog = project_prices(price_root, artifacts, price_needed)
        del price_needed
        flow, flow_provenance, flow_catalog = {}, [], []
        for number, record in enumerate(records, 1):
            projected, provenance, catalog = project_flow(record, flow_needed)
            if flow.keys() & projected.keys():
                raise ValueError("cross-job flow identity collision")
            flow.update(projected)
            flow_provenance.extend(provenance)
            flow_catalog.append(catalog)
            if number % 49 == 0:
                print(f"FLOW_PROJECTED jobs={number}/294", flush=True)
        cutoff = now()
        del flow_needed
        pd.DataFrame(flow_provenance).to_parquet(output / "flow_provenance.parquet", index=False)
        del flow_provenance
        write_new(
            output / "inputs.json",
            dict(
                assembly=config["assembly"],
                price_preflight=preflight,
                active_map=assembly["active_map_identity"],
                price_sources=price_catalog,
                history_manifest_sha256=config["history_manifest_sha256"],
                flow_sources=flow_catalog,
                availability_policy=("actual post-projection verification clock; "
                                     "current-vintage assumption"),
                training_cutoff=cutoff.isoformat(),
                semantic_raw_replay=False,
            ),
        )
        features = build_features(candidates, prices, flow, cutoff)
        print("FEATURE_TABLE_COMPLETE; separate label construction", flush=True)
        labels = build_labels(candidates, prices, cutoff)
        counts, mask = coverage(candidates, features, labels)
        features.to_parquet(output / "features.parquet")
        labels.to_parquet(output / "labels.parquet")
        mask.to_frame().to_parquet(output / "training_mask.parquet")
        status = "FAILED_TRAINING_COVERAGE"
        if counts["joint_training_rows"] >= MINIMUM_ROWS:
            models, fit_mask = fit_pair(features, labels)
            if not fit_mask.equals(mask):
                raise ValueError("fit coverage differs from independent coverage")
            for arm, model in models.items():
                # Serialization/schema check only; no target comparison or model selection.
                predict_serialized(
                    model, features.loc[mask, model["feature_names"]].iloc[:1].to_numpy()
                )
                write_new(output / f"{arm}.model.json", model)
            status = "TRAINED_NOT_EVALUATED"
        verify_code(seal_sha)
        files = {path.name: identity(path) for path in sorted(output.iterdir()) if path.is_file()}
        report = dict(
            protocol_id=PROTOCOL,
            status=status,
            seal_sha256=seal_sha,
            config_sha256=seal["files"][CONFIG],
            started_at=started.isoformat(),
            completed_at=now().isoformat(),
            training_cutoff=cutoff.isoformat(),
            runtime=dict(python=platform.python_version(), packages=versions),
            counts=counts,
            files=files,
            model_fitted=status == "TRAINED_NOT_EVALUATED",
            future_boundary=None,
            historical_economic_evaluation=False,
            live_trading_allowed=False,
            predictions=0,
            trades=0,
            CAGR=None,
            Sharpe=None,
            MDD=None,
            evaluation_status="N/A: training only; future execution/evaluation seals required",
        )
        write_new(output / "manifest.json", report)
        print(
            json.dumps(
                dict(
                    status=status,
                    counts=counts,
                    output=str(output),
                    manifest_sha256=digest(output / "manifest.json"),
                )
            ),
            flush=True,
        )
        return report
    except Exception as error:
        write_new(
            output / "FAILED.json",
            dict(
                error_type=type(error).__name__,
                completed_at=now().isoformat(),
                sealed_run_incomplete=True,
                message=str(error),
                live_trading_allowed=False,
            ),
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    run(args.seal_sha256)


if __name__ == "__main__":
    main()
