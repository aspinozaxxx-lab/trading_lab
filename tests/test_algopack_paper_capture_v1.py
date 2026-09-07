"""Synthetic packets and fake HTTP sessions; production activation is never created."""

import base64
import json
import os
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from market_lab.futures import algopack_paper_capture_v1 as capture
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation

START = datetime(2026, 9, 7, 21, tzinfo=UTC)
NOW = datetime(2026, 9, 8, 8, 4, tzinfo=UTC)


def payload(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    block = query["iss.only"][0]
    columns = query[block + ".columns"][0].split(",")
    rows = []
    if url == capture.discovery.metadata_urls()["rfud"]:
        for asset, prefix in capture.discovery.PREFIXES.items():
            for month, expiry in (("U", "2026-09-17"), ("Z", "2026-12-17")):
                rows.append(
                    dict(
                        SECID=prefix + month + "6",
                        BOARDID="RFUD",
                        ASSETCODE=capture.discovery.ASSETS[asset],
                        SECTYPE="FUT",
                        LASTTRADEDATE=expiry,
                        LASTDELDATE=expiry,
                    )
                )
    elif url == capture.discovery.metadata_urls()["series"]:
        for asset, prefix in capture.discovery.PREFIXES.items():
            for month, expiry in (("U", "2026-09-17"), ("Z", "2026-12-17")):
                rows.append(
                    dict(
                        secid=prefix + month + "6",
                        start_date="2026-01-01",
                        expiration_date=expiry,
                        asset_code=capture.discovery.ASSETS[asset],
                        is_traded=1,
                    )
                )
    elif block == "candles":
        if query["start"] == ["0"]:
            rows.append(
                dict(
                    begin="2026-09-08 10:50:00",
                    end="2026-09-08 10:59:59",
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=5.0,
                )
            )
    elif block == "orderbook":
        secid = parsed.path.split("/")[-2]
        for side, price in (("B", 100.0), ("S", 101.0)):
            rows.append(
                dict(
                    BOARDID="RFUD",
                    SECID=secid,
                    BUYSELL=side,
                    PRICE=price,
                    QUANTITY=10,
                    SEQNUM=17,
                    UPDATETIME="11:04:00",
                    DECIMALS=0,
                )
            )
    else:
        secid = parsed.path.split("/")[-1].removesuffix(".json")
        asset = capture.discovery._outright_asset(secid)
        rows.append(
            dict(
                SECID=secid,
                BOARDID="RFUD",
                ASSETCODE=capture.discovery.ASSETS[asset],
                LASTTRADEDATE="2026-09-17",
                LASTDELDATE="2026-09-17",
                LOTVOLUME=1,
                MINSTEP=1.0,
                STEPPRICE=1.0,
                INITIALMARGIN=1000.0,
                BUYSELLFEE=2.0,
            )
        )
    return json.dumps(
        {block: dict(columns=columns, data=[[row[name] for name in columns] for row in rows])}
    ).encode()


def step(kind, asset=None, secid=None, start=0):
    url = (
        capture.discovery.metadata_urls()[kind]
        if kind in capture.discovery.metadata_urls()
        else capture.market.request_url(
            kind, asset, secid, capture.market.RequestWindow(START, NOW), start
        )
    )
    raw = payload(url)
    receipt = dict(
        url=url,
        http_status=200,
        request_started_at=NOW.isoformat(),
        response_completed_at=NOW.isoformat(),
        validation_completed_at=NOW.isoformat(),
        request_elapsed_seconds=0.0,
        raw_bytes=len(raw),
        raw_sha256=journal.sha(raw),
    )
    if kind in capture.discovery.metadata_urls():
        block = "securities" if kind == "rfud" else "series"
        columns = (
            capture.discovery.RFUD_COLUMNS if kind == "rfud" else capture.discovery.SERIES_COLUMNS
        )
        normalized = capture.discovery._block(capture.discovery._decode(raw), block, columns)
    else:
        parser = {
            "candles": capture.market.parse_candles,
            "orderbook": capture.market.parse_orderbook,
            "specs": capture.market.parse_specs,
        }[kind]
        normalized = parser(
            raw,
            asset=asset,
            secid=secid,
            window=capture.market.RequestWindow(START, NOW),
            received_at=NOW,
        )
    return dict(
        kind=kind,
        asset=asset,
        secid=secid,
        start=start,
        response=dict(
            raw_base64=base64.b64encode(raw).decode(), normalized=normalized, receipt=receipt
        ),
    )


def packet():
    steps = [step("rfud"), step("series")]
    for asset, prefix in capture.discovery.PREFIXES.items():
        secid = prefix + "U6"
        steps.extend(
            [
                step("candles", asset, secid),
                step("candles", asset, secid, 1),
                step("orderbook", asset, secid),
                step("specs", asset, secid),
            ]
        )
    return steps


def test_full_packet_replay():
    result = capture.replay_packet(packet(), future_start=START, completed_at=NOW)
    assert len(result["assets"]) == 4 and result["available_at"] is None
    assert result["execution_admitted"] is False
    assert all(len(asset["candles"]) == 1 for asset in result["assets"])


def test_replayed_packet_to_model_inputs_uses_actual_observation_clock():
    normalized = capture.replay_packet(packet(), future_start=START, completed_at=NOW)
    reference = dict(
        kind="source", key="packet_1", record_sha256="a" * 64, observed_at=NOW.isoformat()
    )
    result = capture.model_inputs(
        dict(
            normalized=normalized,
            source_observation=reference,
            available_at=NOW.isoformat(),
            execution_admitted=False,
        )
    )
    assert len(result["plans"]) == len(result["bars"]) == 4
    assert all(bar.available_at == NOW and bar.begin < NOW for bar in result["bars"])
    assert all(plan.available_at == NOW for plan in result["plans"])
    assert result["bars"][0].contract_id == result["plans"][0].contract_id


@pytest.mark.parametrize(
    "case", ["raw", "normalized", "cursor", "missing", "order", "late_receipt"]
)
def test_tampered_or_incomplete_packet_fails(case):
    steps = packet()
    if case == "raw":
        steps[2]["response"]["raw_base64"] = base64.b64encode(b"{}").decode()
    elif case == "normalized":
        steps[2]["response"]["normalized"][0]["close"] = 999.0
    elif case == "cursor":
        steps[3]["start"] = 2
    elif case == "missing":
        del steps[3]
    elif case == "order":
        steps[2], steps[3] = steps[3], steps[2]
    else:
        steps[-1]["response"]["receipt"]["validation_completed_at"] = "2026-09-08T08:05:00+00:00"
    with pytest.raises(ValueError):
        capture.replay_packet(steps, future_start=START, completed_at=NOW)


def test_empty_day_is_complete_not_fabricated_zero_price():
    steps = packet()
    for index in reversed([2, 6, 10, 14]):
        steps[index + 1]["start"] = 0
        receipt = steps[index + 1]["response"]["receipt"]
        receipt["url"] = receipt["url"].replace("start=1", "start=0")
        del steps[index]
    result = capture.replay_packet(steps, future_start=START, completed_at=NOW)
    assert all(asset["candles"] == [] for asset in result["assets"])


class Response:
    status_code = 200

    def __init__(self, url, fail=False):
        self.url = url
        self.raw = payload(url)
        if fail:
            self.status_code = 403

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_content(self, _size):
        yield self.raw


class Session:
    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(url, self.fail_after is not None and len(self.calls) > self.fail_after)


@pytest.mark.skipif(os.name != "posix", reason="Linux packet journal integration")
class TestLinuxCapture:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        self.root = tmp_path / "journal"
        self.root.mkdir(mode=0o700)
        self.activation = VerifiedActivation(tmp_path, "a" * 64, START, "b" * 64)
        self.gates = []
        monkeypatch.setattr(
            VerifiedActivation, "request_ready", lambda _self: self.gates.append(True)
        )
        monkeypatch.setattr(journal, "now", lambda: NOW)
        monkeypatch.setattr(capture.transport, "now", lambda: NOW)
        monkeypatch.setattr(capture.metadata_transport, "_now", lambda: NOW)
        monkeypatch.setattr(capture.transport, "check_ca", lambda: None)
        monkeypatch.setattr(capture.time, "monotonic", lambda: 100.0)
        monkeypatch.setattr(capture.time, "sleep", lambda _: None)

    def test_fake_end_to_end_capture_replay_publication(self):
        session = Session()
        ref = capture.capture_packet(
            session,
            activation=self.activation,
            root=self.root,
            key="capture_1",
            token="SYNTHETIC_CREDENTIAL",
        )
        assert len(session.calls) == 18
        assert len(self.gates) >= 20
        result = capture.observe_packet(self.root, ref, self.activation)
        assert result["available_at"] == NOW.isoformat()
        assert len(result["normalized"]["assets"]) == 4
        assert result["execution_admitted"] is False
        assert len(list((self.root / "source").iterdir())) == 20  # start,18responses,complete.

    def test_failure_preserves_validated_responses_and_has_no_complete_packet(self):
        session = Session(fail_after=3)
        with pytest.raises(capture.transport.CaptureFailure, match="capture_or_replay"):
            capture.capture_packet(
                session,
                activation=self.activation,
                root=self.root,
                key="failed_1",
                token="SYNTHETIC_CREDENTIAL",
            )
        assert (self.root / "source/failed_1_started/COMMITTED.json").exists()
        assert (self.root / "source/failed_1_p002/COMMITTED.json").exists()
        assert (self.root / "source/failed_1_failed/COMMITTED.json").exists()
        assert not (self.root / "source/failed_1").exists()

    def test_gate_failure_makes_no_http_request(self, monkeypatch):
        def reject(_self):
            raise ValueError("WAIT_FUTURE_BOUNDARY")

        monkeypatch.setattr(VerifiedActivation, "request_ready", reject)
        session = Session()
        with pytest.raises(ValueError, match="WAIT_FUTURE_BOUNDARY"):
            capture.capture_packet(
                session,
                activation=self.activation,
                root=self.root,
                key="blocked_1",
                token="SYNTHETIC_CREDENTIAL",
            )
        assert session.calls == [] and not (self.root / "source").exists()
