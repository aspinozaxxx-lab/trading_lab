"""Mock-testy servernogo 5x3 training runner futures-v7 bez CUDA."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v7.assembly import (
    LoadedV7TrainingArrays,
    load_v7_training_arrays,
)
from market_lab.futures_v7.config import V7_ASSETS, V7_SEEDS, V7FoldConfig
from market_lab.futures_v7.contracts import DecisionTimingBatch
from market_lab.futures_v7.dataset import MultiResolutionArrays
from market_lab.futures_v7.train_run import (
    V7_CODE_IDENTITY_RELATIVE_PATHS,
    V7TrainingApi,
    build_v7_oos_prediction_frame,
    build_v7_oos_sample_indices,
    load_verified_v7_training_inputs,
    run_v7_training,
    validate_v7_fold_supervised_scope,
    verify_v7_assembly_manifest,
)
from market_lab.io_utils import write_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren s kanonicheskim config.
CONFIG_SOURCE = (  # Tochnyi byte-sealed protocol dlya vremennogo project-root.
    PROJECT_ROOT / "configs" / "futures_v7_development_protocol.yaml"
)
ARCHITECTURE_SHA = "a" * 64  # Synthetic architecture identity bez importa torch.


def _sha256(path: Path) -> str:
    """Hashiruet synthetic artifact dlya testovogo manifesta."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(payload: Any) -> str:
    """Povtoryaet kanonicheskii JSON hash checkpoint sidecar."""
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _project_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Kopiruet config bez izmeneniya baitov v izolirovannyi project-root."""
    root = tmp_path / "project"
    config = root / "configs" / CONFIG_SOURCE.name
    config.parent.mkdir(parents=True)
    shutil.copyfile(CONFIG_SOURCE, config)
    for relative_name in V7_CODE_IDENTITY_RELATIVE_PATHS:
        source = PROJECT_ROOT.joinpath(*Path(relative_name).parts)
        destination = root.joinpath(*Path(relative_name).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return root, config


def _synthetic_loaded(
    *,
    mutate_future_targets: bool = False,
) -> LoadedV7TrainingArrays:
    """Stroit po odnomu causal sample v kazhdom score-godu 2021--2025."""
    decision_times = np.asarray(
        [np.datetime64(f"{year}-06-15T15:50:00", "ns") for year in range(2020, 2026)]
    )
    offsets = np.arange(512, 0, -1) * np.timedelta64(10, "m")
    bar_times = np.stack([decision - offsets for decision in decision_times])
    entry_times = decision_times + np.timedelta64(10, "m")
    exit_times = decision_times + np.timedelta64(20, "m")
    timing = DecisionTimingBatch(
        bar_times=bar_times,
        decision_times=decision_times,
        entry_open_times=entry_times,
        exit_open_times=exit_times,
    )
    sample_count = len(decision_times)
    asset_count = len(V7_ASSETS)
    intraday = np.zeros((sample_count, asset_count, 512, 12), dtype=np.float32)
    daily = np.zeros((sample_count, asset_count, 16), dtype=np.float32)
    asset_valid = np.ones((sample_count, asset_count), dtype=bool)
    asset_valid[3, 1] = False
    supervised_target = np.zeros((sample_count, asset_count), dtype=np.float32)
    supervised_valid = np.ones_like(supervised_target, dtype=bool)
    if mutate_future_targets:
        supervised_target[-1] = np.nan
        supervised_valid[-1] = True
    arrays = MultiResolutionArrays(
        intraday=intraday,
        intraday_valid=np.ones(intraday.shape[:3], dtype=bool),
        daily_context=daily,
        daily_valid=np.ones(daily.shape, dtype=bool),
        asset_valid=asset_valid,
        supervised_target=supervised_target,
        supervised_valid=supervised_valid,
        timing=timing,
    )
    asset_entry = np.repeat(entry_times[:, None], asset_count, axis=1)
    asset_exit = np.repeat(exit_times[:, None], asset_count, axis=1)
    if mutate_future_targets:
        asset_entry[-1] = np.datetime64("NaT")
        asset_exit[-1] = np.datetime64("2026-02-01T10:00:00", "ns")
    return LoadedV7TrainingArrays(
        arrays=arrays,
        log_price=np.zeros(intraday.shape[:3], dtype=np.float64),
        asset_entry_open_times=asset_entry,
        asset_exit_open_times=asset_exit,
        sample_trade_dates=decision_times.astype("datetime64[D]"),
    )


def _seal_assembly_payload(payload: dict[str, Any]) -> None:
    """Obnovlyaet bundle i self-payload SHA posle synthetic mutacii manifesta."""
    payload["bundle_sha256"] = hashlib.sha256(
        (
            f"{payload['arrays']['sha256']}:"
            f"{payload['execution_market_overlay']['sha256']}"
        ).encode("ascii")
    ).hexdigest()
    payload.pop("manifest_payload_sha256", None)
    payload["manifest_payload_sha256"] = _canonical_sha(payload)


def _assembly_fixture(
    root: Path,
    loaded: LoadedV7TrainingArrays,
) -> Path:
    """Pishet minimal'nyi hash-linked assembly manifest i dva artifacta."""
    output = root / "data" / "processed" / "futures_v7"
    output.mkdir(parents=True, exist_ok=True)
    arrays_path = output / "assembly_mock.npz"
    overlay_path = output / "execution_mock.parquet"
    arrays_path.write_bytes(b"sealed synthetic arrays")
    overlay_path.write_bytes(b"sealed synthetic overlay")
    arrays = loaded.arrays
    manifest = {
        "schema_version": 2,
        "research_status": "development_only_no_pnl_no_training",
        "protected_from": "2026-01-01",
        "arrays": {
            "path": arrays_path.relative_to(root / "data").as_posix(),
            "bytes": arrays_path.stat().st_size,
            "sha256": _sha256(arrays_path),
            "sample_count": len(arrays.intraday),
            "intraday_shape": list(arrays.intraday.shape),
            "daily_context_shape": list(arrays.daily_context.shape),
            "log_price_shape": list(loaded.log_price.shape),
            "asset_execution_time_shape": list(loaded.asset_entry_open_times.shape),
        },
        "execution_market_overlay": {
            "path": overlay_path.relative_to(root / "data").as_posix(),
            "bytes": overlay_path.stat().st_size,
            "sha256": _sha256(overlay_path),
        },
        "audit": {
            "assets": list(V7_ASSETS),
            "bar_feature_names": [
                "log_return_1",
                "log_return_3",
                "log_return_6",
                "range_log",
                "body_log",
                "close_location",
                "log1p_volume",
                "relative_volume_36",
                "realized_volatility_6",
                "realized_volatility_36",
                "session_phase_sin",
                "session_phase_cos",
            ],
            "daily_feature_names": [
                "daily_return_1",
                "daily_return_5",
                "daily_return_20",
                "daily_volatility_20",
                "roll_yield",
                "days_to_expiry_scaled",
                "open_interest_change_1",
                "open_interest_change_5",
                "physical_net_share_lag_1",
                "legal_net_share_lag_1",
                "cbr_key_rate_level",
                "cbr_key_rate_change",
                "cbr_ruonia_spread",
                "cbr_usdrub_return_1",
                "cftc_primary_score",
                "cftc_cross_asset_score",
            ],
            "sequence_bars": 512,
            "ssl_horizons": [1, 6, 24, 72],
            "sample_count": len(arrays.intraday),
        },
        "source_artifacts": [],
    }
    _seal_assembly_payload(manifest)
    manifest_path = output / "manifest_mock.json"
    write_json(manifest_path, manifest)
    return manifest_path


def _write_loaded_npz(path: Path, loaded: LoadedV7TrainingArrays) -> None:
    """Serializuet minimal'nyi real NPZ contract dlya loader regression."""
    arrays = loaded.arrays
    np.savez(
        path,
        intraday=arrays.intraday,
        intraday_valid=arrays.intraday_valid,
        daily_context=arrays.daily_context,
        daily_valid=arrays.daily_valid,
        asset_valid=arrays.asset_valid,
        supervised_target=arrays.supervised_target,
        supervised_valid=arrays.supervised_valid,
        log_price=loaded.log_price,
        bar_times=arrays.timing.bar_times.astype(np.int64),
        decision_times=arrays.timing.decision_times.astype(np.int64),
        entry_open_times=arrays.timing.entry_open_times.astype(np.int64),
        exit_open_times=arrays.timing.exit_open_times.astype(np.int64),
        sample_trade_dates=loaded.sample_trade_dates.astype("datetime64[ns]").astype(
            np.int64
        ),
        asset_entry_open_times=loaded.asset_entry_open_times.astype(np.int64),
        asset_exit_open_times=loaded.asset_exit_open_times.astype(np.int64),
    )


def _write_fake_checkpoint(
    checkpoint_directory: Path,
    fold_name: str,
    seed: int,
) -> SimpleNamespace:
    """Imitiruet polnyi checkpoint/sidecar finalized training API."""
    checkpoint_directory.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_directory / f"{fold_name}-seed-{seed}.pt"
    checkpoint.write_bytes(f"{fold_name}:{seed}".encode("ascii"))
    core = {
        "format": "market-lab-futures-v7-seed-checkpoint-v2",
        "fold": {"name": fold_name},
        "seed": seed,
        "resume_semantics": "completed_seed_checkpoint_only_no_mid_stage_resume",
        "training_hashes": {
            "architecture_sha256": ARCHITECTURE_SHA,
            "feature_schema_sha256": "b" * 64,
            "timing_sha256": "c" * 64,
            "training_data_sha256": "d" * 64,
        },
    }
    sidecar = checkpoint.with_suffix(checkpoint.suffix + ".manifest.json")
    write_json(
        sidecar,
        {
            "format": "market-lab-futures-v7-seed-manifest-v1",
            "checkpoint_file": checkpoint.name,
            "checkpoint_sha256": _sha256(checkpoint),
            "manifest_sha256": _canonical_sha(core),
            "manifest": core,
        },
    )
    return SimpleNamespace(
        seed=seed,
        model=SimpleNamespace(seed=seed),
        scaler=SimpleNamespace(seed=seed),
        checkpoint_path=checkpoint,
        manifest_path=sidecar,
        resumed=seed == V7_SEEDS[0],
    )


def _fake_training_api(call_log: dict[str, list[Any]]) -> V7TrainingApi:
    """Vozvrashchaet bystryi API, schitayushchii tol'ko synthetic scores."""

    def train_fold_ensemble(
        arrays: MultiResolutionArrays,
        log_price: np.ndarray,
        config: Any,
        fold_name: str,
        checkpoint_directory: Path,
        *,
        resume: bool,
    ) -> tuple[SimpleNamespace, ...]:
        """Sozdaet tri proveriaemyh outcome i zapominaet resume flag."""
        del arrays, log_price
        call_log["train"].append((fold_name, resume))
        return tuple(
            _write_fake_checkpoint(checkpoint_directory, fold_name, seed)
            for seed in config.training.seeds
        )

    def predict_model(
        model: Any,
        arrays: MultiResolutionArrays,
        scaler: Any,
        indices: np.ndarray,
        device: Any,
    ) -> np.ndarray:
        """Stroit score iz seed/index bez chteniya supervised target/mask."""
        del scaler, device
        call_log["predict"].append((model.seed, tuple(indices.tolist())))
        base = np.asarray(indices, dtype=np.float64)[:, None] * 0.01
        asset_offset = np.arange(arrays.asset_valid.shape[1], dtype=np.float64)[None, :]
        return base + asset_offset + model.seed / 1_000_000.0

    def ensemble_predictions(values: Any) -> np.ndarray:
        """Usrednyaet rovno tri synthetic seed prediction arifmeticheski."""
        assert len(values) == 3
        return np.mean(np.stack(values, axis=0), axis=0)

    def build_training_scope(
        timing: DecisionTimingBatch,
        fold: V7FoldConfig,
        timezone_name: str,
        purge_sessions: int,
    ) -> SimpleNamespace:
        """Stroit target-free synthetic expanding scope po decision godam."""
        del timezone_name, purge_sessions
        cutoff = np.datetime64(fold.score_start, "D")
        decisions = np.asarray(timing.decision_times).astype("datetime64[D]")
        indices = np.flatnonzero(decisions < cutoff).astype(np.int64)
        return SimpleNamespace(
            sample_indices=indices,
            effective_end_exclusive_utc=np.datetime64(fold.score_start, "ns"),
        )

    return V7TrainingApi(
        train_fold_ensemble=train_fold_ensemble,
        predict_model=predict_model,
        ensemble_predictions=ensemble_predictions,
        architecture_sha256=lambda config: ARCHITECTURE_SHA,
        build_training_scope=build_training_scope,
        device="mock-cuda:0",
        runtime_identity={
            "gpu_name": "Mock NVIDIA RTX 5090",
            "native_bfloat16": True,
        },
        reset_peak_vram=lambda: call_log["reset"].append(True),
        peak_vram=lambda: {
            "peak_allocated_bytes": 123,
            "peak_reserved_bytes": 456,
        },
        release_fold=lambda: call_log["release"].append(True),
    )


def test_manifest_and_config_are_verified_before_array_loader(tmp_path: Path) -> None:
    """Dokazyvaet byte/hash fail-closed do pervogo vyzova NPZ loader."""
    root, config = _project_fixture(tmp_path)
    loaded = _synthetic_loaded()
    manifest = _assembly_fixture(root, loaded)
    loader_calls: list[Path] = []

    def loader(path: Path) -> LoadedV7TrainingArrays:
        """Zapominaet loader call tol'ko posle uspeshnyh seal proverok."""
        loader_calls.append(path)
        return loaded

    verified = load_verified_v7_training_inputs(
        root,
        config,
        manifest,
        array_loader=loader,
    )
    assert loader_calls == [verified.assembly.arrays_path]

    loader_calls.clear()
    verified.assembly.arrays_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="(bytes|SHA-256) mismatch"):
        load_verified_v7_training_inputs(
            root,
            config,
            manifest,
            array_loader=loader,
        )
    assert loader_calls == []

    loader_calls.clear()
    shutil.copyfile(CONFIG_SOURCE, config)
    config.write_bytes(config.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="config seal mismatch"):
        load_verified_v7_training_inputs(
            root,
            config,
            manifest,
            array_loader=loader,
        )
    assert loader_calls == []


def test_runner_loader_mode_does_not_branch_on_global_target_timing(
    tmp_path: Path,
) -> None:
    """Sohranyaet strict default loader, no razreshaet target-free runner admission."""
    corrupted = _synthetic_loaded(mutate_future_targets=True)
    path = tmp_path / "corrupted-oos-target.npz"
    _write_loaded_npz(path, corrupted)
    with pytest.raises(ValueError, match="valid target"):
        load_v7_training_arrays(path)
    admitted = load_v7_training_arrays(path, validate_supervised_timing=False)
    assert np.isnan(admitted.arrays.supervised_target[-1]).all()
    assert np.isnat(admitted.asset_entry_open_times[-1]).all()


def test_manifest_rejects_path_escape_and_duplicate_source(tmp_path: Path) -> None:
    """Zapreshchaet traversal i dva source-record dlya odnogo faila."""
    root, _ = _project_fixture(tmp_path)
    loaded = _synthetic_loaded()
    manifest = _assembly_fixture(root, loaded)
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    payload["arrays"]["path"] = "../outside.npz"
    _seal_assembly_payload(payload)
    write_json(manifest, payload)
    with pytest.raises(ValueError, match="data-root"):
        verify_v7_assembly_manifest(root, manifest)

    manifest = _assembly_fixture(root, loaded)
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    source = root / "data" / "source.bin"
    source.write_bytes(b"source")
    record = {
        "kind": "synthetic",
        "path": source.relative_to(root / "data").as_posix(),
        "bytes": source.stat().st_size,
        "sha256": _sha256(source),
    }
    payload["source_artifacts"] = [record, dict(record)]
    _seal_assembly_payload(payload)
    write_json(manifest, payload)
    with pytest.raises(ValueError, match="duplicate path"):
        verify_v7_assembly_manifest(root, manifest)


def test_oos_boundaries_and_duplicate_calendar_are_target_free() -> None:
    """Proveryaet inclusive fold-granicy bez peredachi target ili ego maski."""
    fold = V7FoldConfig(
        name="boundary",
        train_start="2018-01-01",
        train_end="2020-12-31",
        score_start="2021-01-01",
        score_end="2021-12-31",
    )
    decisions = np.asarray(
        [
            np.datetime64("2020-12-31T15:50:00", "ns"),
            np.datetime64("2021-01-01T15:50:00", "ns"),
            np.datetime64("2021-12-31T15:50:00", "ns"),
            np.datetime64("2022-01-01T15:50:00", "ns"),
        ]
    )
    dates = decisions.astype("datetime64[D]")
    indices = build_v7_oos_sample_indices(dates, decisions, fold, "Europe/Moscow")
    np.testing.assert_array_equal(indices, np.array([1, 2]))

    duplicate_dates = dates.copy()
    duplicate_dates[2] = duplicate_dates[1]
    duplicate_decisions = decisions.copy()
    duplicate_decisions[2] = duplicate_decisions[1]
    with pytest.raises(ValueError, match="duplicate"):
        build_v7_oos_sample_indices(
            duplicate_dates,
            duplicate_decisions,
            fold,
            "Europe/Moscow",
        )


def test_prediction_mask_uses_only_causal_asset_valid() -> None:
    """Dokazyvaet chto proizvol'naya future-target mask ne vliyaet na OOS rows."""
    loaded = _synthetic_loaded()
    mutated = _synthetic_loaded(mutate_future_targets=True)
    indices = np.arange(len(loaded.sample_trade_dates), dtype=np.int64)
    scores = np.arange(len(indices) * len(V7_ASSETS), dtype=float).reshape(
        len(indices), len(V7_ASSETS)
    )
    first = build_v7_oos_prediction_frame(
        loaded.sample_trade_dates,
        loaded.arrays.timing.decision_times,
        loaded.arrays.asset_valid,
        indices,
        scores,
        "fixed-model",
    )
    second = build_v7_oos_prediction_frame(
        mutated.sample_trade_dates,
        mutated.arrays.timing.decision_times,
        mutated.arrays.asset_valid,
        indices,
        scores,
        "fixed-model",
    )
    pd.testing.assert_frame_equal(first, second)
    assert first["candidate_score"].isna().sum() == 1
    missing_mix = (
        (first["decision_date"] == np.datetime64("2023-06-15"))
        & (first["asset"] == "MIX")
    )
    assert pd.isna(first.loc[missing_mix, "candidate_score"]).all()


def test_supervised_corruption_is_checked_only_inside_current_train_scope() -> None:
    """Propuskaet budushchuyu porchu i otkazyvaet kogda scope nachinaet ee vklyuchat'."""
    loaded = _synthetic_loaded()
    before_2021 = SimpleNamespace(
        sample_indices=np.array([0], dtype=np.int64),
        effective_end_exclusive_utc=np.datetime64("2021-01-01T00:00:00", "ns"),
    )
    through_2021 = SimpleNamespace(
        sample_indices=np.array([0, 1], dtype=np.int64),
        effective_end_exclusive_utc=np.datetime64("2022-01-01T00:00:00", "ns"),
    )
    broken_target = loaded.arrays.supervised_target.copy()
    broken_target[1, 0] = np.nan
    target_corrupted = replace(
        loaded,
        arrays=replace(loaded.arrays, supervised_target=broken_target),
    )
    validate_v7_fold_supervised_scope(target_corrupted, before_2021)
    with pytest.raises(ValueError, match="ne konechen"):
        validate_v7_fold_supervised_scope(target_corrupted, through_2021)

    broken_entry = loaded.asset_entry_open_times.copy()
    broken_entry[1, 0] = np.datetime64("NaT")
    timing_corrupted = replace(loaded, asset_entry_open_times=broken_entry)
    validate_v7_fold_supervised_scope(timing_corrupted, before_2021)
    with pytest.raises(ValueError, match="per-asset timing"):
        validate_v7_fold_supervised_scope(timing_corrupted, through_2021)


def test_full_mock_runner_is_exactly_five_by_three_and_target_independent(
    tmp_path: Path,
) -> None:
    """Proveryaet 15 checkpointov, resume, artifacts i invariant k future labels."""
    root, config = _project_fixture(tmp_path)
    loaded = _synthetic_loaded()
    manifest = _assembly_fixture(root, loaded)
    manifest_sha = _sha256(manifest)

    first_log: dict[str, list[Any]] = {
        "train": [],
        "predict": [],
        "reset": [],
        "release": [],
    }
    first = run_v7_training(
        root,
        config,
        manifest,
        root / "runs" / "first",
        expected_assembly_manifest_sha256=manifest_sha,
        training_api=_fake_training_api(first_log),
        array_loader=lambda path: loaded,
    )
    assert len(first_log["train"]) == 5
    assert len(first_log["predict"]) == 15
    assert len(first_log["reset"]) == 1
    assert len(first_log["release"]) == 5
    assert all(resume for _, resume in first_log["train"])

    predictions = pd.read_parquet(first.predictions_path)
    assert list(predictions.columns) == list(
        (
            "decision_date",
            "decision_at",
            "asset",
            "candidate_score",
            "model_id",
        )
    )
    assert len(predictions) == 5 * len(V7_ASSETS)
    assert not predictions.duplicated(["decision_at", "asset", "model_id"]).any()
    assert predictions["candidate_score"].isna().sum() == 1
    identities = json.loads(
        first.checkpoint_identities_path.read_text(encoding="utf-8-sig")
    )
    assert len(identities["checkpoints"]) == 15
    assert len(
        {
            (row["fold_name"], row["seed"]) for row in identities["checkpoints"]
        }
    ) == 15
    summary = json.loads(first.training_summary_path.read_text(encoding="utf-8-sig"))
    assert summary["completed_seed_checkpoint_count"] == 15
    assert summary["resumed_seed_checkpoint_count"] == 5
    assert summary["runtime"]["gpu_name"] == "Mock NVIDIA RTX 5090"
    assert summary["runtime"]["peak_reserved_bytes"] == 456
    assert summary["pnl_or_trading_metrics_computed"] is False
    run_identity = json.loads(first.run_identity_path.read_text(encoding="utf-8-sig"))
    assert run_identity["identity"]["code_identity_sha256"] == (
        summary["identity"]["code_identity_sha256"]
    )
    assert len(run_identity["identity"]["code_identity"]["files"]) == len(
        V7_CODE_IDENTITY_RELATIVE_PATHS
    )

    mutated = _synthetic_loaded(mutate_future_targets=True)
    second_log: dict[str, list[Any]] = {
        "train": [],
        "predict": [],
        "reset": [],
        "release": [],
    }
    second = run_v7_training(
        root,
        config,
        manifest,
        root / "runs" / "mutated-targets",
        expected_assembly_manifest_sha256=manifest_sha,
        training_api=_fake_training_api(second_log),
        array_loader=lambda path: mutated,
    )
    pd.testing.assert_frame_equal(
        predictions,
        pd.read_parquet(second.predictions_path),
    )


def test_resume_rejects_code_drift_before_any_seed_call(tmp_path: Path) -> None:
    """Menyaet sealed model.py i trebuet otkaz po run_identity do trainer call."""
    root, config = _project_fixture(tmp_path)
    loaded = _synthetic_loaded()
    manifest = _assembly_fixture(root, loaded)
    output = root / "runs" / "code-seal"
    first_log: dict[str, list[Any]] = {
        "train": [],
        "predict": [],
        "reset": [],
        "release": [],
    }
    run_v7_training(
        root,
        config,
        manifest,
        output,
        training_api=_fake_training_api(first_log),
        array_loader=lambda path: loaded,
    )
    model_path = root / "src" / "market_lab" / "futures_v7" / "model.py"
    model_path.write_bytes(model_path.read_bytes() + b"\n# synthetic code drift\n")
    second_log: dict[str, list[Any]] = {
        "train": [],
        "predict": [],
        "reset": [],
        "release": [],
    }
    with pytest.raises(ValueError, match="identity mismatch"):
        run_v7_training(
            root,
            config,
            manifest,
            output,
            training_api=_fake_training_api(second_log),
            array_loader=lambda path: loaded,
        )
    assert second_log["train"] == []
    assert second_log["predict"] == []
    assert second_log["reset"] == []


def test_resume_rejects_orphan_checkpoint_without_identity(tmp_path: Path) -> None:
    """Ne dopuskaet checkpoint posle crash/delete run-identity markera."""
    root, config = _project_fixture(tmp_path)
    loaded = _synthetic_loaded()
    manifest = _assembly_fixture(root, loaded)
    output = root / "runs" / "orphan"
    checkpoint_directory = output / "checkpoints"
    checkpoint_directory.mkdir(parents=True)
    (checkpoint_directory / "outer_2021-seed-1729.pt").write_bytes(b"orphan")
    call_log: dict[str, list[Any]] = {
        "train": [],
        "predict": [],
        "reset": [],
        "release": [],
    }
    with pytest.raises(ValueError, match="bez pre-run identity"):
        run_v7_training(
            root,
            config,
            manifest,
            output,
            training_api=_fake_training_api(call_log),
            array_loader=lambda path: loaded,
        )
    assert call_log["train"] == []


def test_loaded_array_guard_rejects_protected_2026(tmp_path: Path) -> None:
    """Blokiruet sample iz 2026 dazhe pri formal'no korrektnom manifest hash."""
    root, config = _project_fixture(tmp_path)
    loaded = _synthetic_loaded()
    decision_times = loaded.arrays.timing.decision_times.copy()
    decision_times[-1] = np.datetime64("2026-01-02T15:50:00", "ns")
    bar_offsets = np.arange(512, 0, -1) * np.timedelta64(10, "m")
    bar_times = loaded.arrays.timing.bar_times.copy()
    bar_times[-1] = decision_times[-1] - bar_offsets
    entry = loaded.arrays.timing.entry_open_times.copy()
    exit_ = loaded.arrays.timing.exit_open_times.copy()
    entry[-1] = decision_times[-1] + np.timedelta64(10, "m")
    exit_[-1] = decision_times[-1] + np.timedelta64(20, "m")
    timing = DecisionTimingBatch(bar_times, decision_times, entry, exit_)
    protected = replace(
        loaded,
        arrays=replace(loaded.arrays, timing=timing),
        sample_trade_dates=decision_times.astype("datetime64[D]"),
        asset_entry_open_times=np.repeat(entry[:, None], len(V7_ASSETS), axis=1),
        asset_exit_open_times=np.repeat(exit_[:, None], len(V7_ASSETS), axis=1),
    )
    manifest = _assembly_fixture(root, protected)
    with pytest.raises(ValueError, match="Protected 2026"):
        load_verified_v7_training_inputs(
            root,
            config,
            manifest,
            array_loader=lambda path: protected,
        )
