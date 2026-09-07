"""Synthetic-only model and causal frame tests; no market inputs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, MOSCOW, TEN, FlowVersion
from market_lab.futures.algopack_paper_model_v1 import (
    FLOW_COLUMNS,
    PRICE_COLUMNS,
    TARGET_COLUMNS,
    PriceBar,
    build_features,
    build_labels,
    calendar,
    fit_pair,
    predict_serialized,
    price_index,
    price_state,
)

END = datetime(2025, 6, 2, 8, tzinfo=UTC)  # 11:00 Moscow
CUTOFF = datetime(2026, 9, 7, tzinfo=UTC)


def fixture():
    plan = pd.DataFrame(
        [
            dict(
                effective_date=pd.Timestamp("2025-06-02"),
                asset=asset,
                plan_eligible=True,
                secid=asset + "M5",
                contract_id=asset + "_202506",
            )
            for asset in ASSETS
        ]
    )
    candidates = calendar(plan).loc[[pd.Timestamp(END)]]
    bars, flow = [], {}
    for asset in ASSETS:
        for offset in range(-7, 8):
            begin = END + offset * TEN
            value = 100.0 + offset
            bars.append(
                PriceBar(
                    asset,
                    asset + "M5",
                    asset + "_202506",
                    begin,
                    begin + TEN - timedelta(seconds=1),
                    CUTOFF,
                    "a" * 64,
                    value,
                    value + 2,
                    value - 1,
                    value + 1,
                )
            )
        for dataset in ("tradestats", "obstats"):
            for end in (END - timedelta(minutes=5), END):
                local = end.astimezone(MOSCOW)
                flow[(dataset, asset, asset + "M5", end)] = FlowVersion(
                    dataset,
                    asset,
                    asset + "M5",
                    local.date().isoformat(),
                    local.strftime("%H:%M:%S"),
                    CUTOFF,
                    "b" * 64,
                    (3.0, 1.0, 6.0, 2.0),
                )
    return candidates, bars, flow


def state(bars):
    return price_state(
        price_index(bars),
        asset="BR",
        contract="BR_202506",
        secid="BRM5",
        information_end=END,
        available_cutoff=CUTOFF,
    )


def test_price_formulas_exact():
    _, bars, _ = fixture()
    status, values, sources = state(bars)
    assert status == "READY"
    np.testing.assert_allclose(
        values,
        [np.log(100 / 99), np.log(100 / 97), np.log(100 / 94), np.log(100 / 99), np.log(101 / 98)],
    )
    assert sources == ("a" * 64,)


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"contract_id": "ROLLED"}, "MISSING_PRICE_LOOKBACK"),
        ({"secid": "ROLLED"}, "UNAVAILABLE_PRICE_LOOKBACK"),
        ({"available_at": CUTOFF + TEN}, "UNAVAILABLE_PRICE_LOOKBACK"),
        ({"low": 999.0}, "INVALID_OHLC"),
        ({"open": 0.0}, "INVALID_OHLC"),
        ({"close": float("nan")}, "INVALID_OHLC"),
        ({"high": None}, "INVALID_OHLC"),
    ],
)
def test_invalid_past_masks(change, expected):
    _, bars, _ = fixture()
    bars[0] = replace(bars[0], **change)
    assert state(bars)[0] == expected


def test_gap_and_duplicate():
    _, bars, _ = fixture()
    assert state(bars[1:])[0] == "MISSING_PRICE_LOOKBACK"
    with pytest.raises(ValueError, match="duplicate"):
        price_index(bars + bars[:1])


def test_calendar_retains_missing_asset_and_ineligible():
    plan = pd.DataFrame(
        [
            dict(
                effective_date=pd.Timestamp("2025-06-02"),
                asset="BR",
                plan_eligible=False,
                secid="BRM5",
                contract_id="BR_202506",
            )
        ]
    )
    result = calendar(plan)
    assert len(result) == 42
    assert not result["BR_plan_eligible"].any()
    assert not result["SI_plan_eligible"].any()
    assert result.iloc[0].decision_at == pd.Timestamp("2025-06-02T07:14:00Z")


def test_features_no_future_dependency_and_labels_independent():
    candidates, bars, flow = fixture()
    before = build_features(candidates, price_index(bars), flow, CUTOFF)
    past = [bar for bar in bars if bar.begin < END]
    after = build_features(candidates, price_index(past), flow, CUTOFF)
    pd.testing.assert_frame_equal(before, after)
    assert before.index.equals(candidates.index)
    np.testing.assert_allclose(
        before.loc[:, list(FLOW_COLUMNS)].iloc[0], np.tile([0.5, 0.5, 0.5, 0.5, np.arcsinh(1.0)], 4)
    )
    labels = build_labels(candidates, price_index(bars), CUTOFF)
    missing = build_labels(candidates, price_index(past), CUTOFF)
    assert labels.index.equals(missing.index)
    np.testing.assert_allclose(labels.loc[:, list(TARGET_COLUMNS)], np.log(107 / 101))
    assert missing.loc[:, list(TARGET_COLUMNS)].isna().all().all()


@pytest.mark.parametrize(
    "change",
    [
        {"secid": "ROLLED"},
        {"contract_id": "ROLLED"},
        {"open": None},
        {"available_at": CUTOFF + TEN},
    ],
)
def test_label_gap_roll_unavailable(change):
    candidates, bars, _ = fixture()
    bars = [
        replace(bar, **change) if bar.asset == "BR" and bar.begin == END + 4 * TEN else bar
        for bar in bars
    ]
    labels = build_labels(candidates, price_index(bars), CUTOFF)
    assert pd.isna(labels.iloc[0].BR_target)
    assert pd.notna(labels.iloc[0].SI_target)


@pytest.mark.parametrize("builder", [build_features, build_labels])
def test_protected_calendar_even_when_no_inputs(builder):
    candidates, _, _ = fixture()
    candidates.index = pd.DatetimeIndex(["2026-06-01T08:00:00Z"])
    candidates["decision_at"] = candidates.index + pd.Timedelta(minutes=4)
    args = (candidates, {}, {}, CUTOFF) if builder is build_features else (candidates, {}, CUTOFF)
    with pytest.raises(ValueError, match="protected"):
        builder(*args)


def test_training_fixed_pair_serialization_and_joint_mask():
    rng = np.random.default_rng(71)
    columns = list((*PRICE_COLUMNS, *FLOW_COLUMNS))
    features = pd.DataFrame(rng.normal(size=(5003, 40)), columns=columns)
    features[columns[0]] = 3.0  # StandardScaler constant feature must have scale=1.
    labels = pd.DataFrame(rng.normal(size=(5003, 4)), columns=list(TARGET_COLUMNS))
    features.loc[0, FLOW_COLUMNS[0]] = np.nan
    labels.loc[1, TARGET_COLUMNS[0]] = np.nan
    models, mask = fit_pair(features, labels)
    assert mask.sum() == 5001
    for arm, model in models.items():
        assert model["training_rows"] == 5001 and model["alpha"] == 10.0
        assert model["scale"][0] == 1.0
        x = features.loc[mask, model["feature_names"]].to_numpy()
        scaler = StandardScaler().fit(x)
        independent = Ridge(alpha=10.0, solver="svd").fit(scaler.transform(x), labels.loc[mask])
        np.testing.assert_allclose(model["mean"], scaler.mean_)
        np.testing.assert_allclose(
            predict_serialized(model, x[:13]),
            independent.predict(scaler.transform(x[:13])),
            atol=1e-12,
        )
        assert arm in {"price_only", "price_flow"}
    with pytest.raises(ValueError, match="COVERAGE"):
        fit_pair(features.iloc[:5000], labels.iloc[:5000])


def test_training_identity_mismatch():
    with pytest.raises(ValueError, match="identity"):
        fit_pair(pd.DataFrame(index=[0]), pd.DataFrame(index=[1]))
