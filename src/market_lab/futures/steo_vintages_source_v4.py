"""V4: retain duplicate world-series identities and reuse preserved V3 source files."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from market_lab.futures import steo_vintages_source_v1 as parent

CONFIG = parent.PROJECT / "configs/v86_steo_source_v4.json"
SEAL = parent.PROJECT / "configs/v86_steo_source_v4.seal.json"


def verify(expected):
    parent.require(parent.sha(SEAL.read_bytes()) == expected, "V4 seal drift")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for path, digest in seal["files"].items():
        parent.require(parent.sha((parent.PROJECT / path).read_bytes()) == digest, "V4 drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    return cfg, parent.verify(cfg["parent_source_seal_sha256"])


def archive_index(raw):
    # Observed source lacks <tr> before July/April/March2019, retaining </tr>.
    # Repair row-open syntax only; dates, links and preserved raw bytes are unchanged.
    text = raw.decode("utf-8-sig")
    pattern = r"(</tr>\s*)(?=<td>\s*(?:" + "|".join(parent.MONTHS) + r") 20\d{2}\s*</td>)"
    repaired = re.sub(pattern, r"\1<tr>", text)
    return parent.archive_index(repaired.encode("utf-8"))


NS, MONTHS, require = parent.NS, parent.MONTHS, parent.require


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
        require(len(rows["papr_world"]) in (1, 2) and len(rows["patc_world"]) == 1,
                "world series identity")
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


def empty_leaf(root):
    parent.require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
                   "unprepared/symlink leaf")
    parent.require(root.stat().st_uid == os.getuid() and not any(root.iterdir()),
                   "leaf not empty or not service-owned")


def collect(root, expected):
    cfg, acquisition = verify(expected)
    parent.require(os.name == "posix" and os.getuid() == 999, "server service only")
    parent.require(str(root) == cfg["raw_output"] and
                   root.parent.resolve() == Path("/srv/trading_lab_data/source_evidence"),
                   "fixed V4 source root")
    empty_leaf(root)
    parent.write(root / "started.json", {"seal_sha256": expected,
                                         "started_at_utc": datetime.now(UTC).isoformat()})
    cached = Path(cfg["cached_index"]["path"])
    raw = cached.read_bytes()
    parent.require(parent.sha(raw) == cfg["cached_index"]["sha256"], "index cache drift")
    index_meta = cfg["cached_index"]
    (root / "index.html").write_bytes(raw)
    items = archive_index(raw)
    parent.write(root / "request_plan.json", {"index": index_meta, "editions": items})

    def one(item):
        folder = root / item["edition"]
        folder.mkdir(exist_ok=False)
        old = Path(cfg["reuse_root"]) / item["edition"]
        saved = old / "source.xlsx"
        previous = None
        if (old / "manifest.json").is_file():
            previous = json.loads((old / "manifest.json").read_text(encoding="utf-8-sig"))
            parent.require(all(previous[k] == item[k] for k in item), "reuse edition drift")
        if saved.is_file():
            parent.require(saved.resolve() == saved and not saved.is_symlink(), "reuse symlink")
            raw = saved.read_bytes()
            if previous is not None:
                transport = previous["raw"]
                parent.require(parent.sha(raw) == transport["sha256"] and
                               len(raw) == transport["bytes"], "reuse hash drift")
            else:
                transport = {"url": item["url"], "sha256": parent.sha(raw),
                             "bytes": len(raw), "received_at_utc": None,
                             "first_recovery_observation_utc": datetime.now(UTC).isoformat(),
                             "original_transport_manifest_missing": True}
            transport = {**transport, "path": str(saved), "reference_reused": True}
        else:
            raw, transport = parent.fetch(item["url"])
            saved = folder / "source.xlsx"
            saved.write_bytes(raw)
            transport = {**transport, "path": str(saved), "reference_reused": False}
        metadata, _ = workbook(raw, item["edition"])
        notice = None
        if item["notice_url"]:
            saved_notice = old / "notice.html"
            if previous is not None and saved_notice.is_file():
                data, notice = saved_notice.read_bytes(), previous["notice"]
                parent.require(parent.sha(data) == notice["sha256"], "notice reuse drift")
            else:
                data, notice = parent.fetch(item["notice_url"])
                saved_notice = folder / "notice.html"
                saved_notice.write_bytes(data)
            notice = {**notice, "path": str(saved_notice)}
        result = {**item, "raw": transport, "metadata": metadata, "notice": notice,
                  "economic_admission": False}
        parent.write(folder / "manifest.json", result)
        print(json.dumps({"committed": item["edition"], "bytes": transport["bytes"]}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=acquisition["workers"]) as pool:
        results = list(pool.map(one, items))
    parent.write(root / "manifest.json", {
        "protocol_id": cfg["protocol_id"], "seal_sha256": expected,
        "status": "SOURCE_STRUCTURE_COMPLETE", "index": index_meta,
        "editions": results, "raw_bytes": sum(r["raw"]["bytes"] for r in results),
        "economic_values_read": False, "economic_admission": False,
        "original_version_publication_time_verified": False,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    })
    print(json.dumps({"complete": len(results), "manifest_sha256": parent.sha(
        (root / "manifest.json").read_bytes())}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(args.output, args.seal_sha)
