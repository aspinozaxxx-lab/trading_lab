"""Synthetic event selection, exact successor and non-portfolio reporting checks."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import ofz_v67_auction_concession as screen


def cfg():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def fixture():
    dates = pd.bdate_range("2021-01-04", periods=70)
    frames = []
    for i, duration in enumerate([1000, 900, 1100], start=1):
        frames.append(
            pd.DataFrame(
                {
                    "trade_date": dates,
                    "security_id": f"SU2620{i}RMFS{i}",
                    "value_rub": 20000000.0,
                    "open_clean_pct": 100 + np.arange(70) * (0.1 if i == 1 else 0.0),
                    "duration_days": duration,
                    "currency_id": "SUR",
                    "face_unit": "RUB",
                    "available_at_utc": (
                        dates.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
                    ).tz_convert("UTC"),
                }
            )
        )
    a = pd.DataFrame(
        {
            "document_id": [1],
            "event_kind": ["primary_result"],
            "ofz_type": ["ПД"],
            "publication_date": [dates[30]],
            "issue_code": ["26201RMFS"],
            "available_at": [
                (
                    dates[30].tz_localize("Europe/Moscow")
                    + pd.Timedelta(hours=23, minutes=59, seconds=59)
                ).tz_convert("UTC")
            ],
        }
    )
    return pd.concat(frames, ignore_index=True), a


def test_exact_next_open_and_five_session_exit_with_matched_controls():
    h, a = screen.prepare(*fixture(), cfg())
    chosen = screen.choose(h, a, cfg())
    assert chosen.status.tolist() == ["selected"]
    assert chosen.control_1.tolist() == ["SU26202RMFS2"]
    assert chosen.control_2.tolist() == ["SU26203RMFS3"]
    out = screen.evaluate(chosen, h, cfg()).iloc[0]
    dates = sorted(h.trade_date.unique())
    assert out.entry_date == dates[31] and out.exit_date == dates[36]
    assert out.decision_at > a.available_at.iloc[0]
    assert out.evaluation_status == "complete"
    assert np.isclose(out.primary_gross_bps, (103.6 / 103.1 - 1) * 10000)
    assert out.control_gross_bps == 0 and out.excess_bps == out.primary_gross_bps


def test_future_prices_liquidity_and_duration_never_select_past_controls():
    raw, a = fixture()
    h, events = screen.prepare(raw, a, cfg())
    expected = screen.choose(h, events, cfg())
    raw.loc[
        raw.trade_date.gt(a.publication_date.iloc[0]),
        ["open_clean_pct", "value_rub", "duration_days"],
    ] *= 100
    changed, events = screen.prepare(raw, a, cfg())
    pd.testing.assert_frame_equal(expected, screen.choose(changed, events, cfg()))


def test_coauctioned_bonds_cannot_be_controls_and_missing_is_explicit():
    raw, a = fixture()
    a = pd.concat([a, a.assign(document_id=2, issue_code="26202RMFS")], ignore_index=True)
    h, events = screen.prepare(raw, a, cfg())
    chosen = screen.choose(h, events, cfg())
    assert chosen.status.eq("controls_missing").all()
    result, daily = screen.summarize(screen.evaluate(chosen, h, cfg()), cfg())
    assert daily.empty and result["complete_events"] == 0 and result["cagr"] is None
    assert result["verdict"] == "REJECT_STAGE1"


def test_missing_exit_does_not_pick_another_price_or_erase_coverage():
    raw, a = fixture()
    h, events = screen.prepare(raw, a, cfg())
    chosen = screen.choose(h, events, cfg())
    dates = sorted(h.trade_date.unique())
    h.loc[h.trade_date.eq(dates[36]) & h.security_id.eq("SU26201RMFS1"), "open_clean_pct"] = np.nan
    out = screen.evaluate(chosen, h, cfg())
    assert len(out) == 1 and out.evaluation_status.iloc[0] == "missing_entry_or_exit_price"
    metrics, _ = screen.summarize(out, cfg())
    assert metrics["selected_events"] == 1 and metrics["coverage"] == 0


def test_protected_duplicate_and_late_feature_rows_fail_or_mask():
    raw, a = fixture()
    bad = raw.copy()
    bad.loc[0, "trade_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.prepare(bad, a, cfg())
    with pytest.raises(ValueError, match="duplicate"):
        screen.prepare(pd.concat([raw, raw.iloc[:1]]), a, cfg())
    raw.loc[raw.security_id.eq("SU26201RMFS1"), "available_at_utc"] += pd.Timedelta(days=2)
    h, events = screen.prepare(raw, a, cfg())
    assert screen.choose(h, events, cfg()).status.iloc[0] == "primary_not_eligible"


def test_same_day_cluster_and_stage2_pass_never_invents_nav_metrics():
    dates = pd.DatetimeIndex(
        [d for year in range(2021, 2026) for d in pd.bdate_range(f"{year}-01-04", periods=12)]
    )
    evaluation = pd.DataFrame(
        {
            "publication_date": dates,
            "status": "selected",
            "evaluation_status": "complete",
            "primary_gross_bps": 80 + np.arange(60) % 5,
            "control_gross_bps": 10.0,
            "excess_bps": 70 + np.arange(60) % 5,
        }
    )
    result, daily = screen.summarize(pd.concat([evaluation, evaluation]), cfg())
    assert len(daily) == 60 and result["complete_events"] == 120
    assert result["verdict"] == "STAGE2_CANDIDATE"
    assert (
        result["cagr"] is None and result["sharpe"] is None and result["maximum_drawdown"] is None
    )
    assert result["portfolio_trades"] == 0 and result["goal_verified"] is False
