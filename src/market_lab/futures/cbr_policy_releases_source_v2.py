"""Retain date-only footer clocks without backdating CBR policy availability."""

from __future__ import annotations

import argparse
import json
import re
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from market_lab.futures import cbr_policy_releases_source as parent

base = parent.base
CONFIG = base.PROJECT / "configs/cbr_policy_releases_2018_2025_v2.json"
SEAL = base.PROJECT / "configs/cbr_policy_releases_2018_2025_v2.seal.json"
ORIGINAL_PARSE = parent.parse_article


def parse_article(content, record, retrieved):
    html = content.decode("utf-8-sig")
    clocks = sorted(set(re.findall(r"\d\d\.\d\d\.\d{4} \d\d:\d\d:\d\d", html)))
    date_only = len(clocks) == 1 and clocks[0].endswith(" 00:00:00")
    adapted = {**record, "clock": "00:00"} if date_only else record
    row = ORIGINAL_PARSE(content, adapted, retrieved)
    listed = (
        (
            record["publication_date"]
            + pd.Timedelta(hours=int(record["clock"][:2]), minutes=int(record["clock"][3:]))
        )
        .tz_localize("Europe/Moscow")
        .tz_convert("UTC")
    )
    row["footer_clock_text"] = clocks[0]
    row["footer_time_known"] = not date_only
    row["listing_published_at_utc"] = listed
    if date_only:
        row["published_at_utc"] = listed
    base.require(row["published_at_utc"] <= row["available_at_utc"], "late publication label")
    return row


@contextmanager
def parser_adapter():
    previous = parent.parse_article
    parent.parse_article = parse_article
    try:
        yield
    finally:
        parent.parse_article = previous


def load(expected):
    base.require(base.sha(SEAL) == expected, "V2 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V2 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    inherited = parent.load(cfg["parent_v1_seal_sha256"])
    return {
        **inherited,
        "protocol_id": cfg["protocol_id"],
        "output": cfg["output"],
        "article_identity": cfg["correction"],
    }


def audit(cfg, storage, expected, manifest_sha):
    root = base.safe(storage, cfg["output"])
    base.require(base.sha(root / "manifest.json") == manifest_sha, "manifest drift")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(
        manifest["seal_sha256"] == expected and manifest["protocol_id"] == cfg["protocol_id"],
        "source identity",
    )
    records, raw_articles = {}, []
    for item in manifest["raw"]:
        path = base.safe(root, item["path"])
        base.require(
            path.stat().st_size == item["bytes"] and base.sha(path) == item["sha256"], "raw drift"
        )
        if path.name.startswith("list_"):
            for record in parent.parse_listing(path.read_bytes())[0]:
                if record["url"] in records:
                    base.require(record == records[record["url"]], "listing drift")
                records[record["url"]] = record
        else:
            raw_articles.append(item)
    reconstructed = []
    for item in raw_articles:
        row = parse_article(
            base.safe(root, item["path"]).read_bytes(),
            records[item["url"]],
            item["retrieved_at_utc"],
        )
        row["raw_sha256"] = item["sha256"]
        reconstructed.append(row)
    expected_frame = pd.DataFrame(reconstructed).sort_values(
        ["published_at_utc", "source_url"], ignore_index=True
    )
    spec = manifest["processed"]
    path = base.safe(root, spec["path"])
    base.require(
        path.stat().st_size == spec["bytes"] and base.sha(path) == spec["sha256"], "processed drift"
    )
    actual = pd.read_parquet(path)
    base.require(len(actual) == spec["rows"] == len(expected_frame), "row drift")
    base.require(
        actual.to_json(orient="records", date_format="iso")
        == expected_frame.to_json(orient="records", date_format="iso"),
        "source replay drift",
    )
    return {
        "raw_hashes": len(manifest["raw"]),
        "replayed_releases": len(actual),
        "date_only_footers": int((~actual.footer_time_known).sum()),
        "same_day_conservative_eod": True,
        "all_true": True,
        "economic_admission": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--manifest-sha")
    args = parser.parse_args()
    cfg = load(args.seal_sha)
    if args.manifest_sha:
        print(json.dumps(audit(cfg, args.storage_root, args.seal_sha, args.manifest_sha)))
    else:
        with parser_adapter():
            parent.collect(cfg, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
