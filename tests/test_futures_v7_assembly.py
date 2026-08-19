"""Testy real-shaped causal assembly futures-v7 bez PnL i train."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.session_timing import legacy_forts_decision_calendar
from market_lab.futures_v7.assembly import (
    V7_EXECUTION_OVERLAY_COLUMNS,
    assemble_v7_arrays,
    load_v7_training_arrays,
    persist_v7_assembly,
)
from market_lab.futures_v7.config import V7_ASSETS, V7_BAR_FEATURES, V7_DAILY_FEATURES

SYNTHETIC_SESSIONS = 28  # Zapas dlya daily-20 i rolling intraday-36.
SYNTHETIC_BARS_PER_INTERVAL = 45  # Factual 10m bars bez synthetic fill.


def _fixture() -> dict[str, pd.DataFrame]:
    """Stroit four-asset intervals, roll, old leg i PIT macro context."""
    calendar = pd.bdate_range("2024-01-03", periods=SYNTHETIC_SESSIONS)
    timing = legacy_forts_decision_calendar(calendar)
    roll_date = pd.Timestamp(timing.iloc[12]["effective_date"])
    active_rows: list[dict[str, object]] = []
    panel_rows: list[dict[str, object]] = []
    observation_rows: list[dict[str, object]] = []
    bars: list[dict[str, object]] = []
    previous_date: pd.Timestamp | None = None
    for date_index, trade_date in enumerate(calendar):
        timing_match = timing.loc[timing["effective_date"].eq(trade_date)]
        previous_decision = (
            None if timing_match.empty else pd.Timestamp(timing_match.iloc[0]["decision_at"])
        )
        for asset_index, asset in enumerate(V7_ASSETS):
            rolled = asset == "RI" and trade_date >= roll_date
            active_contract = f"{asset}:C2" if rolled else f"{asset}:C1"
            adjustment = -100.0 if rolled else 0.0
            raw_base = 200.0 if rolled else 100.0 + asset_index * 20.0
            daily_open = raw_base + date_index * 0.4
            if asset == "SI" and date_index == 8:
                daily_open += 3.0
            active_rows.append(
                {
                    "effective_date": trade_date,
                    "decision_date": previous_date,
                    "asset_code": asset,
                    "contract_id": active_contract,
                    "forward_additive_adjustment": adjustment,
                    "chain_id": 2 if rolled else 1,
                    "open": daily_open,
                    "high": daily_open + 2.0,
                    "low": daily_open - 2.0,
                    "settle": daily_open + 0.5,
                    "volume": 50_000.0,
                    "expiration_date": trade_date + pd.Timedelta(days=60),
                }
            )
            adjusted_close = raw_base + adjustment + date_index * 0.4 + 0.5
            panel_rows.append(
                {
                    "trade_date": trade_date,
                    "asset_code": asset,
                    "active_chain_id": 2 if rolled else 1,
                    "close": adjusted_close,
                    "open_interest": 100_000.0 + date_index * 100.0 + asset_index,
                    "roll_yield": 0.01 + asset_index * 0.001,
                    "participant_source_date": previous_date,
                    "participant_lag_sessions": 1 if previous_date is not None else np.nan,
                    "participant_snapshot_complete": previous_date is not None,
                    "physical_long": 600.0,
                    "physical_short": 400.0,
                    "legal_long": 450.0,
                    "legal_short": 550.0,
                }
            )
            contracts = {active_contract}
            if asset == "RI" and trade_date >= roll_date:
                contracts.add("RI:C1")
            for contract in sorted(contracts):
                contract_rolled = contract.endswith("C2")
                contract_base = 200.0 if contract_rolled else 100.0 + asset_index * 20.0
                exact_open = contract_base + date_index * 0.4
                observation_rows.append(
                    {
                        "trade_date": trade_date,
                        "asset_code": asset,
                        "canonical_contract_id": contract,
                        "open": (
                            exact_open + 3.0
                            if asset == "SI" and date_index == 8
                            else exact_open
                        ),
                        "high": exact_open + 2.0,
                        "low": exact_open - 2.0,
                        "settle": exact_open + 0.5,
                        "volume": 50_000.0,
                        "reported_trade_activity": True,
                    }
                )
                if previous_decision is None:
                    continue
                missing_active = asset == "MIX" and date_index == 16 and contract == active_contract
                if missing_active:
                    continue
                for bar_index in range(SYNTHETIC_BARS_PER_INTERVAL):
                    timestamp = previous_decision + pd.Timedelta(
                        minutes=10 + 10 * bar_index
                    )
                    price = exact_open + 0.01 * bar_index
                    bars.append(
                        {
                            "timestamp": timestamp,
                            "end_timestamp": timestamp + pd.Timedelta(minutes=9, seconds=59),
                            "asset_code": "RTS" if asset == "RI" else asset,
                            "logical_symbol": asset,
                            "canonical_contract_id": contract,
                            "canonical_segment_id": f"segment:{contract}",
                            "secid": contract.replace(":", ""),
                            "board_id": "RFUD",
                            "open": price,
                            "high": price + 1.0,
                            "low": price - 1.0,
                            "close": price + 0.2,
                            "volume": 1_000.0 + bar_index,
                            "value": 0.0,
                        }
                    )
        previous_date = pd.Timestamp(trade_date)
    earliest = pd.Timestamp("2023-12-01T12:00:00Z")
    cbr_rows: list[dict[str, object]] = []
    for series, values in {
        "key_rate": (15.0, 16.0),
        "ruonia": (14.0, 15.5),
        "usd_rub_official": (90.0, 91.0),
    }.items():
        for offset, value in enumerate(values):
            cbr_rows.append(
                {
                    "series_id": series,
                    "observation_date": pd.Timestamp("2023-11-29")
                    + pd.Timedelta(days=offset),
                    "available_at": earliest + pd.Timedelta(days=offset),
                    "value": value,
                }
            )
    score_rows = [
        {
            "decision_at": decision,
            "asset_code": asset,
            "score": 0.1 * (asset_index + 1),
            "available_at": decision - pd.Timedelta(hours=1),
        }
        for decision in timing["decision_at"]
        for asset_index, asset in enumerate(V7_ASSETS)
    ]
    return {
        "bars": pd.DataFrame(bars),
        "active": pd.DataFrame(active_rows),
        "panel": pd.DataFrame(panel_rows),
        "observations": pd.DataFrame(observation_rows),
        "cbr": pd.DataFrame(cbr_rows),
        "cftc": pd.DataFrame(),
        "scores": pd.DataFrame(score_rows),
    }


def _assemble(fixture: dict[str, pd.DataFrame]) -> object:
    """Vyzyvaet assembly s malym oknom, no temi zhe fixed features."""
    return assemble_v7_arrays(
        fixture["bars"],
        fixture["active"],
        fixture["panel"],
        fixture["cbr"],
        fixture["cftc"],
        contract_observations=fixture["observations"],
        sequence_bars=8,
        ssl_horizons=(1, 6),
        precomputed_cftc_scores=fixture["scores"],
    )


def _with_unmodeled_main_session(
    fixture: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    """Udalyaet daily date, no ostavlyaet sil'nuyu factual all-4 10m sessiyu."""
    changed = {name: frame.copy() for name, frame in fixture.items()}
    dates = pd.DatetimeIndex(sorted(changed["panel"]["trade_date"].unique()))
    missing_date = pd.Timestamp(dates[8])
    previous_date = pd.Timestamp(dates[7])
    active_lookup = changed["active"].set_index(["effective_date", "asset_code"])
    main_rows: list[dict[str, object]] = []
    for asset_index, asset in enumerate(V7_ASSETS):
        contract = str(active_lookup.loc[(previous_date, asset), "contract_id"])
        template = changed["bars"].loc[
            changed["bars"]["logical_symbol"].eq(asset)
            & changed["bars"]["canonical_contract_id"].eq(contract)
        ].iloc[0]
        for bar_index in range(36):
            timestamp = (
                missing_date.tz_localize("Europe/Moscow")
                + pd.Timedelta(hours=10, minutes=10 * bar_index)
            ).tz_convert("UTC")
            price = 130.0 + asset_index * 20.0 + bar_index * 0.01
            row = template.to_dict()
            row.update(
                {
                    "timestamp": timestamp,
                    "end_timestamp": timestamp + pd.Timedelta(minutes=9, seconds=59),
                    "open": price,
                    "high": price + 1.0,
                    "low": price - 1.0,
                    "close": price + 0.2,
                    "volume": 2_000.0 + bar_index,
                }
            )
            main_rows.append(row)
    changed["bars"] = pd.concat(
        [changed["bars"], pd.DataFrame(main_rows)], ignore_index=True
    )
    changed["panel"] = changed["panel"].loc[
        ~changed["panel"]["trade_date"].eq(missing_date)
    ].reset_index(drop=True)
    changed["active"] = changed["active"].loc[
        ~changed["active"]["effective_date"].eq(missing_date)
    ].reset_index(drop=True)
    changed["observations"] = changed["observations"].loc[
        ~changed["observations"]["trade_date"].eq(missing_date)
    ].reset_index(drop=True)
    return changed, missing_date


def test_exact_union_timing_features_and_asof_shapes() -> None:
    """Proveryaet end<=decision, fixed poryadok features i factual union grid."""
    result = _assemble(_fixture())
    arrays = result.arrays
    arrays.timing.validate()
    assert arrays.intraday.shape[1:] == (4, 8, len(V7_BAR_FEATURES))
    assert arrays.daily_context.shape[1:] == (4, len(V7_DAILY_FEATURES))
    assert (arrays.timing.bar_times[:, -1] <= arrays.timing.decision_times).all()
    assert result.audit["synthetic_bars_or_forward_fills"] == 0
    assert result.audit["sampling_uses_target_availability"] is False
    assert result.audit["daily_context"]["cbr_asof_checked"] is True
    assert result.audit["daily_context"]["cftc_asof_checked"] is True
    for sample_index in range(len(result.sample_index)):
        valid_exit = result.asset_exit_open_times[sample_index]
        valid_exit = valid_exit[~np.isnat(valid_exit)]
        assert arrays.timing.exit_open_times[sample_index] == valid_exit.max()


def test_overlay_covers_all_contract_legs_and_audits_daily_open_mismatch() -> None:
    """Sohranyaet active i old roll leg, a daily-open raznicu tolko reportit."""
    fixture = _fixture()
    result = _assemble(fixture)
    overlay = result.execution_market_overlay
    assert tuple(overlay.columns) == V7_EXECUTION_OVERLAY_COLUMNS
    assert len(overlay) == len(fixture["observations"])
    assert overlay["contract_id"].eq("RI:C1").sum() > overlay["is_active_contract"].where(
        overlay["contract_id"].eq("RI:C1"), False
    ).sum()
    audit = result.audit["exact_open_overlay"]
    assert audit["daily_open_mismatch_count"] >= 1
    assert audit["mismatch_is_audited_not_filtered"] is True
    weekend = overlay.loc[overlay["decision_date"].dt.dayofweek.eq(4)]
    if not weekend.empty:
        local = weekend["previous_decision_at"].dt.tz_convert("Europe/Moscow")
        assert local.dt.hour.eq(18).all()
        assert local.dt.minute.eq(50).all()

    monday = overlay.loc[overlay["trade_date"].dt.dayofweek.eq(0)]
    if not monday.empty:
        local_entry = monday["entry_timestamp"].dt.tz_convert("Europe/Moscow")
        local_decision = monday["decision_date"]
        available = local_entry.notna()
        assert local_entry.loc[available].dt.normalize().dt.tz_localize(None).eq(
            local_decision.loc[available]
        ).all()
        assert local_entry.loc[available].dt.hour.ge(19).all()


def test_valuation_envelope_preserves_daily_and_interval_references() -> None:
    """Rasshiryaet ledger envelope, ne nazyvaya settle traded extremumom."""
    fixture = _fixture()
    target = fixture["observations"].index[20]
    fixture["observations"].loc[target, "high"] = 1.0
    fixture["observations"].loc[target, "low"] = 0.5
    fixture["observations"].loc[target, "settle"] = 500.0
    result = _assemble(fixture)
    row = result.execution_market_overlay.iloc[target]
    assert row["daily_high_reference"] == 1.0
    assert row["daily_low_reference"] == 0.5
    assert np.isfinite(row["interval_10m_high"])
    assert np.isfinite(row["interval_10m_low"])
    assert row["high"] == 500.0
    assert row["low"] == 0.5
    assert result.audit["exact_open_overlay"][
        "exact_open_outside_reconstructed_high_low_rows"
    ] == 0


def test_roll_target_exits_same_entry_contract_not_new_active_contract() -> None:
    """Dokazyvaet raw old-leg exit label na RI roll boundary."""
    result = _assemble(_fixture())
    audit = result.audit["supervised_target"]
    assert audit["roll_boundary_target_cells"] > 0
    assert audit["roll_boundary_valid_target_cells"] > 0
    samples = result.sample_index.reset_index(drop=True)
    overlay = result.execution_market_overlay
    active = overlay.loc[overlay["is_active_contract"]].set_index(
        ["trade_date", "asset_code"]
    )
    legs = overlay.set_index(["trade_date", "asset_code", "contract_id"])
    for sample_index, sample in samples.iterrows():
        entry_row = active.loc[(sample["entry_trade_date"], "RI")]
        exit_active = active.loc[(sample["exit_trade_date"], "RI")]
        if entry_row["contract_id"] == exit_active["contract_id"]:
            continue
        old_exit = legs.loc[
            (sample["exit_trade_date"], "RI", entry_row["contract_id"]), "open"
        ]
        expected = np.log(float(old_exit) / float(entry_row["open"]))
        assert result.arrays.supervised_target[sample_index, V7_ASSETS.index("RI")] == (
            np.float32(expected)
        )
        break
    else:
        raise AssertionError("Synthetic roll boundary ne naiden")


def test_missing_asset_target_is_masked_without_dropping_calendar_sample() -> None:
    """Ostavlyaet decision sample, kogda MIX exact entry open otsutstvuet."""
    fixture = _fixture()
    baseline = _assemble(fixture)
    missing_date = pd.Timestamp(fixture["active"].iloc[16 * len(V7_ASSETS)]["effective_date"])
    sample_mask = baseline.sample_index["entry_trade_date"].eq(missing_date)
    assert sample_mask.sum() == 1
    sample_index = int(np.flatnonzero(sample_mask.to_numpy())[0])
    assert not baseline.arrays.supervised_valid[sample_index, V7_ASSETS.index("MIX")]
    assert baseline.arrays.supervised_valid[sample_index].sum() >= 1
    assert baseline.audit["supervised_target"]["missing_target_is_masked_not_sample_dropped"]
    assert baseline.audit["exact_open_overlay"]["active_missing_exact_open_rows"] >= 1


def test_zero_target_session_uses_scalar_placeholder_without_sample_drop() -> None:
    """Sohranyaet halt sample s NaT asset times i tol'ko timing placeholder."""
    fixture = _fixture()
    dates = pd.DatetimeIndex(sorted(fixture["panel"]["trade_date"].unique()))
    missing_entry_date = pd.Timestamp(dates[18])
    timing = legacy_forts_decision_calendar(dates)
    row = timing.loc[timing["effective_date"].eq(missing_entry_date)].iloc[0]
    event = fixture["bars"]["timestamp"].ge(row["conservative_open_at"]) & fixture[
        "bars"
    ]["end_timestamp"].le(
        (
            missing_entry_date.tz_localize("Europe/Moscow")
            + pd.Timedelta(hours=18, minutes=50)
        ).tz_convert("UTC")
    )
    fixture["bars"] = fixture["bars"].loc[~event].reset_index(drop=True)
    result = _assemble(fixture)
    sample_mask = result.sample_index["entry_trade_date"].eq(missing_entry_date)
    assert sample_mask.sum() == 1
    sample_index = int(np.flatnonzero(sample_mask.to_numpy())[0])
    assert result.sample_index.loc[sample_index, "entry_time_placeholder"]
    assert not result.arrays.supervised_valid[sample_index].any()
    assert np.isnat(result.asset_entry_open_times[sample_index]).all()
    assert result.audit["entry_time_placeholder_sample_count"] >= 1


def test_unmodeled_all_asset_session_augments_overlay_and_masks_label() -> None:
    """Ne skhlopyvaet execution boundary i maskiruet ambiguous daily target."""
    fixture, missing_date = _with_unmodeled_main_session(_fixture())
    result = _assemble(fixture)
    calendar_audit = result.audit["factual_session_calendar"]
    assert calendar_audit["unmodeled_all_asset_main_session_dates"] == [
        missing_date.date().isoformat()
    ]
    irregular = result.sample_index["irregular_unmodeled_session_gap"]
    assert irregular.sum() == 1
    sample_index = int(np.flatnonzero(irregular.to_numpy())[0])
    assert not result.arrays.supervised_valid[sample_index].any()
    preceding = result.sample_index["following_irregular_unmodeled_session_gap"]
    assert preceding.sum() == 1
    preceding_index = int(np.flatnonzero(preceding.to_numpy())[0])
    assert preceding_index == sample_index - 1
    assert not result.arrays.supervised_valid[preceding_index].any()
    assert result.audit["supervised_target"][
        "irregular_unmodeled_session_gap_cells"
    ] == 2 * len(V7_ASSETS)
    entry_date = result.sample_index.loc[sample_index, "entry_trade_date"]
    overlay = result.execution_market_overlay
    active = overlay.loc[
        overlay["trade_date"].eq(entry_date) & overlay["is_active_contract"]
    ]
    assert active["augmented_boundary_used"].all()
    local_boundary = active["previous_decision_at"].dt.tz_convert("Europe/Moscow")
    assert local_boundary.dt.tz_localize(None).dt.normalize().eq(missing_date).all()
    assert result.audit["irregular_intervals"][
        "active_contract_chain_adjustment_continuity_cells_checked"
    ] == len(V7_ASSETS)


def test_unmodeled_session_gap_requires_active_chain_continuity() -> None:
    """Padaet zakryto, esli collapsed interval peresekaet smenu contracta."""
    fixture, missing_date = _with_unmodeled_main_session(_fixture())
    dates = pd.DatetimeIndex(sorted(fixture["panel"]["trade_date"].unique()))
    following_date = dates[dates > missing_date][0]
    mask = fixture["active"]["effective_date"].eq(following_date) & fixture["active"][
        "asset_code"
    ].eq("BR")
    fixture["active"].loc[mask, "chain_id"] = 99
    with pytest.raises(ValueError, match="Active contract/chain/adjustment"):
        _assemble(fixture)


def test_scheduled_grid_aligns_jittered_raw_ends_and_censors_terminal_bars() -> None:
    """Klyuchuet attention po begin bucket i ne prisvaivaet terminal evening nazad."""
    fixture = _fixture()
    si = fixture["bars"]["logical_symbol"].eq("SI")
    fixture["bars"].loc[si, "end_timestamp"] += pd.Timedelta(seconds=1)
    baseline = _assemble(fixture)
    grid = baseline.audit["scheduled_grid"]
    assert grid["scheduled_union_timestamp_count"] < grid["raw_end_union_timestamp_count"]
    assert grid["scheduled_one_asset_key_count"] == 0
    assert grid["raw_end_one_asset_key_count"] > 0
    last_date = pd.Timestamp(fixture["panel"]["trade_date"].max())
    terminal = (
        last_date.tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=18, minutes=50)
    ).tz_convert("UTC")
    appended: list[dict[str, object]] = []
    for asset in V7_ASSETS:
        template = fixture["bars"].loc[fixture["bars"]["logical_symbol"].eq(asset)].iloc[-1]
        row = template.to_dict()
        row.update(
            {
                "timestamp": terminal + pd.Timedelta(minutes=10),
                "end_timestamp": terminal + pd.Timedelta(minutes=19, seconds=59),
            }
        )
        appended.append(row)
    fixture["bars"] = pd.concat(
        [fixture["bars"], pd.DataFrame(appended)], ignore_index=True
    )
    revised = _assemble(fixture)
    assert revised.audit["active_10m_rows"] == baseline.audit["active_10m_rows"]
    assert revised.audit["terminal_post_decision_10m_rows_censored"] >= len(V7_ASSETS)


def test_future_bar_and_future_cbr_mutation_leave_past_samples_unchanged() -> None:
    """Mutiruet tolko budushchee i sravnivaet ves' causal prefix bitwise."""
    fixture = _fixture()
    baseline = _assemble(fixture)
    cutoff = pd.Timestamp(baseline.sample_index.iloc[8]["decision_at"])
    changed = {name: frame.copy() for name, frame in fixture.items()}
    future_bars = pd.to_datetime(changed["bars"]["timestamp"], utc=True).gt(cutoff)
    for column in ("open", "high", "low", "close"):
        changed["bars"].loc[future_bars, column] *= 2.0
    changed["cbr"] = pd.concat(
        [
            changed["cbr"],
            pd.DataFrame(
                [
                    {
                        "series_id": "key_rate",
                        "observation_date": cutoff.tz_localize(None) + pd.Timedelta(days=5),
                        "available_at": cutoff + pd.Timedelta(days=5),
                        "value": 999.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    revised = _assemble(changed)
    prefix = baseline.sample_index["decision_at"].le(cutoff)
    np.testing.assert_array_equal(
        baseline.arrays.intraday[prefix], revised.arrays.intraday[prefix]
    )
    np.testing.assert_array_equal(
        baseline.arrays.intraday_valid[prefix], revised.arrays.intraday_valid[prefix]
    )
    np.testing.assert_array_equal(
        baseline.arrays.daily_context[prefix], revised.arrays.daily_context[prefix]
    )


def test_atomic_npz_roundtrip_restores_log_price_for_fold_ssl(tmp_path: Path) -> None:
    """Proveryaet chto server trainer poluchaet raw log-price, a ne full SSL label."""
    result = _assemble(_fixture())
    paths = persist_v7_assembly(result, tmp_path)
    loaded = load_v7_training_arrays(paths.arrays_path)
    np.testing.assert_array_equal(loaded.arrays.intraday, result.arrays.intraday)
    np.testing.assert_array_equal(loaded.arrays.supervised_valid, result.arrays.supervised_valid)
    np.testing.assert_array_equal(loaded.log_price, result.log_price)
    np.testing.assert_array_equal(
        loaded.asset_entry_open_times, result.asset_entry_open_times
    )
    np.testing.assert_array_equal(loaded.asset_exit_open_times, result.asset_exit_open_times)
    np.testing.assert_array_equal(
        loaded.sample_trade_dates,
        result.sample_index["trade_date"].to_numpy(dtype="datetime64[ns]"),
    )
    assert paths.arrays_path.name.startswith("assembly_")
    assert paths.execution_overlay_path.name.startswith("execution_open_")
    assert paths.manifest_path.exists()
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8-sig"))
    expected = manifest.pop("manifest_payload_sha256")
    actual = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    assert actual == expected
    assert paths.manifest_path.name == f"manifest_{expected[:16]}.json"
