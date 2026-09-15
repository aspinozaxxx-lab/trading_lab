"""Ten fixed static-metadata requests for the deferred expiry-pinning hypothesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests

from market_lab import futures_v64_si_tax_calendar as base

CONFIG = base.PROJECT / "configs/v88_option_metadata_probe_v1.json"
SEAL = base.PROJECT / "configs/v88_option_metadata_probe_v1.seal.json"
DESCRIPTION_FIELDS = {
    "SECID", "NAME", "SHORTNAME", "LATNAME", "SECTYPE", "TYPE", "GROUP", "TYPENAME",
    "ASSETCODE", "UNDERLYINGASSET", "UNDERLYING", "UNDERLYINGSECID", "BASETICKER",
    "LASTTRADEDATE", "FIRSTTRADEDATE", "LASTDELDATE", "LSTTRADE", "LSTDELDATE", "FRSTTRADE",
    "EXPIRATIONDATE", "EXPIRATION_DATE", "EXPIRATION", "EXPDAY", "EXP_DATE", "EXECUTIONDATE",
    "OPTIONTYPE", "OPTION_TYPE", "STRIKE", "STRIKEPRICE", "LOTSIZE", "FACEUNIT", "UNIT",
    "MARGINSTYLE", "MARGIN_STYLE", "SETTLEMENTTYPE", "SETTLEMENT_TYPE",
}
CALENDAR_FIELDS = {
    "asset_type_name", "asset_code", "series_name", "series_type", "exec_type", "margin_style",
    "expiration_date", "expiration_type", "expiration_time", "expiration_clr_sess",
    "weekend_session", "option_series_id", "series_id", "id", "secid", "security_id",
    "underlying", "underlying_secid", "underlying_asset", "underlying_asset_code",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(expected):
    base.require(base.sha(SEAL) == expected, "V88 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V88 file drift")
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    base.require(not config["economic_admission"] and not config["live_trading_allowed"], "scope")
    base.require(base.sha(Path(config["transport"]["ca_path"])) ==
                 config["transport"]["ca_sha256"], "CA identity")
    return config


def preflight(config):
    spec = config["source"]
    root = base.safe(Path("/srv/trading_lab_data"), spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "source manifest")
    path = root / "options_weekly_core4.parquet"
    base.require(base.sha(path) == spec["parquet_sha256"], "source bytes")
    d = pd.read_parquet(path, columns=spec["allowed_metadata_columns"])
    d["tradedate"] = pd.to_datetime(d.tradedate)
    base.require(len(d) == spec["rows"] and d.secid.nunique() == spec["unique_securities"]
                 and d.tradedate.between("2021-01-01", "2025-12-31").all(), "source dates/count")
    selected = []
    for asset in ("SI", "RI", "BR", "MIX"):
        for year in (2021, 2025):
            part = d.loc[d.logical_asset.eq(asset) & d.tradedate.dt.year.eq(year)]
            day = part.tradedate.min()
            code = sorted(part.loc[part.tradedate.eq(day), "secid"].unique())[0]
            selected.append({"asset": asset, "year": year, "source_date": str(day.date()),
                             "secid": code})
    base.require(selected == config["securities"], "metadata selection drift")


def requests_plan(config):
    result = [{"kind": "description", "identity": item, "url": config["description_url"].format(
        secid=item["secid"])} for item in config["securities"]]
    result += [{"kind": "calendar", "identity": {"date": day},
                "url": config["calendar_url"].format(date=day)}
               for day in config["calendar_dates"]]
    base.require(len(result) == config["transport"]["maximum_requests"], "request count")
    for item in result:
        u = urlsplit(item["url"])
        base.require(u.scheme == "https" and u.hostname in ("iss.moex.com", "apim.moex.com")
                     and u.username is None and "marketdata" not in item["url"], "request scope")
        if item["kind"] == "calendar":
            base.require(pd.Timestamp(item["identity"]["date"]) < base.BOUNDARY,
                         "protected calendar request")
    return result


def parse(raw, item):
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"status": "NON_JSON", "metadata_available": False}
    block_name = "description" if item["kind"] == "description" else "options"
    if not isinstance(payload, dict) or set(payload) != {block_name}:
        return {"status": "UNEXPECTED_BLOCKS", "metadata_available": False}
    block = payload[block_name]
    columns, rows = block.get("columns"), block.get("data")
    base.require(isinstance(columns, list) and isinstance(rows, list)
                 and len(columns) == len(set(columns))
                 and all(isinstance(row, list) and len(row) == len(columns) for row in rows),
                 "malformed metadata table")
    if item["kind"] == "description":
        base.require("name" in columns and "value" in columns, "description schema")
        keys = [str(row[columns.index("name")]) for row in rows]
        base.require(len(set(keys)) == len(keys), "duplicate description field")
        selected = {key: row[columns.index("value")] for key, row in zip(keys, rows, strict=True)
                    if key in DESCRIPTION_FIELDS}
        exact = str(selected.get("SECID", "")).casefold() == item["identity"]["secid"].casefold()
        return {"status": "EXACT_DESCRIPTION" if exact else "EMPTY_OR_IDENTITY_UNRESOLVED",
                "metadata_available": exact, "field_names": keys, "static_fields": selected,
                "source_rows": len(rows), "original_publication_proved": False}
    lower = [str(c).lower() for c in columns]
    base.require(len(lower) == len(set(lower)), "duplicate normalized calendar field")
    selected = [{name: row[i] for i, name in enumerate(lower) if name in CALENDAR_FIELDS}
                for row in rows]
    return {"status": "CALENDAR_TABLE" if rows else "EMPTY_CALENDAR",
            "metadata_available": bool(rows), "columns": columns, "source_rows": len(rows),
            "static_rows": selected, "original_publication_proved": False,
            "exact_secid_underlying_expiry_mapping_proved": False}


def fetch(session, item, config):
    settings = config["transport"]
    authenticated = urlsplit(item["url"]).hostname == settings["auth_only_host"]
    token = os.environ.get(settings["credential_environment"], "") if authenticated else ""
    base.require(not authenticated or bool(token), "missing service credential")
    headers = {"User-Agent": "trading-lab-static-metadata-research/1.0"}
    if authenticated:
        headers["Authorization"] = "Bearer " + token
    verify_tls = settings["ca_path"] if authenticated else True
    attempts = []
    for attempt in range(1, settings["maximum_attempts_per_request"] + 1):
        start = datetime.now(UTC).isoformat()
        try:
            with session.get(item["url"], headers=headers, timeout=settings["timeout_seconds"],
                             allow_redirects=False, stream=True, verify=verify_tls) as response:
                raw = bytearray()
                for chunk in response.iter_content(65536):
                    raw.extend(chunk)
                    base.require(len(raw) <= settings["maximum_response_bytes"], "response cap")
                base.require(not token or token.encode() not in raw,
                             "credential echoed; no persist")
                attempts.append({"attempt": attempt, "started_at_utc": start,
                                 "received_at_utc": datetime.now(UTC).isoformat(),
                                 "http_status": response.status_code,
                                 "tls": "pinned_moex_ca" if verify_tls is not True else "system"})
                return bytes(raw), attempts
        except requests.exceptions.SSLError:
            attempts.append({"attempt": attempt, "started_at_utc": start, "error": "TLS_ERROR"})
            if not authenticated and attempt < settings["maximum_attempts_per_request"]:
                verify_tls = settings["ca_path"]
                continue
            return None, attempts
        except requests.exceptions.RequestException as exc:
            attempts.append({"attempt": attempt, "started_at_utc": start,
                             "error": type(exc).__name__})
            if attempt == settings["maximum_attempts_per_request"]:
                return None, attempts
        time.sleep(settings["minimum_between_requests_seconds"])
    return None, attempts


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    config = verify(args.seal_sha)
    preflight(config)
    root = Path(config["output"])
    base.require(root.is_dir() and root.resolve() == root and not any(root.iterdir()),
                 "prepared new empty leaf required; no canonical rerun")
    results = []
    with requests.Session() as session:
        for i, item in enumerate(requests_plan(config)):
            raw, attempts = fetch(session, item, config)
            record = {**item, "attempts": attempts}
            if raw is None:
                record["parsed"] = {"status": "TRANSPORT_UNAVAILABLE", "metadata_available": False}
            else:
                path = root / f"response_{i:02d}.raw"
                with path.open("xb") as file:
                    file.write(raw)
                record["raw"] = {"path": path.name, "bytes": len(raw), "sha256": sha(raw)}
                record["parsed"] = (parse(raw, item) if attempts[-1]["http_status"] == 200 else
                                    {"status": "HTTP_ERROR", "metadata_available": False})
            base.write_json(root / f"record_{i:02d}.json", record)
            results.append(record)
            print(json.dumps({"request": i, "kind": item["kind"],
                              "status": record["parsed"]["status"]}), flush=True)
            time.sleep(config["transport"]["minimum_between_requests_seconds"])
    verify(args.seal_sha)
    base.write_json(root / "manifest.json", {
        "protocol_id": config["protocol_id"], "seal_sha256": args.seal_sha,
        "completed_at_utc": datetime.now(UTC).isoformat(), "results": results,
        "all_planned_attempted": len(results) == config["transport"]["maximum_requests"],
        "economic_admission": False, "goal_verified": False,
        "market_prices_positions_returns_or_pnl_read": False,
    })
    print(json.dumps({"root": str(root), "manifest_sha256": base.sha(root / "manifest.json")}),
          flush=True)


if __name__ == "__main__":
    main()
