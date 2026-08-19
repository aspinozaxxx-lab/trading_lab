"""Izolirovannaya development-zagruzka 10m futures bez dostupa k holdout."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from market_lab.futures.iss import futures_candles_url
from market_lab.futures.market_data import parse_futures_candles_payload
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import atomic_write_bytes, write_json

TEN_MINUTE_NAMESPACE = "futures_v7_10m"  # Otdel'noe imya, ne peresekayushcheesya s v5.
TEN_MINUTE_SCHEMA_VERSION = 1  # Versiya proveriaemogo manifesta 10m-nabora.
TEN_MINUTE_INTERVAL = 10  # Oficial'nyi kod intervala desyatiminutnoi svechi ISS.
TEN_MINUTE_PAGE_SIZE = 500  # Zaproshennyi maksimal'nyi razmer stranicy candles.
TEN_MINUTE_DEVELOPMENT_START = date(2018, 1, 1)  # Nachalo development-istorii.
TEN_MINUTE_DEVELOPMENT_END = date(2025, 12, 31)  # Konec development-istorii.
TEN_MINUTE_PROTECTED_FROM = date(2026, 1, 1)  # Fizicheskaya granica netronutogo holdout.
TEN_MINUTE_ASSETS = ("Si", "RTS", "BR", "MIX")  # Polnyi v7 futures-universum.
TEN_MINUTE_USER_AGENT = "market-lab-research/0.7-10m (MOEX ISS)"  # Metka klienta ISS.
TEN_MINUTE_SAFE_STEM = re.compile(r"[^A-Za-z0-9_.-]+")  # Fil'tr imen segmentov.
TEN_MINUTE_OUTPUT_COLUMNS = (  # Stabil'naya normalizovannaya skhema odnogo segmenta.
    "timestamp",
    "end_timestamp",
    "asset_code",
    "logical_symbol",
    "canonical_contract_id",
    "canonical_segment_id",
    "secid",
    "board_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
)


@dataclass(frozen=True, slots=True)
class TenMinuteDownloadSettings:
    """Zadaet bounded retry, pacing i predel paginacii development-zagruzki."""

    timeout_seconds: float = 30.0
    max_retries: int = 5
    retry_backoff_seconds: float = 0.5
    maximum_retry_after_seconds: float = 60.0
    minimum_request_interval_seconds: float = 0.08
    maximum_pages_per_segment: int = 10_000
    progress_every_pages: int = 100

    def __post_init__(self) -> None:
        """Zapreshchaet beskonechnye ili otricatel'nye setevye nastroyki."""
        if self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds dolzhen byt' > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries dolzhen byt' >= 0")
        if self.retry_backoff_seconds < 0.0:
            raise ValueError("retry_backoff_seconds dolzhen byt' >= 0")
        if self.maximum_retry_after_seconds <= 0.0:
            raise ValueError("maximum_retry_after_seconds dolzhen byt' > 0")
        if self.minimum_request_interval_seconds < 0.0:
            raise ValueError("minimum_request_interval_seconds dolzhen byt' >= 0")
        if self.maximum_pages_per_segment <= 0:
            raise ValueError("maximum_pages_per_segment dolzhen byt' > 0")
        if self.progress_every_pages <= 0:
            raise ValueError("progress_every_pages dolzhen byt' > 0")


@dataclass(frozen=True, slots=True)
class TenMinuteSegmentPlan:
    """Fiksiruet odin board-segment iz uzhe proverennogo v5-manifesta."""

    canonical_segment_id: str
    canonical_contract_id: str
    secid: str
    board_id: str
    requested_start: date
    requested_end: date


@dataclass(frozen=True, slots=True)
class TenMinuteSourcePlan:
    """Hranit asset-spec, segmenty i kriptograficheskuyu privyazku k v5."""

    asset: FuturesAssetSpec
    segments: tuple[TenMinuteSegmentPlan, ...]
    source_manifest: dict[str, Any]
    source_segments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TenMinuteFetchedSegment:
    """Hranit proverennye stroki, raw-stranicy i cursor-audit segmenta."""

    frame: pd.DataFrame
    raw_pages: tuple[dict[str, Any], ...]
    page_audit: tuple[dict[str, Any], ...]


def _sha256_bytes(content: bytes) -> str:
    """Vozvrashchaet SHA-256 peredannogo binarnogo soderzhimogo."""
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 faila potokovo bez zagruzki v pamyat'."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    """Serializuet JSON determinirovanno dlya page-level SHA-256."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _safe_stem(value: str) -> str:
    """Stroit korotkoe bezopasnoe imya s digest polnogo identifikatora."""
    cleaned = TEN_MINUTE_SAFE_STEM.sub("_", value).strip("._") or "segment"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:96]}_{digest}"


def _bounded_path(root: Path, *parts: str) -> Path:
    """Razreshaet put' i fail-closed zapreshchaet vyhod iz kornya dannyh."""
    resolved_root = root.resolve()
    target = resolved_root.joinpath(*parts).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"Put' vyshel iz data-root: {target}") from error
    return target


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet normalizovannyi Parquet s Zstandard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_record(data_root: Path, path: Path, rows: int, pages: int) -> dict[str, Any]:
    """Stroit proveriaemuyu zapis' artefakta otnositel'no data-root."""
    resolved_root = data_root.resolve()
    resolved_path = path.resolve()
    return {
        "path": resolved_path.relative_to(resolved_root).as_posix(),
        "rows": int(rows),
        "pages": int(pages),
        "bytes": resolved_path.stat().st_size,
        "sha256": _sha256_file(resolved_path),
    }


def _read_json(path: Path) -> dict[str, Any]:
    """Chitaet JSON s ili bez UTF-8 BOM i trebuet obekt verhnego urovnya."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON ne yavlyaetsya obektom: {path}")
    return payload


def _validate_period(start_date: date, end_date: date) -> None:
    """Razreshaet tol'ko fiksirovannyi development-period do 2026 goda."""
    if end_date < start_date:
        raise ValueError("end_date ran'she start_date")
    if start_date < TEN_MINUTE_DEVELOPMENT_START:
        raise ValueError("start_date ran'she zafiksirovannogo development-perioda")
    if end_date > TEN_MINUTE_DEVELOPMENT_END or end_date >= TEN_MINUTE_PROTECTED_FROM:
        raise ValueError("Zapreshchen dostup k futures holdout s 2026-01-01")


def _verify_record(root: Path, record: dict[str, Any], *, expected_rows: int | None = None) -> Path:
    """Proveryaet granicy, razmer, SHA-256 i pri nalichii chislo strok artefakta."""
    relative = record.get("path")
    if not isinstance(relative, str) or not relative:
        raise ValueError("V artifact-record net puti")
    path = _bounded_path(root, *Path(relative).parts)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(record.get("bytes", -1)):
        raise ValueError(f"Razmer artefakta ne sovpal: {path}")
    if _sha256_file(path) != str(record.get("sha256", "")):
        raise ValueError(f"SHA-256 artefakta ne sovpal: {path}")
    if expected_rows is not None and int(record.get("rows", -1)) != expected_rows:
        raise ValueError(f"Rows artefakta ne sovpali: {path}")
    return path


def load_ten_minute_source_plan(
    source_data_root: Path,
    asset_code: str,
    start_date: date = TEN_MINUTE_DEVELOPMENT_START,
    end_date: date = TEN_MINUTE_DEVELOPMENT_END,
) -> TenMinuteSourcePlan:
    """Chitaet segmenty tol'ko iz lokal'nogo v5-manifesta i proveriaet ego Parquet."""
    _validate_period(start_date, end_date)
    if asset_code not in TEN_MINUTE_ASSETS:
        raise ValueError(f"Neizvestnyi asset_code: {asset_code}")
    manifest_path = _bounded_path(
        source_data_root,
        "processed",
        "futures_v5",
        asset_code,
        f"manifest_{start_date.isoformat()}_{end_date.isoformat()}.json",
    )
    manifest = _read_json(manifest_path)
    if str(manifest.get("requested_start")) != start_date.isoformat():
        raise ValueError("v5 manifest imeet drugoe nachalo perioda")
    if str(manifest.get("requested_end")) != end_date.isoformat():
        raise ValueError("v5 manifest imeet drugoi konec perioda")
    if str(manifest.get("asset", {}).get("asset_code")) != asset_code:
        raise ValueError("v5 manifest imeet drugoi asset_code")
    segment_record = manifest.get("catalog_artifacts", {}).get("segments", {}).get("parquet")
    if not isinstance(segment_record, dict):
        raise ValueError("v5 manifest ne soderzhit segments Parquet")
    segments_path = _verify_record(source_data_root, segment_record)
    segments_frame = pd.read_parquet(segments_path)
    required = {
        "canonical_segment_id",
        "canonical_contract_id",
        "secid",
        "boardid",
        "segment_start",
        "segment_end",
    }
    if missing := required - set(segments_frame.columns):
        raise ValueError(f"V v5 segments net kolonok: {sorted(missing)}")
    if len(segments_frame) != int(segment_record.get("rows", -1)):
        raise ValueError("Fakticheskoe chislo v5 segments ne sovpalo s manifestom")
    if segments_frame["canonical_segment_id"].duplicated().any():
        raise ValueError("Povtor canonical_segment_id v v5 segments")
    indexed = segments_frame.set_index("canonical_segment_id", drop=False)
    raw_plans = manifest.get("segment_artifacts")
    if not isinstance(raw_plans, list) or not raw_plans:
        raise ValueError("v5 manifest ne soderzhit segment_artifacts")
    plans: list[TenMinuteSegmentPlan] = []
    for raw in raw_plans:
        if not isinstance(raw, dict):
            raise ValueError("Nekorrektnyi element v5 segment_artifacts")
        segment_id = str(raw.get("canonical_segment_id", ""))
        if segment_id not in indexed.index:
            raise ValueError(f"v5 segment ne naiden v segments Parquet: {segment_id}")
        source_row = indexed.loc[segment_id]
        requested_start = date.fromisoformat(str(raw.get("requested_start")))
        requested_end = date.fromisoformat(str(raw.get("requested_end")))
        _validate_period(requested_start, requested_end)
        if requested_start < start_date or requested_end > end_date:
            raise ValueError("v5 segment vyshel iz zaproshennogo development-perioda")
        checks = {
            "canonical_contract_id": str(source_row["canonical_contract_id"]),
            "secid": str(source_row["secid"]),
            "boardid": str(source_row["boardid"]),
        }
        for key, expected in checks.items():
            if str(raw.get(key)) != expected:
                raise ValueError(f"v5 manifest/Parquet ne soglasovany po {key}")
        plans.append(
            TenMinuteSegmentPlan(
                canonical_segment_id=segment_id,
                canonical_contract_id=checks["canonical_contract_id"],
                secid=checks["secid"],
                board_id=checks["boardid"],
                requested_start=requested_start,
                requested_end=requested_end,
            )
        )
    if len(plans) != len(segments_frame):
        raise ValueError("v5 manifest i segments Parquet imeyut raznoe chislo segmentov")
    if len({plan.canonical_segment_id for plan in plans}) != len(plans):
        raise ValueError("Povtor segmenta v v5 manifest")
    asset_payload = manifest["asset"]
    asset = FuturesAssetSpec(**asset_payload)
    return TenMinuteSourcePlan(
        asset=asset,
        segments=tuple(plans),
        source_manifest={
            "path": manifest_path.relative_to(source_data_root.resolve()).as_posix(),
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256_file(manifest_path),
        },
        source_segments={
            "path": segments_path.relative_to(source_data_root.resolve()).as_posix(),
            "rows": len(segments_frame),
            "bytes": segments_path.stat().st_size,
            "sha256": _sha256_file(segments_path),
        },
    )


def _raw_columns_and_rows(payload: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """Chitaet syroi candles-blok, ne pozvolyaya parseru skryt' defekt skhemy."""
    block = payload.get("candles")
    if not isinstance(block, dict):
        raise ValueError("Otvet ISS ne soderzhit obekt candles")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("Nekorrektnyi tablichnyi blok ISS: candles")
    normalized = [str(column).lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Povtory kolonok v ISS-bloke candles")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("Stroka candles ne sootvetstvuet columns")
    return normalized, rows


def _assert_raw_page_quality(payload: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """Proveryaet unique raw-stroki i strogo vozrastayushchii begin stranicy."""
    columns, rows = _raw_columns_and_rows(payload)
    keys = [_canonical_json_bytes(row) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Povtor syroi stroki ISS v candles")
    if "begin" not in columns:
        raise ValueError("V candles net kolonki begin")
    begin_index = columns.index("begin")
    begins = pd.to_datetime([row[begin_index] for row in rows], errors="raise")
    if pd.Series(begins).diff().dropna().le(pd.Timedelta(0)).any():
        raise ValueError("candles.begin ne yavlyaetsya strogo vozrastayushchim")
    return columns, rows


def _empty_segment_frame() -> pd.DataFrame:
    """Stroit pustuyu, no stabil'nuyu normalizovannuyu skhemu segmenta."""
    return pd.DataFrame({column: pd.Series(dtype="object") for column in TEN_MINUTE_OUTPUT_COLUMNS})


def _enrich_segment_frame(
    frame: pd.DataFrame,
    asset: FuturesAssetSpec,
    plan: TenMinuteSegmentPlan,
) -> pd.DataFrame:
    """Dobavlyaet kanonicheskie kluchi k proverennym cenam bez izmeneniya znachenii."""
    if frame.empty:
        return _empty_segment_frame()
    enriched = frame.copy()
    enriched["asset_code"] = asset.asset_code
    enriched["logical_symbol"] = asset.logical_symbol
    enriched["canonical_contract_id"] = plan.canonical_contract_id
    enriched["canonical_segment_id"] = plan.canonical_segment_id
    enriched["board_id"] = plan.board_id
    return enriched[list(TEN_MINUTE_OUTPUT_COLUMNS)]


class TenMinuteIssDownloader:
    """Zagruzhaet tol'ko 10m candles po lokal'no zafiksirovannym v5-segmentam."""

    def __init__(
        self,
        session: requests.Session | None = None,
        settings: TenMinuteDownloadSettings | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Sozdaet izolirovannuyu sessiyu ili prinimaet fake-session dlya testov."""
        self.settings = settings or TenMinuteDownloadSettings()
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.monotonic = monotonic
        self._last_request_at: float | None = None
        headers = getattr(self.session, "headers", None)
        if headers is not None:
            headers.update({"User-Agent": TEN_MINUTE_USER_AGENT})

    def close(self) -> None:
        """Zakryvaet tol'ko sessiyu, sozdannuyu etim downloader."""
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> TenMinuteIssDownloader:
        """Vozvrashchaet downloader dlya upravlyaemogo konteksta."""
        return self

    def __exit__(self, *_: object) -> None:
        """Garantirovanno zakryvaet sobstvennuyu setevuyu sessiyu."""
        self.close()

    def _pace(self) -> None:
        """Vyderzhivaet minimal'nyi interval mezhdu zaprosami odnogo processa."""
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = (
                self.settings.minimum_request_interval_seconds - (now - self._last_request_at)
            )
            if remaining > 0.0:
                self.sleeper(remaining)
        self._last_request_at = self.monotonic()

    def _request_json(self, url: str) -> dict[str, Any]:
        """Vypolnyaet GET s bounded retry dlya timeout, 429 i servernyh oshibok."""
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                self._pace()
                response = self.session.get(url, timeout=self.settings.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("ISS vernul ne JSON-obekt")
                return payload
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt >= self.settings.max_retries:
                    break
                response = getattr(error, "response", None)
                status = getattr(response, "status_code", None)
                if status is not None and status != 429 and int(status) < 500:
                    break
                retry_after = 0.0
                if response is not None:
                    raw_retry_after = getattr(response, "headers", {}).get("Retry-After")
                    try:
                        retry_after = float(raw_retry_after) if raw_retry_after else 0.0
                    except ValueError:
                        retry_after = 0.0
                exponential = self.settings.retry_backoff_seconds * (2**attempt)
                delay = min(
                    max(retry_after, exponential),
                    self.settings.maximum_retry_after_seconds,
                )
                if delay > 0.0:
                    self.sleeper(delay)
        raise RuntimeError(f"Ne udalos' poluchit' ISS URL {url}: {last_error}") from last_error

    def fetch_segment(
        self,
        asset: FuturesAssetSpec,
        plan: TenMinuteSegmentPlan,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> TenMinuteFetchedSegment:
        """Listaet start do korotkoi stranicy i auditiruet kazhdyi cursor/payload."""
        _validate_period(plan.requested_start, plan.requested_end)
        frames: list[pd.DataFrame] = []
        raw_pages: list[dict[str, Any]] = []
        audits: list[dict[str, Any]] = []
        offset = 0
        previous_last: pd.Timestamp | None = None
        while len(raw_pages) < self.settings.maximum_pages_per_segment:
            url = futures_candles_url(
                asset,
                plan.secid,
                plan.requested_start,
                plan.requested_end,
                interval=TEN_MINUTE_INTERVAL,
                board_id=plan.board_id,
                cursor_start=offset,
            ) + f"&limit={TEN_MINUTE_PAGE_SIZE}"
            payload = self._request_json(url)
            _, rows = _assert_raw_page_quality(payload)
            if len(rows) > TEN_MINUTE_PAGE_SIZE:
                raise ValueError("Candles-stranica prevysila limit 500")
            frame = parse_futures_candles_payload(payload, asset, plan.secid)
            if len(frame) != len(rows):
                raise ValueError("Candles parser izmenil chislo strok stranicy")
            if not frame.empty:
                local_dates = frame["timestamp"].dt.tz_convert(asset.timezone).dt.date
                if local_dates.lt(plan.requested_start).any() or local_dates.gt(
                    plan.requested_end
                ).any():
                    raise ValueError("Candles vyshli za granicy v5 board-segmenta")
                first = frame["timestamp"].iloc[0]
                if previous_last is not None and first <= previous_last:
                    raise ValueError("Povtor ili nevozrastanie candles mezhdu stranicami")
                previous_last = frame["timestamp"].iloc[-1]
                frames.append(frame)
            page_hash = _sha256_bytes(_canonical_json_bytes(payload))
            next_offset = offset + len(rows) if len(rows) == TEN_MINUTE_PAGE_SIZE else None
            audit = {
                "cursor_start": offset,
                "cursor_next": next_offset,
                "row_count": len(rows),
                "terminal": next_offset is None,
                "first_begin": None if frame.empty else frame["timestamp"].iloc[0],
                "last_begin": None if frame.empty else frame["timestamp"].iloc[-1],
                "payload_sha256": page_hash,
                "url": url,
            }
            audits.append(audit)
            raw_pages.append({"cursor": audit, "payload": payload})
            if progress is not None:
                progress(
                    {
                        "event": "page",
                        "asset_code": asset.asset_code,
                        "canonical_segment_id": plan.canonical_segment_id,
                        "page": len(raw_pages),
                        "cursor_start": offset,
                        "rows": len(rows),
                    }
                )
            if next_offset is None:
                break
            offset = next_offset
        else:
            raise ValueError("Candles pagination prevysila maximum_pages_per_segment")
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not combined.empty:
            if combined["timestamp"].duplicated().any():
                raise ValueError("Povtor candles timestamp mezhdu stranicami")
            if not combined["timestamp"].is_monotonic_increasing:
                raise ValueError("Candles stranicy narushayut hronologicheskii poryadok")
        enriched = _enrich_segment_frame(combined, asset, plan)
        return TenMinuteFetchedSegment(enriched, tuple(raw_pages), tuple(audits))


def _segment_paths(data_root: Path, asset_code: str, segment_id: str) -> dict[str, Path]:
    """Vozvrashchaet razdelennye raw, Parquet i completion-marker puti segmenta."""
    stem = _safe_stem(segment_id)
    return {
        "raw": _bounded_path(
            data_root,
            "raw",
            TEN_MINUTE_NAMESPACE,
            asset_code,
            "segments",
            f"{stem}.json.gz",
        ),
        "parquet": _bounded_path(
            data_root,
            "processed",
            TEN_MINUTE_NAMESPACE,
            asset_code,
            "segments",
            f"{stem}.parquet",
        ),
        "manifest": _bounded_path(
            data_root,
            "processed",
            TEN_MINUTE_NAMESPACE,
            asset_code,
            "segment_manifests",
            f"{stem}.json",
        ),
    }


def _raw_archive_bytes(
    asset: FuturesAssetSpec,
    plan: TenMinuteSegmentPlan,
    fetched: TenMinuteFetchedSegment,
) -> bytes:
    """Upakovyvaet vse raw-stranicy i ih cursor v determinirovannyi gzip."""
    payload = {
        "schema_version": TEN_MINUTE_SCHEMA_VERSION,
        "source": "official anonymous MOEX ISS",
        "asset": asdict(asset),
        "segment": asdict(plan),
        "requests": list(fetched.raw_pages),
    }
    return gzip.compress(_canonical_json_bytes(payload), compresslevel=6, mtime=0)


def _persist_segment(
    data_root: Path,
    asset: FuturesAssetSpec,
    plan: TenMinuteSegmentPlan,
    fetched: TenMinuteFetchedSegment,
) -> dict[str, Any]:
    """Atomarno pishet raw/Parquet, a completion-marker manifest poslednim."""
    paths = _segment_paths(data_root, asset.asset_code, plan.canonical_segment_id)
    atomic_write_bytes(paths["raw"], _raw_archive_bytes(asset, plan, fetched))
    _atomic_write_parquet(paths["parquet"], fetched.frame)
    page_count = len(fetched.raw_pages)
    row_count = len(fetched.frame)
    manifest = {
        "schema_version": TEN_MINUTE_SCHEMA_VERSION,
        "namespace": TEN_MINUTE_NAMESPACE,
        "source": "official anonymous MOEX ISS",
        "asset": asdict(asset),
        "segment": asdict(plan),
        "status": "complete_empty" if fetched.frame.empty else "complete",
        "counts": {
            "rows": row_count,
            "pages": page_count,
            "zero_volume_rows": int((fetched.frame["volume"] == 0.0).sum()),
            "zero_value_rows": int((fetched.frame["value"] == 0.0).sum()),
        },
        "quality": {
            "duplicate_timestamps": 0,
            "invalid_ohlc_rows": 0,
            "out_of_bounds_rows": 0,
            "strictly_increasing_timestamps": True,
        },
        "pagination": {
            "interval_minutes": TEN_MINUTE_INTERVAL,
            "requested_page_size": TEN_MINUTE_PAGE_SIZE,
            "termination": "first_page_shorter_than_requested_limit",
            "pages": list(fetched.page_audit),
        },
        "artifacts": {
            "raw": _artifact_record(data_root, paths["raw"], row_count, page_count),
            "parquet": _artifact_record(data_root, paths["parquet"], row_count, page_count),
        },
    }
    write_json(paths["manifest"], manifest)
    return {
        "path": paths["manifest"].relative_to(data_root.resolve()).as_posix(),
        "rows": row_count,
        "pages": page_count,
        "bytes": paths["manifest"].stat().st_size,
        "sha256": _sha256_file(paths["manifest"]),
        "status": manifest["status"],
        "canonical_segment_id": plan.canonical_segment_id,
    }


def _load_completed_segment(
    data_root: Path,
    plan: TenMinuteSegmentPlan,
) -> dict[str, Any] | None:
    """Vozvrashchaet proverennyi completion-marker ili razreshaet bezopasnyi resume."""
    paths = _segment_paths(
        data_root,
        plan.canonical_contract_id.split(":", 1)[0],
        plan.canonical_segment_id,
    )
    if not paths["manifest"].is_file():
        return None
    manifest = _read_json(paths["manifest"])
    if manifest.get("schema_version") != TEN_MINUTE_SCHEMA_VERSION:
        raise ValueError("Resume-manifest imeet neizvestnuyu versiyu")
    if manifest.get("segment", {}).get("canonical_segment_id") != plan.canonical_segment_id:
        raise ValueError("Resume-manifest ssylayetsya na drugoi segment")
    if manifest.get("status") not in {"complete", "complete_empty"}:
        return None
    counts = manifest.get("counts", {})
    rows = int(counts.get("rows", -1))
    pages = int(counts.get("pages", -1))
    _verify_record(data_root, manifest["artifacts"]["raw"], expected_rows=rows)
    parquet_path = _verify_record(
        data_root,
        manifest["artifacts"]["parquet"],
        expected_rows=rows,
    )
    if len(pd.read_parquet(parquet_path)) != rows:
        raise ValueError("Resume Parquet imeet drugoe chislo strok")
    return {
        "path": paths["manifest"].relative_to(data_root.resolve()).as_posix(),
        "rows": rows,
        "pages": pages,
        "bytes": paths["manifest"].stat().st_size,
        "sha256": _sha256_file(paths["manifest"]),
        "status": manifest["status"],
        "canonical_segment_id": plan.canonical_segment_id,
    }


def _asset_manifest_path(
    data_root: Path,
    asset_code: str,
    start_date: date,
    end_date: date,
) -> Path:
    """Stroit put' final'nogo asset-manifesta posle vseh segmentov."""
    return _bounded_path(
        data_root,
        "processed",
        TEN_MINUTE_NAMESPACE,
        asset_code,
        f"manifest_{start_date.isoformat()}_{end_date.isoformat()}.json",
    )


def _write_sha256_sidecar(path: Path) -> Path:
    """Pishet atomarnyi UTF-8 BOM sidecar s SHA-256 gotovogo manifesta."""
    sidecar = path.with_suffix(path.suffix + ".sha256")
    content = f"{_sha256_file(path)}  {path.name}\n".encode("utf-8-sig")
    atomic_write_bytes(sidecar, content)
    return sidecar


def download_ten_minute_asset(
    data_root: Path,
    source_data_root: Path,
    asset_code: str,
    downloader: TenMinuteIssDownloader,
    start_date: date = TEN_MINUTE_DEVELOPMENT_START,
    end_date: date = TEN_MINUTE_DEVELOPMENT_END,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Zagruzhaet ili resume-it odin asset i pishet manifest tol'ko posle polnoty."""
    _validate_period(start_date, end_date)
    source = load_ten_minute_source_plan(source_data_root, asset_code, start_date, end_date)
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    completed_pages = 0
    for index, plan in enumerate(source.segments, start=1):
        record = _load_completed_segment(data_root, plan)
        resumed = record is not None
        if record is None:
            fetched = downloader.fetch_segment(source.asset, plan, progress=progress)
            record = _persist_segment(data_root, source.asset, plan, fetched)
        records.append(record)
        completed_pages += int(record["pages"])
        if progress is not None:
            elapsed = max(time.monotonic() - started, 1e-9)
            progress(
                {
                    "event": "segment",
                    "asset_code": asset_code,
                    "completed_segments": index,
                    "total_segments": len(source.segments),
                    "rows": int(record["rows"]),
                    "pages_total": completed_pages,
                    "elapsed_seconds": elapsed,
                    "pages_per_second": completed_pages / elapsed,
                    "resumed": resumed,
                }
            )
    totals = {
        "segments": len(records),
        "empty_segments": sum(record["status"] == "complete_empty" for record in records),
        "rows": sum(int(record["rows"]) for record in records),
        "pages": sum(int(record["pages"]) for record in records),
    }
    manifest = {
        "schema_version": TEN_MINUTE_SCHEMA_VERSION,
        "namespace": TEN_MINUTE_NAMESPACE,
        "research_status": "development_only_holdout_untouched",
        "source": "official anonymous MOEX ISS",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "asset": asdict(source.asset),
        "requested_start": start_date,
        "requested_end": end_date,
        "protected_from": TEN_MINUTE_PROTECTED_FROM,
        "source_v5_plan": {
            "manifest": source.source_manifest,
            "segments_parquet": source.source_segments,
        },
        "pagination": {
            "interval_minutes": TEN_MINUTE_INTERVAL,
            "requested_page_size": TEN_MINUTE_PAGE_SIZE,
            "completion_rule": "all_sealed_segments_have_verified_completion_markers",
        },
        "counts": totals,
        "segment_manifests": records,
    }
    manifest_path = _asset_manifest_path(data_root, asset_code, start_date, end_date)
    write_json(manifest_path, manifest)
    _write_sha256_sidecar(manifest_path)
    return manifest_path


def _dataset_manifest_path(data_root: Path, start_date: date, end_date: date) -> Path:
    """Stroit put' manifesta polnogo chetyrehassetnogo 10m-nabora."""
    return _bounded_path(
        data_root,
        "processed",
        TEN_MINUTE_NAMESPACE,
        f"manifest_{start_date.isoformat()}_{end_date.isoformat()}.json",
    )


def finalize_ten_minute_dataset(
    data_root: Path,
    start_date: date = TEN_MINUTE_DEVELOPMENT_START,
    end_date: date = TEN_MINUTE_DEVELOPMENT_END,
) -> Path:
    """Pishet dataset-manifest tol'ko kogda vse chetyre asset-manifesta polny."""
    _validate_period(start_date, end_date)
    asset_records: list[dict[str, Any]] = []
    for asset_code in TEN_MINUTE_ASSETS:
        path = _asset_manifest_path(data_root, asset_code, start_date, end_date)
        if not path.is_file():
            raise FileNotFoundError(f"Net complete asset-manifesta: {path}")
        manifest = _read_json(path)
        if manifest.get("research_status") != "development_only_holdout_untouched":
            raise ValueError("Asset-manifest ne imeet development-only status")
        counts = manifest.get("counts", {})
        records = manifest.get("segment_manifests", [])
        if int(counts.get("segments", -1)) != len(records):
            raise ValueError("Asset-manifest ne dokazyvaet polnotu segmentov")
        for record in records:
            _verify_record(data_root, record, expected_rows=int(record["rows"]))
        asset_records.append(
            {
                "asset_code": asset_code,
                "path": path.relative_to(data_root.resolve()).as_posix(),
                "rows": int(counts["rows"]),
                "pages": int(counts["pages"]),
                "segments": int(counts["segments"]),
                "empty_segments": int(counts["empty_segments"]),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "schema_version": TEN_MINUTE_SCHEMA_VERSION,
        "namespace": TEN_MINUTE_NAMESPACE,
        "research_status": "development_only_holdout_untouched",
        "source": "official anonymous MOEX ISS",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "requested_start": start_date,
        "requested_end": end_date,
        "protected_from": TEN_MINUTE_PROTECTED_FROM,
        "assets": asset_records,
        "totals": {
            "assets": len(asset_records),
            "segments": sum(record["segments"] for record in asset_records),
            "empty_segments": sum(record["empty_segments"] for record in asset_records),
            "rows": sum(record["rows"] for record in asset_records),
            "pages": sum(record["pages"] for record in asset_records),
        },
        "completion": "all_four_asset_manifests_verified",
    }
    path = _dataset_manifest_path(data_root, start_date, end_date)
    write_json(path, manifest)
    _write_sha256_sidecar(path)
    return path


def download_ten_minute_dataset(
    data_root: Path,
    source_data_root: Path,
    settings: TenMinuteDownloadSettings | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Zagruzhaet ves' fiksirovannyi universum i finaliziruet ego odnim markerom."""
    with TenMinuteIssDownloader(settings=settings) as downloader:
        for asset_code in TEN_MINUTE_ASSETS:
            download_ten_minute_asset(
                data_root,
                source_data_root,
                asset_code,
                downloader,
                progress=progress,
            )
    return finalize_ten_minute_dataset(data_root)


def _plan_from_raw_archive(
    payload: dict[str, Any],
) -> tuple[FuturesAssetSpec, TenMinuteSegmentPlan]:
    """Vosstanavlivaet tipizirovannyi asset i segment iz raw-arhiva."""
    raw_asset = payload.get("asset")
    raw_segment = payload.get("segment")
    if not isinstance(raw_asset, dict) or not isinstance(raw_segment, dict):
        raise ValueError("Raw-arhiv ne soderzhit asset/segment")
    asset = FuturesAssetSpec(**raw_asset)
    plan = TenMinuteSegmentPlan(
        canonical_segment_id=str(raw_segment["canonical_segment_id"]),
        canonical_contract_id=str(raw_segment["canonical_contract_id"]),
        secid=str(raw_segment["secid"]),
        board_id=str(raw_segment["board_id"]),
        requested_start=date.fromisoformat(str(raw_segment["requested_start"])),
        requested_end=date.fromisoformat(str(raw_segment["requested_end"])),
    )
    _validate_period(plan.requested_start, plan.requested_end)
    return asset, plan


def _reparse_raw_archive(path: Path) -> tuple[pd.DataFrame, tuple[dict[str, Any], ...]]:
    """Povtorno parse-it kazhduyu raw-stranicu i dokazyvaet cursor/payload SHA."""
    try:
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Nekorrektnyi raw gzip-arhiv: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError("Raw gzip ne soderzhit JSON-obekt")
    if payload.get("schema_version") != TEN_MINUTE_SCHEMA_VERSION:
        raise ValueError("Raw gzip imeet neizvestnuyu versiyu")
    asset, plan = _plan_from_raw_archive(payload)
    requests_payload = payload.get("requests")
    if not isinstance(requests_payload, list) or not requests_payload:
        raise ValueError("Raw gzip ne soderzhit stranicy")
    frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    expected_offset = 0
    previous_last: pd.Timestamp | None = None
    for page_index, raw_request in enumerate(requests_payload, start=1):
        if not isinstance(raw_request, dict):
            raise ValueError("Nekorrektnaya raw-stranica")
        audit = raw_request.get("cursor")
        page = raw_request.get("payload")
        if not isinstance(audit, dict) or not isinstance(page, dict):
            raise ValueError("Raw-stranica ne soderzhit cursor/payload")
        _, rows = _assert_raw_page_quality(page)
        if len(rows) > TEN_MINUTE_PAGE_SIZE:
            raise ValueError("Raw-stranica prevysila 500 strok")
        if int(audit.get("cursor_start", -1)) != expected_offset:
            raise ValueError("Raw cursor_start narushil posledovatel'nost'")
        if int(audit.get("row_count", -1)) != len(rows):
            raise ValueError("Raw cursor row_count ne sovpal s payload")
        expected_hash = _sha256_bytes(_canonical_json_bytes(page))
        if audit.get("payload_sha256") != expected_hash:
            raise ValueError("Raw page payload_sha256 ne sovpal")
        terminal = len(rows) < TEN_MINUTE_PAGE_SIZE
        if bool(audit.get("terminal")) != terminal:
            raise ValueError("Raw terminal flag ne sootvetstvuet razmeru stranicy")
        expected_next = None if terminal else expected_offset + len(rows)
        if audit.get("cursor_next") != expected_next:
            raise ValueError("Raw cursor_next ne sootvetstvuet razmeru stranicy")
        if terminal and page_index != len(requests_payload):
            raise ValueError("Posle terminal raw-stranicy est' dopolnitel'nye stranicy")
        frame = parse_futures_candles_payload(page, asset, plan.secid)
        if len(frame) != len(rows):
            raise ValueError("Raw parser izmenil chislo strok")
        if not frame.empty:
            local_dates = frame["timestamp"].dt.tz_convert(asset.timezone).dt.date
            if local_dates.lt(plan.requested_start).any() or local_dates.gt(
                plan.requested_end
            ).any():
                raise ValueError("Raw candles vyshli iz board-segmenta")
            first = frame["timestamp"].iloc[0]
            if previous_last is not None and first <= previous_last:
                raise ValueError("Raw candles povtoryayutsya mezhdu stranicami")
            previous_last = frame["timestamp"].iloc[-1]
            frames.append(frame)
        audits.append(audit)
        if expected_next is not None:
            expected_offset = expected_next
    if not bool(audits[-1].get("terminal")):
        raise ValueError("Raw pagination ne imeet terminal'noi stranicy")
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    enriched = _enrich_segment_frame(combined, asset, plan)
    return enriched, tuple(audits)


def verify_ten_minute_segment(data_root: Path, manifest_record: dict[str, Any]) -> dict[str, int]:
    """Polnost'yu pereproveryaet segment-manifest, raw payload i Parquet."""
    manifest_path = _verify_record(
        data_root,
        manifest_record,
        expected_rows=int(manifest_record.get("rows", -1)),
    )
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != TEN_MINUTE_SCHEMA_VERSION:
        raise ValueError("Segment-manifest imeet neizvestnuyu versiyu")
    counts = manifest.get("counts")
    artifacts = manifest.get("artifacts")
    if not isinstance(counts, dict) or not isinstance(artifacts, dict):
        raise ValueError("Segment-manifest ne soderzhit counts/artifacts")
    rows = int(counts.get("rows", -1))
    pages = int(counts.get("pages", -1))
    raw_path = _verify_record(data_root, artifacts["raw"], expected_rows=rows)
    parquet_path = _verify_record(data_root, artifacts["parquet"], expected_rows=rows)
    reparsed, audits = _reparse_raw_archive(raw_path)
    stored = pd.read_parquet(parquet_path)
    if list(stored.columns) != list(TEN_MINUTE_OUTPUT_COLUMNS):
        raise ValueError("Parquet imeet nestabil'nuyu skhemu")
    if len(reparsed) != rows or len(stored) != rows or len(audits) != pages:
        raise ValueError("Segment counts ne sovpali s raw/Parquet")
    if rows:
        pd.testing.assert_frame_equal(
            stored.reset_index(drop=True),
            reparsed.reset_index(drop=True),
            check_dtype=True,
            check_exact=True,
        )
    expected_zero_volume = int((stored["volume"] == 0.0).sum())
    expected_zero_value = int((stored["value"] == 0.0).sum())
    if int(counts.get("zero_volume_rows", -1)) != expected_zero_volume:
        raise ValueError("zero_volume_rows ne sovpal")
    if int(counts.get("zero_value_rows", -1)) != expected_zero_value:
        raise ValueError("zero_value_rows ne sovpal")
    if manifest.get("pagination", {}).get("pages") != list(audits):
        raise ValueError("Segment-manifest i raw cursor-audit ne sovpali")
    return {"rows": rows, "pages": pages, "segments": 1}


def verify_ten_minute_asset(
    data_root: Path,
    source_data_root: Path,
    asset_record: dict[str, Any],
) -> dict[str, int]:
    """Proveryaet source-v5 privyazku i vse segmenty odnogo asseta."""
    path = _verify_record(data_root, asset_record)
    manifest = _read_json(path)
    asset_code = str(asset_record.get("asset_code", ""))
    if manifest.get("asset", {}).get("asset_code") != asset_code:
        raise ValueError("Dataset i asset-manifest ne soglasovany po asset_code")
    source_plan = manifest.get("source_v5_plan")
    if not isinstance(source_plan, dict):
        raise ValueError("Asset-manifest ne soderzhit source_v5_plan")
    _verify_record(source_data_root, source_plan["manifest"])
    source_segments = source_plan["segments_parquet"]
    source_path = _verify_record(source_data_root, source_segments)
    if len(pd.read_parquet(source_path)) != int(source_segments.get("rows", -1)):
        raise ValueError("Source v5 segments rows ne sovpali")
    totals = {"rows": 0, "pages": 0, "segments": 0}
    records = manifest.get("segment_manifests")
    if not isinstance(records, list):
        raise ValueError("Asset-manifest ne soderzhit segment_manifests")
    for record in records:
        verified = verify_ten_minute_segment(data_root, record)
        for key in totals:
            totals[key] += verified[key]
    counts = manifest.get("counts", {})
    if any(totals[key] != int(counts.get(key, -1)) for key in totals):
        raise ValueError("Asset totals ne sovpali s segmentami")
    return totals


def verify_ten_minute_dataset(
    data_root: Path,
    source_data_root: Path,
    start_date: date = TEN_MINUTE_DEVELOPMENT_START,
    end_date: date = TEN_MINUTE_DEVELOPMENT_END,
) -> dict[str, int]:
    """Polnost'yu pereproveryaet final'nyi chetyrehassetnyi dataset bez seti."""
    _validate_period(start_date, end_date)
    path = _dataset_manifest_path(data_root, start_date, end_date)
    manifest = _read_json(path)
    if manifest.get("completion") != "all_four_asset_manifests_verified":
        raise ValueError("Dataset-manifest ne imeet complete-marker")
    records = manifest.get("assets")
    if not isinstance(records, list):
        raise ValueError("Dataset-manifest ne soderzhit assets")
    if tuple(record.get("asset_code") for record in records) != TEN_MINUTE_ASSETS:
        raise ValueError("Dataset-manifest imeet drugoi ili nepolnyi universum")
    totals = {"rows": 0, "pages": 0, "segments": 0}
    for record in records:
        verified = verify_ten_minute_asset(data_root, source_data_root, record)
        for key in totals:
            totals[key] += verified[key]
    expected = manifest.get("totals", {})
    if any(totals[key] != int(expected.get(key, -1)) for key in totals):
        raise ValueError("Dataset totals ne sovpali s assetami")
    if int(expected.get("assets", -1)) != len(TEN_MINUTE_ASSETS):
        raise ValueError("Dataset ne soderzhit chetyre asseta")
    return totals


def _print_progress(event: dict[str, Any]) -> None:
    """Pechataet JSONL-progress dlya udalennogo loga i rascheta ETA."""
    if event.get("event") == "page" and int(event.get("page", 0)) % 100 != 0:
        return
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def _build_argument_parser() -> argparse.ArgumentParser:
    """Stroit minimal'nyi CLI dlya udalennogo download/finalize bez model'nogo koda."""
    parser = argparse.ArgumentParser(description="Development-only MOEX futures 10m downloader")
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--data-root", type=Path, required=True)
    download.add_argument("--source-data-root", type=Path, required=True)
    download.add_argument("--timeout", type=float, default=30.0)
    download.add_argument("--max-retries", type=int, default=5)
    download.add_argument("--minimum-request-interval", type=float, default=0.08)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--data-root", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--data-root", type=Path, required=True)
    verify.add_argument("--source-data-root", type=Path, required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Zapuskaet tol'ko download ili proverku polnoty bez PnL/modeli."""
    parsed = _build_argument_parser().parse_args(arguments)
    if parsed.command == "download":
        settings = TenMinuteDownloadSettings(
            timeout_seconds=parsed.timeout,
            max_retries=parsed.max_retries,
            minimum_request_interval_seconds=parsed.minimum_request_interval,
        )
        manifest = download_ten_minute_dataset(
            parsed.data_root,
            parsed.source_data_root,
            settings=settings,
            progress=_print_progress,
        )
    elif parsed.command == "finalize":
        manifest = finalize_ten_minute_dataset(parsed.data_root)
    else:
        totals = verify_ten_minute_dataset(parsed.data_root, parsed.source_data_root)
        print(json.dumps(totals, ensure_ascii=False), flush=True)
        return 0
    print(str(manifest.resolve()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
