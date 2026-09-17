"""One bounded source-only capture; no market inputs, signal, economic run or retry."""

from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport

ROOT = Path("/srv/trading_lab_data/source_evidence/cbr_bop_probe_20260917_v1/capture")
URLS = {
    "index.html": "https://cbr.ru/analytics/dkp/bal/",
    "estimate_method.html": (
        "https://cbr.ru/statistics/macro_itm/external_sector/pb/meth_est_bop/"
    ),
    "revision_method.html": ("https://cbr.ru/statistics/macro_itm/external_sector/pb/met_change/"),
    "q1_2021.pdf": (
        "https://cbr.ru/Collection/Collection/File/32216/Balance_of_Payments_2021-01_7.pdf"
    ),
    "q3_2025.pdf": (
        "https://cbr.ru/Collection/Collection/File/59425/Balance_of_Payments_2025-3_24.pdf"
    ),
}


def main():
    import os

    base = transport.base
    base.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    base.require(
        ROOT.parent.resolve()
        == Path("/srv/trading_lab_data/source_evidence/cbr_bop_probe_20260917_v1"),
        "unexpected destination",
    )
    ROOT.mkdir(exist_ok=False)
    base.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": base.sha(Path(__file__)),
            "transport_sha256": base.sha(Path(transport.__file__)),
            "source_only": True,
            "economic_admission": False,
            "urls": URLS,
            "maximum_requests": 5,
            "maximum_response_bytes": 5_000_000,
            "no_retry_or_redirect": True,
        },
    )
    status, failure = "COMPLETE_FEASIBILITY_CAPTURE_ONLY", None
    try:
        for name, url in URLS.items():
            raw = transport.fetch(url, ROOT / name, 5_000_000, 1.0)
            base.require(
                raw.startswith(b"%PDF-") if name.endswith(".pdf") else b"<html" in raw.lower(),
                "wrong response format",
            )
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
            "economic_admission": False,
            "files": {p.name: base.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(status, "manifest", base.sha(ROOT / "manifest.json"), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
