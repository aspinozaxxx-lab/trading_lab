"""Synthetic torch-testy causal arhitektury futures-v7."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")  # Lokal'no skip bez optional GPU-stack.

from market_lab.futures_v7.config import (  # noqa: E402
    V7_EXPECTED_PARAMETER_COUNT,
    load_v7_research_config,
)
from market_lab.futures_v7.model import (  # noqa: E402
    CausalMultiResolutionFuturesModel,
    configure_supervised_finetuning,
    model_architecture_manifest,
    set_v7_determinism,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren optional torch-testov.
V7_CONFIG_PATH = (  # Kanonicheskii config fiksirovannoi arhitektury.
    PROJECT_ROOT / "configs" / "futures_v7_development_protocol.yaml"
)


def _model_inputs(config: object) -> tuple[torch.Tensor, ...]:
    """Stroit synthetic tensor-batch s odnim propushchennym bar i context."""
    model_config = config.model
    intraday = torch.randn(
        1,
        4,
        model_config.sequence_bars,
        len(model_config.bar_feature_names),
    )
    intraday_mask = torch.ones(intraday.shape[:3], dtype=torch.bool)
    intraday_mask[:, 1, 250] = False
    daily = torch.randn(1, 4, len(model_config.daily_feature_names))
    daily_mask = torch.ones_like(daily, dtype=torch.bool)
    daily_mask[:, 2, 7] = False
    asset_mask = torch.ones(1, 4, dtype=torch.bool)
    return intraday, intraday_mask, daily, daily_mask, asset_mask


def test_exact_parameter_count_shapes_and_no_ticker_embeddings() -> None:
    """Proveryaet 2.245M vesov, obe golovy i otsutstvie ticker-parametrov."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    set_v7_determinism(config.training.seeds[0])
    model = CausalMultiResolutionFuturesModel(config.model).eval()
    manifest = model_architecture_manifest(model)
    assert manifest["parameter_count"] == V7_EXPECTED_PARAMETER_COUNT
    assert 1_000_000 <= manifest["parameter_count"] <= 3_000_000
    assert manifest["receptive_field_bars"] == 511
    assert not any("ticker" in name or "embedding" in name for name, _ in model.named_parameters())
    with torch.no_grad():
        output = model(*_model_inputs(config))
    assert output.daily_return.shape == (1, 4)
    assert output.ssl_return_volatility.shape == (1, 4, 512, 4, 2)
    assert output.encoded_sequence.shape == (1, 4, 512, 192)


def test_future_mutation_cannot_change_any_encoded_prefix() -> None:
    """Mutiruet budushchie bars vseh aktivov i sravnivaet ves' causal-prefix."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    set_v7_determinism(config.training.seeds[0])
    model = CausalMultiResolutionFuturesModel(config.model).eval()
    intraday, intraday_mask, _, _, asset_mask = _model_inputs(config)
    cutoff = 300
    mutated = intraday.clone()
    mutated[:, :, cutoff + 1 :] = torch.randn_like(mutated[:, :, cutoff + 1 :]) * 10_000.0
    with torch.no_grad():
        original_encoded = model.encode_intraday(intraday, intraday_mask, asset_mask)
        mutated_encoded = model.encode_intraday(mutated, intraday_mask, asset_mask)
    torch.testing.assert_close(
        original_encoded[:, :, : cutoff + 1],
        mutated_encoded[:, :, : cutoff + 1],
        rtol=0.0,
        atol=0.0,
    )


def test_masked_values_do_not_affect_output_and_state_roundtrip_is_exact() -> None:
    """Proveryaet sleeping-mask i save-load tol'ko cherez state_dict."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    set_v7_determinism(config.training.seeds[1])
    model = CausalMultiResolutionFuturesModel(config.model).eval()
    inputs = list(_model_inputs(config))
    masked_mutation = [tensor.clone() for tensor in inputs]
    masked_mutation[0][:, 1, 250] = 1_000_000.0
    masked_mutation[2][:, 2, 7] = -1_000_000.0
    with torch.no_grad():
        original = model(*inputs).daily_return
        changed = model(*masked_mutation).daily_return
    torch.testing.assert_close(original, changed, rtol=0.0, atol=0.0)

    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    buffer.seek(0)
    restored = CausalMultiResolutionFuturesModel(config.model).eval()
    restored.load_state_dict(torch.load(buffer, map_location="cpu"))
    with torch.no_grad():
        roundtrip = restored(*inputs).daily_return
    torch.testing.assert_close(original, roundtrip, rtol=0.0, atol=0.0)


def test_asset_permutation_only_permutes_predictions() -> None:
    """Dokazyvaet ticker-agnostic equivariance obshchego encodera i attention."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    set_v7_determinism(config.training.seeds[2])
    model = CausalMultiResolutionFuturesModel(config.model).eval()
    inputs = _model_inputs(config)
    permutation = torch.tensor([2, 0, 3, 1])
    permuted_inputs = tuple(tensor[:, permutation] for tensor in inputs)
    with torch.no_grad():
        original = model(*inputs).daily_return
        permuted = model(*permuted_inputs).daily_return
    torch.testing.assert_close(permuted, original[:, permutation], rtol=0.0, atol=1e-7)


def test_supervised_schedule_freezes_first_six_temporal_blocks() -> None:
    """Proveryaet fiksirovannyi malyi finetune-posle-SSL schedule."""
    config = load_v7_research_config(V7_CONFIG_PATH)
    model = CausalMultiResolutionFuturesModel(config.model)
    configure_supervised_finetuning(model, config.training.freeze_first_temporal_blocks)
    assert not any(parameter.requires_grad for parameter in model.temporal_blocks[0].parameters())
    assert any(parameter.requires_grad for parameter in model.temporal_blocks[-1].parameters())
    assert all(parameter.requires_grad for parameter in model.daily_head.parameters())
    assert not any(parameter.requires_grad for parameter in model.ssl_head.parameters())
