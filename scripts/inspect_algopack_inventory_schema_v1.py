"""One historical metadata request; print schema/types, never response values or secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime

import requests

from market_lab.futures.moex_algopack_fo_historical_inventory_v1 import (
    TOKEN_ENV,
    InventoryFailure,
    _fetch,
    request_url,
    sha,
    verify_seal,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("tradestats", "obstats"), required=True)
    args = parser.parse_args()
    verify_seal("5e3b01bad972fa06123ae99754ea1578d3cacf4446e06d4a66c52ba6c3543cc8")
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise ValueError("missing credential")
    raw, evidence = _fetch(requests.Session(), request_url(args.dataset, 0), token)
    payload = json.loads(raw)
    output = {"request_evidence": evidence, "response_bytes": len(raw), "response_sha256": sha(raw)}
    blocks = {}
    if isinstance(payload, dict):
        for name, table in payload.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.]+", name):
                continue
            if not isinstance(table, dict):
                blocks[name] = {"type": type(table).__name__}
                continue
            columns, rows = table.get("columns"), table.get("data")
            if not isinstance(columns, list) or not all(
                isinstance(c, str) and re.fullmatch(r"[A-Za-z0-9_.]+", c) for c in columns
            ):
                blocks[name] = {"columns_unavailable": True}
                continue
            info = {"columns": columns, "rows": len(rows) if isinstance(rows, list) else None}
            if isinstance(rows, list) and rows and isinstance(rows[0], list):
                info["first_row_types"] = [type(value).__name__ for value in rows[0]]
            if (name == "data.cursor" and columns == ["INDEX", "TOTAL", "PAGESIZE"]
                    and isinstance(rows, list) and len(rows) == 1
                    and all(type(value) is int for value in rows[0])):
                info["cursor_counts"] = rows[0]
            if name == "data" and "tradedate" in columns and isinstance(rows, list):
                index = columns.index("tradedate")
                dates = {row[index] for row in rows if isinstance(row, list) and len(row) > index}
                if all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", value)
                       for value in dates):
                    info["source_dates"] = sorted(dates)
                if columns == ["tradedate", "tradetime", "secid", "asset_code", "SYSTIME"]:
                    anomalies = Counter()
                    keys = set()
                    for values in rows:
                        if not isinstance(values, list) or len(values) != 5:
                            anomalies["row_width"] += 1
                            continue
                        row = dict(zip(columns, values, strict=True))
                        for column, value in row.items():
                            if not isinstance(value, str) or not value:
                                anomalies[column + "_missing_or_nonstring"] += 1
                        try:
                            parsed_time = datetime.strptime(row["tradetime"], "%H:%M:%S")
                            if parsed_time.strftime("%H:%M:%S") != row["tradetime"]:
                                anomalies["noncanonical_time_format"] += 1
                            system_time = datetime.fromisoformat(row["SYSTIME"])
                            if system_time.tzinfo is not None:
                                anomalies["system_timezone_aware"] += 1
                            elif system_time < datetime.fromisoformat(
                                row["tradedate"] + " " + row["tradetime"]
                            ):
                                anomalies["system_before_observation"] += 1
                        except (ValueError, TypeError):
                            anomalies["timestamp_parse"] += 1
                        for column in ("secid", "asset_code"):
                            value = row[column]
                            if not isinstance(value, str) or not re.fullmatch(
                                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value
                            ):
                                anomalies[column + "_identifier_pattern"] += 1
                        key = (row["tradedate"], row["tradetime"], row["secid"])
                        if key in keys:
                            anomalies["duplicate_key"] += 1
                        keys.add(key)
                    info["metadata_anomaly_counts"] = dict(anomalies)
            blocks[name] = info
    output["blocks"] = blocks
    print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except InventoryFailure as error:
        print(json.dumps({"phase": error.phase, "http_status": error.http_status}))
        raise SystemExit(2) from None
    except Exception:
        raise SystemExit("Schema inspection failed; response details suppressed") from None
