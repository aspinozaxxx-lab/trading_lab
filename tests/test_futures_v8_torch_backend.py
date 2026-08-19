"""CUDA micro-smoke real futures-v8 PyTorch backend bez market train ili PnL."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from market_lab.futures_v8.config import (  # noqa: E402
    V8_ASSETS,
    V8_SSL_HORIZONS,
    load_v8_research_config,
)
from market_lab.futures_v8.train_run import (  # noqa: E402
    V8CostScale,
    V8FoldStatistics,
    V8FoldTrainingView,
    V8InferenceView,
    V8SeedTrainingRequest,
    build_v8_torch_training_api,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _cuda_5090_available() -> bool:
    """Vozvrashchaet true tol'ko dlia authorized server micro-smoke GPU."""
    return bool(torch.cuda.is_available() and "RTX 5090" in torch.cuda.get_device_name(0))


def _micro_view() -> V8FoldTrainingView:
    """Stroit dva purged samples s factual 512-bar SSL intervals."""
    rng = np.random.default_rng(1729)
    samples = 2
    assets = len(V8_ASSETS)
    bars = 512
    bar_features = 12
    daily_features = 16
    decisions = np.array(
        ["2024-06-10T15:50:00", "2024-06-17T15:50:00"],
        dtype="datetime64[ns]",
    )
    offsets = np.arange(bars, 0, -1, dtype=np.int64) * np.timedelta64(10, "m")
    bar_times = decisions[:, None] - offsets[None, :]
    intraday = rng.normal(0.0, 0.2, (samples, assets, bars, bar_features)).astype(
        np.float32
    )
    intraday_valid = np.ones((samples, assets, bars), dtype=bool)
    daily = rng.normal(0.0, 0.2, (samples, assets, daily_features)).astype(np.float32)
    daily_valid = np.ones_like(daily, dtype=bool)
    asset_valid = np.ones((samples, assets), dtype=bool)
    increments = rng.normal(0.0, 0.001, (samples, assets, bars - 1))
    log_price = np.concatenate(
        (
            np.full((samples, assets, 1), 4.0, dtype=np.float64),
            4.0 + np.cumsum(increments, axis=2),
        ),
        axis=2,
    )
    ssl_valid = np.zeros((samples, assets, bars, len(V8_SSL_HORIZONS)), dtype=bool)
    for horizon_index, horizon in enumerate(V8_SSL_HORIZONS):
        ssl_valid[:, :, : bars - horizon, horizon_index] = True
    target = np.array(
        [[0.02, -0.01, 0.015, -0.005], [-0.01, 0.02, -0.015, 0.005]],
        dtype=np.float32,
    )
    target_valid = np.ones_like(target, dtype=bool)
    availability = np.broadcast_to(
        np.array(["2024-06-20", "2024-06-27"], dtype="datetime64[ns]")[:, None],
        target.shape,
    ).copy()
    contracts = np.broadcast_to(
        np.asarray([f"{asset}:C1" for asset in V8_ASSETS], dtype="U128")[None, :],
        target.shape,
    ).copy()
    capacity_open = np.broadcast_to(
        (decisions + np.timedelta64(10, "m"))[:, None],
        target.shape,
    ).copy()
    capacity_exit = capacity_open + np.timedelta64(5, "D")
    return V8FoldTrainingView(
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily,
        daily_valid=daily_valid,
        asset_valid=asset_valid,
        log_price=log_price,
        bar_times=bar_times,
        decision_times=decisions,
        sample_trade_dates=decisions.astype("datetime64[D]").astype("datetime64[ns]"),
        normalized_target=target,
        target_valid=target_valid,
        target_availability_times=availability,
        ex_ante_daily_volatility_20=np.full(target.shape, 0.02, dtype=np.float32),
        entry_effective_dates=(decisions + np.timedelta64(1, "D")).astype(
            "datetime64[D]"
        ),
        entry_contract_ids=contracts,
        entry_capacity_open_times=capacity_open,
        exit_capacity_open_times=capacity_exit,
        entry_capacity_volumes=np.full(target.shape, 10_000.0, dtype=np.float64),
        exit_capacity_volumes=np.full(target.shape, 10_000.0, dtype=np.float64),
        ssl_valid_mask=ssl_valid,
        global_sample_indices=np.arange(samples, dtype=np.int64),
        effective_cutoff=np.datetime64("2025-01-01", "ns"),
    )


def _statistics(view: V8FoldTrainingView) -> V8FoldStatistics:
    """Fiksiruet synthetic train-only robust statistics dlia micro-smoke."""
    del view
    return V8FoldStatistics(
        intraday_median=(0.0,) * 12,
        intraday_iqr=(1.0,) * 12,
        intraday_observations=(4096,) * 12,
        daily_median=(0.0,) * 16,
        daily_iqr=(1.0,) * 16,
        daily_observations=(8,) * 16,
        train_target_iqr=0.02,
        train_target_observations=8,
        sample_indices_sha256="0" * 64,
        effective_cutoff="2025-01-01T00:00:00.000000000",
    )


def _inference(view: V8FoldTrainingView) -> V8InferenceView:
    """Kopiruet tol'ko causal arrays i konstruktivno ne peredaet target."""
    return V8InferenceView(
        intraday=view.intraday.copy(),
        intraday_valid=view.intraday_valid.copy(),
        daily_context=view.daily_context.copy(),
        daily_valid=view.daily_valid.copy(),
        asset_valid=view.asset_valid.copy(),
        bar_times=view.bar_times.copy(),
        decision_times=view.decision_times.copy(),
        sample_trade_dates=view.sample_trade_dates.copy(),
        global_sample_indices=view.global_sample_indices.copy(),
    )


@pytest.mark.skipif(not _cuda_5090_available(), reason="requires isolated RTX 5090")
def test_real_torch_backend_micro_smoke_checkpoint_restore_and_determinism() -> None:
    """Prohodit 1+1 test epochs, BF16 predict i identical fresh-seed result."""
    config = load_v8_research_config(
        PROJECT_ROOT / "configs" / "futures_v8_development_protocol.yaml"
    )
    view = _micro_view()
    statistics = _statistics(view)
    cost = V8CostScale(
        values_in_target_iqr=np.full(view.target_valid.shape, 0.01, dtype=np.float32),
        valid=np.ones(view.target_valid.shape, dtype=bool),
        method="test_only_positive_cost",
        source_identity={"test_only": True},
    )
    request = V8SeedTrainingRequest(
        fold_name="micro-fold",
        seed=1729,
        training_view=view,
        statistics=statistics,
        cost_scale=cost,
        ssl_epochs=1,
        supervised_epochs=1,
        ssl_learning_rate=config.training.ssl_learning_rate,
        supervised_learning_rate=config.training.supervised_learning_rate,
        weight_decay=config.training.weight_decay,
        gradient_clip_norm=config.training.gradient_clip_norm,
        precision=config.training.precision,
        deterministic_algorithms=True,
        fresh_ssl_initialization_required=True,
        freeze_encoder_before_supervised_required=True,
    )
    api = build_v8_torch_training_api(
        config,
        ssl_batch_size=2,
        supervised_batch_size=2,
        inference_batch_size=2,
        test_only_allow_epoch_override=True,
    )
    first = api.train_completed_seed(request)
    assert len(first.ssl_history) == len(first.supervised_history) == 1
    assert first.state.model.temporal_blocks[0].training is False
    assert sum(parameter.numel() for parameter in first.state.model.parameters()) == 2_694_086
    assert sum(
        parameter.numel()
        for parameter in first.state.model.parameters()
        if parameter.requires_grad
    ) == 149_534
    causal = _inference(view)
    prediction = api.predict_seed(first.state, causal, statistics)
    restored = api.restore_completed_seed(first.checkpoint_bytes, request)
    restored_prediction = api.predict_seed(restored, causal, statistics)
    for field_name in prediction.__dataclass_fields__:
        np.testing.assert_array_equal(
            getattr(prediction, field_name),
            getattr(restored_prediction, field_name),
        )
    second = api.train_completed_seed(request)
    second_prediction = api.predict_seed(second.state, causal, statistics)
    for field_name in prediction.__dataclass_fields__:
        np.testing.assert_array_equal(
            getattr(prediction, field_name),
            getattr(second_prediction, field_name),
        )
    damaged = bytearray(first.checkpoint_bytes)
    damaged[0] ^= 0x01
    with pytest.raises(ValueError, match="deserialize"):
        api.restore_completed_seed(bytes(damaged), request)
    assert api.runtime_identity["precision"] == "bfloat16"
    assert "RTX 5090" in api.runtime_identity["device_name"]
    api.release_fold()
