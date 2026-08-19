"""Testy causal factor/residual pyatisessionnogo portfolio futures-v8."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from market_lab.futures_v8.config import load_v8_research_config
from market_lab.futures_v8.portfolio import (
    FACTOR_GROSS_BUDGET,
    RESIDUAL_GROSS_BUDGET,
    SLEEVE_WEIGHT,
    AssetDecisionInput,
    AssetSleeveProvenance,
    DecisionModelSnapshot,
    PortfolioDecision,
    assert_v8_portfolio_constants_match_protocol,
    build_v8_portfolio_path,
)

MOSCOW = ZoneInfo("Europe/Moscow")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
V8_CONFIG_PATH = PROJECT_ROOT / "configs" / "futures_v8_development_protocol.yaml"
ASSETS = ("BR", "MIX", "RI", "SI")
DEFAULT_CONTRACTS = ("BRV5", "MXU5", "RIU5", "SiU5")


def _snapshot(
    day: int,
    *,
    factor_location: float | None = 2.0,
    factor_scale: float | None = 1.0,
    factor_decision_score: float | None = 0.8,
    scores: tuple[float | None, ...] = (2.0, 1.0, -1.0, -2.0),
    scales: tuple[float | None, ...] = (1.0, 1.0, 1.0, 1.0),
    vols: tuple[float | None, ...] = (0.01, 0.02, 0.01, 0.02),
    masks: tuple[bool, ...] = (True, True, True, True),
    nominal: tuple[bool, ...] = (True, True, True, True),
    contracts: tuple[str | None, ...] = DEFAULT_CONTRACTS,
) -> DecisionModelSnapshot:
    """Sobiraet polnyi fixed-order D18:50 snapshot bez market-data I/O."""
    assets = tuple(
        AssetDecisionInput(
            asset=asset,
            contract_id=contract,
            residual_decision_score=score,
            total_scale=scale,
            ex_ante_daily_vol20=vol,
            asset_mask=mask,
            nominal_span_eligible=span,
        )
        for asset, contract, score, scale, vol, mask, span in zip(
            ASSETS,
            contracts,
            scores,
            scales,
            vols,
            masks,
            nominal,
            strict=True,
        )
    )
    return DecisionModelSnapshot(
        decision_at=datetime(2025, 9, day, 18, 50, tzinfo=MOSCOW),
        factor_location=factor_location,
        factor_scale=factor_scale,
        factor_decision_score=factor_decision_score,
        assets=assets,
    )


def _asset_provenance(
    snapshot: DecisionModelSnapshot,
) -> dict[str, AssetSleeveProvenance]:
    """Vozvrashchaet asset audit novogo sleeve po canonical name."""
    sleeve = build_v8_portfolio_path([snapshot])[0].new_sleeve
    return {item.asset: item for item in sleeve.assets}


def _target_map(decision: PortfolioDecision) -> dict[tuple[str, str], float]:
    """Prevrashchaet typed target tuple v udobnuyu testovuyu kartu."""
    return {
        (item.asset, item.contract_id): item.target_weight
        for item in decision.target_weights
    }


def test_numeric_factor_residual_budgets_neutrality_and_notional_handoff() -> None:
    """Proveryaet exact inverse-vol, demeaning, 50/50 residual i 0.20 sleeve."""
    decision = build_v8_portfolio_path([_snapshot(1)])[0]
    sleeve = decision.new_sleeve
    factor = [item.factor_weight for item in sleeve.assets]
    residual = [item.residual_weight for item in sleeve.assets]
    combined = [item.combined_weight for item in sleeve.assets]

    assert factor == pytest.approx([0.35 / 3.0, 0.35 / 6.0, 0.35 / 3.0, 0.35 / 6.0])
    assert residual == pytest.approx([0.26, 0.065, -0.1625, -0.1625])
    assert combined == pytest.approx(
        [0.35 / 3.0 + 0.26, 0.35 / 6.0 + 0.065, 0.35 / 3.0 - 0.1625, 0.35 / 6.0 - 0.1625]
    )
    assert sleeve.factor_gross == pytest.approx(FACTOR_GROSS_BUDGET)
    assert sleeve.residual_gross == pytest.approx(RESIDUAL_GROSS_BUDGET)
    assert sum(residual) == pytest.approx(0.0, abs=1e-15)
    assert decision.gross_weight <= SLEEVE_WEIGHT
    assert [item.target_weight for item in decision.target_weights] == pytest.approx(
        [SLEEVE_WEIGHT * item for item in combined]
    )

    handoff = decision.desired_notional_handoff(1_000_000.0)
    assert handoff.integer_sizing_owner == "ledger"
    assert [item.desired_notional for item in handoff.targets] == pytest.approx(
        [200_000.0 * item for item in combined]
    )


def test_factor_abstains_below_one_but_residual_remains_independent() -> None:
    """Derzhit factor cash pri SNR 0.99, ne ubivaya valid residual alpha."""
    sleeve = build_v8_portfolio_path(
        [_snapshot(1, factor_location=0.99, factor_scale=1.0, factor_decision_score=0.7)]
    )[0].new_sleeve

    assert sleeve.factor_state == "cash_factor_snr_below_one"
    assert sleeve.factor_gross == 0.0
    assert sleeve.residual_gross == pytest.approx(0.65)
    assert sum(item.residual_weight for item in sleeve.assets) == pytest.approx(0.0)


def test_missing_or_uncertain_asset_is_cash_with_explicit_reason() -> None:
    """Maskiruet missing score, scale, volatility i asset mask fail-closed."""
    snapshot = _snapshot(
        1,
        scores=(None, 1.0, -1.0, -2.0),
        scales=(1.0, float("inf"), 1.0, 1.0),
        vols=(0.01, 0.02, None, 0.02),
        masks=(True, True, True, False),
    )
    audit = _asset_provenance(snapshot)

    assert audit["BR"].eligibility_reason == "missing_or_invalid_residual_decision_score"
    assert audit["MIX"].eligibility_reason == "missing_or_invalid_total_scale"
    assert audit["RI"].eligibility_reason == "missing_or_invalid_ex_ante_vol20"
    assert audit["SI"].eligibility_reason == "asset_mask_false"
    assert all(item.combined_weight == 0.0 for item in audit.values())


def test_five_sleeve_impulse_persists_exactly_five_decisions_then_expires() -> None:
    """Dokazyvaet 0.20 impulse na indexah 0--4 i ego ischezhnovenie pered indexom 5."""
    impulse = _snapshot(1)
    cash = [
        _snapshot(day, masks=(False, False, False, False))
        for day in range(2, 7)
    ]
    path = build_v8_portfolio_path([impulse, *cash])
    initial = _target_map(path[0])

    for decision in path[:5]:
        assert _target_map(decision) == pytest.approx(initial)
    assert all(value == pytest.approx(0.0) for value in _target_map(path[5]).values())
    assert path[4].active_sleeves[0].sequence_number == 0
    assert all(item.sequence_number != 0 for item in path[5].active_sleeves)


def test_five_identical_sleeves_reach_unit_ladder_without_gross_breach() -> None:
    """Proveryaet mature 5x0.20 ladder i aggregate gross cap odin."""
    path = build_v8_portfolio_path([_snapshot(day) for day in range(1, 6)])
    mature = path[-1]
    unit_weights = [item.combined_weight for item in mature.new_sleeve.assets]

    assert len(mature.active_sleeves) == 5
    assert [item.target_weight for item in mature.target_weights] == pytest.approx(unit_weights)
    assert mature.gross_weight == pytest.approx(sum(abs(value) for value in unit_weights))
    assert mature.gross_weight <= 1.0
    assert mature.net_weight == pytest.approx(sum(unit_weights))


def test_append_only_future_mutation_and_shuffle_guards() -> None:
    """Garantiruet immutable prefix i otkaz ot duplicate ili shuffled vremeni."""
    first = _snapshot(1)
    second = _snapshot(2, factor_location=-2.0, factor_decision_score=-0.8)
    future = _snapshot(3)
    mutated_future = _snapshot(
        3,
        factor_location=-5.0,
        factor_decision_score=-0.9,
        scores=(-9.0, -3.0, 4.0, 8.0),
    )

    prefix = build_v8_portfolio_path([first, second])
    assert build_v8_portfolio_path([first, second, future])[:2] == prefix
    assert build_v8_portfolio_path([first, second, mutated_future])[:2] == prefix

    with pytest.raises(ValueError, match="strogo chronologichny"):
        build_v8_portfolio_path([second, first])
    with pytest.raises(ValueError, match="strogo chronologichny"):
        build_v8_portfolio_path([first, first])


def test_decision_contract_is_locked_without_future_roll_filtering() -> None:
    """Sohranyaet staryi contract sleeve pri budushchem roll i ineligible new contract."""
    first = _snapshot(1)
    second = _snapshot(
        2,
        contracts=("BRZ5", "MXZ5", "RIZ5", "SiZ5"),
        nominal=(False, False, False, False),
    )
    path = build_v8_portfolio_path([first, second])

    assert _target_map(path[1])[("BR", "BRV5")] == pytest.approx(
        _target_map(path[0])[("BR", "BRV5")]
    )
    assert _target_map(path[1])[("BR", "BRZ5")] == 0.0
    assert path[1].active_sleeves[0].assets[0].contract_id == "BRV5"
    assert path[1].new_sleeve.assets[0].eligibility_reason == (
        "nominal_span_ineligible_at_decision"
    )


def test_full_fixed_asset_snapshot_and_pre_2026_are_mandatory() -> None:
    """Otkazyvaet nepolnyi universe i zablokirovannyi 2026 holdout."""
    base = _snapshot(1)
    with pytest.raises(ValueError, match="BR,MIX,RI,SI"):
        DecisionModelSnapshot(
            decision_at=base.decision_at,
            factor_location=2.0,
            factor_scale=1.0,
            factor_decision_score=0.8,
            assets=base.assets[:-1],
        )
    with pytest.raises(ValueError, match="2026 holdout"):
        DecisionModelSnapshot(
            decision_at=datetime(2026, 1, 2, 18, 50, tzinfo=MOSCOW),
            factor_location=2.0,
            factor_scale=1.0,
            factor_decision_score=0.8,
            assets=base.assets,
        )


def test_constructor_constants_exactly_match_final_sealed_protocol() -> None:
    """Svyazyvaet vse pravila portfolio s final'nym config SHA b6f99b8b."""
    config = load_v8_research_config(V8_CONFIG_PATH)

    assert_v8_portfolio_constants_match_protocol(config.portfolio)
