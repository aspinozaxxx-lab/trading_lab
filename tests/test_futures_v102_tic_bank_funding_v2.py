"""Synthetic exact-byte correction tests; never use historical prices."""

import copy
import hashlib

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active
from test_futures_v102_tic_bank_funding import release, source_text

from market_lab import futures_v102_tic_bank_funding_v2 as screen


def test_only_output_identity_and_source_location_change():
    parent = screen.original.read_json(screen.original.CONFIG)
    actual = copy.deepcopy(screen.config())
    actual["protocol_id"] = parent["protocol_id"]
    actual["source"]["source_parent"] = parent["source"]["source_parent"]
    actual["source"].pop("failed_source")
    assert actual == parent


def test_exact_synthetic_header_correction_not_numbers_or_latest_column(monkeypatch):
    raw = source_text("2019-06-17","2019-04","-12.5").replace(b"Apr-18",b"Apr-19")
    with pytest.raises(ValueError,match="unrecognized"):
        screen.parse_release(raw,"20190617","synthetic")
    monkeypatch.setattr(screen,"TYPO_SHA",hashlib.sha256(raw).hexdigest())
    row = screen.parse_release(raw,"20190617","synthetic")
    assert row["unused_prior_rolling_header_corrected"]
    assert row["bank_flow_billion_usd"] == -12.5 and row["observation_month"] == "2019-04"
    assert raw.count(b"Apr-19") == 2
    changed = raw.replace(b"Jan",b"Dec")
    monkeypatch.setattr(screen,"TYPO_SHA",hashlib.sha256(changed).hexdigest())
    with pytest.raises(ValueError,match="header drift"):
        screen.parse_release(changed,"20190617","synthetic")


def test_other_releases_and_targets_are_identical():
    original = release()
    parsed = screen.parse_release(source_text(),"20200716","synthetic")
    assert not parsed.pop("unused_prior_rolling_header_corrected")
    assert parsed == original
    state = screen.original.states([original])
    plan = active(pd.bdate_range("2020-07-14","2020-07-29"))
    a = screen.original.targets(plan,state,screen.original.read_json(screen.original.CONFIG))
    b = screen.original.targets(plan,state,screen.config())
    for arm in a:
        pd.testing.assert_frame_equal(a[arm],b[arm])


def test_typo_in_other_date_not_accepted():
    raw = source_text("2019-06-18","2019-04").replace(b"Apr-18",b"Apr-19")
    with pytest.raises(ValueError,match="rolling year"):
        screen.parse_release(raw,"20190618","synthetic")
