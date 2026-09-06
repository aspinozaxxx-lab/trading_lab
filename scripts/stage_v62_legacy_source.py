"""Copy only byte-declared V62 legacy inputs into a new external source root."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from market_lab.futures_v62_opening_regime_v2 import load_protocol, safe_path, sha, write_json


def stage(source_root: Path, destination: Path) -> dict:
    source_root, destination = source_root.resolve(), destination.resolve()
    allowed = Path("/srv/trading_lab_data/data").resolve()
    if not destination.is_relative_to(allowed) or destination == allowed or destination.exists():
        raise ValueError("staging requires a new specific directory inside external data")
    parent, _ = load_protocol()
    source = parent["source"]
    records = {}

    def admit(relative: str, expected: str) -> dict | None:
        path = safe_path(source_root, relative)
        if sha(path) != expected:
            raise ValueError(f"source drift: {relative}")
        records[relative] = dict(sha256=expected, bytes=path.stat().st_size)
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.suffix == ".json" else None

    top = None
    for role in ("top_manifest", "active_map", "spec_proxy"):
        value = admit(source[f"{role}_relative_path"], source[f"{role}_sha256"])
        if role == "top_manifest":
            top = value
    if top["requested_end"] != "2025-12-31":
        raise ValueError("temporal boundary drift")
    for item in top["assets"]:
        manifest = admit("data/" + item["path"], item["sha256"])
        for segment in manifest["segment_manifests"]:
            declaration = admit("data/" + segment["path"], segment["sha256"])
            if segment["rows"]:
                parquet = declaration["artifacts"]["parquet"]
                admit("data/" + parquet["path"], parquet["sha256"])
    destination.mkdir(parents=False, exist_ok=False)
    for relative, record in records.items():
        target = safe_path(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(safe_path(source_root, relative), target)
        if sha(target) != record["sha256"]:
            raise ValueError("staged file byte drift")
    report = dict(
        source=str(source_root),
        destination=str(destination),
        files=len(records),
        bytes=sum(r["bytes"] for r in records.values()),
        artifacts=records,
        prices_returns_labels_and_pnl_parsed=False,
        exact_byte_copy=True,
    )
    write_json(destination / "staging_manifest.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "artifacts"}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    stage(args.source_root, args.destination)
