"""One date-bounded raw capture for a fixed private-deleveraging candidate."""

import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from market_lab import futures_v97_hurricane_supply as transport

ROOT = Path("/srv/trading_lab_data/source_evidence/dealer_metadata_20260917_v1/source")
KEYS = [
    prefix + venue + "UTSET" + maturity
    for prefix in ("PDSORA-", "PDSIRRA-")
    for venue in ("UBG", "UBS")
    for maturity in ("", "TAL30", "TAG30")
]
URL = "https://markets.newyorkfed.org/read?" + urlencode(
    {
        "productCode": "40",
        "startDt": "2022-01-05",
        "endDt": "2025-12-31",
        "keyIds": ",".join(KEYS),
        "format": "json",
    }
)


def main():
    base = transport.base
    base.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    ROOT.mkdir(exist_ok=False)
    base.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": base.sha(Path(__file__)),
            "transport_sha256": base.sha(Path(transport.__file__)),
            "url": URL,
            "selected_keys": KEYS,
            "maximum_requests": 1,
            "maximum_response_bytes": 3_000_000,
            "economic_admission": False,
            "numeric_magnitudes_read": False,
            "fixed_candidate_before_capture": "Both nominal-Treasury uncleared bilateral repo "
            "borrowing and reverse-repo lending lower than four reports earlier -> SI long/cash. "
            "Sum general/specified collateral across three disjoint maturity buckets per side. "
            "Not capital capacity, solvency or a proven causal USD/RUB predictor. "
            "No broad total or incompatible pre2022 financing substitution.",
            "scope": "Quarantine raw for schema/date/missingness inspection first; "
            "economic code/config/seal required before any numeric feature or PnL calculation.",
        },
    )
    status, failure = "COMPLETE_RAW_QUARANTINE_ONLY", None
    try:
        raw = transport.fetch(URL, ROOT / "financing.json", 3_000_000, 1.0)
        print("financing.json", len(raw), flush=True)
    except Exception as error:
        status, failure = "FAILED_SOURCE_CAPTURE", str(error)
    base.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "numeric_magnitudes_read": False,
            "economic_admission": False,
            "files": {p.name: base.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(status, "manifest", base.sha(ROOT / "manifest.json"), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
