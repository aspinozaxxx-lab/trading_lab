"""Synthetic causal assembly proverki dlya sealed futures-v8 target."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v8.assembly import (
    V8_CAUSAL_V7_KEYS,
    V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES,
    V8_TARGET_HORIZON_COMMON_SESSIONS,
    V8AssemblyResult,
    V8FoldScope,
    V8SourceFileProof,
    V8VerifiedSourceProvenance,
    assemble_v8_from_v7_npz,
    build_v8_fold_scope,
    build_v8_ssl_valid_mask,
    persist_v8_assembly,
    validate_v8_fold_scope,
    verify_v8_source_provenance,
)
from market_lab.futures_v8.config import V8_ASSETS


def _decision_at(day: pd.Timestamp) -> pd.Timestamp:
    """Vozvrashchaet sealed D18:50 Moscow decision v UTC."""
    return (
        day.tz_localize("Europe/Moscow") + pd.Timedelta(hours=18, minutes=50)
    ).tz_convert("UTC")


def _write_v7_npz(
    path: Path,
    sessions: pd.DatetimeIndex,
    *,
    daily_volatility_after_index: int | None = None,
    daily_volatility_after_value: float = 99.0,
    invalid_decision_asset: str | None = None,
) -> None:
    """Pishet namerenno poisoned legacy-label arhiv dlya whitelist-proverki."""
    sample_count = len(sessions)
    asset_count = len(V8_ASSETS)
    bars = 24
    decisions = np.asarray(
        [_decision_at(day).tz_localize(None).to_datetime64() for day in sessions],
        dtype="datetime64[ns]",
    )
    bar_times = np.empty((sample_count, bars), dtype="datetime64[ns]")
    for row, decision in enumerate(decisions):
        bar_times[row] = decision - np.arange(bars - 1, -1, -1).astype("timedelta64[m]") * 10
    intraday = np.zeros((sample_count, asset_count, bars, 12), dtype=np.float32)
    intraday_valid = np.ones(intraday.shape[:3], dtype=bool)
    if invalid_decision_asset is not None:
        intraday_valid[0, V8_ASSETS.index(invalid_decision_asset), -1] = False
    daily = np.zeros((sample_count, asset_count, 16), dtype=np.float32)
    daily[:, :, 3] = 0.02
    if daily_volatility_after_index is not None:
        daily[daily_volatility_after_index:, :, 3] = daily_volatility_after_value
    log_price = np.broadcast_to(
        np.linspace(4.0, 4.2, bars, dtype=np.float64),
        (sample_count, asset_count, bars),
    ).copy()
    # Object metki upadut pod allow_pickle=False, esli v8 loader ih dotronetsya.
    poisoned = np.asarray([{"legacy": "must_not_be_read"}], dtype=object)
    np.savez_compressed(
        path,
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily,
        daily_valid=np.ones(daily.shape, dtype=bool),
        asset_valid=np.ones((sample_count, asset_count), dtype=bool),
        log_price=log_price,
        bar_times=bar_times.astype(np.int64),
        sample_trade_dates=sessions.to_numpy(dtype="datetime64[ns]").astype(np.int64),
        decision_times=decisions.astype(np.int64),
        supervised_target=poisoned,
        supervised_valid=poisoned,
    )


def _fixture(tmp_path: Path, sessions_count: int = 24) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    """Stroit all-contract 10m source i matching active map tol'ko do 2025."""
    sessions = pd.bdate_range("2024-01-02", periods=sessions_count)
    source = tmp_path / "v7_source.npz"
    _write_v7_npz(source, sessions)
    active_rows: list[dict[str, object]] = []
    candle_rows: list[dict[str, object]] = []
    for index, session in enumerate(sessions):
        for asset_number, asset in enumerate(V8_ASSETS):
            active_rows.append(
                {
                    "effective_date": session,
                    "asset_code": asset,
                    "contract_id": f"{asset}:C1",
                    "forward_additive_adjustment": 0.0,
                }
            )
            if index + 1 >= len(sessions):
                continue
            open_at = _decision_at(session) + pd.Timedelta(minutes=30)
            price = 100.0 + asset_number * 10.0 + index * 2.0
            for contract, multiplier in ((f"{asset}:C1", 1.0), (f"{asset}:OLD", 0.5)):
                for timestamp in (open_at - pd.Timedelta(minutes=20), open_at):
                    candle_rows.append(
                        {
                            "timestamp": timestamp,
                            "end_timestamp": timestamp + pd.Timedelta(minutes=9, seconds=59),
                            "logical_symbol": asset,
                            "canonical_contract_id": contract,
                            "open": price * multiplier,
                            "high": price * multiplier + 1.0,
                            "low": price * multiplier - 1.0,
                            "close": price * multiplier,
                            "volume": 1_000.0,
                        }
                    )
    return source, pd.DataFrame(candle_rows), pd.DataFrame(active_rows)


def _verified_sessions() -> pd.DatetimeIndex:
    """Vozvrashchaet explicit factual common-session kalendar synthetic istochnika."""
    return pd.bdate_range("2024-01-02", periods=24)


def _assemble_v8(
    source: Path,
    candles: pd.DataFrame,
    active: pd.DataFrame,
    **kwargs: object,
) -> V8AssemblyResult:
    """Dobavlyaet explicit synthetic factual calendar k kazhdoi validnoi v8 sborke."""
    kwargs.setdefault("allow_unverified_fixture", True)
    kwargs.setdefault("fixture_common_session_dates", _verified_sessions())
    return assemble_v8_from_v7_npz(
        source,
        candles,
        active,
        **kwargs,
    )


def _assemble(tmp_path: Path) -> V8AssemblyResult:
    """Sobiraet regular synthetic source cherez public NPZ granicu."""
    source, candles, active = _fixture(tmp_path)
    return _assemble_v8(source, candles, active)


def test_v8_reads_only_causal_v7_keys_and_has_exact_five_session_target(tmp_path: Path) -> None:
    """Legacy object metki ostayutsya neprochitannymi; entry/exit exact scheduled."""
    result = _assemble(tmp_path)
    assert result.inputs.keys_read == V8_CAUSAL_V7_KEYS
    assert result.targets.valid.shape == (24, len(V8_ASSETS))
    assert result.targets.valid[0].all()
    entry = result.targets.entry_window_open_times[0, 0]
    exit_ = result.targets.exit_window_open_times[0, 0]
    assert entry == np.datetime64("2024-01-02T16:20:00")
    assert exit_ == np.datetime64("2024-01-09T16:20:00")
    assert result.targets.availability_times[0, 0] == np.datetime64("2024-01-09T16:30:00")
    expected_raw = np.log(110.0 / 100.0)
    expected = expected_raw / (0.02 * np.sqrt(V8_TARGET_HORIZON_COMMON_SESSIONS))
    assert result.targets.raw_target[0, 0] == pytest.approx(expected_raw)
    assert result.targets.target[0, 0] == pytest.approx(expected)
    assert not result.targets.valid[-V8_TARGET_HORIZON_COMMON_SESSIONS - 1 :].any()
    assert not result.targets.target[-V8_TARGET_HORIZON_COMMON_SESSIONS - 1 :].any()


def test_future_mutation_cannot_change_completed_target_or_d_known_volatility(
    tmp_path: Path,
) -> None:
    """Mutaciya candles i daily volatility posle complete metki ne menyaet prefix."""
    source, candles, active = _fixture(tmp_path)
    baseline = _assemble_v8(source, candles, active)
    changed = candles.copy()
    future = pd.to_datetime(changed["timestamp"], utc=True).gt(
        pd.Timestamp("2024-01-09T16:30:00Z")
    )
    changed.loc[future, ["open", "high", "low", "close"]] *= 100.0
    changed_source = tmp_path / "v7_source_future_daily.npz"
    _write_v7_npz(
        changed_source,
        pd.bdate_range("2024-01-02", periods=24),
        daily_volatility_after_index=7,
    )
    revised = _assemble_v8(changed_source, changed, active)
    np.testing.assert_array_equal(baseline.targets.target[:1], revised.targets.target[:1])
    np.testing.assert_array_equal(
        baseline.targets.ex_ante_daily_volatility_20[:1],
        revised.targets.ex_ante_daily_volatility_20[:1],
    )


def test_missing_window_roll_and_unpriced_carry_are_asset_masks_not_sample_drops(
    tmp_path: Path,
) -> None:
    """Kazhdoye zapreshchennoe uslovie obnulyaet tol'ko affected asset target cell."""
    source, candles, active = _fixture(tmp_path)
    missing = candles.copy()
    ri_exit = (
        missing["logical_symbol"].eq("RI")
        & missing["canonical_contract_id"].eq("RI:C1")
        & pd.to_datetime(missing["timestamp"], utc=True).eq("2024-01-09T16:20:00Z")
    )
    missing.loc[ri_exit, "volume"] = 0.0
    result = _assemble_v8(source, missing, active)
    assert not result.targets.valid[0, V8_ASSETS.index("RI")]
    assert result.targets.target[0, V8_ASSETS.index("RI")] == 0.0
    assert result.targets.valid[0, V8_ASSETS.index("BR")]

    rolled = active.copy()
    roll = rolled["asset_code"].eq("SI") & rolled["effective_date"].eq("2024-01-05")
    rolled.loc[roll, "contract_id"] = "SI:C2"
    roll_result = _assemble_v8(source, candles, rolled)
    assert not roll_result.targets.valid[0, V8_ASSETS.index("SI")]
    np.testing.assert_array_equal(roll_result.inference_asset_valid, result.inputs.asset_valid)

    unpriced = active.copy()
    unpriced["unpriced_carry"] = False
    unpriced.loc[
        unpriced["asset_code"].eq("MIX") & unpriced["effective_date"].eq("2024-01-05"),
        "unpriced_carry",
    ] = True
    carry_result = _assemble_v8(source, candles, unpriced)
    assert not carry_result.targets.valid[0, V8_ASSETS.index("MIX")]
    assert carry_result.inputs.intraday.shape[0] == 24


def test_real_active_map_carry_flags_and_sparse_completed_window_are_respected(
    tmp_path: Path,
) -> None:
    """Real active-map flags mask carry; sparse factual bar ostayetsya complete."""
    source, candles, active = _fixture(tmp_path)
    sparse = candles.copy()
    sparse_exit = (
        sparse["logical_symbol"].eq("BR")
        & sparse["canonical_contract_id"].eq("BR:C1")
        & pd.to_datetime(sparse["timestamp"], utc=True).eq("2024-01-09T16:20:00Z")
    )
    sparse.loc[sparse_exit, "end_timestamp"] = pd.Timestamp("2024-01-09T16:21:20Z")
    sparse_result = _assemble_v8(source, sparse, active)
    assert sparse_result.targets.valid[0, V8_ASSETS.index("BR")]
    assert sparse_result.targets.availability_times[0, V8_ASSETS.index("BR")] == np.datetime64(
        "2024-01-09T16:30:00"
    )

    source_schema = active.copy()
    source_schema["carry_unfilled"] = False
    source_schema["plan_tradable"] = True
    source_schema["execution_open_available"] = True
    source_schema["feature_input_valid"] = True
    source_schema["ohlc_complete"] = True
    source_schema.loc[
        source_schema["asset_code"].eq("BR")
        & source_schema["effective_date"].eq("2024-01-05"),
        "carry_unfilled",
    ] = True
    masked = _assemble_v8(source, candles, source_schema)
    assert not masked.targets.valid[0, V8_ASSETS.index("BR")]

    zero_capacity = candles.copy()
    capacity_exit = (
        zero_capacity["logical_symbol"].eq("BR")
        & zero_capacity["canonical_contract_id"].eq("BR:C1")
        & pd.to_datetime(zero_capacity["timestamp"], utc=True).eq("2024-01-09T16:00:00Z")
    )
    zero_capacity.loc[capacity_exit, "volume"] = 0.0
    capacity_masked = _assemble_v8(source, zero_capacity, active)
    assert not capacity_masked.targets.valid[0, V8_ASSETS.index("BR")]
    capacity_time = capacity_masked.targets.exit_capacity_open_times[0, V8_ASSETS.index("BR")]
    assert capacity_time == np.datetime64(
        "2024-01-09T16:00:00"
    )
    assert capacity_masked.targets.exit_capacity_volumes[0, V8_ASSETS.index("BR")] == 0.0


def test_unmodeled_factual_common_session_masks_every_crossing_five_session_label(
    tmp_path: Path,
) -> None:
    """Propushchennaya factual session ne mozhet stat' odnim index-shagom horizon."""
    source, candles, active = _fixture(tmp_path)
    factual = _verified_sessions()
    omitted = pd.Timestamp("2024-01-05")
    v7_calendar = factual[factual != omitted]
    _write_v7_npz(source, v7_calendar)
    result = assemble_v8_from_v7_npz(
        source,
        candles,
        active,
        allow_unverified_fixture=True,
        fixture_common_session_dates=factual,
    )
    assert not result.targets.valid[0].any()
    assert result.targets.target[0].sum() == 0.0
    assert result.audit["target"]["invalid_reason_cells"][
        "irregular_or_unproven_common_session_horizon"
    ] > 0

    explicit = assemble_v8_from_v7_npz(
        source,
        candles,
        active,
        allow_unverified_fixture=True,
        fixture_unmodeled_factual_session_dates=[omitted],
    )
    assert not explicit.targets.valid[0].any()
    assert explicit.audit["target"]["factual_common_session_calendar"]["proven"]


def test_negative_d_known_daily_volatility_masks_target(tmp_path: Path) -> None:
    """Otricatel'naya corrupt D-known daily volatility ne prohodit cherez floor."""
    source, candles, active = _fixture(tmp_path)
    _write_v7_npz(
        source,
        _verified_sessions(),
        daily_volatility_after_index=0,
        daily_volatility_after_value=-0.01,
    )
    result = _assemble_v8(source, candles, active)
    assert not result.targets.valid.any()
    assert not result.targets.target.any()


def test_real_api_requires_verified_provenance_unless_fixture_is_explicit(
    tmp_path: Path,
) -> None:
    """Self-asserted calendar ne mozhet sluchaino stat' real source proof."""
    source, candles, active = _fixture(tmp_path)
    with pytest.raises(ValueError, match="provenance"):
        assemble_v8_from_v7_npz(source, candles, active)


def test_only_exact_initial_warmup_null_contract_rows_are_allowed(tmp_path: Path) -> None:
    """Razreshaet four-asset fail-closed warmup, no otklonyaet drugie null contracts."""
    source, candles, active = _fixture(tmp_path)
    active = active.assign(
        action="hold",
        reason="scheduled_hold",
        roll=False,
        plan_tradable=True,
        expiry_horizon_censored=False,
        carry_unfilled=False,
        execution_open_available=True,
        feature_input_valid=True,
        chain_id=1,
    )
    warmup = pd.DataFrame(
        {
            "effective_date": [pd.Timestamp("2024-01-01")] * len(V8_ASSETS),
            "asset_code": list(V8_ASSETS),
            "contract_id": pd.array([pd.NA] * len(V8_ASSETS), dtype="string"),
            "forward_additive_adjustment": 0.0,
            "action": "flat",
            "reason": "initial_warmup",
            "roll": False,
            "plan_tradable": False,
            "expiry_horizon_censored": False,
            "carry_unfilled": False,
            "execution_open_available": False,
            "feature_input_valid": False,
            "chain_id": 0,
        }
    )
    with_warmup = pd.concat([warmup, active], ignore_index=True)
    result = _assemble_v8(source, candles, with_warmup)
    assert result.targets.valid[0].all()

    corrupted = with_warmup.copy()
    corrupted.loc[corrupted["contract_id"].isna(), "reason"] = "unexpected_null"
    with pytest.raises(ValueError, match="initial_warmup"):
        _assemble_v8(source, candles, corrupted)


def test_d_known_daily_volatility_requires_exact_per_asset_decision_bar(
    tmp_path: Path,
) -> None:
    """Shared bar_times ne mozhet dokazat' D18:50 close za asset s invalid barom."""
    source, candles, active = _fixture(tmp_path)
    _write_v7_npz(source, _verified_sessions(), invalid_decision_asset="MIX")
    result = _assemble_v8(source, candles, active)
    assert result.targets.valid[0, V8_ASSETS.index("BR")]
    assert not result.targets.valid[0, V8_ASSETS.index("MIX")]
    assert result.audit["target"]["invalid_reason_cells"][
        "daily_row_not_proven_complete_at_d18_50"
    ] == 1


def test_capacity_bar_requires_exact_completed_sane_ohlcv(tmp_path: Path) -> None:
    """Malformed 19:00 end ili OHLC ne mozhet stat' capacity proof."""
    source, candles, active = _fixture(tmp_path)
    capacity = (
        candles["logical_symbol"].eq("BR")
        & candles["canonical_contract_id"].eq("BR:C1")
        & pd.to_datetime(candles["timestamp"], utc=True).eq("2024-01-02T16:00:00Z")
    )
    late = candles.copy()
    late.loc[capacity, "end_timestamp"] = pd.Timestamp("2024-01-02T16:10:01Z")
    late_result = _assemble_v8(source, late, active)
    assert not late_result.targets.valid[0, V8_ASSETS.index("BR")]

    impossible = candles.copy()
    impossible.loc[capacity, "high"] = impossible.loc[capacity, "close"] - 1.0
    impossible_result = _assemble_v8(source, impossible, active)
    assert not impossible_result.targets.valid[0, V8_ASSETS.index("BR")]


def test_tail_target_uses_verified_factual_boundary_after_last_sample(tmp_path: Path) -> None:
    """I+5 target ne teryaetsya, esli i+6 effective date dokazano calendarom."""
    source, candles, active = _fixture(tmp_path)
    sessions = _verified_sessions()
    final_decision = _decision_at(sessions[-1])
    extra_rows: list[dict[str, object]] = []
    for asset_number, asset in enumerate(V8_ASSETS):
        price = 100.0 + asset_number * 10.0 + (len(sessions) - 1) * 2.0
        for timestamp in (
            final_decision + pd.Timedelta(minutes=10),
            final_decision + pd.Timedelta(minutes=30),
        ):
            extra_rows.append(
                {
                    "timestamp": timestamp,
                    "end_timestamp": timestamp + pd.Timedelta(minutes=9, seconds=59),
                    "logical_symbol": asset,
                    "canonical_contract_id": f"{asset}:C1",
                    "open": price,
                    "high": price + 1.0,
                    "low": price - 1.0,
                    "close": price,
                    "volume": 1_000.0,
                }
            )
    candles = pd.concat([candles, pd.DataFrame(extra_rows)], ignore_index=True)
    next_session = sessions[-1] + pd.offsets.BDay(1)
    active = pd.concat(
        [
            active,
            pd.DataFrame(
                {
                    "effective_date": [next_session] * len(V8_ASSETS),
                    "asset_code": list(V8_ASSETS),
                    "contract_id": [f"{asset}:C1" for asset in V8_ASSETS],
                    "forward_additive_adjustment": 0.0,
                }
            ),
        ],
        ignore_index=True,
    )
    factual = sessions.append(pd.DatetimeIndex([next_session]))
    result = _assemble_v8(
        source,
        candles,
        active,
        fixture_common_session_dates=factual,
    )
    assert result.targets.valid[-V8_TARGET_HORIZON_COMMON_SESSIONS - 1].all()
    assert not result.targets.valid[-V8_TARGET_HORIZON_COMMON_SESSIONS:].any()


def test_fold_scope_purges_ten_sessions_and_ssl_never_crosses_effective_cutoff(
    tmp_path: Path,
) -> None:
    """Supervised exits i SSL origins/ends strogo nahodyatsya do cutoff."""
    result = _assemble(tmp_path)
    scope = build_v8_fold_scope(
        result.inputs,
        result.targets,
        train_start=date(2024, 1, 2),
        train_end=date(2024, 1, 25),
    )
    assert scope.purge_sessions == 10
    assert (result.targets.availability_times[scope.sample_indices] < scope.effective_cutoff).all()
    ssl_valid = build_v8_ssl_valid_mask(result.inputs, scope)
    assert ssl_valid.any()
    validate_v8_fold_scope(result.inputs, result.targets, scope)
    leaked = V8FoldScope(
        sample_indices=np.arange(result.inputs.sample_count, dtype=np.int64),
        effective_cutoff=scope.effective_cutoff,
        purge_sessions=10,
    )
    with pytest.raises(ValueError, match="exit"):
        validate_v8_fold_scope(result.inputs, result.targets, leaked)


def test_fold_scope_ignores_protected_target_timing_outside_causal_train_rows(
    tmp_path: Path,
) -> None:
    """OOS target timing >=2026 ne meniaet causal train scope ili ego validation."""
    result = _assemble(tmp_path)
    baseline = build_v8_fold_scope(
        result.inputs,
        result.targets,
        train_start=date(2024, 1, 2),
        train_end=date(2024, 1, 25),
    )
    availability = result.targets.availability_times.copy()
    outside = np.ones(result.inputs.sample_count, dtype=bool)
    outside[baseline.sample_indices] = False
    availability[outside] = np.datetime64("2035-01-01", "ns")
    poisoned = replace(result.targets, availability_times=availability)
    repeated = build_v8_fold_scope(
        result.inputs,
        poisoned,
        train_start=date(2024, 1, 2),
        train_end=date(2024, 1, 25),
    )
    np.testing.assert_array_equal(baseline.sample_indices, repeated.sample_indices)
    assert baseline.effective_cutoff == repeated.effective_cutoff
    validate_v8_fold_scope(result.inputs, poisoned, repeated)


def test_content_addressed_manifest_is_bom_safe_and_records_only_allowed_input_keys(
    tmp_path: Path,
) -> None:
    """Persistence zapisivaet source hashes/provenance bez legacy metok."""
    result = _assemble(tmp_path)
    paths = persist_v8_assembly(result, tmp_path)
    manifest_bytes = paths.manifest_path.read_bytes()
    manifest_mtime_ns = paths.manifest_path.stat().st_mtime_ns
    repeated = persist_v8_assembly(result, tmp_path)
    assert repeated == paths
    assert paths.manifest_path.read_bytes() == manifest_bytes
    assert paths.manifest_path.stat().st_mtime_ns == manifest_mtime_ns
    assert paths.arrays_path.name.startswith("assembly_")
    payload = json.loads(paths.manifest_path.read_text(encoding="utf-8-sig"))
    assert paths.manifest_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert tuple(payload["v7_source"]["keys_read"]) == V8_CAUSAL_V7_KEYS
    assert payload["v7_source"]["legacy_supervised_keys_read"] == []
    v7_artifact = next(
        artifact
        for artifact in payload["source_artifacts"]
        if artifact["kind"] == "v7_causal_npz"
    )
    assert payload["source_hashes"][v7_artifact["id"]] == result.inputs.source_sha256
    artifact_ids = [artifact["id"] for artifact in payload["source_artifacts"]]
    assert len(artifact_ids) == len(set(artifact_ids))
    assert set(payload["source_hashes"]) == set(artifact_ids)
    with np.load(paths.arrays_path, allow_pickle=False) as archive:
        assert "supervised_target" not in archive.files
        assert set(V8_CAUSAL_V7_KEYS).issubset(archive.files)


def test_cryptographic_provenance_verifies_219_files_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    """Top manifest svyazyvaet exact 219 parquet, active map, NPZ i calendar proof."""

    def sha256(path: Path) -> str:
        """Hashiruet malyi synthetic proof file dlya adversarial testa."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    source, _, _ = _fixture(tmp_path)
    parquet_proofs: list[V8SourceFileProof] = []
    parquet_records: list[dict[str, object]] = []
    for index in range(V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES):
        relative = Path("segments") / f"part_{index:03d}.parquet"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"sealed-{index}".encode("ascii"))
        proof = V8SourceFileProof(
            kind="official_moex_10m_parquet",
            path=relative,
            bytes=path.stat().st_size,
            sha256=sha256(path),
            rows=0,
        )
        parquet_proofs.append(proof)
        parquet_records.append(
            {
                "kind": proof.kind,
                "path": relative.as_posix(),
                "bytes": proof.bytes,
                "sha256": proof.sha256,
                "rows": proof.rows,
            }
        )
    active_relative = Path("active") / "active_map.parquet"
    active_path = tmp_path / active_relative
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_bytes(b"sealed-active-map")
    active_proof = V8SourceFileProof(
        kind="futures_v5_active_contract_map",
        path=active_relative,
        bytes=active_path.stat().st_size,
        sha256=sha256(active_path),
        rows=0,
    )
    active_record = {
        "kind": active_proof.kind,
        "path": active_relative.as_posix(),
        "bytes": active_proof.bytes,
        "sha256": active_proof.sha256,
        "rows": active_proof.rows,
    }
    payload: dict[str, object] = {
        "protected_from": "2026-01-01",
        "arrays": {
            "path": source.relative_to(tmp_path).as_posix(),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
        },
        "audit": {
            "factual_session_calendar": {
                "source": "verified_10m_distinct_scheduled_buckets_10:00_to_18:50_msk",
                "unmodeled_all_asset_main_session_count": 2,
                "unmodeled_all_asset_main_session_dates": [
                    "2020-09-11",
                    "2020-09-14",
                ],
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
    top_relative = Path("manifests") / "v7_top.json"
    top_path = tmp_path / top_relative
    top_path.parent.mkdir(parents=True, exist_ok=True)
    top_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    top_proof = V8SourceFileProof(
        kind="futures_v7_top_manifest",
        path=top_relative,
        bytes=top_path.stat().st_size,
        sha256=sha256(top_path),
    )
    provenance = V8VerifiedSourceProvenance(
        data_root=tmp_path,
        top_manifest=top_proof,
        all_contract_parquets=tuple(parquet_proofs),
        active_contract_map=active_proof,
    )
    records, evidence = verify_v8_source_provenance(provenance, v7_npz_path=source)
    assert len(records) == V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES + 2
    assert len({record["id"] for record in records}) == len(records)
    assert evidence.source_sha256 == top_proof.sha256

    tampered_path = tmp_path / parquet_proofs[0].path
    tampered_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="bytes|SHA-256"):
        verify_v8_source_provenance(provenance, v7_npz_path=source)


def test_pre_io_guard_rejects_2026_before_trying_to_open_source(tmp_path: Path) -> None:
    """Date argument padaet prezhde chem missing path mozhet vyzvat' NPZ I/O."""
    missing = tmp_path / "does_not_exist.npz"
    empty = pd.DataFrame()
    with pytest.raises(ValueError, match="2026"):
        assemble_v8_from_v7_npz(
            missing,
            empty,
            empty,
            source_end=date(2026, 1, 1),
        )
