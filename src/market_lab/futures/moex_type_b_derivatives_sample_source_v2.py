"""Parse the official one-day MOEX derivatives Type B sample without outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_type_b_derivatives_sample_source_v2.yaml"
)
CONFIG_SHA256: Final[str] = (
    "52919f7ce9b0bfa6d617d5e46568781c3e16d3974be42ac39f8e0693a11513f3"
)
DEFAULT_ARCHIVE: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/options/moex-type-b-derivatives-sample-2024-10-01-v1"
    / "OrderLog20241001_B.7z"
)
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/options/moex-type-b-derivatives-sample-2024-10-01-v2"
)
TICK_HEADER: Final[list[str]] = [
    "#SYMBOL",
    "SYSTEM",
    "TYPE",
    "MOMENT",
    "DEAL_ID",
    "PRICE",
    "VOLUME",
]
DEAL_HEADER: Final[list[str]] = [
    "#SYMBOL",
    "SYSTEM",
    "MOMENT",
    "ID_DEAL",
    "PRICE_DEAL",
    "VOLUME",
    "OPEN_POS",
    "DIRECTION",
]
TICK_ARCHIVE: Final[str] = "20241001_opt_tick.7z"
DEAL_ARCHIVE: Final[str] = "20241001_opt_deal.7z"
TICK_MEMBER: Final[str] = "20241001_opt_tick.csv"
DEAL_MEMBER: Final[str] = "20241001_opt_deal.csv"
CHUNK_ROWS: Final[int] = 250_000


@dataclass(frozen=True)
class ParsedStream:
    rows: int
    first_event_at_moscow: str
    last_event_at_moscow: str
    normalized_stream_sha256: str
    counts: dict[str, int]
    trade_ids: frozenset[int]


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
        raise ValueError("Type B sample config must be an object")
    parent = config["parent_v1"]
    source = config["source"]
    discovered = config["discovered_archive_identity"]
    temporal = config["temporal_correction"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_type_b_derivatives_sample_source_v2"
        or config.get("status")
        != "sealed_after_member_header_discovery_before_full_value_parse"
        or config.get("live_trading_allowed") is not False
        or _sha_file(PROJECT_ROOT / parent["config_path"]) != parent["config_sha256"]
        or source["archive_sha256"]
        != "afccc1602d81c15dd064eadd44dd91a3aff53bcb3213fe96840f0b8188601e30"
        or int(source["expected_content_length_bytes"]) != 101_968_982
        or int(discovered["outer_member_count"]) != 4
        or temporal["source_trade_date_can_include_previous_calendar_evening"] is not True
        or config["limitations"][0]
        != "This is one free sample trade date, not a performance sample."
    ):
        raise ValueError("Type B sample source protocol drifted")
    return config


def _run_7z(*arguments: str) -> str:
    completed = subprocess.run(
        ["7z", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no diagnostic").splitlines()
        raise RuntimeError(f"7z failed: {detail[-1] if detail else 'no diagnostic'}")
    return completed.stdout


def _archive_members(path: Path) -> list[dict[str, Any]]:
    text = _run_7z("l", "-slt", str(path))
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_members = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "----------":
            in_members = True
            continue
        if not in_members or " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        if key == "Path":
            if current is not None:
                records.append(current)
            current = {"path": value}
        elif current is not None and key in {"Size", "Packed Size", "CRC"}:
            normalized = key.lower().replace(" ", "_")
            current[normalized] = int(value) if key != "CRC" and value else value
    if current is not None:
        records.append(current)
    return records


def _validate_member_listing(
    actual: list[dict[str, Any]], expected: dict[str, dict[str, Any]]
) -> None:
    by_path = {str(item["path"]): item for item in actual}
    if set(by_path) != set(expected):
        raise ValueError("Type B archive member identity drift")
    for name, identity in expected.items():
        item = by_path[name]
        if int(item["size"]) != int(identity["bytes"]):
            raise ValueError(f"Type B member size drift: {name}")
        if str(item["crc"]).upper() != str(identity["crc32"]).upper():
            raise ValueError(f"Type B member CRC drift: {name}")


def _parse_moment(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    raw = series.astype("string").str.strip()
    allowed = {int(value) for value in config["temporal_correction"]["raw_moment_digits_allowed"]}
    if raw.isna().any() or not raw.str.len().isin(allowed).all() or not raw.str.isdigit().all():
        raise ValueError("Type B MOMENT format drift")
    base = pd.to_datetime(raw.str.slice(0, 14), format="%Y%m%d%H%M%S", errors="raise")
    fraction = raw.str.slice(14)
    micros = fraction.str.pad(6, side="right", fillchar="0").astype("int64")
    event = base.dt.tz_localize(config["temporal_correction"]["timezone"])
    event = event + pd.to_timedelta(micros, unit="us")
    earliest = pd.Timestamp(config["temporal_correction"]["earliest_allowed_event_at_moscow"])
    latest = pd.Timestamp(config["temporal_correction"]["latest_allowed_event_at_moscow"])
    if event.lt(earliest).any() or event.gt(latest).any():
        raise ValueError("Type B event escaped corrected source-session window")
    return event


def _positive_numeric(series: pd.Series, name: str) -> pd.Series:
    output = pd.to_numeric(series, errors="raise").astype(float)
    if output.isna().any() or not np.isfinite(output).all() or output.le(0.0).any():
        raise ValueError(f"Type B {name} must be finite and positive")
    return output


def _positive_integer(series: pd.Series, name: str) -> pd.Series:
    numeric = _positive_numeric(series, name)
    if not np.equal(numeric, np.floor(numeric)).all():
        raise ValueError(f"Type B {name} must be integer")
    return numeric.astype("int64")


def _nonnegative_integer(series: pd.Series, name: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="raise").astype(float)
    if (
        numeric.isna().any()
        or not np.isfinite(numeric).all()
        or numeric.lt(0.0).any()
        or not np.equal(numeric, np.floor(numeric)).all()
    ):
        raise ValueError(f"Type B {name} must be a nonnegative integer")
    return numeric.astype("int64")


def _trade_id(series: pd.Series, *, required: bool) -> pd.Series:
    raw = series.astype("string").str.strip()
    missing = raw.eq("") | raw.isna()
    if required and missing.any():
        raise ValueError("Type B deal row lacks trade id")
    if (~missing & ~raw.str.fullmatch(r"\d+").fillna(False)).any():
        raise ValueError("Type B trade id format drift")
    output = pd.to_numeric(raw.mask(missing), errors="raise").astype("Int64")
    if output.dropna().le(0).any():
        raise ValueError("Type B trade id must be positive")
    return output


def normalize_tick_chunk(
    frame: pd.DataFrame, start_row: int, config: dict[str, Any]
) -> pd.DataFrame:
    if list(frame.columns) != TICK_HEADER:
        raise ValueError("Type B option tick header drift")
    if not frame["SYSTEM"].isin(["C", "P"]).all():
        raise ValueError("Type B option tick admitted non-option system")
    if not frame["TYPE"].isin(["B", "S"]).all():
        raise ValueError("Type B option tick side drift")
    trade_id = _trade_id(frame["DEAL_ID"], required=False)
    rows = np.arange(start_row, start_row + len(frame), dtype=np.int64)
    return pd.DataFrame(
        {
            "source_date": pd.Timestamp(config["source"]["source_trade_date"]),
            "event_at_moscow": _parse_moment(frame["MOMENT"], config),
            "original_row_number": rows,
            "secid": frame["#SYMBOL"].astype("string"),
            "option_system": frame["SYSTEM"].astype("string"),
            "side": frame["TYPE"].astype("string"),
            "event_kind": pd.Series(
                np.where(trade_id.isna(), "best_quote_update", "trade"),
                index=frame.index,
                dtype="string",
            ),
            "trade_id": trade_id,
            "price": _positive_numeric(frame["PRICE"], "tick price"),
            "volume": _positive_integer(frame["VOLUME"], "tick volume"),
        }
    )


def normalize_deal_chunk(
    frame: pd.DataFrame, start_row: int, config: dict[str, Any]
) -> pd.DataFrame:
    if list(frame.columns) != DEAL_HEADER:
        raise ValueError("Type B option deal header drift")
    if not frame["SYSTEM"].isin(["C", "P"]).all():
        raise ValueError("Type B option deal admitted non-option system")
    if not frame["DIRECTION"].isin(["B", "S"]).all():
        raise ValueError("Type B option deal direction drift")
    rows = np.arange(start_row, start_row + len(frame), dtype=np.int64)
    return pd.DataFrame(
        {
            "source_date": pd.Timestamp(config["source"]["source_trade_date"]),
            "event_at_moscow": _parse_moment(frame["MOMENT"], config),
            "original_row_number": rows,
            "secid": frame["#SYMBOL"].astype("string"),
            "option_system": frame["SYSTEM"].astype("string"),
            "trade_id": _trade_id(frame["ID_DEAL"], required=True),
            "price": _positive_numeric(frame["PRICE_DEAL"], "deal price"),
            "volume": _positive_integer(frame["VOLUME"], "deal volume"),
            "open_interest": _nonnegative_integer(frame["OPEN_POS"], "deal open interest"),
            "direction": frame["DIRECTION"].astype("string"),
        }
    )


def _update_stream_hash(digest: Any, frame: pd.DataFrame) -> None:
    digest.update(len(frame).to_bytes(8, "little", signed=False))
    hashes = pd.util.hash_pandas_object(frame, index=False, categorize=False)
    digest.update(hashes.to_numpy(dtype="uint64", copy=False).tobytes())


def _parse_stream(
    archive: Path,
    member: str,
    kind: Literal["tick", "deal"],
    destination: Path,
    config: dict[str, Any],
) -> ParsedStream:
    process = subprocess.Popen(
        ["7z", "x", "-so", str(archive), member],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("7z stream has no stdout")
    reader = pd.read_csv(
        process.stdout,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        chunksize=CHUNK_ROWS,
    )
    writer: pq.ParquetWriter | None = None
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()
    trade_ids: set[int] = set()
    rows = 0
    first_event: pd.Timestamp | None = None
    last_event: pd.Timestamp | None = None
    try:
        for raw in reader:
            normalized = (
                normalize_tick_chunk(raw, rows + 1, config)
                if kind == "tick"
                else normalize_deal_chunk(raw, rows + 1, config)
            )
            event = normalized["event_at_moscow"]
            if not event.is_monotonic_increasing:
                raise ValueError(f"Type B {kind} events are not time ordered")
            if last_event is not None and pd.Timestamp(event.iloc[0]) < last_event:
                raise ValueError(f"Type B {kind} chunk order regressed")
            first_event = pd.Timestamp(event.iloc[0]) if first_event is None else first_event
            last_event = pd.Timestamp(event.iloc[-1])
            ids = normalized["trade_id"].dropna().astype("int64")
            if ids.duplicated().any() or trade_ids.intersection(ids.tolist()):
                raise ValueError(f"Type B {kind} trade ids are not unique")
            trade_ids.update(int(value) for value in ids.tolist())
            for column in ("option_system", "side", "event_kind", "direction"):
                if column in normalized:
                    for value, count in normalized[column].value_counts().items():
                        counts[f"{column}:{value}"] += int(count)
            _update_stream_hash(digest, normalized)
            table = pa.Table.from_pandas(normalized, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(destination, table.schema, compression="zstd")
            elif writer.schema != table.schema:
                raise ValueError(f"Type B {kind} normalized schema drifted by chunk")
            writer.write_table(table)
            rows += len(normalized)
    finally:
        if writer is not None:
            writer.close()
        process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    returncode = process.wait()
    if returncode != 0:
        raise RuntimeError(f"7z stream failed ({returncode}): {stderr.splitlines()[-1:]}")
    if rows == 0 or first_event is None or last_event is None or writer is None:
        raise ValueError(f"Type B {kind} stream is empty")
    return ParsedStream(
        rows=rows,
        first_event_at_moscow=first_event.isoformat(),
        last_event_at_moscow=last_event.isoformat(),
        normalized_stream_sha256=digest.hexdigest(),
        counts=dict(sorted(counts.items())),
        trade_ids=frozenset(trade_ids),
    )


def _prepare_nested(archive: Path, directory: Path, config: dict[str, Any]) -> dict[str, Any]:
    outer_members = _archive_members(archive)
    _validate_member_listing(
        outer_members, config["discovered_archive_identity"]["members"]
    )
    _run_7z("t", str(archive))
    _run_7z("x", "-y", f"-o{directory}", str(archive), TICK_ARCHIVE, DEAL_ARCHIVE)
    tick_archive = directory / TICK_ARCHIVE
    deal_archive = directory / DEAL_ARCHIVE
    tick_members = _archive_members(tick_archive)
    deal_members = _archive_members(deal_archive)
    expected = config["discovered_archive_identity"]
    _validate_member_listing(tick_members, {TICK_MEMBER: expected["option_tick_csv"]})
    _validate_member_listing(deal_members, {DEAL_MEMBER: expected["option_deal_csv"]})
    _run_7z("t", str(tick_archive))
    _run_7z("t", str(deal_archive))
    return {
        "outer": outer_members,
        "option_tick": tick_members,
        "option_deal": deal_members,
    }


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha_file(path),
        "rows": rows,
    }


def _replay(directory: Path, config: dict[str, Any]) -> dict[str, Any]:
    archive = directory / config["outputs"]["raw_archive"]
    with tempfile.TemporaryDirectory(prefix="trading-lab-type-b-audit-") as temporary:
        staging = Path(temporary)
        listing = _prepare_nested(archive, staging, config)
        tick = _parse_stream(
            staging / TICK_ARCHIVE,
            TICK_MEMBER,
            "tick",
            staging / "tick.parquet",
            config,
        )
        deal = _parse_stream(
            staging / DEAL_ARCHIVE,
            DEAL_MEMBER,
            "deal",
            staging / "deal.parquet",
            config,
        )
    return {"listing": listing, "tick": tick, "deal": deal}


def audit(directory: Path) -> dict[str, Any]:
    config = load_config()
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
    replay = _replay(directory, config)
    tick: ParsedStream = replay["tick"]
    deal: ParsedStream = replay["deal"]
    checks = {
        "config_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "archive_identity_exact": (
            manifest["archive_sha256"] == config["source"]["archive_sha256"]
            and manifest["archive_bytes"]
            == int(config["source"]["expected_content_length_bytes"])
        ),
        "artifacts_exact": artifacts_exact,
        "parquet_rows_exact": rows_exact,
        "nested_archive_replay_exact": replay["listing"] == manifest["archive_listing"],
        "tick_raw_replay_exact": (
            tick.rows == int(manifest["streams"]["tick"]["rows"])
            and tick.normalized_stream_sha256
            == manifest["streams"]["tick"]["normalized_stream_sha256"]
        ),
        "deal_raw_replay_exact": (
            deal.rows == int(manifest["streams"]["deal"]["rows"])
            and deal.normalized_stream_sha256
            == manifest["streams"]["deal"]["normalized_stream_sha256"]
        ),
        "trade_identity_overlap_exact": (
            len(tick.trade_ids & deal.trade_ids)
            == int(manifest["trade_identity"]["tick_deal_overlap_count"])
        ),
        "contains_no_economic_outputs": manifest["contains_signal_return_target_or_pnl"]
        is False,
        "live_trading_disabled": manifest["live_trading_allowed"] is False,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def collect(archive: Path = DEFAULT_ARCHIVE, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    config = load_config()
    archive = archive.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable Type B output exists: {output_root}")
    if (
        archive.stat().st_size != int(config["source"]["expected_content_length_bytes"])
        or _sha_file(archive) != config["source"]["archive_sha256"]
    ):
        raise ValueError("Type B raw archive identity mismatch")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.parent / f".{output_root.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        raw_path = temporary / config["outputs"]["raw_archive"]
        try:
            os.link(archive, raw_path)
        except OSError:
            shutil.copy2(archive, raw_path)
        with tempfile.TemporaryDirectory(prefix="trading-lab-type-b-build-") as work:
            staging = Path(work)
            listing = _prepare_nested(raw_path, staging, config)
            tick = _parse_stream(
                staging / TICK_ARCHIVE,
                TICK_MEMBER,
                "tick",
                temporary / config["outputs"]["option_tick_events"],
                config,
            )
            deal = _parse_stream(
                staging / DEAL_ARCHIVE,
                DEAL_MEMBER,
                "deal",
                temporary / config["outputs"]["option_deals"],
                config,
            )
        _write_json(temporary / config["outputs"]["archive_listing"], listing)
        schema_report = {
            "tick_header": TICK_HEADER,
            "deal_header": DEAL_HEADER,
            "tick": {
                "rows": tick.rows,
                "first_event_at_moscow": tick.first_event_at_moscow,
                "last_event_at_moscow": tick.last_event_at_moscow,
                "counts": tick.counts,
                "unique_trade_ids": len(tick.trade_ids),
            },
            "deal": {
                "rows": deal.rows,
                "first_event_at_moscow": deal.first_event_at_moscow,
                "last_event_at_moscow": deal.last_event_at_moscow,
                "counts": deal.counts,
                "unique_trade_ids": len(deal.trade_ids),
            },
            "tick_deal_trade_id_overlap_count": len(tick.trade_ids & deal.trade_ids),
            "contains_signal_return_target_or_pnl": False,
        }
        _write_json(temporary / config["outputs"]["schema_report"], schema_report)
        artifact_paths = [
            raw_path,
            temporary / config["outputs"]["archive_listing"],
            temporary / config["outputs"]["schema_report"],
            temporary / config["outputs"]["option_tick_events"],
            temporary / config["outputs"]["option_deals"],
        ]
        row_counts = {artifact_paths[-2].name: tick.rows, artifact_paths[-1].name: deal.rows}
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "source_trade_date": config["source"]["source_trade_date"],
            "archive_sha256": _sha_file(raw_path),
            "archive_bytes": raw_path.stat().st_size,
            "archive_listing": listing,
            "streams": {
                "tick": {
                    "rows": tick.rows,
                    "normalized_stream_sha256": tick.normalized_stream_sha256,
                },
                "deal": {
                    "rows": deal.rows,
                    "normalized_stream_sha256": deal.normalized_stream_sha256,
                },
            },
            "trade_identity": {
                "tick_unique_trade_ids": len(tick.trade_ids),
                "deal_unique_trade_ids": len(deal.trade_ids),
                "tick_deal_overlap_count": len(tick.trade_ids & deal.trade_ids),
            },
            "artifacts": [
                _artifact(path, row_counts.get(path.name)) for path in artifact_paths
            ],
            "contains_signal_return_target_or_pnl": False,
            "live_trading_allowed": False,
        }
        _write_json(temporary / config["outputs"]["manifest"], manifest)
        report = audit(temporary)
        if report["all_true"] is not True:
            raise ValueError(f"Type B source replay failed: {report['checks']}")
        _write_json(temporary / config["outputs"]["audit"], report)
        temporary.replace(output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        report = audit(args.audit_directory)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["all_true"] is not True:
            raise SystemExit(1)
        return
    print(collect(args.archive, args.output_root))


if __name__ == "__main__":
    main()
