"""Authoritative local build runner dlya sealed futures-v8 assembly."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures_v8.assembly import (
    V8_ASSEMBLY_SCHEMA_VERSION,
    V8_CAUSAL_V7_KEYS,
    V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES,
    V8_PROTECTED_HOLDOUT_START,
    V8AssemblyArtifactPaths,
    V8SourceFileProof,
    V8VerifiedSourceProvenance,
    assemble_v8_from_v7_npz,
    assert_v8_pre_io_date_range,
    persist_v8_assembly,
    verify_v8_source_provenance,
)

# Zapechatannyi relative path authoritative v7 top manifesta.
V8_AUTHORITATIVE_TOP_MANIFEST_RELATIVE_PATH: Final[Path] = Path(
    "processed/futures_v7/manifest_c41c641ef1d54d1e.json"
)
# Zapechatannyi byte SHA-256 authoritative v7 top manifesta.
V8_AUTHORITATIVE_TOP_MANIFEST_SHA256: Final[str] = (
    "4c75ac0df3c06b45ec4ac210f0126488d1796c4ddd6ec72e3bdeeea14aa99dad"
)
# Edinstvennye stolbcy, razreshennye dlya all-contract v8 target assembly.
V8_ALL_CONTRACT_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "end_timestamp",
    "asset_code",
    "logical_symbol",
    "canonical_contract_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
# Exact NPZ schema persisted v8 assembly bez legacy supervised targetov.
V8_PERSISTED_ARRAY_KEYS: Final[tuple[str, ...]] = (
    *V8_CAUSAL_V7_KEYS,
    "target_raw",
    "target_normalized",
    "target_valid",
    "target_ex_ante_daily_volatility_20",
    "target_entry_window_open_times",
    "target_entry_window_close_times",
    "target_exit_window_open_times",
    "target_exit_window_close_times",
    "target_availability_times",
    "target_entry_contract_ids",
    "target_exit_contract_ids",
    "target_entry_capacity_open_times",
    "target_exit_capacity_open_times",
    "target_entry_capacity_volumes",
    "target_exit_capacity_volumes",
)
# Int64 marker numpy NaT dlya persisted timestamp massivov.
V8_NAT_INT64: Final[int] = int(np.datetime64("NaT", "ns").astype(np.int64))


@dataclass(frozen=True, slots=True)
class V8BuildRequest:
    """Fiksiruet byte anchor, data root i development range odnogo builda."""

    data_root: Path
    top_manifest_path: Path = V8_AUTHORITATIVE_TOP_MANIFEST_RELATIVE_PATH
    expected_top_manifest_sha256: str = V8_AUTHORITATIVE_TOP_MANIFEST_SHA256
    source_start: date = date(2018, 1, 1)
    source_end: date = date(2025, 12, 31)


@dataclass(frozen=True, slots=True)
class V8PreparedBuildSources:
    """Hranit proverennye source proofs i razreshennye real input paths."""

    provenance: V8VerifiedSourceProvenance
    v7_npz_path: Path
    parquet_proofs: tuple[V8SourceFileProof, ...]
    active_map_proof: V8SourceFileProof
    top_manifest_payload_sha256: str


@dataclass(frozen=True, slots=True)
class V8BuildReport:
    """Vozvrashchaet exact immutable paths, hashes, shapes i counts builda."""

    arrays_path: Path
    manifest_path: Path
    arrays_sha256: str
    manifest_payload_sha256: str
    arrays_bytes: int
    manifest_bytes: int
    source_candle_rows: int
    source_active_map_rows: int
    verified_file_count: int
    intraday_shape: tuple[int, ...]
    daily_context_shape: tuple[int, ...]
    target_shape: tuple[int, ...]
    target_valid_cells: int
    target_invalid_cells: int

    def to_jsonable(self) -> dict[str, Any]:
        """Preobrazuet report v stabilnyi CLI JSON bez zapisi dopolnitel'nogo faila."""
        payload = asdict(self)
        payload["arrays_path"] = str(self.arrays_path)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


def _sha256_file(path: Path) -> str:
    """Hashiruet source ili result po exact baitam blokami."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _inside_data_root(path: Path, data_root: Path, label: str) -> tuple[Path, Path]:
    """Razreshaet path strogo vnutri data root i vozvrashchaet relative path."""
    root = data_root.resolve()
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} path vne data root: {resolved}") from error
    return resolved, relative


def _manifest_int(record: dict[str, Any], field: str, label: str) -> int:
    """Chitaet neotricatel'noe exact int pole iz source manifest record."""
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label}.{field} dolzhen byt' neotricatel'nym int")
    return value


def _manifest_sha(record: dict[str, Any], label: str) -> str:
    """Chitaet lowercase SHA-256 iz source manifest record."""
    value = record.get("sha256")
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label}.sha256 dolzhen byt' lowercase hex64")
    return value


def _proof_from_manifest_record(record: dict[str, Any], expected_kind: str) -> V8SourceFileProof:
    """Stroit typed proof tol'ko iz polnogo path/bytes/SHA/rows record."""
    if record.get("kind") != expected_kind:
        raise ValueError(f"Source record kind ne raven {expected_kind}")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"{expected_kind}.path dolzhen byt' nepustoi strokoi")
    return V8SourceFileProof(
        kind=expected_kind,
        path=Path(raw_path),
        bytes=_manifest_int(record, "bytes", expected_kind),
        sha256=_manifest_sha(record, expected_kind),
        rows=_manifest_int(record, "rows", expected_kind),
    )


def prepare_v8_build_sources(request: V8BuildRequest) -> V8PreparedBuildSources:
    """Do market-data chteniya proveriaet date guard, byte anchor i vse 222 proof."""
    assert_v8_pre_io_date_range(request.source_start, request.source_end)
    data_root = request.data_root.resolve()
    top_path, top_relative = _inside_data_root(
        request.top_manifest_path, data_root, "V7 top manifest"
    )
    if not top_path.is_file():
        raise FileNotFoundError(top_path)
    top_sha256 = _sha256_file(top_path)
    if top_sha256 != request.expected_top_manifest_sha256:
        raise ValueError("Authoritative V7 top manifest byte SHA-256 ne sovpal")
    payload = json.loads(top_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V7 top manifest dolzhen byt' JSON object")
    artifacts = payload.get("source_artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("V7 top manifest ne soderzhit source_artifacts list")
    parquet_records = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("kind") == "official_moex_10m_parquet"
    ]
    if len(parquet_records) != V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES:
        raise ValueError("Authoritative V8 build trebuet rovno 219 parquet records")
    parquet_proofs = tuple(
        _proof_from_manifest_record(record, "official_moex_10m_parquet")
        for record in parquet_records
    )
    active_records = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("kind") == "futures_v5_active_contract_map"
    ]
    if len(active_records) != 1:
        raise ValueError("V7 top manifest dolzhen imet' odin active-map record")
    active_proof = _proof_from_manifest_record(
        active_records[0], "futures_v5_active_contract_map"
    )
    arrays = payload.get("arrays")
    if not isinstance(arrays, dict) or not isinstance(arrays.get("path"), str):
        raise ValueError("V7 top manifest ne soderzhit arrays.path")
    v7_npz_path, _ = _inside_data_root(Path(arrays["path"]), data_root, "V7 causal NPZ")
    top_proof = V8SourceFileProof(
        kind="futures_v7_top_manifest",
        path=top_relative,
        bytes=top_path.stat().st_size,
        sha256=top_sha256,
    )
    provenance = V8VerifiedSourceProvenance(
        data_root=data_root,
        top_manifest=top_proof,
        all_contract_parquets=parquet_proofs,
        active_contract_map=active_proof,
    )
    verified_records, _ = verify_v8_source_provenance(
        provenance,
        v7_npz_path=v7_npz_path,
    )
    if len(verified_records) != V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES + 2:
        raise RuntimeError("Pre-I/O source verification ne vernula 221 external proofs")
    payload_sha = payload.get("manifest_payload_sha256")
    if not isinstance(payload_sha, str):
        raise ValueError("V7 top manifest ne soderzhit payload SHA-256")
    return V8PreparedBuildSources(
        provenance=provenance,
        v7_npz_path=v7_npz_path,
        parquet_proofs=parquet_proofs,
        active_map_proof=active_proof,
        top_manifest_payload_sha256=payload_sha,
    )


def _read_verified_market_frames(
    prepared: V8PreparedBuildSources,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chitaet tol'ko verified files s physical predicate strogo ran'she 2026."""
    data_root = prepared.provenance.data_root.resolve()
    timestamp_cutoff = pd.Timestamp(V8_PROTECTED_HOLDOUT_START, tz="UTC")
    frames: list[pd.DataFrame] = []
    for proof in prepared.parquet_proofs:
        parquet_path, _ = _inside_data_root(proof.path, data_root, "All-contract parquet")
        frame = pd.read_parquet(
            parquet_path,
            columns=list(V8_ALL_CONTRACT_COLUMNS),
            filters=[("timestamp", "<", timestamp_cutoff)],
            engine="pyarrow",
        )
        frames.append(frame)
    nonempty_frames = [frame for frame in frames if not frame.empty]
    if not nonempty_frames:
        raise ValueError("Verified all-contract source ne soderzhit ni odnoi stroki")
    candles = pd.concat(nonempty_frames, ignore_index=True)
    expected_candle_rows = sum(int(proof.rows) for proof in prepared.parquet_proofs)
    if len(candles) != expected_candle_rows:
        raise ValueError(
            "Predicate <2026 row sum ne sovpal s authoritative parquet row sum"
        )
    timestamps = pd.to_datetime(candles["timestamp"], errors="raise", utc=True)
    end_timestamps = pd.to_datetime(candles["end_timestamp"], errors="raise", utc=True)
    if timestamps.ge(timestamp_cutoff).any() or end_timestamps.ge(timestamp_cutoff).any():
        raise ValueError("All-contract frame prochital protected 2026 timestamp")
    active_path, _ = _inside_data_root(
        prepared.active_map_proof.path, data_root, "Active-map parquet"
    )
    active_map = pd.read_parquet(
        active_path,
        filters=[("effective_date", "<", pd.Timestamp(V8_PROTECTED_HOLDOUT_START))],
        engine="pyarrow",
    )
    if prepared.active_map_proof.rows is None or len(active_map) != int(
        prepared.active_map_proof.rows
    ):
        raise ValueError("Predicate <2026 active-map row sum ne sovpal s proof")
    effective_dates = pd.to_datetime(active_map["effective_date"], errors="raise")
    if effective_dates.ge(pd.Timestamp(V8_PROTECTED_HOLDOUT_START)).any():
        raise ValueError("Active-map frame prochital protected 2026 date")
    return candles, active_map


def _validate_timestamp_int_array(values: np.ndarray, label: str) -> None:
    """Zapreshchaet persisted timestamp na ili posle protected 2026 boundary."""
    integers = np.asarray(values)
    if integers.dtype.kind not in {"i", "u"}:
        raise ValueError(f"{label} dolzhen byt' persisted integer timestamp array")
    cutoff = np.datetime64(V8_PROTECTED_HOLDOUT_START, "ns").astype(np.int64)
    factual = integers[integers != V8_NAT_INT64]
    if factual.size and (factual >= cutoff).any():
        raise ValueError(f"{label} soderzhit protected 2026 timestamp")


def verify_persisted_v8_build(
    artifacts: V8AssemblyArtifactPaths,
    *,
    data_root: Path,
) -> dict[str, Any]:
    """Povtorno otkryvaet immutable NPZ/manifest i fail-closed proveriaet schema/audit."""
    root = data_root.resolve()
    arrays_path, arrays_relative = _inside_data_root(artifacts.arrays_path, root, "V8 arrays")
    manifest_path, _ = _inside_data_root(artifacts.manifest_path, root, "V8 manifest")
    if _sha256_file(arrays_path) != artifacts.arrays_sha256:
        raise ValueError("Persisted V8 arrays SHA-256 ne sovpal")
    manifest_bytes = manifest_path.read_bytes()
    if not manifest_bytes.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Persisted V8 manifest ne imeet UTF-8 BOM")
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    claimed_manifest_sha = manifest.get("manifest_payload_sha256")
    manifest_without_hash = dict(manifest)
    manifest_without_hash.pop("manifest_payload_sha256", None)
    calculated_manifest_sha = hashlib.sha256(
        json.dumps(
            manifest_without_hash,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if claimed_manifest_sha != calculated_manifest_sha:
        raise ValueError("Persisted V8 manifest payload SHA-256 ne sovpal")
    if manifest_path.name != f"manifest_{calculated_manifest_sha[:16]}.json":
        raise ValueError("Persisted V8 manifest filename ne content-addressed")
    arrays_record = manifest.get("arrays", {})
    if arrays_record.get("path") != arrays_relative.as_posix():
        raise ValueError("Persisted V8 arrays relative path ne sovpal s manifest")
    if arrays_record.get("bytes") != arrays_path.stat().st_size:
        raise ValueError("Persisted V8 arrays bytes ne sovpali s manifest")
    if arrays_record.get("sha256") != artifacts.arrays_sha256:
        raise ValueError("Persisted V8 arrays manifest SHA-256 ne sovpal")
    if manifest.get("schema_version") != V8_ASSEMBLY_SCHEMA_VERSION:
        raise ValueError("Persisted V8 manifest schema_version ne sovpal")
    if manifest.get("research_status") != "assembly_only_no_train_no_pnl_no_holdout_access":
        raise ValueError("Persisted V8 manifest research_status narushen")
    provenance = manifest.get("source_provenance", {})
    expected_verified_files = V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES + 3
    if provenance.get("status") != "cryptographically_verified_real_sources" or (
        provenance.get("verified_file_count") != expected_verified_files
    ):
        raise ValueError("Persisted V8 manifest ne dokazyvaet 222 verified files")
    source_artifacts = manifest.get("source_artifacts")
    source_hashes = manifest.get("source_hashes")
    if not isinstance(source_artifacts, list) or not isinstance(source_hashes, dict):
        raise ValueError("Persisted V8 manifest source provenance schema narushena")
    artifact_ids = [artifact.get("id") for artifact in source_artifacts]
    if any(not isinstance(artifact_id, str) for artifact_id in artifact_ids) or len(
        artifact_ids
    ) != len(set(artifact_ids)):
        raise ValueError("Persisted V8 source artifact ids ne unikal'ny")
    if set(source_hashes) != set(artifact_ids):
        raise ValueError("Persisted V8 source_hashes ne sovpali s artifact ids")
    with np.load(arrays_path, allow_pickle=False) as archive:
        if set(archive.files) != set(V8_PERSISTED_ARRAY_KEYS):
            raise ValueError("Persisted V8 NPZ key schema ne sovpala")
        intraday_shape = tuple(archive["intraday"].shape)
        daily_shape = tuple(archive["daily_context"].shape)
        target_shape = tuple(archive["target_normalized"].shape)
        if len(intraday_shape) != 4 or intraday_shape[1:] != (4, 512, 12):
            raise ValueError("Persisted V8 intraday shape ne [samples,4,512,12]")
        samples = intraday_shape[0]
        if daily_shape != (samples, 4, 16) or target_shape != (samples, 4):
            raise ValueError("Persisted V8 daily ili target shape ne sovpala")
        expected_shapes = {
            "intraday_valid": (samples, 4, 512),
            "daily_valid": (samples, 4, 16),
            "asset_valid": (samples, 4),
            "log_price": (samples, 4, 512),
            "bar_times": (samples, 512),
            "sample_trade_dates": (samples,),
            "decision_times": (samples,),
        }
        for key, expected_shape in expected_shapes.items():
            if archive[key].shape != expected_shape:
                raise ValueError(f"Persisted V8 {key} shape ne sovpala")
        for key in V8_PERSISTED_ARRAY_KEYS:
            if key.startswith("target_") and archive[key].shape != target_shape:
                raise ValueError(f"Persisted V8 {key} target shape ne sovpala")
            if archive[key].dtype.kind == "O":
                raise ValueError(f"Persisted V8 {key} ne mozhet imet' object dtype")
        for key in (
            "bar_times",
            "sample_trade_dates",
            "decision_times",
            "target_entry_window_open_times",
            "target_entry_window_close_times",
            "target_exit_window_open_times",
            "target_exit_window_close_times",
            "target_availability_times",
            "target_entry_capacity_open_times",
            "target_exit_capacity_open_times",
        ):
            _validate_timestamp_int_array(archive[key], key)
        target_valid = np.asarray(archive["target_valid"], dtype=bool)
        normalized = np.asarray(archive["target_normalized"], dtype=np.float64)
        if not np.isfinite(normalized[target_valid]).all() or normalized[~target_valid].any():
            raise ValueError("Persisted V8 target values narushili valid mask")
        target_valid_cells = int(target_valid.sum())
    target_audit = manifest.get("audit", {}).get("target", {})
    if target_audit.get("target_valid_cells") != target_valid_cells:
        raise ValueError("Persisted V8 target valid count ne sovpal s audit")
    return {
        "manifest": manifest,
        "manifest_payload_sha256": calculated_manifest_sha,
        "intraday_shape": intraday_shape,
        "daily_context_shape": daily_shape,
        "target_shape": target_shape,
        "target_valid_cells": target_valid_cells,
    }


def run_authoritative_v8_build(request: V8BuildRequest) -> V8BuildReport:
    """Vypolnyaet verify-read-assemble-persist-reload bez train, PnL ili 2026."""
    assert_v8_pre_io_date_range(request.source_start, request.source_end)
    prepared = prepare_v8_build_sources(request)
    candles, active_map = _read_verified_market_frames(prepared)
    result = assemble_v8_from_v7_npz(
        prepared.v7_npz_path,
        candles,
        active_map,
        source_start=request.source_start,
        source_end=request.source_end,
        source_provenance=prepared.provenance,
    )
    artifacts = persist_v8_assembly(result, request.data_root)
    verified = verify_persisted_v8_build(artifacts, data_root=request.data_root)
    manifest = verified["manifest"]
    target_valid_cells = int(verified["target_valid_cells"])
    target_shape = tuple(verified["target_shape"])
    return V8BuildReport(
        arrays_path=artifacts.arrays_path,
        manifest_path=artifacts.manifest_path,
        arrays_sha256=artifacts.arrays_sha256,
        manifest_payload_sha256=str(verified["manifest_payload_sha256"]),
        arrays_bytes=artifacts.arrays_path.stat().st_size,
        manifest_bytes=artifacts.manifest_path.stat().st_size,
        source_candle_rows=len(candles),
        source_active_map_rows=len(active_map),
        verified_file_count=int(manifest["source_provenance"]["verified_file_count"]),
        intraday_shape=tuple(verified["intraday_shape"]),
        daily_context_shape=tuple(verified["daily_context_shape"]),
        target_shape=target_shape,
        target_valid_cells=target_valid_cells,
        target_invalid_cells=int(np.prod(target_shape, dtype=np.int64)) - target_valid_cells,
    )


def _parser() -> argparse.ArgumentParser:
    """Stroit uzkii CLI tol'ko dlya local authoritative assembly builda."""
    parser = argparse.ArgumentParser(description="Build sealed futures-v8 assembly only")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--top-manifest",
        type=Path,
        default=V8_AUTHORITATIVE_TOP_MANIFEST_RELATIVE_PATH,
    )
    parser.add_argument(
        "--expected-top-sha256",
        default=V8_AUTHORITATIVE_TOP_MANIFEST_SHA256,
    )
    parser.add_argument("--source-start", type=date.fromisoformat, default=date(2018, 1, 1))
    parser.add_argument("--source-end", type=date.fromisoformat, default=date(2025, 12, 31))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Zapuskaet build i pechataet mashinochitaemyi report v stdout."""
    arguments = _parser().parse_args(argv)
    report = run_authoritative_v8_build(
        V8BuildRequest(
            data_root=arguments.data_root,
            top_manifest_path=arguments.top_manifest,
            expected_top_manifest_sha256=arguments.expected_top_sha256,
            source_start=arguments.source_start,
            source_end=arguments.source_end,
        )
    )
    print(json.dumps(report.to_jsonable(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "V8_ALL_CONTRACT_COLUMNS",
    "V8_AUTHORITATIVE_TOP_MANIFEST_RELATIVE_PATH",
    "V8_AUTHORITATIVE_TOP_MANIFEST_SHA256",
    "V8_PERSISTED_ARRAY_KEYS",
    "V8BuildReport",
    "V8BuildRequest",
    "V8PreparedBuildSources",
    "main",
    "prepare_v8_build_sources",
    "run_authoritative_v8_build",
    "verify_persisted_v8_build",
]
