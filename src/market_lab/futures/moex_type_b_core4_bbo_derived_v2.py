"""Rebuild Type B BBO context from the end of the prior distinct timestamp."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_type_b_core4_bbo_derived_v1 as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_type_b_core4_bbo_derived_v2.yaml"
CONFIG_SHA256: Final[str] = (
    "fdf8b6555010dadbe87e1194bd87ad476b8a37b7df510f06dbc685322ab1ffd2"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/options/moex-type-b-core4-bbo-2024-10-01-v2"
)
BATCH_ROWS: Final[int] = 250_000
FLUSH_ROWS: Final[int] = 200_000


@dataclass(frozen=True)
class Result:
    metrics: dict[str, Any]
    stream_hashes: dict[str, str]
    row_counts: dict[str, int]


class Writers:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.paths = {
            "state": root / config["outputs"]["bbo_after_timestamp"],
            "trade_context": root / config["outputs"]["trade_context"],
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
            raise ValueError(f"strict-prior {name} schema drifted")
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


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("strict-prior BBO config must be an object")
    source = config["parent_v1"]
    blocks = config["causal_timestamp_blocks"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_type_b_core4_bbo_derived_v2"
        or config.get("status")
        != "sealed_after_same_timestamp_artifact_discovery_before_corrected_replay"
        or config.get("live_trading_allowed") is not False
        or int(source["events_rows"]) != 1_671_909
        or int(source["trade_rows"]) != 13_670
        or source["diagnostic_found_all_trades_at_both_sides_of_transient_locked_book"]
        is not True
        or blocks["trade_context_snapshot"]
        != "state_at_end_of_previous_distinct_timestamp"
        or blocks[
            "quote_updates_and_clears_apply_only_after_all_trade_contexts_in_block_are_captured"
        ]
        is not True
        or config["limitations"][0]
        != "One sample date validates mechanics and coverage, never expected return."
    ):
        raise ValueError("strict-prior BBO protocol drifted")
    return config


def _parent_root(config: dict[str, Any]) -> Path:
    spec = config["parent_v1"]
    root = (PROJECT_ROOT / spec["root"]).resolve()
    if (
        _sha_file(root / "manifest.json") != spec["manifest_sha256"]
        or _sha_file(root / "audit.json") != spec["audit_sha256"]
        or _sha_file(root / "core4_events.parquet") != spec["events_sha256"]
        or _sha_file(root / "core4_trade_context.parquet")
        != spec["trade_context_sha256"]
        or pq.ParquetFile(root / "core4_events.parquet").metadata.num_rows
        != int(spec["events_rows"])
        or pq.ParquetFile(root / "core4_trade_context.parquet").metadata.num_rows
        != int(spec["trade_rows"])
    ):
        raise ValueError("strict-prior BBO parent artifact drift")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((root / "audit.json").read_text(encoding="utf-8-sig"))
    if (
        manifest["protocol_sha256"] != spec["protocol_sha256"]
        or manifest["implementation_sha256"] != spec["implementation_sha256"]
        or audit.get("all_true") is not True
    ):
        raise ValueError("strict-prior BBO parent identity or audit drift")
    return root


def _frame_hash(digest: Any, frame: pd.DataFrame) -> None:
    digest.update(len(frame).to_bytes(8, "little", signed=False))
    values = pd.util.hash_pandas_object(frame, index=False, categorize=False)
    digest.update(values.to_numpy(dtype="uint64", copy=False).tobytes())


def _state_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for column in ("bid_price", "bid_age_seconds", "offer_price", "offer_age_seconds"):
        frame[column] = parent._nullable_float(frame[column].tolist())
    for column in ("bid_volume", "offer_volume"):
        frame[column] = parent._nullable_int(frame[column].tolist())
    for column in ("bid_updated_at_moscow", "offer_updated_at_moscow"):
        frame[column] = parent._moscow_times(frame[column].tolist())
    frame["two_sided"] = parent._nullable_bool(frame["two_sided"].tolist())
    frame["locked_or_crossed"] = parent._nullable_bool(
        frame["locked_or_crossed"].tolist()
    )
    return frame


def _trade_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for column in ("prior_bid_price", "prior_offer_price"):
        frame[column] = parent._nullable_float(frame[column].tolist())
    for column in ("prior_bid_volume", "prior_offer_volume"):
        frame[column] = parent._nullable_int(frame[column].tolist())
    for column in ("prior_bid_updated_at_moscow", "prior_offer_updated_at_moscow"):
        frame[column] = parent._moscow_times(frame[column].tolist())
    for column in (
        "prior_two_sided",
        "prior_locked_or_crossed",
        "trade_at_or_above_prior_offer",
        "trade_at_or_below_prior_bid",
        "trade_inside_prior_spread",
    ):
        frame[column] = parent._nullable_bool(frame[column].tolist())
    return frame


def process_timestamp_block(
    block: list[tuple[Any, ...]],
    states: dict[str, parent.QuoteState],
    deal_metadata: dict[int, tuple[str, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not block:
        return [], []
    timestamp = pd.Timestamp(block[0][1])
    if any(pd.Timestamp(row[1]) != timestamp for row in block):
        raise ValueError("strict-prior block contains multiple timestamps")
    touched: dict[str, tuple[Any, ...]] = {}
    pre_state: dict[str, parent.QuoteState] = {}
    for row in block:
        secid = str(row[3])
        touched[secid] = row
        pre_state.setdefault(secid, replace(states.get(secid, parent.QuoteState())))
    trade_rows: list[dict[str, Any]] = []
    for row in block:
        (
            source_date,
            event_at,
            original_row,
            secid,
            logical_asset,
            strike,
            option_type,
            _option_system,
            _side,
            event_kind,
            trade_id,
            price,
            volume,
        ) = row
        if str(event_kind) != "trade":
            continue
        identifier = int(trade_id)
        if identifier not in deal_metadata:
            raise ValueError("strict-prior trade lacks parent deal metadata")
        direction, open_interest = deal_metadata[identifier]
        prior = pre_state[str(secid)]
        for updated in (prior.bid_updated_at, prior.offer_updated_at):
            if updated is not None and updated >= pd.Timestamp(event_at):
                raise ValueError("strict-prior trade context used same/future timestamp")
        two_sided = prior.bid_price is not None and prior.offer_price is not None
        trade_price = float(price)
        trade_rows.append(
            {
                "source_date": source_date,
                "event_at_moscow": event_at,
                "original_row_number": int(original_row),
                "secid": str(secid),
                "logical_asset": logical_asset,
                "strike": float(strike),
                "option_type": option_type,
                "trade_id": identifier,
                "trade_price": trade_price,
                "trade_volume": int(volume),
                "deal_direction": direction,
                "open_interest": open_interest,
                "prior_bid_price": prior.bid_price,
                "prior_bid_volume": prior.bid_volume,
                "prior_bid_updated_at_moscow": prior.bid_updated_at,
                "prior_offer_price": prior.offer_price,
                "prior_offer_volume": prior.offer_volume,
                "prior_offer_updated_at_moscow": prior.offer_updated_at,
                "prior_two_sided": two_sided,
                "prior_locked_or_crossed": (
                    None if not two_sided else prior.bid_price >= prior.offer_price
                ),
                "trade_at_or_above_prior_offer": (
                    None if prior.offer_price is None else trade_price >= prior.offer_price
                ),
                "trade_at_or_below_prior_bid": (
                    None if prior.bid_price is None else trade_price <= prior.bid_price
                ),
                "trade_inside_prior_spread": (
                    None
                    if not two_sided
                    else prior.bid_price < trade_price < prior.offer_price
                ),
            }
        )
    for row in block:
        event_at, secid, side, event_kind, price, volume = (
            pd.Timestamp(row[1]),
            str(row[3]),
            str(row[8]),
            str(row[9]),
            row[11],
            row[12],
        )
        current = states.setdefault(secid, parent.QuoteState())
        if event_kind == "trade":
            continue
        if event_kind not in {"best_quote_update", "best_quote_clear"}:
            raise ValueError("strict-prior event kind drift")
        cleared = event_kind == "best_quote_clear"
        if side == "B":
            current.bid_price = None if cleared else float(price)
            current.bid_volume = None if cleared else int(volume)
            current.bid_updated_at = event_at
        elif side == "S":
            current.offer_price = None if cleared else float(price)
            current.offer_volume = None if cleared else int(volume)
            current.offer_updated_at = event_at
        else:
            raise ValueError("strict-prior side drift")
    state_rows: list[dict[str, Any]] = []
    for secid, last_row in touched.items():
        current = states.setdefault(secid, parent.QuoteState())
        two_sided = current.bid_price is not None and current.offer_price is not None
        bid_age = (
            None
            if current.bid_price is None or current.bid_updated_at is None
            else (timestamp - current.bid_updated_at).total_seconds()
        )
        offer_age = (
            None
            if current.offer_price is None or current.offer_updated_at is None
            else (timestamp - current.offer_updated_at).total_seconds()
        )
        if (bid_age is not None and bid_age < 0.0) or (
            offer_age is not None and offer_age < 0.0
        ):
            raise ValueError("strict-prior negative quote age")
        state_rows.append(
            {
                "source_date": last_row[0],
                "event_at_moscow": timestamp,
                "last_original_row_number": int(last_row[2]),
                "secid": secid,
                "logical_asset": last_row[4],
                "strike": float(last_row[5]),
                "option_type": last_row[6],
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
    return state_rows, trade_rows


def build(root: Path, config: dict[str, Any]) -> Result:
    source_root = _parent_root(config)
    old_context = pd.read_parquet(
        source_root / "core4_trade_context.parquet",
        columns=["trade_id", "deal_direction", "open_interest"],
    )
    if old_context["trade_id"].duplicated().any():
        raise ValueError("strict-prior parent trade ids are not unique")
    deal_metadata = {
        int(row.trade_id): (str(row.deal_direction), int(row.open_interest))
        for row in old_context.itertuples(index=False)
    }
    event_file = pq.ParquetFile(source_root / "core4_events.parquet")
    writers = Writers(root, config)
    digests = {name: hashlib.sha256() for name in writers.paths}
    row_counts: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    states: dict[str, parent.QuoteState] = {}
    pending_timestamp: pd.Timestamp | None = None
    pending_block: list[tuple[Any, ...]] = []
    state_buffer: list[dict[str, Any]] = []
    trade_buffer: list[dict[str, Any]] = []
    scanned = 0
    last_timestamp: pd.Timestamp | None = None
    last_row_number = 0

    def flush_buffers(force: bool = False) -> None:
        if force or len(state_buffer) >= FLUSH_ROWS:
            frame = _state_frame(state_buffer)
            writers.write("state", frame)
            if not frame.empty:
                _frame_hash(digests["state"], frame)
                row_counts["state"] += len(frame)
            state_buffer.clear()
        if force or len(trade_buffer) >= FLUSH_ROWS:
            frame = _trade_frame(trade_buffer)
            writers.write("trade_context", frame)
            if not frame.empty:
                _frame_hash(digests["trade_context"], frame)
                row_counts["trade_context"] += len(frame)
                counts["trade:prior_two_sided"] += int(
                    frame["prior_two_sided"].fillna(False).sum()
                )
                counts["trade:prior_locked_or_crossed"] += int(
                    frame["prior_locked_or_crossed"].fillna(False).sum()
                )
                counts["trade:at_or_above_offer"] += int(
                    frame["trade_at_or_above_prior_offer"].fillna(False).sum()
                )
                counts["trade:at_or_below_bid"] += int(
                    frame["trade_at_or_below_prior_bid"].fillna(False).sum()
                )
                counts["trade:inside_spread"] += int(
                    frame["trade_inside_prior_spread"].fillna(False).sum()
                )
            trade_buffer.clear()

    def finish_block() -> None:
        if not pending_block:
            return
        state_rows, trade_rows = process_timestamp_block(
            pending_block, states, deal_metadata
        )
        state_buffer.extend(state_rows)
        trade_buffer.extend(trade_rows)
        counts["timestamp_blocks"] += 1
        flush_buffers()

    try:
        for batch in event_file.iter_batches(batch_size=BATCH_ROWS):
            frame = batch.to_pandas()
            for row in frame[parent.EVENT_COLUMNS].itertuples(index=False, name=None):
                timestamp = pd.Timestamp(row[1])
                row_number = int(row[2])
                if last_timestamp is not None and timestamp < last_timestamp:
                    raise ValueError("strict-prior event timestamp regressed")
                if row_number <= last_row_number:
                    raise ValueError("strict-prior original row number regressed")
                if pending_timestamp is not None and timestamp != pending_timestamp:
                    finish_block()
                    pending_block = []
                pending_timestamp = timestamp
                pending_block.append(row)
                last_timestamp = timestamp
                last_row_number = row_number
                scanned += 1
        finish_block()
        pending_block = []
        flush_buffers(force=True)
    finally:
        writers.close()
    expected_events = int(config["parent_v1"]["events_rows"])
    expected_trades = int(config["parent_v1"]["trade_rows"])
    if scanned != expected_events:
        raise ValueError("strict-prior did not scan every parent event")
    if row_counts["trade_context"] != expected_trades:
        raise ValueError("strict-prior trade context coverage drift")
    if set(writers.writers) != {"state", "trade_context"}:
        raise ValueError("strict-prior output stream is empty")
    metrics = {
        "parent_event_rows_scanned": scanned,
        "timestamp_blocks": counts["timestamp_blocks"],
        "bbo_after_timestamp_rows": row_counts["state"],
        "trade_context_rows": row_counts["trade_context"],
        "counts": dict(sorted(counts.items())),
        "same_timestamp_quotes_used_for_trade_context": False,
        "contains_signal_return_target_prediction_position_equity_or_pnl": False,
        "single_sample_day_not_performance_evidence": True,
        "live_trading_allowed": False,
    }
    return Result(
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
    _parent_root(config)
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
    with tempfile.TemporaryDirectory(prefix="trading-lab-strict-bbo-audit-") as temporary:
        replay = build(Path(temporary), config)
    checks = {
        "config_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "parent_exact_and_audited": True,
        "artifacts_exact": artifacts_exact,
        "parquet_rows_exact": rows_exact,
        "state_replay_hashes_exact": replay.stream_hashes == manifest["stream_hashes"],
        "state_replay_rows_exact": replay.row_counts == manifest["row_counts"],
        "structural_metrics_replay_exact": replay.metrics == manifest["structural_metrics"],
        "every_trade_has_context": (
            replay.row_counts["trade_context"] == int(config["parent_v1"]["trade_rows"])
        ),
        "no_same_timestamp_quote_context": replay.metrics[
            "same_timestamp_quotes_used_for_trade_context"
        ]
        is False,
        "contains_no_economic_outputs": replay.metrics[
            "contains_signal_return_target_prediction_position_equity_or_pnl"
        ]
        is False,
        "live_trading_disabled": manifest["live_trading_allowed"] is False,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def run(output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    config = load_config()
    _parent_root(config)
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable strict-prior BBO output exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.parent / f".{output_root.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        result = build(temporary, config)
        metrics_path = temporary / config["outputs"]["structural_metrics"]
        _write_json(metrics_path, result.metrics)
        state_path = temporary / config["outputs"]["bbo_after_timestamp"]
        trade_path = temporary / config["outputs"]["trade_context"]
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "parent_manifest_sha256": config["parent_v1"]["manifest_sha256"],
            "stream_hashes": result.stream_hashes,
            "row_counts": result.row_counts,
            "structural_metrics": result.metrics,
            "artifacts": [
                _artifact(state_path, result.row_counts["state"]),
                _artifact(trade_path, result.row_counts["trade_context"]),
                _artifact(metrics_path),
            ],
            "contains_signal_return_target_prediction_position_equity_or_pnl": False,
            "live_trading_allowed": False,
        }
        _write_json(temporary / config["outputs"]["manifest"], manifest)
        report = audit(temporary)
        if report["all_true"] is not True:
            raise ValueError(f"strict-prior BBO audit failed: {report['checks']}")
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
