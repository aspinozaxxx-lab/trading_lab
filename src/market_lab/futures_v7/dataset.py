"""Massivnye kontrakty i SSL-targety causal multi-resolution futures-v7."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from market_lab.futures_v7.config import V7ModelConfig
from market_lab.futures_v7.contracts import DecisionTimingBatch


@dataclass(frozen=True)
class SelfSupervisedTargets:
    """Hranit future-return/vol label i masku, no ne yavlyaetsya vkhodom modeli."""

    values: np.ndarray
    valid: np.ndarray


def build_self_supervised_targets(
    log_price: np.ndarray,
    bar_valid: np.ndarray,
    horizons: tuple[int, ...],
) -> SelfSupervisedTargets:
    """Stroit multi-horizon future log-return i RMS-vol dlya causal context."""
    prices = np.asarray(log_price, dtype=np.float64)
    valid_bars = np.asarray(bar_valid, dtype=bool)
    if prices.ndim != 3:
        raise ValueError("log_price dolzhen imet' formu [samples, assets, bars]")
    if valid_bars.shape != prices.shape:
        raise ValueError("bar_valid ne sovpadaet s log_price")
    if not horizons or any(horizon < 1 for horizon in horizons):
        raise ValueError("SSL horizons dolzhny byt' polozhitel'nymi")
    sample_count, asset_count, bar_count = prices.shape
    target = np.zeros(
        (sample_count, asset_count, bar_count, len(horizons), 2),
        dtype=np.float32,
    )
    target_valid = np.zeros(
        (sample_count, asset_count, bar_count, len(horizons)),
        dtype=bool,
    )
    finite = np.isfinite(prices) & valid_bars
    clean_prices = np.where(finite, prices, 0.0)
    squared_increment = np.square(np.diff(clean_prices, axis=-1))
    squared_prefix = np.concatenate(
        (
            np.zeros((*prices.shape[:-1], 1), dtype=np.float64),
            np.cumsum(squared_increment, axis=-1),
        ),
        axis=-1,
    )
    invalid_prefix = np.concatenate(
        (
            np.zeros((*prices.shape[:-1], 1), dtype=np.int32),
            np.cumsum(~finite, axis=-1, dtype=np.int32),
        ),
        axis=-1,
    )
    for horizon_index, horizon in enumerate(horizons):
        if horizon >= bar_count:
            continue
        usable_count = bar_count - horizon
        invalid_count = (
            invalid_prefix[..., horizon + 1 :] - invalid_prefix[..., :usable_count]
        )
        horizon_valid = invalid_count == 0
        future_return = (
            clean_prices[..., horizon:] - clean_prices[..., :usable_count]
        )
        future_square_sum = (
            squared_prefix[..., horizon:] - squared_prefix[..., :usable_count]
        )
        future_volatility = np.sqrt(future_square_sum / float(horizon))
        target[..., :usable_count, horizon_index, 0] = np.where(
            horizon_valid,
            future_return,
            0.0,
        )
        target[..., :usable_count, horizon_index, 1] = np.where(
            horizon_valid,
            future_volatility,
            0.0,
        )
        target_valid[..., :usable_count, horizon_index] = horizon_valid
    return SelfSupervisedTargets(values=target, valid=target_valid)


@dataclass(frozen=True)
class MultiResolutionArrays:
    """Hranit odin dataset bez ticker-id i s yavnymi missing-maskami."""

    intraday: np.ndarray
    intraday_valid: np.ndarray
    daily_context: np.ndarray
    daily_valid: np.ndarray
    asset_valid: np.ndarray
    supervised_target: np.ndarray
    supervised_valid: np.ndarray
    timing: DecisionTimingBatch

    def validate_inputs(self, config: V7ModelConfig) -> None:
        """Proveryaet tol'ko causal model-input i timing, ne zaglyadyvaya v target."""
        bars = np.asarray(self.intraday)
        bar_valid = np.asarray(self.intraday_valid, dtype=bool)
        daily = np.asarray(self.daily_context)
        daily_valid = np.asarray(self.daily_valid, dtype=bool)
        asset_valid = np.asarray(self.asset_valid, dtype=bool)
        if bars.ndim != 4:
            raise ValueError("Intraday dolzhen imet' chetyrehmernuyu formu")
        if asset_valid.ndim != 2 or asset_valid.shape[0] != bars.shape[0]:
            raise ValueError("asset_valid imeet nevernuyu formu")
        expected_bar_shape = (
            bars.shape[0],
            asset_valid.shape[1],
            config.sequence_bars,
            len(config.bar_feature_names),
        )
        if bars.shape != expected_bar_shape:
            raise ValueError(f"Intraday shape {bars.shape} != {expected_bar_shape}")
        if bar_valid.shape != bars.shape[:3]:
            raise ValueError("intraday_valid ne sovpadaet s intraday")
        expected_daily_shape = (
            bars.shape[0],
            bars.shape[1],
            len(config.daily_feature_names),
        )
        if daily.shape != expected_daily_shape or daily_valid.shape != expected_daily_shape:
            raise ValueError("Daily context/mask imeet nevernuyu formu")
        if asset_valid.shape != bars.shape[:2]:
            raise ValueError("asset_valid imeet nevernuyu formu")
        if not asset_valid.any(axis=1).all():
            raise ValueError("Kazhdii sample dolzhen imet' hotya by odin aktiv")
        if not np.isfinite(bars[bar_valid]).all():
            raise ValueError("Valid intraday yacheiki dolzhny byt' konechnymi")
        if not np.isfinite(daily[daily_valid]).all():
            raise ValueError("Valid daily yacheiki dolzhny byt' konechnymi")
        self.timing.validate()
        if self.timing.bar_times.shape != (bars.shape[0], bars.shape[2]):
            raise ValueError("Timing bar-grid ne sovpadaet s intraday")

    def validate(self, config: V7ModelConfig) -> None:
        """Sohranyaet polnuyu proverku input i supervised target dlya obshchih callers."""
        self.validate_inputs(config)
        targets = np.asarray(self.supervised_target)
        target_valid = np.asarray(self.supervised_valid, dtype=bool)
        input_shape = np.asarray(self.intraday).shape
        if targets.shape != input_shape[:2] or target_valid.shape != targets.shape:
            raise ValueError("Supervised target/mask imeet nevernuyu formu")
        if not np.isfinite(targets[target_valid]).all():
            raise ValueError("Valid target yacheiki dolzhny byt' konechnymi")

    def sanitized_inputs(self) -> tuple[np.ndarray, ...]:
        """Zamenyaet masked znacheniya nulem, sohranyaya maski otdel'nymi."""
        clean_bars = np.where(
            np.asarray(self.intraday_valid, dtype=bool)[..., None],
            np.asarray(self.intraday, dtype=np.float32),
            0.0,
        )
        clean_daily = np.where(
            np.asarray(self.daily_valid, dtype=bool),
            np.asarray(self.daily_context, dtype=np.float32),
            0.0,
        )
        return (
            clean_bars.astype(np.float32, copy=False),
            np.asarray(self.intraday_valid, dtype=bool),
            clean_daily.astype(np.float32, copy=False),
            np.asarray(self.daily_valid, dtype=bool),
            np.asarray(self.asset_valid, dtype=bool),
        )


class CausalMultiResolutionDataset:
    """Vozvrashchaet numpy-sample bez skrytyh ticker embeddings i future metadata."""

    def __init__(self, arrays: MultiResolutionArrays, config: V7ModelConfig) -> None:
        """Validiruet immutable massivy odin raz do pervogo batching."""
        arrays.validate(config)
        self.arrays = arrays

    def __len__(self) -> int:
        """Vozvrashchaet chislo decision-samples."""
        return int(self.arrays.intraday.shape[0])

    def __getitem__(self, index: int) -> dict[str, Any]:
        """Vozvrashchaet odin ochishchennyi model-input i otdel'nyi target."""
        bar_mask = np.asarray(self.arrays.intraday_valid[index], dtype=bool)
        bars = np.where(
            bar_mask[..., None],
            np.asarray(self.arrays.intraday[index], dtype=np.float32),
            0.0,
        ).astype(np.float32, copy=False)
        daily_mask = np.asarray(self.arrays.daily_valid[index], dtype=bool)
        daily = np.where(
            daily_mask,
            np.asarray(self.arrays.daily_context[index], dtype=np.float32),
            0.0,
        ).astype(np.float32, copy=False)
        asset_mask = np.asarray(self.arrays.asset_valid[index], dtype=bool)
        return {
            "intraday": bars,
            "intraday_mask": bar_mask,
            "daily_context": daily,
            "daily_mask": daily_mask,
            "asset_mask": asset_mask,
            "target": np.where(
                self.arrays.supervised_valid[index],
                self.arrays.supervised_target[index],
                0.0,
            ).astype(np.float32),
            "target_mask": self.arrays.supervised_valid[index],
        }
