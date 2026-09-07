"""Synthetic-only alignment: future targets cannot determine an earlier decision."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from market_lab.futures.algopack_paper_alignment_v1 import (
    FlowVersion,
    OpenObservation,
    bucket_end,
    mature_label,
    next_entry_boundary,
    select_flow,
    select_training_flow,
)

END = datetime(2025, 9, 8, 8, 0, tzinfo=UTC)
DECISION = END + timedelta(minutes=4)


def versions():
    return tuple(
        FlowVersion(
            dataset,
            "SI",
            "SiU5",
            "2025-09-08",
            clock,
            END + timedelta(minutes=1),
            f"{index:064x}",
            (2.0, 1.0, 4.0, 2.0),
        )
        for index, (dataset, clock) in enumerate(
            (dataset, clock)
            for dataset in ("tradestats", "obstats")
            for clock in ("10:55:00", "11:00:00")
        )
    )


def select(rows=None, **kwargs):
    args = dict(asset="SI", secid="SiU5", information_end=END, decision_at=DECISION)
    args.update(kwargs)
    return select_flow(versions() if rows is None else rows, **args)


def opens():
    entry = next_entry_boundary(DECISION)
    return tuple(
        OpenObservation(
            "SI",
            "SiU5",
            entry + i * timedelta(minutes=10),
            entry + (i + 1) * timedelta(minutes=10),
            100.0 + i,
        )
        for i in range(7)
    )


def label(rows=None, **kwargs):
    args = dict(
        asset="SI", secid="SiU5", decision_at=DECISION, evaluated_at=END + timedelta(hours=2)
    )
    args.update(kwargs)
    return mature_label(opens() if rows is None else rows, **args)


def test_end_label_not_start_label():
    assert bucket_end("2025-09-08", "11:00:00") == END


@pytest.mark.parametrize(
    "date,clock",
    [("2025-9-08", "11:00:00"), ("2025-09-08", "11:02:00"), ("2025-09-08", "11:00:01")],
)
def test_noncanonical_or_offgrid_rejected(date, clock):
    with pytest.raises(ValueError):
        bucket_end(date, clock)


def test_next_open_strictly_later_even_at_exact_boundary():
    assert next_entry_boundary(END) == END + timedelta(minutes=10)
    assert next_entry_boundary(DECISION) == END + timedelta(minutes=10)


def test_complete_features_and_provenance():
    result = select()
    assert result.status == "READY"
    assert result.features[:4] == pytest.approx((1 / 3,) * 4)
    assert len(result.version_ids) == 4
    assert result.available_at == END + timedelta(minutes=1)


def test_future_revision_cannot_change_prior_features():
    future = replace(
        versions()[0],
        values=(999.0,) * 4,
        available_at=DECISION + timedelta(seconds=1),
        version_sha256="f" * 64,
    )
    assert select((*versions(), future)) == select()


def test_latest_available_revision_selected_without_rewriting_old_decision():
    revision = replace(
        versions()[0],
        values=(10.0, 1.0, 4.0, 2.0),
        available_at=END + timedelta(minutes=3),
        version_sha256="f" * 64,
    )
    rows = (*versions(), revision)
    assert select(rows).version_ids[0] == "f" * 64
    assert select(rows, decision_at=END + timedelta(minutes=2)) == select(
        decision_at=END + timedelta(minutes=2)
    )


def test_conflicting_receipts_rejected():
    conflict = replace(versions()[0], values=(8.0,) * 4)
    with pytest.raises(ValueError, match="conflicting"):
        select((*versions(), conflict))


@pytest.mark.parametrize("index", range(4))
def test_missing_bucket_never_filled(index):
    rows = versions()
    assert select(rows[:index] + rows[index + 1 :]).status == "MISSING_BUCKET"


def test_wrong_contract_does_not_fill_gap():
    rows = (replace(versions()[0], secid="SiZ5"), *versions()[1:])
    assert select(rows).status == "MISSING_BUCKET"


def test_missing_and_known_zero_remain_distinct():
    missing = (replace(versions()[0], values=(None, 1.0, 4.0, 2.0)), *versions()[1:])
    zero = tuple(replace(row, values=(0.0,) * 4) for row in versions())
    assert select(missing).status == "MISSING_FIELD"
    assert select(zero).status == "UNDEFINED_RATIO"


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), True])
def test_invalid_numeric_fields_rejected(value):
    with pytest.raises(ValueError):
        replace(versions()[0], values=(value, 1.0, 4.0, 2.0))


def test_receipt_before_vendor_end_is_not_backdated():
    rows = tuple(replace(row, available_at=END - timedelta(minutes=6)) for row in versions())
    assert select(rows).status == "LABEL_RECEIPT_CONFLICT"


def test_stale_and_weekend_not_guessed():
    assert select(decision_at=END + timedelta(minutes=10)).status == "STALE_INFORMATION"
    weekend = END - timedelta(days=1)
    assert select(information_end=weekend, decision_at=weekend).status == "UNRESOLVED_SESSION"


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        select(decision_at=DECISION.replace(tzinfo=None))


def test_future_labels_never_change_inference():
    before = select()
    assert label().status == "READY"
    assert label(()).status == "MISSING_EXACT_PATH"
    assert select() == before


def test_mature_exact_label():
    import math

    result = label()
    assert result.status == "READY"
    assert result.exit_at - result.entry_at == timedelta(minutes=60)
    assert result.log_return == pytest.approx(math.log(1.06))


@pytest.mark.parametrize("index", range(7))
def test_label_gap_or_roll_is_unresolved(index):
    rows = opens()
    assert label(rows[:index] + rows[index + 1 :]).status == "MISSING_EXACT_PATH"
    rolled = rows[:index] + (replace(rows[index], secid="SiZ5"),) + rows[index + 1 :]
    assert label(rolled).status == "MISSING_EXACT_PATH"


def test_no_partial_or_future_receipts_in_label():
    assert label(evaluated_at=END + timedelta(minutes=75)).status == "NOT_MATURE"
    rows = (*opens()[:-1], replace(opens()[-1], available_at=END + timedelta(days=1)))
    assert label(rows).status == "MISSING_EXACT_PATH"
    rows = (replace(opens()[0], available_at=opens()[0].begin), *opens()[1:])
    assert label(rows).status == "INCOMPLETE_BAR_RECEIPT"


def test_duplicate_label_or_invalid_price_not_silently_resolved():
    with pytest.raises(ValueError, match="duplicate"):
        label((*opens(), opens()[0]))
    assert label((replace(opens()[0], open_price=None), *opens()[1:])).status == "INVALID_OPEN"


def test_all_zero_one_side_is_valid_not_missing():
    rows = tuple(replace(row, values=(4.0, 0.0, 4.0, 0.0)) for row in versions())
    assert select(rows).features[:4] == (1.0,) * 4


def test_training_cutoff_does_not_backdate_archive():
    received = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    rows = tuple(replace(row, available_at=received) for row in versions())
    result = select_training_flow(
        rows,
        asset="SI",
        secid="SiU5",
        information_end=END,
        training_cutoff=received + timedelta(minutes=1),
    )
    assert result.status == "READY_ARCHIVE_ASSUMPTION"
    assert result.available_at == received
    assert select(rows).status == "MISSING_BUCKET"
    assert (
        select_training_flow(
            rows,
            asset="SI",
            secid="SiU5",
            information_end=END,
            training_cutoff=received - timedelta(seconds=1),
        ).status
        == "MISSING_BUCKET"
    )


@pytest.mark.parametrize(
    "end",
    [
        datetime(2019, 12, 31, 12, tzinfo=UTC),
        datetime(2026, 1, 1, 12, tzinfo=UTC),
        datetime(2025, 12, 31, 22, tzinfo=UTC),
    ],
)
def test_training_boundary_rejects_protected_vendor_or_utc_date(end):
    with pytest.raises(ValueError, match="boundary|protected"):
        select_training_flow(
            (),
            asset="SI",
            secid="SiU5",
            information_end=end,
            training_cutoff=datetime(2026, 9, 7, tzinfo=UTC),
        )
