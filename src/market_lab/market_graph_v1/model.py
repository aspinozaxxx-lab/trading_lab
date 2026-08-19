"""Fixed causal TCN plus masked cross-asset attention for market-graph-v1."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import torch
from torch import nn
from torch.nn import functional as F


class CausalConv1d(nn.Conv1d):
    """One-dimensional convolution with left-only padding."""

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        padding = (self.kernel_size[0] - 1) * self.dilation[0]
        return super().forward(F.pad(inputs, (padding, 0)))


class TemporalBlock(nn.Module):
    """Two-convolution causal residual block."""

    def __init__(self, channels: int, kernel_size: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.first = CausalConv1d(channels, channels, kernel_size, dilation=dilation)
        self.second = CausalConv1d(channels, channels, kernel_size, dilation=dilation)
        self.first_norm = nn.GroupNorm(1, channels)
        self.second_norm = nn.GroupNorm(1, channels)
        self.dropout = nn.Dropout(dropout)

    def forward(self, inputs: torch.Tensor, history_mask: torch.Tensor) -> torch.Tensor:
        hidden = F.gelu(self.first_norm(self.first(inputs)))
        hidden = self.dropout(hidden)
        hidden = self.second_norm(self.second(hidden))
        output = F.gelu(inputs + self.dropout(hidden))
        return output * history_mask[:, None, :]


class CorrelationAttention(nn.Module):
    """Masked multi-head self-attention with a causal rolling-correlation bias."""

    def __init__(self, hidden: int, heads: int, dropout: float) -> None:
        super().__init__()
        if hidden % heads:
            raise ValueError("hidden dimension must divide evenly across heads")
        self.hidden = hidden
        self.heads = heads
        self.head_dimension = hidden // heads
        self.query = nn.Linear(hidden, hidden)
        self.key = nn.Linear(hidden, hidden)
        self.value = nn.Linear(hidden, hidden)
        self.output = nn.Linear(hidden, hidden)
        self.correlation_strength = nn.Parameter(torch.ones(heads))
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        inputs: torch.Tensor,
        asset_mask: torch.Tensor,
        correlations: torch.Tensor,
    ) -> torch.Tensor:
        batch, assets, _ = inputs.shape

        def heads(projection: nn.Linear) -> torch.Tensor:
            return (
                projection(inputs)
                .view(batch, assets, self.heads, self.head_dimension)
                .transpose(1, 2)
            )

        query = heads(self.query)
        key = heads(self.key)
        value = heads(self.value)
        logits = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(self.head_dimension)
        logits = logits + (
            correlations[:, None, :, :] * self.correlation_strength[None, :, None, None]
        )
        logits = logits.masked_fill(~asset_mask[:, None, None, :], -10_000.0)
        attention = torch.softmax(logits, dim=-1)
        attention = attention * asset_mask[:, None, :, None]
        attended = torch.matmul(self.dropout(attention), value)
        attended = attended.transpose(1, 2).reshape(batch, assets, self.hidden)
        return self.output(attended) * asset_mask[:, :, None]


class GraphBlock(nn.Module):
    """Identical block whose attention path can be disabled for the fixed ablation."""

    def __init__(self, hidden: int, heads: int, dropout: float) -> None:
        super().__init__()
        self.attention_norm = nn.LayerNorm(hidden)
        self.attention = CorrelationAttention(hidden, heads, dropout)
        self.feedforward_norm = nn.LayerNorm(hidden)
        self.feedforward = nn.Sequential(
            nn.Linear(hidden, hidden * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden * 2, hidden),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        inputs: torch.Tensor,
        asset_mask: torch.Tensor,
        correlations: torch.Tensor,
        *,
        use_attention: bool,
    ) -> torch.Tensor:
        hidden = inputs
        if use_attention:
            hidden = hidden + self.attention(self.attention_norm(hidden), asset_mask, correlations)
        hidden = hidden + self.feedforward(self.feedforward_norm(hidden))
        return hidden * asset_mask[:, :, None]


@dataclass(frozen=True, slots=True)
class ModelOutput:
    """Location/scale outputs; direction is auxiliary and never a return score."""

    factor_location: torch.Tensor
    factor_scale: torch.Tensor
    residual_location: torch.Tensor
    residual_scale: torch.Tensor
    direction_logit: torch.Tensor


class MarketGraphModel(nn.Module):
    """Shared temporal encoder operating on every synchronized asset at once."""

    def __init__(
        self,
        *,
        input_features: int,
        assets: int,
        hidden: int = 128,
        temporal_blocks: int = 6,
        graph_layers: int = 4,
        heads: int = 4,
        kernel_size: int = 3,
        dropout: float = 0.10,
        variant: Literal["graph", "no_attention"] = "graph",
    ) -> None:
        super().__init__()
        self.variant = variant
        self.assets = assets
        self.input_projection = nn.Conv1d(input_features, hidden, kernel_size=1)
        self.temporal = nn.ModuleList(
            TemporalBlock(hidden, kernel_size, 2**index, dropout)
            for index in range(temporal_blocks)
        )
        self.temporal_norm = nn.LayerNorm(hidden)
        self.ticker_embedding = nn.Embedding(assets, hidden)
        self.graph = nn.ModuleList(GraphBlock(hidden, heads, dropout) for _ in range(graph_layers))
        half = hidden // 2
        self.factor_location_head = nn.Sequential(
            nn.Linear(hidden, half), nn.GELU(), nn.Linear(half, 1)
        )
        self.factor_scale_head = nn.Sequential(
            nn.Linear(hidden, half), nn.GELU(), nn.Linear(half, 1)
        )
        self.residual_location_head = nn.Sequential(
            nn.Linear(hidden, half), nn.GELU(), nn.Linear(half, 1)
        )
        self.residual_scale_head = nn.Sequential(
            nn.Linear(hidden, half), nn.GELU(), nn.Linear(half, 1)
        )
        self.direction_head = nn.Sequential(nn.Linear(hidden, half), nn.GELU(), nn.Linear(half, 1))

    def forward(
        self,
        inputs: torch.Tensor,
        history_mask: torch.Tensor,
        current_mask: torch.Tensor,
        correlations: torch.Tensor,
    ) -> ModelOutput:
        """Accept [batch, all assets, 128 sessions, features] and explicit masks."""
        batch, assets, history, features = inputs.shape
        if assets != self.assets:
            raise ValueError("model requires the entire sealed asset axis")
        hidden = self.input_projection(
            inputs.reshape(batch * assets, history, features).transpose(1, 2)
        )
        flat_history_mask = history_mask.reshape(batch * assets, history)
        hidden = hidden * flat_history_mask[:, None, :]
        for block in self.temporal:
            hidden = block(hidden, flat_history_mask)
        summary = self.temporal_norm(hidden[:, :, -1]).reshape(batch, assets, -1)
        ticker_ids = torch.arange(assets, device=inputs.device)
        summary = summary + self.ticker_embedding(ticker_ids)[None, :, :]
        summary = summary * current_mask[:, :, None]
        for block in self.graph:
            summary = block(
                summary,
                current_mask,
                correlations,
                use_attention=self.variant == "graph",
            )
        count = current_mask.sum(dim=1, keepdim=True).clamp_min(1)
        pooled = (summary * current_mask[:, :, None]).sum(dim=1) / count
        factor_location = self.factor_location_head(pooled).squeeze(-1)
        factor_scale = F.softplus(self.factor_scale_head(pooled).squeeze(-1)) + 1e-3
        residual_location = self.residual_location_head(summary).squeeze(-1)
        residual_sum = (residual_location * current_mask).sum(dim=1, keepdim=True)
        residual_location = (residual_location - residual_sum / count) * current_mask
        residual_scale = (
            F.softplus(self.residual_scale_head(summary).squeeze(-1)) + 1e-3
        ) * current_mask
        direction = self.direction_head(summary).squeeze(-1) * current_mask
        return ModelOutput(
            factor_location=factor_location,
            factor_scale=factor_scale,
            residual_location=residual_location,
            residual_scale=residual_scale,
            direction_logit=direction,
        )


def parameter_count(model: nn.Module) -> int:
    """Return the number of trainable parameters."""
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
