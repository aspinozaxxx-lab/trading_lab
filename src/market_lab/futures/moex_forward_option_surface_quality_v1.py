"""Audit structural quality of timestamped forward option snapshots without economics."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from market_lab.futures import moex_forward_option_surface_source_v2 as source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_forward_option_surface_quality_v1.yaml"
CONFIG_SHA256: Final[str] = "b26c35c67882a112f4f493e9d876a29118cdfc435839fffe9e4c17b14f253341"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-options-surface-v2-quality-v1"
)
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
TIME_ONLY: Final[re.Pattern[str]] = re.compile(
    r"^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?$"
)
REPORT_ECONOMIC_FLAG: Final[str] = (
    "contains_feature_label_return_target_prediction_signal_trade_position_equity_or_pnl"
)
IDENTITY_ECONOMIC_FLAG: Final[str] = (
    "contains_market_values_features_labels_returns_targets_predictions_signals_trades_"
    "positions_equity_or_pnl"
)


def _sha(path: Path) -> str:
    return source._sha_file(path)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("option quality config must be an object")
    parent = config["parent_source"]
    clock = config["clock_diagnostics"]
    output = config["output_contract"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_forward_option_surface_quality_v1"
        or config.get("status")
        != "sealed_after_v2_schema_before_clock_bbo_margin_quality_values"
        or config.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["config_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"])
        != parent["implementation_sha256"]
        or _sha(PROJECT_ROOT / parent["admission_path"]) != parent["admission_sha256"]
        or parent["quality_values_read_before_seal"] is not False
        or parent["parent_raw_replay_required"] is not True
        or clock["negative_lag_is_invalid"] is not True
        or clock["thresholds_are_descriptive_not_strategy_selection"] is not True
        or list(clock["reporting_lag_minutes"]) != [1, 5, 15, 60]
        or list(clock["reporting_quantiles"]) != [0.5, 0.9, 0.99]
        or output["raw_price_or_strike_values_emitted"] is not False
        or output["counts_and_clock_lag_summaries_only"] is not True
    ):
        raise ValueError("option quality protocol drifted")
    return config


def _exchange_timestamp(value: Any, source_date: Any) -> pd.Timestamp:
    text = str(value).strip()
    if not text or text.lower() in {"<na>", "nan", "nat", "none"}:
        return pd.NaT
    if TIME_ONLY.fullmatch(text):
        day = pd.Timestamp(source_date).date().isoformat()
        parsed = pd.Timestamp(f"{day}T{text}")
    else:
        parsed = pd.Timestamp(text)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(MOSCOW)
    return parsed.tz_convert("UTC")


def _clock_lags(frame: pd.DataFrame, column: str) -> pd.Series:
    exchange = pd.Series(
        [
            _exchange_timestamp(value, source_date)
            for value, source_date in zip(frame[column], frame["source_date"], strict=True)
        ],
        index=frame.index,
        dtype="datetime64[ns, UTC]",
    )
    retrieval = pd.to_datetime(frame["retrieved_at_utc"], utc=True, errors="raise")
    return (retrieval - exchange).dt.total_seconds() / 60.0


def _lag_summary(lags: pd.Series, config: Mapping[str, Any]) -> dict[str, Any]:
    valid = lags.dropna().astype(float)
    negative = int(valid.lt(0).sum())
    if negative:
        raise ValueError("negative exchange-clock lag is invalid")
    thresholds = [int(value) for value in config["reporting_lag_minutes"]]
    quantiles = [float(value) for value in config["reporting_quantiles"]]
    result: dict[str, Any] = {
        "valid_count": int(len(valid)),
        "missing_count": int(lags.isna().sum()),
        "negative_count": negative,
        "cumulative_counts": {
            f"le_{threshold}_minutes": int(valid.le(threshold).sum())
            for threshold in thresholds
        },
        "above_largest_threshold_count": int(valid.gt(max(thresholds)).sum()),
    }
    result["lag_minutes"] = (
        {
            **{
                f"q{int(quantile * 100):02d}": round(float(valid.quantile(quantile)), 6)
                for quantile in quantiles
            },
            "maximum": round(float(valid.max()), 6),
        }
        if len(valid)
        else {"q50": None, "q90": None, "q99": None, "maximum": None}
    )
    return result


def _as_counts(values: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in values.sort_index().items()}


def _adjacent_two_sided_pairs(frame: pd.DataFrame, two_sided: pd.Series) -> dict[str, int]:
    eligible = frame.loc[two_sided, ["asset_code", "last_trade_date", "option_type", "strike"]]
    if eligible.empty:
        return {str(asset): 0 for asset in sorted(frame["asset_code"].astype(str).unique())}
    unique = eligible.dropna(subset=["strike"]).drop_duplicates()
    group_sizes = unique.groupby(
        ["asset_code", "last_trade_date", "option_type"], observed=True
    ).size()
    pairs = group_sizes.sub(1).clip(lower=0).groupby(level="asset_code").sum()
    return {
        str(asset): int(pairs.get(asset, 0))
        for asset in sorted(frame["asset_code"].astype(str).unique())
    }


def summarize_frame(frame: pd.DataFrame, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    resolved = load_config() if config is None else config
    required = {
        "source_date",
        "retrieved_at_utc",
        "asset_code",
        "last_trade_date",
        "option_type",
        "strike",
        "bid",
        "offer",
        "exchange_sequence_number",
        "initial_margin_non_covered",
        "initial_margin_sell",
        "initial_margin_buy",
        "initial_margin_exchange_time",
        "market_update_time",
        "last_trade_time",
    }
    missing = sorted(required - set(frame.columns))
    if missing or frame.empty:
        raise ValueError(f"option quality input missing required rows/columns: {missing}")
    assets = set(frame["asset_code"].astype(str))
    expected = set(resolved["eligibility"]["all_four_assets_required"])
    if assets != expected:
        raise ValueError(f"option quality asset mismatch: {sorted(assets)}")

    bid = pd.to_numeric(frame["bid"], errors="coerce")
    offer = pd.to_numeric(frame["offer"], errors="coerce")
    bid_positive = bid.gt(0)
    offer_positive = offer.gt(0)
    two_sided = bid_positive & offer_positive
    one_sided = bid_positive ^ offer_positive
    no_quote = ~bid_positive & ~offer_positive
    locked = two_sided & offer.eq(bid)
    crossed = two_sided & offer.lt(bid)

    quote_states: dict[str, dict[str, int]] = {}
    for asset, group in frame.groupby("asset_code", observed=True, sort=True):
        index = group.index
        quote_states[str(asset)] = {
            "rows": int(len(group)),
            "two_sided_positive": int(two_sided.loc[index].sum()),
            "one_sided_positive": int(one_sided.loc[index].sum()),
            "no_positive_quote": int(no_quote.loc[index].sum()),
            "locked": int(locked.loc[index].sum()),
            "crossed": int(crossed.loc[index].sum()),
        }

    clock_config = resolved["clock_diagnostics"]
    clocks = {
        column: _lag_summary(_clock_lags(frame, column), clock_config)
        for column in (
            "market_update_time",
            "last_trade_time",
            "initial_margin_exchange_time",
        )
    }
    sequence = pd.to_numeric(frame["exchange_sequence_number"], errors="coerce")
    sequence_counts: dict[str, dict[str, int]] = {}
    margin_counts: dict[str, dict[str, int]] = {}
    margin_columns = [
        str(value)
        for value in resolved["reported_counts_only"]["positive_margin_rows_by_field"]
    ]
    for asset, group in frame.groupby("asset_code", observed=True, sort=True):
        index = group.index
        sequence_counts[str(asset)] = {
            "rows": int(len(group)),
            "nonnull": int(sequence.loc[index].notna().sum()),
            "unique": int(sequence.loc[index].nunique(dropna=True)),
        }
        margin_counts[str(asset)] = {
            column: int(pd.to_numeric(group[column], errors="coerce").gt(0).sum())
            for column in margin_columns
        }

    result = {
        "row_count": int(len(frame)),
        "rows_by_asset": _as_counts(frame.groupby("asset_code", observed=True).size()),
        "unique_expiries_by_asset": _as_counts(
            frame.groupby("asset_code", observed=True)["last_trade_date"].nunique(dropna=True)
        ),
        "unique_strikes_by_asset": _as_counts(
            frame.groupby("asset_code", observed=True)["strike"].nunique(dropna=True)
        ),
        "quote_states_by_asset": quote_states,
        "adjacent_two_sided_pairs_by_asset": _adjacent_two_sided_pairs(frame, two_sided),
        "exchange_sequence_by_asset": sequence_counts,
        "positive_margin_rows_by_asset": margin_counts,
        "clock_lag_summaries": clocks,
        "contains_raw_market_or_strike_values": False,
        REPORT_ECONOMIC_FLAG: False,
        "live_trading_allowed": False,
    }
    _assert_output_contract(result, resolved)
    return result


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key).lower() for key in value} | {
            nested
            for item in value.values()
            for nested in _all_keys(item)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {nested for item in value for nested in _all_keys(item)}
    return set()


def _assert_output_contract(report: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    forbidden = {str(value).lower() for value in config["forbidden_outputs"]}
    escaped = sorted(forbidden & _all_keys(report))
    if escaped:
        raise ValueError(f"quality report exposed forbidden market/economic keys: {escaped}")
    if (
        report.get("contains_raw_market_or_strike_values") is not False
        or report.get(REPORT_ECONOMIC_FLAG) is not False
        or report.get("live_trading_allowed") is not False
    ):
        raise ValueError("quality report violated non-economic output contract")


def _parent_identity(snapshot: Path, config: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    checks = source.audit(snapshot)
    if not checks or not all(checks.values()):
        raise ValueError("parent option V2 source audit failed")
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    boundary = pd.Timestamp(config["eligibility"]["earliest_retrieved_at_utc"])
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    if retrieval < boundary:
        raise ValueError("parent option V2 snapshot precedes quality boundary")
    processed = snapshot / manifest["processed"]["path"]
    if _sha(processed) != manifest["processed"]["sha256"]:
        raise ValueError("parent option V2 processed identity mismatch")
    return manifest, processed


def publish(
    snapshot: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    config = load_config()
    snapshot = snapshot.resolve()
    manifest, processed = _parent_identity(snapshot, config)
    report = summarize_frame(pd.read_parquet(processed), config)
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / f"quality_{snapshot.name}_{CONFIG_SHA256[:8]}"
    if final.exists():
        raise FileExistsError(f"immutable option quality report already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=output_root))
    try:
        _write_json(temporary / "quality.json", report)
        identity = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(MODULE_PATH),
            "parent_snapshot_path": str(snapshot),
            "parent_manifest_sha256": _sha(snapshot / "manifest.json"),
            "parent_processed_sha256": manifest["processed"]["sha256"],
            "quality_sha256": _sha(temporary / "quality.json"),
            IDENTITY_ECONOMIC_FLAG: False,
            "live_trading_allowed": False,
        }
        _write_json(temporary / "identity.json", identity)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("published option quality report failed replay audit")
    return final


def audit(report_directory: Path) -> dict[str, bool]:
    config = load_config()
    identity = json.loads((report_directory / "identity.json").read_text(encoding="utf-8-sig"))
    stored = json.loads((report_directory / "quality.json").read_text(encoding="utf-8-sig"))
    snapshot = Path(identity["parent_snapshot_path"])
    manifest, processed = _parent_identity(snapshot, config)
    rebuilt = summarize_frame(pd.read_parquet(processed), config)
    try:
        _assert_output_contract(stored, config)
        contract_exact = True
    except ValueError:
        contract_exact = False
    return {
        "config_exact": identity["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": identity["implementation_sha256"] == _sha(MODULE_PATH),
        "parent_manifest_exact": identity["parent_manifest_sha256"]
        == _sha(snapshot / "manifest.json"),
        "parent_processed_exact": identity["parent_processed_sha256"]
        == manifest["processed"]["sha256"],
        "stored_quality_exact": identity["quality_sha256"]
        == _sha(report_directory / "quality.json"),
        "deterministic_replay_exact": stored == rebuilt,
        "output_contract_exact": contract_exact,
        "target_free": identity[IDENTITY_ECONOMIC_FLAG] is False,
        "live_trading_disabled": identity["live_trading_allowed"] is False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        if not all(checks.values()):
            raise SystemExit(1)
        return
    if args.snapshot is None:
        parser.error("--snapshot is required unless --audit-directory is used")
    print(publish(args.snapshot, args.output_root))


if __name__ == "__main__":
    main()
