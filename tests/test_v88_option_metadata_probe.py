"""Synthetic static-only parsing, closed request scope and credential routing."""

import json

import pytest

from market_lab.futures import v88_option_metadata_probe as probe


def config():
    return json.loads(probe.CONFIG.read_text(encoding="utf-8-sig"))


def description():
    return probe.requests_plan(config())[0]


def calendar():
    return probe.requests_plan(config())[-1]


def table(block, columns, rows):
    return json.dumps({block: {"columns": columns, "data": rows}}).encode()


def test_plan_exact_ten_static_queries():
    plan = probe.requests_plan(config())
    assert len(plan) == 10
    assert [p["kind"] for p in plan].count("description") == 8
    assert "from=2021-01-08&till=2021-01-08" in plan[-2]["url"]
    assert all("marketdata" not in p["url"] and "2026" not in p["url"] for p in plan)


def test_description_exact_identity_and_lasttrade_not_called_expiry():
    raw = table("description", ["name", "value"], [
        ["SECID", description()["identity"]["secid"]], ["LASTTRADEDATE", "2021-03-18"],
        ["UNKNOWN_FIELD", "not-interpreted"], ["LAST", "must-not-be-interpreted"],
    ])
    result = probe.parse(raw, description())
    assert result["status"] == "EXACT_DESCRIPTION"
    assert result["static_fields"]["LASTTRADEDATE"] == "2021-03-18"
    assert "LAST" not in result["static_fields"] and "UNKNOWN_FIELD" not in result["static_fields"]
    assert not result["original_publication_proved"]


@pytest.mark.parametrize("secid", ["different", "", None])
def test_wrong_identity_never_admitted(secid):
    result = probe.parse(table("description", ["name", "value"], [["SECID", secid]]), description())
    assert not result["metadata_available"]


def test_calendar_only_static_fields_and_no_mapping_claim():
    raw = table("options", ["asset_code", "series_name", "expiration_date", "price"],
                [["SI", "synthetic", "2025-01-09", "not-interpreted"]])
    result = probe.parse(raw, calendar())
    assert result["metadata_available"]
    assert "price" not in result["static_rows"][0]
    assert not result["exact_secid_underlying_expiry_mapping_proved"]


def test_empty_and_html_are_feasibility_failures_not_fabricated_metadata():
    assert probe.parse(b"<html>login</html>", calendar())["status"] == "NON_JSON"
    assert not probe.parse(table("description", ["name", "value"], []),
                           description())["metadata_available"]


def test_unexpected_market_blocks_are_not_interpreted():
    raw = table("marketdata", ["LAST"], [["not-interpreted"]])
    assert probe.parse(raw, description())["status"] == "UNEXPECTED_BLOCKS"


@pytest.mark.parametrize("raw", [
    table("description", ["name", "value"], [["SECID", "a"], ["SECID", "b"]]),
    table("description", ["name", "value"], [["SECID"]]),
    table("options", ["asset_code", "asset_code"], [["SI", "SI"]]),
])
def test_malformed_or_ambiguous_metadata_fail_closed(raw):
    item = calendar() if b"options" in raw else description()
    with pytest.raises(ValueError):
        probe.parse(raw, item)


class Response:
    status_code = 200

    def __init__(self, raw=b"{}"):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield self.raw


class Session:
    def __init__(self, raw=b"{}"):
        self.kwargs = []
        self.raw = raw

    def get(self, url, **kwargs):
        self.kwargs.append(kwargs)
        return Response(self.raw)


def test_credential_only_apim_and_no_redirect(monkeypatch):
    monkeypatch.setenv("MOEX_ALGOPACK_TOKEN", "synthetic-secret")
    public, auth = Session(), Session()
    probe.fetch(public, description(), config())
    probe.fetch(auth, calendar(), config())
    assert "Authorization" not in public.kwargs[0]["headers"]
    assert auth.kwargs[0]["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert not auth.kwargs[0]["allow_redirects"]
    assert auth.kwargs[0]["verify"] == config()["transport"]["ca_path"]


def test_echoed_credential_not_persistable(monkeypatch):
    monkeypatch.setenv("MOEX_ALGOPACK_TOKEN", "synthetic-secret")
    with pytest.raises(ValueError, match="credential echoed"):
        probe.fetch(Session(b"synthetic-secret"), calendar(), config())


def test_response_cap():
    cfg = config()
    cfg["transport"]["maximum_response_bytes"] = 1
    with pytest.raises(ValueError, match="response cap"):
        probe.fetch(Session(), description(), cfg)


def test_protected_calendar_not_requested():
    cfg = config()
    cfg["calendar_dates"][0] = "2026-01-01"
    with pytest.raises(ValueError, match="protected calendar"):
        probe.requests_plan(cfg)
