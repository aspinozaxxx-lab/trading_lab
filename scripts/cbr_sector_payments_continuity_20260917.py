"""Early/late monthly PDF layout sample, not a signal or economic result."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport

ROOT = Path(
    "/srv/trading_lab_data/source_evidence/cbr_sector_payments_20260917_v1/continuity"
)
REQUESTS = (
    ("finflows_20210513.pdf", "https://www.cbr.ru/Collection/Collection/File/32280/finflows_20210513.pdf"),
    ("finflows_20251211.pdf", "https://www.cbr.ru/Collection/Collection/File/59481/finflows_20251211.pdf"),
)


def main():
    b = transport.base
    b.require(os.name == "posix" and os.getuid() == 999, "server research user only")
    ROOT.mkdir(exist_ok=False)
    b.write_json(ROOT / "started.json", {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "script_sha256": b.sha(Path(__file__)),
        "transport_sha256": b.sha(Path(transport.__file__)),
        "maximum_requests": 2,
        "maximum_response_bytes": 10000000,
        "no_retry_or_redirect": True,
        "scope": "Dated May2021/December2025 PDFs, monthly source layout/definition only. "
        "No new signals, market outcomes or economic admission. "
        "Private research with CBR attribution, no raw redistribution.",
        "rights_reference": "cbr_bank_funding_20260917_v2/capture: terms.html and agreement.html",
    })
    failure = None
    try:
        for name, url in REQUESTS:
            raw = transport.fetch(url, ROOT / name, 10000000, 1.0)
            b.require(raw.startswith(b"%PDF-"), "not a PDF")
    except Exception as error:
        failure = str(error)
    result = {
        "status": "FAILED_SOURCE_NO_RETRY" if failure else "COMPLETE_SOURCE_SAMPLE_ONLY",
        "failure": failure,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "economic_admission": False,
        "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
    }
    b.write_json(ROOT / "manifest.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
