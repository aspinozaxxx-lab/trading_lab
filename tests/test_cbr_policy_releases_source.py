"""Synthetic source-only CBR archive/identity/clock tests."""

import pandas as pd
import pytest

from market_lab.futures import cbr_policy_releases_source as source


def listing(day="25 октября 2024 г.", clock="13:30"):
    return (
        '<div class="previews_day" data-cross-ajax-url="/Crosscut/NewsList/LoadMore/84035'
        '?intOffset=0&amp;extOffset=10">'
        f'<div class="previews_day-date">{day}</div>'
        f'<div class="previews_item-time">{clock}</div>'
        '<div class="previews_item-title"><a href="/press/pr/?file=example.htm">'
        "Банк России сохранил ставку</a></div></div>"
    ).encode()


def article():
    return (
        "<h1>Банк России сохранил ставку</h1>"
        '<div class="news-info-line_date">25 октября 2024 года</div>'
        '<div>MENU NOT BODY</div><div class="landing-text">'
        "<p>Первый <b>абзац</b>.</p><div><p>Второй абзац.</p>"
        "<script>IGNORE()</script></div></div><p>NOT BODY</p>"
        "<time>25.10.2024 13:30:00</time>"
    ).encode()


def test_dated_listing_and_continuation():
    rows, following = source.parse_listing(listing())
    assert rows[0]["publication_date"] == pd.Timestamp("2024-10-25")
    assert following.endswith("intOffset=0&extOffset=10")
    assert rows[0]["url"] == "https://www.cbr.ru/press/pr/?file=example.htm"


def test_body_scope_and_bound_publication_clock():
    record = source.parse_listing(listing())[0][0]
    row = source.parse_article(article(), record, "2026-09-13T00:00:00Z")
    assert row["paragraphs"] == ["Первый абзац.", "Второй абзац."]
    assert row["published_at_utc"] == pd.Timestamp("2024-10-25T10:30:00Z")
    assert row["available_at_utc"] == pd.Timestamp("2024-10-25T20:59:59Z")
    assert not row["original_version_verified"]


@pytest.mark.parametrize(
    "fault", ["date", "clock", "headline", "body", "ambiguous_clock", "future"]
)
def test_article_mismatch_fails_closed(fault):
    record = source.parse_listing(listing())[0][0]
    raw = article()
    if fault == "date":
        raw = raw.replace("25 октября".encode(), "24 октября".encode())
    elif fault == "clock":
        raw = raw.replace(b"13:30:00", b"13:31:00")
    elif fault == "headline":
        record["headline"] = "Другая новость"
    elif fault == "body":
        raw = raw.replace(b"landing-text", b"unrelated")
    elif fault == "ambiguous_clock":
        raw += b"25.10.2024 14:00:00"
    else:
        record["publication_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):
        source.parse_article(raw, record, "receipt")


@pytest.mark.parametrize(
    "raw",
    [
        b"<html>denied</html>",
        listing(clock="unknown"),
        listing().replace(b"/press/pr/", b"/unexpected/"),
    ],
)
def test_invalid_listing_fails_closed(raw):
    with pytest.raises(ValueError):
        source.parse_listing(raw)


def test_hidden_nested_content_and_entities():
    parser = source.Article()
    parser.feed(
        '<div class="landing-text"><p>A&nbsp;&amp; B</p><style>not evidence</style>'
        "<div><p>C</p></div></div>outside"
    )
    assert parser.paragraphs == ["A & B", "C"]
