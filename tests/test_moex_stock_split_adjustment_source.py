"""Tests for the official stock split/consolidation adjustment source."""

from __future__ import annotations

from market_lab.futures import moex_stock_split_adjustment_source as source


def test_protocol_and_affected_contract_identity_are_exact() -> None:
    protocol = source.load_protocol()
    affected = source._adjusted_contracts(protocol)

    assert tuple(event["stock_secid"] for event in protocol["events"]) == source.EXPECTED_STOCKS
    assert len(affected) == 27
    assert not affected["contract_id"].duplicated().any()
    assert affected["back_adjusted_spot_units"].gt(0).all()


def test_html_text_extraction_decodes_entities_and_whitespace() -> None:
    raw = "<html><body>Лот&nbsp; 100 <b>акций</b></body></html>".encode()

    assert source._extract_text(raw) == "Лот 100 акций"
