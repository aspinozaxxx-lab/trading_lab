"""Testy strogogo LLM/OCR JSON-contract bez cen, labels i setevogo inference."""

from __future__ import annotations

import json
from datetime import date

import pytest

from market_lab.filings import (
    DOCUMENT_EXTRACTION_SCHEMA_VERSION,
    DocumentInferenceInput,
    PairwiseExtractionRequest,
    ReportPeriod,
    canonical_extraction_json,
    document_extraction_from_json,
    extracted_metrics_to_numeric_facts,
    extraction_fingerprint,
    recommended_inference_contract,
)


def _extraction_payload() -> dict[str, object]:
    """Stroit synthetic output nevybrannoi lokal'noi modeli s postranichnym evidence."""
    document_hash = "d" * 64
    return {
        "source_event_id": "fake-sber-2024-v1",
        "document_sha256": document_hash,
        "document_revision": 1,
        "schema_version": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        "model_id": "unselected-local-model",
        "model_revision": "license-review-pending",
        "prompt_sha256": "f" * 64,
        "deterministic_seed": 42,
        "temperature": 0.0,
        "price_context_included": False,
        "label_context_included": False,
        "metrics": [
            {
                "metric": "revenue",
                "value": 125.0,
                "unit": "rub",
                "scale": 1_000_000_000.0,
                "period": {
                    "fiscal_year": 2024,
                    "fiscal_months": 12,
                    "period_start": "2024-01-01",
                    "period_end": "2024-12-31",
                },
                "accounting_standard": "ifrs",
                "reporting_scope": "consolidated",
                "evidence": [
                    {
                        "artifact_sha256": document_hash,
                        "page_number": 10,
                        "source_span": "table=financial-results,row=revenue,col=2024",
                        "evidence_text_sha256": "e" * 64,
                        "char_start": 140,
                        "char_end": 173,
                        "ocr_used": True,
                    }
                ],
                "confidence": 0.94,
                "revision": 1,
                "human_verified": False,
            }
        ],
    }


def test_document_extraction_round_trip_and_fingerprint_are_deterministic() -> None:
    """Proveryaet canonical JSON i odin hash pri raznom poryadke vhodnyh keys."""
    payload = _extraction_payload()
    first = document_extraction_from_json(json.dumps(payload))
    reversed_payload = dict(reversed(list(payload.items())))
    second = document_extraction_from_json(json.dumps(reversed_payload))
    assert canonical_extraction_json(first) == canonical_extraction_json(second)
    assert extraction_fingerprint(first) == extraction_fingerprint(second)
    assert first.metrics[0].evidence[0].page_number == 10
    assert first.metrics[0].evidence[0].ocr_used


def test_llm_confidence_never_becomes_human_verification() -> None:
    """Ne pozvolyaet vysokomu self-confidence modeli avtomaticheski stat' trusted fact."""
    extraction = document_extraction_from_json(json.dumps(_extraction_payload()))
    facts = extracted_metrics_to_numeric_facts(extraction)
    assert len(facts) == 1
    assert facts[0].normalized_value == 125_000_000_000.0
    assert not facts[0].verified
    assert "page=10" in facts[0].source_locator
    self_attested = _extraction_payload()
    self_attested["metrics"][0]["human_verified"] = True
    with pytest.raises(ValueError, match="human_verified"):
        document_extraction_from_json(json.dumps(self_attested))


@pytest.mark.parametrize("forbidden_field", ["price_context_included", "label_context_included"])
def test_price_and_label_context_are_rejected(forbidden_field: str) -> None:
    """Zapreshchaet podmeshivat' v LLM dokument ceny, returny ili target labels."""
    payload = _extraction_payload()
    payload[forbidden_field] = True
    with pytest.raises(ValueError, match="ceny"):
        document_extraction_from_json(json.dumps(payload))


def test_json_validation_rejects_extra_duplicate_and_nonfinite_values() -> None:
    """Otkazyvaetsya ot extra fields, duplicate keys i nestandartnogo NaN."""
    extra = _extraction_payload()
    extra["future_return"] = 0.5
    with pytest.raises(ValueError, match="extra"):
        document_extraction_from_json(json.dumps(extra))
    duplicate = '{"source_event_id":"a","source_event_id":"b"}'
    with pytest.raises(ValueError, match="Duplicate"):
        document_extraction_from_json(duplicate)
    nonfinite = json.dumps(_extraction_payload()).replace("125.0", "NaN", 1)
    with pytest.raises(ValueError, match="konstanta"):
        document_extraction_from_json(nonfinite)


def test_evidence_and_revision_must_match_document() -> None:
    """Zapreshchaet ssylku evidence na drugoi PDF i metric ot drugoi revizii."""
    wrong_hash = _extraction_payload()
    wrong_hash["metrics"][0]["evidence"][0]["artifact_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="drugoi dokument"):
        document_extraction_from_json(json.dumps(wrong_hash))
    wrong_revision = _extraction_payload()
    wrong_revision["metrics"][0]["revision"] = 0
    with pytest.raises(ValueError, match="Reviziya"):
        document_extraction_from_json(json.dumps(wrong_revision))


def test_recommended_contract_covers_text_scan_and_pairwise_without_market_context() -> None:
    """Fiksiruet OCR, current/prior i arithmetic-outside-LLM pravila do vybora modeli."""
    contract = recommended_inference_contract()
    assert "OCR" in contract.scanned_pdf_rule
    assert "current" in contract.pairwise_rule
    assert "deterministic Python" in contract.numeric_delta_rule
    assert {"price", "return", "target", "label"}.issubset(contract.forbidden_context)


def test_typed_pairwise_request_requires_previous_same_period() -> None:
    """Razreshaet modeli videt' dve versii perioda, no ne market context ili drugoi kvartal."""
    prior_period = ReportPeriod(
        fiscal_year=2023,
        fiscal_months=12,
        period_start=date(2023, 1, 1),
        period_end=date(2023, 12, 31),
    )
    current_period = ReportPeriod(
        fiscal_year=2024,
        fiscal_months=12,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
    )
    prior = DocumentInferenceInput(
        source_event_id="prior",
        issuer_symbol="SBER",
        artifact_sha256="a" * 64,
        media_type="application/pdf",
        period=prior_period,
        ocr_manifest_sha256="b" * 64,
    )
    current = DocumentInferenceInput(
        source_event_id="current",
        issuer_symbol="SBER",
        artifact_sha256="c" * 64,
        media_type="application/pdf",
        period=current_period,
        extracted_text_sha256="d" * 64,
    )
    request = PairwiseExtractionRequest(current=current, prior_same_period=prior)
    assert not request.price_context_included
    with pytest.raises(ValueError, match="ceny"):
        PairwiseExtractionRequest(
            current=current,
            prior_same_period=prior,
            price_context_included=True,
        )
    with pytest.raises(ValueError, match="allowlist"):
        DocumentInferenceInput(
            source_event_id="frozen",
            issuer_symbol="YDEX",
            artifact_sha256="e" * 64,
            media_type="application/pdf",
            period=current_period,
            extracted_text_sha256="f" * 64,
        )
