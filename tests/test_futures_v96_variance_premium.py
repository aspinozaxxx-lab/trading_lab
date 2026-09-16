"""Synthetic tests only: bounded dates, variance units, causal months and ledger."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v96_variance_premium as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


def fixture():
    dates = pd.bdate_range("2018-01-02", "2021-05-31")
    x = np.arange(len(dates))
    calendar = pd.DataFrame({"source_date": dates, "next_session": dates + pd.offsets.BDay()})
    sp = pd.DataFrame(
        {"source_date": dates, "sp500_present": True, "sp500": 1000 * np.exp(x * 0.001)}
    )
    vix = pd.DataFrame(
        {
            "observation_date": dates,
            "vix_close": 10 + x * 0.01,
            "available_at": (dates + pd.Timedelta(hours=23, minutes=59))
            .tz_localize("America/Chicago")
            .tz_convert("UTC"),
        }
    )
    active = pd.concat(
        [
            pd.DataFrame(
                {
                    "decision_date": pd.Series(dates).shift(1),
                    "observed_through": pd.Series(dates).shift(1),
                    "effective_date": dates,
                    "asset_code": a,
                    "contract_id": a + "A",
                    "plan_tradable": True,
                    "roll": False,
                }
            )
            for a in ("BR", "MIX", "RI", "SI")
        ],
        ignore_index=True,
    )
    return calendar, sp, vix, active


def test_csv_all_dates_before_numeric_conversion_and_missing_preserved():
    data = b"observation_date,SP500\n2018-01-02,100.12\n2018-01-03,.\n"
    f = screen.parse_sp500(data)
    assert f.sp500.iloc[0] == 100.12 and np.isnan(f.sp500.iloc[1])
    assert "sp500" not in screen.parse_sp500(data, metadata_only=True)
    for bad, match in (
        (b"2018-01-02,invalid\n2026-01-01,999\n", "protected"),
        (b"2018-01-03,100\n2018-01-02,101\n", "unordered"),
        (b"2018-01-02,100\n2018-01-02,101\n", "unordered"),
        (b"2018-01-02,100,extra\n", "width"),
        (b"2018-01-02,NaN\n", "format"),
        (b"2018-01-02,0\n", "invalid"),
    ):
        with pytest.raises(ValueError, match=match):
            screen.parse_sp500(b"observation_date,SP500\n" + bad)


def test_variance_units_21_exact_sessions_and_252_median_excludes_current():
    calendar, sp, vix, _ = fixture()
    s = screen.features(calendar, sp, vix, config())
    assert s.realized_variance.iloc[:21].isna().all()
    np.testing.assert_allclose(s.realized_variance.iloc[21:], 252 * 0.001**2, rtol=1e-10)
    assert s.prior_median.iloc[:273].isna().all()
    assert s.prior_median.iloc[273] == pytest.approx(s.vrp_proxy.iloc[21:273].median())
    assert s.high.iloc[273:].all()


def test_missing_session_cannot_compress_returns_or_rank_window():
    calendar, sp, vix, _ = fixture()
    pos = 400
    for broken in (
        sp.drop(index=pos),
        sp.assign(sp500=sp.sp500.mask(sp.index == pos)),
        sp.assign(sp500_present=sp.sp500_present.mask(sp.index == pos, False)),
    ):
        s = screen.features(calendar, broken, vix, config())
        assert s.log_return.iloc[pos : pos + 2].isna().all()
        assert s.realized_variance.iloc[pos : pos + 22].isna().all()
        assert not s.ready.iloc[pos : pos + 274].any()
        assert s.ready.iloc[pos + 274]


def test_clock_waits_next_session_end_and_unknown_clock_does_not_disappear():
    calendar, sp, vix, _ = fixture()
    s = screen.features(calendar, sp, vix, config())
    r = s.loc[s.source_date.eq("2021-01-29")].iloc[0]
    assert r.available_at_utc == pd.Timestamp("2021-02-02T04:59:59Z")
    vix.loc[vix.observation_date.eq("2021-01-28"), "available_at"] = pd.NaT
    bad = screen.features(calendar, sp, vix, config())
    r = bad.loc[bad.source_date.eq("2021-01-28")].iloc[0]
    assert not r.ready and pd.notna(r.available_at_utc)
    assert np.isnan(r.vrp_proxy)
    assert not bad.loc[bad.source_date.ge("2021-01-28"), "ready"].any()


def test_source_does_not_follow_redirects():
    with pytest.raises(ValueError, match="redirect"):
        screen.NoRedirect().redirect_request(None, None, 302, None, None, "https://example.com")


def test_monthly_three_cohorts_and_constant_control_use_same_masks():
    calendar, sp, vix, active = fixture()
    state = screen.features(calendar, sp, vix, config())
    signals = screen.targets(active, state, config())
    p, c = signals["primary"], signals["control"]
    assert p.loc[~p.terminal_flat, "target_weight"].eq(0.45).all()
    assert c.loc[~c.terminal_flat, "target_weight"].eq(0.225).all()
    assert (p.source_date < p.selection_date).all()
    assert (p.selection_date <= p.decision_date).all()
    assert (p.decision_date < p.effective_date).all()
    assert p.loc[p.terminal_flat, "target_weight"].eq(0).all()
    assert p.loc[p.decision_date.eq("2021-02-01"), "source_date"].eq("2021-01-28").all()
    # Most recent invalid state blocks the cohort: no fallback to a ready older row.
    state.loc[state.source_date.eq("2021-01-28"), "ready"] = False
    signals = screen.targets(active, state, config())
    p, c = signals["primary"], signals["control"]
    blocked = p.decision_date.between("2021-02-01", "2021-04-30")
    assert p.loc[blocked, "feature_unavailable"].all()
    assert p.loc[blocked, "target_weight"].eq(0).all()
    assert c.loc[blocked, "target_weight"].eq(0).all()
    assert p.loc[p.decision_date.eq("2021-05-03"), "target_weight"].eq(0.45).all()


def test_low_month_changes_only_next_cohort_and_no_short_or_leverage():
    calendar, sp, vix, active = fixture()
    state = screen.features(calendar, sp, vix, config())
    state.loc[state.source_date.eq("2021-01-28"), "high"] = False
    p = screen.targets(active, state, config())["primary"]
    part = p.loc[p.decision_date.between("2021-02-01", "2021-04-30")]
    assert part.target_weight.to_numpy() == pytest.approx(0.3)
    assert p.target_weight.between(0, 0.45).all()


def test_future_mutation_leaves_past_features_and_targets_unchanged():
    calendar, sp, vix, active = fixture()
    changed = sp.copy()
    cutoff = pd.Timestamp("2021-02-12")
    changed.loc[changed.source_date.gt(cutoff), "sp500"] *= 3
    a, b = [screen.features(calendar, f, vix, config()) for f in (sp, changed)]
    pd.testing.assert_frame_equal(a.loc[a.source_date.le(cutoff)], b.loc[b.source_date.le(cutoff)])
    ta, tb = [screen.targets(active, f, config())["primary"] for f in (a, b)]
    pd.testing.assert_frame_equal(
        ta.loc[ta.decision_date.le(cutoff)], tb.loc[tb.decision_date.le(cutoff)]
    )


def test_protected_or_duplicate_source_and_noncausal_map_fail():
    calendar, sp, vix, active = fixture()
    for col in ("source_date", "next_session"):
        bad = calendar.copy()
        bad.loc[4, col] = pd.Timestamp("2026-01-01" if col == "source_date" else "2018-01-01")
        with pytest.raises(ValueError, match="calendar"):
            screen.features(bad, sp, vix, config())
    with pytest.raises(ValueError, match="source"):
        screen.features(calendar, pd.concat([sp, sp.iloc[:1]]), vix, config())
    bad = active.copy()
    bad.loc[5, "observed_through"] = pd.Timestamp("2025-01-01")
    with pytest.raises(ValueError, match="noncausal"):
        screen.targets(bad, screen.features(calendar, sp, vix, config()), config())


def test_existing_four_arm_ledger_has_only_cost_losses_on_flat_prices(tmp_path):
    calendar, sp, vix, active = fixture()
    cfg = config()
    signals = screen.targets(active, screen.features(calendar, sp, vix, cfg), cfg)
    dates = sorted(signals["primary"].effective_date.unique())
    market = pd.DataFrame(
        [
            {
                "session_date": d,
                "asset_code": a,
                "contract_id": a + "A",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "settle": 100.0,
                "volume": 1e7,
                "sizing_point_value": 100.0,
                "accounting_point_value": 100.0,
                "tick_size": 0.01,
                "fee_per_contract": 1.0,
                "initial_margin": 1000.0,
            }
            for d in dates
            for a in cfg["assets"]
        ]
    )
    case = screen.engine.simulate_case(
        tmp_path / "case", signals, market, {"ready_asset_date_fraction": 1.0}, cfg, "synthetic"
    )
    for arm in ("primary", "control"):
        for value in case["metrics"][arm].values():
            assert value["execution_complete"] and not value["terminal_carried"]
            assert value["gross_vm_pnl"] == pytest.approx(0)
            assert value["net_pnl"] == pytest.approx(-value["total_cost"])
        assert case["metrics"][arm]["double"]["net_pnl"] < case["metrics"][arm]["base"]["net_pnl"]
    assert case["assessment"]["verdict"] == "REJECT_STAGE1"
    with pytest.raises(FileExistsError):
        screen.engine.simulate_case(
            tmp_path / "case", signals, market, {"ready_asset_date_fraction": 1.0}, cfg, "synthetic"
        )
