"""Regression for the actual missing-row-open HTML class, not economic data."""

from test_steo_vintages_source_v1 import index

from market_lab.futures import steo_vintages_source_v3 as source


def test_missing_row_open_does_not_drop_2019_releases():
    raw = index()
    for name in (b"July", b"April", b"March"):
        raw = raw.replace(b"<tr><td>" + name + b" 2019", b"<td>" + name + b" 2019")
    fixed = source.archive_index(raw)
    assert fixed == source.parent.archive_index(index())
    assert len(fixed) == 97


def test_well_formed_index_is_unchanged():
    assert source.archive_index(index()) == source.parent.archive_index(index())
