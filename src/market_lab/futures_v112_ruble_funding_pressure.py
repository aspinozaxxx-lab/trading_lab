"""Joint domestic funding pressure, SI short/cash; unchanged futures ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

import pandas as pd

from market_lab import futures_v101_manufacturing_demand as prior
from market_lab.futures import cbr_liquidity_factors_source as html

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v112_ruble_funding_pressure_v1.json"
SEAL = base.PROJECT / "configs/v112_ruble_funding_pressure_v1.seal.json"
BOUNDARY = pd.Timestamp("2026-01-01", tz="Europe/Moscow").tz_convert("UTC")
DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)?")


def tables(raw):
    parser = html._DataTableParser()
    parser.feed(raw.decode("utf-8-sig"))
    base.require(len(parser.tables) == 1, "expected one data table")
    return parser.tables[0]


def number(token):
    token = "".join(token.split()).replace("\u2212", "-")
    if token in {"", "-", "–", "—"}:
        return None
    base.require(NUMBER.fullmatch(token) is not None, "malformed selected number")
    value = Decimal(token.replace(",", "."))
    base.require(value.is_finite(), "nonfinite selected number")
    return str(value)


def day_token(token):
    base.require(DATE.fullmatch(token) is not None, "malformed source date")
    return pd.Timestamp(datetime.strptime(token, "%d.%m.%Y").date())


def midnight(day):
    return day.tz_localize("Europe/Moscow").tz_convert("UTC")


def liquidity(raw, cfg, numeric=False):
    rows = tables(raw)
    base.require(
        any(
            len(r) >= 3 and "без учета корсчетов" in r[2] for r in rows if not DATE.fullmatch(r[0])
        ),
        "unadjusted deficit header missing",
    )
    result = {}
    for cells in rows:
        if not DATE.fullmatch(cells[0]):
            continue
        day = day_token(cells[0])
        base.require(len(cells) == 15, "liquidity row schema drift")
        base.require(
            cfg["period"]["start"] <= str(day.date()) <= cfg["period"]["end"],
            "liquidity source date escaped",
        )
        base.require(day not in result, "duplicate liquidity date")
        # Snapshot at start of observation day; extra following-calendar-day allowance.
        available = midnight(day + pd.Timedelta(days=2)) - pd.Timedelta(seconds=1)
        row = {"observation_date": day, "available_at_utc": available}
        if numeric and available < BOUNDARY:
            row["deficit"] = number(cells[2])
        result[day] = row
    base.require(len(result) == cfg["source"]["expected_raw_rows"], "liquidity calendar drift")
    return result


def rates(ruonia_raw, key_raw, cfg, numeric=False):
    ruonia, keys = {}, {}
    for cells in tables(ruonia_raw):
        if not DATE.fullmatch(cells[0]):
            continue
        base.require(len(cells) == 11, "RUONIA schema drift")
        day, published = day_token(cells[0]), day_token(cells[10])
        base.require(published > day, "RUONIA publication clock")
        available = midnight(published + pd.Timedelta(days=1))
        if available >= BOUNDARY:
            continue
        base.require(
            cfg["period"]["start"] <= str(day.date()) <= cfg["period"]["end"], "RUONIA date escaped"
        )
        base.require(day not in ruonia, "duplicate RUONIA date")
        row = {
            "observation_date": day,
            "publication_date": published,
            "available_at_utc": available,
        }
        if numeric:
            row["rate"] = number(cells[1])
            base.require(row["rate"] is None or Decimal(row["rate"]) > 0, "invalid RUONIA")
        ruonia[day] = row
    for element in ET.fromstring(key_raw).iter():
        if element.tag.rsplit("}", 1)[-1] != "KR":
            continue
        children = {e.tag.rsplit("}", 1)[-1]: e.text for e in element}
        base.require(set(children) == {"DT", "Rate"}, "key-rate schema drift")
        timestamp = pd.Timestamp(children["DT"])
        base.require(timestamp == timestamp.normalize(), "key-rate date clock")
        if timestamp.tz is not None:
            base.require(timestamp.utcoffset() == pd.Timedelta(hours=3), "key-rate time zone")
        day = timestamp.tz_localize(None)
        available = midnight(day + pd.Timedelta(days=1))
        if available >= BOUNDARY:
            continue
        base.require(
            cfg["period"]["start"] <= str(day.date()) <= cfg["period"]["end"],
            "key-rate date escaped",
        )
        base.require(day not in keys, "duplicate key-rate date")
        row = {"observation_date": day, "available_at_utc": available}
        if numeric:
            row["rate"] = number(children["Rate"] or "")
            base.require(row["rate"] is None or Decimal(row["rate"]) >= 0, "negative key rate")
        keys[day] = row
    base.require(len(ruonia) == cfg["monetary"]["ruonia_rows"], "RUONIA calendar drift")
    base.require(len(keys) == cfg["monetary"]["key_rate_rows"], "key-rate calendar drift")
    return ruonia, keys


def records(raw, monetary, cfg, numeric=False):
    stock = liquidity(raw, cfg, numeric)
    overnight, policy = rates(monetary["ruonia"], monetary["key_rate"], cfg, numeric)
    result = []
    for day, rate in sorted(overnight.items()):
        bank, key = stock.get(day), policy.get(day)
        proxy = midnight(day + pd.Timedelta(days=2)) - pd.Timedelta(seconds=1)
        available = max(rate["available_at_utc"], proxy, key["available_at_utc"] if key else proxy)
        if available >= BOUNDARY:
            continue
        row = {
            "source_date": day,
            "available_at_utc": available,
            "ruonia_publication_date": rate["publication_date"],
            "liquidity_proxy_available_at_utc": proxy,
            "ruonia_available_at_utc": rate["available_at_utc"],
            "key_rate_available_at_utc": key["available_at_utc"] if key else pd.NaT,
            "source_url": cfg["source"]["url"] + "#" + str(day.date()),
            "date_matched": bank is not None and key is not None,
        }
        if numeric:
            row.update(
                ruonia=rate["rate"],
                key_rate=key["rate"] if key else None,
                deficit=bank.get("deficit") if bank else None,
            )
        result.append(row)
    base.require(len(result) == cfg["monetary"]["ruonia_rows"], "joint calendar drift")
    available = pd.Series([r["available_at_utc"] for r in result])
    base.require(available.is_monotonic_increasing, "out-of-order publication clocks")
    return result


def states(rows):
    result = []
    for row in rows:
        ready = row["date_matched"] and all(
            row[k] is not None for k in ("ruonia", "key_rate", "deficit")
        )
        premium = Decimal(row["ruonia"]) - Decimal(row["key_rate"]) if ready else None
        pressure = ready and premium > 0
        direction = -float(pressure and Decimal(row["deficit"]) > 0)
        result.append(
            {
                **row,
                "asset_code": "SI",
                "ready": ready,
                "premium_percentage_points": str(premium) if ready else None,
                "primary_direction": direction,
                "control_direction": -float(pressure),
            }
        )
    return pd.DataFrame(result)


def source(cfg, storage=STORAGE):
    root = base.safe(storage, cfg["source"]["root"])
    base.require(
        base.sha(root / "manifest.json") == cfg["source"]["manifest_sha256"],
        "source manifest drift",
    )
    manifest = prior.read_json(root / "manifest.json")
    base.require(manifest["status"] == "COMPLETE_METADATA_ONLY", "source not complete")
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "source artifact drift")
    raw = root / "liquidity.html"
    base.require(base.sha(raw) == cfg["source"]["raw_sha256"], "liquidity raw drift")
    meta = prior.read_json(root / "liquidity.html.metadata.json")
    base.require(
        meta["url"] == cfg["source"]["url"]
        and meta["http_status"] == "200"
        and meta["curl_returncode"] == 0
        and meta["bytes"] == raw.stat().st_size,
        "liquidity HTTP identity drift",
    )
    monetary = {}
    for name, spec in cfg["monetary"]["files"].items():
        path = base.safe(storage, spec["path"])
        base.require(
            base.sha(path) == spec["sha256"] and path.stat().st_size == spec["bytes"],
            "monetary source drift",
        )
        if name in {"ruonia", "key_rate"}:
            monetary[name] = path.read_bytes()
    return raw.read_bytes(), monetary, manifest


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V112 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V112 file drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["SI"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected):
    raw, monetary, evidence = source(cfg)
    metadata = records(raw, monetary, cfg)
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
    state = states(records(raw, monetary, cfg, numeric=True))
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
        "control_short_reports": int(state.control_direction.lt(0).sum()),
        "original_receipt_verified": False,
    }
    base.write_json(out / "source_quality.json", quality)
    base.require(
        quality["ready_asset_date_fraction"]
        >= cfg["screen_gates"]["minimum_ready_asset_date_fraction"],
        "source coverage gate",
    )
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(
        out / "case", signals, market, quality, cfg, "ruble_funding_pressure"
    )
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
