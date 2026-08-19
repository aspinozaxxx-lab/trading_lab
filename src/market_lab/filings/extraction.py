"""Deterministicheskaya skhema LLM/OCR izvlecheniya bez cen i targetov."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from market_lab.filings.schema import (
    DEVELOPMENT_ISSUER_ALLOWLIST,
    FROZEN_ISSUER_DENYLIST,
    SHA256_PATTERN,
    AccountingStandard,
    ExtractionMethod,
    NumericFact,
    NumericMetric,
    NumericUnit,
    ReportingScope,
    ReportPeriod,
)

DOCUMENT_EXTRACTION_SCHEMA_VERSION = "filings-extraction-v1"  # Versiya strogogo JSON-contract.
DEFAULT_EXTRACTION_SEED = 42  # Fiksirovannyi seed lokal'nogo deterministic inference.
INFERENCE_MEDIA_TYPES = (  # Formaty dlya text-layer ili postranichnogo OCR.
    "application/pdf",
    "text/html",
    "application/xhtml+xml",
)


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    """Svyazyvaet fakt s konkretnoi stranicei i fragmentom original'nogo dokumenta."""

    artifact_sha256: str
    page_number: int
    source_span: str
    evidence_text_sha256: str
    char_start: int | None = None
    char_end: int | None = None
    ocr_used: bool = False

    def __post_init__(self) -> None:
        """Proveryaet hash, nomer stranicy i koordinaty fragmenta bez hraneniya citaty."""
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        _require_sha256(self.evidence_text_sha256, "evidence_text_sha256")
        if self.page_number <= 0:
            raise ValueError("page_number dolzhen nachinat'sya s 1")
        if not self.source_span.strip():
            raise ValueError("source_span obyazatelen")
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start i char_end zadayutsya vmeste")
        if self.char_start is not None and (
            self.char_start < 0 or self.char_end is None or self.char_end <= self.char_start
        ):
            raise ValueError("Nekorrektnye granicy evidence span")


@dataclass(frozen=True, slots=True)
class ExtractedMetric:
    """Hranit metric, period, dokazatel'stvo, confidence i reviziyu dokumenta."""

    metric: NumericMetric
    value: float
    unit: NumericUnit
    scale: float
    period: ReportPeriod
    accounting_standard: AccountingStandard
    reporting_scope: ReportingScope
    evidence: tuple[EvidenceSpan, ...]
    confidence: float
    revision: int
    human_verified: bool = False

    def __post_init__(self) -> None:
        """Zapreshchaet neoboznachennye, nedokazannye ili nekonechnye znacheniya."""
        if not math.isfinite(float(self.value)):
            raise ValueError("ExtractedMetric.value dolzhen byt' konechnym")
        if not math.isfinite(float(self.scale)) or self.scale <= 0.0:
            raise ValueError("ExtractedMetric.scale dolzhen byt' > 0")
        if not self.evidence:
            raise ValueError("Kazhdogo extracted metric dolzhno podderzhivat' evidence")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence dolzhen byt' v [0, 1]")
        if self.revision < 0:
            raise ValueError("revision ne mozhet byt' otricatel'nym")

    @property
    def deterministic_key(self) -> tuple[str, str, str, str, int, int]:
        """Vozvrashchaet klyuch dlya poiska dvoinoi interpretacii odnogo pokazatelya."""
        return (
            self.metric.value,
            self.unit.value,
            self.accounting_standard.value,
            self.reporting_scope.value,
            self.period.fiscal_year,
            self.period.fiscal_months,
        )


@dataclass(frozen=True, slots=True)
class DocumentExtraction:
    """Predstavlyaet strogo proverennyi JSON-vyhod lokal'noi modeli ili parsera."""

    source_event_id: str
    document_sha256: str
    document_revision: int
    schema_version: str
    model_id: str
    model_revision: str
    prompt_sha256: str
    deterministic_seed: int
    temperature: float
    price_context_included: bool
    label_context_included: bool
    metrics: tuple[ExtractedMetric, ...]

    def __post_init__(self) -> None:
        """Garantiruet deterministic decode, provenance i polnuyu izolyaciyu ot market labels."""
        if not self.source_event_id.strip():
            raise ValueError("source_event_id obyazatelen")
        _require_sha256(self.document_sha256, "document_sha256")
        _require_sha256(self.prompt_sha256, "prompt_sha256")
        if self.document_revision < 0:
            raise ValueError("document_revision ne mozhet byt' otricatel'nym")
        if self.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            raise ValueError("Neizvestnaya versiya extraction schema")
        if not self.model_id.strip() or not self.model_revision.strip():
            raise ValueError("Model i ego tochnaya reviziya obyazatel'ny")
        if self.deterministic_seed < 0:
            raise ValueError("deterministic_seed ne mozhet byt' otricatel'nym")
        if self.temperature != 0.0:
            raise ValueError("Production extraction trebuet temperature=0")
        if self.price_context_included or self.label_context_included:
            raise ValueError("LLM ne dolzhen poluchat' ceny, returny, targety ili labels")
        keys = [metric.deterministic_key for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("Extraction soderzhit dvoinoi metric za odin period")
        for metric in self.metrics:
            if metric.human_verified:
                raise ValueError("LLM JSON ne mozhet sam prisvoit' human_verified=true")
            if metric.revision != self.document_revision:
                raise ValueError("Reviziya metric ne sootvetstvuet revizii dokumenta")
            if any(span.artifact_sha256 != self.document_sha256 for span in metric.evidence):
                raise ValueError("Evidence ssylayetsya na drugoi dokument")


@dataclass(frozen=True, slots=True)
class RecommendedInferenceContract:
    """Opisyvaet bezopasnyi pipeline dlya text PDF, skanov i pairwise-sravneniya."""

    accepted_media_types: tuple[str, ...]
    text_pdf_rule: str
    scanned_pdf_rule: str
    pairwise_rule: str
    numeric_delta_rule: str
    structured_output_rule: str
    forbidden_context: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentInferenceInput:
    """Opisyvaet odin dokument v pairwise-zaprose bez market context."""

    source_event_id: str
    issuer_symbol: str
    artifact_sha256: str
    media_type: str
    period: ReportPeriod
    extracted_text_sha256: str | None = None
    ocr_manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        """Proveryaet hash dokumenta i audit-sled text-layer/OCR."""
        if not self.source_event_id.strip():
            raise ValueError("source_event_id inference-dokumenta obyazatelen")
        symbol = self.issuer_symbol.upper().strip()
        object.__setattr__(self, "issuer_symbol", symbol)
        if symbol in FROZEN_ISSUER_DENYLIST or symbol not in DEVELOPMENT_ISSUER_ALLOWLIST:
            raise ValueError("Inference-dokument ne vhodit v development allowlist")
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        if self.media_type not in INFERENCE_MEDIA_TYPES:
            raise ValueError("Nedopustimyi media_type dlya document inference")
        if self.extracted_text_sha256 is not None:
            _require_sha256(self.extracted_text_sha256, "extracted_text_sha256")
        if self.ocr_manifest_sha256 is not None:
            _require_sha256(self.ocr_manifest_sha256, "ocr_manifest_sha256")
        if self.extracted_text_sha256 is None and self.ocr_manifest_sha256 is None:
            raise ValueError("Inference input trebuet text-layer hash ili OCR manifest hash")


@dataclass(frozen=True, slots=True)
class PairwiseExtractionRequest:
    """Svyazyvaet current i prior same-period dokumenty bez cen i labels."""

    current: DocumentInferenceInput
    prior_same_period: DocumentInferenceInput
    price_context_included: bool = False
    label_context_included: bool = False

    def __post_init__(self) -> None:
        """Trebuet predydushchii god, tot zhe period i pustoi market context."""
        if self.price_context_included or self.label_context_included:
            raise ValueError("Pairwise request ne mozhet soderzhat' ceny ili labels")
        if self.prior_same_period.period.fiscal_year != self.current.period.fiscal_year - 1:
            raise ValueError("Prior document dolzhen byt' za predydushchii fiscal year")
        if self.prior_same_period.issuer_symbol != self.current.issuer_symbol:
            raise ValueError("Pairwise dokumenty dolzhny prinadlezhat' odnomu emitentu")
        if self.prior_same_period.period.same_period_key != self.current.period.same_period_key:
            raise ValueError("Pairwise dokumenty dolzhny imet' odinakovyi fiscal period")


def recommended_inference_contract() -> RecommendedInferenceContract:
    """Vozvrashchaet rekomenduemyi, no ne privyazannyi k konkretnoi modeli contract."""
    return RecommendedInferenceContract(
        accepted_media_types=INFERENCE_MEDIA_TYPES,
        text_pdf_rule=(
            "Izvlech' text po stranicam, normalizovat' tablicy, hashit' kazhdyi evidence span."
        ),
        scanned_pdf_rule=(
            "Detektiruy tekstovyi sloi; OCR tol'ko pustyh/skanirovannyh stranic s ocr_used=true."
        ),
        pairwise_rule=(
            "Model vidit current i previous same-period dokumenty s yavno razdelennymi rol'yami; "
            "kazhdyi fakt poluchaet nezavisimoe evidence."
        ),
        numeric_delta_rule=(
            "Model ne schitaet YoY delta: current-prior vychislyaet deterministic Python "
            "posle validacii."
        ),
        structured_output_rule=(
            "Temperature=0, fiksirovannyi seed, JSON Schema, zapret extra fields i NaN/Infinity."
        ),
        forbidden_context=(
            "price",
            "return",
            "target",
            "label",
            "future_filing",
            "holdout_symbol",
        ),
    )


def document_extraction_from_json(payload: str | bytes) -> DocumentExtraction:
    """Chitaet JSON s otkazom pri duplicate keys, NaN, extra fields ili type coercion."""
    decoded = json.loads(
        payload,
        object_pairs_hook=_unique_object_pairs,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(decoded, dict):
        raise ValueError("DocumentExtraction JSON dolzhen byt' obektom")
    return document_extraction_from_mapping(decoded)


def document_extraction_from_mapping(payload: dict[str, Any]) -> DocumentExtraction:
    """Validiruet kazhdoe pole extraction mapping v fiksirovannom poryadke."""
    _require_exact_keys(
        payload,
        {
            "source_event_id",
            "document_sha256",
            "document_revision",
            "schema_version",
            "model_id",
            "model_revision",
            "prompt_sha256",
            "deterministic_seed",
            "temperature",
            "price_context_included",
            "label_context_included",
            "metrics",
        },
        "DocumentExtraction",
    )
    raw_metrics = payload["metrics"]
    if not isinstance(raw_metrics, list):
        raise ValueError("metrics dolzhen byt' JSON-array")
    metrics = tuple(_metric_from_mapping(item) for item in raw_metrics)
    return DocumentExtraction(
        source_event_id=_strict_str(payload["source_event_id"], "source_event_id"),
        document_sha256=_strict_str(payload["document_sha256"], "document_sha256"),
        document_revision=_strict_int(payload["document_revision"], "document_revision"),
        schema_version=_strict_str(payload["schema_version"], "schema_version"),
        model_id=_strict_str(payload["model_id"], "model_id"),
        model_revision=_strict_str(payload["model_revision"], "model_revision"),
        prompt_sha256=_strict_str(payload["prompt_sha256"], "prompt_sha256"),
        deterministic_seed=_strict_int(payload["deterministic_seed"], "deterministic_seed"),
        temperature=_strict_float(payload["temperature"], "temperature"),
        price_context_included=_strict_bool(
            payload["price_context_included"], "price_context_included"
        ),
        label_context_included=_strict_bool(
            payload["label_context_included"], "label_context_included"
        ),
        metrics=metrics,
    )


def canonical_extraction_json(extraction: DocumentExtraction) -> str:
    """Serializuet proverennyi vyhod v odin kanonicheskii JSON dlya povtornogo hash."""
    payload = {
        "source_event_id": extraction.source_event_id,
        "document_sha256": extraction.document_sha256,
        "document_revision": extraction.document_revision,
        "schema_version": extraction.schema_version,
        "model_id": extraction.model_id,
        "model_revision": extraction.model_revision,
        "prompt_sha256": extraction.prompt_sha256,
        "deterministic_seed": extraction.deterministic_seed,
        "temperature": extraction.temperature,
        "price_context_included": extraction.price_context_included,
        "label_context_included": extraction.label_context_included,
        "metrics": [_metric_to_mapping(metric) for metric in extraction.metrics],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def extraction_fingerprint(extraction: DocumentExtraction) -> str:
    """Vychislyaet stabil'nyi SHA-256 kanonicheskogo validirovannogo JSON."""
    return hashlib.sha256(canonical_extraction_json(extraction).encode("utf-8")).hexdigest()


def extracted_metrics_to_numeric_facts(extraction: DocumentExtraction) -> tuple[NumericFact, ...]:
    """Prevrashchaet extraction v facts, ne podmenyaya LLM confidence human-proverkoi."""
    facts = []
    for metric in extraction.metrics:
        locators = ";".join(
            f"page={span.page_number}:{span.source_span}" for span in metric.evidence
        )
        facts.append(
            NumericFact(
                metric=metric.metric,
                value=metric.value,
                unit=metric.unit,
                scale=metric.scale,
                accounting_standard=metric.accounting_standard,
                reporting_scope=metric.reporting_scope,
                source_locator=locators,
                extraction_method=ExtractionMethod.LOCAL_LLM_JSON,
                verified=metric.human_verified,
            )
        )
    return tuple(facts)


def _metric_from_mapping(payload: Any) -> ExtractedMetric:
    """Vosstanavlivaet odin metric i vse ego evidence iz strogogo JSON-obekta."""
    if not isinstance(payload, dict):
        raise ValueError("Element metrics dolzhen byt' JSON-obektom")
    _require_exact_keys(
        payload,
        {
            "metric",
            "value",
            "unit",
            "scale",
            "period",
            "accounting_standard",
            "reporting_scope",
            "evidence",
            "confidence",
            "revision",
            "human_verified",
        },
        "ExtractedMetric",
    )
    period_payload = payload["period"]
    if not isinstance(period_payload, dict):
        raise ValueError("period dolzhen byt' JSON-obektom")
    _require_exact_keys(
        period_payload,
        {"fiscal_year", "fiscal_months", "period_start", "period_end"},
        "ReportPeriod",
    )
    evidence_payload = payload["evidence"]
    if not isinstance(evidence_payload, list):
        raise ValueError("evidence dolzhen byt' JSON-array")
    return ExtractedMetric(
        metric=NumericMetric(_strict_str(payload["metric"], "metric")),
        value=_strict_float(payload["value"], "value"),
        unit=NumericUnit(_strict_str(payload["unit"], "unit")),
        scale=_strict_float(payload["scale"], "scale"),
        period=ReportPeriod(
            fiscal_year=_strict_int(period_payload["fiscal_year"], "fiscal_year"),
            fiscal_months=_strict_int(period_payload["fiscal_months"], "fiscal_months"),
            period_start=date.fromisoformat(
                _strict_str(period_payload["period_start"], "period_start")
            ),
            period_end=date.fromisoformat(
                _strict_str(period_payload["period_end"], "period_end")
            ),
        ),
        accounting_standard=AccountingStandard(
            _strict_str(payload["accounting_standard"], "accounting_standard")
        ),
        reporting_scope=ReportingScope(
            _strict_str(payload["reporting_scope"], "reporting_scope")
        ),
        evidence=tuple(_evidence_from_mapping(item) for item in evidence_payload),
        confidence=_strict_float(payload["confidence"], "confidence"),
        revision=_strict_int(payload["revision"], "revision"),
        human_verified=_strict_bool(payload["human_verified"], "human_verified"),
    )


def _evidence_from_mapping(payload: Any) -> EvidenceSpan:
    """Vosstanavlivaet odin postranichnyi evidence span bez tikhih defaultov."""
    if not isinstance(payload, dict):
        raise ValueError("Element evidence dolzhen byt' JSON-obektom")
    _require_exact_keys(
        payload,
        {
            "artifact_sha256",
            "page_number",
            "source_span",
            "evidence_text_sha256",
            "char_start",
            "char_end",
            "ocr_used",
        },
        "EvidenceSpan",
    )
    return EvidenceSpan(
        artifact_sha256=_strict_str(payload["artifact_sha256"], "artifact_sha256"),
        page_number=_strict_int(payload["page_number"], "page_number"),
        source_span=_strict_str(payload["source_span"], "source_span"),
        evidence_text_sha256=_strict_str(
            payload["evidence_text_sha256"], "evidence_text_sha256"
        ),
        char_start=_strict_optional_int(payload["char_start"], "char_start"),
        char_end=_strict_optional_int(payload["char_end"], "char_end"),
        ocr_used=_strict_bool(payload["ocr_used"], "ocr_used"),
    )


def _metric_to_mapping(metric: ExtractedMetric) -> dict[str, Any]:
    """Prevrashchaet odin metric v kanonicheskoe slovarnoe predstavlenie."""
    return {
        "metric": metric.metric.value,
        "value": metric.value,
        "unit": metric.unit.value,
        "scale": metric.scale,
        "period": {
            "fiscal_year": metric.period.fiscal_year,
            "fiscal_months": metric.period.fiscal_months,
            "period_start": metric.period.period_start.isoformat(),
            "period_end": metric.period.period_end.isoformat(),
        },
        "accounting_standard": metric.accounting_standard.value,
        "reporting_scope": metric.reporting_scope.value,
        "evidence": [
            {
                "artifact_sha256": span.artifact_sha256,
                "page_number": span.page_number,
                "source_span": span.source_span,
                "evidence_text_sha256": span.evidence_text_sha256,
                "char_start": span.char_start,
                "char_end": span.char_end,
                "ocr_used": span.ocr_used,
            }
            for span in metric.evidence
        ],
        "confidence": metric.confidence,
        "revision": metric.revision,
        "human_verified": metric.human_verified,
    }


def _require_exact_keys(payload: dict[str, Any], expected: set[str], label: str) -> None:
    """Zapreshchaet propushchennye i neizvestnye JSON-polya."""
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{label} keys ne sootvetstvuyut schema: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Zapreshchaet duplicate JSON keys do postroeniya slovarya."""
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"Duplicate JSON key: {key}")
        output[key] = value
    return output


def _reject_json_constant(value: str) -> None:
    """Zapreshchaet nestandartnye JSON-konstanty NaN i Infinity."""
    raise ValueError(f"Nedopustimaya JSON-konstanta: {value}")


def _strict_str(value: Any, field_name: str) -> str:
    """Trebuet imenno nepustuyu stroku bez avtopreobrazovaniya tipa."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} dolzhen byt' nepustoi strokoi")
    return value


def _strict_int(value: Any, field_name: str) -> int:
    """Trebuet imenno celoe chislo, otklonyaya bool."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} dolzhen byt' integer")
    return value


def _strict_optional_int(value: Any, field_name: str) -> int | None:
    """Trebuet None ili strogoe celoe chislo."""
    return None if value is None else _strict_int(value, field_name)


def _strict_float(value: Any, field_name: str) -> float:
    """Trebuet JSON-number bez bool i vozvrashchaet konechnyi float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} dolzhen byt' number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} dolzhen byt' konechnym")
    return converted


def _strict_bool(value: Any, field_name: str) -> bool:
    """Trebuet imenno JSON boolean bez podmeny 0/1."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} dolzhen byt' boolean")
    return value


def _require_sha256(value: str, field_name: str) -> None:
    """Proveryaet lowercase SHA-256 bez tikhogo ispravleniya."""
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} dolzhen byt' lowercase SHA-256")
