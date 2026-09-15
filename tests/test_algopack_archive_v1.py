import gzip
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from market_lab.futures import algopack_archive_v1 as mod


def payload(start=0, total=2, size=1, day="2024-10-15", values=None):
    rows = [[day, "SYNTH", 1.25, None]] if start < total else []
    return json.dumps({
        "data": {"columns": ["tradedate", "secid", "price", "depth"],
                 "data": rows if values is None else values},
        "data.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"],
                        "data": [[start, total, size]]},
    }).encode()


def config():
    return mod.read(Path(mod.REPO) / mod.CONFIG)


@pytest.mark.parametrize("dataset", mod.DATASETS)
def test_date_bounded_all_fields(dataset):
    parsed = urlparse(mod.url_for(dataset, "2024-10-15", 1000))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.netloc == "apim.moex.com"
    assert query["date"] == ["2024-10-15"] and query["latest"] == ["0"]
    assert "data.columns" not in query


@pytest.mark.parametrize("day", ["2019-12-31", "2026-01-01", "2026-09-15"])
def test_protected_request(day):
    with pytest.raises(ValueError):
        mod.url_for("eq/obstats", day, 0)


def test_plan_all_calendar_days_no_duplicate():
    plan = mod.jobs(config())
    assert len(plan) == len(set(plan))
    assert len(plan) == 11 * 2192 + 3 * 731
    assert plan[0] == ("eq/tradestats", "2024-10-15")
    assert ("eq/obstats", "2020-01-04") in plan
    assert ("eq/alerts", "2023-12-31") not in plan


def test_parse_and_empty():
    assert mod.parse(payload(), "2024-10-15", 0)["rows"] == 1
    assert mod.parse(payload(total=0), "2024-10-15", 0)["total"] == 0


@pytest.mark.parametrize("raw", [
    payload(day="2026-01-01"), payload(day="2024-10-16"),
    payload(start=1), payload(total=2, size=2), payload(values=[["2024-10-15"]]),
    b'{"data":{},"data":{},"data.cursor":{}}', b"not json",
])
def test_bad_page_rejected(raw):
    with pytest.raises(ValueError):
        mod.parse(raw, "2024-10-15", 0)


def test_resume_never_redownload_committed_pages(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(session, url, token, settings):
        index = int(parse_qs(urlparse(url).query)["start"][0])
        calls.append(index)
        return payload(start=index), {"http_status": 200}

    monkeypatch.setattr(mod, "fetch", fake_fetch)
    monkeypatch.setattr(mod.os, "open", mod.os.open)
    settings = {**config(), "minimum_free_bytes": 0}
    # Directory fsync is POSIX-only; Windows tests use the ordinary file publication path.
    original_save = mod.page_save
    if mod.os.name != "posix":
        def save(parent, index, raw, meta):
            destination = parent / f"page_{index:09d}"
            destination.mkdir()
            compressed = gzip.compress(raw, mtime=0)
            (destination / "raw.json.gz").write_bytes(compressed)
            mod.write_new(destination / "page.json", {
                **meta, "raw_sha256": mod.sha(raw), "raw_bytes": len(raw),
                "compressed_sha256": mod.sha(compressed), "compressed_bytes": len(compressed),
            })
        monkeypatch.setattr(mod, "page_save", save)
    else:
        assert original_save is mod.page_save
    first = mod.collect_job(tmp_path, "eq/obstats", "2024-10-15", settings, None, "synthetic")
    again = mod.collect_job(tmp_path, "eq/obstats", "2024-10-15", settings, None, "synthetic")
    assert calls == [0, 1] and first["rows"] == 2 and again["reused_pages"] == 2
    raw_path = tmp_path / "eq_obstats/2024/2024-10-15/page_000000000/raw.json.gz"
    raw_path.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        mod.collect_job(tmp_path, "eq/obstats", "2024-10-15", settings, None, "synthetic")
    assert calls == [0, 1]


class Response:
    status_code = 200

    def __init__(self, url, body):
        self.url, self.body = url, body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body


@pytest.mark.parametrize("body,limit", [(b"synthetic-secret", 1000), (b"Bearer x", 1000),
                                      (b"abcd", 3)])
def test_fetch_safety(body, limit, monkeypatch):
    class Session:
        def get(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            assert kwargs["headers"]["Authorization"] == "Bearer synthetic-secret"
            return Response(url, body)
    monkeypatch.setattr(mod.time, "sleep", lambda value: None)
    with pytest.raises(mod.ArchiveError):
        mod.fetch(Session(), mod.url_for("eq/obstats", "2024-10-15", 0),
                  "synthetic-secret", {**config(), "maximum_response_bytes": limit})
