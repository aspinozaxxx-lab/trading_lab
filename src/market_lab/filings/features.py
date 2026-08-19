"""Kausal'nye priznaki otchetnosti bez chteniya cen, targetov ili holdout."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from market_lab.filings.calendar import first_eligible_session_open
from market_lab.filings.revisions import (
    ResolvedReport,
    resolve_active_reports,
    validate_revision_chains,
)
from market_lab.filings.schema import (
    FilingEventAction,
    NumericFact,
    NumericMetric,
    ReportEvent,
    TextEmbeddingStatus,
)

FEATURE_METRICS = tuple(NumericMetric)  # Polnyi fiksirovannyi nabor fundamental'nyh signalov.


def build_causal_report_features(
    events: list[ReportEvent] | tuple[ReportEvent, ...],
    session_opens: Iterable[pd.Timestamp],
) -> pd.DataFrame:
    """Stroit event-log, dostupnyi tol'ko s pervogo open strogo posle publikacii."""
    unique = validate_revision_chains(events)
    opens = tuple(session_opens)
    rows: list[dict[str, Any]] = []
    for state_event in unique:
        eligible_open = first_eligible_session_open(state_event.published_at, opens)
        active = resolve_active_reports(unique, state_event.published_at)
        current = _current_document(active, state_event)
        row = _base_row(state_event, eligible_open, current is not None)
        if current is None:
            _add_missing_numeric_features(row)
            _add_missing_text_features(row)
        else:
            content = current.content_event
            prior = _prior_same_period(active, content)
            _add_numeric_features(row, content, prior)
            _add_text_features(row, content)
            row["content_source_event_id"] = content.source_event_id
            row["content_revision_number"] = content.revision_number
        rows.append(row)
    columns = _feature_columns()
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["eligible_session_open", "issuer_symbol", "source_event_id"],
        ignore_index=True,
    )


def _current_document(
    active: tuple[ResolvedReport, ...],
    state_event: ReportEvent,
) -> ResolvedReport | None:
    """Nahodit tekushchee soderzhimoe imenno izmenennogo dokumenta."""
    for item in active:
        if (
            item.content_event.issuer.symbol == state_event.issuer.symbol
            and item.document_id == state_event.document_id
        ):
            return item
    return None


def _prior_same_period(
    active: tuple[ResolvedReport, ...],
    current: ReportEvent,
) -> ReportEvent | None:
    """Vybirayet poslednyuyu izvestnuyu versiyu togo zhe perioda godom ran'she."""
    candidates = [
        item
        for item in active
        if item.content_event.issuer.symbol == current.issuer.symbol
        and item.content_event.filing_kind is current.filing_kind
        and item.content_event.period.fiscal_year == current.period.fiscal_year - 1
        and item.content_event.period.same_period_key == current.period.same_period_key
    ]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda item: (
            item.state_event.published_at,
            item.content_event.revision_number,
            item.document_id,
        ),
    )
    return selected.content_event


def _base_row(
    event: ReportEvent,
    eligible_open: pd.Timestamp,
    active: bool,
) -> dict[str, Any]:
    """Sozdaet audit-polya, ne zavisyashchie ot soderzhimogo dokumenta."""
    return {
        "issuer_symbol": event.issuer.symbol,
        "document_id": event.document_id,
        "source_event_id": event.source_event_id,
        "content_source_event_id": None,
        "action": event.action.value,
        "revision_number": event.revision_number,
        "content_revision_number": np.nan,
        "published_at": pd.Timestamp(event.published_at).tz_convert("UTC"),
        "eligible_session_open": eligible_open,
        "document_active": int(active),
        "filing_kind": event.filing_kind.value,
        "fiscal_year": event.period.fiscal_year,
        "fiscal_months": event.period.fiscal_months,
        "artifact_sha256": event.artifact.content_sha256,
        "is_revision_event": int(event.action is FilingEventAction.REVISED),
    }


def _verified_metric_map(event: ReportEvent | None) -> dict[NumericMetric, NumericFact]:
    """Beret tol'ko proverennye chisla i otklonyaet dvusmyslennyi metric."""
    selected: dict[NumericMetric, NumericFact] = {}
    if event is None:
        return selected
    for fact in event.numeric_facts:
        if not fact.verified:
            continue
        if fact.metric in selected:
            raise ValueError(f"Neskol'ko verified faktov dlya metric={fact.metric.value}")
        selected[fact.metric] = fact
    return selected


def _add_numeric_features(
    row: dict[str, Any],
    current: ReportEvent,
    prior: ReportEvent | None,
) -> None:
    """Dobavlyaet proverennye YoY surprise, sohranyaya NaN pri otsutstvii dokazatel'stv."""
    current_facts = _verified_metric_map(current)
    prior_facts = _verified_metric_map(prior)
    for metric in FEATURE_METRICS:
        prefix = metric.value
        fact = current_facts.get(metric)
        if fact is None:
            _set_missing_metric(row, prefix)
            continue
        value = fact.normalized_value
        comparison = prior_facts.get(metric)
        comparable = comparison is not None and comparison.comparison_key == fact.comparison_key
        prior_value = (
            comparison.normalized_value
            if comparable and comparison is not None
            else np.nan
        )
        surprise_abs = value - prior_value if comparable else np.nan
        surprise_pct = (
            surprise_abs / abs(prior_value)
            if comparable and prior_value != 0.0
            else np.nan
        )
        row[f"{prefix}__present"] = 1
        row[f"{prefix}__value"] = value
        row[f"{prefix}__prior_same_period"] = prior_value
        row[f"{prefix}__surprise_abs"] = surprise_abs
        row[f"{prefix}__surprise_pct"] = surprise_pct


def _add_missing_numeric_features(row: dict[str, Any]) -> None:
    """Zapolnyaet otsutstvuyushchee soderzhimoe NaN, no nikogda synthetic nulem."""
    for metric in FEATURE_METRICS:
        _set_missing_metric(row, metric.value)


def _set_missing_metric(row: dict[str, Any], prefix: str) -> None:
    """Dobavlyaet odin yavnyi missing-blok fundamental'nogo pokazatelya."""
    row[f"{prefix}__present"] = 0
    row[f"{prefix}__value"] = np.nan
    row[f"{prefix}__prior_same_period"] = np.nan
    row[f"{prefix}__surprise_abs"] = np.nan
    row[f"{prefix}__surprise_pct"] = np.nan


def _add_text_features(row: dict[str, Any], content: ReportEvent) -> None:
    """Perenosit tol'ko validirovannuyu metadata embedding i ee gotovyi pairwise delta."""
    metadata = content.text_metadata
    row["text_status"] = metadata.status.value
    row["text_embedding_available"] = int(metadata.status is TextEmbeddingStatus.EMBEDDED)
    row["text_embedding_model"] = metadata.embedding_model
    row["text_embedding_sha256"] = metadata.embedding_sha256
    row["text_previous_embedding_sha256"] = metadata.previous_embedding_sha256
    row["text_cosine_delta_from_previous"] = (
        metadata.cosine_delta_from_previous
        if metadata.cosine_delta_from_previous is not None
        else np.nan
    )


def _add_missing_text_features(row: dict[str, Any]) -> None:
    """Fiksiruet otsutstvie teksta bez synthetic embedding ili delta."""
    row["text_status"] = TextEmbeddingStatus.NOT_EXTRACTED.value
    row["text_embedding_available"] = 0
    row["text_embedding_model"] = None
    row["text_embedding_sha256"] = None
    row["text_previous_embedding_sha256"] = None
    row["text_cosine_delta_from_previous"] = np.nan


def _feature_columns() -> list[str]:
    """Vozvrashchaet stabil'nyi poryadok kolonok dlya Parquet i hash-audita."""
    columns = [
        "issuer_symbol",
        "document_id",
        "source_event_id",
        "content_source_event_id",
        "action",
        "revision_number",
        "content_revision_number",
        "published_at",
        "eligible_session_open",
        "document_active",
        "filing_kind",
        "fiscal_year",
        "fiscal_months",
        "artifact_sha256",
        "is_revision_event",
    ]
    for metric in FEATURE_METRICS:
        columns.extend(
            [
                f"{metric.value}__present",
                f"{metric.value}__value",
                f"{metric.value}__prior_same_period",
                f"{metric.value}__surprise_abs",
                f"{metric.value}__surprise_pct",
            ]
        )
    columns.extend(
        [
            "text_status",
            "text_embedding_available",
            "text_embedding_model",
            "text_embedding_sha256",
            "text_previous_embedding_sha256",
            "text_cosine_delta_from_previous",
        ]
    )
    return columns
