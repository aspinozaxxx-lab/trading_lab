"""Build causal core-four option BBO states from the official Type B sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_type_b_core4_bbo_derived_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "37b96e58548e0f4f2f6ab2ad3cdefb874b9909469eb575b5da33c74052d44db0"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/options/moex-type-b-core4-bbo-2024-10-01-v1"
)
BATCH_ROWS: Final[int] = 250_000
EVENT_COLUMNS: Final[list[str]] = [
    "source_date",
    "event_at_moscow",
    "original_row_number",
    "secid",
    "logical_asset",
    "strike",
    "option_type",
    "option_system",
    "side",
    "event_kind",
    "trade_id",
    "price",
    "volume",
]


@dataclass
class QuoteState:
    bid_price: float | None = None
    bid_volume: int | None = None
    bid_updated_at: pd.Timestamp | None = None
    offer_price: float | None = None
    offer_volume: int | None = None
    offer_updated_at: pd.Timestamp | None = None


@dataclass(frozen=True)
class BuildResult:
    metrics: dict[str, Any]
    stream_hashes: dict[str, str]
    row_counts: dict[str, int]


class Writers:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        outputs = config["outputs"]
        self.paths = {
            "events": root / outputs["events"],
            "state": root / outputs["state"],
            "trade_context": root / outputs["trade_context"],
        }
        self.writers: dict[str, pq.ParquetWriter] = {}

    def write(self, name: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        writer = self.writers.get(name)
        if writer is None:
            writer = pq.ParquetWriter(self.paths[name], table.schema, compression="zstd")
            self.writers[name] = writer
        elif writer.schema != table.schema:
            raise ValueError(f"core-four {name} schema drifted across batches")
        writer.write_table(table)

    def close(self) -> None:
        for writer in self.writers.values():
            writer.close()


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
        raise ValueError("core-four BBO config must be an object")
    type_b = config["type_b_parent"]
    identity = config["identity_parent"]
    state = config["state_machine"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_type_b_core4_bbo_derived_v1"
        or config.get("status")
        != "sealed_after_parent_structural_counts_before_bbo_state_reconstruction"
        or config.get("live_trading_allowed") is not False
        or int(type_b["tick_rows"]) != 6_561_395
        or int(type_b["deal_rows"]) != 16_753
        or int(identity["processed_rows"]) != 1_327_744
        or pd.Timestamp(identity["identity_date"])
        >= pd.Timestamp(type_b.get("source_trade_date", "2024-10-01"))
        or identity["current_or_future_metadata_fallback"] != "forbidden"
        or state["trade_event_does_not_change_bid_or_offer"] is not True
        or state["quote_clear_sets_exact_side_price_and_volume_to_null"] is not True
        or config["limitations"][0]
        != "Structural counts from this single sample day cannot select an economic strategy."
    ):
        raise ValueError("core-four BBO protocol drifted")
    return config


def _verify_parent(config: dict[str, Any]) -> tuple[Path, Path]:
    type_b = config["type_b_parent"]
    identity = config["identity_parent"]
    type_root = _root(type_b["root"])
    identity_root = _root(identity["root"])
    for root, spec in ((type_root, type_b), (identity_root, identity)):
        if _sha_file(root / "manifest.json") != spec["manifest_sha256"]:
            raise ValueError("core-four parent manifest drift")
        if _sha_file(root / "audit.json") != spec["audit_sha256"]:
            raise ValueError("core-four parent audit drift")
        report = json.loads((root / "audit.json").read_text(encoding="utf-8-sig"))
        if report.get("all_true") is not True:
            raise ValueError("core-four parent audit is not all true")
    type_manifest = json.loads((type_root / "manifest.json").read_text(encoding="utf-8-sig"))
    identity_manifest = json.loads(
        (identity_root / "manifest.json").read_text(encoding="utf-8-sig")
    )
    tick = type_root / "option_tick_events.parquet"
    deal = type_root / "option_deals.parquet"
    processed = identity_root / "options_weekly_core4.parquet"
    if (
        type_manifest["protocol_id"] != type_b["protocol_id"]
        or type_manifest["protocol_sha256"] != type_b["protocol_sha256"]
        or _sha_file(tick) != type_b["tick_sha256"]
        or pq.ParquetFile(tick).metadata.num_rows != int(type_b["tick_rows"])
        or _sha_file(deal) != type_b["deal_sha256"]
        or pq.ParquetFile(deal).metadata.num_rows != int(type_b["deal_rows"])
        or identity_manifest["protocol_id"] != identity["protocol_id"]
        or identity_manifest["config_sha256"] != identity["protocol_sha256"]
        or _sha_file(processed) != identity["processed_sha256"]
        or pq.ParquetFile(processed).metadata.num_rows != int(identity["processed_rows"])
    ):
        raise ValueError("core-four parent artifact identity drift")
    return type_root, identity_root


def _identity(identity_root: Path, config: dict[str, Any]) -> pd.DataFrame:
    spec = config["identity_parent"]
    columns = ["tradedate", *spec["allowed_identity_columns"]]
    frame = pd.read_parquet(identity_root / "options_weekly_core4.parquet", columns=columns)
    frame["tradedate"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    selected = frame.loc[
        frame["tradedate"].eq(pd.Timestamp(spec["identity_date"])),
        spec["allowed_identity_columns"],
    ].copy()
    if selected.empty:
        raise ValueError("core-four identity date is empty")
    duplicated = selected[selected.duplicated("secid", keep=False)]
    if not duplicated.empty:
        unique_per_id = duplicated.groupby("secid", observed=True).nunique(dropna=False)
        if unique_per_id.gt(1).any(axis=None):
            raise ValueError("core-four identity conflicts on prior date")
        selected = selected.drop_duplicates("secid", keep="first")
    expected_assets = set(config["universe"]["logical_assets"])
    if set(selected["logical_asset"].astype(str)) != expected_assets:
        raise ValueError("core-four identity asset coverage drift")
    if selected["secid"].isna().any() or selected["strike"].isna().any():
        raise ValueError("core-four identity contains null keys")
    return selected.sort_values("secid", kind="stable", ignore_index=True)


def _hash_frame(digest: Any, frame: pd.DataFrame) -> None:
    digest.update(len(frame).to_bytes(8, "little", signed=False))
    hashes = pd.util.hash_pandas_object(frame, index=False, categorize=False)
    digest.update(hashes.to_numpy(dtype="uint64", copy=False).tobytes())


def _nullable_float(values: list[float | None]) -> pd.Series:
    return pd.Series(values, dtype="Float64")


def _nullable_int(values: list[int | None]) -> pd.Series:
    return pd.Series(values, dtype="Int64")


def _nullable_bool(values: list[bool | None]) -> pd.Series:
    return pd.Series(values, dtype="boolean")


def _moscow_times(values: list[pd.Timestamp | None]) -> pd.Series:
    return pd.Series(values, dtype="datetime64[ns, Europe/Moscow]")


def apply_state_machine(
    events: pd.DataFrame,
    states: dict[str, QuoteState],
    deals: dict[int, tuple[str, str, int]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    state_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for row in events[EVENT_COLUMNS].itertuples(index=False):
        (
            source_date,
            event_at,
            original_row,
            secid,
            logical_asset,
            strike,
            option_type,
            option_system,
            side,
            event_kind,
            trade_id,
            price,
            volume,
        ) = row
        secid = str(secid)
        event_at = pd.Timestamp(event_at)
        current = states.setdefault(secid, QuoteState())
        if str(event_kind) == "trade":
            if pd.isna(trade_id):
                raise ValueError("core-four trade event lacks trade id")
            identifier = int(trade_id)
            if identifier not in deals or deals[identifier][0] != secid:
                raise ValueError("core-four trade/deal identity mismatch")
            direction, deal_asset, open_interest = deals[identifier][1:]
            if deal_asset != str(logical_asset):
                raise ValueError("core-four trade/deal asset mismatch")
            two_sided_before = current.bid_price is not None and current.offer_price is not None
            trade_price = float(price)
            trade_rows.append(
                {
                    "source_date": source_date,
                    "event_at_moscow": event_at,
                    "original_row_number": int(original_row),
                    "secid": secid,
                    "logical_asset": logical_asset,
                    "strike": float(strike),
                    "option_type": option_type,
                    "trade_id": identifier,
                    "trade_price": trade_price,
                    "trade_volume": int(volume),
                    "deal_direction": direction,
                    "open_interest": open_interest,
                    "prior_bid_price": current.bid_price,
                    "prior_bid_volume": current.bid_volume,
                    "prior_offer_price": current.offer_price,
                    "prior_offer_volume": current.offer_volume,
                    "prior_two_sided": two_sided_before,
                    "trade_at_or_above_prior_offer": (
                        None
                        if current.offer_price is None
                        else trade_price >= current.offer_price
                    ),
                    "trade_at_or_below_prior_bid": (
                        None if current.bid_price is None else trade_price <= current.bid_price
                    ),
                    "trade_inside_prior_spread": (
                        None
                        if not two_sided_before
                        else current.bid_price < trade_price < current.offer_price
                    ),
                }
            )
        elif str(event_kind) in {"best_quote_update", "best_quote_clear"}:
            cleared = str(event_kind) == "best_quote_clear"
            if str(side) == "B":
                current.bid_price = None if cleared else float(price)
                current.bid_volume = None if cleared else int(volume)
                current.bid_updated_at = event_at
            elif str(side) == "S":
                current.offer_price = None if cleared else float(price)
                current.offer_volume = None if cleared else int(volume)
                current.offer_updated_at = event_at
            else:
                raise ValueError("core-four quote side drift")
        else:
            raise ValueError("core-four event kind drift")
        two_sided = current.bid_price is not None and current.offer_price is not None
        bid_age = (
            None
            if current.bid_price is None or current.bid_updated_at is None
            else (event_at - current.bid_updated_at).total_seconds()
        )
        offer_age = (
            None
            if current.offer_price is None or current.offer_updated_at is None
            else (event_at - current.offer_updated_at).total_seconds()
        )
        state_rows.append(
            {
                "source_date": source_date,
                "event_at_moscow": event_at,
                "original_row_number": int(original_row),
                "secid": secid,
                "logical_asset": logical_asset,
                "strike": float(strike),
                "option_type": option_type,
                "trigger_event_kind": event_kind,
                "trigger_side": side,
                "bid_price": current.bid_price,
                "bid_volume": current.bid_volume,
                "bid_updated_at_moscow": current.bid_updated_at,
                "bid_age_seconds": bid_age,
                "offer_price": current.offer_price,
                "offer_volume": current.offer_volume,
                "offer_updated_at_moscow": current.offer_updated_at,
                "offer_age_seconds": offer_age,
                "two_sided": two_sided,
                "locked_or_crossed": (
                    None if not two_sided else current.bid_price >= current.offer_price
                ),
            }
        )
    state_frame = pd.DataFrame(state_rows)
    if state_frame.empty:
        return state_frame, pd.DataFrame()
    for column in ("bid_price", "bid_age_seconds", "offer_price", "offer_age_seconds"):
        state_frame[column] = _nullable_float(state_frame[column].tolist())
    for column in ("bid_volume", "offer_volume"):
        state_frame[column] = _nullable_int(state_frame[column].tolist())
    for column in ("bid_updated_at_moscow", "offer_updated_at_moscow"):
        state_frame[column] = _moscow_times(state_frame[column].tolist())
    state_frame["two_sided"] = _nullable_bool(state_frame["two_sided"].tolist())
    state_frame["locked_or_crossed"] = _nullable_bool(
        state_frame["locked_or_crossed"].tolist()
    )
    trade_frame = pd.DataFrame(trade_rows)
    if not trade_frame.empty:
        for column in ("prior_bid_price", "prior_offer_price"):
            trade_frame[column] = _nullable_float(trade_frame[column].tolist())
        for column in ("prior_bid_volume", "prior_offer_volume"):
            trade_frame[column] = _nullable_int(trade_frame[column].tolist())
        for column in (
            "prior_two_sided",
            "trade_at_or_above_prior_offer",
            "trade_at_or_below_prior_bid",
            "trade_inside_prior_spread",
        ):
            trade_frame[column] = _nullable_bool(trade_frame[column].tolist())
    return state_frame, trade_frame


def _deal_lookup(type_root: Path, identity: pd.DataFrame) -> dict[int, tuple[str, str, int]]:
    deals = pd.read_parquet(type_root / "option_deals.parquet")
    mapped = deals.merge(
        identity[["secid", "logical_asset"]], on="secid", how="inner", validate="many_to_one"
    )
    if mapped["trade_id"].duplicated().any():
        raise ValueError("core-four mapped deal ids are not unique")
    return {
        int(row.trade_id): (
            str(row.secid),
            str(row.direction),
            str(row.logical_asset),
            int(row.open_interest),
        )
        for row in mapped.itertuples(index=False)
    }


def build(root: Path, config: dict[str, Any]) -> BuildResult:
    type_root, identity_root = _verify_parent(config)
    identity = _identity(identity_root, config)
    identity_path = root / config["outputs"]["identity"]
    identity.to_parquet(identity_path, index=False, compression="zstd")
    deals_raw = pd.read_parquet(type_root / "option_deals.parquet")
    deals_mapped = deals_raw.merge(
        identity[["secid", "logical_asset"]], on="secid", how="inner", validate="many_to_one"
    )
    if deals_mapped["trade_id"].duplicated().any():
        raise ValueError("core-four mapped deal ids are not unique")
    deals = {
        int(row.trade_id): (
            str(row.secid),
            str(row.direction),
            str(row.logical_asset),
            int(row.open_interest),
        )
        for row in deals_mapped.itertuples(index=False)
    }
    parent_file = pq.ParquetFile(type_root / "option_tick_events.parquet")
    identity_ids = set(identity["secid"].astype(str))
    states: dict[str, QuoteState] = {}
    writers = Writers(root, config)
    digests = {name: hashlib.sha256() for name in writers.paths}
    row_counts: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    mapped_secids: set[str] = set()
    total_input = 0
    last_event: pd.Timestamp | None = None
    last_row = 0
    try:
        for batch in parent_file.iter_batches(batch_size=BATCH_ROWS):
            raw = batch.to_pandas()
            total_input += len(raw)
            mapped = raw.loc[raw["secid"].astype(str).isin(identity_ids)].merge(
                identity, on="secid", how="inner", validate="many_to_one", sort=False
            )
            if mapped.empty:
                continue
            mapped = mapped.sort_values("original_row_number", kind="stable")
            mapped = mapped.loc[:, EVENT_COLUMNS].reset_index(drop=True)
            event_times = pd.to_datetime(mapped["event_at_moscow"], errors="raise")
            rows = mapped["original_row_number"].astype("int64")
            if not event_times.is_monotonic_increasing or not rows.is_monotonic_increasing:
                raise ValueError("core-four mapped input order is not monotonic")
            if last_event is not None and event_times.iloc[0] < last_event:
                raise ValueError("core-four event time regressed across batches")
            if int(rows.iloc[0]) <= last_row:
                raise ValueError("core-four original row regressed across batches")
            last_event = pd.Timestamp(event_times.iloc[-1])
            last_row = int(rows.iloc[-1])
            state_frame, trade_frame = apply_state_machine(mapped, states, deals)
            writers.write("events", mapped)
            writers.write("state", state_frame)
            writers.write("trade_context", trade_frame)
            for name, frame in (
                ("events", mapped),
                ("state", state_frame),
                ("trade_context", trade_frame),
            ):
                if not frame.empty:
                    _hash_frame(digests[name], frame)
                    row_counts[name] += len(frame)
            mapped_secids.update(mapped["secid"].astype(str))
            for key, value in mapped.groupby(["logical_asset", "event_kind"]).size().items():
                counts[f"event:{key[0]}:{key[1]}"] += int(value)
            counts["state:two_sided"] += int(state_frame["two_sided"].fillna(False).sum())
            counts["state:locked_or_crossed"] += int(
                state_frame["locked_or_crossed"].fillna(False).sum()
            )
            if not trade_frame.empty:
                counts["trade:prior_two_sided"] += int(
                    trade_frame["prior_two_sided"].fillna(False).sum()
                )
                counts["trade:at_or_above_offer"] += int(
                    trade_frame["trade_at_or_above_prior_offer"].fillna(False).sum()
                )
                counts["trade:at_or_below_bid"] += int(
                    trade_frame["trade_at_or_below_prior_bid"].fillna(False).sum()
                )
                counts["trade:inside_spread"] += int(
                    trade_frame["trade_inside_prior_spread"].fillna(False).sum()
                )
    finally:
        writers.close()
    if total_input != int(config["type_b_parent"]["tick_rows"]):
        raise ValueError("core-four did not scan every parent event")
    if row_counts["events"] != row_counts["state"]:
        raise ValueError("core-four state row count differs from mapped input")
    if row_counts["trade_context"] != len(deals):
        raise ValueError("core-four trade context does not cover every mapped deal")
    if set(writers.writers) != {"events", "state", "trade_context"}:
        raise ValueError("core-four output stream is empty")
    metrics = {
        "source_trade_date": config["type_b_parent"].get(
            "source_trade_date", "2024-10-01"
        ),
        "identity_date": config["identity_parent"]["identity_date"],
        "parent_event_rows_scanned": total_input,
        "identity_rows": len(identity),
        "mapped_unique_secids": len(mapped_secids),
        "mapped_event_rows": row_counts["events"],
        "excluded_unmapped_event_rows": total_input - row_counts["events"],
        "mapped_trade_rows": row_counts["trade_context"],
        "counts": dict(sorted(counts.items())),
        "contains_signal_return_target_prediction_position_equity_or_pnl": False,
        "single_sample_day_not_performance_evidence": True,
        "live_trading_allowed": False,
    }
    return BuildResult(
        metrics=metrics,
        stream_hashes={name: digest.hexdigest() for name, digest in digests.items()},
        row_counts={name: int(value) for name, value in row_counts.items()},
    )


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha_file(path),
        "rows": rows,
    }


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
    with tempfile.TemporaryDirectory(prefix="trading-lab-core4-bbo-audit-") as temporary:
        replay = build(Path(temporary), config)
    checks = {
        "config_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "parent_artifacts_and_audits_exact": True,
        "artifacts_exact": artifacts_exact,
        "parquet_rows_exact": rows_exact,
        "state_replay_hashes_exact": replay.stream_hashes == manifest["stream_hashes"],
        "state_replay_rows_exact": replay.row_counts == manifest["row_counts"],
        "structural_metrics_replay_exact": replay.metrics == manifest["structural_metrics"],
        "events_and_state_one_to_one": (
            replay.row_counts["events"] == replay.row_counts["state"]
        ),
        "every_mapped_trade_has_context": (
            replay.row_counts["trade_context"]
            == replay.metrics["mapped_trade_rows"]
        ),
        "contains_no_economic_outputs": manifest["structural_metrics"][
            "contains_signal_return_target_prediction_position_equity_or_pnl"
        ]
        is False,
        "live_trading_disabled": manifest["live_trading_allowed"] is False,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def run(output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    config = load_config()
    _verify_parent(config)
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable core-four BBO output exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.parent / f".{output_root.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        result = build(temporary, config)
        metrics_path = temporary / config["outputs"]["metrics"]
        _write_json(metrics_path, result.metrics)
        output_paths = {
            "identity": temporary / config["outputs"]["identity"],
            "events": temporary / config["outputs"]["events"],
            "state": temporary / config["outputs"]["state"],
            "trade_context": temporary / config["outputs"]["trade_context"],
            "metrics": metrics_path,
        }
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "parent_type_b_manifest_sha256": config["type_b_parent"]["manifest_sha256"],
            "parent_identity_manifest_sha256": config["identity_parent"][
                "manifest_sha256"
            ],
            "stream_hashes": result.stream_hashes,
            "row_counts": result.row_counts,
            "structural_metrics": result.metrics,
            "artifacts": [
                _artifact(
                    output_paths["identity"],
                    len(_identity(_verify_parent(config)[1], config)),
                ),
                _artifact(output_paths["events"], result.row_counts["events"]),
                _artifact(output_paths["state"], result.row_counts["state"]),
                _artifact(
                    output_paths["trade_context"], result.row_counts["trade_context"]
                ),
                _artifact(output_paths["metrics"]),
            ],
            "contains_signal_return_target_prediction_position_equity_or_pnl": False,
            "live_trading_allowed": False,
        }
        _write_json(temporary / config["outputs"]["manifest"], manifest)
        report = audit(temporary)
        if report["all_true"] is not True:
            raise ValueError(f"core-four BBO audit failed: {report['checks']}")
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
