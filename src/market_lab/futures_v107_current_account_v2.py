"""V107 V2: same economics, older compact quarterly table support and cached raw reuse."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from html.parser import HTMLParser

import pandas as pd
import pypdf

from market_lab import futures_v101_manufacturing_demand as prior

base, engine, STORAGE = prior.base, prior.engine, prior.STORAGE
CONFIG = base.PROJECT / "configs/v107_current_account_v2.json"
SEAL = base.PROJECT / "configs/v107_current_account_v2.seal.json"
MONTHS = dict(
    zip(
        [
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ],
        range(1, 13),
        strict=True,
    )
)
QUARTERS = {"I": 1, "II": 2, "III": 3, "IV": 4}


def normalize(text):
    return text.replace("\xa0", " ").replace("\u202f", " ").replace("−", "-")


class Index(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current, self.rows = None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and "versions_item" in a.get("class", "").split():
            self.current = {
                "url": a.get("href", ""),
                "published": a.get("data-tooltip-content", ""),
                "title": "",
            }

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def select(raw, cfg):
    parser = Index()
    parser.feed(raw.decode("utf-8-sig"))
    items = []
    for row in parser.rows:
        if not re.fullmatch(
            r"/Collection/Collection/File/\d+/Balance_of_Payments_[\w-]+\.pdf", row["url"]
        ):
            continue
        match = re.search(r"•\s*(IV|III|II|I)\s+квартал\s+(20\d{2})\s+г\.", normalize(row["title"]))
        base.require(match is not None, "ambiguous quarter label")
        quarter = pd.Period(year=int(match[2]), quarter=QUARTERS[match[1]], freq="Q")
        if not pd.Period("2020Q3") <= quarter <= pd.Period("2025Q3"):
            continue
        published = re.fullmatch(r"Опубликовано (\d{1,2}) (\w+) (20\d{2})", row["published"])
        base.require(published is not None and published[2] in MONTHS, "missing publication date")
        day = pd.Timestamp(
            year=int(published[3]), month=MONTHS[published[2]], day=int(published[1])
        )
        base.require(
            quarter.end_time.normalize() < day < base.BOUNDARY
            and (day - quarter.end_time.normalize()).days <= 120,
            "quarter/publication clock",
        )
        items.append(
            {
                "quarter": str(quarter),
                "publication_date": str(day.date()),
                "url": "https://cbr.ru" + row["url"],
            }
        )
    items.sort(key=lambda x: x["publication_date"])
    expected = [str(q) for q in pd.period_range("2020Q3", "2025Q3", freq="Q") if str(q) != "2022Q1"]
    base.require(
        [r["quarter"] for r in items] == expected
        and len(items) == cfg["source"]["expected_releases"],
        "incomplete quarter inventory",
    )
    base.require(
        len({r["url"] for r in items}) == len({r["publication_date"] for r in items}) == len(items),
        "duplicate source identities",
    )
    return items


def compact_table(text, row, quarter):
    """Older explicit YoY-difference layout; optional annual columns retain their labels."""
    unit = r"ПЛАТЕЖНЫЙ БАЛАНС РОССИИ\s+\(МЛРД\s+ДОЛЛ\.\s+США\)"
    base.require(len(re.findall(unit, text)) == 1, "compact table unit/title")
    header = text[: row.start()]
    q = pd.Period(quarter, freq="Q")
    roman = list(QUARTERS)[q.quarter - 1]
    delta = re.search(
        rf"Изменение\s+в\s+{roman}\s+кв\.\s+{q.year}\s+г\.\s+"
        rf"к\s+{roman}\s+кв\.\s+{q.year - 1}\s+г\.\*+\s*$",
        header,
    )
    base.require(delta is not None, "compact difference header identity")
    lines = header[: delta.start()].splitlines()
    year_lines = [
        (i, re.findall(r"20\d{2}", line))
        for i, line in enumerate(lines)
        if re.findall(r"20\d{2}", line) and not re.sub(r"20\d{2}|г\.|\*|\s", "", line)
    ]
    base.require(len(year_lines) == 1, "compact year header")
    index, years = year_lines[0]
    years = list(map(int, years))
    base.require(years == [q.year - 1, q.year], "compact year identity")
    tokens = re.sub(r"кв\.|\*", "", " ".join(lines[index + 1 :])).split()
    keys, cursor = [], 0
    for year in years:
        count = 4 if year < q.year else q.quarter
        expected = list(QUARTERS)[:count]
        base.require(tokens[cursor : cursor + count] == expected, "compact quarter headers")
        keys.extend((year, n) for n in range(1, count + 1))
        cursor += count
        if cursor < len(tokens) and tokens[cursor] == "Год":
            base.require(count == 4, "partial-year annual column")
            keys.append((year, None))
            cursor += 1
    base.require(cursor == len(tokens), "extra compact header")
    tokens = re.sub(r"(?<=,)\s+(?=\d)", "", row[1]).split()
    base.require(
        len(tokens) == len(keys) + 1 and all(re.fullmatch(r"-?\d+(?:,\d+)?", t) for t in tokens),
        "compact numeric row",
    )
    # Final column is independently rounded YoY difference, NOT a quarterly balance.
    values = dict(zip(keys, [Decimal(t.replace(",", ".")) for t in tokens[:-1]], strict=True))
    return {
        "current_account_usd_bn": str(values[(q.year, q.quarter)]),
        "prior_year_same_quarter_usd_bn": str(values[(q.year - 1, q.quarter)]),
    }


def parse_table(text, quarter):
    """Require explicit year/quarter headers; never mistake an annual total for Q4."""
    text = normalize(text)
    candidates = list(re.finditer(r"(?m)^\s*Счет текущих операций[ \t]+([^\n]+)$", text))
    if not candidates:
        return None
    base.require(len(candidates) == 1, "ambiguous current-account row")
    row = candidates[0]
    prefix = text[: row.start()]
    if re.search(r"Изменение\s+в\s+", prefix):
        return compact_table(text, row, quarter)
    start = prefix.upper().rfind("ПЛАТЕЖНЫЙ БАЛАНС")
    base.require(start >= 0, "missing table title")
    header = prefix[start:]
    base.require(re.search(r"МЛРД\s+ДОЛЛ(?:АРОВ|\.)?\s+США", header) is not None, "wrong unit")
    lines = header.splitlines()
    year_lines = [
        (i, re.findall(r"20\d{2}", line))
        for i, line in enumerate(lines)
        if re.findall(r"20\d{2}", line) and not re.sub(r"20\d{2}|г\.|\*|\s", "", line)
    ]
    base.require(len(year_lines) == 1, "ambiguous table years")
    index, labels = year_lines[0]
    years = list(map(int, labels))
    q = pd.Period(quarter, freq="Q")
    base.require(
        2 <= len(years) <= 3 and years == list(range(years[0], q.year + 1)),
        "nonconsecutive/future table years",
    )
    token_text = " ".join(lines[index + 1 :])
    token_text = re.sub(r"кв\.|\*", "", token_text)
    tokens = token_text.split()
    keys = []
    expected = []
    for year in years:
        quarters = range(1, 5) if year < q.year else range(1, q.quarter + 1)
        for number in quarters:
            keys.append((year, number))
            expected.append(list(QUARTERS)[number - 1])
        if year < q.year or q.quarter == 4:
            keys.append((year, None))
            expected.append("Год")
    base.require(tokens == expected, "quarter/annual header mismatch")
    values = row[1].split()
    base.require(
        len(values) == len(keys) and all(re.fullmatch(r"-?\d+(?:,\d+)?", v) for v in values),
        "missing/ambiguous numeric row",
    )
    values = dict(zip(keys, [Decimal(v.replace(",", ".")) for v in values], strict=True))
    current, previous = values[(q.year, q.quarter)], values[(q.year - 1, q.quarter)]
    return {"current_account_usd_bn": str(current), "prior_year_same_quarter_usd_bn": str(previous)}


def parse_pdf(raw, item):
    day, quarter = pd.Timestamp(item["publication_date"]), pd.Period(item["quarter"], freq="Q")
    base.require(day < base.BOUNDARY and quarter.end_time.normalize() < day, "protected PDF")
    base.require(pypdf.__version__ == "6.10.0", "pypdf version drift")
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    base.require(not reader.is_encrypted and 1 <= len(reader.pages) <= 25, "PDF shape")
    pages = [p.extract_text() for p in reader.pages]
    roman = list(QUARTERS)[quarter.quarter - 1]
    base.require(
        re.search(rf"\b{roman}\s+квартал\s+{quarter.year}\b", normalize(pages[0])) is not None,
        "PDF quarter identity",
    )
    # Metadata is not proof of publication, but later document dates contradict admission.
    for key in ("/CreationDate", "/ModDate"):
        value = (reader.metadata or {}).get(key, "")
        match = re.match(r"D:(\d{8})", value)
        base.require(
            match is not None and pd.Timestamp(match[1]) <= day,
            "missing/post-publication PDF metadata",
        )
    tables = [(i, parse_table(text, str(quarter))) for i, text in enumerate(pages)]
    tables = [(i, result) for i, result in tables if result is not None]
    base.require(len(tables) == 1, "missing/duplicate account table")
    page, values = tables[0]
    return {
        **item,
        **values,
        "table_page_zero_based": page,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_url": item["url"],
    }


def states(rows):
    records = []
    for row in rows:
        day = pd.Timestamp(row["publication_date"])
        q = pd.Period(row["quarter"], freq="Q")
        base.require(q.end_time.normalize() < day < base.BOUNDARY, "source period clock")
        current = Decimal(row["current_account_usd_bn"])
        previous = Decimal(row["prior_year_same_quarter_usd_bn"])
        base.require(current.is_finite() and previous.is_finite(), "nonfinite account value")
        available = (
            day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        ).tz_convert("UTC")
        records.append(
            {
                **row,
                "asset_code": "SI",
                "source_date": day,
                "observation_end": q.end_time.normalize(),
                "available_at_utc": available,
                "ready": True,
                "primary_direction": -float(current > 0 and current > previous),
                "control_direction": -1.0,
                "original_receipt_verified": False,
            }
        )
    result = pd.DataFrame(records).sort_values("source_date", ignore_index=True)
    base.require(
        not result.empty and not result.source_date.duplicated().any(), "empty/duplicate states"
    )
    return result


def targets(active, state, cfg):
    return {arm: engine.adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}


def probe(cfg, storage=STORAGE):
    spec = cfg["source"]
    root = base.safe(storage, spec["probe_path"])
    base.require(base.sha(root / "manifest.json") == spec["probe_manifest_sha256"], "probe drift")
    manifest = prior.read_json(root / "manifest.json")
    base.require(manifest["status"] == "COMPLETE_FEASIBILITY_CAPTURE_ONLY", "incomplete probe")
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "probe artifact drift")
    return root, manifest, select((root / "index.html").read_bytes(), cfg)


def collect(cfg, expected):
    source, _, items = probe(cfg)
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    root.mkdir(exist_ok=False)
    (root / "raw").mkdir()
    base.write_json(
        root / "started.json",
        {"seal_sha256": expected, "started_at_utc": datetime.now(UTC).isoformat()},
    )
    base.write_json(root / "selected.json", items)
    rows, requests = [], 0
    try:
        for name in ("index.html", "index.html.metadata.json"):
            shutil.copyfile(source / name, root / "raw" / name)
        for item in items:
            target = root / "raw" / (item["quarter"] + ".pdf")
            reused = cfg["source"]["reuse"].get(item["quarter"])
            if reused:
                for suffix in ("", ".metadata.json"):
                    shutil.copyfile(
                        source / (reused + suffix), root / "raw" / (target.name + suffix)
                    )
                raw = target.read_bytes()
            else:
                requests += 1
                raw = prior.prior.source_tools.fetch(item["url"], target, 5_000_000, 1.0)
            meta = prior.read_json(target.with_suffix(".pdf.metadata.json"))
            base.require(
                meta["url"] == item["url"]
                and meta["http_status"] == "200"
                and meta["sha256"] == base.sha(target),
                "raw response identity",
            )
            rows.append(parse_pdf(raw, item))
            print(item["quarter"], "parsed", len(rows), flush=True)
        states(rows)
        base.write_json(root / "releases.json", rows)
        status, failure = "COMPLETE", None
    except Exception as error:
        status, failure = "FAILED_SOURCE_NO_ECONOMICS", str(error)
    base.write_json(
        root / "manifest.json",
        {
            "status": status,
            "error": failure,
            "seal_sha256": expected,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "parsed_releases": len(rows),
            "new_http_requests": requests,
            "original_receipt_verified": False,
            "economic_admission": False,
            "files": {
                p.relative_to(root).as_posix(): base.sha(p)
                for p in sorted(root.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(status, base.sha(root / "manifest.json"), failure, flush=True)
    base.require(status == "COMPLETE", "source failed; no economics or automatic retry")


def verify_source(cfg, expected, digest):
    root = base.safe(STORAGE, cfg["source"]["source_parent"] + "/" + expected[:12])
    base.require(base.sha(root / "manifest.json") == digest, "source manifest drift")
    manifest = prior.read_json(root / "manifest.json")
    base.require(
        manifest["status"] == "COMPLETE" and manifest["seal_sha256"] == expected,
        "incomplete source",
    )
    for name, value in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == value, "source file drift")
    _, _, items = probe(cfg)
    base.require(items == prior.read_json(root / "selected.json"), "calendar drift")
    rows = [parse_pdf((root / "raw" / (i["quarter"] + ".pdf")).read_bytes(), i) for i in items]
    base.require(rows == prior.read_json(root / "releases.json"), "source replay drift")
    return manifest, rows


def load(expected):
    base.require(base.sha(SEAL) == expected, "V107 seal drift")
    for name, digest in prior.read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V107 code drift")
    cfg = prior.read_json(CONFIG)
    _, parent = prior.load(cfg["parent_v101_seal_sha256"])
    base.require(
        cfg["assets"] == ["SI"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["live_trading_allowed"]
        and not cfg["goal_verified"],
        "scope drift",
    )
    return cfg, parent


def run(cfg, parent, expected, digest):
    manifest, rows = verify_source(cfg, expected, digest)
    state = states(rows)
    verified = base.preflight(parent, STORAGE)
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = targets(active, state, cfg)
    p = signals["primary"]
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "source_releases": len(rows),
        "short_source_states": int(state.primary_direction.lt(0).sum()),
        "original_receipt_verified": False,
    }
    out = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    out.mkdir(exist_ok=False)
    base.write_json(
        out / "inputs.json",
        {
            "seal_sha256": expected,
            "source_manifest_sha256": digest,
            "source_manifest": manifest,
            "futures": verified,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    state.to_parquet(out / "source_states.parquet", index=False)
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(out / "case", signals, market, quality, cfg, "current_account")
    audit = prior.audit_case(out / "case", case, signals)
    payload = {
        "status": "COMPLETE",
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "source_manifest_sha256": digest,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "case": case,
        "audit": audit,
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(out / "metrics.json", payload)
    base.write_json(
        out / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "completed_at_utc": payload["completed_at_utc"],
            "files": {
                p.relative_to(out).as_posix(): base.sha(p)
                for p in sorted(out.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(case["assessment"], flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--collect", action="store_true")
    cli.add_argument("--source-manifest-sha")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    base.require(args.collect != bool(args.source_manifest_sha), "source or economic operation")
    cfg, parent = load(args.seal_sha)
    if args.collect:
        collect(cfg, args.seal_sha)
    else:
        run(cfg, parent, args.seal_sha, args.source_manifest_sha)


if __name__ == "__main__":
    main()
