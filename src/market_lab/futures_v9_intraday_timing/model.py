"""Small shared GRU with an optional masked cross-asset attention block."""

from __future__ import annotations

from typing import Literal

import torch
from torch import nn
from torch.nn import functional as F


class TimingGRU(nn.Module):
    """Encode each asset causally, then optionally exchange same-cutoff state."""

    def __init__(
        self,
        *,
        input_size: int,
        hidden_size: int = 32,
        asset_embedding_size: int = 8,
        attention_heads: int = 2,
        variant: Literal["attention", "independent"],
    ) -> None:
        super().__init__()
        self.variant = variant
        self.asset_embedding = nn.Embedding(4, asset_embedding_size)
        self.gru = nn.GRU(
            input_size + asset_embedding_size,
            hidden_size,
            num_layers=1,
            batch_first=True,
        )
        if variant == "attention":
            self.attention = nn.MultiheadAttention(
                hidden_size,
                attention_heads,
                dropout=0.0,
                batch_first=True,
            )
            self.attention_norm = nn.LayerNorm(hidden_size)
        else:
            self.attention = None
            self.attention_norm = None
        self.value_head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.SiLU(),
            nn.Linear(hidden_size, 6),
        )
        self.uncertainty_head = nn.Sequential(
            nn.Linear(hidden_size, 16),
            nn.SiLU(),
            nn.Linear(16, 1),
        )

    def forward(
        self,
        inputs: torch.Tensor,
        asset_valid: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Return six scaled action values and one positive uncertainty per asset."""
        batch, length, assets, _channels = inputs.shape
        ids = torch.arange(assets, device=inputs.device)
        embedding = self.asset_embedding(ids)[None, None].expand(batch, length, -1, -1)
        joined = torch.cat([inputs, embedding], dim=-1)
        joined = joined.permute(0, 2, 1, 3).reshape(batch * assets, length, -1)
        _sequence, hidden = self.gru(joined)
        state = hidden[-1].reshape(batch, assets, -1)
        if self.attention is not None and self.attention_norm is not None:
            attended, _weights = self.attention(
                state,
                state,
                state,
                key_padding_mask=~asset_valid,
                need_weights=False,
            )
            state = self.attention_norm(state + attended)
        values = self.value_head(state)
        uncertainty = F.softplus(self.uncertainty_head(state)) + 1e-4
        return values, uncertainty


__all__ = ["TimingGRU"]
