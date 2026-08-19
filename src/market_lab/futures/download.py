"""Strogaya zagruzka futures-dannyh iz oficial'nogo MOEX ISS."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from market_lab.futures.iss import (
    FuturesSeriesCatalog,
    futures_boards_url,
    futures_candles_url,
    futures_daily_url,
    futures_open_interest_url,
    futures_series_url,
    parse_futures_boards_payload,
    parse_futures_series_catalog,
    resolve_canonical_board_segments,
)
from market_lab.futures.market_data import (
    parse_futures_candles_payload,
    parse_futures_daily_payload,
    parse_futures_participant_oi_payload,
)
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import atomic_write_bytes, write_json

CANDLE_PAGE_SIZE = 500  # Fiksirovannyi maksimal'nyi razmer stranicy candles ISS.
DEFAULT_OI_WINDOW_DAYS = 90  # Razmer kalendarnogo okna participant OI bez cursor.
DEFAULT_OI_COVERAGE_TOLERANCE_DAYS = 14  # Dopustimyi razryv na prazdniki MOEX.
DEFAULT_TIMEOUT_SECONDS = 30.0  # Timeout odnogo HTTPS-zaprosa k ISS.
DEFAULT_MAX_RETRIES = 3  # Chislo povtorov posle pervogo neudachnogo zaprosa.
DEFAULT_MAX_PAGES = 100_000  # Predel ot beskonechnoi ili ignoriruemoi paginacii.
PROTECTED_HOLDOUT_START = date(2026, 1, 1)  # Nachalo netronutogo futures holdout.
DOWNLOAD_USER_AGENT = "market-lab-research/0.5 (MOEX ISS)"  # Identifikator klienta.
SAFE_STEM_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")  # Fil'tr imen artefaktov Windows.


@dataclass(frozen=True, slots=True)
class FuturesDownloadSettings:
    """Zadaet setevye limity i fail-closed granicy zagruzchika."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = 0.25
    max_pages: int = DEFAULT_MAX_PAGES
    oi_window_days: int = DEFAULT_OI_WINDOW_DAYS
    oi_coverage_tolerance_days: int = DEFAULT_OI_COVERAGE_TOLERANCE_DAYS
    protected_from: date | None = PROTECTED_HOLDOUT_START

    def __post_init__(self) -> None:
        """Proveryaet polozhitel'nye i konechnye setevye limity."""
        if self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds dolzhen byt' > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries dolzhen byt' >= 0")
        if self.retry_backoff_seconds < 0.0:
            raise ValueError("retry_backoff_seconds dolzhen byt' >= 0")
        if self.max_pages <= 0:
            raise ValueError("max_pages dolzhen byt' > 0")
        if self.oi_window_days <= 0:
            raise ValueError("oi_window_days dolzhen byt' > 0")
        if self.oi_coverage_tolerance_days < 0:
            raise ValueError("oi_coverage_tolerance_days dolzhen byt' >= 0")


@dataclass(frozen=True, slots=True)
class FetchedIssTable:
    """Hranit proverennuyu tablicu i vse syrye stranicy dlya audita."""

    frame: pd.DataFrame
    pages: tuple[dict[str, Any], ...]
    urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FuturesAssetDownloadResult:
    """Vozvrashchaet put' manifesta i razmery polnogo asset-nabora."""

    asset_code: str
    start_date: date
    end_date: date
    contracts: int
    excluded: int
    board_segments: int
    daily_rows: int
    candle_rows: int
    participant_oi_rows: int
    manifest_path: Path


def _block_columns_and_rows(
    payload: dict[str, Any],
    block_name: str,
) -> tuple[list[str], list[list[Any]]]:
    """Chitaet syroi ISS-blok bez sortirovki, chtoby proverit' poryadok."""
    block = payload.get(block_name)
    if not isinstance(block, dict):
        raise ValueError(f"Otvet ISS ne soderzhit obekt {block_name}")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"Nekorrektnyi tablichnyi blok ISS: {block_name}")
    normalized = [str(column).lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"Povtory kolonok v ISS-bloke {block_name}")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"Stroka {block_name} ne sootvetstvuet columns")
    return normalized, rows


def _raw_column(
    payload: dict[str, Any],
    block_name: str,
    column_name: str,
) -> pd.Series:
    """Vozvrashchaet odnu kolonku v original'nom poryadke servera."""
    columns, rows = _block_columns_and_rows(payload, block_name)
    if column_name not in columns:
        raise ValueError(f"V {block_name} net kolonki {column_name}")
    index = columns.index(column_name)
    return pd.Series([row[index] for row in rows], dtype="object")


def _assert_no_duplicate_raw_rows(payload: dict[str, Any], block_name: str) -> None:
    """Zapreshchaet dazhe polnost'yu odinakovye stroki do raboty parsera."""
    _, rows = _block_columns_and_rows(payload, block_name)
    keys = [json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Povtor syroi stroki ISS v {block_name}")


def _assert_raw_time_order(
    payload: dict[str, Any],
    block_name: str,
    column_name: str,
    allow_equal: bool,
) -> None:
    """Proveryaet servernyi poryadok vremeni do normalizuyushchei sortirovki."""
    raw = _raw_column(payload, block_name, column_name)
    if raw.empty:
        return
    parsed = pd.to_datetime(raw, errors="raise")
    if parsed.isna().any():
        raise ValueError(f"Propusk vremeni v {block_name}.{column_name}")
    differences = parsed.diff().dropna()
    invalid = differences.lt(pd.Timedelta(0)) if allow_equal else differences.le(pd.Timedelta(0))
    if invalid.any():
        relation = "neubyvayushchim" if allow_equal else "strogo vozrastayushchim"
        raise ValueError(f"{block_name}.{column_name} ne yavlyaetsya {relation}")


def _count_grouped_raw_time_inversions(
    payload: dict[str, Any],
    block_name: str,
    time_column: str,
    group_column: str,
) -> int:
    """Schitaet narusheniya raw-poryadka bez otkaza ot polnogo unique nabora."""
    raw_time = _raw_column(payload, block_name, time_column)
    raw_group = _raw_column(payload, block_name, group_column)
    if raw_time.empty:
        return 0
    parsed = pd.to_datetime(raw_time, errors="raise")
    if parsed.isna().any() or raw_group.isna().any():
        raise ValueError(f"Propusk vremeni ili gruppy v {block_name}")
    audit = pd.DataFrame({"time": parsed, "group": raw_group})
    return int(
        sum(
            rows["time"].diff().dropna().lt(pd.Timedelta(0)).sum()
            for _, rows in audit.groupby("group", sort=False)
        )
    )


def _assert_date_bounds(
    values: pd.Series,
    start_date: date,
    end_date: date,
    label: str,
) -> None:
    """Zapreshchaet stroki ISS za predelami zaproshennogo intervala."""
    if values.empty:
        return
    normalized = pd.to_datetime(values, errors="raise").dt.date
    if normalized.lt(start_date).any() or normalized.gt(end_date).any():
        raise ValueError(f"{label} vyshel za granicy zaproshennogo intervala")


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 gotovogo artefakta potokovo."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet DataFrame v Parquet s Zstandard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _raw_archive_bytes(table: FetchedIssTable) -> bytes:
    """Upakovyvaet URL i JSON-stranicy v determinirovannyi gzip-konteiner."""
    payload = {
        "requests": [
            {"url": url, "payload": page}
            for url, page in zip(table.urls, table.pages, strict=True)
        ]
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return gzip.compress(serialized, compresslevel=6, mtime=0)


def _safe_stem(value: str) -> str:
    """Stroit korotkoe Windows-compatible imya bez poteri unikal'nosti."""
    cleaned = SAFE_STEM_PATTERN.sub("_", value).strip("._") or "artifact"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:96]}_{digest}"


def _bounded_path(root: Path, *parts: str) -> Path:
    """Razreshaet put' i zapreshchaet vyhod iz peredannogo kornya."""
    resolved_root = root.resolve()
    target = resolved_root.joinpath(*parts).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"Put' artefakta vyshel iz kornya: {target}") from error
    return target


def _artifact_record(root: Path, path: Path, rows: int, pages: int) -> dict[str, Any]:
    """Stroit proveriaemuyu stroku manifesta odnogo artefakta."""
    return {
        "path": path.relative_to(root.resolve()).as_posix(),
        "rows": rows,
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _date_windows(start_date: date, end_date: date, window_days: int) -> list[tuple[date, date]]:
    """Razbivaet interval na soprikasayushchiesya, no ne peresekayushchiesya okna."""
    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(end_date, cursor + timedelta(days=window_days - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _resolve_all_board_segments(
    contracts: pd.DataFrame,
    boards: pd.DataFrame,
) -> pd.DataFrame:
    """Sokhranyaet kazhdyi datirovannyi board-segment kazhdogo storage-aliasa."""
    return resolve_canonical_board_segments(
        contracts,
        boards,
        preferred_board="RFUD",
        require_all=True,
    )


class FuturesIssDownloader:
    """Zagruzhaet ISS posledovatel'no i fail-closed proveriaet kazhduyu stranicu."""

    def __init__(
        self,
        root: Path,
        session: requests.Session | None = None,
        settings: FuturesDownloadSettings | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Sozdaet izolirovannyi klient s vnedryaemoi fake-session dlya testov."""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings or FuturesDownloadSettings()
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.sleeper = sleeper
        headers = getattr(self.session, "headers", None)
        if headers is not None:
            headers.update({"User-Agent": DOWNLOAD_USER_AGENT})

    def close(self) -> None:
        """Zakryvaet tol'ko sozdanuyu samim downloader setevuyu sessiyu."""
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> FuturesIssDownloader:
        """Vozvrashchaet downloader dlya upravlyaemogo konteksta."""
        return self

    def __exit__(self, *_: object) -> None:
        """Garantirovanno zakryvaet sobstvennuyu sessiyu."""
        self.close()

    def _validate_period(self, start_date: date, end_date: date) -> None:
        """Proveryaet poryadok dat i blokiruet zafiksirovannyi holdout."""
        if end_date < start_date:
            raise ValueError("end_date ran'she start_date")
        protected = self.settings.protected_from
        if protected is not None and end_date >= protected:
            raise ValueError(f"Zapreshchen dostup k futures holdout s {protected}")

    def _request_json(self, url: str) -> dict[str, Any]:
        """Vypolnyaet HTTPS GET s timeout i ogranichennym exponential backoff."""
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
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
                delay = self.settings.retry_backoff_seconds * (2**attempt)
                if delay:
                    self.sleeper(delay)
        raise RuntimeError(f"Ne udalos' poluchit' ISS URL {url}: {last_error}") from last_error

    def fetch_series(self, asset: FuturesAssetSpec) -> tuple[FuturesSeriesCatalog, FetchedIssTable]:
        """Zagruzhaet series i otdel'no vozvrashchaet audit isklyuchennyh strok."""
        url = futures_series_url(asset)
        payload = self._request_json(url)
        _assert_no_duplicate_raw_rows(payload, "series")
        catalog = parse_futures_series_catalog(payload, asset)
        if catalog.contracts.empty:
            raise ValueError(f"ISS ne vernul outright-kontrakty dlya {asset.asset_code}")
        table = FetchedIssTable(catalog.contracts, (payload,), (url,))
        return catalog, table

    def fetch_boards(
        self,
        contracts: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame, FetchedIssTable]:
        """Zagruzhaet boards dlya kazhdogo storage-aliasa i razreshaet vse segmenty."""
        if "secid" not in contracts:
            raise ValueError("V contracts net kolonki secid")
        frames: list[pd.DataFrame] = []
        pages: list[dict[str, Any]] = []
        urls: list[str] = []
        for secid in sorted(set(contracts["secid"].astype(str))):
            url = futures_boards_url(secid)
            payload = self._request_json(url)
            _assert_no_duplicate_raw_rows(payload, "boards")
            frame = parse_futures_boards_payload(payload, preferred_board="RFUD")
            if frame.empty:
                raise ValueError(f"Pustoi boards-otvet dlya {secid}")
            if (frame["secid"] != secid).any():
                raise ValueError(f"Boards dlya {secid} soderzhit drugoi SECID")
            frames.append(frame)
            pages.append(payload)
            urls.append(url)
        boards = pd.concat(frames, ignore_index=True)
        if boards.duplicated(["secid", "boardid", "history_from", "history_till"]).any():
            raise ValueError("Povtor board-segmenta mezhdu otvetami ISS")
        boards = boards.sort_values(["secid", "history_from", "boardid"], ignore_index=True)
        segments = _resolve_all_board_segments(contracts, boards)
        return boards, segments, FetchedIssTable(boards, tuple(pages), tuple(urls))

    def fetch_daily(
        self,
        asset: FuturesAssetSpec,
        secid: str,
        board_id: str,
        start_date: date,
        end_date: date,
    ) -> FetchedIssTable:
        """Dozhidaetsya cursor.total i zapreshchaet lyubuyu usechennuyu daily-stranicu."""
        self._validate_period(start_date, end_date)
        frames: list[pd.DataFrame] = []
        pages: list[dict[str, Any]] = []
        urls: list[str] = []
        offset = 0
        expected_total: int | None = None
        while len(pages) < self.settings.max_pages:
            url = futures_daily_url(
                asset,
                secid,
                start_date,
                end_date,
                board_id=board_id,
                cursor_start=offset,
            )
            payload = self._request_json(url)
            _assert_no_duplicate_raw_rows(payload, "history")
            _assert_raw_time_order(payload, "history", "tradedate", allow_equal=False)
            raw_rows = _block_columns_and_rows(payload, "history")[1]
            frame, cursor = parse_futures_daily_payload(payload, asset, expected_secid=secid)
            if cursor.index != offset:
                raise ValueError(f"Daily cursor.index={cursor.index}, ozhidalsya {offset}")
            if expected_total is None:
                expected_total = cursor.total
            elif cursor.total != expected_total:
                raise ValueError("Daily cursor.total izmenilsya mezhdu stranicami")
            expected_rows = min(cursor.page_size, max(cursor.total - cursor.index, 0))
            if len(raw_rows) != expected_rows or len(frame) != expected_rows:
                raise ValueError(
                    f"Usechennaya daily-stranica: {len(raw_rows)} vmesto {expected_rows}"
                )
            _assert_date_bounds(frame["trade_date"], start_date, end_date, "daily")
            pages.append(payload)
            urls.append(url)
            if not frame.empty:
                frames.append(frame)
            next_index = cursor.next_index
            if next_index is None:
                break
            if next_index <= offset:
                raise ValueError("Daily cursor ne prodvigaetsya")
            offset = next_index
        else:
            raise ValueError("Daily pagination prevysila max_pages")
        expected_total = expected_total or 0
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if len(combined) != expected_total:
            raise ValueError(f"Daily pokrytie {len(combined)} ne ravno total={expected_total}")
        if combined.empty:
            raise ValueError(f"ISS ne vernul daily history dlya {secid}/{board_id}")
        if combined.duplicated(["trade_date", "secid", "board_id"]).any():
            raise ValueError("Povtor daily stroki mezhdu stranicami")
        if not combined["trade_date"].is_monotonic_increasing:
            raise ValueError("Daily stranicy narushayut hronologicheskii poryadok")
        return FetchedIssTable(combined, tuple(pages), tuple(urls))

    def fetch_candles(
        self,
        asset: FuturesAssetSpec,
        secid: str,
        board_id: str,
        start_date: date,
        end_date: date,
    ) -> FetchedIssTable:
        """Listaet candles start do pervoi stranicy koroche 500 bez deduplikacii."""
        self._validate_period(start_date, end_date)
        frames: list[pd.DataFrame] = []
        pages: list[dict[str, Any]] = []
        urls: list[str] = []
        offset = 0
        previous_last: pd.Timestamp | None = None
        while len(pages) < self.settings.max_pages:
            url = (
                futures_candles_url(
                    asset,
                    secid,
                    start_date,
                    end_date,
                    board_id=board_id,
                    cursor_start=offset,
                )
                + f"&limit={CANDLE_PAGE_SIZE}"
            )
            payload = self._request_json(url)
            _assert_no_duplicate_raw_rows(payload, "candles")
            _assert_raw_time_order(payload, "candles", "begin", allow_equal=False)
            raw_rows = _block_columns_and_rows(payload, "candles")[1]
            if len(raw_rows) > CANDLE_PAGE_SIZE:
                raise ValueError("Candles-stranica prevysila limit 500")
            frame = parse_futures_candles_payload(payload, asset, secid)
            if len(frame) != len(raw_rows):
                raise ValueError("Candles parser izmenil chislo strok stranicy")
            if not frame.empty:
                local_dates = frame["timestamp"].dt.tz_convert(asset.timezone).dt.date
                _assert_date_bounds(local_dates, start_date, end_date, "candles")
                first = frame["timestamp"].iloc[0]
                if previous_last is not None and first <= previous_last:
                    raise ValueError("Povtor ili nevozrastanie candles mezhdu stranicami")
                previous_last = frame["timestamp"].iloc[-1]
                frames.append(frame)
            pages.append(payload)
            urls.append(url)
            if len(raw_rows) < CANDLE_PAGE_SIZE:
                break
            offset += len(raw_rows)
        else:
            raise ValueError("Candles pagination prevysila max_pages")
        if not frames:
            raise ValueError(f"ISS ne vernul candles dlya {secid}/{board_id}")
        combined = pd.concat(frames, ignore_index=True)
        if combined["timestamp"].duplicated().any():
            raise ValueError("Povtor candles timestamp mezhdu stranicami")
        if not combined["timestamp"].is_monotonic_increasing:
            raise ValueError("Candles stranicy narushayut hronologicheskii poryadok")
        return FetchedIssTable(combined, tuple(pages), tuple(urls))

    def fetch_participant_oi(
        self,
        asset: FuturesAssetSpec,
        start_date: date,
        end_date: date,
    ) -> FetchedIssTable:
        """Listaet OI po datam i dokazyvaet pokrytie, poskol'ku endpoint ne daet cursor."""
        self._validate_period(start_date, end_date)
        frames: list[pd.DataFrame] = []
        pages: list[dict[str, Any]] = []
        urls: list[str] = []
        raw_time_inversion_count = 0
        windows = _date_windows(start_date, end_date, self.settings.oi_window_days)
        if len(windows) > self.settings.max_pages:
            raise ValueError("Participant OI pagination prevysila max_pages")
        for window_start, window_end in windows:
            url = futures_open_interest_url(asset, window_start, window_end)
            payload = self._request_json(url)
            _assert_no_duplicate_raw_rows(payload, "open_positions")
            raw_time_inversion_count += _count_grouped_raw_time_inversions(
                payload,
                "open_positions",
                "tradedate",
                "is_fiz",
            )
            raw_rows = _block_columns_and_rows(payload, "open_positions")[1]
            frame = parse_futures_participant_oi_payload(payload, asset)
            if len(frame) != len(raw_rows):
                raise ValueError("Participant OI parser izmenil chislo strok")
            _assert_date_bounds(frame["trade_date"], window_start, window_end, "participant OI")
            if not frame.empty:
                category_counts = frame.groupby("trade_date")["is_physical"].agg(
                    lambda values: frozenset(bool(value) for value in values)
                )
                if not category_counts.eq(frozenset({False, True})).all():
                    raise ValueError("Participant OI ne soderzhit obe kategorii na kazhduyu datu")
                frames.append(frame)
            pages.append(payload)
            urls.append(url)
        if not frames:
            raise ValueError(f"ISS ne vernul participant OI dlya {asset.asset_code}")
        combined = pd.concat(frames, ignore_index=True).sort_values(
            ["trade_date", "is_physical"], ignore_index=True
        )
        if combined.duplicated(["trade_date", "asset_code", "is_physical"]).any():
            raise ValueError("Povtor participant OI mezhdu oknami")
        dates = combined["trade_date"].drop_duplicates().sort_values(ignore_index=True)
        tolerance = pd.Timedelta(days=self.settings.oi_coverage_tolerance_days)
        if dates.iloc[0] > pd.Timestamp(start_date) + tolerance:
            raise ValueError("Participant OI ne pokryvaet nachalo intervala")
        if dates.iloc[-1] < pd.Timestamp(end_date) - tolerance:
            raise ValueError("Participant OI ne pokryvaet konec intervala")
        gaps = dates.diff().dropna()
        if gaps.gt(tolerance).any():
            raise ValueError("Participant OI soderzhit nepokrytyi kalendarnyi razryv")
        combined.attrs["raw_time_inversion_count"] = raw_time_inversion_count
        return FetchedIssTable(combined, tuple(pages), tuple(urls))

    def _persist_table(
        self,
        relative_stem: str,
        table: FetchedIssTable,
    ) -> dict[str, dict[str, Any]]:
        """Atomarno sohranyaet raw JSON.gz i normalizovannyi Parquet pod root."""
        raw_path = _bounded_path(self.root, "raw", "futures_v5", f"{relative_stem}.json.gz")
        parquet_path = _bounded_path(
            self.root,
            "processed",
            "futures_v5",
            f"{relative_stem}.parquet",
        )
        atomic_write_bytes(raw_path, _raw_archive_bytes(table))
        _atomic_write_parquet(parquet_path, table.frame)
        return {
            "raw": _artifact_record(self.root, raw_path, len(table.frame), len(table.pages)),
            "parquet": _artifact_record(
                self.root,
                parquet_path,
                len(table.frame),
                len(table.pages),
            ),
        }

    def download_asset(
        self,
        asset: FuturesAssetSpec,
        start_date: date,
        end_date: date,
        include_candles: bool = True,
    ) -> FuturesAssetDownloadResult:
        """Zagruzhaet catalog, vse aliases/boards, ryady kontraktov i participant OI."""
        self._validate_period(start_date, end_date)
        catalog, series_table = self.fetch_series(asset)
        contracts = catalog.contracts.loc[
            (catalog.contracts["expiration_date"].dt.date >= start_date)
            & (catalog.contracts["start_date"].dt.date <= end_date)
        ].copy()
        if contracts.empty:
            raise ValueError("Net futures-kontraktov, peresekayushchih zaproshennyi period")
        boards, segments, boards_table = self.fetch_boards(contracts)
        active_segments = segments.loc[
            (segments["segment_end"].dt.date >= start_date)
            & (segments["segment_start"].dt.date <= end_date)
        ].copy()
        if active_segments.empty:
            raise ValueError("Net board-segmentov, peresekayushchih zaproshennyi period")
        artifacts: dict[str, Any] = {}
        catalog_stem = f"{asset.asset_code}/catalog/series"
        artifacts["series"] = self._persist_table(
            catalog_stem,
            FetchedIssTable(
                contracts.reset_index(drop=True),
                series_table.pages,
                series_table.urls,
            ),
        )
        excluded_table = FetchedIssTable(
            catalog.excluded,
            series_table.pages,
            series_table.urls,
        )
        artifacts["excluded"] = self._persist_table(
            f"{asset.asset_code}/catalog/excluded",
            excluded_table,
        )
        artifacts["boards"] = self._persist_table(
            f"{asset.asset_code}/catalog/boards",
            FetchedIssTable(boards, boards_table.pages, boards_table.urls),
        )
        segments_table = FetchedIssTable(active_segments, boards_table.pages, boards_table.urls)
        artifacts["segments"] = self._persist_table(
            f"{asset.asset_code}/catalog/segments",
            segments_table,
        )
        daily_rows = 0
        candle_rows = 0
        segment_artifacts: list[dict[str, Any]] = []
        for row in active_segments.to_dict("records"):
            segment_start = max(start_date, row["segment_start"].date())
            segment_end = min(end_date, row["segment_end"].date())
            daily = self.fetch_daily(
                asset,
                str(row["secid"]),
                str(row["boardid"]),
                segment_start,
                segment_end,
            )
            segment_stem = _safe_stem(str(row["canonical_segment_id"]))
            prefix = f"{asset.asset_code}/segments/{segment_stem}"
            candles_artifact: dict[str, dict[str, Any]] | None = None
            if include_candles:
                candles = self.fetch_candles(
                    asset,
                    str(row["secid"]),
                    str(row["boardid"]),
                    segment_start,
                    segment_end,
                )
                candles_artifact = self._persist_table(f"{prefix}/candles_10m", candles)
                candle_rows += len(candles.frame)
            segment_artifacts.append(
                {
                    "canonical_segment_id": row["canonical_segment_id"],
                    "canonical_contract_id": row["canonical_contract_id"],
                    "secid": row["secid"],
                    "boardid": row["boardid"],
                    "requested_start": segment_start,
                    "requested_end": segment_end,
                    "daily": self._persist_table(f"{prefix}/daily", daily),
                    "candles_10m": candles_artifact,
                }
            )
            daily_rows += len(daily.frame)
        participant_oi = self.fetch_participant_oi(asset, start_date, end_date)
        artifacts["participant_oi"] = self._persist_table(
            f"{asset.asset_code}/participant_oi",
            participant_oi,
        )
        manifest_path = _bounded_path(
            self.root,
            "processed",
            "futures_v5",
            asset.asset_code,
            f"manifest_{start_date.isoformat()}_{end_date.isoformat()}.json",
        )
        manifest = {
            "schema_version": 1,
            "source": "official anonymous MOEX ISS",
            "asset": asdict(asset),
            "requested_start": start_date,
            "requested_end": end_date,
            "protected_from": self.settings.protected_from,
            "pagination": {
                "candles_page_size": CANDLE_PAGE_SIZE,
                "candles_included": include_candles,
                "daily": "cursor_to_exact_total",
                "participant_oi_window_days": self.settings.oi_window_days,
                "participant_oi_coverage_tolerance_days": (
                    self.settings.oi_coverage_tolerance_days
                ),
            },
            "counts": {
                "contracts": len(contracts),
                "excluded": len(catalog.excluded),
                "board_segments": len(active_segments),
                "daily_rows": daily_rows,
                "candle_rows": candle_rows,
                "participant_oi_rows": len(participant_oi.frame),
            },
            "quality": {
                "participant_oi_raw_time_inversion_count": int(
                    participant_oi.frame.attrs.get("raw_time_inversion_count", 0)
                ),
            },
            "catalog_artifacts": artifacts,
            "segment_artifacts": segment_artifacts,
        }
        write_json(manifest_path, manifest)
        return FuturesAssetDownloadResult(
            asset_code=asset.asset_code,
            start_date=start_date,
            end_date=end_date,
            contracts=len(contracts),
            excluded=len(catalog.excluded),
            board_segments=len(active_segments),
            daily_rows=daily_rows,
            candle_rows=candle_rows,
            participant_oi_rows=len(participant_oi.frame),
            manifest_path=manifest_path,
        )


def download_futures_asset(
    root: Path,
    asset: FuturesAssetSpec,
    start_date: date,
    end_date: date,
    session: requests.Session | None = None,
    settings: FuturesDownloadSettings | None = None,
    include_candles: bool = True,
) -> FuturesAssetDownloadResult:
    """Vypolnyaet odnu izolirovannuyu zagruzku i korrektno zakryvaet svoi Session."""
    with FuturesIssDownloader(root, session=session, settings=settings) as downloader:
        return downloader.download_asset(
            asset,
            start_date,
            end_date,
            include_candles=include_candles,
        )


def _parse_cli_date(value: str) -> date:
    """Prevrashchaet CLI-datu ISO v date s ponyatnoi oshibkoi."""
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Nekorrektnaya ISO-data: {value}") from error


def main(argv: list[str] | None = None) -> int:
    """Zapuskaet development-only zagruzku iz `python -m` bez izmeneniya osnovnogo CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Strict MOEX ISS futures downloader")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True, choices=("SI", "RI", "BR", "MIX"))
    parser.add_argument("--from", dest="start_date", required=True)
    parser.add_argument("--till", dest="end_date", required=True)
    parser.add_argument("--daily-only", action="store_true")
    arguments = parser.parse_args(argv)
    start_date = _parse_cli_date(arguments.start_date)
    end_date = _parse_cli_date(arguments.end_date)
    for symbol in arguments.symbols:
        result = download_futures_asset(
            arguments.root,
            FuturesAssetSpec.from_symbol(symbol),
            start_date,
            end_date,
            include_candles=not arguments.daily_only,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
