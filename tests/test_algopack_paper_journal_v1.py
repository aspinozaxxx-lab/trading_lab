"""Synthetic journal events; Linux tests exercise real exclusive creation and fsync."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, TEN
from market_lab.futures.algopack_paper_model_v1 import TARGET_COLUMNS

START = datetime(2026, 9, 7, 21, tzinfo=UTC)  # Synthetic only, not production activation.
END = datetime(2026, 9, 8, 8, tzinfo=UTC)
NOW = END + timedelta(minutes=4, seconds=1)


def candidate():
    return dict(
        state="COMPUTED_NOT_PERSISTED",
        information_end=END.isoformat(),
        input_cutoff=(END + timedelta(minutes=4)).isoformat(),
        completed_at=NOW.isoformat(),
        future_start=START.isoformat(),
        planned_entry_at=(END + TEN).isoformat(),
        target_exit_at=(END + 7 * TEN).isoformat(),
        live_trading_allowed=False,
        execution_admitted=False,
        target_names=list(TARGET_COLUMNS),
        assets=[dict(asset=asset) for asset in ASSETS],
        source_observations=[
            dict(
                kind="source",
                key="capture_1",
                record_sha256="a" * 64,
                observed_at=(END + timedelta(minutes=3)).isoformat(),
            )
        ],
        arms={
            arm: dict(model_sha256=sha, status="READY", prediction=[0.001] * 4)
            for arm, sha in journal.MODEL_SHA.items()
        },
    )


def test_forecast_key_is_unique_per_information_end():
    assert journal.forecast_key(candidate()) == "20260908T080000Z"


@pytest.mark.parametrize(
    "changes",
    [
        dict(live_trading_allowed=True),
        dict(execution_admitted=True),
        dict(state="UNPUBLISHED"),
        dict(planned_entry_at=END.isoformat()),
        dict(target_names=["OTHER"]),
        dict(completed_at=(END + TEN).isoformat()),
        dict(source_observations=[]),
    ],
)
def test_invalid_forecast_declaration(changes):
    with pytest.raises(ValueError):
        journal.forecast_key({**candidate(), **changes})


@pytest.mark.parametrize(
    "prediction", [[None] * 4, [True] * 4, [float("nan")] * 4, ["0.1"] * 4, [1.0] * 3]
)
def test_invalid_prediction_values(prediction):
    value = candidate()
    value["arms"]["price_only"]["prediction"] = prediction
    with pytest.raises(ValueError):
        journal.forecast_key(value)


def test_future_input_reference_rejected():
    value = candidate()
    value["source_observations"][0]["observed_at"] = (NOW + TEN).isoformat()
    with pytest.raises(ValueError, match="as-of"):
        journal.forecast_key(value)


@pytest.mark.skipif(os.name != "posix", reason="Linux fsync/flock semantics required")
class TestLinuxJournal:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.root = tmp_path / "journal"
        self.root.mkdir(mode=0o700)
        self.clock = NOW
        monkeypatch.setattr(journal, "now", lambda: self.clock)

    def source(self, key="capture_1"):
        return journal.publish(
            self.root,
            kind="source",
            key=key,
            future_start=START,
            payload=dict(source_schema="synthetic", rows=[]),
        )

    def forecast(self):
        self.clock = END + timedelta(minutes=2)
        ref = self.source()
        observed = journal.observe(
            self.root,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=START,
        )
        self.clock = NOW
        value = candidate()
        value["source_observations"][0].update(
            record_sha256=ref["record_sha256"], observed_at=observed["observed_at"]
        )
        return value

    def test_roundtrip_and_actual_observation_clock(self):
        ref = self.source()
        self.clock += timedelta(seconds=1)
        result = journal.observe(
            self.root,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=START,
        )
        assert result["observed_at"] == self.clock.isoformat()
        assert result["durable_payload_at"] == NOW.isoformat()
        assert result["payload"]["rows"] == []
        assert not result["execution_admitted"]

    def test_no_overwrite(self):
        ref = self.source()
        raw = (self.root / "source/capture_1/payload.json").read_bytes()
        with pytest.raises(FileExistsError):
            self.source()
        assert (self.root / "source/capture_1/payload.json").read_bytes() == raw
        assert ref["state"] == "RECORDED_NOT_CONSUMED"

    @pytest.mark.parametrize("filename", ["payload.json", "record.json", "COMMITTED.json"])
    def test_crash_leaves_reserved_incomplete_attempt(self, monkeypatch, filename):
        write = journal._write

        def interrupted(path, raw):
            if path.name == filename:
                raise OSError("synthetic crash")
            write(path, raw)

        monkeypatch.setattr(journal, "_write", interrupted)
        with pytest.raises(OSError):
            self.source()
        assert (self.root / "source/capture_1/STARTED.json").exists()
        with pytest.raises(ValueError, match="incomplete"):
            journal.observe(
                self.root,
                kind="source",
                key="capture_1",
                record_sha256="a" * 64,
                future_start=START,
            )
        with pytest.raises(FileExistsError):
            self.source()

    def test_payload_tampering_rejected(self):
        ref = self.source()
        (self.root / "source/capture_1/payload.json").write_bytes(b"{}\n")
        with pytest.raises(ValueError, match="payload identity"):
            journal.observe(
                self.root,
                kind="source",
                key=ref["key"],
                record_sha256=ref["record_sha256"],
                future_start=START,
            )

    def test_wrong_boundary_stops_before_payload_read(self, monkeypatch):
        ref = self.source()
        read, paths = journal._read, []

        def traced(path, *args):
            paths.append(path.name)
            return read(path, *args)

        monkeypatch.setattr(journal, "_read", traced)
        with pytest.raises(ValueError, match="header"):
            journal.observe(
                self.root,
                kind="source",
                key=ref["key"],
                record_sha256=ref["record_sha256"],
                future_start=START + timedelta(minutes=1),
            )
        assert "payload.json" not in paths

    def test_symlink_and_hardlink_refused(self):
        ref = self.source()
        linked = self.root.parent / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            journal.observe(
                linked,
                kind="source",
                key=ref["key"],
                record_sha256=ref["record_sha256"],
                future_start=START,
            )
        os.link(self.root / "source/capture_1/payload.json", self.root.parent / "hardlink")
        with pytest.raises(ValueError, match="unlinked"):
            journal.observe(
                self.root,
                kind="source",
                key=ref["key"],
                record_sha256=ref["record_sha256"],
                future_start=START,
            )

    def test_concurrent_lock_refused(self):
        with journal._lock(self.root), pytest.raises(BlockingIOError):
            self.source()

    def test_consumption_deadline_cannot_be_backdated(self):
        value = self.forecast()
        original = journal.encode(value)
        ref = journal.publish_forecast(self.root, value)
        result = journal.consume_forecast(self.root, ref, START)
        assert result["payload"]["arms"]["price_only"]["status"] == "READY"
        self.clock = END + TEN
        late = journal.consume_forecast(self.root, ref, START)
        assert all(
            arm["prediction"] is None and arm["status"] == "MISSED_CONSUMPTION_DEADLINE"
            for arm in late["payload"]["arms"].values()
        )
        assert journal.encode(value) == original  # Immutable source candidate unchanged.

    def test_slow_publication_is_not_timely_consumption(self, monkeypatch):
        value = self.forecast()
        write = journal._write

        def slow_marker(path, raw):
            write(path, raw)
            if path.name == "COMMITTED.json":
                self.clock = END + TEN

        monkeypatch.setattr(journal, "_write", slow_marker)
        ref = journal.publish_forecast(self.root, value)
        assert ref["durable_payload_at"] == NOW.isoformat()
        assert ref["acknowledged_at"] == (END + TEN).isoformat()
        consumed = journal.consume_forecast(self.root, ref, START)
        assert consumed["payload"]["arms"]["price_only"]["prediction"] is None

    def test_unpublished_or_backdated_source_cannot_support_forecast(self):
        with pytest.raises(FileNotFoundError):
            journal.publish_forecast(self.root, candidate())
        value = self.forecast()
        value["source_observations"][0]["observed_at"] = (END + timedelta(minutes=1)).isoformat()
        with pytest.raises(ValueError, match="claimed observation"):
            journal.publish_forecast(self.root, value)
        assert not (self.root / "forecast").exists()

    @pytest.mark.parametrize("key", ["../escape", "/absolute", "a/b", "a\\b", ""])
    def test_path_escape_refused_before_creation(self, key):
        with pytest.raises(ValueError, match="kind/key"):
            self.source(key)
        assert not (self.root / "source").exists()

    def test_no_write_before_f(self):
        self.clock = START - timedelta(seconds=1)
        with pytest.raises(ValueError, match="boundary"):
            self.source()
        assert not (self.root / "source").exists()

    def test_unknown_member_rejected(self):
        ref = self.source()
        (self.root / "source/capture_1/unexpected").write_bytes(b"extra")
        with pytest.raises(ValueError, match="membership"):
            journal.observe(
                self.root,
                kind="source",
                key=ref["key"],
                record_sha256=ref["record_sha256"],
                future_start=START,
            )
