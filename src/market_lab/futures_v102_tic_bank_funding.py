"""One TIC bank-funding contraction screen; reuse the sealed daily futures ledger."""

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
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v102_tic_bank_funding_v1.json"
SEAL = base.PROJECT / "configs/v102_tic_bank_funding_v1.seal.json"
ORIGIN = "https://home.treasury.gov"
INDEX_URL = ORIGIN + "/data/treasury-international-capital-tic-system/tic-press-releases-by-topic"
TITLE = "TIC Monthly Reports on Cross-Border Financial Flows"
LABEL = "change in banks' own net dollar-denominated liabilities"
MONTHS = {s.lower(): i for i, s in enumerate(calendar.month_abbr) if s}
read_json, normalize = prior.read_json, prior.prior.normalize


class Index(HTMLParser):
    def __init__(self):
        super().__init__()
        self.year, self.link, self.parts, self.links = None, None, [], []
        self.heading, self.monthly = None, False

    def handle_starttag(self, tag, attrs):
        if tag == "h4":
            self.heading = []
        if tag == "a":
            self.link, self.parts = dict(attrs).get("href", ""), []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        match = re.search(r"(\d{4}),\s*release\s*date", normalize(data), re.I)
        if match:
            self.year = int(match[1])
        if self.link is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h4" and self.heading is not None:
            self.monthly = normalize(" ".join(self.heading)).startswith(
                "1. Monthly Releases and Archives of Treasury International Capital")
            self.heading = None
        if tag == "a" and self.link is not None:
            if self.monthly:
                self.links.append((self.link, normalize(" ".join(self.parts)), self.year))
            self.link = None


def select_dates(raw, cfg):
    parser = Index()
    parser.feed(raw.decode("utf-8-sig"))
    dates = {}
    for link, label, year in parser.links:
        url = urlparse(urljoin(ORIGIN, link))
        match = re.fullmatch(r"(\d{2})/(\d{2})(?:/(\d{4}))?", label)
        if not (match and url.scheme == "https" and url.netloc == "home.treasury.gov"
                and re.fullmatch(r"/news/press-releases?/[a-z]+\d+", url.path)
                and not url.query and not url.fragment):
            continue
        month, day = int(match[1]), int(match[2])
        base.require(match[3] is not None or year is not None, "missing calendar year")
        actual_year = int(match[3]) if match[3] else year + int(month <= 2)
        if url.path in cfg["source"]["date_overrides"]:
            override = cfg["source"]["date_overrides"][url.path]
            base.require(label == override["index_label"], "calendar override label drift")
            date = pd.Timestamp(override["release_date"])
        else:
            date = pd.Timestamp(year=actual_year, month=month, day=day)
        if not pd.Timestamp("2017-12-01") <= date < base.BOUNDARY:
            continue
        key = date.strftime("%Y%m%d")
        value = ORIGIN + url.path
        base.require(key not in dates or dates[key] == value, "ambiguous release date")
        dates[key] = value
    counts = {str(m): sum(d[:6] == m.strftime("%Y%m") for d in dates)
              for m in pd.period_range("2017-12", "2025-12", freq="M")}
    expected = {m: cfg["source"]["month_count_exceptions"].get(m, 1) for m in counts}
    base.require(counts == expected and len(dates) == cfg["source"]["expected_releases"],
                 "release month coverage mismatch")
    return dict(sorted(dates.items()))


class Release(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.rows, self.row, self.cell = [], None, None, None
        self.times, self.urls, self.titles, self.title = [], [], [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") == "og:url":
            self.urls.append(attrs.get("content"))
        if tag == "time" and "datetime" in attrs.get("class", "").split():
            self.times.append(attrs.get("datetime"))
        if tag == "h2":
            self.title = []
        if tag == "table":
            base.require(self.rows is None, "nested source table")
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.row = []
        elif tag in {"td", "th"} and self.rows is not None:
            base.require(self.row is not None and self.cell is None, "malformed cell")
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.title is not None:
            self.title.append(data)

    def handle_endtag(self, tag):
        if tag == "h2" and self.title is not None:
            title = normalize(" ".join(self.title))
            if title.lower().startswith("treasury international capital"):
                self.titles.append(title)
            self.title = None
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(normalize(" ".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows is not None:
            base.require(self.cell is None, "unclosed source table")
            self.tables.append(self.rows)
            self.rows = None


def parse_release(raw, release, url):
    day = pd.Timestamp(release)
    base.require(day < base.BOUNDARY, "protected release")
    parser = Release()
    parser.feed(raw.decode("utf-8-sig"))
    base.require(parser.urls == [url] and len(parser.times) == len(parser.titles) == 1,
                 "release identity metadata")
    stamp = pd.Timestamp(parser.times[0])
    base.require(stamp.tzinfo is not None and stamp.date() == day.date()
                 and "treasury international capital" in parser.titles[0].lower(),
                 "release date/title identity")
    tables = [t for t in parser.tables if any(TITLE in r for r in t)]
    base.require(len(tables) == 1 and parser.rows is None, "ambiguous TIC table")
    rows = [[c for c in r if c] for r in tables[0]]
    base.require(any("(Billions of dollars, not seasonally adjusted)" in r for r in rows),
                 "TIC unit mismatch")
    headers = [r for r in rows if len(r) == 8 and all(x.lower() in MONTHS for x in r[-4:])]
    base.require(len(headers) == 1, "monthly header count")
    header = headers[0]
    base.require(all(re.fullmatch(r"\d{4}", x) for x in header[:2]), "annual header format")
    rolling = [re.fullmatch(r"([A-Za-z]{3})-(\d{2})", x) for x in header[2:4]]
    base.require(all(rolling), "rolling header format")
    month, year = MONTHS.get(rolling[1][1].lower()), 2000 + int(rolling[1][2])
    base.require(month is not None and rolling[0][1].lower() == rolling[1][1].lower()
                 and int(rolling[0][2]) + 1 == int(rolling[1][2]), "rolling year/month mismatch")
    observed = pd.Period(year=year, month=month, freq="M")
    periods = list(pd.period_range(end=observed, periods=4, freq="M"))
    base.require([MONTHS[x.lower()] for x in header[-4:]] == [p.month for p in periods]
                 and 1 <= day.to_period("M").ordinal - observed.ordinal <= 3,
                 "nonconsecutive/future monthly columns")
    banks = [r for r in rows if r and r[0] == "29"]
    base.require(len(banks) == 1 and len(banks[0]) == 10
                 and banks[0][1].lower().replace("’", "'") == LABEL, "bank row identity/width")
    numbers = [x.replace("−", "-") for x in banks[0][2:]]
    base.require(all(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", x) for x in numbers),
                 "missing/non-numeric bank flow")
    values = [float(x) for x in numbers]
    base.require(all(np.isfinite(x) and abs(x) < 1e6 for x in values), "bank flow range")
    return {"release_date": day.date().isoformat(), "observation_month": str(observed),
            "available_at_utc": prior.prior.day_availability(day).isoformat(),
            "bank_flow_billion_usd": values[-1], "source_url": url,
            "table_row": 29, "monthly_columns": 4, "usable": True,
            "original_receipt_verified": False}


def states(releases):
    result = []
    for row in releases:
        day, available = pd.Timestamp(row["release_date"]), pd.Timestamp(row["available_at_utc"])
        observed = pd.Period(row["observation_month"], freq="M")
        base.require(day < base.BOUNDARY and available == prior.prior.day_availability(day)
                     and available < base.BOUNDARY.tz_localize("UTC"), "protected/source clock")
        base.require(1 <= day.to_period("M").ordinal - observed.ordinal <= 3
                     and np.isfinite(row["bank_flow_billion_usd"]) and row["usable"] is True,
                     "unusable bank state")
        result.append({**row, "available": available})
    stamps = [s["available"] for s in result]
    base.require(stamps and stamps == sorted(set(stamps)), "duplicate/unordered releases")
    return result


def targets(active, state, cfg):
    plan = prior.prior.mapping_tools.mapping(active)
    plan = plan.loc[plan.asset_code.eq("SI") & plan.decision_date.notna()]
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
                arm == "control" or source["bank_flow_billion_usd"] < 0) else 0.
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
                       bank_flow_billion_usd=source["bank_flow_billion_usd"] if source else None,
                       decision_at_utc=decision, provenance="v102_tic_bank_funding_" + arm)
            result[arm].append(row)
    for arm, rows in result.items():
        frame = pd.DataFrame(rows)
        base.require(not frame.empty, "empty calendar")
        frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
        frame.loc[frame.terminal_flat, "target_weight"] = 0.
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        result[arm] = frame.sort_values("effective_date", ignore_index=True)
    return result


def checked_inventory(root, digest, status):
    base.require(base.sha(root / "manifest.json") == digest, "source manifest drift")
    manifest = read_json(root / "manifest.json")
    base.require(manifest["status"] == status, "source status drift")
    for name, expected in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == expected, "source artifact drift")
    return manifest


def check_http(path, url):
    metadata = read_json(path.with_suffix(".html.metadata.json"))
    base.require(metadata["url"] == url and metadata["http_status"] == "200"
                 and metadata["curl_returncode"] == 0 and metadata["bytes"] == path.stat().st_size
                 and metadata["sha256"] == base.sha(path), "HTTP evidence drift")


def collect(cfg, expected):
    spec = cfg["source"]
    probes = {}
    for key, item in spec["probes"].items():
        path = base.safe(STORAGE, item["path"])
        checked_inventory(path, item["manifest_sha256"], "COMPLETE_FEASIBILITY_ONLY")
        probes[key] = path
    root = base.safe(STORAGE, spec["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(root / "started.json", {"seal_sha256": expected,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    rows, requests, reused = [], 0, 0
    try:
        for name in ("index.html", "index.html.metadata.json"):
            shutil.copyfile(probes["initial"] / name, root / "raw" / name)
        check_http(root / "raw/index.html", INDEX_URL)
        dates = select_dates((root / "raw/index.html").read_bytes(), cfg)
        base.write_json(root / "selected_dates.json", dates)
        for date, url in dates.items():
            name = date + ".html"
            if date in spec["reused_dates"]:
                for suffix in ("", ".metadata.json"):
                    shutil.copyfile(probes[spec["reused_dates"][date]] / (name + suffix),
                                    root / "raw" / (name + suffix))
                raw = (root / "raw" / name).read_bytes()
                reused += 1
            else:
                requests += 1
                raw = prior.prior.source_tools.fetch(url, root / "raw" / name, 3000000, 1.)
            check_http(root / "raw" / name, url)
            rows.append(parse_release(raw, date, url))
            print(json.dumps({"parsed_releases": len(rows), "release_date": date}), flush=True)
        states(rows)
        base.require(requests == spec["expected_releases"] - len(spec["reused_dates"])
                     and reused == len(spec["reused_dates"]), "request/reuse count drift")
        base.write_json(root / "releases.json", rows)
        status, error = "COMPLETE", None
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        status, error = "FAILED_SOURCE_NO_RETRY", str(exc)
    base.write_json(root / "manifest.json", {
        "status": status, "error": error, "seal_sha256": expected,
        "parsed_releases": len(rows), "new_http_requests": requests, "reused_releases": reused,
        "completed_at_utc": datetime.now(UTC).isoformat(), "economic_admission": False,
        "original_receipt_verified": False, "files": {
            p.relative_to(root).as_posix(): base.sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}})
    print(json.dumps({"source_root": str(root), "status": status, "error": error,
                      "manifest_sha256": base.sha(root / "manifest.json")}), flush=True)
    base.require(status == "COMPLETE", "source failed; preserve root, no economics")


def verify_source(cfg, expected, manifest_sha):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    manifest = checked_inventory(root, manifest_sha, "COMPLETE")
    base.require(manifest["seal_sha256"] == expected, "source seal drift")
    dates = select_dates((root / "raw/index.html").read_bytes(), cfg)
    base.require(dates == read_json(root / "selected_dates.json"), "calendar drift")
    check_http(root / "raw/index.html", INDEX_URL)
    for date, url in dates.items():
        check_http(root / "raw" / (date + ".html"), url)
    releases = read_json(root / "releases.json")
    replay = [parse_release((root / "raw" / (d + ".html")).read_bytes(), d, u)
              for d, u in dates.items()]
    base.require(releases == replay and len(releases) == manifest["parsed_releases"],
                 "source reparse drift")
    return manifest, releases


def load(expected):
    base.require(base.sha(SEAL) == expected, "V102 seal drift")
    for name, digest in read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V102 file drift")
    cfg = read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(cfg["assets"] == ["SI"] and cfg["protected_from"] == "2026-01-01"
                 and not cfg["goal_verified"] and not cfg["live_trading_allowed"], "scope drift")
    return cfg, parent


def run(cfg, parent, expected, manifest_sha):
    manifest, releases = verify_source(cfg, expected, manifest_sha)
    state = states(releases)
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected,
                    "source_manifest_sha256": manifest_sha, "source_manifest": manifest,
                    "futures": verified, "started_at_utc": datetime.now(UTC).isoformat()})
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    signals = targets(active, state, cfg)
    quality = {"ready_asset_date_fraction": float((~(signals["primary"].feature_unavailable
                                                    | signals["primary"].stale_at_fill)).mean()),
               "source_releases": len(releases), "original_receipt_verified": False}
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "tic_bank_funding")
    audit = prior.audit_case(output / "case", case, signals)
    payload = {"status": "COMPLETE", "protocol_id": cfg["protocol_id"], "seal_sha256": expected,
               "source_manifest_sha256": manifest_sha,
               "completed_at_utc": datetime.now(UTC).isoformat(),
               "case": case, "audit": audit, "limitations": cfg["limitations"],
               "goal_verified": False}
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


if __name__ == "__main__":
    main()
