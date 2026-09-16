"""A source-only transport change may not alter any V96 economic parameter."""

import subprocess
import urllib.request

import pytest

from market_lab import futures_v96_variance_premium_retry1 as retry


def test_retry_economics_and_source_url_are_identical():
    retry.check_unchanged_economics()


def test_real_opener_routes_only_exact_bounded_url_to_curl(monkeypatch):
    calls = []

    def fake(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, b"observation_date,SP500\n2018-01-02,100\n\n200")

    monkeypatch.setattr(retry.subprocess, "run", fake)
    with urllib.request.build_opener(retry.CurlSource()).open(retry.URL, timeout=90) as response:
        assert response.status == 200 and response.url == retry.URL
        assert response.read(200).startswith(b"observation_date,SP500")
    cmd, kwargs = calls[0]
    assert "--http1.1" in cmd and "--location" not in cmd and "-L" not in cmd
    assert "--insecure" not in cmd and "--cookie" not in cmd
    assert cmd[-1] == retry.URL and kwargs["timeout"] == 50
    with pytest.raises(ValueError, match="source URL"):
        urllib.request.build_opener(retry.CurlSource()).open("https://example.com/", timeout=1)


@pytest.mark.parametrize(
    "payload,returncode", [(b"redirect\n302", 0), (b"error\n500", 0), (b"\n000", 28)]
)
def test_non_200_or_failed_transport_never_masquerades_as_source(monkeypatch, payload, returncode):
    monkeypatch.setattr(
        retry.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, returncode, payload),
    )
    with pytest.raises(ValueError):
        urllib.request.build_opener(retry.CurlSource()).open(retry.URL, timeout=90)
