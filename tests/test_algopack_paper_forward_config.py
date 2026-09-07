"""The production config is descriptive until a complete prospective activation exists."""

import hashlib
import json
from pathlib import Path

from market_lab.futures import algopack_paper_evaluation_v1 as evaluation
from market_lab.futures import algopack_paper_execution_v1 as execution
from market_lab.futures import algopack_paper_inference_v1 as inference

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "configs/algopack_paper_forward_v1.json"


def config():
    return json.loads(PATH.read_bytes())


def test_config_byte_identity_and_no_authority_escalation():
    assert PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").strip() == (
        hashlib.sha256(PATH.read_bytes()).hexdigest()
    )
    value = config()
    assert value["paper_only"] is True and value["future_start"] is None
    for key in (
        "live_trading_allowed",
        "historical_evaluation_allowed",
        "retraining_allowed",
        "target_income_verified",
    ):
        assert value[key] is False
    assert value["runtime_protocol"] == "algopack_paper_runtime_v2"
    assert value["execution_protocol_id"] == execution.PROTOCOL
    assert value["evaluation_protocol_id"] == evaluation.PROTOCOL


def test_fixed_model_identity_without_model_io():
    value = config()
    assert value["model_sha256"] == inference.MODEL_SHA
    assert value["model_manifest_sha256"] == inference.TRAINING_MANIFEST_SHA


def test_documented_constants_match_executable_protocol():
    assert config()["implementation_snapshot"] == dict(
        assets=list(execution.ASSETS),
        initial_capital_rub_per_arm=execution.INITIAL_CAPITAL_RUB,
        broker_fee_rub_per_contract_side=execution.BROKER_FEE_RUB,
        broker_fee_verified=False,
        notional_fraction_per_asset=execution.NOTIONAL_FRACTION,
        margin_fraction_per_asset=execution.MARGIN_FRACTION,
        depth_fraction=execution.DEPTH_FRACTION,
        edge_cost_multiple=execution.EDGE_COST_MULTIPLE,
        max_quote_age_seconds=execution.MAX_QUOTE_AGE.total_seconds(),
        max_terms_age_seconds=execution.MAX_TERMS_AGE.total_seconds(),
        max_fill_delay_seconds=execution.MAX_FILL_DELAY.total_seconds(),
        slippage_ticks_per_side=execution.SLIPPAGE_TICKS,
        decisions_per_arm_per_open_day=evaluation.DECISIONS_PER_DAY,
        minimum_annual_sessions=evaluation.MIN_ANNUAL_SESSIONS,
        minimum_annual_days=evaluation.MIN_ANNUAL_DAYS,
        cost_scenarios=list(evaluation.COSTS),
    )
