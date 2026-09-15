import json

import pandas as pd
import pytest

from market_lab import futures_v79_algopack_fast_screen as parent
from market_lab import futures_v79_algopack_fast_screen_r1 as mod


def fixture(status):
    index = pd.date_range("2024-10-15 08:00", periods=3, freq="10min", tz="UTC")
    calendar, features = pd.DataFrame(index=index), pd.DataFrame(index=index)
    calendar["local_date"] = "2024-10-15"
    for asset in parent.ASSETS:
        calendar[f"{asset}_plan_eligible"] = True
        calendar[f"{asset}_contract_id"] = "SYNTH"
        for name, value in zip(parent.FIELDS, (.01, .5, .5, .3, .3, 2), strict=True):
            features[f"{asset}_{name}"] = value
        features[f"{asset}_price_status"] = "READY"
        features[f"{asset}_flow_status"] = status
    return calendar, features


def test_actual_archival_tag_regression_and_original_unchanged():
    config = json.loads((parent.REPO / parent.CONFIG).read_bytes())
    calendar, features = fixture("READY_ARCHIVE_ASSUMPTION")
    original = features.copy()
    broken = parent.make_signals(calendar, features, config)
    corrected = mod.make_signals(calendar, features, config)
    assert broken["eligible"].sum() == 0
    assert corrected["eligible"].sum() == 32
    pd.testing.assert_frame_equal(features, original)
    online = features.copy()
    for asset in parent.ASSETS:
        online[f"{asset}_flow_status"] = "READY"
    pd.testing.assert_frame_equal(corrected, parent.make_signals(calendar, online, config))


@pytest.mark.parametrize("status", ["READY", "MISSING_BUCKET", None, "UNRESOLVED_SESSION"])
def test_no_online_missing_or_unknown_status_admission(status):
    calendar, features = fixture(status)
    config = json.loads((parent.REPO / parent.CONFIG).read_bytes())
    assert mod.make_signals(calendar, features, config)["eligible"].sum() == 0
