"""Synthetic testy causal calibrated residual alpha arhitektury futures-v8."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
import yaml

torch = pytest.importorskip("torch")

from market_lab.futures_v8.config import (  # noqa: E402
    V8_ASSETS,
    V8_EXPECTED_PARAMETER_COUNT,
    V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT,
    V8ResearchConfig,
)
from market_lab.futures_v8.model import (  # noqa: E402
    CausalPatchStateSpaceRegimeAlphaModel,
    configure_v8_supervised_finetuning,
    load_v8_checkpoint_verified,
    model_architecture_manifest,
    set_v8_determinism,
)
from market_lab.futures_v8.training import (  # noqa: E402
    FiveSessionTargetBatch,
    FoldLocalSslBoundary,
    OrderedDecisionBatch,
    auxiliary_residual_direction_loss,
    causal_patch_contrastive_loss,
    causal_previous_positions,
    cross_asset_residual_targets,
    differentiable_cost_aware_residual_utility_loss,
    masked_dynamic_ssl_loss,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V8_CONFIG_PATH = PROJECT_ROOT / "configs" / "futures_v8_development_protocol.yaml"


def _inputs(config: object) -> tuple[torch.Tensor, ...]:
    """Stroit odin complete synthetic D18:50 feature batch bez targetov."""
    model_config = config.model
    intraday = torch.randn(
        1,
        4,
        model_config.sequence_bars,
        len(model_config.bar_feature_names),
    )
    intraday_mask = torch.ones(intraday.shape[:3], dtype=torch.bool)
    intraday_mask[:, 1, 240] = False
    daily = torch.randn(1, 4, len(model_config.daily_feature_names))
    daily_mask = torch.ones_like(daily, dtype=torch.bool)
    daily_mask[:, 2, 6] = False
    asset_mask = torch.ones(1, 4, dtype=torch.bool)
    return intraday, intraday_mask, daily, daily_mask, asset_mask


def _model() -> tuple[object, CausalPatchStateSpaceRegimeAlphaModel]:
    """Chitaet current YAML bez pending sidecar seal i stroit deterministic model."""
    payload = yaml.safe_load(V8_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    config = V8ResearchConfig.model_validate(payload)
    set_v8_determinism(config.training.seeds[0])
    return config, CausalPatchStateSpaceRegimeAlphaModel(config.model).eval()


def test_exact_parameter_count_shapes_and_frozen_supervised_budget() -> None:
    """Proveryaet sealed 2.694M model i men'shii 150k supervised surface."""
    config, model = _model()
    manifest = model_architecture_manifest(model)
    assert manifest["parameter_count"] == V8_EXPECTED_PARAMETER_COUNT == 2_694_086
    assert manifest["patch_count"] == 64
    assert not any("ticker" in name or "embedding" in name for name, _ in model.named_parameters())
    with torch.no_grad():
        output = model(*_inputs(config))
    assert output.return_location.shape == (1, 4)
    assert output.factor_location.shape == (1,)
    assert output.factor_scale.shape == (1,)
    assert output.factor_decision_score.shape == (1,)
    assert output.residual_location.shape == (1, 4)
    assert output.direction_logit.shape == (1, 4)
    assert output.patch_embeddings.shape == (1, 4, 64, 160)
    assert output.ssl_forecasts.shape == (1, 4, 64, 4, 2)
    torch.testing.assert_close(
        output.residual_location.mean(dim=1),
        torch.zeros(1),
        rtol=0.0,
        atol=1e-7,
    )
    configure_v8_supervised_finetuning(model)
    assert model_architecture_manifest(model)["supervised_trainable_parameter_count"] == (
        V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT
    )


def test_ssl_contrastive_gradient_reaches_asset_attention_before_supervised_freeze() -> None:
    """Ne ostavliaet cross-asset attention sluchainym pered ego freeze."""
    config, model = _model()
    model.train()
    inputs = _inputs(config)
    first = model(*inputs)
    second = model(*inputs)
    input_end = np.full(
        (1, len(V8_ASSETS), 64),
        np.datetime64("2024-01-01T12:00:00", "ns"),
        dtype="datetime64[ns]",
    )
    boundary = FoldLocalSslBoundary(
        input_bar_end_times=input_end,
        horizon_end_times=np.broadcast_to(input_end[..., None], (*input_end.shape, 4)),
        purged_train_cutoff=np.datetime64("2025-01-01", "ns"),
    )
    loss = causal_patch_contrastive_loss(
        first.contrastive_embedding,
        second.contrastive_embedding,
        inputs[-1],
        boundary,
    )
    assert torch.isfinite(loss) and loss.item() > 0.0
    loss.backward()
    gradients = [
        parameter.grad
        for parameter in model.asset_attention.parameters()
        if parameter.grad is not None
    ]
    assert gradients
    assert all(torch.isfinite(gradient).all() for gradient in gradients)
    assert sum(float(gradient.abs().sum()) for gradient in gradients) > 0.0
    configure_v8_supervised_finetuning(model)
    model.train()
    assert not model.asset_attention.training
    assert all(not parameter.requires_grad for parameter in model.asset_attention.parameters())


def test_effective_asset_mask_and_missing_tail_cannot_inject_bias_or_change_decision() -> None:
    """Vyvodit effective asset mask iz faktov i ignoriruet fully missing asset/tail."""
    config, model = _model()
    inputs = list(_inputs(config))
    inputs[1][:, 0, 400:] = False
    inputs[2][:, 0] = -123.0
    inputs[3][:, 0] = False
    mutated = [item.clone() for item in inputs]
    mutated[0][:, 0, 400:] = 1_000_000.0
    with torch.no_grad():
        original = model(*inputs)
        changed = model(*mutated)
    torch.testing.assert_close(original.decision_score, changed.decision_score, rtol=0.0, atol=0.0)
    torch.testing.assert_close(
        original.patch_embeddings[:, 0, 50:],
        torch.zeros_like(original.patch_embeddings[:, 0, 50:]),
        rtol=0.0,
        atol=0.0,
    )
    no_intraday = [item.clone() for item in inputs]
    no_intraday[1][:, 3] = False
    no_intraday[0][:, 3] = 1_000_000.0
    no_intraday[2][:, 3] = torch.nan
    mutated_no_intraday = [item.clone() for item in no_intraday]
    mutated_no_intraday[0][:, 3] = -1_000_000.0
    mutated_no_intraday[2][:, 3] = torch.inf
    with torch.no_grad():
        excluded_first = model(*no_intraday)
        excluded_second = model(*mutated_no_intraday)
    torch.testing.assert_close(
        excluded_first.decision_score[:, :3],
        excluded_second.decision_score[:, :3],
        rtol=0.0,
        atol=0.0,
    )
    torch.testing.assert_close(
        excluded_first.decision_score[:, 3],
        torch.zeros_like(excluded_first.decision_score[:, 3]),
        rtol=0.0,
        atol=0.0,
    )
    all_missing = [item.clone() for item in inputs]
    all_missing[1][:] = False
    with pytest.raises(ValueError, match="factual intraday bar"):
        model(*all_missing)


def test_frozen_supervised_encoder_stays_eval_after_model_train_and_is_repeatable() -> None:
    """Ne daet outer ``train`` vkliuchit' dropout v zapechatannom SSL encoder."""
    config, model = _model()
    configure_v8_supervised_finetuning(model)
    model.train()
    assert model.training
    assert not model.patch_projection.training
    assert not model.temporal_blocks.training
    assert not model.asset_attention.training
    intraday, intraday_mask, _, _, asset_mask = _inputs(config)
    with torch.no_grad():
        first = model.encode_patches(intraday, intraday_mask, asset_mask)
        second = model.encode_patches(intraday, intraday_mask, asset_mask)
    torch.testing.assert_close(first, second, rtol=0.0, atol=0.0)
    latest = model._last_valid_patch(first, model._patch_valid(intraday_mask))
    with torch.no_grad():
        first_asset_state = model.asset_attention(latest, asset_mask)
        second_asset_state = model.asset_attention(latest, asset_mask)
    torch.testing.assert_close(first_asset_state, second_asset_state, rtol=0.0, atol=0.0)


def test_future_patch_mutation_cannot_change_any_completed_patch_prefix() -> None:
    """Mutiruet budushchie 10m bars i proveriaet vse zakonchennye causal patchi."""
    config, model = _model()
    intraday, intraday_mask, _, _, asset_mask = _inputs(config)
    completed_patch_count = 35
    mutated = intraday.clone()
    future_start = completed_patch_count * config.model.patch_size_bars
    mutated[:, :, future_start:] = torch.randn_like(mutated[:, :, future_start:]) * 1_000_000.0
    with torch.no_grad():
        original = model.encode_patches(intraday, intraday_mask, asset_mask)
        changed = model.encode_patches(mutated, intraday_mask, asset_mask)
    torch.testing.assert_close(
        original[:, :, :completed_patch_count],
        changed[:, :, :completed_patch_count],
        rtol=0.0,
        atol=0.0,
    )


def test_masked_values_and_repeat_seed_are_exactly_deterministic() -> None:
    """Dokazyvaet sleeping mask i povtor state/input bez future ili RNG drift."""
    config, first = _model()
    inputs = list(_inputs(config))
    changed = [item.clone() for item in inputs]
    changed[0][:, 1, 240] = 1_000_000.0
    changed[2][:, 2, 6] = -1_000_000.0
    with torch.no_grad():
        original = first(*inputs).decision_score
        masked_changed = first(*changed).decision_score
    torch.testing.assert_close(original, masked_changed, rtol=0.0, atol=0.0)

    set_v8_determinism(config.training.seeds[0])
    second = CausalPatchStateSpaceRegimeAlphaModel(config.model).eval()
    with torch.no_grad():
        repeat = second(*inputs).decision_score
    torch.testing.assert_close(original, repeat, rtol=0.0, atol=0.0)


def test_direction_logit_cannot_create_uniform_long_return_or_cost_score() -> None:
    """Regressia protiv v7 bug: high BCE logit ne prevrashchaetsia v return alpha."""
    config, model = _model()
    with torch.no_grad():
        model.factor_head.return_location.weight.zero_()
        model.factor_head.return_location.bias.zero_()
        model.factor_head.return_scale.weight.zero_()
        model.factor_head.return_scale.bias.zero_()
        for expert in model.residual_experts:
            expert.return_location.weight.zero_()
            expert.return_location.bias.zero_()
            expert.direction_logit.weight.zero_()
            expert.direction_logit.bias.fill_(50.0)
    with torch.no_grad():
        output = model(*_inputs(config))
    assert torch.all(output.direction_logit > 40.0)
    torch.testing.assert_close(output.return_location, torch.zeros_like(output.return_location))
    torch.testing.assert_close(output.decision_score, torch.zeros_like(output.decision_score))

    targets = torch.tensor([[0.010, -0.010, 0.005, -0.005]])
    valid = torch.ones_like(targets, dtype=torch.bool)
    residuals = cross_asset_residual_targets(targets, valid, train_target_iqr=0.01)
    torch.testing.assert_close(residuals.factor, torch.zeros(1))
    assert residuals.residual_valid.all()
    direction_loss = auxiliary_residual_direction_loss(
        output.direction_logit,
        residuals.residual,
        residuals.residual_valid,
    )
    assert direction_loss.item() > 1.0
    cost_loss = differentiable_cost_aware_residual_utility_loss(
        output.decision_score,
        residuals.residual,
        residuals.residual_valid,
        torch.full_like(targets, 0.02),
        OrderedDecisionBatch(
            decision_times=np.array(["2025-01-01T15:50:00"], dtype="datetime64[ns]"),
            sequence_numbers=np.array([0]),
            starts_flat=True,
        ),
    )
    assert cost_loss.item() == pytest.approx(0.0, abs=0.0)


@pytest.mark.parametrize("invalid_cost", [0.0, -0.01, float("nan"), float("inf")])
def test_cost_aware_loss_rejects_unknown_or_nonpositive_required_cost(
    invalid_cost: float,
) -> None:
    """Fail-closed esli hotia odin residual-valid D-known cost ne positive finite."""
    scores = torch.tensor([[0.2, -0.1]])
    targets = torch.tensor([[0.1, -0.1]])
    valid = torch.ones_like(scores, dtype=torch.bool)
    costs = torch.tensor([[0.01, invalid_cost]])
    ordered = OrderedDecisionBatch(
        decision_times=np.array(["2025-01-01T15:50:00"], dtype="datetime64[ns]"),
        sequence_numbers=np.array([0]),
        starts_flat=True,
    )
    with pytest.raises(ValueError, match="finite positive"):
        differentiable_cost_aware_residual_utility_loss(
            scores,
            targets,
            valid,
            costs,
            ordered,
        )


def test_factor_sleeve_is_bounded_and_separate_from_residual_direction_logit() -> None:
    """Common factor poluchaet svoj risk/abstain output, no BCE ne sozdaet long alpha."""
    config, model = _model()
    with torch.no_grad():
        model.factor_head.return_location.weight.zero_()
        model.factor_head.return_location.bias.fill_(2.0)
        model.factor_head.return_scale.weight.zero_()
        model.factor_head.return_scale.bias.zero_()
        for expert in model.residual_experts:
            expert.return_location.weight.zero_()
            expert.return_location.bias.zero_()
            expert.direction_logit.weight.zero_()
            expert.direction_logit.bias.fill_(50.0)
    with torch.no_grad():
        output = model(*_inputs(config))
    assert output.factor_location.item() == pytest.approx(2.0)
    assert output.factor_scale.item() > 0.0
    assert 0.0 < output.factor_decision_score.item() <= 1.0
    torch.testing.assert_close(output.decision_score, torch.zeros_like(output.decision_score))


def test_causal_previous_position_contract_rejects_shuffle_and_uses_only_t_minus_one() -> None:
    """Zapreshchaet shuffled batch i strogo stroit turnover baseline iz predydushchego score."""
    scores = torch.tensor([[0.20, -0.40], [0.60, 0.10], [-0.30, 0.20]])
    times = np.array(
        [
            "2025-01-01T15:50:00",
            "2025-01-02T15:50:00",
            "2025-01-03T15:50:00",
        ],
        dtype="datetime64[ns]",
    )
    ordered = OrderedDecisionBatch(
        decision_times=times,
        sequence_numbers=np.array([10, 11, 12]),
        starts_flat=True,
    )
    previous = causal_previous_positions(scores, ordered).values
    torch.testing.assert_close(previous[0], torch.zeros(2), rtol=0.0, atol=0.0)
    torch.testing.assert_close(previous[1], scores[0], rtol=0.0, atol=0.0)
    torch.testing.assert_close(previous[2], scores[1], rtol=0.0, atol=0.0)
    with pytest.raises(ValueError, match="strogo vozrastaiushchimi"):
        causal_previous_positions(
            scores,
            OrderedDecisionBatch(
                decision_times=times[[1, 0, 2]],
                sequence_numbers=np.array([10, 11, 12]),
                starts_flat=True,
            ),
        )
    with pytest.raises(ValueError, match="contiguous"):
        causal_previous_positions(
            scores,
            OrderedDecisionBatch(
                decision_times=times,
                sequence_numbers=np.array([10, 12, 13]),
                starts_flat=True,
            ),
        )
    with pytest.raises(TypeError, match="OrderedDecisionBatch"):
        causal_previous_positions(scores, times)  # type: ignore[arg-type]


def test_five_session_target_and_fold_local_ssl_reject_cutoff_leakage() -> None:
    """Ne daet ni supervised, ni fresh-fold SSL label dostich' purged cutoff."""
    target = FiveSessionTargetBatch(
        values=torch.tensor([[0.01, -0.02]]),
        target_mask=torch.ones((1, 2), dtype=torch.bool),
        label_end_times=np.array(
            [["2024-12-18T16:30:00", "2024-12-19T16:30:00"]],
            dtype="datetime64[ns]",
        ),
        purged_train_cutoff=np.datetime64("2024-12-20T00:00:00"),
    )
    target.validate()
    with pytest.raises(ValueError, match="horizon rovno 5"):
        FiveSessionTargetBatch(
            values=target.values,
            target_mask=target.target_mask,
            label_end_times=target.label_end_times,
            purged_train_cutoff=target.purged_train_cutoff,
            horizon_common_sessions=1,
        ).validate()
    leaking_target = FiveSessionTargetBatch(
        values=target.values,
        target_mask=target.target_mask,
        label_end_times=np.array(
            [["2024-12-18T16:30:00", "2024-12-20T00:00:00"]],
            dtype="datetime64[ns]",
        ),
        purged_train_cutoff=target.purged_train_cutoff,
    )
    with pytest.raises(ValueError, match="strogo do purged cutoff"):
        leaking_target.validate()

    forecasts = torch.zeros((1, 1, 2, 2, 2))
    ssl_targets = torch.zeros_like(forecasts)
    ssl_mask = torch.ones(forecasts.shape[:-1], dtype=torch.bool)
    safe_boundary = FoldLocalSslBoundary(
        input_bar_end_times=np.array(
            [[["2024-12-18T10:00:00", "2024-12-18T11:00:00"]]],
            dtype="datetime64[ns]",
        ),
        horizon_end_times=np.array(
            [
                [
                    [
                        ["2024-12-18T11:00:00", "2024-12-18T12:00:00"],
                        ["2024-12-18T12:00:00", "2024-12-18T13:00:00"],
                    ]
                ]
            ],
            dtype="datetime64[ns]",
        ),
        purged_train_cutoff=np.datetime64("2024-12-20T00:00:00"),
    )
    assert torch.isfinite(
        masked_dynamic_ssl_loss(forecasts, ssl_targets, ssl_mask, safe_boundary)
    )
    contrastive = torch.randn((1, 1, 8))
    assert causal_patch_contrastive_loss(
        contrastive,
        contrastive,
        torch.ones((1, 1), dtype=torch.bool),
        safe_boundary,
    ).item() == pytest.approx(0.0, abs=0.0)
    leaking_horizons = safe_boundary.horizon_end_times.copy()
    leaking_horizons[0, 0, 1, 1] = np.datetime64("2024-12-20T00:00:00")
    with pytest.raises(ValueError, match="horizon end"):
        masked_dynamic_ssl_loss(
            forecasts,
            ssl_targets,
            ssl_mask,
            FoldLocalSslBoundary(
                input_bar_end_times=safe_boundary.input_bar_end_times,
                horizon_end_times=leaking_horizons,
                purged_train_cutoff=safe_boundary.purged_train_cutoff,
            ),
        )
    leaking_inputs = safe_boundary.input_bar_end_times.copy()
    leaking_inputs[0, 0, 1] = np.datetime64("2024-12-20T00:00:00")
    leaking_input_boundary = FoldLocalSslBoundary(
        input_bar_end_times=leaking_inputs,
        horizon_end_times=safe_boundary.horizon_end_times,
        purged_train_cutoff=safe_boundary.purged_train_cutoff,
    )
    with pytest.raises(ValueError, match="factual SSL input"):
        masked_dynamic_ssl_loss(
            forecasts,
            ssl_targets,
            ssl_mask,
            leaking_input_boundary,
        )
    with pytest.raises(ValueError, match="Contrastive input end"):
        causal_patch_contrastive_loss(
            contrastive,
            contrastive,
            torch.ones((1, 1), dtype=torch.bool),
            leaking_input_boundary,
        )


def test_checkpoint_sha_sidecar_is_consumed_before_strict_load(tmp_path: Path) -> None:
    """Otkloniaet podmenennyi checkpoint do torch deserializacii."""
    _, model = _model()
    checkpoint_path = tmp_path / "model.pt"
    sidecar_path = tmp_path / "model.pt.sha256"
    torch.save({"model_state_dict": model.state_dict()}, checkpoint_path)
    expected = sha256(checkpoint_path.read_bytes()).hexdigest()
    sidecar_path.write_text(expected + "\n", encoding="utf-8-sig")
    restored_config, restored = _model()
    assert restored_config.model == model.config
    assert load_v8_checkpoint_verified(restored, checkpoint_path, sidecar_path) == expected
    checkpoint_path.write_bytes(checkpoint_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        load_v8_checkpoint_verified(restored, checkpoint_path, sidecar_path)
