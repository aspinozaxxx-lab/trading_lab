"""Proverki hronologicheskogo gap i walk-forward."""

from __future__ import annotations

from market_lab.config import AppConfig
from market_lab.validation import make_time_split, make_walk_forward_plan


def test_time_split_has_two_bar_gaps(app_config: AppConfig) -> None:
    """Proveryaet otsutstvie peresechenii i embargo mezhdu zonami."""
    split = make_time_split(320, app_config.validation)
    assert split.train[-1] + app_config.validation.gap_bars < split.validation[0]
    assert split.validation[-1] + app_config.validation.gap_bars < split.test[0]
    assert set(split.train).isdisjoint(split.validation)
    assert set(split.validation).isdisjoint(split.test)


def test_walk_forward_is_expanding_and_ordered(app_config: AppConfig) -> None:
    """Proveryaet zadannye rastushchie train-okna i OOS-validation."""
    plan = make_walk_forward_plan(320, app_config.validation)
    assert len(plan.folds) == app_config.validation.walk_forward_folds
    train_lengths = [len(fold.train) for fold in plan.folds]
    assert train_lengths == sorted(train_lengths)
    assert len(set(train_lengths)) == app_config.validation.walk_forward_folds
    for fold in plan.folds:
        assert fold.train[-1] + app_config.validation.gap_bars < fold.validation[0]
    assert plan.refit[-1] + app_config.validation.gap_bars < plan.test[0]
