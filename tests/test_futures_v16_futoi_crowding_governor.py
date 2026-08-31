"""Tests for the sealed V16 causal FUTOI crowding governor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v16_futoi_crowding_governor as v16


def _weekly(decision_date: str = "2021-01-05") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "decision_date": [pd.Timestamp(decision_date)] * len(v16.v12.ASSETS),
            "asset": list(v16.v12.ASSETS),
            "target_weight": [0.25] * len(v16.v12.ASSETS),
            "provenance": ["frozen-v12"] * len(v16.v12.ASSETS),
        }
    )


def _scores(decision_date: str = "2021-01-05") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "decision_date": [pd.Timestamp(decision_date)] * len(v16.v12.ASSETS),
            "asset": list(v16.v12.ASSETS),
            "candidate_score": [1.0] * len(v16.v12.ASSETS),
        }
    )


def _synthetic_futoi(
    prior_date: str = "2021-01-04",
    *,
    include_same_day: bool = True,
) -> v16.FutoiVerification:
    rows: list[dict[str, object]] = []
    for asset in v16.v12.ASSETS:
        parameters = v16.WARMUP_PARAMETERS[asset]
        imbalance = parameters["median"]
        if asset == "BR":
            imbalance += 1.5 * parameters["robust_scale"]
        rows.append(
            {
                "source_date": pd.Timestamp(prior_date),
                "available_at": pd.Timestamp(f"{prior_date}T20:00:00Z"),
                "asset_code": asset,
                "client_group": v16.FUTOI_CLIENT_GROUP,
                "net_position": imbalance,
                "long_position": 1.0,
                "short_position": 0.0,
                "reported_pair_balance_exact": True,
            }
        )
        if include_same_day:
            rows.append(
                {
                    "source_date": pd.Timestamp("2021-01-05"),
                    "available_at": pd.Timestamp("2021-01-05T20:00:00Z"),
                    "asset_code": asset,
                    "client_group": v16.FUTOI_CLIENT_GROUP,
                    "net_position": -0.99,
                    "long_position": 1.0,
                    "short_position": 0.0,
                    "reported_pair_balance_exact": True,
                }
            )
    return v16.FutoiVerification(frame=pd.DataFrame(rows), checks={"synthetic": True})


def test_protocol_is_sealed_and_directly_tests_stability_goal() -> None:
    protocol = v16.load_protocol()

    assert protocol["protocol_id"] == "futures_v16_futoi_crowding_governor_v1"
    assert protocol["futoi_governor"]["aggressive_multiplier"] == pytest.approx(2.0)
    assert protocol["futoi_governor"]["crowded_multiplier"] == pytest.approx(1.0)
    assert protocol["execution"]["unexecutable_target_policy"] == "cancel_and_clip"
    assert "primary_combined_cagr_at_least_0_20" in protocol["promotion_rule"][
        "require_all"
    ]
    assert "primary_combined_maximum_drawdown_at_most_0_25" in protocol[
        "promotion_rule"
    ]["require_all"]
    assert protocol["live_trading_allowed"] is False
    assert v16.v12.sha256_file(v16.CONFIG_PATH) == v16.CONFIG_SHA256


def test_governor_uses_strictly_prior_futoi_and_reduces_crowded_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores = _scores()
    monkeypatch.setattr(v16.v12, "weekly_score_snapshots", lambda _frame: scores)

    governed = v16.build_futoi_governor(_weekly(), scores, _synthetic_futoi())
    indexed = governed.frame.set_index("asset")

    assert indexed["source_date"].eq(pd.Timestamp("2021-01-04")).all()
    assert bool(indexed.loc["BR", "crowded_state"])
    assert indexed.loc["BR", "risk_multiplier"] == pytest.approx(1.0)
    assert indexed.loc["BR", "target_weight"] == pytest.approx(0.25)
    assert indexed.drop(index="BR")["risk_multiplier"].eq(2.0).all()
    assert governed.frame["target_weight"].abs().sum() == pytest.approx(1.75)
    assert all(governed.checks.values())


def test_stale_futoi_fails_closed_to_base_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly = _weekly("2021-01-20")
    scores = _scores("2021-01-20")
    monkeypatch.setattr(v16.v12, "weekly_score_snapshots", lambda _frame: scores)

    governed = v16.build_futoi_governor(
        weekly,
        scores,
        _synthetic_futoi(include_same_day=False),
    )

    assert ~governed.frame["futoi_observed_and_fresh"].any()
    assert governed.frame["risk_multiplier"].eq(1.0).all()
    assert governed.frame["target_weight"].abs().sum() == pytest.approx(1.0)


def test_execution_mapping_carries_last_weekly_governor_state_through_roll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weekly_date = pd.Timestamp("2021-01-04")
    roll_date = pd.Timestamp("2021-01-06")
    target_rows: list[dict[str, object]] = []
    for decision_date, effective_date in (
        (weekly_date, pd.Timestamp("2021-01-05")),
        (roll_date, pd.Timestamp("2021-01-07")),
    ):
        for asset in v16.v12.ASSETS:
            target_rows.append(
                {
                    "effective_date": effective_date,
                    "decision_date": decision_date,
                    "observed_through": decision_date,
                    "asset_code": asset,
                    "contract_id": f"{asset}-synthetic",
                    "target_weight": 0.25,
                    "provenance": "v12-mapped",
                }
            )
    base = v16.v12.TargetBuild(
        targets=pd.DataFrame(target_rows),
        decision_audit=pd.DataFrame({"decision_date": [weekly_date, roll_date]}),
        weekly_decisions=1,
        roll_decisions=1,
    )
    monkeypatch.setattr(v16.v12, "build_execution_targets", lambda *_args: base)
    governor = v16.GovernorBuild(
        frame=pd.DataFrame(
            {
                "decision_date": [weekly_date] * len(v16.v12.ASSETS),
                "asset": list(v16.v12.ASSETS),
                "risk_multiplier": [2.0, 1.0, 1.0, 1.0],
                "crowded_state": [False, True, True, True],
                "source_date": [pd.Timestamp("2020-12-30")] * len(v16.v12.ASSETS),
            }
        ),
        checks={"synthetic": True},
    )

    result = v16.build_execution_targets(_weekly("2021-01-04"), governor, pd.DataFrame())
    indexed = result.targets.set_index(["decision_date", "asset_code"])

    assert indexed.loc[(weekly_date, "SI"), "target_weight"] == pytest.approx(0.50)
    assert indexed.loc[(roll_date, "SI"), "target_weight"] == pytest.approx(0.50)
    assert indexed.loc[(roll_date, "RI"), "target_weight"] == pytest.approx(0.25)
    assert result.weekly_decisions == 1
    assert result.roll_decisions == 1


def test_capacity_aware_ledger_settings_are_fail_closed() -> None:
    settings = v16.CapacityAwareLeveredLedgerConfig()

    assert settings.unexecutable_target_policy == "cancel_and_clip"
    assert settings.maximum_gross_notional_multiple == pytest.approx(2.0)
    with pytest.raises(ValueError, match="settings drift"):
        v16.CapacityAwareLeveredLedgerConfig(maximum_participation=0.02)


def test_sidecar_names_the_sealed_protocol() -> None:
    sidecar = Path(v16.CONFIG_PATH).with_suffix(".sha256")
    digest, name = sidecar.read_text(encoding="utf-8-sig").split()

    assert digest == v16.CONFIG_SHA256
    assert name == v16.CONFIG_PATH.name


def test_invalidated_v16_cannot_be_replayed_as_causal(tmp_path: Path) -> None:
    assert v16.INVALIDATED_FUTOI_PIT_STATES == 932
    assert v16.TOTAL_FUTOI_OOS_STATES == 1_044
    with pytest.raises(RuntimeError, match="V16 invalidated"):
        v16.run_experiment(tmp_path)
