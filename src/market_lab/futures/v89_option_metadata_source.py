"""NULL-bitmap census, then exact descriptions for all reported-OI option identities."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

from market_lab.futures import v88_option_metadata_probe as parent

base = parent.base
CONFIG = base.PROJECT / "configs/v89_option_metadata_source_v1.json"
SEAL = base.PROJECT / "configs/v89_option_metadata_source_v1.seal.json"


def verify(expected):
    base.require(base.sha(SEAL) == expected, "V89 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V89 dependency drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent.verify(cfg["reuse"]["parent_seal_sha256"])
    base.require(
        not cfg["economic_admission"]
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "source-only scope",
    )
    return cfg


def presence_only(column):
    """Never convert or compare numerical OI values; only the validity bitmap escapes."""
    return pc.is_valid(column).to_numpy(zero_copy_only=False)


def inventory(metadata, present):
    d = metadata.copy()
    base.require(len(d) == len(present) and present.dtype.kind == "b", "bitmap alignment")
    d["tradedate"] = pd.to_datetime(d.tradedate)
    base.require(
        d.tradedate.between("2021-01-01", "2025-12-31").all()
        and d.logical_asset.isin(["SI", "RI", "BR", "MIX"]).all()
        and not d.duplicated(["tradedate", "boardid", "secid"]).any(),
        "source scope",
    )
    d["oi_nonnull"] = present
    d["reported_date"] = d.tradedate.where(d.oi_nonnull)
    plan = (
        d.groupby(["logical_asset", "secid"], sort=True)
        .agg(
            source_rows=("tradedate", "size"),
            first_seen=("tradedate", "min"),
            last_seen=("tradedate", "max"),
            nonnull_rows=("oi_nonnull", "sum"),
            first_reported=("reported_date", "min"),
            last_reported=("reported_date", "max"),
        )
        .reset_index()
    )
    base.require(not plan.secid.duplicated().any(), "one SECID mapped to multiple assets")
    plan["needs_description"] = plan.nonnull_rows.gt(0)
    plan = plan.sort_values(["logical_asset", "first_seen", "secid"], ignore_index=True)
    counts = (
        d.groupby(["logical_asset", d.tradedate.dt.year.rename("year")])
        .agg(
            source_rows=("tradedate", "size"),
            nonnull_rows=("oi_nonnull", "sum"),
            securities=("secid", "nunique"),
        )
        .reset_index()
    )
    q = {
        "source_rows": len(d),
        "nonnull_rows": int(d.oi_nonnull.sum()),
        "null_rows": int((~d.oi_nonnull).sum()),
        "source_securities": len(plan),
        "needed_descriptions": int(plan.needs_description.sum()),
        "all_null_securities_retained": int((~plan.needs_description).sum()),
        "nonnull_does_not_prove_valid_oi": True,
        "oi_magnitudes_read": False,
        "market_prices_or_pnl_read": False,
    }
    return plan, counts, q


def census(cfg, expected):
    spec = cfg["source"]
    src = base.safe(Path("/srv/trading_lab_data"), spec["root"])
    for name, key in (
        ("manifest.json", "manifest_sha256"),
        ("audit.json", "audit_sha256"),
        ("options_weekly_core4.parquet", "parquet_sha256"),
    ):
        base.require(base.sha(src / name) == spec[key], "source identity")
    path = src / "options_weekly_core4.parquet"
    metadata = pd.read_parquet(path, columns=spec["metadata_columns"])
    days = pd.to_datetime(metadata.tradedate)
    base.require(
        len(metadata) == spec["rows"]
        and metadata.secid.nunique() == spec["unique_securities"]
        and days.notna().all()
        and str(days.min().date()) == spec["minimum_tradedate"]
        and str(days.max().date()) == spec["maximum_tradedate"]
        and days.lt(base.BOUNDARY).all(),
        "dates before bitmap access",
    )
    column = pq.read_table(path, columns=[spec["presence_column"]]).column(spec["presence_column"])
    present = presence_only(column)
    del column
    plan, counts, q = inventory(metadata, present)
    root = prepared(cfg["census_root"])
    plan.to_parquet(root / "contracts.parquet", index=False)
    counts.to_parquet(root / "presence_by_asset_year.parquet", index=False)
    base.write_json(
        root / "manifest.json",
        {
            "protocol_id": cfg["protocol_id"],
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "source": spec,
            "quality": q,
            "artifacts": {p.name: base.sha(p) for p in sorted(root.iterdir()) if p.is_file()},
            "economic_admission": False,
        },
    )
    print(
        json.dumps(
            {"root": str(root), "manifest_sha256": base.sha(root / "manifest.json"), "quality": q}
        ),
        flush=True,
    )


def prepared(text):
    root = Path(text)
    base.require(
        root.parent == Path("/srv/trading_lab_data/source_evidence")
        and root.resolve() == root
        and root.is_dir()
        and not any(root.iterdir()),
        "prepared empty source leaf required; never overwrite canonical",
    )
    return root


def parse_description(raw, item, cfg):
    parsed = parent.parse(raw, item)
    if parsed["status"] != "EXACT_DESCRIPTION":
        return parsed
    block = json.loads(raw)["description"]
    fields = {
        row[block["columns"].index("name")]: row[block["columns"].index("value")]
        for row in block["data"]
    }
    parsed["static_fields"].update(
        {k: fields[k] for k in cfg["additional_static_fields"] if k in fields}
    )
    dates = {}
    for key in ("FRSTTRADE", "LSTTRADE", "LSTDELDATE"):
        try:
            value = pd.Timestamp(fields.get(key))
            dates[key] = str(value.date()) if pd.notna(value) else None
        except (ValueError, TypeError):
            dates[key] = None
    parsed["static_date_fields"] = dates
    parsed["exact_underlying_execution_mapping_admitted"] = False
    return parsed


def reused(cfg):
    spec = cfg["reuse"]
    root = Path(spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "V88 identity")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    result = {}
    for item in manifest["results"]:
        if item["kind"] != "description":
            continue
        path = base.safe(root, item["raw"]["path"])
        raw = path.read_bytes()
        base.require(parent.sha(raw) == item["raw"]["sha256"], "reused raw drift")
        result[item["identity"]["secid"]] = (
            raw,
            {
                "path": str(path),
                "sha256": parent.sha(raw),
                "bytes": len(raw),
                "attempts": item["attempts"],
                "source_manifest_sha256": spec["manifest_sha256"],
            },
        )
    base.require(len(result) == 8, "V88 description count")
    return result


def collect(cfg, expected, census_sha):
    census_root = Path(cfg["census_root"])
    base.require(base.sha(census_root / "manifest.json") == census_sha, "census identity")
    manifest = json.loads((census_root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(manifest["seal_sha256"] == expected, "census protocol")
    for name, digest in manifest["artifacts"].items():
        base.require(base.sha(base.safe(census_root, name)) == digest, "census artifact")
    all_plan = pd.read_parquet(census_root / "contracts.parquet")
    plan = all_plan.loc[all_plan.needs_description].reset_index(drop=True)
    base.require(
        len(plan) == manifest["quality"]["needed_descriptions"]
        and 0 < len(plan) <= cfg["transport"]["maximum_logical_requests"],
        "plan size",
    )
    cache = reused(cfg)
    root = prepared(cfg["output_root"])
    status = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "census_manifest_sha256": census_sha,
        "planned": len(plan),
        "processed": 0,
        "reused": 0,
        "requested": 0,
        "exact_descriptions": 0,
        "unavailable": 0,
        "raw_bytes": 0,
        "status": "RUNNING",
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    base.write_json(root / "identity.json", dict(status))
    index, failures = [], 0
    with requests.Session() as session:
        for i, row in plan.iterrows():
            base.require(
                shutil.disk_usage(root).free >= cfg["transport"]["minimum_free_bytes"],
                "source disk reserve",
            )
            item = {
                "kind": "description",
                "identity": {"secid": row.secid, "asset": row.logical_asset},
                "url": cfg["description_url"].format(secid=quote(row.secid, safe="")),
            }
            record = {**item, "reference_reused": row.secid in cache}
            if row.secid in cache:
                raw, ref = cache[row.secid]
                record.update(raw=ref, attempts=ref["attempts"])
                status["reused"] += 1
            else:
                # Fixed public ISS URL only; this service has no credential EnvironmentFile.
                base.require(
                    item["url"].startswith("https://iss.moex.com/iss/securities/"),
                    "public static route only",
                )
                raw, attempts = parent.fetch(session, item, cfg)
                status["requested"] += 1
                record["attempts"] = attempts
                if raw is not None:
                    base.require(
                        status["raw_bytes"] + len(raw)
                        <= cfg["transport"]["maximum_total_raw_bytes"],
                        "archive size cap",
                    )
                    path = root / f"response_{i:06d}.raw"
                    with path.open("xb") as file:
                        file.write(raw)
                    record["raw"] = {
                        "path": str(path),
                        "sha256": parent.sha(raw),
                        "bytes": len(raw),
                    }
                    status["raw_bytes"] += len(raw)
                time.sleep(cfg["transport"]["minimum_between_requests_seconds"])
            successful_http = bool(
                record["attempts"] and record["attempts"][-1].get("http_status") == 200
            )
            record["parsed"] = (
                parse_description(raw, item, cfg)
                if raw is not None and successful_http
                else {"status": "SOURCE_UNAVAILABLE", "metadata_available": False}
            )
            good = record["parsed"]["metadata_available"]
            status["processed"] += 1
            status["exact_descriptions"] += int(good)
            status["unavailable"] += int(not good)
            failures = 0 if good else failures + 1
            target = root / f"record_{i:06d}.json"
            base.write_json(target, record)
            index.append(
                {
                    "secid": row.secid,
                    "logical_asset": row.logical_asset,
                    "record": target.name,
                    "sha256": base.sha(target),
                    "metadata_available": good,
                }
            )
            status["updated_at_utc"] = datetime.now(UTC).isoformat()
            temporary = root / "status.next.json"
            base.write_json(temporary, status)
            temporary.replace(root / "status.json")
            if status["processed"] % 100 == 0:
                print(json.dumps(status), flush=True)
            base.require(
                failures < cfg["transport"]["maximum_consecutive_unavailable"],
                "consecutive metadata failures; preserve root, do not restart",
            )
    verify(expected)
    base.require(status["processed"] == status["planned"], "incomplete plan")
    status["status"] = "COMPLETE_WITH_SOURCE_GAPS" if status["unavailable"] else "SOURCE_COMPLETE"
    base.write_json(root / "status.next.json", status)
    (root / "status.next.json").replace(root / "status.json")
    base.write_json(
        root / "manifest.json",
        {
            **status,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "records": index,
            "economic_admission": False,
            "goal_verified": False,
            "exact_underlying_execution_mapping_admitted": False,
        },
    )
    print(
        json.dumps(
            {
                "root": str(root),
                "manifest_sha256": base.sha(root / "manifest.json"),
                "status": status["status"],
            }
        ),
        flush=True,
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--census-only", action="store_true")
    cli.add_argument("--census-sha")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    base.require(args.census_only != bool(args.census_sha), "choose census or sealed acquisition")
    cfg = verify(args.seal_sha)
    if args.census_only:
        census(cfg, args.seal_sha)
    else:
        collect(cfg, args.seal_sha, args.census_sha)


if __name__ == "__main__":
    main()
