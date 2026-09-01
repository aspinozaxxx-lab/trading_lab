"""Acquire the official current-vintage Bank of Russia macro survey workbook."""

from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as wall_time
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Final, Protocol
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SOURCE_URL: Final[str] = "https://www.cbr.ru/statistics/ddkp/mo_br/"
WORKBOOK_URL: Final[str] = "https://www.cbr.ru/Content/Document/File/144490/full.xlsx"
SOURCE_START: Final[date] = date(2021, 5, 1)
SOURCE_END: Final[date] = date(2025, 12, 1)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/cbr-macro-survey-current-vintage-2021-2025-v1"
)
USER_AGENT: Final[str] = "market-lab-cbr-macro-survey/1.0 (causal research)"
MAX_WORKBOOK_BYTES: Final[int] = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES: Final[int] = 64 * 1024 * 1024
_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"cbr.ru", "www.cbr.ru"})
_MAIN_NS: Final[str] = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS: Final[str] = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS: Final[str] = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF: Final[re.Pattern[str]] = re.compile(r"^(?P<column>[A-Z]+)(?P<row>[1-9]\d*)$")
_SAFE_SNAPSHOT_ID: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ResponseLike(Protocol):
    """Minimal requests-compatible response used by production and tests."""

    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    """Minimal requests-compatible session used by production and tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """One stable workbook sheet and its normalized economic meaning."""

    sheet: str
    indicator: str
    english_name: str
    unit: str
    forecast_periods: bool = True


INDICATOR_SPECS: Final[tuple[IndicatorSpec, ...]] = (
    IndicatorSpec("1", "cpi_dec_to_dec_pct", "CPI", "percent"),
    IndicatorSpec("2", "cpi_average_yoy_pct", "CPI", "percent"),
    IndicatorSpec("3", "key_rate_average_pct", "Key rate", "percent_per_annum"),
    IndicatorSpec("4", "gdp_yoy_pct", "GDP", "percent_yoy"),
    IndicatorSpec("5", "unemployment_average_pct", "Unemployment rate", "percent"),
    IndicatorSpec("6", "unemployment_december_pct", "Unemployment rate", "percent"),
    IndicatorSpec("7", "nominal_wages_yoy_pct", "Nominal wages", "percent_yoy"),
    IndicatorSpec(
        "8",
        "consolidated_budget_balance_gdp_pct",
        "Consolidated budget balance",
        "percent_of_gdp",
    ),
    IndicatorSpec("9", "exports_goods_services_usd_bln", "Exports", "usd_billion"),
    IndicatorSpec("10", "imports_goods_services_usd_bln", "Imports", "usd_billion"),
    IndicatorSpec("11", "usd_rub_average", "USD / RUB rate", "rub_per_usd"),
    IndicatorSpec("12", "oil_tax_price_usd_bbl", "Oil price for tax", "usd_per_barrel"),
    IndicatorSpec("13", "brent_price_usd_bbl", "Brent oil price", "usd_per_barrel"),
    IndicatorSpec("14", "urals_price_usd_bbl", "Urals oil price", "usd_per_barrel"),
    IndicatorSpec("15", "russia_cds_5y_bp", "CDS spread 5Y", "basis_points"),
    IndicatorSpec(
        "16",
        "neutral_key_rate_pct",
        "Neutral key rate",
        "percent_per_annum",
        forecast_periods=False,
    ),
    IndicatorSpec(
        "17",
        "long_term_gdp_growth_pct",
        "Long-term GDP growth",
        "percent_yoy",
        forecast_periods=False,
    ),
)
STATISTIC_LABELS: Final[dict[str, str]] = {
    "Median": "median",
    "Average": "average",
    "Max": "maximum",
    "90th percentile": "p90",
    "3rd quartile": "p75",
    "1st quartile": "p25",
    "10th percentile": "p10",
    "Min": "minimum",
    "Total answers": "total_answers",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _official_url(value: str) -> str:
    absolute = urljoin(SOURCE_URL, value)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("CBR URL escaped the official HTTPS host")
    return absolute


class _WorkbookLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and href.lower().split("?", maxsplit=1)[0].endswith("/full.xlsx"):
            self.links.append(_official_url(href))


def workbook_url_from_page(content: bytes) -> str:
    """Recover the one official aggregated-results workbook link from the CBR page."""
    parser = _WorkbookLinkParser()
    parser.feed(content.decode("utf-8-sig"))
    links = sorted(set(parser.links))
    if links != [WORKBOOK_URL]:
        raise ValueError(f"unexpected CBR macro-survey workbook links: {links}")
    return links[0]


def _safe_zip_members(archive: zipfile.ZipFile) -> None:
    total = 0
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe path in CBR XLSX archive")
        total += item.file_size
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("CBR XLSX archive exceeds the uncompressed size limit")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read(path))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _normalize_sheet_target(target: str) -> str:
    normalized = PurePosixPath(target.lstrip("/"))
    if not normalized.parts or ".." in normalized.parts:
        raise ValueError("unsafe CBR workbook relationship target")
    if normalized.parts[0] != "xl":
        normalized = PurePosixPath("xl") / normalized
    return normalized.as_posix()


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.attrib["Id"]: _normalize_sheet_target(item.attrib["Target"])
        for item in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        name = sheet.attrib["name"]
        relationship_id = sheet.attrib[f"{{{_REL_NS}}}id"]
        if relationship_id not in targets:
            raise ValueError(f"CBR workbook sheet {name!r} has no relationship")
        result[name] = targets[relationship_id]
    return result


def _inline_text(cell: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))


def _sheet_cells(
    archive: zipfile.ZipFile,
    path: str,
    shared_strings: Sequence[str],
) -> dict[str, str]:
    root = ElementTree.fromstring(archive.read(path))
    cells: dict[str, str] = {}
    for cell in root.findall(f".//{{{_MAIN_NS}}}c"):
        reference = cell.attrib.get("r")
        if reference is None or _CELL_REF.fullmatch(reference) is None:
            raise ValueError("CBR workbook contains an invalid cell reference")
        kind = cell.attrib.get("t")
        if kind == "inlineStr":
            value = _inline_text(cell)
        else:
            value_node = cell.find(f"{{{_MAIN_NS}}}v")
            if value_node is None:
                continue
            value = value_node.text or ""
            if kind == "s":
                try:
                    value = shared_strings[int(value)]
                except (IndexError, ValueError) as error:
                    raise ValueError("invalid CBR shared-string reference") from error
            elif kind == "e":
                raise ValueError(f"CBR workbook contains an error cell at {reference}")
        if reference in cells:
            raise ValueError(f"duplicate CBR workbook cell: {reference}")
        cells[reference] = value
    return cells


def workbook_cells(content: bytes) -> dict[str, dict[str, str]]:
    """Read cached XLSX values with only the standard library and fail closed."""
    if not content.startswith(b"PK"):
        raise ValueError("CBR workbook is not an XLSX ZIP archive")
    if len(content) > MAX_WORKBOOK_BYTES:
        raise ValueError("CBR workbook exceeds the compressed size limit")
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            _safe_zip_members(archive)
            shared = _shared_strings(archive)
            paths = _sheet_paths(archive)
            return {
                name: _sheet_cells(archive, path, shared)
                for name, path in paths.items()
            }
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ValueError("CBR workbook has an invalid XLSX structure") from error


def _column_number(label: str) -> int:
    number = 0
    for character in label:
        number = number * 26 + ord(character) - ord("A") + 1
    return number


def _column_label(number: int) -> str:
    if number < 1:
        raise ValueError("column number must be positive")
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _maximum_column(cells: Mapping[str, str]) -> int:
    return max(
        _column_number(_CELL_REF.fullmatch(reference).group("column"))
        for reference in cells
    )


def _excel_date(value: str, *, field: str) -> date:
    try:
        serial = float(value)
    except ValueError as error:
        raise ValueError(f"CBR {field} is not an Excel date: {value!r}") from error
    if not math.isfinite(serial) or serial != int(serial):
        raise ValueError(f"CBR {field} must be a whole Excel date")
    result = (pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(serial))).date()
    if not 2000 <= result.year <= 2035:
        raise ValueError(f"CBR {field} date is outside the admitted range")
    return result


def conservative_available_at(survey_month: date) -> pd.Timestamp:
    """Admit a labeled survey only at the end of the following Moscow month."""
    if survey_month.day != 1:
        raise ValueError("CBR survey month must be represented by its first day")
    next_month_index = survey_month.month + 1
    next_year = survey_month.year + (next_month_index > 12)
    next_month = 1 if next_month_index > 12 else next_month_index
    end_day = calendar.monthrange(next_year, next_month)[1]
    local = datetime.combine(
        date(next_year, next_month, end_day),
        wall_time(23, 59, 59),
        tzinfo=MOSCOW,
    )
    return pd.Timestamp(local.astimezone(UTC))


def _survey_headers(
    cells: Mapping[str, str],
    *,
    first_column: int,
) -> list[tuple[str, date, str]]:
    headers: list[tuple[str, date, str]] = []
    seen: set[date] = set()
    for number in range(first_column, _maximum_column(cells) + 1):
        column = _column_label(number)
        raw_month = cells.get(f"{column}6")
        label = " ".join(cells.get(f"{column}7", "").split())
        if raw_month is None and not label:
            continue
        if raw_month is None or not label:
            raise ValueError(f"incomplete CBR survey header in column {column}")
        month = _excel_date(raw_month, field="survey month")
        if month.day != 1:
            raise ValueError("CBR survey header is not a month-start date")
        expected_label = month.strftime("%B %Y")
        if label != expected_label:
            raise ValueError(
                f"CBR survey label mismatch in {column}: {label!r} != {expected_label!r}"
            )
        if month in seen:
            raise ValueError(f"duplicate CBR survey month: {month}")
        seen.add(month)
        if SOURCE_START <= month <= SOURCE_END:
            headers.append((column, month, label))
    if not headers:
        raise ValueError("CBR workbook has no admitted survey columns")
    if headers != sorted(headers, key=lambda item: item[1]):
        raise ValueError("CBR survey columns are not chronological")
    return headers


def _optional_number(value: str | None, *, cell: str) -> float | None:
    if value is None or value.strip() in {"", "-"}:
        return None
    normalized = value.strip().replace("\u00a0", "").replace(",", ".")
    try:
        result = float(normalized)
    except ValueError as error:
        raise ValueError(f"CBR data cell {cell} is not numeric: {value!r}") from error
    if not math.isfinite(result):
        raise ValueError(f"CBR data cell {cell} is not finite")
    return result


def _statistic_rows(cells: Mapping[str, str]) -> list[tuple[int, str]]:
    maximum_row = max(int(_CELL_REF.fullmatch(reference).group("row")) for reference in cells)
    current: str | None = None
    rows: list[tuple[int, str]] = []
    for row in range(8, maximum_row + 1):
        label = " ".join(cells.get(f"C{row}", "").split())
        if label:
            if label not in STATISTIC_LABELS:
                continue
            current = STATISTIC_LABELS[label]
        if current is not None:
            rows.append((row, current))
    return rows


def _base_record(
    spec: IndicatorSpec,
    *,
    survey_month: date,
    survey_label: str,
    statistic: str,
    source_cell: str,
    retrieved_at_utc: str,
) -> dict[str, object]:
    return {
        "survey_month": pd.Timestamp(survey_month),
        "survey_label": survey_label,
        "available_at": conservative_available_at(survey_month),
        "indicator": spec.indicator,
        "indicator_name": spec.english_name,
        "unit": spec.unit,
        "statistic": statistic,
        "source_sheet": spec.sheet,
        "source_cell": source_cell,
        "source_url": WORKBOOK_URL,
        "retrieved_at_utc": pd.Timestamp(retrieved_at_utc),
        "current_vintage": True,
    }


def _forecast_records(
    spec: IndicatorSpec,
    cells: Mapping[str, str],
    *,
    retrieved_at_utc: str,
) -> list[dict[str, object]]:
    headers = _survey_headers(cells, first_column=5)
    records: list[dict[str, object]] = []
    for row, statistic in _statistic_rows(cells):
        raw_period = cells.get(f"D{row}")
        if raw_period is None:
            continue
        forecast_period = _excel_date(raw_period, field="forecast period")
        for column, survey_month, survey_label in headers:
            source_cell = f"{column}{row}"
            value = _optional_number(cells.get(source_cell), cell=source_cell)
            if value is None:
                continue
            records.append(
                {
                    **_base_record(
                        spec,
                        survey_month=survey_month,
                        survey_label=survey_label,
                        statistic=statistic,
                        source_cell=source_cell,
                        retrieved_at_utc=retrieved_at_utc,
                    ),
                    "forecast_period": pd.Timestamp(forecast_period),
                    "forecast_year": forecast_period.year,
                    "value": value,
                }
            )
    return records


def _scalar_records(
    spec: IndicatorSpec,
    cells: Mapping[str, str],
    *,
    retrieved_at_utc: str,
) -> list[dict[str, object]]:
    headers = _survey_headers(cells, first_column=4)
    records: list[dict[str, object]] = []
    for row, statistic in _statistic_rows(cells):
        for column, survey_month, survey_label in headers:
            source_cell = f"{column}{row}"
            value = _optional_number(cells.get(source_cell), cell=source_cell)
            if value is None:
                continue
            records.append(
                {
                    **_base_record(
                        spec,
                        survey_month=survey_month,
                        survey_label=survey_label,
                        statistic=statistic,
                        source_cell=source_cell,
                        retrieved_at_utc=retrieved_at_utc,
                    ),
                    "forecast_period": pd.NaT,
                    "forecast_year": None,
                    "value": value,
                }
            )
    return records


def parse_macro_survey_workbook(
    content: bytes,
    *,
    retrieved_at_utc: str,
    indicator_specs: Sequence[IndicatorSpec] = INDICATOR_SPECS,
) -> pd.DataFrame:
    """Normalize non-missing survey statistics without inventing historical vintages."""
    try:
        retrieved = pd.Timestamp(retrieved_at_utc)
    except ValueError as error:
        raise ValueError("invalid CBR retrieval timestamp") from error
    if retrieved.tzinfo is None:
        raise ValueError("CBR retrieval timestamp must be timezone-aware")
    sheets = workbook_cells(content)
    required = {spec.sheet for spec in indicator_specs}
    missing = required - set(sheets)
    if missing:
        raise ValueError(f"CBR workbook misses required sheets: {sorted(missing)}")
    records: list[dict[str, object]] = []
    for spec in indicator_specs:
        cells = sheets[spec.sheet]
        title = " ".join(cells.get("B5", "").split())
        if spec.english_name.casefold() not in title.casefold():
            raise ValueError(
                f"CBR sheet {spec.sheet} title mismatch: {title!r} lacks {spec.english_name!r}"
            )
        builder = _forecast_records if spec.forecast_periods else _scalar_records
        records.extend(builder(spec, cells, retrieved_at_utc=retrieved.isoformat()))
    if not records:
        raise ValueError("CBR workbook produced no normalized records")
    frame = pd.DataFrame(records)
    frame["value"] = pd.array(frame["value"], dtype="Float64")
    frame["forecast_year"] = pd.array(frame["forecast_year"], dtype="Int64")
    key = ["survey_month", "indicator", "statistic", "forecast_period"]
    if frame.duplicated(key, keep=False).any():
        raise ValueError("CBR normalized records contain duplicate economic keys")
    return frame.sort_values(
        ["survey_month", "indicator", "statistic", "forecast_period"],
        kind="mergesort",
        na_position="last",
        ignore_index=True,
    )


def _fetch(session: SessionLike, url: str) -> ResponseLike:
    response = session.get(
        _official_url(url),
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=60.0,
    )
    response.raise_for_status()
    return response


def _selected_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: str(headers[name])
        for name in ("Last-Modified", "Content-Type", "ETag")
        if name in headers
    }


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download_cbr_macro_survey(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
    minimum_records: int = 1_000,
) -> Path:
    """Write one immutable target-free source bundle; never overwrite an existing path."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"CBR macro-survey output already exists: {final}")
    if not _SAFE_SNAPSHOT_ID.fullmatch(final.name):
        raise ValueError("unsafe CBR macro-survey snapshot directory name")
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = session or requests.Session()
    page_response = _fetch(client, SOURCE_URL)
    discovered_workbook_url = workbook_url_from_page(page_response.content)
    workbook_response = _fetch(client, discovered_workbook_url)
    frame = parse_macro_survey_workbook(
        workbook_response.content,
        retrieved_at_utc=fetched_at,
    )
    if len(frame) < minimum_records:
        raise ValueError("CBR macro-survey normalized coverage is unexpectedly small")
    survey_months = sorted(frame["survey_month"].dt.date.unique().tolist())
    if survey_months[0] != SOURCE_START or survey_months[-1] != SOURCE_END:
        raise ValueError("CBR macro-survey interval bounds changed unexpectedly")
    if set(month.year for month in survey_months) != set(range(2021, 2026)):
        raise ValueError("CBR macro-survey does not cover every requested year")
    indicators = set(frame["indicator"].astype(str))
    if indicators != {spec.indicator for spec in INDICATOR_SPECS}:
        raise ValueError("CBR macro-survey indicator coverage is incomplete")
    required_signal_indicators = {
        "cpi_dec_to_dec_pct",
        "key_rate_average_pct",
        "gdp_yoy_pct",
        "usd_rub_average",
        "oil_tax_price_usd_bbl",
    }
    median = frame["statistic"].eq("median")
    if not required_signal_indicators.issubset(set(frame.loc[median, "indicator"])):
        raise ValueError("CBR macro-survey misses required median forecast channels")
    coverage = (
        frame.groupby(["survey_month", "indicator"], observed=True)
        .agg(
            available_at=("available_at", "first"),
            records=("value", "size"),
            median_records=("statistic", lambda values: int(values.eq("median").sum())),
            minimum_forecast_year=("forecast_year", "min"),
            maximum_forecast_year=("forecast_year", "max"),
        )
        .reset_index()
        .sort_values(["survey_month", "indicator"], ignore_index=True)
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "cbr_macro_survey_forecasts.parquet"
        coverage_path = temporary / "coverage.parquet"
        workbook_path = temporary / "official_cbr_macro_survey_current_vintage.xlsx"
        page_path = temporary / "official_cbr_macro_survey_page.html.gz"
        _atomic_parquet(data_path, frame)
        _atomic_parquet(coverage_path, coverage)
        atomic_write_bytes(workbook_path, workbook_response.content)
        atomic_write_bytes(
            page_path,
            gzip.compress(page_response.content, compresslevel=6, mtime=0),
        )
        year_counts = Counter(month.year for month in survey_months)
        indicator_counts = Counter(frame["indicator"].astype(str))
        availability = frame[["survey_month", "available_at"]].drop_duplicates()
        before_boundary = availability["available_at"].lt(PROTECTED_FROM)
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-cbr-macro-survey-current-vintage-2021-2025-v1",
            "provider": "Bank of Russia",
            "source_name": "Macroeconomic survey of analysts, aggregated results",
            "source_url": SOURCE_URL,
            "workbook_url": discovered_workbook_url,
            "fetched_at_utc": fetched_at,
            "request_count": 2,
            "response_headers": {
                "page": _selected_headers(page_response.headers),
                "workbook": _selected_headers(workbook_response.headers),
            },
            "coverage": {
                "records": len(frame),
                "survey_months": len(survey_months),
                "survey_months_by_year": {
                    str(year): year_counts[year] for year in sorted(year_counts)
                },
                "minimum_survey_month": survey_months[0].isoformat(),
                "maximum_survey_month": survey_months[-1].isoformat(),
                "minimum_available_at": frame["available_at"].min().isoformat(),
                "maximum_available_at": frame["available_at"].max().isoformat(),
                "survey_months_available_before_protected_boundary": int(
                    before_boundary.sum()
                ),
                "indicator_record_counts": dict(sorted(indicator_counts.items())),
                "statistics": sorted(frame["statistic"].unique().tolist()),
            },
            "temporal_semantics": {
                "survey_month": "month label embedded in the official aggregated workbook",
                "available_at": (
                    "23:59:59 Europe/Moscow on the last calendar day of the month "
                    "following survey_month"
                ),
                "availability_is_deliberately_later_than_typical_publication": True,
                "admissible_join": "available_at less than or equal to decision_at",
                "current_vintage_historical_record": True,
                "original_historical_workbook_vintages_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_prices_returns_targets_labels_or_pnl": False,
                "missing_workbook_cells_are_not_zero": True,
            },
            "source_quality": {
                "official_page_points_to_expected_workbook": True,
                "all_17_indicator_sheets_present": True,
                "survey_columns_strictly_chronological": True,
                "duplicate_economic_keys": 0,
                "future_survey_columns_filtered_from_processed_data": True,
            },
            "rights": {
                "redistribution_license_verified": False,
                "raw_stored_outside_git": True,
            },
            "artifacts": {
                "processed": {
                    "path": data_path.name,
                    "bytes": data_path.stat().st_size,
                    "sha256": sha256_file(data_path),
                    "rows": len(frame),
                    "columns": frame.columns.tolist(),
                },
                "coverage": {
                    "path": coverage_path.name,
                    "bytes": coverage_path.stat().st_size,
                    "sha256": sha256_file(coverage_path),
                    "rows": len(coverage),
                },
                "raw_workbook": {
                    "path": workbook_path.name,
                    "bytes": workbook_path.stat().st_size,
                    "sha256": sha256_file(workbook_path),
                },
                "raw_page": {
                    "path": page_path.name,
                    "bytes": page_path.stat().st_size,
                    "sha256": sha256_file(page_path),
                },
            },
        }
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {
                **manifest_core,
                "manifest_payload_sha256": sha256_bytes(_canonical_json(manifest_core)),
            },
        )
        manifest_sha = sha256_file(manifest_path)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{manifest_sha}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-records", type=int, default=1_000)
    arguments = parser.parse_args()
    print(
        download_cbr_macro_survey(
            arguments.output_directory,
            minimum_records=arguments.minimum_records,
        )
    )


if __name__ == "__main__":
    main()
