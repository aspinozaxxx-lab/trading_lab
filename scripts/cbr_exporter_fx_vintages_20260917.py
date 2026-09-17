"""One bounded 2023-2025 CBR appendix batch; raw capture, no economic admission."""

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/cbr_exporter_fx_sample_20260917_v1/vintages")
INDEX_SHA = "c927dc43c89c42cff176f6c8b7e37a1733a15b8dacddbdd73a19a3b9cd13cc0b"
REUSE = {
    "2023-04": (
        "continuity/charts_ORFR_2023-04.xlsx",
        "dbbb7594889d4df9d4612f550dca7a3a352691b081d400c55575ba0578d32d37",
    ),
    "2025-04": (
        "appendix/charts_ORFR_2025-4.xlsx",
        "fac734de0de78d620d2fb2ab696ae305af0a07b16c5f774855def7b5ad36583c",
    ),
    "2025-11": (
        "continuity/ORFR_2025-11.xlsx",
        "8da786c8da8eb9b79d47b4748fc3eda49bd18d9f85908b29ea43f5cc442e242e",
    ),
}


def jobs(raw):
    result = {}
    for href in re.findall(r'href="([^"]+)"', raw.decode("utf-8-sig")):
        if not re.fullmatch(r"/Collection/Collection/File/\d+/[A-Za-z0-9_-]+\.xlsx", href, re.I):
            continue
        name = href.rsplit("/", 1)[1]
        if name == "charts_ORFR_2024-25-1.xlsx":
            period = "2025-01"
        else:
            match = re.fullmatch(r"(?:charts_)?ORFR_(2023|2024|2025)-(\d{1,2})\.xlsx", name, re.I)
            if not match:
                continue  # Includes all 2026 and December2025-January2026 files.
            period = f"{match[1]}-{int(match[2]):02}"
        prior.base.require("2023-04" <= period <= "2025-11", "out of sample period")
        prior.base.require(period not in result, "duplicate period")
        result[period] = "https://www.cbr.ru" + href
    expected = {f"2023-{m:02}" for m in range(4, 13)}
    expected |= {f"2024-{m:02}" for m in range(1, 12)}
    expected |= {f"2025-{m:02}" for m in range(1, 12)}
    prior.base.require(set(result) == expected, "index coverage drift")
    return dict(sorted(result.items()))


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server research user only")
    index = ROOT.parent / "capture/statistics_index.html"
    b.require(b.sha(index) == INDEX_SHA, "index drift")
    inventory = jobs(index.read_bytes())
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "maximum_requests": 28,
            "maximum_response_bytes": 10000000,
            "no_retry_or_redirect": True,
            "economic_admission": False,
            "source_index_sha256": INDEX_SHA,
            "jobs": inventory,
            "scope": "CBR release-specific appendices April2023-November2025 only. "
            "Raw capture and later metadata coverage check. No prices/targets/PnL extraction. "
            "Private research, no raw redistribution, existing CBR rights notes retained. "
            "File date labels are not original publication/receipt proof. "
            "Combined December2024-January2025 issue cannot be split into invented releases.",
        },
    )
    failure, completed, requested = None, [], 0
    try:
        for period, url in inventory.items():
            target = ROOT / (period + ".xlsx")
            if period in REUSE:
                rel, digest = REUSE[period]
                source = ROOT.parent / rel
                b.require(b.sha(source) == digest, "reused source drift")
                b.require(not target.exists(), "no overwrite")
                shutil.copyfile(source, target)
                b.write_json(
                    target.with_suffix(".reference.json"),
                    {
                        "relative_origin": rel,
                        "sha256": digest,
                        "url": url,
                    },
                )
            else:
                requested += 1
                raw = transport.fetch(url, target, 10000000, 1.0)
                b.require(raw.startswith(b"PK\x03\x04"), "not XLSX/ZIP")
            completed.append(period)
    except Exception as error:
        failure = str(error)
    result = {
        "status": "FAILED_SOURCE_NO_RETRY" if failure else "COMPLETE_RAW_ONLY",
        "failure": failure,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "economic_admission": False,
        "completed_periods": completed,
        "http_requests": requested,
        "reused_files": [p for p in completed if p in REUSE],
        "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
    }
    b.write_json(ROOT / "manifest.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
