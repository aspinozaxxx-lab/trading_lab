"""Unsealed ISS news catalogue prototype; never grants event/PIT/PnL admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = "configs/moex_index_news_source_v1.yaml"
SEAL_PATH = "configs/moex_index_news_source_v1.seal.json"
BASE = "https://iss.moex.com/iss/sitenews"
LOWER = "2011-01-01 00:00:00"
UPPER = "2026-01-01 00:00:00"


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8-sig")


def write_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value)


def stamp(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", value):
        raise ValueError("invalid publication stamp format")
    datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return value


def block(payload: dict, name: str, columns: list[str]) -> list[dict]:
    item = payload.get(name)
    if not isinstance(item, dict) or item.get("columns") != columns:
        raise ValueError(f"unexpected {name} columns")
    data = item.get("data")
    if not isinstance(data, list) or any(
        not isinstance(r, list) or len(r) != len(columns) for r in data
    ):
        raise ValueError("invalid table rows")
    return [dict(zip(columns, row, strict=True)) for row in data]


def payload_json(content: bytes, blocks: set[str]) -> dict:
    payload = json.loads(content.decode("utf-8-sig"))
    if not isinstance(payload, dict) or set(payload) != blocks:
        raise ValueError("unexpected payload blocks")
    return payload


def parse_listing(content: bytes, expected_start: int, clock_only: bool) -> tuple[list[dict], dict]:
    payload = payload_json(content, {"sitenews", "sitenews.cursor"})
    columns = ["id", "published_at"] + ([] if clock_only else ["title"])
    rows = block(payload, "sitenews", columns)
    cursors = block(payload, "sitenews.cursor", ["INDEX", "TOTAL", "PAGESIZE"])
    if len(cursors) != 1:
        raise ValueError("cursor cardinality")
    cursor = cursors[0]
    if any(type(v) is not int for v in cursor.values()):
        raise ValueError("cursor types")
    if (
        cursor["INDEX"] != expected_start
        or cursor["PAGESIZE"] <= 0
        or cursor["TOTAL"] < 0
        or len(rows) > cursor["PAGESIZE"]
    ):
        raise ValueError("cursor bounds")
    ids, stamps = [], []
    for row in rows:
        if type(row["id"]) is not int or row["id"] <= 0:
            raise ValueError("invalid news id")
        value = stamp(row["published_at"])
        if not clock_only and (value >= UPPER or not isinstance(row["title"], str)):
            raise ValueError("protected date or invalid title")
        ids.append(row["id"])
        stamps.append(value)
    if len(set(ids)) != len(ids) or stamps != sorted(stamps, reverse=True):
        raise ValueError("duplicate id or non-descending chronology")
    return rows, cursor


def classify_title(title: str) -> str:
    value = title.casefold()
    if "индекс" not in value:
        return "non_index_news"
    terms = ("баз", "состав", "спис", "включ", "исключ", "пересмотр", "перечн", "изменени")
    return "candidate_index_change" if any(t in value for t in terms) else "other_index_news"


class BodyText(HTMLParser):
    """Parse the API article fragment, not the enclosing MOEX website."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.paragraphs: list[str] = []
        self.hidden = 0

    def flush(self) -> None:
        value = " ".join("".join(self.parts).split())
        if value:
            self.paragraphs.append(value)
        self.parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "tr", "li", "br", "h1", "h2", "h3"}:
            self.flush()
        elif not self.hidden and tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.flush()

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def detail_row(content: bytes, news_id: int, expected_stamp: str, body: bool) -> dict:
    columns = ["id", "title", "published_at"] + (["body"] if body else [])
    rows = block(payload_json(content, {"content"}), "content", columns)
    if len(rows) != 1:
        raise ValueError("article cardinality")
    row = rows[0]
    if row["id"] != news_id or stamp(row["published_at"]) != expected_stamp:
        raise ValueError("article identity/stamp mismatch")
    if not LOWER <= expected_stamp < UPPER or not isinstance(row["title"], str):
        raise ValueError("article outside discovery interval")
    return row


def parse_article(content: bytes, news_id: int, expected_stamp: str) -> dict:
    row = detail_row(content, news_id, expected_stamp, True)
    body = row["body"]
    if not isinstance(body, str) or not body.strip():
        raise ValueError("missing article body")
    parser = BodyText()
    parser.feed(body)
    parser.flush()
    if not parser.paragraphs:
        raise ValueError("empty parsed article")
    return {
        "id": news_id,
        "title": row["title"],
        "published_at_raw": expected_stamp,
        "body_sha256": sha(body.encode("utf-8")),
        "paragraphs": parser.paragraphs,
        "content_vintage": "current_retrieved",
        "publication_timezone_status": "unverified",
        "original_version_verified": False,
        "historical_model_eligible": False,
        "available_at": None,
    }


def candidates(rows: list[dict], config: dict) -> list[dict]:
    return [
        row
        for row in rows
        if classify_title(row["title"]) == "candidate_index_change"
        and (
            "акци" in row["title"].casefold()
            or not any(word in row["title"].casefold() for word in config["excluded_title_terms"])
        )
    ]


def load_protocol(seal_sha: str) -> tuple[dict, dict]:
    seal_bytes = (PROJECT_ROOT / SEAL_PATH).read_bytes()
    if sha(seal_bytes) != seal_sha:
        raise ValueError("closure seal mismatch")
    seal = json.loads(seal_bytes.decode("utf-8-sig"))
    for relative, expected in seal["files"].items():
        path = (PROJECT_ROOT / relative).resolve()
        if not path.is_relative_to(PROJECT_ROOT.resolve()) or sha(path.read_bytes()) != expected:
            raise ValueError(f"sealed file mismatch: {relative}")
    config = yaml.safe_load((PROJECT_ROOT / CONFIG_PATH).read_text(encoding="utf-8-sig"))
    if config["publication_lower"] != LOWER or config["publication_upper_exclusive"] != UPPER:
        raise ValueError("date boundary mismatch")
    return config, seal


class Acquisition:
    def __init__(self, output: Path, config: dict) -> None:
        self.output, self.config = output, config
        self.records: list[dict] = []
        self.session = requests.Session()
        self.last_request = 0.0

    def fetch(self, kind: str, key: int, **metadata: object) -> tuple[bytes, int]:
        if len(self.records) >= self.config["max_requests"]:
            raise ValueError("request budget exceeded")
        params = {"iss.meta": "off"}
        if kind in {"clock", "catalog"}:
            params.update(
                {
                    "start": key,
                    "lang": "ru",
                    "iss.only": "sitenews,sitenews.cursor",
                    "sitenews.columns": "id,published_at" + (",title" if kind == "catalog" else ""),
                }
            )
            url = BASE + ".json?" + urlencode(params)
        elif kind in {"header", "article"}:
            if kind == "header":
                params["content.columns"] = "id,title,published_at"
            url = BASE + f"/{key}.json?" + urlencode(params)
        else:
            raise ValueError("unknown request kind")
        delay = self.config["request_interval_seconds"] - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        retrieved = datetime.now(UTC).isoformat()
        response = self.session.get(
            url, timeout=self.config["timeout_seconds"], allow_redirects=False
        )
        content = response.content
        relative = f"raw/{len(self.records):05d}_{kind}_{key}.json"
        write_new(self.output / relative, content)
        record = {
            "kind": kind,
            "key": key,
            "url": url,
            "final_url": response.url,
            "retrieved_at_utc": retrieved,
            "status": response.status_code,
            "path": relative,
            "bytes": len(content),
            "sha256": sha(content),
            "content_type": response.headers.get("Content-Type"),
            **metadata,
        }
        self.records.append(record)
        if response.status_code != 200:
            raise ValueError(f"source HTTP {response.status_code}; no retry or bypass")
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("non-JSON response")
        return content, len(self.records) - 1


def assemble(records: list[dict], get_raw, traversal: list[int], config: dict) -> dict:
    clocks: dict[int, tuple[list[dict], dict]] = {}
    catalog: list[dict] = []
    articles: list[dict] = []
    consumed: dict[int, list[dict]] = {}
    heads = []
    for index, record in enumerate(records):
        content = get_raw(record)
        kind, key = record["kind"], record["key"]
        if (
            record["status"] != 200
            or record["sha256"] != sha(content)
            or len(content) != record["bytes"]
        ):
            raise ValueError("raw identity/status mismatch")
        if kind == "clock":
            clocks[index] = parse_listing(content, key, True)
            if key == 0:
                heads.append(clocks[index])
        elif kind == "catalog":
            rows, cursor = parse_listing(content, key, False)
            clock, expected_cursor = clocks[record["clock_request"]]
            if (
                [{k: r[k] for k in ("id", "published_at")} for r in rows] != clock
                or cursor != expected_cursor
                or not all(LOWER <= r["published_at"] < UPPER for r in rows)
            ):
                raise ValueError("listing changed or outside range")
            catalog.extend(rows)
            consumed.setdefault(record["clock_request"], []).extend(rows)
        elif kind == "header":
            row = detail_row(content, key, record["expected_stamp"], False)
            catalog.append(row)
            consumed.setdefault(record["clock_request"], []).append(row)
        elif kind == "article":
            articles.append(parse_article(content, key, record["expected_stamp"]))
        else:
            raise ValueError("unknown archived request kind")
    if len(heads) < 2 or heads[0] != heads[-1]:
        raise ValueError("head snapshot drift")
    size, total = heads[0][1]["PAGESIZE"], heads[0][1]["TOTAL"]
    if any(c["PAGESIZE"] != size or c["TOTAL"] != total for _, c in clocks.values()):
        raise ValueError("archive size drift")
    starts = [clocks[index][1]["INDEX"] for index in traversal]
    if not starts or starts != list(range(starts[0], starts[-1] + size, size)):
        raise ValueError("incomplete traversal")
    for index in traversal:
        expected = [r for r in clocks[index][0] if LOWER <= r["published_at"] < UPPER]
        actual = [{k: r[k] for k in ("id", "published_at")} for r in consumed.get(index, [])]
        if actual != expected:
            raise ValueError("unaccounted eligible catalogue rows")
    first_rows = clocks[traversal[0]][0]
    last_rows = clocks[traversal[-1]][0]
    lower_bracket = bool(last_rows and last_rows[-1]["published_at"] < LOWER)
    upper_bracket = starts[0] == 0 or any(
        cursor["INDEX"] == starts[0] - size and rows and rows[-1]["published_at"] >= UPPER
        for rows, cursor in clocks.values()
    )
    if not first_rows or not lower_bracket or not upper_bracket:
        raise ValueError("publication interval not bracketed")
    ids = [r["id"] for r in catalog]
    stamps = [r["published_at"] for r in catalog]
    if len(ids) != len(set(ids)) or stamps != sorted(stamps, reverse=True):
        raise ValueError("cross-page duplicate/chronology failure")
    selected = candidates(catalog, config)
    if [a["id"] for a in articles] != [r["id"] for r in selected]:
        raise ValueError("candidate article coverage mismatch")
    for article, row in zip(articles, selected, strict=True):
        if article["title"] != row["title"] or article["published_at_raw"] != row["published_at"]:
            raise ValueError("catalogue/article mismatch")
    counts = Counter(r["published_at"][:4] for r in catalog)
    selected_counts = Counter(r["published_at"][:4] for r in selected)
    return {
        "catalog": catalog,
        "articles": articles,
        "summary": {
            "status": "CATALOG_COLLECTED_EVENT_ADMISSION_PENDING",
            "catalog_rows": len(catalog),
            "candidate_articles": len(articles),
            "requests": len(records),
            "listing_pages": len(traversal),
            "archive_total_at_capture": total,
            "publication_min": min(stamps),
            "publication_max": max(stamps),
            "catalog_rows_by_year": dict(sorted(counts.items())),
            "candidate_articles_by_year": dict(sorted(selected_counts.items())),
            "listing_interval_complete": True,
            "event_corpus_complete": False,
            "original_version_verified": False,
            "historical_model_eligible": False,
            "economic_evaluation_allowed": False,
            "live_trading_allowed": False,
        },
    }


def collect(storage_root: Path, seal_sha: str) -> dict:
    config, _ = load_protocol(seal_sha)
    base = storage_root.resolve()
    output = (
        base / "data/processed/index_announcements" / (config["protocol_id"] + "_" + seal_sha[:12])
    )
    if output.exists() or not output.resolve().is_relative_to(base):
        raise ValueError("existing or escaping output")
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "started.json",
        encode({"seal_sha256": seal_sha, "started_at": datetime.now(UTC).isoformat()}),
    )
    acquisition = Acquisition(output, config)
    traversal: list[int] = []
    try:
        head, head_idx = acquisition.fetch("clock", 0)
        _, initial = parse_listing(head, 0, True)
        size, total = initial["PAGESIZE"], initial["TOTAL"]
        page_count = (total + size - 1) // size
        if page_count > config["max_listing_pages"]:
            raise ValueError("archive page budget")
        cache: dict[int, tuple[list[dict], int]] = {0: (parse_listing(head, 0, True)[0], head_idx)}

        def clock_page(page: int) -> tuple[list[dict], int]:
            if page not in cache:
                raw, index = acquisition.fetch("clock", page * size)
                rows, cursor = parse_listing(raw, page * size, True)
                if cursor["TOTAL"] != total or cursor["PAGESIZE"] != size:
                    raise ValueError("archive changed during discovery")
                cache[page] = rows, index
            return cache[page]

        lo, hi = 0, page_count - 1
        while lo < hi:
            mid = (lo + hi) // 2
            rows, _ = clock_page(mid)
            if not rows:
                raise ValueError("empty interior clock page")
            if rows[-1]["published_at"] < UPPER:
                hi = mid
            else:
                lo = mid + 1
        if lo:
            clock_page(lo - 1)
        catalog: list[dict] = []
        for page in range(lo, page_count):
            rows, index = clock_page(page)
            traversal.append(index)
            eligible = [r for r in rows if LOWER <= r["published_at"] < UPPER]
            if rows and len(eligible) == len(rows):
                raw, _ = acquisition.fetch("catalog", page * size, clock_request=index)
                values, cursor = parse_listing(raw, page * size, False)
                if [{k: r[k] for k in ("id", "published_at")} for r in values] != rows or cursor[
                    "TOTAL"
                ] != total:
                    raise ValueError("clock/catalogue drift")
                catalog.extend(values)
            else:
                for row in eligible:
                    raw, _ = acquisition.fetch(
                        "header", row["id"], clock_request=index, expected_stamp=row["published_at"]
                    )
                    catalog.append(detail_row(raw, row["id"], row["published_at"], False))
            if len(traversal) % 50 == 0:
                print(
                    json.dumps({"listing_pages": len(traversal), "catalog_rows": len(catalog)}),
                    flush=True,
                )
            if not rows or rows[-1]["published_at"] < LOWER:
                break
        selected = candidates(catalog, config)
        if len(selected) > config["max_candidate_articles"]:
            raise ValueError("candidate article budget")
        print(
            json.dumps({"catalogue_done": len(catalog), "candidate_articles": len(selected)}),
            flush=True,
        )
        for count, row in enumerate(selected, 1):
            raw, _ = acquisition.fetch("article", row["id"], expected_stamp=row["published_at"])
            parse_article(raw, row["id"], row["published_at"])
            if count % 50 == 0:
                print(
                    json.dumps({"articles_done": count, "articles_total": len(selected)}),
                    flush=True,
                )
        acquisition.fetch("clock", 0)
        result = assemble(
            acquisition.records, lambda r: (output / r["path"]).read_bytes(), traversal, config
        )
        files = {}
        for name, value in result.items():
            content = encode(value)
            write_new(output / (name + ".json"), content)
            files[name + ".json"] = sha(content)
        manifest = {
            "seal_sha256": seal_sha,
            "config_sha256": sha((PROJECT_ROOT / CONFIG_PATH).read_bytes()),
            "requests": acquisition.records,
            "traversal": traversal,
            "files": files,
            "status": result["summary"]["status"],
            "completed_at": datetime.now(UTC).isoformat(),
        }
        raw = encode(manifest)
        write_new(output / "manifest.json", raw)
        return {"output": str(output), "manifest_sha256": sha(raw), **result["summary"]}
    except Exception as error:
        write_new(
            output / "failure.json",
            encode(
                {
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "requests": acquisition.records,
                    "traversal": traversal,
                    "economic_evaluation_allowed": False,
                }
            ),
        )
        raise


def audit(output: Path, seal_sha: str, manifest_sha: str) -> dict:
    config, _ = load_protocol(seal_sha)
    output = output.resolve()
    raw = (output / "manifest.json").read_bytes()
    if sha(raw) != manifest_sha:
        raise ValueError("manifest SHA mismatch")
    manifest = json.loads(raw.decode("utf-8-sig"))
    if manifest["seal_sha256"] != seal_sha:
        raise ValueError("manifest seal mismatch")

    def read_record(record: dict) -> bytes:
        path = (output / record["path"]).resolve()
        if not path.is_relative_to(output) or path == output:
            raise ValueError("raw path escape")
        return path.read_bytes()

    replay = assemble(manifest["requests"], read_record, manifest["traversal"], config)
    checks = {"manifest_identity": True, "raw_replay": True}
    for name, value in replay.items():
        filename = name + ".json"
        content = (output / filename).read_bytes()
        checks[filename + "_sha"] = sha(content) == manifest["files"][filename]
        checks[filename + "_replay"] = content == encode(value)
    if not all(checks.values()):
        raise ValueError("normalized identity/replay mismatch")
    return {"checks": checks, "passed": len(checks), "summary": replay["summary"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--manifest-sha")
    args = parser.parse_args()
    if args.audit:
        if not args.manifest_sha:
            parser.error("--audit requires --manifest-sha")
        result = audit(args.audit, args.seal_sha, args.manifest_sha)
    else:
        if not args.storage_root:
            parser.error("collection requires --storage-root")
        result = collect(args.storage_root, args.seal_sha)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
