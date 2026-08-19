"""Tipizirovannye PIT i vremennye kontrakty dlya futures-v7."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

UTC_NS = "datetime64[ns]"  # Edinyi numpy-tip dlya sravneniya UTC timestamps.


def _as_utc_ns(values: np.ndarray) -> np.ndarray:
    """Privodit timestamp-massiv k nanosekundam bez tikhogo object-sravneniya."""
    converted = np.asarray(values).astype(UTC_NS)
    if np.isnat(converted).any():
        raise ValueError("Timestamp contract ne dopuskaet NaT")
    return converted


@dataclass(frozen=True)
class DecisionTimingBatch:
    """Hranit obshchii cross-asset bar-kalendar' i granicy daily-targeta."""

    bar_times: np.ndarray
    decision_times: np.ndarray
    entry_open_times: np.ndarray
    exit_open_times: np.ndarray

    def validate(self) -> None:
        """Dokazyvaet causal-window i next-open-to-next-open poryadok."""
        bars = _as_utc_ns(self.bar_times)
        decisions = _as_utc_ns(self.decision_times)
        entries = _as_utc_ns(self.entry_open_times)
        exits = _as_utc_ns(self.exit_open_times)
        if bars.ndim != 2:
            raise ValueError("bar_times dolzhen imet' formu [samples, bars]")
        if decisions.shape != (bars.shape[0],):
            raise ValueError("decision_times ne sovpadaet s samples")
        if entries.shape != decisions.shape or exits.shape != decisions.shape:
            raise ValueError("entry/exit times ne sovpadayut s samples")
        if (np.diff(bars, axis=1) <= np.timedelta64(0, "ns")).any():
            raise ValueError("10m timestamps dolzhny strogo vozrastat'")
        if (bars[:, -1] > decisions).any():
            raise ValueError("Intraday window soderzhit bar posle decision")
        if not ((decisions < entries).all() and (entries < exits).all()):
            raise ValueError("Trebuetsya decision < next open < subsequent open")


@dataclass(frozen=True)
class DailyAsOfSnapshot:
    """Hranit ochishchennyi daily-kontekst i ego yavnuyu masku dostupnosti."""

    values: np.ndarray
    valid: np.ndarray


def mask_daily_context_as_of(
    values: np.ndarray,
    available_at: np.ndarray,
    decision_times: np.ndarray,
) -> DailyAsOfSnapshot:
    """Ukladyvaet budushchie, NaN i neizvestnye daily-kanaly v sleeping-masku."""
    raw_values = np.asarray(values, dtype=np.float32)
    availability = np.asarray(available_at).astype(UTC_NS)
    decisions = _as_utc_ns(decision_times)
    if raw_values.ndim != 3:
        raise ValueError("Daily context dolzhen imet' formu [samples, assets, features]")
    if availability.shape != raw_values.shape:
        raise ValueError("Daily availability ne sovpadaet s context")
    if decisions.shape != (raw_values.shape[0],):
        raise ValueError("Decision timestamps ne sovpadayut s daily samples")
    causal = availability <= decisions[:, None, None]
    valid = causal & ~np.isnat(availability) & np.isfinite(raw_values)
    cleaned = np.where(valid, raw_values, 0.0).astype(np.float32, copy=False)
    return DailyAsOfSnapshot(values=cleaned, valid=valid)


def next_open_to_next_open_log_return(
    entry_open: np.ndarray,
    exit_open: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Stroit supervised-target tol'ko iz sleduyushchego i posleduyushchego open."""
    entry = np.asarray(entry_open, dtype=np.float64)
    exit_ = np.asarray(exit_open, dtype=np.float64)
    if entry.shape != exit_.shape:
        raise ValueError("Entry i exit open dolzhny imet' odinakovuyu formu")
    valid = np.isfinite(entry) & np.isfinite(exit_) & (entry > 0.0) & (exit_ > 0.0)
    target = np.zeros(entry.shape, dtype=np.float32)
    target[valid] = np.log(exit_[valid] / entry[valid]).astype(np.float32)
    return target, valid


def supervised_train_indices(
    timing: DecisionTimingBatch,
    train_end: np.datetime64,
) -> np.ndarray:
    """Dopuskaet v train tol'ko primery s targetom, zavershivshimsya do cutoff."""
    timing.validate()
    exits = _as_utc_ns(timing.exit_open_times)
    boundary = np.datetime64(train_end, "ns")
    return np.flatnonzero(exits <= boundary)
