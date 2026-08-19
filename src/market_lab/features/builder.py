"""Past-only priznaki i metki napravleniya sleduyushchego intervala."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab.config import FeaturesConfig

SUPPORTED_FEATURES = {  # Yavno podderzhivaemye priznaki pervogo MVP.
    "return_1",
    "return_5",
    "momentum_5",
    "momentum_20",
    "momentum_60",
    "sma_ratio_5_20",
    "sma_ratio_20_75",
    "volatility_10",
    "volatility_20",
    "volatility_60",
    "volume_ratio_5_20",
}


class MarketFeatureBuilder:
    """Stroit deterministichnye priznaki bez centered i future okon."""

    def __init__(self, config: FeaturesConfig) -> None:
        """Proveryaet spisok priznakov pri sozdanii postroitelya."""
        unknown = set(config.names) - SUPPORTED_FEATURES
        if unknown:
            raise ValueError(f"Neizvestnye priznaki: {sorted(unknown)}")
        self.names = list(config.names)

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Vychislyaet priznaki tolko iz tekushchego i proshlyh barov."""
        close = frame["close"].astype(float)
        volume = frame["volume"].astype(float)
        return_1 = close.pct_change(1, fill_method=None)
        all_features = pd.DataFrame(index=frame.index)
        all_features["return_1"] = return_1
        all_features["return_5"] = close.pct_change(5, fill_method=None)
        all_features["momentum_5"] = close / close.shift(5) - 1.0
        all_features["momentum_20"] = close / close.shift(20) - 1.0
        all_features["momentum_60"] = close / close.shift(60) - 1.0
        sma_fast = close.rolling(5, min_periods=5).mean()
        sma_slow = close.rolling(20, min_periods=20).mean()
        all_features["sma_ratio_5_20"] = sma_fast / sma_slow - 1.0
        sma_medium = close.rolling(20, min_periods=20).mean()
        sma_regime = close.rolling(75, min_periods=75).mean()
        all_features["sma_ratio_20_75"] = sma_medium / sma_regime - 1.0
        all_features["volatility_10"] = return_1.rolling(10, min_periods=10).std(ddof=1)
        all_features["volatility_20"] = return_1.rolling(20, min_periods=20).std(ddof=1)
        all_features["volatility_60"] = return_1.rolling(60, min_periods=60).std(ddof=1)
        volume_mean = volume.rolling(20, min_periods=20).mean()
        all_features["volume_ratio_5_20"] = (
            volume.rolling(5, min_periods=5).mean() / volume_mean - 1.0
        )
        selected = all_features.loc[:, self.names]
        return selected.replace([np.inf, -np.inf], np.nan)


def make_direction_labels(frame: pd.DataFrame) -> pd.Series:
    """Stroit metku znaka intervala ot open t+1 do open t+2."""
    future_return = frame["open"].shift(-2) / frame["open"].shift(-1) - 1.0
    labels = (future_return > 0.0).astype(float)
    return labels.where(future_return.notna()).rename("target_up")
