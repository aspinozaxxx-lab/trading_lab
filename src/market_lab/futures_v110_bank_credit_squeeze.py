"""Fixed SLOOS credit squeeze -> BR short/cash; conditional current-vintage screen."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

import pandas as pd

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v110_bank_credit_squeeze_v1.json"
SEAL = base.PROJECT / "configs/v110_bank_credit_squeeze_v1.seal.json"
SERIES = ("DRTSCILM", "DRSDCILM")
XML_SERIES = {"DRTSCILM": "SUBLPDCILS_N.Q", "DRSDCILM": "SUBLPDCILD_N.Q"}
XML_ATTRIBUTES = {
    "BANKSIZE": "ALL",
    "CURRENCY": "NA",
    "FREQ": "162",
    "LOANTYPE": "CILG",
    "PANEL": "DOM",
    "TERMS": "NA",
    "UNIT": "Percentage",
    "UNIT_MULT": "1",
}
SOURCE_URL = "https://www.federalreserve.gov/releases/sloos/data/FRB_SLOOS_xml.zip"
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def source_url(series, cfg):
    return SOURCE_URL + "#series=" + XML_SERIES[series]


def xml_records(raw, cfg, *, numeric=False):
    """Select exact published series and dates before any observation value inspection."""
    archive = zipfile.ZipFile(io.BytesIO(raw))
    base.require(sum(m.file_size for m in archive.infolist()) <= 50000000, "archive expansion")
    base.require(archive.namelist().count("SLOOS_data.xml") == 1, "data member identity")
    tree = ET.fromstring(archive.read("SLOOS_data.xml"))
    datasets = [e for e in tree if e.get("id") == "SLOOS"]
    base.require(len(datasets) == 1, "dataset identity")
    raws = {}
    for series, name in XML_SERIES.items():
        selected = [e for e in datasets[0] if e.get("SERIES_NAME") == name]
        base.require(len(selected) == 1, "missing/duplicate selected series")
        element = selected[0]
        expected = {
            **XML_ATTRIBUTES,
            "SERIES_NAME": name,
            "MEASURE": "STND" if series == "DRTSCILM" else "DEMAND",
        }
        base.require(element.attrib == expected, "series attributes drift")
        lines = ["observation_date," + series]
        for obs in element:
            if not obs.tag.endswith("}Obs"):
                continue
            text = obs.get("TIME_PERIOD")
            base.require(
                isinstance(text, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text),
                "XML date format",
            )
            if text < cfg["source"]["raw_start"] or text > cfg["source"]["raw_end"]:
                continue  # Neither status nor value of other/protected quarters is inspected.
            day = pd.Timestamp(text)
            base.require(day.is_quarter_end, "XML quarter-end label")
            base.require(
                set(obs.attrib) == {"TIME_PERIOD", "OBS_VALUE", "OBS_STATUS"}
                and obs.get("OBS_STATUS") == "A",
                "observation status/schema",
            )
            quarter_start = day.to_period("Q").start_time.strftime("%Y-%m-%d")
            value = obs.get("OBS_VALUE")
            base.require(
                value == "." or isinstance(value, str) and NUMBER.fullmatch(value),
                "invalid XML percent token",
            )
            lines.append(quarter_start + "," + value)
        raws[series] = "\n".join(lines).encode()
    result = records(raws, cfg, numeric=numeric)
    for row in result:
        row["xml_quarter_end_label"] = row["observation_date"] + pd.offsets.QuarterEnd(0)
    return result


def clock(day):
    """Proxy date, NOT the quarter label or a claim of an original release date."""
    proxy = day + pd.DateOffset(months=1) + pd.offsets.MonthEnd(0)
    available = (
        (proxy + pd.Timedelta(days=1)).tz_localize("America/New_York") - pd.Timedelta(seconds=1)
    ).tz_convert("UTC")
    return proxy, available


def records(raws, cfg, *, numeric=False):
    spec = cfg["source"]
    base.require(set(raws) == set(SERIES), "series identity")
    expected = list(pd.date_range(spec["raw_start"], spec["raw_end"], freq="QS"))
    base.require(len(expected) == spec["expected_reports"], "declared calendar")
    columns = {}
    for series in SERIES:
        reader = csv.DictReader(io.StringIO(raws[series].decode("utf-8-sig")))
        base.require(reader.fieldnames == ["observation_date", series], "CSV header identity")
        rows = list(reader)
        dates = []
        for row in rows:
            base.require(set(row) == {"observation_date", series}, "CSV row schema")
            text = row["observation_date"]
            base.require(
                isinstance(text, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text),
                "invalid observation date",
            )
            base.require(
                spec["raw_start"] <= text <= spec["raw_end"] and text < "2026-01-01",
                "outside/protected date",
            )
            dates.append(pd.Timestamp(text))
        base.require(dates == expected, "quarter calendar/duplicates/order")
        columns[series] = rows
    result = []
    for i, day in enumerate(expected):
        proxy, available = clock(day)
        base.require(available < pd.Timestamp(base.BOUNDARY, tz="UTC"), "protected clock")
        values = {series: columns[series][i][series] for series in SERIES}
        base.require(
            all(v == "." or isinstance(v, str) and NUMBER.fullmatch(v) for v in values.values()),
            "invalid percent token",
        )
        record = {
            "observation_date": day,
            "source_date": proxy,
            "available_at_utc": available,
            "cells_complete": all(v != "." for v in values.values()),
            "source_url": ";".join(source_url(s, cfg) for s in SERIES)
            + "#observation-date="
            + str(day.date()),
            "original_receipt_verified": False,
        }
        if numeric:
            record["values"] = values
        result.append(record)
    return result


def states(rows):
    result = []
    for row in rows:
        values = {s: None if v == "." else Decimal(v) for s, v in row["values"].items()}
        base.require(
            all(v is None or v.is_finite() and -100 <= v <= 100 for v in values.values()),
            "percent outside bounds",
        )
        ready = row["cells_complete"] and all(v is not None for v in values.values())
        short = ready and values["DRTSCILM"] > 0 and values["DRSDCILM"] < 0
        result.append(
            {
                **{k: v for k, v in row.items() if k != "values"},
                "asset_code": "BR",
                "ready": ready,
                "primary_direction": -float(short),
                "control_direction": -float(ready),
                "net_tightening": row["values"]["DRTSCILM"],
                "net_stronger_demand": row["values"]["DRSDCILM"],
            }
        )
    return pd.DataFrame(result)


def source(cfg, storage=STORAGE):
    spec = cfg["source"]
    root = base.safe(storage, spec["root"])
    base.require(
        base.sha(root / "manifest.json") == spec["manifest_sha256"], "source manifest drift"
    )
    manifest = prior.read_json(root / "manifest.json")
    base.require(manifest["status"] == "COMPLETE_SCHEMA_ONLY", "incomplete source")
    for name, sha in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == sha, "source artifact drift")
    path = root / "FRB_SLOOS_xml.zip"
    base.require(base.sha(path) == spec["raw_sha256"], "raw drift")
    metadata = prior.read_json(root / "FRB_SLOOS_xml.zip.metadata.json")
    base.require(
        metadata["url"] == SOURCE_URL and metadata["http_status"] == "200",
        "source query/status drift",
    )
    return path.read_bytes(), manifest


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V110 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V110 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["BR"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected):
    raw, evidence = source(cfg)
    metadata = xml_records(raw, cfg)
    verified = base.preflight(parent, STORAGE)
    out = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    out.mkdir(exist_ok=False)
    base.write_json(
        out / "inputs.json",
        {
            "seal_sha256": expected,
            "source_manifest": evidence,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    base.write_json(out / "source_metadata.json", metadata)
    state = states(xml_records(raw, cfg, numeric=True))
    state.to_parquet(out / "source_states.parquet", index=False)
    pd.testing.assert_frame_equal(state, pd.read_parquet(out / "source_states.parquet"))
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = targets(active, state, cfg)
    p = signals["primary"]
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "source_reports": len(state),
        "ready_reports": int(state.ready.sum()),
        "short_reports": int(state.primary_direction.lt(0).sum()),
        "original_receipt_verified": False,
    }
    base.write_json(out / "source_quality.json", quality)
    base.require(
        quality["ready_asset_date_fraction"]
        >= cfg["screen_gates"]["minimum_ready_asset_date_fraction"],
        "source coverage gate",
    )
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(out / "case", signals, market, quality, cfg, "bank_credit_squeeze")
    audit = prior.audit_case(out / "case", case, signals)
    base.write_json(
        out / "metrics.json",
        {
            "status": "COMPLETE",
            "protocol_id": cfg["protocol_id"],
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "case": case,
            "audit": audit,
            "limitations": cfg["limitations"],
            "goal_verified": False,
        },
    )
    base.write_json(
        out / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "files": {
                p.relative_to(out).as_posix(): base.sha(p)
                for p in sorted(out.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(json.dumps({"output": str(out), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service user only")
    cfg, parent = load(args.seal_sha)
    run(cfg, parent, args.seal_sha)


if __name__ == "__main__":
    main()
