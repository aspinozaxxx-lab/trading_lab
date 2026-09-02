"""Collect replayable stock-futures and realized-dividend source data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_calendar_spread_source as shared
from market_lab.futures import moex_dividend_calendar_spread_source as dividend_source
from market_lab.futures.market_data import parse_iss_page_cursor
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_stock_futures_cash_carry_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "a97377752e7f64997be1b5307c9e042983ccf5e8d983cd5fb9b2679211053c14"
)
SOURCE_START: Final[date] = date(2023, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[date] = date(2026, 1, 1)
ASSETS: Final[tuple[str, ...]] = ("GAZR", "SBRF", "ROSN", "TATN", "NOTK")
EQUITY_SECIDS: Final[dict[str, str]] = {
    "GAZR": "GAZP",
    "SBRF": "SBER",
    "ROSN": "ROSN",
    "TATN": "TATN",
    "NOTK": "NVTK",
}
EXPECTED_COUNTS: Final[dict[str, int]] = {
    "GAZR": 12,
    "SBRF": 12,
    "ROSN": 12,
    "TATN": 13,
    "NOTK": 12,
}
DIVIDEND_REQUIRED: Final[frozenset[str]] = frozenset(
    {"secid", "isin", "registryclosedate", "value", "currencyid"}
)
CONTRACT_COLUMNS: Final[tuple[str, ...]] = (
    "contract_id",
    "logical_asset",
    "asset_code",
    "spot_secid",
    "secid",
    "series_start",
    "expiration",
    "board_id",
    "board_history_from",
    "board_history_till",
    "request_from",
    "request_till",
)
DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "available_at",
    "contract_id",
    "logical_asset",
    "asset_code",
    "spot_secid",
    "secid",
    "board_id",
    "expiration",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "waprice",
    "volume",
    "value",
    "num_trades",
    "open_interest",
    "open_interest_value",
    "reported_trade_activity",
    "ohlc_complete",
    "has_settlement",
)
DIVIDEND_COLUMNS: Final[tuple[str, ...]] = (
    "logical_asset",
    "spot_secid",
    "isin",
    "registry_close_date",
    "value",
    "currency_id",
    "outcome_reference_only",
    "retrieved_at_utc",
)
FORBIDDEN: Final[tuple[str, ...]] = (
    "basis",
    "return",
    "target",
    "label",
    "signal",
    "prediction",
    "equity",
    "pnl",
    "profit",
)


@dataclass(frozen=True, slots=True)
class AssetSpec:
    asset_code: str
    logical_symbol: str
    security_prefix: str
    engine: str = "futures"
    market: str = "forts"
    primary_board: str = "RFUD"
    timezone: str = "Europe/Moscow"

    @classmethod
    def from_symbol(cls, symbol: str) -> AssetSpec:
        item = dividend_source.DividendAssetSpec.from_symbol(symbol)
        return cls(item.asset_code, str(item.logical_symbol), str(item.security_prefix))


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    output: Path
    dependencies: dict[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _project_path(value: str, required_root: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe stock cash-carry source path: {value}")
    if relative.parts[0].lower() != required_root.lower():
        raise ValueError(f"stock cash-carry path must start with {required_root}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = sha256_file(CONFIG_PATH)
    sidecar = CONFIG_PATH.with_suffix(".sha256")
    declared = sidecar.read_text(encoding="utf-8-sig").split()[0].lower()
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("stock cash-carry source config must be an object")
    period = payload["period"]
    universe = payload["universe"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_stock_futures_cash_carry_source_v1"
        or payload.get("scope")
        != "source_only_no_basis_returns_targets_signals_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or date.fromisoformat(period["start"]) != SOURCE_START
        or date.fromisoformat(period["end"]) != SOURCE_END
        or date.fromisoformat(period["protected_from"]) != PROTECTED_FROM
        or tuple(universe["logical_assets"]) != ASSETS
        or universe["equity_secids"] != EQUITY_SECIDS
        or {key: int(value) for key, value in universe["exact_contract_counts"].items()}
        != EXPECTED_COUNTS
        or int(universe["exact_contract_count"]) != sum(EXPECTED_COUNTS.values())
        or payload["output"]["immutable"] is not True
    ):
        raise ValueError("stock cash-carry source protocol drifted")
    dependencies: dict[str, str] = {}
    sections = (
        "identity_source",
        "existing_spot_source",
        "anticipated_cashflow_source",
        "ruonia_source",
    )
    for section_name in sections:
        section = payload[section_name]
        root = _project_path(section["root"], "data")
        for key, declaration in section.items():
            if key in {"root", "source_manifest_sha256", "files"}:
                continue
            if not isinstance(declaration, Mapping) or "file" not in declaration:
                continue
            path = root / declaration["file"]
            expected = str(declaration["sha256"])
            if sha256_file(path) != expected:
                raise ValueError(f"stock cash-carry dependency drifted: {section_name}.{key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"stock cash-carry rows drifted: {section_name}.{key}")
            dependencies[str(path.relative_to(PROJECT_ROOT))] = expected
        if section_name == "existing_spot_source":
            for secid, declaration in section["files"].items():
                path = root / declaration["file"]
                expected = str(declaration["sha256"])
                if sha256_file(path) != expected:
                    raise ValueError(f"stock cash-carry spot drifted: {secid}")
                if pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"]):
                    raise ValueError(f"stock cash-carry spot rows drifted: {secid}")
                dependencies[str(path.relative_to(PROJECT_ROOT))] = expected
    output = _project_path(payload["output"]["directory"], "data")
    return Protocol(payload, actual, output, dependencies)


def _identity_raw_path(protocol: Protocol) -> Path:
    section = protocol.payload["identity_source"]
    return _project_path(section["root"], "data") / section["raw"]["file"]


def _series_records(protocol: Protocol) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with gzip.open(_identity_raw_path(protocol), "rt", encoding="utf-8") as stream:
        for line in stream:
            raw = json.loads(line)
            if raw.get("kind") == "series":
                records[str(raw["logical_asset"])] = raw
    if set(records) != set(ASSETS):
        raise ValueError("stock cash-carry source lacks exact raw series identities")
    return records


def build_contract_catalog(protocol: Protocol) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    identity = protocol.payload["identity_source"]
    catalog_path = _project_path(identity["root"], "data") / identity["catalog"]["file"]
    spread_catalog = pd.read_parquet(catalog_path)
    expected_secids = {
        asset: set(protocol.payload["universe"]["exact_secids"][asset]) for asset in ASSETS
    }
    raw_series = _series_records(protocol)
    records: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    for asset in ASSETS:
        rows = spread_catalog.loc[spread_catalog["logical_asset"].eq(asset)]
        legs = set(rows["near_secid"].astype(str)) | set(rows["far_secid"].astype(str))
        if legs != expected_secids[asset]:
            raise ValueError(f"stock cash-carry exact leg set drifted: {asset}")
        raw = raw_series[asset]
        series = iss._parse_iss_block(raw["payload"], "series", shared.SERIES_REQUIRED_COLUMNS)
        series = series.loc[series["asset_code"].astype(str).eq(asset)].copy()
        series["start_date"] = pd.to_datetime(series["start_date"], errors="coerce")
        series["expiration_date"] = pd.to_datetime(
            series["expiration_date"], errors="coerce"
        )
        selected = series.loc[series["secid"].astype(str).isin(legs)]
        if set(selected["secid"].astype(str)) != legs or selected["expiration_date"].isna().any():
            raise ValueError(f"stock cash-carry selected series drifted: {asset}")
        for row in selected.itertuples(index=False):
            expiration = pd.Timestamp(row.expiration_date).normalize()
            series_start = pd.Timestamp(row.start_date).normalize()
            records.append(
                {
                    "contract_id": f"{asset}:{row.secid}:{expiration.date()}",
                    "logical_asset": asset,
                    "asset_code": asset,
                    "spot_secid": EQUITY_SECIDS[asset],
                    "secid": str(row.secid),
                    "series_start": series_start,
                    "expiration": expiration,
                }
            )
        preserved.append(raw)
    frame = pd.DataFrame(records)
    if len(frame) != 61 or frame["contract_id"].duplicated().any():
        raise ValueError("stock cash-carry contract catalog count/identity drifted")
    return frame.sort_values(["logical_asset", "expiration", "secid"], ignore_index=True), preserved


def _normalize_history(payload: dict[str, Any]) -> dict[str, Any]:
    return dividend_source._blank_assetcode_as_missing(payload)


def _parse_daily(payload: dict[str, Any], row: Mapping[str, Any]) -> tuple[pd.DataFrame, Any]:
    fake = {
        "spread_id": row["contract_id"],
        "logical_asset": row["logical_asset"],
        "asset_code": row["asset_code"],
        "secid": row["secid"],
        "board_id": row["board_id"],
        "near_secid": row["secid"],
        "far_secid": row["secid"],
        "spread_last_trade": row["expiration"],
        "near_expiration": row["expiration"],
        "far_expiration": row["expiration"],
    }
    parsed, cursor = shared.parse_spread_history_page(_normalize_history(payload), fake)
    if parsed.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS), cursor
    prices = parsed[["open", "high", "low", "close", "settle", "waprice"]]
    if (prices.stack().dropna() < 0.0).any():
        raise ValueError("stock futures source contains negative outright price")
    output = pd.DataFrame(
        {
            "trade_date": parsed["trade_date"],
            "available_at": parsed["available_at"],
            "contract_id": row["contract_id"],
            "logical_asset": row["logical_asset"],
            "asset_code": row["asset_code"],
            "spot_secid": row["spot_secid"],
            "secid": parsed["secid"],
            "board_id": parsed["board_id"],
            "expiration": row["expiration"],
            "open": parsed["open"],
            "high": parsed["high"],
            "low": parsed["low"],
            "close": parsed["close"],
            "settle": parsed["settle"],
            "waprice": parsed["waprice"],
            "volume": parsed["volume"],
            "value": parsed["value"],
            "num_trades": parsed["num_trades"],
            "open_interest": parsed["open_interest"],
            "open_interest_value": parsed["open_interest_value"],
            "reported_trade_activity": parsed["reported_trade_activity"],
            "ohlc_complete": parsed["ohlc_complete"],
            "has_settlement": parsed["has_settlement"],
        }
    )
    return output.loc[:, DAILY_COLUMNS], cursor


def _fetch_history(
    client: shared.OfficialMoexClient, asset: AssetSpec, row: Mapping[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    request_from = pd.Timestamp(row["request_from"]).date()
    request_till = pd.Timestamp(row["request_till"]).date()
    frames: list[pd.DataFrame] = []
    raw: list[dict[str, Any]] = []
    expected_total: int | None = None
    offset = 0
    for _ in range(shared.MAX_PAGES):
        url = iss.futures_daily_url(
            asset,
            str(row["secid"]),
            request_from,
            request_till,
            board_id=str(row["board_id"]),
            cursor_start=offset,
        )
        payload = client.get_json(url)
        original = iss._parse_iss_block(payload, "history", shared.HISTORY_REQUIRED_COLUMNS)
        frame, cursor = _parse_daily(payload, row)
        if cursor.index != offset:
            raise ValueError("stock futures history cursor index drifted")
        if expected_total is None:
            expected_total = cursor.total
        elif expected_total != cursor.total:
            raise ValueError("stock futures history cursor total drifted")
        expected_rows = min(cursor.page_size, max(cursor.total - cursor.index, 0))
        if len(original) != expected_rows or len(frame) != expected_rows:
            raise ValueError("stock futures history page truncated")
        raw.append(
            {
                "kind": "history",
                "logical_asset": row["logical_asset"],
                "contract_id": row["contract_id"],
                "secid": row["secid"],
                "request_from": request_from.isoformat(),
                "request_till": request_till.isoformat(),
                "url": url,
                "payload": payload,
            }
        )
        if not frame.empty:
            frames.append(frame)
        if cursor.next_index is None:
            break
        if cursor.next_index <= offset:
            raise ValueError("stock futures history cursor did not advance")
        offset = cursor.next_index
    else:
        raise ValueError("stock futures history exceeded maximum pages")
    combined = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=DAILY_COLUMNS)
    )
    if len(combined) != int(expected_total or 0):
        raise ValueError("stock futures history total drifted")
    return combined, raw


def _dividend_url(secid: str, offset: int) -> str:
    return (
        f"https://iss.moex.com/iss/securities/{quote(secid, safe='')}/dividends.json"
        f"?iss.meta=off&iss.only=dividends,dividends.cursor&start={offset}"
    )


def _parse_dividends(
    payload: dict[str, Any], asset: str, retrieved_at: pd.Timestamp
) -> tuple[pd.DataFrame, Any]:
    frame = iss._parse_iss_block(payload, "dividends", DIVIDEND_REQUIRED)
    cursor = parse_iss_page_cursor(payload, "dividends")
    if frame.empty:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS), cursor
    secid = EQUITY_SECIDS[asset]
    if (frame["secid"].astype(str) != secid).any():
        raise ValueError("dividend endpoint returned another security")
    dates = pd.to_datetime(frame["registryclosedate"], errors="raise").dt.normalize()
    values = pd.to_numeric(frame["value"], errors="raise")
    if (~np.isfinite(values) | values.lt(0.0)).any():
        raise ValueError("invalid realized dividend value")
    output = pd.DataFrame(
        {
            "logical_asset": asset,
            "spot_secid": secid,
            "isin": frame["isin"].astype(str),
            "registry_close_date": dates,
            "value": values,
            "currency_id": frame["currencyid"].astype(str),
            "outcome_reference_only": True,
            "retrieved_at_utc": retrieved_at,
        }
    )
    mask = dates.dt.date.between(SOURCE_START, SOURCE_END)
    return output.loc[mask, DIVIDEND_COLUMNS].reset_index(drop=True), cursor


def _fetch_dividends(
    client: shared.OfficialMoexClient, asset: str, retrieved_at: pd.Timestamp
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    raw: list[dict[str, Any]] = []
    expected_total: int | None = None
    offset = 0
    for _ in range(shared.MAX_PAGES):
        url = _dividend_url(EQUITY_SECIDS[asset], offset)
        payload = client.get_json(url)
        original = iss._parse_iss_block(payload, "dividends", DIVIDEND_REQUIRED)
        frame, cursor = _parse_dividends(payload, asset, retrieved_at)
        if cursor.index != offset:
            raise ValueError("dividend cursor index drifted")
        if expected_total is None:
            expected_total = cursor.total
        elif expected_total != cursor.total:
            raise ValueError("dividend cursor total drifted")
        expected_rows = min(cursor.page_size, max(cursor.total - cursor.index, 0))
        if len(original) != expected_rows:
            raise ValueError("dividend page truncated")
        raw.append(
            {
                "kind": "dividends",
                "logical_asset": asset,
                "equity_secid": EQUITY_SECIDS[asset],
                "url": url,
                "payload": payload,
                "retrieved_at_utc": retrieved_at.isoformat(),
            }
        )
        if not frame.empty:
            frames.append(frame)
        if cursor.next_index is None:
            break
        offset = int(cursor.next_index)
    else:
        raise ValueError("dividend history exceeded maximum pages")
    return (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DIVIDEND_COLUMNS),
        raw,
    )


def _raw_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    return gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0)


def _read_raw(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        value["rows"] = int(rows)
    return value


def _forbidden(frame: pd.DataFrame) -> bool:
    return any(any(fragment in str(column).lower() for fragment in FORBIDDEN) for column in frame)


def collect(protocol: Protocol, client: shared.OfficialMoexClient | None = None) -> Path:
    final = protocol.output.resolve()
    if final.exists():
        raise FileExistsError(f"stock cash-carry source exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    own_client = client is None
    active = client or shared.OfficialMoexClient()
    try:
        base_catalog, raw_records = build_contract_catalog(protocol)
        contract_rows: list[dict[str, Any]] = []
        daily_frames: list[pd.DataFrame] = []
        for row in base_catalog.to_dict("records"):
            asset = AssetSpec.from_symbol(str(row["logical_asset"]))
            board_url = iss.futures_boards_url(str(row["secid"]))
            board_payload = active.get_json(board_url)
            board = shared._select_board(
                board_payload,
                {
                    **row,
                    "spread_id": row["contract_id"],
                    "spread_last_trade": row["expiration"],
                },
            )
            enriched = {**row, **board}
            enriched["request_from"] = pd.Timestamp(
                max(
                    SOURCE_START,
                    pd.Timestamp(row["series_start"]).date(),
                    pd.Timestamp(board["board_history_from"]).date(),
                )
            )
            enriched["request_till"] = pd.Timestamp(
                min(
                    SOURCE_END,
                    pd.Timestamp(row["expiration"]).date(),
                    pd.Timestamp(board["board_history_till"]).date(),
                )
            )
            raw_records.append(
                {
                    "kind": "boards",
                    "logical_asset": row["logical_asset"],
                    "contract_id": row["contract_id"],
                    "secid": row["secid"],
                    "url": board_url,
                    "payload": board_payload,
                }
            )
            daily, history_raw = _fetch_history(active, asset, enriched)
            raw_records.extend(history_raw)
            if not daily.empty:
                daily_frames.append(daily)
            contract_rows.append(enriched)
        retrieved_at = pd.Timestamp.now(tz="UTC")
        dividend_frames: list[pd.DataFrame] = []
        for asset in ASSETS:
            dividends, dividend_raw = _fetch_dividends(active, asset, retrieved_at)
            raw_records.extend(dividend_raw)
            if not dividends.empty:
                dividend_frames.append(dividends)
        catalog = pd.DataFrame(contract_rows, columns=CONTRACT_COLUMNS).sort_values(
            ["logical_asset", "expiration", "secid"], ignore_index=True
        )
        daily = pd.concat(daily_frames, ignore_index=True).sort_values(
            ["trade_date", "logical_asset", "expiration", "secid"], ignore_index=True
        )
        dividends = (
            pd.concat(dividend_frames, ignore_index=True).sort_values(
                ["registry_close_date", "logical_asset"], ignore_index=True
            )
            if dividend_frames
            else pd.DataFrame(columns=DIVIDEND_COLUMNS)
        )
        if len(catalog) != 61 or daily.duplicated(["trade_date", "contract_id"]).any():
            raise ValueError("stock cash-carry source catalog/daily identity failed")
        if any(_forbidden(frame) for frame in (catalog, daily, dividends)):
            raise ValueError("stock cash-carry source leaked outcome columns")
        if pd.to_datetime(daily["trade_date"]).dt.date.ge(PROTECTED_FROM).any():
            raise ValueError("stock cash-carry daily source crossed protected period")
        if not dividends.empty and pd.to_datetime(dividends["registry_close_date"]).dt.date.ge(
            PROTECTED_FROM
        ).any():
            raise ValueError("stock cash-carry dividend source crossed protected period")
        paths = {
            "contracts": temporary / "contracts.parquet",
            "futures_daily": temporary / "futures_daily.parquet",
            "realized_dividends": temporary / "realized_dividends.parquet",
            "raw": temporary / "official_moex_responses.jsonl.gz",
        }
        _write_parquet(paths["contracts"], catalog)
        _write_parquet(paths["futures_daily"], daily)
        _write_parquet(paths["realized_dividends"], dividends)
        atomic_write_bytes(paths["raw"], _raw_bytes(raw_records))
        artifacts = {
            "contracts": _artifact(paths["contracts"], len(catalog)),
            "futures_daily": _artifact(paths["futures_daily"], len(daily)),
            "realized_dividends": _artifact(
                paths["realized_dividends"], len(dividends)
            ),
            "raw": _artifact(paths["raw"], len(raw_records)),
        }
        manifest = {
            "bundle_id": "moex-stock-futures-cash-carry-source-2023-2025-v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": sha256_file(Path(__file__)),
            "source_only": True,
            "contains_basis_returns_targets_signals_predictions_equity_or_pnl": False,
            "realized_dividends_outcome_reference_only": True,
            "live_trading_allowed": False,
            "counts": {
                "contracts": len(catalog),
                "futures_daily_rows": len(daily),
                "realized_dividend_rows": len(dividends),
                "raw_responses": len(raw_records),
                "by_asset": {
                    asset: int(catalog["logical_asset"].eq(asset).sum()) for asset in ASSETS
                },
            },
            "artifacts": artifacts,
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{sha256_file(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()
    return final


def audit(protocol: Protocol) -> dict[str, bool]:
    root = protocol.output.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    sidecar = (root / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0]
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar == sha256_file(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == protocol.config_sha256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == sha256_file(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "outcome_reference_only": manifest["realized_dividends_outcome_reference_only"]
        is True,
        "live_forbidden": manifest["live_trading_allowed"] is False,
    }
    frames: dict[str, pd.DataFrame] = {}
    for name in ("contracts", "futures_daily", "realized_dividends"):
        declaration = manifest["artifacts"][name]
        path = root / declaration["file"]
        checks[f"{name}_sha_exact"] = sha256_file(path) == declaration["sha256"]
        checks[f"{name}_bytes_exact"] = path.stat().st_size == declaration["bytes"]
        checks[f"{name}_rows_exact"] = (
            pq.ParquetFile(path).metadata.num_rows == declaration["rows"]
        )
        frames[name] = pd.read_parquet(path)
        checks[f"{name}_outcome_columns_absent"] = not _forbidden(frames[name])
    raw_declaration = manifest["artifacts"]["raw"]
    raw_path = root / raw_declaration["file"]
    checks["raw_sha_exact"] = sha256_file(raw_path) == raw_declaration["sha256"]
    checks["raw_bytes_exact"] = raw_path.stat().st_size == raw_declaration["bytes"]
    raw = _read_raw(raw_path)
    checks["raw_rows_exact"] = len(raw) == raw_declaration["rows"]
    catalog = frames["contracts"]
    daily = frames["futures_daily"]
    dividends = frames["realized_dividends"]
    checks["catalog_columns_exact"] = tuple(catalog.columns) == CONTRACT_COLUMNS
    checks["daily_columns_exact"] = tuple(daily.columns) == DAILY_COLUMNS
    checks["dividend_columns_exact"] = tuple(dividends.columns) == DIVIDEND_COLUMNS
    checks["contract_count_exact"] = len(catalog) == 61
    checks["asset_counts_exact"] = {
        asset: int(catalog["logical_asset"].eq(asset).sum()) for asset in ASSETS
    } == EXPECTED_COUNTS
    checks["daily_identity_unique"] = not daily.duplicated(["trade_date", "contract_id"]).any()
    checks["daily_before_protected"] = bool(
        daily.empty or pd.to_datetime(daily["trade_date"]).dt.date.lt(PROTECTED_FROM).all()
    )
    checks["dividends_before_protected"] = bool(
        dividends.empty
        or pd.to_datetime(dividends["registry_close_date"]).dt.date.lt(PROTECTED_FROM).all()
    )
    index = catalog.set_index("contract_id", drop=False)
    replay_daily: list[pd.DataFrame] = []
    replay_dividends: list[pd.DataFrame] = []
    board_count = 0
    series_count = 0
    dividend_page_count = 0
    for item in raw:
        kind = item["kind"]
        if kind == "series":
            iss._parse_iss_block(item["payload"], "series", shared.SERIES_REQUIRED_COLUMNS)
            series_count += 1
            continue
        if kind == "boards":
            row = index.loc[item["contract_id"]]
            selected = shared._select_board(
                item["payload"],
                {
                    **row.to_dict(),
                    "spread_id": row["contract_id"],
                    "spread_last_trade": row["expiration"],
                },
            )
            if selected["board_id"] != row["board_id"]:
                raise ValueError("stock cash-carry board replay drifted")
            board_count += 1
            continue
        if kind == "history":
            row = index.loc[item["contract_id"]]
            frame, _ = _parse_daily(item["payload"], row)
            if not frame.empty:
                replay_daily.append(frame)
            continue
        if kind == "dividends":
            retrieved = pd.Timestamp(item["retrieved_at_utc"])
            frame, _ = _parse_dividends(item["payload"], item["logical_asset"], retrieved)
            if not frame.empty:
                replay_dividends.append(frame)
            dividend_page_count += 1
            continue
        raise ValueError(f"unknown stock cash-carry raw kind: {kind}")
    replayed_daily = pd.concat(replay_daily, ignore_index=True).sort_values(
        ["trade_date", "logical_asset", "expiration", "secid"], ignore_index=True
    )
    replayed_dividends = (
        pd.concat(replay_dividends, ignore_index=True).sort_values(
            ["registry_close_date", "logical_asset"], ignore_index=True
        )
        if replay_dividends
        else pd.DataFrame(columns=DIVIDEND_COLUMNS)
    )
    try:
        pd.testing.assert_frame_equal(replayed_daily, daily, check_dtype=False)
        checks["raw_daily_replay_exact"] = True
    except AssertionError:
        checks["raw_daily_replay_exact"] = False
    try:
        pd.testing.assert_frame_equal(replayed_dividends, dividends, check_dtype=False)
        checks["raw_dividend_replay_exact"] = True
    except AssertionError:
        checks["raw_dividend_replay_exact"] = False
    checks["raw_series_count_exact"] = series_count == len(ASSETS)
    checks["raw_board_count_exact"] = board_count == len(catalog)
    checks["raw_dividend_pages_present"] = dividend_page_count >= len(ASSETS)
    if not all(checks.values()):
        raise ValueError(f"stock cash-carry source audit failed: {checks}")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol()
    if not arguments.audit_only:
        print(collect(protocol))
    print(json.dumps(audit(protocol), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
