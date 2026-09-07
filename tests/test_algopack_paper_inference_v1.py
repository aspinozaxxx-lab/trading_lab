"""Pure synthetic future data and fake model bytes; no protected market inputs."""

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from market_lab.futures import algopack_paper_inference_v1 as core
from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, FIVE, MOSCOW, TEN, FlowVersion
from market_lab.futures.algopack_paper_model_v1 import (
    FLOW_COLUMNS,
    PRICE_COLUMNS,
    TARGET_COLUMNS,
    PriceBar,
)

END = datetime(2026, 9, 8, 8, tzinfo=UTC)
CUTOFF = END + timedelta(minutes=4)
START = END - timedelta(hours=2)  # Synthetic F only; this is NOT a production boundary.


def fixture():
    plans, bars, flow = [], [], []
    for asset in ASSETS:
        plans.append(
            core.ContractPlan(
                asset,
                asset + "U6",
                asset + "_202609",
                date(2026, 9, 8),
                date(2026, 9, 17),
                END - timedelta(hours=1),
                "a" * 64,
            )
        )
        for offset in range(-7, 0):
            begin = END + offset * TEN
            value = 100.0 + offset
            bars.append(
                PriceBar(
                    asset,
                    asset + "U6",
                    asset + "_202609",
                    begin,
                    begin + TEN - timedelta(seconds=1),
                    begin + TEN + timedelta(minutes=1),
                    "b" * 64,
                    value,
                    value + 2,
                    value - 1,
                    value + 1,
                )
            )
        for dataset in ("tradestats", "obstats"):
            for end in (END - FIVE, END):
                local = end.astimezone(MOSCOW)
                flow.append(
                    FlowVersion(
                        dataset,
                        asset,
                        asset + "U6",
                        local.date().isoformat(),
                        local.strftime("%H:%M:%S"),
                        end + timedelta(minutes=2),
                        "c" * 64,
                        (3.0, 1.0, 6.0, 2.0),
                    )
                )
    return dict(
        information_end=END,
        input_cutoff=CUTOFF,
        future_start=START,
        plans=tuple(plans),
        bars=tuple(bars),
        flow=tuple(flow),
    )


@pytest.fixture
def models(monkeypatch):
    result, hashes = {}, {}
    for arm in ("price_only", "price_flow"):
        names = list(PRICE_COLUMNS if arm == "price_only" else (*PRICE_COLUMNS, *FLOW_COLUMNS))
        model = dict(
            feature_names=names,
            target_names=list(TARGET_COLUMNS),
            mean=[0.0] * len(names),
            scale=[1.0] * len(names),
            coefficients=np.zeros((4, len(names))).tolist(),
            intercept=[0.001, -0.002, 0.003, -0.004],
            training_rows=56996,
            alpha=10.0,
            solver="svd",
        )
        result[arm] = json.dumps(model, allow_nan=False).encode()
        hashes[arm] = hashlib.sha256(result[arm]).hexdigest()
    monkeypatch.setattr(core, "MODEL_SHA", hashes)  # Explicit synthetic model identities only.
    return result


def test_ready_both_arms_provenance_and_target_order(models):
    prepared = core.prepare_features(**fixture())
    result = core.predict_prepared(prepared, models)
    assert result["state"] == "UNPUBLISHED"
    for arm in result["arms"].values():
        assert arm["status"] == "READY"
        assert arm["prediction"] == [0.001, -0.002, 0.003, -0.004]
    assert result["target_names"] == list(TARGET_COLUMNS)
    assert len(result["assets"]) == 4
    assert result["assets"][0]["price_sources"] == ("b" * 64,)
    assert len(result["assets"][0]["flow_versions"]) == 4
    completed = core.complete_forecast(result, completed_at=CUTOFF + timedelta(seconds=1))
    assert completed["state"] == "COMPUTED_NOT_PERSISTED"
    assert completed["planned_entry_at"] == (END + TEN).isoformat()
    assert completed["target_exit_at"] == (END + 7 * TEN).isoformat()
    assert completed["execution_admitted"] is False
    assert result["state"] == "UNPUBLISHED"  # No mutation of source record.


def test_baseline_survives_missing_flow(models):
    kwargs = fixture()
    kwargs["flow"] = ()
    prepared = core.prepare_features(**kwargs)
    result = core.predict_prepared(prepared, models)
    assert result["arms"]["price_only"]["status"] == "READY"
    assert result["arms"]["price_flow"]["status"] == "SLEEP_MISSING_FEATURES"
    assert result["arms"]["price_flow"]["prediction"] is None


def test_missing_any_joint_price_sleeps_both(models):
    kwargs = fixture()
    kwargs["bars"] = kwargs["bars"][1:]
    result = core.predict_prepared(core.prepare_features(**kwargs), models)
    assert all(row["prediction"] is None for row in result["arms"].values())
    assert result["assets"][0]["price_status"] == "MISSING_PRICE_LOOKBACK"


def test_late_revisions_and_plan_do_not_change_past():
    kwargs = fixture()
    original = core.prepare_features(**kwargs)
    kwargs["bars"] += (replace(kwargs["bars"][0], available_at=CUTOFF + TEN, close=999.0),)
    kwargs["flow"] += (
        replace(kwargs["flow"][0], available_at=CUTOFF + TEN, values=(99.0, 1.0, 99.0, 1.0)),
    )
    kwargs["plans"] += (replace(kwargs["plans"][0], available_at=CUTOFF + TEN, secid="OTHER"),)
    assert core.prepare_features(**kwargs) == original


def test_latest_invalid_price_not_replaced_by_older_good_version():
    kwargs = fixture()
    kwargs["bars"] += (replace(kwargs["bars"][0], available_at=CUTOFF, close=999.0),)
    result = core.prepare_features(**kwargs)
    assert result.assets[0].price_status == "INVALID_OHLC"


@pytest.mark.parametrize(
    "field, change",
    [
        ("bars", dict(close=999.0)),
        ("flow", dict(values=(99.0, 1.0, 99.0, 1.0))),
        ("plans", dict(secid="OTHER")),
    ],
)
def test_tied_conflicting_versions_fail(field, change):
    kwargs = fixture()
    kwargs[field] += (replace(kwargs[field][0], **change),)
    with pytest.raises(ValueError, match="conflict"):
        core.prepare_features(**kwargs)


def test_pre_f_price_rejected_not_silently_filtered():
    kwargs = fixture()
    bar = kwargs["bars"][0]
    kwargs["bars"] += (replace(bar, begin=START - TEN, end=START - timedelta(seconds=1)),)
    with pytest.raises(ValueError, match="pre-F"):
        core.prepare_features(**kwargs)


@pytest.mark.parametrize("delta", [0, 1, 60])
def test_late_completion_cannot_emit_prediction(models, delta):
    result = core.predict_prepared(core.prepare_features(**fixture()), models)
    result = core.complete_forecast(result, completed_at=END + TEN + timedelta(seconds=delta))
    assert all(
        row["prediction"] is None and row["status"] == "MISSED_PUBLICATION_DEADLINE"
        for row in result["arms"].values()
    )


def test_late_input_sleeps(models):
    kwargs = fixture()
    kwargs["input_cutoff"] = END + TEN
    prepared = core.prepare_features(**kwargs)
    assert prepared.status == "MISSED_INPUT_DEADLINE"
    assert all(
        row["prediction"] is None
        for row in core.predict_prepared(prepared, models)["arms"].values()
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(expiration_day=date(2026, 9, 8)),
        dict(available_at=CUTOFF + TEN),
        dict(effective_day=date(2026, 9, 7)),
    ],
)
def test_unavailable_expired_or_stale_plan_sleeps(change):
    kwargs = fixture()
    kwargs["plans"] = (replace(kwargs["plans"][0], **change), *kwargs["plans"][1:])
    assert core.prepare_features(**kwargs).assets[0].price_status == "NO_ELIGIBLE_PLAN"


def test_roll_has_no_old_contract_lookback():
    kwargs = fixture()
    kwargs["plans"] = (
        replace(kwargs["plans"][0], contract_id="NEW", secid="BRZ6"),
        *kwargs["plans"][1:],
    )
    state = core.prepare_features(**kwargs).assets[0]
    assert state.price_status == "MISSING_PRICE_LOOKBACK"
    assert state.flow_status == "MISSING_BUCKET"


def test_frozen_bytes_and_model_pair_required(models):
    prepared = core.prepare_features(**fixture())
    with pytest.raises(ValueError, match="identity"):
        core.predict_prepared(prepared, {**models, "price_only": models["price_only"] + b" "})
    with pytest.raises(ValueError, match="both"):
        core.predict_prepared(prepared, {"price_only": models["price_only"]})


def test_no_label_api_or_time_travel(models):
    assert not {"labels", "targets", "returns", "pnl"} & set(
        inspect.signature(core.prepare_features).parameters
    )
    result = core.predict_prepared(core.prepare_features(**fixture()), models)
    with pytest.raises(ValueError, match="precedes"):
        core.complete_forecast(result, completed_at=END)
    with pytest.raises(ValueError, match="boundary"):
        core.prepare_features(**{**fixture(), "future_start": core.TRAINED_AT})


def test_model_reader_only_pinned_three_files(tmp_path, models, monkeypatch):
    files = {}
    for arm, raw in models.items():
        name = f"{arm}.model.json"
        (tmp_path / name).write_bytes(raw)
        files[name] = dict(path=name, bytes=len(raw), sha256=core.MODEL_SHA[arm])
    manifest = dict(
        status="TRAINED_NOT_EVALUATED",
        completed_at=core.TRAINED_AT.isoformat(),
        live_trading_allowed=False,
        files=files,
    )
    raw = json.dumps(manifest).encode()
    (tmp_path / "manifest.json").write_bytes(raw)
    (tmp_path / "labels.parquet").write_bytes(b"DO NOT READ")
    monkeypatch.setattr(core, "TRAINING_MANIFEST_SHA", hashlib.sha256(raw).hexdigest())
    assert core.load_fixed_models(tmp_path) == models
    (tmp_path / "price_only.model.json").write_bytes(models["price_only"] + b" ")
    with pytest.raises(ValueError, match="manifest"):
        core.load_fixed_models(tmp_path)
