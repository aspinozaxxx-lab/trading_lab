"""First attempts at two CSV URLs; timed-out legal page is not retried."""

import csv
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/sloos_fred_20260917_v1/csv")


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server user only")
    old = ROOT.parent / "capture"
    b.require(
        b.sha(old / "manifest.json")
        == "7a3290b2918e1ac582aff74fdef348daa0866564b205de1cd2f2ddcff74ccc60",
        "prior drift",
    )
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "maximum_requests": 2,
            "maximum_bytes": 1000000,
            "no_retry_or_redirect": True,
            "prior_failure": "Legal page only, HTTP000/curl28/30sec timeout/0bytes. "
            "Neither CSV URL was attempted. No access denial/challenge was returned. "
            "Legal page not retried; official terms read through web tool 2026-09-17.",
            "rights_url": "https://fred.stlouisfed.org/legal/",
            "rights_scope": "Limited personal noncommercial research download license, "
            "two small date-bounded copies; notices preserved, no distribution/service archive.",
            "attribution": "Board of Governors of the Federal Reserve System (US), SLOOS; "
            "FRED, Federal Reserve Bank of St. Louis.",
            "source_only": True,
            "economic_admission": False,
        },
    )
    status, failure, inventory = "COMPLETE_METADATA_ONLY", None, {}
    try:
        for series in ("DRTSCILM", "DRSDCILM"):
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series
            url += "&cosd=2017-10-01&coed=2025-12-31"
            raw = transport.fetch(url, ROOT / (series + ".csv"), 1000000, 1.0)
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            b.require(reader.fieldnames == ["observation_date", series], "CSV header")
            dates = []
            for row in reader:
                day = row["observation_date"]
                b.require("2017-10-01" <= day <= "2025-12-31", "outside/protected date")
                dates.append(day)
            inventory[series] = {
                "url": url,
                "rows": len(dates),
                "dates": dates,
                "raw_sha256": b.sha(ROOT / (series + ".csv")),
                "numeric_values_inspected": False,
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
