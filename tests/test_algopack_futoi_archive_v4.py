"""Synthetic archive coverage, no HTTP credentials or economic outcomes."""

import gzip
import json
from pathlib import Path

import pytest
from test_algopack_futoi_archive_v2 import (
    DAY,
    pair,
    payload,
    windows_publication_adapter,  # noqa: F401 (pytest fixture)
)

from market_lab.futures import algopack_futoi_archive_v4 as m


def config():
    return {**m.base.read(m.REPO / f"configs/{m.PROTOCOL}.json"),
            "minimum_free_bytes": 0, "remaining_bytes": 10**9}


def test_empty_response_retained_not_fabricated():
    parsed, tail = m.parse(payload([]), DAY, "AA")
    assert parsed["rows"] == 0 and parsed["tickers"] == [] and tail == {}
    with pytest.raises(m.Error, match="missing_planned_ticker_day"):
        m.source.parse(payload([]), DAY, "AA")  # sealed parent remains strict


@pytest.mark.parametrize("raw,day,ticker,code", [
    (payload([]), "2026-01-01", "AA", "invalid_request_date"),
    (payload(pair("BB")), DAY, "AA", "wrong_ticker"),
    (payload([dict(row, tradedate="2026-01-05") for row in pair()]), DAY, "AA",
     "protected_or_wrong_date"),
    (payload(pair() + pair()), DAY, "AA", "duplicate_sequence_group"),
    (payload(pair() * 500), DAY, "AA", "possibly_truncated_1000_rows"),
    (payload([]), DAY, "../AA", "invalid_ticker"),
    (b'{"futoi":{"columns":[],"data":[]}}', DAY, "AA", "invalid_schema"),
    (b'{"wrong":{}}', DAY, "AA", "unexpected_blocks"),
], ids=["protected-request", "wrong-ticker", "protected-row", "duplicate-row", "row-cap",
        "unsafe-ticker", "invalid-schema", "wrong-block"])
def test_safety_guards_unchanged(raw, day, ticker, code):
    with pytest.raises(m.Error, match=code):
        m.parse(raw, day, ticker)


def test_global_final_point_and_unpaired_observations_retained():
    old = pair(seq=1, clock="11:55:00")[1:]
    last = pair(seq=2, clock="23:50:00")[:1]
    parsed, tail = m.parse(payload(old + last), DAY, "AA")
    assert parsed["rows"] == 2 and tail == m.parent.global_tail(payload(last), DAY, None)
    with pytest.raises(m.Error, match="daily_latest_not_single_point"):
        m.parse(payload(old + last), DAY, None)


@pytest.mark.parametrize("gap", ["empty", "tail", "schema"])
def test_day_continues_after_gap_preserves_raw_and_is_replayable(tmp_path, monkeypatch, gap):
    calls = []
    original = {}

    def fake_fetch(session, url, token, settings):
        calls.append(url)
        columns = m.source.COLUMNS
        if "latest=1" in url:
            rows = pair("AA") + pair("BB")
        elif "/bb.json" in url:
            rows = pair("BB")
        elif gap == "empty":
            rows = []
        elif gap == "tail":
            rows = [dict(row, pos=100) for row in pair()]
        else:
            columns = (*columns, "extra")
            rows = [dict(row, extra=None) for row in pair()]
        raw = payload(rows, columns)
        original[url] = raw
        return raw, {"http_status": 200, "retrieved_at_utc": "synthetic"}

    monkeypatch.setattr(m.base, "fetch", fake_fetch)
    first = m.collect_day(tmp_path, DAY, config(), None, "synthetic", {}, {"stored_bytes": 0})
    assert first["status"] == "WITH_SOURCE_GAPS"
    assert first["ticker_days"] == 2
    assert first["unresolved_ticker_days"] == first["resolved_ticker_days"] == 1
    doc = m.base.read(tmp_path / DAY[:4] / DAY / "manifest.json")
    assert doc["tickers"][0]["status"] == "UNRESOLVED_SOURCE_GAP"
    assert doc["tickers"][1]["status"] == "SOURCE_MATCHED"
    assert doc["economic_admission"] is False and len(calls) == 3
    page = doc["tickers"][0]["page"]
    assert gzip.decompress((tmp_path / page["path"] / "raw.json.gz").read_bytes()) == original[
        m.source.url_for(DAY, "AA")]

    def forbidden(*args, **kwargs):
        raise AssertionError("No re-download of committed empty/mismatched response")

    monkeypatch.setattr(m.base, "fetch", forbidden)
    second = m.collect_day(tmp_path, DAY, config(), None, "synthetic", {}, {"stored_bytes": 0})
    assert first == second


def test_empty_discovery_is_not_missing_ticker_day(tmp_path, monkeypatch):
    monkeypatch.setattr(m.base, "fetch", lambda *args: (payload([]), {"http_status": 200}))
    result = m.collect_day(tmp_path, DAY, config(), None, "synthetic", {}, {"stored_bytes": 0})
    assert result["status"] == "EMPTY" and result["ticker_days"] == 0
    assert result["unresolved_ticker_days"] == 0


def prior_fixture(tmp_path, monkeypatch):
    roots = [tmp_path / "v2", tmp_path / "v3"]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(m.base, "fetch", lambda *args: (payload(pair()), {"http_status": 200}))
    for root, ticker in zip(roots, [None, "AA"], strict=True):
        m.source.response(root, DAY, ticker, config(), None, "synthetic")
    priors = []
    for root in roots:
        item = {"prior_root": str(root)}
        for name in ("identity", "status"):
            m.base.write_new(root / f"{name}.json", {"synthetic": name})
            item[f"prior_{name}_sha256"] = m.base.sha((root / f"{name}.json").read_bytes())
        items = {str(p.relative_to(root)): m.base.sha(p.read_bytes())
                 for p in sorted(root.glob("*/*/*/page_000000000/page.json"))}
        item.update(prior_pages=len(items),
                    prior_inventory_sha256=m.base.sha(m.base.encoded(items)))
        priors.append(item)
    return roots, {**config(), "prior_archives": priors}


def test_two_prior_roots_reused_without_mutation_or_network(tmp_path, monkeypatch):
    roots, settings = prior_fixture(tmp_path, monkeypatch)
    inventory = m.prior_inventory(settings)
    current = tmp_path / "current"
    current.mkdir()
    before = {str(p): m.base.sha(p.read_bytes()) for root in roots
              for p in root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("Pinned prior response must not be downloaded")

    monkeypatch.setattr(m.base, "fetch", forbidden)
    result = m.collect_day(current, DAY, settings, None, "synthetic", inventory,
                           {"stored_bytes": 0})
    assert result["reused_pages"] == 2 and result["unresolved_ticker_days"] == 0
    assert result["stored_bytes"] == result["new_root_intraday_rows"] == 0
    assert not list(current.rglob("raw.json.gz"))
    after = {str(p): m.base.sha(p.read_bytes()) for root in roots
             for p in root.rglob("*") if p.is_file()}
    assert before == after
    doc = m.base.read(current / DAY[:4] / DAY / "manifest.json")
    assert doc["latest"]["source_root"] == str(roots[0])
    assert doc["tickers"][0]["page"]["source_root"] == str(roots[1])


@pytest.mark.parametrize("tamper", ["raw", "metadata", "status", "duplicate"])
def test_prior_tampering_and_duplicate_requests_rejected(tmp_path, monkeypatch, tamper):
    roots, settings = prior_fixture(tmp_path, monkeypatch)
    inventory = m.prior_inventory(settings)
    if tamper == "raw":
        next(roots[0].rglob("raw.json.gz")).write_bytes(b"tamper")
        with pytest.raises(m.Error, match="stored_page_changed"):
            m.source_response(tmp_path, DAY, None, settings, None, "synthetic", inventory)
    elif tamper == "metadata":
        next(roots[0].rglob("page.json")).write_bytes(b"tamper")
        with pytest.raises(m.Error, match="prior_page_changed"):
            m.source_response(tmp_path, DAY, None, settings, None, "synthetic", inventory)
    else:
        if tamper == "status":
            (roots[0] / "status.json").write_text("changed")
            code = "prior_archive_changed"
        else:
            settings["prior_archives"].append(settings["prior_archives"][0])
            code = "duplicate_prior_request"
        with pytest.raises(m.Error, match=code):
            m.prior_inventory(settings)


@pytest.mark.parametrize("gaps", [0, 1])
def test_final_all_attempted_not_equal_full_source_coverage(gaps):
    item = {"date": DAY, **dict.fromkeys(m.TOTALS, 0), "ticker_days": 1,
            "unresolved_ticker_days": gaps, "resolved_ticker_days": 1 - gaps}
    state = {**item, "planned_days": 1, "processed_days": 1}
    result = m.final_manifest(state, [item])
    assert result["status"] == ("COMPLETE_WITH_SOURCE_GAPS" if gaps else "COMPLETE")
    assert result["source_coverage_complete"] is (not gaps)
    assert result["economic_admission"] is result["live_trading_allowed"] is False
    with pytest.raises(m.Error, match="incomplete_plan"):
        m.final_manifest({**state, "planned_days": 2}, [item])
    with pytest.raises(m.Error, match="totals_mismatch"):
        m.final_manifest({**state, "intraday_rows": 999}, [item])


def test_bom_and_plan_scope():
    for name in (f"src/market_lab/futures/{m.PROTOCOL}.py", f"tests/test_{m.PROTOCOL}.py",
                 f"configs/{m.PROTOCOL}.json", "docs/ALGOPACK_FUTOI_ARCHIVE_V4.md"):
        assert (Path(m.REPO) / name).read_bytes().startswith(b"\xef\xbb\xbf")
    assert len(m.source.days(config())) == 2192
    assert json.loads(m.base.encoded(config()).decode("utf-8-sig"))["source_only"] is True
