"""Fake sessions only: redaction, time gates, and explicit paid-host transport."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from market_lab.futures import algopack_paper_market_transport_v1 as transport

ORIGINAL_CHECK_CA = transport.check_ca

START = datetime(2026, 9, 7, 21, tzinfo=UTC)  # Synthetic F, never an actual activation.
NOW = datetime(2026, 9, 8, 8, 4, tzinfo=UTC)
EMPTY = b'{"candles":{"columns":["begin","end","open","high","low","close","volume"],"data":[]}}'


class Response:
    status_code = 200
    url = ""

    def __init__(self, body=EMPTY):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_content(self, size):
        yield self.body


class Session:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or Response()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.response.url:
            self.response.url = url
        return self.response


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(transport, "check_ca", lambda: None)
    monkeypatch.setattr(transport, "now", lambda: NOW)
    monkeypatch.setattr(transport.time, "monotonic", lambda: 100.0)


def capture(session, **changes):
    params = dict(
        kind="candles",
        asset="SI",
        secid="SiU6",
        future_start=START,
        token="SYNTHETIC_CREDENTIAL",
        deadline=200.0,
    )
    params.update(changes)
    return transport.capture_response(session, **params)


def test_paid_route_tls_no_redirect_and_no_implicit_admission():
    session = Session()
    result = capture(session)
    assert len(session.calls) == 1
    url, options = session.calls[0]
    assert url.startswith("https://apim.moex.com/")
    assert options["allow_redirects"] is False and options["stream"] is True
    assert options["verify"] == str(transport.CA_PATH)
    assert options["timeout"] == 30.0
    assert result["state"] == "VALIDATED_NOT_PERSISTED"
    assert result["available_at"] is None and result["execution_admitted"] is False
    assert result["normalized"] == []
    assert "SYNTHETIC_CREDENTIAL" not in str(result["receipt"])


@pytest.mark.parametrize(
    "changes",
    [
        dict(future_start=START + timedelta(days=1)),
        dict(future_start=None),
        dict(kind="trades"),
        dict(secid="https://example.com"),
    ],
)
def test_no_request_when_scope_or_boundary_invalid(changes):
    session = Session()
    with pytest.raises(transport.CaptureFailure, match="scope_or_future_boundary"):
        capture(session, **changes)
    assert session.calls == []


@pytest.mark.parametrize("token", ["", "bad\ncredential", None])
def test_bad_credential_stops_before_request(token):
    session = Session()
    with pytest.raises(transport.CaptureFailure, match="credential"):
        capture(session, token=token)
    assert session.calls == []


def test_expired_deadline_stops_before_request():
    session = Session()
    with pytest.raises(transport.CaptureFailure, match="deadline"):
        capture(session, deadline=100.0)
    assert session.calls == []


@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
def test_http_failure_no_retry_or_fallback(code):
    response = Response()
    response.status_code = code
    session = Session(response)
    with pytest.raises(transport.CaptureFailure, match="http_status_or_redirect"):
        capture(session)
    assert len(session.calls) == 1


def test_response_url_changed_is_rejected():
    response = Response()
    response.url = "https://example.com/"
    with pytest.raises(transport.CaptureFailure, match="redirect"):
        capture(Session(response))


@pytest.mark.parametrize(
    "body, phase",
    [
        (b"", "empty_or_secret_reflection"),
        (b"SYNTHETIC_CREDENTIAL", "empty_or_secret_reflection"),
        (b'{"error":"private details"}', "schema_or_source_time"),
        (b"x" * (transport.MAX_BYTES + 1), "response_limit"),
    ],
    ids=["empty", "reflection", "schema", "too_large"],
)
def test_body_never_appears_in_errors(body, phase):
    with pytest.raises(transport.CaptureFailure) as caught:
        capture(Session(Response(body)))
    assert str(caught.value) == phase


def test_exception_text_is_suppressed():
    class FailingSession:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("SYNTHETIC_CREDENTIAL private request details")

    with pytest.raises(transport.CaptureFailure) as caught:
        capture(FailingSession())
    assert str(caught.value) == "transport" and caught.value.__suppress_context__


def test_clock_discontinuity(monkeypatch):
    clocks = iter([NOW, NOW - timedelta(seconds=1)])
    monkeypatch.setattr(transport, "now", lambda: next(clocks))
    with pytest.raises(transport.CaptureFailure, match="clock_discontinuity"):
        capture(Session())


def test_actual_ca_verifier_rejects_byte_change(tmp_path, monkeypatch):
    path = tmp_path / "public-ca-fixture.pem"
    content = b"SYNTHETIC PUBLIC CERTIFICATE"
    path.write_bytes(content)
    monkeypatch.setattr(transport, "CA_PATH", path)
    monkeypatch.setattr(transport, "CA_SHA", hashlib.sha256(content).hexdigest())
    ORIGINAL_CHECK_CA()
    path.write_bytes(content + b" modified")
    with pytest.raises(transport.CaptureFailure, match="ca_identity"):
        ORIGINAL_CHECK_CA()
