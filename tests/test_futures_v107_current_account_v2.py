"""One structural format correction only; frozen economics are byte-equivalent AST."""

import ast
import inspect

import pandas as pd
import pytest
from test_futures_v107_current_account import row, si_active, table

from market_lab import futures_v107_current_account as v1
from market_lab import futures_v107_current_account_v2 as v2


def compact():
    return (
        "Платежный баланс России\n2019 2020\nI II III IV I II III**\n"
        "Изменение\nв III кв. 2020 г.\nк III кв. 2019 г.***\n"
        "Счет текущих операций 33,5 9,9 10,7 11,2 22, 1 -0,5 2,5 -8,3\n"
        "ПЛАТЕЖНЫЙ БАЛАНС РОССИИ\n(МЛРД ДОЛЛ. США)*\nТабл. 1\n"
    )


def test_compact_current_not_rounded_difference_and_decimal_glyph_space():
    assert v2.parse_table(compact(), "2020Q3") == {
        "current_account_usd_bn": "2.5",
        "prior_year_same_quarter_usd_bn": "10.7",
    }
    assert v2.parse_table(compact().replace("-8,3", "100,0"), "2020Q3") == v2.parse_table(
        compact(), "2020Q3"
    )


@pytest.mark.parametrize("change", ["unit", "year", "quarter", "missing", "headers"])
def test_compact_header_and_numeric_failures(change):
    text = compact()
    old, new = {
        "unit": ("МЛРД", "МЛН"),
        "year": ("к III кв. 2019", "к III кв. 2018"),
        "quarter": ("в III кв.", "в II кв."),
        "missing": ("2,5 -8,3", "- -8,3"),
        "headers": ("I II III IV I II III**", "I II III IV I III II**"),
    }[change]
    with pytest.raises(ValueError):
        v2.parse_table(text.replace(old, new), "2020Q3")


def test_annual_layout_unchanged():
    for q, three in [("2021Q1", False), ("2021Q4", False), ("2025Q3", True)]:
        assert v2.parse_table(table(q, three), q) == v1.parse_table(table(q, three), q)


def test_every_nonparser_function_and_all_economic_parameters_unchanged():
    for name in [
        "normalize",
        "select",
        "parse_pdf",
        "states",
        "targets",
        "probe",
        "collect",
        "verify_source",
        "load",
        "run",
        "main",
    ]:
        assert ast.dump(ast.parse(inspect.getsource(getattr(v1, name)))) == ast.dump(
            ast.parse(inspect.getsource(getattr(v2, name)))
        )
    a, b = v1.prior.read_json(v1.CONFIG), v2.prior.read_json(v2.CONFIG)
    for key in set(a) - {"protocol_id", "source", "limitations"}:
        assert a[key] == b[key]
    for key in set(a["source"]) - {
        "probe_path",
        "probe_manifest_sha256",
        "source_parent",
        "reuse",
        "new_http_requests",
    }:
        assert a["source"][key] == b["source"][key]
    state = v1.states([row()])
    pd.testing.assert_frame_equal(state, v2.states([row()]))
    plan = si_active(pd.bdate_range("2021-04-14", "2021-04-23"))
    for arm in ("primary", "control"):
        pd.testing.assert_frame_equal(
            v1.targets(plan, state, a)[arm], v2.targets(plan, state, a)[arm]
        )
