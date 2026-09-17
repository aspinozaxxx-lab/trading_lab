"""Earliest/latest pre-2026 XLSX samples, metadata feasibility only."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/cbr_exporter_fx_sample_20260917_v1/continuity")
REQUESTS = (
    (
        "charts_ORFR_2023-04.xlsx",
        "https://www.cbr.ru/Collection/Collection/File/43974/charts_ORFR_2023-04.xlsx",
    ),
    ("ORFR_2025-11.xlsx", "https://www.cbr.ru/Collection/Collection/File/59480/ORFR_2025-11.xlsx"),
)


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server research user only")
    index = ROOT.parent / "capture/statistics_index.html"
    expected = "c927dc43c89c42cff176f6c8b7e37a1733a15b8dacddbdd73a19a3b9cd13cc0b"
    b.require(b.sha(index) == expected, "index drift")
    for _, url in REQUESTS:
        b.require(url.split("www.cbr.ru", 1)[1].encode() in index.read_bytes(), "not indexed")
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "maximum_requests": 2,
            "maximum_response_bytes": 10000000,
            "no_retry_or_redirect": True,
            "economic_admission": False,
            "scope": "Earliest and latest eligible appendix in saved CBR index, metadata only. "
            "Private research, no raw redistribution, no 2026 source or new trading outcomes.",
        },
    )
    failure = None
    try:
        for name, url in REQUESTS:
            raw = transport.fetch(url, ROOT / name, 10000000, 1.0)
            b.require(raw.startswith(b"PK\x03\x04"), "not XLSX/ZIP")
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
