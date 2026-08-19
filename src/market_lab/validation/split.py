"""Indeksnye hronologicheskie razbieniya bez peremeshivaniya."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from market_lab.config import ValidationConfig


@dataclass(frozen=True)
class TimeSplit:
    """Hranit bazovye train, validation i test indeksy."""

    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray


@dataclass(frozen=True)
class WalkForwardFold:
    """Hranit expanding train i sleduyushchii validation-otrezok."""

    train: np.ndarray
    validation: np.ndarray


@dataclass(frozen=True)
class WalkForwardPlan:
    """Obedinyaet OOS-foldy, refit-istoriyu i finalnyi test."""

    folds: tuple[WalkForwardFold, ...]
    refit: np.ndarray
    test: np.ndarray


def make_time_split(length: int, config: ValidationConfig) -> TimeSplit:
    """Stroit odin vremennoy split s gap pered validation i test."""
    if length < 20:
        raise ValueError("Dlya vremennogo split nuzhno minimum 20 barov")
    train_boundary = int(length * config.train_fraction)
    validation_boundary = int(length * (config.train_fraction + config.validation_fraction))
    train_end = train_boundary - config.gap_bars
    test_start = validation_boundary + config.gap_bars
    train = np.arange(0, train_end, dtype=int)
    validation = np.arange(train_boundary, validation_boundary, dtype=int)
    test = np.arange(test_start, length, dtype=int)
    if min(len(train), len(validation), len(test)) < 2:
        raise ValueError("Posle gap odin iz vremennyh otsekov slishkom korotok")
    return TimeSplit(train=train, validation=validation, test=test)


def make_walk_forward_plan(length: int, config: ValidationConfig) -> WalkForwardPlan:
    """Delit validation-zonu na expanding walk-forward foldy."""
    base = make_time_split(length, config)
    chunks = np.array_split(base.validation, config.walk_forward_folds)
    folds: list[WalkForwardFold] = []
    for chunk in chunks:
        if len(chunk) < 2:
            raise ValueError("Validation-fold slishkom korotok")
        train_end = int(chunk[0]) - config.gap_bars
        train = np.arange(0, train_end, dtype=int)
        if len(train) < 2:
            raise ValueError("Train-fold slishkom korotok")
        folds.append(WalkForwardFold(train=train, validation=chunk.astype(int)))
    refit_end = int(base.test[0]) - config.gap_bars
    refit = np.arange(0, refit_end, dtype=int)
    return WalkForwardPlan(folds=tuple(folds), refit=refit, test=base.test)
