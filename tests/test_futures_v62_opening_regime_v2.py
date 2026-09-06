"""Synthetic counterfactual tests of V62 causal boundaries and cash accounting."""

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.opening_execution_v2 import metrics, simulate
from market_lab.futures.opening_regime_v2 import (
    ASSETS,
    FEATURES,
    Market,
    build_candidates,
    build_labels,
    fit_fold,
    local_time,
    walk_forward,
)


def market_fixture(count=65):
    sessions = pd.bdate_range("2021-01-04", periods=count)
    rows, plans = [], []
    for n, day in enumerate(sessions):
        for j, asset in enumerate(ASSETS):
            contract = f"{asset}_contract"
            plans.append(dict(local_date=day, asset=asset, contract_id=contract))
            for minute in range(600, 1121, 10):
                t = local_time(day, minute)
                # Gaps vary, making standardized opening candidates non-degenerate.
                price = 1000 * np.exp(0.008 * np.sin(n * 0.73 + j) + 0.00001 * (minute - 600))
                rows.append(
                    dict(
                        contract_id=contract,
                        timestamp=t,
                        end_timestamp=t + pd.Timedelta(minutes=9, seconds=59),
                        open=price,
                        close=price * 1.0001,
                        high=price * 1.001,
                        low=price * 0.999,
                        volume=100_000.0,
                        asset=asset,
                    )
                )
    return Market(pd.DataFrame(rows), pd.DataFrame(plans), sessions)


@pytest.fixture(scope="module")
def data():
    market = market_fixture()
    return market, build_candidates(market)


def changed_market(market, frame):
    return Market(frame, market.plan.copy(), market.sessions.copy())


def test_evening_absence_cannot_remove_morning_candidates(data):
    market, baseline = data
    bars = market.bars.loc[market.bars["timestamp"].ne(local_time(market.sessions[-1], 1120))]
    actual = build_candidates(changed_market(market, bars))
    pd.testing.assert_frame_equal(actual, baseline)
    assert len(baseline) > 0
    assert baseline.loc[baseline.local_date.eq(market.sessions[-1])].shape[0] > 0


def test_future_path_and_exit_volume_cannot_change_morning_information(data):
    market, baseline = data
    bars = market.bars.copy()
    stamp = local_time(market.sessions[-1], 670)
    selected = bars.timestamp.eq(stamp)
    bars.loc[selected, ["open", "close", "high", "low"]] *= 1.2
    bars.loc[selected, "volume"] = 0
    actual = build_candidates(changed_market(market, bars))
    pd.testing.assert_frame_equal(actual, baseline)
    before_labels = build_labels(baseline, market)
    after_labels = build_labels(actual, changed_market(market, bars))
    assert not before_labels.equals(after_labels)


def test_missing_future_bar_retains_candidates_but_invalidates_label(data):
    market, baseline = data
    stamp = local_time(market.sessions[-1], 650)
    changed = changed_market(market, market.bars.loc[market.bars.timestamp.ne(stamp)])
    actual = build_candidates(changed)
    pd.testing.assert_frame_equal(
        actual.loc[actual.decision_at.le(stamp)].reset_index(drop=True),
        baseline.loc[baseline.decision_at.le(stamp)].reset_index(drop=True),
    )
    labels = build_labels(actual, changed)
    assert (~labels.valid).any()


def test_missing_previous_session_does_not_bridge_to_older_close(data):
    market, _ = data
    stamp = local_time(market.sessions[-2], 1120)
    actual = build_candidates(
        changed_market(market, market.bars.loc[market.bars.timestamp.ne(stamp)])
    )
    assert not actual.local_date.eq(market.sessions[-1]).any()


def test_roll_uses_current_contract_at_both_gap_endpoints(data):
    market, baseline = data
    day = market.sessions[-1]
    plan = market.plan.copy()
    plan.loc[plan.local_date.eq(day) & plan.asset.eq("BR"), "contract_id"] = "BR_new"
    extra = market.bars.loc[market.bars.contract_id.eq("BR_contract")].copy()
    extra["contract_id"] = "BR_new"
    extra[["open", "close", "high", "low"]] *= 5
    rolled = Market(pd.concat([market.bars, extra]), plan, market.sessions)
    actual = build_candidates(rolled)
    old = baseline.loc[baseline.local_date.eq(day)].reset_index(drop=True)
    new = actual.loc[actual.local_date.eq(day)].reset_index(drop=True)
    np.testing.assert_allclose(new[list(FEATURES)], old[list(FEATURES)], equal_nan=True, atol=1e-10)


def test_protected_timestamps_refused(data):
    market, _ = data
    bars = market.bars.head(1).copy()
    bars["timestamp"] = pd.Timestamp("2026-01-01", tz="UTC")
    with pytest.raises(ValueError, match="protected"):
        changed_market(market, bars)


def execution_fixture():
    market = market_fixture(count=2)
    day = market.sessions[-1]
    rows = []
    for asset in ("BR", "SI"):
        rows.append(
            dict(
                candidate_id=f"test_{asset}",
                asset=asset,
                contract_id=f"{asset}_contract",
                local_date=day,
                decision_at=local_time(day, 610),
                entry_at=local_time(day, 610),
                exit_at=local_time(day, 670),
                direction=1,
                decision_minute=600,
                decision_close=1000.0,
                decision_volume=10_000.0,
            )
        )
    specs = pd.DataFrame(
        [
            dict(
                local_date=day,
                contract_id=f"{asset}_contract",
                sizing_usable=True,
                sizing_observed_session_date=market.sessions[0],
                sizing_point_value=1.0,
                sizing_tick_cash_value=0.1,
                conservative_fee_per_side=1.0,
            )
            for asset in ASSETS
        ]
    )
    return market, pd.DataFrame(rows), specs


def test_future_exit_capacity_does_not_resize_entry_and_retry_is_real():
    market, predictions, specs = execution_fixture()
    before = simulate(predictions, market, specs, "primary")
    bars = market.bars.copy()
    exit_stamp = predictions.exit_at.iloc[0]
    bars.loc[bars.timestamp.eq(exit_stamp), "volume"] = 0.0
    after = simulate(predictions, changed_market(market, bars), specs, "primary")
    pd.testing.assert_frame_equal(
        before[2].query("kind == 'entry'").reset_index(drop=True),
        after[2].query("kind == 'entry'").reset_index(drop=True),
    )
    assert after[0].exit_retried.all()
    assert after[3]["metrics"]["economic_metrics_valid"]
    assert after[3]["metrics"]["maximum_participation"] <= 0.01
    assert after[1].pnl.sum() == pytest.approx(after[0].pnl.sum())


def test_insufficient_terminal_capacity_invalidates_economics():
    market, predictions, specs = execution_fixture()
    bars = market.bars.copy()
    bars.loc[bars.timestamp.ge(predictions.exit_at.iloc[0]), "volume"] = 0.0
    result = simulate(predictions, changed_market(market, bars), specs, "primary")[3]["metrics"]
    assert not result["execution_complete"]
    assert not result["economic_metrics_valid"]
    assert any(x["reason"] == "unresolved_terminal_position" for x in result["failures"])


def test_costs_accounting_and_equity_are_conserved():
    market, predictions, specs = execution_fixture()
    low = simulate(predictions, market, specs, "primary")
    high = simulate(predictions, market, specs, "stress")
    assert low[1].equity.iloc[-1] - 1_000_000 == pytest.approx(low[0].pnl.sum())
    assert high[3]["metrics"]["costs"] > low[3]["metrics"]["costs"]
    assert high[1].equity.iloc[-1] < low[1].equity.iloc[-1]


def test_initial_loss_is_in_sharpe_and_drawdown():
    equity = pd.DataFrame(
        dict(
            local_date=pd.to_datetime(["2021-01-04", "2021-01-05"]),
            equity_before=[1_000_000, 900_000],
            equity=[900_000, 900_000],
        )
    )
    result = metrics(equity)
    assert result["maximum_drawdown"] == pytest.approx(0.10)
    assert result["sharpe"] < 0


def test_inference_rejects_outcome_columns(data):
    _, candidates = data
    with pytest.raises(ValueError, match="outcome"):
        fit_fold(candidates, candidates, candidates.assign(positive=1))


def test_real_models_use_all_three_seeds_and_finite_probabilities():
    random = np.random.default_rng(1729)
    frame = pd.DataFrame(random.normal(size=(1600, len(FEATURES))), columns=FEATURES)
    frame["positive"] = (frame[FEATURES[0]] > 0).astype(int)
    probabilities, models, trace = fit_fold(
        frame.iloc[:1200], frame.iloc[1200:1500], frame.iloc[1500:].drop(columns="positive")
    )
    assert [record["seed"] for record in trace] == [6201, 6202, 6203]
    assert len(models["mlp"]) == 3
    for values in probabilities.values():
        assert np.isfinite(values).all() and ((values >= 0) & (values <= 1)).all()


def test_outer_labels_are_never_supplied_to_fit(monkeypatch):
    sessions = pd.bdate_range("2018-01-01", "2021-12-31")
    frames = []
    for n, day in enumerate(sessions):
        for k in range(4):
            row = {column: 0.0 for column in FEATURES}
            row.update(candidate_id=f"{n}_{k}", local_date=day, own_gap_z=1.0)
            frames.append(row)
    candidates = pd.DataFrame(frames)
    labels = candidates[["candidate_id"]].copy()
    labels["available_at"] = [local_time(day, 700) for day in candidates.local_date]
    labels["positive"] = np.arange(len(labels)) % 2
    labels["raw_return"] = 0.01
    labels["valid"] = True
    calls = []

    def fake_fit(core, validation, inference):
        assert core.local_date.max() < validation.local_date.min()
        assert validation.local_date.max() < inference.local_date.min()
        assert "positive" not in inference and "raw_return" not in inference
        assert core.positive.isin([0, 1]).all()
        calls.append((len(core), len(validation)))
        return (
            {"mlp": np.full(len(inference), 0.7), "logistic": np.full(len(inference), 0.5)},
            {},
            [],
        )

    monkeypatch.setattr("market_lab.futures.opening_regime_v2.fit_fold", fake_fit)
    outer = labels.available_at.dt.year.ge(2021)
    labels.loc[outer, "positive"] = 9999
    walk_forward(candidates, labels, sessions)
    assert len(calls) == 1
