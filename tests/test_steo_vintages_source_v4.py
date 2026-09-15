"""Repeated physical-series codes stay explicit; numeric cells remain unread."""

import io
from zipfile import ZipFile

import pytest
from test_steo_vintages_source_v1 import xlsx

from market_lab.futures import steo_vintages_source_v4 as source


def duplicates(count):
    original = ZipFile(io.BytesIO(xlsx()))
    out = io.BytesIO()
    with ZipFile(out, "w") as target:
        for name in original.namelist():
            raw = original.read(name)
            if name.endswith("sheet1.xml"):
                rows = "".join(f'<row r="{r}"><c r="A{r}" t="s"><v>1</v></c>'
                               f'<c r="C{r}"><v>not-evaluated</v></c></row>'
                               for r in range(6, 6 + count))
                raw = raw.replace(b"</sheetData>", rows.encode() + b"</sheetData>")
            target.writestr(name, raw)
    return out.getvalue()


def test_duplicate_world_production_is_preserved_not_chosen():
    metadata, _ = source.workbook(duplicates(1), "202401")
    assert sorted(metadata["series_rows"]["papr_world"]) == [6, 18]
    assert not metadata["economic_values_read"] and "not-evaluated" not in str(metadata)


def test_three_occurrences_remain_ambiguous():
    with pytest.raises(ValueError, match="identity"):
        source.workbook(duplicates(2), "202401")
