"""Testy point-in-time foundation raskrytii bez seti, cen i frozen holdout."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from market_lab.filings import (
    AtomicFilingStore,
    FilingEventAction,
    FilingSourceKind,
    IssuerIdentity,
    ReportEvent,
    ReportPeriod,
    SourceArtifact,
    build_causal_report_features,
    deduplicate_report_events,
    default_residual_target_specs,
    first_eligible_session_open,
    report_event_from_mapping,
    require_bulk_authorization,
    resolve_active_reports,
    source_access_policy,
)
from market_lab.io_utils import read_text

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "filings_point_in_time.json"  # Fake PIT events.


@pytest.fixture
def report_events() -> tuple[ReportEvent, ...]:
    """Chitaet tol'ko synthetic SBER fixture iz development allowlist."""
    payload = json.loads(read_text(FIXTURE_PATH))
    return tuple(report_event_from_mapping(item) for item in payload)


def _artifact(seed: str, published_at: datetime) -> SourceArtifact:
    """Stroit synthetic provenance dlya state-events revizii."""
    return SourceArtifact(
        source_kind=FilingSourceKind.INTERFAX_GATEWAY,
        source_url=f"https://gateway.e-disclosure.ru/fake/{seed}",
        retrieved_at=published_at,
        content_sha256=seed * 64,
        byte_size=0,
        media_type="application/json",
        attachment_uid=seed,
    )


def _state_event(
    base: ReportEvent,
    event_id: str,
    action: FilingEventAction,
    revision_number: int,
    revision_of: str,
    published_at: datetime,
    seed: str,
) -> ReportEvent:
    """Stroit synthetic delete/restore bez kopirovaniya fundamental'nyh facts."""
    return replace(
        base,
        source_event_id=event_id,
        action=action,
        revision_number=revision_number,
        revision_of_event_id=revision_of,
        published_at=published_at,
        artifact=_artifact(seed, published_at),
        numeric_facts=(),
    )


def test_allowlist_and_protected_period_fail_closed(report_events: tuple[ReportEvent, ...]) -> None:
    """Zapreshchaet frozen19, neizvestnyi ticker i lyubuyu publikaciyu s 2026 goda."""
    with pytest.raises(ValueError, match="allowlist"):
        IssuerIdentity("YDEX", "Frozen issuer", "7700000000")
    with pytest.raises(ValueError, match="allowlist"):
        IssuerIdentity("UNKNOWN", "Unknown issuer", "7700000000")
    with pytest.raises(ValueError, match="holdout"):
        replace(report_events[0], published_at=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="holdout"):
        ReportPeriod(
            fiscal_year=2026,
            fiscal_months=3,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
        )


def test_first_eligible_open_is_strictly_after_publication() -> None:
    """Razreshaet pre-open v tot zhe den', no exact-open perenosit na sleduyushchuyu sessiyu."""
    opens = pd.to_datetime(
        ["2025-03-03T07:00:00Z", "2025-03-04T07:00:00Z", "2025-03-05T07:00:00Z"],
        utc=True,
    )
    before = datetime(2025, 3, 3, 6, 59, 59, tzinfo=UTC)
    exact = datetime(2025, 3, 3, 7, 0, 0, tzinfo=UTC)
    assert first_eligible_session_open(before, opens) == opens[0]
    assert first_eligible_session_open(exact, opens) == opens[1]


def test_deduplication_and_revision_asof_are_deterministic(
    report_events: tuple[ReportEvent, ...],
) -> None:
    """Skleivaet povtornuyu zagruzku i vybirayet tol'ko izvestnuyu k as_of versiyu."""
    current, revised = report_events[1:]
    later_retrieval = replace(
        current,
        artifact=replace(
            current.artifact,
            retrieved_at=current.artifact.retrieved_at + pd.Timedelta(days=1),
        ),
    )
    unique = deduplicate_report_events((revised, current, later_retrieval))
    assert [event.source_event_id for event in unique] == [
        "fake-sber-2024-v0",
        "fake-sber-2024-v1",
    ]
    before_revision = resolve_active_reports(
        report_events,
        datetime(2025, 3, 4, tzinfo=UTC),
    )
    after_revision = resolve_active_reports(
        report_events,
        datetime(2025, 3, 6, tzinfo=UTC),
    )
    before_content = next(
        item for item in before_revision if item.document_id == current.document_id
    ).content_event
    after_content = next(
        item for item in after_revision if item.document_id == current.document_id
    ).content_event
    assert before_content is current
    assert after_content is revised
    conflicting = replace(current, artifact=replace(current.artifact, content_sha256="d" * 64))
    with pytest.raises(ValueError, match="Konflikt"):
        deduplicate_report_events((current, conflicting))


def test_delete_and_restore_do_not_rewrite_past(report_events: tuple[ReportEvent, ...]) -> None:
    """Udalyaet dokument tol'ko posle delete i vosstanavlivaet predydushchee soderzhimoe."""
    base, revised = report_events[1:]
    deleted = _state_event(
        base,
        "fake-sber-2024-delete",
        FilingEventAction.DELETED,
        2,
        revised.source_event_id,
        datetime(2025, 3, 7, 9, tzinfo=UTC),
        "d",
    )
    restored = _state_event(
        base,
        "fake-sber-2024-restore",
        FilingEventAction.RESTORED,
        3,
        deleted.source_event_id,
        datetime(2025, 3, 10, 9, tzinfo=UTC),
        "e",
    )
    history = (*report_events, deleted, restored)
    during_delete = resolve_active_reports(history, datetime(2025, 3, 8, tzinfo=UTC))
    after_restore = resolve_active_reports(history, datetime(2025, 3, 11, tzinfo=UTC))
    assert all(item.document_id != base.document_id for item in during_delete)
    restored_state = next(item for item in after_restore if item.document_id == base.document_id)
    assert restored_state.content_event.source_event_id == revised.source_event_id
    assert restored_state.state_event.source_event_id == restored.source_event_id


def test_features_are_causal_and_invariant_to_future_revision(
    report_events: tuple[ReportEvent, ...],
) -> None:
    """Dokazyvaet, chto budushchaya reviziya ne menyaet ran'she dostupnyi feature-row."""
    opens = pd.to_datetime(
        [
            "2024-03-04T07:00:00Z",
            "2025-03-03T07:00:00Z",
            "2025-03-04T07:00:00Z",
            "2025-03-05T07:00:00Z",
            "2025-03-06T07:00:00Z",
        ],
        utc=True,
    )
    baseline = build_causal_report_features(report_events[:2], opens)
    with_future = build_causal_report_features(report_events, opens)
    pd.testing.assert_frame_equal(baseline, with_future.iloc[:2].reset_index(drop=True))
    current = baseline.loc[baseline["source_event_id"] == "fake-sber-2024-v0"].iloc[0]
    assert current["eligible_session_open"] == opens[1]
    assert current["revenue__value"] == pytest.approx(120_000_000_000.0)
    assert current["revenue__surprise_abs"] == pytest.approx(20_000_000_000.0)
    assert current["revenue__surprise_pct"] == pytest.approx(0.20)
    assert current["free_cash_flow__present"] == 0
    assert pd.isna(current["free_cash_flow__value"])
    assert current["text_embedding_available"] == 0


def test_atomic_store_verifies_raw_hash_and_writes_processed(
    tmp_path: Path,
    report_events: tuple[ReportEvent, ...],
) -> None:
    """Proveryaet hash-before-write, BOM metadata i atomarnyi Parquet pod project root."""
    content = b"synthetic filing bytes"
    digest = hashlib.sha256(content).hexdigest()
    event = replace(
        report_events[0],
        artifact=replace(
            report_events[0].artifact,
            content_sha256=digest,
            byte_size=len(content),
        ),
    )
    store = AtomicFilingStore(tmp_path)
    raw_path, metadata_path = store.write_raw_event(event, content)
    assert raw_path.read_bytes() == content
    assert metadata_path.read_bytes().startswith(b"\xef\xbb\xbf")
    processed_path = store.write_processed_events((event,))
    assert processed_path.is_relative_to(tmp_path)
    assert pd.read_parquet(processed_path)["source_event_id"].tolist() == [event.source_event_id]
    with pytest.raises(ValueError, match="content_sha256"):
        store.write_raw_event(event, b"tampered")
    with pytest.raises(ValueError, match="filename"):
        store.write_processed_frame(pd.DataFrame(), "../escape.parquet")


def test_source_policy_and_target_schema_have_fail_closed_defaults() -> None:
    """Fiksiruet avtorizaciyu Gateway i target-skhemu bez prava chitat' ceny."""
    gateway = source_access_policy(FilingSourceKind.INTERFAX_GATEWAY)
    portal = source_access_policy(FilingSourceKind.INTERFAX_PORTAL)
    assert gateway.automated_interface
    assert gateway.authentication_required
    assert gateway.revision_events_expected
    assert gateway.attachment_download_expected
    assert not gateway.bulk_research_approved
    assert not portal.automated_interface
    with pytest.raises(PermissionError, match="Bulk"):
        require_bulk_authorization(FilingSourceKind.INTERFAX_GATEWAY, contract_confirmed=False)
    targets = default_residual_target_specs()
    assert [target.horizon_sessions for target in targets] == [1, 5, 20]
    assert all(not target.price_access_permitted for target in targets)
