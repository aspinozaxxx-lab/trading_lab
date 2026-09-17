"""Identity-only correction must not change forecasts, clocks or economics."""

import copy

import pandas as pd
import pytest
from test_futures_v105_survey_dispersion import config, fixture

from market_lab import futures_v105_survey_dispersion_v2 as corrected


def correction():
    return corrected.original.prior.read_json(corrected.CONFIG)


def test_only_protocol_id_and_declared_source_url_change():
    parent = config()
    unchanged = copy.deepcopy(parent)
    cfg = corrected.corrected_config(correction(), parent)
    assert parent == unchanged
    cfg["protocol_id"] = parent["protocol_id"]
    cfg["source"]["source_url"] = parent["source"]["source_url"]
    assert cfg == parent


def test_source_identity_change_preserves_all_economic_states():
    raw, calendar = fixture()
    expected = corrected.original.states(raw, calendar, config())
    cfg = corrected.corrected_config(correction(), config())
    raw["source_url"] = cfg["source"]["source_url"]
    assert corrected.metadata_identity(raw.drop(columns="value"), cfg)
    actual = corrected.original.states(raw, calendar, cfg)
    pd.testing.assert_frame_equal(
        actual.drop(columns=["source_url", "provider_url"]),
        expected.drop(columns=["source_url", "provider_url"]),
    )


@pytest.mark.parametrize(
    "column,value", [("source_url", "bad"), ("unit", "bad"), ("current_vintage", False)]
)
def test_metadata_checks_identity_before_numeric_read(column, value):
    raw, _ = fixture()
    cfg = corrected.corrected_config(correction(), config())
    meta = raw.drop(columns="value").assign(source_url=cfg["source"]["source_url"])
    meta.loc[0, column] = value
    with pytest.raises(ValueError, match="metadata source identity"):
        corrected.metadata_identity(meta, cfg)


def test_unknown_replacement_url_is_not_permitted():
    c = correction()
    c["source_url"] = "https://example.org/other.xlsx"
    with pytest.raises(ValueError, match="undeclared correction"):
        corrected.corrected_config(c, config())
