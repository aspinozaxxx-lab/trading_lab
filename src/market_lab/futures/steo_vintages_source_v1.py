"""Bounded EIA monthly vintage archive; structure only, no economic values."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import requests

PROJECT = Path(__file__).resolve().parents[3]
CONFIG = PROJECT / "configs/v86_steo_source_v1.json"
SEAL = PROJECT / "configs/v86_steo_source_v1.seal.json"
BASE = "https://www.eia.gov/outlooks/steo/archives/"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, obj):
    with path.open("x", encoding="utf-8-sig") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def plan():
    return ["201712"] + [f"{y}{m:02d}" for y in range(2018, 2026) for m in range(1, 13)]


class IndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.current = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = {"text": [], "links": []}
        elif tag == "a" and self.current is not None:
            self.current["links"].append(dict(attrs).get("href", ""))

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def archive_index(raw):
    parser = IndexParser()
    parser.feed(raw.decode("utf-8-sig"))
    records = {}
    for row in parser.rows:
        text = " ".join(" ".join(row["text"]).split())
        match = re.search(r"\b(" + "|".join(MONTHS) + r") (20\d{2})\b", text)
        if not match:
            continue
        month = MONTHS.index(match[1]) + 1
        edition = f"{match[2]}{month:02d}"
        if edition not in plan():
            continue  # Never follow a 2026/current report link.
        date = re.search(r"\b(\d{1,2}/\d{1,2}/20\d{2})\b", text)
        require(date is not None, "missing release date")
        day = datetime.strptime(date[1], "%m/%d/%Y").date().isoformat()
        require(day[:7].replace("-", "") == edition, "edition/release mismatch")
        filename = MONTHS[month - 1][:3].lower() + edition[2:4] + "_base.xlsx"
        names = [urlparse(h).path.rsplit("/", 1)[-1] for h in row["links"]]
        require(filename in names and edition not in records, "missing/duplicate workbook")
        notices = [n for n in names if re.fullmatch(r"notice_data_\d{2}_\d{2}_\d{4}\.php", n)]
        require(len(notices) <= 1, "ambiguous notices")
        records[edition] = {"edition": edition, "release_date": day,
                            "filename": filename, "url": BASE + filename,
                            "notice_url": BASE + notices[0] if notices else None}
    require(sorted(records) == plan(), "incomplete 97-edition archive index")
    return [records[p] for p in plan()]


def workbook(raw, edition):
    """Only Table3a XML is parsed. Other sheets/prices are never materialized."""
    require(len(raw) <= 3_000_000 and raw.startswith(b"PK\x03\x04"), "not bounded XLSX")
    with ZipFile(io.BytesIO(raw)) as archive:
        require(sum(p.file_size for p in archive.infolist()) <= 40_000_000, "ZIP expansion")
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(
            archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = wb.findall("s:sheets/s:sheet", NS)
        selected = [s for s in sheets if s.get("name") == "3atab"]
        require(len(selected) == 1, "missing Table3a")
        link = selected[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rels[link]
        require(".." not in target and not target.startswith("http"), "external sheet")
        path = target.lstrip("/") if target.startswith("/xl/") else "xl/" + target
        strings = ["".join(a.itertext()) for a in ET.fromstring(
            archive.read("xl/sharedStrings.xml"))]
        sheet = ET.fromstring(archive.read(path))
        cells = {c.get("r"): c for c in sheet.findall("s:sheetData/s:row/s:c", NS)}

        def text(address):
            cell = cells.get(address)
            if cell is None:
                return None
            value = cell.find("s:v", NS)
            if value is None:
                return None
            return strings[int(value.text)] if cell.get("t") == "s" else value.text

        heading = text("B2")
        expected = MONTHS[int(edition[4:]) - 1] + " " + edition[:4]
        require(heading is not None and heading.endswith(expected), "wrong vintage heading")
        labels = {a: text(a) for a, c in cells.items()
                  if re.fullmatch(r"[AB]\d+", a) and c.get("t") in ("s", "str")}
        headers = {a: text(a) for a in cells if re.fullmatch(r"[A-Z]+[345]", a)
                   and text(a) is not None}
        rows = {code: [int(a[1:]) for a, v in labels.items()
                       if a.startswith("A") and v == code]
                for code in ("papr_world", "patc_world")}
        require(all(len(r) == 1 for r in rows.values()), "world series identity")
        core = ET.fromstring(archive.read("docProps/core.xml"))
        clocks = {e.tag.split("}")[-1]: e.text for e in core
                  if e.tag.split("}")[-1] in ("created", "modified")}
        metadata = {"edition_heading": heading, "sheet": "3atab", "sheet_path": path,
                    "headers": headers, "series_rows": rows,
                    "selected_labels": {a: v for a, v in labels.items()
                                        if "million barrels per day" in v or v in
                                        ("papr_world", "patc_world") or
                                        "Total World" in v},
                    "document_clocks_not_original_availability_proof": clocks,
                    "economic_values_read": False}
        return metadata, cells  # Caller must not evaluate other cells before economic seal.


def fetch(url):
    require(url.startswith(BASE) or url ==
            "https://www.eia.gov/outlooks/steo/outlook.php/archives/1Q95.pdf", "URL scope")
    last = None
    for attempt in range(1, 4):
        try:
            with requests.get(url, timeout=(15, 45), stream=True, allow_redirects=False) as r:
                r.raise_for_status()
                require(r.status_code == 200, "unexpected status/redirect")
                chunks, size = [], 0
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    require(size <= 3_000_000, "response size")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                return raw, {"url": url, "status": r.status_code, "attempt": attempt,
                             "bytes": len(raw), "sha256": sha(raw),
                             "received_at_utc": datetime.now(UTC).isoformat()}
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = type(exc).__name__
    raise RuntimeError("transport exhausted: " + str(last))


def verify(expected):
    require(sha(SEAL.read_bytes()) == expected, "source seal drift")
    sealed = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in sealed["files"].items():
        require(sha((PROJECT / name).read_bytes()) == digest, "source file drift: " + name)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    require(cfg["editions"] == plan() and not cfg["economic_admission"], "scope drift")
    return cfg


def collect(root, expected):
    cfg = verify(expected)
    require(os.name == "posix" and os.getuid() == 999, "server research user only")
    require(str(root) == "/srv/trading_lab_data/source_evidence/v86_steo_vintages_v1",
            "fixed external source root")
    require(not root.exists() and not root.is_symlink(), "preserve existing source")
    require(root.parent.resolve() == Path("/srv/trading_lab_data/source_evidence"), "parent")
    root.mkdir(exist_ok=False)
    raw, index_meta = fetch(cfg["archive_index_url"])
    (root / "index.html").write_bytes(raw)
    items = archive_index(raw)
    write(root / "request_plan.json", {"index": index_meta, "editions": items})

    def one(item):
        folder = root / item["edition"]
        folder.mkdir(exist_ok=False)
        raw, transport = fetch(item["url"])
        (folder / "source.xlsx").write_bytes(raw)
        metadata, _ = workbook(raw, item["edition"])
        notice = None
        if item["notice_url"]:
            data, notice = fetch(item["notice_url"])
            (folder / "notice.html").write_bytes(data)
        result = {**item, "raw": transport, "metadata": metadata, "notice": notice,
                  "economic_admission": False}
        write(folder / "manifest.json", result)
        print(json.dumps({"committed": item["edition"], "bytes": transport["bytes"]}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        results = list(pool.map(one, items))
    write(root / "manifest.json", {
        "protocol_id": cfg["protocol_id"], "seal_sha256": expected,
        "status": "SOURCE_STRUCTURE_COMPLETE", "index": index_meta,
        "editions": results, "raw_bytes": sum(r["raw"]["bytes"] for r in results),
        "economic_values_read": False, "economic_admission": False,
        "original_version_publication_time_verified": False,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    })
    print(json.dumps({"complete": len(results), "manifest_sha256": sha(
        (root / "manifest.json").read_bytes())}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(args.output, args.seal_sha)
