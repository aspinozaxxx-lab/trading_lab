"""Synthetic ZIP/XML and archive metadata only, no market values."""

import io
from zipfile import ZipFile

import pytest

from market_lab.futures import steo_vintages_source_v1 as source


def index(extra=""):
    rows = []
    for edition in source.plan():
        y, m = int(edition[:4]), int(edition[4:])
        month = source.MONTHS[m - 1]
        name = month[:3].lower() + edition[2:4] + "_base.xlsx"
        rows.append(f'<tr><td>{month} {y}</td><td>{m}/09/{y}</td>'
                    f'<td><a href="archives/{name}">data</a></td></tr>')
    return ("<table>" + "".join(rows) + extra + "</table>").encode()


def test_exact97_sorted_plan_and_safe_2026_skip():
    extra = '<tr><td>January 2026</td><a href="jan26_base.xlsx">data</a></tr>'
    got = source.archive_index(index(extra))
    assert len(got) == 97 and [x["edition"] for x in got] == source.plan()
    assert all(x["url"].startswith(source.BASE) for x in got)
    assert all(x["release_date"] < "2026-01-01" for x in got)


@pytest.mark.parametrize("old,new", [
    (b"1/09/2024", b"2/09/2024"), (b"jan24_base.xlsx", b"jan26_base.xlsx"),
    (b"January 2024", b"Unknown 2024"),
])
def test_incomplete_or_mislabeled_index_rejected(old, new):
    with pytest.raises(ValueError):
        source.archive_index(index().replace(old, new))


def xlsx(edition="202401", code="papr_world", malicious_value="never-read"):
    ns = source.NS["s"]
    raw = io.BytesIO()
    with ZipFile(raw, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="' + ns + '" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="3atab" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" '
                   'Target="worksheets/sheet1.xml"/></Relationships>')
        strings = [source.MONTHS[int(edition[4:]) - 1] + " " + edition[:4], code, "patc_world"]
        z.writestr("xl/sharedStrings.xml", "<sst>" + "".join(
            "<si><t>" + s + "</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>'
                   '<row r="2"><c r="B2" t="s"><v>0</v></c></row>'
                   '<row r="18"><c r="A18" t="s"><v>1</v></c>'
                   f'<c r="C18"><v>{malicious_value}</v></c></row>'
                   '<row r="36"><c r="A36" t="s"><v>2</v></c></row>'
                   '</sheetData></worksheet>')
        z.writestr("docProps/core.xml", '<properties><modified>2024-01-05T12:00:00Z</modified>'
                   '</properties>')
    return raw.getvalue()


def test_metadata_does_not_read_numeric_cell():
    meta, _ = source.workbook(xlsx(), "202401")
    assert not meta["economic_values_read"]
    assert meta["series_rows"] == {"papr_world": [18], "patc_world": [36]}
    assert "never-read" not in str(meta)


def test_vintage_heading_is_required_not_just_filename():
    with pytest.raises(ValueError, match="heading"):
        source.workbook(xlsx("202501"), "202401")


def test_price_series_cannot_replace_physical_series():
    with pytest.raises(ValueError, match="series"):
        source.workbook(xlsx(code="brent_spot_price"), "202401")


def test_html_not_treated_as_excel():
    with pytest.raises(ValueError, match="XLSX"):
        source.workbook(b"<html>not xlsx</html>", "202401")
