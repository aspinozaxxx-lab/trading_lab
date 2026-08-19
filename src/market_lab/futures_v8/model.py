"""Causal patch-state-space set' dlia robustnogo futures-v8 residual alpha."""

from __future__ import annotations

import random
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.nn import functional as functional

from market_lab.futures_v8.config import (
    V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT,
    V8ModelConfig,
)


class CausalPatchStateSpaceBlock(nn.Module):
    """Soedinyaet po-shagovoe state-space sostoyanie i causal patch attention."""

    def __init__(
        self,
        width: int,
        attention_heads: int,
        feedforward_multiplier: int,
        dropout: float,
    ) -> None:
        """Stroit odin strictly-causal patch block bez future key/value."""
        super().__init__()
        hidden_width = width * feedforward_multiplier
        self.state_norm = nn.LayerNorm(width)
        self.state_in = nn.Linear(width, width * 2)
        self.state_out = nn.Linear(width, width)
        self.attention_norm = nn.LayerNorm(width)
        self.attention = nn.MultiheadAttention(
            embed_dim=width,
            num_heads=attention_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.feedforward_norm = nn.LayerNorm(width)
        self.feedforward = nn.Sequential(
            nn.Linear(width, hidden_width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_width, width),
        )
        self.dropout = nn.Dropout(dropout)

    def _state_space(self, inputs: torch.Tensor, patch_mask: torch.Tensor) -> torch.Tensor:
        """Obnovliaet state sleva napravo; missing patch ne meniaet ni state, ni prefix."""
        normalized = self.state_norm(inputs)
        candidate, decay_logits = self.state_in(normalized).chunk(2, dim=-1)
        decay = torch.sigmoid(decay_logits)
        state = torch.zeros_like(candidate[:, 0])
        states: list[torch.Tensor] = []
        for step in range(candidate.shape[1]):
            proposal = torch.tanh(candidate[:, step])
            updated = decay[:, step] * state + (1.0 - decay[:, step]) * proposal
            current_valid = patch_mask[:, step, None]
            state = torch.where(current_valid, updated, state)
            states.append(state * current_valid.to(state.dtype))
        return self.state_out(torch.stack(states, dim=1))

    def forward(self, inputs: torch.Tensor, patch_mask: torch.Tensor) -> torch.Tensor:
        """Kodiruet valid patchi; fully missing patch ne yavliaetsia key/value/query."""
        if inputs.ndim != 3 or patch_mask.shape != inputs.shape[:2]:
            raise ValueError("Patch block prinimaet [batch, patches, width] i patch_mask")
        sequence_length = inputs.shape[1]
        causal_mask = torch.ones(
            (sequence_length, sequence_length),
            dtype=torch.bool,
            device=inputs.device,
        ).triu(diagonal=1)
        mask_float = patch_mask[:, :, None].to(inputs.dtype)
        state_hidden = (
            inputs + self.dropout(self._state_space(inputs, patch_mask)) * mask_float
        ) * mask_float
        safe_patch_mask = patch_mask.clone()
        empty_rows = ~safe_patch_mask.any(dim=1)
        safe_patch_mask[empty_rows, 0] = True
        attention_input = self.attention_norm(state_hidden)
        attended, _ = self.attention(
            attention_input,
            attention_input,
            attention_input,
            attn_mask=causal_mask,
            key_padding_mask=~safe_patch_mask,
            need_weights=False,
        )
        attended_hidden = (state_hidden + self.dropout(attended)) * mask_float
        feedforward = self.feedforward(self.feedforward_norm(attended_hidden))
        return (attended_hidden + self.dropout(feedforward)) * mask_float


class SameTimestampAssetAttention(nn.Module):
    """Delaet equivariant cross-asset obmen tol'ko v odin decision moment."""

    def __init__(
        self,
        width: int,
        attention_heads: int,
        feedforward_multiplier: int,
        dropout: float,
    ) -> None:
        """Stroit masked attention bez ticker embedding ili asset position."""
        super().__init__()
        hidden_width = width * feedforward_multiplier
        self.attention_norm = nn.LayerNorm(width)
        self.attention = nn.MultiheadAttention(
            embed_dim=width,
            num_heads=attention_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.feedforward_norm = nn.LayerNorm(width)
        self.feedforward = nn.Sequential(
            nn.Linear(width, hidden_width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_width, width),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, inputs: torch.Tensor, asset_mask: torch.Tensor) -> torch.Tensor:
        """Primeniaet attention k [batch, assets, width] s fail-closed maskoi."""
        if inputs.ndim != 3:
            raise ValueError("Asset attention prinimaet [batch, assets, width]")
        if asset_mask.shape != inputs.shape[:2]:
            raise ValueError("asset_mask imeet nevernuiu formu")
        if (~asset_mask).all(dim=1).any():
            raise ValueError("Sample bez valid activa ne dopuskaetsia")
        normalized = self.attention_norm(inputs)
        attended, _ = self.attention(
            normalized,
            normalized,
            normalized,
            key_padding_mask=~asset_mask,
            need_weights=False,
        )
        hidden = inputs + self.dropout(attended)
        hidden = hidden + self.dropout(self.feedforward(self.feedforward_norm(hidden)))
        return hidden * asset_mask[:, :, None].to(hidden.dtype)


class ResidualRegimeExpert(nn.Module):
    """Predskazyvaet location, scale i otdel'nyi direction logit odnogo regime."""

    def __init__(self, width: int, dropout: float) -> None:
        """Stroit maluiu specialist-golovu, ne sviazannuiu s return scale BCE."""
        super().__init__()
        hidden_width = width // 2
        self.body = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, hidden_width),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.return_location = nn.Linear(hidden_width, 1)
        self.return_scale = nn.Linear(hidden_width, 1)
        self.direction_logit = nn.Linear(hidden_width, 1)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Vozvrashchaet three isolated outputs; logit nikogda ne est' return."""
        hidden = self.body(inputs)
        return (
            self.return_location(hidden).squeeze(-1),
            self.return_scale(hidden).squeeze(-1),
            self.direction_logit(hidden).squeeze(-1),
        )


class FactorLocationScaleHead(nn.Module):
    """Predskazyvaet otdel'nye calibrated location i scale common factora."""

    def __init__(self, width: int) -> None:
        """Stroit common-factor golovu bez direction-logit ili residual mixing."""
        super().__init__()
        hidden_width = width // 2
        self.body = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, hidden_width),
            nn.GELU(),
        )
        self.return_location = nn.Linear(hidden_width, 1)
        self.return_scale = nn.Linear(hidden_width, 1)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Vozvrashchaet location i strictly-positive calibrated scale."""
        hidden = self.body(inputs)
        return (
            self.return_location(hidden).squeeze(-1),
            self.return_scale(hidden).squeeze(-1),
        )


@dataclass(frozen=True)
class V8ModelOutput:
    """Razdelyaet calibrated residual alpha, risk i auxiliary direction heads."""

    factor_location: torch.Tensor
    factor_scale: torch.Tensor
    factor_abstain_probability: torch.Tensor
    factor_decision_score: torch.Tensor
    residual_location: torch.Tensor
    return_location: torch.Tensor
    aleatoric_scale: torch.Tensor
    expert_disagreement: torch.Tensor
    total_scale: torch.Tensor
    direction_logit: torch.Tensor
    regime_probabilities: torch.Tensor
    abstain_probability: torch.Tensor
    decision_score: torch.Tensor
    patch_embeddings: torch.Tensor
    ssl_forecasts: torch.Tensor
    contrastive_embedding: torch.Tensor


class CausalPatchStateSpaceRegimeAlphaModel(nn.Module):
    """Ticker-agnostic v8: causal patches, regimes, residual alpha i abstention."""

    def __init__(self, config: V8ModelConfig) -> None:
        """Stroit v8 bez target/input mixing i bez ticker-specific parameters."""
        super().__init__()
        self.config = config
        width = config.width
        self.bar_projection = nn.Linear(len(config.bar_feature_names) + 1, width)
        self.patch_projection = nn.Sequential(
            nn.LayerNorm(config.patch_size_bars * width),
            nn.Linear(config.patch_size_bars * width, width),
        )
        self.temporal_blocks = nn.ModuleList(
            CausalPatchStateSpaceBlock(
                width=width,
                attention_heads=config.attention_heads,
                feedforward_multiplier=config.feedforward_multiplier,
                dropout=config.dropout,
            )
            for _ in range(config.state_space_blocks)
        )
        self.asset_attention = SameTimestampAssetAttention(
            width=width,
            attention_heads=config.attention_heads,
            feedforward_multiplier=config.feedforward_multiplier,
            dropout=config.dropout,
        )
        daily_size = len(config.daily_feature_names)
        self.daily_projection = nn.Sequential(
            nn.Linear(daily_size * 2, width),
            nn.GELU(),
            nn.Linear(width, width),
        )
        self.daily_gate = nn.Linear(width * 2, width)
        self.regime_router = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, width // 2),
            nn.GELU(),
            nn.Linear(width // 2, config.regime_experts),
        )
        self.factor_head = FactorLocationScaleHead(width)
        self.residual_experts = nn.ModuleList(
            ResidualRegimeExpert(width, config.dropout)
            for _ in range(config.regime_experts)
        )
        self.ssl_head = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, width),
            nn.GELU(),
            nn.Linear(width, len(config.ssl_horizons) * 2),
        )
        self.contrastive_head = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, width),
            nn.GELU(),
            nn.Linear(width, config.contrastive_projection_width),
        )
        self._supervised_encoder_frozen = False

    def _set_frozen_encoder_eval(self) -> None:
        """Derzhit SSL encoder v eval mode, dazhe esli outer model pereshel v train."""
        for module in (
            self.bar_projection,
            self.patch_projection,
            self.temporal_blocks,
            self.asset_attention,
        ):
            module.eval()

    def train(self, mode: bool = True) -> CausalPatchStateSpaceRegimeAlphaModel:
        """Sohraniaet frozen encoder bez dropout posle standard ``model.train()``."""
        super().train(mode)
        if self._supervised_encoder_frozen:
            self._set_frozen_encoder_eval()
        return self

    def _validate_inputs(
        self,
        intraday: torch.Tensor,
        intraday_mask: torch.Tensor,
        daily_context: torch.Tensor,
        daily_mask: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Proveryaet input i strogo vyvodit effective mask iz factual 10m bars."""
        if intraday.ndim != 4:
            raise ValueError("intraday dolzhen imet' [batch, assets, bars, features]")
        batch_size, asset_count, bars, features = intraday.shape
        if bars != self.config.sequence_bars:
            raise ValueError("Nevernaia dlina 10m okna")
        if features != len(self.config.bar_feature_names):
            raise ValueError("Nevernoe chislo 10m features")
        if intraday_mask.shape != (batch_size, asset_count, bars):
            raise ValueError("intraday_mask imeet nevernuiu formu")
        daily_shape = (batch_size, asset_count, len(self.config.daily_feature_names))
        if daily_context.shape != daily_shape or daily_mask.shape != daily_shape:
            raise ValueError("daily_context/daily_mask imeiut nevernuiu formu")
        if asset_mask.shape != (batch_size, asset_count):
            raise ValueError("asset_mask imeet nevernuiu formu")
        if (
            intraday_mask.dtype != torch.bool
            or daily_mask.dtype != torch.bool
            or asset_mask.dtype != torch.bool
        ):
            raise ValueError("Vse availability maski dolzhny byt' torch.bool")
        has_intraday = intraday_mask.any(dim=-1)
        effective_asset_mask = asset_mask & has_intraday
        if (~effective_asset_mask).all(dim=1).any():
            raise ValueError("Kazhdii sample trebuet factual intraday bar hotia by odnomu assetu")
        if not torch.isfinite(intraday[intraday_mask]).all():
            raise ValueError("Factual intraday observations dolzhny byt' finite")
        effective_daily_mask = daily_mask & effective_asset_mask[..., None]
        if not torch.isfinite(daily_context[effective_daily_mask]).all():
            raise ValueError("Factual daily observations dolzhny byt' finite")
        return effective_asset_mask

    def _patch_valid(self, intraday_mask: torch.Tensor) -> torch.Tensor:
        """Szhimaet 10m availability v patch availability bez imputacii missing patcha."""
        return intraday_mask.reshape(
            *intraday_mask.shape[:2],
            self.config.sequence_bars // self.config.patch_size_bars,
            self.config.patch_size_bars,
        ).any(dim=-1)

    def encode_patches(
        self,
        intraday: torch.Tensor,
        intraday_mask: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Kodiruet exact causal patch-prefixy; token opisivaet tol'ko svoj 8-bar end."""
        if intraday.ndim != 4 or intraday_mask.shape != intraday.shape[:3]:
            raise ValueError("Intraday/mask imeiut nevernuiu formu")
        clean = torch.where(intraday_mask[..., None], intraday, torch.zeros_like(intraday))
        valid_channel = intraday_mask.to(intraday.dtype)[..., None]
        projected = self.bar_projection(torch.cat((clean, valid_channel), dim=-1))
        batch_size, asset_count, _, width = projected.shape
        patch_count = self.config.sequence_bars // self.config.patch_size_bars
        patches = projected.reshape(
            batch_size,
            asset_count,
            patch_count,
            self.config.patch_size_bars * width,
        )
        patch_valid = self._patch_valid(intraday_mask)
        hidden = self.patch_projection(patches) * patch_valid[..., None].to(projected.dtype)
        hidden = hidden.reshape(batch_size * asset_count, patch_count, width)
        flattened_patch_mask = patch_valid.reshape(batch_size * asset_count, patch_count)
        for block in self.temporal_blocks:
            hidden = block(hidden, flattened_patch_mask)
        hidden = hidden.reshape(batch_size, asset_count, patch_count, width)
        return hidden * asset_mask[:, :, None, None].to(hidden.dtype)

    @staticmethod
    def _last_valid_patch(
        patch_embeddings: torch.Tensor,
        patch_valid: torch.Tensor,
    ) -> torch.Tensor:
        """Vybiraet poslednii factual patch kazhdogo asseta, ne fixed final padding."""
        patch_indices = torch.arange(
            patch_embeddings.shape[2],
            device=patch_embeddings.device,
        ).reshape(1, 1, -1)
        last_index = torch.where(patch_valid, patch_indices, 0).max(dim=2).values
        return patch_embeddings.gather(
            dim=2,
            index=last_index[:, :, None, None].expand(-1, -1, 1, patch_embeddings.shape[-1]),
        ).squeeze(2)

    def _condition_daily(
        self,
        decision_embedding: torch.Tensor,
        daily_context: torch.Tensor,
        daily_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Dobavliaet PIT daily kanaly tol'ko tam, gde mask razreshaet availability."""
        clean_daily = torch.where(daily_mask, daily_context, torch.zeros_like(daily_context))
        daily_input = torch.cat((clean_daily, daily_mask.to(daily_context.dtype)), dim=-1)
        daily_embedding = self.daily_projection(daily_input)
        gate_input = torch.cat((decision_embedding, daily_embedding), dim=-1)
        gate = torch.sigmoid(self.daily_gate(gate_input))
        return decision_embedding + gate * daily_embedding

    @staticmethod
    def _masked_mean(inputs: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """Schitaet equivariant pooled global state bez zapolneniia missing assets."""
        weights = mask[:, :, None].to(inputs.dtype)
        denominator = weights.sum(dim=1).clamp_min(1.0)
        return (inputs * weights).sum(dim=1) / denominator

    def forward(
        self,
        intraday: torch.Tensor,
        intraday_mask: torch.Tensor,
        daily_context: torch.Tensor,
        daily_mask: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> V8ModelOutput:
        """Vozvrashchaet risk-scaled residual alpha; direction logit ne est' return."""
        effective_asset_mask = self._validate_inputs(
            intraday,
            intraday_mask,
            daily_context,
            daily_mask,
            asset_mask,
        )
        patch_valid = self._patch_valid(intraday_mask)
        patch_embeddings = self.encode_patches(
            intraday,
            intraday_mask,
            effective_asset_mask,
        )
        latest_patch_embedding = self._last_valid_patch(patch_embeddings, patch_valid)
        decision_embedding = self.asset_attention(latest_patch_embedding, effective_asset_mask)
        effective_daily_mask = daily_mask & effective_asset_mask[..., None]
        conditioned = self._condition_daily(
            decision_embedding,
            daily_context,
            effective_daily_mask,
        ) * effective_asset_mask[..., None].to(decision_embedding.dtype)
        global_embedding = self._masked_mean(conditioned, effective_asset_mask)
        regime_probabilities = torch.softmax(self.regime_router(global_embedding), dim=-1)
        factor_location, factor_raw_scale = self.factor_head(global_embedding)
        factor_scale = functional.softplus(factor_raw_scale).clamp_min(
            self.config.scale_floor_iqr
        )
        expert_outputs = tuple(expert(conditioned) for expert in self.residual_experts)
        expert_locations = torch.stack([output[0] for output in expert_outputs], dim=-1)
        expert_location_mean = (
            expert_locations
            * effective_asset_mask[:, :, None].to(expert_locations.dtype)
        ).sum(dim=1, keepdim=True) / effective_asset_mask.sum(
            dim=1,
            keepdim=True,
        ).clamp_min(1).to(expert_locations.dtype)[:, :, None]
        expert_locations = expert_locations - expert_location_mean
        expert_scales = functional.softplus(
            torch.stack([output[1] for output in expert_outputs], dim=-1)
        ).clamp_min(self.config.scale_floor_iqr)
        expert_direction_logits = torch.stack([output[2] for output in expert_outputs], dim=-1)
        regime_weights = regime_probabilities[:, None, :]
        residual_location = (expert_locations * regime_weights).sum(dim=-1)
        aleatoric_scale = torch.sqrt(
            (expert_scales.square() * regime_weights).sum(dim=-1).clamp_min(1e-8)
        )
        expert_disagreement = torch.sqrt(
            (
                (expert_locations - residual_location[..., None]).square() * regime_weights
            ).sum(dim=-1).clamp_min(0.0)
        )
        total_scale = torch.sqrt(
            (aleatoric_scale.square() + expert_disagreement.square()).clamp_min(1e-8)
        )
        direction_logit = (expert_direction_logits * regime_weights).sum(dim=-1)
        factor_signal_to_noise = factor_location / factor_scale
        factor_abstain_probability = torch.sigmoid(
            (self.config.abstain_z_threshold - factor_signal_to_noise.abs())
            / self.config.abstain_temperature
        )
        factor_decision_score = torch.tanh(factor_signal_to_noise) * (
            1.0 - factor_abstain_probability
        )
        signal_to_noise = residual_location / total_scale
        abstain_probability = torch.sigmoid(
            (self.config.abstain_z_threshold - signal_to_noise.abs())
            / self.config.abstain_temperature
        )
        decision_score = torch.tanh(signal_to_noise) * (1.0 - abstain_probability)
        return_location = factor_location[:, None] + residual_location
        ssl_forecasts = self.ssl_head(patch_embeddings).reshape(
            *patch_embeddings.shape[:-1], len(self.config.ssl_horizons), 2
        ) * patch_valid[:, :, :, None, None].to(patch_embeddings.dtype)
        contrastive_embedding = functional.normalize(
            self.contrastive_head(decision_embedding),
            p=2.0,
            dim=-1,
        )
        valid = effective_asset_mask.to(return_location.dtype)
        return V8ModelOutput(
            factor_location=factor_location,
            factor_scale=factor_scale,
            factor_abstain_probability=factor_abstain_probability,
            factor_decision_score=factor_decision_score,
            residual_location=residual_location * valid,
            return_location=return_location * valid,
            aleatoric_scale=aleatoric_scale * valid,
            expert_disagreement=expert_disagreement * valid,
            total_scale=total_scale * valid,
            direction_logit=direction_logit * valid,
            regime_probabilities=regime_probabilities,
            abstain_probability=abstain_probability * valid,
            decision_score=decision_score * valid,
            patch_embeddings=patch_embeddings,
            ssl_forecasts=ssl_forecasts,
            contrastive_embedding=contrastive_embedding * valid[:, :, None],
        )


def set_v8_determinism(seed: int) -> None:
    """Fiksiruet Python, NumPy i torch random state dlia povtoriaemogo build."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def configure_v8_supervised_finetuning(
    model: CausalPatchStateSpaceRegimeAlphaModel,
) -> None:
    """Zamorazhivaet encoder i attention; supervised fit men'she 200k parametrov."""
    for parameter in model.parameters():
        parameter.requires_grad = False
    trainable_modules: tuple[nn.Module, ...] = (
        model.daily_projection,
        model.daily_gate,
        model.regime_router,
        model.factor_head,
        model.residual_experts,
    )
    for module in trainable_modules:
        for parameter in module.parameters():
            parameter.requires_grad = True
    model._supervised_encoder_frozen = True
    model._set_frozen_encoder_eval()
    trainable_count = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    if trainable_count != V8_SUPERVISED_TRAINABLE_PARAMETER_COUNT:
        raise RuntimeError("V8 supervised trainable parameter seal mismatch")


def model_architecture_manifest(
    model: CausalPatchStateSpaceRegimeAlphaModel,
) -> dict[str, Any]:
    """Vozvrashchaet audit parametrizacii i explicit separation return/logit."""
    total = sum(parameter.numel() for parameter in model.parameters())
    trainable = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    return {
        "architecture": model.config.architecture,
        "input_layout": "batch x assets x 512 causal 10m bars x 12 features",
        "patch_size_bars": model.config.patch_size_bars,
        "patch_count": model.config.sequence_bars // model.config.patch_size_bars,
        "temporal_core": "causal recurrent state-space plus causal patch attention",
        "cross_asset_attention": "same timestamp only",
        "ticker_embeddings": False,
        "regime_specialists": ("normal", "trend", "crash"),
        "return_head": "factor_plus_cross_asset_residual_location",
        "factor_sleeve": "independent_location_scale_snr_with_abstention",
        "direction_head": "auxiliary_only_never_converted_to_return",
        "uncertainty": "aleatoric_plus_expert_disagreement_abstention",
        "ssl": "dynamic_horizon_forecast_and_causal_contrastive",
        "parameter_count": total,
        "supervised_trainable_parameter_count": trainable,
    }


def _file_sha256(path: Path) -> str:
    """Schitaet byte-level SHA-256 dlia checkpoint do deserializacii."""
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_v8_checkpoint_verified(
    model: CausalPatchStateSpaceRegimeAlphaModel,
    checkpoint_path: Path,
    sha256_sidecar_path: Path,
    *,
    map_location: str | torch.device = "cpu",
) -> str:
    """Proveriaet consumed sidecar SHA i tol'ko zatem strict zagruzhaet vesa."""
    checkpoint = Path(checkpoint_path).resolve()
    sidecar = Path(sha256_sidecar_path).resolve()
    if not checkpoint.is_file() or not sidecar.is_file():
        raise FileNotFoundError("Checkpoint i ego SHA-256 sidecar dolzhny sushchestvovat'")
    expected = sidecar.read_text(encoding="utf-8-sig").strip().split()[0].lower()
    if len(expected) != 64 or any(symbol not in "0123456789abcdef" for symbol in expected):
        raise ValueError("Checkpoint sidecar ne soderzhit valid SHA-256")
    actual = _file_sha256(checkpoint)
    if actual != expected:
        raise ValueError("Checkpoint SHA-256 ne sovpadaet s consumed sidecar")
    payload = torch.load(checkpoint, map_location=map_location, weights_only=True)
    state_dict = payload.get("model_state_dict", payload) if isinstance(payload, dict) else payload
    if not isinstance(state_dict, dict):
        raise ValueError("Checkpoint ne soderzhit model state_dict")
    model.load_state_dict(state_dict, strict=True)
    return actual


__all__ = [
    "CausalPatchStateSpaceRegimeAlphaModel",
    "V8ModelOutput",
    "configure_v8_supervised_finetuning",
    "load_v8_checkpoint_verified",
    "model_architecture_manifest",
    "set_v8_determinism",
]
