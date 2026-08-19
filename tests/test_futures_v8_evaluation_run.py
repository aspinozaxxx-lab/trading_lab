"""Testy authoritative target-free futures-v8 evaluation orchestration."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import market_lab.futures_v8.evaluation_run as evaluation_run_module
from market_lab.futures_v8.eval_run import (
    CORE_STRATEGY_ID,
    V8ScenarioId,
    V8TrustedCandleIndex,
)
from market_lab.futures_v8.evaluation_run import (
    V8_ACTIVE_MAP_COLUMNS,
    V8_BASE_PREDICTION_COLUMNS,
    V8_CALENDAR_COLUMNS,
    V8_ENRICHMENT_COLUMNS,
    V8_EVALUATION_SOURCE_FORMAT,
    V8_REQUIRED_SOURCE_KINDS,
    V8_SPEC_PROXY_COLUMNS,
    V8_TEN_MINUTE_COLUMNS,
    V8EvaluationBlockedError,
    V8EvaluationMode,
    V8EvaluationSourceSeal,
    V8EvaluationVerificationRequest,
    build_v8_evaluation_code_identity,
    inspect_v8_evaluation_readiness,
    persist_v8_evaluation_result,
    prepare_v8_evaluation,
    run_and_persist_v8_evaluation,
    run_v8_evaluation,
    verify_v8_evaluation_sources,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOSCOW = ZoneInfo("Europe/Moscow")
ASSETS = ("BR", "MIX", "RI", "SI")
SOURCE_SHA = "1" * 64


def _unsafe_prepared_forgery(prepared: Any, **changes: object) -> Any:
    """Imitiruet in-memory tampering frozen Prepared bez ego __post_init__."""
    forged = object.__new__(type(prepared))
    for name in prepared.__dataclass_fields__:
        value = changes[name] if name in changes else getattr(prepared, name)
        object.__setattr__(forged, name, value)
    return forged


def _bytes_sha(path: Path) -> str:
    """Schitaet byte SHA test artifacta."""
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    """Pishet stable runtime JSON; eto ne repository source edit."""
    path.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
        encoding="utf-8-sig",
    )


def _local(day: date, clock: time) -> datetime:
    """Stroit aware Moscow timestamp dlya fake factual calendar."""
    return datetime.combine(day, clock, tzinfo=MOSCOW)


def _daily_dates() -> tuple[date, ...]:
    """Vozvrashchaet Jan-4->Jan-5 regression calendar s shestyu D."""
    return (
        date(2021, 1, 4),
        date(2021, 1, 5),
        date(2021, 1, 6),
        date(2021, 1, 7),
        date(2021, 1, 8),
        date(2021, 1, 11),
    )


def _multi_year_dates() -> tuple[date, ...]:
    """Daet 11 sealed transitions i metrics coverage 2021--2025."""
    return (
        date(2021, 1, 4),
        date(2021, 2, 1),
        date(2021, 3, 1),
        date(2021, 4, 1),
        date(2021, 5, 3),
        date(2021, 6, 1),
        date(2022, 1, 3),
        date(2022, 6, 1),
        date(2023, 1, 3),
        date(2024, 1, 3),
        date(2025, 1, 3),
    )


def _calendar_rows(decision_dates: tuple[date, ...]) -> list[dict[str, Any]]:
    """Stroit explicit D->next economic session bez wall-clock inference."""
    final_effective = date(2021, 1, 12) if decision_dates == _daily_dates() else date(2025, 12, 30)
    effective_dates = (*decision_dates[1:], final_effective)
    rows: list[dict[str, Any]] = []
    for sequence_id, (decision_date, effective_date) in enumerate(
        zip(decision_dates, effective_dates, strict=True)
    ):
        rows.append(
            {
                "sequence_id": sequence_id,
                "decision_session_date": decision_date.isoformat(),
                "decision_at": _local(decision_date, time(18, 50)).isoformat(),
                "entry_effective_session_date": effective_date.isoformat(),
                "calendar_known_at": _local(date(2020, 1, 1), time(12)).isoformat(),
                "settlement_candle_opened_at": _local(decision_date, time(19, 30)).isoformat(),
                "settlement_candle_closed_at": _local(decision_date, time(19, 40)).isoformat(),
                "settlement_at": _local(effective_date, time(0, 0)).isoformat(),
                "accounting_as_of": _local(effective_date, time(0, 30)).isoformat(),
                "source_sha256": SOURCE_SHA,
            }
        )
    return rows


def _prediction_frames(
    calendar: list[dict[str, Any]],
    *,
    active_sequences: frozenset[int],
    invalid_cells: frozenset[tuple[int, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stroit exact target-free base/enrichment/active-map fake tables."""
    base_rows: list[dict[str, Any]] = []
    enrichment_rows: list[dict[str, Any]] = []
    active_rows: list[dict[str, Any]] = []
    for session in calendar:
        decision_at = pd.Timestamp(session["decision_at"])
        sequence_id = session["sequence_id"]
        factor_signal = 3.0 if sequence_id in active_sequences else 0.0
        for asset in ASSETS:
            active = sequence_id in active_sequences and asset == "BR"
            model_valid = (sequence_id, asset) not in invalid_cells
            residual_signal = 3.0 if active else 0.0
            residual_location = 0.0 if model_valid else float("nan")
            residual_scale = 1.0 if model_valid else float("nan")
            direction_logit = residual_signal if model_valid else float("nan")
            base_rows.append(
                {
                    "decision_date": decision_at.date(),
                    "decision_at": decision_at,
                    "capacity_window_open_at": decision_at + pd.Timedelta(minutes=10),
                    "capacity_window_close_at": decision_at + pd.Timedelta(minutes=20),
                    "execution_window_open_at": decision_at + pd.Timedelta(minutes=30),
                    "execution_window_close_at": decision_at + pd.Timedelta(minutes=40),
                    "asset": asset,
                    "asset_valid": model_valid,
                    "factor_location": factor_signal,
                    "factor_scale": 1.0,
                    "factor_score": factor_signal,
                    "residual_location": residual_location,
                    "residual_scale": residual_scale,
                    "residual_decision_score": (residual_signal if model_valid else float("nan")),
                    "direction_logit": direction_logit,
                    "model_id": "fake-model",
                }
            )
            enrichment = {
                "decision_at": decision_at,
                "asset": asset,
                "known_at": decision_at - pd.Timedelta(minutes=1),
                "total_scale": 1.0,
                "abstain_probability": 0.0,
                "normal_probability": 1.0,
                "trend_probability": 0.0,
                "crash_probability": 0.0,
                "close": 100.0,
                "atr_20": 1.0,
                "daily_volatility_20": 0.01,
                "momentum_20": residual_signal,
                "range_position_20": 0.5,
                "volatility_ratio_20": 1.0,
                "volume_ratio_20": 1.0,
                "market_data_sha256": SOURCE_SHA,
            }
            for channel in (
                "carry_z",
                "cftc_crowd_z",
                "key_rate_change_z",
                "usd_rub_return_z",
            ):
                for suffix in (
                    "value",
                    "published_at",
                    "source_id",
                    "observation_id",
                    "source_sha256",
                ):
                    enrichment[f"{channel}_{suffix}"] = None
            enrichment_rows.append(enrichment)
            active_rows.append(
                {
                    "decision_at": decision_at,
                    "asset": asset,
                    "contract_id": f"{asset}H1",
                    "contract_known_at": decision_at - pd.Timedelta(minutes=2),
                    "entry_effective_session_date": pd.Timestamp(
                        session["entry_effective_session_date"]
                    ).date(),
                    "expiration_date": date(2025, 12, 31),
                    "maturity_known_at": decision_at - pd.Timedelta(days=30),
                    "asset_mask": active,
                    "source_sha256": SOURCE_SHA,
                }
            )
    return (
        pd.DataFrame(base_rows, columns=V8_BASE_PREDICTION_COLUMNS),
        pd.DataFrame(enrichment_rows, columns=V8_ENRICHMENT_COLUMNS),
        pd.DataFrame(active_rows, columns=V8_ACTIVE_MAP_COLUMNS),
    )


def _spec_frame(calendar: list[dict[str, Any]]) -> pd.DataFrame:
    """Stroit daily lag-1/current spec proxy dlya vseh four contracts."""
    rows: list[dict[str, Any]] = []
    for session in calendar:
        decision_date = date.fromisoformat(session["decision_session_date"])
        effective = date.fromisoformat(session["entry_effective_session_date"])
        for asset in ASSETS:
            rows.append(
                {
                    "session_date": effective,
                    "asset": asset,
                    "contract_id": f"{asset}H1",
                    "sizing_observed_session_date": decision_date,
                    "sizing_known_at": _local(decision_date, time(18)).isoformat(),
                    "accounting_known_at": _local(effective, time(0)).isoformat(),
                    "sizing_point_value": 1.0,
                    "realized_accounting_point_value": 1.0,
                    "modeled_initial_margin": 100.0,
                    "conservative_fee_per_side": 1.0,
                    "sizing_lag_sessions": 1,
                    "sizing_status": "available_lag_1_session",
                    "accounting_status": "available_primary_after_session",
                    "source_sha256": SOURCE_SHA,
                }
            )
    return pd.DataFrame(rows, columns=V8_SPEC_PROXY_COLUMNS)


def _candle_frame(
    calendar: list[dict[str, Any]],
    *,
    include_br: bool,
    missing_capacity: bool,
) -> pd.DataFrame:
    """Stroit exact capacity/primary/delay-settlement factual BR candles."""
    rows: list[dict[str, Any]] = []
    if include_br:
        for session in calendar:
            decision_date = date.fromisoformat(session["decision_session_date"])
            for clock, volume in (
                (time(19), None if missing_capacity else 100),
                (time(19, 20), 100),
                (time(19, 30), 100),
            ):
                opened = _local(decision_date, clock)
                rows.append(
                    {
                        "contract_id": "BRH1",
                        "opened_at": opened,
                        "closed_at": opened + timedelta(minutes=10),
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.0,
                        "volume": volume,
                    }
                )
    return pd.DataFrame(rows, columns=V8_TEN_MINUTE_COLUMNS)


def _manifest(
    root: Path,
    kind: str,
    artifact: Path,
    rows: int,
    columns: tuple[str, ...],
    dependencies: dict[str, str],
) -> dict[str, Any]:
    """Stroit odin normalized byte-sealed source manifest payload."""
    payload: dict[str, Any] = {
        "format": V8_EVALUATION_SOURCE_FORMAT,
        "kind": kind,
        "artifact": {
            "path": artifact.relative_to(root).as_posix(),
            "sha256": _bytes_sha(artifact),
            "bytes": artifact.stat().st_size,
            "rows": rows,
        },
        "columns": list(columns),
        "array_keys": ["checkpoints"] if kind == "checkpoint_identities" else [],
        "maximum_session_date": "2025-12-31",
        "dependencies": dependencies,
    }
    if kind == "checkpoint_identities":
        payload.update(completed_checkpoint_count=15, all_completed=True)
    if kind == "enrichment":
        payload["audit_status"] = "audited_complete"
        payload["context_completion_status"] = "audited_full_causal_context"
    return payload


def _build_request(
    tmp_path: Path,
    *,
    decision_dates: tuple[date, ...] | None = None,
    active_sequences: frozenset[int] = frozenset(),
    invalid_cells: frozenset[tuple[int, str]] = frozenset(),
    include_br_candles: bool = False,
    missing_capacity: bool = False,
) -> V8EvaluationVerificationRequest:
    """Materializuet vse eight exact fake source artifacts/manifests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    decision_dates = decision_dates or _daily_dates()
    calendar = _calendar_rows(decision_dates)
    base, enrichment, active_map = _prediction_frames(
        calendar,
        active_sequences=active_sequences,
        invalid_cells=invalid_cells,
    )
    frames = {
        "base_predictions": (base, V8_BASE_PREDICTION_COLUMNS),
        "enrichment": (enrichment, V8_ENRICHMENT_COLUMNS),
        "active_map": (active_map, V8_ACTIVE_MAP_COLUMNS),
        "spec_proxy": (_spec_frame(calendar), V8_SPEC_PROXY_COLUMNS),
        "moex_10m": (
            _candle_frame(
                calendar,
                include_br=include_br_candles,
                missing_capacity=missing_capacity,
            ),
            V8_TEN_MINUTE_COLUMNS,
        ),
    }
    artifacts: dict[str, Path] = {}
    rows_by_kind: dict[str, int] = {}
    columns_by_kind: dict[str, tuple[str, ...]] = {}
    for kind, (frame, columns) in frames.items():
        path = tmp_path / f"{kind}.parquet"
        frame.to_parquet(path, index=False)
        artifacts[kind] = path
        rows_by_kind[kind] = len(frame)
        columns_by_kind[kind] = columns
    checkpoint_path = tmp_path / "checkpoint_identities.json"
    checkpoints = [
        {
            "fold_id": fold,
            "seed": seed,
            "status": "completed",
            "checkpoint_sha256": sha256(f"{fold}-{seed}".encode()).hexdigest(),
        }
        for fold in range(5)
        for seed in range(3)
    ]
    _write_json(checkpoint_path, {"checkpoints": checkpoints})
    artifacts["checkpoint_identities"] = checkpoint_path
    rows_by_kind["checkpoint_identities"] = 15
    columns_by_kind["checkpoint_identities"] = ()
    assembly_path = tmp_path / "assembly.json"
    _write_json(assembly_path, {"format": "fake-assembly-v1", "arrays": []})
    artifacts["assembly"] = assembly_path
    rows_by_kind["assembly"] = 0
    columns_by_kind["assembly"] = ()
    calendar_path = tmp_path / "calendar.json"
    _write_json(
        calendar_path,
        {
            "format": "market-lab-futures-v8-evaluation-calendar-v1",
            "columns": list(V8_CALENDAR_COLUMNS),
            "sessions": calendar,
        },
    )
    artifacts["calendar"] = calendar_path
    rows_by_kind["calendar"] = len(calendar)
    columns_by_kind["calendar"] = V8_CALENDAR_COLUMNS
    artifact_hashes = {kind: _bytes_sha(path) for kind, path in artifacts.items()}
    seals: list[V8EvaluationSourceSeal] = []
    dependency_kinds = {
        "base_predictions": ("checkpoint_identities",),
        "checkpoint_identities": (),
        "enrichment": ("assembly", "base_predictions", "checkpoint_identities"),
        "calendar": ("assembly",),
        "assembly": (),
        "active_map": ("assembly", "calendar"),
        "spec_proxy": ("active_map", "calendar"),
        "moex_10m": ("active_map", "calendar"),
    }
    for kind in V8_REQUIRED_SOURCE_KINDS:
        dependencies = {
            dependency: artifact_hashes[dependency] for dependency in dependency_kinds[kind]
        }
        manifest_payload = _manifest(
            PROJECT_ROOT,
            kind,
            artifacts[kind],
            rows_by_kind[kind],
            columns_by_kind[kind],
            dependencies,
        )
        manifest_path = tmp_path / f"{kind}.manifest.json"
        _write_json(manifest_path, manifest_payload)
        seals.append(
            V8EvaluationSourceSeal(
                kind=kind,
                manifest_path=manifest_path,
                manifest_sha256=_bytes_sha(manifest_path),
                artifact_path=artifacts[kind],
                artifact_sha256=artifact_hashes[kind],
                rows=rows_by_kind[kind],
            )
        )
    return V8EvaluationVerificationRequest(
        project_root=PROJECT_ROOT,
        sources=tuple(seals),
        expected_code_identity_sha256=build_v8_evaluation_code_identity(PROJECT_ROOT)[
            "code_identity_sha256"
        ],
    )


def _replace_source(
    request: V8EvaluationVerificationRequest,
    kind: str,
    *,
    artifact_payload: object | None = None,
    artifact_frame: pd.DataFrame | None = None,
    manifest_mutation: tuple[str, object] | None = None,
) -> V8EvaluationVerificationRequest:
    """Reseal'it odin fake source posle adversarial mutation."""
    old = next(item for item in request.sources if item.kind == kind)
    if artifact_payload is not None:
        _write_json(old.artifact_path, artifact_payload)
    if artifact_frame is not None:
        artifact_frame.to_parquet(old.artifact_path, index=False)
    manifest = json.loads(old.manifest_path.read_text(encoding="utf-8-sig"))
    rows = (
        len(artifact_frame)
        if artifact_frame is not None
        else len(artifact_payload.get("sessions", artifact_payload.get("arrays", [])))
        if isinstance(artifact_payload, dict)
        else old.rows
    )
    if kind == "checkpoint_identities":
        rows = old.rows
    manifest["artifact"].update(
        sha256=_bytes_sha(old.artifact_path),
        bytes=old.artifact_path.stat().st_size,
        rows=rows,
    )
    if manifest_mutation is not None:
        manifest[manifest_mutation[0]] = manifest_mutation[1]
    _write_json(old.manifest_path, manifest)
    replacement = V8EvaluationSourceSeal(
        kind=kind,
        manifest_path=old.manifest_path,
        manifest_sha256=_bytes_sha(old.manifest_path),
        artifact_path=old.artifact_path,
        artifact_sha256=_bytes_sha(old.artifact_path),
        rows=rows,
    )
    updated_sources: list[V8EvaluationSourceSeal] = []
    for item in request.sources:
        if item.kind == kind:
            updated_sources.append(replacement)
            continue
        dependent_manifest = json.loads(item.manifest_path.read_text(encoding="utf-8-sig"))
        dependencies = dependent_manifest.get("dependencies", {})
        if kind in dependencies:
            dependencies[kind] = replacement.artifact_sha256
            _write_json(item.manifest_path, dependent_manifest)
            item = replace(
                item,
                manifest_sha256=_bytes_sha(item.manifest_path),
            )
        updated_sources.append(item)
    return replace(
        request,
        sources=tuple(updated_sources),
    )


def _set_br_strategy_signal(
    request: V8EvaluationVerificationRequest,
    sequence_id: int,
    *,
    family: str,
    close: float = 100.0,
) -> V8EvaluationVerificationRequest:
    """Mutate only target-free BR context fields for a synthetic stateful signal."""
    source = next(item for item in request.sources if item.kind == "enrichment")
    frame = pd.read_parquet(source.artifact_path)
    decisions = tuple(sorted(frame["decision_at"].drop_duplicates()))
    decision_at = decisions[sequence_id]
    mask = (frame["decision_at"] == decision_at) & (frame["asset"] == "BR")
    frame.loc[mask, "close"] = close
    if family == "corridor":
        frame.loc[mask, "normal_probability"] = 1.0
        frame.loc[mask, "trend_probability"] = 0.0
        frame.loc[mask, "crash_probability"] = 0.0
        frame.loc[mask, "range_position_20"] = 0.10
        frame.loc[mask, "volatility_ratio_20"] = 1.50
    elif family == "breakout":
        frame.loc[mask, "normal_probability"] = 0.40
        frame.loc[mask, "trend_probability"] = 0.60
        frame.loc[mask, "crash_probability"] = 0.0
        frame.loc[mask, "range_position_20"] = 1.10
        frame.loc[mask, "volatility_ratio_20"] = 1.20
    elif family == "neutral":
        frame.loc[mask, "normal_probability"] = 1.0
        frame.loc[mask, "trend_probability"] = 0.0
        frame.loc[mask, "crash_probability"] = 0.0
        frame.loc[mask, "range_position_20"] = 0.50
        frame.loc[mask, "volatility_ratio_20"] = 1.0
    else:
        raise ValueError(f"unknown synthetic family: {family}")
    return _replace_source(request, "enrichment", artifact_frame=frame)


def _set_high_capacity_candles(
    request: V8EvaluationVerificationRequest,
    *,
    ambiguous_corridor_first_settlement: bool = False,
    add_missing_br_union_slot: bool = False,
) -> V8EvaluationVerificationRequest:
    """Raise factual capacity and optionally add adversarial corridor bar geometry."""
    source = next(item for item in request.sources if item.kind == "moex_10m")
    frame = pd.read_parquet(source.artifact_path)
    frame.loc[:, "volume"] = 1_000_000
    if ambiguous_corridor_first_settlement:
        local = pd.to_datetime(frame["opened_at"], utc=True).dt.tz_convert(MOSCOW)
        first_date = min(local.dt.date)
        mask = (local.dt.date == first_date) & (local.dt.time == time(19, 30))
        frame.loc[mask, ["open", "high", "low", "close"]] = [100.0, 103.0, 97.0, 100.0]
    if add_missing_br_union_slot:
        first_decision = min(
            pd.to_datetime(frame["opened_at"], utc=True).dt.tz_convert(MOSCOW).dt.date
        )
        opened = _local(first_decision, time(19, 40))
        extra = pd.DataFrame(
            [
                {
                    "contract_id": "MIXH1",
                    "opened_at": opened,
                    "closed_at": opened + timedelta(minutes=10),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000_000,
                }
            ],
            columns=V8_TEN_MINUTE_COLUMNS,
        )
        frame = pd.concat((frame, extra), ignore_index=True)
    return _replace_source(request, "moex_10m", artifact_frame=frame)


def _roll_br_contract_after_sequence(
    request: V8EvaluationVerificationRequest,
    sequence_id: int,
) -> V8EvaluationVerificationRequest:
    """Create a valid future contract snapshot to exercise persistent-roll admission."""
    active_source = next(item for item in request.sources if item.kind == "active_map")
    active = pd.read_parquet(active_source.artifact_path)
    decisions = tuple(sorted(active["decision_at"].drop_duplicates()))
    changed_decisions = set(decisions[sequence_id:])
    mask = active["decision_at"].isin(changed_decisions) & (active["asset"] == "BR")
    changed_sessions = set(active.loc[mask, "entry_effective_session_date"])
    active.loc[mask, "contract_id"] = "BRM1"
    request = _replace_source(request, "active_map", artifact_frame=active)
    spec_source = next(item for item in request.sources if item.kind == "spec_proxy")
    specs = pd.read_parquet(spec_source.artifact_path)
    spec_mask = specs["session_date"].isin(changed_sessions) & (specs["asset"] == "BR")
    rolled_specs = specs.loc[spec_mask].copy()
    rolled_specs.loc[:, "contract_id"] = "BRM1"
    specs = pd.concat((specs, rolled_specs), ignore_index=True)
    request = _replace_source(request, "spec_proxy", artifact_frame=specs)
    candle_source = next(item for item in request.sources if item.kind == "moex_10m")
    candles = pd.read_parquet(candle_source.artifact_path)
    changed_dates = {
        pd.Timestamp(item).tz_convert(MOSCOW).date() for item in changed_decisions
    }
    local_dates = pd.to_datetime(candles["opened_at"], utc=True).dt.tz_convert(MOSCOW).dt.date
    copies = candles.loc[
        (candles["contract_id"] == "BRH1") & local_dates.isin(changed_dates)
    ].copy()
    copies.loc[:, "contract_id"] = "BRM1"
    candles = pd.concat((candles, copies), ignore_index=True)
    return _replace_source(request, "moex_10m", artifact_frame=candles)


def test_prepare_exact_jan4_to_jan5_and_d_known_eligibility(tmp_path: Path) -> None:
    """Dokazyvaet explicit economic join i five-session maturity rule."""
    prepared = prepare_v8_evaluation(_build_request(tmp_path, active_sequences=frozenset({0})))
    first = prepared.bundle.predictions[0]
    assert first.context.decision_at.astimezone(MOSCOW).date() == date(2021, 1, 4)
    assert {item.entry_effective_session_date for item in first.contracts} == {date(2021, 1, 5)}
    br_contract = next(item for item in first.contracts if item.asset_id == "BR")
    assert br_contract.asset_mask is True
    assert br_contract.nominal_span_eligible is True
    assert (
        prepared.bundle.prediction_sha256
        == prepared.verified.source("base_predictions").artifact_sha256
    )
    assert prepared.readiness_audit.validity_activity_mismatch_count == 23


def test_prepare_issues_one_verified_full_candle_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stroit O(panel) index odin raz i bindit ego k exact moex artifact coverage."""
    moex_reads: list[int] = []
    original = evaluation_run_module._read_verified_frame

    def counted_read(
        *args: object,
        **kwargs: object,
    ) -> pd.DataFrame:
        source = args[0]
        if getattr(source, "kind", None) == "moex_10m":
            moex_reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        evaluation_run_module,
        "_read_verified_frame",
        counted_read,
    )
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    source = prepared.verified.source("moex_10m")
    trusted = prepared.trusted_candle_index

    assert moex_reads == [1, 1]
    assert trusted.row_count == source.rows == len(prepared.bundle.candles)
    assert trusted.market_data_sha256 == source.artifact_sha256
    assert trusted.source_manifest_sha256 == source.manifest_sha256
    assert trusted.source_identity_sha256 == prepared.verified.source_identity_sha256
    assert trusted.candles == prepared.bundle.candles
    assert not hasattr(V8TrustedCandleIndex, "_from_verified_bundle")
    with pytest.raises(TypeError, match="callable issuer"):
        evaluation_run_module._V8AuthoritativeCandleIndex(
            prepared.verified,
            prepared.bundle,
        )


def test_fake_prepared_or_post_prepare_source_drift_is_rejected(
    tmp_path: Path,
) -> None:
    """Ne daet podmenit' capability/bundle ili izmenit' artifact pered startom."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    forged_bundle = replace(
        prepared.bundle,
        candles=prepared.bundle.candles[:-1],
    )
    with pytest.raises(ValueError, match="trusted candle artifact/coverage identity"):
        replace(prepared, bundle=forged_bundle)
    with pytest.raises(TypeError, match="authoritative candle capability"):
        replace(prepared, trusted_candle_index=object())

    source = prepared.verified.source("moex_10m")
    source.artifact_path.write_bytes(source.artifact_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact byte SHA mismatch"):
        run_v8_evaluation(
            prepared,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
        )


@pytest.mark.parametrize("forgery_kind", ("factor", "context"))
def test_run_canonical_rebuild_rejects_prediction_or_context_forgery(
    tmp_path: Path,
    forgery_kind: str,
) -> None:
    """Otklonyaet self-consistent prediction/context podmenu posle source rehash."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path / forgery_kind,
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    prediction = prepared.bundle.predictions[0]
    if forgery_kind == "factor":
        forged_prediction = replace(
            prediction,
            factor_location=prediction.factor_location + 0.25,
        )
    else:
        asset = prediction.context.assets[0]
        forged_asset = replace(asset, close=asset.close + 1.0)
        forged_context = replace(
            prediction.context,
            assets=(forged_asset, *prediction.context.assets[1:]),
        )
        forged_prediction = replace(prediction, context=forged_context)
    forged_bundle = replace(
        prepared.bundle,
        predictions=(forged_prediction, *prepared.bundle.predictions[1:]),
    )
    forged = _unsafe_prepared_forgery(prepared, bundle=forged_bundle)

    with pytest.raises(ValueError, match="prepared canonical rebuild mismatch"):
        run_v8_evaluation(
            forged,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
        )


def test_run_canonical_rebuild_rejects_contract_spec_forgery(tmp_path: Path) -> None:
    """Otklonyaet validno perehashirovannuyu, no ne source-derived spec podmenu."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    spec = prepared.bundle.contract_specs[0]
    forged_spec = replace(spec, fee_per_contract=spec.fee_per_contract + 1.0)
    forged_bundle = replace(
        prepared.bundle,
        contract_specs=(forged_spec, *prepared.bundle.contract_specs[1:]),
    )
    forged = _unsafe_prepared_forgery(prepared, bundle=forged_bundle)

    with pytest.raises(ValueError, match="prepared canonical rebuild mismatch"):
        run_v8_evaluation(
            forged,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
        )


def test_run_canonical_rebuild_rejects_calendar_forgery(tmp_path: Path) -> None:
    """Otklonyaet calendar dataclass, poddelannyi posle sealed source load."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    forged_session = replace(prepared.calendar[0], source_sha256="9" * 64)
    forged_calendar = (forged_session, *prepared.calendar[1:])
    forged = _unsafe_prepared_forgery(prepared, calendar=forged_calendar)

    with pytest.raises(ValueError, match="prepared canonical rebuild mismatch"):
        run_v8_evaluation(
            forged,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
        )


def test_run_canonical_rebuild_rejects_readiness_forgery(tmp_path: Path) -> None:
    """Otklonyaet samosoglasovannyi readiness audit s pridumannoi prichinoi."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    row = prepared.readiness_audit.rows[0]
    forged_row = replace(
        row,
        reason_codes=(*row.reason_codes, "forged_source_independent_reason"),
    )
    forged_audit = replace(
        prepared.readiness_audit,
        rows=(forged_row, *prepared.readiness_audit.rows[1:]),
    )
    forged = _unsafe_prepared_forgery(prepared, readiness_audit=forged_audit)

    with pytest.raises(ValueError, match="prepared canonical rebuild mismatch"):
        run_v8_evaluation(
            forged,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
        )


def test_run_canonical_rebuild_rejects_cross_source_prepared_mix(tmp_path: Path) -> None:
    """Ne daet verified graph A zapustit' bundle/capability iz istochnikov B."""
    prepared_a = prepare_v8_evaluation(
        _build_request(
            tmp_path / "source_a",
            active_sequences=frozenset({0}),
            include_br_candles=True,
        )
    )
    prepared_b = prepare_v8_evaluation(
        _build_request(
            tmp_path / "source_b",
            active_sequences=frozenset({1}),
            include_br_candles=True,
        )
    )
    forged = _unsafe_prepared_forgery(
        prepared_a,
        bundle=prepared_b.bundle,
        calendar=prepared_b.calendar,
        readiness_audit=prepared_b.readiness_audit,
        trusted_candle_index=prepared_b.trusted_candle_index,
        prepared_identity_sha256=prepared_b.prepared_identity_sha256,
    )

    with pytest.raises(ValueError, match="prepared canonical rebuild mismatch"):
        run_v8_evaluation(
            forged,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
        )


def test_readiness_preserves_two_masks_and_blocks_invalid_nan_before_context(
    tmp_path: Path,
) -> None:
    """Ne imputiruet invalid NaN i ne smeshivaet model-valid s contract-active."""
    normal = _build_request(tmp_path / "normal")
    audit = inspect_v8_evaluation_readiness(normal)
    assert audit.model_input_invalid_count == 0
    assert audit.active_contract_inactive_count == 24
    assert audit.validity_activity_mismatch_count == 24
    assert audit.executable_asset_count == 0
    invalid = _build_request(
        tmp_path / "invalid",
        active_sequences=frozenset({0}),
        invalid_cells=frozenset({(0, "BR")}),
    )
    invalid_audit = inspect_v8_evaluation_readiness(invalid)
    row = next(
        item
        for item in invalid_audit.rows
        if item.decision_at.astimezone(MOSCOW).date() == date(2021, 1, 4) and item.asset_id == "BR"
    )
    assert row.model_input_valid is False
    assert row.entry_contract_active is True
    assert row.executable_asset_mask is False
    assert "model_input_invalid" in row.reason_codes
    with pytest.raises(V8EvaluationBlockedError, match="validity-aware"):
        prepare_v8_evaluation(invalid)


def test_verify_rejects_target_manifest_before_parquet_read(tmp_path: Path) -> None:
    """Blokiruet target_valid name na manifest boundary."""
    request = _build_request(tmp_path)
    columns = [*V8_BASE_PREDICTION_COLUMNS, "target_valid"]
    poisoned = _replace_source(
        request,
        "base_predictions",
        manifest_mutation=("columns", columns),
    )
    with pytest.raises(ValueError, match="forbidden target/label"):
        verify_v8_evaluation_sources(poisoned)


def test_prepare_rejects_nested_label_array_and_future_manifest(tmp_path: Path) -> None:
    """Blokiruet poison v JSON arrays i any declared 2026 boundary."""
    request = _build_request(tmp_path)
    poisoned = _replace_source(
        request,
        "assembly",
        artifact_payload={"format": "fake-assembly-v1", "arrays": [{"label": [1]}]},
    )
    with pytest.raises(ValueError, match="forbidden target/label"):
        prepare_v8_evaluation(poisoned)
    future = _replace_source(
        _build_request(tmp_path / "future"),
        "calendar",
        manifest_mutation=("maximum_session_date", "2026-01-01"),
    )
    with pytest.raises(ValueError, match="protected 2026"):
        verify_v8_evaluation_sources(future)


def test_prepare_rejects_2026_row_even_with_resealed_manifest(tmp_path: Path) -> None:
    """Blokiruet protected future v artifact body, ne tol'ko declared maximum."""
    request = _build_request(tmp_path)
    source = next(item for item in request.sources if item.kind == "base_predictions")
    frame = pd.read_parquet(source.artifact_path)
    future_decision = pd.Timestamp("2026-01-05T18:50:00+03:00")
    frame.loc[0, "decision_date"] = future_decision.date()
    frame.loc[0, "decision_at"] = future_decision
    frame.loc[0, "capacity_window_open_at"] = future_decision + pd.Timedelta(minutes=10)
    frame.loc[0, "capacity_window_close_at"] = future_decision + pd.Timedelta(minutes=20)
    frame.loc[0, "execution_window_open_at"] = future_decision + pd.Timedelta(minutes=30)
    frame.loc[0, "execution_window_close_at"] = future_decision + pd.Timedelta(minutes=40)
    mutated = _replace_source(request, "base_predictions", artifact_frame=frame)
    with pytest.raises(ValueError, match="protected 2026"):
        prepare_v8_evaluation(mutated)


def test_verify_rejects_byte_tamper(tmp_path: Path) -> None:
    """Fail-closed ot replay artifacta s drugim byte SHA."""
    request = _build_request(tmp_path)
    source = next(item for item in request.sources if item.kind == "assembly")
    source.artifact_path.write_bytes(source.artifact_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact byte SHA mismatch"):
        verify_v8_evaluation_sources(request)


def test_verify_rejects_source_mix_without_exact_dependency_graph(tmp_path: Path) -> None:
    """Blokiruet valid individual SHA, esli enrichment ne svyazan s base/assembly."""
    request = _build_request(tmp_path)
    mixed = _replace_source(
        request,
        "enrichment",
        manifest_mutation=("dependencies", {}),
    )
    with pytest.raises(ValueError, match="exact graph"):
        verify_v8_evaluation_sources(mixed)


def test_verify_blocks_regime_only_enrichment_without_full_context_builder(
    tmp_path: Path,
) -> None:
    """Ne dopuskaet regime-only artifact kak gotovyi CausalDecisionContext."""
    request = _build_request(tmp_path)
    regime_only = _replace_source(
        request,
        "enrichment",
        manifest_mutation=("context_completion_status", "regime_only"),
    )
    with pytest.raises(V8EvaluationBlockedError, match="regime-only enrichment"):
        verify_v8_evaluation_sources(regime_only)


@pytest.mark.parametrize("mutation", ["omission", "duplicate"])
def test_prepare_rejects_calendar_omission_or_duplicate(
    tmp_path: Path,
    mutation: str,
) -> None:
    """Trebuet contiguous unique common-session chain."""
    request = _build_request(tmp_path)
    source = next(item for item in request.sources if item.kind == "calendar")
    payload = json.loads(source.artifact_path.read_text(encoding="utf-8-sig"))
    if mutation == "omission":
        payload["sessions"][0]["entry_effective_session_date"] = "2021-01-06"
    else:
        payload["sessions"][1]["sequence_id"] = 0
    mutated = _replace_source(request, "calendar", artifact_payload=payload)
    with pytest.raises(ValueError, match="calendar|settlement"):
        prepare_v8_evaluation(mutated)


def test_prepare_rejects_unknown_exact_contract_session_spec(tmp_path: Path) -> None:
    """Ne pozvolyaet stale spec fallback dlya missing contract/session key."""
    request = _build_request(tmp_path)
    source = next(item for item in request.sources if item.kind == "spec_proxy")
    frame = pd.read_parquet(source.artifact_path)
    first_session = frame.iloc[0]["session_date"]
    reduced = frame.loc[
        ~((frame["contract_id"] == "BRH1") & (frame["session_date"] == first_session))
    ].reset_index(drop=True)
    mutated = _replace_source(request, "spec_proxy", artifact_frame=reduced)
    with pytest.raises(ValueError, match="exact contract/session sizing spec"):
        prepare_v8_evaluation(mutated)


def test_authoritative_run_blocks_before_any_pnl_and_api_has_no_metrics(
    tmp_path: Path,
) -> None:
    """Fiksiruet final-context admission block i target-free public signature."""
    prepared = prepare_v8_evaluation(_build_request(tmp_path))
    parameters = inspect.signature(run_v8_evaluation).parameters
    assert "metrics" not in parameters
    assert "equity" not in parameters
    with pytest.raises(V8EvaluationBlockedError, match="full-context admission"):
        run_v8_evaluation(prepared, initial_cash=1_000_000.0)


def test_corridor_bridge_uses_stop_first_and_separate_scenario_windows(
    tmp_path: Path,
) -> None:
    """Runs a full entry/bracket exit through stateful event -> common ledger."""
    request = _build_request(
        tmp_path,
        decision_dates=_multi_year_dates(),
        active_sequences=frozenset({0}),
        include_br_candles=True,
    )
    request = _set_br_strategy_signal(request, 0, family="corridor")
    request = _set_high_capacity_candles(
        request,
        ambiguous_corridor_first_settlement=True,
    )
    result = run_v8_evaluation(
        prepare_v8_evaluation(request),
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    corridor_orders = tuple(
        item
        for item in result.orders
        if item.single_position is not None
        and item.single_position.strategy_id == "volatility_corridor_harvest"
    )
    assert corridor_orders
    assert not any(
        item.code == "generic_sleeve_substitution_forbidden"
        for item in result.failure_events
    )
    primary = tuple(
        item
        for item in result.evidence
        if item.scenario_id is V8ScenarioId.PRIMARY
        and item.order_id.startswith(("entry-volatility", "exit-corridor"))
    )
    doubled = tuple(
        item
        for item in result.evidence
        if item.scenario_id is V8ScenarioId.DOUBLE_COST
        and item.order_id.startswith(("entry-volatility", "exit-corridor"))
    )
    delayed = tuple(
        item
        for item in result.evidence
        if item.scenario_id is V8ScenarioId.DELAY
        and item.order_id.startswith("entry-volatility")
    )
    assert len(primary) == 2
    assert len(doubled) == 2
    assert len(delayed) == 1
    assert primary[0].legs[0].window_opened_at == doubled[0].legs[0].window_opened_at
    assert delayed[0].legs[0].window_opened_at == primary[0].legs[0].window_closed_at
    # Both stop and TP were touched; the long exits at the adverse low, never at TP.
    assert primary[1].legs[0].execution_price == 97.0
    primary_ledger = result.ledger_matrix.ledger(
        "volatility_corridor_harvest",
        V8ScenarioId.PRIMARY,
    )
    assert primary_ledger.positions == ()


def test_corridor_missing_union_bar_is_terminal_no_go(tmp_path: Path) -> None:
    """A missing held-contract row becomes an unresolved machine state, not a fill."""
    request = _build_request(
        tmp_path,
        decision_dates=_multi_year_dates(),
        active_sequences=frozenset({0}),
        include_br_candles=True,
    )
    request = _set_br_strategy_signal(request, 0, family="corridor")
    request = _set_high_capacity_candles(request, add_missing_br_union_slot=True)
    result = run_v8_evaluation(
        prepare_v8_evaluation(request),
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    assert any(
        item.code == "missing_corridor_factual_bar"
        for item in result.failure_events
    )
    assert any(
        item.code == "unresolved_terminal_stateful_corridor"
        and item.metric_critical_increment == 1
        for item in result.failure_events
    )
    gate = next(
        item
        for item in result.gates_and_ranking.outcomes
        if item.strategy_id == "volatility_corridor_harvest"
    )
    assert gate.passed is False


def test_corridor_partial_entry_is_unresolved_terminal_no_go(tmp_path: Path) -> None:
    """A partial bracket entry never becomes a fabricated one-contract position."""
    request = _build_request(
        tmp_path,
        decision_dates=_multi_year_dates(),
        active_sequences=frozenset({0}),
        include_br_candles=True,
    )
    request = _set_br_strategy_signal(request, 0, family="corridor")
    result = run_v8_evaluation(
        prepare_v8_evaluation(request),
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    entries = tuple(
        item
        for item in result.evidence
        if item.order_id.startswith("entry-volatility")
    )
    assert len(entries) == len(V8ScenarioId)
    assert all(item.status.value == "partial_carry" for item in entries)
    assert all(item.executed_contracts != 0 for item in entries)
    assert all(item.carry_contracts != 0 for item in entries)
    assert any(
        item.code == "unresolved_corridor_entry"
        for item in result.failure_events
    )
    terminal = tuple(
        item
        for item in result.failure_events
        if item.code == "unresolved_terminal_stateful_corridor"
    )
    assert len(terminal) == len(V8ScenarioId)
    assert all(item.metric_critical_increment == 1 for item in terminal)
    for scenario in V8ScenarioId:
        ledger = result.ledger_matrix.ledger(
            "volatility_corridor_harvest",
            scenario,
        )
        assert ledger.positions
        assert ledger.unresolved_orders


def test_breakout_bridge_advances_only_on_full_scenario_evidence(
    tmp_path: Path,
) -> None:
    """Exercises persistent ENTER, ADD and trailing exit in all isolated scenarios."""
    request = _build_request(
        tmp_path,
        decision_dates=_multi_year_dates(),
        active_sequences=frozenset({0, 1, 2}),
        include_br_candles=True,
    )
    request = _set_br_strategy_signal(
        request,
        0,
        family="breakout",
        close=100.0,
    )
    request = _set_br_strategy_signal(
        request,
        1,
        family="breakout",
        close=102.0,
    )
    request = _set_br_strategy_signal(
        request,
        2,
        family="neutral",
        close=90.0,
    )
    request = _set_high_capacity_candles(request)
    result = run_v8_evaluation(
        prepare_v8_evaluation(request),
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    breakout = tuple(
        item for item in result.evidence if item.order_id.startswith("breakout-")
    )
    assert len(breakout) == 9
    by_scenario = {
        scenario: tuple(item for item in breakout if item.scenario_id is scenario)
        for scenario in V8ScenarioId
    }
    assert all(len(rows) == 3 for rows in by_scenario.values())
    for scenario, rows in by_scenario.items():
        assert tuple(item.status.value for item in rows) == ("filled", "filled", "filled")
        ledger = result.ledger_matrix.ledger(
            "breakout_pyramiding_trailing_stop",
            scenario,
        )
        assert ledger.positions == ()
        assert ledger.unresolved_orders == ()
    primary_by_id = {item.order_id: item for item in by_scenario[V8ScenarioId.PRIMARY]}
    double_by_id = {
        item.order_id: item for item in by_scenario[V8ScenarioId.DOUBLE_COST]
    }
    delay_by_id = {item.order_id: item for item in by_scenario[V8ScenarioId.DELAY]}
    assert set(primary_by_id) == set(double_by_id) == set(delay_by_id)
    for order_id in primary_by_id:
        primary_window = primary_by_id[order_id].legs[0]
        doubled_window = double_by_id[order_id].legs[0]
        delayed_window = delay_by_id[order_id].legs[0]
        assert primary_window.window_opened_at == doubled_window.window_opened_at
        assert delayed_window.window_opened_at == primary_window.window_closed_at
    assert not any(
        item.code == "unresolved_terminal_stateful_breakout"
        for item in result.failure_events
    )


def test_breakout_invalid_observation_locks_and_carries_position(
    tmp_path: Path,
) -> None:
    """An inactive next snapshot locks the live breakout instead of force-closing it."""
    request = _build_request(
        tmp_path,
        decision_dates=_multi_year_dates(),
        active_sequences=frozenset({0}),
        include_br_candles=True,
    )
    request = _set_br_strategy_signal(request, 0, family="breakout")
    request = _set_high_capacity_candles(request)
    result = run_v8_evaluation(
        prepare_v8_evaluation(request),
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    breakout = tuple(
        item for item in result.evidence if item.order_id.startswith("breakout-")
    )
    assert len(breakout) == len(V8ScenarioId)
    assert all(item.status.value == "filled" for item in breakout)
    terminal = tuple(
        item
        for item in result.failure_events
        if item.code == "unresolved_terminal_stateful_breakout"
    )
    assert len(terminal) == len(V8ScenarioId)
    assert all("locked=1" in item.message for item in terminal)
    assert all(item.metric_critical_increment == 1 for item in terminal)
    for scenario in V8ScenarioId:
        ledger = result.ledger_matrix.ledger(
            "breakout_pyramiding_trailing_stop",
            scenario,
        )
        assert ledger.positions
        assert ledger.unresolved_orders == ()


def test_persistent_breakout_contract_roll_is_explicitly_blocked(
    tmp_path: Path,
) -> None:
    """Never compresses an old/new paired-roll state into one breakout contract."""
    request = _build_request(
        tmp_path,
        decision_dates=_multi_year_dates(),
        active_sequences=frozenset({0, 1}),
        include_br_candles=True,
    )
    request = _set_br_strategy_signal(request, 0, family="breakout")
    request = _set_high_capacity_candles(request)
    request = _roll_br_contract_after_sequence(request, 1)
    prepared = prepare_v8_evaluation(request)
    with pytest.raises(V8EvaluationBlockedError, match="persistent breakout roll unsupported"):
        run_v8_evaluation(
            prepared,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.SYNTHETIC_TEST,
        )


def test_missing_factual_candle_fails_closed(tmp_path: Path) -> None:
    """Zapreshchaet settlement price fallback pri active order/position."""
    prepared = prepare_v8_evaluation(_build_request(tmp_path, active_sequences=frozenset({0})))
    with pytest.raises(V8EvaluationBlockedError, match="missing factual settlement candle"):
        run_v8_evaluation(
            prepared,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.SYNTHETIC_TEST,
        )


def test_capacity_is_exit_first_persistent_and_terminal_carry_is_no_go(
    tmp_path: Path,
) -> None:
    """Proveryaet same-window exit-first cap i unresolved terminal audit."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            decision_dates=_multi_year_dates(),
            active_sequences=frozenset({0, 5}),
            include_br_candles=True,
        )
    )
    result = run_v8_evaluation(
        prepared,
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    core_primary = result.ledger_matrix.ledger(CORE_STRATEGY_ID, V8ScenarioId.PRIMARY)
    same_window = [
        item
        for item in result.evidence
        if item.scenario_id is V8ScenarioId.PRIMARY
        and item.base_execution.decision_at.astimezone(MOSCOW).date() == _multi_year_dates()[5]
        and item.order_id.startswith(("exit-core", "entry-core"))
    ]
    assert same_window
    exit_rows = [item for item in same_window if item.order_id.startswith("exit-core")]
    entry_rows = [item for item in same_window if item.order_id.startswith("entry-core")]
    assert sum(abs(item.executed_contracts) for item in exit_rows) == 1
    assert all(item.executed_contracts == 0 for item in entry_rows)
    assert core_primary.unresolved_orders
    gate = next(
        item for item in result.gates_and_ranking.outcomes if item.strategy_id == CORE_STRATEGY_ID
    )
    assert gate.passed is False
    assert dict(gate.checks)["terminal_resolution"] is False


def test_missing_capacity_records_failure_and_two_runs_do_not_leak_state(
    tmp_path: Path,
) -> None:
    """Unknown capacity stanovitsya NO-GO i repeated run ostayetsya byte-stable."""
    prepared = prepare_v8_evaluation(
        _build_request(
            tmp_path,
            decision_dates=_multi_year_dates(),
            active_sequences=frozenset({0, 5}),
            include_br_candles=True,
            missing_capacity=True,
        )
    )
    first = run_v8_evaluation(
        prepared,
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    second = run_v8_evaluation(
        prepared,
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    assert first.result_sha256 == second.result_sha256
    assert any("capacity" in item.message for item in first.failure_events)
    assert all(not item.passed for item in first.gates_and_ranking.outcomes)


def test_content_addressed_persistence_replays_and_rejects_forged_metrics(
    tmp_path: Path,
) -> None:
    """Persist rehash/replay blokiruet forged metrics i pishet BOM artifacts."""
    prepared = prepare_v8_evaluation(
        _build_request(tmp_path / "inputs", decision_dates=_multi_year_dates())
    )
    result = run_v8_evaluation(
        prepared,
        initial_cash=1_000_000.0,
        mode=V8EvaluationMode.SYNTHETIC_TEST,
    )
    first_bundle = result.metrics[0]
    primary = first_bundle.scenario(V8ScenarioId.PRIMARY)
    forged_primary = replace(primary, net_cagr=primary.net_cagr + 0.25)
    forged_bundle = replace(
        first_bundle,
        scenarios=tuple(
            forged_primary if item.scenario_id is V8ScenarioId.PRIMARY else item
            for item in first_bundle.scenarios
        ),
    )
    forged = replace(result, metrics=(forged_bundle, *result.metrics[1:]))
    with pytest.raises(ValueError, match="forged/caller-supplied metrics"):
        persist_v8_evaluation_result(
            forged,
            prepared=prepared,
            project_root=PROJECT_ROOT,
            output_directory=tmp_path / "forged",
        )
    persisted = persist_v8_evaluation_result(
        result,
        prepared=prepared,
        project_root=PROJECT_ROOT,
        output_directory=tmp_path / "run",
    )
    assert persisted.manifest_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert _bytes_sha(persisted.manifest_path) == persisted.manifest_sha256
    assert {item.kind for item in persisted.artifacts} == {
        "input_identity",
        "code_identity",
        "decisions",
        "orders",
        "execution_evidence",
        "fills",
        "equity",
        "scenario_metrics",
        "gates",
        "ranking",
        "failure_events",
        "report",
    }
    assert all(item.path.read_bytes().startswith(b"\xef\xbb\xbf") for item in persisted.artifacts)


def test_blocked_wrapper_writes_failure_but_no_success_manifest(tmp_path: Path) -> None:
    """Authoritative block atomarno ostavlyaet failure event bez false success."""
    prepared = prepare_v8_evaluation(_build_request(tmp_path / "inputs"))
    output = tmp_path / "blocked"
    with pytest.raises(V8EvaluationBlockedError):
        run_and_persist_v8_evaluation(
            prepared,
            initial_cash=1_000_000.0,
            mode=V8EvaluationMode.AUTHORITATIVE,
            project_root=PROJECT_ROOT,
            output_directory=output,
        )
    assert tuple(output.glob("failure_events-*.json"))
    assert not tuple(output.glob("evaluation-run-*.json"))
