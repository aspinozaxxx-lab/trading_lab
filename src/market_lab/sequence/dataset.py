"""Pamyatno-effektivnye dynamic sequence-dataset i vremennye vyborki."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from market_lab.sequence.config import SequenceExperimentConfig
from market_lab.sequence.data import sequence_partition_path
from market_lab.sequence.features import (
    FEATURE_COLUMNS,
    FeatureScaler,
    add_cross_section_features,
    build_asset_features,
)


@dataclass(frozen=True)
class AssetSequenceArray:
    """Hranit odin masshtabirovannyi vremennoy ryad v plotnyh massivah."""

    ticker: str
    features: np.ndarray
    timestamps: np.ndarray
    local_dates: np.ndarray
    slots: np.ndarray
    entry_times: np.ndarray
    exit_times: np.ndarray
    entry_opens: np.ndarray
    exit_opens: np.ndarray
    targets: np.ndarray
    raw_targets: np.ndarray
    market_regime: np.ndarray
    momentum_score: np.ndarray
    signal_available: np.ndarray
    valid_sequences: np.ndarray


@dataclass(frozen=True)
class SequenceStore:
    """Obedinyaet massivy aktivov i dlinu istoricheskogo okna."""

    assets: tuple[AssetSequenceArray, ...]
    sequence_length: int


@dataclass(frozen=True)
class SequenceSamples:
    """Hranit ssylki na okonchaniya sequence i audit-metadannye."""

    asset_ids: np.ndarray
    positions: np.ndarray
    metadata: pd.DataFrame

    def __len__(self) -> int:
        """Vozvrashchaet chislo primerov v vyborke."""
        return len(self.positions)


class EntryTimeBatchSampler:
    """Pakuet celye entry-time gruppy bez smeshivaniya granic timestamp."""

    def __init__(
        self,
        samples: SequenceSamples,
        batch_size: int,
        shuffle: bool,
        seed: int,
    ) -> None:
        """Fiksiruet gruppy i parametr deterministichnogo epoch-shuffle."""
        if batch_size < 1:
            raise ValueError("batch_size dolzhen byt polozhitel'nym")
        if len(samples.metadata) != len(samples):
            raise ValueError("Metadata sequence-primerov ne sovpadaet s indeksami")
        if len(samples) == 0:
            raise ValueError("Net primerov dlya cross-sectional batching")
        if "entry_time" not in samples.metadata:
            raise ValueError("Net entry_time dlya cross-sectional batching")
        entry_times = pd.to_datetime(samples.metadata["entry_time"], utc=True)
        if entry_times.isna().any():
            raise ValueError("entry_time grupp ne mozhet byt pustym")
        group_ids = pd.factorize(entry_times, sort=True)[0]
        self.groups = tuple(
            np.flatnonzero(group_ids == group_id).astype(int).tolist()
            for group_id in range(int(group_ids.max()) + 1)
        )
        if not self.groups:
            raise ValueError("Net grupp dlya cross-sectional batching")
        largest_group = max(len(group) for group in self.groups)
        if largest_group > batch_size:
            raise ValueError(
                f"Entry-time gruppa {largest_group} prevyshaet batch_size {batch_size}"
            )
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0

    def _packed_batches(self, epoch: int) -> tuple[list[int], ...]:
        """Sobiraet next-fit pakety dlya odnoi deterministichnoi epohi."""
        order = np.arange(len(self.groups))
        if self.shuffle:
            np.random.default_rng(self.seed + epoch).shuffle(order)
        batches: list[list[int]] = []
        current: list[int] = []
        for group_index in order:
            group = self.groups[int(group_index)]
            if current and len(current) + len(group) > self.batch_size:
                batches.append(current)
                current = []
            current.extend(group)
        if current:
            batches.append(current)
        return tuple(batches)

    def __iter__(self) -> Iterator[list[int]]:
        """Vozvrashchaet pakety tekushchei epohi i sdvigaet epoch-counter."""
        batches = self._packed_batches(self.epoch)
        self.epoch += 1
        return iter(batches)

    def __len__(self) -> int:
        """Vozvrashchaet chislo paketov dlya sleduyushchei epohi."""
        return len(self._packed_batches(self.epoch))


class DynamicSequenceDataset:
    """Vydelyaet okno po zaprosu bez materializacii gigabaitov kopii."""

    def __init__(
        self,
        store: SequenceStore,
        samples: SequenceSamples,
        target_scale: float,
        include_target: bool = True,
        include_group_id: bool = False,
    ) -> None:
        """Sohranyaet immutable ssylki i masshtab targeta."""
        if target_scale <= 0:
            raise ValueError("target_scale dolzhen byt polozhitel'nym")
        self.store = store
        self.samples = samples
        self.target_scale = float(target_scale)
        self.include_target = include_target
        self.include_group_id = include_group_id
        if include_group_id and not include_target:
            raise ValueError("group_id trebuet include_target=True")
        self.group_ids = np.empty(0, dtype=np.int64)
        if include_group_id:
            entry_times = pd.to_datetime(samples.metadata["entry_time"], utc=True)
            if entry_times.isna().any():
                raise ValueError("entry_time grupp ne mozhet byt pustym")
            self.group_ids = pd.factorize(entry_times, sort=True)[0].astype(np.int64)

    def __len__(self) -> int:
        """Vozvrashchaet chislo primerov."""
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[np.ndarray, ...]:
        """Vozvrashchaet kopiyu okna, regression-target i ego znak."""
        asset_id = int(self.samples.asset_ids[index])
        position = int(self.samples.positions[index])
        asset = self.store.assets[asset_id]
        start = position - self.store.sequence_length + 1
        window = np.ascontiguousarray(asset.features[start : position + 1])
        if not self.include_target:
            return (window,)
        target = np.float32(asset.targets[position] / self.target_scale)
        direction = np.float32(asset.targets[position] > 0.0)
        if self.include_group_id:
            return window, target, direction, self.group_ids[index]
        return window, target, direction


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 ispol'zovannogo Parquet-kesha."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _utc_end(day: date) -> pd.Timestamp:
    """Vozvrashchaet poslednyuyu UTC-nanosekundu kalendarnogo dnya."""
    return pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)


def load_sequence_panel(
    config: SequenceExperimentConfig,
    tickers: list[str],
    end_date: date,
    partition: Literal["pretest", "test"],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chitaet odnu fizicheskuyu particiyu i stroit obshchii causal-kalendar'."""
    if partition == "pretest" and end_date > config.protocol.calibration_end:
        raise ValueError("Pretest-particiyu nel'zya chitat' posle calibration_end")
    frames: dict[str, pd.DataFrame] = {}
    manifest: list[dict[str, object]] = []
    boundary = _utc_end(end_date)
    for ticker in tickers:
        path = sequence_partition_path(config, ticker, partition)
        if not path.exists():
            raise FileNotFoundError(f"Net {partition}-kesha dlya {ticker}: {path}")
        frame = pd.read_parquet(path)
        used = frame.loc[frame.index <= boundary]
        if used.empty:
            raise ValueError(f"Pustoi 10m-kesh dlya {ticker}")
        frames[ticker] = used
        manifest.append(
            {
                "ticker": ticker,
                "path": str(path),
                "sha256": _sha256_file(path),
                "source_rows_used": len(used),
                "first_timestamp_used": used.index.min(),
                "last_timestamp_used": used.index.max(),
                "partition": partition,
            }
        )
    calendar = pd.DatetimeIndex(
        sorted(set().union(*(frame.index for frame in frames.values())))
    )
    parts = [
        build_asset_features(
            frame,
            ticker,
            config.protocol.horizon_bars,
            calendar_index=calendar,
        )
        for ticker, frame in frames.items()
    ]
    panel = add_cross_section_features(
        pd.concat(parts, ignore_index=True),
        target_mode=config.model.target_mode,
    )
    return panel, pd.DataFrame(manifest)


def build_sequence_store(
    panel: pd.DataFrame,
    scaler: FeatureScaler,
    sequence_length: int,
) -> SequenceStore:
    """Upakovyvaet panel v otdel'nye nepreryvnye massivy aktivov."""
    assets: list[AssetSequenceArray] = []
    for ticker, part in panel.groupby("ticker", sort=True):
        ordered = part.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        raw_features = ordered.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float32)
        finite_rows = np.isfinite(raw_features).all(axis=1)
        valid_sequences = (
            pd.Series(finite_rows.astype(np.int16))
            .rolling(sequence_length, min_periods=sequence_length)
            .sum()
            .eq(sequence_length)
            .to_numpy()
        )
        features = scaler.transform(raw_features)
        assets.append(
            AssetSequenceArray(
                ticker=str(ticker),
                features=features,
                timestamps=ordered["timestamp"].to_numpy(),
                local_dates=ordered["local_date"].to_numpy(dtype="datetime64[D]"),
                slots=ordered["slot"].to_numpy(dtype=np.int16),
                entry_times=ordered["entry_time"].to_numpy(),
                exit_times=ordered["exit_time"].to_numpy(),
                entry_opens=ordered["entry_open"].to_numpy(dtype=np.float64),
                exit_opens=ordered["exit_open"].to_numpy(dtype=np.float64),
                targets=ordered["model_target"].to_numpy(dtype=np.float32),
                raw_targets=ordered["target_return"].to_numpy(dtype=np.float32),
                market_regime=ordered["market_return_24"].to_numpy(dtype=np.float32)
                if "market_return_24" in ordered
                else ordered["market_return_6"].to_numpy(dtype=np.float32),
                momentum_score=ordered["return_24"].to_numpy(dtype=np.float32),
                signal_available=ordered["bar_available"].eq(1.0).to_numpy(),
                valid_sequences=valid_sequences,
            )
        )
    return SequenceStore(assets=tuple(assets), sequence_length=sequence_length)


def _date64(day: date) -> np.datetime64:
    """Preobrazuet date v dnyevnoi numpy timestamp."""
    return np.datetime64(day.isoformat(), "D")


def select_sequence_samples(
    store: SequenceStore,
    start_date: date,
    end_date: date,
    stride_bars: int,
    embargo_bars: int = 0,
    allowed_slots: list[int] | None = None,
    require_target: bool = True,
) -> SequenceSamples:
    """Otbiraet causal-signaly bez budushchei fil'tracii pri evaluation."""
    if stride_bars < 1 or embargo_bars < 0:
        raise ValueError("stride_bars i embargo_bars zadany nekorrektno")
    asset_ids: list[np.ndarray] = []
    positions: list[np.ndarray] = []
    metadata_parts: list[pd.DataFrame] = []
    lower = _date64(start_date)
    upper = _date64(end_date)
    for asset_id, asset in enumerate(store.assets):
        period_positions = np.flatnonzero(
            (asset.local_dates >= lower) & (asset.local_dates <= upper)
        )
        allowed = np.zeros(len(asset.targets), dtype=bool)
        if len(period_positions) > embargo_bars:
            allowed[period_positions[embargo_bars:]] = True
        slot_mask = (
            np.isin(asset.slots, np.asarray(allowed_slots, dtype=np.int16))
            if allowed_slots is not None
            else asset.slots % stride_bars == 0
        )
        mask = allowed & asset.valid_sequences & asset.signal_available & slot_mask
        if require_target:
            mask &= np.isfinite(asset.targets)
        selected = np.flatnonzero(mask)
        if not len(selected):
            continue
        asset_ids.append(np.full(len(selected), asset_id, dtype=np.int16))
        positions.append(selected.astype(np.int32))
        metadata_parts.append(
            pd.DataFrame(
                {
                    "ticker": asset.ticker,
                    "timestamp": asset.timestamps[selected],
                    "entry_time": asset.entry_times[selected],
                    "exit_time": asset.exit_times[selected],
                    "entry_open": asset.entry_opens[selected],
                    "exit_open": asset.exit_opens[selected],
                    "entry_available": np.isfinite(asset.entry_opens[selected]),
                    "target_return": asset.raw_targets[selected],
                    "model_target": asset.targets[selected],
                    "market_regime": asset.market_regime[selected],
                    "momentum_score": asset.momentum_score[selected],
                }
            )
        )
    if not positions:
        raise ValueError(f"Net sequence-primerov za {start_date}..{end_date}")
    all_asset_ids = np.concatenate(asset_ids)
    all_positions = np.concatenate(positions)
    metadata = pd.concat(metadata_parts, ignore_index=True)
    ordering = np.lexsort((metadata["ticker"].to_numpy(), metadata["entry_time"].to_numpy()))
    return SequenceSamples(
        asset_ids=all_asset_ids[ordering],
        positions=all_positions[ordering],
        metadata=metadata.iloc[ordering].reset_index(drop=True),
    )


def robust_target_scale(samples: SequenceSamples) -> float:
    """Ocenivaet train-only IQR targeta s zashchitoi ot nulya."""
    values = samples.metadata["model_target"].to_numpy(dtype=np.float64)
    scale = float(np.nanpercentile(values, 75.0) - np.nanpercentile(values, 25.0))
    return max(scale, 1e-4)
