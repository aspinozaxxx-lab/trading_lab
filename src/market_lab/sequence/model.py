"""Causal temporal convolutional network dlya vnutridnevnyh targetov."""

from __future__ import annotations

from typing import Any

import torch
from torch import nn
from torch.nn import functional as functional

from market_lab.sequence.config import SequenceModelConfig


class CausalConv1d(nn.Conv1d):
    """Delaet levyi padding, chtoby vyhod ne videl budushchie shagi."""

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        """Primenaet tol'ko levyi padding i standartnuyu svertku."""
        left_padding = (self.kernel_size[0] - 1) * self.dilation[0]
        return super().forward(functional.pad(inputs, (left_padding, 0)))


class TemporalResidualBlock(nn.Module):
    """Dve causal-svertki s normalizaciei, GELU i residual-svyaz'yu."""

    def __init__(self, channels: int, kernel_size: int, dilation: int, dropout: float) -> None:
        """Sozdaet odin residual-blok zadannogo masshtaba."""
        super().__init__()
        self.conv_first = CausalConv1d(
            channels,
            channels,
            kernel_size,
            dilation=dilation,
        )
        self.conv_second = CausalConv1d(
            channels,
            channels,
            kernel_size,
            dilation=dilation,
        )
        self.norm_first = nn.GroupNorm(1, channels)
        self.norm_second = nn.GroupNorm(1, channels)
        self.dropout = nn.Dropout(dropout)
        self.activation = nn.GELU()

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        """Vychislyaet residualnoe preobrazovanie posledovatel'nosti."""
        hidden = self.activation(self.norm_first(self.conv_first(inputs)))
        hidden = self.dropout(hidden)
        hidden = self.norm_second(self.conv_second(hidden))
        return self.activation(inputs + self.dropout(hidden))


class CausalTCN(nn.Module):
    """Obshchaya dlya vseh tickerov TCN s regression i direction-golovami."""

    def __init__(self, input_features: int, config: SequenceModelConfig) -> None:
        """Stroit input-proekciyu, dilated-bloki i dve golovy."""
        super().__init__()
        self.input_projection = nn.Conv1d(input_features, config.channels, kernel_size=1)
        self.blocks = nn.ModuleList(
            TemporalResidualBlock(
                channels=config.channels,
                kernel_size=config.kernel_size,
                dilation=2**block,
                dropout=config.dropout,
            )
            for block in range(config.blocks)
        )
        self.final_norm = nn.LayerNorm(config.channels)
        self.regression_head = nn.Sequential(
            nn.Linear(config.channels, config.channels // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.channels // 2, 1),
        )
        self.direction_head = nn.Sequential(
            nn.Linear(config.channels, config.channels // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.channels // 2, 1),
        )

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Vozvrashchaet masshtabirovannuyu dohodnost' i direction-logit."""
        hidden = self.input_projection(inputs.transpose(1, 2))
        for block in self.blocks:
            hidden = block(hidden)
        summary = self.final_norm(hidden[:, :, -1])
        regression = self.regression_head(summary).squeeze(-1)
        direction = self.direction_head(summary).squeeze(-1)
        return regression, direction


def build_causal_tcn(input_features: int, config: SequenceModelConfig) -> CausalTCN:
    """Sozdaet model' bez skrytoi zavisimosti ot chisla instrumentov."""
    return CausalTCN(input_features=input_features, config=config)


def model_architecture(model: CausalTCN, config: SequenceModelConfig) -> dict[str, Any]:
    """Opisivaet arhitekturu, receptive field i chislo obuchaemyh vesov."""
    parameters = sum(parameter.numel() for parameter in model.parameters())
    trainable = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    receptive_field = 1 + 2 * (config.kernel_size - 1) * sum(
        2**block for block in range(config.blocks)
    )
    return {
        "model_type": "shared causal temporal convolutional neural network",
        "neural_network": True,
        "input_layout": "batch x configured historical 10-minute bars x features",
        "channels": config.channels,
        "residual_blocks": config.blocks,
        "kernel_size": config.kernel_size,
        "dilations": [2**block for block in range(config.blocks)],
        "receptive_field_bars": receptive_field,
        "heads": ["scaled forward return", "positive-return logit"],
        "parameter_count": parameters,
        "trainable_parameter_count": trainable,
    }
