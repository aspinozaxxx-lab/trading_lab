"""Pre-decision calendar policy on fake HTTP and synthetic Linux journals."""

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from test_algopack_paper_calendar_source_v1 import Session
from test_algopack_paper_calendar_source_v1 import runtime as source_runtime

from market_lab.futures import algopack_paper_calendar_policy_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation

DAY = date(2026, 9, 8)


def test_fixed_window_and_key():
    begin, end = core.window(DAY)
    assert begin.isoformat() == "2026-09-08T06:00:00+00:00"
    assert end - begin == timedelta(minutes=5)
    assert core.key(DAY) == "calendar_20260908"
    with pytest.raises(ValueError):
        core.key("2026-09-08")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    activation, root = source_runtime.__wrapped__(tmp_path, monkeypatch)
    raw = json.loads((tmp_path / core.BUNDLE).read_bytes())
    raw["files"]["src/market_lab/futures/" + Path(core.__file__).name] = hashlib.sha256(
        Path(core.__file__).read_bytes()
    ).hexdigest()
    encoded = json.dumps(raw).encode()
    (tmp_path / core.BUNDLE).write_bytes(encoded)
    activation = VerifiedActivation(
        tmp_path,
        activation.activation_sha256,
        activation.future_start,
        hashlib.sha256(encoded).hexdigest(),
    )
    clock = [core.window(DAY)[0]]
    monkeypatch.setattr(core.journal, "now", lambda: clock[0])
    return activation, root, clock


def test_capture_outside_window_no_http(runtime):
    activation, root, clock = runtime
    session = Session()
    clock[0] = core.window(DAY)[1]
    with pytest.raises(ValueError, match="window"):
        core.capture(session, root, activation, token="SYNTHETIC")
    assert not session.calls


def test_policy_closure_before_io(runtime):
    activation, root, _ = runtime
    (activation.project / core.BUNDLE).write_bytes(b"{}")
    session = Session()
    with pytest.raises(ValueError):
        core.capture(session, root, activation, token="SYNTHETIC")
    assert not session.calls


@pytest.mark.skipif(os.name != "posix", reason="private Linux journal")
class TestPolicy:
    def test_missing_calendar_blocks_expected_tuple(self, runtime):
        activation, root, clock = runtime
        clock[0] += timedelta(hours=10)
        result = core.build(root, activation, through=DAY)
        assert result["expected_days"] is None
        assert result["unresolved_days"] == [DAY.isoformat()]
        assert result["calendar_source_verified"] is False

    def test_timely_source_resolves_and_digest_stable(self, runtime):
        activation, root, clock = runtime
        core.capture(Session(), root, activation, token="SYNTHETIC")
        clock[0] += timedelta(hours=10)
        result = core.build(root, activation, through=DAY)
        assert result["expected_days"] == [DAY.isoformat()]
        assert result["calendar_source_verified"] is True
        assert result["report_admitted"] is False
        clock[0] += timedelta(hours=1)
        assert (
            core.build(root, activation, through=DAY)["calendar_sha256"]
            == result["calendar_sha256"]
        )

    def test_early_or_late_source_is_unresolved(self, runtime):
        activation, root, clock = runtime
        clock[0] += timedelta(minutes=6)
        core.source.collect(Session(), root, core.key(DAY), activation, token="SYNTHETIC")
        clock[0] += timedelta(hours=10)
        result = core.build(root, activation, through=DAY)
        assert result["days"][0]["status"] == "LATE_CALENDAR"
        assert result["expected_days"] is None

    def test_alternate_revision_cannot_replace_canonical(self, runtime):
        activation, root, clock = runtime
        core.source.collect(Session(), root, "alternative", activation, token="SYNTHETIC")
        clock[0] += timedelta(hours=10)
        assert core.build(root, activation, through=DAY)["expected_days"] is None

    def test_unknown_or_closed_status(self, runtime):
        activation, root, clock = runtime
        raw = json.dumps(
            {
                "off_days": {
                    "columns": core.source.core.COLUMNS,
                    "data": [["2026-09-08", 0, None, "H", "2026-09-08 08:00:00"]],
                }
            }
        ).encode()

        class ClosedSession(Session):
            def get(self, url, **kwargs):
                self.bad = raw if not self.calls else None
                return super().get(url, **kwargs)

        core.capture(ClosedSession(), root, activation, token="SYNTHETIC")
        clock[0] += timedelta(hours=10)
        result = core.build(root, activation, through=DAY)
        assert result["expected_days"] == []
        assert result["days"][0]["status"] == "CLOSED"
        assert (
            result["report_admitted"] is False
        )  # Must still verify no excluded economic activity.

    def test_complete_period_no_trimming_and_weekend_out_of_scope(self, runtime):
        activation, root, clock = runtime
        core.capture(Session(), root, activation, token="SYNTHETIC")
        clock[0] += timedelta(days=5, hours=10)
        result = core.build(root, activation, through=date(2026, 9, 13))
        assert len(result["days"]) == 6
        assert result["expected_days"] is None
        assert len(result["unresolved_days"]) == 3
        assert all(row["status"] == "OUT_OF_SCOPE_WEEKEND" for row in result["days"][-2:])

    def test_unmatured_period_rejected_before_source(self, runtime):
        activation, root, _ = runtime
        with pytest.raises(ValueError, match="period"):
            core.build(root, activation, through=DAY)

    def test_corruption_not_fallback(self, runtime):
        activation, root, clock = runtime
        core.capture(Session(), root, activation, token="SYNTHETIC")
        path = root / "source" / core.key(DAY) / "payload.json"
        path.write_bytes(path.read_bytes() + b" ")
        clock[0] += timedelta(hours=10)
        with pytest.raises(ValueError):
            core.build(root, activation, through=DAY)
