"""Synthetic testy train-only normalizacii i checkpointov futures-v7."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")  # Optional GPU-stack ne obyazatelen dlya bazovogo MVP.

from market_lab.futures_v7.config import V7FoldConfig, load_v7_research_config  # noqa: E402
from market_lab.futures_v7.contracts import DecisionTimingBatch  # noqa: E402
from market_lab.futures_v7.dataset import MultiResolutionArrays  # noqa: E402
from market_lab.futures_v7.model import (  # noqa: E402
    CausalMultiResolutionFuturesModel,
    masked_supervised_loss,
    set_v7_determinism,
)
from market_lab.futures_v7.training import (  # noqa: E402
    V7_RANKING_WEIGHT,
    DeterministicEpochSampler,
    arithmetic_ensemble_predictions,
    build_fold_training_scope,
    build_strict_fold_ssl_sample,
    build_v7_training_hashes,
    checkpoint_bytes,
    fit_fold_robust_scaler,
    fit_fold_target_iqr,
    fold_pairwise_ranking_loss,
    load_v7_checkpoint_bundle,
    masked_portfolio_supervised_loss,
    run_v7_fold_seed_training,
    save_v7_checkpoint_bundle,
    write_checkpoint_copy_atomic,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren s zapechatannym v7-config.
V7_CONFIG_PATH = (  # Kanonicheskii config dlya synthetic training-testov.
    PROJECT_ROOT / "configs" / "futures_v7_development_protocol.yaml"
)


def _synthetic_arrays() -> tuple[MultiResolutionArrays, np.ndarray]:
    """Stroit train 2020 i odin budushchii 2021 sample s polnym 512-bar oknom."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    rng = np.random.default_rng(1729)
    decision_days = [
        np.datetime64(f"2020-12-{day:02d}T15:50:00", "ns")
        for day in range(10, 22)
    ] + [np.datetime64("2021-01-05T15:50:00", "ns")]
    decisions = np.asarray(decision_days)
    bar_offsets = np.arange(config.model.sequence_bars, 0, -1) * np.timedelta64(10, "m")
    bar_times = np.stack([decision - bar_offsets for decision in decisions])
    entries = decisions + np.timedelta64(10, "m")
    exits = entries + np.timedelta64(16, "h")
    timing = DecisionTimingBatch(bar_times, decisions, entries, exits)
    sample_count = len(decisions)
    asset_count = len(config.development.assets)
    intraday = rng.normal(
        size=(
            sample_count,
            asset_count,
            config.model.sequence_bars,
            len(config.model.bar_feature_names),
        )
    ).astype(np.float32)
    intraday_valid = np.ones(intraday.shape[:3], dtype=bool)
    daily = rng.normal(
        size=(sample_count, asset_count, len(config.model.daily_feature_names))
    ).astype(np.float32)
    daily_valid = np.ones(daily.shape, dtype=bool)
    asset_valid = np.ones((sample_count, asset_count), dtype=bool)
    target = rng.normal(0.0, 0.01, size=(sample_count, asset_count)).astype(np.float32)
    target_valid = np.ones(target.shape, dtype=bool)
    log_price = np.cumsum(
        rng.normal(0.0, 0.002, size=intraday.shape[:3]),
        axis=-1,
    ).astype(np.float32)
    arrays = MultiResolutionArrays(
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily,
        daily_valid=daily_valid,
        asset_valid=asset_valid,
        supervised_target=target,
        supervised_valid=target_valid,
        timing=timing,
    )
    return arrays, log_price


def _fixed_history(stage: str, epochs: int) -> tuple[dict[str, object], ...]:
    """Stroit polnuyu synthetic istoriyu bez imitatsii early stopping."""
    return tuple(
        {
            "stage": stage,
            "epoch": epoch,
            "train_loss": 1.0 / epoch,
            "batches": 1,
            "valid_labels": 10,
        }
        for epoch in range(1, epochs + 1)
    )


def test_fold_scaler_and_target_iqr_ignore_future_mutation() -> None:
    """Dokazyvaet chto score/OOS values ne vliyayut na train median, IQR i hash."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    arrays, log_price = _synthetic_arrays()
    fold = V7FoldConfig(
        name="synthetic_boundary",
        train_start=date(2020, 12, 9),
        train_end=date(2020, 12, 31),
        score_start=date(2021, 1, 1),
        score_end=date(2021, 1, 31),
    )
    scope = build_fold_training_scope(
        arrays.timing,
        fold,
        config.development.decision_timezone,
        purge_sessions=0,
    )
    original_scaler = fit_fold_robust_scaler(arrays, config.model, scope)
    original_target_iqr = fit_fold_target_iqr(arrays, scope)
    original_hashes = build_v7_training_hashes(arrays, log_price, config.model, scope)

    changed_intraday = arrays.intraday.copy()
    changed_daily = arrays.daily_context.copy()
    changed_target = arrays.supervised_target.copy()
    changed_price = log_price.copy()
    changed_intraday[-1] = 1_000_000.0
    changed_daily[-1] = -1_000_000.0
    changed_target[-1] = 999.0
    changed_price[-1] = 777.0
    changed_arrays = replace(
        arrays,
        intraday=changed_intraday,
        daily_context=changed_daily,
        supervised_target=changed_target,
    )
    changed_scaler = fit_fold_robust_scaler(changed_arrays, config.model, scope)
    changed_target_iqr = fit_fold_target_iqr(changed_arrays, scope)
    changed_hashes = build_v7_training_hashes(
        changed_arrays,
        changed_price,
        config.model,
        scope,
    )
    assert original_scaler.as_dict() == changed_scaler.as_dict()
    assert original_target_iqr == pytest.approx(changed_target_iqr, rel=0.0, abs=0.0)
    assert original_hashes == changed_hashes
    assert int(scope.sample_indices.max()) < len(arrays.intraday) - 1


def test_ssl_labels_require_origin_and_horizon_end_inside_train() -> None:
    """Mutiruet pre-train history i proveriaet zero label za train-boundary."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    arrays, log_price = _synthetic_arrays()
    fold = V7FoldConfig(
        name="synthetic_boundary",
        train_start=date(2020, 12, 9),
        train_end=date(2020, 12, 31),
        score_start=date(2021, 1, 1),
        score_end=date(2021, 1, 31),
    )
    scope = build_fold_training_scope(
        arrays.timing,
        fold,
        config.development.decision_timezone,
        purge_sessions=0,
    )
    index = int(scope.sample_indices[0])
    original = build_strict_fold_ssl_sample(
        log_price[index],
        arrays.intraday_valid[index],
        arrays.timing.bar_times[index],
        arrays.asset_valid[index],
        config.model.ssl_horizons,
        scope,
    )
    mutation_mask = arrays.timing.bar_times[index] < scope.calendar_start_utc
    mutated_price = log_price[index].copy()
    mutated_price[:, mutation_mask] += 10_000.0
    mutated = build_strict_fold_ssl_sample(
        mutated_price,
        arrays.intraday_valid[index],
        arrays.timing.bar_times[index],
        arrays.asset_valid[index],
        config.model.ssl_horizons,
        scope,
    )
    assert mutation_mask.any()
    np.testing.assert_array_equal(original.valid, mutated.valid)
    np.testing.assert_allclose(original.values, mutated.values, rtol=0.0, atol=0.0)
    origin_in_train = arrays.timing.bar_times[index] >= scope.calendar_start_utc
    assert not original.valid[:, ~origin_in_train].any()
    assert np.count_nonzero(original.values[~original.valid]) == 0


def test_pairwise_ranking_formula_and_less_than_two_assets_zero() -> None:
    """Proveryaet softplus, ties, finite-mask i exact zero bez pary."""
    predictions = torch.tensor([[0.02, -0.01, 5.0]], dtype=torch.float64)
    targets = torch.tensor([[0.03, -0.02, float("nan")]], dtype=torch.float64)
    valid = torch.tensor([[True, True, False]])
    temperature = 0.05
    ranking = fold_pairwise_ranking_loss(predictions, targets, valid, temperature)
    expected_ranking = torch.nn.functional.softplus(torch.tensor(-0.6)).item()
    assert ranking.item() == pytest.approx(expected_ranking)
    combined = masked_portfolio_supervised_loss(
        predictions,
        targets,
        valid,
        temperature,
    )
    base = masked_supervised_loss(predictions, targets, valid)
    assert combined.item() == pytest.approx(
        base.item() + V7_RANKING_WEIGHT * expected_ranking
    )
    one_valid = torch.tensor([[True, False, False]])
    zero = fold_pairwise_ranking_loss(predictions, targets, one_valid, temperature)
    assert zero.item() == 0.0

    tied_predictions = torch.tensor([[0.20, 0.10, -0.10]], dtype=torch.float64)
    tied_targets = torch.tensor([[1.0, 1.0, 0.0]], dtype=torch.float64)
    tied_valid = torch.ones_like(tied_targets, dtype=torch.bool)
    tied_loss = fold_pairwise_ranking_loss(
        tied_predictions,
        tied_targets,
        tied_valid,
        train_target_iqr=1.0,
    )
    tied_terms = torch.stack(
        (
            torch.nn.functional.softplus(torch.tensor(0.0, dtype=torch.float64)),
            torch.nn.functional.softplus(torch.tensor(-0.30, dtype=torch.float64)),
            torch.nn.functional.softplus(torch.tensor(-0.20, dtype=torch.float64)),
        )
    )
    assert tied_loss.item() == pytest.approx(tied_terms.mean().item())


def test_deterministic_epoch_order_and_arithmetic_seed_mean() -> None:
    """Proveryaet povtor shuffle po seed/epoch i prostoe usrednenie treh seed."""
    first = DeterministicEpochSampler(20, seed=1729, stage_offset=10_000)
    second = DeterministicEpochSampler(20, seed=1729, stage_offset=10_000)
    first.set_epoch(3)
    second.set_epoch(3)
    assert list(first) == list(second)
    second.set_epoch(4)
    assert list(first) != list(second)
    mean = arithmetic_ensemble_predictions(
        (
            np.array([[1.0, 2.0]]),
            np.array([[2.0, 4.0]]),
            np.array([[3.0, 6.0]]),
        )
    )
    np.testing.assert_array_equal(mean, np.array([[2.0, 4.0]]))


def test_atomic_checkpoint_is_self_contained_and_tamper_evident(tmp_path: Path) -> None:
    """Proveryaet state/scaler/hash roundtrip i otkaz posle podmeny sidecar."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    arrays, log_price = _synthetic_arrays()
    fold = config.development.folds[0]
    scope = build_fold_training_scope(
        arrays.timing,
        fold,
        config.development.decision_timezone,
        config.development.purge_sessions,
    )
    scaler = fit_fold_robust_scaler(arrays, config.model, scope)
    target_iqr = fit_fold_target_iqr(arrays, scope)
    hashes = build_v7_training_hashes(arrays, log_price, config.model, scope)
    set_v7_determinism(config.training.seeds[0])
    model = CausalMultiResolutionFuturesModel(config.model).eval()
    checkpoint = tmp_path / "outer_2021-seed-1729.pt"
    sidecar = save_v7_checkpoint_bundle(
        checkpoint,
        model,
        config,
        fold,
        config.training.seeds[0],
        scope,
        scaler,
        target_iqr,
        hashes,
        _fixed_history("ssl", config.training.ssl_epochs),
        _fixed_history("supervised", config.training.supervised_epochs),
    )
    loaded = load_v7_checkpoint_bundle(checkpoint, expected_hashes=hashes)
    assert loaded.scaler.as_dict() == scaler.as_dict()
    assert loaded.manifest["training_hashes"]["architecture_sha256"] == (
        hashes.architecture_sha256
    )
    assert loaded.manifest["training_hashes"]["feature_schema_sha256"] == (
        hashes.feature_schema_sha256
    )
    assert loaded.manifest["training_hashes"]["timing_sha256"] == hashes.timing_sha256
    for expected, actual in zip(model.parameters(), loaded.model.parameters(), strict=True):
        torch.testing.assert_close(expected, actual, rtol=0.0, atol=0.0)
    assert not list(tmp_path.glob(".*.pt.*"))
    assert loaded.manifest["resume_semantics"] == (
        "completed_seed_checkpoint_only_no_mid_stage_resume"
    )
    assert loaded.manifest["mid_stage_resume_supported"] is False
    assert loaded.manifest["optimizer_state_included"] is False
    assert loaded.manifest["rng_state_included"] is False

    copied_checkpoint = tmp_path / "transport" / "renamed-seed.pt"
    copied_sidecar = write_checkpoint_copy_atomic(
        copied_checkpoint,
        checkpoint_bytes(checkpoint),
    )
    copied = load_v7_checkpoint_bundle(copied_checkpoint, expected_hashes=hashes)
    assert copied.sidecar_path == copied_sidecar
    assert copied.manifest == loaded.manifest

    wrong_iqr_checkpoint = tmp_path / "wrong-iqr" / checkpoint.name
    save_v7_checkpoint_bundle(
        wrong_iqr_checkpoint,
        model,
        config,
        fold,
        config.training.seeds[0],
        scope,
        scaler,
        target_iqr * 2.0,
        hashes,
        _fixed_history("ssl", config.training.ssl_epochs),
        _fixed_history("supervised", config.training.supervised_epochs),
    )
    with pytest.raises(ValueError, match="train target IQR mismatch"):
        run_v7_fold_seed_training(
            arrays,
            log_price,
            config,
            fold.name,
            config.training.seeds[0],
            wrong_iqr_checkpoint.parent,
            resume=True,
        )

    manifest = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    manifest["checkpoint_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(manifest), encoding="utf-8-sig")
    with pytest.raises(ValueError, match="Checkpoint SHA-256 mismatch"):
        load_v7_checkpoint_bundle(checkpoint, expected_hashes=hashes)
