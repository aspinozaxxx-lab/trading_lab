"""Proverki causal daily-panel i pyatidnevnogo split-protokola."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.sequence.daily import (
    DAILY_FEATURE_COLUMNS,
    build_daily_panel,
    select_daily_samples,
)


def _daily_frames(days: int = 170) -> dict[str, pd.DataFrame]:
    """Stroit tri raznyh 10m-ryada s vechernim barom-posle cutoff."""
    sessions = pd.bdate_range("2021-01-04", periods=days, tz="Europe/Moscow")
    specifications = {"AAA": 0.0010, "BBB": 0.0020, "CCC": -0.0005}
    frames: dict[str, pd.DataFrame] = {}
    for ticker, daily_slope in specifications.items():
        timestamps: list[pd.Timestamp] = []
        rows: list[dict[str, float]] = []
        for session_number, session in enumerate(sessions):
            session_base = 100.0 * np.exp(daily_slope * session_number)
            for minute, intraday_move in (
                (9 * 60 + 50, 0.0000),
                (12 * 60, 0.0004),
                (18 * 60 + 40, 0.0008),
                (19 * 60, 2.0000),
            ):
                begin = session + pd.Timedelta(minutes=minute)
                open_price = session_base * np.exp(intraday_move)
                close_price = open_price * 1.0001
                timestamps.append(begin)
                rows.append(
                    {
                        "open": open_price,
                        "high": close_price * 1.001,
                        "low": open_price * 0.999,
                        "close": close_price,
                        "volume": 1_000.0 + session_number,
                        "value": open_price * (1_000.0 + session_number),
                    }
                )
        frames[ticker] = pd.DataFrame(
            rows,
            index=pd.DatetimeIndex(timestamps, name="timestamp").tz_convert("UTC"),
        )
    return frames


def _ticker_row(panel: pd.DataFrame, ticker: str, session: pd.Timestamp) -> pd.Series:
    """Vozvrashchaet edinstvennuyu stroku tickera i session-date."""
    rows = panel.loc[
        panel["ticker"].eq(ticker)
        & panel["session_date"].eq(session.tz_localize(None).normalize())
    ]
    assert len(rows) == 1
    return rows.iloc[0]


def test_daily_target_uses_next_open_and_fifth_session_exit() -> None:
    """Proveryaet cutoff, next-session entry i open posle pyati sessii."""
    frames = _daily_frames()
    panel = build_daily_panel(frames)
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    signal_position = 130
    row = _ticker_row(panel, "AAA", sessions[signal_position])
    entry_base = 100.0 * np.exp(0.0010 * (signal_position + 1))
    exit_base = 100.0 * np.exp(0.0010 * (signal_position + 6))
    assert row["raw_close"] < entry_base * 2.0
    assert row["entry_open"] == pytest.approx(entry_base)
    assert row["exit_open"] == pytest.approx(exit_base)
    assert row["raw_target_return"] == pytest.approx(exit_base / entry_base - 1.0)
    assert row["entry_session"] == sessions[signal_position + 1].tz_localize(None)
    assert row["exit_session"] == sessions[signal_position + 6].tz_localize(None)
    assert row["signal_time"] == sessions[signal_position] + pd.Timedelta(hours=18, minutes=50)


def test_daily_target_carries_missing_scheduled_exit_to_first_real_open() -> None:
    """Proveryaet factual exit posle propushchennogo planovogo open bez synthetic ceny."""
    frames = _daily_frames()
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    signal_position = 130
    scheduled_exit = sessions[signal_position + 6].normalize()
    next_exit = sessions[signal_position + 7].normalize()
    aaa = frames["AAA"].copy()
    local_dates = aaa.index.tz_convert("Europe/Moscow").normalize()
    aaa = aaa.loc[local_dates != scheduled_exit].copy()
    next_mask = aaa.index.tz_convert("Europe/Moscow").normalize() == next_exit
    aaa.loc[next_mask, ["open", "high", "low", "close"]] = 80.0
    frames["AAA"] = aaa
    panel = build_daily_panel(frames)
    row = _ticker_row(panel, "AAA", sessions[signal_position])
    assert pd.isna(row["scheduled_exit_open"])
    assert row["exit_session"] == next_exit.tz_localize(None)
    assert row["exit_open"] == pytest.approx(80.0)
    assert row["raw_target_return"] == pytest.approx(80.0 / row["entry_open"] - 1.0)


def test_daily_features_and_context_do_not_see_future() -> None:
    """Proveryaet invariantnost' priznakov i backward as-of context join."""
    frames = _daily_frames()
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    signal_position = 135
    signal_time = sessions[signal_position] + pd.Timedelta(hours=18, minutes=50)
    context = pd.DataFrame(
        {"rvi": [10.0, 99.0]},
        index=pd.DatetimeIndex(
            [signal_time - pd.Timedelta(minutes=1), signal_time + pd.Timedelta(minutes=1)]
        ).tz_convert("UTC"),
    )
    original = build_daily_panel(frames, external_context=context)
    changed_frames = {ticker: frame.copy() for ticker, frame in frames.items()}
    for frame in changed_frames.values():
        local_dates = frame.index.tz_convert("Europe/Moscow").normalize()
        future = local_dates > sessions[signal_position].normalize()
        frame.loc[future, ["open", "high", "low", "close"]] *= 3.0
    changed = build_daily_panel(changed_frames, external_context=context)
    original_row = _ticker_row(original, "AAA", sessions[signal_position])
    changed_row = _ticker_row(changed, "AAA", sessions[signal_position])
    np.testing.assert_allclose(
        original_row.loc[list(DAILY_FEATURE_COLUMNS)].to_numpy(dtype=float),
        changed_row.loc[list(DAILY_FEATURE_COLUMNS)].to_numpy(dtype=float),
        equal_nan=True,
    )
    assert original_row["context_rvi"] == pytest.approx(10.0)
    assert changed_row["context_rvi"] == pytest.approx(10.0)


def test_missing_next_session_is_not_filtered_at_inference() -> None:
    """Proveryaet chto budushchii missing open ne menyaet eval sample."""
    frames = _daily_frames()
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    signal_position = 135
    missing_session = sessions[signal_position + 1].normalize()
    aaa = frames["AAA"]
    local_dates = aaa.index.tz_convert("Europe/Moscow").normalize()
    frames["AAA"] = aaa.loc[local_dates != missing_session]
    panel = build_daily_panel(frames)
    row = _ticker_row(panel, "AAA", sessions[signal_position])
    assert pd.isna(row["entry_open"])
    assert pd.isna(row["target_return"])
    samples = select_daily_samples(
        panel,
        sessions[signal_position].date(),
        sessions[signal_position].date(),
        sequence_length=3,
        mode="eval",
    )
    selected = samples.metadata.loc[samples.metadata["ticker"].eq("AAA")]
    assert len(selected) == 1
    assert not bool(selected.iloc[0]["entry_available"])


def test_late_first_bar_is_not_mislabeled_as_scheduled_open() -> None:
    """Proveryaet chto bar posle 09:50 ne podmenyaet cenu planovogo vhoda."""
    frames = _daily_frames()
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    signal_position = 135
    entry_session = sessions[signal_position + 1].normalize()
    aaa = frames["AAA"]
    local = aaa.index.tz_convert("Europe/Moscow")
    first_bar = (local.normalize() == entry_session) & (local.hour == 9) & (local.minute == 50)
    frames["AAA"] = aaa.loc[~first_bar]
    panel = build_daily_panel(frames)
    row = _ticker_row(panel, "AAA", sessions[signal_position])
    assert pd.isna(row["entry_open"])
    assert not bool(row["entry_available"])


def test_cross_section_and_beta_residual_targets() -> None:
    """Proveryaet median-residual i causal beta-residual k market-series."""
    frames = _daily_frames()
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    panel = build_daily_panel(frames)
    session = sessions[135].tz_localize(None).normalize()
    cross = panel.loc[panel["session_date"].eq(session)]
    expected = cross["raw_target_return"] - cross["raw_target_return"].median()
    np.testing.assert_allclose(cross["target_return"], expected)
    assert cross["target_return"].median() == pytest.approx(0.0)

    increments = 0.001 + 0.0005 * np.sin(np.arange(len(sessions), dtype=float) / 3.0)
    market = pd.Series(100.0 * np.exp(np.cumsum(increments)), index=sessions)
    beta_panel = build_daily_panel(
        frames,
        residual_method="beta",
        market_series=market,
        beta_window=20,
        beta_min_periods=10,
    )
    beta_row = _ticker_row(beta_panel, "AAA", sessions[135])
    assert np.isfinite(beta_row["rolling_beta"])
    assert beta_row["target_return"] == pytest.approx(
        beta_row["raw_target_return"]
        - beta_row["rolling_beta"] * beta_row["external_market_target_return"]
    )


def test_staggered_phase_nonoverlap_and_exit_boundary_purge() -> None:
    """Proveryaet phase 0..4, embargo i purge po fakticheskomu exit-time."""
    frames = _daily_frames()
    panel = build_daily_panel(frames)
    sessions = pd.bdate_range("2021-01-04", periods=170, tz="Europe/Moscow")
    samples = select_daily_samples(
        panel,
        sessions[130].date(),
        sessions[160].date(),
        sequence_length=3,
        mode="eval",
        embargo_sessions=2,
        phases=[0],
    )
    assert samples.metadata["session_phase"].eq(0).all()
    assert samples.metadata["session_date"].min() >= sessions[132].tz_localize(None)
    aaa = samples.metadata.loc[samples.metadata["ticker"].eq("AAA")].sort_values(
        "signal_time"
    )
    assert (
        pd.to_datetime(aaa["exit_time"].iloc[:-1], utc=True).to_numpy()
        <= pd.to_datetime(aaa["entry_time"].iloc[1:], utc=True).to_numpy()
    ).all()

    boundary = sessions[150] + pd.Timedelta(hours=9, minutes=50)
    purged = select_daily_samples(
        panel,
        sessions[125].date(),
        sessions[149].date(),
        sequence_length=3,
        mode="train",
        purge_exit_before=boundary,
    )
    assert (pd.to_datetime(purged.metadata["exit_time"], utc=True) < boundary).all()
