"""Synthetic fake-backend testy fail-closed futures-v8 train runnera."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v8.assembly import (
    V8_CAUSAL_V7_KEYS,
    V8AssemblyResult,
    V8CausalInputs,
    V8TargetArrays,
    build_v8_fold_scope,
)
from market_lab.futures_v8.config import (
    DEFAULT_V8_CONFIG_SHA256,
    V8_ASSETS,
    V8_SEEDS,
    V8_SSL_HORIZONS,
    load_v8_research_config,
)
from market_lab.futures_v8.train_run import (
    V8_PREDICTION_COLUMNS,
    V8CostScale,
    V8FoldStatistics,
    V8FoldTrainingView,
    V8InferenceView,
    V8SeedPrediction,
    V8SeedTrainingOutcome,
    V8SeedTrainingRequest,
    V8TrainingApi,
    build_authoritative_v8_cost_scale,
    build_v8_code_identity,
    build_v8_fold_training_view,
    build_v8_inference_view,
    build_v8_oos_sample_indices,
    fit_v8_fold_statistics,
    load_verified_v8_training_inputs,
    run_v8_training,
    verify_authoritative_v8_spec_proxy,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    """Hashiruet test artifact byte-v-byte."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(payload: Any) -> str:
    """Povtoriaet canonical manifest payload hash."""
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _decision(day: pd.Timestamp) -> np.datetime64:
    """Stroit D18:50 Moscow kak naive UTC datetime64."""
    value = (
        day.tz_localize("Europe/Moscow") + pd.Timedelta(hours=18, minutes=50)
    ).tz_convert("UTC")
    return np.datetime64(value.tz_localize(None), "ns")


def _synthetic_result(source: Path) -> V8AssemblyResult:
    """Stroit 2018--2025 causal arrays s 512 bars i five-session labels."""
    sessions = pd.DatetimeIndex(
        np.concatenate(
            [
                pd.bdate_range(f"{year}-01-02", periods=15).to_numpy(
                    dtype="datetime64[ns]"
                )
                for year in range(2018, 2026)
            ]
        )
    )
    samples = len(sessions)
    assets = len(V8_ASSETS)
    bars = 512
    bar_features = 12
    daily_features = 16
    decisions = np.asarray([_decision(day) for day in sessions], dtype="datetime64[ns]")
    offsets = np.arange(bars, 0, -1, dtype=np.int64) * np.timedelta64(10, "m")
    bar_times = decisions[:, None] - offsets[None, :]
    sample_axis = np.linspace(-1.0, 1.0, samples, dtype=np.float32)[:, None, None]
    asset_axis = np.arange(assets, dtype=np.float32)[None, :, None] * 0.05
    bar_axis = np.linspace(-0.2, 0.2, bars, dtype=np.float32)[None, None, :]
    base = sample_axis + asset_axis + bar_axis
    intraday = np.stack(
        [base + np.float32(feature * 0.01) for feature in range(bar_features)],
        axis=-1,
    ).astype(np.float32)
    intraday_valid = np.ones((samples, assets, bars), dtype=bool)
    daily_base = sample_axis[:, :, 0] + asset_axis[:, :, 0]
    daily = np.stack(
        [daily_base + np.float32(feature * 0.02) for feature in range(daily_features)],
        axis=-1,
    ).astype(np.float32)
    daily[:, :, 3] = 0.02 + np.arange(samples, dtype=np.float32)[:, None] * 1e-5
    daily_valid = np.ones_like(daily, dtype=bool)
    asset_valid = np.ones((samples, assets), dtype=bool)
    log_price = (
        4.0
        + sample_axis.astype(np.float64) * 0.01
        + asset_axis.astype(np.float64) * 0.02
        + bar_axis.astype(np.float64) * 0.03
    )
    normalized = np.zeros((samples, assets), dtype=np.float32)
    raw = np.zeros_like(normalized)
    target_valid = np.zeros((samples, assets), dtype=bool)
    volatility = np.zeros_like(normalized)
    nat = np.datetime64("NaT", "ns")
    entry_open = np.full((samples, assets), nat, dtype="datetime64[ns]")
    entry_close = entry_open.copy()
    exit_open = entry_open.copy()
    exit_close = entry_open.copy()
    availability = entry_open.copy()
    entry_capacity_open = entry_open.copy()
    exit_capacity_open = entry_open.copy()
    entry_capacity_volume = np.zeros((samples, assets), dtype=np.float32)
    exit_capacity_volume = np.zeros((samples, assets), dtype=np.float32)
    entry_contract = np.full((samples, assets), "", dtype="U16")
    exit_contract = np.full((samples, assets), "", dtype="U16")
    for row in range(samples - 6):
        for asset in range(assets):
            value = np.sin(row * 0.31 + asset * 0.7) * 0.4 + (asset - 1.5) * 0.03
            normalized[row, asset] = np.float32(value)
            raw[row, asset] = np.float32(value * 0.02 * np.sqrt(5.0))
            target_valid[row, asset] = True
            volatility[row, asset] = 0.02
            entry_open[row, asset] = decisions[row] + np.timedelta64(30, "m")
            entry_close[row, asset] = decisions[row] + np.timedelta64(40, "m")
            exit_open[row, asset] = decisions[row + 5] + np.timedelta64(30, "m")
            exit_close[row, asset] = decisions[row + 5] + np.timedelta64(40, "m")
            availability[row, asset] = exit_close[row, asset]
            entry_capacity_open[row, asset] = decisions[row] + np.timedelta64(10, "m")
            exit_capacity_open[row, asset] = decisions[row + 5] + np.timedelta64(10, "m")
            entry_capacity_volume[row, asset] = 1_000.0
            exit_capacity_volume[row, asset] = 1_000.0
            entry_contract[row, asset] = f"{V8_ASSETS[asset]}:C1"
            exit_contract[row, asset] = f"{V8_ASSETS[asset]}:C1"
    inputs = V8CausalInputs(
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily,
        daily_valid=daily_valid,
        asset_valid=asset_valid,
        log_price=np.asarray(log_price, dtype=np.float64),
        bar_times=bar_times,
        sample_trade_dates=sessions.to_numpy(dtype="datetime64[ns]"),
        decision_times=decisions,
        source_path=source.resolve(),
        source_sha256=_sha256(source),
    )
    targets = V8TargetArrays(
        raw_target=raw,
        normalized_target=normalized,
        valid=target_valid,
        ex_ante_daily_volatility_20=volatility,
        entry_window_open_times=entry_open,
        entry_window_close_times=entry_close,
        exit_window_open_times=exit_open,
        exit_window_close_times=exit_close,
        availability_times=availability,
        entry_contract_ids=entry_contract,
        exit_contract_ids=exit_contract,
        entry_capacity_open_times=entry_capacity_open,
        exit_capacity_open_times=exit_capacity_open,
        entry_capacity_volumes=entry_capacity_volume,
        exit_capacity_volumes=exit_capacity_volume,
    )
    audit = {
        "schema_version": 1,
        "research_status": "assembly_only_no_train_no_pnl_no_holdout_access",
        "protected_holdout_start": "2026-01-01",
        "v7_causal_keys_read": list(V8_CAUSAL_V7_KEYS),
        "legacy_v7_supervised_keys_read": [],
        "target_valid_is_ex_post_label_only_not_inference_eligibility": True,
        "target": {"horizon_common_sessions": 5},
    }
    return V8AssemblyResult(
        inputs=inputs,
        targets=targets,
        audit=audit,
        source_artifacts=(),
    )


@dataclass(frozen=True)
class _SyntheticProject:
    """Hranit isolated fake project, manifest seal i in-memory arrays."""

    root: Path
    config_path: Path
    manifest_path: Path
    manifest_sha256: str
    result: V8AssemblyResult

    def loader(self, path: Path, manifest: object) -> V8AssemblyResult:
        """Vozvrashchaet public assembly result posle runner hash-proverki dummy NPZ."""
        del manifest
        assert path.name == "assembly_synthetic.npz"
        return self.result


@pytest.fixture
def synthetic_project(tmp_path: Path) -> _SyntheticProject:
    """Kopiruet runtime closure/config i sozdaet externally sealed manifest."""
    root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT / "src" / "market_lab", root / "src" / "market_lab")
    config_dir = root / "configs"
    config_dir.mkdir(parents=True)
    config_name = "futures_v8_development_protocol.yaml"
    shutil.copy2(PROJECT_ROOT / "configs" / config_name, config_dir / config_name)
    shutil.copy2(
        PROJECT_ROOT / "configs" / "futures_v8_development_protocol.sha256",
        config_dir / "futures_v8_development_protocol.sha256",
    )
    data_root = root / "data"
    raw = data_root / "raw"
    processed = data_root / "processed" / "futures_v8"
    raw.mkdir(parents=True)
    processed.mkdir(parents=True)
    source = raw / "v7_causal_source.npz"
    source.write_bytes(b"sealed-v7-causal-source")
    parquet_a = raw / "same_kind_a.parquet"
    parquet_b = raw / "same_kind_b.parquet"
    parquet_a.write_bytes(b"sealed-parquet-a")
    parquet_b.write_bytes(b"sealed-parquet-b")
    result = _synthetic_result(source)
    arrays = processed / "assembly_synthetic.npz"
    arrays.write_bytes(b"synthetic-array-bytes-verified-before-injected-loader")
    in_memory_candles_sha = hashlib.sha256(b"candles").hexdigest()
    in_memory_map_sha = hashlib.sha256(b"active-map").hexdigest()
    source_relative = source.relative_to(data_root).as_posix()
    v7_source_id = f"v7_causal_npz:{source_relative}"
    candles_source_id = f"sealed_all_contract_10m_in_memory:{in_memory_candles_sha}"
    map_source_id = f"active_contract_map_in_memory:{in_memory_map_sha}"
    repeated_file_records = []
    for parquet in (parquet_a, parquet_b):
        relative = parquet.relative_to(data_root).as_posix()
        repeated_file_records.append(
            {
                "id": f"official_moex_10m_parquet:{relative}",
                "kind": "official_moex_10m_parquet",
                "path": relative,
                "bytes": parquet.stat().st_size,
                "rows": 1,
                "sha256": _sha256(parquet),
            }
        )
    source_artifacts = [
        {
            "id": v7_source_id,
            "kind": "v7_causal_npz",
            "path": source_relative,
            "bytes": source.stat().st_size,
            "sha256": _sha256(source),
            "keys_read": list(V8_CAUSAL_V7_KEYS),
            "legacy_supervised_keys_read": [],
        },
        {
            "id": candles_source_id,
            "kind": "sealed_all_contract_10m_in_memory",
            "rows": 100,
            "sha256": in_memory_candles_sha,
        },
        {
            "id": map_source_id,
            "kind": "active_contract_map_in_memory",
            "rows": 100,
            "sha256": in_memory_map_sha,
        },
        *repeated_file_records,
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "research_status": "assembly_only_no_train_no_pnl_no_holdout_access",
        "protected_holdout_start": "2026-01-01",
        "arrays": {
            "path": arrays.relative_to(data_root).as_posix(),
            "bytes": arrays.stat().st_size,
            "sha256": _sha256(arrays),
            "sample_count": result.inputs.sample_count,
            "intraday_shape": list(result.inputs.intraday.shape),
            "target_shape": list(result.targets.target.shape),
        },
        "v7_source": {
            "path": source_relative,
            "sha256": _sha256(source),
            "keys_read": list(V8_CAUSAL_V7_KEYS),
            "legacy_supervised_keys_read": [],
        },
        "source_hashes": {
            v7_source_id: _sha256(source),
            candles_source_id: in_memory_candles_sha,
            map_source_id: in_memory_map_sha,
            **{
                str(record["id"]): str(record["sha256"])
                for record in repeated_file_records
            },
        },
        "source_artifacts": source_artifacts,
        "audit": result.audit,
    }
    payload["manifest_payload_sha256"] = _canonical_sha(payload)
    manifest = processed / "manifest_synthetic.json"
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    return _SyntheticProject(
        root=root,
        config_path=config_dir / config_name,
        manifest_path=manifest,
        manifest_sha256=_sha256(manifest),
        result=result,
    )


class _FakeBackend:
    """Zapisyvaet calls i nikogda ne poluchaet OOS target container."""

    def __init__(self, *, drift_path: Path | None = None) -> None:
        """Nastroivaet normalnyi ili code-drift fake backend."""
        self.train_requests: list[V8SeedTrainingRequest] = []
        self.restore_requests: list[V8SeedTrainingRequest] = []
        self.inference_views: list[V8InferenceView] = []
        self.cost_views: list[V8FoldTrainingView] = []
        self.drift_path = drift_path
        self._drifted = False

    def fit_cost_scale(
        self,
        view: V8FoldTrainingView,
        statistics: V8FoldStatistics,
    ) -> V8CostScale:
        """Dokazyvaet train-only availability i vozvrashchaet nonzero fake cost."""
        self.cost_views.append(view)
        required = view.target_valid & view.asset_valid
        assert (view.target_availability_times[required] < view.effective_cutoff).all()
        assert statistics.train_target_iqr > 0.0
        bars = np.asarray(view.bar_times).astype("datetime64[ns]")
        for horizon_index, horizon in enumerate(V8_SSL_HORIZONS):
            usable = bars.shape[1] - horizon
            valid = view.ssl_valid_mask[:, :, :usable, horizon_index]
            origins = np.broadcast_to(bars[:, None, :usable], valid.shape)
            ends = np.broadcast_to(bars[:, None, horizon:], valid.shape)
            assert (origins[valid] < view.effective_cutoff).all()
            assert (ends[valid] < view.effective_cutoff).all()
        return V8CostScale(
            values_in_target_iqr=np.full(required.shape, 0.01, dtype=np.float32),
            valid=required.copy(),
            method="synthetic_d_known_fee_plus_tick_over_notional_vol_sqrt5_iqr",
            source_identity={"fixture_sha256": hashlib.sha256(b"cost").hexdigest()},
        )

    def train(self, request: V8SeedTrainingRequest) -> V8SeedTrainingOutcome:
        """Vozvrashchaet exact 48/32 histories i optional source drift."""
        self.train_requests.append(request)
        assert request.ssl_epochs == 48
        assert request.supervised_epochs == 32
        assert request.precision == "bfloat16"
        assert request.deterministic_algorithms
        assert request.fresh_ssl_initialization_required
        assert request.freeze_encoder_before_supervised_required
        assert request.training_view.global_sample_indices.ndim == 1
        assert np.all(np.diff(request.training_view.global_sample_indices) == 1)
        if self.drift_path is not None and not self._drifted:
            self.drift_path.write_text(
                self.drift_path.read_text(encoding="utf-8-sig") + "\n# drift\n",
                encoding="utf-8-sig",
            )
            self._drifted = True
        checkpoint = json.dumps(
            {"fold": request.fold_name, "seed": request.seed},
            sort_keys=True,
        ).encode("utf-8")
        return V8SeedTrainingOutcome(
            seed=request.seed,
            state=(request.fold_name, request.seed),
            checkpoint_bytes=checkpoint,
            ssl_history=tuple(
                {"epoch": epoch, "loss": 1.0 / epoch} for epoch in range(1, 49)
            ),
            supervised_history=tuple(
                {"epoch": epoch, "loss": 2.0 / epoch} for epoch in range(1, 33)
            ),
            fresh_ssl_initialization=True,
            encoder_frozen_before_supervised=True,
        )

    def restore(self, content: bytes, request: V8SeedTrainingRequest) -> tuple[str, int]:
        """Vosstanavlivaet tol'ko hash-proverennyi completed fake checkpoint."""
        self.restore_requests.append(request)
        payload = json.loads(content)
        assert payload == {"fold": request.fold_name, "seed": request.seed}
        return request.fold_name, request.seed

    def predict(
        self,
        state: tuple[str, int],
        inference: V8InferenceView,
        statistics: V8FoldStatistics,
    ) -> V8SeedPrediction:
        """Stroit target-free finite outputs s razdelennymi factor/residual heads."""
        del statistics
        assert not hasattr(inference, "normalized_target")
        assert not hasattr(inference, "target_valid")
        self.inference_views.append(inference)
        samples = len(inference.decision_times)
        assets = len(V8_ASSETS)
        seed_value = state[1] / 10_000.0
        residual = np.broadcast_to(
            np.asarray([-0.3, -0.1, 0.1, 0.3], dtype=np.float64),
            (samples, assets),
        ).copy()
        return V8SeedPrediction(
            factor_location=np.full(samples, seed_value),
            factor_scale=np.full(samples, 0.5 + seed_value * 0.01),
            factor_score=np.full(samples, 0.2),
            residual_location=residual,
            residual_scale=np.full((samples, assets), 0.7),
            residual_decision_score=np.tanh(residual),
            direction_logit=residual * 2.0,
        )

    def api(self) -> V8TrainingApi:
        """Sobiraet injectable API bez torch/CUDA."""
        return V8TrainingApi(
            fit_cost_scale=self.fit_cost_scale,
            train_completed_seed=self.train,
            restore_completed_seed=self.restore,
            predict_seed=self.predict,
            runtime_identity={
                "backend": "synthetic_fake",
                "precision": "bfloat16",
                "deterministic_algorithms": True,
            },
            reset_peak_vram=lambda: None,
            peak_vram=lambda: {"peak_allocated_bytes": 0, "peak_reserved_bytes": 0},
            release_fold=lambda: None,
        )


def _run(project: _SyntheticProject, backend: _FakeBackend, *, resume: bool = True):
    """Zapuskaet odin isolated fake run s exact external seals."""
    return run_v8_training(
        project.root,
        project.config_path,
        project.manifest_path,
        project.root / "runs" / "v8-fake",
        expected_config_sha256=DEFAULT_V8_CONFIG_SHA256,
        expected_assembly_manifest_sha256=project.manifest_sha256,
        expected_code_identity_sha256=build_v8_code_identity(project.root)[
            "code_identity_sha256"
        ],
        resume=resume,
        training_api=backend.api(),
        array_loader=project.loader,
    )


def test_fake_runner_completes_exact_5x3_and_emits_target_free_timing_schema(
    synthetic_project: _SyntheticProject,
) -> None:
    """Proveryaet 15 fresh stages, exact timing i otsutstvie targeta v inference."""
    backend = _FakeBackend()
    artifacts = _run(synthetic_project, backend)
    assert len(backend.cost_views) == 5
    assert len(backend.train_requests) == 15
    assert len(backend.restore_requests) == 0
    assert len(backend.inference_views) == 15
    assert {(item.fold_name, item.seed) for item in backend.train_requests} == {
        (f"outer_{year}", seed) for year in range(2021, 2026) for seed in V8_SEEDS
    }
    frame = pd.read_parquet(artifacts.predictions_path)
    assert tuple(frame.columns) == V8_PREDICTION_COLUMNS
    assert len(frame) == 5 * 15 * len(V8_ASSETS)
    assert frame["asset_valid"].all()
    decisions = pd.to_datetime(frame["decision_at"], utc=True).dt.tz_convert("Europe/Moscow")
    capacity = pd.to_datetime(frame["capacity_window_open_at"], utc=True).dt.tz_convert(
        "Europe/Moscow"
    )
    execution = pd.to_datetime(frame["execution_window_open_at"], utc=True).dt.tz_convert(
        "Europe/Moscow"
    )
    assert set(decisions.dt.strftime("%H:%M:%S")) == {"18:50:00"}
    assert set(capacity.dt.strftime("%H:%M:%S")) == {"19:00:00"}
    assert set(execution.dt.strftime("%H:%M:%S")) == {"19:20:00"}
    summary = json.loads(artifacts.training_summary_path.read_text(encoding="utf-8-sig"))
    assert summary["completed_seed_checkpoint_count"] == 15
    assert summary["pnl_or_trading_metrics_computed"] is False
    assert summary["prediction_artifact"]["mask_semantics"].endswith("never_target_valid")


def test_resume_accepts_only_completed_hash_matched_seed_bundles(
    synthetic_project: _SyntheticProject,
) -> None:
    """Resume ne povtoriaet train i otkloniaet podmenennyi checkpoint."""
    first = _FakeBackend()
    artifacts = _run(synthetic_project, first)
    resumed = _FakeBackend()
    _run(synthetic_project, resumed)
    assert not resumed.train_requests
    assert len(resumed.restore_requests) == 15
    checkpoint = next((artifacts.output_directory / "checkpoints").rglob("*.pt"))
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checkpoint byte SHA"):
        _run(synthetic_project, _FakeBackend())


def test_oos_path_ignores_poisoned_target_values_masks_and_all_timing(
    synthetic_project: _SyntheticProject,
) -> None:
    """Outer-2025 target poison ne meniaet loader, scope, stats, admission ili predict."""
    config = load_v8_research_config(synthetic_project.config_path)
    fold = config.development.folds[-1]
    baseline = build_v8_oos_sample_indices(
        synthetic_project.result.inputs.sample_trade_dates,
        synthetic_project.result.inputs.decision_times,
        fold,
        config.development.decision_timezone,
    )
    original = synthetic_project.result.targets
    raw = original.raw_target.copy()
    normalized = original.normalized_target.copy()
    valid = original.valid.copy()
    volatility = original.ex_ante_daily_volatility_20.copy()
    raw[baseline] = np.nan
    normalized[baseline] = np.inf
    valid[baseline] = ~valid[baseline]
    volatility[baseline] = -1_000_000.0
    timing_updates: dict[str, np.ndarray] = {}
    for field_name in (
        "entry_window_open_times",
        "entry_window_close_times",
        "exit_window_open_times",
        "exit_window_close_times",
        "availability_times",
        "entry_capacity_open_times",
        "exit_capacity_open_times",
    ):
        values = np.asarray(getattr(original, field_name)).copy()
        values[baseline] = np.datetime64("2035-01-01", "ns")
        timing_updates[field_name] = values
    poisoned_targets = replace(
        original,
        raw_target=raw,
        normalized_target=normalized,
        valid=valid,
        ex_ante_daily_volatility_20=volatility,
        **timing_updates,
    )
    poisoned_result = replace(synthetic_project.result, targets=poisoned_targets)
    loaded = load_verified_v8_training_inputs(
        synthetic_project.root,
        synthetic_project.config_path,
        synthetic_project.manifest_path,
        expected_assembly_manifest_sha256=synthetic_project.manifest_sha256,
        array_loader=lambda _path, _manifest: poisoned_result,
    )
    repeated = build_v8_oos_sample_indices(
        loaded.result.inputs.sample_trade_dates,
        loaded.result.inputs.decision_times,
        fold,
        config.development.decision_timezone,
    )
    np.testing.assert_array_equal(baseline, repeated)
    baseline_scope = build_v8_fold_scope(
        synthetic_project.result.inputs,
        synthetic_project.result.targets,
        train_start=fold.train_start,
        train_end=fold.train_end,
        purge_sessions=config.development.purge_sessions,
    )
    poisoned_scope = build_v8_fold_scope(
        loaded.result.inputs,
        loaded.result.targets,
        train_start=fold.train_start,
        train_end=fold.train_end,
        purge_sessions=config.development.purge_sessions,
    )
    np.testing.assert_array_equal(baseline_scope.sample_indices, poisoned_scope.sample_indices)
    baseline_stats = fit_v8_fold_statistics(
        synthetic_project.result,
        baseline_scope,
        config,
    )
    poisoned_stats = fit_v8_fold_statistics(loaded.result, poisoned_scope, config)
    assert baseline_stats.as_dict() == poisoned_stats.as_dict()
    baseline_inference = build_v8_inference_view(synthetic_project.result, baseline)
    poisoned_inference = build_v8_inference_view(loaded.result, repeated)
    for field_name in baseline_inference.__dataclass_fields__:
        np.testing.assert_array_equal(
            getattr(baseline_inference, field_name),
            getattr(poisoned_inference, field_name),
        )
    backend = _FakeBackend()
    baseline_prediction = backend.predict(
        (fold.name, V8_SEEDS[0]),
        baseline_inference,
        baseline_stats,
    )
    poisoned_prediction = backend.predict(
        (fold.name, V8_SEEDS[0]),
        poisoned_inference,
        poisoned_stats,
    )
    for field_name in baseline_prediction.__dataclass_fields__:
        np.testing.assert_array_equal(
            getattr(baseline_prediction, field_name),
            getattr(poisoned_prediction, field_name),
        )


def test_feature_scaler_excludes_target_invalid_asset_observations(
    synthetic_project: _SyntheticProject,
) -> None:
    """Target-invalid train asset ne mozhet contaminorovat' intraday/daily scaler."""
    config = load_v8_research_config(synthetic_project.config_path)
    fold = config.development.folds[0]
    targets = synthetic_project.result.targets
    valid = targets.valid.copy()
    valid[0, 0] = False
    modified_targets = replace(targets, valid=valid)
    first_inputs = synthetic_project.result.inputs
    first_intraday = first_inputs.intraday.copy()
    second_intraday = first_inputs.intraday.copy()
    first_daily = first_inputs.daily_context.copy()
    second_daily = first_inputs.daily_context.copy()
    first_intraday[0, 0] = 1_000_000.0
    second_intraday[0, 0] = -1_000_000.0
    first_daily[0, 0] = 2_000_000.0
    second_daily[0, 0] = -2_000_000.0
    first = replace(
        synthetic_project.result,
        inputs=replace(first_inputs, intraday=first_intraday, daily_context=first_daily),
        targets=modified_targets,
    )
    second = replace(
        synthetic_project.result,
        inputs=replace(
            first_inputs,
            intraday=second_intraday,
            daily_context=second_daily,
        ),
        targets=modified_targets,
    )
    scope = build_v8_fold_scope(
        first.inputs,
        first.targets,
        train_start=fold.train_start,
        train_end=fold.train_end,
        purge_sessions=config.development.purge_sessions,
    )
    assert 0 in scope.sample_indices
    assert fit_v8_fold_statistics(first, scope, config).as_dict() == (
        fit_v8_fold_statistics(second, scope, config).as_dict()
    )


def test_manifest_and_code_seals_fail_before_backend_training(
    synthetic_project: _SyntheticProject,
) -> None:
    """External data/code drift otsekaetsia do cost ili seed backend call."""
    backend = _FakeBackend()
    with pytest.raises(ValueError, match="manifest byte seal"):
        run_v8_training(
            synthetic_project.root,
            synthetic_project.config_path,
            synthetic_project.manifest_path,
            synthetic_project.root / "runs" / "bad-manifest",
            expected_assembly_manifest_sha256="0" * 64,
            training_api=backend.api(),
            array_loader=synthetic_project.loader,
        )
    assert not backend.cost_views and not backend.train_requests
    with pytest.raises(ValueError, match="code identity pre-CUDA"):
        run_v8_training(
            synthetic_project.root,
            synthetic_project.config_path,
            synthetic_project.manifest_path,
            synthetic_project.root / "runs" / "bad-code",
            expected_assembly_manifest_sha256=synthetic_project.manifest_sha256,
            expected_code_identity_sha256="0" * 64,
            training_api=backend.api(),
            array_loader=synthetic_project.loader,
        )
    assert not backend.cost_views and not backend.train_requests


def test_runtime_code_drift_prevents_first_checkpoint_commit(
    synthetic_project: _SyntheticProject,
) -> None:
    """Mutation posle identity commit ne sozdaet completed seed sidecar."""
    drift = synthetic_project.root / "src" / "market_lab" / "futures_v8" / "training.py"
    backend = _FakeBackend(drift_path=drift)
    with pytest.raises(ValueError, match="runtime code closure drift"):
        _run(synthetic_project, backend)
    checkpoint_root = synthetic_project.root / "runs" / "v8-fake" / "checkpoints"
    assert not list(checkpoint_root.rglob("*.manifest.json"))


def test_unknown_cost_provider_mask_fails_closed_before_seed_training(
    synthetic_project: _SyntheticProject,
) -> None:
    """Unknown cost nikogda ne zameniaetsia nulem dlia supervised targeta."""
    backend = _FakeBackend()

    def missing_cost(view: V8FoldTrainingView, _: V8FoldStatistics) -> V8CostScale:
        return V8CostScale(
            values_in_target_iqr=np.zeros(view.target_valid.shape, dtype=np.float32),
            valid=np.zeros(view.target_valid.shape, dtype=bool),
            method="missing",
            source_identity={},
        )

    api = backend.api()
    broken = V8TrainingApi(
        fit_cost_scale=missing_cost,
        train_completed_seed=api.train_completed_seed,
        restore_completed_seed=api.restore_completed_seed,
        predict_seed=api.predict_seed,
        runtime_identity=api.runtime_identity,
        reset_peak_vram=api.reset_peak_vram,
        peak_vram=api.peak_vram,
        release_fold=api.release_fold,
    )
    with pytest.raises(ValueError, match="ne dokazal cost"):
        run_v8_training(
            synthetic_project.root,
            synthetic_project.config_path,
            synthetic_project.manifest_path,
            synthetic_project.root / "runs" / "unknown-cost",
            expected_assembly_manifest_sha256=synthetic_project.manifest_sha256,
            training_api=broken,
            array_loader=synthetic_project.loader,
        )
    assert not backend.train_requests


def test_authoritative_spec_provider_verifies_sha_formula_and_decision_d_asof(
    synthetic_project: _SyntheticProject,
) -> None:
    """Proveryaet exact fee+tick formula i zapret stale/future observed date."""
    config = load_v8_research_config(synthetic_project.config_path)
    fold = config.development.folds[0]
    scope = build_v8_fold_scope(
        synthetic_project.result.inputs,
        synthetic_project.result.targets,
        train_start=fold.train_start,
        train_end=fold.train_end,
        purge_sessions=config.development.purge_sessions,
    )
    view = build_v8_fold_training_view(synthetic_project.result, scope)
    statistics = fit_v8_fold_statistics(synthetic_project.result, scope, config)
    rows: list[dict[str, Any]] = []
    for sample_index, decision_date in enumerate(view.sample_trade_dates):
        for asset_index, asset in enumerate(V8_ASSETS):
            rows.append(
                {
                    "session_date": view.entry_effective_dates[sample_index],
                    "contract_id": view.entry_contract_ids[sample_index, asset_index],
                    "asset_symbol": asset,
                    "sizing_observed_session_date": decision_date,
                    "sizing_notional": 10_000.0,
                    "sizing_tick_cash_value": 2.0,
                    "conservative_fee_per_side": 5.0,
                    "sizing_usable": True,
                    "spec_proxy_version": "futures-conservative-spec-proxy-v1",
                    "research_only": True,
                }
            )
    frame = pd.DataFrame(rows)
    directory = synthetic_project.root / "data" / "processed" / "spec_fixture"
    directory.mkdir(parents=True)
    parquet = directory / "spec_proxy.parquet"
    frame.to_parquet(parquet, index=False)
    manifest_payload = {
        "schema_version": 1,
        "spec_proxy_version": "futures-conservative-spec-proxy-v1",
        "requested_end": "2025-12-31",
        "protected_from": "2026-01-01",
        "output": {
            "parquet": {
                "path": parquet.relative_to(synthetic_project.root / "data").as_posix(),
                "rows": len(frame),
                "bytes": parquet.stat().st_size,
                "sha256": _sha256(parquet),
            }
        },
    }
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    verified = verify_authoritative_v8_spec_proxy(
        synthetic_project.root,
        manifest,
        _sha256(manifest),
    )
    cost = build_authoritative_v8_cost_scale(view, statistics, verified)
    required = view.target_valid & view.asset_valid
    required &= required.sum(axis=1, keepdims=True) >= 2
    expected = (5.0 + 2.0) / 10_000.0 / (
        np.maximum(view.ex_ante_daily_volatility_20, 0.01)
        * np.sqrt(5.0)
        * statistics.train_target_iqr
    )
    np.testing.assert_allclose(cost.values_in_target_iqr[required], expected[required])
    assert cost.valid[required].all()
    changed = verified.frame.copy()
    changed.loc[0, "sizing_observed_session_date"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="observed_session_date"):
        build_authoritative_v8_cost_scale(view, statistics, replace(verified, frame=changed))
    parquet.write_bytes(parquet.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="parquet bytes mismatch|parquet SHA mismatch"):
        verify_authoritative_v8_spec_proxy(
            synthetic_project.root,
            manifest,
            _sha256(manifest),
        )
