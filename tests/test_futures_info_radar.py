"""Testy causal'nogo information-radar tol'ko na fake-session i synthetic data."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pandas.testing as pdt
import pytest
import requests
import yaml

from market_lab.futures.info_radar import (
    CBR_DAILY_INFO_ENDPOINT,
    DEFAULT_GDELT_CHANNELS,
    GdeltChannelSpec,
    InformationDownloadSettings,
    InformationRadarDownloader,
    build_causal_cbr_features,
    build_causal_information_features,
    build_cbr_fx_url,
    build_cbr_key_rate_soap,
    build_cbr_ruonia_url,
    build_gdelt_url,
    information_channel_digest,
    merge_gdelt_channel_frames,
    parse_cbr_fx_xml,
    parse_cbr_key_rate_xml,
    parse_cbr_ruonia_html,
    parse_gdelt_tone_payload,
    parse_gdelt_volume_payload,
)

TEST_CHANNEL = GdeltChannelSpec(  # Korotkii zapechatannyi kanal synthetic testov.
    "ruble_attention",
    "(ruble OR rouble)",
    "Synthetic proverka rublevogo kanala.",
)
FIXED_NOW = datetime(2025, 2, 1, 12, 30, tzinfo=UTC)  # Stabil'noe vremya manifesta.


class FakeResponse:
    """Imitiruet minimal'nyi HTTP response s binarnym body."""

    def __init__(
        self,
        content: bytes,
        status_code: int = 200,
        content_type: str = "application/json",
    ) -> None:
        """Sohranyaet immutable body i synthetic status."""
        self.content = bytes(content)
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        """Podnimaet requests.HTTPError dlya neuspeshnogo statusa."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"synthetic status {self.status_code}")


class FakeSession:
    """Marshrutiziruet request v synthetic dispatcher i vedet audit vyzovov."""

    def __init__(self, dispatcher: Any) -> None:
        """Sohranyaet dispatcher i pustoi spisok zaprosov."""
        self.dispatcher = dispatcher
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout: float,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        """Zapisyvaet vse parametry i vozvrashchaet dispatcher response."""
        call = {
            "method": method,
            "url": url,
            "timeout": timeout,
            "data": data,
            "headers": headers,
        }
        self.calls.append(call)
        outcome = self.dispatcher(call)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        """Fiksiruet zakrytie fake-session."""
        self.closed = True


def _settings(**changes: Any) -> InformationDownloadSettings:
    """Stroit bystrye setevye limity bez real'nyh pauz."""
    values = {
        "timeout_seconds": 4.0,
        "max_retries": 0,
        "retry_backoff_seconds": 0.0,
        "gdelt_interval_seconds": 0.0,
        "gdelt_chunk_days": 365,
    }
    values.update(changes)
    return InformationDownloadSettings(**values)


def _gdelt_payload(
    start_date: date,
    days: int,
    mode: str,
    *,
    malformed: bool = False,
) -> dict[str, Any]:
    """Stroit dnevnoi timeline raw/norm ili tone."""
    points: list[dict[str, Any]] = []
    for index in range(days):
        current = start_date + timedelta(days=index)
        point = {
            "date": current.strftime("%Y%m%dT000000Z"),
            "value": float(10 + index) if mode == "timelinevolraw" else float(-2 + index),
        }
        if mode == "timelinevolraw" and not malformed:
            point["norm"] = 10_000.0 + index
        points.append(point)
    return {"timeline": [{"series": mode, "data": points}]}


def _json_response(payload: dict[str, Any]) -> FakeResponse:
    """Kodiruet synthetic GDELT JSON bez BOM."""
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def _ruonia_html(rows: list[tuple[str, ...]]) -> bytes:
    """Stroit minimal'nuyu oficial'no-podobnuyu tablicu RUONIA."""
    headers = "".join(f"<th>header {index}</th>" for index in range(11))
    body = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<html><table class="data"><tr>{headers}</tr>{body}</table></html>'.encode()


def _key_rate_xml(rows: list[tuple[str, str]]) -> bytes:
    """Stroit minimal'nyi SOAP KeyRateXML s namespace."""
    records = "".join(
        f"<KR><DT>{timestamp}</DT><Rate>{value}</Rate></KR>" for timestamp, value in rows
    )
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><KeyRateXMLResponse xmlns="http://web.cbr.ru/">'
        f'<KeyRateXMLResult><KeyRate xmlns="">{records}</KeyRate></KeyRateXMLResult>'
        "</KeyRateXMLResponse></soap:Body></soap:Envelope>"
    ).encode()


def _fx_xml(rows: list[tuple[str, str]]) -> bytes:
    """Stroit minimal'nyi oficial'no-podobnyi CBR FX XML."""
    records = "".join(
        (
            f'<Record Date="{trade_date}" Id="R01235">'
            f"<Nominal>1</Nominal><Value>{value}</Value><VunitRate>{value}</VunitRate>"
            "</Record>"
        )
        for trade_date, value in rows
    )
    return f'<ValCurs ID="R01235">{records}</ValCurs>'.encode()


def _synthetic_gdelt(days: int = 40) -> pd.DataFrame:
    """Stroit normalizovannyi kanal s dvuhdnevnym availability lag."""
    volume = parse_gdelt_volume_payload(
        _gdelt_payload(date(2024, 1, 1), days, "timelinevolraw"),
        TEST_CHANNEL,
    )
    tone = parse_gdelt_tone_payload(
        _gdelt_payload(date(2024, 1, 1), days, "timelinetone"),
        TEST_CHANNEL,
    )
    return merge_gdelt_channel_frames(volume, tone)


def _synthetic_cbr(days: int = 40) -> pd.DataFrame:
    """Stroit odin CBR ryad s odnodnevnym availability lag."""
    rows = []
    for index in range(days):
        effective = date(2024, 1, 1) + timedelta(days=index)
        rows.append(
            {
                "source": "cbr",
                "series_id": "key_rate",
                "observation_date": effective,
                "effective_date": effective,
                "publication_date": None,
                "available_at": pd.Timestamp(effective, tz="Europe/Moscow").tz_convert("UTC")
                + pd.Timedelta(days=1),
                "value": 10.0 + index,
                "availability_rule": "effective_date_plus_one_calendar_day",
            }
        )
    return pd.DataFrame(rows)


def test_sealed_config_matches_code_channels() -> None:
    """Proveryaet otsutstvie drifta mezhdu YAML-seal i runtime constants."""
    path = Path(__file__).resolve().parents[1] / "configs" / "futures_v6_information_channels.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    configured = [
        (item["id"], item["query"], item["rationale"])
        for item in payload["gdelt"]["channels"]
    ]
    runtime = [
        (channel.channel_id, channel.query, channel.rationale)
        for channel in DEFAULT_GDELT_CHANNELS
    ]
    assert payload["sealed_before_return_analysis"] is True
    assert configured == runtime
    assert len(information_channel_digest()) == 64
    sidecar = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sidecar


def test_deterministic_urls_and_soap_body() -> None:
    """Proveryaet stabil'nyi poryadok query-parametrov i request body."""
    gdelt = build_gdelt_url(
        TEST_CHANNEL,
        "timelinevolraw",
        date(2024, 1, 1),
        date(2024, 1, 10),
    )
    assert gdelt == (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        "enddatetime=20240110235959&format=json&mode=timelinevolraw&"
        "query=%28ruble%20OR%20rouble%29&startdatetime=20240101000000&timelinesmooth=0"
    )
    protected = build_gdelt_url(
        TEST_CHANNEL,
        "timelinevolraw",
        date(2025, 12, 1),
        date(2025, 12, 31),
    )
    assert "20260101" not in protected
    assert "enddatetime=20251231235959" in protected
    assert build_cbr_ruonia_url(date(2024, 1, 1), date(2024, 1, 10)) == (
        "https://www.cbr.ru/hd_base/ruonia/dynamics/?"
        "UniDbQuery.From=01.01.2024&UniDbQuery.Posted=True&UniDbQuery.To=10.01.2024"
    )
    assert build_cbr_fx_url(date(2024, 1, 1), date(2024, 1, 10)).endswith(
        "VAL_NM_RQ=R01235&date_req1=01%2F01%2F2024&date_req2=10%2F01%2F2024"
    )
    assert build_cbr_key_rate_soap(date(2024, 1, 1), date(2024, 1, 10)) == (
        build_cbr_key_rate_soap(date(2024, 1, 1), date(2024, 1, 10))
    )


def test_gdelt_schema_share_and_malformed_norm() -> None:
    """Proveryaet count/norm share, tone join i fail-closed otsutstvie norm."""
    volume = parse_gdelt_volume_payload(
        _gdelt_payload(date(2024, 1, 1), 2, "timelinevolraw"),
        TEST_CHANNEL,
    )
    tone = parse_gdelt_tone_payload(
        _gdelt_payload(date(2024, 1, 1), 2, "timelinetone"),
        TEST_CHANNEL,
    )
    merged = merge_gdelt_channel_frames(volume, tone)
    assert merged.loc[0, "article_share"] == pytest.approx(10 / 10_000)
    assert merged.loc[0, "available_at"] == pd.Timestamp("2024-01-03T00:00:00Z")
    assert merged["tone"].tolist() == [-2.0, -1.0]
    with pytest.raises(ValueError, match="date/value/norm"):
        parse_gdelt_volume_payload(
            _gdelt_payload(date(2024, 1, 1), 1, "timelinevolraw", malformed=True),
            TEST_CHANNEL,
        )


def test_cbr_schema_and_explicit_availability_lags() -> None:
    """Proveryaet RUONIA publication date i conservative lag ostal'nyh ryadov."""
    ruonia = parse_cbr_ruonia_html(
        _ruonia_html(
            [
                (
                    "10.01.2024",
                    "15,34",
                    "840,78",
                    "71",
                    "17",
                    "15,10",
                    "15,15",
                    "15,50",
                    "15,60",
                    "Стандартный",
                    "11.01.2024",
                )
            ]
        )
    )
    assert ruonia.loc[0, "publication_date"] == date(2024, 1, 11)
    assert ruonia.loc[0, "available_at"] == pd.Timestamp("2024-01-11T21:00:00Z")
    key = parse_cbr_key_rate_xml(
        _key_rate_xml([("2024-01-10T00:00:00+03:00", "16.00")])
    )
    assert key.loc[0, "available_at"] == pd.Timestamp("2024-01-10T21:00:00Z")
    fx = parse_cbr_fx_xml(_fx_xml([("10.01.2024", "90,4040")]))
    assert fx.loc[0, "value"] == pytest.approx(90.404)
    assert fx.loc[0, "available_at"] == pd.Timestamp("2024-01-10T21:00:00Z")


def test_ruonia_accepts_documented_historical_auxiliary_dashes() -> None:
    """Proveryaet, chto starye procherki aux polei ne unichtozhayut sam RUONIA ryad."""
    row = (
        "15.01.2018",
        "7,00",
        "141,18",
        "—",
        "—",
        "—",
        "—",
        "—",
        "—",
        "—",
        "16.01.2018",
    )
    frame = parse_cbr_ruonia_html(_ruonia_html([row]))
    assert frame.loc[0, "value"] == pytest.approx(7.0)
    assert frame.loc[0, "volume_bln_rub"] == pytest.approx(141.18)
    assert pd.isna(frame.loc[0, "transactions"])
    assert frame.loc[0, "status"] is None


def test_no_same_day_fill_before_ruonia_release_boundary() -> None:
    """Proveryaet, chto publication date ne oznachaet dostupnost' utrom etogo dnya."""
    gdelt = _synthetic_gdelt(12)
    cbr = parse_cbr_ruonia_html(
        _ruonia_html(
            [
                (
                    "08.01.2024",
                    "15,10",
                    "100,0",
                    "10",
                    "5",
                    "15,0",
                    "15,0",
                    "15,2",
                    "15,3",
                    "Стандартный",
                    "09.01.2024",
                )
            ]
        )
    )
    decisions = ["2024-01-09T20:59:59Z", "2024-01-09T21:00:00Z"]
    features = build_causal_information_features(
        gdelt,
        cbr,
        decisions,
        minimum_history=2,
    )
    assert pd.isna(features.loc[0, "cbr_ruonia_value"])
    assert features.loc[1, "cbr_ruonia_value"] == pytest.approx(15.10)


def test_cbr_only_builder_preserves_explicit_availability_boundary() -> None:
    """Proveryaet CBR-only fallback bez synthetic news kolonok ili budushchego."""
    cbr = _synthetic_cbr()
    decisions = ["2024-01-10T20:59:59Z", "2024-01-10T21:00:00Z"]
    features = build_causal_cbr_features(cbr, decisions)
    assert list(features.columns) == [
        "decision_at",
        "cbr_key_rate_available_at",
        "cbr_key_rate_observation_date",
        "cbr_key_rate_value",
        "cbr_key_rate_change",
    ]
    assert features.loc[0, "cbr_key_rate_value"] == pytest.approx(18.0)
    assert features.loc[1, "cbr_key_rate_value"] == pytest.approx(19.0)
    assert features.loc[0, "cbr_key_rate_available_at"] <= features.loc[0, "decision_at"]
    assert features.loc[1, "cbr_key_rate_available_at"] <= features.loc[1, "decision_at"]


def test_future_mutation_cannot_change_past_features() -> None:
    """Proveryaet invariantnost' proshlyh reshenii k mutacii budushchih istochnikov."""
    gdelt = _synthetic_gdelt()
    cbr = _synthetic_cbr()
    decisions = pd.Series(["2024-01-20T18:00:00Z", "2024-01-25T18:00:00Z"])
    baseline = build_causal_information_features(
        gdelt,
        cbr,
        decisions,
        minimum_history=3,
    )
    changed_gdelt = gdelt.copy()
    future_news = pd.to_datetime(changed_gdelt["observation_date"]).dt.date >= date(2024, 1, 26)
    changed_gdelt.loc[future_news, ["article_count", "article_share", "tone"]] *= 1_000
    changed_cbr = cbr.copy()
    future_cbr = pd.to_datetime(changed_cbr["observation_date"]).dt.date >= date(2024, 1, 26)
    changed_cbr.loc[future_cbr, "value"] *= -100
    mutated = build_causal_information_features(
        changed_gdelt,
        changed_cbr,
        decisions,
        minimum_history=3,
    )
    pdt.assert_frame_equal(baseline, mutated)


def test_download_writes_raw_parquet_and_provenance_append_only(tmp_path: Path) -> None:
    """Proveryaet atomic raw/Parquet/manifest i zapret povtornogo snapshot id."""
    def dispatcher(call: dict[str, Any]) -> FakeResponse:
        """Vozvrashchaet odin iz dvuh GDELT rezhimov po URL query."""
        mode = parse_qs(urlparse(call["url"]).query)["mode"][0]
        return _json_response(_gdelt_payload(date(2024, 1, 1), 10, mode))

    session = FakeSession(dispatcher)
    downloader = InformationRadarDownloader(
        tmp_path,
        session=session,
        settings=_settings(),
        clock=lambda: FIXED_NOW,
    )
    result = downloader.download(
        date(2024, 1, 1),
        date(2024, 1, 10),
        channels=(TEST_CHANNEL,),
        include_cbr=False,
        snapshot_id="fixed-snapshot",
    )
    assert result.gdelt_rows == 10
    assert result.cbr_path is None
    assert result.gdelt_path is not None
    assert len(pd.read_parquet(result.gdelt_path)) == 10
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["append_only"] is True
    assert manifest["channels"][0]["query"] == TEST_CHANNEL.query
    assert len(manifest["requests"]) == 2
    assert all(record["url"] for record in manifest["requests"])
    original_manifest = result.manifest_path.read_bytes()
    calls_before = len(session.calls)
    with pytest.raises(FileExistsError, match="uzhe sushchestvuet"):
        downloader.download(
            date(2024, 1, 1),
            date(2024, 1, 10),
            channels=(TEST_CHANNEL,),
            include_cbr=False,
            snapshot_id="fixed-snapshot",
        )
    assert len(session.calls) == calls_before
    assert result.manifest_path.read_bytes() == original_manifest


def test_malformed_download_writes_no_artifacts(tmp_path: Path) -> None:
    """Proveryaet, chto schema failure sluchaetsya do pervoi zapisi na disk."""
    def dispatcher(call: dict[str, Any]) -> FakeResponse:
        """Lomaet norm tol'ko v volume response."""
        mode = parse_qs(urlparse(call["url"]).query)["mode"][0]
        return _json_response(
            _gdelt_payload(
                date(2024, 1, 1),
                10,
                mode,
                malformed=mode == "timelinevolraw",
            )
        )

    downloader = InformationRadarDownloader(
        tmp_path,
        session=FakeSession(dispatcher),
        settings=_settings(),
        clock=lambda: FIXED_NOW,
    )
    with pytest.raises(ValueError, match="date/value/norm"):
        downloader.download(
            date(2024, 1, 1),
            date(2024, 1, 10),
            channels=(TEST_CHANNEL,),
            include_cbr=False,
            snapshot_id="malformed",
        )
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_holdout_block_happens_before_network(tmp_path: Path) -> None:
    """Proveryaet fizicheskii zapret information dat 2026 do zaprosa."""
    session = FakeSession(lambda _: AssertionError("set' ne dolzhna vyzyvat'sya"))
    downloader = InformationRadarDownloader(
        tmp_path,
        session=session,
        settings=_settings(),
    )
    with pytest.raises(ValueError, match="holdout"):
        downloader.download(
            date(2025, 12, 1),
            date(2026, 1, 1),
            channels=(TEST_CHANNEL,),
            include_cbr=False,
        )
    assert not session.calls


def test_full_cbr_fake_download_records_post_body_hash(tmp_path: Path) -> None:
    """Proveryaet vse tri CBR parsera i audit SOAP body v odnom snapshot."""
    def dispatcher(call: dict[str, Any]) -> FakeResponse:
        """Marshrutiziruet RUONIA HTML, KeyRate SOAP i FX XML."""
        if call["url"] == CBR_DAILY_INFO_ENDPOINT:
            return FakeResponse(
                _key_rate_xml([("2024-01-10T00:00:00+03:00", "16.00")]),
                content_type="text/xml; charset=utf-8",
            )
        if "/ruonia/dynamics/" in call["url"]:
            return FakeResponse(
                _ruonia_html(
                    [
                        (
                            "10.01.2024",
                            "15,34",
                            "840,78",
                            "71",
                            "17",
                            "15,10",
                            "15,15",
                            "15,50",
                            "15,60",
                            "Стандартный",
                            "11.01.2024",
                        )
                    ]
                ),
                content_type="text/html; charset=utf-8",
            )
        if "XML_dynamic.asp" in call["url"]:
            return FakeResponse(
                _fx_xml([("10.01.2024", "90,4040")]),
                content_type="application/xml",
            )
        raise AssertionError(f"Neozhidannyi URL: {call['url']}")

    session = FakeSession(dispatcher)
    downloader = InformationRadarDownloader(
        tmp_path,
        session=session,
        settings=_settings(),
        clock=lambda: FIXED_NOW,
    )
    result = downloader.download(
        date(2024, 1, 10),
        date(2024, 1, 10),
        include_gdelt=False,
        snapshot_id="cbr-snapshot",
    )
    assert result.cbr_rows == 3
    assert result.cbr_path is not None
    cbr = pd.read_parquet(result.cbr_path)
    assert set(cbr["series_id"]) == {"ruonia", "key_rate", "usd_rub_official"}
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    key_record = next(item for item in manifest["requests"] if item["series_id"] == "key_rate")
    assert key_record["method"] == "POST"
    assert len(key_record["request_body_sha256"]) == 64
    assert {call["timeout"] for call in session.calls} == {4.0}
