"""Bounded 56-release PDF corpus, reuse three samples, no numeric extraction."""

import json
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from market_lab import futures_v97_hurricane_supply as transport

PARENT = Path("/srv/trading_lab_data/source_evidence/cbr_sector_payments_20260917_v1")
ROOT = PARENT / "corpus"
INDEX_SHA = "a8881ea7681da93e9cf8da69409b0bcc6740a59d61c889856f667508da39f249"
REUSE = {
    "20210513": ("continuity", "44be7c43c85ec7d93ff791530a718344b70a718d33ee616e59009acd02805f48"),
    "20250410": ("capture", "c5fc8e54a476d49eb2797620e2a9089ef0c176d22d0f1a727d22235b1105e7f4"),
    "20251211": ("continuity", "7a209bb22f90d0efa822c92f3e95a8794402de9cba65c7c69a4bebd7917186a4"),
}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href, self.words, self.links = None, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.words = dict(attrs).get("href", ""), []

    def handle_data(self, text):
        if self.href is not None:
            self.words.append(text)

    def handle_endtag(self, tag):
        if tag != "a" or self.href is None:
            return
        match = re.fullmatch(r"/Collection/Collection/File/\d+/finflows_(\d{8})\.pdf", self.href)
        if match and "20210501" <= match[1] <= "20251231":
            day = datetime.strptime(match[1], "%Y%m%d")
            label = " ".join(self.words).replace("\xa0", " ")
            transport.base.require(day.strftime("%d.%m.%Y") in label, "index label/date mismatch")
            self.links.append({"release_date": day.date().isoformat(),
                               "file": "finflows_" + match[1] + ".pdf",
                               "url": urljoin("https://www.cbr.ru", self.href),
                               "label": label})
        self.href = None


def main():
    b = transport.base
    b.require(os.name == "posix" and os.getuid() == 999, "server research user only")
    index = PARENT / "capture/index.html"
    b.require(b.sha(index) == INDEX_SHA, "index drift")
    parser = Links()
    parser.feed(index.read_text(encoding="utf-8-sig"))
    links = sorted(parser.links, key=lambda r: r["release_date"])
    months = Counter(r["release_date"][:7] for r in links)
    expected = {f"{year}-{month:02}": 1 for year in range(2021, 2026)
                for month in range(5 if year == 2021 else 1, 13)}
    b.require(len(links) == 56 and months == expected, "56 monthly releases required")
    ROOT.mkdir(exist_ok=False)
    b.write_json(ROOT / "started.json", {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "script_sha256": b.sha(Path(__file__)),
        "transport_sha256": b.sha(Path(transport.__file__)),
        "index_sha256": INDEX_SHA,
        "maximum_http_requests": 53,
        "maximum_response_bytes": 10000000,
        "no_retry_or_redirect": True,
        "scope": "56 current copies of dated 2021-2025 CBR monthly reports. "
        "Private attributed research only, no raw redistribution. "
        "No numeric extraction, source admission is not economic admission.",
        "rights_reference": "cbr_bank_funding_20260917_v2/capture: terms.html and agreement.html",
        "releases": links,
    })
    failure, completed, requested, reused = None, [], 0, 0
    try:
        for record in links:
            name = record["file"]
            stamp = record["release_date"].replace("-", "")
            if stamp in REUSE:
                folder, digest = REUSE[stamp]
                source = PARENT / folder / name
                b.require(b.sha(source) == digest, "reused sample drift")
                shutil.copyfile(source, ROOT / name)
                shutil.copyfile(source.with_suffix(".pdf.metadata.json"),
                                (ROOT / name).with_suffix(".pdf.metadata.json"))
                raw = (ROOT / name).read_bytes()
                reused += 1
            else:
                requested += 1
                raw = transport.fetch(record["url"], ROOT / name, 10000000, 1.0)
            b.require(raw.startswith(b"%PDF-"), "not a PDF")
            completed.append({**record, "sha256": b.sha(ROOT / name),
                              "bytes": len(raw), "reused": stamp in REUSE})
            print(json.dumps({"completed": len(completed), "release": record["release_date"]}),
                  flush=True)
    except Exception as error:
        failure = str(error)
    result = {
        "status": "FAILED_SOURCE_NO_RETRY" if failure else "COMPLETE_RAW_CORPUS_ONLY",
        "failure": failure,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "requests": requested,
        "reused": reused,
        "economic_admission": False,
        "releases": completed,
        "files": {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
    }
    b.write_json(ROOT / "manifest.json", result)
    print(json.dumps({"status": result["status"], "completed": len(completed),
                      "failure": failure}), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
