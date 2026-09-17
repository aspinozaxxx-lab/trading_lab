"""Two bounded personal-research SLOOS CSV copies; metadata only, no retries."""

import csv
import io
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/sloos_fred_20260917_v1/capture")
SERIES = ("DRTSCILM", "DRSDCILM")


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server user only")
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "source_only": True,
            "economic_admission": False,
            "maximum_requests": 3,
            "maximum_bytes_per_response": 1000000,
            "no_retry_or_redirect": True,
            "attribution": "Board of Governors of the Federal Reserve System (US), SLOOS, "
            "retrieved through FRED, Federal Reserve Bank of St. Louis.",
            "rights_scope": "Two small date-bounded copies solely for personal noncommercial "
            "research under FRED General License; notices retained. No service replication, "
            "distribution, commercial product, account, or paid access.",
            "distinct_from_paused_branch": "Not a repair/resumption of original PDF/HTML "
            "reconstruction. Current-vintage aggregate CSV; original vintages not proved.",
        },
    )
    status, failure, inventory = "COMPLETE_METADATA_ONLY", None, {}
    try:
        transport.fetch("https://fred.stlouisfed.org/legal/", ROOT / "terms.html", 1000000, 1.0)
        expected = list(pd.date_range("2017-10-01", "2025-10-01", freq="QS"))
        for series in SERIES:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series
            url += "&cosd=2017-10-01&coed=2025-12-31"
            raw = transport.fetch(url, ROOT / (series + ".csv"), 1000000, 1.0)
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            b.require(reader.fieldnames == ["observation_date", series], "CSV header identity")
            dates, missing = [], 0
            for row in reader:
                text = row["observation_date"]
                b.require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text), "date format")
                b.require("2017-10-01" <= text <= "2025-12-31", "protected/outside date")
                dates.append(pd.Timestamp(text))
                token = row[series]
                b.require(token == "." or re.fullmatch(r"-?\d+(?:\.\d+)?", token), "cell token")
                missing += token == "."
            b.require(dates == expected, "quarter calendar coverage/duplicates/order")
            inventory[series] = {
                "url": url,
                "rows": len(dates),
                "missing": missing,
                "first_date": str(dates[0].date()),
                "last_date": str(dates[-1].date()),
                "raw_sha256": b.sha(ROOT / (series + ".csv")),
                "numeric_values_converted": False,
            }
        b.write_json(ROOT / "inventory.json", inventory)
    except Exception as error:
        status, failure = "FAILED_SOURCE_NO_RETRY", str(error)
    b.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "economic_admission": False,
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
