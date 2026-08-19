"""Testy validity-aware futures-v8 context bez targets, PnL i 2026."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from math import log, sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pyarrow import parquet as parquet_module

from market_lab.futures_v8 import context_run
from market_lab.futures_v8.context_run import (
    MAIN_SESSION_EXPECTED_BUCKETS,
    MAIN_SESSION_MINIMUM_BUCKETS,
    AdjustedDailyObservation,
    CausalSessionContractObservation,
    ContextDependencyProof,
    MainSessionBarObservation,
    PlannedContractObservation,
    RawPitObservation,
    assess_planned_contract,
    audit_pit_standardization,
    build_evaluation_exit_observability,
    build_expanding_pit_standardization,
    build_market_feature_snapshots,
    compare_final_expiration_qa,
    derive_nominal_maturity_date,
    load_context_protocol,
    reconcile_final_daily_panel_qa,
    verify_context_dependency_proofs,
)

# Koren' proekta dlya budushchih byte-seal testov.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Fiksirovannyi fake source hash.
SOURCE_SHA = "a" * 64
# Moscow timezone dlya exact main-session schedule.
MOSCOW = ZoneInfo("Europe/Moscow")


def _dependency_proof(name: str, relative_path: str) -> ContextDependencyProof:
    """Stroit proof iz factual project bytes, no proverka potom ne doveryaet emu."""
    path = PROJECT_ROOT / relative_path
    content = path.read_bytes()
    return ContextDependencyProof(
        name=name,
        relative_path=relative_path,
        sha256=sha256(content).hexdigest(),
        bytes=len(content),
    )


def _all_dependency_proofs() -> tuple[ContextDependencyProof, ...]:
    """Sobiraet exact required bundle iz sealed protocol i dynamic code/catalog."""
    protocol = load_context_protocol()
    proofs = [
        _dependency_proof(name, relative_path)
        for name, (relative_path, _) in protocol.dependency_pins.items()
    ]
    proofs.extend(
        (
            _dependency_proof(
                "aggressive_catalog",
                "configs/futures_v8_aggressive_candidates.yaml",
            ),
            _dependency_proof(
                "aggressive_catalog_sidecar",
                "configs/futures_v8_aggressive_candidates.sha256",
            ),
            _dependency_proof(
                "context_implementation",
                "src/market_lab/futures_v8/context_run.py",
            ),
        )
    )
    return tuple(proofs)


def _decision(day: date) -> datetime:
    """Stroit exact D18:50 Moscow decision v UTC."""
    return datetime.combine(day, time(18, 50), MOSCOW).astimezone(UTC)


def _business_decisions(start: date, count: int) -> tuple[datetime, ...]:
    """Stroit prostoi weekday calendar bez exchange-holiday pretensii."""
    rows: list[datetime] = []
    current = start
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(_decision(current))
        current += timedelta(days=1)
    return tuple(rows)


def _daily_rows(decisions: tuple[datetime, ...]) -> tuple[AdjustedDailyObservation, ...]:
    """Stroit final daily panel tol'ko dlya post-build QA."""
    rows: list[AdjustedDailyObservation] = []
    for index, decision_at in enumerate(decisions):
        adjustment = 100.0
        raw_first_close = 1_000.0 + index
        raw_last_close = raw_first_close + 5.2
        rows.append(
            AdjustedDailyObservation(
                decision_at=decision_at,
                asset_id="BR",
                active_chain_id="BR-forward-adjusted-chain",
                active_contract_id="BRZ5",
                open=raw_first_close - 0.02 + adjustment,
                high=raw_last_close + 0.05 + adjustment,
                low=raw_first_close - 0.05 + adjustment,
                close=raw_last_close + adjustment,
                source_id="active-map-adjusted-daily",
                observation_id=f"daily-{decision_at.date().isoformat()}",
                source_sha256=SOURCE_SHA,
            )
        )
    return tuple(rows)


def _session_contracts(
    decisions: tuple[datetime, ...],
) -> tuple[CausalSessionContractObservation, ...]:
    """Stroit D-known active contract i additive offset do intervala."""
    rows: list[CausalSessionContractObservation] = []
    for index, decision_at in enumerate(decisions):
        previous = decisions[index - 1] if index else decision_at - timedelta(days=1)
        rows.append(
            CausalSessionContractObservation(
                decision_at=decision_at,
                previous_decision_at=previous,
                asset_id="BR",
                contract_id="BRZ5",
                forward_additive_adjustment=100.0,
                known_at=previous,
                source_id="active-map",
                observation_id=f"contract-{decision_at.date().isoformat()}",
                source_sha256=SOURCE_SHA,
            )
        )
    return tuple(rows)


def _session_bars(
    decision_at: datetime,
    session_index: int,
) -> tuple[MainSessionBarObservation, ...]:
    """Stroit exact 53 scheduled bucket s raw end ran'she scheduled close."""
    local_day = decision_at.astimezone(MOSCOW).date()
    rows: list[MainSessionBarObservation] = []
    for bucket in range(MAIN_SESSION_EXPECTED_BUCKETS):
        opened = datetime.combine(local_day, time(10), MOSCOW) + timedelta(minutes=10 * bucket)
        closed = opened + timedelta(minutes=10)
        close = 1_000.0 + session_index + 0.1 * bucket
        rows.append(
            MainSessionBarObservation(
                decision_at=decision_at,
                asset_id="BR",
                contract_id="BRZ5",
                bar_open_at=opened,
                bar_close_at=closed,
                raw_end_at=opened + timedelta(minutes=7),
                open=close - 0.02,
                high=close + 0.05,
                low=close - 0.05,
                close=close,
                volume=float(100 + session_index),
                source_id="moex-iss-10m",
                observation_id=f"bar-{local_day.isoformat()}-{bucket:02d}",
                source_sha256=SOURCE_SHA,
            )
        )
    return tuple(rows)


def _market_fixture(
    count: int = 26,
) -> tuple[
    tuple[datetime, ...],
    tuple[CausalSessionContractObservation, ...],
    tuple[MainSessionBarObservation, ...],
    tuple[AdjustedDailyObservation, ...],
]:
    """Sobiraet warmup i OOS-like market inputs tol'ko dlya BR."""
    decisions = _business_decisions(date(2024, 1, 2), count)
    contracts = _session_contracts(decisions)
    bars = tuple(
        bar
        for index, decision_at in enumerate(decisions)
        for bar in _session_bars(decision_at, index)
    )
    return decisions, contracts, bars, _daily_rows(decisions)


def _market_build(
    decisions: tuple[datetime, ...],
    contracts: tuple[CausalSessionContractObservation, ...],
    bars: tuple[MainSessionBarObservation, ...],
):
    """Vyzyvaet fixed raw-10m market builder."""
    return build_market_feature_snapshots(
        decisions,
        contracts,
        bars,
        raw_10m_source_sha256="b" * 64,
    )


def test_context_protocol_bom_seal_and_transitive_dependency_closure() -> None:
    """Protocol/catalog/code i 10m child tree obrazuyut exact proverennyi closure."""
    protocol = load_context_protocol()
    sidecar = protocol.path.with_suffix(".sha256")
    assert protocol.path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert sidecar.read_bytes().startswith(b"\xef\xbb\xbf")
    assert sha256(protocol.path.read_bytes()).hexdigest() == protocol.sha256
    verified = verify_context_dependency_proofs(_all_dependency_proofs(), protocol)
    assert len(verified.proofs) == len(protocol.required_dependency_names)
    assert verified.main_session_tree.asset_manifest_count == 4
    assert verified.main_session_tree.segment_manifest_count == 219
    assert verified.main_session_tree.parquet_rows == 1_699_545
    assert verified.main_session_tree.child_bundle_sha256 == (
        "622b4f245f6cf16d9e0af99f85e11963600cadc2f21af9c67fc7495646e489e8"
    )


def test_dependency_proofs_reject_escape_duplicate_wrong_bytes_rows_and_code() -> None:
    """Caller assertions ne mogut oboiti path/identity/row/transitive code checks."""
    with pytest.raises(ValueError, match="parent escape"):
        ContextDependencyProof("escape", "../outside", SOURCE_SHA, 0)
    protocol = load_context_protocol()
    proofs = _all_dependency_proofs()
    with pytest.raises(ValueError, match="duplicate name"):
        verify_context_dependency_proofs((*proofs, proofs[0]), protocol)
    first = replace(proofs[0], sha256="f" * 64)
    with pytest.raises(ValueError, match="bytes/hash mismatch"):
        verify_context_dependency_proofs((first, *proofs[1:]), protocol)
    base_index = next(
        index for index, proof in enumerate(proofs) if proof.name == "base_predictions"
    )
    wrong_rows = replace(proofs[base_index], rows=1)
    with pytest.raises(ValueError, match="row-count mismatch"):
        verify_context_dependency_proofs(
            (*proofs[:base_index], wrong_rows, *proofs[base_index + 1 :]),
            protocol,
        )
    code_index = next(
        index for index, proof in enumerate(proofs) if proof.name == "context_implementation"
    )
    wrong_code = replace(proofs[code_index], sha256="f" * 64)
    with pytest.raises(ValueError, match="bytes/hash mismatch"):
        verify_context_dependency_proofs(
            (*proofs[:code_index], wrong_code, *proofs[code_index + 1 :]),
            protocol,
        )


def test_market_formulas_use_raw_exact_close_and_prior20_comparable_sessions() -> None:
    """Proveryaet ATR/range/RV/volume i razdelenie raw/adjusted price basis."""
    decisions, contracts, bars, daily_qa = _market_fixture()
    built = _market_build(decisions, contracts, bars)
    index = 20
    snapshot = built[(decisions[index], "BR")]
    current_bars = _session_bars(decisions[index], index)
    current_rv = sqrt(
        sum(
            (log(current.close) - log(previous.close)) ** 2
            for previous, current in zip(current_bars, current_bars[1:], strict=False)
        )
    )
    baseline_rv = []
    for prior_index in range(20):
        prior_bars = _session_bars(decisions[prior_index], prior_index)
        baseline_rv.append(
            sqrt(
                sum(
                    (log(current.close) - log(previous.close)) ** 2
                    for previous, current in zip(prior_bars, prior_bars[1:], strict=False)
                )
            )
        )
    assert snapshot.decision_market_valid
    assert snapshot.main_session_bucket_count == 53
    assert snapshot.close == pytest.approx(current_bars[-1].close)
    assert snapshot.close_bar_open_at == current_bars[-1].bar_open_at
    assert snapshot.close_bar_scheduled_close_at == current_bars[-1].bar_close_at
    assert snapshot.close_bar_raw_end_at == current_bars[-1].raw_end_at
    assert snapshot.adjusted_signal_close == pytest.approx(daily_qa[index].close)
    assert snapshot.adjusted_signal_open == pytest.approx(daily_qa[index].open)
    assert snapshot.adjusted_signal_high == pytest.approx(daily_qa[index].high)
    assert snapshot.adjusted_signal_low == pytest.approx(daily_qa[index].low)
    assert snapshot.atr_20 == pytest.approx(5.3)
    expected_closes = [1_005.2 + prior + 100.0 for prior in range(21)]
    expected_returns = [
        log(current) - log(previous)
        for previous, current in zip(expected_closes, expected_closes[1:], strict=False)
    ]
    assert snapshot.momentum_20 == pytest.approx(log(expected_closes[-1]) - log(expected_closes[0]))
    assert snapshot.daily_volatility_20 == pytest.approx(
        sqrt(
            sum(
                (value - sum(expected_returns) / len(expected_returns)) ** 2
                for value in expected_returns
            )
            / len(expected_returns)
        )
    )
    assert snapshot.range_position_20 > 1.0
    assert snapshot.volatility_ratio_20 == pytest.approx(current_rv / (sum(baseline_rv) / 20))
    assert snapshot.volume_ratio_20 == pytest.approx(120.0 / 109.5)


def test_daily_ohlc_includes_prior_evening_inside_exact_causal_interval() -> None:
    """Daily open beretsya iz pervogo raw bucket posle previous D18:50."""
    decisions, contracts, bars, _ = _market_fixture()
    index = 20
    decision_at = decisions[index]
    previous = decisions[index - 1]
    opened = previous + timedelta(minutes=10)
    evening = MainSessionBarObservation(
        decision_at=decision_at,
        asset_id="BR",
        contract_id="BRZ5",
        bar_open_at=opened,
        bar_close_at=opened + timedelta(minutes=10),
        raw_end_at=opened + timedelta(minutes=4),
        open=990.0,
        high=991.0,
        low=989.0,
        close=990.5,
        volume=10.0,
        source_id="moex-iss-10m",
        observation_id="prior-evening",
        source_sha256=SOURCE_SHA,
    )
    snapshot = _market_build(decisions, contracts, (*bars, evening))[(decision_at, "BR")]
    assert snapshot.adjusted_signal_open == pytest.approx(1_090.0)
    assert snapshot.adjusted_signal_low == pytest.approx(1_089.0)
    assert snapshot.close == pytest.approx(_session_bars(decision_at, index)[-1].close)


def test_prior_ratio_can_exist_while_daily_history_fails_closed() -> None:
    """RV baseline ostayetsya causal, no missing prior close blokiruet daily features."""
    decisions, contracts, bars, _ = _market_fixture()
    prior = decisions[0]
    without_prior_close = tuple(
        bar
        for bar in bars
        if not (
            bar.decision_at == prior and bar.bar_open_at.astimezone(MOSCOW).time() == time(18, 40)
        )
    )
    snapshot = _market_build(decisions, contracts, without_prior_close)[(decisions[20], "BR")]
    assert not snapshot.decision_market_valid
    assert snapshot.volatility_ratio_20 is not None
    assert snapshot.volume_ratio_20 is not None
    assert snapshot.atr_20 is None
    assert "atr20_insufficient_consecutive_history" in snapshot.reason_codes


def test_exact_close_stale_fallback_and_48_of_53_fail_closed() -> None:
    """Net 18:40 bara ili tol'ko 47 bucketov: close ne beretsya iz bolee rannego bara."""
    decisions, contracts, bars, _ = _market_fixture()
    target = decisions[20]
    no_close = tuple(
        bar
        for bar in bars
        if not (
            bar.decision_at == target and bar.bar_open_at.astimezone(MOSCOW).time() == time(18, 40)
        )
    )
    stale = _market_build(decisions, contracts, no_close)[(target, "BR")]
    assert stale.main_session_bucket_count == 52
    assert stale.close is None
    assert not stale.decision_market_valid
    assert "missing_exact_18_40_to_18_50_close_bar" in stale.reason_codes

    remove_opens = {time(10, minute) for minute in (0, 10, 20, 30, 40, 50)}
    sparse = tuple(
        bar
        for bar in bars
        if not (
            bar.decision_at == target and bar.bar_open_at.astimezone(MOSCOW).time() in remove_opens
        )
    )
    insufficient = _market_build(decisions, contracts, sparse)[(target, "BR")]
    assert insufficient.main_session_bucket_count == MAIN_SESSION_MINIMUM_BUCKETS - 1
    assert not insufficient.decision_market_valid
    assert "main_session_below_48_of_53_buckets" in insufficient.reason_codes


def test_bar_preserves_raw_end_but_uses_scheduled_close_as_availability() -> None:
    """Sparse last trade dopustim, no raw end posle scheduled bucket close zapreshchen."""
    decision_at = _decision(date(2024, 2, 1))
    bar = _session_bars(decision_at, 0)[-1]
    assert bar.raw_end_at < bar.bar_close_at == decision_at
    with pytest.raises(ValueError, match="raw end"):
        replace(bar, raw_end_at=bar.bar_close_at + timedelta(seconds=1))


def test_physical_intraday_parquet_with_2026_timestamp_is_rejected(tmp_path: Path) -> None:
    """Hash-verifiable parquet vse ravno fail-closed, esli physical row popal v 2026."""
    poisoned = tmp_path / "poisoned.parquet"
    pd.DataFrame(
        {
            "timestamp": [datetime(2025, 12, 31, 23, 55, tzinfo=UTC)],
            "end_timestamp": [datetime(2026, 1, 1, tzinfo=UTC)],
        }
    ).to_parquet(poisoned, index=False)
    parquet = parquet_module.ParquetFile(poisoned)
    with pytest.raises(ValueError, match="protected 2026"):
        context_run._require_parquet_pre_holdout_timestamps(poisoned, parquet)


def test_future_append_does_not_mutate_market_prefix() -> None:
    """Dobavlenie sleduyushchego D ne menyaet ni odin predydushchii market hash/value."""
    decisions, contracts, bars, _ = _market_fixture()
    prefix = _market_build(
        decisions[:-1],
        contracts[:-1],
        tuple(bar for bar in bars if bar.decision_at != decisions[-1]),
    )
    full = _market_build(decisions, contracts, bars)
    for key, value in prefix.items():
        assert full[key] == value


def test_forward_additive_daily_chain_does_not_reset_on_contract_roll() -> None:
    """New active contract raw gap kompensiruetsya D-known offset bez reset lookback."""
    decisions, contracts, bars, _ = _market_fixture()
    roll_at = decisions[20]
    rolled_contracts = tuple(
        replace(
            item,
            contract_id="BRH6",
            forward_additive_adjustment=200.0,
            observation_id=f"rolled-{item.observation_id}",
        )
        if item.decision_at >= roll_at
        else item
        for item in contracts
    )
    rolled_bars = tuple(
        replace(
            item,
            contract_id="BRH6",
            open=item.open - 100.0,
            high=item.high - 100.0,
            low=item.low - 100.0,
            close=item.close - 100.0,
            observation_id=f"rolled-{item.observation_id}",
        )
        if item.decision_at >= roll_at
        else item
        for item in bars
    )
    baseline = _market_build(decisions, contracts, bars)[(roll_at, "BR")]
    rolled = _market_build(decisions, rolled_contracts, rolled_bars)[(roll_at, "BR")]
    assert rolled.decision_market_valid
    assert rolled.adjusted_signal_close == pytest.approx(baseline.adjusted_signal_close)
    assert rolled.atr_20 == pytest.approx(baseline.atr_20)
    assert rolled.momentum_20 == pytest.approx(baseline.momentum_20)


def test_final_daily_panel_is_qa_only_and_close_mismatch_is_row_fail_closed() -> None:
    """Panel ne menyaet context; close drift blokiruet publication global'no."""
    decisions, contracts, bars, daily_qa = _market_fixture()
    raw = _market_build(decisions, contracts, bars)
    reconciled, audit = reconcile_final_daily_panel_qa(raw, daily_qa)
    key = (decisions[20], "BR")
    assert reconciled[key].decision_market_valid
    assert audit.close_mismatch_rows == 0
    ohl_changed = tuple(
        replace(item, open=item.open + 0.1, high=item.high + 0.1)
        if item.decision_at == decisions[20]
        else item
        for item in daily_qa
    )
    ohl_reconciled, ohl_audit = reconcile_final_daily_panel_qa(raw, ohl_changed)
    assert ohl_reconciled == raw
    assert ohl_audit.open_mismatch_rows == ohl_audit.high_mismatch_rows == 1
    changed = tuple(
        replace(item, close=item.close + 0.01) if item.decision_at == decisions[20] else item
        for item in daily_qa
    )
    with pytest.raises(ValueError, match="global NO_GO"):
        reconcile_final_daily_panel_qa(raw, changed)


def _pit_row(
    decision_at: datetime,
    asset_id: str | None,
    channel: str,
    value: float,
    observation_id: str,
    available_at: datetime | None = None,
) -> RawPitObservation:
    """Stroit odin PIT raw release s yavnoi available granicei."""
    available = available_at or decision_at
    return RawPitObservation(
        decision_at=decision_at,
        asset_id=asset_id,
        channel=channel,
        raw_value=value,
        published_at=available,
        available_at=available,
        source_id=f"source-{channel}",
        observation_id=observation_id,
        source_sha256=SOURCE_SHA,
    )


def test_cftc_expanding_z_is_unique_release_per_asset_without_key_collision() -> None:
    """BR/RI histories nezavisimy, a stale weekly repeat ne uvelichivaet history count."""
    decisions = _business_decisions(date(2018, 1, 2), 62)
    rows: list[RawPitObservation] = []
    for index, decision_at in enumerate(decisions[:61]):
        rows.append(_pit_row(decision_at, "BR", "cftc_crowd_z", float(index), f"br-{index}"))
        rows.append(
            _pit_row(
                decision_at,
                "RI",
                "cftc_crowd_z",
                float(index * index + 1),
                f"ri-{index}",
            )
        )
    rows.append(
        _pit_row(
            decisions[61],
            "BR",
            "cftc_crowd_z",
            60.0,
            "br-60",
            available_at=decisions[60],
        )
    )
    built = build_expanding_pit_standardization(rows)
    br = built[(decisions[60], "BR", "cftc_crowd_z")]
    ri = built[(decisions[60], "RI", "cftc_crowd_z")]
    stale = built[(decisions[61], "BR", "cftc_crowd_z")]
    assert br.history_count == ri.history_count == 60
    assert br.standardized is not None and ri.standardized is not None
    assert br.standardized.value != ri.standardized.value
    assert stale.history_count == 60
    assert stale.standardized.value == br.standardized.value


def test_global_unique_release_z_is_future_append_invariant() -> None:
    """CBR stale daily snapshots poluchayut odin z, future release ne menyaet prefix."""
    decisions = _business_decisions(date(2018, 1, 2), 63)
    rows = [
        _pit_row(decision_at, None, "key_rate_change_z", float(index), f"rate-{index}")
        for index, decision_at in enumerate(decisions[:61])
    ]
    rows.append(
        _pit_row(
            decisions[61],
            None,
            "key_rate_change_z",
            60.0,
            "rate-60",
            available_at=decisions[60],
        )
    )
    prefix = build_expanding_pit_standardization(rows)
    extended = build_expanding_pit_standardization(
        [*rows, _pit_row(decisions[62], None, "key_rate_change_z", 100.0, "rate-61")]
    )
    key = (decisions[61], None, "key_rate_change_z")
    assert prefix[key] == extended[key]
    assert prefix[key].history_count == 60


def test_key_rate_41_unique_changes_remains_explicitly_sleeping() -> None:
    """Sealed min60 ne adaptiruetsya pod 41 factual key-rate change event."""
    decisions = _business_decisions(date(2018, 1, 2), 41)
    rows = [
        _pit_row(
            decision_at,
            None,
            "key_rate_change_z",
            float(index + 1),
            f"key-rate-change-{index:02d}",
        )
        for index, decision_at in enumerate(decisions)
    ]
    built = build_expanding_pit_standardization(rows)
    audit = audit_pit_standardization(
        built,
        channel="key_rate_change_z",
        decisions=decisions,
    )
    assert audit.unique_observation_ids == 41
    assert audit.standardized_rows == 0
    assert audit.sleeping_rows == 41
    assert audit.maximum_history_count == 40


def test_evaluation_exit_mask_is_exact_independent_calendar_last_five_false() -> None:
    """D_i->D_i+5 mask ne zavisit ot strategy/contract i blokiruet last five entries."""
    decisions = _business_decisions(date(2025, 12, 1), 12)
    built = build_evaluation_exit_observability(decisions)
    for index, decision_at in enumerate(decisions):
        item = built[decision_at]
        if index < len(decisions) - 5:
            assert item.evaluation_exit_observable
            assert item.evaluation_exit_decision_at == decisions[index + 5]
        else:
            assert not item.evaluation_exit_observable
            assert item.evaluation_exit_decision_at is None
        assert len(item.provenance_sha256) == 64


def test_unique_releases_with_equal_available_at_do_not_see_each_other() -> None:
    """Ravno-vremennye releases oba standartizuyutsya tol'ko po strict earlier history."""
    decisions = _business_decisions(date(2018, 1, 2), 62)
    rows = [
        _pit_row(decision_at, None, "usd_rub_return_z", float(index), f"fx-{index}")
        for index, decision_at in enumerate(decisions[:60])
    ]
    shared_available_at = decisions[60]
    rows.extend(
        (
            _pit_row(
                decisions[60],
                None,
                "usd_rub_return_z",
                100.0,
                "fx-a",
                available_at=shared_available_at,
            ),
            _pit_row(
                decisions[61],
                None,
                "usd_rub_return_z",
                200.0,
                "fx-b",
                available_at=shared_available_at,
            ),
        )
    )
    built = build_expanding_pit_standardization(rows)
    first = built[(decisions[60], None, "usd_rub_return_z")]
    second = built[(decisions[61], None, "usd_rub_return_z")]
    assert first.history_count == second.history_count == 60


def test_nominal_contract_proxy_never_uses_final_expiration_for_decision() -> None:
    """RIH2 anomaly ostayetsya otdel'nym QA i ne menyaet D-known proxy result."""
    decision_at = _decision(date(2022, 2, 1))
    observation = PlannedContractObservation(
        decision_at=decision_at,
        asset_id="RI",
        contract_id="RTS:RIH2:2022-03-29",
        contract_code="RIH2",
        known_at=decision_at,
        source_id="active-map",
        observation_id="RI-2022-02-01",
        source_sha256=SOURCE_SHA,
    )
    assessment = assess_planned_contract(observation, decision_at=decision_at, asset_id="RI")
    assert derive_nominal_maturity_date("RI", "RIH2", decision_at.date()) == date(2022, 3, 17)
    assert assessment.planned_contract_valid
    qa = compare_final_expiration_qa(assessment, date(2022, 3, 29))
    assert qa.differs
    assert (
        assessment.provenance_sha256
        == assess_planned_contract(
            observation,
            decision_at=decision_at,
            asset_id="RI",
        ).provenance_sha256
    )


def test_unproved_nominal_mapping_is_cash_not_expiration_fallback() -> None:
    """Neizvestnyi code delaet planned mask false bez fallback na final metadata."""
    decision_at = _decision(date(2025, 1, 10))
    observation = PlannedContractObservation(
        decision_at=decision_at,
        asset_id="BR",
        contract_id="mystery-contract",
        contract_code="UNKNOWN",
        known_at=decision_at,
        source_id="active-map",
        observation_id="BR-unknown",
        source_sha256=SOURCE_SHA,
    )
    assessment = assess_planned_contract(observation, decision_at=decision_at, asset_id="BR")
    assert not assessment.planned_contract_valid
    assert assessment.nominal_maturity_date is None
    assert assessment.reason_codes == ("nominal_maturity_mapping_unproved",)
