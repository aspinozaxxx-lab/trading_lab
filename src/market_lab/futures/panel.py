"""Causal'naya panel' real'nyh futures iz proverennyh lokal'nyh manifestov."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from market_lab.futures.roll import RollPlannerConfig, plan_causal_rolls
from market_lab.io_utils import write_json

PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)  # Granica netronutogo holdout.
REQUIRED_LOGICAL_ASSETS: Final[tuple[str, ...]] = (  # Fiksirovannyi cross-asset universe.
    "SI",
    "RI",
    "BR",
    "MIX",
)
MANIFEST_SCHEMA_VERSION: Final[int] = 1  # Podderzhivaemaya versiya manifesta downloadera.
PANEL_SCHEMA_VERSION: Final[int] = 1  # Versiya vosproizvodimoi paneli i ee audita.
HASH_BLOCK_BYTES: Final[int] = 1024 * 1024  # Razmer bloka potokovoi proverki SHA-256.
DAILY_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(  # Skhema contract daily.
    {
        "trade_date",
        "board_id",
        "secid",
        "asset_code",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "volume",
        "value",
        "num_trades",
        "open_interest",
        "reported_trade_activity",
        "ohlc_complete",
        "ohlc_missing_with_activity",
        "has_trade",
        "has_settlement",
    }
)
PARTICIPANT_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(  # Skhema participant OI.
    {
        "trade_date",
        "asset_code",
        "is_physical",
        "open_position_long",
        "open_position_short",
    }
)
PRICE_COLUMNS: Final[tuple[str, ...]] = (  # Cenovye polya aktivnogo kontrakta.
    "open",
    "high",
    "low",
    "close",
)
RAW_MARKET_COLUMNS: Final[tuple[str, ...]] = (  # Polya, nuzhnye feature i execution sloyam.
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "value",
    "num_trades",
    "open_interest",
    "reported_trade_activity",
    "ohlc_complete",
    "ohlc_missing_with_activity",
    "has_trade",
    "has_settlement",
)


@dataclass(frozen=True, slots=True)
class VerifiedFuturesAsset:
    """Hranit proverennye contract observations i participant OI odnogo asset."""

    logical_asset: str
    storage_asset: str
    manifest_path: Path
    manifest_sha256: str
    observations: pd.DataFrame
    participant_oi: pd.DataFrame
    verified_artifact_count: int


@dataclass(frozen=True, slots=True)
class FuturesPanelBuildResult:
    """Hranit long feature-panel', active contract map, source rows i audit."""

    panel: pd.DataFrame
    active_contract_map: pd.DataFrame
    contract_observations: pd.DataFrame
    audit: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FuturesPanelArtifactPaths:
    """Vozvrashchaet puti atomarno zapisannyh development-artefaktov."""

    panel_path: Path
    active_contract_map_path: Path
    contract_observations_path: Path
    audit_path: Path


def _logical_asset(value: object) -> str:
    """Privodit storage asset code k stabil'nomu logical kodu model'nogo universa."""
    normalized = str(value).strip().upper()
    return "RI" if normalized == "RTS" else normalized


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 artefakta bez zagruzki vsego faila v pamyat'."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(HASH_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


def _bounded_path(root: Path, relative: object) -> Path:
    """Razreshaet manifest path i zapreshchaet vyhod za data root."""
    resolved_root = root.resolve()
    target = resolved_root.joinpath(str(relative)).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"Artifact path vyshel iz data root: {target}") from error
    return target


def _parse_manifest_date(value: object, field: str) -> date:
    """Chitaet obyazatel'nuyu ISO-datu manifesta s ponyatnoi oshibkoi."""
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"Nekorrektnaya data manifesta {field}: {value}") from error


def _verify_url_holdout(url: str, protected_from: date) -> None:
    """Zapreshchaet raw-zaprosy, kotorye mogli poluchit' ryady iz holdout."""
    query = parse_qs(urlparse(url).query)
    for key in ("from", "till", "date"):
        for raw_value in query.get(key, []):
            try:
                parsed = date.fromisoformat(raw_value)
            except ValueError:
                continue
            if parsed >= protected_from:
                raise ValueError(f"Raw URL peresekaet protected holdout: {url}")


def _verify_raw_archive(path: Path, expected_pages: int, protected_from: date) -> None:
    """Proveryaet gzip JSON, chislo stranic i vremennuyu granicu URL."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Nekorrektnyi raw archive: {path}") from error
    requests = payload.get("requests") if isinstance(payload, dict) else None
    if not isinstance(requests, list) or len(requests) != expected_pages:
        raise ValueError(f"Raw archive pages ne sovpadayut s manifestom: {path}")
    for request in requests:
        if not isinstance(request, dict):
            raise ValueError(f"Nekorrektnaya raw request v {path}")
        url = request.get("url")
        if not isinstance(url, str) or not isinstance(request.get("payload"), dict):
            raise ValueError(f"Raw request bez URL/payload v {path}")
        _verify_url_holdout(url, protected_from)


def _verify_artifact_record(
    data_root: Path,
    record: Mapping[str, Any],
    protected_from: date,
) -> Path:
    """Sveryaet path, bytes, SHA-256 i strukturnye schyotchiki odnogo artefakta."""
    required = {"path", "rows", "pages", "bytes", "sha256"}
    if missing := required - set(record):
        raise ValueError(f"V artifact record net polei: {sorted(missing)}")
    path = _bounded_path(data_root, record["path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_bytes = int(record["bytes"])
    expected_rows = int(record["rows"])
    expected_pages = int(record["pages"])
    if min(expected_bytes, expected_rows, expected_pages) < 0:
        raise ValueError(f"Otricatel'nyi schetchik artifact record: {path}")
    if path.stat().st_size != expected_bytes:
        raise ValueError(f"Artifact bytes ne sovpadayut s manifestom: {path}")
    if _sha256_file(path) != str(record["sha256"]).lower():
        raise ValueError(f"Artifact SHA-256 ne sovpadaet s manifestom: {path}")
    if path.suffix == ".parquet":
        parquet_rows = len(pd.read_parquet(path))
        if parquet_rows != expected_rows:
            raise ValueError(f"Artifact rows ne sovpadayut s manifestom: {path}")
    elif path.name.endswith(".json.gz"):
        _verify_raw_archive(path, expected_pages, protected_from)
    else:
        raise ValueError(f"Nepodderzhivaemyi artifact type: {path}")
    return path


def _artifact_pairs(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Sobiraet vse raw/parquet pary kataloga, segmentov i participant OI."""
    pairs: list[Mapping[str, Any]] = []
    catalog = manifest.get("catalog_artifacts")
    if not isinstance(catalog, dict):
        raise ValueError("Manifest ne soderzhit catalog_artifacts")
    pairs.extend(catalog.values())
    segments = manifest.get("segment_artifacts")
    if not isinstance(segments, list):
        raise ValueError("Manifest ne soderzhit segment_artifacts")
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("daily"), dict):
            raise ValueError("Nekorrektnyi segment artifact")
        pairs.append(segment["daily"])
        candles = segment.get("candles_10m")
        if candles is not None:
            if not isinstance(candles, dict):
                raise ValueError("Nekorrektnyi candles artifact")
            pairs.append(candles)
    return pairs


def _verify_artifact_pair(
    data_root: Path,
    pair: Mapping[str, Any],
    protected_from: date,
) -> tuple[Path, Path]:
    """Sveryaet raw i parquet, vklyuchaya odinakovye rows/pages v pare."""
    raw = pair.get("raw")
    parquet = pair.get("parquet")
    if not isinstance(raw, dict) or not isinstance(parquet, dict):
        raise ValueError("Artifact pair dolzhna soderzhat' raw i parquet")
    for field in ("rows", "pages"):
        if int(raw.get(field, -1)) != int(parquet.get(field, -2)):
            raise ValueError(f"Raw/parquet {field} ne sovpadayut")
    return (
        _verify_artifact_record(data_root, raw, protected_from),
        _verify_artifact_record(data_root, parquet, protected_from),
    )


def _verify_manifest_counts(
    manifest: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
) -> None:
    """Sveryaet aggregate counts s zapisannymi parquet artifact records."""
    counts = manifest.get("counts")
    catalog = manifest.get("catalog_artifacts")
    segments = manifest.get("segment_artifacts")
    if not isinstance(counts, dict) or not isinstance(catalog, dict) or not isinstance(
        segments, list
    ):
        raise ValueError("Manifest counts/catalog/segments imeyut nevernyi tip")
    expected = {
        "contracts": int(catalog["series"]["parquet"]["rows"]),
        "excluded": int(catalog["excluded"]["parquet"]["rows"]),
        "board_segments": int(catalog["segments"]["parquet"]["rows"]),
        "daily_rows": sum(int(item["daily"]["parquet"]["rows"]) for item in segments),
        "candle_rows": sum(
            int(item["candles_10m"]["parquet"]["rows"])
            for item in segments
            if item.get("candles_10m") is not None
        ),
        "participant_oi_rows": int(catalog["participant_oi"]["parquet"]["rows"]),
    }
    if any(int(counts.get(name, -1)) != value for name, value in expected.items()):
        raise ValueError("Aggregate counts ne sovpadayut s artifact records")
    if len(pairs) != 5 + len(segments) + sum(
        item.get("candles_10m") is not None for item in segments
    ):
        raise RuntimeError("Vnutrennyaya oshibka polnogo spiska artifact pairs")


def _normalize_daily_dates(frame: pd.DataFrame, protected_from: date) -> pd.DataFrame:
    """Normalizuet contract dates i blokiruet lyubuyu market-stroku holdout."""
    if missing := DAILY_REQUIRED_COLUMNS - set(frame.columns):
        raise ValueError(f"V daily parquet net kolonok: {sorted(missing)}")
    output = frame.copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="raise").dt.normalize()
    if (output["trade_date"].dt.date >= protected_from).any():
        raise ValueError("Daily parquet peresekaet protected holdout")
    return output


def _load_contract_observations(
    data_root: Path,
    manifest: Mapping[str, Any],
    protected_from: date,
) -> pd.DataFrame:
    """Stitchit storage aliases po manifest contract id bez overlap ili dublikatov."""
    catalog = manifest["catalog_artifacts"]
    series_path = _bounded_path(data_root, catalog["series"]["parquet"]["path"])
    series = pd.read_parquet(series_path)
    required_series = {"canonical_contract_id", "expiration_date", "asset_code"}
    if missing := required_series - set(series.columns):
        raise ValueError(f"V series parquet net kolonok: {sorted(missing)}")
    series["expiration_date"] = pd.to_datetime(
        series["expiration_date"], errors="raise"
    ).dt.normalize()
    expiration_by_id = series.drop_duplicates("canonical_contract_id").set_index(
        "canonical_contract_id"
    )["expiration_date"]
    pieces: list[pd.DataFrame] = []
    for segment in manifest["segment_artifacts"]:
        canonical_id = str(segment["canonical_contract_id"])
        if canonical_id not in expiration_by_id.index:
            raise ValueError(f"Segment contract id otsutstvuet v series: {canonical_id}")
        parquet_path = _bounded_path(
            data_root,
            segment["daily"]["parquet"]["path"],
        )
        frame = _normalize_daily_dates(pd.read_parquet(parquet_path), protected_from)
        if not frame.empty:
            if (frame["secid"].astype(str) != str(segment["secid"])).any():
                raise ValueError(f"Daily SECID ne sovpadaet s segment manifest: {canonical_id}")
            if (frame["board_id"].astype(str) != str(segment["boardid"])).any():
                raise ValueError(f"Daily BOARDID ne sovpadaet s segment manifest: {canonical_id}")
            requested_start = _parse_manifest_date(segment["requested_start"], "requested_start")
            requested_end = _parse_manifest_date(segment["requested_end"], "requested_end")
            if (
                frame["trade_date"].min().date() < requested_start
                or frame["trade_date"].max().date() > requested_end
            ):
                raise ValueError(f"Daily rows vyshli iz requested period: {canonical_id}")
        frame["canonical_contract_id"] = canonical_id
        frame["expiration_date"] = expiration_by_id.loc[canonical_id]
        frame["storage_secid"] = str(segment["secid"])
        pieces.append(frame)
    if not pieces:
        raise ValueError("Manifest ne soderzhit daily segmentov")
    observations = pd.concat(pieces, ignore_index=True)
    duplicate = observations.duplicated(
        ["trade_date", "canonical_contract_id"], keep=False
    )
    if duplicate.any():
        examples = observations.loc[
            duplicate,
            ["trade_date", "canonical_contract_id", "storage_secid"],
        ].head(5)
        raise ValueError(f"Storage aliases imeyut overlap/dublikat: {examples.to_dict('records')}")
    return observations.sort_values(
        ["trade_date", "expiration_date", "canonical_contract_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def _load_participant_oi(
    data_root: Path,
    manifest: Mapping[str, Any],
    protected_from: date,
) -> pd.DataFrame:
    """Chitaet proverennyi asset-level participant OI bez contract podmeny."""
    record = manifest["catalog_artifacts"]["participant_oi"]["parquet"]
    frame = pd.read_parquet(_bounded_path(data_root, record["path"]))
    if missing := PARTICIPANT_REQUIRED_COLUMNS - set(frame.columns):
        raise ValueError(f"V participant OI net kolonok: {sorted(missing)}")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if (frame["trade_date"].dt.date >= protected_from).any():
        raise ValueError("Participant OI peresekaet protected holdout")
    if frame.duplicated(["trade_date", "asset_code", "is_physical"]).any():
        raise ValueError("Povtor participant OI category")
    return frame.sort_values(["trade_date", "is_physical"]).reset_index(drop=True)


def verify_and_load_futures_manifest(
    data_root: Path,
    manifest_path: Path,
    protected_from: date = PROTECTED_HOLDOUT_START,
) -> VerifiedFuturesAsset:
    """Polnost'yu proveryaet manifest i tol'ko zatem vozvrashchaet market frames."""
    root = data_root.resolve()
    resolved_manifest = manifest_path.resolve()
    try:
        resolved_manifest.relative_to(root)
    except ValueError as error:
        raise ValueError("Manifest path vyshel iz data root") from error
    manifest = json.loads(resolved_manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or int(manifest.get("schema_version", -1)) != (
        MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError("Nepodderzhivaemaya versiya futures manifesta")
    requested_start = _parse_manifest_date(manifest.get("requested_start"), "requested_start")
    requested_end = _parse_manifest_date(manifest.get("requested_end"), "requested_end")
    if requested_start > requested_end or requested_end >= protected_from:
        raise ValueError("Manifest peresekaet protected holdout")
    manifest_protected = _parse_manifest_date(manifest.get("protected_from"), "protected_from")
    if manifest_protected != protected_from:
        raise ValueError("Manifest protected_from ne sovpadaet s panel policy")
    asset = manifest.get("asset")
    if not isinstance(asset, dict) or not str(asset.get("asset_code", "")).strip():
        raise ValueError("Manifest ne soderzhit asset metadata")
    pairs = _artifact_pairs(manifest)
    for pair in pairs:
        _verify_artifact_pair(root, pair, protected_from)
    _verify_manifest_counts(manifest, pairs)
    observations = _load_contract_observations(root, manifest, protected_from)
    participant = _load_participant_oi(root, manifest, protected_from)
    storage_asset = str(asset["asset_code"])
    if not observations["asset_code"].astype(str).eq(storage_asset).all():
        raise ValueError("Daily asset_code ne sovpadaet s manifestom")
    if not participant["asset_code"].astype(str).eq(storage_asset).all():
        raise ValueError("Participant asset_code ne sovpadaet s manifestom")
    return VerifiedFuturesAsset(
        logical_asset=_logical_asset(storage_asset),
        storage_asset=storage_asset,
        manifest_path=resolved_manifest,
        manifest_sha256=_sha256_file(resolved_manifest),
        observations=observations,
        participant_oi=participant,
        verified_artifact_count=2 * len(pairs),
    )


def discover_futures_manifests(data_root: Path) -> tuple[Path, ...]:
    """Nahodit tol'ko downloader-manifesty neposredstvennyh asset-katalogov."""
    base = data_root.resolve() / "processed" / "futures_v5"
    paths = tuple(sorted(base.glob("*/manifest_*.json")))
    if not paths:
        raise FileNotFoundError(f"Futures manifesty ne naideny v {base}")
    return paths


def derive_common_session_calendar(
    observations_by_asset: Mapping[str, pd.DataFrame],
) -> pd.DatetimeIndex:
    """Stroit peresechenie factual MOEX session dates bez business-day dopolneniya."""
    if not observations_by_asset:
        raise ValueError("Nuzhen hotya by odin asset dlya session calendar")
    calendars: list[pd.DatetimeIndex] = []
    for asset, frame in observations_by_asset.items():
        if "trade_date" not in frame:
            raise ValueError(f"V observations {asset} net trade_date")
        dates = pd.DatetimeIndex(pd.to_datetime(frame["trade_date"], errors="raise"))
        if dates.tz is not None:
            dates = dates.tz_localize(None)
        dates = dates.normalize().drop_duplicates().sort_values()
        if dates.empty:
            raise ValueError(f"Pustoi session calendar dlya {asset}")
        calendars.append(dates)
    common = calendars[0]
    for calendar in calendars[1:]:
        common = common.intersection(calendar, sort=True)
    if common.empty:
        raise ValueError("Net obshchih factual MOEX sessions")
    return common


def _normalize_core_observations(
    observations_by_asset: Mapping[str, pd.DataFrame],
    protected_from: date,
) -> dict[str, pd.DataFrame]:
    """Proveryaet logical universe, contract id, expiracii i vremennuyu granicu."""
    normalized: dict[str, pd.DataFrame] = {}
    for raw_asset, source in observations_by_asset.items():
        asset = _logical_asset(raw_asset)
        if asset in normalized:
            raise ValueError(f"Povtor logical asset posle normalizacii: {asset}")
        required = DAILY_REQUIRED_COLUMNS | {"canonical_contract_id", "expiration_date"}
        if missing := required - set(source.columns):
            raise ValueError(f"V observations {asset} net kolonok: {sorted(missing)}")
        frame = source.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
        frame["expiration_date"] = pd.to_datetime(
            frame["expiration_date"], errors="raise"
        ).dt.normalize()
        if (frame["trade_date"].dt.date >= protected_from).any():
            raise ValueError("Observations peresekayut protected holdout")
        if frame.duplicated(["trade_date", "canonical_contract_id"]).any():
            raise ValueError(f"Povtor contract/session v {asset}")
        frame["logical_asset"] = asset
        normalized[asset] = frame.sort_values(
            ["trade_date", "expiration_date", "canonical_contract_id"],
            kind="mergesort",
        ).reset_index(drop=True)
    if set(normalized) != set(REQUIRED_LOGICAL_ASSETS):
        raise ValueError(
            f"Nuzhen tochnyi universe {REQUIRED_LOGICAL_ASSETS}, poluchen {sorted(normalized)}"
        )
    return normalized


def _front_next_snapshot(
    observations: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    logical_asset: str,
) -> pd.DataFrame:
    """Stroit simultaneous front/next settle snapshot, dostupnyi na decision close."""
    rows: list[dict[str, Any]] = []
    for trading_date in calendar:
        today = observations.loc[
            (observations["trade_date"] == trading_date)
            & (observations["expiration_date"] >= trading_date)
        ].sort_values(["expiration_date", "canonical_contract_id"])
        front = today.iloc[0] if len(today) >= 1 else None
        following = today.iloc[1] if len(today) >= 2 else None
        front_settle = np.nan if front is None else front["settle"]
        next_settle = np.nan if following is None else following["settle"]
        front_expiry = pd.NaT if front is None else front["expiration_date"]
        next_expiry = pd.NaT if following is None else following["expiration_date"]
        distance = (
            np.nan
            if pd.isna(front_expiry) or pd.isna(next_expiry)
            else float((next_expiry - front_expiry).days)
        )
        valid_curve = all(
            (
                pd.notna(front_settle),
                pd.notna(next_settle),
                np.isfinite(float(front_settle)) if pd.notna(front_settle) else False,
                np.isfinite(float(next_settle)) if pd.notna(next_settle) else False,
                float(front_settle) > 0.0 if pd.notna(front_settle) else False,
                float(next_settle) > 0.0 if pd.notna(next_settle) else False,
                pd.notna(distance) and distance > 0.0,
            )
        )
        roll_yield = (
            (float(front_settle) / float(next_settle) - 1.0) * (365.0 / distance)
            if valid_curve
            else np.nan
        )
        rows.append(
            {
                "trade_date": trading_date,
                "asset_code": logical_asset,
                "curve_observed_through": trading_date,
                "curve_available_at": "decision_close",
                "front_contract_id": (
                    pd.NA if front is None else str(front["canonical_contract_id"])
                ),
                "next_contract_id": (
                    pd.NA if following is None else str(following["canonical_contract_id"])
                ),
                "front_settle": front_settle,
                "next_settle": next_settle,
                "front_expiration_date": front_expiry,
                "next_expiration_date": next_expiry,
                "front_days_to_expiry": (
                    np.nan if front is None else float((front_expiry - trading_date).days)
                ),
                "next_days_to_expiry": (
                    np.nan if following is None else float((next_expiry - trading_date).days)
                ),
                "roll_yield": roll_yield,
                "curve_valid": valid_curve,
            }
        )
    return pd.DataFrame(rows)


def _lag_participant_oi(
    participant: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    logical_asset: str,
) -> pd.DataFrame:
    """Perenosit participant snapshot na sleduyushchuyu factual session po yavnoi date."""
    if missing := PARTICIPANT_REQUIRED_COLUMNS - set(participant.columns):
        raise ValueError(f"V participant OI {logical_asset} net kolonok: {sorted(missing)}")
    source = participant.copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="raise").dt.normalize()
    if source.duplicated(["trade_date", "is_physical"]).any():
        raise ValueError(f"Povtor participant category v {logical_asset}")
    target_by_source = {
        pd.Timestamp(calendar[index]): pd.Timestamp(calendar[index + 1])
        for index in range(len(calendar) - 1)
    }
    source = source.loc[source["trade_date"].isin(target_by_source)].copy()
    source["participant_effective_date"] = source["trade_date"].map(target_by_source)
    wide_rows: list[dict[str, Any]] = []
    for source_date, snapshot in source.groupby("trade_date", sort=True):
        categories = {bool(row["is_physical"]): row for _, row in snapshot.iterrows()}
        output: dict[str, Any] = {
            "trade_date": target_by_source[pd.Timestamp(source_date)],
            "asset_code": logical_asset,
            "participant_source_date": source_date,
            "participant_lag_sessions": 1,
            "participant_snapshot_complete": set(categories) == {False, True},
        }
        for flag, prefix in ((True, "physical"), (False, "legal")):
            row = categories.get(flag)
            output[f"{prefix}_long"] = (
                np.nan if row is None else row["open_position_long"]
            )
            output[f"{prefix}_short"] = (
                np.nan if row is None else row["open_position_short"]
            )
        wide_rows.append(output)
    columns = [
        "trade_date",
        "asset_code",
        "participant_source_date",
        "participant_lag_sessions",
        "participant_snapshot_complete",
        "physical_long",
        "physical_short",
        "legal_long",
        "legal_short",
    ]
    return pd.DataFrame(wide_rows, columns=columns)


def _plan_with_bounded_calendar(
    observations: pd.DataFrame,
    output_calendar: pd.DatetimeIndex,
    expiry_calendar: pd.DatetimeIndex,
    config: RollPlannerConfig,
) -> pd.DataFrame:
    """Vyzyvaet planner s exact calendar i horizon-censored dal'nei expiraciei."""
    selected = observations.loc[observations["trade_date"].isin(output_calendar)].copy()
    planner_input = selected.copy()
    planner_input["asset_code"] = planner_input["logical_asset"]
    return plan_causal_rolls(
        planner_input,
        config=config,
        session_calendar=expiry_calendar,
    )


def _active_map_and_prices(
    observations: pd.DataFrame,
    plan: pd.DataFrame,
    logical_asset: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Svyazyvaet fakticheskii position id s raw row i causal'noi forward-popravkoi."""
    indexed = observations.set_index(["trade_date", "canonical_contract_id"], drop=False)
    active_rows: list[dict[str, Any]] = []
    panel_rows: list[dict[str, Any]] = []
    additive_offset = 0.0
    chain_id = 0
    reset_chain = True
    for item in plan.sort_values("effective_date", kind="mergesort").to_dict("records"):
        trading_date = pd.Timestamp(item["effective_date"])
        contract_value = item["position_contract_id"]
        contract_id = None if pd.isna(contract_value) else str(contract_value)
        raw: pd.Series | None = None
        if contract_id is not None:
            try:
                found = indexed.loc[(trading_date, contract_id)]
            except KeyError:
                found = None
            if isinstance(found, pd.DataFrame):
                raise RuntimeError("Povtor raw active contract row")
            raw = found
        action = str(item["action"])
        carry = action.startswith("carry_")
        plan_tradable = bool(item["tradable"])
        raw_open_valid = bool(
            raw is not None
            and pd.notna(raw["open"])
            and np.isfinite(float(raw["open"]))
            and float(raw["open"]) > 0.0
        )
        raw_ohlc_complete = bool(raw is not None and raw["ohlc_complete"])
        feature_input_valid = bool(
            plan_tradable
            and not carry
            and raw is not None
            and raw_ohlc_complete
            and all(
                pd.notna(raw[column]) and np.isfinite(float(raw[column]))
                for column in ("volume", "open_interest")
            )
        )
        if action == "roll" and plan_tradable:
            old_anchor = item["overlap_old_price"]
            new_anchor = item["overlap_new_price"]
            if not (
                pd.notna(old_anchor)
                and pd.notna(new_anchor)
                and np.isfinite(float(old_anchor))
                and np.isfinite(float(new_anchor))
            ):
                feature_input_valid = False
            else:
                additive_offset += float(old_anchor) - float(new_anchor)
        if action == "enter" and plan_tradable:
            if reset_chain:
                chain_id += 1
                additive_offset = 0.0
            reset_chain = False
        elif contract_id is None:
            reset_chain = True
        active: dict[str, Any] = {
            "effective_date": trading_date,
            "decision_date": item["decision_date"],
            "observed_through": item["observed_through"],
            "asset_code": logical_asset,
            "contract_id": contract_id or pd.NA,
            "secid": pd.NA if raw is None else raw["secid"],
            "expiration_date": pd.NaT if raw is None else raw["expiration_date"],
            "action": action,
            "reason": item["reason"],
            "roll": bool(item["roll"]),
            "plan_tradable": plan_tradable,
            "expiry_horizon_censored": bool(item["expiry_horizon_censored"]),
            "carry_unfilled": carry,
            "execution_open_available": raw_open_valid,
            "feature_input_valid": feature_input_valid,
            "chain_id": chain_id,
            "forward_additive_adjustment": additive_offset,
            "execution_price": item["execution_price"],
            "exit_execution_price": item["exit_execution_price"],
            "entry_execution_price": item["entry_execution_price"],
            "overlap_old_price": item["overlap_old_price"],
            "overlap_new_price": item["overlap_new_price"],
        }
        for column in RAW_MARKET_COLUMNS:
            active[column] = np.nan if raw is None else raw[column]
        active_rows.append(active)
        panel: dict[str, Any] = {
            "trade_date": trading_date,
            "asset_code": logical_asset,
            "active_contract_id": contract_id or pd.NA,
            "active_contract_action": action,
            "active_contract_reason": item["reason"],
            "active_contract_valid": feature_input_valid,
            "active_contract_carry_unfilled": carry,
            "active_expiry_horizon_censored": bool(
                item["expiry_horizon_censored"]
            ),
            "active_chain_id": chain_id,
        }
        for column in PRICE_COLUMNS:
            panel[column] = (
                float(raw[column]) + additive_offset
                if feature_input_valid and raw is not None
                else np.nan
            )
        for column in ("volume", "open_interest"):
            panel[column] = raw[column] if feature_input_valid and raw is not None else np.nan
        panel["raw_ohlc_missing_with_activity"] = bool(
            raw is not None and raw["ohlc_missing_with_activity"]
        )
        panel["raw_ohlc_complete"] = raw_ohlc_complete
        panel_rows.append(panel)
    active_frame = pd.DataFrame(active_rows)
    panel_frame = pd.DataFrame(panel_rows)
    for column in ("effective_date", "decision_date", "observed_through", "expiration_date"):
        active_frame[column] = pd.to_datetime(active_frame[column], errors="coerce")
    for column in ("asset_code", "contract_id", "secid", "action", "reason"):
        active_frame[column] = active_frame[column].astype("string")
    for column in (
        "roll",
        "plan_tradable",
        "expiry_horizon_censored",
        "carry_unfilled",
        "execution_open_available",
        "feature_input_valid",
        "reported_trade_activity",
        "ohlc_complete",
        "ohlc_missing_with_activity",
        "has_trade",
        "has_settlement",
    ):
        active_frame[column] = active_frame[column].astype("boolean")
    numeric_active = {
        "chain_id",
        "forward_additive_adjustment",
        "execution_price",
        "exit_execution_price",
        "entry_execution_price",
        "overlap_old_price",
        "overlap_new_price",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "volume",
        "value",
        "num_trades",
        "open_interest",
    }
    for column in numeric_active:
        active_frame[column] = pd.to_numeric(active_frame[column], errors="coerce")
    panel_frame["trade_date"] = pd.to_datetime(panel_frame["trade_date"], errors="raise")
    for column in (
        "asset_code",
        "active_contract_id",
        "active_contract_action",
        "active_contract_reason",
    ):
        panel_frame[column] = panel_frame[column].astype("string")
    for column in (
        "active_contract_valid",
        "active_contract_carry_unfilled",
        "active_expiry_horizon_censored",
        "raw_ohlc_missing_with_activity",
        "raw_ohlc_complete",
    ):
        panel_frame[column] = panel_frame[column].astype("boolean")
    for column in (*PRICE_COLUMNS, "volume", "open_interest", "active_chain_id"):
        panel_frame[column] = pd.to_numeric(panel_frame[column], errors="coerce")
    return active_frame, panel_frame


def build_causal_development_panel(
    observations_by_asset: Mapping[str, pd.DataFrame],
    participant_by_asset: Mapping[str, pd.DataFrame],
    roll_config: RollPlannerConfig | None = None,
    protected_from: date = PROTECTED_HOLDOUT_START,
    expiry_session_calendar: Sequence[object] | pd.DatetimeIndex | None = None,
) -> FuturesPanelBuildResult:
    """Stroit cross-asset panel' iz factual sessions s causal roll i as-of metkami."""
    observations = _normalize_core_observations(observations_by_asset, protected_from)
    participants = {_logical_asset(key): value for key, value in participant_by_asset.items()}
    if set(participants) != set(REQUIRED_LOGICAL_ASSETS):
        raise ValueError("Participant OI dolzhen pokryvat' ves' logical universe")
    calendar = derive_common_session_calendar(observations)
    if (calendar.date >= protected_from).any():
        raise ValueError("Common calendar peresekaet protected holdout")
    expiry_calendar = (
        calendar
        if expiry_session_calendar is None
        else pd.DatetimeIndex(pd.to_datetime(list(expiry_session_calendar), errors="raise"))
        .tz_localize(None)
        .normalize()
        .drop_duplicates()
        .sort_values()
    )
    if expiry_calendar.empty or not calendar.isin(expiry_calendar).all():
        raise ValueError("Expiry session calendar dolzhen pokryvat' common sessions")
    if (expiry_calendar.date >= protected_from).any():
        raise ValueError("Expiry session calendar peresekaet protected holdout")
    settings = roll_config or RollPlannerConfig()
    panels: list[pd.DataFrame] = []
    active_maps: list[pd.DataFrame] = []
    snapshots: list[pd.DataFrame] = []
    lagged_participants: list[pd.DataFrame] = []
    audit_assets: dict[str, Any] = {}
    contract_frames: list[pd.DataFrame] = []
    for asset in REQUIRED_LOGICAL_ASSETS:
        frame = observations[asset].loc[
            observations[asset]["trade_date"].isin(calendar)
        ].copy()
        plan = _plan_with_bounded_calendar(frame, calendar, expiry_calendar, settings)
        active_map, panel = _active_map_and_prices(frame, plan, asset)
        snapshot = _front_next_snapshot(frame, calendar, asset)
        lagged = _lag_participant_oi(participants[asset], calendar, asset)
        panels.append(panel)
        active_maps.append(active_map)
        snapshots.append(snapshot)
        lagged_participants.append(lagged)
        contract_frames.append(frame.assign(asset_code=asset))
        carry_count = int(active_map["carry_unfilled"].sum())
        action_counts = active_map["action"].astype(str).value_counts()
        audit_assets[asset] = {
            "contract_rows": len(frame),
            "contracts": int(frame["canonical_contract_id"].nunique()),
            "source_sessions": int(observations[asset]["trade_date"].nunique()),
            "common_sessions": len(calendar),
            "source_sessions_excluded_from_common": int(
                observations[asset]["trade_date"].nunique() - len(calendar)
            ),
            "ohlc_missing_with_activity_count": int(
                frame["ohlc_missing_with_activity"].sum()
            ),
            "settlement_only_count": int((~frame["has_trade"] & frame["has_settlement"]).sum()),
            "active_invalid_count": int((~active_map["feature_input_valid"]).sum()),
            "carry_unfilled_count": carry_count,
            "calendar_horizon_carry_count": int(
                action_counts.get("carry_calendar_horizon", 0)
            ),
            "horizon_censored_hold_count": int(
                active_map["expiry_horizon_censored"].sum()
            ),
            "missing_mark_carry_count": int(action_counts.get("carry_missing_mark", 0)),
            "unfilled_roll_count": int(action_counts.get("carry_unfilled_roll", 0)),
            "unfilled_exit_count": int(action_counts.get("carry_unfilled_exit", 0)),
            "roll_count": int(active_map["roll"].sum()),
        }
    panel = pd.concat(panels, ignore_index=True)
    panel = panel.merge(pd.concat(snapshots, ignore_index=True), on=["trade_date", "asset_code"])
    panel = panel.merge(
        pd.concat(lagged_participants, ignore_index=True),
        on=["trade_date", "asset_code"],
        how="left",
    )
    panel["participant_snapshot_complete"] = (
        panel["participant_snapshot_complete"].astype("boolean").fillna(False).astype(bool)
    )
    panel = panel.sort_values(["trade_date", "asset_code"], kind="mergesort").reset_index(
        drop=True
    )
    active_contract_map = pd.concat(active_maps, ignore_index=True).sort_values(
        ["effective_date", "asset_code"], kind="mergesort"
    ).reset_index(drop=True)
    contracts = pd.concat(contract_frames, ignore_index=True).sort_values(
        ["trade_date", "asset_code", "expiration_date", "canonical_contract_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    expected_rows = len(calendar) * len(REQUIRED_LOGICAL_ASSETS)
    if len(panel) != expected_rows or panel.duplicated(["trade_date", "asset_code"]).any():
        raise RuntimeError("Panel ne obrazovala polnyi common-session cross-asset snapshot")
    participant_dates = panel["participant_source_date"].notna()
    if (
        panel.loc[participant_dates, "participant_source_date"]
        >= panel.loc[participant_dates, "trade_date"]
    ).any():
        raise RuntimeError("Participant OI narushil strogo proshluyu as-of granicu")
    audit: dict[str, Any] = {
        "schema_version": PANEL_SCHEMA_VERSION,
        "protected_from": protected_from.isoformat(),
        "calendar_source": "intersection_of_factual_asset_trade_dates",
        "business_days_fabricated": 0,
        "calendar_start": calendar.min().date().isoformat(),
        "calendar_end": calendar.max().date().isoformat(),
        "common_session_count": len(calendar),
        "panel_rows": len(panel),
        "active_contract_rows": len(active_contract_map),
        "contract_observation_rows": len(contracts),
        "assets": audit_assets,
        "point_value_fabricated": False,
        "fee_fabricated": False,
        "initial_margin_fabricated": False,
        "broker_executable_pnl_supported": False,
    }
    return FuturesPanelBuildResult(panel, active_contract_map, contracts, audit)


def build_verified_futures_panel(
    data_root: Path,
    manifest_paths: Sequence[Path] | None = None,
    roll_config: RollPlannerConfig | None = None,
    protected_from: date = PROTECTED_HOLDOUT_START,
) -> FuturesPanelBuildResult:
    """Verificiruet vse real manifests, a zatem stroit odnu development-panel'."""
    paths = tuple(manifest_paths) if manifest_paths is not None else discover_futures_manifests(
        data_root
    )
    verified: dict[str, VerifiedFuturesAsset] = {}
    for path in paths:
        asset = verify_and_load_futures_manifest(data_root, path, protected_from)
        if asset.logical_asset in verified:
            raise ValueError(f"Povtor manifesta logical asset {asset.logical_asset}")
        verified[asset.logical_asset] = asset
    if set(verified) != set(REQUIRED_LOGICAL_ASSETS):
        raise ValueError(f"Manifesty ne pokryvayut universe {REQUIRED_LOGICAL_ASSETS}")
    result = build_causal_development_panel(
        {asset: verified[asset].observations for asset in REQUIRED_LOGICAL_ASSETS},
        {asset: verified[asset].participant_oi for asset in REQUIRED_LOGICAL_ASSETS},
        roll_config=roll_config,
        protected_from=protected_from,
    )
    audit = dict(result.audit)
    audit["source_manifests"] = {
        asset: {
            "path": verified[asset].manifest_path.as_posix(),
            "sha256": verified[asset].manifest_sha256,
            "verified_artifact_count": verified[asset].verified_artifact_count,
        }
        for asset in REQUIRED_LOGICAL_ASSETS
    }
    audit["verified_artifact_count"] = sum(
        item.verified_artifact_count for item in verified.values()
    )
    return FuturesPanelBuildResult(
        result.panel,
        result.active_contract_map,
        result.contract_observations,
        audit,
    )


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet Parquet ryadom s celevoi direktoriei."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_futures_panel(
    data_root: Path,
    result: FuturesPanelBuildResult,
    stem: str = "development_panel_2018_2025",
) -> FuturesPanelArtifactPaths:
    """Atomarno sohranyaet panel', active map, source rows i hash-audit v futures_v5."""
    output_root = data_root.resolve() / "processed" / "futures_v5"
    output_root.mkdir(parents=True, exist_ok=True)
    panel_path = output_root / f"{stem}.parquet"
    active_path = output_root / f"{stem}_active_contract_map.parquet"
    observations_path = output_root / f"{stem}_contract_observations.parquet"
    audit_path = output_root / f"{stem}_audit.json"
    _atomic_write_parquet(panel_path, result.panel)
    _atomic_write_parquet(active_path, result.active_contract_map)
    _atomic_write_parquet(observations_path, result.contract_observations)
    audit = dict(result.audit)
    audit["output_artifacts"] = {
        "panel": {
            "path": panel_path.as_posix(),
            "rows": len(result.panel),
            "bytes": panel_path.stat().st_size,
            "sha256": _sha256_file(panel_path),
        },
        "active_contract_map": {
            "path": active_path.as_posix(),
            "rows": len(result.active_contract_map),
            "bytes": active_path.stat().st_size,
            "sha256": _sha256_file(active_path),
        },
        "contract_observations": {
            "path": observations_path.as_posix(),
            "rows": len(result.contract_observations),
            "bytes": observations_path.stat().st_size,
            "sha256": _sha256_file(observations_path),
        },
    }
    write_json(audit_path, audit)
    return FuturesPanelArtifactPaths(panel_path, active_path, observations_path, audit_path)


def main(argv: list[str] | None = None) -> int:
    """Stroit i atomarno sohranyaet strogo development-only futures panel'."""
    import argparse

    parser = argparse.ArgumentParser(description="Build verified causal futures panel")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--stem", default="development_panel_2018_2025")
    arguments = parser.parse_args(argv)
    result = build_verified_futures_panel(arguments.data_root)
    paths = persist_futures_panel(arguments.data_root, result, stem=arguments.stem)
    print(json.dumps({**result.audit, "audit_path": paths.audit_path.as_posix()}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
