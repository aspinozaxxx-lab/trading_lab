"""Synthetic regression for final-point semantics and no-network raw reuse."""

import json
from pathlib import Path

import pytest
from test_algopack_futoi_archive_v2 import (
    DAY,
    pair,
    payload,
    windows_publication_adapter,  # noqa: F401 (pytest fixture)
)

from market_lab.futures import algopack_futoi_archive_v3 as m


def config():
    return m.base.read(m.REPO / f"configs/{m.PROTOCOL}.json")


def test_final_common_point_excludes_old_group_only_from_proof():
    old = pair(seq=1, clock="11:55:00")[1:]
    last = pair(seq=2, clock="23:50:00")[:1]
    raw = payload(old + last)
    proof = m.global_tail(payload(last), DAY, None)
    assert m.global_tail(raw, DAY, "AA") == proof
    assert m.parent.parse(raw, DAY, "AA")[0]["rows"] == 2
    assert m.parent.stable_sha(old + last) != proof["AA"]


def test_complete_pair_and_metadata_session_label_preserved():
    rows = [dict(row, trade_session_date="2026-01-05") for row in pair()]
    raw = payload(rows, (*m.parent.COLUMNS, "trade_session_date"))
    assert m.global_tail(raw, DAY, None) == m.global_tail(raw, DAY, "AA")
    assert b"2026-01-05" in raw


def test_protected_actual_date_not_admitted():
    raw = payload([dict(row, tradedate="2026-01-05") for row in pair()])
    with pytest.raises(m.Error, match="protected_or_wrong_date"):
        m.global_tail(raw, DAY, "AA")


def test_discovery_must_be_one_point_not_last_per_group():
    with pytest.raises(m.Error, match="daily_latest_not_single_point"):
        m.global_tail(payload(pair(seq=1)[:1] + pair(seq=2)[1:]), DAY, None)


def test_genuine_last_value_difference_detected():
    original = m.global_tail(payload(pair()), DAY, None)
    changed = m.global_tail(payload([dict(row, pos=999) for row in pair()]), DAY, "AA")
    assert original != changed


def make_prior(tmp_path, monkeypatch):
    prior, current = tmp_path / "prior", tmp_path / "current"
    prior.mkdir()
    current.mkdir()
    last = pair(seq=2, clock="23:50:00")[:1]

    def fake_fetch(session, url, token, settings):
        rows = last if "latest=1" in url else pair(seq=1, clock="11:55:00")[1:] + last
        return payload(rows), {"http_status": 200}

    monkeypatch.setattr(m.base, "fetch", fake_fetch)
    settings = {**config(), "minimum_free_bytes": 0, "remaining_bytes": 10**9,
                "prior_root": str(prior)}
    for ticker in (None, "AA"):
        m.parent.response(prior, DAY, ticker, settings, None, "synthetic")
    inventory = {str(p.relative_to(prior)): m.base.sha(p.read_bytes())
                 for p in prior.glob("*/*/*/page_000000000/page.json")}

    def forbidden(*args, **kwargs):
        raise AssertionError("committed prior response must not be downloaded")

    monkeypatch.setattr(m.base, "fetch", forbidden)
    return prior, current, settings, inventory


def test_reuse_prior_pages_without_copy_network_or_mutation(tmp_path, monkeypatch):
    prior, current, settings, inventory = make_prior(tmp_path, monkeypatch)
    before = {str(p): m.base.sha(p.read_bytes()) for p in prior.rglob("*") if p.is_file()}
    state = {"stored_bytes": 0}
    first = m.collect_day(current, DAY, settings, None, "synthetic", inventory, {}, {}, state)
    second = m.collect_day(current, DAY, settings, None, "synthetic", inventory, {}, {}, state)
    assert first == second
    assert first["intraday_rows"] == 2 and first["reused_v2_pages"] == 2
    assert first["stored_bytes"] == first["new_root_intraday_rows"] == 0
    assert not list(current.rglob("raw.json.gz"))
    after = {str(p): m.base.sha(p.read_bytes()) for p in prior.rglob("*") if p.is_file()}
    assert before == after
    doc = m.base.read(current / DAY[:4] / DAY / "manifest.json")
    assert doc["tickers"][0]["page"]["source_root"] == str(prior)


def test_prior_tamper_rejected(tmp_path, monkeypatch):
    prior, current, settings, inventory = make_prior(tmp_path, monkeypatch)
    p = next(prior.rglob("raw.json.gz"))
    p.write_bytes(b"tamper")
    with pytest.raises(m.Error, match="stored_page_changed"):
        m.source_response(current, DAY, None, settings, None, "synthetic", inventory)


def test_inventory_checks_metadata_and_checkpoint(tmp_path, monkeypatch):
    prior, _, settings, inventory = make_prior(tmp_path, monkeypatch)
    for name in ("identity", "status"):
        m.base.write_new(prior / f"{name}.json", {"synthetic": name})
        settings[f"prior_{name}_sha256"] = m.base.sha((prior / f"{name}.json").read_bytes())
    settings["prior_pages"] = len(inventory)
    settings["prior_inventory_sha256"] = m.base.sha(m.base.encoded(inventory))
    assert m.prior_inventory(settings) == inventory
    (prior / "status.json").write_text(json.dumps({"changed": True}), encoding="utf-8-sig")
    with pytest.raises(m.Error, match="prior_archive_changed"):
        m.prior_inventory(settings)


def test_bom():
    for name in (f"src/market_lab/futures/{m.PROTOCOL}.py", f"tests/test_{m.PROTOCOL}.py",
                 f"configs/{m.PROTOCOL}.json", "docs/ALGOPACK_FUTOI_ARCHIVE_V3.md"):
        assert (Path(m.REPO) / name).read_bytes().startswith(b"\xef\xbb\xbf")
