"""Two metadata-only GETs for the official historical menu and its API routing."""

import os
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport

ROOT = Path("/srv/trading_lab_data/source_evidence/dealer_metadata_20260917_v1/menu")
URLS = {
    "main.js": "https://www.newyorkfed.org/medialibrary/Interactives/markets-data/"
    "gsds/gsds-pi-ui/browser/main.js",
    "menu.json": "https://markets.newyorkfed.org/read?"
    "productCode=refdata&targetProductCode=40&group=menu",
}


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
            "urls": URLS,
            "maximum_requests": 2,
            "maximum_response_bytes": 2_000_000,
            "source_only": True,
            "numeric_survey_values_read": False,
            "terms_evidence": "../capture/terms.html",
            "economic_admission": False,
        },
    )
    status, failure = "COMPLETE_METADATA_ONLY", None
    try:
        for name, url in URLS.items():
            raw = transport.fetch(url, ROOT / name, 2_000_000, 1.0)
            print(name, len(raw), flush=True)
    except Exception as error:
        status, failure = "FAILED_METADATA_CAPTURE", str(error)
    base.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "numeric_survey_values_read": False,
            "economic_admission": False,
            "files": {p.name: base.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(status, "manifest", base.sha(ROOT / "manifest.json"), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
