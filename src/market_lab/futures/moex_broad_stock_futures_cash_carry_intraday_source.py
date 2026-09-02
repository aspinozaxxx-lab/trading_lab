"""Collect sealed broad pre-2026 single-stock futures 10-minute candles."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final
from typing import Protocol as TypingProtocol
from urllib.parse import urlencode

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import iss, market_data
from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT
    / "configs/moex_broad_stock_futures_cash_carry_intraday_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "6bc8f4a25c3ff1fb63b0cda021ae003f77d8c4fd0c5b7341581269fd53199aec"
)
SOURCE_START: Final[date] = date(2023, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[date] = date(2026, 1, 1)
PAGE_LIMIT: Final[int] = 500
MAX_PAGES: Final[int] = 120
GENERIC_FUTURES: Final[Any] = SimpleNamespace(
    engine="futures", market="forts", timezone="Europe/Moscow"
)
CATALOG_COLUMNS: Final[tuple[str, ...]] = (
    "contract_id",
    "stock_secid",
    "secid",
    "asset_code",
    "series_start",
    "expiration",
)
SPEC_COLUMNS: Final[tuple[str, ...]] = CATALOG_COLUMNS + (
    "board_id",
    "lot_size_shares",
    "first_trade",
    "last_trade",
    "last_delivery",
    "request_from",
    "request_till",
)
CANDLE_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "end_timestamp",
    "available_at",
    "contract_id",
    "stock_secid",
    "asset_code",
    "secid",
    "board_id",
    "expiration",
    "lot_size_shares",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
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


class JsonClient(TypingProtocol):
    def get_json(self, url: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    output: Path


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def _safe_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe broad historical source path: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "processed"):
        raise ValueError("broad historical source must be under data/processed")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("broad historical source protocol must be an object")
    counts = payload["universe"]["exact_outright_contract_count_by_stock"]
    stocks = payload["universe"]["exact_stock_order"]
    dependency = payload["dependencies"]["fixed_universe_source"]
    dependency_path = PROJECT_ROOT / dependency["file"]
    if (
        actual != CONFIG_SHA256
        or actual != declared
        or payload.get("protocol_id")
        != "moex_broad_stock_futures_cash_carry_intraday_source_v1"
        or payload.get("live_trading_allowed") is not False
        or len(stocks) != 30
        or set(stocks) != set(counts)
        or sum(int(value) for value in counts.values()) != 339
        or int(counts["ENPG"]) != 0
        or int(payload["contract_selection"]["exact_total_must_equal"]) != 339
        or int(payload["official_sources"]["page_limit"]) != PAGE_LIMIT
        or payload["output"]["immutable"] is not True
        or _sha(dependency_path) != dependency["sha256"]
    ):
        raise ValueError("broad historical source protocol drifted")
    return Protocol(payload=payload, output=_safe_path(payload["output"]["directory"]))


def _series_url(protocol: Protocol, stock: str) -> str:
    query = urlencode(
        {
            "underlying_asset": stock,
            "show_expired": 1,
            "iss.meta": "off",
            "iss.only": "series",
            "series.columns": (
                "secid,name,start_date,expiration_date,asset_code,"
                "underlying_asset,is_traded"
            ),
        }
    )
    return f"{protocol.payload['official_sources']['series']}?{query}"


def select_catalog(raw: list[dict[str, Any]], protocol: Protocol) -> pd.DataFrame:
    by_stock = {str(item["stock_secid"]): item for item in raw}
    stocks = [str(value) for value in protocol.payload["universe"]["exact_stock_order"]]
    if set(by_stock) != set(stocks) or len(raw) != len(stocks):
        raise ValueError("broad historical series response identity drifted")
    pattern = re.compile(str(protocol.payload["contract_selection"]["secid_regex"]))
    rows: list[dict[str, Any]] = []
    factual_counts: dict[str, int] = {}
    for stock in stocks:
        frame = iss._parse_iss_block(
            by_stock[stock]["payload"],
            "series",
            frozenset(
                {
                    "secid",
                    "name",
                    "start_date",
                    "expiration_date",
                    "asset_code",
                    "underlying_asset",
                    "is_traded",
                }
            ),
        )
        frame["series_start"] = pd.to_datetime(frame["start_date"], errors="raise")
        frame["expiration"] = pd.to_datetime(
            frame["expiration_date"], errors="raise"
        )
        selected = frame.loc[
            frame["underlying_asset"].astype(str).eq(stock)
            & frame["expiration"].dt.date.ge(SOURCE_START)
            & frame["expiration"].dt.date.le(SOURCE_END)
            & frame["name"].astype(str).str.contains("-", regex=False)
            & frame["secid"].astype(str).map(lambda value: bool(pattern.fullmatch(value)))
        ].sort_values(["expiration", "secid"])
        factual_counts[stock] = len(selected)
        for item in selected.itertuples():
            expiration = pd.Timestamp(item.expiration)
            asset_code = str(item.asset_code)
            secid = str(item.secid)
            rows.append(
                {
                    "contract_id": (
                        f"{stock}:{asset_code}:{secid}:{expiration.date().isoformat()}"
                    ),
                    "stock_secid": stock,
                    "secid": secid,
                    "asset_code": asset_code,
                    "series_start": pd.Timestamp(item.series_start),
                    "expiration": expiration,
                }
            )
    expected = {
        str(key): int(value)
        for key, value in protocol.payload["universe"][
            "exact_outright_contract_count_by_stock"
        ].items()
    }
    if factual_counts != expected:
        raise ValueError(f"broad historical contract counts drifted: {factual_counts}")
    catalog = pd.DataFrame(rows, columns=CATALOG_COLUMNS)
    if len(catalog) != 339 or catalog["contract_id"].duplicated().any():
        raise ValueError("broad historical contract catalog identity drifted")
    return catalog


def _description_url(protocol: Protocol, secid: str) -> str:
    return str(protocol.payload["official_sources"]["description_template"]).format(
        secid=secid
    ) + "?iss.meta=off"


def _positive_integer(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return None
    return int(number)


def parse_description(
    payload: dict[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    description = iss._parse_iss_block(
        payload, "description", frozenset({"name", "value"})
    )
    boards = iss._parse_iss_block(
        payload, "boards", frozenset({"secid", "boardid"})
    )
    values = dict(zip(description["name"].astype(str), description["value"], strict=True))
    secid = str(row["secid"])
    board_ids = set(
        boards.loc[boards["secid"].astype(str).eq(secid), "boardid"].astype(str)
    )
    lot_size = _positive_integer(values.get("LOTSIZE"))
    if (
        str(values.get("SECID")) != secid
        or str(values.get("ASSETCODE")) != str(row["asset_code"])
        or str(values.get("TYPE")) != "futures"
        or "RFUD" not in board_ids
        or lot_size is None
    ):
        raise ValueError(f"broad historical contract description drifted: {secid}")
    first_trade = pd.Timestamp(values["FRSTTRADE"])
    last_trade = pd.Timestamp(values["LSTTRADE"])
    last_delivery = pd.Timestamp(values["LSTDELDATE"])
    request_from = max(SOURCE_START, pd.Timestamp(row["series_start"]).date(), first_trade.date())
    request_till = min(SOURCE_END, pd.Timestamp(row["expiration"]).date(), last_trade.date())
    if request_till < request_from or request_till >= PROTECTED_FROM:
        raise ValueError(f"broad historical request interval invalid: {secid}")
    return {
        **{column: row[column] for column in CATALOG_COLUMNS},
        "board_id": "RFUD",
        "lot_size_shares": lot_size,
        "first_trade": first_trade,
        "last_trade": last_trade,
        "last_delivery": last_delivery,
        "request_from": pd.Timestamp(request_from),
        "request_till": pd.Timestamp(request_till),
    }


def _candles_url(protocol: Protocol, spec: Mapping[str, Any], offset: int) -> str:
    query = urlencode(
        {
            "from": pd.Timestamp(spec["request_from"]).date().isoformat(),
            "till": pd.Timestamp(spec["request_till"]).date().isoformat(),
            "interval": int(protocol.payload["official_sources"]["candle_interval_minutes"]),
            "start": offset,
            "limit": PAGE_LIMIT,
            "iss.meta": "off",
            "iss.only": "candles",
        }
    )
    template = str(protocol.payload["official_sources"]["candles_template"])
    return f"{template.format(secid=spec['secid'])}?{query}"


def parse_candles(payload: dict[str, Any], spec: Mapping[str, Any]) -> pd.DataFrame:
    parsed = market_data.parse_futures_candles_payload(
        payload, GENERIC_FUTURES, str(spec["secid"])
    )
    if parsed.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    frame = pd.DataFrame(
        {
            "timestamp": parsed["timestamp"],
            "end_timestamp": parsed["end_timestamp"],
            "available_at": parsed["end_timestamp"],
            "contract_id": spec["contract_id"],
            "stock_secid": spec["stock_secid"],
            "asset_code": spec["asset_code"],
            "secid": parsed["secid"],
            "board_id": spec["board_id"],
            "expiration": spec["expiration"],
            "lot_size_shares": spec["lot_size_shares"],
            "open": parsed["open"],
            "high": parsed["high"],
            "low": parsed["low"],
            "close": parsed["close"],
            "volume": parsed["volume"],
            "value": parsed["value"],
        },
        columns=CANDLE_COLUMNS,
    )
    local_dates = frame["timestamp"].dt.tz_convert("Europe/Moscow").dt.date
    if local_dates.lt(SOURCE_START).any() or local_dates.ge(PROTECTED_FROM).any():
        raise ValueError("broad historical candle escaped protected interval")
    return frame


def fetch_candles(
    client: JsonClient, protocol: Protocol, spec: Mapping[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    raw: list[dict[str, Any]] = []
    offset = 0
    previous_last: pd.Timestamp | None = None
    for _ in range(MAX_PAGES):
        url = _candles_url(protocol, spec, offset)
        payload = client.get_json(url)
        original = iss._parse_iss_block(
            payload, "candles", market_data.CANDLES_REQUIRED_COLUMNS
        )
        frame = parse_candles(payload, spec)
        if len(original) != len(frame) or len(frame) > PAGE_LIMIT:
            raise ValueError("broad historical candle page row count drifted")
        if not frame.empty:
            if previous_last is not None and frame["timestamp"].iloc[0] <= previous_last:
                raise ValueError("broad historical candle pages overlap")
            previous_last = frame["timestamp"].iloc[-1]
            frames.append(frame)
        raw.append(
            {
                "kind": "candles",
                "contract_id": spec["contract_id"],
                "offset": offset,
                "url": url,
                "payload": payload,
            }
        )
        if len(original) < PAGE_LIMIT:
            break
        offset += len(original)
    else:
        raise ValueError("broad historical candle pagination exceeded maximum")
    combined = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=CANDLE_COLUMNS)
    )
    if combined.duplicated(["contract_id", "timestamp"]).any():
        raise ValueError("broad historical duplicate contract timestamp")
    return combined, raw


def _forbidden(frame: pd.DataFrame) -> bool:
    return any(
        fragment in str(column).casefold()
        for column in frame.columns
        for fragment in FORBIDDEN
    )


def collect(protocol: Protocol | None = None, client: JsonClient | None = None) -> Path:
    active_protocol = protocol or load_protocol()
    final = active_protocol.output.resolve()
    if final.exists():
        raise FileExistsError(f"broad historical source exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    own_client = client is None
    active = client or network.OfficialMoexClient()
    raw: list[dict[str, Any]] = []
    try:
        series_raw: list[dict[str, Any]] = []
        for stock in active_protocol.payload["universe"]["exact_stock_order"]:
            url = _series_url(active_protocol, str(stock))
            item = {
                "kind": "series",
                "stock_secid": str(stock),
                "url": url,
                "payload": active.get_json(url),
            }
            series_raw.append(item)
            raw.append(item)
        catalog = select_catalog(series_raw, active_protocol)
        specs: list[dict[str, Any]] = []
        candle_frames: list[pd.DataFrame] = []
        for row in catalog.to_dict("records"):
            url = _description_url(active_protocol, str(row["secid"]))
            payload = active.get_json(url)
            spec = parse_description(payload, row)
            specs.append(spec)
            raw.append(
                {
                    "kind": "description",
                    "contract_id": row["contract_id"],
                    "url": url,
                    "payload": payload,
                }
            )
            candles, pages = fetch_candles(active, active_protocol, spec)
            raw.extend(pages)
            if not candles.empty:
                candle_frames.append(candles)
        spec_frame = pd.DataFrame(specs, columns=SPEC_COLUMNS).sort_values(
            ["stock_secid", "expiration", "secid"], ignore_index=True
        )
        candles = (
            pd.concat(candle_frames, ignore_index=True).sort_values(
                ["stock_secid", "expiration", "secid", "timestamp"],
                ignore_index=True,
            )
            if candle_frames
            else pd.DataFrame(columns=CANDLE_COLUMNS)
        )
        if (
            len(spec_frame) != 339
            or candles.empty
            or candles.duplicated(["contract_id", "timestamp"]).any()
            or _forbidden(spec_frame)
            or _forbidden(candles)
        ):
            raise ValueError("broad historical normalized output failed")
        paths = {
            "specs": temporary / "contract_specs.parquet",
            "candles": temporary / "futures_10m.parquet",
            "raw": temporary / "official_moex_responses.jsonl.gz",
        }
        storage._write_parquet(paths["specs"], spec_frame)
        storage._write_parquet(paths["candles"], candles)
        atomic_write_bytes(paths["raw"], storage._raw_bytes(raw))
        manifest = {
            "bundle_id": "moex-broad-stock-futures-carry-intraday-2023-2025-v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_only": True,
            "contains_basis_returns_targets_signals_predictions_equity_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "stocks_declared": 30,
                "stocks_with_contracts": 29,
                "contracts": len(spec_frame),
                "candles": len(candles),
                "raw_responses": len(raw),
                "contracts_by_stock": spec_frame.groupby("stock_secid")
                .size()
                .astype(int)
                .to_dict(),
                "candles_by_stock": candles.groupby("stock_secid")
                .size()
                .astype(int)
                .to_dict(),
            },
            "artifacts": {
                name: storage._artifact(
                    path,
                    len(raw)
                    if name == "raw"
                    else len(spec_frame)
                    if name == "specs"
                    else len(candles),
                )
                for name, path in paths.items()
            },
            "limitations": active_protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()  # type: ignore[attr-defined]
    checks = audit(active_protocol)
    write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("broad historical source audit failed")
    return final


def _read_raw(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def audit(protocol: Protocol | None = None) -> dict[str, bool]:
    active_protocol = protocol or load_protocol()
    root = active_protocol.output.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    specs_path = root / manifest["artifacts"]["specs"]["file"]
    candles_path = root / manifest["artifacts"]["candles"]["file"]
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    specs = pd.read_parquet(specs_path)
    candles = pd.read_parquet(candles_path)
    raw = _read_raw(raw_path)
    series_raw = [item for item in raw if item["kind"] == "series"]
    rebuilt_catalog = select_catalog(series_raw, active_protocol)
    spec_index = specs.set_index("contract_id", drop=False)
    replay_specs: list[dict[str, Any]] = []
    replay_candles: list[pd.DataFrame] = []
    for item in raw:
        if item["kind"] == "description":
            row = rebuilt_catalog.loc[
                rebuilt_catalog["contract_id"].eq(item["contract_id"])
            ].iloc[0]
            replay_specs.append(parse_description(item["payload"], row))
        elif item["kind"] == "candles":
            frame = parse_candles(item["payload"], spec_index.loc[item["contract_id"]])
            if not frame.empty:
                replay_candles.append(frame)
        elif item["kind"] != "series":
            raise ValueError(f"unknown broad historical raw kind: {item['kind']}")
    rebuilt_specs = pd.DataFrame(replay_specs, columns=SPEC_COLUMNS).sort_values(
        ["stock_secid", "expiration", "secid"], ignore_index=True
    )
    rebuilt_candles = pd.concat(replay_candles, ignore_index=True).sort_values(
        ["stock_secid", "expiration", "secid", "timestamp"], ignore_index=True
    )
    try:
        pd.testing.assert_frame_equal(rebuilt_specs, specs, check_dtype=False)
        specs_replay = True
    except AssertionError:
        specs_replay = False
    try:
        pd.testing.assert_frame_equal(rebuilt_candles, candles, check_dtype=False)
        candles_replay = True
    except AssertionError:
        candles_replay = False
    local_dates = candles["timestamp"].dt.tz_convert("Europe/Moscow").dt.date
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "specs_sha_exact": _sha(specs_path) == manifest["artifacts"]["specs"]["sha256"],
        "candles_sha_exact": _sha(candles_path) == manifest["artifacts"]["candles"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "row_counts_exact": pq.ParquetFile(specs_path).metadata.num_rows == 339
        and pq.ParquetFile(candles_path).metadata.num_rows == manifest["counts"]["candles"]
        and len(raw) == manifest["counts"]["raw_responses"],
        "contract_identity_exact": len(specs) == 339
        and not specs["contract_id"].duplicated().any(),
        "candle_identity_unique": not candles.duplicated(["contract_id", "timestamp"]).any(),
        "protected_period_exact": bool(local_dates.lt(PROTECTED_FROM).all())
        and bool(local_dates.ge(SOURCE_START).all()),
        "forbidden_columns_absent": not _forbidden(specs) and not _forbidden(candles),
        "raw_specs_replay_exact": specs_replay,
        "raw_candles_replay_exact": candles_replay,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    protocol = load_protocol()
    if not args.audit_only:
        print(collect(protocol))
    else:
        checks = audit(protocol)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))


if __name__ == "__main__":
    main()
