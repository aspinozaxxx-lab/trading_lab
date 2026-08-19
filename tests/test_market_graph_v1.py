"""Trust-boundary and causal tests for market-graph-v1."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from market_lab.market_graph_v1.data import (
    PROTOCOL_PATH,
    PROTOCOL_SHA256,
    causal_correlations,
    causal_feature_window,
    inference_arrays,
    load_market_graph_arrays,
    load_protocol,
    sha256_file,
)
from market_lab.market_graph_v1.portfolio import (
    construct_prediction_weights,
    run_five_sleeve_backtest,
)


@pytest.fixture(scope="module")
def graph_data():
    config = load_protocol()
    arrays = load_market_graph_arrays(config)
    return config, arrays


def test_sealed_panel_is_all_assets_and_stops_before_2026(graph_data) -> None:
    config, arrays = graph_data
    assert (
        sha256_file(__import__("pathlib").Path(config["source"]["panel_path"]))
        == config["source"]["panel_sha256"]
    )
    assert arrays.features.shape == (2073, 30, 53)
    assert arrays.features.shape[:2] == arrays.asset_mask.shape
    assert str(arrays.dates[-1])[:10] == "2025-12-30"
    assert sha256_file(PROTOCOL_PATH) == PROTOCOL_SHA256


def test_correlation_and_windows_ignore_future_mutation(graph_data) -> None:
    config, arrays = graph_data
    cutoff = 500
    returns = arrays.correlation_returns.copy()
    baseline = causal_correlations(returns[: cutoff + 2], arrays.asset_mask[: cutoff + 2])
    returns[cutoff + 1 :] = 1_000_000.0
    changed = causal_correlations(returns[: cutoff + 2], arrays.asset_mask[: cutoff + 2])
    np.testing.assert_array_equal(baseline[: cutoff + 1], changed[: cutoff + 1])
    from market_lab.market_graph_v1.data import build_folds

    fold = build_folds(arrays, config)[0]
    correlations = causal_correlations(arrays.correlation_returns, arrays.asset_mask)
    inputs = inference_arrays(arrays, fold, correlations)
    window, mask = causal_feature_window(inputs, cutoff, 128)
    inputs.normalized_features[cutoff + 1 :] = 999.0
    poisoned_window, poisoned_mask = causal_feature_window(inputs, cutoff, 128)
    np.testing.assert_array_equal(window, poisoned_window)
    np.testing.assert_array_equal(mask, poisoned_mask)
    assert window.shape == (30, 128, 53)


def test_exact_portfolio_weights_respect_limits() -> None:
    factor = np.array([0.02, -0.02])
    sigma = np.array([0.01, 0.01])
    residual = np.tile(np.linspace(-1.0, 1.0, 30), (2, 1))
    current = np.ones((2, 30), dtype=bool)
    observable = current.copy()
    weights = construct_prediction_weights(factor, sigma, residual, current, observable)
    assert np.all(np.abs(weights) <= 0.10000001)
    assert np.all(np.abs(weights).sum(axis=1) <= 1.00000001)
    residual_only = construct_prediction_weights(
        np.zeros(2), np.full(2, np.inf), residual, current, observable
    )
    np.testing.assert_allclose(residual_only.sum(axis=1), 0.0, atol=1e-12)
    np.testing.assert_allclose(np.maximum(residual_only, 0.0).sum(axis=1), 0.375)
    np.testing.assert_allclose(np.abs(np.minimum(residual_only, 0.0)).sum(axis=1), 0.375)


def test_poisoned_targets_cannot_change_inference_inputs(graph_data) -> None:
    config, arrays = graph_data
    from market_lab.market_graph_v1.data import build_folds

    fold = build_folds(arrays, config)[0]
    correlations = causal_correlations(arrays.correlation_returns, arrays.asset_mask)
    baseline = inference_arrays(arrays, fold, correlations)
    poisoned_arrays = replace(
        arrays,
        targets=np.full_like(arrays.targets, 1_000_000.0),
        target_mask=~arrays.target_mask,
    )
    poisoned = inference_arrays(poisoned_arrays, fold, correlations)
    np.testing.assert_array_equal(baseline.normalized_features, poisoned.normalized_features)
    np.testing.assert_array_equal(baseline.feature_mask, poisoned.feature_mask)
    np.testing.assert_array_equal(baseline.asset_mask, poisoned.asset_mask)
    np.testing.assert_array_equal(baseline.correlations, poisoned.correlations)


def test_five_sleeve_holding_is_five_common_sessions() -> None:
    dates = np.arange(
        np.datetime64("2021-01-01"), np.datetime64("2021-01-13"), np.timedelta64(1, "D")
    )
    opens = np.full((len(dates), 2), 100.0)
    weights = np.zeros_like(opens)
    weights[0, 0] = 0.10
    result = run_five_sleeve_backtest(
        dates,
        ("AAA", "BBB"),
        opens,
        weights,
        start_index=0,
        one_way_cost_bps=0.0,
        short_borrow_rate_annual=0.0,
    )
    asset_orders = result.orders.loc[result.orders["ticker"].eq("AAA")]
    assert asset_orders["session_date"].tolist() == [
        __import__("pandas").Timestamp(dates[1]),
        __import__("pandas").Timestamp(dates[6]),
    ]
    assert not result.metrics["gross_limit_breach"]


def test_model_masks_invalid_asset_and_inference_has_no_target() -> None:
    torch = pytest.importorskip("torch")
    from market_lab.market_graph_v1.data import InferenceArrays
    from market_lab.market_graph_v1.experiment import TorchInferenceArrays
    from market_lab.market_graph_v1.model import MarketGraphModel

    assert "targets" not in InferenceArrays.__dataclass_fields__
    assert "targets" not in TorchInferenceArrays.__dataclass_fields__
    torch.manual_seed(7)
    model = MarketGraphModel(
        input_features=5,
        assets=4,
        hidden=16,
        temporal_blocks=2,
        graph_layers=2,
        heads=4,
        dropout=0.0,
        variant="graph",
    ).eval()
    values = torch.randn(2, 4, 8, 5)
    history_mask = torch.ones(2, 4, 8, dtype=torch.bool)
    current_mask = torch.ones(2, 4, dtype=torch.bool)
    current_mask[:, 3] = False
    correlation = torch.zeros(2, 4, 4)
    with torch.no_grad():
        baseline = model(values, history_mask, current_mask, correlation)
        poisoned = values.clone()
        poisoned[:, 3] = 1_000_000.0
        changed = model(poisoned, history_mask, current_mask, correlation)
    torch.testing.assert_close(baseline.factor_location, changed.factor_location, rtol=0, atol=0)
    torch.testing.assert_close(
        baseline.residual_location[:, :3], changed.residual_location[:, :3], rtol=0, atol=0
    )


def test_arithmetic_ensemble_is_deterministic_and_order_invariant() -> None:
    pytest.importorskip("torch")
    from market_lab.market_graph_v1.experiment import arithmetic_seed_ensemble

    values = {
        3141: np.array([3.0, 1.0]),
        1729: np.array([1.0, 5.0]),
        2718: np.array([2.0, 3.0]),
    }
    first = arithmetic_seed_ensemble(values)
    second = arithmetic_seed_ensemble(dict(reversed(list(values.items()))))
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(first, np.array([2.0, 3.0]))
