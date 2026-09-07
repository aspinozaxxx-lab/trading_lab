"""No market values: absent historical prior decisions must remain masked."""

import hashlib

import pandas as pd
import pytest

from market_lab.futures import algopack_paper_inputs_v1 as v1
from market_lab.futures import algopack_paper_inputs_v2 as v2


def fixture(root, **overrides):
    row = dict(
        effective_date=pd.Timestamp("2025-09-08"),
        decision_date=pd.Timestamp("2025-09-05"),
        observed_through=pd.Timestamp("2025-09-05"),
        asset_code="SI",
        contract_id="Si:SiU5:2025-09-18",
        secid="SiU5",
        plan_tradable=True,
    )
    row.update(overrides)
    path = root / "plan.parquet"
    pd.DataFrame([row]).to_parquet(path, index=False)
    raw = path.read_bytes()
    return dict(path=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), rows=1)


@pytest.mark.parametrize("column", ["decision_date", "observed_through"])
@pytest.mark.parametrize("tradable", [False, True])
def test_missing_prior_date_kept_and_ineligible(tmp_path, column, tradable):
    ref = fixture(tmp_path, **{column: pd.NaT, "plan_tradable": tradable})
    plan = v2.load_active_plan(tmp_path, ref)
    assert len(plan) == 1 and not plan.iloc[0].plan_eligible
    assert pd.isna(plan.iloc[0][column])


def test_no_change_for_valid_inputs_or_price_gates(tmp_path):
    ref = fixture(tmp_path)
    pd.testing.assert_frame_equal(
        v1.load_active_plan(tmp_path, ref), v2.load_active_plan(tmp_path, ref)
    )
    assert v2.inspect_intraday is v1.inspect_intraday
    assert v2.load_price_artifact is v1.load_price_artifact


@pytest.mark.parametrize("value", [pd.NaT, pd.Timestamp("2026-01-01")])
def test_missing_or_protected_effective_date_still_fails(tmp_path, value):
    with pytest.raises(ValueError):
        v2.load_active_plan(tmp_path, fixture(tmp_path, effective_date=value))
