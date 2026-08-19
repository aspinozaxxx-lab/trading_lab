"""Kausal'nyi CFTC COT radar dlya zapechatannyh ekonomicheskih kanalov."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from market_lab.io_utils import atomic_write_bytes, write_json

CFTC_RADAR_VERSION: Final = "cftc-cot-radar-v1"  # Versiya zapechatannoi skhemy.
CFTC_ROUTER_VERSION: Final = "cftc-asset-router-v1"  # Versiya causal asset mapping.
CFTC_HISTORICAL_INDEX_URL: Final = (  # Oficial'nyi katalog godovyh COT arhivov.
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm"
)
CFTC_RELEASE_SCHEDULE_URL: Final = (  # Oficial'noe opisanie vremeni reliza COT.
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm"
)
CFTC_SPECIAL_ANNOUNCEMENTS_URL: Final = (  # Oficial'nyi zhurnal zaderzhek/revisions.
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
    "HistoricalSpecialAnnouncements/index.htm"
)
CFTC_BULK_ROOT: Final = (  # Oficial'nyi koren stabil'nyh ZIP endpointov CFTC.
    "https://www.cftc.gov/files/dea/history"
)
CFTC_DISAGGREGATED_FUTURES_ONLY: Final = (  # Natural-resource futures-only report.
    "disaggregated_futures_only"
)
CFTC_TFF_FUTURES_ONLY: Final = "tff_futures_only"  # Financial futures-only report.
CFTC_MIN_YEAR: Final = 2018  # Pervyi razreshennyi god development istorii.
CFTC_MAX_YEAR: Final = 2025  # Poslednii razreshennyi god development istorii.
CFTC_PROTECTED_FROM: Final = date(2026, 1, 1)  # Granica fizicheski netronutogo holdout.
CFTC_RELEASE_TIME: Final = time(15, 30)  # Oficial'noe vremya reliza po Eastern Time.
CFTC_RELEASE_ZONE: Final = ZoneInfo("America/New_York")  # DST-aware zona reliza CFTC.
CFTC_CONSERVATIVE_LAG_SESSIONS: Final = 1  # Dobavochnyi MOEX lag tol'ko dlya ambiguity.
CFTC_MAX_ARCHIVE_BYTES: Final = 16 * 1024 * 1024  # Fail-closed limit syrogo ZIP.
CFTC_MAX_CSV_BYTES: Final = 128 * 1024 * 1024  # Fail-closed limit raspakovannogo CSV.
CFTC_FUTURES_ONLY_COLUMN: Final = "FutOnly_or_Combined"  # Documented format flag.
CFTC_FUTURES_ONLY_VALUE: Final = "FutOnly"  # Edinstvenno dopustimyi format reporta.
CFTC_SNAPSHOT_ID_PATTERN: Final = re.compile(  # Bezopasnoe append-only imya snapshot.
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
)
CFTC_AVAILABILITY_RULE: Final = (  # Audit-opisanie standardnoi dostupnosti.
    "first_moex_decision_strictly_after_release_timestamp"
)
CFTC_AMBIGUOUS_AVAILABILITY_RULE: Final = (  # Pravilo dlya holiday ambiguity.
    "first_moex_decision_strictly_after_release_timestamp_plus_one_session"
)

CftcReportKind = Literal[  # Zakrytyi nabor razreshennyh tipov oficial'nogo reporta.
    "disaggregated_futures_only",
    "tff_futures_only",
]


@dataclass(frozen=True, slots=True)
class CftcCategorySpec:
    """Svyazyvaet stabil'nuyu kategoriyu s dvumya kolonami CFTC."""

    category: str
    long_column: str
    short_column: str

    def __post_init__(self) -> None:
        """Proveryaet nepustye imena kategorii i ishodnyh kolonok."""
        if not self.category or not self.long_column or not self.short_column:
            raise ValueError("CFTC category spec ne mozhet byt' pustym")


@dataclass(frozen=True, slots=True)
class CftcMarketSpec:
    """Fiksiruet odin dopushchennyi CFTC contract market i ego aliases."""

    market_id: str
    economic_channel: str
    report_kind: CftcReportKind
    contract_code: str
    allowed_names: tuple[str, ...]
    categories: tuple[CftcCategorySpec, ...]

    def __post_init__(self) -> None:
        """Zapreshchaet nepolnyi ili rasshirennyi bez audita market spec."""
        if self.report_kind not in {
            CFTC_DISAGGREGATED_FUTURES_ONLY,
            CFTC_TFF_FUTURES_ONLY,
        }:
            raise ValueError(f"Neizvestnyi CFTC report kind: {self.report_kind}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.market_id):
            raise ValueError(f"Nekorrektnyi CFTC market_id: {self.market_id}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.economic_channel):
            raise ValueError(f"Nekorrektnyi CFTC channel: {self.economic_channel}")
        if not re.fullmatch(r"[A-Z0-9+]{6}", self.contract_code):
            raise ValueError(f"Nekorrektnyi CFTC contract code: {self.contract_code}")
        if not self.allowed_names or not self.categories:
            raise ValueError("CFTC market spec dolzhen imet' aliases i kategorii")


DISAGGREGATED_CATEGORIES: Final = (  # Kategorii oficial'nogo Disaggregated report.
    CftcCategorySpec(
        "producer_merchant",
        "Prod_Merc_Positions_Long_All",
        "Prod_Merc_Positions_Short_All",
    ),
    CftcCategorySpec(
        "swap_dealer",
        "Swap_Positions_Long_All",
        "Swap__Positions_Short_All",
    ),
    CftcCategorySpec(
        "managed_money",
        "M_Money_Positions_Long_All",
        "M_Money_Positions_Short_All",
    ),
    CftcCategorySpec(
        "other_reportables",
        "Other_Rept_Positions_Long_All",
        "Other_Rept_Positions_Short_All",
    ),
)
TFF_CATEGORIES: Final = (  # Kategorii oficial'nogo Traders in Financial Futures report.
    CftcCategorySpec(
        "dealer_intermediary",
        "Dealer_Positions_Long_All",
        "Dealer_Positions_Short_All",
    ),
    CftcCategorySpec(
        "asset_manager",
        "Asset_Mgr_Positions_Long_All",
        "Asset_Mgr_Positions_Short_All",
    ),
    CftcCategorySpec(
        "leveraged_money",
        "Lev_Money_Positions_Long_All",
        "Lev_Money_Positions_Short_All",
    ),
    CftcCategorySpec(
        "other_reportables",
        "Other_Rept_Positions_Long_All",
        "Other_Rept_Positions_Short_All",
    ),
)

CFTC_MARKETS: Final = (  # Allowlist, zapechatannyi do lyubogo OOS analiza.
    CftcMarketSpec(
        market_id="wti",
        economic_channel="energy_positioning",
        report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
        contract_code="067651",
        allowed_names=(
            "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
            "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE",
        ),
        categories=DISAGGREGATED_CATEGORIES,
    ),
    CftcMarketSpec(
        market_id="brent",
        economic_channel="energy_positioning",
        report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
        contract_code="06765T",
        allowed_names=(
            "BRENT CRUDE OIL LAST DAY - NEW YORK MERCANTILE EXCHANGE",
            "BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE",
        ),
        categories=DISAGGREGATED_CATEGORIES,
    ),
    CftcMarketSpec(
        market_id="usd_index",
        economic_channel="usd_positioning",
        report_kind=CFTC_TFF_FUTURES_ONLY,
        contract_code="098662",
        allowed_names=(
            "U.S. DOLLAR INDEX - ICE FUTURES U.S.",
            "USD INDEX - ICE FUTURES U.S.",
        ),
        categories=TFF_CATEGORIES,
    ),
    CftcMarketSpec(
        market_id="emini_sp500",
        economic_channel="equity_risk_positioning",
        report_kind=CFTC_TFF_FUTURES_ONLY,
        contract_code="13874A",
        allowed_names=(
            "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
            "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        ),
        categories=TFF_CATEGORIES,
    ),
    CftcMarketSpec(
        market_id="emini_nasdaq100",
        economic_channel="equity_risk_positioning",
        report_kind=CFTC_TFF_FUTURES_ONLY,
        contract_code="209742",
        allowed_names=(
            "NASDAQ-100 STOCK INDEX (MINI) - CHICAGO MERCANTILE EXCHANGE",
            "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
        ),
        categories=TFF_CATEGORIES,
    ),
)
CFTC_MARKETS_BY_KIND_CODE: Final = {  # Poisk spec tol'ko po report kind i exact code.
    (spec.report_kind, spec.contract_code): spec for spec in CFTC_MARKETS
}
CFTC_MARKETS_BY_ID: Final = {  # Determinirovannyi poisk spec po market_id.
    spec.market_id: spec for spec in CFTC_MARKETS
}
CFTC_CHANNEL_COMPONENTS: Final = {  # Tri ekonomicheskih kanala i primary kategorii.
    "energy_positioning": (("wti", "managed_money"), ("brent", "managed_money")),
    "usd_positioning": (("usd_index", "leveraged_money"),),
    "equity_risk_positioning": (
        ("emini_sp500", "leveraged_money"),
        ("emini_nasdaq100", "leveraged_money"),
    ),
}
CFTC_CHANNEL_SIGNAL_FORMULA: Final = (  # Fixed ex-ante nonlinear channel transform.
    "tanh(2*net_oi+4*change)"
)
CFTC_ASSET_SCORE_WEIGHTS: Final = {  # Fixed ex-ante channel-to-asset router weights.
    "SI": (("usd_positioning", 1.0), ("equity_risk_positioning", -0.20)),
    "RI": (
        ("equity_risk_positioning", 0.75),
        ("energy_positioning", 0.15),
        ("usd_positioning", -0.10),
    ),
    "BR": (("energy_positioning", 1.0), ("equity_risk_positioning", 0.10)),
    "MIX": (
        ("equity_risk_positioning", 0.75),
        ("energy_positioning", 0.15),
        ("usd_positioning", -0.10),
    ),
}
CFTC_ASSET_SCORE_FORMULAS: Final = {  # Audit-formuly s explicit final clipping.
    "SI": "clip(1.00*usd_positioning-0.20*equity_risk_positioning,-1,1)",
    "RI": (
        "clip(0.75*equity_risk_positioning+0.15*energy_positioning"
        "-0.10*usd_positioning,-1,1)"
    ),
    "BR": "clip(1.00*energy_positioning+0.10*equity_risk_positioning,-1,1)",
    "MIX": (
        "clip(0.75*equity_risk_positioning+0.15*energy_positioning"
        "-0.10*usd_positioning,-1,1)"
    ),
}
CFTC_2025_SHUTDOWN_PUBLICATION_DATES: Final = {  # Final accelerated CFTC schedule.
    date(2025, 9, 30): date(2025, 11, 19),
    date(2025, 10, 7): date(2025, 11, 21),
    date(2025, 10, 14): date(2025, 11, 25),
    date(2025, 10, 21): date(2025, 12, 2),
    date(2025, 10, 28): date(2025, 12, 5),
    date(2025, 11, 4): date(2025, 12, 9),
    date(2025, 11, 10): date(2025, 12, 10),
    date(2025, 11, 18): date(2025, 12, 12),
    date(2025, 11, 25): date(2025, 12, 15),
    date(2025, 12, 2): date(2025, 12, 17),
    date(2025, 12, 9): date(2025, 12, 19),
    date(2025, 12, 16): date(2025, 12, 23),
    date(2025, 12, 23): date(2025, 12, 29),
}
CFTC_DEVELOPMENT_PUBLICATION_DATES: Final = {  # Tochnye nestandartnye relizy development.
    date(2018, 12, 24): date(2019, 2, 1),
    date(2018, 12, 31): date(2019, 2, 5),
    date(2019, 1, 8): date(2019, 2, 8),
    date(2019, 1, 15): date(2019, 2, 12),
    date(2019, 1, 22): date(2019, 2, 15),
    date(2019, 1, 29): date(2019, 2, 19),
    date(2019, 2, 5): date(2019, 2, 22),
    date(2019, 2, 12): date(2019, 2, 26),
    date(2019, 2, 19): date(2019, 3, 1),
    date(2019, 2, 26): date(2019, 3, 5),
    date(2020, 12, 21): date(2020, 12, 28),
    date(2021, 6, 15): date(2021, 6, 21),
    date(2023, 1, 31): date(2023, 2, 24),
    date(2023, 2, 7): date(2023, 3, 3),
    date(2023, 2, 14): date(2023, 3, 8),
    date(2023, 2, 21): date(2023, 3, 10),
    date(2023, 2, 28): date(2023, 3, 14),
    date(2023, 3, 7): date(2023, 3, 16),
    date(2023, 3, 14): date(2023, 3, 21),
    date(2023, 7, 3): date(2023, 7, 7),
    date(2025, 1, 7): date(2025, 1, 13),
    **CFTC_2025_SHUTDOWN_PUBLICATION_DATES,
}
CFTC_2019_DELAYED_REPORT_URL_TEMPLATE: Final = (  # Oficial'noe dokazatel'stvo reporta.
    "https://www.cftc.gov/sites/default/files/files/dea/cotarchives/"
    "{year}/futures/financial_lf{report_stamp}.htm"
)
CFTC_2023_JULY_REPORT_URL: Final = (  # Oficial'nyi report s dannymi ponedel'nika.
    "https://www.cftc.gov/files/dea/cotarchives/2023/futures/financial_lf070323.htm"
)
CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS: Final = {  # Oficial'nyi source dlya kazhdoi daty.
    **{
        report_date: CFTC_2019_DELAYED_REPORT_URL_TEMPLATE.format(
            year=report_date.year,
            report_stamp=report_date.strftime("%m%d%y"),
        )
        for report_date in (
            date(2018, 12, 24),
            date(2018, 12, 31),
            date(2019, 1, 8),
            date(2019, 1, 15),
            date(2019, 1, 22),
            date(2019, 1, 29),
            date(2019, 2, 5),
            date(2019, 2, 12),
            date(2019, 2, 19),
            date(2019, 2, 26),
        )
    },
    date(2020, 12, 21): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2021, 6, 15): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 1, 31): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 2, 7): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 2, 14): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 2, 21): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 2, 28): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 3, 7): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 3, 14): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    date(2023, 7, 3): CFTC_2023_JULY_REPORT_URL,
    date(2025, 1, 7): CFTC_SPECIAL_ANNOUNCEMENTS_URL,
    **{
        report_date: CFTC_SPECIAL_ANNOUNCEMENTS_URL
        for report_date in CFTC_2025_SHUTDOWN_PUBLICATION_DATES
    },
}
CFTC_EXACT_RELEASE_REQUIRED_DATES: Final = frozenset(  # Known nonstandard releases.
    CFTC_DEVELOPMENT_PUBLICATION_DATES
)
CFTC_BULK_PREFIX_BY_KIND: Final = {  # Fiksirovannye imena oficial'nyh godovyh ZIP.
    CFTC_DISAGGREGATED_FUTURES_ONLY: "fut_disagg_txt",
    CFTC_TFF_FUTURES_ONLY: "fut_fin_txt",
}
CFTC_DATE_COLUMNS_BY_KIND: Final = {  # Documented aliases daty v static CSV.
    CFTC_DISAGGREGATED_FUTURES_ONLY: (
        "Report_Date_as_YYYY-MM-DD",
        "As_of_Date_Form_YYYY-MM-DD",
        "As_of_Date_In_Form_YYMMDD",
    ),
    CFTC_TFF_FUTURES_ONLY: (
        "Report_Date_as_MM_DD_YYYY",
        "As_of_Date_In_Form_YYMMDD",
        "Report_Date_as_YYYY-MM-DD",
    ),
}
CFTC_BASE_RECORD_COLUMNS: Final = (  # Minimal'naya normalized skhema position records.
    "report_date",
    "report_kind",
    "market_id",
    "economic_channel",
    "contract_code",
    "market_name",
    "category",
    "open_interest",
    "long_positions",
    "short_positions",
    "source_url",
    "archive_sha256",
    "csv_sha256",
    "revision_id",
    "radar_version",
)
CFTC_HISTORY_COLUMNS: Final = (  # Audit-skhema category/OI i causal weekly change.
    *CFTC_BASE_RECORD_COLUMNS,
    "net_positions",
    "net_share_oi",
    "net_share_oi_change",
)


@dataclass(frozen=True, slots=True)
class CftcArchiveProvenance:
    """Hranit source, oba hasha i versioned revision odnogo arhiva."""

    report_kind: CftcReportKind
    year: int
    source_url: str
    fetched_at: datetime
    member_name: str
    archive_sha256: str
    csv_sha256: str
    archive_bytes: int
    csv_bytes: int
    revision_id: str
    http_etag: str | None = None
    http_last_modified: str | None = None

    def __post_init__(self) -> None:
        """Proveryaet exact official URL, timezone i kriptograficheskie hashi."""
        if self.source_url != cftc_bulk_url(self.year, self.report_kind):
            raise ValueError("CFTC provenance soderzhit neoficial'nyi ili neexact URL")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("CFTC fetched_at dolzhen byt' timezone-aware")
        if not re.fullmatch(r"[0-9a-f]{64}", self.archive_sha256):
            raise ValueError("Nekorrektnyi CFTC archive SHA-256")
        if not re.fullmatch(r"[0-9a-f]{64}", self.csv_sha256):
            raise ValueError("Nekorrektnyi CFTC CSV SHA-256")
        if not re.fullmatch(r"[0-9a-f]{64}", self.revision_id):
            raise ValueError("Nekorrektnyi CFTC revision id")
        if self.archive_bytes <= 0 or self.csv_bytes <= 0:
            raise ValueError("CFTC provenance ne mozhet ssylat'sya na pustye bytes")


@dataclass(frozen=True, slots=True)
class ParsedCftcArchive:
    """Peredaet proverennye raw bytes, provenance i allowlisted records."""

    provenance: CftcArchiveProvenance
    archive_content: bytes
    csv_content: bytes
    records: pd.DataFrame


@dataclass(frozen=True, slots=True)
class CftcSnapshotResult:
    """Vozvrashchaet puti gotovogo atomarnogo append-only snapshot."""

    snapshot_id: str
    snapshot_path: Path
    manifest_path: Path
    processed_path: Path
    rows: int


def cftc_bulk_url(year: int, report_kind: CftcReportKind) -> str:
    """Stroit exact official annual ZIP URL tol'ko dlya development let."""
    _validate_development_year(year)
    try:
        prefix = CFTC_BULK_PREFIX_BY_KIND[report_kind]
    except KeyError as error:
        raise ValueError(f"Neizvestnyi CFTC report kind: {report_kind}") from error
    return f"{CFTC_BULK_ROOT}/{prefix}_{year}.zip"


def nominal_cftc_release_at(report_date: date | pd.Timestamp) -> pd.Timestamp:
    """Prevrashchaet report date v sleduyushchuyu pyatnicu 15:30 Eastern."""
    normalized = _normalize_report_date(report_date)
    days_to_friday = (4 - normalized.weekday()) % 7
    release_date = normalized + timedelta(days=days_to_friday)
    local_release = datetime.combine(release_date, CFTC_RELEASE_TIME, CFTC_RELEASE_ZONE)
    return pd.Timestamp(local_release.astimezone(UTC))


def official_2025_shutdown_release_overrides() -> dict[date, pd.Timestamp]:
    """Vozvrashchaet final CFTC backlog dates v official 15:30 America/New_York."""
    return {
        report_date: pd.Timestamp(
            datetime.combine(publication_date, CFTC_RELEASE_TIME, CFTC_RELEASE_ZONE).astimezone(
                UTC
            )
        )
        for report_date, publication_date in CFTC_2025_SHUTDOWN_PUBLICATION_DATES.items()
    }


def official_development_release_overrides() -> dict[date, pd.Timestamp]:
    """Vozvrashchaet vse frozen special releases 2018-2025 v 15:30 Eastern."""
    if set(CFTC_DEVELOPMENT_PUBLICATION_DATES) != set(
        CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS
    ):
        raise RuntimeError("CFTC special release dates i official sources raskhodjatsya")
    if set(CFTC_DEVELOPMENT_PUBLICATION_DATES) != set(
        CFTC_EXACT_RELEASE_REQUIRED_DATES
    ):
        raise RuntimeError("CFTC special release overrides nepolny")
    return {
        report_date: pd.Timestamp(
            datetime.combine(
                publication_date,
                CFTC_RELEASE_TIME,
                CFTC_RELEASE_ZONE,
            ).astimezone(UTC)
        )
        for report_date, publication_date in CFTC_DEVELOPMENT_PUBLICATION_DATES.items()
    }


def parse_cftc_archive(
    content: bytes,
    *,
    year: int,
    report_kind: CftcReportKind,
    fetched_at: datetime,
    source_url: str | None = None,
    http_etag: str | None = None,
    http_last_modified: str | None = None,
    require_complete: bool = True,
) -> ParsedCftcArchive:
    """Chitaet odin official annual ZIP bez seti i filtruet strict allowlist."""
    expected_url = cftc_bulk_url(year, report_kind)
    resolved_url = source_url or expected_url
    if resolved_url != expected_url:
        raise ValueError("Razreshen tol'ko exact official CFTC annual URL")
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at dolzhen byt' timezone-aware")
    if not content or len(content) > CFTC_MAX_ARCHIVE_BYTES:
        raise ValueError("Pustoi ili slishkom bol'shoi CFTC ZIP")
    archive_sha256 = hashlib.sha256(content).hexdigest()
    csv_content, member_name = _read_single_cftc_csv(content)
    csv_sha256 = hashlib.sha256(csv_content).hexdigest()
    revision_payload = (
        f"{report_kind}\n{year}\n{resolved_url}\n{archive_sha256}\n{csv_sha256}"
    ).encode("ascii")
    revision_id = hashlib.sha256(revision_payload).hexdigest()
    provenance = CftcArchiveProvenance(
        report_kind=report_kind,
        year=year,
        source_url=resolved_url,
        fetched_at=fetched_at,
        member_name=member_name,
        archive_sha256=archive_sha256,
        csv_sha256=csv_sha256,
        archive_bytes=len(content),
        csv_bytes=len(csv_content),
        revision_id=revision_id,
        http_etag=http_etag,
        http_last_modified=http_last_modified,
    )
    records = _parse_cftc_csv_records(
        csv_content,
        provenance,
        require_complete=require_complete,
    )
    return ParsedCftcArchive(
        provenance=provenance,
        archive_content=content,
        csv_content=csv_content,
        records=records,
    )


def build_cftc_position_history(
    records: pd.DataFrame | Sequence[pd.DataFrame],
) -> pd.DataFrame:
    """Schitaet net/OI i ego causal change posle obedineniya godovyh arhivov."""
    if isinstance(records, pd.DataFrame):
        combined = records.copy()
    else:
        frames = [frame.copy() for frame in records]
        if not frames:
            return pd.DataFrame(columns=CFTC_HISTORY_COLUMNS)
        combined = pd.concat(frames, ignore_index=True)
    missing = set(CFTC_BASE_RECORD_COLUMNS) - set(combined.columns)
    if missing:
        raise ValueError(f"CFTC records ne soderzhat kolonok: {sorted(missing)}")
    combined = combined.loc[:, CFTC_BASE_RECORD_COLUMNS].copy()
    combined["report_date"] = [
        pd.Timestamp(_normalize_report_date(value)) for value in combined["report_date"]
    ]
    for column in ("open_interest", "long_positions", "short_positions"):
        combined[column] = pd.to_numeric(combined[column], errors="coerce")
        if (~np.isfinite(combined[column])).any():
            raise ValueError(f"CFTC {column} soderzhit non-finite znachenie")
    if (combined["open_interest"] <= 0.0).any():
        raise ValueError("CFTC open interest dolzhen byt' > 0")
    if (combined[["long_positions", "short_positions"]] < 0.0).any(axis=None):
        raise ValueError("CFTC positions ne mogut byt' otricatel'nymi")
    key = ["report_date", "market_id", "category"]
    if combined.duplicated(key).any():
        raise ValueError("CFTC history soderzhit duplicate market/category/report date")
    combined = combined.sort_values(key, kind="stable", ignore_index=True)
    combined["net_positions"] = combined["long_positions"] - combined["short_positions"]
    combined["net_share_oi"] = combined["net_positions"] / combined["open_interest"]
    combined["net_share_oi_change"] = combined.groupby(
        ["market_id", "category"],
        sort=False,
    )["net_share_oi"].diff()
    return combined.loc[:, CFTC_HISTORY_COLUMNS]


def attach_cftc_availability(
    history: pd.DataFrame,
    moex_decision_times: Sequence[object] | pd.Series | pd.DatetimeIndex,
    *,
    release_overrides: Mapping[object, object] | None = None,
    ambiguous_report_dates: Iterable[object] = (),
) -> pd.DataFrame:
    """Naznachaet as-of dostupnost' po factual MOEX decisions posle CFTC release."""
    frame = build_cftc_position_history(history)
    decisions = _normalize_decision_times(moex_decision_times)
    overrides = _normalize_release_overrides(release_overrides or {})
    ambiguous = {_normalize_report_date(value) for value in ambiguous_report_dates}
    if set(overrides) & ambiguous:
        raise ValueError("Exact CFTC release override ne mozhet byt' odnovremenno ambiguous")
    observed_report_days = {value.date() for value in frame["report_date"].unique()}
    unknown_timing_dates = (set(overrides) | ambiguous) - observed_report_days
    if unknown_timing_dates:
        raise ValueError(
            f"CFTC timing metadata ssylayutsya na otsutstvuyushchie daty: "
            f"{sorted(unknown_timing_dates)}"
        )
    missing_exact_overrides = (
        observed_report_days & CFTC_EXACT_RELEASE_REQUIRED_DATES
    ) - set(overrides)
    if missing_exact_overrides:
        raise ValueError(
            "CFTC known special release dates trebuyut exact official overrides: "
            f"{sorted(missing_exact_overrides)}"
        )
    release_by_date: dict[pd.Timestamp, pd.Timestamp] = {}
    available_by_date: dict[pd.Timestamp, pd.Timestamp | pd.NaT] = {}
    exact_by_date: dict[pd.Timestamp, bool] = {}
    source_by_date: dict[pd.Timestamp, str] = {}
    source_url_by_date: dict[pd.Timestamp, str] = {}
    lag_by_date: dict[pd.Timestamp, int] = {}
    rule_by_date: dict[pd.Timestamp, str] = {}
    decision_values = decisions.asi8
    for report_timestamp in frame["report_date"].drop_duplicates():
        report_day = report_timestamp.date()
        if report_day in overrides:
            release_at = overrides[report_day]
            release_exact = True
            release_source = "exact_official_override"
            release_source_url = CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS.get(
                report_day,
                "caller_supplied_unverified",
            )
        else:
            if report_day.weekday() != 1:
                raise ValueError(
                    "Netipichnaya CFTC report date trebuet exact release override"
                )
            release_at = nominal_cftc_release_at(report_timestamp)
            release_exact = False
            release_source = "official_standard_friday_schedule"
            release_source_url = CFTC_RELEASE_SCHEDULE_URL
        lag_sessions = CFTC_CONSERVATIVE_LAG_SESSIONS if report_day in ambiguous else 0
        first_later = int(np.searchsorted(decision_values, release_at.value, side="right"))
        usable_index = first_later + lag_sessions
        available_at: pd.Timestamp | pd.NaT = (
            pd.NaT if usable_index >= len(decisions) else decisions[usable_index]
        )
        release_by_date[report_timestamp] = release_at
        available_by_date[report_timestamp] = available_at
        exact_by_date[report_timestamp] = release_exact
        source_by_date[report_timestamp] = release_source
        source_url_by_date[report_timestamp] = release_source_url
        lag_by_date[report_timestamp] = lag_sessions
        rule_by_date[report_timestamp] = (
            CFTC_AMBIGUOUS_AVAILABILITY_RULE
            if lag_sessions
            else CFTC_AVAILABILITY_RULE
        )
    result = frame.copy()
    result["release_at"] = result["report_date"].map(release_by_date)
    result["available_at"] = result["report_date"].map(available_by_date)
    result["availability_rule"] = result["report_date"].map(rule_by_date)
    result["release_timing_exact"] = result["report_date"].map(exact_by_date)
    result["release_timestamp_source"] = result["report_date"].map(source_by_date)
    result["release_source_url"] = result["report_date"].map(source_url_by_date)
    result["holiday_or_timezone_ambiguous"] = result["report_date"].map(
        lambda value: value.date() in ambiguous
    )
    result["conservative_lag_sessions"] = result["report_date"].map(lag_by_date)
    result["approximate"] = True
    result["research_only"] = True
    return result


def build_causal_cftc_features(
    history: pd.DataFrame,
    moex_decision_times: Sequence[object] | pd.Series | pd.DatetimeIndex,
    *,
    release_overrides: Mapping[object, object] | None = None,
    ambiguous_report_dates: Iterable[object] = (),
) -> pd.DataFrame:
    """Stroit wide as-of features i tri zapechatannyh ekonomicheskih kanala."""
    decisions = _normalize_decision_times(moex_decision_times)
    available = attach_cftc_availability(
        history,
        decisions,
        release_overrides=release_overrides,
        ambiguous_report_dates=ambiguous_report_dates,
    )
    rows: list[dict[str, object]] = []
    for decision_at in decisions:
        eligible = available[
            available["available_at"].notna() & (available["available_at"] <= decision_at)
        ]
        latest = (
            eligible.sort_values(["report_date", "market_id", "category"], kind="stable")
            .drop_duplicates(["market_id", "category"], keep="last")
            .set_index(["market_id", "category"], drop=False)
        )
        output: dict[str, object] = {"decision_at": decision_at}
        for spec in CFTC_MARKETS:
            for category_spec in spec.categories:
                feature_base = f"cftc_{spec.market_id}_{category_spec.category}"
                key = (spec.market_id, category_spec.category)
                if key not in latest.index:
                    output[f"{feature_base}_net_oi"] = np.nan
                    output[f"{feature_base}_change"] = np.nan
                    continue
                source_row = latest.loc[key]
                output[f"{feature_base}_net_oi"] = float(source_row["net_share_oi"])
                output[f"{feature_base}_change"] = float(
                    source_row["net_share_oi_change"]
                )
        for channel, components in CFTC_CHANNEL_COMPONENTS.items():
            _set_channel_features(output, latest, channel, components)
        rows.append(output)
    return pd.DataFrame(rows)


def build_causal_cftc_asset_scores(features: pd.DataFrame) -> pd.DataFrame:
    """Marshrutiziruet tri CFTC channel v sleeping SI/RI/BR/MIX score bez fill."""
    required_columns = {"decision_at"}
    for channel in CFTC_CHANNEL_COMPONENTS:
        feature_base = f"cftc_{channel}"
        required_columns.update(
            {
                f"{feature_base}_net_oi",
                f"{feature_base}_change",
                f"{feature_base}_report_date",
                f"{feature_base}_available_at",
            }
        )
    missing = required_columns - set(features.columns)
    if missing:
        raise ValueError(f"CFTC asset router ne soderzhit kolonok: {sorted(missing)}")
    decisions = _normalize_decision_times(features["decision_at"])
    rows: list[dict[str, object]] = []
    for row_index, decision_at in enumerate(decisions):
        source_row = features.iloc[row_index]
        channel_signals: dict[str, float] = {}
        provenance: dict[str, object] = {}
        for channel in CFTC_CHANNEL_COMPONENTS:
            feature_base = f"cftc_{channel}"
            net_oi = _finite_or_nan(source_row[f"{feature_base}_net_oi"])
            change = _finite_or_nan(source_row[f"{feature_base}_change"])
            report_date = source_row[f"{feature_base}_report_date"]
            available_at = source_row[f"{feature_base}_available_at"]
            signal = (
                float(np.tanh(2.0 * net_oi + 4.0 * change))
                if np.isfinite(net_oi) and np.isfinite(change)
                else float("nan")
            )
            if np.isfinite(signal):
                _validate_channel_provenance(
                    channel,
                    report_date,
                    available_at,
                    decision_at,
                )
            channel_signals[channel] = signal
            provenance[f"{channel}_report_date"] = report_date
            provenance[f"{channel}_available_at"] = available_at
        for asset_symbol, weights in CFTC_ASSET_SCORE_WEIGHTS.items():
            required_channels = tuple(channel for channel, _ in weights)
            required_signals = [channel_signals[channel] for channel in required_channels]
            usable = all(np.isfinite(value) for value in required_signals)
            raw_score = (
                sum(channel_signals[channel] * weight for channel, weight in weights)
                if usable
                else float("nan")
            )
            score = float(np.clip(raw_score, -1.0, 1.0)) if usable else float("nan")
            rows.append(
                {
                    "decision_at": decision_at,
                    "asset_symbol": asset_symbol,
                    "score": score,
                    "score_status": "available" if usable else "sleeping_missing_channel",
                    "required_channels": ",".join(required_channels),
                    "channel_signal_formula": CFTC_CHANNEL_SIGNAL_FORMULA,
                    "score_formula": CFTC_ASSET_SCORE_FORMULAS[asset_symbol],
                    "source": "cftc_cot_official",
                    "router_version": CFTC_ROUTER_VERSION,
                    "causal": True,
                    "research_only": True,
                    **{
                        f"{channel}_signal": channel_signals[channel]
                        for channel in CFTC_CHANNEL_COMPONENTS
                    },
                    **provenance,
                }
            )
    return pd.DataFrame(rows)


def assert_append_only_cftc_history(
    existing: pd.DataFrame,
    candidate: pd.DataFrame,
) -> None:
    """Razreshaet tol'ko stroki strogo posle poslednei immutable report date."""
    old = build_cftc_position_history(existing)
    new = build_cftc_position_history(candidate)
    if old.empty:
        return
    keys = ["report_date", "market_id", "category"]
    old_indexed = old.set_index(keys).sort_index()
    new_indexed = new.set_index(keys).sort_index()
    if not old_indexed.index.isin(new_indexed.index).all():
        raise ValueError("CFTC append-only candidate udalil istoricheskie stroki")
    aligned = new_indexed.loc[old_indexed.index, old_indexed.columns]
    try:
        pd.testing.assert_frame_equal(old_indexed, aligned, check_exact=True)
    except AssertionError as error:
        raise ValueError("CFTC append-only candidate izmenil istoricheskie stroki") from error
    old_last = old["report_date"].max()
    additions = new.merge(old.loc[:, keys], on=keys, how="left", indicator=True)
    additions = additions[additions["_merge"] == "left_only"]
    if not additions.empty and (additions["report_date"] <= old_last).any():
        raise ValueError("CFTC append-only candidate vstavlyaet stroku v proshloe")


def persist_cftc_snapshot(
    root: Path,
    snapshot_id: str,
    archives: Sequence[ParsedCftcArchive],
    *,
    created_at: datetime,
) -> CftcSnapshotResult:
    """Atomarno sohranyaet raw ZIP/CSV, hashi i normalized Parquet bez overwrite."""
    if not CFTC_SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
        raise ValueError("Nekorrektnyi CFTC snapshot_id")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("CFTC created_at dolzhen byt' timezone-aware")
    if not archives:
        raise ValueError("CFTC snapshot dolzhen soderzhat' hotya by odin arhiv")
    archive_keys = [
        (archive.provenance.report_kind, archive.provenance.year) for archive in archives
    ]
    if len(set(archive_keys)) != len(archive_keys):
        raise ValueError("CFTC snapshot ne mozhet soderzhat' dve revizii odnogo goda")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_path = root / snapshot_id
    if snapshot_path.exists():
        raise FileExistsError(f"CFTC snapshot uzhe sushchestvuet: {snapshot_id}")
    history = build_cftc_position_history([archive.records for archive in archives])
    temporary_path = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.", dir=root))
    try:
        manifest_archives: list[dict[str, object]] = []
        for archive in sorted(
            archives,
            key=lambda item: (item.provenance.year, item.provenance.report_kind),
        ):
            provenance = archive.provenance
            stem = f"{provenance.report_kind}_{provenance.year}"
            zip_relative = Path("raw") / f"{stem}.zip"
            csv_relative = Path("raw") / f"{stem}.csv"
            atomic_write_bytes(temporary_path / zip_relative, archive.archive_content)
            atomic_write_bytes(temporary_path / csv_relative, archive.csv_content)
            record = asdict(provenance)
            record["fetched_at"] = provenance.fetched_at.astimezone(UTC).isoformat()
            record["raw_zip_path"] = zip_relative.as_posix()
            record["raw_csv_path"] = csv_relative.as_posix()
            manifest_archives.append(record)
        parquet_buffer = io.BytesIO()
        history.to_parquet(parquet_buffer, index=False)
        processed_relative = Path("processed") / "cftc_positions.parquet"
        atomic_write_bytes(temporary_path / processed_relative, parquet_buffer.getvalue())
        manifest = {
            "snapshot_id": snapshot_id,
            "created_at": created_at.astimezone(UTC).isoformat(),
            "radar_version": CFTC_RADAR_VERSION,
            "append_only": True,
            "research_only": True,
            "historical_index_url": CFTC_HISTORICAL_INDEX_URL,
            "release_schedule_url": CFTC_RELEASE_SCHEDULE_URL,
            "special_announcements_url": CFTC_SPECIAL_ANNOUNCEMENTS_URL,
            "protected_from": CFTC_PROTECTED_FROM.isoformat(),
            "rows": len(history),
            "processed_path": processed_relative.as_posix(),
            "archives": manifest_archives,
        }
        write_json(temporary_path / "manifest.json", manifest)
        temporary_path.replace(snapshot_path)
    finally:
        if temporary_path.exists():
            resolved_root = root.resolve()
            if temporary_path.resolve().parent != resolved_root:
                raise RuntimeError("CFTC temporary path vyshel za predely root")
            shutil.rmtree(temporary_path)
    return CftcSnapshotResult(
        snapshot_id=snapshot_id,
        snapshot_path=snapshot_path,
        manifest_path=snapshot_path / "manifest.json",
        processed_path=snapshot_path / "processed" / "cftc_positions.parquet",
        rows=len(history),
    )


def _validate_development_year(year: int) -> None:
    """Blokiruet goda vne zapechatannogo development intervala 2018-2025."""
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("CFTC year dolzhen byt' celym chislom")
    if not CFTC_MIN_YEAR <= year <= CFTC_MAX_YEAR:
        raise ValueError("CFTC god vne development intervala ili kasaetsya holdout 2026")


def _normalize_report_kind(value: str) -> CftcReportKind:
    """Proveryaet zakrytyi report kind i vozvrashchaet ego typed variant."""
    if value == CFTC_DISAGGREGATED_FUTURES_ONLY:
        return CFTC_DISAGGREGATED_FUTURES_ONLY
    if value == CFTC_TFF_FUTURES_ONLY:
        return CFTC_TFF_FUTURES_ONLY
    raise ValueError(f"Neizvestnyi CFTC report kind: {value}")


def _normalize_report_date(value: object) -> date:
    """Normalizuet report date i fizicheski zapreshchaet 2026 i budushchee."""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Nekorrektnaya CFTC report date: {value!r}") from error
    if pd.isna(timestamp):
        raise ValueError("Pustaya CFTC report date")
    if timestamp.tzinfo is not None:
        raise ValueError("CFTC report date dolzhna byt' kalendarnoi, bez timezone")
    normalized = timestamp.date()
    if normalized < date(CFTC_MIN_YEAR, 1, 1) or normalized >= CFTC_PROTECTED_FROM:
        raise ValueError("CFTC report date vne development intervala ili v holdout 2026")
    if normalized.weekday() >= 5:
        raise ValueError("CFTC report date ne mozhet byt' vyhodnym")
    return normalized


def _read_single_cftc_csv(content: bytes) -> tuple[bytes, str]:
    """Raspakovyvaet odin bezopasnyi text/CSV member bez zapisi na disk."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [
                info
                for info in archive.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() in {".txt", ".csv"}
            ]
            if len(members) != 1:
                raise ValueError("CFTC ZIP dolzhen soderzhat' odin CSV/TXT member")
            member = members[0]
            normalized_name = member.filename.replace("\\", "/")
            path = PurePosixPath(normalized_name)
            if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
                raise ValueError("CFTC ZIP soderzhit nebezopasnoe imya member")
            if member.file_size <= 0 or member.file_size > CFTC_MAX_CSV_BYTES:
                raise ValueError("Pustoi ili slishkom bol'shoi CFTC CSV member")
            csv_content = archive.read(member)
    except zipfile.BadZipFile as error:
        raise ValueError("CFTC payload ne yavlyaetsya korrektnym ZIP") from error
    if len(csv_content) != member.file_size:
        raise ValueError("Razmer raspakovannogo CFTC CSV ne sovpal s ZIP metadata")
    return csv_content, path.name


def _parse_cftc_csv_records(
    content: bytes,
    provenance: CftcArchiveProvenance,
    *,
    require_complete: bool,
) -> pd.DataFrame:
    """Chitaet documented static CSV i razvorachivaet ego v category records."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CFTC CSV dolzhen byt' UTF-8/ASCII") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise ValueError("CFTC CSV ne soderzhit header")
    stripped_headers = [header.strip() for header in reader.fieldnames]
    if len(stripped_headers) != len(set(stripped_headers)):
        raise ValueError("CFTC CSV soderzhit duplicate header")
    header_map = dict(zip(stripped_headers, reader.fieldnames, strict=True))
    required_common = {
        "Market_and_Exchange_Names",
        "CFTC_Contract_Market_Code",
        "Open_Interest_All",
        CFTC_FUTURES_ONLY_COLUMN,
    }
    missing_common = required_common - set(header_map)
    if missing_common:
        raise ValueError(f"CFTC CSV ne soderzhit kolonok: {sorted(missing_common)}")
    report_kind = _normalize_report_kind(provenance.report_kind)
    date_column = _resolve_date_column(header_map, report_kind)
    selected_rows: list[dict[str, object]] = []
    observed_codes: set[str] = set()
    observed_market_dates: set[tuple[str, date]] = set()
    for raw_row in reader:
        code = str(raw_row[header_map["CFTC_Contract_Market_Code"]]).strip().strip('"')
        spec = CFTC_MARKETS_BY_KIND_CODE.get((report_kind, code))
        if spec is None:
            continue
        report_format = str(
            raw_row[header_map[CFTC_FUTURES_ONLY_COLUMN]]
        ).strip().strip('"')
        if report_format != CFTC_FUTURES_ONLY_VALUE:
            raise ValueError("CFTC row ne yavlyaetsya Futures Only")
        market_name = _normalize_market_name(
            raw_row[header_map["Market_and_Exchange_Names"]]
        )
        allowed_names = {_normalize_market_name(name) for name in spec.allowed_names}
        if market_name not in allowed_names:
            raise ValueError(
                f"CFTC code {code} poluchil neallowlisted market name: {market_name}"
            )
        report_date = _parse_csv_report_date(raw_row[header_map[date_column]])
        if report_date.year != provenance.year:
            raise ValueError("CFTC CSV report date ne sootvetstvuet godu arhiva")
        market_date_key = (spec.market_id, report_date)
        if market_date_key in observed_market_dates:
            raise ValueError("CFTC CSV soderzhit duplicate code/report date")
        observed_market_dates.add(market_date_key)
        observed_codes.add(code)
        open_interest = _parse_nonnegative_number(
            raw_row[header_map["Open_Interest_All"]],
            "Open_Interest_All",
            strictly_positive=True,
        )
        for category in spec.categories:
            missing_category = {
                category.long_column,
                category.short_column,
            } - set(header_map)
            if missing_category:
                raise ValueError(
                    f"CFTC CSV ne soderzhit category kolonok: {sorted(missing_category)}"
                )
            selected_rows.append(
                {
                    "report_date": pd.Timestamp(report_date),
                    "report_kind": report_kind,
                    "market_id": spec.market_id,
                    "economic_channel": spec.economic_channel,
                    "contract_code": spec.contract_code,
                    "market_name": market_name,
                    "category": category.category,
                    "open_interest": open_interest,
                    "long_positions": _parse_nonnegative_number(
                        raw_row[header_map[category.long_column]],
                        category.long_column,
                    ),
                    "short_positions": _parse_nonnegative_number(
                        raw_row[header_map[category.short_column]],
                        category.short_column,
                    ),
                    "source_url": provenance.source_url,
                    "archive_sha256": provenance.archive_sha256,
                    "csv_sha256": provenance.csv_sha256,
                    "revision_id": provenance.revision_id,
                    "radar_version": CFTC_RADAR_VERSION,
                }
            )
    expected_codes = {
        spec.contract_code for spec in CFTC_MARKETS if spec.report_kind == report_kind
    }
    missing_codes = expected_codes - observed_codes
    if require_complete and missing_codes:
        raise ValueError(
            f"CFTC annual archive ne soderzhit allowlisted codes: {sorted(missing_codes)}"
        )
    if not selected_rows:
        raise ValueError("CFTC annual archive ne soderzhit ni odnogo allowlisted market")
    return pd.DataFrame(selected_rows).loc[:, CFTC_BASE_RECORD_COLUMNS]


def _resolve_date_column(
    header_map: Mapping[str, str],
    report_kind: CftcReportKind,
) -> str:
    """Vyberaet pervyi documented date header bez heuristiki po znacheniyam."""
    matches = [name for name in CFTC_DATE_COLUMNS_BY_KIND[report_kind] if name in header_map]
    if not matches:
        raise ValueError("CFTC CSV ne soderzhit documented report date header")
    return matches[0]


def _parse_csv_report_date(value: object) -> date:
    """Chitaet tol'ko documented ISO, US slash ili YYMMDD formy report date."""
    text = str(value).strip().strip('"')
    formats = ("%Y-%m-%d", "%m/%d/%Y", "%y%m%d")
    for date_format in formats:
        try:
            parsed = datetime.strptime(text, date_format).date()
        except ValueError:
            continue
        return _normalize_report_date(parsed)
    raise ValueError(f"Nekorrektnaya CFTC report date v CSV: {text!r}")


def _parse_nonnegative_number(
    value: object,
    column: str,
    *,
    strictly_positive: bool = False,
) -> float:
    """Chitaet finite CFTC count bez molchalivogo zapolneniya propuskov."""
    text = str(value).strip().strip('"').replace(",", "")
    try:
        number = float(text)
    except ValueError as error:
        raise ValueError(f"CFTC {column} ne yavlyaetsya chislom: {value!r}") from error
    if not np.isfinite(number) or number < 0.0 or (strictly_positive and number <= 0.0):
        raise ValueError(f"CFTC {column} soderzhit nedopustimoe znachenie")
    return number


def _normalize_market_name(value: object) -> str:
    """Normalizuet tol'ko probely i registr, ne skryvaya semantic drift imeni."""
    return " ".join(str(value).strip().strip('"').upper().split())


def _normalize_decision_times(
    values: Sequence[object] | pd.Series | pd.DatetimeIndex,
) -> pd.DatetimeIndex:
    """Trebuet unique rastushchie timezone-aware MOEX decision timestamps do 2026."""
    raw_values = list(values)
    if not raw_values:
        raise ValueError("MOEX decision calendar ne mozhet byt' pustym")
    normalized: list[pd.Timestamp] = []
    for value in raw_values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Nekorrektnyi MOEX decision timestamp: {value!r}") from error
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            raise ValueError("MOEX decision timestamp dolzhen byt' timezone-aware")
        utc_timestamp = timestamp.tz_convert("UTC")
        if utc_timestamp >= pd.Timestamp(CFTC_PROTECTED_FROM, tz="UTC"):
            raise ValueError("MOEX decision timestamp kasaetsya holdout 2026")
        normalized.append(utc_timestamp)
    result = pd.DatetimeIndex(normalized)
    if result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("MOEX decision calendar dolzhen byt' unique i rastushchim")
    return result


def _normalize_release_overrides(values: Mapping[object, object]) -> dict[date, pd.Timestamp]:
    """Trebuet timezone-aware exact release timestamps dlya netipichnyh nedel'."""
    normalized: dict[date, pd.Timestamp] = {}
    for report_value, release_value in values.items():
        report_day = _normalize_report_date(report_value)
        if report_day in normalized:
            raise ValueError("CFTC release overrides soderzhat duplicate report date")
        try:
            release_at = pd.Timestamp(release_value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Nekorrektnyi CFTC release override: {release_value!r}") from error
        if pd.isna(release_at) or release_at.tzinfo is None:
            raise ValueError("CFTC release override dolzhen byt' timezone-aware")
        release_at = release_at.tz_convert("UTC")
        if release_at >= pd.Timestamp(CFTC_PROTECTED_FROM, tz="UTC"):
            raise ValueError("CFTC release override kasaetsya holdout 2026")
        if release_at <= pd.Timestamp(report_day, tz="UTC"):
            raise ValueError("CFTC release override dolzhen byt' pozhe report date")
        normalized[report_day] = release_at
    return normalized


def _finite_or_nan(value: object) -> float:
    """Prevrashchaet numeric scalar v float, a propusk v NaN bez imputacii."""
    if pd.isna(value):
        return float("nan")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"CFTC feature ne yavlyaetsya chislom: {value!r}") from error
    if not np.isfinite(number):
        raise ValueError("CFTC feature soderzhit infinity")
    return number


def _validate_channel_provenance(
    channel: str,
    report_date: object,
    available_at: object,
    decision_at: pd.Timestamp,
) -> None:
    """Fail-closed zapreshchaet numeric channel bez causal as-of provenance."""
    if pd.isna(report_date) or pd.isna(available_at):
        raise ValueError(f"CFTC {channel} signal ne imeet polnoi provenance")
    report_timestamp = pd.Timestamp(report_date)
    availability = pd.Timestamp(available_at)
    if report_timestamp.tzinfo is not None:
        raise ValueError("CFTC channel report date dolzhna byt' timezone-naive")
    if availability.tzinfo is None:
        raise ValueError("CFTC channel available_at dolzhen byt' timezone-aware")
    availability = availability.tz_convert("UTC")
    if availability > decision_at:
        raise ValueError(f"CFTC {channel} signal narushaet as-of granicu decision")
    if report_timestamp.date() >= CFTC_PROTECTED_FROM:
        raise ValueError("CFTC channel provenance kasaetsya holdout 2026")


def _set_channel_features(
    output: dict[str, object],
    latest: pd.DataFrame,
    channel: str,
    components: Iterable[tuple[str, str]],
) -> None:
    """Agregiruet primary category tol'ko pri polnom odnovremennom channel slice."""
    component_rows: list[pd.Series] = []
    for key in components:
        if key not in latest.index:
            component_rows = []
            break
        component_rows.append(latest.loc[key])
    feature_base = f"cftc_{channel}"
    if not component_rows:
        output[f"{feature_base}_net_oi"] = np.nan
        output[f"{feature_base}_change"] = np.nan
        output[f"{feature_base}_report_date"] = pd.NaT
        output[f"{feature_base}_available_at"] = pd.NaT
        return
    report_dates = {row["report_date"] for row in component_rows}
    if len(report_dates) != 1:
        output[f"{feature_base}_net_oi"] = np.nan
        output[f"{feature_base}_change"] = np.nan
        output[f"{feature_base}_report_date"] = pd.NaT
        output[f"{feature_base}_available_at"] = pd.NaT
        return
    values = [float(row["net_share_oi"]) for row in component_rows]
    changes = [float(row["net_share_oi_change"]) for row in component_rows]
    output[f"{feature_base}_net_oi"] = float(np.mean(values))
    output[f"{feature_base}_change"] = (
        float(np.mean(changes)) if all(np.isfinite(changes)) else np.nan
    )
    output[f"{feature_base}_report_date"] = next(iter(report_dates))
    output[f"{feature_base}_available_at"] = max(
        row["available_at"] for row in component_rows
    )
