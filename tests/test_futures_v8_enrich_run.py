"""Regressii target-free futures-v8 regime/abstain enrichment."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v8.assembly import V8CausalInputs
from market_lab.futures_v8.config import V8_ASSETS, V8_SEEDS, V8FoldConfig
from market_lab.futures_v8.enrich_run import (
    V8CheckpointBundle,
    V8DiagnosticOutput,
    _atomic_write_parquet,
    _canonical_json_sha256,
    _file_sha256,
    _verify_checkpoint_sidecar,
    build_causal_purged_train_indices,
    build_ensemble_enrichment_frame,
    build_per_seed_enrichment_frame,
    build_target_free_inference_view,
    build_v8_enrichment_code_identity,
    ensemble_diagnostic_outputs,
    fit_target_masked_feature_scaler,
    read_selected_train_target_valid,
    validate_diagnostic_output,
    verify_exact_base_prediction_replay,
)
from market_lab.futures_v8.train_run import (
    V8SeedPrediction,
    build_v8_oos_prediction_frame,
    ensemble_v8_seed_predictions,
)


def _causal_inputs(samples: int = 20) -> V8CausalInputs:
    """Stroit malyi causal calendar bez target container."""
    assets = len(V8_ASSETS)
    bars = 4
    intraday_features = 2
    daily_features = 3
    days = pd.bdate_range("2021-01-04", periods=samples)
    decisions = (
        days.tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=18, minutes=50)
    ).tz_convert("UTC").tz_localize(None)
    bar_offsets = np.asarray([-30, -20, -10, 0], dtype="timedelta64[m]")
    bar_times = decisions.to_numpy(dtype="datetime64[ns]")[:, None] + bar_offsets[None, :]
    source = np.arange(
        samples * assets * bars * intraday_features,
        dtype=np.float32,
    ).reshape(samples, assets, bars, intraday_features)
    daily = np.arange(
        samples * assets * daily_features,
        dtype=np.float32,
    ).reshape(samples, assets, daily_features)
    return V8CausalInputs(
        intraday=source,
        intraday_valid=np.ones((samples, assets, bars), dtype=bool),
        daily_context=daily,
        daily_valid=np.ones_like(daily, dtype=bool),
        asset_valid=np.ones((samples, assets), dtype=bool),
        log_price=np.zeros((samples, assets, bars), dtype=np.float64),
        bar_times=bar_times.astype("datetime64[ns]"),
        sample_trade_dates=days.to_numpy(dtype="datetime64[ns]"),
        decision_times=decisions.to_numpy(dtype="datetime64[ns]"),
        source_path=Path("synthetic.npz"),
        source_sha256="1" * 64,
    )


def _fold() -> V8FoldConfig:
    """Vozvrashchaet fold s exact ten-session purge."""
    return V8FoldConfig(
        name="outer_2021",
        train_start=date(2021, 1, 4),
        train_end=date(2021, 1, 29),
        score_start=date(2021, 2, 1),
        score_end=date(2021, 2, 26),
    )


def _canonical_bytes(payload: object) -> bytes:
    """Serializuet test payload tak zhe odnoznachno, kak production seal."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def test_causal_scope_excludes_purge_plus_horizon_before_target_mask_read() -> None:
    """Dokazyvaet causal prefix purge10+horizon5 i exact cutoff do target API."""
    inputs = _causal_inputs()
    indices, cutoff = build_causal_purged_train_indices(
        inputs,
        _fold(),
        purge_sessions=10,
        horizon_common_sessions=5,
        timezone_name="Europe/Moscow",
    )
    assert np.array_equal(indices, np.arange(5, dtype=np.int64))
    expected = pd.Timestamp("2021-01-18").tz_localize("Europe/Moscow").tz_convert("UTC")
    assert cutoff == expected.tz_localize(None).to_datetime64()
    assert (inputs.bar_times[indices] < cutoff).all()


def test_oos_target_poison_cannot_change_sealed_scaler_bytes(tmp_path: Path) -> None:
    """Meniaet vse OOS mask/timing/value, no train scaler ostaetsia byte-identichen."""
    inputs = _causal_inputs()
    indices, cutoff = build_causal_purged_train_indices(
        inputs,
        _fold(),
        purge_sessions=10,
        horizon_common_sessions=5,
        timezone_name="Europe/Moscow",
    )
    shape = (inputs.sample_count, inputs.asset_count)
    first_valid = np.ones(shape, dtype=bool)
    second_valid = first_valid.copy()
    second_valid[len(indices) :] = False
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    np.savez_compressed(
        first,
        target_valid=first_valid,
        target_raw=np.zeros(shape, dtype=np.float32),
        target_normalized=np.zeros(shape, dtype=np.float32),
        target_availability_times=np.zeros(shape, dtype=np.int64),
    )
    np.savez_compressed(
        second,
        target_valid=second_valid,
        target_raw=np.full(shape, np.float32(9.9e20)),
        target_normalized=np.full(shape, np.float32(-9.9e20)),
        target_availability_times=np.full(shape, np.iinfo(np.int64).max),
    )
    first_selected = read_selected_train_target_valid(first, indices, expected_shape=shape)
    second_selected = read_selected_train_target_valid(second, indices, expected_shape=shape)
    assert np.array_equal(first_selected, second_selected)
    first_scaler = fit_target_masked_feature_scaler(
        inputs,
        indices,
        cutoff,
        first_selected,
        fold_name="outer_2021",
        purge_sessions=10,
        horizon_common_sessions=5,
        original_statistics_sha256="a" * 64,
    )
    second_scaler = fit_target_masked_feature_scaler(
        inputs,
        indices,
        cutoff,
        second_selected,
        fold_name="outer_2021",
        purge_sessions=10,
        horizon_common_sessions=5,
        original_statistics_sha256="a" * 64,
    )
    assert _canonical_bytes(first_scaler.as_dict()) == _canonical_bytes(second_scaler.as_dict())
    assert first_scaler.scaler_statistics_sha256 == second_scaler.scaler_statistics_sha256
    serialized = _canonical_bytes(first_scaler.as_dict())
    assert b"target_raw" not in serialized
    assert b"target_normalized" not in serialized
    assert b"availability" not in serialized


def test_train_mask_changes_scaler_and_no_target_value_argument_exists() -> None:
    """Dokazyvaet exact train mask v scale i otsutstvie supervised value API."""
    inputs = _causal_inputs()
    indices, cutoff = build_causal_purged_train_indices(
        inputs,
        _fold(),
        purge_sessions=10,
        horizon_common_sessions=5,
        timezone_name="Europe/Moscow",
    )
    full = np.ones((len(indices), len(V8_ASSETS)), dtype=bool)
    masked = full.copy()
    masked[-1, -1] = False
    first = fit_target_masked_feature_scaler(
        inputs,
        indices,
        cutoff,
        full,
        fold_name="outer_2021",
        purge_sessions=10,
        horizon_common_sessions=5,
        original_statistics_sha256="b" * 64,
    )
    second = fit_target_masked_feature_scaler(
        inputs,
        indices,
        cutoff,
        masked,
        fold_name="outer_2021",
        purge_sessions=10,
        horizon_common_sessions=5,
        original_statistics_sha256="b" * 64,
    )
    assert first.train_indices_sha256 == second.train_indices_sha256
    assert first.train_target_valid_sha256 != second.train_target_valid_sha256
    assert first.scaler_statistics_sha256 != second.scaler_statistics_sha256
    assert first.intraday_median != second.intraday_median


def _inference_view() -> object:
    """Stroit target-free two-row inference view s odnim masked asset."""
    inputs = _causal_inputs(samples=2)
    inputs.asset_valid[1, -1] = False
    return build_target_free_inference_view(inputs, np.asarray([0, 1], dtype=np.int64))


def _diagnostic(offset: float = 0.0) -> V8DiagnosticOutput:
    """Vozvrashchaet valid calibrated synthetic diagnostic."""
    regimes = np.asarray(
        [
            [0.2 + offset, 0.3, 0.5 - offset],
            [0.1 + offset, 0.6 - offset, 0.3],
        ],
        dtype=np.float32,
    )
    factor = np.asarray([0.25 + offset, 0.5], dtype=np.float32)
    residual = np.full((2, len(V8_ASSETS)), 0.4 + offset, dtype=np.float32)
    return V8DiagnosticOutput(regimes, factor, residual)


def _base_template(inference: object) -> pd.DataFrame:
    """Stroit exact timing/model long template bez prediction values."""
    decisions = pd.DatetimeIndex(inference.decision_times).tz_localize("UTC")
    local = decisions.tz_convert("Europe/Moscow").normalize()
    assets = len(V8_ASSETS)
    return pd.DataFrame(
        {
            "decision_date": np.repeat(
                inference.sample_trade_dates.astype("datetime64[D]"),
                assets,
            ),
            "decision_at": np.repeat(decisions.to_numpy(), assets),
            "capacity_window_open_at": np.repeat(
                (local + pd.Timedelta(hours=19)).tz_convert("UTC").to_numpy(),
                assets,
            ),
            "capacity_window_close_at": np.repeat(
                (local + pd.Timedelta(hours=19, minutes=10)).tz_convert("UTC").to_numpy(),
                assets,
            ),
            "execution_window_open_at": np.repeat(
                (local + pd.Timedelta(hours=19, minutes=20)).tz_convert("UTC").to_numpy(),
                assets,
            ),
            "execution_window_close_at": np.repeat(
                (local + pd.Timedelta(hours=19, minutes=30)).tz_convert("UTC").to_numpy(),
                assets,
            ),
            "asset": np.tile(np.asarray(V8_ASSETS, dtype=object), len(decisions)),
            "asset_valid": inference.asset_valid.reshape(-1),
            "model_id": "sealed-model",
        }
    )


def _checkpoint(seed: int = V8_SEEDS[0]) -> V8CheckpointBundle:
    """Stroit synthetic identity dlia pure frame test."""
    return V8CheckpointBundle(
        fold_name="outer_2021",
        seed=seed,
        checkpoint_path=Path("unused.pt"),
        checkpoint_sha256=f"{seed:064x}",
        sidecar_path=Path("unused.json"),
        sidecar_sha256="c" * 64,
        original_statistics_sha256="d" * 64,
    )


def _seed_prediction(offset: float = 0.0) -> V8SeedPrediction:
    """Stroit complete synthetic base fields s odnoi masked asset cell."""
    samples = 2
    assets = len(V8_ASSETS)
    residual_location = np.arange(samples * assets, dtype=np.float32).reshape(samples, assets)
    return V8SeedPrediction(
        factor_location=np.asarray([0.1 + offset, -0.2 + offset], dtype=np.float32),
        factor_scale=np.asarray([0.5, 0.75], dtype=np.float32),
        factor_score=np.asarray([0.2 + offset, -0.3 + offset], dtype=np.float32),
        residual_location=residual_location + np.float32(offset),
        residual_scale=np.full((samples, assets), 0.8 + offset, dtype=np.float32),
        residual_decision_score=np.full(
            (samples, assets),
            0.15 + offset,
            dtype=np.float32,
        ),
        direction_logit=np.full((samples, assets), -0.1 + offset, dtype=np.float32),
    )


def test_exact_base_replay_gate_checks_all_seven_fields_and_mask() -> None:
    """Blokiruet enrichment pri lyubom drift base prediction ili asset mask."""
    inference = _inference_view()
    seeds = tuple(_seed_prediction(offset) for offset in (0.0, 0.01, 0.02))
    ensemble = ensemble_v8_seed_predictions(seeds, inference)
    base = build_v8_oos_prediction_frame(inference, ensemble, "sealed-model")
    audit = verify_exact_base_prediction_replay(
        base,
        inference,
        seeds,
        fold_name="outer_2021",
        model_id="sealed-model",
    )
    assert audit["exact"] is True
    assert audit["rows"] == len(base)
    assert audit["invalid_rows"] == 1
    assert audit["numeric_columns"] == [
        "factor_location",
        "factor_scale",
        "factor_score",
        "residual_location",
        "residual_scale",
        "residual_decision_score",
        "direction_logit",
    ]
    assert set(audit["max_abs_diff"].values()) == {0.0}

    numeric_poison = base.copy()
    numeric_poison.loc[0, "factor_location"] += 1e-7
    with pytest.raises(ValueError, match="factor_location"):
        verify_exact_base_prediction_replay(
            numeric_poison,
            inference,
            seeds,
            fold_name="outer_2021",
            model_id="sealed-model",
        )

    mask_poison = base.copy()
    mask_poison.loc[0, "asset_valid"] = False
    with pytest.raises(ValueError, match="asset_valid"):
        verify_exact_base_prediction_replay(
            mask_poison,
            inference,
            seeds,
            fold_name="outer_2021",
            model_id="sealed-model",
        )


def test_probabilities_sum_and_fixed_three_seed_mean() -> None:
    """Trebuet simplex, granicy abstention i arithmetic fixed-seed mean."""
    inference = _inference_view()
    outputs = (_diagnostic(0.0), _diagnostic(0.01), _diagnostic(0.02))
    for output in outputs:
        validate_diagnostic_output(output, inference)
    ensemble = ensemble_diagnostic_outputs(outputs, inference)
    assert np.allclose(ensemble.regime_probabilities.sum(axis=1), 1.0)
    assert np.allclose(
        ensemble.factor_abstain_probability,
        np.mean([item.factor_abstain_probability for item in outputs], axis=0),
    )
    with pytest.raises(ValueError, match="exact three seeds"):
        ensemble_diagnostic_outputs(outputs[:2], inference)
    poisoned = V8DiagnosticOutput(
        np.asarray([[0.2, 0.2, 0.2], [0.1, 0.6, 0.3]], dtype=np.float32),
        outputs[0].factor_abstain_probability,
        outputs[0].residual_abstain_probability,
    )
    with pytest.raises(ValueError, match="calibration"):
        validate_diagnostic_output(poisoned, inference)


def test_frames_keep_exact_calendar_model_mask_and_are_byte_deterministic(
    tmp_path: Path,
) -> None:
    """Dokazyvaet immutable base keys i deterministic parquet bez target kolonok."""
    inference = _inference_view()
    template = _base_template(inference)
    output = _diagnostic()
    checkpoint = _checkpoint()
    first = build_per_seed_enrichment_frame(template, inference, output, checkpoint)
    second = build_per_seed_enrichment_frame(template, inference, output, checkpoint)
    assert first.equals(second)
    assert first["model_id"].eq("sealed-model").all()
    assert np.array_equal(first["asset_valid"].to_numpy(bool), inference.asset_valid.reshape(-1))
    assert first.loc[~first["asset_valid"], "residual_abstain_probability"].isna().all()
    assert not any("target" in column or "pnl" in column for column in first.columns)
    first_path = tmp_path / "first.parquet"
    second_path = tmp_path / "second.parquet"
    _atomic_write_parquet(first_path, first)
    _atomic_write_parquet(second_path, second)
    assert first_path.read_bytes() == second_path.read_bytes()
    ensemble = ensemble_diagnostic_outputs((output, output, output), inference)
    ensemble_frame = build_ensemble_enrichment_frame(
        template,
        inference,
        ensemble,
        "outer_2021",
        ["1" * 64, "2" * 64, "3" * 64],
    )
    assert ensemble_frame["seed_count"].eq(3).all()
    assert ensemble_frame["seed_set_sha256"].nunique() == 1


def test_checkpoint_sidecar_hash_drift_is_rejected(tmp_path: Path) -> None:
    """Otkazyvaet podmenennyi checkpoint do model deserialize/CUDA."""
    root = tmp_path.resolve()
    checkpoint = root / "runs" / "base" / "checkpoints" / "outer_2021" / "seed-1729.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"sealed-checkpoint")
    identity = {"code_identity_sha256": "e" * 64}
    core = {
        "identity": identity,
        "completed": True,
        "fold_name": "outer_2021",
        "seed": 1729,
        "statistics_sha256": "f" * 64,
    }
    outer = {
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": _file_sha256(checkpoint),
        "manifest": core,
        "manifest_sha256": _canonical_json_sha256(core),
    }
    sidecar = checkpoint.with_suffix(".pt.manifest.json")
    sidecar.write_text(json.dumps(outer), encoding="utf-8")
    record = {
        "checkpoint_path": checkpoint.relative_to(root).as_posix(),
        "checkpoint_sha256": _file_sha256(checkpoint),
        "checkpoint_bytes": checkpoint.stat().st_size,
        "sidecar_path": sidecar.relative_to(root).as_posix(),
        "sidecar_sha256": _file_sha256(sidecar),
        "sidecar_bytes": sidecar.stat().st_size,
        "fold_name": "outer_2021",
        "seed": 1729,
    }
    verified = _verify_checkpoint_sidecar(root, record, identity)
    assert verified.checkpoint_sha256 == record["checkpoint_sha256"]
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="byte seal"):
        _verify_checkpoint_sidecar(root, record, identity)


def test_enrichment_code_identity_includes_module_and_detects_copy_drift(
    tmp_path: Path,
) -> None:
    """Dokazyvaet, chto novyi inference module vhodit v runtime code seal."""
    project = Path(__file__).resolve().parents[1]
    first = build_v8_enrichment_code_identity(project)
    assert any(item["path"].endswith("futures_v8/enrich_run.py") for item in first["files"])
    copied = tmp_path / "project"
    shutil.copytree(project / "src", copied / "src")
    module = copied / "src" / "market_lab" / "futures_v8" / "enrich_run.py"
    module.write_bytes(module.read_bytes() + b"\n")
    second = build_v8_enrichment_code_identity(copied)
    assert first["code_identity_sha256"] != second["code_identity_sha256"]


def test_enrichment_text_has_required_bom() -> None:
    """Fiksiruet UTF-8 BOM dlia novogo production/test text."""
    production = Path(__file__).resolve().parents[1] / "src/market_lab/futures_v8/enrich_run.py"
    assert production.read_bytes().startswith(b"\xef\xbb\xbf")
    assert Path(__file__).read_bytes().startswith(b"\xef\xbb\xbf")
