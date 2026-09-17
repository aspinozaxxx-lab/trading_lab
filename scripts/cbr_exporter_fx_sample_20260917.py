"""Bounded read-only exporter FX source sample, not a trading experiment."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/cbr_exporter_fx_sample_20260917_v1/capture")
REQUESTS = (
    ("ORFR_2025-4.pdf", "https://www.cbr.ru/Collection/Collection/File/55867/ORFR_2025-4.pdf"),
    ("statistics_index.html", "https://www.cbr.ru/finstab/statistics/"),
    ("calendar.html", "https://www.cbr.ru/calendar/"),
)


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server research user only")
    ROOT.mkdir(exist_ok=False)
    b.write_json(ROOT / "started.json", {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "script_sha256": b.sha(Path(__file__)),
        "transport_sha256": b.sha(Path(transport.__file__)),
        "maximum_requests": 3,
        "maximum_response_bytes": 10000000,
        "no_retry_or_redirect": True,
        "scope": "Bank of Russia; private historical research, no raw redistribution. "
        "April2025 PDF plus source index/calendar metadata only. No 2026 market data. "
        "No economic rule, features, labels, PnL or admission. "
        "Current calendar is not proof of original publication time.",
        "rights_reference": "cbr_bank_funding_20260917_v2/capture: terms.html and agreement.html",
    })
    failure = None
    try:
        for name, url in REQUESTS:
            raw = transport.fetch(url, ROOT / name, 10000000, 1.0)
            if name.endswith(".pdf"):
                b.require(raw.startswith(b"%PDF-"), "response is not a PDF")
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
