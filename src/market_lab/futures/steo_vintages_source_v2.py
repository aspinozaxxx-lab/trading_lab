"""V1 acquisition with an explicitly pre-created service-owned empty leaf."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures import steo_vintages_source_v1 as parent

CONFIG = parent.PROJECT / "configs/v86_steo_source_v2.json"
SEAL = parent.PROJECT / "configs/v86_steo_source_v2.seal.json"


def verify(expected):
    parent.require(parent.sha(SEAL.read_bytes()) == expected, "V2 seal drift")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for path, digest in seal["files"].items():
        parent.require(parent.sha((parent.PROJECT / path).read_bytes()) == digest, "V2 drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    return cfg, parent.verify(cfg["parent_source_seal_sha256"])


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
                   "fixed V2 source root")
    empty_leaf(root)
    parent.write(root / "started.json", {"seal_sha256": expected,
                                         "started_at_utc": datetime.now(UTC).isoformat()})
    raw, index_meta = parent.fetch(acquisition["archive_index_url"])
    (root / "index.html").write_bytes(raw)
    items = parent.archive_index(raw)
    parent.write(root / "request_plan.json", {"index": index_meta, "editions": items})

    def one(item):
        folder = root / item["edition"]
        folder.mkdir(exist_ok=False)
        raw, transport = parent.fetch(item["url"])
        (folder / "source.xlsx").write_bytes(raw)
        metadata, _ = parent.workbook(raw, item["edition"])
        notice = None
        if item["notice_url"]:
            data, notice = parent.fetch(item["notice_url"])
            (folder / "notice.html").write_bytes(data)
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
