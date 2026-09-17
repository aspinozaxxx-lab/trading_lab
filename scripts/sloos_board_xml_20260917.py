"""One official Board XML download; inventory archive/schema without observation values."""

import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path("/srv/trading_lab_data/source_evidence/sloos_board_20260917_v1/capture")
URL = "https://www.federalreserve.gov/releases/sloos/data/FRB_SLOOS_xml.zip"


def main():
    b = prior.base
    b.require(os.name == "posix" and os.getuid() == 999, "server user only")
    ROOT.mkdir(exist_ok=False)
    old = Path("/srv/trading_lab_data/source_evidence/sloos_feasibility_20260917_v1/capture")
    b.require(
        b.sha(old / "index.html")
        == "39fbbfed4f0761577324444646f940a7ed64a8f93370d35a33a2748ae7dcc4da",
        "index drift",
    )
    b.require(
        b.sha(old / "terms.html")
        == "fa241d5b4381b2625282c2c34c6f651cca8218f92bf95572ef10140900905a76",
        "terms drift",
    )
    b.require(
        b"/releases/sloos/data/FRB_SLOOS_xml.zip" in (old / "index.html").read_bytes(),
        "link not witnessed",
    )
    b.write_json(
        ROOT / "started.json",
        {
            "started_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": b.sha(Path(__file__)),
            "transport_sha256": b.sha(Path(transport.__file__)),
            "url": URL,
            "maximum_requests": 1,
            "maximum_response_bytes": 5000000,
            "maximum_uncompressed_bytes": 50000000,
            "no_retry_or_redirect": True,
            "attribution": "Board of Governors of the Federal Reserve System, SLOOS",
            "terms_evidence": str(old / "terms.html"),
            "rights": "Board published data, public domain except marked third-party content; "
            "private research only, preserve attribution/notices, no redistribution/endorsement.",
            "source_only": True,
            "economic_admission": False,
            "reason": "Separate official current-vintage machine export, not original-vintage "
            "reconstruction or a retry of FRED timeouts. Same pre-stated credit-squeeze mechanism. "
            "2026/other-series observation cells stay uninspected/quarantined.",
        },
    )
    status, failure, inventory = "COMPLETE_SCHEMA_ONLY", None, []
    try:
        raw = transport.fetch(URL, ROOT / "FRB_SLOOS_xml.zip", 5000000, 1.0)
        archive = zipfile.ZipFile(io.BytesIO(raw))
        b.require(sum(m.file_size for m in archive.infolist()) <= 50000000, "archive expansion")
        for item in archive.infolist():
            info = {"name": item.filename, "bytes": item.file_size}
            if item.filename.lower().endswith(".xml"):
                tree = ET.fromstring(archive.read(item))
                info["root"] = tree.tag
                series = []
                for element in tree.iter():
                    if element.tag.split("}")[-1].lower() == "series":
                        series.append(
                            {
                                "attributes": element.attrib,
                                "metadata_children": [
                                    {
                                        "tag": c.tag,
                                        "attributes": c.attrib,
                                        "text": (c.text or "").strip()[:500],
                                    }
                                    for c in element
                                    if c.tag.split("}")[-1].lower() not in ("obs", "observation")
                                ],
                            }
                        )
                info["series"] = series
            inventory.append(info)
        b.write_json(ROOT / "schema.json", inventory)
    except Exception as error:
        status, failure = "FAILED_SOURCE_PAUSED", str(error)
    b.write_json(
        ROOT / "manifest.json",
        {
            "status": status,
            "failure": failure,
            "economic_admission": False,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
        },
    )
    print(
        json.dumps(
            {
                "status": status,
                "failure": failure,
                "manifest_sha256": b.sha(ROOT / "manifest.json"),
                "members": [{k: v for k, v in r.items() if k != "series"} for r in inventory],
            }
        ),
        flush=True,
    )
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
