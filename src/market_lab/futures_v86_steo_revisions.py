"""Fixed next-quarter oil-balance forecast revision screen; existing daily ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

from market_lab import futures_v78_treasury_channels as engine
from market_lab.futures import steo_vintages_source_v4 as source

base, adapter = engine.base, engine.adapter
CONFIG = base.PROJECT / "configs/v86_steo_revisions_v1.json"
SEAL = base.PROJECT / "configs/v86_steo_revisions_v1.seal.json"


def column_number(col):
    result = 0
    for letter in col:
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def monthly_columns(metadata):
    h = metadata["headers"]
    years = sorted((column_number(a[:-1]), int(v)) for a, v in h.items()
                   if a.endswith("3") and re.fullmatch(r"20\d{2}", v))
    months = {m[:3]: i + 1 for i, m in enumerate(source.MONTHS)}
    columns = {}
    for address, value in h.items():
        if not address.endswith("4") or value not in months:
            continue
        col = address[:-1]
        prior = [(c, y) for c, y in years if c <= column_number(col)]
        base.require(bool(prior), "month lacks year heading")
        year_col, year = prior[-1]
        month = months[value]
        base.require(column_number(col) - year_col == month - 1, "nonmonthly header spacing")
        key = f"{year}-{month:02d}"
        base.require(key not in columns, "duplicate monthly columns")
        columns[key] = col
    base.require(bool(columns), "no monthly columns")
    return columns


def next_quarter(edition):
    month = pd.Period(edition[:4] + "-" + edition[4:], freq="M")
    quarter = month.asfreq("Q") + 1
    return [str(quarter.asfreq("M", "start") + i) for i in range(3)]


class NoticeText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def availability(item, notice_raw):
    release = pd.Timestamp(item["release_date"])
    modified = item["metadata"]["document_clocks_not_original_availability_proof"].get("modified")
    if not modified:
        return None, "missing_workbook_clock"
    clock = pd.Timestamp(modified)
    if clock.tzinfo is None:
        return None, "untimed_workbook_clock"
    dates = [release, clock.tz_convert("UTC").tz_localize(None).normalize()]
    if item["notice_url"]:
        if notice_raw is None:
            return None, "missing_notice"
        parser = NoticeText()
        parser.feed(notice_raw.decode("utf-8-sig"))
        text = " ".join(" ".join(parser.parts).split())
        dates_text = re.findall(r"\bReleased:\s*(" + "|".join(source.MONTHS) +
                                r")\s+(\d{1,2}),\s*(20\d{2})\b", text)
        if len(dates_text) != 1:
            return None, "ambiguous_notice_date"
        m, day, year = dates_text[0]
        notice_date = pd.Timestamp(int(year), source.MONTHS.index(m) + 1, int(day))
        if notice_date < release:
            return None, "notice_before_edition"
        dates.append(notice_date)
    day = max(dates)
    if day >= base.BOUNDARY:
        return None, "current_bytes_not_available_pre2026"
    return ((day + pd.Timedelta(days=1)).tz_localize("America/New_York")
            - pd.Timedelta(nanoseconds=1)).tz_convert("UTC"), "ready"


def physical_value(cells, col, rows):
    values = []
    for row in rows:
        cell = cells.get(f"{col}{row}")
        if cell is None or cell.get("t") not in (None, "n"):
            return None, "missing_or_nonnumeric_cached_forecast"
        text = cell.findtext("s:v", namespaces=source.NS)
        try:
            value = Decimal(text) if text is not None else None
        except InvalidOperation:
            value = None
        if value is None or not value.is_finite() or not Decimal(0) < value < Decimal(200):
            return None, "invalid_world_volume"
        values.append(value)
    if not values or any(v != values[0] for v in values):
        return None, "duplicated_world_series_disagree"
    return values[0], "ready"


def deficit(metadata, cells, quarter):
    columns = monthly_columns(metadata)
    if not all(m in columns for m in quarter):
        return None, "quarter_not_covered"
    quantities = []
    for month in quarter:
        result = {}
        for name in ("papr_world", "patc_world"):
            value, reason = physical_value(cells, columns[month], metadata["series_rows"][name])
            if reason != "ready":
                return None, reason
            result[name] = value
        quantities.append(result["patc_world"] - result["papr_world"])
    return sum(quantities, Decimal(0)) / Decimal(3), "ready"


def verified_path(text):
    path = Path(text)
    roots = [Path("/srv/trading_lab_data/source_evidence/v86_steo_vintages_v" + v)
             for v in ("3", "4")]
    base.require(any(path.is_relative_to(r) for r in roots) and path.resolve() == path
                 and not path.is_symlink(), "source reference escaped roots")
    return path


def read_sources(cfg):
    spec = cfg["source"]
    root = Path(spec["root"])
    base.require(base.sha(root / "manifest.json") == spec["manifest_sha256"], "source manifest")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(manifest["status"] == "SOURCE_STRUCTURE_COMPLETE" and
                 manifest["seal_sha256"] == spec["seal_sha256"] and
                 not manifest["economic_admission"] and not manifest["economic_values_read"],
                 "source admission drift")
    base.require([i["edition"] for i in manifest["editions"]] == source.parent.plan(), "editions")
    records, loaded = [], {}
    for item in manifest["editions"]:
        edition = item["edition"]
        base.require(item == json.loads((root / edition / "manifest.json").read_text(
            encoding="utf-8-sig")), "edition manifest drift")
        base.require(pd.Timestamp(item["release_date"]) < base.BOUNDARY, "protected release")
        raw = verified_path(item["raw"]["path"]).read_bytes()
        base.require(source.parent.sha(raw) == item["raw"]["sha256"] and
                     len(raw) == item["raw"]["bytes"], "raw bytes drift")
        metadata, cells = source.workbook(raw, edition)  # identity/dates before values
        base.require(metadata == item["metadata"], "metadata replay")
        units = metadata["selected_labels"].values()
        base.require(any("million barrels per day" in u and
                         ("Production" in u or "Supply" in u) for u in units)
                     and any("Consumption (million barrels per day)" in u for u in units),
                     "physical unit drift")
        notice = None
        if item["notice"]:
            notice = verified_path(item["notice"]["path"]).read_bytes()
            base.require(source.parent.sha(notice) == item["notice"]["sha256"], "notice drift")
        clock, reason = availability(item, notice)
        loaded[edition] = (metadata, cells, clock, reason)
        if edition == "201712":
            continue
        previous = str(pd.Period(edition[:4] + "-" + edition[4:], freq="M") - 1).replace("-", "")
        old_meta, old_cells, old_clock, old_reason = loaded[previous]
        quarter = next_quarter(edition)
        now, before = None, None
        if reason == "ready" and old_reason == "ready":
            now, reason = deficit(metadata, cells, quarter)
            before, old_reason = deficit(old_meta, old_cells, quarter)
        ready = reason == old_reason == "ready"
        if clock is not None and old_clock is not None:
            effective_clock = max(clock, old_clock)
        else:
            effective_clock = ((pd.Timestamp(item["release_date"]) + pd.Timedelta(days=1))
                               .tz_localize("America/New_York")
                               - pd.Timedelta(nanoseconds=1)).tz_convert("UTC")
        change = now - before if ready else None
        records.append({
            "edition": edition, "previous_edition": previous, "source_date": item["release_date"],
            "available_at_utc": effective_clock, "ready": ready,
            "quarter_months": ",".join(quarter), "deficit_mbd": str(now) if ready else None,
            "previous_deficit_same_quarter_mbd": str(before) if ready else None,
            "revision_mbd": str(change) if ready else None,
            "primary_direction": (int(change > 0) - int(change < 0)) if ready else 0,
            "control_direction": int(ready), "reason": reason + "/" + old_reason,
            "source_url": item["url"], "raw_sha256": item["raw"]["sha256"], "asset_code": "BR",
        })
    frame = pd.DataFrame(records)
    frame["source_date"] = pd.to_datetime(frame.source_date)
    ordered = frame.sort_values(["available_at_utc", "source_date"])
    ordered["dominated_late_edition"] = ordered.source_date.lt(ordered.source_date.cummax())
    state = ordered.loc[~ordered.dominated_late_edition].reset_index(drop=True)
    state = state.loc[state.available_at_utc.lt("2026-01-01T00:00:00Z")].reset_index(drop=True)
    return frame, state


def load(expected):
    base.require(base.sha(SEAL) == expected, "economic seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "economic file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    source.verify(cfg["source"]["seal_sha256"])
    base.require(cfg["assets"] == ["BR"] and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"], "scope")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    cfg, parent = load(args.seal_sha)
    storage = Path("/srv/trading_lab_data")
    output = storage / "runs" / (cfg["protocol_id"] + "_" + args.seal_sha[:12])
    base.require(args.audit or not output.exists(), "no canonical rerun")
    verified = base.preflight(parent, storage)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(storage, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    raw, state = read_sources(cfg)
    signals = {arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}
    signal = signals["primary"]
    q = {"ready_asset_date_fraction": float((~(signal.feature_unavailable |
                                              signal.stale_at_fill)).mean()),
         "ready_source_dates": int(raw.ready.sum()), "source_editions": len(raw) + 1,
         "reason_counts": {str(k): int(v) for k, v in raw.reason.value_counts().items()},
         "original_vintages_proved": False}
    if args.audit:
        identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run identity")
        for name, digest in identity["files"].items():
            base.require(base.sha(output / name) == digest, "artifact drift")
        pd.testing.assert_frame_equal(raw, pd.read_parquet(output / "forecasts.parquet"))
        pd.testing.assert_frame_equal(state, pd.read_parquet(output / "states.parquet"))
        payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        base.require(payload["quality"] == q and payload["case"]["counts"] ==
                     engine.target_counts(signals), "quality/count drift")
        n = engine.prior.replay(output / "case", payload["case"], signals, q, cfg)
        print(json.dumps({"hashes": len(identity["files"]), "source_state_target_replay": True,
                          "metric_year_count_cash_replays": n, "all_true": True}))
        return
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"futures": verified, "source": cfg["source"]})
    raw.to_parquet(output / "forecasts.parquet", index=False)
    state.to_parquet(output / "states.parquet", index=False)
    gates = cfg["screen_gates"]
    base.write_json(output / "feasibility.json", {"quality": q, "moex_outcomes_read": False})
    base.require(q["ready_source_dates"] >= gates["minimum_ready_source_dates"] and
                 q["ready_asset_date_fraction"] >= gates["minimum_ready_asset_date_fraction"],
                 "source feasibility gate before market outcomes")
    start = time.monotonic()
    market = engine.market_inputs(storage, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, q, cfg, "steo_revisions")
    base.write_json(output / "metrics.json", {"protocol_id": cfg["protocol_id"],
                    "seal_sha256": args.seal_sha, "quality": q, "case": case,
                    "economic_seconds": time.monotonic() - start, "goal_verified": False})
    base.write_json(output / "identity.json", {"seal_sha256": args.seal_sha, "files": {
        str(p.relative_to(output)): base.sha(p) for p in sorted(output.rglob("*")) if p.is_file()
    }})
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


if __name__ == "__main__":
    main()
