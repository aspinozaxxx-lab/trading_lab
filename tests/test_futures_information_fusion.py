"""Testy causal'nogo information fusion bez market returns i seti."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from market_lab.futures.information_fusion import (
    FUSION_ASSETS,
    FUSION_CANDIDATES,
    MACRO_CANDIDATES,
    CausalInformationFusionConfig,
    build_information_conditioned_targets,
    build_macro_conditioned_targets,
)

TEST_CHANNELS = (  # Polnyi zapechatannyi nabor fusion-kanalov.
    "sanctions_russia",
    "geopolitics_russia",
    "russian_credit",
    "global_risk",
    "oil_supply",
    "gas_europe",
    "ruble_attention",
    "russian_monetary",
)


def _frames(periods: int = 100) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stroit polnye base/info/calendar frames bez target ili return label."""
    dates = pd.bdate_range("2023-01-02", periods=periods)
    decision_at = dates.tz_localize("Europe/Moscow") + pd.Timedelta(hours=20)
    decision_at = decision_at.tz_convert("UTC")
    calendar = pd.DataFrame({"trade_date": dates, "decision_at": decision_at})
    base_rows: list[dict[str, object]] = []
    base_scores = {"SI": 0.35, "RI": 0.40, "BR": 0.25, "MIX": 0.45}
    denominator = sum(abs(score) for score in base_scores.values())
    for trade_date in dates:
        for asset in FUSION_ASSETS:
            score = base_scores[asset]
            base_rows.append(
                {
                    "trade_date": trade_date,
                    "asset_code": asset,
                    "target_score": score,
                    "target_weight": score / denominator,
                    "signal_valid": True,
                    "target_session_offset": 1,
                }
            )
    information = pd.DataFrame({"decision_at": decision_at})
    for channel_index, channel in enumerate(TEST_CHANNELS):
        phase = np.arange(periods, dtype=float) + channel_index
        information[f"gdelt_{channel}_attention_surprise"] = 0.15 * np.sin(phase / 9.0)
        information[f"gdelt_{channel}_tone_surprise"] = 0.20 * np.cos(phase / 11.0)
        information[f"gdelt_{channel}_available_at"] = decision_at - pd.Timedelta(days=2)
    information["cbr_ruonia_change"] = 0.01 * np.sin(np.arange(periods) / 5.0)
    information["cbr_key_rate_change"] = 0.02 * np.cos(np.arange(periods) / 13.0)
    information["cbr_usd_rub_official_change"] = 0.1 * np.sin(np.arange(periods) / 7.0)
    for series in ("ruonia", "key_rate", "usd_rub_official"):
        information[f"cbr_{series}_available_at"] = decision_at - pd.Timedelta(days=1)
    return pd.DataFrame(base_rows), information, calendar


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet fusion output dlya strogogo causal sravneniya."""
    return frame.sort_values(["candidate_id", "trade_date", "asset_code"]).reset_index(
        drop=True
    )


def test_fusion_emits_all_precommitted_candidates_with_bounded_gross() -> None:
    """Proveryaet tri kandidata, base-identichnost' i gross ne vyshe 1x."""
    base, information, calendar = _frames()
    result = build_information_conditioned_targets(base, information, calendar)
    assert tuple(result["candidate_id"].drop_duplicates()) == FUSION_CANDIDATES
    gross = result.groupby(["candidate_id", "trade_date"])["candidate_weight"].apply(
        lambda values: values.abs().sum()
    )
    assert (gross <= 1.0 + 1e-12).all()
    base_result = result.loc[result["candidate_id"] == "base_moe"]
    expected = base.sort_values(["trade_date", "asset_code"])["target_weight"].to_numpy()
    np.testing.assert_allclose(base_result["candidate_weight"], expected)
    assert not any("return" in column for column in result.columns)


def test_sleeping_information_expert_wakes_on_news_shock_and_cuts_conflict() -> None:
    """Proveryaet risk-off proekciyu i cash-scale pri konflikte s market signalom."""
    base, information, calendar = _frames()
    last = information.index[-1]
    for channel in (
        "sanctions_russia",
        "geopolitics_russia",
        "russian_credit",
        "global_risk",
    ):
        information.loc[last, f"gdelt_{channel}_attention_surprise"] = 3.0
        information.loc[last, f"gdelt_{channel}_tone_surprise"] = -3.0
    result = build_information_conditioned_targets(base, information, calendar)
    final_date = calendar["trade_date"].iloc[-1]
    overlay = result.loc[
        (result["candidate_id"] == "information_overlay")
        & (result["trade_date"] == final_date)
    ].set_index("asset_code")
    assert overlay.loc["SI", "information_score"] > 0.0
    assert overlay.loc["RI", "information_score"] < 0.0
    assert overlay.loc["MIX", "information_score"] < 0.0
    assert overlay["information_activation"].eq(overlay["information_activation"].iloc[0]).all()
    confirmation = result.loc[
        (result["candidate_id"] == "information_confirmation")
        & (result["trade_date"] == final_date)
    ].set_index("asset_code")
    assert confirmation.loc["RI", "gross_scale"] == pytest.approx(0.25)
    assert confirmation.loc["MIX", "gross_scale"] == pytest.approx(0.25)
    assert confirmation["candidate_weight"].abs().sum() < 1.0


def test_future_information_mutation_cannot_rewrite_past_targets() -> None:
    """Proveryaet invariantnost' proshlogo k novostyam posle cutoff."""
    base, information, calendar = _frames()
    cutoff = calendar["trade_date"].iloc[70]
    baseline = build_information_conditioned_targets(base, information, calendar)
    changed = information.copy()
    future = changed["decision_at"] > calendar.loc[70, "decision_at"]
    feature_columns = [
        column
        for column in changed
        if column.endswith("attention_surprise") or column.endswith("tone_surprise")
    ]
    changed.loc[future, feature_columns] = 3.0
    mutated = build_information_conditioned_targets(base, changed, calendar)
    past_baseline = _sorted(baseline.loc[baseline["trade_date"] <= cutoff])
    past_mutated = _sorted(mutated.loc[mutated["trade_date"] <= cutoff])
    pdt.assert_frame_equal(past_baseline, past_mutated)


def test_appending_future_decisions_preserves_existing_output() -> None:
    """Proveryaet append-only invariant pri dobavlenii pozdnih reshenii."""
    base, information, calendar = _frames()
    shortened_base = base.loc[base["trade_date"] <= calendar["trade_date"].iloc[75]]
    shortened_info = information.iloc[:76]
    shortened_calendar = calendar.iloc[:76]
    short_result = build_information_conditioned_targets(
        shortened_base,
        shortened_info,
        shortened_calendar,
    )
    full_result = build_information_conditioned_targets(base, information, calendar)
    comparable = full_result.loc[
        full_result["trade_date"] <= shortened_calendar["trade_date"].iloc[-1]
    ]
    pdt.assert_frame_equal(_sorted(short_result), _sorted(comparable))


def test_future_availability_timestamp_is_rejected_before_fusion() -> None:
    """Proveryaet fail-closed otkaz pri available_at pozhe decision_at."""
    base, information, calendar = _frames()
    information.loc[10, "gdelt_global_risk_available_at"] = (
        information.loc[10, "decision_at"] + pd.Timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="Budushchaya informaciya"):
        build_information_conditioned_targets(base, information, calendar)


def test_missing_channel_and_incomplete_asset_snapshot_are_rejected() -> None:
    """Proveryaet zapechatannyi channel-set i polnyi chetyrehassetnyi snapshot."""
    base, information, calendar = _frames()
    with pytest.raises(ValueError, match="zapechatannyh kolonok"):
        build_information_conditioned_targets(
            base,
            information.drop(columns="gdelt_oil_supply_tone_surprise"),
            calendar,
        )
    incomplete = base.drop(index=base.index[-1])
    with pytest.raises(ValueError, match="Nepolnyi base snapshot"):
        build_information_conditioned_targets(incomplete, information, calendar)


def test_configuration_rejects_hindsight_friendly_unbounded_values() -> None:
    """Proveryaet fiksirovannye granicy overlay, cash i causal scale."""
    with pytest.raises(ValueError, match="information_budget"):
        CausalInformationFusionConfig(information_budget=0.75)
    with pytest.raises(ValueError, match="CBR scale"):
        CausalInformationFusionConfig(cbr_scale_lookback=10)


def test_explicit_cbr_only_mode_never_pretends_that_news_was_available() -> None:
    """Proveryaet otdel'nye macro-kandidaty i yavnuyu markirovku source mode."""
    base, information, calendar = _frames()
    cbr_columns = [
        "decision_at",
        "cbr_ruonia_change",
        "cbr_key_rate_change",
        "cbr_usd_rub_official_change",
        "cbr_ruonia_available_at",
        "cbr_key_rate_available_at",
        "cbr_usd_rub_official_available_at",
    ]
    cbr = information[cbr_columns].copy()
    cbr.loc[cbr.index[-1], "cbr_usd_rub_official_change"] = 10.0
    cbr.loc[cbr.index[-1], "cbr_key_rate_change"] = 5.0
    result = build_macro_conditioned_targets(base, cbr, calendar)
    assert tuple(result["candidate_id"].drop_duplicates()) == MACRO_CANDIDATES
    assert result["information_source_mode"].eq("cbr_only").all()
    assert result["shock_risk_off"].eq(0.0).all()
    assert result["shock_energy_supply"].eq(0.0).all()
    assert not any(column.startswith("gdelt_") for column in result.columns)
    final = result.loc[
        (result["candidate_id"] == "macro_overlay")
        & (result["trade_date"] == calendar["trade_date"].iloc[-1])
    ].set_index("asset_code")
    assert final.loc["SI", "information_score"] > 0.0
    assert final.loc["RI", "information_score"] < 0.0
