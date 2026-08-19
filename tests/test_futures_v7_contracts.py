"""Synthetic testy config, timing, masks i SSL-dataset futures-v7."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from market_lab.futures_v7.config import (
    DEFAULT_V7_CONFIG_SHA256,
    V7ResearchConfig,
    byte_sha256,
    load_v7_research_config,
)
from market_lab.futures_v7.contracts import (
    DecisionTimingBatch,
    mask_daily_context_as_of,
    next_open_to_next_open_log_return,
    supervised_train_indices,
)
from market_lab.futures_v7.dataset import (
    CausalMultiResolutionDataset,
    MultiResolutionArrays,
    build_self_supervised_targets,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren s zapechatannym v7-config.
V7_CONFIG_PATH = (  # Kanonicheskii development config bez dostupa k dannym.
    PROJECT_ROOT / "configs" / "futures_v7_development_protocol.yaml"
)


def _timing(sample_count: int, bar_count: int) -> DecisionTimingBatch:
    """Stroit strogo causal synthetic timing s obshchim cross-asset kalendarem."""
    start = np.datetime64("2025-01-01T08:00:00", "ns")
    offsets = np.arange(bar_count) * np.timedelta64(10, "m")
    bars = np.stack(
        [start + offsets + sample * np.timedelta64(7, "D") for sample in range(sample_count)]
    )
    decisions = bars[:, -1] + np.timedelta64(1, "m")
    entries = decisions + np.timedelta64(9, "m")
    exits = entries + np.timedelta64(1, "D")
    return DecisionTimingBatch(bars, decisions, entries, exits)


def _arrays(config: V7ResearchConfig, sample_count: int = 2) -> MultiResolutionArrays:
    """Stroit malyi massivo-ustoychivyi synthetic dataset s missing cells."""
    rng = np.random.default_rng(1729)
    asset_count = len(config.development.assets)
    bar_count = config.model.sequence_bars
    feature_count = len(config.model.bar_feature_names)
    daily_count = len(config.model.daily_feature_names)
    intraday = rng.normal(size=(sample_count, asset_count, bar_count, feature_count)).astype(
        np.float32
    )
    intraday_valid = np.ones(intraday.shape[:3], dtype=bool)
    intraday_valid[0, 1, 100] = False
    intraday[0, 1, 100] = np.nan
    daily = rng.normal(size=(sample_count, asset_count, daily_count)).astype(np.float32)
    daily_valid = np.ones(daily.shape, dtype=bool)
    daily_valid[0, 2, 4] = False
    daily[0, 2, 4] = np.nan
    asset_valid = np.ones((sample_count, asset_count), dtype=bool)
    target = rng.normal(size=(sample_count, asset_count)).astype(np.float32)
    target_valid = np.ones(target.shape, dtype=bool)
    target_valid[1, 3] = False
    target[1, 3] = np.nan
    return MultiResolutionArrays(
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily,
        daily_valid=daily_valid,
        asset_valid=asset_valid,
        supervised_target=target,
        supervised_valid=target_valid,
        timing=_timing(sample_count, bar_count),
    )


def test_v7_config_byte_seal_and_fixed_protocol() -> None:
    """Proveryaet exact hash, pyat' foldov, purge, v6 benchmark i holdout lock."""
    assert byte_sha256(V7_CONFIG_PATH) == DEFAULT_V7_CONFIG_SHA256
    config = load_v7_research_config(V7_CONFIG_PATH)
    assert tuple(fold.score_start.year for fold in config.development.folds) == tuple(
        range(2021, 2026)
    )
    assert config.development.purge_sessions == 5
    assert config.development.protected_holdout_local_read_allowed is False
    assert config.development.protected_holdout_network_download_allowed is False
    assert config.execution.slippage_ticks == (1, 2, 4)
    assert config.execution.fee_multipliers == (1.0, 2.0)


def test_v7_semantic_drift_is_rejected_without_oos_tuning() -> None:
    """Proveryaet otkaz pri smene width ili seed dazhe do real'nyh metrik."""
    payload = yaml.safe_load(V7_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    width_drift = deepcopy(payload)
    width_drift["model"]["width"] = 256
    with pytest.raises(ValidationError, match="Architecture drift v7"):
        V7ResearchConfig.model_validate(width_drift)
    seed_drift = deepcopy(payload)
    seed_drift["training"]["seeds"] = [1, 2, 3]
    with pytest.raises(ValidationError, match="Training drift v7"):
        V7ResearchConfig.model_validate(seed_drift)


def test_timing_contract_rejects_future_bar_and_orders_targets() -> None:
    """Proveryaet bars <= decision < entry open < exit open."""
    timing = _timing(2, 16)
    timing.validate()
    invalid_bars = timing.bar_times.copy()
    invalid_bars[0, -1] = timing.entry_open_times[0]
    with pytest.raises(ValueError, match="bar posle decision"):
        DecisionTimingBatch(
            invalid_bars,
            timing.decision_times,
            timing.entry_open_times,
            timing.exit_open_times,
        ).validate()


def test_daily_asof_mask_hides_unpublished_and_missing_values() -> None:
    """Proveryaet chto future release i NaN ne mogut proniknut' v model-input."""
    decision = np.array([np.datetime64("2025-01-10T15:50:00", "ns")])
    values = np.array([[[1.0, 999.0, np.nan]]], dtype=np.float32)
    available = np.array(
        [
            [
                [
                    np.datetime64("2025-01-10T12:00:00", "ns"),
                    np.datetime64("2025-01-10T16:00:00", "ns"),
                    np.datetime64("2025-01-10T10:00:00", "ns"),
                ]
            ]
        ]
    )
    snapshot = mask_daily_context_as_of(values, available, decision)
    assert snapshot.valid.tolist() == [[[True, False, False]]]
    assert snapshot.values.tolist() == [[[1.0, 0.0, 0.0]]]


def test_next_open_target_and_train_cutoff_use_exit_not_decision() -> None:
    """Proveryaet target-formulu i otsechenie primera po momentu exit-open."""
    target, valid = next_open_to_next_open_log_return(
        np.array([[100.0, 0.0]]),
        np.array([[110.0, 120.0]]),
    )
    assert target[0, 0] == pytest.approx(np.log(1.1))
    assert valid.tolist() == [[True, False]]
    timing = _timing(2, 8)
    selected = supervised_train_indices(timing, timing.exit_open_times[0])
    assert selected.tolist() == [0]


def test_ssl_targets_are_future_labels_but_never_model_inputs() -> None:
    """Proveryaet exact multi-horizon return/vol i poslednii invalidnyi hvost."""
    log_price = np.log(
        np.array([[[1.0, 2.0, 4.0, 8.0, 16.0]]], dtype=np.float64)
    )
    targets = build_self_supervised_targets(
        log_price,
        np.ones_like(log_price, dtype=bool),
        (1, 2),
    )
    assert targets.values.shape == (1, 1, 5, 2, 2)
    assert targets.values[0, 0, 0, 0, 0] == pytest.approx(np.log(2.0))
    assert targets.values[0, 0, 0, 1, 0] == pytest.approx(np.log(4.0))
    assert targets.values[0, 0, 0, 1, 1] == pytest.approx(np.log(2.0))
    assert not targets.valid[0, 0, -1].any()


def test_dataset_sanitizes_missing_cells_and_preserves_masks() -> None:
    """Proveryaet shape contract i nul' vmesto NaN bez poteri missing-mask."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    arrays = _arrays(config)
    dataset = CausalMultiResolutionDataset(arrays, config.model)
    sample = dataset[0]
    assert len(dataset) == 2
    assert sample["intraday"].shape == (4, 512, 12)
    assert sample["daily_context"].shape == (4, 16)
    assert sample["intraday"][1, 100].tolist() == [0.0] * 12
    assert not bool(sample["intraday_mask"][1, 100])
    assert sample["daily_context"][2, 4] == pytest.approx(0.0)
    assert not bool(sample["daily_mask"][2, 4])
