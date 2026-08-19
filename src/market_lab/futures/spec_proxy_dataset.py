"""Sborka immutable causal spec-proxy tolko iz proverennogo futures v5 raw-kesha."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_lab.futures.market_data import parse_futures_daily_payload
from market_lab.futures.spec_proxy import (
    PROTECTED_HOLDOUT_START,
    SPEC_PROXY_VERSION,
    build_causal_spec_proxy,
)
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import write_json

# Neizmenyaemaya versiya derived dataset, otdelnaya ot source futures_v5.
SPEC_PROXY_DATASET_VERSION = "futures_v5_specs_v1"
# Reviziya builder-semantiki, uchastvuyushchaya v content fingerprint.
SPEC_PROXY_BUILDER_REVISION = "1.0.2"
# Read-only katalog proverennoi source-vyborki.
SOURCE_DATASET_RELATIVE = Path("processed/futures_v5")
# Edinstvennyi katalog novyh derived artefaktov.
OUTPUT_DATASET_RELATIVE = Path("processed/futures_v5_specs_v1")
# Stabilnoe imya manifesta source-vyborki odnogo asset.
SOURCE_MANIFEST_TEMPLATE = "manifest_{start}_{end}.json"
# Alias logical symbol, asset code i contract prefix v odin logical asset.
ASSET_INPUT_ALIASES = {
    "SI": "SI",
    "RI": "RI",
    "RTS": "RI",
    "BR": "BR",
    "MIX": "MIX",
    "MX": "MIX",
}
# Minimal'nye factual polya pered causal spec-proxy bez returns ili targetov.
DAILY_PROXY_COLUMNS = (
    "session_date",
    "contract_id",
    "asset_symbol",
    "value",
    "volume",
    "waprice",
    "settle",
    "open_interest",
    "open_interest_value",
)


@dataclass(frozen=True, slots=True)
class FuturesSpecProxyDatasetResult:
    """Vozvrashchaet puti i razmery odnogo immutable derived dataset."""

    dataset_directory: Path
    parquet_path: Path
    manifest_path: Path
    rows: int
    sessions: int
    contracts: int
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class _LoadedAssetDaily:
    """Hranit proverennye daily-stroki i audit-provenance odnogo asset."""

    frame: pd.DataFrame
    manifest_record: dict[str, Any]
    raw_records: tuple[dict[str, Any], ...]
    segment_count: int
    canonical_contract_count: int


def _validate_period_before_io(start_date: date, end_date: date) -> None:
    """Blokiruet nekorrektnyi interval i holdout do lyuboi operacii s failami."""
    if end_date < start_date:
        raise ValueError("end_date ran'she start_date")
    if end_date >= PROTECTED_HOLDOUT_START:
        raise ValueError(
            f"Zapreshchen I/O futures holdout s {PROTECTED_HOLDOUT_START.isoformat()}"
        )


def _normalize_assets(values: tuple[str, ...] | list[str]) -> tuple[FuturesAssetSpec, ...]:
    """Normalizuet logical/ISS aliases i zapreshchaet duplicate asset."""
    if not values:
        raise ValueError("Nuzhen hotya by odin futures asset")
    symbols: list[str] = []
    for value in values:
        alias = str(value).strip().upper()
        if alias not in ASSET_INPUT_ALIASES:
            raise ValueError(f"Neizvestnyi futures asset: {value!r}")
        symbols.append(ASSET_INPUT_ALIASES[alias])
    if len(symbols) != len(set(symbols)):
        raise ValueError("Futures assets ne dolzhny povtoryat'sya cherez aliases")
    return tuple(FuturesAssetSpec.from_symbol(symbol) for symbol in sorted(symbols))


def _bounded_existing_file(data_root: Path, relative_path: object) -> Path:
    """Razreshaet symlinks i trebuet sushchestvuyushchii fail strogo pod data root."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("Manifest soderzhit pustoi artifact path")
    candidate_relative = Path(relative_path)
    if candidate_relative.is_absolute() or candidate_relative.drive:
        raise ValueError("Artifact path dolzhen byt' otnositel'nym")
    try:
        candidate = data_root.joinpath(candidate_relative).resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"Artifact ne naiden: {relative_path}") from error
    try:
        candidate.relative_to(data_root)
    except ValueError as error:
        raise ValueError(f"Artifact path vyshel iz data root: {relative_path}") from error
    if not candidate.is_file():
        raise ValueError(f"Artifact path ne yavlyaetsya failom: {relative_path}")
    return candidate


def _relative_to_root(path: Path, data_root: Path) -> str:
    """Vozvrashchaet stabilnyi POSIX-put artefakta otnositel'no data root."""
    return path.relative_to(data_root).as_posix()


def _sha256_bytes(content: bytes) -> str:
    """Schitaet SHA-256 tochnyh baitov source ili output artefakta."""
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    """Schitaet SHA-256 bolshogo output faila potokovo."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _required_nonnegative_int(payload: dict[str, Any], name: str, label: str) -> int:
    """Chitaet obyazatel'noe celoe schetnoe pole bez bool-coercion."""
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}.{name} dolzhen byt' nonnegative int")
    return value


def _required_string(payload: dict[str, Any], name: str, label: str) -> str:
    """Chitaet obyazatel'nuyu ne-pustuyu stroku manifesta."""
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label}.{name} dolzhen byt' stabil'noi strokoi")
    return value


def _parse_manifest_bytes(content: bytes, path: Path) -> dict[str, Any]:
    """Dekodiruet source manifest tolko posle polnogo chteniya ego baitov."""
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Nekorrektnyi source manifest: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError("Source manifest dolzhen byt' JSON-obektom")
    return payload


def _validate_manifest_identity(
    payload: dict[str, Any],
    expected_asset: FuturesAssetSpec,
    start_date: date,
    end_date: date,
) -> None:
    """Sveryaet versiyu, asset i development period do chteniya raw payload."""
    if payload.get("schema_version") != 1:
        raise ValueError("Neizvestnaya schema source futures_v5 manifesta")
    if payload.get("requested_start") != start_date.isoformat():
        raise ValueError("Source manifest requested_start ne sovpadaet")
    manifest_end = payload.get("requested_end")
    if manifest_end != end_date.isoformat():
        raise ValueError("Source manifest requested_end ne sovpadaet")
    if date.fromisoformat(str(manifest_end)) >= PROTECTED_HOLDOUT_START:
        raise ValueError("Source manifest ssylayetsya na zashchishchennyi holdout")
    if payload.get("protected_from") != PROTECTED_HOLDOUT_START.isoformat():
        raise ValueError("Source manifest ne fiksiruet pravil'nuyu holdout-granicu")
    asset_payload = payload.get("asset")
    if not isinstance(asset_payload, dict):
        raise ValueError("Source manifest ne soderzhit asset-obekt")
    try:
        manifest_asset = FuturesAssetSpec(**asset_payload)
    except (TypeError, ValueError) as error:
        raise ValueError("Source manifest soderzhit nekorrektnyi asset") from error
    if manifest_asset != expected_asset:
        raise ValueError("Source manifest asset ne sootvetstvuet zaproshennomu")


def _verified_raw_bytes(
    data_root: Path,
    artifact: dict[str, Any],
) -> tuple[Path, bytes, int, int, str]:
    """Proveryaet path, bytes i SHA compressed raw do JSON/gzip payload parsing."""
    label = "segment.daily.raw"
    raw_path = _bounded_existing_file(data_root, artifact.get("path"))
    if raw_path.suffixes[-2:] != [".json", ".gz"]:
        raise ValueError("Daily raw artifact dolzhen imet' suffix .json.gz")
    expected_rows = _required_nonnegative_int(artifact, "rows", label)
    expected_pages = _required_nonnegative_int(artifact, "pages", label)
    expected_bytes = _required_nonnegative_int(artifact, "bytes", label)
    expected_sha = _required_string(artifact, "sha256", label).lower()
    if len(expected_sha) != 64 or any(symbol not in "0123456789abcdef" for symbol in expected_sha):
        raise ValueError("Daily raw sha256 nekorrektnyi")
    if raw_path.stat().st_size != expected_bytes:
        raise ValueError("Daily raw bytes ne sovpadayut s manifestom")
    compressed = raw_path.read_bytes()
    if len(compressed) != expected_bytes:
        raise ValueError("Daily raw bytes izmenilis' vo vremya chteniya")
    actual_sha = _sha256_bytes(compressed)
    if actual_sha != expected_sha:
        raise ValueError("Daily raw SHA-256 ne sovpadaet s manifestom")
    return raw_path, compressed, expected_rows, expected_pages, actual_sha


def _decode_raw_archive(compressed: bytes, raw_path: Path) -> list[dict[str, Any]]:
    """Raspakovyvaet uzhe proverennyi gzip i vozvrashchaet ISS request-obekty."""
    try:
        payload = json.loads(gzip.decompress(compressed).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Nekorrektnyi proverennyi raw archive: {raw_path}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("requests"), list):
        raise ValueError("Daily raw archive ne soderzhit requests-list")
    requests_payload = payload["requests"]
    if any(not isinstance(item, dict) for item in requests_payload):
        raise ValueError("Daily raw request dolzhen byt' JSON-obektom")
    return requests_payload


def _parse_segment_pages(
    requests_payload: list[dict[str, Any]],
    asset: FuturesAssetSpec,
    secid: str,
    board_id: str,
    segment_start: date,
    segment_end: date,
    expected_rows: int,
    expected_pages: int,
) -> pd.DataFrame:
    """Parserit kazhduyu ISS-stranitsu i dokazyvaet cursor/poryadok/pokrytie."""
    if len(requests_payload) != expected_pages or expected_pages <= 0:
        raise ValueError("Daily raw pages ne sovpadayut s manifestom")
    frames: list[pd.DataFrame] = []
    expected_index = 0
    expected_total: int | None = None
    previous_date: pd.Timestamp | None = None
    final_next_index: int | None = 0
    for page_number, request in enumerate(requests_payload, start=1):
        page_payload = request.get("payload")
        if not isinstance(page_payload, dict):
            raise ValueError(f"Daily raw page {page_number} ne soderzhit payload-obekt")
        frame, cursor = parse_futures_daily_payload(
            page_payload,
            asset,
            expected_secid=secid,
        )
        if cursor.index != expected_index:
            raise ValueError("Daily raw cursor.index narushaet pagination")
        if expected_total is None:
            expected_total = cursor.total
        elif cursor.total != expected_total:
            raise ValueError("Daily raw cursor.total izmenilsya mezhdu stranicami")
        expected_page_rows = min(cursor.page_size, max(cursor.total - cursor.index, 0))
        if len(frame) != expected_page_rows:
            raise ValueError("Daily raw page usechena otnositel'no cursor")
        if not frame.empty:
            if (frame["board_id"] != board_id).any():
                raise ValueError("Daily raw page soderzhit drugoi board_id")
            dates = frame["trade_date"].dt.date
            if dates.lt(segment_start).any() or dates.gt(segment_end).any():
                raise ValueError("Daily raw page vyshel za requested segment period")
            if dates.ge(PROTECTED_HOLDOUT_START).any():
                raise ValueError("Daily raw page soderzhit zashchishchennyi holdout")
            if previous_date is not None and frame["trade_date"].iloc[0] <= previous_date:
                raise ValueError("Daily raw pages ne yavlyayutsya strogo hronologicheskimi")
            previous_date = frame["trade_date"].iloc[-1]
            frames.append(frame)
        final_next_index = cursor.next_index
        if page_number < len(requests_payload):
            if final_next_index is None:
                raise ValueError("Daily raw archive soderzhit stranicu posle cursor.total")
            expected_index = final_next_index
    if final_next_index is not None:
        raise ValueError("Daily raw archive oborvan do cursor.total")
    expected_total = expected_total or 0
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != expected_rows or len(combined) != expected_total:
        raise ValueError("Daily raw row count ne sovpadaet s manifestom/cursor.total")
    if combined.empty:
        raise ValueError("Daily raw segment pust")
    if combined.duplicated(["trade_date", "secid", "board_id"]).any():
        raise ValueError("Daily raw segment soderzhit duplicate rows")
    return combined


def _load_asset_daily(
    data_root: Path,
    asset: FuturesAssetSpec,
    start_date: date,
    end_date: date,
) -> _LoadedAssetDaily:
    """Chitaet odin source manifest i vse ego daily raw artefakty fail-closed."""
    manifest_name = SOURCE_MANIFEST_TEMPLATE.format(
        start=start_date.isoformat(), end=end_date.isoformat()
    )
    manifest_relative = SOURCE_DATASET_RELATIVE / asset.asset_code / manifest_name
    manifest_path = _bounded_existing_file(data_root, manifest_relative.as_posix())
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest = _parse_manifest_bytes(manifest_bytes, manifest_path)
    _validate_manifest_identity(manifest, asset, start_date, end_date)
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("Source manifest ne soderzhit counts-obekt")
    expected_daily_rows = _required_nonnegative_int(counts, "daily_rows", "counts")
    expected_segments = _required_nonnegative_int(counts, "board_segments", "counts")
    segments = manifest.get("segment_artifacts")
    if not isinstance(segments, list) or len(segments) != expected_segments:
        raise ValueError("Source manifest segment_artifacts ne sovpadaet s counts")
    frames: list[pd.DataFrame] = []
    raw_records: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    canonical_contracts: set[str] = set()
    for segment_number, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError("Source segment artifact dolzhen byt' obektom")
        label = f"segment_artifacts[{segment_number}]"
        canonical_segment_id = _required_string(segment, "canonical_segment_id", label)
        canonical_contract_id = _required_string(segment, "canonical_contract_id", label)
        secid = _required_string(segment, "secid", label)
        board_id = _required_string(segment, "boardid", label)
        if not canonical_contract_id.startswith(f"{asset.asset_code}:"):
            raise ValueError("canonical_contract_id ne sootvetstvuet asset_code")
        try:
            segment_start = date.fromisoformat(_required_string(segment, "requested_start", label))
            segment_end = date.fromisoformat(_required_string(segment, "requested_end", label))
        except ValueError as error:
            raise ValueError("Source segment soderzhit nekorrektnye ISO-daty") from error
        if segment_end < segment_start:
            raise ValueError("Source segment end ran'she start")
        if segment_start < start_date or segment_end > end_date:
            raise ValueError("Source segment vyshel za requested dataset period")
        if segment_end >= PROTECTED_HOLDOUT_START:
            raise ValueError("Source segment ssylayetsya na zashchishchennyi holdout")
        daily = segment.get("daily")
        if not isinstance(daily, dict) or not isinstance(daily.get("raw"), dict):
            raise ValueError("Source segment ne soderzhit daily.raw artifact")
        raw_path, compressed, raw_rows, raw_pages, raw_sha = _verified_raw_bytes(
            data_root,
            daily["raw"],
        )
        if raw_path in seen_paths:
            raise ValueError("Odin daily raw artifact ukazan bolee odnogo raza")
        seen_paths.add(raw_path)
        requests_payload = _decode_raw_archive(compressed, raw_path)
        parsed = _parse_segment_pages(
            requests_payload,
            asset,
            secid,
            board_id,
            segment_start,
            segment_end,
            raw_rows,
            raw_pages,
        )
        parsed = parsed.assign(
            session_date=parsed["trade_date"],
            contract_id=canonical_contract_id,
            asset_symbol=asset.logical_symbol,
        )
        frames.append(parsed.loc[:, DAILY_PROXY_COLUMNS])
        canonical_contracts.add(canonical_contract_id)
        raw_records.append(
            {
                "canonical_segment_id": canonical_segment_id,
                "canonical_contract_id": canonical_contract_id,
                "storage_secid": secid,
                "board_id": board_id,
                "path": _relative_to_root(raw_path, data_root),
                "bytes": len(compressed),
                "sha256": raw_sha,
                "pages": raw_pages,
                "rows": len(parsed),
            }
        )
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != expected_daily_rows:
        raise ValueError("Asset daily rows ne sovpadayut s source manifest counts")
    if combined.duplicated(["session_date", "contract_id"]).any():
        raise ValueError("Canonical contract/session povtoryaetsya mezhdu storage aliases")
    manifest_record = {
        "asset_code": asset.asset_code,
        "logical_symbol": asset.logical_symbol,
        "path": _relative_to_root(manifest_path, data_root),
        "bytes": len(manifest_bytes),
        "sha256": manifest_sha,
        "daily_rows": expected_daily_rows,
        "segments": expected_segments,
    }
    return _LoadedAssetDaily(
        frame=combined,
        manifest_record=manifest_record,
        raw_records=tuple(raw_records),
        segment_count=expected_segments,
        canonical_contract_count=len(canonical_contracts),
    )


def _source_fingerprint(
    start_date: date,
    end_date: date,
    manifests: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
) -> str:
    """Stroit content fingerprint vseh source-hash i zamorozhennoi proxy-versii."""
    payload = {
        "dataset_version": SPEC_PROXY_DATASET_VERSION,
        "builder_revision": SPEC_PROXY_BUILDER_REVISION,
        "spec_proxy_version": SPEC_PROXY_VERSION,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "source_manifests": [
            {"path": item["path"], "sha256": item["sha256"]}
            for item in sorted(manifests, key=lambda record: record["path"])
        ],
        "source_raw": [
            {"path": item["path"], "sha256": item["sha256"]}
            for item in sorted(raw_records, key=lambda record: record["path"])
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _cleanup_temporary_directory(path: Path, output_root: Path) -> None:
    """Udaliaet tolko izvestnyi temp-katalog posle proverki ego output-granicy."""
    try:
        path.relative_to(output_root)
    except ValueError as error:
        raise RuntimeError("Temporary output vyshel iz output root") from error
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink()
        else:
            raise RuntimeError("Neozhidannyi vlozhennyi katalog v temporary output")
    path.rmdir()


def _write_immutable_dataset(
    data_root: Path,
    proxy: pd.DataFrame,
    start_date: date,
    end_date: date,
    source_fingerprint: str,
    source_manifests: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    quality: dict[str, Any],
) -> FuturesSpecProxyDatasetResult:
    """Atomarno publikuet novyi content-addressed katalog bez overwrite."""
    output_root = data_root.joinpath(OUTPUT_DATASET_RELATIVE).resolve()
    try:
        output_root.relative_to(data_root)
    except ValueError as error:
        raise ValueError("Spec-proxy output vyshel iz data root") from error
    output_name = (
        f"spec_proxy_{start_date.isoformat()}_{end_date.isoformat()}_"
        f"{source_fingerprint[:16]}"
    )
    final_directory = output_root / output_name
    if final_directory.exists():
        raise FileExistsError(f"Immutable spec-proxy dataset uzhe sushchestvuet: {final_directory}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_name}.", dir=output_root)).resolve()
    try:
        temporary.relative_to(output_root)
        temporary_parquet = temporary / "spec_proxy.parquet"
        proxy.to_parquet(temporary_parquet, index=False, compression="zstd")
        parquet_sha = _sha256_file(temporary_parquet)
        manifest_payload = {
            "schema_version": 1,
            "dataset_version": SPEC_PROXY_DATASET_VERSION,
            "builder_revision": SPEC_PROXY_BUILDER_REVISION,
            "spec_proxy_version": SPEC_PROXY_VERSION,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
            "protected_from": PROTECTED_HOLDOUT_START.isoformat(),
            "source_fingerprint": source_fingerprint,
            "source_manifests": source_manifests,
            "source_raw_daily": raw_records,
            "counts": {
                "source_manifests": len(source_manifests),
                "source_raw_artifacts": len(raw_records),
                "rows": len(proxy),
                "sessions": int(proxy["session_date"].nunique()),
                "contracts": int(proxy["contract_id"].nunique()),
                "assets": int(proxy["asset_symbol"].nunique()),
            },
            "quality": quality,
            "output": {
                "parquet": {
                    "path": (
                        OUTPUT_DATASET_RELATIVE / output_name / "spec_proxy.parquet"
                    ).as_posix(),
                    "rows": len(proxy),
                    "bytes": temporary_parquet.stat().st_size,
                    "sha256": parquet_sha,
                }
            },
        }
        write_json(temporary / "manifest.json", manifest_payload)
        os.rename(temporary, final_directory)
    except Exception:
        _cleanup_temporary_directory(temporary, output_root)
        raise
    return FuturesSpecProxyDatasetResult(
        dataset_directory=final_directory,
        parquet_path=final_directory / "spec_proxy.parquet",
        manifest_path=final_directory / "manifest.json",
        rows=len(proxy),
        sessions=int(proxy["session_date"].nunique()),
        contracts=int(proxy["contract_id"].nunique()),
        source_fingerprint=source_fingerprint,
    )


def build_futures_spec_proxy_dataset(
    data_root: Path,
    start_date: date,
    end_date: date,
    assets: tuple[str, ...] | list[str] = ("SI", "RI", "BR", "MIX"),
) -> FuturesSpecProxyDatasetResult:
    """Proveryaet futures_v5 raw i publikuet causal spec-proxy bez PnL/returns."""
    _validate_period_before_io(start_date, end_date)
    normalized_assets = _normalize_assets(assets)
    try:
        resolved_data_root = Path(data_root).resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"Data root ne sushchestvuet: {data_root}") from error
    if not resolved_data_root.is_dir():
        raise ValueError("Data root dolzhen byt' katalogom")
    loaded = [
        _load_asset_daily(resolved_data_root, asset, start_date, end_date)
        for asset in normalized_assets
    ]
    daily = pd.concat([item.frame for item in loaded], ignore_index=True)
    if daily.empty:
        raise ValueError("Proverennyi futures daily dataset pust")
    factual_calendar = pd.DatetimeIndex(
        pd.to_datetime(daily["session_date"], errors="raise")
        .drop_duplicates()
        .sort_values(ignore_index=True)
    )
    proxy = build_causal_spec_proxy(daily, factual_calendar)
    source_manifests = [item.manifest_record for item in loaded]
    raw_records = [record for item in loaded for record in item.raw_records]
    source_fingerprint = _source_fingerprint(
        start_date,
        end_date,
        source_manifests,
        raw_records,
    )
    total_segments = sum(item.segment_count for item in loaded)
    canonical_contracts = sum(item.canonical_contract_count for item in loaded)
    waprice_numeric = pd.to_numeric(daily["waprice"], errors="coerce")
    waprice_usable = waprice_numeric.notna() & waprice_numeric.gt(0.0)
    waprice_zero = waprice_numeric.eq(0.0)
    waprice_unusable_by_asset = {
        str(asset): int(waprice_zero.loc[index].sum())
        for asset, index in daily.groupby("asset_symbol", sort=True).groups.items()
    }
    primary_status = proxy["realized_accounting_status"].eq(
        "available_primary_after_session"
    )
    fallback_status = proxy["realized_accounting_status"].eq(
        "available_fallback_after_session"
    )
    unusable_status = proxy["realized_accounting_status"].eq(
        "invalid_primary_and_fallback"
    )
    realized_status_by_asset = {
        str(asset): {
            "primary": int(primary_status.loc[index].sum()),
            "fallback": int(fallback_status.loc[index].sum()),
            "unusable": int(unusable_status.loc[index].sum()),
        }
        for asset, index in proxy.groupby("asset_symbol", sort=True).groups.items()
    }
    primary_proxy = pd.to_numeric(
        proxy["primary_trade_accounting_point_value"], errors="coerce"
    )
    fallback_proxy = pd.to_numeric(
        proxy["fallback_open_interest_accounting_point_value"], errors="coerce"
    )
    both_available = (
        primary_proxy.notna()
        & primary_proxy.gt(0.0)
        & fallback_proxy.notna()
        & fallback_proxy.gt(0.0)
    )
    proxy_ratio = (fallback_proxy.loc[both_available] / primary_proxy.loc[both_available]).astype(
        float
    )
    ratio_quality = {
        "fallback_primary_ratio_rows": len(proxy_ratio),
        "fallback_primary_ratio_p01": (
            float(proxy_ratio.quantile(0.01)) if not proxy_ratio.empty else None
        ),
        "fallback_primary_ratio_median": (
            float(proxy_ratio.median()) if not proxy_ratio.empty else None
        ),
        "fallback_primary_ratio_p99": (
            float(proxy_ratio.quantile(0.99)) if not proxy_ratio.empty else None
        ),
        "fallback_primary_ratio_max_absolute_deviation": (
            float((proxy_ratio - 1.0).abs().max()) if not proxy_ratio.empty else None
        ),
        "fallback_primary_ratio_abs_deviation_gt_1pct_rows": int(
            (proxy_ratio.sub(1.0).abs() > 0.01).sum()
        ),
    }
    quality = {
        "all_source_paths_bounded": True,
        "all_source_bytes_and_sha256_verified": True,
        "all_daily_pages_parsed": True,
        "cursor_pagination_complete": True,
        "canonical_contract_mapping_applied": True,
        "factual_calendar_is_union_of_daily_dates": True,
        "factual_calendar_first": factual_calendar.min().date().isoformat(),
        "factual_calendar_last": factual_calendar.max().date().isoformat(),
        "source_daily_rows": len(daily),
        "waprice_finite_positive_rows": int(waprice_usable.sum()),
        "waprice_unusable_rows": int(waprice_zero.sum()),
        "waprice_unusable_rows_by_asset": waprice_unusable_by_asset,
        "waprice_missing_rows": int(waprice_numeric.isna().sum()),
        "waprice_zero_rows": int(waprice_zero.sum()),
        "waprice_nonpositive_or_missing_rows": int((~waprice_usable).sum()),
        "realized_primary_rows": int(primary_status.sum()),
        "realized_fallback_rows": int(fallback_status.sum()),
        "realized_unusable_rows": int(unusable_status.sum()),
        "realized_status_rows_by_asset": realized_status_by_asset,
        **ratio_quality,
        "sizing_usable_rows": int(proxy["sizing_usable"].sum()),
        "sizing_unusable_rows": int((~proxy["sizing_usable"]).sum()),
        "storage_segments": total_segments,
        "canonical_contracts": canonical_contracts,
        "additional_storage_alias_segments": total_segments - canonical_contracts,
        "contains_pnl": False,
        "contains_returns": False,
        "research_only": True,
    }
    return _write_immutable_dataset(
        resolved_data_root,
        proxy,
        start_date,
        end_date,
        source_fingerprint,
        source_manifests,
        raw_records,
        quality,
    )
