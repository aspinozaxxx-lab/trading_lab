"""Build an immutable price-preserving, outcome-free pre-2026 stock bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
MODULE_PATH: Final[Path] = Path(__file__).resolve()
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/stock_intraday_pre2026_source_v1.yaml"
CONFIG_SHA256: Final[str] = "ba1934d6e6dd1281716a2949fe7bcc692ebfda3eaa2029e3e8c11558b82e80f5"
SOURCE_COLUMNS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
    "timestamp",
)
FORBIDDEN_COLUMNS: Final[frozenset[str]] = frozenset(
    {"return", "returns", "label", "labels", "target", "targets", "pnl", "equity"}
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved != CONFIG_PATH.resolve():
        raise ValueError("source V1 accepts only its canonical config")
    actual = sha256_file(resolved)
    if actual != CONFIG_SHA256:
        raise ValueError(f"source V1 config SHA mismatch: {actual}")
    sidecar = resolved.with_suffix(".sha256")
    declared = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if declared != actual:
        raise ValueError("source V1 sidecar SHA mismatch")
    return yaml.safe_load(resolved.read_text(encoding="utf-8-sig"))


def _parse_cutoff(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("cutoff must have an explicit timezone")
    parsed = parsed.astimezone(UTC)
    if parsed != datetime(2026, 1, 1, tzinfo=UTC):
        raise ValueError("source V1 cutoff must be exactly 2026-01-01 UTC")
    return parsed


def _source_entries(
    source_manifest: dict[str, Any], expected_tickers: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    if source_manifest.get("source") != "MOEX ISS":
        raise ValueError("unexpected source identity")
    results = source_manifest.get("results")
    if not isinstance(results, list):
        raise ValueError("source manifest results must be a list")
    entries = {str(item["ticker"]): item for item in results}
    if set(entries) != set(expected_tickers) or len(entries) != len(expected_tickers):
        raise ValueError("source ticker universe mismatch")
    return entries


def _input_path(source_root: Path, ticker: str) -> Path:
    matches = sorted(source_root.glob(f"{ticker}_TQBR_10m_*.parquet"))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one source parquet for {ticker}")
    return matches[0]


def _filtered_table(source_path: Path, cutoff: datetime) -> pa.Table:
    schema = pq.read_schema(source_path)
    if tuple(schema.names) != SOURCE_COLUMNS:
        raise ValueError(f"unexpected source schema for {source_path.name}: {schema.names}")
    table = pq.read_table(
        source_path,
        columns=list(SOURCE_COLUMNS),
        filters=[("timestamp", "<", cutoff)],
    )
    if table.num_rows == 0:
        raise ValueError(f"no pre-2026 rows in {source_path.name}")
    timestamps = table.column("timestamp")
    if pc.any(pc.greater_equal(timestamps, pa.scalar(cutoff, type=timestamps.type))).as_py():
        raise ValueError("protected timestamp escaped the Arrow filter")
    return table


def build_bundle(
    *,
    source_root: Path,
    source_manifest_path: Path,
    output_directory: Path,
    expected_tickers: tuple[str, ...],
    expected_manifest_sha256: str,
    expected_manifest_bytes: int,
    cutoff: datetime,
    row_group_size: int = 65_536,
) -> Path:
    """Copy only pre-cutoff OHLCV rows without computing any derived value."""
    source_root = source_root.resolve()
    source_manifest_path = source_manifest_path.resolve()
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"immutable output already exists: {output_directory}")
    if source_manifest_path.stat().st_size != expected_manifest_bytes:
        raise ValueError("source manifest byte count mismatch")
    if sha256_file(source_manifest_path) != expected_manifest_sha256:
        raise ValueError("source manifest SHA mismatch")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8-sig"))
    entries = _source_entries(source_manifest, expected_tickers)

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}-", dir=output_directory.parent)
    )
    artifacts: list[dict[str, Any]] = []
    try:
        for ticker in expected_tickers:
            source_path = _input_path(source_root, ticker)
            expected_source_sha = str(entries[ticker].get("sha256", ""))
            actual_source_sha = sha256_file(source_path)
            if not expected_source_sha or actual_source_sha != expected_source_sha:
                raise ValueError(f"source parquet SHA mismatch for {ticker}")
            table = _filtered_table(source_path, cutoff)
            output_path = temporary / f"{ticker}_TQBR_10m_pre2026.parquet"
            pq.write_table(
                table,
                output_path,
                compression="zstd",
                row_group_size=row_group_size,
            )
            timestamp_column = table.column("timestamp")
            artifacts.append(
                {
                    "ticker": ticker,
                    "rows": table.num_rows,
                    "minimum_timestamp": pc.min(timestamp_column).as_py().isoformat(),
                    "maximum_timestamp": pc.max(timestamp_column).as_py().isoformat(),
                    "path": output_path.name,
                    "bytes": output_path.stat().st_size,
                    "sha256": sha256_file(output_path),
                    "source_path": source_path.name,
                    "source_sha256": actual_source_sha,
                }
            )
        manifest = {
            "protocol": "stock-intraday-pre2026-source-v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_manifest_path": source_manifest_path.name,
            "source_manifest_sha256": expected_manifest_sha256,
            "cutoff_exclusive_utc": cutoff.isoformat(),
            "columns": list(SOURCE_COLUMNS),
            "contains_returns_labels_targets_or_pnl": False,
            "ticker_count": len(expected_tickers),
            "total_rows": sum(int(item["rows"]) for item in artifacts),
            "artifacts": artifacts,
            "implementation_sha256": sha256_file(MODULE_PATH),
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(output_directory)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output_directory


def audit_bundle(
    output_directory: Path,
    *,
    expected_tickers: tuple[str, ...] | None = None,
) -> dict[str, bool]:
    output_directory = output_directory.resolve()
    manifest_path = output_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    artifacts = manifest.get("artifacts", [])
    cutoff = _parse_cutoff(str(manifest["cutoff_exclusive_utc"]))
    tickers = tuple(str(item.get("ticker")) for item in artifacts)
    checks: dict[str, bool] = {
        "manifest_exists": manifest_path.is_file(),
        "protocol_exact": manifest.get("protocol") == "stock-intraday-pre2026-source-v1",
        "outcome_free_manifest": manifest.get("contains_returns_labels_targets_or_pnl") is False,
        "columns_exact": tuple(manifest.get("columns", [])) == SOURCE_COLUMNS,
        "ticker_count_exact": int(manifest.get("ticker_count", -1)) == len(artifacts),
        "ticker_universe_exact": expected_tickers is None or set(tickers) == set(expected_tickers),
        "artifact_names_unique": len({item.get("path") for item in artifacts}) == len(artifacts),
    }
    total_rows = 0
    identities = True
    schemas = True
    boundaries = True
    row_counts = True
    for item in artifacts:
        path = output_directory / str(item["path"])
        if not path.is_file():
            identities = False
            continue
        identities &= path.stat().st_size == int(item["bytes"])
        identities &= sha256_file(path) == item["sha256"]
        metadata = pq.ParquetFile(path)
        schemas &= tuple(metadata.schema_arrow.names) == SOURCE_COLUMNS
        row_counts &= metadata.metadata.num_rows == int(item["rows"])
        total_rows += metadata.metadata.num_rows
        timestamps = pq.read_table(path, columns=["timestamp"]).column("timestamp")
        boundaries &= not pc.any(
            pc.greater_equal(timestamps, pa.scalar(cutoff, type=timestamps.type))
        ).as_py()
    checks.update(
        {
            "artifact_identities_exact": bool(identities),
            "schemas_exact": bool(schemas),
            "row_counts_exact": bool(row_counts),
            "protected_boundary_exact": bool(boundaries),
            "total_rows_exact": total_rows == int(manifest.get("total_rows", -1)),
        }
    )
    return checks


def _canonical_build(config: dict[str, Any]) -> Path:
    source = config["source"]
    output = config["output"]
    boundary = config["boundary"]
    tickers = tuple(config["universe"]["tickers"])
    return build_bundle(
        source_root=PROJECT_ROOT / source["root"],
        source_manifest_path=PROJECT_ROOT / source["manifest_path"],
        output_directory=PROJECT_ROOT / output["directory"],
        expected_tickers=tickers,
        expected_manifest_sha256=str(source["manifest_sha256"]),
        expected_manifest_bytes=int(source["manifest_bytes"]),
        cutoff=_parse_cutoff(str(boundary["cutoff_exclusive_utc"])),
        row_group_size=int(output["parquet_row_group_size"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    config = load_config()
    output_directory = (PROJECT_ROOT / config["output"]["directory"]).resolve()
    if not args.audit_only:
        output_directory = _canonical_build(config)
    checks = audit_bundle(
        output_directory,
        expected_tickers=tuple(config["universe"]["tickers"]),
    )
    print(json.dumps({"output": str(output_directory), "checks": checks}, indent=2))
    if not all(checks.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
