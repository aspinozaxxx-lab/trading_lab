"""Static option -> dated futures binding. No HTTP, OI, price or execution inputs."""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from market_lab.futures.specs import FUTURES_ASSET_REGISTRY, canonical_contract_id

CATALOG_COLUMNS = (
    "canonical_contract_id", "secid", "name", "start_date", "expiration_date",
    "asset_code", "underlying_asset",
)
FUTURES_CODE = re.compile(r"^[A-Za-z]+[FGHJKMNQUVXZ]\d(?:_\d{4})?$")
STRIKE_DELIVERY = (
    "При исполнении опциона заключается фьючерс, являющийся базовым активом опциона, "
    "по цене, равной цене исполнения опциона."
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).split())


def exact_day(value):
    """No month-code, weekday, timezone or intraday-to-date inference."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("exact ISO date required")
    return date.fromisoformat(value)


@dataclass(frozen=True)
class FuturesCatalog:
    rows: tuple[dict, ...]
    evidence_sha256: str
    sources: tuple[dict, ...]


def prepare_catalog(frame, sources=()):
    """Canonical IDs collapse aliases, never different expirations of a decade SECID."""
    require(set(frame.columns) == set(CATALOG_COLUMNS), "static catalog schema only")
    d = frame.copy()
    for key in ("start_date", "expiration_date"):
        values = pd.to_datetime(d[key])
        require(values.notna().all() and values.dt.tz is None
                and values.eq(values.dt.normalize()).all(), "catalog exact dates")
        d[key] = values.dt.strftime("%Y-%m-%d")
    d["underlying_asset"] = d.underlying_asset.where(d.underlying_asset.notna(), None)
    rows = d.to_dict("records")
    aliases = set()
    registry = {official: (logical, prefix)
                for logical, (official, prefix) in FUTURES_ASSET_REGISTRY.items()}
    for row in rows:
        require(row["asset_code"] in registry, "catalog asset")
        _, prefix = registry[row["asset_code"]]
        require(all(isinstance(row[k], str) and row[k].strip() == row[k] and row[k]
                    for k in ("canonical_contract_id", "secid", "name")), "catalog names")
        require(FUTURES_CODE.fullmatch(row["secid"])
                and row["secid"].startswith(prefix), "catalog outright contract")
        first, expiry = exact_day(row["start_date"]), exact_day(row["expiration_date"])
        require(first <= expiry, "catalog lifecycle")
        require(row["canonical_contract_id"] == canonical_contract_id(
            row["asset_code"], row["secid"], expiry), "catalog canonical identity")
        key = (row["canonical_contract_id"], row["secid"])
        require(key not in aliases, "duplicate catalog alias")
        aliases.add(key)
    rows.sort(key=lambda r: (r["canonical_contract_id"], r["secid"]))
    evidence = json.dumps({"rows": rows, "sources": sources}, sort_keys=True,
                          ensure_ascii=True, separators=(",", ":")).encode()
    return FuturesCatalog(tuple(rows), digest(evidence), tuple(sources))


def checked_file(root, spec):
    root = Path(root).resolve()
    path = root / spec["path"]
    require(not Path(spec["path"]).is_absolute() and path.resolve().is_relative_to(root),
            "catalog path escape")
    raw = path.read_bytes()
    require(len(raw) == spec["bytes"] and digest(raw) == spec["sha256"], "catalog source drift")
    return path, raw


def load_catalogs(root, config):
    """Read only pinned static catalog artifacts, never linked candles/spec prices/OI."""
    frames, evidence = [], []
    require(set(config["catalogs"]) == set(FUTURES_ASSET_REGISTRY), "four static catalogs")
    for logical, specs in config["catalogs"].items():
        _, raw_manifest = checked_file(root, specs["manifest"])
        manifest = json.loads(raw_manifest)
        official, prefix = FUTURES_ASSET_REGISTRY[logical]
        require(manifest["asset"]["asset_code"] == official
                and manifest["asset"]["logical_symbol"] == logical
                and manifest["requested_start"] == "2018-01-01"
                and manifest["requested_end"] == "2025-12-31"
                and manifest["protected_from"] == "2026-01-01", "catalog manifest scope")
        declared = manifest["catalog_artifacts"]["series"]
        for role in ("raw", "parquet"):
            require(all(declared[role][k] == v for k, v in specs[role].items()),
                    "catalog manifest artifact binding")
        path, _ = checked_file(root, specs["parquet"])
        require(set(pq.read_schema(path).names) == set(CATALOG_COLUMNS) | {"is_traded"},
                "unexpected catalog columns")
        frame = pd.read_parquet(path, columns=list(CATALOG_COLUMNS))
        require(len(frame) == specs["parquet"]["rows"], "catalog rows")
        _, packed = checked_file(root, specs["raw"])
        archive = json.loads(gzip.decompress(packed))
        replay = []
        for request in archive["requests"]:
            require(request["url"].startswith(
                "https://iss.moex.com/iss/statistics/engines/futures/markets/forts/series.json?"
            ) and set(request["payload"]) == {"series"}, "static catalog route/block")
            block = request["payload"]["series"]
            columns = block["columns"]
            require(len(columns) == len(set(columns))
                    and set(columns) == (set(CATALOG_COLUMNS) - {"canonical_contract_id"})
                    | {"is_traded"}, "raw static catalog schema")
            for values in block["data"]:
                require(len(values) == len(columns), "raw catalog row length")
                row = dict(zip(columns, values, strict=True))
                # is_traded is deliberately not used as historical eligibility.
                if row["asset_code"] != official or not isinstance(row["secid"], str):
                    continue
                if not FUTURES_CODE.fullmatch(row["secid"]) or not row["secid"].startswith(prefix):
                    continue
                if row["start_date"] is None or row["expiration_date"] is None:
                    continue
                first, expiry = exact_day(row["start_date"]), exact_day(row["expiration_date"])
                if expiry < date(2018, 1, 1) or first > date(2025, 12, 31):
                    continue
                row["canonical_contract_id"] = canonical_contract_id(official, row["secid"], expiry)
                replay.append({k: row[k] for k in CATALOG_COLUMNS})
        replay_frame = pd.DataFrame(replay, columns=CATALOG_COLUMNS).drop_duplicates()
        require(prepare_catalog(frame).rows == prepare_catalog(replay_frame).rows,
                "raw to normalized catalog mismatch")
        frames.append(frame)
        evidence.append({"logical_asset": logical, **specs})
    return prepare_catalog(pd.concat(frames, ignore_index=True), evidence)


def description_fields(raw):
    payload = json.loads(raw)
    require(isinstance(payload, dict) and set(payload) == {"description"},
            "description-only payload")
    block = payload["description"]
    columns, data = block["columns"], block["data"]
    require(isinstance(columns, list) and isinstance(data, list)
            and len(columns) == len(set(columns))
            and {"name", "value", "type", "title"} <= set(columns), "description schema")
    result = {}
    for values in data:
        require(isinstance(values, list) and len(values) == len(columns), "description row")
        row = dict(zip(columns, values, strict=True))
        require(isinstance(row["name"], str) and row["name"] not in result,
                "duplicate description field")
        result[row["name"]] = row
    return result


def map_description(raw, raw_sha256, *, secid, logical_asset, catalog):
    """Hash-bound static mapping; caller must bind expected SHA to closed source manifest."""
    require(logical_asset in FUTURES_ASSET_REGISTRY and isinstance(secid, str) and secid,
            "option requested identity")
    require(isinstance(raw, bytes) and digest(raw) == raw_sha256, "description hash mismatch")
    out = dict(
        secid=secid, logical_asset=logical_asset, metadata_ready=False, option_class="unknown",
        first_trade_date=None, last_trade_date=None, expiry_date=None,
        underlying_contract_id=None, option_type=None, strike=None, unit=None, lot_size=None,
        exercise_style=None, series_name=None, quote_units_compatible=False,
        reason="MALFORMED_DESCRIPTION", description_sha256=raw_sha256,
        catalog_evidence_sha256=catalog.evidence_sha256, matched_future_name=None,
        underlying_binding=None, strike_price_equality_proved=False,
        original_publication_proved=False, economic_admission=False,
    )
    try:
        fields = description_fields(raw)
    except (ValueError, TypeError, KeyError, AttributeError):
        return out
    values = {k: row["value"] for k, row in fields.items()}
    if str(values.get("SECID", "")).casefold() != secid.casefold():
        out["reason"] = "OPTION_IDENTITY_MISMATCH"
        return out
    official = FUTURES_ASSET_REGISTRY[logical_asset][0]
    if values.get("ASSETCODE") != official or values.get("GROUP") != "futures_options":
        out["reason"] = "OPTION_ASSET_OR_GROUP_MISMATCH"
        return out
    if values.get("TYPE") == "option_on_currency" and values.get("MARGINSTYLE") == "Премиальный":
        out.update(metadata_ready=True, option_class="premium_currency_option",
                   reason="EXCLUDED_PREMIUM_CURRENCY")
        return out
    if values.get("TYPE") != "option" or values.get("MARGINSTYLE") != "Маржируемый":
        out["reason"] = "UNSUPPORTED_OPTION_CLASS"
        return out
    out["option_class"] = "margined_future_option"
    try:
        for source, target in (("FRSTTRADE", "first_trade_date"), ("LSTTRADE", "last_trade_date"),
                               ("LSTDELDATE", "expiry_date")):
            require(fields[source]["type"] == "date", "description date type")
            out[target] = exact_day(values[source]).isoformat()
        require(normalized_text(fields["LSTDELDATE"]["title"]).casefold() == "дата экспирации",
                "explicit expiry definition")
        require(out["first_trade_date"] <= out["last_trade_date"] <= out["expiry_date"],
                "option lifecycle order")
    except (ValueError, TypeError, KeyError):
        out["reason"] = "INVALID_EXPLICIT_LIFECYCLE"
        return out
    try:
        out.update(option_type={"C": "call", "P": "put"}.get(values.get("OPTIONTYPE")),
                   unit=values.get("UNIT"), exercise_style=values.get("EXECTYPE"),
                   series_name=values.get("SERIES_NAME"))
        require(fields["STRIKE"]["type"] == "number"
                and normalized_text(fields["STRIKE"]["title"]).casefold() == "цена страйк",
                "explicit strike definition")
        for source, target in (("STRIKE", "strike"), ("LOTSIZE", "lot_size")):
            require(not isinstance(values[source], bool), "boolean is not a contract amount")
            out[target] = float(values[source])
            require(math.isfinite(out[target]) and out[target] > 0, "positive contract amount")
        require(out["option_type"] is not None
                and out["exercise_style"] in ("Американский", "Европейский")
                and all(isinstance(out[k], str) and out[k].strip()
                        for k in ("unit", "series_name")), "option static fields")
    except (ValueError, TypeError, KeyError, OverflowError):
        out["reason"] = "INVALID_STRIKE_OR_CONTRACT_FIELDS"
        return out
    name = values.get("NAME", "")
    candidates = [r for r in catalog.rows if r["asset_code"] == official
                  and isinstance(name, str)
                  and name.endswith("на фьюч. контр. " + r["name"])
                  and out["series_name"].startswith(r["name"] + "M")]
    ids = {r["canonical_contract_id"] for r in candidates}
    if len(ids) != 1:
        out["reason"] = "UNDERLYING_NAME_MISSING" if not ids else "AMBIGUOUS_UNDERLYING_NAME"
        return out
    contract = next(iter(ids))
    aliases = [r for r in catalog.rows if r["canonical_contract_id"] == contract]
    underlying = values.get("UNDERLYINGASSET")
    if not isinstance(underlying, str):
        out["reason"] = "UNDERLYING_FIELD_CONFLICT"
        return out
    if underlying in {r["secid"] for r in aliases} | {contract.split(":")[1]}:
        binding = "EXACT_NAME_SERIES_AND_FUTURES_SECID"
    elif logical_asset == "SI" and underlying == "USD000UTSTOM" and all(
        r["underlying_asset"] == underlying for r in aliases
    ):
        binding = "EXACT_NAME_SERIES_AND_SI_CASH_ROOT"
    else:
        out["reason"] = "UNDERLYING_FIELD_CONFLICT"
        return out
    if (min(r["start_date"] for r in aliases) > out["first_trade_date"]
            or out["expiry_date"] > aliases[0]["expiration_date"]):
        out["reason"] = "UNDERLYING_LIFECYCLE_CONFLICT"
        return out
    if STRIKE_DELIVERY.casefold() not in normalized_text(values.get("DELIVERYTYPE")).casefold():
        out["reason"] = "STRIKE_TO_FUTURES_PRICE_NOT_PROVED"
        return out
    out.update(metadata_ready=True, quote_units_compatible=True,
               underlying_contract_id=contract, matched_future_name=candidates[0]["name"],
               underlying_binding=binding, strike_price_equality_proved=True,
               reason="EXACT_STATIC_BINDING")
    return out
