"""Synthetic outside-heading layout; frozen economics remain identical."""

import copy

import pytest
from test_futures_v102_tic_bank_funding import source_text

from market_lab import futures_v102_tic_bank_funding_v3 as screen


def outside_text():
    raw = source_text()
    start = raw.index(b'<table>')
    end = raw.index(b'</tr>',raw.index(b'not seasonally adjusted')) + len(b'</tr>')
    headings = (f'<h3>{screen.original.TITLE}</h3>'
                '<p>(Billions of dollars, not seasonally adjusted)</p><table>').encode()
    return raw[:start] + headings + raw[end:]


def test_outside_and_inside_same_numerical_release():
    inside = screen.parse_release(source_text(),'20200716','synthetic')
    outside = screen.parse_release(outside_text(),'20200716','synthetic')
    assert not inside.pop('headings_outside_table') and outside.pop('headings_outside_table')
    assert inside == outside


@pytest.mark.parametrize('mutation',[
    lambda b:b.replace(b'Billions',b'Millions'),
    lambda b:b.replace(b'not seasonally adjusted',b'seasonally adjusted'),
    lambda b:b+b'<table></table>',
    lambda b:b.replace(b'>29<',b'>28<'),
])
def test_ambiguous_outside_metadata_rejected(mutation):
    with pytest.raises(ValueError):
        screen.parse_release(mutation(outside_text()),'20200716','synthetic')


def test_economic_configuration_identical_to_v1():
    parent=screen.original.read_json(screen.original.CONFIG)
    actual=copy.deepcopy(screen.config())
    actual['protocol_id']=parent['protocol_id']
    actual['source']['source_parent']=parent['source']['source_parent']
    actual['source'].pop('failed_source')
    assert actual == parent
