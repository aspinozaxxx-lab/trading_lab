"""Pure discovery and FO parsers; vendor timestamps never imply original publication."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from urllib.parse import urlencode

PROTOCOL = "algopack_fo_witnessed_v1"
ASSETS = {"BR": "BR", "MIX": "MIX", "RI": "RTS", "SI": "Si"}
PREFIXES = {"BR": "BR", "MIX": "MX", "RI": "RI", "SI": "Si"}
RFUD_COLUMNS = ["SECID", "BOARDID", "ASSETCODE", "SECTYPE", "LASTTRADEDATE", "LASTDELDATE"]
SERIES_COLUMNS = ["secid", "start_date", "expiration_date", "asset_code", "is_traded"]
COMMON = ["tradedate", "tradetime", "secid", "asset_code", "SYSTIME"]
FIELDS = {
    "tradestats": [
        "trades",
        "trades_b",
        "trades_s",
        "vol",
        "vol_b",
        "vol_s",
        "val",
        "val_b",
        "val_s",
        "disb",
    ],
    "obstats": [
        "spread_l1",
        "spread_l10",
        "levels_b",
        "levels_s",
        "vol_b_l1",
        "vol_s_l1",
        "vol_b_l10",
        "vol_s_l10",
    ],
}
COUNT_FIELDS = {"trades", "trades_b", "trades_s", "vol", "vol_b", "vol_s"}
SIGNED_FIELDS = {"disb", "spread_l1", "spread_l10"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
MONTHS = "FGHJKMNQUVXZ"


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate source JSON key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise ValueError("nonfinite source JSON literal")


def _decode(raw: bytes) -> dict:
    if not isinstance(raw, bytes):
        raise ValueError("source response must be bytes")
    payload = json.loads(
        raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant
    )
    if not isinstance(payload, dict):
        raise ValueError("source response must be an object")
    return payload


def _date(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("source date must be exact ISO")
    if datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
        raise ValueError("source date must be exact ISO")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("source metadata string is missing or malformed")
    return value


def _outright_asset(secid: object) -> str | None:
    if not isinstance(secid, str):
        return None
    for asset, prefix in PREFIXES.items():
        if re.fullmatch(re.escape(prefix) + f"[{MONTHS}][0-9]", secid):
            return asset
    return None


def _block(payload: dict, name: str, columns: list[str]) -> list[dict]:
    block = payload[name]
    if (
        not isinstance(block, dict)
        or set(block) != {"columns", "data"}
        or block["columns"] != columns
        or not isinstance(block["data"], list)
    ):
        raise ValueError("source block schema differs")
    rows = []
    for values in block["data"]:
        if not isinstance(values, list) or len(values) != len(columns):
            raise ValueError("source row width differs")
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def metadata_urls() -> dict[str, str]:
    return {
        "rfud": "https://iss.moex.com/iss/engines/futures/markets/forts/boards/RFUD/securities.json?"
        + urlencode(
            {
                "iss.meta": "off",
                "iss.only": "securities",
                "securities.columns": ",".join(RFUD_COLUMNS),
            }
        ),
        "series": "https://iss.moex.com/iss/statistics/engines/futures/markets/forts/series.json?"
        + urlencode(
            {
                "iss.meta": "off",
                "iss.only": "series",
                "show_expired": 0,
                "series.columns": ",".join(SERIES_COLUMNS),
            }
        ),
    }


def select_contracts(rfud_raw: bytes, series_raw: bytes, source_date: str) -> list[dict]:
    """Nearest two regular outright contracts per asset, excluding the expiry day itself."""
    try:
        day = _date(source_date)
        rfud_payload, series_payload = _decode(rfud_raw), _decode(series_raw)
        if set(rfud_payload) != {"securities"} or set(series_payload) != {"series"}:
            raise ValueError("unexpected discovery blocks")
        rfud, series, seen = {}, {}, set()
        for row in _block(rfud_payload, "securities", RFUD_COLUMNS):
            secid = _text(row["SECID"])
            if secid in seen:
                raise ValueError("duplicate RFUD security")
            seen.add(secid)
            asset = _outright_asset(secid)
            if asset is None:
                continue  # Other underlyings, perpetuals and spreads are not candidate contracts.
            if row["BOARDID"] != "RFUD" or row["ASSETCODE"] != ASSETS[asset]:
                raise ValueError("RFUD candidate identity differs")
            _text(row["SECTYPE"])
            _date(row["LASTDELDATE"])
            rfud[secid] = {
                "asset_code": asset,
                "secid": secid,
                "last_trade_date": _date(row["LASTTRADEDATE"]),
            }
        seen = set()
        for row in _block(series_payload, "series", SERIES_COLUMNS):
            secid = _text(row["secid"])
            if secid in seen:
                raise ValueError("duplicate futures series")
            seen.add(secid)
            asset = _outright_asset(secid)
            if asset is None:
                continue
            if row["asset_code"] != ASSETS[asset]:
                raise ValueError("series candidate alias differs")
            if type(row["is_traded"]) is not int or row["is_traded"] not in (0, 1):
                raise ValueError("series traded flag is not binary integer")
            start, expiry = _date(row["start_date"]), _date(row["expiration_date"])
            if start > expiry:
                raise ValueError("series dates inverted")
            series[secid] = {
                "start_date": start,
                "expiration_date": expiry,
                "is_traded": row["is_traded"],
            }
            if row["is_traded"] == 1 and start <= day < expiry and secid not in rfud:
                raise ValueError("active candidate absent from RFUD metadata")
        candidates = {asset: [] for asset in ASSETS}
        for secid, row in rfud.items():
            if row["last_trade_date"] <= day:
                continue
            if secid not in series:
                raise ValueError("unexpired RFUD candidate missing series metadata")
            listing = series[secid]
            if listing["start_date"] > row["last_trade_date"]:
                raise ValueError("candidate start date after last trade date")
            if (
                listing["is_traded"] == 1
                and listing["start_date"] <= day
                and listing["expiration_date"] > day
            ):
                candidates[row["asset_code"]].append(
                    {
                        **row,
                        "expiration_date": listing["expiration_date"],
                        "start_date": listing["start_date"],
                    }
                )
        selected = []
        for asset in ASSETS:
            rows = sorted(candidates[asset], key=lambda row: (row["last_trade_date"], row["secid"]))
            if len(rows) < 2:
                raise ValueError("insufficient eligible discovery candidates")
            selected.extend(rows[:2])
        return selected
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("invalid witnessed contract discovery") from None


def _job(job: dict, start: int) -> None:
    if (
        not isinstance(job, dict)
        or set(job) != {"dataset", "asset_code", "secid", "from", "till"}
        or job["dataset"] not in FIELDS
        or job["asset_code"] not in ASSETS
        or _outright_asset(job["secid"]) != job["asset_code"]
        or _date(job["from"]) > _date(job["till"])
        or type(start) is not int
        or start < 0
    ):
        raise ValueError("invalid witnessed source job")


def flow_url(job: dict, start: int) -> str:
    try:
        _job(job, start)
        columns = COMMON + FIELDS[job["dataset"]]
        query = urlencode(
            {
                "from": job["from"],
                "till": job["till"],
                "latest": 0,
                "start": start,
                "iss.meta": "off",
                "iss.only": "data,data.cursor",
                "data.columns": ",".join(columns),
            }
        )
        return (
            f"https://apim.moex.com/iss/datashop/algopack/fo/{job['dataset']}/"
            f"{job['secid']}.json?{query}"
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid witnessed source request") from None


def row_key(row: dict) -> tuple:
    return tuple(
        row[field]
        for field in ("dataset", "requested_asset_code", "secid", "tradedate", "tradetime")
    )


def parse_page(raw: bytes, job: dict, start: int) -> tuple[list[dict], dict]:
    """Parse only the declared date window; receipt/availability belong to the collector."""
    try:
        _job(job, start)
        payload = _decode(raw)
        if set(payload) != {"data", "data.cursor"}:
            raise ValueError("unexpected witnessed source blocks")
        source_rows = _block(payload, "data", COMMON + FIELDS[job["dataset"]])
        cursors = _block(payload, "data.cursor", ["INDEX", "TOTAL", "PAGESIZE"])
        if len(cursors) != 1:
            raise ValueError("invalid witnessed cursor shape")
        cursor = cursors[0]
        index, total, size = (cursor[key] for key in ("INDEX", "TOTAL", "PAGESIZE"))
        if (
            any(type(value) is not int for value in (index, total, size))
            or index != start
            or total < index
            or size <= 0
            or len(source_rows) != min(size, total - index)
        ):
            raise ValueError("invalid witnessed cursor completeness")
        output, seen = [], set()
        for row in source_rows:
            day = _date(row["tradedate"])
            if not job["from"] <= day <= job["till"] or row["secid"] != job["secid"]:
                raise ValueError("witnessed row escaped declared date or contract")
            clock = datetime.strptime(row["tradetime"], "%H:%M:%S")
            if clock.strftime("%H:%M:%S") != row["tradetime"]:
                raise ValueError("witnessed clock is not exact")
            system = datetime.fromisoformat(row["SYSTIME"])
            if system.tzinfo is not None or system.isoformat(sep=" ") != row["SYSTIME"]:
                raise ValueError("witnessed vendor system time invalid")
            missing = row["asset_code"] is None or row["asset_code"] == ""
            if not missing and (
                not isinstance(row["asset_code"], str)
                or not IDENTIFIER.fullmatch(row["asset_code"])
            ):
                raise ValueError("witnessed asset metadata invalid")
            for field in FIELDS[job["dataset"]]:
                value = row[field]
                if value is not None and (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or (field not in SIGNED_FIELDS and value < 0)
                    or (field in COUNT_FIELDS and value != math.trunc(value))
                ):
                    raise ValueError("witnessed numeric domain invalid")
            normalized = {
                **row,
                "dataset": job["dataset"],
                "requested_asset_code": job["asset_code"],
                "asset_code_missing": missing,
                "asset_code_mismatch": not missing
                and row["asset_code"] != ASSETS[job["asset_code"]],
            }
            key = row_key(normalized)
            if key in seen:
                raise ValueError("duplicate witnessed observation")
            seen.add(key)
            output.append(normalized)
        return output, cursor
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("invalid witnessed source response") from None
