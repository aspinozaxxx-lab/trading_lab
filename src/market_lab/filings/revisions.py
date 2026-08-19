"""Deterministicheskaya deduplikaciya i as-of obrabotka versii dokumentov."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_lab.filings.schema import FilingEventAction, ReportEvent, event_fingerprint


@dataclass(frozen=True, slots=True)
class ResolvedReport:
    """Hranit aktivnoe soderzhimoe i poslednee izvestnoe state-sobytie dokumenta."""

    document_id: str
    content_event: ReportEvent
    state_event: ReportEvent


def deduplicate_report_events(
    events: list[ReportEvent] | tuple[ReportEvent, ...],
) -> tuple[ReportEvent, ...]:
    """Skleivaet identichnye provider-events i otklonyaet konflikty odnogo ID."""
    selected: dict[tuple[str, str], ReportEvent] = {}
    fingerprints: dict[tuple[str, str], str] = {}
    for event in events:
        key = (event.artifact.source_kind.value, event.source_event_id)
        fingerprint = event_fingerprint(event)
        if key in fingerprints and fingerprints[key] != fingerprint:
            raise ValueError(f"Konflikt soderzhimogo dlya source_event_id={event.source_event_id}")
        fingerprints[key] = fingerprint
        previous = selected.get(key)
        if previous is None or event.artifact.retrieved_at < previous.artifact.retrieved_at:
            selected[key] = event
    return tuple(sorted(selected.values(), key=_event_order_key))


def validate_revision_chains(
    events: list[ReportEvent] | tuple[ReportEvent, ...],
) -> tuple[ReportEvent, ...]:
    """Proveryaet ssylki nazad, rost nomera versii i strogoe vremya v dokumente."""
    unique = deduplicate_report_events(events)
    by_document: dict[tuple[str, str], list[ReportEvent]] = {}
    for event in unique:
        by_document.setdefault((event.issuer.symbol, event.document_id), []).append(event)
    for document_events in by_document.values():
        known: dict[str, ReportEvent] = {}
        last_time: datetime | None = None
        last_revision = -1
        active = False
        root: ReportEvent | None = None
        roots = 0
        for event in sorted(document_events, key=_event_order_key):
            if last_time is not None and event.published_at <= last_time:
                raise ValueError("Versii odnogo dokumenta dolzhny imet' strogo rastushchee vremya")
            last_time = event.published_at
            if event.action is FilingEventAction.PUBLISHED:
                roots += 1
                root = event
                active = True
            else:
                referenced = known.get(str(event.revision_of_event_id))
                if referenced is None:
                    raise ValueError(
                        "revision_of ssylayetsya na neizvestnoe ili budushchee sobytie"
                    )
                if event.revision_number <= referenced.revision_number:
                    raise ValueError("Nomer revizii dolzhen rasti")
                if event.revision_number <= last_revision:
                    raise ValueError("Revizii dokumenta dolzhny monotonno rasti vo vremeni")
                if root is None or (
                    event.filing_kind is not root.filing_kind
                    or event.period != root.period
                    or event.artifact.source_kind is not root.artifact.source_kind
                ):
                    raise ValueError("Reviziya izmenila identichnost' dokumenta")
                if event.action is FilingEventAction.REVISED and not active:
                    raise ValueError("Reviziya udalennogo dokumenta trebuet snachala restore")
                if event.action is FilingEventAction.DELETED:
                    if not active:
                        raise ValueError("Nel'zya povtorno udalit' neaktivnyi dokument")
                    active = False
                elif event.action is FilingEventAction.RESTORED:
                    if active:
                        raise ValueError("Nel'zya restore uzhe aktivnyi dokument")
                    active = True
            known[event.source_event_id] = event
            last_revision = event.revision_number
        if roots != 1:
            raise ValueError("U dokumenta dolzhna byt' rovno odna pervaya publikaciya")
    return unique


def resolve_active_reports(
    events: list[ReportEvent] | tuple[ReportEvent, ...],
    as_of: datetime,
) -> tuple[ResolvedReport, ...]:
    """Vosstanavlivaet tol'ko aktivnye dokumenty iz sobytii, izvestnyh k as_of."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of dolzhen soderzhat' timezone")
    unique = validate_revision_chains(events)
    visible = [event for event in unique if event.published_at <= as_of]
    states: dict[tuple[str, str], tuple[ReportEvent | None, ReportEvent, bool]] = {}
    for event in sorted(visible, key=_event_order_key):
        key = (event.issuer.symbol, event.document_id)
        content, _, active = states.get(key, (None, event, False))
        if event.action in {FilingEventAction.PUBLISHED, FilingEventAction.REVISED}:
            content = event
            active = True
        elif event.action is FilingEventAction.DELETED:
            active = False
        elif event.action is FilingEventAction.RESTORED:
            if content is None:
                raise ValueError("Nel'zya vosstanovit' dokument bez izvestnogo soderzhimogo")
            active = True
        states[key] = (content, event, active)
    resolved = [
        ResolvedReport(document_id=key[1], content_event=content, state_event=state)
        for key, (content, state, active) in states.items()
        if active and content is not None
    ]
    return tuple(
        sorted(
            resolved,
            key=lambda item: (
                item.content_event.issuer.symbol,
                item.document_id,
                item.state_event.published_at,
            ),
        )
    )


def _event_order_key(event: ReportEvent) -> tuple[datetime, int, str, str]:
    """Zadaet edinstvennyi poryadok sobytii dlya povtoryaemyh vychislenii."""
    return (
        event.published_at,
        event.revision_number,
        event.issuer.symbol,
        event.source_event_id,
    )
