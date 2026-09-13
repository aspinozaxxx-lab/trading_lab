"""The sole V2 correction is unknown midnight footer-time handling."""

import pandas as pd
import pytest

from market_lab.futures import cbr_policy_releases_source_v2 as source


def values(clock):
    record = {
        "publication_date": pd.Timestamp("2022-07-22"),
        "clock": "13:30",
        "headline": "Headline",
        "url": "https://www.cbr.ru/press/pr/?file=synthetic.htm",
    }
    raw = (
        '<h1>Headline</h1><div class="news-info-line_date">22 июля 2022 года</div>'
        '<div class="landing-text"><p>Synthetic policy text.</p></div>'
        f"<time>22.07.2022 {clock}</time>"
    ).encode()
    return raw, record


def test_date_only_footer_not_backdated_to_midnight():
    raw, record = values("00:00:00")
    row = source.parse_article(raw, record, "receipt")
    assert not row["footer_time_known"]
    assert row["footer_clock_text"] == "22.07.2022 00:00:00"
    assert row["published_at_utc"] == pd.Timestamp("2022-07-22T10:30:00Z")
    assert row["available_at_utc"] == pd.Timestamp("2022-07-22T20:59:59Z")
    assert record["clock"] == "13:30" and not row["original_version_verified"]


def test_exact_clock_preserved():
    raw, record = values("13:30:00")
    row = source.parse_article(raw, record, "receipt")
    assert row["footer_time_known"]
    assert row["published_at_utc"] == row["listing_published_at_utc"]


@pytest.mark.parametrize("fault", ["nonzero_disagreement", "different_date", "future"])
def test_other_identity_failures_are_not_weakened(fault):
    raw, record = values("00:00:00")
    if fault == "nonzero_disagreement":
        raw = raw.replace(b"00:00:00", b"13:31:00")
    elif fault == "different_date":
        raw = raw.replace(b"22.07.2022", b"21.07.2022")
    else:
        record["publication_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):
        source.parse_article(raw, record, "receipt")


def test_adapter_always_restores_parent():
    original = source.parent.parse_article
    with source.parser_adapter():
        assert source.parent.parse_article is source.parse_article
    assert source.parent.parse_article is original
