"""Two official requests, metadata only; no source values or outcomes interpreted."""

import csv
import io
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/ebp_20260917_v1/capture")
ORIGIN = "https://www.federalreserve.gov/econres/notes/feds-notes/"
NOTE = ORIGIN + "updating-the-recession-risk-and-the-excess-bond-premium-20161006.html"
CSV = ORIGIN + "ebp_csv.csv"


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server user only")
    terms = Path(
        "/srv/trading_lab_data/source_evidence/sloos_feasibility_20260917_v1/capture/terms.html"
    )
    b.require(
        b.sha(terms) == "fa241d5b4381b2625282c2c34c6f651cca8218f92bf95572ef10140900905a76",
        "Board terms drift",
    )
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "maximum_requests": 2,
            "maximum_response_bytes": 1000000,
            "no_retry_or_redirect": True,
            "economic_admission": False,
            "attribution": "Favara, Gilchrist, Lewis, Zakrajsek (2016), Board of Governors, "
            "Updating the Recession Risk and the Excess Bond Premium, doi:10.17016/2380-7172.1836",
            "terms_evidence": str(terms),
            "rights": "Personal research using the Board's explicitly published research CSV; "
            "no underlying proprietary security-level data, redistribution, commercial product "
            "or endorsement. Original notices retained.",
            "limitations": "Staff research/current vintage. Whole history may revise each month, "
            "monthly release may be delayed. Neither lag nor source download proves original PIT. "
            "Only dates/schema inspected.2026 and unrelated fields, "
            "including recession probabilities, "
            "remain uninspected; no archive-training or market outcome scope expansion.",
        },
    )
    status, failure, inventory = "COMPLETE_METADATA_ONLY", None, {}
    try:
        note = transport.fetch(NOTE, ROOT / "note.html", 1000000, 1.0)
        b.require(b"ebp_csv.csv" in note, "CSV link not witnessed")
        raw = transport.fetch(CSV, ROOT / "ebp.csv", 1000000, 1.0)
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        headers = reader.fieldnames
        b.require(headers is not None and len(headers) == len(set(headers)), "CSV headers")
        date_key = headers[0]
        dates = []
        for row in reader:
            b.require(set(row) == set(headers), "row width")
            day = row[date_key]
            b.require(
                isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day), "date format"
            )
            dates.append(day)
        b.require(bool(dates) and dates == sorted(set(dates)), "date ordering/duplicates")
        eligible = [d for d in dates if "2017-11-01" <= d <= "2025-12-31"]
        inventory = {
            "headers": headers,
            "date_key": date_key,
            "raw_rows": len(dates),
            "first_date": dates[0],
            "last_date": dates[-1],
            "selected_dates": eligible,
            "selected_rows": len(eligible),
            "source_values_inspected": False,
            "raw_sha256": b.sha(ROOT / "ebp.csv"),
        }
        b.write_json(ROOT / "inventory.json", inventory)
    except Exception as error:
        status, failure = "FAILED_SOURCE_NO_RETRY", str(error)
    b.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "economic_admission": False,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(
        json.dumps(
            {
                "status": status,
                "failure": failure,
                "inventory": inventory,
                "manifest_sha256": b.sha(ROOT / "manifest.json"),
            }
        ),
        flush=True,
    )
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
