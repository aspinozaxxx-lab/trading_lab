"""Causal ticker-agnostic multi-resolution network futures-v7."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.nn import functional as functional

from market_lab.futures_v7.config import V7ModelConfig


class CausalDepthwiseConv1d(nn.Conv1d):
    """Primenaet depthwise-svertku tol'ko k tekushchemu i proshlym baram."""

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        """Dobavlyaet tol'ko levyi padding bez budushchego kraya."""
        left_padding = (self.kernel_size[0] - 1) * self.dilation[0]
        return super().forward(functional.pad(inputs, (left_padding, 0)))


class MultiScaleTemporalBlock(nn.Module):
    """Sochetaet causal depthwise GLU-mixer i pointwise feed-forward."""

    def __init__(
        self,
        width: int,
        kernel_size: int,
        dilation: int,
        feedforward_multiplier: int,
        dropout: float,
    ) -> None:
        """Stroit odin zapechatannyi dilation-masshtab obshchego encodera."""
        super().__init__()
        hidden_width = width * feedforward_multiplier
        self.temporal_norm = nn.LayerNorm(width)
        self.depthwise = CausalDepthwiseConv1d(
            width,
            width,
            kernel_size=kernel_size,
            dilation=dilation,
            groups=width,
        )
        self.channel_gate = nn.Conv1d(width, width * 2, kernel_size=1)
        self.feedforward_norm = nn.LayerNorm(width)
        self.feedforward = nn.Sequential(
            nn.Linear(width, hidden_width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_width, width),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        """Kodiruet [batch*assets, bars, width] bez pravogo padding."""
        normalized = self.temporal_norm(inputs).transpose(1, 2)
        mixed = self.channel_gate(self.depthwise(normalized))
        gated = functional.glu(mixed, dim=1).transpose(1, 2)
        temporal = inputs + self.dropout(gated)
        feedforward = self.feedforward(self.feedforward_norm(temporal))
        return temporal + self.dropout(feedforward)


class SameTimestampAssetAttention(nn.Module):
    """Obmenivaet informaciyu mezhdu aktivami tol'ko v final'nyi decision."""

    def __init__(
        self,
        width: int,
        attention_heads: int,
        feedforward_multiplier: int,
        dropout: float,
    ) -> None:
        """Stroit odin cross-asset blok bez positional ili ticker embeddings."""
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

    def forward(
        self,
        inputs: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Primenaet attention k final'nym embedding odnogo decision timestamp."""
        if inputs.ndim != 3:
            raise ValueError("Asset attention prinimaet tol'ko [batch, assets, width]")
        batch_size, asset_count, _ = inputs.shape
        if asset_mask.shape != (batch_size, asset_count):
            raise ValueError("asset_mask imeet nevernuyu formu")
        if (~asset_mask).all(dim=1).any():
            raise ValueError("Attention ne dopuskaet sample bez aktivov")
        normalized = self.attention_norm(inputs)
        key_padding = ~asset_mask
        attended, _ = self.attention(
            normalized,
            normalized,
            normalized,
            key_padding_mask=key_padding,
            need_weights=False,
        )
        hidden = inputs + self.dropout(attended)
        hidden = hidden + self.dropout(self.feedforward(self.feedforward_norm(hidden)))
        return hidden * asset_mask[:, :, None].to(hidden.dtype)


@dataclass(frozen=True)
class V7ModelOutput:
    """Razdelyaet daily trading-head i SSL-label predictions."""

    daily_return: torch.Tensor
    ssl_return_volatility: torch.Tensor
    encoded_sequence: torch.Tensor


class CausalMultiResolutionFuturesModel(nn.Module):
    """Obshchaya causal-set' bez identifikatorov SI/RI/BR/MIX."""

    def __init__(self, config: V7ModelConfig) -> None:
        """Stroit 10m encoder, same-time attention, PIT-gate i dve golovy."""
        super().__init__()
        self.config = config
        width = config.width
        self.input_projection = nn.Linear(len(config.bar_feature_names) + 1, width)
        self.temporal_blocks = nn.ModuleList(
            MultiScaleTemporalBlock(
                width=width,
                kernel_size=config.kernel_size,
                dilation=dilation,
                feedforward_multiplier=config.feedforward_multiplier,
                dropout=config.dropout,
            )
            for dilation in config.dilations
        )
        self.asset_attention = SameTimestampAssetAttention(
            width=width,
            attention_heads=config.attention_heads,
            feedforward_multiplier=config.feedforward_multiplier,
            dropout=config.dropout,
        )
        daily_features = len(config.daily_feature_names)
        self.daily_projection = nn.Sequential(
            nn.Linear(daily_features * 2, width),
            nn.GELU(),
            nn.Linear(width, width),
        )
        self.daily_gate = nn.Linear(width * 2, width)
        head_width = width // 2
        self.daily_head = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, head_width),
            nn.GELU(),
            nn.Linear(head_width, 1),
        )
        self.ssl_head = nn.Sequential(
            nn.LayerNorm(width),
            nn.Linear(width, head_width),
            nn.GELU(),
            nn.Linear(head_width, len(config.ssl_horizons) * 2),
        )

    def _validate_inputs(
        self,
        intraday: torch.Tensor,
        intraday_mask: torch.Tensor,
        daily_context: torch.Tensor,
        daily_mask: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> None:
        """Proveryaet vse tensor-formy pered GPU-vychisleniem."""
        if intraday.ndim != 4:
            raise ValueError("intraday dolzhen imet' formu [batch, assets, bars, features]")
        batch_size, asset_count, bar_count, feature_count = intraday.shape
        if bar_count != self.config.sequence_bars:
            raise ValueError("Nevernaya dlina 10m okna")
        if feature_count != len(self.config.bar_feature_names):
            raise ValueError("Nevernoe chislo 10m priznakov")
        if intraday_mask.shape != (batch_size, asset_count, bar_count):
            raise ValueError("intraday_mask imeet nevernuyu formu")
        expected_daily = (
            batch_size,
            asset_count,
            len(self.config.daily_feature_names),
        )
        if daily_context.shape != expected_daily or daily_mask.shape != expected_daily:
            raise ValueError("daily context/mask imeet nevernuyu formu")
        if asset_mask.shape != (batch_size, asset_count):
            raise ValueError("asset_mask imeet nevernuyu formu")

    def encode_intraday(
        self,
        intraday: torch.Tensor,
        intraday_mask: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Kodiruet vse bar-prefixy dlya testiruemogo causal SSL-prediction."""
        clean = torch.where(intraday_mask[..., None], intraday, torch.zeros_like(intraday))
        valid_channel = intraday_mask.to(intraday.dtype)[..., None]
        projected = self.input_projection(torch.cat((clean, valid_channel), dim=-1))
        batch_size, asset_count, bar_count, width = projected.shape
        hidden = projected.reshape(batch_size * asset_count, bar_count, width)
        for block in self.temporal_blocks:
            hidden = block(hidden)
        hidden = hidden.reshape(batch_size, asset_count, bar_count, width)
        return hidden * asset_mask[:, :, None, None].to(hidden.dtype)

    def _condition_daily(
        self,
        encoded_decision: torch.Tensor,
        daily_context: torch.Tensor,
        daily_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Primenyaet mask-aware gate k carry/OI/CBR/CFTC snapshot."""
        clean_daily = torch.where(daily_mask, daily_context, torch.zeros_like(daily_context))
        condition_input = torch.cat((clean_daily, daily_mask.to(daily_context.dtype)), dim=-1)
        condition = self.daily_projection(condition_input)
        gate = torch.sigmoid(self.daily_gate(torch.cat((encoded_decision, condition), dim=-1)))
        return encoded_decision + gate * condition

    def forward(
        self,
        intraday: torch.Tensor,
        intraday_mask: torch.Tensor,
        daily_context: torch.Tensor,
        daily_mask: torch.Tensor,
        asset_mask: torch.Tensor,
    ) -> V7ModelOutput:
        """Predskazyvaet daily return i SSL return/vol iz causal-prefixov."""
        self._validate_inputs(
            intraday,
            intraday_mask,
            daily_context,
            daily_mask,
            asset_mask,
        )
        encoded = self.encode_intraday(intraday, intraday_mask, asset_mask)
        decision_encoded = self.asset_attention(encoded[:, :, -1], asset_mask)
        conditioned = self._condition_daily(decision_encoded, daily_context, daily_mask)
        daily_return = self.daily_head(conditioned).squeeze(-1)
        daily_return = daily_return * asset_mask.to(daily_return.dtype)
        ssl_raw = self.ssl_head(encoded).reshape(
            *encoded.shape[:-1],
            len(self.config.ssl_horizons),
            2,
        )
        ssl_return = ssl_raw[..., 0]
        ssl_volatility = functional.softplus(ssl_raw[..., 1])
        ssl_prediction = torch.stack((ssl_return, ssl_volatility), dim=-1)
        ssl_prediction = ssl_prediction * asset_mask[:, :, None, None, None].to(
            ssl_prediction.dtype
        )
        return V7ModelOutput(
            daily_return=daily_return,
            ssl_return_volatility=ssl_prediction,
            encoded_sequence=encoded,
        )


def set_v7_determinism(seed: int) -> None:
    """Fiksiruet Python, NumPy, CPU/CUDA torch i deterministic kernels."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def configure_supervised_finetuning(
    model: CausalMultiResolutionFuturesModel,
    freeze_first_temporal_blocks: int,
) -> None:
    """Ostavlyaet trainable poslednie bloki, conditioning, attention i maluyu golovu."""
    if not 0 <= freeze_first_temporal_blocks <= len(model.temporal_blocks):
        raise ValueError("Nevernoe chislo zamerzshih temporal blocks")
    for parameter in model.parameters():
        parameter.requires_grad = False
    trainable_modules: list[nn.Module] = [
        *model.temporal_blocks[freeze_first_temporal_blocks:],
        model.asset_attention,
        model.daily_projection,
        model.daily_gate,
        model.daily_head,
    ]
    for module in trainable_modules:
        for parameter in module.parameters():
            parameter.requires_grad = True


def masked_ssl_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    target_mask: torch.Tensor,
) -> torch.Tensor:
    """Schitaet Huber SSL-loss tol'ko po dostupnym future horizon labels."""
    if predictions.shape != targets.shape or predictions.shape[:-1] != target_mask.shape:
        raise ValueError("SSL prediction/target/mask shapes ne sovpadayut")
    expanded_mask = target_mask[..., None].expand_as(predictions)
    if not expanded_mask.any():
        return predictions.sum() * 0.0
    return functional.smooth_l1_loss(predictions[expanded_mask], targets[expanded_mask])


def masked_supervised_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    target_mask: torch.Tensor,
) -> torch.Tensor:
    """Sochetaet robust return-regression i direction loss na valid targetah."""
    if predictions.shape != targets.shape or target_mask.shape != targets.shape:
        raise ValueError("Supervised prediction/target/mask shapes ne sovpadayut")
    if not target_mask.any():
        return predictions.sum() * 0.0
    predicted = predictions[target_mask]
    actual = targets[target_mask]
    regression = functional.smooth_l1_loss(predicted, actual)
    direction = functional.binary_cross_entropy_with_logits(predicted, (actual > 0).to(actual))
    return regression + 0.25 * direction


def model_architecture_manifest(
    model: CausalMultiResolutionFuturesModel,
) -> dict[str, Any]:
    """Vozvrashchaet audit-opisanie i tochnoe chislo vesov bez ticker embedding."""
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    trainable_count = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    receptive_field = 1 + (model.config.kernel_size - 1) * sum(model.config.dilations)
    return {
        "architecture": model.config.architecture,
        "input_layout": "batch x assets x 512 causal 10m bars x 12 features",
        "shared_ticker_agnostic_encoder": True,
        "ticker_embeddings": False,
        "width": model.config.width,
        "temporal_blocks": model.config.temporal_blocks,
        "dilations": list(model.config.dilations),
        "receptive_field_bars": receptive_field,
        "cross_asset_attention": "same timestamp only",
        "daily_conditioning": model.config.daily_conditioning,
        "ssl_horizons_bars": list(model.config.ssl_horizons),
        "daily_target": model.config.prediction_target,
        "parameter_count": parameter_count,
        "trainable_parameter_count": trainable_count,
    }
