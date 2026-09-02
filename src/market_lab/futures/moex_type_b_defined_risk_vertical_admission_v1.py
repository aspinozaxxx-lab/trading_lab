"""Measure strictly-prior BBO coverage for defined-risk adjacent option verticals."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_type_b_defined_risk_vertical_admission_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "f6c95bc1ed9dab6552b6adf05c8aa1ddcf77193c5385a033779eba7787bd4f27"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/options/moex-type-b-defined-risk-vertical-admission-2024-10-01-v1"
)


@dataclass(frozen=True)
class BuildResult:
    pair_inventory: pd.DataFrame
    grid_leg_states: pd.DataFrame
    opportunities: pd.DataFrame
    metrics: dict[str, Any]


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def _root(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("defined-risk admission config must be an object")
    bbo = config["bbo_parent"]
    identity = config["identity_parent"]
    grid = config["observation_grid"]
    pairs = config["pair_construction"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id")
        != "moex_type_b_defined_risk_vertical_admission_v1"
        or config.get("status")
        != "sealed_before_grid_age_or_vertical_opportunity_values"
        or config.get("live_trading_allowed") is not False
        or int(bbo["state_rows"]) != 957_259
        or int(identity["processed_rows"]) != 1_327_744
        or identity["future_identity_fallback"] != "forbidden"
        or int(grid["frequency_minutes"]) != 10
        or [int(value) for value in config["freshness_sensitivity_seconds"]]
        != [1, 5, 15, 60]
        or pairs["strikes"] != "adjacent_distinct_only"
        or pairs["naked_short_options"] != "forbidden"
        or pairs["simultaneous_fill_assumed"] is not False
        or config["limitations"][0]
        != "One sample date can validate structure and scale, not profitability or stability."
    ):
        raise ValueError("defined-risk admission protocol drifted")
    return config


def _verify_parent(config: dict[str, Any]) -> tuple[Path, Path]:
    bbo = config["bbo_parent"]
    identity = config["identity_parent"]
    bbo_root = _root(bbo["root"])
    identity_root = _root(identity["root"])
    if (
        _sha_file(bbo_root / "manifest.json") != bbo["manifest_sha256"]
        or _sha_file(bbo_root / "audit.json") != bbo["audit_sha256"]
        or _sha_file(bbo_root / "bbo_after_timestamp.parquet") != bbo["state_sha256"]
        or pq.ParquetFile(bbo_root / "bbo_after_timestamp.parquet").metadata.num_rows
        != int(bbo["state_rows"])
        or _sha_file(identity_root / "manifest.json") != identity["manifest_sha256"]
        or _sha_file(identity_root / "audit.json") != identity["audit_sha256"]
        or _sha_file(identity_root / "options_weekly_core4.parquet")
        != identity["processed_sha256"]
        or pq.ParquetFile(identity_root / "options_weekly_core4.parquet").metadata.num_rows
        != int(identity["processed_rows"])
    ):
        raise ValueError("defined-risk parent artifact drift")
    bbo_manifest = json.loads(
        (bbo_root / "manifest.json").read_text(encoding="utf-8-sig")
    )
    identity_manifest = json.loads(
        (identity_root / "manifest.json").read_text(encoding="utf-8-sig")
    )
    bbo_audit = json.loads((bbo_root / "audit.json").read_text(encoding="utf-8-sig"))
    identity_audit = json.loads(
        (identity_root / "audit.json").read_text(encoding="utf-8-sig")
    )
    if (
        bbo_manifest["protocol_sha256"] != bbo["protocol_sha256"]
        or bbo_manifest["implementation_sha256"] != bbo["implementation_sha256"]
        or identity_manifest["config_sha256"] != identity["protocol_sha256"]
        or bbo_audit.get("all_true") is not True
        or identity_audit.get("all_true") is not True
    ):
        raise ValueError("defined-risk parent protocol or audit drift")
    return bbo_root, identity_root


def observation_grid(config: dict[str, Any]) -> pd.DatetimeIndex:
    grid = config["observation_grid"]
    frequency = f"{int(grid['frequency_minutes'])}min"
    evening = pd.date_range(
        grid["previous_evening_first"], grid["previous_evening_last"], freq=frequency
    )
    main = pd.date_range(grid["main_first"], grid["main_last"], freq=frequency)
    result = evening.append(main)
    if result.duplicated().any() or not result.is_monotonic_increasing:
        raise ValueError("defined-risk observation grid drift")
    return result


def load_identity(identity_root: Path, config: dict[str, Any]) -> pd.DataFrame:
    spec = config["identity_parent"]
    columns = ["tradedate", *spec["identity_columns"]]
    frame = pd.read_parquet(identity_root / "options_weekly_core4.parquet", columns=columns)
    frame["tradedate"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    identity = frame.loc[
        frame["tradedate"].eq(pd.Timestamp(spec["identity_date"])),
        spec["identity_columns"],
    ].copy()
    if identity.empty or identity["secid"].duplicated().any():
        raise ValueError("defined-risk prior identity is empty or duplicated")
    if set(identity["logical_asset"].astype(str)) != {"SI", "RI", "BR", "MIX"}:
        raise ValueError("defined-risk prior identity lost a core asset")
    identity["encoded_week_code"] = identity["encoded_week_code"].fillna("").astype(str)
    return identity.sort_values("secid", kind="stable", ignore_index=True)


def pair_inventory(identity: pd.DataFrame, available_secids: set[str]) -> pd.DataFrame:
    eligible = identity.loc[identity["secid"].astype(str).isin(available_secids)].copy()
    group_columns = [
        "logical_asset",
        "option_type",
        "encoded_expiry_month",
        "encoded_expiry_year_digit",
        "encoded_week_code",
    ]
    rows: list[dict[str, Any]] = []
    for key, group in eligible.groupby(group_columns, observed=True, dropna=False):
        ordered = group.sort_values(["strike", "secid"], kind="stable")
        if ordered["strike"].duplicated().any():
            raise ValueError("defined-risk expiry has duplicate strike identity")
        records = list(ordered.itertuples(index=False))
        for lower, higher in zip(records, records[1:], strict=False):
            lower_strike = float(lower.strike)
            higher_strike = float(higher.strike)
            if not higher_strike > lower_strike:
                raise ValueError("defined-risk adjacent strike order drift")
            option_type = str(key[1]).lower()
            if option_type == "call":
                long_secid, short_secid = str(lower.secid), str(higher.secid)
            elif option_type == "put":
                long_secid, short_secid = str(higher.secid), str(lower.secid)
            else:
                raise ValueError("defined-risk option type drift")
            rows.append(
                {
                    "pair_id": (
                        f"{key[0]}:{option_type}:{key[2]}:{key[3]}:{key[4]}:"
                        f"{lower.secid}:{higher.secid}"
                    ),
                    "logical_asset": str(key[0]),
                    "option_type": option_type,
                    "encoded_expiry_month": int(key[2]),
                    "encoded_expiry_year_digit": int(key[3]),
                    "encoded_week_code": str(key[4]),
                    "lower_secid": str(lower.secid),
                    "higher_secid": str(higher.secid),
                    "lower_strike": lower_strike,
                    "higher_strike": higher_strike,
                    "strike_width": higher_strike - lower_strike,
                    "long_secid": long_secid,
                    "short_secid": short_secid,
                }
            )
    output = pd.DataFrame(rows)
    if output.empty or output["pair_id"].duplicated().any():
        raise ValueError("defined-risk pair inventory is empty or duplicated")
    return output.sort_values("pair_id", kind="stable", ignore_index=True)


def grid_leg_states(
    state: pd.DataFrame, secids: list[str], grid: pd.DatetimeIndex
) -> pd.DataFrame:
    state = state.copy()
    state["event_at_moscow"] = pd.to_datetime(
        state["event_at_moscow"], errors="raise", utc=True
    ).dt.tz_convert("Europe/Moscow")
    for column in ("bid_updated_at_moscow", "offer_updated_at_moscow"):
        state[column] = pd.to_datetime(state[column], errors="coerce", utc=True).dt.tz_convert(
            "Europe/Moscow"
        )
    rows: list[pd.DataFrame] = []
    grid_ns = grid.as_unit("ns").asi8
    columns = [
        "event_at_moscow",
        "bid_price",
        "bid_volume",
        "bid_updated_at_moscow",
        "offer_price",
        "offer_volume",
        "offer_updated_at_moscow",
        "two_sided",
        "locked_or_crossed",
    ]
    grouped = {str(key): value for key, value in state.groupby("secid", observed=True)}
    for secid in secids:
        source = grouped.get(secid)
        if source is None:
            continue
        source = source.sort_values("event_at_moscow", kind="stable")
        source_ns = source["event_at_moscow"].astype("int64").to_numpy()
        locations = np.searchsorted(source_ns, grid_ns, side="left") - 1
        valid = locations >= 0
        selected = source.iloc[np.maximum(locations, 0)][columns].reset_index(drop=True)
        selected.loc[~valid, columns] = pd.NA
        selected.insert(0, "grid_at_moscow", grid)
        selected.insert(1, "secid", secid)
        selected.rename(columns={"event_at_moscow": "state_event_at_moscow"}, inplace=True)
        selected["bid_age_seconds"] = (
            selected["grid_at_moscow"] - selected["bid_updated_at_moscow"]
        ).dt.total_seconds()
        selected["offer_age_seconds"] = (
            selected["grid_at_moscow"] - selected["offer_updated_at_moscow"]
        ).dt.total_seconds()
        if selected["state_event_at_moscow"].ge(selected["grid_at_moscow"]).fillna(False).any():
            raise ValueError("defined-risk asof join used same/future timestamp")
        if selected[["bid_age_seconds", "offer_age_seconds"]].lt(0.0).any(axis=None):
            raise ValueError("defined-risk grid has negative quote age")
        rows.append(selected)
    output = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if output.empty or output.duplicated(["grid_at_moscow", "secid"]).any():
        raise ValueError("defined-risk grid leg state is empty or duplicated")
    return output.sort_values(["grid_at_moscow", "secid"], kind="stable", ignore_index=True)


def vertical_opportunities(
    pairs: pd.DataFrame, legs: pd.DataFrame, age_buckets: list[int]
) -> pd.DataFrame:
    fields = [
        "grid_at_moscow",
        "secid",
        "bid_price",
        "bid_volume",
        "bid_age_seconds",
        "offer_price",
        "offer_volume",
        "offer_age_seconds",
        "two_sided",
        "locked_or_crossed",
    ]
    long = legs[fields].rename(
        columns={column: f"long_{column}" for column in fields if column != "grid_at_moscow"}
    )
    short = legs[fields].rename(
        columns={column: f"short_{column}" for column in fields if column != "grid_at_moscow"}
    )
    base = pairs.merge(long, left_on="long_secid", right_on="long_secid", how="inner")
    base = base.merge(
        short,
        left_on=["grid_at_moscow", "short_secid"],
        right_on=["grid_at_moscow", "short_secid"],
        how="inner",
        validate="many_to_one",
    )
    base["entry_debit"] = base["long_offer_price"] - base["short_bid_price"]
    output: list[pd.DataFrame] = []
    for age in age_buckets:
        fresh = pd.Series(True, index=base.index)
        for column in (
            "long_bid_age_seconds",
            "long_offer_age_seconds",
            "short_bid_age_seconds",
            "short_offer_age_seconds",
        ):
            fresh &= base[column].notna() & base[column].le(float(age))
        valid = (
            fresh
            & base["long_two_sided"].fillna(False)
            & base["short_two_sided"].fillna(False)
            & ~base["long_locked_or_crossed"].fillna(True)
            & ~base["short_locked_or_crossed"].fillna(True)
            & base["entry_debit"].gt(0.0)
            & base["entry_debit"].lt(base["strike_width"])
        )
        admitted = base.loc[valid].copy()
        admitted.insert(1, "freshness_seconds", age)
        output.append(admitted)
    result = pd.concat(output, ignore_index=True) if output else pd.DataFrame()
    if not result.empty and (
        result["entry_debit"].le(0.0).any()
        or result["entry_debit"].ge(result["strike_width"]).any()
    ):
        raise ValueError("defined-risk opportunity escaped debit bounds")
    return result.sort_values(
        ["freshness_seconds", "grid_at_moscow", "pair_id"],
        kind="stable",
        ignore_index=True,
    )


def build(config: dict[str, Any]) -> BuildResult:
    bbo_root, identity_root = _verify_parent(config)
    state = pd.read_parquet(bbo_root / "bbo_after_timestamp.parquet")
    identity = load_identity(identity_root, config)
    available_secids = set(state["secid"].astype(str).unique())
    pairs = pair_inventory(identity, available_secids)
    pair_secids = sorted(set(pairs["long_secid"]) | set(pairs["short_secid"]))
    grid = observation_grid(config)
    legs = grid_leg_states(state, pair_secids, grid)
    ages = [int(value) for value in config["freshness_sensitivity_seconds"]]
    opportunities = vertical_opportunities(pairs, legs, ages)
    counts: Counter[str] = Counter()
    for key, value in pairs.groupby("logical_asset").size().items():
        counts[f"pairs:{key}"] = int(value)
    for age in ages:
        fresh_leg = (
            legs["two_sided"].fillna(False)
            & ~legs["locked_or_crossed"].fillna(True)
            & legs["bid_age_seconds"].notna()
            & legs["offer_age_seconds"].notna()
            & legs["bid_age_seconds"].le(float(age))
            & legs["offer_age_seconds"].le(float(age))
        )
        counts[f"fresh_two_sided_legs:{age}s"] = int(fresh_leg.sum())
        subset = opportunities.loc[opportunities["freshness_seconds"].eq(age)]
        counts[f"opportunities:{age}s"] = len(subset)
        counts[f"timestamps_with_opportunity:{age}s"] = subset[
            "grid_at_moscow"
        ].nunique()
        for key, value in subset.groupby(["logical_asset", "option_type"]).size().items():
            counts[f"opportunities:{age}s:{key[0]}:{key[1]}"] = int(value)
    metrics = {
        "grid_timestamp_count": len(grid),
        "identity_date": config["identity_parent"]["identity_date"],
        "available_identity_count": len(available_secids),
        "pair_inventory_count": len(pairs),
        "pair_leg_secid_count": len(pair_secids),
        "grid_leg_state_rows": len(legs),
        "opportunity_rows_all_age_buckets": len(opportunities),
        "counts": dict(sorted(counts.items())),
        "contains_return_label_target_prediction_trade_position_equity_or_pnl": False,
        "single_sample_day_not_performance_evidence": True,
        "live_trading_allowed": False,
    }
    return BuildResult(pairs, legs, opportunities, metrics)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha_file(path),
        "rows": rows,
    }


def _write_build(root: Path, config: dict[str, Any], result: BuildResult) -> dict[str, Path]:
    outputs = config["outputs"]
    paths = {
        "pairs": root / outputs["pair_inventory"],
        "legs": root / outputs["grid_leg_states"],
        "opportunities": root / outputs["opportunities"],
        "metrics": root / outputs["metrics"],
    }
    result.pair_inventory.to_parquet(paths["pairs"], index=False, compression="zstd")
    result.grid_leg_states.to_parquet(paths["legs"], index=False, compression="zstd")
    result.opportunities.to_parquet(
        paths["opportunities"], index=False, compression="zstd"
    )
    _write_json(paths["metrics"], result.metrics)
    return paths


def audit(directory: Path) -> dict[str, Any]:
    config = load_config()
    _verify_parent(config)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    artifacts_exact = True
    rows_exact = True
    for item in manifest["artifacts"]:
        path = directory / item["path"]
        artifacts_exact &= bool(
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and _sha_file(path) == item["sha256"]
        )
        if item["rows"] is not None and path.suffix == ".parquet":
            rows_exact &= pq.ParquetFile(path).metadata.num_rows == int(item["rows"])
    replay = build(config)
    checks = {
        "config_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "parents_exact_and_audited": True,
        "artifacts_exact": artifacts_exact,
        "parquet_rows_exact": rows_exact,
        "metrics_replay_exact": replay.metrics == manifest["structural_metrics"],
        "pairs_replay_exact": (
            _sha_frame(replay.pair_inventory) == manifest["frame_hashes"]["pairs"]
        ),
        "legs_replay_exact": (
            _sha_frame(replay.grid_leg_states) == manifest["frame_hashes"]["legs"]
        ),
        "opportunities_replay_exact": (
            _sha_frame(replay.opportunities)
            == manifest["frame_hashes"]["opportunities"]
        ),
        "strict_prior_state": bool(
            (
                replay.grid_leg_states["state_event_at_moscow"].isna()
                | replay.grid_leg_states["state_event_at_moscow"].lt(
                    replay.grid_leg_states["grid_at_moscow"]
                )
            ).all()
        ),
        "contains_no_economic_outputs": replay.metrics[
            "contains_return_label_target_prediction_trade_position_equity_or_pnl"
        ]
        is False,
        "live_trading_disabled": manifest["live_trading_allowed"] is False,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def _sha_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(len(frame).to_bytes(8, "little", signed=False))
    values = pd.util.hash_pandas_object(frame, index=False, categorize=False)
    digest.update(values.to_numpy(dtype="uint64", copy=False).tobytes())
    return digest.hexdigest()


def run(output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    config = load_config()
    _verify_parent(config)
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable defined-risk output exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.parent / f".{output_root.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        result = build(config)
        paths = _write_build(temporary, config, result)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "parent_bbo_manifest_sha256": config["bbo_parent"]["manifest_sha256"],
            "parent_identity_manifest_sha256": config["identity_parent"][
                "manifest_sha256"
            ],
            "structural_metrics": result.metrics,
            "frame_hashes": {
                "pairs": _sha_frame(result.pair_inventory),
                "legs": _sha_frame(result.grid_leg_states),
                "opportunities": _sha_frame(result.opportunities),
            },
            "artifacts": [
                _artifact(paths["pairs"], len(result.pair_inventory)),
                _artifact(paths["legs"], len(result.grid_leg_states)),
                _artifact(paths["opportunities"], len(result.opportunities)),
                _artifact(paths["metrics"]),
            ],
            "contains_return_label_target_prediction_trade_position_equity_or_pnl": False,
            "live_trading_allowed": False,
        }
        _write_json(temporary / config["outputs"]["manifest"], manifest)
        report = audit(temporary)
        if report["all_true"] is not True:
            raise ValueError(f"defined-risk admission audit failed: {report['checks']}")
        _write_json(temporary / config["outputs"]["audit"], report)
        temporary.replace(output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        report = audit(args.audit_directory)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["all_true"] is not True:
            raise SystemExit(1)
        return
    print(run(args.output_root))


if __name__ == "__main__":
    main()
