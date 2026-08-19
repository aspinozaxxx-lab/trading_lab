"""Causal'nyi information-radar iz GDELT DOC 2.0 i oficial'nyh ryadov CBR."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

GDELT_DOC_ENDPOINT = (  # Oficial'nyi endpoint polnotekstovogo GDELT DOC 2.0.
    "https://api.gdeltproject.org/api/v2/doc/doc"
)
CBR_RUONIA_ENDPOINT = (  # Oficial'naya tablica dinamiki RUONIA s datoi publikacii.
    "https://www.cbr.ru/hd_base/ruonia/dynamics/"
)
CBR_DAILY_INFO_ENDPOINT = (  # Oficial'nyi SOAP endpoint ezhednevnyh dannyh CBR.
    "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
)
CBR_FX_ENDPOINT = (  # Oficial'nyi XML endpoint dinamiki valutnyh kursov CBR.
    "https://www.cbr.ru/scripts/XML_dynamic.asp"
)
CBR_USD_RUB_ID = "R01235"  # Identifikator dollara SShA v spravochnike CBR.
CBR_TIMEZONE = ZoneInfo("Europe/Moscow")  # Zona kalendarnyh dat publikacii CBR.
PROTECTED_INFORMATION_HOLDOUT_START = date(  # Granica fizicheski netronutogo holdout.
    2026,
    1,
    1,
)
GDELT_MODES = ("timelinevolraw", "timelinetone")  # Fiksirovannye rezhimy DOC API.
GDELT_AVAILABILITY_LAG_DAYS = 2  # Polnyi den' plus sutki na indeksaciyu GDELT.
CBR_CONSERVATIVE_LAG_DAYS = 1  # Lag dlya ryadov bez tochnogo publication timestamp.
DEFAULT_TIMEOUT_SECONDS = 30.0  # Timeout odnogo zaprosa k otkrytomu istochniku.
DEFAULT_MAX_RETRIES = 3  # Chislo povtorov posle pervoi neudachnoi popytki.
DEFAULT_RETRY_BACKOFF_SECONDS = 5.25  # Pauza, soglasovannaya s limitom GDELT.
DEFAULT_GDELT_INTERVAL_SECONDS = 5.25  # Minimal'nyi interval mezhdu GDELT GET.
DEFAULT_GDELT_CHUNK_DAYS = 365  # Razmer zaprosa, sohranyayushchii dnevnoi timeline.
DEFAULT_PAST_SHORT_DAYS = 7  # Korotkoe tol'ko-proshloe okno informacii.
DEFAULT_PAST_LONG_DAYS = 28  # Dlinnoe tol'ko-proshloe okno surprise.
DEFAULT_MIN_HISTORY = 7  # Minimal'noe chislo proshlyh tochiek v rolling ocenke.
INFORMATION_USER_AGENT = (  # Identifikator vosproizvodimogo issledovatel'skogo klienta.
    "market-lab-research/0.6 (GDELT DOC 2.0; Bank of Russia)"
)
SAFE_IDENTIFIER_PATTERN = re.compile(  # Dopustimye append-only imena snapshotov.
    r"^[A-Za-z0-9_.-]+$"
)
CHANNEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")  # Format stabil'nogo channel id.


@dataclass(frozen=True, slots=True)
class GdeltChannelSpec:
    """Fiksiruet odin ekonomicheski motivirovannyi, neoptimiziruemyi news-kanal."""

    channel_id: str
    query: str
    rationale: str

    def __post_init__(self) -> None:
        """Proveryaet bezopasnyi identifikator i nepustoi zapechatannyi zapros."""
        if not CHANNEL_ID_PATTERN.fullmatch(self.channel_id):
            raise ValueError(f"Nekorrektnyi channel_id: {self.channel_id}")
        if not self.query.strip() or not self.rationale.strip():
            raise ValueError("query i rationale ne dolzhny byt' pustymi")


DEFAULT_GDELT_CHANNELS = (  # Konechnyi spisok, zapechatannyi do analiza returns.
    GdeltChannelSpec(
        "ruble_attention",
        "(ruble OR rouble)",
        "Pryamoi potok novostei o ruble dlya valutnogo futures SI.",
    ),
    GdeltChannelSpec(
        "sanctions_russia",
        "Russia (sanction OR sanctions OR embargo)",
        "Sankcionnyi rezhim menyaet risk-premiyu RUB, akcii i eksport.",
    ),
    GdeltChannelSpec(
        "geopolitics_russia",
        "Russia (Ukraine OR war OR invasion OR ceasefire)",
        "Geopoliticheskii shok odnovremenno vozdeistvuet na SI, RI, MIX i BR.",
    ),
    GdeltChannelSpec(
        "oil_supply",
        "oil (OPEC OR supply OR production OR embargo)",
        "Fizicheskii i politicheskii neftyanoi risk dlya BR i rossiiskih indeksov.",
    ),
    GdeltChannelSpec(
        "gas_europe",
        '("natural gas" OR LNG) (Russia OR Europe OR pipeline)',
        "Evropeiskii gazovyi kanal eksportnoi vyruchki i energeticheskogo riska.",
    ),
    GdeltChannelSpec(
        "russian_monetary",
        'Russia ("central bank" OR "interest rate" OR inflation)',
        "Ozhidaniya monetarnoi politiki dlya stavok, rublya i ocenki akcii.",
    ),
    GdeltChannelSpec(
        "russian_credit",
        "Russia (default OR debt OR liquidity OR bank)",
        "Kreditnyi stress i likvidnost' kak rezhimnyi indikator risk-off.",
    ),
    GdeltChannelSpec(
        "global_risk",
        '(recession OR "financial crisis" OR "risk aversion")',
        "Vneshnii risk-off faktor dlya indeksov, rublya i nefti.",
    ),
)


@dataclass(frozen=True, slots=True)
class InformationDownloadSettings:
    """Zadaet timeout, retry, pacing, lag i fail-closed granicy istochnikov."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    gdelt_interval_seconds: float = DEFAULT_GDELT_INTERVAL_SECONDS
    gdelt_chunk_days: int = DEFAULT_GDELT_CHUNK_DAYS
    gdelt_availability_lag_days: int = GDELT_AVAILABILITY_LAG_DAYS
    cbr_conservative_lag_days: int = CBR_CONSERVATIVE_LAG_DAYS
    protected_from: date | None = PROTECTED_INFORMATION_HOLDOUT_START

    def __post_init__(self) -> None:
        """Proveryaet polozhitel'nye i konechnye setevye limity."""
        if self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds dolzhen byt' > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries dolzhen byt' >= 0")
        if self.retry_backoff_seconds < 0.0 or self.gdelt_interval_seconds < 0.0:
            raise ValueError("setevye pauzy dolzhny byt' >= 0")
        if self.gdelt_chunk_days < 8:
            raise ValueError("gdelt_chunk_days dolzhen byt' >= 8 dlya dnevnoi setki")
        if self.gdelt_availability_lag_days < 1:
            raise ValueError("GDELT lag dolzhen zakryvat' hotya by konec sutok")
        if self.cbr_conservative_lag_days < 1:
            raise ValueError("CBR conservative lag dolzhen byt' >= 1")


class InformationResponse(Protocol):
    """Opisyvaet minimal'nyi HTTP response dlya real'noi i fake-session."""

    content: bytes
    headers: Any
    status_code: int

    def raise_for_status(self) -> None:
        """Signaliziruet o neuspeshnom HTTP statuse."""


class InformationSession(Protocol):
    """Opisyvaet vnedryaemuyu HTTP session bez privyazki k requests.Session."""

    headers: Any

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout: float,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> InformationResponse:
        """Vypolnyaet odin HTTP zapros s yavnym timeout."""

    def close(self) -> None:
        """Zakryvaet resursy HTTP session."""


@dataclass(frozen=True, slots=True)
class FetchedInformationDocument:
    """Hranit syroi otvet i polnuyu provenance odnogo HTTP zaprosa."""

    source: str
    series_id: str
    mode: str
    method: str
    url: str
    query: str | None
    fetched_at: datetime
    content_type: str | None
    content: bytes
    request_body_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class InformationDownloadResult:
    """Vozvrashchaet append-only puti i chislo normalizovannyh strok."""

    snapshot_id: str
    manifest_path: Path
    gdelt_path: Path | None
    cbr_path: Path | None
    gdelt_rows: int
    cbr_rows: int


def information_channel_digest(
    channels: Sequence[GdeltChannelSpec] = DEFAULT_GDELT_CHANNELS,
) -> str:
    """Vychislyaet stabil'nyi SHA-256 ekonomicheskoi specifikacii kanalov."""
    payload = [
        {
            "channel_id": channel.channel_id,
            "query": channel.query,
            "rationale": channel.rationale,
        }
        for channel in channels
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_period(
    start_date: date,
    end_date: date,
    protected_from: date | None,
) -> None:
    """Zapreshchaet perevernutyi interval i lyuboe kasanie holdout 2026."""
    if end_date < start_date:
        raise ValueError("end_date ran'she start_date")
    if protected_from is not None and end_date >= protected_from:
        raise ValueError(f"Zapreshchen dostup k information holdout s {protected_from}")


def _urlencode(parameters: dict[str, str]) -> str:
    """Kodiruet query-parametry v leksikograficheskom poryadke i bez plus-probelov."""
    return urlencode(sorted(parameters.items()), quote_via=quote, safe="")


def build_gdelt_url(
    channel: GdeltChannelSpec,
    mode: str,
    start_date: date,
    end_date: date,
) -> str:
    """Stroit GDELT URL s poslednei sekundoi dnya bez kasaniya sleduyushchei daty."""
    if mode not in GDELT_MODES:
        raise ValueError(f"Neizvestnyi GDELT mode: {mode}")
    if end_date < start_date:
        raise ValueError("end_date ran'she start_date")
    parameters = {
        "enddatetime": end_date.strftime("%Y%m%d235959"),
        "format": "json",
        "mode": mode,
        "query": channel.query,
        "startdatetime": start_date.strftime("%Y%m%d000000"),
        "timelinesmooth": "0",
    }
    return f"{GDELT_DOC_ENDPOINT}?{_urlencode(parameters)}"


def build_cbr_ruonia_url(start_date: date, end_date: date) -> str:
    """Stroit determinirovannyi URL oficial'noi tablicy RUONIA."""
    parameters = {
        "UniDbQuery.From": start_date.strftime("%d.%m.%Y"),
        "UniDbQuery.Posted": "True",
        "UniDbQuery.To": end_date.strftime("%d.%m.%Y"),
    }
    return f"{CBR_RUONIA_ENDPOINT}?{_urlencode(parameters)}"


def build_cbr_fx_url(start_date: date, end_date: date) -> str:
    """Stroit determinirovannyi URL oficial'nogo USD/RUB XML."""
    parameters = {
        "VAL_NM_RQ": CBR_USD_RUB_ID,
        "date_req1": start_date.strftime("%d/%m/%Y"),
        "date_req2": end_date.strftime("%d/%m/%Y"),
    }
    return f"{CBR_FX_ENDPOINT}?{_urlencode(parameters)}"


def build_cbr_key_rate_soap(start_date: date, end_date: date) -> bytes:
    """Stroit determinirovannoe SOAP 1.1 telo KeyRateXML bez lokal'nyh dat."""
    start_value = f"{start_date.isoformat()}T00:00:00"
    end_value = f"{end_date.isoformat()}T00:00:00"
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><KeyRateXML xmlns="http://web.cbr.ru/">'
        f"<fromDate>{start_value}</fromDate><ToDate>{end_value}</ToDate>"
        "</KeyRateXML></soap:Body></soap:Envelope>"
    )
    return body.encode("utf-8")


def _parse_gdelt_timestamp(value: Any) -> pd.Timestamp:
    """Normalizuet dopustimye GDELT datetime v UTC i otkazyvaetsya ot naive rezultata."""
    text = str(value).strip()
    compact = re.fullmatch(r"(\d{8})(?:T?(\d{6}))?Z?", text)
    if compact:
        day, clock = compact.groups()
        parsed = pd.to_datetime(day + (clock or "000000"), format="%Y%m%d%H%M%S", utc=True)
    else:
        parsed = pd.to_datetime(text, errors="raise", utc=True)
    if pd.isna(parsed):
        raise ValueError("Pustoi GDELT timestamp")
    return pd.Timestamp(parsed)


def _gdelt_timeline_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Izvlekaet edinstvennuyu seriyu timeline iz proverennogo JSON-obekta."""
    timeline = payload.get("timeline")
    if not isinstance(timeline, list) or len(timeline) != 1:
        raise ValueError("GDELT JSON dolzhen soderzhat' odnu timeline-seriyu")
    series = timeline[0]
    if not isinstance(series, dict) or not isinstance(series.get("data"), list):
        raise ValueError("Nekorrektnaya GDELT timeline.data")
    points = series["data"]
    if not points or any(not isinstance(point, dict) for point in points):
        raise ValueError("GDELT timeline ne soderzhit proveriaemyh tochiek")
    return points


def parse_gdelt_volume_payload(
    payload: dict[str, Any],
    channel: GdeltChannelSpec,
    availability_lag_days: int = GDELT_AVAILABILITY_LAG_DAYS,
) -> pd.DataFrame:
    """Normalizuet raw count/norm i schitaet dolyu statei bez smoothing."""
    rows: list[dict[str, Any]] = []
    for point in _gdelt_timeline_points(payload):
        if not {"date", "value", "norm"}.issubset(point):
            raise ValueError("TimelineVolRaw point ne soderzhit date/value/norm")
        timestamp = _parse_gdelt_timestamp(point["date"])
        count = float(point["value"])
        norm = float(point["norm"])
        if not np.isfinite(count) or not np.isfinite(norm) or count < 0.0 or norm <= 0.0:
            raise ValueError("Nedopustimye GDELT count/norm")
        if count > norm:
            raise ValueError("GDELT count prevysil obshchii norm")
        observation_date = timestamp.date()
        available_at = pd.Timestamp(
            datetime.combine(
                observation_date + timedelta(days=availability_lag_days),
                datetime_time.min,
                tzinfo=UTC,
            )
        )
        rows.append(
            {
                "source": "gdelt_doc_2",
                "channel_id": channel.channel_id,
                "query": channel.query,
                "observation_date": observation_date,
                "available_at": available_at,
                "article_count": count,
                "norm": norm,
                "article_share": count / norm,
            }
        )
    frame = pd.DataFrame(rows).sort_values("observation_date", ignore_index=True)
    if frame["observation_date"].duplicated().any():
        raise ValueError("GDELT volume soderzhit bolee odnoi tochki v den'")
    return frame


def parse_gdelt_tone_payload(
    payload: dict[str, Any],
    channel: GdeltChannelSpec,
) -> pd.DataFrame:
    """Normalizuet document-level srednii tone po dnevnym UTC tochkam."""
    rows: list[dict[str, Any]] = []
    for point in _gdelt_timeline_points(payload):
        if not {"date", "value"}.issubset(point):
            raise ValueError("TimelineTone point ne soderzhit date/value")
        timestamp = _parse_gdelt_timestamp(point["date"])
        tone = float(point["value"])
        if not np.isfinite(tone) or not -100.0 <= tone <= 100.0:
            raise ValueError("Nedopustimyi GDELT tone")
        rows.append(
            {
                "channel_id": channel.channel_id,
                "observation_date": timestamp.date(),
                "tone": tone,
            }
        )
    frame = pd.DataFrame(rows).sort_values("observation_date", ignore_index=True)
    if frame["observation_date"].duplicated().any():
        raise ValueError("GDELT tone soderzhit bolee odnoi tochki v den'")
    return frame


def merge_gdelt_channel_frames(volume: pd.DataFrame, tone: pd.DataFrame) -> pd.DataFrame:
    """Soedinyaet dve zapechatannye metriky i zapreshchaet tone bez volume."""
    volume_keys = set(zip(volume["channel_id"], volume["observation_date"], strict=False))
    tone_keys = set(zip(tone["channel_id"], tone["observation_date"], strict=False))
    if not tone_keys.issubset(volume_keys):
        raise ValueError("GDELT tone soderzhit daty bez volume/norm")
    merged = volume.merge(
        tone,
        on=["channel_id", "observation_date"],
        how="left",
        validate="one_to_one",
    )
    return merged.sort_values(["channel_id", "observation_date"], ignore_index=True)


class _CbrTableParser(HTMLParser):
    """Chitaet tol'ko tablicu class=data bez vneshnih HTML-zavisimostei."""

    def __init__(self) -> None:
        """Inicializiruet avtomat sostoyanii odnoi tablicy CBR."""
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._active_table: list[list[str]] | None = None
        self._active_row: list[str] | None = None
        self._active_cell: list[str] | None = None
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Otkryvaet nuzhnuyu tablicu, stroku ili yacheiku."""
        attributes = dict(attrs)
        if tag == "table":
            classes = set((attributes.get("class") or "").split())
            if self._active_table is not None:
                self._table_depth += 1
            elif "data" in classes:
                self._active_table = []
                self._table_depth = 1
            return
        if self._active_table is None or self._table_depth != 1:
            return
        if tag == "tr":
            self._active_row = []
        elif tag in {"th", "td"} and self._active_row is not None:
            self._active_cell = []

    def handle_data(self, data: str) -> None:
        """Nakaplivaet tekst tekushchei yacheiki bez poteri HTML entities."""
        if self._active_cell is not None:
            self._active_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Zakryvaet yacheiku, stroku ili celuyu nuzhnuyu tablicu."""
        if self._active_table is None:
            return
        if tag in {"th", "td"} and self._active_cell is not None:
            value = " ".join("".join(self._active_cell).split())
            if self._active_row is not None:
                self._active_row.append(value)
            self._active_cell = None
        elif tag == "tr" and self._active_row is not None and self._table_depth == 1:
            if self._active_row:
                self._active_table.append(self._active_row)
            self._active_row = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                self.tables.append(self._active_table)
                self._active_table = None


def _decimal_number(value: str, label: str) -> float:
    """Chitaet desyatichnuyu zapyatuyu CBR i zapreshchaet nefinite znacheniya."""
    normalized = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        number = float(normalized)
    except ValueError as error:
        raise ValueError(f"Nekorrektnoe chislo CBR {label}: {value}") from error
    if not np.isfinite(number):
        raise ValueError(f"Nefinite chislo CBR {label}")
    return number


def _optional_decimal_number(value: str, label: str) -> float:
    """Vozvrashchaet NaN dlya oficial'nogo procherka v istoricheskih RUONIA polyah."""
    normalized = value.replace("\xa0", "").strip()
    if normalized in {"", "-", "–", "—"}:
        return float("nan")
    return _decimal_number(value, label)


def _calendar_lag_available_at(effective_date: date, lag_days: int) -> pd.Timestamp:
    """Stavit conservative availability v nachalo sleduyushchego kalendarnogo dnya MSK."""
    local = datetime.combine(
        effective_date + timedelta(days=lag_days),
        datetime_time.min,
        tzinfo=CBR_TIMEZONE,
    )
    return pd.Timestamp(local.astimezone(UTC))


def parse_cbr_ruonia_html(content: bytes) -> pd.DataFrame:
    """Chitaet RUONIA i ispol'zuet konec yavnoi daty publikacii kak availability."""
    try:
        html = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("RUONIA HTML ne yavlyaetsya UTF-8") from error
    parser = _CbrTableParser()
    parser.feed(html)
    if len(parser.tables) != 1:
        raise ValueError("RUONIA HTML dolzhen soderzhat' odnu data-tablicu")
    rows = parser.tables[0]
    if len(rows) < 2 or len(rows[0]) != 11:
        raise ValueError("Nekorrektnaya schema RUONIA tablicy")
    normalized_rows: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) != 11:
            raise ValueError("Stroka RUONIA ne sootvetstvuet 11 kolonkam")
        effective_date = datetime.strptime(row[0], "%d.%m.%Y").date()
        publication_date = datetime.strptime(row[10], "%d.%m.%Y").date()
        if publication_date < effective_date:
            raise ValueError("RUONIA publication_date ran'she rate_date")
        normalized_rows.append(
            {
                "source": "cbr",
                "series_id": "ruonia",
                "observation_date": effective_date,
                "effective_date": effective_date,
                "publication_date": publication_date,
                "available_at": _calendar_lag_available_at(publication_date, 1),
                "value": _decimal_number(row[1], "ruonia"),
                "volume_bln_rub": _optional_decimal_number(row[2], "volume"),
                "transactions": _optional_decimal_number(row[3], "transactions"),
                "participants": _optional_decimal_number(row[4], "participants"),
                "min_rate": _optional_decimal_number(row[5], "min_rate"),
                "p25_rate": _optional_decimal_number(row[6], "p25_rate"),
                "p75_rate": _optional_decimal_number(row[7], "p75_rate"),
                "max_rate": _optional_decimal_number(row[8], "max_rate"),
                "status": None if row[9] in {"", "-", "–", "—"} else row[9],
                "availability_rule": "publication_date_plus_one_calendar_day",
            }
        )
    frame = pd.DataFrame(normalized_rows).sort_values("effective_date", ignore_index=True)
    if frame["effective_date"].duplicated().any():
        raise ValueError("Povtor effective_date v RUONIA")
    return frame


def _xml_local_name(element: ElementTree.Element) -> str:
    """Udaliaet namespace iz XML taga bez zavisimosti ot prefixa."""
    return element.tag.rsplit("}", maxsplit=1)[-1]


def _xml_child_text(element: ElementTree.Element, name: str) -> str:
    """Nahodit obyazatel'nogo pryamogo potomka XML po lokal'nomu imeni."""
    matches = [child for child in element if _xml_local_name(child) == name]
    if len(matches) != 1 or matches[0].text is None:
        raise ValueError(f"XML element ne soderzhit edinstvennyi {name}")
    return matches[0].text.strip()


def parse_cbr_key_rate_xml(
    content: bytes,
    conservative_lag_days: int = CBR_CONSERVATIVE_LAG_DAYS,
) -> pd.DataFrame:
    """Chitaet SOAP KeyRateXML i konservativno sdvigaet effective date na sutki."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise ValueError("Nekorrektnyi CBR KeyRate XML") from error
    records = [element for element in root.iter() if _xml_local_name(element) == "KR"]
    if not records:
        raise ValueError("CBR KeyRate XML ne soderzhit KR")
    rows: list[dict[str, Any]] = []
    for record in records:
        effective_timestamp = pd.Timestamp(_xml_child_text(record, "DT"))
        effective_date = effective_timestamp.date()
        value = _decimal_number(_xml_child_text(record, "Rate"), "key_rate")
        if value < 0.0:
            raise ValueError("Key rate ne mozhet byt' otricatel'noi v etom feed")
        rows.append(
            {
                "source": "cbr",
                "series_id": "key_rate",
                "observation_date": effective_date,
                "effective_date": effective_date,
                "publication_date": None,
                "available_at": _calendar_lag_available_at(
                    effective_date,
                    conservative_lag_days,
                ),
                "value": value,
                "availability_rule": "effective_date_plus_one_calendar_day",
            }
        )
    frame = pd.DataFrame(rows).sort_values("effective_date", ignore_index=True)
    if frame["effective_date"].duplicated().any():
        raise ValueError("Povtor effective_date v KeyRateXML")
    return frame


def parse_cbr_fx_xml(
    content: bytes,
    conservative_lag_days: int = CBR_CONSERVATIVE_LAG_DAYS,
) -> pd.DataFrame:
    """Chitaet oficial'nyi USD/RUB XML i ne razreshaet ispol'zovanie v tot zhe den'."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise ValueError("Nekorrektnyi CBR FX XML") from error
    if root.attrib.get("ID") != CBR_USD_RUB_ID:
        raise ValueError("CBR FX XML vernul drugoi identifikator valyuty")
    records = [element for element in root if _xml_local_name(element) == "Record"]
    if not records:
        raise ValueError("CBR FX XML ne soderzhit Record")
    rows: list[dict[str, Any]] = []
    for record in records:
        if record.attrib.get("Id") != CBR_USD_RUB_ID or "Date" not in record.attrib:
            raise ValueError("Nekorrektnye atributy CBR FX Record")
        effective_date = datetime.strptime(record.attrib["Date"], "%d.%m.%Y").date()
        nominal = _decimal_number(_xml_child_text(record, "Nominal"), "fx_nominal")
        value = _decimal_number(_xml_child_text(record, "Value"), "fx_value")
        if nominal <= 0.0 or value <= 0.0:
            raise ValueError("CBR FX nominal/value dolzhny byt' > 0")
        rows.append(
            {
                "source": "cbr",
                "series_id": "usd_rub_official",
                "observation_date": effective_date,
                "effective_date": effective_date,
                "publication_date": None,
                "available_at": _calendar_lag_available_at(
                    effective_date,
                    conservative_lag_days,
                ),
                "value": value / nominal,
                "availability_rule": "effective_date_plus_one_calendar_day",
            }
        )
    frame = pd.DataFrame(rows).sort_values("effective_date", ignore_index=True)
    if frame["effective_date"].duplicated().any():
        raise ValueError("Povtor effective_date v CBR FX")
    return frame


def _assert_date_bounds(
    frame: pd.DataFrame,
    start_date: date,
    end_date: date,
    column: str,
    label: str,
) -> None:
    """Zapreshchaet tikhie stroki za granicami zaproshennogo intervala."""
    if frame.empty:
        raise ValueError(f"Pustoi normalizovannyi ryad {label}")
    values = pd.to_datetime(frame[column], errors="raise").dt.date
    if values.lt(start_date).any() or values.gt(end_date).any():
        raise ValueError(f"{label} vyshel za granicy zaprosa")


def _date_chunks(start_date: date, end_date: date, days: int) -> list[tuple[date, date]]:
    """Razbivaet interval na neperesekayushchiesya calendar chunks."""
    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(end_date, cursor + timedelta(days=days - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet normalizovannyi DataFrame v Parquet Zstandard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_bytes(content: bytes) -> str:
    """Vychislyaet SHA-256 syrogo otveta ili SOAP tela."""
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 gotovogo artefakta potokovo."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _bounded_path(root: Path, *parts: str) -> Path:
    """Razreshaet put' i zapreshchaet vyhod iz peredannogo kornya."""
    resolved_root = root.resolve()
    target = resolved_root.joinpath(*parts).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"Put' info-radar vyshel iz kornya: {target}") from error
    return target


def _snapshot_identifier(retrieved_at: datetime, digest: str) -> str:
    """Stroit vremya-plyus-hash identifikator bez sluchainogo global'nogo sostoyaniya."""
    timestamp = retrieved_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{digest[:10]}"


class InformationRadarDownloader:
    """Zagruzhaet GDELT/CBR posledovatel'no i sohranyaet append-only snapshot."""

    def __init__(
        self,
        root: Path,
        session: InformationSession | None = None,
        settings: InformationDownloadSettings | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Sozdaet izolirovannyi klient s vnedryaemymi chasami i fake-session."""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings or InformationDownloadSettings()
        self._owns_session = session is None
        self.session: InformationSession = session or requests.Session()
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.clock = clock
        self._last_gdelt_request: float | None = None
        headers = getattr(self.session, "headers", None)
        if headers is not None:
            headers.update({"User-Agent": INFORMATION_USER_AGENT})

    def close(self) -> None:
        """Zakryvaet tol'ko sessiyu, sozdannuyu samim downloader."""
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> InformationRadarDownloader:
        """Vozvrashchaet downloader dlya upravlyaemogo konteksta."""
        return self

    def __exit__(self, *_: object) -> None:
        """Garantirovanno zakryvaet sobstvennuyu sessiyu."""
        self.close()

    def _pace_gdelt(self) -> None:
        """Soblyudaet publichnyi limit ne chashche odnogo GDELT zaprosa v pyat' sekund."""
        now = self.monotonic()
        if self._last_gdelt_request is not None:
            remaining = self.settings.gdelt_interval_seconds - (
                now - self._last_gdelt_request
            )
            if remaining > 0.0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_gdelt_request = now

    def _request(
        self,
        method: str,
        url: str,
        *,
        source: str,
        series_id: str,
        mode: str,
        query: str | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchedInformationDocument:
        """Vypolnyaet zapros s bounded retry i vozvrashchaet immutable provenance."""
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            if source == "gdelt_doc_2":
                self._pace_gdelt()
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.settings.timeout_seconds,
                    data=data,
                    headers=headers,
                )
                response.raise_for_status()
                content = bytes(response.content)
                if not content:
                    raise ValueError("Istochnik vernul pustoi HTTP body")
                response_headers = getattr(response, "headers", {})
                content_type = response_headers.get("content-type") if response_headers else None
                return FetchedInformationDocument(
                    source=source,
                    series_id=series_id,
                    mode=mode,
                    method=method,
                    url=url,
                    query=query,
                    fetched_at=self.clock().astimezone(UTC),
                    content_type=content_type,
                    content=content,
                    request_body_sha256=_sha256_bytes(data) if data is not None else None,
                )
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt >= self.settings.max_retries:
                    break
                delay = self.settings.retry_backoff_seconds * (2**attempt)
                if delay > 0.0:
                    self.sleeper(delay)
        raise RuntimeError(f"Ne udalos' poluchit' {url}: {last_error}") from last_error

    def _fetch_gdelt(
        self,
        start_date: date,
        end_date: date,
        channels: Sequence[GdeltChannelSpec],
    ) -> tuple[pd.DataFrame, list[FetchedInformationDocument]]:
        """Zagruzhaet oba rezhima po godovym chunks i sobiraet dnevnoi panel."""
        documents: list[FetchedInformationDocument] = []
        channel_frames: list[pd.DataFrame] = []
        for channel in channels:
            chunks: list[pd.DataFrame] = []
            for chunk_start, chunk_end in _date_chunks(
                start_date,
                end_date,
                self.settings.gdelt_chunk_days,
            ):
                parsed: dict[str, pd.DataFrame] = {}
                for mode in GDELT_MODES:
                    url = build_gdelt_url(channel, mode, chunk_start, chunk_end)
                    document = self._request(
                        "GET",
                        url,
                        source="gdelt_doc_2",
                        series_id=channel.channel_id,
                        mode=mode,
                        query=channel.query,
                    )
                    documents.append(document)
                    try:
                        payload = json.loads(document.content.decode("utf-8-sig"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise ValueError("GDELT ne vernul korrektnyi UTF-8 JSON") from error
                    if not isinstance(payload, dict):
                        raise ValueError("GDELT JSON ne yavlyaetsya obektom")
                    if mode == "timelinevolraw":
                        frame = parse_gdelt_volume_payload(
                            payload,
                            channel,
                            self.settings.gdelt_availability_lag_days,
                        )
                    else:
                        frame = parse_gdelt_tone_payload(payload, channel)
                    _assert_date_bounds(
                        frame,
                        chunk_start,
                        chunk_end,
                        "observation_date",
                        f"GDELT {channel.channel_id}/{mode}",
                    )
                    parsed[mode] = frame
                chunks.append(
                    merge_gdelt_channel_frames(
                        parsed["timelinevolraw"],
                        parsed["timelinetone"],
                    )
                )
            combined = pd.concat(chunks, ignore_index=True)
            if combined["observation_date"].duplicated().any():
                raise ValueError(f"Povtor GDELT dat mezhdu chunks {channel.channel_id}")
            channel_frames.append(combined)
        panel = pd.concat(channel_frames, ignore_index=True)
        return panel.sort_values(["channel_id", "observation_date"], ignore_index=True), documents

    def _fetch_cbr(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[pd.DataFrame, list[FetchedInformationDocument]]:
        """Zagruzhaet RUONIA, key rate i USD/RUB iz treh oficial'nyh interfeisov."""
        ruonia_url = build_cbr_ruonia_url(start_date, end_date)
        ruonia_document = self._request(
            "GET",
            ruonia_url,
            source="cbr",
            series_id="ruonia",
            mode="html_table",
        )
        key_body = build_cbr_key_rate_soap(start_date, end_date)
        key_document = self._request(
            "POST",
            CBR_DAILY_INFO_ENDPOINT,
            source="cbr",
            series_id="key_rate",
            mode="soap_key_rate_xml",
            data=key_body,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "http://web.cbr.ru/KeyRateXML",
            },
        )
        fx_url = build_cbr_fx_url(start_date, end_date)
        fx_document = self._request(
            "GET",
            fx_url,
            source="cbr",
            series_id="usd_rub_official",
            mode="xml_dynamic",
        )
        frames = [
            parse_cbr_ruonia_html(ruonia_document.content),
            parse_cbr_key_rate_xml(
                key_document.content,
                self.settings.cbr_conservative_lag_days,
            ),
            parse_cbr_fx_xml(
                fx_document.content,
                self.settings.cbr_conservative_lag_days,
            ),
        ]
        for frame in frames:
            series_id = str(frame["series_id"].iloc[0])
            _assert_date_bounds(
                frame,
                start_date,
                end_date,
                "effective_date",
                f"CBR {series_id}",
            )
        panel = pd.concat(frames, ignore_index=True, sort=False)
        panel = panel.sort_values(["series_id", "effective_date"], ignore_index=True)
        return panel, [ruonia_document, key_document, fx_document]

    def _persist_snapshot(
        self,
        snapshot_id: str,
        start_date: date,
        end_date: date,
        channels: Sequence[GdeltChannelSpec],
        gdelt: pd.DataFrame | None,
        cbr: pd.DataFrame | None,
        documents: Sequence[FetchedInformationDocument],
        retrieved_at: datetime,
    ) -> InformationDownloadResult:
        """Atomarno pishet kazhdyi fail i nikogda ne zamenyaet gotovyi snapshot."""
        if not SAFE_IDENTIFIER_PATTERN.fullmatch(snapshot_id):
            raise ValueError(f"Nekorrektnyi snapshot_id: {snapshot_id}")
        raw_directory = _bounded_path(self.root, "raw", "info_radar", snapshot_id)
        processed_directory = _bounded_path(self.root, "processed", "info_radar", snapshot_id)
        if raw_directory.exists() or processed_directory.exists():
            raise FileExistsError(f"Info-radar snapshot uzhe sushchestvuet: {snapshot_id}")
        raw_directory.mkdir(parents=True, exist_ok=False)
        processed_directory.mkdir(parents=True, exist_ok=False)
        request_records: list[dict[str, Any]] = []
        for index, document in enumerate(documents):
            extension = {
                "html_table": "html",
                "soap_key_rate_xml": "xml",
                "xml_dynamic": "xml",
            }.get(document.mode, "json")
            filename = (
                f"{index:04d}_{document.source}_{document.series_id}_"
                f"{document.mode}.{extension}"
            )
            path = raw_directory / filename
            atomic_write_bytes(path, document.content)
            request_records.append(
                {
                    "source": document.source,
                    "series_id": document.series_id,
                    "mode": document.mode,
                    "method": document.method,
                    "url": document.url,
                    "query": document.query,
                    "fetched_at": document.fetched_at.isoformat(),
                    "content_type": document.content_type,
                    "request_body_sha256": document.request_body_sha256,
                    "raw_path": path.relative_to(self.root).as_posix(),
                    "raw_bytes": path.stat().st_size,
                    "raw_sha256": _sha256_file(path),
                }
            )
        gdelt_path: Path | None = None
        cbr_path: Path | None = None
        artifacts: dict[str, Any] = {}
        if gdelt is not None:
            gdelt_path = processed_directory / "gdelt_daily.parquet"
            _atomic_write_parquet(gdelt_path, gdelt)
            artifacts["gdelt"] = {
                "path": gdelt_path.relative_to(self.root).as_posix(),
                "rows": len(gdelt),
                "sha256": _sha256_file(gdelt_path),
            }
        if cbr is not None:
            cbr_path = processed_directory / "cbr_daily.parquet"
            _atomic_write_parquet(cbr_path, cbr)
            artifacts["cbr"] = {
                "path": cbr_path.relative_to(self.root).as_posix(),
                "rows": len(cbr),
                "sha256": _sha256_file(cbr_path),
            }
        manifest_path = processed_directory / "manifest.json"
        manifest = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "append_only": True,
            "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
            "protected_holdout_start": (
                self.settings.protected_from.isoformat()
                if self.settings.protected_from is not None
                else None
            ),
            "channel_digest_sha256": information_channel_digest(channels),
            "channels": [
                {
                    "channel_id": channel.channel_id,
                    "query": channel.query,
                    "rationale": channel.rationale,
                }
                for channel in channels
            ],
            "availability": {
                "gdelt_calendar_days": self.settings.gdelt_availability_lag_days,
                "ruonia": "publication_date_plus_one_calendar_day",
                "key_rate": "effective_date_plus_one_calendar_day",
                "usd_rub_official": "effective_date_plus_one_calendar_day",
            },
            "requests": request_records,
            "artifacts": artifacts,
            "limitations": [
                "GDELT historical timeline is a current retrospective snapshot, not point-in-time.",
                "GDELT source mix, translation and tone can be revised or biased.",
                "CBR key-rate and FX feeds do not expose exact publication timestamps here.",
            ],
        }
        write_json(manifest_path, manifest)
        return InformationDownloadResult(
            snapshot_id=snapshot_id,
            manifest_path=manifest_path,
            gdelt_path=gdelt_path,
            cbr_path=cbr_path,
            gdelt_rows=0 if gdelt is None else len(gdelt),
            cbr_rows=0 if cbr is None else len(cbr),
        )

    def _assert_snapshot_available(self, snapshot_id: str) -> None:
        """Fail-fast zapreshchaet povtornyi explicit snapshot do lyubogo HTTP zaprosa."""
        if not SAFE_IDENTIFIER_PATTERN.fullmatch(snapshot_id):
            raise ValueError(f"Nekorrektnyi snapshot_id: {snapshot_id}")
        raw_directory = _bounded_path(self.root, "raw", "info_radar", snapshot_id)
        processed_directory = _bounded_path(self.root, "processed", "info_radar", snapshot_id)
        if raw_directory.exists() or processed_directory.exists():
            raise FileExistsError(f"Info-radar snapshot uzhe sushchestvuet: {snapshot_id}")

    def download(
        self,
        start_date: date,
        end_date: date,
        *,
        channels: Sequence[GdeltChannelSpec] = DEFAULT_GDELT_CHANNELS,
        include_gdelt: bool = True,
        include_cbr: bool = True,
        snapshot_id: str | None = None,
    ) -> InformationDownloadResult:
        """Proveryaet granicy do seti, parsit vse v pamyati i sohranyaet snapshot."""
        _validate_period(start_date, end_date, self.settings.protected_from)
        if snapshot_id is not None:
            self._assert_snapshot_available(snapshot_id)
        if not include_gdelt and not include_cbr:
            raise ValueError("Nuzhen hotya by odin information source")
        if include_gdelt and not channels:
            raise ValueError("Dlya GDELT nuzhen hotya by odin channel")
        identifiers = [channel.channel_id for channel in channels]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Povtor channel_id v information spec")
        retrieved_at = self.clock().astimezone(UTC)
        gdelt: pd.DataFrame | None = None
        cbr: pd.DataFrame | None = None
        documents: list[FetchedInformationDocument] = []
        if include_gdelt:
            gdelt, gdelt_documents = self._fetch_gdelt(start_date, end_date, channels)
            documents.extend(gdelt_documents)
        if include_cbr:
            cbr, cbr_documents = self._fetch_cbr(start_date, end_date)
            documents.extend(cbr_documents)
        digest_material = (
            information_channel_digest(channels)
            + start_date.isoformat()
            + end_date.isoformat()
            + str(include_gdelt)
            + str(include_cbr)
        )
        digest = hashlib.sha256(digest_material.encode("utf-8")).hexdigest()
        resolved_snapshot_id = snapshot_id or _snapshot_identifier(retrieved_at, digest)
        return self._persist_snapshot(
            resolved_snapshot_id,
            start_date,
            end_date,
            channels,
            gdelt,
            cbr,
            documents,
            retrieved_at,
        )


def _normalize_decision_times(decision_times: Sequence[Any] | pd.Series) -> pd.DataFrame:
    """Normalizuet unikal'nye timezone-aware momenty reshenii v UTC."""
    parsed: list[pd.Timestamp] = []
    for value in decision_times:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError("decision_at dolzhen byt' timezone-aware")
        parsed.append(timestamp.tz_convert("UTC"))
    if not parsed:
        raise ValueError("decision_times ne dolzhen byt' pustym")
    if len(parsed) != len(set(parsed)):
        raise ValueError("decision_times soderzhit povtory")
    return pd.DataFrame({"decision_at": sorted(parsed)})


def _rolling_past(
    values: pd.Series,
    dates: pd.Series,
    days: int,
    minimum_history: int,
    statistic: str,
) -> pd.Series:
    """Schitaet vremennuyu statistiku po strogo predshestvuyushchim datam."""
    indexed = pd.Series(values.to_numpy(dtype=float), index=pd.to_datetime(dates))
    rolling = indexed.rolling(f"{days}D", closed="left", min_periods=minimum_history)
    if statistic == "mean":
        result = rolling.mean()
    elif statistic == "std":
        result = rolling.std(ddof=0)
    else:
        raise ValueError(f"Neizvestnaya rolling statistika: {statistic}")
    return pd.Series(result.to_numpy(), index=values.index, dtype=float)


def _gdelt_features(
    gdelt: pd.DataFrame,
    short_days: int,
    long_days: int,
    minimum_history: int,
) -> pd.DataFrame:
    """Stroit share/tone change i surprise iz strogo proshlyh calendar windows."""
    required = {
        "channel_id",
        "observation_date",
        "available_at",
        "article_count",
        "norm",
        "article_share",
        "tone",
    }
    if not required.issubset(gdelt):
        raise ValueError(f"GDELT frame ne soderzhit {sorted(required - set(gdelt))}")
    frame = gdelt.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="raise")
    frame = frame.sort_values(["channel_id", "observation_date"], ignore_index=True)
    feature_frames: list[pd.DataFrame] = []
    for _, group in frame.groupby("channel_id", sort=True):
        local = group.copy()
        share_short_mean = _rolling_past(
            local["article_share"],
            local["observation_date"],
            short_days,
            minimum_history,
            "mean",
        )
        share_long_mean = _rolling_past(
            local["article_share"],
            local["observation_date"],
            long_days,
            minimum_history,
            "mean",
        )
        share_long_std = _rolling_past(
            local["article_share"],
            local["observation_date"],
            long_days,
            minimum_history,
            "std",
        )
        tone_short_mean = _rolling_past(
            local["tone"],
            local["observation_date"],
            short_days,
            minimum_history,
            "mean",
        )
        tone_long_mean = _rolling_past(
            local["tone"],
            local["observation_date"],
            long_days,
            minimum_history,
            "mean",
        )
        tone_long_std = _rolling_past(
            local["tone"],
            local["observation_date"],
            long_days,
            minimum_history,
            "std",
        )
        local["attention_change"] = local["article_share"] - share_short_mean
        local["attention_surprise"] = (
            (local["article_share"] - share_long_mean) / share_long_std.replace(0.0, np.nan)
        )
        local["tone_change"] = local["tone"] - tone_short_mean
        local["tone_surprise"] = (
            (local["tone"] - tone_long_mean) / tone_long_std.replace(0.0, np.nan)
        )
        feature_frames.append(local)
    return pd.concat(feature_frames, ignore_index=True)


def _asof_feature_block(
    decisions: pd.DataFrame,
    frame: pd.DataFrame,
    prefix: str,
    value_columns: Sequence[str],
) -> pd.DataFrame:
    """Prisoedinyaet poslednyuyu tol'ko uzhe dostupnuyu informaciyu k resheniyam."""
    selected = frame[["available_at", "observation_date", *value_columns]].copy()
    selected = selected.rename(
        columns={
            "available_at": f"{prefix}available_at",
            "observation_date": f"{prefix}observation_date",
            **{column: f"{prefix}{column}" for column in value_columns},
        }
    )
    right_time = f"{prefix}available_at"
    selected = selected.sort_values(right_time)
    merged = pd.merge_asof(
        decisions.sort_values("decision_at"),
        selected,
        left_on="decision_at",
        right_on=right_time,
        direction="backward",
        allow_exact_matches=True,
    )
    invalid = merged[right_time].notna() & (merged[right_time] > merged["decision_at"])
    if invalid.any():
        raise AssertionError("merge_asof propustil budushchuyu informaciyu")
    return merged.drop(columns="decision_at")


def build_causal_cbr_features(
    cbr: pd.DataFrame,
    decision_times: Sequence[Any] | pd.Series,
) -> pd.DataFrame:
    """Stroit CBR-only wide features, esli news source yavno nedostupen."""
    decisions = _normalize_decision_times(decision_times)
    required_cbr = {
        "series_id",
        "observation_date",
        "available_at",
        "value",
    }
    if not required_cbr.issubset(cbr):
        raise ValueError(f"CBR frame ne soderzhit {sorted(required_cbr - set(cbr))}")
    normalized_cbr = cbr.copy()
    normalized_cbr["available_at"] = pd.to_datetime(
        normalized_cbr["available_at"],
        errors="raise",
        utc=True,
    )
    normalized_cbr["observation_date"] = pd.to_datetime(
        normalized_cbr["observation_date"],
        errors="raise",
    )
    normalized_cbr = normalized_cbr.sort_values(
        ["series_id", "available_at"],
        ignore_index=True,
    )
    normalized_cbr["change"] = normalized_cbr.groupby("series_id")["value"].diff()
    output = decisions.copy()
    for series_id, group in normalized_cbr.groupby("series_id", sort=True):
        prefix = f"cbr_{series_id}_"
        block = _asof_feature_block(
            decisions,
            group,
            prefix,
            ("value", "change"),
        )
        output = pd.concat([output, block], axis=1)
    return output.loc[:, ~output.columns.duplicated()].reset_index(drop=True)


def build_causal_information_features(
    gdelt: pd.DataFrame,
    cbr: pd.DataFrame,
    decision_times: Sequence[Any] | pd.Series,
    *,
    short_days: int = DEFAULT_PAST_SHORT_DAYS,
    long_days: int = DEFAULT_PAST_LONG_DAYS,
    minimum_history: int = DEFAULT_MIN_HISTORY,
) -> pd.DataFrame:
    """Stroit wide features, dostupnye ne pozdnee kazhdogo decision timestamp."""
    if short_days <= 0 or long_days < short_days or minimum_history <= 0:
        raise ValueError("Nekorrektnye information rolling windows")
    decisions = _normalize_decision_times(decision_times)
    output = decisions.copy()
    gdelt_features = _gdelt_features(gdelt, short_days, long_days, minimum_history)
    for channel_id, group in gdelt_features.groupby("channel_id", sort=True):
        prefix = f"gdelt_{channel_id}_"
        block = _asof_feature_block(
            decisions,
            group,
            prefix,
            (
                "article_count",
                "norm",
                "article_share",
                "attention_change",
                "attention_surprise",
                "tone",
                "tone_change",
                "tone_surprise",
            ),
        )
        output = pd.concat([output, block], axis=1)
    cbr_features = build_causal_cbr_features(cbr, decisions["decision_at"])
    output = pd.concat(
        [output, cbr_features.drop(columns="decision_at")],
        axis=1,
    )
    return output.loc[:, ~output.columns.duplicated()].reset_index(drop=True)
