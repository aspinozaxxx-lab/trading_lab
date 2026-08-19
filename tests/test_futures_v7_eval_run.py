"""Testy sealed input, timing, participation i artifacts futures-v7 eval-run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import market_lab.futures_v7.eval_run as eval_run
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult
from market_lab.futures.spec_proxy import SPEC_PROXY_VERSION
from market_lab.futures_v7.config import V7_ASSETS
from market_lab.futures_v7.evaluation import (
    V7ScenarioResult,
    evaluate_v7_gates,
    fixed_v7_scenarios,
)
from market_lab.futures_v7.train_run import (
    V7_MODEL_ID_PREFIX,
    V7_PREDICTION_COLUMNS,
    V7_RUN_FORMAT,
    VerifiedV7AssemblyManifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V7_CONFIG_SOURCE = PROJECT_ROOT / "configs" / "futures_v7_development_protocol.yaml"


def _sha(path: Path) -> str:
    """Hashiruet synthetic artifact dlya byte-seal testov."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _predictions(
    dates: pd.DatetimeIndex,
    *,
    model_id: str = "synthetic-v7-model",
    asset_valid: np.ndarray | None = None,
) -> pd.DataFrame:
    """Stroit polnye four-asset OOS prediction snapshots D18:50 MSK."""
    rows: list[dict[str, object]] = []
    for index, decision_date in enumerate(dates):
        decision_at = (
            decision_date.tz_localize("Europe/Moscow")
            + pd.Timedelta(hours=18, minutes=50)
        ).tz_convert("UTC")
        for asset_index, asset in enumerate(V7_ASSETS):
            valid = asset_valid is None or bool(asset_valid[index, asset_index])
            rows.append(
                {
                    "decision_date": decision_date,
                    "decision_at": decision_at,
                    "asset": asset,
                    "candidate_score": (
                        (-1.0) ** asset_index * (0.2 + index * 0.01)
                        if valid
                        else np.nan
                    ),
                    "model_id": model_id,
                }
            )
    return pd.DataFrame(rows, columns=list(V7_PREDICTION_COLUMNS))


def _install_v7_config(root: Path) -> Path:
    """Kopiruet sealed config byte-v-byte v synthetic project root."""
    target = root / "configs" / V7_CONFIG_SOURCE.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(V7_CONFIG_SOURCE.read_bytes())
    return target


def _synthetic_calendar() -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Stroit po dve OOS decision dates na kazhdyi iz pyati foldov."""
    dates = pd.DatetimeIndex(
        [
            pd.Timestamp(f"{year}-{month_day}")
            for year in range(2021, 2026)
            for month_day in ("01-04", "07-01")
        ]
    )
    asset_valid = np.ones((len(dates), len(V7_ASSETS)), dtype=bool)
    asset_valid[3, 1] = False
    return dates, asset_valid


def _model_identity(root: Path) -> tuple[str, str]:
    """Vychislyaet sealed architecture SHA i model-id kak training runner."""
    config = eval_run.load_v7_research_config(
        root / "configs" / V7_CONFIG_SOURCE.name
    )
    architecture_sha = eval_run._canonical_json_sha256(
        config.model.model_dump(mode="json")
    )
    return architecture_sha, f"{V7_MODEL_ID_PREFIX}_{architecture_sha[:12]}"


def _assembly_identity(root: Path) -> VerifiedV7AssemblyManifest:
    """Stroit minimal'nuyu identity s target-free NPZ i poisoned labels."""
    _install_v7_config(root)
    manifest = root / "data" / "manifest.json"
    arrays = root / "data" / "arrays.npz"
    overlay = root / "data" / "overlay.parquet"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    dates, asset_valid = _synthetic_calendar()
    decisions = pd.DatetimeIndex(
        [
            (
                date.tz_localize("Europe/Moscow")
                + pd.Timedelta(hours=18, minutes=50)
            ).tz_convert("UTC").tz_localize(None)
            for date in dates
        ]
    )
    np.savez_compressed(
        arrays,
        sample_trade_dates=dates.to_numpy(dtype="datetime64[ns]").astype(np.int64),
        decision_times=decisions.to_numpy(dtype="datetime64[ns]").astype(np.int64),
        asset_valid=asset_valid,
        supervised_target=np.asarray(["forbidden-target"], dtype=object),
        supervised_valid=np.asarray(["forbidden-mask"], dtype=object),
    )
    manifest.write_bytes(b"synthetic-manifest")
    overlay.write_bytes(b"synthetic-overlay")
    return VerifiedV7AssemblyManifest(
        manifest_path=manifest,
        manifest_sha256=_sha(manifest),
        arrays_path=arrays,
        arrays_sha256=_sha(arrays),
        execution_overlay_path=overlay,
        execution_overlay_sha256=_sha(overlay),
        source_artifacts=(),
        payload={"arrays": {"sample_count": len(dates)}},
    )


def _write_training_outputs(
    root: Path,
    assembly: VerifiedV7AssemblyManifest,
) -> tuple[Path, str, Path, str]:
    """Pishet valid summary/prediction paru s vzaimnymi hashes."""
    output = root / "runs" / "training"
    output.mkdir(parents=True)
    predictions_path = output / "oos_predictions.parquet"
    dates, asset_valid = _synthetic_calendar()
    architecture_sha, model_id = _model_identity(root)
    predictions = _predictions(dates, model_id=model_id, asset_valid=asset_valid)
    predictions.to_parquet(predictions_path, index=False)
    prediction_sha = _sha(predictions_path)
    summary = {
        "format": V7_RUN_FORMAT,
        "research_status": "training_complete_no_pnl_no_holdout_access",
        "identity": {
            "config_sha256": eval_run.DEFAULT_V7_CONFIG_SHA256,
            "architecture_sha256": architecture_sha,
            "assembly_manifest_sha256": assembly.manifest_sha256,
            "assembly_arrays_sha256": assembly.arrays_sha256,
            "execution_overlay_sha256": assembly.execution_overlay_sha256,
        },
        "model_id": model_id,
        "fold_names": [f"outer_{year}" for year in range(2021, 2026)],
        "seeds": [1729, 2718, 3141],
        "expected_fold_count": 5,
        "expected_seed_count_per_fold": 3,
        "completed_seed_checkpoint_count": 15,
        "prediction_artifact": {
            "path": predictions_path.relative_to(root).as_posix(),
            "bytes": predictions_path.stat().st_size,
            "sha256": prediction_sha,
            "rows": len(predictions),
            "valid_candidate_scores": int(predictions["candidate_score"].notna().sum()),
            "masked_candidate_scores": int(predictions["candidate_score"].isna().sum()),
            "columns": list(V7_PREDICTION_COLUMNS),
            "mask_semantics": "causal_asset_valid_only_never_supervised_valid",
        },
        "oos_index_semantics": "trade_date_and_decision_timestamp_fold_bounds_only",
        "protected_holdout_start": "2026-01-01",
        "pnl_or_trading_metrics_computed": False,
    }
    summary_path = output / "training_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8-sig"
    )
    return summary_path, _sha(summary_path), predictions_path, prediction_sha


def _panel_active_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stroit 90-session market, active map i poslednie OOS predictions."""
    dates = pd.bdate_range("2020-09-01", periods=100)
    panel_rows: list[dict[str, object]] = []
    active_rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        for asset_index, asset in enumerate(V7_ASSETS):
            panel_rows.append(
                {
                    "trade_date": trade_date,
                    "asset_code": asset,
                    "close": (100.0 + asset_index * 20.0)
                    * np.exp(0.001 * index + 0.004 * np.sin(index * 0.3 + asset_index)),
                }
            )
            if index == 0:
                continue
            active_rows.append(
                {
                    "decision_date": dates[index - 1],
                    "effective_date": trade_date,
                    "observed_through": dates[index - 1],
                    "asset_code": asset,
                    "contract_id": f"{asset}:C1",
                    "plan_tradable": True,
                }
            )
    decision_dates = dates[-8:-3]
    return pd.DataFrame(panel_rows), pd.DataFrame(active_rows), _predictions(decision_dates)


def _target_snapshot() -> pd.DataFrame:
    """Stroit dva polnyh target snapshots s odnim non-flat asset."""
    rows: list[dict[str, object]] = []
    for index, effective_date in enumerate(pd.to_datetime(["2021-01-04", "2021-01-05"])):
        for asset in V7_ASSETS:
            nonflat = asset == "SI"
            rows.append(
                {
                    "effective_date": effective_date,
                    "decision_date": effective_date - pd.Timedelta(days=1),
                    "asset_code": asset,
                    "contract_id": "SI:C1" if nonflat else pd.NA,
                    "target_weight": 0.25 + index * 0.01 if nonflat else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _entry_volume(volume: float = 1_000.0) -> pd.DataFrame:
    """Stroit exact first-candle volume dlya synthetic SI order keys."""
    return pd.DataFrame(
        [
            {
                "session_date": date,
                "asset_code": "SI",
                "contract_id": "SI:C1",
                "entry_timestamp": pd.Timestamp(date).tz_localize("UTC")
                + pd.Timedelta(hours=16),
                "exact_open_available": True,
                "authoritative_unpriced_nontradable": False,
                "exact_entry_candle_volume": volume,
            }
            for date in pd.to_datetime(["2021-01-04", "2021-01-05"])
        ]
    )


def _orders(quantity: int, *, filled: bool = True) -> pd.DataFrame:
    """Stroit odnu ili dve filled nogi odnogo aggregate order key."""
    return pd.DataFrame(
        [
            {
                "session_date": pd.Timestamp("2021-01-04"),
                "asset_code": "SI",
                "contract_id": "SI:C1",
                "quantity_delta": quantity,
                "filled": filled,
            }
        ]
    )


def _passing_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stroit fixed 12-scenario i five-fold prohodyashchie metriki."""
    scenarios = pd.DataFrame(
        [
            {
                "candidate_id": eval_run.V7_EVALUATION_CANDIDATE_ID,
                "scenario_id": scenario.scenario_id,
                "cagr": 0.15 if scenario.scenario_id == "asset_s1_f1" else 0.04,
                "sharpe": 1.1,
                "maximum_drawdown": 0.10,
                "intraday_adverse_drawdown": 0.12,
                "execution_complete": True,
                "critical_execution_event_count": 0,
                "unresolved_halt_event_count": 0,
            }
            for scenario in fixed_v7_scenarios()
        ]
    )
    folds = pd.DataFrame(
        [
            {
                "candidate_id": eval_run.V7_EVALUATION_CANDIDATE_ID,
                "scenario_id": "asset_s1_f1",
                "fold_year": year,
                "cagr": -0.05 if year == 2021 else 0.08,
            }
            for year in range(2021, 2026)
        ]
    )
    return scenarios, folds


def _empty_result() -> V7ScenarioResult:
    """Stroit minimal'nyi immutable result dlya artifact persistence test."""
    raw = FuturesPortfolioLedgerResult(
        ledger=pd.DataFrame(
            {
                "session_date": [pd.Timestamp("2021-01-04")],
                "starting_cash": [1_000_000.0],
                "ending_cash": [1_000_000.0],
                "intraday_adverse_equity": [1_000_000.0],
            }
        ),
        positions=pd.DataFrame(),
        orders=pd.DataFrame(
            columns=[
                "session_date",
                "asset_code",
                "contract_id",
                "quantity_delta",
                "filled",
            ]
        ),
        metrics={},
        execution_complete=True,
    )
    return V7ScenarioResult(
        raw=raw,
        scored_ledger=raw.ledger,
        failure_events=pd.DataFrame(columns=["event_id", "scenario_id"]),
        metrics={},
        execution_complete=True,
    )


def test_training_hash_and_exact_target_free_calendar_are_enforced(
    tmp_path: Path,
) -> None:
    """Lovit byte-tamper i ne prinimaet odnu podstavnuyu datu na fold."""
    root = tmp_path
    assembly = _assembly_identity(root)
    summary, summary_sha, predictions, prediction_sha = _write_training_outputs(
        root, assembly
    )
    verified = eval_run.verify_v7_training_outputs(
        root,
        assembly,
        summary,
        summary_sha,
        predictions,
        prediction_sha,
    )
    assert len(verified.predictions) == 10 * len(V7_ASSETS)
    assert verified.predictions["candidate_score"].isna().sum() == 1
    assert verified.expected_oos_decision_count == 10
    with predictions.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        eval_run.verify_v7_training_outputs(
            root,
            assembly,
            summary,
            summary_sha,
            predictions,
            prediction_sha,
        )

    subset_root = tmp_path / "subset"
    subset_assembly = _assembly_identity(subset_root)
    summary, _, predictions, _ = _write_training_outputs(
        subset_root, subset_assembly
    )
    subset = pd.read_parquet(predictions)
    subset = subset.loc[subset["decision_date"].dt.month.eq(1)].reset_index(drop=True)
    subset.to_parquet(predictions, index=False)
    payload = json.loads(summary.read_text(encoding="utf-8-sig"))
    payload["prediction_artifact"].update(
        {
            "bytes": predictions.stat().st_size,
            "sha256": _sha(predictions),
            "rows": len(subset),
            "valid_candidate_scores": int(subset["candidate_score"].notna().sum()),
            "masked_candidate_scores": int(subset["candidate_score"].isna().sum()),
        }
    )
    summary.write_text(json.dumps(payload), encoding="utf-8-sig")
    with pytest.raises(ValueError, match="exact target-free calendar"):
        eval_run.verify_v7_training_outputs(
            subset_root,
            subset_assembly,
            summary,
            _sha(summary),
            predictions,
            _sha(predictions),
        )


def test_target_free_loader_never_reads_labels_and_rejects_arrays_tamper(
    tmp_path: Path,
) -> None:
    """Chitaet tri razreshennyh NPZ key i fail-it pri arrays byte drift."""
    assembly = _assembly_identity(tmp_path)
    summary, summary_sha, predictions, prediction_sha = _write_training_outputs(
        tmp_path, assembly
    )
    verified = eval_run.verify_v7_training_outputs(
        tmp_path,
        assembly,
        summary,
        summary_sha,
        predictions,
        prediction_sha,
    )
    assert verified.expected_oos_decision_count == 10
    with assembly.arrays_path.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="Assembly arrays SHA-256 mismatch"):
        eval_run.verify_v7_training_outputs(
            tmp_path,
            assembly,
            summary,
            summary_sha,
            predictions,
            prediction_sha,
        )


def test_prediction_mask_must_equal_asset_valid_and_model_id_cannot_be_null(
    tmp_path: Path,
) -> None:
    """Trebuet exact causal mask i odin non-null sealed model-id na vseh rows."""
    assembly = _assembly_identity(tmp_path)
    summary, _, predictions, _ = _write_training_outputs(tmp_path, assembly)
    frame = pd.read_parquet(predictions)
    valid_index = frame.index[frame["candidate_score"].notna()][0]
    frame.loc[valid_index, "candidate_score"] = np.nan
    frame.to_parquet(predictions, index=False)
    payload = json.loads(summary.read_text(encoding="utf-8-sig"))
    payload["prediction_artifact"].update(
        {
            "bytes": predictions.stat().st_size,
            "sha256": _sha(predictions),
            "valid_candidate_scores": int(frame["candidate_score"].notna().sum()),
            "masked_candidate_scores": int(frame["candidate_score"].isna().sum()),
        }
    )
    summary.write_text(json.dumps(payload), encoding="utf-8-sig")
    with pytest.raises(ValueError, match="mask ne raven causal asset_valid"):
        eval_run.verify_v7_training_outputs(
            tmp_path,
            assembly,
            summary,
            _sha(summary),
            predictions,
            _sha(predictions),
        )

    null_root = tmp_path / "null_model"
    null_assembly = _assembly_identity(null_root)
    null_summary, _, null_predictions, _ = _write_training_outputs(
        null_root, null_assembly
    )
    null_frame = pd.read_parquet(null_predictions)
    null_frame.loc[0, "model_id"] = pd.NA
    null_frame.to_parquet(null_predictions, index=False)
    null_payload = json.loads(null_summary.read_text(encoding="utf-8-sig"))
    null_payload["prediction_artifact"].update(
        {
            "bytes": null_predictions.stat().st_size,
            "sha256": _sha(null_predictions),
        }
    )
    null_summary.write_text(json.dumps(null_payload), encoding="utf-8-sig")
    with pytest.raises(ValueError, match="model_id"):
        eval_run.verify_v7_training_outputs(
            null_root,
            null_assembly,
            null_summary,
            _sha(null_summary),
            null_predictions,
            _sha(null_predictions),
        )


def test_targets_are_next_open_causal_and_future_scores_leave_prefix_unchanged() -> None:
    """Dokazyvaet D->next session timing i target-independent causal prefix."""
    panel, active, predictions = _panel_active_fixture()
    baseline = eval_run.build_v7_evaluation_targets(panel, active, predictions)
    assert baseline["score_source"].eq(
        "sealed_oos_candidate_score_never_supervised_target"
    ).all()
    assert (
        pd.to_datetime(baseline["decision_date"])
        < pd.to_datetime(baseline["effective_date"])
    ).all()
    changed = predictions.copy()
    last_date = pd.Timestamp(changed["decision_date"].max())
    changed.loc[changed["decision_date"].eq(last_date), "candidate_score"] *= -99.0
    revised = eval_run.build_v7_evaluation_targets(panel, active, changed)
    prefix = pd.to_datetime(baseline["decision_date"]).lt(last_date)
    pd.testing.assert_frame_equal(
        baseline.loc[prefix].reset_index(drop=True),
        revised.loc[prefix].reset_index(drop=True),
    )

    decision_lookup = predictions.drop_duplicates("decision_date").set_index(
        "decision_date"
    )["decision_at"]
    overlay_rows: list[dict[str, object]] = []
    for row in baseline.loc[baseline["target_weight"].abs().gt(1e-12)].itertuples():
        decision_at = pd.Timestamp(decision_lookup.loc[pd.Timestamp(row.decision_date)])
        event_end = (
            pd.Timestamp(row.effective_date).tz_localize("Europe/Moscow")
            + pd.Timedelta(hours=18, minutes=50)
        ).tz_convert("UTC")
        overlay_rows.append(
            {
                "trade_date": row.effective_date,
                "decision_date": row.decision_date,
                "asset_code": row.asset_code,
                "contract_id": row.contract_id,
                "entry_timestamp": decision_at + pd.Timedelta(minutes=10),
                "conservative_open_at": decision_at + pd.Timedelta(minutes=10),
                "event_interval_end_at": event_end,
                "open": 100.0,
                "high": 102.0,
                "low": 98.0,
                "settle": 101.0,
                "exact_open_available": True,
            }
        )
    timing = eval_run.audit_v7_target_execution_timing(
        baseline,
        predictions,
        pd.DataFrame(overlay_rows),
    )
    assert timing["timing_valid"].all()
    assert (timing["entry_timestamp"] > timing["decision_at"]).all()

    halt_overlay = pd.DataFrame(overlay_rows)
    halt_overlay.loc[0, "exact_open_available"] = False
    halt_overlay.loc[0, "entry_timestamp"] = pd.NaT
    with pytest.raises(ValueError, match="causal exact next-open timing"):
        eval_run.audit_v7_target_execution_timing(
            baseline,
            predictions,
            halt_overlay,
        )
    halt_overlay["authoritative_unpriced_nontradable"] = False
    halt_overlay.loc[0, "authoritative_unpriced_nontradable"] = True
    classified = eval_run.audit_v7_target_execution_timing(
        baseline,
        predictions,
        halt_overlay,
    )
    assert classified["timing_valid"].all()
    assert classified["authoritative_unpriced_nontradable"].sum() == 1


def test_pre_pnl_and_realized_exact_first_candle_participation() -> None:
    """Trebuet coverage do PnL i gate-it aggregate filled delta po 1%."""
    targets = _target_snapshot()
    volumes = _entry_volume()
    pre_pnl = eval_run.audit_v7_pre_pnl_participation_coverage(targets, volumes)
    assert pre_pnl.complete
    result = SimpleNamespace(raw=SimpleNamespace(orders=_orders(9)))
    passed = eval_run.audit_v7_realized_entry_participation(
        {"asset_s1_f1": result}, volumes
    )
    assert passed.passed
    assert passed.maximum_participation == pytest.approx(0.009)

    breached = eval_run.audit_v7_realized_entry_participation(
        {"asset_s1_f1": SimpleNamespace(raw=SimpleNamespace(orders=_orders(11)))},
        volumes,
    )
    assert not breached.passed
    assert breached.breach_count == 1
    unknown = eval_run.audit_v7_realized_entry_participation(
        {"asset_s1_f1": result}, volumes.iloc[1:].copy()
    )
    assert not unknown.passed
    assert unknown.unknown_volume_count == 1


def test_only_authoritative_unpriced_proof_allows_carry_before_pnl() -> None:
    """Ne putayet exact-open absence s proof i nikogda ne razreshaet fill."""
    targets = _target_snapshot().iloc[:4].copy()
    volumes = _entry_volume().iloc[:1].copy()
    volumes.loc[:, "entry_timestamp"] = pd.NaT
    volumes.loc[:, "exact_open_available"] = False
    volumes.loc[:, "exact_entry_candle_volume"] = np.nan
    pre_pnl = eval_run.audit_v7_pre_pnl_participation_coverage(targets, volumes)
    assert not pre_pnl.complete
    assert pre_pnl.unknown_order_key_count == 1

    volumes.loc[:, "authoritative_unpriced_nontradable"] = True
    pre_pnl = eval_run.audit_v7_pre_pnl_participation_coverage(targets, volumes)
    assert pre_pnl.complete
    assert pre_pnl.coverage["authoritative_unpriced_nontradable"].all()

    result = SimpleNamespace(raw=SimpleNamespace(orders=_orders(1)))
    realized = eval_run.audit_v7_realized_entry_participation(
        {"asset_s1_f1": result}, volumes
    )
    assert not realized.passed
    assert realized.unknown_volume_count == 1


def test_unpriced_nontradable_evidence_requires_full_active_map_conjunction() -> None:
    """Ne vyvodit carry-proof iz odnogo otsutstviya exact open."""
    active = pd.DataFrame(
        [
            {
                "effective_date": "2022-03-01",
                "decision_date": "2022-02-28",
                "asset_code": "RI",
                "contract_id": "RTS:RIH2",
                "action": "carry_missing_mark",
                "reason": "missing_hold_mark",
                "plan_tradable": False,
                "execution_open_available": False,
                "ohlc_complete": False,
                "has_trade": False,
                "has_settlement": True,
                "carry_unfilled": True,
                "open": np.nan,
                "high": np.nan,
                "low": np.nan,
                "close": np.nan,
            }
        ]
    )
    overlay = pd.DataFrame(
        [
            {
                "trade_date": "2022-03-01",
                "decision_date": "2022-02-28",
                "asset_code": "RI",
                "contract_id": "RTS:RIH2",
                "entry_timestamp": pd.NaT,
                "conservative_open_at": "2022-02-28T16:00:00Z",
                "event_interval_end_at": "2022-03-01T15:50:00Z",
                "open": np.nan,
                "high": 100.0,
                "low": 100.0,
                "settle": 100.0,
                "exact_open_available": False,
            }
        ]
    )
    proven = eval_run.build_authoritative_unpriced_nontradable_evidence(
        active, overlay
    )
    assert proven["authoritative_unpriced_nontradable"].all()

    incomplete = active.assign(has_trade=True)
    rejected = eval_run.build_authoritative_unpriced_nontradable_evidence(
        incomplete, overlay
    )
    assert not rejected["authoritative_unpriced_nontradable"].any()

    with pytest.raises(ValueError, match="protivorechit overlay price"):
        eval_run.build_authoritative_unpriced_nontradable_evidence(
            active,
            overlay.assign(open=101.0),
        )
    with pytest.raises(ValueError, match="protivorechit overlay price"):
        eval_run.build_authoritative_unpriced_nontradable_evidence(
            active,
            overlay.assign(settle=np.nan),
        )


def test_execution_market_replaces_open_and_valuation_envelope_one_to_one() -> None:
    """Ne ostavlyaet daily-open fallback i trebuet exact overlay key set."""
    observations = pd.DataFrame(
        [
            {
                "trade_date": "2021-01-04",
                "asset_code": "SI",
                "canonical_contract_id": "SI:C1",
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 101.0,
                "settle": 102.0,
                "volume": 10_000.0,
            }
        ]
    )
    specs = pd.DataFrame(
        [
            {
                "trade_date": "2021-01-04",
                "asset_symbol": "SI",
                "canonical_contract_id": "SI:C1",
                "sizing_point_value": 1_000.0,
                "sizing_observed_session_date": "2020-12-31",
                "sizing_lag_sessions": 1,
                "sizing_usable": True,
                "realized_accounting_point_value": 1_000.0,
                "realized_available_after_session": True,
                "tick_size": 1.0,
                "conservative_fee_per_side": 2.0,
                "modeled_initial_margin": 5_000.0,
                "spec_proxy_version": SPEC_PROXY_VERSION,
                "approximate": True,
                "research_only": True,
                "historical_exchange_exact": False,
                "broker_exact": False,
            }
        ]
    )
    decision = pd.Timestamp("2020-12-31T15:50:00Z")
    overlay = pd.DataFrame(
        [
            {
                "trade_date": "2021-01-04",
                "decision_date": "2020-12-31",
                "asset_code": "SI",
                "contract_id": "SI:C1",
                "entry_timestamp": decision + pd.Timedelta(minutes=10),
                "conservative_open_at": decision + pd.Timedelta(minutes=10),
                "event_interval_end_at": pd.Timestamp("2021-01-04T15:50:00Z"),
                "open": 110.0,
                "high": 112.0,
                "low": 98.0,
                "settle": 102.0,
                "exact_open_available": True,
            }
        ]
    )
    market = eval_run.build_exact_v7_execution_market(observations, specs, overlay)
    assert market.iloc[0]["open"] == 110.0
    assert market.iloc[0]["high"] == 112.0
    assert market.iloc[0]["low"] == 98.0
    assert "daily_open_fallback" in market.iloc[0]["provenance"]
    with pytest.raises(ValueError, match="raznye one-to-one keys"):
        eval_run.build_exact_v7_execution_market(
            pd.concat([observations, observations.assign(trade_date="2021-01-05")]),
            pd.concat([specs, specs.assign(trade_date="2021-01-05")]),
            overlay,
        )


def test_pre_pnl_unknown_volume_blocks_scenario_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ne vyzyvaet ni odin ledger kogda exact volume coverage nepolna."""
    assembly = _assembly_identity(tmp_path)
    summary, summary_sha, predictions_path, prediction_sha = _write_training_outputs(
        tmp_path, assembly
    )
    training = eval_run.verify_v7_training_outputs(
        tmp_path,
        assembly,
        summary,
        summary_sha,
        predictions_path,
        prediction_sha,
    )
    inputs = eval_run.V7EvaluationInputs(
        project_root=tmp_path,
        assembly=assembly,
        training=training,
        panel=pd.DataFrame(),
        active_map=pd.DataFrame(),
        contract_observations=pd.DataFrame(),
        spec_proxy=pd.DataFrame(),
        execution_overlay=pd.DataFrame(),
        exact_entry_volume=pd.DataFrame(),
        input_seals={},
    )
    incomplete = eval_run.V7ParticipationCoverageAudit(
        possible_order_key_count=1,
        covered_order_key_count=0,
        unknown_order_key_count=1,
        exact_join=False,
        coverage=pd.DataFrame(),
        failures=pd.DataFrame([{"event_id": "missing"}]),
    )
    monkeypatch.setattr(eval_run, "build_v7_evaluation_targets", lambda *args: pd.DataFrame())
    monkeypatch.setattr(eval_run, "build_exact_v7_execution_market", lambda *args: pd.DataFrame())
    monkeypatch.setattr(eval_run, "audit_v7_target_execution_timing", lambda *args: pd.DataFrame())
    monkeypatch.setattr(
        eval_run,
        "verify_v7_evaluation_code_identity",
        lambda *args: {},
    )
    monkeypatch.setattr(
        eval_run,
        "audit_v7_pre_pnl_participation_coverage",
        lambda *args: incomplete,
    )
    called = False

    def forbidden(*args: object, **kwargs: object) -> object:
        """Fiksiruet nedopustimyi PnL call posle coverage failure."""
        nonlocal called
        called = True
        raise AssertionError("Scenario runner ne dolzhen byt' vyzvan")

    with pytest.raises(eval_run.V7ParticipationCoverageError):
        eval_run.run_v7_evaluation_from_inputs(
            inputs,
            tmp_path / "runs" / "eval",
            scenario_runner=forbidden,
        )
    assert not called


def test_participation_extends_fixed_gate_and_all_artifacts_are_sealed(
    tmp_path: Path,
) -> None:
    """Delaet NO_GO pri breach i atomarno seal-it polnyi output nabor."""
    scenarios, folds = _passing_metrics()
    fixed = evaluate_v7_gates(scenarios, folds)
    assert fixed.passed
    pre_pnl = eval_run.audit_v7_pre_pnl_participation_coverage(
        _target_snapshot(), _entry_volume()
    )
    breached = eval_run.V7RealizedParticipationAudit(
        order_key_count=1,
        covered_order_key_count=1,
        unknown_volume_count=0,
        breach_count=1,
        maximum_participation=0.02,
        threshold=0.01,
        rows=pd.DataFrame(),
    )
    rejected = eval_run._evaluation_gate_payload(fixed, pre_pnl, breached)
    assert not rejected["passed"]
    assert not rejected["checks"]["realized_first_candle_participation_lte_1pct"]

    assembly = _assembly_identity(tmp_path)
    summary, summary_sha, predictions_path, prediction_sha = _write_training_outputs(
        tmp_path, assembly
    )
    training = eval_run.verify_v7_training_outputs(
        tmp_path,
        assembly,
        summary,
        summary_sha,
        predictions_path,
        prediction_sha,
    )
    inputs = eval_run.V7EvaluationInputs(
        project_root=tmp_path,
        assembly=assembly,
        training=training,
        panel=pd.DataFrame(),
        active_map=pd.DataFrame(),
        contract_observations=pd.DataFrame(),
        spec_proxy=pd.DataFrame(),
        execution_overlay=pd.DataFrame(),
        exact_entry_volume=_entry_volume(),
        input_seals={
            "sealed": True,
            "evaluation_implementation": {"aggregate_sha256": "d" * 64},
        },
    )
    results = {
        scenario.scenario_id: _empty_result() for scenario in fixed_v7_scenarios()
    }
    realized = eval_run.audit_v7_realized_entry_participation(results, _entry_volume())
    gate = eval_run._evaluation_gate_payload(fixed, pre_pnl, realized)
    output = tmp_path / "runs" / "evaluation"
    artifacts = eval_run._persist_evaluation_artifacts(
        inputs,
        output,
        _target_snapshot(),
        pre_pnl,
        scenarios,
        folds,
        results,
        realized,
        gate,
    )
    assert artifacts.manifest_path.exists()
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8-sig"))
    assert set(manifest["artifacts"]) == set(eval_run.V7_EVALUATION_ARTIFACT_NAMES)
    for record in manifest["artifacts"].values():
        path = output / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert _sha(path) == record["sha256"]
    assert manifest["supervised_target_read_for_scores"] is False
    assert manifest["supervised_valid_read_for_scores"] is False
    assert manifest["assembly_npz_read_for_target_free_calendar"] is True
    assert manifest["assembly_npz_array_keys_read"] == [
        "sample_trade_dates",
        "decision_times",
        "asset_valid",
    ]


def test_evaluation_code_identity_rejects_mutation_and_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lovit code TOCTOU i propazhu faila do pervogo scenario/PnL call."""
    code = tmp_path / "src" / "sealed_eval.py"
    code.parent.mkdir(parents=True)
    code.write_text("VALUE = 1\n", encoding="utf-8-sig")
    monkeypatch.setattr(
        eval_run,
        "V7_EVALUATION_CODE_RELATIVE_PATHS",
        ("src/sealed_eval.py",),
    )
    identity = eval_run.build_v7_evaluation_code_identity(tmp_path)
    assert eval_run.verify_v7_evaluation_code_identity(tmp_path, identity) == identity
    code.write_text("VALUE = 2\n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="implementation identity mismatch"):
        eval_run.verify_v7_evaluation_code_identity(tmp_path, identity)
    code.unlink()
    with pytest.raises(FileNotFoundError):
        eval_run.verify_v7_evaluation_code_identity(tmp_path, identity)


def test_evaluation_code_seal_contains_all_local_python_source() -> None:
    """Fiksiruet ves' local Python closure i obyazatel'nye core moduli."""
    expected_core = {
        "src/market_lab/futures_v7/eval_run.py",
        "src/market_lab/futures_v7/evaluation.py",
        "src/market_lab/futures_v7/assembly.py",
        "src/market_lab/futures_v7/config.py",
        "src/market_lab/futures_v7/train_run.py",
        "src/market_lab/futures/v7_portfolio.py",
        "src/market_lab/futures/portfolio_construction.py",
        "src/market_lab/futures/execution_dataset.py",
        "src/market_lab/futures/portfolio_ledger.py",
        "src/market_lab/futures/spec_proxy.py",
        "src/market_lab/futures/session_timing.py",
        "src/market_lab/futures/v6_protocol.py",
        "src/market_lab/io_utils.py",
    }
    source_root = (PROJECT_ROOT / "src").resolve()
    expected_all = {
        path.resolve().relative_to(PROJECT_ROOT).as_posix()
        for path in source_root.rglob("*.py")
        if path.is_file()
    }
    identity = eval_run.build_v7_evaluation_code_identity(PROJECT_ROOT)
    actual = {str(record["path"]) for record in identity["files"]}
    assert expected_core <= actual
    assert actual == expected_all
    assert len(identity["files"]) == len(expected_all)
    for relative_name in actual:
        path = (PROJECT_ROOT / relative_name).resolve()
        path.relative_to(source_root)
        assert path.is_file()


def test_prediction_keys_must_equal_selected_active_map_keys() -> None:
    """Zapreshchaet podmenu ili propusk decision-asset key posle NPZ audita."""
    dates = pd.DatetimeIndex(["2021-01-04", "2021-01-05"])
    predictions = _predictions(dates)
    active = predictions.loc[:, ["decision_date", "asset"]].rename(
        columns={"asset": "asset_code"}
    )
    eval_run.audit_v7_prediction_active_key_identity(predictions, active)
    with pytest.raises(ValueError, match="active-map keys"):
        eval_run.audit_v7_prediction_active_key_identity(
            predictions,
            active.iloc[:-1].copy(),
        )
