"""Bounded one-shot CBR decision-text archive; no signal, prices or PnL."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pandas as pd
import requests

from market_lab import futures_v64_si_tax_calendar as base

CONFIG = base.PROJECT / "configs/cbr_policy_releases_2018_2025_v1.json"
SEAL = base.PROJECT / "configs/cbr_policy_releases_2018_2025_v1.seal.json"
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


def plain(text):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", text)).split())


def russian_date(text):
    match = re.fullmatch(r"(\d{1,2}) ([а-я]+) (\d{4})(?: г\.| года)?", plain(text))
    base.require(match is not None and match[2] in MONTHS, "unknown CBR date")
    return pd.Timestamp(year=int(match[3]), month=MONTHS[match[2]], day=int(match[1]))


def parse_listing(content):
    html = content.decode("utf-8-sig")
    pieces = re.split(r'(?=<div\s+class="previews_day")', html)
    rows = []
    for part in pieces[1:]:
        date = re.search(r'class="previews_day-date"[^>]*>(.*?)</div>', part, re.S)
        titles = re.findall(
            r'class="previews_item-title"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', part, re.S
        )
        clocks = re.findall(r'class="previews_item-time"[^>]*>(.*?)</div>', part, re.S)
        base.require(date is not None and len(titles) == len(clocks) and titles, "listing schema")
        day = russian_date(date[1])
        for (href, title), clock in zip(titles, clocks, strict=True):
            base.require(re.fullmatch(r"\d\d:\d\d", plain(clock)) is not None, "listing clock")
            url = urljoin("https://www.cbr.ru", unescape(href))
            base.require(url.startswith("https://www.cbr.ru/press/pr/?"), "non-release link")
            rows.append(
                {
                    "publication_date": day,
                    "clock": plain(clock),
                    "url": url,
                    "headline": plain(title),
                }
            )
    base.require(bool(rows), "empty listing")
    dates = [r["publication_date"] for r in rows]
    base.require(dates == sorted(dates, reverse=True), "unordered listing")
    following = re.findall(r'data-cross-ajax-url=[\'"]([^\'"]+)[\'"]', html)
    urls = set(urljoin("https://www.cbr.ru", unescape(value)) for value in following)
    base.require(len(urls) <= 1, "ambiguous continuation")
    return rows, next(iter(urls), None)


class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.body_depth = None
        self.body_count = 0
        self.hidden = 0
        self.parts = []
        self.paragraphs = []

    def flush(self):
        text = " ".join("".join(self.parts).split())
        if text:
            self.paragraphs.append(text)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.depth += 1
            if "landing-text" in attrs.get("class", "").split():
                self.body_depth = self.depth
                self.body_count += 1
        if self.body_depth is not None:
            if tag in {"script", "style"}:
                self.hidden += 1
            elif tag in {"p", "li", "tr", "h2", "h3", "br"}:
                self.flush()

    def handle_endtag(self, tag):
        if self.body_depth is not None:
            if tag in {"script", "style"}:
                self.hidden = max(0, self.hidden - 1)
            elif tag in {"p", "li", "tr", "h2", "h3"}:
                self.flush()
            if tag == "div" and self.depth == self.body_depth:
                self.flush()
                self.body_depth = None
        if tag == "div":
            self.depth -= 1

    def handle_data(self, value):
        if self.body_depth is not None and not self.hidden:
            self.parts.append(value)


def parse_article(content, record, retrieved):
    day = record["publication_date"]
    base.require(pd.Timestamp("2018-01-01") <= day < base.BOUNDARY, "protected article")
    html = content.decode("utf-8-sig")
    headings = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    dates = re.findall(r'class="[^"]*news-info-line_date[^"]*"[^>]*>(.*?)</div>', html, re.S)
    clocks = sorted(set(re.findall(r"\d\d\.\d\d\.\d{4} \d\d:\d\d:\d\d", html)))
    base.require(len(headings) == len(dates) == len(clocks) == 1, "article identity schema")
    base.require(plain(headings[0]) == record["headline"], "headline drift")
    base.require(russian_date(dates[0]) == day, "article date drift")
    published = pd.Timestamp(datetime.strptime(clocks[0], "%d.%m.%Y %H:%M:%S"))
    base.require(
        published.normalize() == day and published.strftime("%H:%M") == record["clock"],
        "article clock drift",
    )
    parser = Article()
    parser.feed(html)
    parser.flush()
    base.require(parser.body_count == 1 and bool(parser.paragraphs), "article body schema")
    return {
        "publication_date": day,
        "published_at_utc": published.tz_localize("Europe/Moscow").tz_convert("UTC"),
        "available_at_utc": (
            day.tz_localize("Europe/Moscow") + pd.Timedelta(hours=23, minutes=59, seconds=59)
        ).tz_convert("UTC"),
        "headline": record["headline"],
        "paragraphs": parser.paragraphs,
        "source_url": record["url"],
        "retrieved_at_utc": retrieved,
        "original_version_verified": False,
    }


def load(expected):
    base.require(base.sha(SEAL) == expected, "source seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "source code drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    base.load_config(cfg["parent_helper_seal_sha256"])
    return cfg


def collect(cfg, storage, expected):
    base.require(
        os.name == "posix" and str(storage.resolve()) == "/srv/trading_lab_data", "server only"
    )
    root = base.safe(storage, cfg["output"])
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    session = requests.Session()
    session.trust_env = False
    calls, last_start, records = [], 0.0, []

    def fetch(url, name):
        nonlocal last_start
        parsed = urlsplit(url)
        base.require(parsed.scheme == "https" and parsed.netloc == "www.cbr.ru", "foreign origin")
        base.require(
            parsed.path.startswith(("/Crosscut/NewsList/LoadMore/84035", "/press/pr/")),
            "foreign route",
        )
        base.require(len(calls) < cfg["maximum_http_requests"], "HTTP budget")
        time.sleep(
            max(0, cfg["minimum_request_interval_seconds"] - (time.monotonic() - last_start))
        )
        last_start = time.monotonic()
        response = session.get(url, timeout=cfg["timeout_seconds"], allow_redirects=False)
        received = datetime.now(UTC).isoformat()
        base.require(response.status_code == 200, f"HTTP status {response.status_code}")
        base.require(len(response.content) <= cfg["maximum_response_bytes"], "response size")
        path = root / "raw" / name
        with path.open("xb") as stream:
            stream.write(response.content)
        calls.append(
            {
                "url": url,
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": base.sha(path),
                "retrieved_at_utc": received,
            }
        )
        return response.content, received

    url = cfg["listing_url"]
    first_rows = None
    previous_oldest = None
    seen_urls = set()
    for page in range(cfg["maximum_listing_pages"]):
        content, _ = fetch(url, f"list_{page:02d}.html")
        rows, following = parse_listing(content)
        if first_rows is None:
            first_rows = rows
        if previous_oldest is not None:
            base.require(rows[0]["publication_date"] < previous_oldest, "page overlap or drift")
        for row in rows:
            base.require(row["url"] not in seen_urls, "duplicate listing record")
            seen_urls.add(row["url"])
        records.extend(rows)
        previous_oldest = rows[-1]["publication_date"]
        if previous_oldest < pd.Timestamp(cfg["source_start"]):
            break
        base.require(following is not None, "premature end of archive")
        url = following
    else:
        raise ValueError("listing budget exhausted before source start")
    recheck, _ = fetch(cfg["listing_url"], "list_recheck.html")
    base.require(parse_listing(recheck)[0] == first_rows, "listing changed during collection")
    chosen = [
        r
        for r in records
        if pd.Timestamp(cfg["source_start"])
        <= r["publication_date"]
        <= pd.Timestamp(cfg["source_end"])
    ]
    counts = pd.Series([r["publication_date"].year for r in chosen]).value_counts()
    base.require(
        all(counts.get(year, 0) >= cfg["minimum_releases_each_year"] for year in range(2018, 2026)),
        "incomplete yearly release coverage",
    )
    output = []
    for i, record in enumerate(chosen):
        content, received = fetch(
            record["url"], f"article_{i:03d}_{record['publication_date'].strftime('%Y%m%d')}.html"
        )
        row = parse_article(content, record, received)
        row["raw_sha256"] = calls[-1]["sha256"]
        output.append(row)
    frame = pd.DataFrame(output).sort_values(["published_at_utc", "source_url"], ignore_index=True)
    path = root / "releases.parquet"
    frame.to_parquet(path, index=False)
    base.write_json(
        root / "manifest.json",
        {
            "protocol_id": cfg["protocol_id"],
            "seal_sha256": expected,
            "processed": {
                "path": path.name,
                "bytes": path.stat().st_size,
                "rows": len(frame),
                "sha256": base.sha(path),
            },
            "minimum_publication_date": str(frame.publication_date.min().date()),
            "maximum_publication_date": str(frame.publication_date.max().date()),
            "releases_by_year": {str(k): int(v) for k, v in sorted(counts.items())},
            "request_count": len(calls),
            "listing_rows": len(records),
            "raw": calls,
            "original_versions_proved": False,
            "economic_admission": False,
            "contains_market_prices_returns_targets_or_pnl": False,
            "availability": cfg["availability"],
            "goal_verified": False,
        },
    )
    print(
        json.dumps(
            {
                "output": str(root),
                "rows": len(frame),
                "requests": len(calls),
                "manifest_sha256": base.sha(root / "manifest.json"),
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    args = parser.parse_args()
    collect(load(args.seal_sha), args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
