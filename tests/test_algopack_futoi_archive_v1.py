"""Synthetic only; no HTTP, credentials, historical prices or market outcomes."""

import gzip
import json
from pathlib import Path

import pytest

from market_lab.futures import algopack_futoi_archive_v1 as m

DAY = "2024-10-15"


@pytest.fixture(autouse=True)
def windows_publication_adapter(monkeypatch):
    # POSIX directory fsync is tested unmodified on the authoritative Linux server.
    if m.os.name == "posix":
        return

    def save(parent, index, raw, meta):
        destination = parent / f"page_{index:09d}"
        destination.mkdir()
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        (destination / "raw.json.gz").write_bytes(compressed)
        m.base.write_new(destination / "page.json", {
            **meta, "raw_sha256": m.base.sha(raw), "raw_bytes": len(raw),
            "compressed_sha256": m.base.sha(compressed), "compressed_bytes": len(compressed),
        })

    monkeypatch.setattr(m.base, "page_save", save)


def pair(ticker="AA", seq=2, clock="18:45:00"):
    return [dict(zip(m.COLUMNS, [1, seq, DAY, clock, ticker, group, sign * 2,
                                10 + sign, sign * 2 - 10 - sign, 3, 4,
                                "2026-09-01 00:00:00"], strict=True))
            for group, sign in (("FIZ", 1), ("YUR", -1))]


def payload(rows, columns=m.COLUMNS):
    return m.base.encoded({"futoi": {"columns": list(columns),
                                     "data": [[row[c] for c in columns] for row in rows]}})


def config():
    return m.base.read(m.REPO / f"configs/{m.PROTOCOL}.json")


def test_dates_and_routes():
    plan = m.days(config())
    assert len(plan) == len(set(plan)) == 2192
    assert plan[:3] == [DAY, "2020-05-04", "2025-12-30"]
    assert min(plan) == "2020-01-01" and max(plan) == "2025-12-31"
    assert "date=2024-10-15&latest=1" in m.url_for(DAY)
    url = m.url_for(DAY, "USDRUBF")
    assert "/usdrubf.json?from=2024-10-15&till=2024-10-15" in url
    assert "start=" not in url and "latest=" not in url and "columns=" not in url


@pytest.mark.parametrize("day", ["2026-01-01", "2019-12-31", "2025-1-1", "bad"])
def test_protected_dates(day):
    with pytest.raises(ValueError):
        m.url_for(day)


@pytest.mark.parametrize("ticker", ["", "../Si", "A/B", "a?b", "a%2fb", " A", "АА"])
def test_path_filter(ticker):
    with pytest.raises(m.Error, match="invalid_ticker"):
        m.url_for(DAY, ticker)


def test_latest_schema_and_no_value_projection():
    rows = pair() + pair("BB")
    for row in rows:
        row["new_field"] = None
    parsed, latest = m.parse(payload(rows, (*m.COLUMNS, "new_field")), DAY)
    assert parsed["tickers"] == ["AA", "BB"]
    assert parsed["rows"] == 4
    assert "new_field" in latest["AA"][0]


def test_empty_discovery_not_intraday():
    parsed, _ = m.parse(payload([]), DAY)
    assert parsed["rows"] == 0 and parsed["tickers"] == []
    with pytest.raises(m.Error, match="missing_planned"):
        m.parse(payload([]), DAY, "AA")


def test_sequences_keep_repeated_wall_clock():
    rows = pair(seq=1) + pair(seq=2)
    parsed, latest = m.parse(payload(rows), DAY, "AA")
    assert parsed["paired_points_by_ticker"] == {"AA": 2}
    assert latest["AA"][0]["seqnum"] == 2
    with pytest.raises(m.Error, match="daily_latest_not_unique"):
        m.parse(payload(rows), DAY)


@pytest.mark.parametrize("mutation,code", [
    (lambda rows: rows + rows, "duplicate_sequence"),
    (lambda rows: rows[:1], "unpaired_sequence"),
    (lambda rows: [dict(row, tradedate="2026-01-01") for row in rows], "wrong_date"),
    (lambda rows: [dict(row, ticker=None) for row in rows], "invalid_ticker"),
    (lambda rows: [dict(row, tradetime="25:00:00") for row in rows], "invalid_sequence"),
    (lambda rows: [dict(row, seqnum=True) for row in rows], "invalid_sequence"),
    (lambda rows: [dict(row, clgroup="OTHER") for row in rows], "invalid_sequence"),
])
def test_bad_rows(mutation, code):
    with pytest.raises(m.Error, match=code):
        m.parse(payload(mutation(pair())), DAY, "AA")


def test_wrong_ticker_and_cap():
    with pytest.raises(m.Error, match="wrong_ticker"):
        m.parse(payload(pair()), DAY, "BB")
    with pytest.raises(m.Error, match="possibly_truncated"):
        m.parse(payload(pair() * 500), DAY)


def test_invalid_json_schema_and_width():
    cases = [b'{"futoi":{},"futoi":{}}', b'{}', b'not-json',
             payload(pair(), m.COLUMNS[:-1])]
    for raw in cases:
        with pytest.raises(m.Error):
            m.parse(raw, DAY)
    raw = json.loads(payload(pair()).decode("utf-8-sig"))
    raw["futoi"]["data"][0].append(0)
    with pytest.raises(m.Error, match="row_width"):
        m.parse(m.base.encoded(raw), DAY)


def test_systime_excluded_but_values_and_sequence_not_excluded():
    original = pair()
    assert m.stable_sha(original) == m.stable_sha([
        dict(row, systime="different") for row in reversed(original)])
    assert m.stable_sha(original) != m.stable_sha([dict(row, pos=55) for row in original])
    assert m.stable_sha(original) != m.stable_sha(pair(seq=3))


def setup_fetch(monkeypatch, rows):
    calls = []

    def fetch(session, url, token, settings):
        calls.append(url)
        return payload(rows), {"http_status": 200, "retrieved_at_utc": "2026-09-15T00:00:00Z"}

    monkeypatch.setattr(m.base, "fetch", fetch)
    return calls


def test_response_replay_no_http_and_tamper_rejected(tmp_path, monkeypatch):
    calls = setup_fetch(monkeypatch, pair())
    settings = {**config(), "minimum_free_bytes": 0, "remaining_bytes": 10**9}
    first = m.response(tmp_path, DAY, None, settings, None, "synthetic")
    second = m.response(tmp_path, DAY, None, settings, None, "synthetic")
    assert first == second and len(calls) == 1
    p = tmp_path / first["path"] / "raw.json.gz"
    p.write_bytes(p.read_bytes() + b"tampered")
    with pytest.raises(m.Error, match="stored_page_changed"):
        m.response(tmp_path, DAY, None, settings, None, "synthetic")
    assert len(calls) == 1


@pytest.mark.parametrize("reuse", [True, False])
def test_day_reuse_or_new_vintage_and_resume(tmp_path, monkeypatch, reuse):
    calls = setup_fetch(monkeypatch, pair())
    settings = {**config(), "minimum_free_bytes": 0}
    counts = {(DAY, "AA"): 348}
    proofs = {(DAY, "AA"): m.stable_sha(pair()) if reuse else "different-vintage"}
    state = {"stored_bytes": 0}
    first = m.collect_day(tmp_path, DAY, settings, None, "synthetic", counts, proofs, state)
    assert first["reused_ticker_days"] == int(reuse)
    assert first["downloaded_intraday_rows"] == (0 if reuse else 2)
    assert len(calls) == (1 if reuse else 2)
    second = m.collect_day(tmp_path, DAY, settings, None, "synthetic", counts, proofs, state)
    assert first == second and len(calls) == (1 if reuse else 2)


def test_latest_mismatch_stops_without_day_manifest(tmp_path, monkeypatch):
    def fetch(session, url, token, settings):
        return payload(pair(seq=2 if "latest=1" in url else 1)), {"http_status": 200}

    monkeypatch.setattr(m.base, "fetch", fetch)
    with pytest.raises(m.Error, match="intraday_daily_latest_mismatch"):
        m.collect_day(tmp_path, DAY, {**config(), "minimum_free_bytes": 0},
                      None, "synthetic", {}, {}, {"stored_bytes": 0})
    assert not (tmp_path / DAY[:4] / DAY / "manifest.json").exists()


def test_disk_reserve_before_http(tmp_path, monkeypatch):
    calls = setup_fetch(monkeypatch, pair())
    with pytest.raises(m.Error, match="disk_reserve"):
        m.response(tmp_path, DAY, None, {**config(), "minimum_free_bytes": 10**30,
                                        "remaining_bytes": 10**9}, None, "synthetic")
    assert not calls


def test_archive_ceiling_before_http(tmp_path, monkeypatch):
    calls = setup_fetch(monkeypatch, pair())
    with pytest.raises(m.Error, match="archive_size_ceiling"):
        m.response(tmp_path, DAY, None, {**config(), "minimum_free_bytes": 0,
                                        "remaining_bytes": 1}, None, "synthetic")
    assert not calls


def test_bom_new_authored_files():
    for relative in (f"src/market_lab/futures/{m.PROTOCOL}.py",
                     f"tests/test_{m.PROTOCOL}.py", f"configs/{m.PROTOCOL}.json",
                     "docs/ALGOPACK_FUTOI_ARCHIVE_V1.md"):
        assert (Path(m.REPO) / relative).read_bytes().startswith(b"\xef\xbb\xbf")
