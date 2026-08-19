"""Tipizirovannaya point-in-time skhema korporativnyh raskrytii."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

PROTECTED_HOLDOUT_START = date(2026, 1, 1)  # Nachalo zapreshchennogo perioda dannyh.
MOEX_TIMEZONE = ZoneInfo("Europe/Moscow")  # Zona dlya granicy torgovoi daty holdout.
DEVELOPMENT_ISSUER_ALLOWLIST = frozenset(  # Ishodnyi development-universe bez frozen19.
    {
        "SBER",
        "GAZP",
        "LKOH",
        "NVTK",
        "ROSN",
        "TATN",
        "MOEX",
        "VTBR",
        "CHMF",
        "PHOR",
        "RUAL",
    }
)
FROZEN_ISSUER_DENYLIST = frozenset(  # Netronutyi asset holdout, zapreshchennyi dlya I/O.
    {
        "ASTR",
        "FEES",
        "FLOT",
        "HEAD",
        "HYDR",
        "LEAS",
        "MSNG",
        "MTLR",
        "MTLRP",
        "PIKK",
        "POSI",
        "SELG",
        "SMLT",
        "SVCB",
        "T",
        "UGLD",
        "UPRO",
        "VKCO",
        "YDEX",
    }
)
RESIDUAL_TARGET_HORIZONS = (1, 5, 20)  # Razreshennye gorizonty target v sessiyah.
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")  # Strogoe predstavlenie SHA-256.
REPORT_MONTHS = frozenset({3, 6, 9, 12})  # Razreshennye kumulyativnye periody otcheta.


class FilingSourceKind(StrEnum):
    """Perechislyaet razreshennye istochniki korporativnyh raskrytii."""

    INTERFAX_GATEWAY = "interfax_gateway"
    INTERFAX_PORTAL = "interfax_portal"
    ISSUER_IR = "issuer_ir"


class FilingKind(StrEnum):
    """Razdelyaet tipy otchetnosti bez smeshivaniya raznyh baz ucheta."""

    IFRS = "ifrs"
    RAS = "ras"
    ISSUER_REPORT = "issuer_report"
    ANNUAL_REPORT = "annual_report"
    OPERATING_RESULTS = "operating_results"
    DIVIDEND_ANNOUNCEMENT = "dividend_announcement"
    OTHER = "other"


class FilingEventAction(StrEnum):
    """Opisyvaet sostoyanie publikacii, vklyuchaya ispravleniya i udaleniya."""

    PUBLISHED = "published"
    REVISED = "revised"
    DELETED = "deleted"
    RESTORED = "restored"


class NumericMetric(StrEnum):
    """Fiksiruet chisla, kotorye mozhno izvlekat' tol'ko iz samogo otcheta."""

    REVENUE = "revenue"
    EBITDA = "ebitda"
    OPERATING_PROFIT = "operating_profit"
    NET_INCOME = "net_income"
    FREE_CASH_FLOW = "free_cash_flow"
    NET_DEBT = "net_debt"
    CAPEX = "capex"
    GROSS_MARGIN = "gross_margin"
    EBITDA_MARGIN = "ebitda_margin"
    OPERATING_MARGIN = "operating_margin"
    NET_MARGIN = "net_margin"
    DIVIDENDS = "dividends"
    ACCRUALS = "accruals"


class NumericUnit(StrEnum):
    """Razdelyaet denezhnye, otnositel'nye i na-akciyu pokazateli."""

    RUB = "rub"
    RUB_PER_SHARE = "rub_per_share"
    RATIO = "ratio"
    PERCENT = "percent"


class AccountingStandard(StrEnum):
    """Fiksiruet standart ucheta dlya korrektnogo sravneniya periodov."""

    IFRS = "ifrs"
    RAS = "ras"
    MANAGEMENT = "management"
    NOT_APPLICABLE = "not_applicable"


class ReportingScope(StrEnum):
    """Razdelyaet konsolidirovannuyu i individual'nuyu otchetnost'."""

    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"
    NOT_APPLICABLE = "not_applicable"


class ExtractionMethod(StrEnum):
    """Pokazyvaet, kak polucheno chislo bez pretenzii na avtomaticheskuyu istinu."""

    XBRL = "xbrl"
    TABLE_PARSER = "table_parser"
    MANUAL_VERIFIED = "manual_verified"
    ISSUER_STRUCTURED = "issuer_structured"
    LOCAL_LLM_JSON = "local_llm_json"


class TextEmbeddingStatus(StrEnum):
    """Razdelyaet pustoi placeholder i proverennyi embedding bez hraneniya vektora."""

    NOT_EXTRACTED = "not_extracted"
    TEXT_EXTRACTED = "text_extracted"
    EMBEDDED = "embedded"


@dataclass(frozen=True, slots=True)
class IssuerIdentity:
    """Hranit stabil'nye identifikatory emitenta iz development allowlist."""

    symbol: str
    legal_name: str
    inn: str
    disclosure_id: str | None = None
    ogrn: str | None = None

    def __post_init__(self) -> None:
        """Zapreshchaet frozen i lyubye neodobrennye simvoly."""
        symbol = self.symbol.upper().strip()
        object.__setattr__(self, "symbol", symbol)
        if symbol in FROZEN_ISSUER_DENYLIST or symbol not in DEVELOPMENT_ISSUER_ALLOWLIST:
            raise ValueError(f"Emitent {symbol!r} ne vhodit v development allowlist")
        if not self.legal_name.strip():
            raise ValueError("Pustoe yuridicheskoe naimenovanie emitenta")
        if not self.inn.isdigit() or len(self.inn) not in {10, 12}:
            raise ValueError("INN dolzhen soderzhat' 10 ili 12 cifr")


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    """Opisyvaet fiscal'nyi kumulyativnyi period, a ne datu publikacii."""

    fiscal_year: int
    fiscal_months: Literal[3, 6, 9, 12]
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        """Proveryaet granicy perioda i blokiruet holdout-daty."""
        if self.fiscal_months not in REPORT_MONTHS:
            raise ValueError("fiscal_months dolzhen byt' 3, 6, 9 ili 12")
        if self.period_start > self.period_end:
            raise ValueError("Nachalo otchetnogo perioda pozhe konca")
        if self.period_end.year != self.fiscal_year:
            raise ValueError("fiscal_year ne sootvetstvuet period_end")
        if self.period_end >= PROTECTED_HOLDOUT_START:
            raise ValueError("Otchetnyi period zahodit v zashchishchennyi holdout")

    @property
    def same_period_key(self) -> tuple[int, int, int]:
        """Vozvrashchaet klyuch mesyacev i kalendarnoi granicy dlya YoY-sravneniya."""
        return self.fiscal_months, self.period_end.month, self.period_end.day


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """Fiksiruet proishozhdenie i kriptograficheskii otpechatok syrogo artefakta."""

    source_kind: FilingSourceKind
    source_url: str
    retrieved_at: datetime
    content_sha256: str
    byte_size: int
    media_type: str
    attachment_uid: str | None = None

    def __post_init__(self) -> None:
        """Proveryaet HTTPS, aware-vremya, hash i razmer bez setevogo dostupa."""
        if not self.source_url.startswith("https://"):
            raise ValueError("Istochnik raskrytiya dolzhen ispol'zovat' HTTPS")
        _require_aware(self.retrieved_at, "retrieved_at")
        digest = self.content_sha256.lower()
        object.__setattr__(self, "content_sha256", digest)
        if SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("content_sha256 dolzhen byt' 64-znachnym lowercase hex")
        if self.byte_size < 0:
            raise ValueError("byte_size ne mozhet byt' otricatel'nym")
        if not self.media_type.strip():
            raise ValueError("media_type obyazatelen")


@dataclass(frozen=True, slots=True)
class NumericFact:
    """Hranit odno izvlechennoe chislo vmeste s bazisom sopostavimosti."""

    metric: NumericMetric
    value: float
    unit: NumericUnit
    scale: float
    accounting_standard: AccountingStandard
    reporting_scope: ReportingScope
    source_locator: str
    extraction_method: ExtractionMethod
    verified: bool = False

    def __post_init__(self) -> None:
        """Zapreshchaet NaN, beskonechnost', nulevoi scale i anonimnye chisla."""
        if not math.isfinite(float(self.value)):
            raise ValueError("NumericFact.value dolzhen byt' konechnym")
        if not math.isfinite(float(self.scale)) or self.scale <= 0.0:
            raise ValueError("NumericFact.scale dolzhen byt' konechnym i > 0")
        if not self.source_locator.strip():
            raise ValueError("Dlya chisla obyazatelen source_locator")

    @property
    def normalized_value(self) -> float:
        """Privodit chislo k bazovoi edinice, ne menyaya ego ekonomicheskii smysl."""
        return float(self.value) * float(self.scale)

    @property
    def comparison_key(self) -> tuple[str, str, str, str]:
        """Vozvrashchaet klyuch, kotoryi zapreshchaet sravnivat' nesovmestimye chisla."""
        return (
            self.metric.value,
            self.unit.value,
            self.accounting_standard.value,
            self.reporting_scope.value,
        )


@dataclass(frozen=True, slots=True)
class TextSignalMetadata:
    """Hranit tol'ko audit-metadata teksta i embedding, no ne pridumyvaet vektor."""

    status: TextEmbeddingStatus = TextEmbeddingStatus.NOT_EXTRACTED
    source_text_sha256: str | None = None
    extraction_version: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_sha256: str | None = None
    previous_embedding_sha256: str | None = None
    cosine_delta_from_previous: float | None = None

    def __post_init__(self) -> None:
        """Trebuet polnuyu provenance dlya gotovogo embedding i pustotu placeholdera."""
        hashes = (
            self.source_text_sha256,
            self.embedding_sha256,
            self.previous_embedding_sha256,
        )
        for digest in (value for value in hashes if value is not None):
            if digest != digest.lower() or SHA256_PATTERN.fullmatch(digest) is None:
                raise ValueError("Hash text/embedding dolzhen byt' lowercase SHA-256")
        if self.status is TextEmbeddingStatus.NOT_EXTRACTED:
            forbidden = (
                self.extraction_version,
                self.embedding_model,
                self.embedding_dimensions,
                self.embedding_sha256,
                self.previous_embedding_sha256,
                self.cosine_delta_from_previous,
            )
            if any(value is not None for value in forbidden):
                raise ValueError("Placeholder ne mozhet soderzhat' synthetic embedding metadata")
            return
        if self.source_text_sha256 is None or not self.extraction_version:
            raise ValueError("Izvlechennomu tekstu nuzhny source hash i versiya parsera")
        if self.status is TextEmbeddingStatus.TEXT_EXTRACTED:
            if any(
                value is not None
                for value in (
                    self.embedding_model,
                    self.embedding_dimensions,
                    self.embedding_sha256,
                    self.previous_embedding_sha256,
                    self.cosine_delta_from_previous,
                )
            ):
                raise ValueError("TEXT_EXTRACTED ne dolzhen vydavat' sebya za embedding")
            return
        if (
            not self.embedding_model
            or self.embedding_dimensions is None
            or self.embedding_dimensions <= 0
            or self.embedding_sha256 is None
        ):
            raise ValueError("EMBEDDED trebuet model, razmernost' i hash vektora")
        if self.cosine_delta_from_previous is not None:
            if self.previous_embedding_sha256 is None:
                raise ValueError("Text delta trebuet hash predydushchego embedding")
            if not 0.0 <= self.cosine_delta_from_previous <= 2.0:
                raise ValueError("Cosine distance dolzhna byt' v [0, 2]")


@dataclass(frozen=True, slots=True)
class ReportEvent:
    """Predstavlyaet odno point-in-time sobytie zhiznennogo cikla dokumenta."""

    source_event_id: str
    document_id: str
    action: FilingEventAction
    revision_number: int
    revision_of_event_id: str | None
    issuer: IssuerIdentity
    filing_kind: FilingKind
    period: ReportPeriod
    published_at: datetime
    artifact: SourceArtifact
    numeric_facts: tuple[NumericFact, ...] = field(default_factory=tuple)
    text_metadata: TextSignalMetadata = field(default_factory=TextSignalMetadata)
    issuer_event_at: datetime | None = None

    def __post_init__(self) -> None:
        """Proveryaet vremya dostupnosti, versiyu i unikal'nost' chislennoj skhemy."""
        if not self.source_event_id.strip() or not self.document_id.strip():
            raise ValueError("source_event_id i document_id obyazatel'ny")
        _require_development_timestamp(self.published_at, "published_at")
        if self.artifact.retrieved_at < self.published_at:
            raise ValueError("Artefakt ne mozhet byt' poluchen ran'she publikacii")
        if self.issuer_event_at is not None:
            _require_development_timestamp(self.issuer_event_at, "issuer_event_at")
        if self.action is FilingEventAction.PUBLISHED:
            if self.revision_number != 0 or self.revision_of_event_id is not None:
                raise ValueError("Pervaya publikaciya dolzhna imet' revision_number=0 bez ssylki")
        else:
            if self.revision_number <= 0 or not self.revision_of_event_id:
                raise ValueError("Izmenenie sostoyaniya trebuet nomer versii i revision_of")
        keys = [fact.comparison_key for fact in self.numeric_facts]
        if len(keys) != len(set(keys)):
            raise ValueError("V odnom otchete povtoryaetsya sopostavimyi numeric fact")
        if (
            self.action in {FilingEventAction.DELETED, FilingEventAction.RESTORED}
            and self.numeric_facts
        ):
            raise ValueError("Delete/restore sobytie ne dolzhno kopirovat' numeric facts")


@dataclass(frozen=True, slots=True)
class ResidualTargetSpec:
    """Opisyvaet target bez dostupа k cenam i bez ego vychisleniya."""

    horizon_sessions: Literal[1, 5, 20]
    entry_price: str = "first_eligible_next_session_open"
    exit_price: str = "open_after_horizon_sessions"
    response: str = "issuer_return_minus_causal_market_beta_return"
    price_access_permitted: bool = False

    def __post_init__(self) -> None:
        """Zapreshchaet inye gorizonty i vstraivanie cen v sloi raskrytii."""
        if self.horizon_sessions not in RESIDUAL_TARGET_HORIZONS:
            raise ValueError("Razresheny tol'ko residual target 1/5/20 sessii")
        if self.price_access_permitted:
            raise ValueError("Foundation raskrytii ne mozhet chitat' ceny")


def default_residual_target_specs() -> tuple[ResidualTargetSpec, ...]:
    """Vozvrashchaet fiksirovannye opisaniya 1/5/20 next-open residual targets."""
    return tuple(ResidualTargetSpec(horizon) for horizon in RESIDUAL_TARGET_HORIZONS)


def report_event_to_mapping(event: ReportEvent) -> dict[str, Any]:
    """Prevrashchaet sobytie v stabil'no serializuemoe slovarnoe predstavlenie."""
    return _json_ready(asdict(event))


def report_event_from_mapping(payload: dict[str, Any]) -> ReportEvent:
    """Vosstanavlivaet strogo tipizirovannoe sobytie iz raw/fixture metadata."""
    issuer_payload = payload["issuer"]
    period_payload = payload["period"]
    artifact_payload = payload["artifact"]
    text_payload = payload.get("text_metadata", {})
    facts = tuple(
        NumericFact(
            metric=NumericMetric(item["metric"]),
            value=float(item["value"]),
            unit=NumericUnit(item["unit"]),
            scale=float(item["scale"]),
            accounting_standard=AccountingStandard(item["accounting_standard"]),
            reporting_scope=ReportingScope(item["reporting_scope"]),
            source_locator=str(item["source_locator"]),
            extraction_method=ExtractionMethod(item["extraction_method"]),
            verified=bool(item.get("verified", False)),
        )
        for item in payload.get("numeric_facts", [])
    )
    text_metadata = TextSignalMetadata(
        status=TextEmbeddingStatus(text_payload.get("status", "not_extracted")),
        source_text_sha256=text_payload.get("source_text_sha256"),
        extraction_version=text_payload.get("extraction_version"),
        embedding_model=text_payload.get("embedding_model"),
        embedding_dimensions=text_payload.get("embedding_dimensions"),
        embedding_sha256=text_payload.get("embedding_sha256"),
        previous_embedding_sha256=text_payload.get("previous_embedding_sha256"),
        cosine_delta_from_previous=text_payload.get("cosine_delta_from_previous"),
    )
    return ReportEvent(
        source_event_id=str(payload["source_event_id"]),
        document_id=str(payload["document_id"]),
        action=FilingEventAction(payload["action"]),
        revision_number=int(payload["revision_number"]),
        revision_of_event_id=payload.get("revision_of_event_id"),
        issuer=IssuerIdentity(**issuer_payload),
        filing_kind=FilingKind(payload["filing_kind"]),
        period=ReportPeriod(
            fiscal_year=int(period_payload["fiscal_year"]),
            fiscal_months=int(period_payload["fiscal_months"]),
            period_start=date.fromisoformat(period_payload["period_start"]),
            period_end=date.fromisoformat(period_payload["period_end"]),
        ),
        published_at=_parse_datetime(payload["published_at"]),
        artifact=SourceArtifact(
            source_kind=FilingSourceKind(artifact_payload["source_kind"]),
            source_url=str(artifact_payload["source_url"]),
            retrieved_at=_parse_datetime(artifact_payload["retrieved_at"]),
            content_sha256=str(artifact_payload["content_sha256"]),
            byte_size=int(artifact_payload["byte_size"]),
            media_type=str(artifact_payload["media_type"]),
            attachment_uid=artifact_payload.get("attachment_uid"),
        ),
        numeric_facts=facts,
        text_metadata=text_metadata,
        issuer_event_at=(
            _parse_datetime(payload["issuer_event_at"])
            if payload.get("issuer_event_at") is not None
            else None
        ),
    )


def event_fingerprint(event: ReportEvent) -> str:
    """Heshiruet soderzhimoe sobytiya, ignoriruya povtornuyu datu polucheniya."""
    payload = report_event_to_mapping(event)
    payload["artifact"].pop("retrieved_at", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_datetime(value: str | datetime) -> datetime:
    """Chitaet ISO timestamp s podderzhkoi suffiksa Z."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _require_aware(value: datetime, field_name: str) -> None:
    """Zapreshchaet naivnoe vremya, ne pozvolyayushchee point-in-time audit."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} dolzhen soderzhat' timezone")


def _require_development_timestamp(value: datetime, field_name: str) -> None:
    """Proveryaet aware timestamp i fail-closed granicu netronutogo holdout."""
    _require_aware(value, field_name)
    if value.astimezone(MOEX_TIMEZONE).date() >= PROTECTED_HOLDOUT_START:
        raise ValueError(f"{field_name} popadaet v zashchishchennyi holdout")


def _json_ready(value: Any) -> Any:
    """Rekursivno privodit dataclass-znacheniya k stabil'nomu JSON-formatu."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value
