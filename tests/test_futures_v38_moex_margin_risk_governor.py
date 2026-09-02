"""Tests for the sealed V38 official MOEX MR1 governor."""

from __future__ import annotations

import pandas as pd

from market_lab import futures_v38_moex_margin_risk_governor as subject


def test_protocol_seals_zero_change_asset_specific_reduction() -> None:
    protocol = subject.load_protocol()

    assert protocol["margin_risk_governor"]["threshold"] == (
        "exact_positive_change_above_zero"
    )
    assert protocol["margin_risk_governor"]["global_cross_asset_cash_switch"] is False
    assert protocol["validation"]["number_of_variants"] == 1


def test_governor_blocks_only_asset_with_positive_weekly_mr1_change() -> None:
    decision_dates = pd.to_datetime(["2021-01-08", "2021-01-15", "2021-01-22"])
    weights = pd.DataFrame(
        [
            {
                "decision_date": decision,
                "asset": asset,
                "target_weight": 0.10,
                "provenance": "frozen_v27",
            }
            for decision in decision_dates
            for asset in subject.v12.ASSETS
        ]
    )
    rows = []
    for index, decision in enumerate(decision_dates):
        for asset, code in subject.ASSET_MAPPING.items():
            mr1 = 0.10 + (0.02 if asset == "SI" and index >= 1 else 0.0)
            rows.append(
                {
                    "tradedate": decision,
                    "assetcode": code,
                    "mr1": mr1,
                    "updatetime": f"{decision.date()} 18:00:00",
                    "archive_query_date": decision,
                    "available_at_utc": pd.Timestamp(decision).tz_localize("UTC")
                    + pd.Timedelta(hours=15),
                    "retrieved_at_utc": pd.Timestamp("2026-09-02T00:00:00Z"),
                }
            )
    source = subject.MarginRiskVerification(
        frame=pd.DataFrame(rows).sort_values(
            ["assetcode", "available_at_utc"], ignore_index=True
        ),
        checks={"synthetic": True},
        manifest_sha256="synthetic",
        audit_sha256="synthetic",
    )

    result = subject.apply_margin_risk_governor(weights, source)
    governed = result.weights.set_index(["decision_date", "asset"])

    assert governed.loc[(pd.Timestamp("2021-01-15"), "SI"), "target_weight"] == 0.0
    assert governed.loc[(pd.Timestamp("2021-01-15"), "RI"), "target_weight"] == 0.10
    assert governed.loc[(pd.Timestamp("2021-01-22"), "SI"), "target_weight"] == 0.10
    assert (
        governed["target_weight"].abs()
        <= governed["pre_margin_risk_target_weight"].abs()
    ).all()
    assert all(result.checks.values())
