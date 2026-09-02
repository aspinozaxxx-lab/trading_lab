"""Build the sealed source-only monthly RVI futures daily history."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_rvi_futures_daily_source_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "bb4aec1d8f5c93bfdcae555c5c159c6da7334644db246822ce5ae69cdc2d7149"
)
ASSET_CODE: Final[str] = "RVI"
SECID_PATTERN: Final[str] = r"^VI[FGHJKMNQUVXZ][0-9]$"
HISTORY_COLUMNS: Final[tuple[str, ...]] = (
    "BOARDID",
    "TRADEDATE",
    "SECID",
    "OPEN",
    "LOW",
    "HIGH",
    "CLOSE",
    "OPENPOSITIONVALUE",
    "VALUE",
    "VOLUME",
    "OPENPOSITION",
    "SETTLEPRICE",
    "SWAPRATE",
    "WAPRICE",
    "CHANGE",
    "QTY",
    "NUMTRADES",
    "SHORTNAME",
    "ASSETCODE",
)
SERIES_COLUMNS: Final[tuple[str, ...]] = (
    "secid",
    "short_name",
    "start_date",
    "expiration_date",
    "asset_code",
)
DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "asset_code",
    "secid",
    "short_name",
    "series_start_date",
    "expiration_date",
    "board_id",
    "trade_date",
    "open",
    "low",
    "high",
    "close",
    "open_position_value",
    "value",
    "volume",
    "open_position",
    "settle_price",
    "swap_rate",
    "waprice",
    "change",
    "qty",
    "num_trades",
)


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("RVI source config must be an object")
    probe = payload["availability_probe_only"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_rvi_futures_daily_source_v1"
        or payload.get("live_trading_allowed") is not False
        or probe["asset_code"] != ASSET_CODE
        or probe["secid_regex"] != SECID_PATTERN
        or int(probe["exact_monthly_series_2019_2025"]) != 84
        or payload["collection"]["protected_from"] != "2026-01-01"
    ):
        raise ValueError("RVI source protocol drifted")
    return payload


def _safe_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe RVI output root: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "processed"):
        raise ValueError("RVI output must be under data/processed")
    return PROJECT_ROOT / relative


def _series_url(config: dict[str, Any]) -> str:
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "series",
            "asset_code": ASSET_CODE,
            "show_expired": 1,
        }
    )
    return f"{config['official_sources']['series_endpoint']}?{query}"


def _history_url(
    config: dict[str, Any], secid: str, start: int, request_from: str
) -> str:
    base = str(config["official_sources"]["history_template"]).format(secid=secid)
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "history,history.cursor",
            "history.columns": ",".join(HISTORY_COLUMNS),
            "from": request_from,
            "till": config["collection"]["end"],
            "start": start,
        }
    )
    return f"{base}?{query}"


def select_series(payload: dict[str, Any], config: dict[str, Any]) -> pd.DataFrame:
    frame = iss._parse_iss_block(
        payload,
        "series",
        frozenset({"secid", "name", "start_date", "expiration_date", "asset_code"}),
    )
    frame = frame.loc[
        frame["asset_code"].astype(str).eq(ASSET_CODE)
        & frame["secid"].astype(str).map(
            lambda value: re.fullmatch(SECID_PATTERN, value) is not None
        )
    ].copy()
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="raise")
    frame["expiration_date"] = pd.to_datetime(
        frame["expiration_date"], errors="raise"
    )
    frame = frame.loc[
        frame["expiration_date"].ge("2019-01-01")
        & frame["expiration_date"].le(config["collection"]["end"])
    ].copy()
    output = pd.DataFrame(
        {
            "secid": frame["secid"].astype("string"),
            "short_name": frame["name"].astype("string"),
            "start_date": frame["start_date"],
            "expiration_date": frame["expiration_date"],
            "asset_code": frame["asset_code"].astype("string"),
        }
    ).sort_values("expiration_date", ignore_index=True)
    if len(output) != 84:
        raise ValueError(f"expected 84 RVI monthly series, got {len(output)}")
    if output["secid"].duplicated().any() or output["expiration_date"].duplicated().any():
        raise ValueError("duplicate RVI series identity")
    if output["expiration_date"].min() != pd.Timestamp("2019-01-17"):
        raise ValueError("first RVI expiration drifted")
    if output["expiration_date"].max() != pd.Timestamp("2025-12-18"):
        raise ValueError("last RVI expiration drifted")
    return output.loc[:, SERIES_COLUMNS]


def _cursor(payload: dict[str, Any]) -> tuple[int, int, int]:
    cursor = iss._parse_iss_block(
        payload, "history.cursor", frozenset({"index", "total", "pagesize"})
    )
    if len(cursor) != 1:
        raise ValueError("history cursor must contain exactly one row")
    values = tuple(int(cursor.iloc[0][name]) for name in ("index", "total", "pagesize"))
    if values[0] < 0 or values[1] < 0 or values[2] <= 0:
        raise ValueError("invalid history cursor values")
    return values


def _history_frame(
    payload: dict[str, Any],
    *,
    secid: str,
    series_start: pd.Timestamp,
    expiration: pd.Timestamp,
) -> pd.DataFrame:
    frame = iss._parse_iss_block(
        payload,
        "history",
        frozenset(column.lower() for column in HISTORY_COLUMNS),
    )
    if frame.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    if set(frame["secid"].astype(str)) != {secid}:
        raise ValueError(f"history SECID drifted for {secid}")
    if set(frame["assetcode"].astype(str)) != {ASSET_CODE}:
        raise ValueError(f"history ASSETCODE drifted for {secid}")
    if set(frame["boardid"].astype(str)) != {"RFUD"}:
        raise ValueError(f"history BOARDID drifted for {secid}")
    trade_dates = pd.to_datetime(frame["tradedate"], errors="raise")
    if trade_dates.ge("2026-01-01").any():
        raise ValueError("protected 2026 history leaked into RVI source")
    output = pd.DataFrame(
        {
            "asset_code": frame["assetcode"].astype("string"),
            "secid": frame["secid"].astype("string"),
            "short_name": frame["shortname"].astype("string"),
            "series_start_date": series_start,
            "expiration_date": expiration,
            "board_id": frame["boardid"].astype("string"),
            "trade_date": trade_dates,
        }
    )
    mapping = {
        "open": "open",
        "low": "low",
        "high": "high",
        "close": "close",
        "openpositionvalue": "open_position_value",
        "value": "value",
        "volume": "volume",
        "openposition": "open_position",
        "settleprice": "settle_price",
        "swaprate": "swap_rate",
        "waprice": "waprice",
        "change": "change",
        "qty": "qty",
        "numtrades": "num_trades",
    }
    for source_column, output_column in mapping.items():
        output[output_column] = pd.to_numeric(frame[source_column], errors="coerce")
    output = output.loc[
        output["trade_date"].ge(series_start)
        & output["trade_date"].le(expiration)
    ].copy()
    return output.loc[:, DAILY_COLUMNS]


def rebuild(
    raw: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    series_items = [item for item in raw if item["kind"] == "series"]
    if len(series_items) != 1:
        raise ValueError("raw RVI series response count drifted")
    series = select_series(series_items[0]["payload"], config)
    lookup = {
        str(row.secid): (pd.Timestamp(row.start_date), pd.Timestamp(row.expiration_date))
        for row in series.itertuples(index=False)
    }
    frames = []
    for item in raw:
        if item["kind"] != "history":
            continue
        secid = str(item["secid"])
        if secid not in lookup:
            raise ValueError(f"unexpected raw RVI history identity: {secid}")
        series_start, expiration = lookup[secid]
        frames.append(
            _history_frame(
                item["payload"],
                secid=secid,
                series_start=series_start,
                expiration=expiration,
            )
        )
    daily = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=DAILY_COLUMNS)
    )
    daily = daily.sort_values(["trade_date", "expiration_date"], ignore_index=True)
    if daily.duplicated(["secid", "trade_date"]).any():
        raise ValueError("duplicate RVI contract-date row")
    if set(daily["secid"].astype(str)) - set(series["secid"].astype(str)):
        raise ValueError("RVI daily history contains an unsealed series")
    if not daily.empty and pd.to_datetime(daily["trade_date"]).ge("2026-01-01").any():
        raise ValueError("protected 2026 history leaked into RVI source")
    forbidden = {str(value).casefold() for value in config["forbidden_derived_columns"]}
    if any(str(column).casefold() in forbidden for column in daily.columns):
        raise ValueError("forbidden derived column leaked into RVI source")
    return series, daily


def collect(output_root: Path | None = None, *, client=None) -> Path:
    config = load_config()
    root = (output_root or _safe_root(config["output"]["root"])).resolve()
    if root.exists():
        raise FileExistsError(f"RVI source already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    active = client or network.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        series_url = _series_url(config)
        series_payload = active.get_json(series_url)
        raw.append({"kind": "series", "url": series_url, "payload": series_payload})
        series = select_series(series_payload, config)
        for row in series.itertuples(index=False):
            request_from = max(
                pd.Timestamp(config["collection"]["start"]),
                pd.Timestamp(row.start_date),
            ).date().isoformat()
            cursor_start = 0
            while True:
                url = _history_url(config, str(row.secid), cursor_start, request_from)
                payload = active.get_json(url)
                raw.append(
                    {
                        "kind": "history",
                        "secid": str(row.secid),
                        "cursor_start": cursor_start,
                        "url": url,
                        "payload": payload,
                    }
                )
                index, total, page_size = _cursor(payload)
                rows = len(payload["history"]["data"])
                if index != cursor_start:
                    raise ValueError(f"history cursor index drifted for {row.secid}")
                if cursor_start + rows >= total:
                    break
                if rows <= 0:
                    raise ValueError(f"history pagination stalled for {row.secid}")
                cursor_start += page_size
        series, daily = rebuild(raw, config)
        series_path = temporary / "series.parquet"
        daily_path = temporary / "daily_history.parquet"
        raw_path = temporary / "raw_responses.jsonl.gz"
        storage._write_parquet(series_path, series)
        storage._write_parquet(daily_path, daily)
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        activity = daily["num_trades"].gt(0) & daily["volume"].gt(0)
        both_prices = daily[["open", "close"]].notna().all(axis=1)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_only": True,
            "contains_curve_return_label_signal_trade_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "series": len(series),
                "daily_rows": len(daily),
                "raw_responses": len(raw),
                "positive_trade_activity_rows": int(activity.sum()),
                "open_and_close_rows": int(both_prices.sum()),
                "positive_activity_by_year": {
                    str(year): int(
                        activity.loc[
                            pd.to_datetime(daily["trade_date"]).dt.year.eq(year)
                        ].sum()
                    )
                    for year in range(2019, 2026)
                },
            },
            "artifacts": {
                "series": storage._artifact(series_path, len(series)),
                "daily": storage._artifact(daily_path, len(daily)),
                "raw": storage._artifact(raw_path, len(raw)),
            },
            "limitations": config["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()
    checks = audit(root)
    write_json(root / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("RVI source audit failed")
    return root


def audit(root: Path) -> dict[str, bool]:
    config = load_config()
    bundle = root.resolve()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_path = bundle / manifest["artifacts"]["raw"]["file"]
    series_path = bundle / manifest["artifacts"]["series"]["file"]
    daily_path = bundle / manifest["artifacts"]["daily"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt_series, rebuilt_daily = rebuild(raw, config)
    stored_series = pd.read_parquet(series_path)
    stored_daily = pd.read_parquet(daily_path)
    try:
        pd.testing.assert_frame_equal(stored_series, rebuilt_series, check_dtype=False)
        series_replay = True
    except AssertionError:
        series_replay = False
    try:
        pd.testing.assert_frame_equal(stored_daily, rebuilt_daily, check_dtype=False)
        daily_replay = True
    except AssertionError:
        daily_replay = False
    return {
        "manifest_sha_exact": (bundle / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_curve_return_label_signal_trade_or_pnl"]
        is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "artifact_hashes_exact": _sha(raw_path)
        == manifest["artifacts"]["raw"]["sha256"]
        and _sha(series_path) == manifest["artifacts"]["series"]["sha256"]
        and _sha(daily_path) == manifest["artifacts"]["daily"]["sha256"],
        "artifact_rows_exact": len(stored_series)
        == manifest["artifacts"]["series"]["rows"]
        == 84
        and len(stored_daily) == manifest["artifacts"]["daily"]["rows"],
        "series_replay_exact": series_replay,
        "daily_replay_exact": daily_replay,
        "dates_before_2026": bool(
            pd.to_datetime(stored_daily["trade_date"]).lt("2026-01-01").all()
        ),
        "identity_unique": not stored_daily.duplicated(["secid", "trade_date"]).any(),
        "asset_exact": set(stored_daily["asset_code"].astype(str)) == {ASSET_CODE},
        "missing_not_zero_imputed": bool(stored_daily.isna().any().any()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit-only", type=Path)
    args = parser.parse_args()
    if args.audit_only:
        checks = audit(args.audit_only)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
