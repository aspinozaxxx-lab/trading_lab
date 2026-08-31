"""Tests for the sealed V15 leverage and causal collateral-income accounting."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult


def _ledger(margin: float = 100_000.0) -> FuturesPortfolioLedgerResult:
    frame = pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2020-12-30", "2021-01-04", "2021-01-05"]),
            "ending_cash": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "intraday_adverse_equity": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "modeled_initial_margin": [margin, margin, margin],
        }
    )
    return FuturesPortfolioLedgerResult(
        ledger=frame,
        positions=pd.DataFrame(),
        orders=pd.DataFrame(),
        metrics={},
        execution_complete=True,
    )


def _ruonia() -> v15.RuoniaVerification:
    return v15.RuoniaVerification(
        frame=pd.DataFrame(
            {
                "observation_date": pd.to_datetime(["2020-12-28", "2021-01-04"]),
                "available_at": pd.to_datetime(
                    ["2020-12-29T21:00:00Z", "2021-01-04T21:00:00Z"], utc=True
                ),
                "ruonia_percent": [10.0, 100.0],
            }
        ),
        checks={"synthetic": True},
    )


def test_protocol_is_sealed_and_directly_tests_twenty_percent_goal() -> None:
    protocol = v15.load_protocol()

    assert protocol["protocol_id"] == "futures_v15_levered_ruonia_collateral_v1"
    assert protocol["leverage"]["target_weight_multiplier"] == pytest.approx(2.0)
    assert protocol["collateral_income"]["applied_rate_fraction"] == pytest.approx(0.50)
    assert "primary_combined_cagr_at_least_0_20" in protocol["promotion_rule"]["require_all"]
    assert protocol["live_trading_allowed"] is False
    assert v15.v12.sha256_file(v15.CONFIG_PATH) == v15.CONFIG_SHA256


def test_leverage_doubles_frozen_targets_without_changing_relative_signs() -> None:
    weights = pd.DataFrame(
        {
            "decision_date": [pd.Timestamp("2021-01-01")] * 4,
            "asset": list(v15.v12.ASSETS),
            "target_weight": [0.25, -0.20, 0.15, -0.10],
            "provenance": ["v12"] * 4,
        }
    )

    levered = v15.build_levered_weights(weights)

    indexed = levered.set_index("asset")
    assert indexed.loc["SI", "target_weight"] == pytest.approx(0.50)
    assert indexed.loc["RI", "target_weight"] == pytest.approx(-0.40)
    assert indexed.loc["BR", "target_weight"] == pytest.approx(0.30)
    assert indexed.loc["MIX", "target_weight"] == pytest.approx(-0.20)
    assert indexed.loc["SI", "v12_target_weight"] == pytest.approx(0.25)
    assert levered["target_weight"].abs().sum() == pytest.approx(1.40)


def test_execution_mapping_is_frozen_v12_then_doubled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly = pd.DataFrame(
        {
            "decision_date": [pd.Timestamp("2021-01-04")],
            "asset": ["SI"],
            "target_weight": [0.60],
            "provenance": ["v12"],
        }
    )
    mapped = pd.DataFrame(
        {
            "effective_date": [pd.Timestamp("2021-01-05")],
            "decision_date": [pd.Timestamp("2021-01-04")],
            "observed_through": [pd.Timestamp("2021-01-04")],
            "asset_code": ["SI"],
            "contract_id": ["SiH1"],
            "target_weight": [0.60],
            "provenance": ["v12-mapped"],
        }
    )
    base = v15.v12.TargetBuild(
        targets=mapped,
        decision_audit=pd.DataFrame({"decision_date": [pd.Timestamp("2021-01-04")]}),
        weekly_decisions=1,
        roll_decisions=0,
    )

    def fake_builder(weights: pd.DataFrame, active: pd.DataFrame) -> v15.v12.TargetBuild:
        pd.testing.assert_frame_equal(weights, weekly)
        assert active.empty
        return base

    monkeypatch.setattr(v15.v12, "build_execution_targets", fake_builder)
    result = v15.build_levered_execution_targets(weekly, pd.DataFrame())

    assert result.targets.loc[0, "v12_target_weight"] == pytest.approx(0.60)
    assert result.targets.loc[0, "target_weight"] == pytest.approx(1.20)
    assert result.weekly_decisions == 1
    assert result.roll_decisions == 0


def _levered_targets(weights: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "effective_date": [pd.Timestamp("2021-01-05")] * 4,
            "decision_date": [pd.Timestamp("2021-01-04")] * 4,
            "asset_code": list(v15.v12.ASSETS),
            "contract_id": ["SiH1", "RIH1", "BRG1", pd.NA],
            "target_weight": weights,
        }
    )


def test_levered_target_gate_accepts_two_x_and_rejects_any_excess() -> None:
    calendar = pd.DatetimeIndex([pd.Timestamp("2021-01-05")])
    accepted = v15._normalize_levered_targets(
        _levered_targets([1.20, -0.40, 0.20, 0.0]), calendar, v15.v12.ASSETS
    )

    assert accepted["target_weight"].abs().sum() == pytest.approx(1.80)
    with pytest.raises(ValueError, match="target_weight"):
        v15._normalize_levered_targets(
            _levered_targets([2.01, 0.0, 0.0, 0.0]), calendar, v15.v12.ASSETS
        )
    with pytest.raises(ValueError, match="Gross target"):
        v15._normalize_levered_targets(
            _levered_targets([1.20, -0.90, 0.0, 0.0]), calendar, v15.v12.ASSETS
        )


def test_levered_ledger_always_restores_frozen_normalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = v15.ledger_engine._normalize_targets

    def fail_before_pnl(*_args: object, **_kwargs: object) -> None:
        assert v15.ledger_engine._normalize_targets is v15._normalize_levered_targets
        raise RuntimeError("synthetic pre-PnL failure")

    monkeypatch.setattr(v15.ledger_engine, "run_futures_portfolio_ledger", fail_before_pnl)
    with pytest.raises(RuntimeError, match="synthetic pre-PnL failure"):
        v15.run_levered_portfolio_ledger(
            pd.DataFrame(), pd.DataFrame(), v15.LeveredLedgerConfig()
        )

    assert v15.ledger_engine._normalize_targets is original


def test_collateral_uses_only_rate_known_at_interval_start_and_clips_oos() -> None:
    evaluation = v15.evaluate_collateral_income(_ledger(), _ruonia())
    audit = evaluation.audit

    expected_first = 700_000.0 * 0.05 * 3.0 / 365.0
    expected_second = 700_000.0 * 0.05 * 1.0 / 365.0
    assert audit.loc[0, "calendar_days"] == 3
    assert audit.loc[0, "eligible_balance"] == pytest.approx(700_000.0)
    assert audit.loc[0, "ruonia_percent"] == pytest.approx(10.0)
    assert audit.loc[1, "ruonia_percent"] == pytest.approx(10.0)
    assert audit.loc[0, "interest_rub"] == pytest.approx(expected_first)
    assert audit.loc[1, "interest_rub"] == pytest.approx(expected_second)
    assert evaluation.metrics["collateral_income_rub"] == pytest.approx(
        expected_first + expected_second
    )
    assert evaluation.combined_ledger.loc[0, "cumulative_collateral_interest"] == 0.0
    assert evaluation.combined_ledger.loc[2, "combined_ending_equity"] == pytest.approx(
        1_000_000.0 + expected_first + expected_second
    )


def test_margin_and_operational_buffers_can_reduce_eligible_balance_to_zero() -> None:
    evaluation = v15.evaluate_collateral_income(_ledger(margin=600_000.0), _ruonia())

    assert evaluation.audit["eligible_balance"].eq(0.0).all()
    assert evaluation.metrics["collateral_income_rub"] == 0.0
    assert evaluation.combined_ledger["combined_ending_equity"].eq(1_000_000.0).all()


def test_missing_rate_fails_closed() -> None:
    missing = v15.RuoniaVerification(
        frame=pd.DataFrame(
            columns=["observation_date", "available_at", "ruonia_percent"]
        ),
        checks={"synthetic": True},
    )

    with pytest.raises(ValueError, match="missing causal RUONIA"):
        v15.evaluate_collateral_income(_ledger(), missing)


def test_ruonia_identity_proves_publication_lag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = pd.to_datetime(["2018-01-09", "2020-01-10", "2025-12-29"])
    publications = pd.to_datetime(["2018-01-10", "2020-01-13", "2025-12-30"])
    available = (publications + pd.Timedelta(days=1)).tz_localize(
        v15.MOSCOW_TIMEZONE
    ).tz_convert("UTC")
    frame = pd.DataFrame(
        {
            "source": "cbr",
            "series_id": "ruonia",
            "observation_date": observations,
            "publication_date": publications,
            "available_at": available,
            "value": [6.88, 6.10, 15.85],
            "availability_rule": "publication_date_plus_one_calendar_day",
        }
    )
    monkeypatch.setattr(v15, "RUONIA_ROWS", 3)

    verified = v15.verify_ruonia(frame)

    assert len(verified.frame) == 3
    assert all(verified.checks.values())
    broken = frame.copy()
    broken.loc[0, "available_at"] = pd.Timestamp("2018-01-10T00:00:00Z")
    with pytest.raises(ValueError, match="available_at"):
        v15.verify_ruonia(broken)


def test_sidecar_names_the_sealed_protocol() -> None:
    sidecar = Path(v15.CONFIG_PATH).with_suffix(".sha256")
    digest, name = sidecar.read_text(encoding="utf-8-sig").split()

    assert digest == v15.CONFIG_SHA256
    assert name == v15.CONFIG_PATH.name
