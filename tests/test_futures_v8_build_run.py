"""End-to-end proverki authoritative futures-v8 build runnera."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v8.build_run import (
    V8BuildRequest,
    prepare_v8_build_sources,
    run_authoritative_v8_build,
)
from market_lab.futures_v8.config import V8_ASSETS


def _sha256(path: Path) -> str:
    """Hashiruet synthetic source po exact baitam."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision_at(day: pd.Timestamp) -> pd.Timestamp:
    """Vozvrashchaet D18:50 Moscow kak UTC timestamp."""
    return (
        day.tz_localize("Europe/Moscow") + pd.Timedelta(hours=18, minutes=50)
    ).tz_convert("UTC")


def _write_causal_npz(path: Path, sessions: pd.DatetimeIndex) -> None:
    """Pishet minimal'nyi causal v7 NPZ s sealed 512x12/16 shapes."""
    samples = len(sessions)
    assets = len(V8_ASSETS)
    bars = 512
    decisions = np.asarray(
        [_decision_at(day).tz_localize(None).to_datetime64() for day in sessions],
        dtype="datetime64[ns]",
    )
    bar_times = np.empty((samples, bars), dtype="datetime64[ns]")
    for sample_index, decision in enumerate(decisions):
        bar_times[sample_index] = decision - np.arange(
            bars - 1, -1, -1
        ).astype("timedelta64[m]") * 10
    intraday = np.zeros((samples, assets, bars, 12), dtype=np.float32)
    intraday_valid = np.ones((samples, assets, bars), dtype=bool)
    daily = np.zeros((samples, assets, 16), dtype=np.float32)
    daily[:, :, 3] = 0.02
    log_price = np.broadcast_to(
        np.linspace(4.0, 4.2, bars, dtype=np.float64),
        (samples, assets, bars),
    ).copy()
    np.savez_compressed(
        path,
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily,
        daily_valid=np.ones(daily.shape, dtype=bool),
        asset_valid=np.ones((samples, assets), dtype=bool),
        log_price=log_price,
        bar_times=bar_times.astype(np.int64),
        sample_trade_dates=sessions.to_numpy(dtype="datetime64[ns]").astype(np.int64),
        decision_times=decisions.astype(np.int64),
        supervised_target=np.ones((samples, assets), dtype=np.float32),
        supervised_valid=np.ones((samples, assets), dtype=bool),
    )


def _market_frames(
    sessions: pd.DatetimeIndex,
    *,
    include_protected_row: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stroit factual 19:00/19:20 candles i same-contract active map."""
    candle_rows: list[dict[str, object]] = []
    active_rows: list[dict[str, object]] = []
    for session_index, session in enumerate(sessions):
        for asset_index, asset in enumerate(V8_ASSETS):
            active_rows.append(
                {
                    "effective_date": session,
                    "asset_code": asset,
                    "contract_id": f"{asset}:C1",
                    "forward_additive_adjustment": 0.0,
                }
            )
            if session_index + 1 >= len(sessions):
                continue
            price = 100.0 + asset_index * 10.0 + session_index * 2.0
            decision = _decision_at(session)
            for timestamp in (
                decision + pd.Timedelta(minutes=10),
                decision + pd.Timedelta(minutes=30),
            ):
                candle_rows.append(
                    {
                        "timestamp": timestamp,
                        "end_timestamp": timestamp + pd.Timedelta(minutes=9, seconds=59),
                        "asset_code": asset,
                        "logical_symbol": asset,
                        "canonical_contract_id": f"{asset}:C1",
                        "open": price,
                        "high": price + 1.0,
                        "low": price - 1.0,
                        "close": price,
                        "volume": 1_000.0,
                    }
                )
    if include_protected_row:
        candle_rows.append(
            {
                "timestamp": pd.Timestamp("2026-01-02T16:00:00Z"),
                "end_timestamp": pd.Timestamp("2026-01-02T16:09:59Z"),
                "asset_code": "BR",
                "logical_symbol": "BR",
                "canonical_contract_id": "BR:C1",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000.0,
            }
        )
    return pd.DataFrame(candle_rows), pd.DataFrame(active_rows)


def _source_record(kind: str, path: Path, data_root: Path, rows: int) -> dict[str, object]:
    """Stroit top-manifest record iz uzhe zapisannogo synthetic file."""
    absolute = data_root / path
    return {
        "kind": kind,
        "path": path.as_posix(),
        "rows": rows,
        "bytes": absolute.stat().st_size,
        "sha256": _sha256(absolute),
    }


def _sealed_synthetic_tree(
    tmp_path: Path,
    *,
    include_protected_row: bool = False,
) -> tuple[Path, Path, str]:
    """Pishet 219-file byte-sealed synthetic source tree dlya runner testa."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    sessions = pd.bdate_range("2024-01-02", periods=24)
    npz_relative = Path("processed/v7/source.npz")
    npz_path = data_root / npz_relative
    npz_path.parent.mkdir(parents=True)
    _write_causal_npz(npz_path, sessions)
    candles, active = _market_frames(
        sessions,
        include_protected_row=include_protected_row,
    )
    parquet_records: list[dict[str, object]] = []
    for part in range(219):
        relative = Path("processed/ten_minute") / f"part_{part:03d}.parquet"
        path = data_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = candles if part == 0 else candles.iloc[:0]
        frame.to_parquet(path, index=False)
        parquet_records.append(
            _source_record("official_moex_10m_parquet", relative, data_root, len(frame))
        )
    active_relative = Path("processed/active/active_map.parquet")
    active_path = data_root / active_relative
    active_path.parent.mkdir(parents=True)
    active.to_parquet(active_path, index=False)
    active_record = _source_record(
        "futures_v5_active_contract_map",
        active_relative,
        data_root,
        len(active),
    )
    payload: dict[str, object] = {
        "schema_version": 2,
        "research_status": "development_only_no_pnl_no_training",
        "protected_from": "2026-01-01",
        "arrays": {
            "path": npz_relative.as_posix(),
            "bytes": npz_path.stat().st_size,
            "sha256": _sha256(npz_path),
        },
        "audit": {
            "factual_session_calendar": {
                "source": "verified_10m_distinct_scheduled_buckets_10:00_to_18:50_msk",
                "unmodeled_all_asset_main_session_count": 0,
                "unmodeled_all_asset_main_session_dates": [],
            }
        },
        "source_artifacts": [*parquet_records, active_record],
    }
    payload["manifest_payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    top_relative = Path("processed/v7/top_manifest.json")
    top_path = data_root / top_relative
    top_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    return data_root, top_relative, _sha256(top_path)


def test_pre_io_guard_precedes_missing_manifest_access(tmp_path: Path) -> None:
    """Protected range padaet do lyubogo source path I/O."""
    request = V8BuildRequest(
        data_root=tmp_path / "missing",
        top_manifest_path=Path("missing.json"),
        expected_top_manifest_sha256="0" * 64,
        source_end=date(2026, 1, 1),
    )
    with pytest.raises(ValueError, match="2026"):
        prepare_v8_build_sources(request)


def test_authoritative_runner_builds_reloads_and_reuses_immutable_artifacts(
    tmp_path: Path,
) -> None:
    """Synthetic 222-proof build prohodit persist/reload i ne overwrite repeat."""
    data_root, top_relative, top_sha = _sealed_synthetic_tree(tmp_path)
    request = V8BuildRequest(
        data_root=data_root,
        top_manifest_path=top_relative,
        expected_top_manifest_sha256=top_sha,
    )
    report = run_authoritative_v8_build(request)
    manifest_bytes = report.manifest_path.read_bytes()
    manifest_mtime_ns = report.manifest_path.stat().st_mtime_ns
    assert report.verified_file_count == 222
    assert report.source_candle_rows == 184
    assert report.source_active_map_rows == 96
    assert report.intraday_shape == (24, 4, 512, 12)
    assert report.daily_context_shape == (24, 4, 16)
    assert report.target_shape == (24, 4)
    assert report.target_valid_cells == 72
    assert report.target_invalid_cells == 24
    assert report.arrays_path.is_file()
    assert report.manifest_path.read_bytes().startswith(b"\xef\xbb\xbf")

    repeated = run_authoritative_v8_build(request)
    assert repeated.arrays_path == report.arrays_path
    assert repeated.manifest_path == report.manifest_path
    assert repeated.arrays_sha256 == report.arrays_sha256
    assert repeated.manifest_path.read_bytes() == manifest_bytes
    assert repeated.manifest_path.stat().st_mtime_ns == manifest_mtime_ns


def test_physical_predicate_rejects_any_protected_row_before_assembly(
    tmp_path: Path,
) -> None:
    """Verified file s 2026 row ne mozhet byt' molcha obrezan i prinyat po menshemu sum."""
    data_root, top_relative, top_sha = _sealed_synthetic_tree(
        tmp_path,
        include_protected_row=True,
    )
    request = V8BuildRequest(
        data_root=data_root,
        top_manifest_path=top_relative,
        expected_top_manifest_sha256=top_sha,
    )
    with pytest.raises(ValueError, match="row sum"):
        run_authoritative_v8_build(request)
    assert not (data_root / "processed/futures_v8").exists()
