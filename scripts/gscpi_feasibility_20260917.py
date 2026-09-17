"""Four bounded source-only captures; no numeric series, markets or economic model read."""

import os
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport

ROOT = Path("/srv/trading_lab_data/source_evidence/gscpi_probe_20260917_v1/capture")
URLS = {
    "index.html": "https://www.newyorkfed.org/research/policy/gscpi",
    "terms.html": "https://www.newyorkfed.org/privacy/termsofuse",
    "description.json": (
        "https://www.newyorkfed.org/medialibrary/research/interactives/data/gscpi/gscpi.json"
    ),
    "gscpi_interactive_data.csv": (
        "https://www.newyorkfed.org/medialibrary/research/interactives/data/gscpi/"
        "gscpi_interactive_data.csv"
    ),
}


def main():
    base = transport.base
    base.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    base.require(
        ROOT.parent.resolve()
        == Path("/srv/trading_lab_data/source_evidence/gscpi_probe_20260917_v1"),
        "unexpected destination",
    )
    ROOT.mkdir(exist_ok=False)
    base.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": base.sha(Path(__file__)),
            "transport_sha256": base.sha(Path(transport.__file__)),
            "urls": URLS,
            "maximum_requests": 4,
            "maximum_response_bytes": 2_000_000,
            "no_retry_or_redirect": True,
            "source_only": True,
            "numeric_values_read": False,
            "economic_admission": False,
            "scope": (
                "Raw macro index quarantined; header/date-only inventory before any numeric read."
            ),
            "attribution": (
                "Global Supply Chain Pressure Index. Gianluca Benigno, Julian di Giovanni, "
                "Jan J. J. Groen, Adam I. Noble. Federal Reserve Bank of New York. "
                "Content subject to https://www.newyorkfed.org/privacy/termsofuse . "
                "Private research only; no affiliation or endorsement; "
                "underlying vendor feeds excluded."
            ),
        },
    )
    status, failure = "COMPLETE_FEASIBILITY_CAPTURE_ONLY", None
    try:
        for name, url in URLS.items():
            raw = transport.fetch(url, ROOT / name, 2_000_000, 1.0)
            print(name, len(raw), flush=True)
    except Exception as error:
        status, failure = "FAILED_FEASIBILITY_CAPTURE", str(error)
    base.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "source_only": True,
            "numeric_values_read": False,
            "economic_admission": False,
            "files": {p.name: base.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(status, "manifest", base.sha(ROOT / "manifest.json"), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
