"""Collect sealed 10-minute single-stock futures source data from MOEX ISS."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_stock_futures_cash_carry_source as daily_source
from market_lab.futures.market_data import (
    CANDLES_REQUIRED_COLUMNS,
    parse_futures_candles_payload,
)
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_stock_futures_cash_carry_intraday_source_v3.yaml"
)
CONFIG_SHA256: Final[str] = (
    "d6e751e725e9df0d718b7bf6b324e1bb14df3a9954a6ce3e564ef4ba0504a6c0"
)
SOURCE_START: Final[date] = date(2023, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[date] = date(2026, 1, 1)
PAGE_LIMIT: Final[int] = 500
MAX_PAGES: Final[int] = 120
SPEC_COLUMNS: Final[tuple[str, ...]] = (
    "contract_id",
    "logical_asset",
    "spot_secid",
    "secid",
    "asset_code",
    "board_id",
    "lot_size_shares",
    "first_trade",
    "last_trade",
    "last_delivery",
    "expiration",
    "request_from",
    "request_till",
)
CANDLE_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "end_timestamp",
    "available_at",
    "contract_id",
    "logical_asset",
    "asset_code",
    "spot_secid",
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


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    output: Path
    v2_root: Path


def _sha(path: Path) -> str:
    return daily_source.sha256_file(path)


def _safe_path(value: str) -> Path:
    return daily_source._project_path(value, "data")


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("intraday cash-carry source config must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "moex_stock_futures_cash_carry_intraday_source_v3"
        or payload.get("scope")
        != "source_only_no_basis_returns_targets_signals_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or int(payload["universe"]["exact_contract_count"]) != 61
        or int(payload["universe"]["expected_lot_size_shares"]) != 100
        or int(payload["official_sources"]["interval_minutes"]) != 10
        or int(payload["official_sources"]["page_limit"]) != PAGE_LIMIT
        or payload["output"]["immutable"] is not True
    ):
        raise ValueError("intraday cash-carry source protocol drifted")
    section = payload["v2_source"]
    v2_root = _safe_path(section["root"])
    for key in ("manifest", "contracts", "futures_daily", "rms_cashflows", "raw"):
        declaration = section[key]
        path = v2_root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"intraday cash-carry V2 dependency drifted: {key}")
        if (
            "rows" in declaration
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
        ):
            raise ValueError(f"intraday cash-carry V2 rows drifted: {key}")
    return Protocol(payload, actual, _safe_path(payload["output"]["directory"]), v2_root)


def _description_url(secid: str) -> str:
    return f"https://iss.moex.com/iss/securities/{secid}.json?iss.meta=off"


def _parse_description(payload: dict[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    description = iss._parse_iss_block(payload, "description", frozenset({"name", "value"}))
    boards = iss._parse_iss_block(payload, "boards", frozenset({"secid", "boardid"}))
    values = dict(zip(description["name"].astype(str), description["value"], strict=True))
    expected_asset = str(row["asset_code"])
    board_ids = set(boards.loc[boards["secid"].astype(str).eq(str(row["secid"])), "boardid"])
    if (
        str(values.get("SECID")) != str(row["secid"])
        or str(values.get("ASSETCODE")) != expected_asset
        or int(float(values.get("LOTSIZE"))) != 100
        or str(values.get("TYPE")) != "futures"
        or "RFUD" not in board_ids
    ):
        raise ValueError(f"intraday cash-carry contract description drifted: {row['secid']}")
    return {
        "contract_id": row["contract_id"],
        "logical_asset": row["logical_asset"],
        "spot_secid": row["spot_secid"],
        "secid": row["secid"],
        "asset_code": expected_asset,
        "board_id": "RFUD",
        "lot_size_shares": 100,
        "first_trade": pd.Timestamp(values["FRSTTRADE"]),
        "last_trade": pd.Timestamp(values["LSTTRADE"]),
        "last_delivery": pd.Timestamp(values["LSTDELDATE"]),
        "expiration": pd.Timestamp(row["expiration"]),
        "request_from": pd.Timestamp(row["request_from"]),
        "request_till": pd.Timestamp(row["request_till"]),
    }


def _parse_candles(
    payload: dict[str, Any], spec: Mapping[str, Any]
) -> pd.DataFrame:
    asset = daily_source.AssetSpec.from_symbol(str(spec["logical_asset"]))
    frame = parse_futures_candles_payload(payload, asset, str(spec["secid"]))
    if frame.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    output = pd.DataFrame(
        {
            "timestamp": frame["timestamp"],
            "end_timestamp": frame["end_timestamp"],
            "available_at": frame["end_timestamp"],
            "contract_id": spec["contract_id"],
            "logical_asset": spec["logical_asset"],
            "asset_code": spec["asset_code"],
            "spot_secid": spec["spot_secid"],
            "secid": frame["secid"],
            "board_id": spec["board_id"],
            "expiration": spec["expiration"],
            "lot_size_shares": spec["lot_size_shares"],
            "open": frame["open"],
            "high": frame["high"],
            "low": frame["low"],
            "close": frame["close"],
            "volume": frame["volume"],
            "value": frame["value"],
        }
    )
    return output.loc[:, CANDLE_COLUMNS]


def _fetch_candles(
    client: Any, spec: Mapping[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    asset = daily_source.AssetSpec.from_symbol(str(spec["logical_asset"]))
    request_from = max(SOURCE_START, pd.Timestamp(spec["request_from"]).date())
    request_till = min(SOURCE_END, pd.Timestamp(spec["request_till"]).date())
    offset = 0
    frames: list[pd.DataFrame] = []
    raw: list[dict[str, Any]] = []
    previous_last: pd.Timestamp | None = None
    for _ in range(MAX_PAGES):
        url = iss.futures_candles_url(
            asset,
            str(spec["secid"]),
            request_from,
            request_till,
            interval=10,
            board_id="RFUD",
            cursor_start=offset,
        ) + f"&limit={PAGE_LIMIT}"
        payload = client.get_json(url)
        original = iss._parse_iss_block(payload, "candles", CANDLES_REQUIRED_COLUMNS)
        if len(original) > PAGE_LIMIT:
            raise ValueError("intraday cash-carry candle page exceeded sealed limit")
        frame = _parse_candles(payload, spec)
        if len(frame) != len(original):
            raise ValueError("intraday cash-carry candle parser changed row count")
        if not frame.empty:
            if previous_last is not None and frame["timestamp"].iloc[0] <= previous_last:
                raise ValueError("intraday cash-carry candle pages overlap")
            previous_last = frame["timestamp"].iloc[-1]
            frames.append(frame)
        raw.append(
            {
                "kind": "candles",
                "contract_id": spec["contract_id"],
                "logical_asset": spec["logical_asset"],
                "secid": spec["secid"],
                "offset": offset,
                "url": url,
                "payload": payload,
            }
        )
        if len(original) < PAGE_LIMIT:
            break
        offset += len(original)
    else:
        raise ValueError("intraday cash-carry candle pagination exceeded maximum")
    combined = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=CANDLE_COLUMNS)
    )
    if not combined.empty and combined["timestamp"].duplicated().any():
        raise ValueError("intraday cash-carry duplicate contract timestamps")
    return combined, raw


def _forbidden(frame: pd.DataFrame) -> bool:
    return any(
        fragment in str(column).lower()
        for column in frame.columns
        for fragment in FORBIDDEN
    )


def collect(protocol: Protocol, client: Any | None = None) -> Path:
    final = protocol.output.resolve()
    if final.exists():
        raise FileExistsError(f"intraday cash-carry source exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    own_client = client is None
    active = client or daily_source.shared.OfficialMoexClient()
    try:
        contracts = pd.read_parquet(protocol.v2_root / "contracts.parquet")
        if len(contracts) != 61 or contracts["contract_id"].duplicated().any():
            raise ValueError("intraday cash-carry contract input drifted")
        specs: list[dict[str, Any]] = []
        candle_frames: list[pd.DataFrame] = []
        raw: list[dict[str, Any]] = []
        for row in contracts.to_dict("records"):
            url = _description_url(str(row["secid"]))
            payload = active.get_json(url)
            spec = _parse_description(payload, row)
            specs.append(spec)
            raw.append(
                {
                    "kind": "description",
                    "contract_id": row["contract_id"],
                    "logical_asset": row["logical_asset"],
                    "secid": row["secid"],
                    "url": url,
                    "payload": payload,
                }
            )
            candles, pages = _fetch_candles(active, spec)
            raw.extend(pages)
            if not candles.empty:
                candle_frames.append(candles)
        spec_frame = pd.DataFrame(specs, columns=SPEC_COLUMNS).sort_values(
            ["logical_asset", "expiration", "secid"], ignore_index=True
        )
        candles = pd.concat(candle_frames, ignore_index=True).sort_values(
            ["timestamp", "logical_asset", "expiration", "secid"], ignore_index=True
        )
        if len(spec_frame) != 61 or candles.duplicated(["contract_id", "timestamp"]).any():
            raise ValueError("intraday cash-carry output identity failed")
        if any(_forbidden(frame) for frame in (spec_frame, candles)):
            raise ValueError("intraday cash-carry source leaked outcome columns")
        local_dates = candles["timestamp"].dt.tz_convert("Europe/Moscow").dt.date
        if local_dates.ge(PROTECTED_FROM).any() or local_dates.lt(SOURCE_START).any():
            raise ValueError("intraday cash-carry candles crossed sealed period")
        paths = {
            "specs": temporary / "contract_specs.parquet",
            "candles": temporary / "futures_10m.parquet",
            "raw": temporary / "official_moex_intraday_responses.jsonl.gz",
        }
        daily_source._write_parquet(paths["specs"], spec_frame)
        daily_source._write_parquet(paths["candles"], candles)
        atomic_write_bytes(paths["raw"], daily_source._raw_bytes(raw))
        artifacts = {
            "specs": daily_source._artifact(paths["specs"], len(spec_frame)),
            "candles": daily_source._artifact(paths["candles"], len(candles)),
            "raw": daily_source._artifact(paths["raw"], len(raw)),
        }
        manifest = {
            "bundle_id": "moex-stock-futures-cash-carry-intraday-2023-2025-v3",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_only": True,
            "contains_basis_returns_targets_signals_predictions_equity_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "contracts": len(spec_frame),
                "candles": len(candles),
                "raw_responses": len(raw),
                "by_asset": candles.groupby("logical_asset").size().astype(int).to_dict(),
            },
            "artifacts": artifacts,
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()
    return final


def _read_raw(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def audit(protocol: Protocol) -> dict[str, bool]:
    root = protocol.output.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == protocol.config_sha256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "live_forbidden": manifest["live_trading_allowed"] is False,
    }
    frames: dict[str, pd.DataFrame] = {}
    for name in ("specs", "candles"):
        declaration = manifest["artifacts"][name]
        path = root / declaration["file"]
        checks[f"{name}_sha_exact"] = _sha(path) == declaration["sha256"]
        checks[f"{name}_rows_exact"] = pq.ParquetFile(path).metadata.num_rows == declaration["rows"]
        frames[name] = pd.read_parquet(path)
        checks[f"{name}_outcome_columns_absent"] = not _forbidden(frames[name])
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    raw = _read_raw(raw_path)
    checks["raw_sha_exact"] = _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"]
    checks["raw_rows_exact"] = len(raw) == manifest["artifacts"]["raw"]["rows"]
    specs = frames["specs"]
    candles = frames["candles"]
    checks["spec_columns_exact"] = tuple(specs.columns) == SPEC_COLUMNS
    checks["candle_columns_exact"] = tuple(candles.columns) == CANDLE_COLUMNS
    checks["contract_count_exact"] = len(specs) == 61
    checks["lot_size_exact"] = set(specs["lot_size_shares"].astype(int)) == {100}
    checks["candle_identity_unique"] = not candles.duplicated(["contract_id", "timestamp"]).any()
    checks["candles_before_protected"] = bool(
        candles["timestamp"].dt.tz_convert("Europe/Moscow").dt.date.lt(PROTECTED_FROM).all()
    )
    index = specs.set_index("contract_id", drop=False)
    replay_specs: list[dict[str, Any]] = []
    replay_candles: list[pd.DataFrame] = []
    for item in raw:
        spec = index.loc[item["contract_id"]]
        if item["kind"] == "description":
            replay_specs.append(_parse_description(item["payload"], spec))
        elif item["kind"] == "candles":
            frame = _parse_candles(item["payload"], spec)
            if not frame.empty:
                replay_candles.append(frame)
        else:
            raise ValueError(f"unknown intraday cash-carry raw kind: {item['kind']}")
    replayed_specs = pd.DataFrame(replay_specs, columns=SPEC_COLUMNS).sort_values(
        ["logical_asset", "expiration", "secid"], ignore_index=True
    )
    replayed_candles = pd.concat(replay_candles, ignore_index=True).sort_values(
        ["timestamp", "logical_asset", "expiration", "secid"], ignore_index=True
    )
    try:
        pd.testing.assert_frame_equal(replayed_specs, specs, check_dtype=False)
        checks["raw_specs_replay_exact"] = True
    except AssertionError:
        checks["raw_specs_replay_exact"] = False
    try:
        pd.testing.assert_frame_equal(replayed_candles, candles, check_dtype=False)
        checks["raw_candles_replay_exact"] = True
    except AssertionError:
        checks["raw_candles_replay_exact"] = False
    if not all(checks.values()):
        raise ValueError(f"intraday cash-carry source audit failed: {checks}")
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
