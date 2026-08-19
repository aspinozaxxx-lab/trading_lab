"""Testy causal'noi futures-paneli, manifestov, as-of i holdout bar'era."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.panel import (
    PROTECTED_HOLDOUT_START,
    build_causal_development_panel,
    derive_common_session_calendar,
    verify_and_load_futures_manifest,
)
from market_lab.futures.roll import RollPlannerConfig

STORAGE_CODES = {  # Storage-kody synthetic universa, vklyuchaya alias RTS -> RI.
    "SI": "Si",
    "RI": "RTS",
    "BR": "BR",
    "MIX": "MIX",
}


def _sha256(path: Path) -> str:
    """Vychislyaet testovyi SHA-256 malogo artefakta."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pair(root: Path, stem: str, frame: pd.DataFrame) -> dict[str, Any]:
    """Sozdaet minimal'nuyu raw/parquet paru s chestnym manifest record."""
    raw_path = root / f"raw/futures_v5/{stem}.json.gz"
    parquet_path = root / f"processed/futures_v5/{stem}.parquet"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "url": "https://iss.moex.com/test?from=2018-01-01&till=2025-12-31",
        "payload": {"test": {"columns": [], "data": []}},
    }
    serialized = json.dumps(
        {"requests": [request]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    raw_path.write_bytes(gzip.compress(serialized, compresslevel=6, mtime=0))
    frame.to_parquet(parquet_path, index=False)

    def record(path: Path) -> dict[str, Any]:
        """Stroit odin artifact record dlya synthetic manifesta."""
        return {
            "path": path.relative_to(root).as_posix(),
            "rows": len(frame),
            "pages": 1,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    return {"raw": record(raw_path), "parquet": record(parquet_path)}


def _daily_row(
    trading_date: pd.Timestamp,
    secid: str,
    asset_code: str,
    price: float,
    volume: float = 1_000.0,
    open_interest: float = 10_000.0,
) -> dict[str, Any]:
    """Stroit validnuyu daily-stroku downloader-skhemy."""
    return {
        "trade_date": trading_date,
        "board_id": "RFUD",
        "secid": secid,
        "asset_code": asset_code,
        "open": price,
        "high": price * 1.01,
        "low": price * 0.99,
        "close": price * 1.002,
        "settle": price * 1.001,
        "volume": volume,
        "value": price * volume,
        "num_trades": 100,
        "open_interest": open_interest,
        "reported_trade_activity": True,
        "ohlc_complete": True,
        "ohlc_missing_with_activity": False,
        "has_trade": True,
        "has_settlement": True,
    }


def _save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Sohranyaet testovyi manifest s BOM, kak production writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def _manifest_fixture(
    root: Path,
    segments: list[tuple[str, str, pd.DataFrame]],
) -> tuple[Path, dict[str, Any]]:
    """Sobiraet polnyi minimal'nyi downloader manifest dlya odnogo asset."""
    canonical_ids = sorted({canonical_id for canonical_id, _, _ in segments})
    series = pd.DataFrame(
        [
            {
                "canonical_contract_id": canonical_id,
                "secid": segments[0][1],
                "name": canonical_id,
                "start_date": pd.Timestamp("2023-01-01"),
                "expiration_date": pd.Timestamp(canonical_id.rsplit(":", 1)[1]),
                "asset_code": "Si",
                "underlying_asset": "USD000UTSTOM",
                "is_traded": False,
            }
            for canonical_id in canonical_ids
        ]
    )
    excluded = pd.DataFrame(columns=series.columns)
    boards = pd.DataFrame(
        [{"secid": secid, "boardid": "RFUD"} for _, secid, _ in segments]
    )
    segment_catalog = pd.DataFrame(
        [
            {
                "canonical_segment_id": f"segment:{index}",
                "canonical_contract_id": canonical_id,
                "secid": secid,
                "boardid": "RFUD",
                "segment_start": frame["trade_date"].min(),
                "segment_end": frame["trade_date"].max(),
            }
            for index, (canonical_id, secid, frame) in enumerate(segments)
        ]
    )
    participant = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2024-01-02"),
                "asset_code": "Si",
                "is_physical": flag,
                "persons_long": 1,
                "persons_short": 1,
                "open_position_long": 100,
                "open_position_short": 90,
                "oi_change_long": 0,
                "oi_change_short": 0,
            }
            for flag in (False, True)
        ]
    )
    catalog = {
        "series": _write_pair(root, "Si/catalog/series", series),
        "excluded": _write_pair(root, "Si/catalog/excluded", excluded),
        "boards": _write_pair(root, "Si/catalog/boards", boards),
        "segments": _write_pair(root, "Si/catalog/segments", segment_catalog),
        "participant_oi": _write_pair(root, "Si/participant_oi", participant),
    }
    segment_artifacts: list[dict[str, Any]] = []
    for index, (canonical_id, secid, frame) in enumerate(segments):
        segment_artifacts.append(
            {
                "canonical_segment_id": f"segment:{index}",
                "canonical_contract_id": canonical_id,
                "secid": secid,
                "boardid": "RFUD",
                "requested_start": frame["trade_date"].min().date().isoformat(),
                "requested_end": frame["trade_date"].max().date().isoformat(),
                "daily": _write_pair(root, f"Si/segments/segment_{index}/daily", frame),
                "candles_10m": None,
            }
        )
    manifest = {
        "schema_version": 1,
        "source": "official anonymous MOEX ISS",
        "asset": {"asset_code": "Si"},
        "requested_start": "2018-01-01",
        "requested_end": "2025-12-31",
        "protected_from": "2026-01-01",
        "counts": {
            "contracts": len(series),
            "excluded": len(excluded),
            "board_segments": len(segment_catalog),
            "daily_rows": sum(len(frame) for _, _, frame in segments),
            "candle_rows": 0,
            "participant_oi_rows": len(participant),
        },
        "catalog_artifacts": catalog,
        "segment_artifacts": segment_artifacts,
    }
    manifest_path = root / "processed/futures_v5/Si/manifest_2018-01-01_2025-12-31.json"
    _save_manifest(manifest_path, manifest)
    return manifest_path, manifest


def _synthetic_universe(
    dates: pd.DatetimeIndex,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Stroit chetyre asseta s dvumya simultaneous kontraktami i participant OI."""
    observations: dict[str, pd.DataFrame] = {}
    participants: dict[str, pd.DataFrame] = {}
    front_expiry = pd.Timestamp(dates[-2])
    next_expiry = pd.Timestamp(dates[-1])
    for asset_index, (logical, storage) in enumerate(STORAGE_CODES.items()):
        daily_rows: list[dict[str, Any]] = []
        participant_rows: list[dict[str, Any]] = []
        for index, trading_date in enumerate(dates):
            front = _daily_row(
                trading_date,
                f"{logical}F",
                storage,
                100.0 + asset_index * 20.0 + index,
            )
            front["canonical_contract_id"] = (
                f"{storage}:{logical}F:{front_expiry.date().isoformat()}"
            )
            front["expiration_date"] = front_expiry
            following = _daily_row(
                trading_date,
                f"{logical}N",
                storage,
                102.0 + asset_index * 20.0 + index,
                volume=100.0,
                open_interest=1_000.0,
            )
            following["canonical_contract_id"] = (
                f"{storage}:{logical}N:{next_expiry.date().isoformat()}"
            )
            following["expiration_date"] = next_expiry
            daily_rows.extend((front, following))
            for physical in (False, True):
                participant_rows.append(
                    {
                        "trade_date": trading_date,
                        "asset_code": storage,
                        "is_physical": physical,
                        "open_position_long": 1_000 + 10 * index + int(physical),
                        "open_position_short": 900 + 5 * index + int(physical),
                    }
                )
        observations[logical] = pd.DataFrame(daily_rows)
        participants[logical] = pd.DataFrame(participant_rows)
    return observations, participants


@pytest.mark.parametrize("tamper", ["bytes", "sha256", "rows"])
def test_manifest_verification_rejects_bytes_hash_and_rows(
    tmp_path: Path,
    tamper: str,
) -> None:
    """Proveryaet vse tri nezavisimye artifact-invarianta manifesta."""
    frame = pd.DataFrame(
        [_daily_row(pd.Timestamp("2024-01-02"), "SiH4", "Si", 90.0)]
    )
    manifest_path, manifest = _manifest_fixture(
        tmp_path,
        [("Si:SiH4:2024-03-21", "SiH4", frame)],
    )
    daily = manifest["segment_artifacts"][0]["daily"]
    if tamper == "bytes":
        path = tmp_path / daily["parquet"]["path"]
        with path.open("ab") as stream:
            stream.write(b"x")
    elif tamper == "sha256":
        daily["parquet"]["sha256"] = "0" * 64
        _save_manifest(manifest_path, manifest)
    else:
        daily["raw"]["rows"] = 2
        daily["parquet"]["rows"] = 2
        manifest["counts"]["daily_rows"] = 2
        _save_manifest(manifest_path, manifest)
    with pytest.raises(ValueError, match="bytes|SHA-256|rows"):
        verify_and_load_futures_manifest(tmp_path, manifest_path)


def test_storage_aliases_stitch_without_overlap_and_keep_contract_id(tmp_path: Path) -> None:
    """Proveryaet disjoint aliases odnogo kontrakta i hard-error pri overlap."""
    first = pd.DataFrame(
        [_daily_row(pd.Timestamp("2024-01-02"), "SiH4", "Si", 90.0)]
    )
    second = pd.DataFrame(
        [_daily_row(pd.Timestamp("2024-01-03"), "SiH4_2024", "Si", 91.0)]
    )
    contract_id = "Si:SiH4:2024-03-21"
    manifest_path, _ = _manifest_fixture(
        tmp_path,
        [(contract_id, "SiH4", first), (contract_id, "SiH4_2024", second)],
    )
    verified = verify_and_load_futures_manifest(tmp_path, manifest_path)
    assert len(verified.observations) == 2
    assert verified.observations["canonical_contract_id"].eq(contract_id).all()
    assert set(verified.observations["storage_secid"]) == {"SiH4", "SiH4_2024"}
    overlap_root = tmp_path / "overlap"
    overlapping = second.copy()
    overlapping["trade_date"] = pd.Timestamp("2024-01-02")
    overlap_manifest, _ = _manifest_fixture(
        overlap_root,
        [(contract_id, "SiH4", first), (contract_id, "SiH4_2024", overlapping)],
    )
    with pytest.raises(ValueError, match="overlap/dublikat"):
        verify_and_load_futures_manifest(overlap_root, overlap_manifest)


def test_holdout_rows_and_manifest_period_are_hard_blocked(tmp_path: Path) -> None:
    """Proveryaet zapret kak deklaracii, tak i skrytoi market-stroki 2026."""
    future = pd.DataFrame(
        [_daily_row(pd.Timestamp("2026-01-05"), "SiH6", "Si", 100.0)]
    )
    manifest_path, manifest = _manifest_fixture(
        tmp_path,
        [("Si:SiH6:2026-03-19", "SiH6", future)],
    )
    with pytest.raises(ValueError, match="protected holdout"):
        verify_and_load_futures_manifest(tmp_path, manifest_path)
    manifest["requested_end"] = "2026-01-05"
    _save_manifest(manifest_path, manifest)
    with pytest.raises(ValueError, match="protected holdout"):
        verify_and_load_futures_manifest(tmp_path, manifest_path)


def test_common_calendar_curve_and_participant_asof_use_only_factual_dates() -> None:
    """Proveryaet bez-fabrikacii calendar, same-close curve i yavno predydushchii OI."""
    dates = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-09", "2024-01-10"]
    )
    observations, participants = _synthetic_universe(dates)
    missing_date = pd.Timestamp("2024-01-05")
    observations["BR"] = observations["BR"].loc[
        observations["BR"]["trade_date"] != missing_date
    ]
    calendar = derive_common_session_calendar(observations)
    assert list(calendar) == [value for value in dates if value != missing_date]
    result = build_causal_development_panel(
        observations,
        participants,
        roll_config=RollPlannerConfig(hard_fallback_sessions=0),
    )
    assert missing_date not in set(result.panel["trade_date"])
    row = result.panel.loc[
        (result.panel["trade_date"] == pd.Timestamp("2024-01-09"))
        & result.panel["asset_code"].eq("SI")
    ].iloc[0]
    assert row["curve_observed_through"] == pd.Timestamp("2024-01-09")
    expected_yield = (row["front_settle"] / row["next_settle"] - 1.0) * (
        365.0
        / (row["next_expiration_date"] - row["front_expiration_date"]).days
    )
    assert row["roll_yield"] == pytest.approx(expected_yield)
    assert row["participant_source_date"] == pd.Timestamp("2024-01-03")
    assert row["participant_lag_sessions"] == 1
    assert result.audit["business_days_fabricated"] == 0


def test_future_mutation_and_append_do_not_rewrite_existing_panel() -> None:
    """Proveryaet future-mutation i append-only invariant pri exact izvestnom kalendare."""
    dates = pd.to_datetime(
        [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-09",
            "2024-01-10",
            "2024-01-11",
            "2024-01-12",
            "2024-01-15",
            "2024-01-16",
        ]
    )
    observations, participants = _synthetic_universe(dates)
    baseline = build_causal_development_panel(
        observations,
        participants,
        roll_config=RollPlannerConfig(hard_fallback_sessions=0),
    )
    cutoff = pd.Timestamp("2024-01-11")
    changed_observations = {asset: frame.copy() for asset, frame in observations.items()}
    changed_participants = {asset: frame.copy() for asset, frame in participants.items()}
    for frame in changed_observations.values():
        future = frame["trade_date"] > cutoff
        frame.loc[future, ["open", "high", "low", "close", "settle"]] *= 1.7
        frame.loc[future, ["volume", "open_interest"]] *= 3.0
    for frame in changed_participants.values():
        frame.loc[frame["trade_date"] > cutoff, "open_position_long"] *= 4
    changed = build_causal_development_panel(
        changed_observations,
        changed_participants,
        roll_config=RollPlannerConfig(hard_fallback_sessions=0),
    )
    pd.testing.assert_frame_equal(
        baseline.panel.loc[baseline.panel["trade_date"] <= cutoff].reset_index(drop=True),
        changed.panel.loc[changed.panel["trade_date"] <= cutoff].reset_index(drop=True),
    )
    prefix_observations = {
        asset: frame.loc[frame["trade_date"] <= cutoff].copy()
        for asset, frame in observations.items()
    }
    prefix_participants = {
        asset: frame.loc[frame["trade_date"] <= cutoff].copy()
        for asset, frame in participants.items()
    }
    prefix = build_causal_development_panel(
        prefix_observations,
        prefix_participants,
        roll_config=RollPlannerConfig(hard_fallback_sessions=0),
        expiry_session_calendar=dates,
    )
    pd.testing.assert_frame_equal(
        prefix.panel,
        baseline.panel.loc[baseline.panel["trade_date"] <= cutoff].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        prefix.active_contract_map,
        baseline.active_contract_map.loc[
            baseline.active_contract_map["effective_date"] <= cutoff
        ].reset_index(drop=True),
    )


def test_unfilled_roll_preserves_position_and_invalidates_feature_row() -> None:
    """Proveryaet carry starogo kontrakta vmesto skrytogo cash pri nepolnom rolle."""
    dates = pd.date_range("2024-01-02", periods=7, freq="B")
    observations, participants = _synthetic_universe(dates)
    si = observations["SI"].copy()
    next_contract = si["secid"].eq("SIN")
    si.loc[next_contract & (si["trade_date"] >= dates[1]), "volume"] = 5_000.0
    si.loc[next_contract & (si["trade_date"] >= dates[1]), "open_interest"] = 50_000.0
    old_contract = si["secid"].eq("SIF")
    failed_date = dates[3]
    failed = old_contract & si["trade_date"].eq(failed_date)
    si.loc[failed, ["open", "high", "low", "close"]] = np.nan
    si.loc[failed, "ohlc_complete"] = False
    si.loc[failed, "ohlc_missing_with_activity"] = True
    observations["SI"] = si
    result = build_causal_development_panel(
        observations,
        participants,
        roll_config=RollPlannerConfig(
            confirmation_days=2,
            hard_fallback_sessions=0,
            dominance_ratio=1.0,
        ),
    )
    active = result.active_contract_map.loc[
        (result.active_contract_map["effective_date"] == failed_date)
        & result.active_contract_map["asset_code"].eq("SI")
    ].iloc[0]
    assert active["action"] == "carry_unfilled_roll"
    assert bool(active["carry_unfilled"])
    assert "SIF" in str(active["contract_id"])
    assert not bool(active["feature_input_valid"])
    panel = result.panel.loc[
        (result.panel["trade_date"] == failed_date)
        & result.panel["asset_code"].eq("SI")
    ].iloc[0]
    assert panel["active_contract_carry_unfilled"]
    assert not panel["active_contract_valid"]
    assert pd.isna(panel["open"])


def test_core_builder_rejects_direct_holdout_date() -> None:
    """Proveryaet holdout-bar'er dazhe v obhode manifest-loadera."""
    dates = pd.to_datetime(["2025-12-30", "2026-01-05"])
    observations, participants = _synthetic_universe(dates)
    with pytest.raises(ValueError, match="protected holdout"):
        build_causal_development_panel(
            observations,
            participants,
            protected_from=PROTECTED_HOLDOUT_START,
        )


def test_panel_rolls_to_future_expiry_on_factual_development_open() -> None:
    """Proveryaet year-end roll bez 2026 market rows i bez lozhnogo calendar carry."""
    dates = pd.to_datetime(
        [
            "2025-12-08",
            "2025-12-09",
            "2025-12-10",
            "2025-12-11",
            "2025-12-12",
            "2025-12-15",
            "2025-12-16",
            "2025-12-17",
            "2025-12-18",
            "2025-12-19",
        ]
    )
    observations, participants = _synthetic_universe(dates)
    for frame in observations.values():
        front = frame["secid"].astype(str).str.endswith("F")
        frame.loc[front, "expiration_date"] = dates[-3]
        frame.loc[~front, "expiration_date"] = pd.Timestamp("2026-03-19")
    result = build_causal_development_panel(
        observations,
        participants,
        roll_config=RollPlannerConfig(hard_fallback_sessions=2),
    )
    for asset in STORAGE_CODES:
        active = result.active_contract_map.loc[
            result.active_contract_map["asset_code"].eq(asset)
        ]
        rolled = active.loc[active["action"].eq("roll")]
        assert len(rolled) == 1
        assert str(rolled.iloc[0]["contract_id"]).split(":")[1].endswith("N")
        assert active["expiry_horizon_censored"].any()
        assert not active["action"].eq("carry_calendar_horizon").any()
    assert (
        result.active_contract_map["effective_date"] < pd.Timestamp("2026-01-01")
    ).all()
