"""One published manufacturing-output demand hypothesis; existing daily ledger."""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd

from market_lab import futures_v98_fomc_event_premium as prior

base, engine = prior.base, prior.engine
STORAGE = Path("/srv/trading_lab_data")
CONFIG = base.PROJECT / "configs/v101_manufacturing_demand_v1.json"
SEAL = base.PROJECT / "configs/v101_manufacturing_demand_v1.seal.json"
ORIGIN = "https://www.federalreserve.gov/releases/g17/"
TITLE = "Industrial Production and Capacity Utilization: Summary"
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class IndexLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dates = set()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        url = urlparse(urljoin(ORIGIN, dict(attrs).get("href", "")))
        if url.scheme != "https" or url.netloc != "www.federalreserve.gov" or url.query:
            return
        match = re.fullmatch(r"/releases/g17/(\d{8})(?:/|/default\.htm)?", url.path, re.I)
        if match:
            self.dates.add(match[1])


def select_dates(raw, cfg):
    parser = IndexLinks()
    parser.feed(raw.decode("utf-8-sig"))
    spec = cfg["source"]
    dates = sorted(d for d in parser.dates if spec["first_date"] <= d <= spec["last_date"])
    base.require(len(dates) == spec["expected_releases"], "missing release dates")
    counts = {str(m): sum(d[:6] == m.strftime("%Y%m") for d in dates)
              for m in pd.period_range("2017-12", "2025-12", freq="M")}
    expected = {m: spec["month_count_exceptions"].get(m, 1) for m in counts}
    base.require(counts == expected, "release month coverage mismatch")
    base.require(all(pd.Timestamp(d) < base.BOUNDARY for d in dates), "protected release date")
    return dates


class SummaryTable(HTMLParser):
    """Keep table cells and their explicit header references, not positional columns."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows = [], None
        self.row, self.cell = None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            base.require(self.rows is None, "nested summary table")
            if attrs.get("title") == TITLE:
                self.rows = []
        if self.rows is None:
            return
        if tag == "tr":
            self.row = []
        elif tag in {"th", "td"}:
            base.require(self.cell is None and self.row is not None, "malformed cells")
            self.cell = {"tag": tag, "attrs": attrs, "parts": [], "abbr": []}
        elif tag == "abbr" and self.cell is not None:
            self.cell["abbr"].append(attrs.get("title", "").lower())

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["parts"].append(data)

    def handle_endtag(self, tag):
        if self.rows is None:
            return
        if tag in {"th", "td"} and self.cell is not None:
            self.cell["text"] = prior.normalize(" ".join(self.cell.pop("parts")))
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            base.require(self.cell is None, "unclosed table cell")
            self.tables.append(self.rows)
            self.rows = None


def parse_release(raw, release, url):
    day = pd.Timestamp(release)
    base.require(day < base.BOUNDARY, "protected source")
    decoded = raw.decode("utf-8-sig")
    text_parser = prior.TextParser()
    text_parser.feed(decoded)
    text = prior.normalize(" ".join(text_parser.parts))
    headers = re.findall(r"Release Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    base.require(len(headers) == 1 and pd.Timestamp(headers[0]) == day, "release identity")
    base.require("Seasonally adjusted" in text, "missing seasonal unit")
    parser = SummaryTable()
    parser.feed(decoded)
    base.require(len(parser.tables) == 1 and parser.rows is None, "ambiguous summary table")
    rows = parser.tables[0]
    cells = [c for row in rows for c in row]
    identified = [c for c in cells if c["attrs"].get("id")]
    by_id = {c["attrs"]["id"].strip(): c for c in identified}
    base.require(len(by_id) == len(identified), "duplicate table header id")
    manufacturing = [row for row in rows if row and row[0]["tag"] == "th"
                     and row[0]["text"] in {"Manufacturing (see note below)", "Manufacturing*"}]
    base.require(len(manufacturing) == 1, "ambiguous manufacturing row")
    observations = []
    for cell in manufacturing[0][1:]:
        keys = cell["attrs"].get("headers", "").split()
        base.require(keys and all(k in by_id for k in keys), "unknown header reference")
        refs = [by_id[k] for k in keys]
        if not any(c["text"] == "Percent change" for c in refs):
            continue
        years = [int(c["text"]) for c in refs if re.fullmatch(r"\d{4}", c["text"])]
        months = []
        for c in refs:
            match = re.fullmatch(r"([A-Za-z]+)\.? \[([rp])\]", c["text"])
            if match and match[1].lower() in MONTHS:
                months.append((MONTHS[match[1].lower()], match[2]))
        if not years and not months:  # Separate year-on-year column, never the feature.
            continue
        base.require(len(years) == len(months) == 1, "ambiguous month/year headers")
        base.require(re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", cell["text"]) is not None,
                     "missing/non-numeric monthly estimate")
        value = float(cell["text"])
        base.require(np.isfinite(value) and -100 < value <= 1000, "invalid monthly change")
        observations.append((pd.Period(year=years[0], month=months[0][0], freq="M"),
                             months[0][1], value))
    base.require(len(observations) in (6, 7), "unexpected monthly column count")
    periods = [r[0] for r in observations]
    base.require(periods == list(pd.period_range(periods[0], periods[-1], freq="M")),
                 "duplicate/nonconsecutive monthly columns")
    month, flag, value = observations[-1]
    base.require(flag == "p" and 1 <= day.to_period("M").ordinal - month.ordinal <= 3,
                 "latest observation is not prior preliminary month")
    return {"release_date": day.date().isoformat(), "observation_month": str(month),
            "available_at_utc": prior.day_availability(day).isoformat(),
            "manufacturing_mom_percent": value, "source_url": url,
            "monthly_columns": len(observations), "usable": True,
            "original_receipt_verified": False}


def states(releases):
    result = []
    for row in releases:
        day = pd.Timestamp(row["release_date"])
        available = pd.Timestamp(row["available_at_utc"])
        base.require(day < base.BOUNDARY and available == prior.day_availability(day)
                     and available < base.BOUNDARY.tz_localize("UTC"), "protected/source clock")
        observed = pd.Period(row["observation_month"], freq="M")
        base.require(1 <= day.to_period("M").ordinal - observed.ordinal <= 3,
                     "observation clock mismatch")
        value = row["manufacturing_mom_percent"]
        base.require(np.isfinite(value) and -100 < value <= 1000 and row["usable"] is True,
                     "unusable source state")
        result.append({**row, "available": available})
    stamps = [s["available"] for s in result]
    base.require(stamps and stamps == sorted(set(stamps)), "duplicate/unordered releases")
    return result


def collect(cfg, expected):
    spec = cfg["source"]
    probe = base.safe(STORAGE, spec["probe_path"])
    base.require(base.sha(probe / "manifest.json") == spec["probe_manifest_sha256"],
                 "probe manifest drift")
    inventory = read_json(probe / "manifest.json")
    base.require(inventory["status"] == "COMPLETE_FEASIBILITY_ONLY", "incomplete probe")
    for name, digest in inventory["files"].items():
        base.require(base.sha(base.safe(probe, name)) == digest, "probe artifact drift")
    root = base.safe(STORAGE, spec["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    rows, requests = [], 0
    try:
        for name in ("index.html", "index.html.metadata.json"):
            shutil.copyfile(probe / name, root / "raw" / name)
        dates = select_dates((root / "raw/index.html").read_bytes(), cfg)
        base.write_json(root / "selected_dates.json", dates)
        for release in dates:
            name = release + ".html"
            url = ORIGIN + release + "/"
            if release in spec["reused_probe_dates"]:
                base.require(name in inventory["files"], "unrecorded source reuse")
                for suffix in ("", ".metadata.json"):
                    shutil.copyfile(probe / (name + suffix), root / "raw" / (name + suffix))
                raw = (root / "raw" / name).read_bytes()
            else:
                requests += 1
                raw = prior.source_tools.fetch(url, root / "raw" / name, 3000000, 1.0)
            rows.append(parse_release(raw, release, url))
            print(json.dumps({"parsed_releases": len(rows), "release_date": release}), flush=True)
        states(rows)
        base.write_json(root / "releases.json", rows)
        status, error = "COMPLETE", None
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as failure:
        status, error = "FAILED_SOURCE_NO_RETRY", str(failure)
    base.write_json(root / "manifest.json", {
        "status": status, "error": error, "seal_sha256": expected,
        "parsed_releases": len(rows), "new_http_requests": requests,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "original_receipt_verified": False, "economic_admission": False,
        "files": {p.relative_to(root).as_posix(): base.sha(p)
                  for p in sorted(root.rglob("*")) if p.is_file()}})
    print(json.dumps({"source_root": str(root), "status": status, "error": error,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(status == "COMPLETE", "source failed; preserve root, no economics")


def verify_source(cfg, expected, manifest_sha):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    base.require(base.sha(root / "manifest.json") == manifest_sha, "source manifest drift")
    manifest = read_json(root / "manifest.json")
    base.require(manifest["status"] == "COMPLETE" and manifest["seal_sha256"] == expected,
                 "incomplete source")
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "source artifact drift")
    dates = select_dates((root / "raw/index.html").read_bytes(), cfg)
    base.require(dates == read_json(root / "selected_dates.json"), "source calendar drift")
    releases = read_json(root / "releases.json")
    replay = [parse_release((root / "raw" / (d + ".html")).read_bytes(), d, ORIGIN + d + "/")
              for d in dates]
    base.require(releases == replay and len(releases) == manifest["parsed_releases"],
                 "source reparse drift")
    return manifest, releases


def audit_case(folder, case, signals):
    base.require(engine.target_counts(signals) == case["counts"], "target count drift")
    for arm, frame in signals.items():
        pd.testing.assert_frame_equal(frame, pd.read_parquet(folder / f"targets_{arm}.parquet"))
        used = frame.loc[frame.target_weight.ne(0)]
        base.require(frame.effective_date.lt(base.BOUNDARY).all()
                     and frame.decision_date.lt(frame.effective_date).all()
                     and used.available_at_utc.le(used.decision_at_utc).all(), "noncausal targets")
        for cost, metric in case["metrics"][arm].items():
            ledger = pd.read_parquet(folder / f"ledger_{arm}_{cost}.parquet")
            orders = pd.read_parquet(folder / f"orders_{arm}_{cost}.parquet")
            positions = pd.read_parquet(folder / f"positions_{arm}_{cost}.parquet")
            dates = pd.to_datetime(ledger.session_date)
            costs = ledger.commission_cost + ledger.slippage_cost
            base.require(dates.lt(base.BOUNDARY).all() and np.isclose(
                ledger.starting_cash.iloc[0], base.CAPITAL), "ledger boundary/capital drift")
            base.require(np.allclose(ledger.starting_cash.iloc[1:], ledger.ending_cash.iloc[:-1],
                                      rtol=1e-10, atol=1e-6), "cash continuity drift")
            base.require(np.allclose(ledger.ending_cash, ledger.starting_cash
                                      + ledger.variation_margin - costs, rtol=1e-10, atol=1e-6),
                         "daily cash identity drift")
            filled = orders.loc[orders.filled.eq(True)]  # noqa: E712
            paid = float(filled.commission_cost.sum() + filled.slippage_cost.sum())
            base.require(np.isclose(paid, costs.sum()) and np.isclose(paid, metric["total_cost"]),
                         "order costs drift")
            replay = base._performance_metrics(ledger.ending_cash, ledger.session_date,
                                                base.CAPITAL)
            base.require(all(np.isclose(metric[k], v) for k, v in replay.items()), "metric drift")
            daily = ledger.ending_cash / ledger.starting_cash - 1
            for year, part in daily.groupby(dates.dt.year):
                base.require(np.isclose((1 + part).prod() - 1,
                                         metric["annual_returns"][str(year)]), "annual drift")
            counts = engine.shared.position_counts(positions)
            base.require(all(metric[k] == v for k, v in counts.items()), "position count drift")
    return {"source_target_replays": len(signals),
            "cash_cost_metric_annual_count_replays": sum(len(v) for v in case["metrics"].values())}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V101 seal drift")
    for name, digest in read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V101 file drift")
    cfg = read_json(CONFIG)
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(cfg["assets"] == ["BR"] and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"], "scope drift")
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def run(cfg, parent, expected, manifest_sha):
    manifest, releases = verify_source(cfg, expected, manifest_sha)
    state = states(releases)
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = targets(active, state, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "source_releases": len(releases), "original_receipt_verified": False}
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "source_manifest": manifest,
                    "futures": verified, "started_at_utc": datetime.now(UTC).isoformat()})
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "manufacturing")
    audit = audit_case(output / "case", case, signals)
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"],
               "seal_sha256": expected, "source_manifest_sha256": manifest_sha,
               "completed_at_utc": datetime.now(UTC).isoformat(), "case": case,
               "audit": audit, "limitations": cfg["limitations"], "goal_verified": False}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "manifest.json", {"status": "COMPLETE", "seal_sha256": expected,
                    "completed_at_utc": payload["completed_at_utc"], "files": {
                        p.relative_to(output).as_posix(): base.sha(p)
                        for p in sorted(output.rglob("*")) if p.is_file()}})
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--collect", action="store_true")
    cli.add_argument("--source-manifest-sha")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    base.require(args.collect != bool(args.source_manifest_sha), "choose source or economics")
    cfg, parent = load(args.seal_sha)
    if args.collect:
        collect(cfg, args.seal_sha)
    else:
        run(cfg, parent, args.seal_sha, args.source_manifest_sha)


def targets(active, state, cfg):
    plan = prior.mapping_tools.mapping(active)
    plan = plan.loc[plan.asset_code.eq("BR") & plan.decision_date.notna()]
    result = {"primary": [], "control": []}
    for original in plan.to_dict("records"):
        day, effective = original["decision_date"], original["effective_date"]
        if not pd.Timestamp(cfg["period"]["start"]) <= effective <= pd.Timestamp(
                cfg["period"]["end"]):
            continue
        decision = (day + pd.Timedelta(hours=18, minutes=45)).tz_localize(
            "Europe/Moscow").tz_convert("UTC")
        available = [s for s in state if s["available"] <= decision]
        source = max(available, key=lambda s: s["available"]) if available else None
        ready = bool(source and (day - pd.Timestamp(source["release_date"])).days
                     <= cfg["signal"]["maximum_age_days"])
        for arm in result:
            row = dict(original)
            row["feature_unavailable"] = not ready
            row["source_unavailable"] = not (row["plan_tradable"] is True
                                               and pd.notna(row["contract_id"]))
            requested = cfg["signal"]["target_weight"] if ready and (
                arm == "control" or source["manufacturing_mom_percent"] > 0) else 0.0
            stale = bool(requested and (
                (effective - day).days > cfg["signal"]["maximum_fill_gap_days"]
                or (effective - pd.Timestamp(source["release_date"])).days
                > cfg["signal"]["maximum_age_days"]))
            row.update(requested_weight=requested, stale_at_fill=stale,
                       target_weight=requested if not (row["source_unavailable"] or stale) else 0.,
                       source_url=source["source_url"] if source else "",
                       source_date=pd.Timestamp(source["release_date"]) if source else pd.NaT,
                       available_at_utc=source["available"] if source else pd.NaT,
                       observation_month=source["observation_month"] if source else None,
                       manufacturing_mom_percent=source["manufacturing_mom_percent"]
                       if source else None, decision_at_utc=decision,
                       provenance="v101_manufacturing_demand_" + arm)
            result[arm].append(row)
    for arm, rows in result.items():
        frame = pd.DataFrame(rows)
        base.require(not frame.empty, "empty calendar")
        frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
        frame.loc[frame.terminal_flat, "target_weight"] = 0.
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        result[arm] = frame.sort_values("effective_date", ignore_index=True)
    return result


if __name__ == "__main__":
    main()
