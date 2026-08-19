"""Causality and isolation tests for the sparse Event Alpha V1 challenger."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from market_lab.event_alpha_v1.core import (
    attach_causal_targets,
    build_cbr_events,
    evaluate_expanding_folds,
    expanding_prior_z,
    prepare_price_panel,
    validate_text_fact_payload,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _protocol() -> dict[str, object]:
    """Loads the already frozen protocol without accessing any return artifact."""
    return yaml.safe_load(
        (PROJECT_ROOT / "configs/event_alpha_v1.yaml").read_text(encoding="utf-8-sig")
    )


def _event(available_at: str = "2021-02-01T12:00:00Z") -> pd.DataFrame:
    """Builds one price-free synthetic event row."""
    return pd.DataFrame(
        [
            {
                "event_id": "event-1",
                "event_family": "cbr_key_rate_change",
                "source": "cbr",
                "available_at": pd.Timestamp(available_at),
                "observation_at": pd.Timestamp("2021-02-01"),
                "asset": "SI",
                "innovation_z": 2.0,
                "innovation_raw": 0.25,
                "level": 5.0,
                "prior_innovation_raw": -0.25,
                "direction": 1.0,
                "absolute_innovation_z": 2.0,
                "release_source": "synthetic-test",
                "source_revision_id": "a" * 64,
                "pit_grade": "synthetic-test",
            }
        ]
    )


def _prices(*, roll_at: int | None = None) -> pd.DataFrame:
    """Builds exact active daily opens with an optional contract boundary."""
    times = pd.date_range("2020-12-20", periods=80, freq="D", tz="UTC")
    contracts = ["SI:H1"] * len(times)
    if roll_at is not None:
        contracts[roll_at:] = ["SI:M1"] * (len(times) - roll_at)
    return pd.DataFrame(
        {
            "asset_code": "SI",
            "contract_id": contracts,
            "conservative_open_at": times,
            "open": np.linspace(70_000.0, 74_000.0, len(times)),
            "is_active_contract": True,
            "exact_open_available": True,
        }
    )


def test_expanding_z_is_prior_only_and_future_mutation_invariant() -> None:
    """A later extreme release cannot alter any earlier standardized innovation."""
    prefix = np.array([1.0, 2.0, 3.0, 4.0])
    base = expanding_prior_z(prefix, 2)
    mutated = expanding_prior_z(np.r_[prefix, 1_000_000.0], 2)
    np.testing.assert_array_equal(base, mutated[: len(prefix)])
    assert base[2] == pytest.approx(3.0)


def test_target_starts_strictly_after_event_and_uses_same_contract() -> None:
    """Entry is the next open, context is prior-only and a roll boundary sleeps."""
    events = _event()
    attached = attach_causal_targets(events, _prices(), [1, 5])
    assert set(attached["horizon_sessions"]) == {1, 5}
    assert (attached["available_at"] < attached["entry_at"]).all()
    assert (attached["entry_at"] < attached["exit_at"]).all()
    assert (attached["contract_id"] == "SI:H1").all()
    rolled = attach_causal_targets(events, _prices(roll_at=46), [1, 5])
    assert len(rolled) < len(attached)


def test_duplicate_and_revision_conflict_fail_closed() -> None:
    """Two IDs for one source observation cannot masquerade as separate releases."""
    first = _event()
    duplicate = pd.concat([first, first], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate"):
        attach_causal_targets(duplicate, _prices(), [1])
    revised = pd.concat(
        [first, first.assign(event_id="event-2", source_revision_id="b" * 64)],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="Revision conflict"):
        attach_causal_targets(revised, _prices(), [1])


def test_text_extractor_is_isolated_from_prices_and_labels() -> None:
    """Qwen facts need page evidence and cannot carry a market target."""
    validate_text_fact_payload(
        {
            "metric": "revenue",
            "value": 123.0,
            "unit": "rub",
            "page_evidence": "page=7; table=revenue",
        }
    )
    with pytest.raises(ValueError, match="forbidden"):
        validate_text_fact_payload(
            {"metric": "revenue", "value": 123.0, "target": 0.05, "page_evidence": "page=7"}
        )
    with pytest.raises(ValueError, match="page evidence"):
        validate_text_fact_payload({"metric": "revenue", "value": 123.0})


def test_protected_future_price_row_is_rejected_before_feature_use() -> None:
    """A 2026 mutation is a hard failure rather than an as-of filtering opportunity."""
    mutated = pd.concat(
        [
            _prices(),
            pd.DataFrame(
                [
                    {
                        "asset_code": "SI",
                        "contract_id": "SI:H6",
                        "conservative_open_at": pd.Timestamp("2026-01-02T16:00:00Z"),
                        "open": 999_999.0,
                        "is_active_contract": True,
                        "exact_open_available": True,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="Protected 2026"):
        prepare_price_panel(mutated)


def test_cbr_key_rate_history_counts_changes_not_stale_daily_repeats() -> None:
    """Key-rate z history advances only when the official level actually changes."""
    protocol = _protocol()
    rows: list[dict[str, object]] = []
    start = pd.Timestamp("2018-01-01")
    levels = [7.5]
    for index in range(1, 12):
        levels.append(levels[-1] + (0.25 if index % 2 else 0.50))
    for index, level in enumerate(levels):
        for stale_day in range(3):
            observed = start + pd.Timedelta(days=index * 4 + stale_day)
            rows.append(
                {
                    "series_id": "key_rate",
                    "observation_date": observed,
                    "available_at": observed.tz_localize("UTC") + pd.Timedelta(days=1),
                    "value": level,
                    "availability_rule": "test",
                }
            )
    for series_id, transform in (
        ("ruonia", lambda index: 6.0 + np.sin(index / 5.0)),
        ("usd_rub_official", lambda index: 60.0 + index * 0.01),
    ):
        for index in range(100):
            observed = start + pd.Timedelta(days=index)
            rows.append(
                {
                    "series_id": series_id,
                    "observation_date": observed,
                    "available_at": observed.tz_localize("UTC") + pd.Timedelta(hours=21),
                    "value": transform(index),
                    "availability_rule": "test",
                }
            )
    events = build_cbr_events(pd.DataFrame(rows), protocol, "c" * 64)
    key = events[events["event_family"] == "cbr_key_rate_change"]
    assert len(key) == 6
    assert key["event_id"].nunique() == 3


def test_purged_expanding_fold_never_uses_crossing_label() -> None:
    """Every persisted train-last-exit timestamp precedes the OOS year boundary."""
    protocol = _protocol()
    rows: list[dict[str, object]] = []
    for index, entry_at in enumerate(
        pd.date_range("2018-01-05", "2021-12-01", freq="7D", tz="UTC")
    ):
        rows.append(
            {
                "event_id": f"event-{index}",
                "event_family": "cftc_energy_tail",
                "source": "cftc",
                "available_at": entry_at - pd.Timedelta(hours=1),
                "observation_at": entry_at.tz_localize(None),
                "asset": "BR",
                "innovation_z": float(np.sin(index)),
                "innovation_raw": float(np.sin(index) / 10.0),
                "level": float(index / 100.0),
                "prior_innovation_raw": float(np.cos(index) / 10.0),
                "direction": float(np.sign(np.sin(index))),
                "absolute_innovation_z": abs(float(np.sin(index))),
                "prior_asset_momentum_20": float(np.cos(index) / 20.0),
                "prior_asset_volatility_20": 0.2 + (index % 5) / 100.0,
                "horizon_sessions": 5,
                "entry_at": entry_at,
                "exit_at": entry_at + pd.Timedelta(days=6),
                "target_log_return": float(np.sin(index + 1) / 100.0),
                "target_simple_return": float(np.sin(index + 1) / 100.0),
            }
        )
    predictions = evaluate_expanding_folds(pd.DataFrame(rows), protocol)
    assert not predictions.empty
    fold_start = pd.to_datetime(predictions["fold_year"].astype(str) + "-01-01", utc=True)
    assert (predictions["train_last_exit_at"].reset_index(drop=True) < fold_start).all()
    assert predictions["fold_year"].min() >= 2021


def test_frozen_protocol_excludes_2026_and_synthetic_corporate_metrics() -> None:
    """The human-readable contract keeps holdout and fake reports outside metrics."""
    protocol = _protocol()
    assert protocol["protected_holdout_start"] == date(2026, 1, 1)
    assert protocol["forbid_2026_rows"] is True
    assert protocol["corporate_reporting"]["status"] == "sleeping_legal_and_pit_blocker"
    assert protocol["corporate_reporting"]["eligible_issuers"] == []
