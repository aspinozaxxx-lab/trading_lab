"""Proverki 10m-priznakov, splitov i intraday-backtesta."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.sequence.backtest import (
    IntradayStrategySpec,
    build_intraday_weights,
    run_intraday_backtest,
)
from market_lab.sequence.config import (
    SequenceModelConfig,
    SequenceProtocolConfig,
    load_sequence_config,
)
from market_lab.sequence.dataset import (
    DynamicSequenceDataset,
    EntryTimeBatchSampler,
    SequenceSamples,
    build_sequence_store,
    robust_target_scale,
    select_sequence_samples,
)
from market_lab.sequence.features import (
    FEATURE_COLUMNS,
    add_cross_section_features,
    build_asset_features,
    fit_feature_scaler,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren sequence-testov.


def _intraday_frame(days: int = 12, bars_per_day: int = 48) -> pd.DataFrame:
    """Stroit validnye 10m-svechi bez overnight-targetov."""
    timestamps: list[pd.Timestamp] = []
    for day in pd.bdate_range("2022-12-19", periods=days, tz="Europe/Moscow"):
        timestamps.extend(
            day + pd.Timedelta(hours=10, minutes=10 * bar)
            for bar in range(bars_per_day)
        )
    index = pd.DatetimeIndex(timestamps).tz_convert("UTC")
    base = 100.0 * np.exp(np.arange(len(index), dtype=float) * 0.0001)
    return pd.DataFrame(
        {
            "open": base,
            "high": base * 1.001,
            "low": base * 0.999,
            "close": base * 1.0002,
            "volume": 1000.0 + np.arange(len(index)) % 31,
            "value": base * (1000.0 + np.arange(len(index)) % 31),
        },
        index=pd.DatetimeIndex(index, name="timestamp"),
    )


def test_sequence_config_has_disjoint_holdout_and_nonoverlapping_target() -> None:
    """Proveryaet razdelenie instrumentov i shag ne men'she targeta."""
    config = load_sequence_config(PROJECT_ROOT / "configs" / "sequence_5090.yaml")
    assert set(config.universe.development).isdisjoint(config.universe.holdout)
    differences = np.diff(config.protocol.evaluation_decision_slots)
    assert (differences >= config.protocol.horizon_bars).all()
    assert config.protocol.train_end < config.protocol.validation_start
    assert config.protocol.calibration_end < config.protocol.test_start
    assert config.model.target_mode == "absolute"
    assert config.model.ranking_weight == pytest.approx(0.0)
    assert config.model.ranking_temperature > 0.0
    assert config.portfolio.position_mode_candidates == ["long_only"]
    assert config.portfolio.short_borrow_rate_annual == pytest.approx(0.0)
    extended_protocol = SequenceProtocolConfig.model_validate(
        {
            **config.protocol.model_dump(mode="python"),
            "horizon_bars": 72,
            "evaluation_decision_slots": [0],
        }
    )
    assert extended_protocol.horizon_bars == 72


def test_entry_time_batch_sampler_keeps_groups_whole_and_is_deterministic() -> None:
    """Proveryaet celye timestamp-gruppy i vosproizvodimyi epoch-shuffle."""
    entry_times = pd.to_datetime(
        [
            "2025-01-10 07:10Z",
            "2025-01-10 07:10Z",
            "2025-01-10 07:10Z",
            "2025-01-10 08:10Z",
            "2025-01-10 08:10Z",
            "2025-01-10 09:10Z",
            "2025-01-10 09:10Z",
            "2025-01-10 09:10Z",
            "2025-01-10 10:10Z",
            "2025-01-10 10:10Z",
        ]
    )
    samples = SequenceSamples(
        asset_ids=np.zeros(len(entry_times), dtype=np.int16),
        positions=np.arange(len(entry_times), dtype=np.int32),
        metadata=pd.DataFrame({"entry_time": entry_times}),
    )
    first = EntryTimeBatchSampler(samples, batch_size=5, shuffle=True, seed=42)
    second = EntryTimeBatchSampler(samples, batch_size=5, shuffle=True, seed=42)
    first_epoch = list(first)
    second_epoch = list(second)
    assert first_epoch == second_epoch
    assert list(first) == list(second)
    assert sorted(index for batch in first_epoch for index in batch) == list(
        range(len(entry_times))
    )
    assert all(len(batch) <= 5 for batch in first_epoch)
    for _, group in pd.Series(range(len(entry_times))).groupby(entry_times):
        group_indices = set(group.to_list())
        containing_batches = [
            set(batch) for batch in first_epoch if group_indices & set(batch)
        ]
        assert containing_batches and len(containing_batches) == 1
        assert group_indices <= containing_batches[0]


def test_pairwise_ranking_loss_prefers_correct_order_inside_group() -> None:
    """Proveryaet predpochtenie pravil'nogo rankinga bez mezhgruppovyh par."""
    torch = pytest.importorskip("torch")
    from market_lab.sequence.training import (
        _batch_loss,
        _loader,
        mean_cross_section_ic,
        pairwise_ranking_loss,
    )

    targets = torch.tensor([2.0, 1.0, -1.0])
    group_ids = torch.tensor([0, 0, 0])
    correct = pairwise_ranking_loss(
        torch.tensor([2.0, 1.0, -1.0]),
        targets,
        group_ids,
        temperature=1.0,
    )
    reversed_order = pairwise_ranking_loss(
        torch.tensor([-1.0, 1.0, 2.0]),
        targets,
        group_ids,
        temperature=1.0,
    )
    assert float(correct) < float(reversed_order)
    isolated = pairwise_ranking_loss(
        torch.tensor([-10.0, 10.0]),
        torch.tensor([2.0, -2.0]),
        torch.tensor([0, 1]),
        temperature=1.0,
    )
    assert float(isolated) == pytest.approx(0.0)

    class DummyModel(torch.nn.Module):
        """Vozvrashchaet kontroliruemye regression i classification vyhody."""

        def forward(self, features):
            """Ispol'zuet pervyi element kak regression i nulevoi logit."""
            return features[:, 0, 0], torch.zeros_like(features[:, 0, 0])

    features = torch.tensor([[[0.5]], [[-0.5]]])
    auxiliary_targets = torch.tensor([0.25, -0.25])
    directions = torch.tensor([1.0, 0.0])
    default_loss, _ = _batch_loss(
        DummyModel(),
        (features, auxiliary_targets, directions),
        torch.device("cpu"),
        classification_weight=0.25,
        autocast_dtype=None,
    )
    expected_default = torch.nn.functional.smooth_l1_loss(
        features[:, 0, 0],
        auxiliary_targets,
        beta=0.5,
    ) + 0.25 * torch.nn.functional.binary_cross_entropy_with_logits(
        torch.zeros(2),
        directions,
    )
    assert float(default_loss) == pytest.approx(float(expected_default))
    ic_metadata = pd.DataFrame(
        {
            "entry_time": [pd.Timestamp("2025-01-10 07:10Z")] * 3,
            "target_return": [1.0, 2.0, 3.0],
            "model_target": [3.0, 2.0, 1.0],
        }
    )
    ic_predictions = np.array([3.0, 2.0, 1.0])
    assert mean_cross_section_ic(ic_metadata, ic_predictions) == pytest.approx(-1.0)
    assert mean_cross_section_ic(
        ic_metadata,
        ic_predictions,
        target_column="model_target",
    ) == pytest.approx(1.0)

    class DummyGroupedDataset:
        """Imitiruet chetyre polnye cross-sectional gruppy dlya DataLoader."""

        def __init__(self):
            """Sozdaet gruppy razmerov 20, 12, 20 i 12."""
            times = pd.to_datetime(
                ["2025-01-10 07:10Z"] * 20
                + ["2025-01-10 08:10Z"] * 12
                + ["2025-01-10 09:10Z"] * 20
                + ["2025-01-10 10:10Z"] * 12
            )
            self.samples = SequenceSamples(
                asset_ids=np.zeros(64, dtype=np.int16),
                positions=np.arange(64, dtype=np.int32),
                metadata=pd.DataFrame({"entry_time": times}),
            )
            self.include_target = True
            self.include_group_id = True
            self.group_ids = np.repeat(np.arange(4, dtype=np.int64), [20, 12, 20, 12])

        def __len__(self):
            """Vozvrashchaet chislo synthetic primerov."""
            return len(self.group_ids)

        def __getitem__(self, index):
            """Vozvrashchaet minimal'nyi training-primer s group_id."""
            return (
                np.zeros((2, 2), dtype=np.float32),
                np.float32(index),
                np.float32(1.0),
                self.group_ids[index],
            )

    ranking_config = SequenceModelConfig(
        batch_size=32,
        workers=0,
        ranking_weight=1.0,
    )
    batches = list(
        _loader(DummyGroupedDataset(), ranking_config, shuffle=True, seed=42)
    )
    assert [len(batch[0]) for batch in batches] == [32, 32]
    for group_id in range(4):
        assert sum(bool((batch[3] == group_id).any()) for batch in batches) == 1


def test_sequence_target_uses_future_opens_but_features_do_not() -> None:
    """Proveryaet next-open timing i invariantnost' tekushchih priznakov."""
    frame = _intraday_frame()
    built = add_cross_section_features(build_asset_features(frame, "TEST", horizon_bars=6))
    position = 220
    assert built.loc[position, "entry_open"] == pytest.approx(frame.iloc[position + 1]["open"])
    assert built.loc[position, "exit_open"] == pytest.approx(frame.iloc[position + 7]["open"])
    assert built.loc[position, "target_return"] == pytest.approx(
        frame.iloc[position + 7]["open"] / frame.iloc[position + 1]["open"] - 1.0
    )
    changed = frame.copy()
    changed.iloc[position + 1 :, :4] *= 5.0
    changed_built = add_cross_section_features(
        build_asset_features(changed, "TEST", horizon_bars=6)
    )
    np.testing.assert_allclose(
        built.loc[position, list(FEATURE_COLUMNS)].to_numpy(dtype=float),
        changed_built.loc[position, list(FEATURE_COLUMNS)].to_numpy(dtype=float),
        equal_nan=True,
    )


def test_sequence_target_is_removed_across_moscow_overnight() -> None:
    """Proveryaet zapret targeta, kotoryi peresekaet granicu torgovogo dnya."""
    frame = _intraday_frame(days=3)
    built = build_asset_features(frame, "TEST", horizon_bars=6)
    first_day = built.loc[built["local_date"] == built.loc[0, "local_date"]]
    assert first_day.iloc[-7:]["target_return"].isna().all()
    assert first_day.iloc[10]["target_return"] > 0.0


def test_flat_candle_has_neutral_close_location() -> None:
    """Proveryaet konechnyi priznak dlya bara bez cenovogo diapazona."""
    frame = _intraday_frame(days=3)
    frame.iloc[100, frame.columns.get_indexer(["high", "low", "close"])] = frame.iloc[
        100
    ]["open"]
    built = build_asset_features(frame, "TEST", horizon_bars=6)
    assert built.loc[100, "close_location"] == pytest.approx(0.0)


def test_missing_bar_does_not_stretch_wall_clock_target() -> None:
    """Proveryaet exact timestamp target vmesto shift po sleduyushchei stroke."""
    full = _intraday_frame(days=5)
    decision_position = 120
    missing_exit = full.index[decision_position + 7]
    incomplete = full.drop(index=missing_exit)
    built = build_asset_features(
        incomplete,
        "TEST",
        horizon_bars=6,
        calendar_index=full.index,
    ).set_index("timestamp")
    decision = full.index[decision_position]
    assert built.loc[decision, "exit_time"] == missing_exit
    assert pd.isna(built.loc[decision, "exit_open"])
    assert pd.isna(built.loc[decision, "target_return"])


def test_sequence_scaler_and_split_use_declared_periods() -> None:
    """Proveryaet train-only scaler, sequence-length, stride i embargo."""
    first = build_asset_features(_intraday_frame(), "AAA", horizon_bars=6)
    second_frame = _intraday_frame()
    second_frame.loc[:, ["open", "high", "low", "close"]] *= 2.0
    second = build_asset_features(second_frame, "BBB", horizon_bars=6)
    panel = add_cross_section_features(pd.concat([first, second], ignore_index=True))
    train_end = pd.Timestamp("2022-12-23").date()
    scaler = fit_feature_scaler(panel, train_end)
    future_changed = panel.copy()
    future_changed.loc[future_changed["local_date"] > pd.Timestamp(train_end), "return_1"] = 99
    repeated = fit_feature_scaler(future_changed, train_end)
    np.testing.assert_array_equal(scaler.median, repeated.median)
    store = build_sequence_store(panel, scaler, sequence_length=48)
    samples = select_sequence_samples(
        store,
        pd.Timestamp("2022-12-26").date(),
        pd.Timestamp("2022-12-30").date(),
        stride_bars=6,
        embargo_bars=12,
    )
    assert len(samples) > 0
    assert (samples.metadata["timestamp"] >= pd.Timestamp("2022-12-26", tz="UTC")).all()
    references = zip(samples.asset_ids, samples.positions, strict=True)
    assert all(
        store.assets[int(asset)].valid_sequences[int(position)]
        for asset, position in references
    )


def test_residual_model_target_keeps_raw_target_for_backtest() -> None:
    """Proveryaet residual-label, dataset-scale i raw target v metadata."""
    first_frame = _intraday_frame()
    second_frame = _intraday_frame()
    trend = np.exp(np.arange(len(second_frame), dtype=float) * 0.0002)
    price_columns = ["open", "high", "low", "close"]
    second_frame.loc[:, price_columns] = second_frame.loc[:, price_columns].mul(
        trend,
        axis=0,
    )
    first = build_asset_features(first_frame, "AAA", horizon_bars=6)
    second = build_asset_features(second_frame, "BBB", horizon_bars=6)
    panel = add_cross_section_features(
        pd.concat([first, second], ignore_index=True),
        target_mode="cross_section_residual",
    )
    paired = panel.dropna(subset=["target_return", "model_target"]).groupby(
        "timestamp"
    )
    residual_sums = paired["model_target"].sum()
    assert np.allclose(residual_sums.to_numpy(), 0.0, atol=1e-10)

    last_date = panel["local_date"].max().date()
    scaler = fit_feature_scaler(panel, last_date)
    store = build_sequence_store(panel, scaler, sequence_length=48)
    training = select_sequence_samples(
        store,
        panel["local_date"].min().date(),
        last_date,
        stride_bars=6,
        require_target=True,
    )
    evaluation = select_sequence_samples(
        store,
        panel["local_date"].min().date(),
        last_date,
        stride_bars=6,
        require_target=False,
    )
    assert evaluation.metadata["target_return"].isna().any()
    assert len(evaluation) > len(training)
    assert not np.allclose(
        training.metadata["target_return"],
        training.metadata["model_target"],
    )
    expected_scale = np.nanpercentile(training.metadata["model_target"], 75.0) - (
        np.nanpercentile(training.metadata["model_target"], 25.0)
    )
    target_scale = robust_target_scale(training)
    assert target_scale == pytest.approx(max(float(expected_scale), 1e-4))
    dataset = DynamicSequenceDataset(store, training, target_scale)
    _, scaled_target, direction = dataset[0]
    expected_target = training.metadata.loc[0, "model_target"] / target_scale
    assert scaled_target == pytest.approx(expected_target)
    assert direction == pytest.approx(float(expected_target > 0.0))


def test_intraday_weights_and_costs_charge_entry_switch_and_terminal_exit() -> None:
    """Proveryaet top-k, sleduyushchii open, switch-turnover i final'nyi vyhod."""
    config = load_sequence_config(PROJECT_ROOT / "configs" / "sequence_5090.yaml")
    entries = pd.to_datetime(["2025-01-10 07:10Z", "2025-01-10 08:10Z"])
    exits = pd.to_datetime(["2025-01-10 08:10Z", "2025-01-10 09:10Z"])
    rows: list[dict[str, object]] = []
    for offset, (entry, exit_time) in enumerate(zip(entries, exits, strict=True)):
        for ticker, prediction, target in (
            ("AAA", 2.0 - 2.0 * offset, 0.01),
            ("BBB", 1.0 + 2.0 * offset, 0.02),
        ):
            rows.append(
                {
                    "entry_time": entry,
                    "exit_time": exit_time,
                    "ticker": ticker,
                    "prediction": prediction,
                    "target_return": target,
                    "market_regime": 0.01,
                    "entry_available": True,
                }
            )
    predictions = pd.DataFrame(rows)
    spec = IntradayStrategySpec("test", 1, 0.0, 1, False, 1.0)
    weights = build_intraday_weights(predictions, spec)
    result = run_intraday_backtest(predictions, weights, config.portfolio)
    assert weights.loc[entries[0], "AAA"] == pytest.approx(1.0)
    assert weights.loc[entries[1], "BBB"] == pytest.approx(1.0)
    assert result.metrics["turnover"] == pytest.approx(4.0, abs=0.03)
    assert result.metrics["trade_count"] == 4
    assert result.metrics["total_cost"] > 0.0


def test_long_short_weights_are_neutral_with_exact_gross_and_spread_gate() -> None:
    """Proveryaet top-bottom spread, znaki, net-nol' i zadannyi gross."""
    entry = pd.Timestamp("2025-01-10 07:10Z")
    scores = {"AAA": 0.03, "BBB": 0.02, "CCC": -0.01, "DDD": -0.02}
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entry,
                "exit_time": entry + pd.Timedelta(hours=1),
                "ticker": ticker,
                "prediction": score,
                "target_return": 0.0,
                "market_regime": -0.01,
                "entry_available": True,
            }
            for ticker, score in scores.items()
        ]
    )
    spec = IntradayStrategySpec(
        "long-short",
        top_k=2,
        minimum_score=0.035,
        keep_rank=2,
        regime_filter=True,
        leverage=1.5,
        position_mode="long_short",
    )
    weights = build_intraday_weights(predictions, spec).loc[entry]
    assert weights[["AAA", "BBB"]].gt(0.0).all()
    assert weights[["CCC", "DDD"]].lt(0.0).all()
    assert weights.sum() == pytest.approx(0.0)
    assert weights.abs().sum() == pytest.approx(1.5)

    blocked = build_intraday_weights(
        predictions,
        IntradayStrategySpec(
            "spread-blocked",
            top_k=2,
            minimum_score=0.041,
            keep_rank=2,
            regime_filter=False,
            leverage=1.5,
            position_mode="long_short",
        ),
    ).loc[entry]
    assert blocked.abs().sum() == pytest.approx(0.0)


def test_short_pnl_and_borrow_use_actual_short_notional_and_elapsed_time() -> None:
    """Proveryaet tochnyi short PnL i borrow za fakticheskoe vremya uderzhaniya."""
    config = load_sequence_config(PROJECT_ROOT / "configs" / "sequence_5090.yaml")
    portfolio = config.portfolio.model_copy(
        update={
            "commission_bps": 0.0,
            "slippage_bps": 0.0,
            "financing_rate_annual": 0.0,
            "short_borrow_rate_annual": 0.10,
        }
    )
    entry = pd.Timestamp("2025-01-10 07:10Z")
    exit_time = entry + pd.Timedelta(days=365, hours=6)
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entry,
                "exit_time": exit_time,
                "ticker": "AAA",
                "prediction": 0.10,
                "target_return": 0.10,
                "market_regime": 0.0,
                "entry_available": True,
            },
            {
                "entry_time": entry,
                "exit_time": exit_time,
                "ticker": "BBB",
                "prediction": -0.10,
                "target_return": -0.10,
                "market_regime": 0.0,
                "entry_available": True,
            },
        ]
    )
    spec = IntradayStrategySpec(
        "borrow",
        top_k=1,
        minimum_score=0.0,
        keep_rank=1,
        regime_filter=False,
        leverage=1.0,
        position_mode="long_short",
    )
    result = run_intraday_backtest(
        predictions,
        build_intraday_weights(predictions, spec),
        portfolio,
    )
    expected_gross_pnl = 100_000.0
    expected_borrow = 50_000.0
    assert result.ledger.loc[0, "gross_pnl"] == pytest.approx(expected_gross_pnl)
    assert result.ledger.loc[0, "short_borrow_cost"] == pytest.approx(expected_borrow)
    assert result.metrics["short_borrow_cost"] == pytest.approx(expected_borrow)
    assert result.metrics["total_cost"] == pytest.approx(expected_borrow)
    assert result.metrics["final_equity"] == pytest.approx(1_050_000.0)


def test_weights_do_not_use_future_target_availability() -> None:
    """Proveryaet chto otsutstvuyushchii future exit ne menyaet order-intent."""
    entry = pd.Timestamp("2025-01-10 07:10Z")
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entry,
                "exit_time": entry + pd.Timedelta(hours=1),
                "ticker": "AAA",
                "prediction": 2.0,
                "target_return": np.nan,
                "market_regime": 0.01,
                "entry_available": True,
            },
            {
                "entry_time": entry,
                "exit_time": entry + pd.Timedelta(hours=1),
                "ticker": "BBB",
                "prediction": 1.0,
                "target_return": 0.01,
                "market_regime": 0.01,
                "entry_available": True,
            },
        ]
    )
    spec = IntradayStrategySpec("no-lookahead", 1, 0.0, 1, False, 1.0)
    weights = build_intraday_weights(predictions, spec)
    assert weights.loc[entry, "AAA"] == pytest.approx(1.0)
    assert weights.loc[entry, "BBB"] == pytest.approx(0.0)


def test_hysteresis_carries_only_filled_previous_intent() -> None:
    """Proveryaet chto nedostupnyi entry ne stanovitsya sleduyushchim held-aktivom."""
    entries = pd.to_datetime(["2025-01-10 07:10Z", "2025-01-10 08:10Z"])
    exits = pd.to_datetime(["2025-01-10 08:10Z", "2025-01-10 09:10Z"])
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entries[0],
                "exit_time": exits[0],
                "ticker": "AAA",
                "prediction": 2.0,
                "target_return": 0.01,
                "market_regime": 0.01,
                "entry_available": False,
            },
            {
                "entry_time": entries[0],
                "exit_time": exits[0],
                "ticker": "BBB",
                "prediction": 1.0,
                "target_return": 0.01,
                "market_regime": 0.01,
                "entry_available": True,
            },
            {
                "entry_time": entries[1],
                "exit_time": exits[1],
                "ticker": "AAA",
                "prediction": 1.0,
                "target_return": 0.01,
                "market_regime": 0.01,
                "entry_available": True,
            },
            {
                "entry_time": entries[1],
                "exit_time": exits[1],
                "ticker": "BBB",
                "prediction": 2.0,
                "target_return": 0.01,
                "market_regime": 0.01,
                "entry_available": True,
            },
        ]
    )
    spec = IntradayStrategySpec("actual-fill", 1, 0.0, 2, False, 1.0)
    weights = build_intraday_weights(predictions, spec)
    assert weights.loc[entries[0], "AAA"] == pytest.approx(1.0)
    assert weights.loc[entries[1], "AAA"] == pytest.approx(0.0)
    assert weights.loc[entries[1], "BBB"] == pytest.approx(1.0)


def test_unavailable_entry_has_no_cost_and_no_actual_active_interval() -> None:
    """Proveryaet cash, izderzhki i actual activity pri otsutstvuyushchem entry."""
    config = load_sequence_config(PROJECT_ROOT / "configs" / "sequence_5090.yaml")
    entry = pd.Timestamp("2025-01-10 07:10Z")
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entry,
                "exit_time": entry + pd.Timedelta(hours=1),
                "ticker": "AAA",
                "prediction": 1.0,
                "target_return": 0.10,
                "market_regime": 0.01,
                "entry_available": False,
            }
        ]
    )
    spec = IntradayStrategySpec("unavailable", 1, 0.0, 1, False, 1.0)
    weights = build_intraday_weights(predictions, spec)
    result = run_intraday_backtest(predictions, weights, config.portfolio)
    assert weights.loc[entry, "AAA"] == pytest.approx(1.0)
    assert result.ledger.loc[0, "gross_exposure"] == pytest.approx(0.0)
    assert result.metrics["active_interval_fraction"] == pytest.approx(0.0)
    assert result.metrics["trade_count"] == 0
    assert result.metrics["turnover"] == pytest.approx(0.0)
    assert result.metrics["total_cost"] == pytest.approx(0.0)
    assert result.metrics["final_equity"] == pytest.approx(
        config.portfolio.initial_capital
    )


def test_missing_exit_marks_result_non_executable() -> None:
    """Proveryaet chto synthetic exit pomechaet rezultat neispolnimym."""
    config = load_sequence_config(PROJECT_ROOT / "configs" / "sequence_5090.yaml")
    entry = pd.Timestamp("2025-01-10 07:10Z")
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entry,
                "exit_time": entry + pd.Timedelta(hours=1),
                "ticker": "AAA",
                "prediction": 1.0,
                "target_return": np.nan,
                "market_regime": 0.01,
                "entry_available": True,
            }
        ]
    )
    spec = IntradayStrategySpec("missing-exit", 1, 0.0, 1, False, 1.0)
    result = run_intraday_backtest(
        predictions,
        build_intraday_weights(predictions, spec),
        config.portfolio,
    )
    assert result.metrics["missing_exit_count"] == 1
    assert result.metrics["execution_complete"] is False


def test_intraday_drawdown_includes_initial_capital() -> None:
    """Proveryaet chto pervaya ubytochnaya sdelka popadaet v max drawdown."""
    config = load_sequence_config(PROJECT_ROOT / "configs" / "sequence_5090.yaml")
    portfolio = config.portfolio.model_copy(
        update={"commission_bps": 0.0, "slippage_bps": 0.0}
    )
    entry = pd.Timestamp("2025-01-10 07:10Z")
    predictions = pd.DataFrame(
        [
            {
                "entry_time": entry,
                "exit_time": entry + pd.Timedelta(hours=1),
                "ticker": "AAA",
                "prediction": 1.0,
                "target_return": -0.10,
                "market_regime": 0.01,
                "entry_available": True,
            }
        ]
    )
    spec = IntradayStrategySpec("drawdown", 1, 0.0, 1, False, 1.0)
    weights = build_intraday_weights(predictions, spec)
    result = run_intraday_backtest(predictions, weights, portfolio)
    assert result.metrics["total_return"] == pytest.approx(-0.10)
    assert result.metrics["max_drawdown"] == pytest.approx(0.10)
