"""One route-format repair; reuse three captured pages, nine new sample GETs."""

import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

PARENT = Path("/srv/trading_lab_data/source_evidence/sloos_feasibility_20260917_v1")
ROOT = PARENT / "capture_v2"
ORIGIN = "https://www.federalreserve.gov"
SAMPLES = ["201710", "201802", "202510"]


def links(raw, page):
    return sorted(
        {urljoin(page, u) for u in re.findall(r'href=["\']([^"\']+)["\']', raw.decode("utf-8-sig"))}
    )


def unique(items, pattern):
    result = [
        u
        for u in items
        if urlparse(u).netloc == "www.federalreserve.gov"
        and urlparse(u).scheme == "https"
        and re.fullmatch(pattern, urlparse(u).path)
        and not urlparse(u).query
    ]
    prior.base.require(len(result) == 1, "ambiguous official sample link: " + pattern)
    return result[0]


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server user only")
    old = PARENT / "capture"
    expected = "0faf4de5f35477e81838307c98d1aaf51095891485d2d1f904adb6047640d9ed"
    b.require(b.sha(old / "manifest.json") == expected, "failed source drift")
    m = prior.read_json(old / "manifest.json")
    b.require(m["status"] == "FAILED_SOURCE_NO_RETRY", "wrong source status")
    for name, digest in m["files"].items():
        b.require(b.sha(b.safe(old, name)) == digest, "failed artifact drift")
    ROOT.mkdir(exist_ok=False)
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "samples": SAMPLES,
            "maximum_new_requests": 9,
            "maximum_response_bytes": 3000000,
            "reused_manifest_sha256": expected,
            "source_only": True,
            "economic_admission": False,
            "no_retry_or_redirect": True,
            "attribution": "Board of Governors of the Federal Reserve System, SLOOS; "
            "private research, original notices retained, no endorsement.",
            "repair": "Legacy201710/default.htm, relative table1.htm/fullreport.pdf; "
            "201802 is the first2018 survey identifier. No protected or missing releases invented.",
            "prior_exposure": "2017Oct narrative/standards/terms and2025Jan/Oct narrative "
            "plus2025Octstandards seen on web. No corpus states, targets or new PnL.",
        },
    )
    status, failure, requests, selected = "COMPLETE_FEASIBILITY_ONLY", None, 0, {}
    try:
        for name in ["index.html", "terms.html", "announcements.html"]:
            for suffix in ["", ".metadata.json"]:
                shutil.copyfile(old / (name + suffix), ROOT / (name + suffix))
        index = links((ROOT / "index.html").read_bytes(), ORIGIN + "/data/sloos.htm")
        for sample in SAMPLES:
            url = unique(index, rf"/data/sloos/(?:sloos-{sample}\.htm|{sample}/default\.htm)")
            requests += 1
            raw = transport.fetch(url, ROOT / (sample + ".html"), 3000000, 1.0)
            items = links(raw, url)
            table = unique(
                items,
                rf"/data/sloos/(?:sloos-{sample}-table-1\.htm|"
                rf"{sample}/table1\.htm)",
            )
            cover = unique(
                items,
                rf"/data/(?:documents/sloos-{sample}(?:-fullreport)?\.pdf|"
                rf"sloos/{sample}/fullreport\.pdf)",
            )
            selected[sample] = {"narrative": url, "table": table, "cover": cover}
            for name, target in [(sample + "-table.html", table), (sample + ".pdf", cover)]:
                requests += 1
                transport.fetch(target, ROOT / name, 3000000, 1.0)
            print(sample, "captured", flush=True)
        b.write_json(ROOT / "links.json", selected)
    except Exception as error:
        status, failure = "FAILED_SOURCE_PAUSED", str(error)
    b.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "new_requests_attempted": requests,
            "reused_files": 6,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "source_only": True,
            "economic_admission": False,
            "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(status, b.sha(ROOT / "manifest.json"), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
