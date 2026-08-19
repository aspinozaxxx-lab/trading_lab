"""Zapechatannyi orchestration development-ocenki futures-v7 bez holdout."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures.execution_dataset import (
    build_portfolio_market,
    map_decision_weights_to_next_open,
)
from market_lab.futures.session_timing import legacy_forts_decision_calendar
from market_lab.futures.v6_protocol import (
    FUTURES_V6_PROTOCOL_SHA256,
    FuturesV6Protocol,
    load_futures_v6_protocol,
    resolve_record_path,
)
from market_lab.futures.v7_portfolio import build_causal_v7_portfolio_targets
from market_lab.futures_v7.config import (
    DEFAULT_V7_CONFIG_SHA256,
    V7_ASSETS,
    V7_SEEDS,
    V7ResearchConfig,
    byte_sha256,
    load_v7_research_config,
)
from market_lab.futures_v7.evaluation import (
    V7GateDecision,
    V7ScenarioResult,
    evaluate_v7_gates,
    run_v7_scenarios,
)
from market_lab.futures_v7.train_run import (
    V7_MODEL_ID_PREFIX,
    V7_PREDICTION_COLUMNS,
    V7_RUN_FORMAT,
    VerifiedV7AssemblyManifest,
    build_v7_oos_prediction_frame,
    build_v7_oos_sample_indices,
    verify_v7_assembly_manifest,
)
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

V7_EVALUATION_FORMAT: Final[str] = (  # Versiya atomarnogo evaluation run.
    "market-lab-futures-v7-evaluation-v1"
)
V7_SCORE_START: Final[date] = date(2021, 1, 1)  # Nachalo development score.
V7_SCORE_END: Final[date] = date(2025, 12, 31)  # Konec development score.
V7_PROTECTED_FROM: Final[date] = date(2026, 1, 1)  # Zapreshchennyi holdout.
V7_PROTECTED_FROM_UTC: Final[pd.Timestamp] = (  # Lokal'naya 2026 granica v UTC.
    pd.Timestamp(V7_PROTECTED_FROM).tz_localize("Europe/Moscow").tz_convert("UTC")
)
V7_INITIAL_CASH: Final[float] = 1_000_000.0  # Obshchii RUB cash pool.
V7_MAXIMUM_ENTRY_PARTICIPATION: Final[float] = 0.01  # Fixed first-candle limit.
V7_EVALUATION_CANDIDATE_ID: Final[str] = (  # Stabil'nyi candidate ID.
    "causal_multiresolution_ensemble"
)
V7_CONFIG_PATH: Final[Path] = (  # Sealed target-free fold/calendar config.
    Path("configs/futures_v7_development_protocol.yaml")
)
V7_EVALUATION_CODE_RELATIVE_PATHS: Final[tuple[str, ...]] = (  # PnL code seal.
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
)
V7_EVALUATION_ARTIFACT_NAMES: Final[tuple[str, ...]] = (  # Polnyi output nabor.
    "input_seals.json",
    "targets.parquet",
    "pre_pnl_participation_coverage.csv",
    "scenario_metrics.csv",
    "metrics.json",
    "fold_metrics.csv",
    "execution_failures.csv",
    "orders.parquet",
    "equity_curve.parquet",
    "realized_participation.csv",
    "gate_decision.json",
    "report.md",
)


@dataclass(frozen=True, slots=True)
class VerifiedV7TrainingOutputs:
    """Hranit byte-proverennyi summary i OOS predictions bez model arrays."""

    summary_path: Path
    summary_sha256: str
    summary: dict[str, Any]
    predictions_path: Path
    predictions_sha256: str
    predictions: pd.DataFrame
    model_id: str
    config_path: Path
    config_sha256: str
    expected_oos_calendar_sha256: str
    expected_oos_decision_count: int


@dataclass(frozen=True, slots=True)
class V7TargetFreeOOSCalendar:
    """Hranit exact fold key/mask contract bez supervised arrays."""

    config: V7ResearchConfig
    config_path: Path
    config_sha256: str
    expected: pd.DataFrame
    calendar_sha256: str
    decision_count: int


@dataclass(frozen=True, slots=True)
class V7EvaluationInputs:
    """Obedinyaet vse proverennye frames i ih immutable identity."""

    project_root: Path
    assembly: VerifiedV7AssemblyManifest
    training: VerifiedV7TrainingOutputs
    panel: pd.DataFrame
    active_map: pd.DataFrame
    contract_observations: pd.DataFrame
    spec_proxy: pd.DataFrame
    execution_overlay: pd.DataFrame
    exact_entry_volume: pd.DataFrame
    input_seals: dict[str, Any]


@dataclass(frozen=True, slots=True)
class V7ParticipationCoverageAudit:
    """Hranit pre-PnL coverage exact volume ili sealed unpriced carry proof."""

    possible_order_key_count: int
    covered_order_key_count: int
    unknown_order_key_count: int
    exact_join: bool
    coverage: pd.DataFrame
    failures: pd.DataFrame

    @property
    def complete(self) -> bool:
        """Trebuet positive volume ili explicit unpriced-nontradable proof."""
        return bool(
            self.exact_join
            and self.unknown_order_key_count == 0
            and self.covered_order_key_count == self.possible_order_key_count
            and self.failures.empty
        )


class V7ParticipationCoverageError(ValueError):
    """Ostanavlivaet orchestration do PnL pri unknown exact 10m volume."""

    def __init__(self, audit: V7ParticipationCoverageAudit) -> None:
        """Sohranyaet machine-readable coverage audit dlya reporta."""
        self.audit = audit
        super().__init__(
            "V7 exact entry-volume coverage incomplete: "
            f"{audit.covered_order_key_count}/{audit.possible_order_key_count}"
        )


@dataclass(frozen=True, slots=True)
class V7RealizedParticipationAudit:
    """Hranit realized filled order participation vo vseh 12 scenario."""

    order_key_count: int
    covered_order_key_count: int
    unknown_volume_count: int
    breach_count: int
    maximum_participation: float
    threshold: float
    rows: pd.DataFrame

    @property
    def passed(self) -> bool:
        """Trebuet unknown=0 i maximum participation ne vyshe fixed 1%."""
        return bool(
            self.unknown_volume_count == 0
            and self.covered_order_key_count == self.order_key_count
            and self.breach_count == 0
            and self.maximum_participation <= self.threshold + 1e-12
        )


@dataclass(frozen=True, slots=True)
class V7EvaluationArtifacts:
    """Vozvrashchaet exact puti atomarno zapisannogo evaluation run."""

    output_directory: Path
    manifest_path: Path
    gate_path: Path
    targets_path: Path
    metrics_path: Path


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 faila potokovo."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(payload: Any) -> str:
    """Hashiruet JSON-compatible payload stabil'noi serializaciei."""
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _require_sha256(value: str, label: str) -> str:
    """Trebuet polnyi hex SHA-256 i vozvrashchaet lower-case formu."""
    normalized = str(value).lower()
    if len(normalized) != 64 or any(
        symbol not in "0123456789abcdef" for symbol in normalized
    ):
        raise ValueError(f"{label} ne yavlyaetsya SHA-256")
    return normalized


def _bounded_path(root: Path, value: Path, label: str) -> Path:
    """Razreshaet path strogo vnutri project root."""
    resolved_root = root.resolve()
    candidate = value if value.is_absolute() else resolved_root / value
    target = candidate.resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{label} vyshel iz project root: {target}") from error
    return target


def _read_json_object(path: Path) -> dict[str, Any]:
    """Chitaet BOM-sovmestimyi JSON object bez neyasnogo top-level tipa."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON ne yavlyaetsya object: {path}")
    return payload


def _verify_file_seal(path: Path, expected_sha256: str, label: str) -> str:
    """Sravnivaet obyazatel'nyi external byte-seal do chteniya faila."""
    expected = _require_sha256(expected_sha256, label)
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: {path}")
    return actual


def build_v7_evaluation_code_identity(project_root: Path) -> dict[str, Any]:
    """Hashiruet polnyi local Python source closure vnutri project src."""
    root = project_root.resolve()
    source_root = (root / "src").resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    relative_names = set(V7_EVALUATION_CODE_RELATIVE_PATHS)
    relative_names.update(
        path.resolve().relative_to(root).as_posix()
        for path in source_root.rglob("*.py")
        if path.is_file()
    )
    files: list[dict[str, Any]] = []
    for relative_name in sorted(relative_names):
        path = root.joinpath(*Path(relative_name).parts).resolve()
        try:
            path.relative_to(source_root)
        except ValueError as error:
            raise ValueError("Evaluation code path vyshel iz project src") from error
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "files": files,
        "aggregate_sha256": _canonical_json_sha256(files),
    }


def verify_v7_evaluation_code_identity(
    project_root: Path,
    expected: Any,
) -> dict[str, Any]:
    """Lovit mutation ili propazhu code posle pre-PnL identity commit."""
    if not isinstance(expected, dict):
        raise ValueError("Evaluation input seals ne imeyut code identity")
    actual = build_v7_evaluation_code_identity(project_root)
    if actual != expected:
        raise ValueError("Evaluation implementation identity mismatch")
    return actual


def _verify_assembly_payload_seal(assembly: VerifiedV7AssemblyManifest) -> None:
    """Proveryaet canonical payload seal novogo authoritative manifesta."""
    payload = dict(assembly.payload)
    stated = payload.pop("manifest_payload_sha256", None)
    if stated is None:
        raise ValueError("Assembly manifest ne imeet manifest_payload_sha256")
    expected = _require_sha256(str(stated), "Assembly payload seal")
    if _canonical_json_sha256(payload) != expected:
        raise ValueError("Assembly canonical payload SHA-256 mismatch")
    if not assembly.manifest_path.stem.endswith(expected[:16]):
        raise ValueError("Assembly manifest filename ne sootvetstvuet payload seal")


def _target_free_calendar_hash(
    expected: pd.DataFrame,
    config_sha256: str,
    fold_names: tuple[str, ...],
) -> str:
    """Hashiruet exact OOS decision/asset/mask rows bez score i targetov."""
    rows = [
        {
            "decision_date": pd.Timestamp(row.decision_date).date().isoformat(),
            "decision_at": pd.Timestamp(row.decision_at).isoformat(),
            "asset": str(row.asset),
            "score_required": bool(row.score_required),
            "fold_name": str(row.fold_name),
        }
        for row in expected.itertuples(index=False)
    ]
    return _canonical_json_sha256(
        {
            "version": "v7-target-free-oos-calendar-v1",
            "config_sha256": config_sha256,
            "fold_names": list(fold_names),
            "rows": rows,
        }
    )


def load_v7_target_free_oos_calendar(
    project_root: Path,
    assembly: VerifiedV7AssemblyManifest,
    *,
    config_path: Path = V7_CONFIG_PATH,
    expected_config_sha256: str = DEFAULT_V7_CONFIG_SHA256,
) -> V7TargetFreeOOSCalendar:
    """Lenivo chitaet tol'ko sample dates, decisions i causal asset mask iz NPZ."""
    root = project_root.resolve()
    resolved_config = _bounded_path(root, config_path, "V7 evaluation config")
    config = load_v7_research_config(
        resolved_config,
        _require_sha256(expected_config_sha256, "Expected V7 config"),
    )
    config_sha = byte_sha256(resolved_config)
    _verify_file_seal(
        assembly.arrays_path,
        assembly.arrays_sha256,
        "Assembly arrays",
    )
    try:
        with np.load(assembly.arrays_path, allow_pickle=False) as archive:
            sample_raw = np.asarray(archive["sample_trade_dates"]).copy()
            decision_raw = np.asarray(archive["decision_times"]).copy()
            asset_valid = np.asarray(archive["asset_valid"]).copy()
    except KeyError as error:
        raise ValueError("Assembly NPZ ne imeet target-free calendar key") from error
    if sample_raw.dtype.kind not in {"i", "M"}:
        raise ValueError("sample_trade_dates dolzhen byt' int64 ili datetime64")
    if decision_raw.dtype.kind not in {"i", "M"}:
        raise ValueError("decision_times dolzhen byt' int64 ili datetime64")
    if asset_valid.dtype.kind != "b":
        raise ValueError("asset_valid dolzhen byt' exact bool array")
    sample_dates = sample_raw.astype("datetime64[ns]").astype("datetime64[D]")
    decisions = decision_raw.astype("datetime64[ns]")
    if sample_dates.ndim != 1 or decisions.shape != sample_dates.shape:
        raise ValueError("Target-free sample calendar imeet nevernye formy")
    expected_asset_shape = (len(sample_dates), len(V7_ASSETS))
    if asset_valid.shape != expected_asset_shape:
        raise ValueError(
            f"asset_valid shape {asset_valid.shape} != {expected_asset_shape}"
        )
    if np.isnat(sample_dates).any() or np.isnat(decisions).any():
        raise ValueError("Target-free sample calendar ne dopuskaet NaT")
    if len(np.unique(sample_dates)) != len(sample_dates):
        raise ValueError("Target-free sample calendar soderzhit duplicate date")
    if len(np.unique(decisions)) != len(decisions):
        raise ValueError("Target-free sample calendar soderzhit duplicate decision")
    if len(decisions) > 1 and (np.diff(decisions) <= np.timedelta64(0, "ns")).any():
        raise ValueError("Target-free decision times ne vozrastayut strogo")
    local = pd.DatetimeIndex(decisions).tz_localize("UTC").tz_convert(
        config.development.decision_timezone
    )
    local_dates = local.tz_localize(None).to_numpy(dtype="datetime64[D]")
    if not np.array_equal(sample_dates, local_dates):
        raise ValueError("sample_trade_dates ne sovpadayut s local decision dates")
    if not (
        local.hour == 18
    ).all() or not (local.minute == 50).all() or not (local.second == 0).all():
        raise ValueError("Assembly decision_times dolzhny byt' rovno D18:50 MSK")
    if (sample_dates >= np.datetime64(V7_PROTECTED_FROM, "D")).any():
        raise ValueError("Target-free calendar pronik v protected 2026")
    arrays_record = assembly.payload.get("arrays")
    if not isinstance(arrays_record, dict) or int(
        arrays_record.get("sample_count", -1)
    ) != len(sample_dates):
        raise ValueError("Assembly manifest sample_count ne sovpadaet s calendar")

    used: set[int] = set()
    frames: list[pd.DataFrame] = []
    fold_names = tuple(fold.name for fold in config.development.folds)
    for fold in config.development.folds:
        indices = build_v7_oos_sample_indices(
            sample_dates,
            decisions,
            fold,
            config.development.decision_timezone,
        )
        overlap = used.intersection(int(index) for index in indices)
        if overlap:
            raise ValueError(f"V7 evaluation OOS folds overlap: {sorted(overlap)}")
        used.update(int(index) for index in indices)
        frame = build_v7_oos_prediction_frame(
            sample_dates,
            decisions,
            asset_valid,
            indices,
            np.zeros((len(indices), len(V7_ASSETS)), dtype=np.float64),
            "target-free-calendar",
        )
        frame = frame.rename(columns={"candidate_score": "calendar_score"})
        frame["score_required"] = frame["calendar_score"].notna()
        frame["fold_name"] = fold.name
        frames.append(
            frame.loc[
                :,
                [
                    "decision_date",
                    "decision_at",
                    "asset",
                    "score_required",
                    "fold_name",
                ],
            ]
        )
    expected = pd.concat(frames, ignore_index=True)
    keys = ["decision_date", "decision_at", "asset"]
    if expected.duplicated(keys).any():
        raise ValueError("Target-free OOS calendar soderzhit duplicate key")
    decision_count = int(expected["decision_at"].nunique())
    if len(expected) != decision_count * len(V7_ASSETS):
        raise ValueError("Target-free OOS calendar ne pokryvaet 4 asset na decision")
    calendar_sha = _target_free_calendar_hash(expected, config_sha, fold_names)
    return V7TargetFreeOOSCalendar(
        config=config,
        config_path=resolved_config,
        config_sha256=config_sha,
        expected=expected,
        calendar_sha256=calendar_sha,
        decision_count=decision_count,
    )


def _normalize_predictions(
    frame: pd.DataFrame,
    summary: dict[str, Any],
    calendar: V7TargetFreeOOSCalendar,
) -> pd.DataFrame:
    """Proveryaet polnye OOS score snapshots i exact decision timing."""
    if tuple(frame.columns) != V7_PREDICTION_COLUMNS:
        raise ValueError("OOS prediction columns/order mismatch")
    result = frame.copy()
    result["decision_date"] = pd.to_datetime(
        result["decision_date"], errors="raise"
    ).dt.normalize()
    result["decision_at"] = pd.to_datetime(
        result["decision_at"], errors="raise", utc=True
    )
    result["asset"] = result["asset"].astype("string").str.strip().str.upper()
    result["candidate_score"] = pd.to_numeric(
        result["candidate_score"], errors="coerce"
    )
    result["model_id"] = result["model_id"].astype("string")
    finite_or_missing = result["candidate_score"].isna() | np.isfinite(
        result["candidate_score"]
    )
    if not finite_or_missing.all():
        raise ValueError("OOS candidate_score dolzhen byt' finite ili NaN")
    model_id = str(summary.get("model_id", ""))
    if (
        not model_id
        or result["model_id"].isna().any()
        or result["model_id"].str.strip().eq("").any()
        or set(result["model_id"]) != {model_id}
    ):
        raise ValueError("OOS model_id ne sovpadaet s training summary")
    prediction_keys = ["decision_date", "decision_at", "asset"]
    if result.duplicated(prediction_keys).any():
        raise ValueError("OOS predictions soderzhat duplicate key")
    local_dates = (
        result["decision_at"]
        .dt.tz_convert("Europe/Moscow")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    if not local_dates.eq(result["decision_date"]).all():
        raise ValueError("OOS decision_date ne sovpadaet s decision_at MSK")
    local_decisions = result["decision_at"].dt.tz_convert("Europe/Moscow")
    if not (
        local_decisions.dt.hour.eq(18)
        & local_decisions.dt.minute.eq(50)
        & local_decisions.dt.second.eq(0)
    ).all():
        raise ValueError("OOS decision_at dolzhen byt' rovno D18:50 MSK")
    if result["decision_date"].dt.date.lt(V7_SCORE_START).any():
        raise ValueError("OOS predictions nachinayutsya do 2021 score period")
    if result["decision_date"].dt.date.gt(V7_SCORE_END).any():
        raise ValueError("OOS predictions vyshli za 2025 score period")
    if result["decision_date"].dt.date.ge(V7_PROTECTED_FROM).any():
        raise ValueError("OOS predictions pronikli v protected 2026")
    expected = calendar.expected
    compared = result.loc[:, prediction_keys].merge(
        expected.loc[:, [*prediction_keys, "score_required"]],
        on=prediction_keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not compared["_merge"].eq("both").all():
        missing = int(compared["_merge"].eq("right_only").sum())
        extra = int(compared["_merge"].eq("left_only").sum())
        raise ValueError(
            "OOS predictions ne ravny exact target-free calendar: "
            f"missing={missing}, extra={extra}"
        )
    checked = result.merge(
        expected.loc[:, [*prediction_keys, "score_required"]],
        on=prediction_keys,
        how="inner",
        validate="one_to_one",
    )
    if not checked["candidate_score"].notna().eq(checked["score_required"]).all():
        raise ValueError("OOS candidate_score mask ne raven causal asset_valid")
    return result.sort_values(
        ["decision_at", "asset", "model_id"], kind="mergesort", ignore_index=True
    )


def verify_v7_training_outputs(
    project_root: Path,
    assembly: VerifiedV7AssemblyManifest,
    training_summary_path: Path,
    expected_training_summary_sha256: str,
    predictions_path: Path,
    expected_predictions_sha256: str,
    *,
    config_path: Path = V7_CONFIG_PATH,
    expected_config_sha256: str = DEFAULT_V7_CONFIG_SHA256,
) -> VerifiedV7TrainingOutputs:
    """Fail-closed proveryaet training summary, identity i OOS Parquet."""
    root = project_root.resolve()
    summary_path = _bounded_path(root, training_summary_path, "Training summary")
    summary_sha = _verify_file_seal(
        summary_path,
        expected_training_summary_sha256,
        "Training summary",
    )
    summary = _read_json_object(summary_path)
    if summary.get("format") != V7_RUN_FORMAT:
        raise ValueError("Training summary format mismatch")
    if summary.get("research_status") != "training_complete_no_pnl_no_holdout_access":
        raise ValueError("Training summary status ne razreshaet evaluation")
    if summary.get("pnl_or_trading_metrics_computed") is not False:
        raise ValueError("Training summary uzhe soderzhit PnL")
    if summary.get("protected_holdout_start") != V7_PROTECTED_FROM.isoformat():
        raise ValueError("Training summary ne imeet protected 2026 boundary")
    calendar = load_v7_target_free_oos_calendar(
        root,
        assembly,
        config_path=config_path,
        expected_config_sha256=expected_config_sha256,
    )
    fold_names = summary.get("fold_names")
    if (
        not isinstance(fold_names, list)
        or tuple(map(str, fold_names))
        != tuple(fold.name for fold in calendar.config.development.folds)
        or int(summary.get("expected_fold_count", -1)) != 5
    ):
        raise ValueError("Training summary ne zavershil exact sealed five folds")
    if (
        tuple(summary.get("seeds", [])) != V7_SEEDS
        or int(summary.get("expected_seed_count_per_fold", -1)) != len(V7_SEEDS)
        or int(summary.get("completed_seed_checkpoint_count", -1))
        != 5 * len(V7_SEEDS)
    ):
        raise ValueError("Training summary ne zavershil fixed 5x3 seeds")
    identity = summary.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("Training summary identity otsutstvuet")
    architecture_sha = _canonical_json_sha256(
        calendar.config.model.model_dump(mode="json")
    )
    expected_identity = {
        "config_sha256": calendar.config_sha256,
        "architecture_sha256": architecture_sha,
        "assembly_manifest_sha256": assembly.manifest_sha256,
        "assembly_arrays_sha256": assembly.arrays_sha256,
        "execution_overlay_sha256": assembly.execution_overlay_sha256,
    }
    for key, expected in expected_identity.items():
        if str(identity.get(key, "")).lower() != expected:
            raise ValueError(f"Training/assembly identity mismatch: {key}")
    expected_model_id = f"{V7_MODEL_ID_PREFIX}_{architecture_sha[:12]}"
    if summary.get("model_id") != expected_model_id:
        raise ValueError("Training summary model_id ne sootvetstvuet architecture")
    record = summary.get("prediction_artifact")
    if not isinstance(record, dict):
        raise ValueError("Training summary ne imeet prediction_artifact")
    resolved_predictions = _bounded_path(root, predictions_path, "OOS predictions")
    stated_path = _bounded_path(
        root,
        Path(str(record.get("path", ""))),
        "Summary prediction artifact",
    )
    if stated_path != resolved_predictions:
        raise ValueError("Prediction path ne sovpadaet s training summary")
    prediction_sha = _verify_file_seal(
        resolved_predictions,
        expected_predictions_sha256,
        "OOS predictions",
    )
    if prediction_sha != str(record.get("sha256", "")).lower():
        raise ValueError("OOS predictions SHA ne sovpadaet s summary")
    if resolved_predictions.stat().st_size != int(record.get("bytes", -1)):
        raise ValueError("OOS predictions bytes ne sovpadayut s summary")
    if tuple(record.get("columns", [])) != V7_PREDICTION_COLUMNS:
        raise ValueError("Summary prediction columns mismatch")
    if record.get("mask_semantics") != (
        "causal_asset_valid_only_never_supervised_valid"
    ):
        raise ValueError("Summary prediction mask semantics mismatch")
    if summary.get("oos_index_semantics") != (
        "trade_date_and_decision_timestamp_fold_bounds_only"
    ):
        raise ValueError("Training summary OOS index semantics mismatch")
    predictions = _normalize_predictions(
        pd.read_parquet(resolved_predictions),
        summary,
        calendar,
    )
    if len(predictions) != int(record.get("rows", -1)):
        raise ValueError("OOS prediction rows ne sovpadayut s summary")
    valid_count = int(predictions["candidate_score"].notna().sum())
    if valid_count != int(record.get("valid_candidate_scores", -1)):
        raise ValueError("OOS valid score count ne sovpadaet s summary")
    if len(predictions) - valid_count != int(record.get("masked_candidate_scores", -1)):
        raise ValueError("OOS masked score count ne sovpadaet s summary")
    return VerifiedV7TrainingOutputs(
        summary_path=summary_path,
        summary_sha256=summary_sha,
        summary=summary,
        predictions_path=resolved_predictions,
        predictions_sha256=prediction_sha,
        predictions=predictions,
        model_id=str(summary["model_id"]),
        config_path=calendar.config_path,
        config_sha256=calendar.config_sha256,
        expected_oos_calendar_sha256=calendar.calendar_sha256,
        expected_oos_decision_count=calendar.decision_count,
    )


def _normalized_overlay(overlay: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet exact execution overlay i ego valuation envelope."""
    required = {
        "trade_date",
        "decision_date",
        "asset_code",
        "contract_id",
        "entry_timestamp",
        "open",
        "high",
        "low",
        "settle",
        "exact_open_available",
        "conservative_open_at",
        "event_interval_end_at",
    }
    if missing := required - set(overlay.columns):
        raise ValueError(f"Execution overlay ne soderzhit: {sorted(missing)}")
    result = overlay.copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    result["decision_date"] = pd.to_datetime(
        result["decision_date"], errors="coerce"
    ).dt.normalize()
    if result["trade_date"].dt.date.ge(V7_PROTECTED_FROM).any():
        raise ValueError("Execution overlay pronik v protected 2026")
    result["asset_code"] = (
        result["asset_code"].astype("string").str.strip().str.upper()
    )
    result["contract_id"] = result["contract_id"].astype("string").str.strip()
    result["entry_timestamp"] = pd.to_datetime(
        result["entry_timestamp"], errors="coerce", utc=True
    )
    result["conservative_open_at"] = pd.to_datetime(
        result["conservative_open_at"], errors="coerce", utc=True
    )
    result["event_interval_end_at"] = pd.to_datetime(
        result["event_interval_end_at"], errors="coerce", utc=True
    )
    for column in ("open", "high", "low", "settle"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    valid_available = result["exact_open_available"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not valid_available.all():
        raise ValueError("Exact open available dolzhen byt' exact bool")
    result["exact_open_available"] = result["exact_open_available"].astype(bool)
    keys = ["trade_date", "asset_code", "contract_id"]
    if result.duplicated(keys).any():
        raise ValueError("Execution overlay soderzhit duplicate exact key")
    available = result["exact_open_available"]
    exact_valid = (
        result["entry_timestamp"].notna()
        & np.isfinite(result["open"])
        & result["open"].gt(0.0)
        & result["entry_timestamp"].ge(result["conservative_open_at"])
        & result["entry_timestamp"].lt(result["event_interval_end_at"])
    )
    if not exact_valid.loc[available].all():
        raise ValueError("Available exact overlay open narushaet timing/price")
    envelope = available & (
        result["open"].gt(result["high"] + 1e-12)
        | result["open"].lt(result["low"] - 1e-12)
        | result["settle"].gt(result["high"] + 1e-12)
        | result["settle"].lt(result["low"] - 1e-12)
    )
    if envelope.any():
        raise ValueError("Execution overlay valuation envelope ne pokryvaet open/settle")
    return result.sort_values(keys, kind="mergesort", ignore_index=True)


def build_authoritative_unpriced_nontradable_evidence(
    active_map: pd.DataFrame,
    execution_overlay: pd.DataFrame,
) -> pd.DataFrame:
    """Dokazyvaet unpriced carry tol'ko polnoi conjunction iz active map."""
    required = {
        "effective_date",
        "decision_date",
        "asset_code",
        "contract_id",
        "action",
        "reason",
        "plan_tradable",
        "execution_open_available",
        "ohlc_complete",
        "has_trade",
        "has_settlement",
        "carry_unfilled",
        "open",
        "high",
        "low",
        "close",
    }
    if missing := required - set(active_map.columns):
        raise ValueError(f"Active map ne soderzhit unpriced proof: {sorted(missing)}")
    active = active_map.loc[:, sorted(required)].copy()
    active["effective_date"] = pd.to_datetime(
        active["effective_date"], errors="raise"
    ).dt.normalize()
    active["decision_date"] = pd.to_datetime(
        active["decision_date"], errors="coerce"
    ).dt.normalize()
    active["asset_code"] = active["asset_code"].astype("string").str.upper()
    active["contract_id"] = active["contract_id"].astype("string").str.strip()
    active["action"] = active["action"].astype("string")
    active["reason"] = active["reason"].astype("string")
    boolean_columns = (
        "plan_tradable",
        "execution_open_available",
        "ohlc_complete",
        "has_trade",
        "has_settlement",
        "carry_unfilled",
    )
    for column in boolean_columns:
        valid = active[column].isna() | active[column].map(
            lambda value: isinstance(value, (bool, np.bool_))
        )
        if not valid.all():
            raise ValueError(f"Active-map {column} dolzhen byt' bool ili NA")
    allowed_action_reason = (
        active["action"].eq("carry_missing_mark")
        & active["reason"].eq("missing_hold_mark")
    ) | (
        active["action"].eq("carry_unfilled_roll")
        & active["reason"].eq("missing_roll_execution_leg")
    )
    evidence = (
        active["decision_date"].notna()
        & active["contract_id"].notna()
        & active["plan_tradable"].eq(False).fillna(False)
        & active["execution_open_available"].eq(False).fillna(False)
        & active["ohlc_complete"].eq(False).fillna(False)
        & active["has_trade"].eq(False).fillna(False)
        & active["has_settlement"].eq(True).fillna(False)
        & active["carry_unfilled"].eq(True).fillna(False)
        & active[["open", "high", "low", "close"]].isna().all(axis=1)
        & allowed_action_reason.fillna(False)
    )
    proof = active.loc[
        evidence,
        ["effective_date", "decision_date", "asset_code", "contract_id"],
    ].rename(columns={"effective_date": "trade_date"})
    keys = ["trade_date", "decision_date", "asset_code", "contract_id"]
    if proof.duplicated(keys).any():
        raise ValueError("Authoritative unpriced proof soderzhit duplicate key")
    overlay = _normalized_overlay(execution_overlay)
    if not proof.empty:
        proof_match = proof.merge(
            overlay.loc[:, keys],
            on=keys,
            how="left",
            validate="one_to_one",
            indicator=True,
        )
        if not proof_match["_merge"].eq("both").all():
            raise ValueError("Authoritative unpriced proof ne imeet exact overlay key")
    proof["authoritative_unpriced_nontradable"] = True
    result = overlay.merge(proof, on=keys, how="left", validate="one_to_one")
    result["authoritative_unpriced_nontradable"] = result[
        "authoritative_unpriced_nontradable"
    ].eq(True)
    marked = result["authoritative_unpriced_nontradable"]
    contradictory_price = marked & (
        result["open"].notna()
        | ~np.isfinite(result["settle"])
        | result["settle"].le(0.0)
        | ~np.isfinite(result["high"])
        | ~np.isfinite(result["low"])
        | result["high"].lt(result["low"])
        | result["settle"].gt(result["high"] + 1e-12)
        | result["settle"].lt(result["low"] - 1e-12)
    )
    if (
        result.loc[marked, "exact_open_available"].any()
        or result.loc[marked, "entry_timestamp"].notna().any()
        or contradictory_price.any()
    ):
        raise ValueError("Authoritative unpriced proof protivorechit overlay price")
    return result.sort_values(
        ["trade_date", "asset_code", "contract_id"],
        kind="mergesort",
        ignore_index=True,
    )


def _load_exact_entry_candle_volume(
    project_root: Path,
    assembly: VerifiedV7AssemblyManifest,
    overlay: pd.DataFrame,
) -> pd.DataFrame:
    """Vosstanavlivaet volume exact first candle iz sealed 10m Parquet."""
    normalized_overlay = _normalized_overlay(overlay)
    exact = normalized_overlay.loc[
        normalized_overlay["exact_open_available"],
        ["trade_date", "asset_code", "contract_id", "entry_timestamp"],
    ].copy()
    pieces: list[pd.DataFrame] = []
    data_root = project_root.resolve() / "data"
    for record in assembly.source_artifacts:
        if record.get("kind") != "official_moex_10m_parquet":
            continue
        path = data_root.joinpath(*Path(str(record["path"])).parts).resolve()
        try:
            path.relative_to(data_root.resolve())
        except ValueError as error:
            raise ValueError("10m source path vyshel iz data root") from error
        frame = pd.read_parquet(
            path,
            columns=[
                "timestamp",
                "logical_symbol",
                "canonical_contract_id",
                "volume",
            ],
            filters=[("timestamp", "<", V7_PROTECTED_FROM_UTC)],
        )
        frame = frame.rename(
            columns={
                "logical_symbol": "asset_code",
                "canonical_contract_id": "contract_id",
                "volume": "exact_entry_candle_volume",
            }
        )
        if not frame.empty:
            pieces.append(frame)
    if not pieces:
        raise ValueError("Assembly ne ssylayetsya na official 10m Parquet")
    candles = pd.concat(pieces, ignore_index=True)
    candles["entry_timestamp"] = pd.to_datetime(
        candles.pop("timestamp"), errors="raise", utc=True
    )
    if candles["entry_timestamp"].ge(V7_PROTECTED_FROM_UTC).any():
        raise ValueError("Exact entry-volume loader pronik v protected 2026")
    candles["asset_code"] = (
        candles["asset_code"].astype("string").str.strip().str.upper()
    )
    candles["contract_id"] = candles["contract_id"].astype("string").str.strip()
    candles["exact_entry_candle_volume"] = pd.to_numeric(
        candles["exact_entry_candle_volume"], errors="coerce"
    )
    join = ["entry_timestamp", "asset_code", "contract_id"]
    selected = exact.merge(
        candles,
        on=join,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not selected["_merge"].eq("both").all():
        raise ValueError("Exact overlay entry ne imeet first 10m candle volume")
    selected = selected.drop(columns="_merge")
    if (
        ~np.isfinite(selected["exact_entry_candle_volume"])
        | selected["exact_entry_candle_volume"].lt(0.0)
    ).any():
        raise ValueError("Exact first 10m candle volume invalid")
    full = normalized_overlay.loc[
        :,
        [
            "trade_date",
            "asset_code",
            "contract_id",
            "entry_timestamp",
            "exact_open_available",
            "authoritative_unpriced_nontradable",
        ],
    ].merge(
        selected,
        on=["trade_date", "asset_code", "contract_id", "entry_timestamp"],
        how="left",
        validate="one_to_one",
    )
    return full.rename(columns={"trade_date": "session_date"}).sort_values(
        ["session_date", "asset_code", "contract_id"],
        kind="mergesort",
        ignore_index=True,
    )


def _protocol_frames_and_seals(
    project_root: Path,
    protocol_path: Path,
    expected_protocol_sha256: str,
) -> tuple[FuturesV6Protocol, dict[str, pd.DataFrame], dict[str, Any]]:
    """Zagruzhaet tol'ko sealed v5 market/spec artifacts posle full verify."""
    root = project_root.resolve()
    resolved_protocol = _bounded_path(root, protocol_path, "V6 protocol")
    protocol = load_futures_v6_protocol(
        resolved_protocol,
        expected_sha256=expected_protocol_sha256,
        verify_references=True,
        project_root=root,
    )
    required_ids = ("panel", "active_map", "contract_observations", "spec_proxy")
    paths = {
        record_id: resolve_record_path(root, protocol.artifact(record_id))
        for record_id in required_ids
    }
    frames = {record_id: pd.read_parquet(path) for record_id, path in paths.items()}
    seals = {
        "protocol": {
            "path": resolved_protocol.relative_to(root).as_posix(),
            "bytes": resolved_protocol.stat().st_size,
            "sha256": _sha256_file(resolved_protocol),
        },
        "artifacts": {
            record_id: {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "rows": len(frames[record_id]),
            }
            for record_id, path in paths.items()
        },
    }
    return protocol, frames, seals


def audit_v7_prediction_active_key_identity(
    predictions: pd.DataFrame,
    active_map: pd.DataFrame,
) -> None:
    """Trebuet exact prediction/active decision-asset keys bez podmeny dat."""
    required = {"decision_date", "asset_code"}
    if missing := required - set(active_map.columns):
        raise ValueError(f"Active map ne soderzhit key polya: {sorted(missing)}")
    prediction_keys = predictions.loc[:, ["decision_date", "asset"]].rename(
        columns={"asset": "asset_code"}
    )
    prediction_keys["decision_date"] = pd.to_datetime(
        prediction_keys["decision_date"], errors="raise"
    ).dt.normalize()
    prediction_keys["asset_code"] = (
        prediction_keys["asset_code"].astype("string").str.upper()
    )
    decisions = frozenset(prediction_keys["decision_date"])
    active_keys = active_map.loc[:, ["decision_date", "asset_code"]].copy()
    active_keys["decision_date"] = pd.to_datetime(
        active_keys["decision_date"], errors="raise"
    ).dt.normalize()
    active_keys["asset_code"] = active_keys["asset_code"].astype("string").str.upper()
    active_keys = active_keys.loc[active_keys["decision_date"].isin(decisions)]
    keys = ["decision_date", "asset_code"]
    compared = prediction_keys.merge(
        active_keys,
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not compared["_merge"].eq("both").all():
        raise ValueError("OOS prediction keys ne ravny selected active-map keys")


def load_verified_v7_evaluation_inputs(
    project_root: Path,
    assembly_manifest_path: Path,
    expected_assembly_manifest_sha256: str,
    training_summary_path: Path,
    expected_training_summary_sha256: str,
    predictions_path: Path,
    expected_predictions_sha256: str,
    *,
    v7_config_path: Path = V7_CONFIG_PATH,
    expected_v7_config_sha256: str = DEFAULT_V7_CONFIG_SHA256,
    v6_protocol_path: Path = Path("configs/futures_v6_experiment.yaml"),
    expected_v6_protocol_sha256: str = FUTURES_V6_PROTOCOL_SHA256,
    entry_volume_loader: Callable[
        [Path, VerifiedV7AssemblyManifest, pd.DataFrame], pd.DataFrame
    ] = _load_exact_entry_candle_volume,
) -> V7EvaluationInputs:
    """Chitaet tol'ko sealed target-free NPZ calendar i vse input seals."""
    root = project_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    assembly = verify_v7_assembly_manifest(
        root,
        assembly_manifest_path,
        _require_sha256(
            expected_assembly_manifest_sha256,
            "Expected assembly manifest",
        ),
    )
    _verify_assembly_payload_seal(assembly)
    training = verify_v7_training_outputs(
        root,
        assembly,
        training_summary_path,
        expected_training_summary_sha256,
        predictions_path,
        expected_predictions_sha256,
        config_path=v7_config_path,
        expected_config_sha256=expected_v7_config_sha256,
    )
    _, frames, protocol_seals = _protocol_frames_and_seals(
        root,
        v6_protocol_path,
        expected_v6_protocol_sha256,
    )
    audit_v7_prediction_active_key_identity(training.predictions, frames["active_map"])
    overlay = build_authoritative_unpriced_nontradable_evidence(
        frames["active_map"],
        pd.read_parquet(assembly.execution_overlay_path),
    )
    exact_volume = entry_volume_loader(root, assembly, overlay)
    code_identity = build_v7_evaluation_code_identity(root)
    input_seals = {
        "format": V7_EVALUATION_FORMAT,
        "assembly": {
            "manifest_path": assembly.manifest_path.relative_to(root).as_posix(),
            "manifest_sha256": assembly.manifest_sha256,
            "arrays_path": assembly.arrays_path.relative_to(root).as_posix(),
            "arrays_sha256": assembly.arrays_sha256,
            "arrays_file_read_for_target_free_calendar": True,
            "array_keys_read": [
                "sample_trade_dates",
                "decision_times",
                "asset_valid",
            ],
            "supervised_target_read": False,
            "supervised_valid_read": False,
            "log_price_read": False,
            "intraday_read": False,
            "daily_context_read": False,
            "execution_overlay_path": assembly.execution_overlay_path.relative_to(
                root
            ).as_posix(),
            "execution_overlay_sha256": assembly.execution_overlay_sha256,
        },
        "training": {
            "summary_path": training.summary_path.relative_to(root).as_posix(),
            "summary_sha256": training.summary_sha256,
            "predictions_path": training.predictions_path.relative_to(root).as_posix(),
            "predictions_sha256": training.predictions_sha256,
            "model_id": training.model_id,
            "v7_config_path": training.config_path.relative_to(root).as_posix(),
            "v7_config_sha256": training.config_sha256,
            "expected_oos_calendar_sha256": (
                training.expected_oos_calendar_sha256
            ),
            "expected_oos_decision_count": training.expected_oos_decision_count,
            "expected_oos_prediction_row_count": len(training.predictions),
        },
        "authoritative_unpriced_nontradable": {
            "evidence_source": "sealed_v5_active_map_full_conjunction",
            "overlay_row_count": int(
                overlay["authoritative_unpriced_nontradable"].sum()
            ),
            "absence_only_is_never_evidence": True,
            "filled_order_is_never_allowed_without_exact_positive_volume": True,
        },
        "v6_market_protocol": protocol_seals,
        "evaluation_implementation": code_identity,
        "protected_from": V7_PROTECTED_FROM.isoformat(),
        "score_source": "sealed_oos_predictions_only_never_supervised_target",
    }
    return V7EvaluationInputs(
        project_root=root,
        assembly=assembly,
        training=training,
        panel=frames["panel"],
        active_map=frames["active_map"],
        contract_observations=frames["contract_observations"],
        spec_proxy=frames["spec_proxy"],
        execution_overlay=overlay,
        exact_entry_volume=exact_volume,
        input_seals=input_seals,
    )


def _portfolio_market_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Pereimenuet causal adjusted close dlya fixed portfolio constructor."""
    required = {"trade_date", "asset_code", "close"}
    if missing := required - set(panel.columns):
        raise ValueError(f"Daily panel ne soderzhit: {sorted(missing)}")
    result = panel.loc[:, ["trade_date", "asset_code", "close"]].rename(
        columns={
            "trade_date": "session_date",
            "asset_code": "asset",
            "close": "adjusted_close",
        }
    )
    dates = pd.to_datetime(result["session_date"], errors="raise")
    if dates.dt.date.ge(V7_PROTECTED_FROM).any():
        raise ValueError("Daily panel pronik v protected 2026")
    return result


def _common_panel_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    """Stroit factual common decision D -> next modeled session calendar."""
    required = {"trade_date", "asset_code"}
    if missing := required - set(panel.columns):
        raise ValueError(f"Daily panel calendar ne soderzhit: {sorted(missing)}")
    frame = panel.loc[:, ["trade_date", "asset_code"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["asset_code"] = frame["asset_code"].astype("string").str.upper()
    per_asset = frame.groupby("asset_code")["trade_date"].apply(set)
    if set(per_asset.index) != set(V7_ASSETS):
        raise ValueError("Daily panel calendar imeet drugoi asset universe")
    common = sorted(set.intersection(*per_asset.tolist()))
    return legacy_forts_decision_calendar(common)


def _active_rows_for_decisions(
    active_map: pd.DataFrame,
    decision_dates: pd.Series,
) -> pd.DataFrame:
    """Ostavlyaet polnyi active snapshot tol'ko dlya OOS decision dates."""
    required = {
        "decision_date",
        "effective_date",
        "observed_through",
        "asset_code",
        "contract_id",
    }
    if missing := required - set(active_map.columns):
        raise ValueError(f"Active map ne soderzhit: {sorted(missing)}")
    decisions = pd.DatetimeIndex(pd.to_datetime(decision_dates, errors="raise")).normalize()
    active_dates = pd.to_datetime(active_map["decision_date"], errors="coerce").dt.normalize()
    selected = active_map.loc[active_dates.isin(decisions)].copy()
    expected_rows = len(decisions.unique()) * len(V7_ASSETS)
    if len(selected) != expected_rows:
        raise ValueError("Active map ne pokryvaet vse OOS decision snapshots")
    return selected


def build_v7_evaluation_targets(
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
    predictions: pd.DataFrame,
) -> pd.DataFrame:
    """Stroit fixed post-sleeve targets tol'ko iz sealed OOS predictions."""
    score_columns = {"decision_date", "asset", "candidate_score"}
    if missing := score_columns - set(predictions.columns):
        raise ValueError(f"OOS predictions ne soderzhat: {sorted(missing)}")
    scores = predictions.loc[:, sorted(score_columns)].copy()
    weights = build_causal_v7_portfolio_targets(
        _portfolio_market_panel(panel),
        scores,
    )
    if weights.empty:
        raise ValueError("Fixed V7 portfolio builder vernul pustye targets")
    timing = _common_panel_calendar(panel)
    active = _active_rows_for_decisions(active_map, weights["decision_date"])
    mapped = map_decision_weights_to_next_open(weights, timing, active)
    effective = pd.to_datetime(mapped["effective_date"], errors="raise").dt.normalize()
    if effective.dt.date.lt(V7_SCORE_START).any():
        raise ValueError("Mapped targets nachinayutsya do score period")
    if effective.dt.date.gt(V7_SCORE_END).any():
        raise ValueError("Mapped targets vyshli za development score period")
    mapped["score_source"] = "sealed_oos_candidate_score_never_supervised_target"
    return mapped.sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )


def build_exact_v7_execution_market(
    contract_observations: pd.DataFrame,
    spec_proxy: pd.DataFrame,
    execution_overlay: pd.DataFrame,
) -> pd.DataFrame:
    """Zamenyaet daily open/H/L exact open i valuation envelope one-to-one."""
    market = build_portfolio_market(contract_observations, spec_proxy)
    overlay = _normalized_overlay(execution_overlay).rename(
        columns={"trade_date": "session_date"}
    )
    keys = ["session_date", "asset_code", "contract_id"]
    compared = market.loc[:, keys].merge(
        overlay.loc[:, keys],
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not compared["_merge"].eq("both").all():
        raise ValueError("Daily market i exact overlay imeyut raznye one-to-one keys")
    exact = overlay.loc[
        :,
        [
            *keys,
            "entry_timestamp",
            "exact_open_available",
            "open",
            "high",
            "low",
        ],
    ].rename(
        columns={
            "open": "exact_open",
            "high": "valuation_envelope_high",
            "low": "valuation_envelope_low",
        }
    )
    merged = market.merge(exact, on=keys, how="inner", validate="one_to_one")
    merged["open"] = merged.pop("exact_open")
    merged["high"] = merged.pop("valuation_envelope_high")
    merged["low"] = merged.pop("valuation_envelope_low")
    valid_open = merged["open"].notna()
    invalid = valid_open & (
        merged["open"].le(0.0)
        | merged["open"].gt(merged["high"] + 1e-12)
        | merged["open"].lt(merged["low"] - 1e-12)
    )
    if invalid.any():
        raise ValueError("Exact execution market narushaet valuation envelope")
    if pd.to_datetime(merged["session_date"]).dt.date.ge(V7_PROTECTED_FROM).any():
        raise ValueError("Exact execution market pronik v protected 2026")
    merged["provenance"] = merged["provenance"].map(
        lambda value: json.dumps(
            {
                "base": json.loads(str(value)),
                "open": "first_factual_10m_open_gte_19:00",
                "high_low": "valuation_envelope_not_traded_extrema_claim",
                "one_to_one_overlay_join": True,
                "daily_open_fallback": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return merged.sort_values(keys, kind="mergesort", ignore_index=True)


def audit_v7_target_execution_timing(
    targets: pd.DataFrame,
    predictions: pd.DataFrame,
    overlay: pd.DataFrame,
) -> pd.DataFrame:
    """Dokazyvaet signal D18:50 -> exact open posle decision dlya non-flat."""
    decisions = predictions.loc[:, ["decision_date", "decision_at"]].drop_duplicates()
    decisions["decision_date"] = pd.to_datetime(
        decisions["decision_date"], errors="raise"
    ).dt.normalize()
    decisions["decision_at"] = pd.to_datetime(
        decisions["decision_at"], errors="raise", utc=True
    )
    if decisions["decision_date"].duplicated().any():
        raise ValueError("Prediction decision_date imeet neskol'ko decision_at")
    nonflat = targets.loc[
        pd.to_numeric(targets["target_weight"], errors="raise").abs().gt(1e-12)
    ].copy()
    nonflat["effective_date"] = pd.to_datetime(
        nonflat["effective_date"], errors="raise"
    ).dt.normalize()
    nonflat["decision_date"] = pd.to_datetime(
        nonflat["decision_date"], errors="raise"
    ).dt.normalize()
    normalized_overlay = _normalized_overlay(overlay).rename(
        columns={"trade_date": "effective_date"}
    )
    if "authoritative_unpriced_nontradable" not in normalized_overlay:
        normalized_overlay["authoritative_unpriced_nontradable"] = False
    evidence_valid = normalized_overlay["authoritative_unpriced_nontradable"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not evidence_valid.all():
        raise ValueError("Authoritative unpriced evidence dolzhen byt' exact bool")
    joined = nonflat.merge(
        decisions,
        on="decision_date",
        how="left",
        validate="many_to_one",
    ).merge(
        normalized_overlay.loc[
            :,
            [
                "effective_date",
                "decision_date",
                "asset_code",
                "contract_id",
                "entry_timestamp",
                "exact_open_available",
                "authoritative_unpriced_nontradable",
            ],
        ],
        on=["effective_date", "decision_date", "asset_code", "contract_id"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_overlay"),
        indicator=True,
    )
    joined["causal_exact_open"] = (
        joined["_merge"].eq("both")
        & joined["exact_open_available"].eq(True)
        & joined["entry_timestamp"].notna()
        & joined["decision_at"].notna()
        & joined["entry_timestamp"].gt(joined["decision_at"])
    )
    joined["authoritative_unpriced_nontradable"] = (
        joined["_merge"].eq("both")
        & joined["authoritative_unpriced_nontradable"].eq(True)
        & joined["exact_open_available"].notna()
        & joined["exact_open_available"].eq(False)
        & joined["entry_timestamp"].isna()
    )
    joined["timing_valid"] = (
        joined["causal_exact_open"]
        | joined["authoritative_unpriced_nontradable"]
    )
    if not joined["timing_valid"].all():
        raise ValueError("Non-flat target ne imeet causal exact next-open timing")
    return joined.drop(columns="_merge").sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )


def _normalized_exact_entry_volume(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet one-to-one exact first-candle volume table bez fill."""
    aliases = {"trade_date": "session_date"}
    result = frame.rename(
        columns={source: target for source, target in aliases.items() if target not in frame}
    ).copy()
    required = {
        "session_date",
        "asset_code",
        "contract_id",
        "entry_timestamp",
        "exact_open_available",
        "authoritative_unpriced_nontradable",
        "exact_entry_candle_volume",
    }
    if missing := required - set(result.columns):
        raise ValueError(f"Exact entry volume ne soderzhit: {sorted(missing)}")
    result = result.loc[:, sorted(required)].copy()
    result["session_date"] = pd.to_datetime(
        result["session_date"], errors="raise"
    ).dt.normalize()
    result["asset_code"] = result["asset_code"].astype("string").str.upper()
    result["contract_id"] = result["contract_id"].astype("string").str.strip()
    result["entry_timestamp"] = pd.to_datetime(
        result["entry_timestamp"], errors="coerce", utc=True
    )
    valid_available = result["exact_open_available"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not valid_available.all():
        raise ValueError("Exact open available dolzhen byt' exact bool")
    result["exact_open_available"] = result["exact_open_available"].astype(bool)
    valid_evidence = result["authoritative_unpriced_nontradable"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not valid_evidence.all():
        raise ValueError("Authoritative unpriced evidence dolzhen byt' exact bool")
    result["authoritative_unpriced_nontradable"] = result[
        "authoritative_unpriced_nontradable"
    ].astype(bool)
    result["exact_entry_candle_volume"] = pd.to_numeric(
        result["exact_entry_candle_volume"], errors="coerce"
    )
    proof = result["authoritative_unpriced_nontradable"]
    if (
        result.loc[proof, "exact_open_available"].any()
        or result.loc[proof, "entry_timestamp"].notna().any()
        or result.loc[proof, "exact_entry_candle_volume"].notna().any()
    ):
        raise ValueError("Authoritative unpriced proof protivorechit exact volume")
    keys = ["session_date", "asset_code", "contract_id"]
    if result.duplicated(keys).any():
        raise ValueError("Exact entry volume soderzhit duplicate key")
    if result["session_date"].dt.date.ge(V7_PROTECTED_FROM).any():
        raise ValueError("Exact entry volume pronik v protected 2026")
    return result.sort_values(keys, kind="mergesort", ignore_index=True)


def _possible_target_order_keys(targets: pd.DataFrame) -> pd.DataFrame:
    """Stroit conservative union entry/rebalance/exit keys do PnL sizing."""
    required = {
        "effective_date",
        "asset_code",
        "contract_id",
        "target_weight",
    }
    if missing := required - set(targets.columns):
        raise ValueError(f"Targets ne soderzhat order-key polya: {sorted(missing)}")
    frame = targets.loc[:, sorted(required)].copy()
    frame["effective_date"] = pd.to_datetime(
        frame["effective_date"], errors="raise"
    ).dt.normalize()
    frame["asset_code"] = frame["asset_code"].astype("string").str.upper()
    frame["contract_id"] = frame["contract_id"].astype("string").str.strip()
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="raise")
    rows: list[dict[str, object]] = []
    previous: dict[str, str | None] = {asset: None for asset in V7_ASSETS}
    for effective_date, snapshot in frame.groupby("effective_date", sort=True):
        indexed = snapshot.set_index("asset_code")
        if set(indexed.index) != set(V7_ASSETS):
            raise ValueError("Target snapshot ne pokryvaet full V7 universe")
        for asset in V7_ASSETS:
            row = indexed.loc[asset]
            current = (
                str(row["contract_id"])
                if abs(float(row["target_weight"])) > 1e-12
                and pd.notna(row["contract_id"])
                and str(row["contract_id"]) != "<NA>"
                else None
            )
            contracts = {contract for contract in (previous[asset], current) if contract}
            for contract in sorted(contracts):
                rows.append(
                    {
                        "session_date": pd.Timestamp(effective_date),
                        "asset_code": asset,
                        "contract_id": contract,
                        "possible_reason": (
                            "entry_or_rebalance"
                            if contract == current
                            else "prior_contract_exit"
                        ),
                    }
                )
            previous[asset] = current
    if not rows:
        return pd.DataFrame(
            columns=["session_date", "asset_code", "contract_id", "possible_reason"]
        )
    result = pd.DataFrame(rows)
    grouped = (
        result.groupby(
            ["session_date", "asset_code", "contract_id"],
            as_index=False,
            observed=True,
        )["possible_reason"]
        .agg(lambda values: "|".join(sorted(set(values))))
        .sort_values(["session_date", "asset_code", "contract_id"], ignore_index=True)
    )
    return grouped


def audit_v7_pre_pnl_participation_coverage(
    targets: pd.DataFrame,
    exact_entry_volume: pd.DataFrame,
) -> V7ParticipationCoverageAudit:
    """Fiksiruet 1% rule i explicit unpriced-carry proof do PnL."""
    possible = _possible_target_order_keys(targets)
    volumes = _normalized_exact_entry_volume(exact_entry_volume)
    keys = ["session_date", "asset_code", "contract_id"]
    joined = possible.merge(
        volumes,
        on=keys,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    joined["exact_volume_row"] = joined["_merge"].eq("both")
    joined["positive_exact_entry_volume"] = (
        joined["exact_open_available"].eq(True)
        & joined["exact_entry_candle_volume"].notna()
        & np.isfinite(joined["exact_entry_candle_volume"])
        & joined["exact_entry_candle_volume"].gt(0.0)
        & joined["entry_timestamp"].notna()
    )
    joined["covered"] = (
        joined["exact_volume_row"]
        & (
            joined["positive_exact_entry_volume"]
            | joined["authoritative_unpriced_nontradable"].eq(True)
        )
    )
    failures = joined.loc[~joined["covered"], keys].copy()
    failures["event_id"] = (
        "pre_pnl_volume:"
        + failures["session_date"].dt.date.astype(str)
        + "|"
        + failures["asset_code"].astype(str)
        + "|"
        + failures["contract_id"].astype(str)
    )
    failures["reason"] = np.where(
        joined.loc[~joined["covered"], "exact_volume_row"].to_numpy(),
        "nonpositive_or_unknown_exact_entry_candle_volume_without_proof",
        "missing_exact_entry_candle_volume_key",
    )
    failures = failures.loc[
        :, ["event_id", *keys, "reason"]
    ].reset_index(drop=True)
    if failures["event_id"].duplicated().any():
        raise ValueError("Pre-PnL participation failure event_id ne unikal'nyi")
    coverage = joined.drop(columns="_merge").sort_values(keys, ignore_index=True)
    return V7ParticipationCoverageAudit(
        possible_order_key_count=len(joined),
        covered_order_key_count=int(joined["covered"].sum()),
        unknown_order_key_count=int((~joined["covered"]).sum()),
        exact_join=bool(joined["exact_volume_row"].all()),
        coverage=coverage,
        failures=failures,
    )


def _combined_orders(
    results: dict[str, V7ScenarioResult],
) -> pd.DataFrame:
    """Obedinyaet immutable ledger orders vseh scenario s scenario_id."""
    frames: list[pd.DataFrame] = []
    for scenario_id, result in sorted(results.items()):
        frame = result.raw.orders.copy()
        frame.insert(0, "scenario_id", scenario_id)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["scenario_id"])
    return pd.concat(frames, ignore_index=True)


def audit_v7_realized_entry_participation(
    results: dict[str, V7ScenarioResult],
    exact_entry_volume: pd.DataFrame,
    *,
    threshold: float = V7_MAXIMUM_ENTRY_PARTICIPATION,
) -> V7RealizedParticipationAudit:
    """Gate-it aggregate filled deltas po exact first 10m candle volume."""
    if not np.isfinite(threshold) or not 0.0 < threshold <= 0.01:
        raise ValueError("Exact entry participation threshold dolzhen byt' v (0, 1%]")
    orders = _combined_orders(results)
    required = {
        "scenario_id",
        "session_date",
        "asset_code",
        "contract_id",
        "quantity_delta",
        "filled",
    }
    if missing := required - set(orders.columns):
        raise ValueError(f"Ledger orders ne soderzhat: {sorted(missing)}")
    orders["session_date"] = pd.to_datetime(
        orders["session_date"], errors="raise"
    ).dt.normalize()
    orders["quantity_delta"] = pd.to_numeric(
        orders["quantity_delta"], errors="raise"
    )
    filled = orders.loc[
        orders["filled"].eq(True)
        & orders["quantity_delta"].ne(0),
        [
            "scenario_id",
            "session_date",
            "asset_code",
            "contract_id",
            "quantity_delta",
        ],
    ].copy()
    keys = ["scenario_id", "session_date", "asset_code", "contract_id"]
    if filled.empty:
        empty = pd.DataFrame(
            columns=[
                *keys,
                "absolute_quantity",
                "entry_timestamp",
                "exact_entry_candle_volume",
                "exact_participation",
                "covered",
                "breach",
            ]
        )
        return V7RealizedParticipationAudit(0, 0, 0, 0, 0.0, threshold, empty)
    filled["absolute_quantity"] = filled["quantity_delta"].abs()
    aggregated = filled.groupby(keys, as_index=False, observed=True)[
        "absolute_quantity"
    ].sum()
    volumes = _normalized_exact_entry_volume(exact_entry_volume)
    joined = aggregated.merge(
        volumes,
        on=["session_date", "asset_code", "contract_id"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    joined["covered"] = (
        joined["_merge"].eq("both")
        & joined["exact_open_available"].eq(True)
        & joined["entry_timestamp"].notna()
        & joined["exact_entry_candle_volume"].notna()
        & np.isfinite(joined["exact_entry_candle_volume"])
        & joined["exact_entry_candle_volume"].gt(0.0)
    )
    joined["exact_participation"] = np.where(
        joined["covered"],
        joined["absolute_quantity"] / joined["exact_entry_candle_volume"],
        np.nan,
    )
    joined["breach"] = joined["covered"] & joined["exact_participation"].gt(
        threshold + 1e-12
    )
    maximum = (
        float(joined.loc[joined["covered"], "exact_participation"].max())
        if joined["covered"].any()
        else 0.0
    )
    rows = joined.drop(columns="_merge").sort_values(keys, ignore_index=True)
    return V7RealizedParticipationAudit(
        order_key_count=len(rows),
        covered_order_key_count=int(rows["covered"].sum()),
        unknown_volume_count=int((~rows["covered"]).sum()),
        breach_count=int(rows["breach"].sum()),
        maximum_participation=maximum,
        threshold=threshold,
        rows=rows,
    )


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet Parquet Zstandard v output directory."""
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    atomic_write_bytes(path, buffer.getvalue())


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet CSV UTF-8 BOM so stabil'nym newline."""
    atomic_write_text(path, frame.to_csv(index=False, lineterminator="\n"))


def _json_safe(value: Any) -> Any:
    """Prevrashchaet pandas/numpy znacheniya v JSON-compatible payload."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return str(value)
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _combined_failures(
    results: dict[str, V7ScenarioResult],
) -> pd.DataFrame:
    """Obedinyaet unique execution failure events vseh scenario."""
    frames: list[pd.DataFrame] = []
    for scenario_id, result in sorted(results.items()):
        frame = result.failure_events.copy()
        if "scenario_id" not in frame:
            frame.insert(0, "scenario_id", scenario_id)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["scenario_id", "event_id"])
    combined = pd.concat(frames, ignore_index=True)
    if "event_id" in combined and combined["event_id"].duplicated().any():
        raise ValueError("Combined execution failure event_id ne unikal'nyi")
    return combined


def _combined_equity(
    results: dict[str, V7ScenarioResult],
) -> pd.DataFrame:
    """Obedinyaet continuous raw ledger vseh scenario bez fold reset."""
    frames: list[pd.DataFrame] = []
    for scenario_id, result in sorted(results.items()):
        frame = result.raw.ledger.copy()
        frame.insert(0, "scenario_id", scenario_id)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["scenario_id"])
    return pd.concat(frames, ignore_index=True)


def _evaluation_gate_payload(
    fixed_gate: V7GateDecision,
    pre_pnl: V7ParticipationCoverageAudit,
    realized: V7RealizedParticipationAudit,
) -> dict[str, Any]:
    """Dobavlyaet execution-integrity preconditions bez smeny fixed gates."""
    checks = {
        **fixed_gate.checks,
        "pre_pnl_exact_entry_volume_coverage": pre_pnl.complete,
        "realized_exact_entry_volume_unknown_zero": realized.unknown_volume_count == 0,
        "realized_first_candle_participation_lte_1pct": (
            realized.breach_count == 0
            and realized.maximum_participation
            <= V7_MAXIMUM_ENTRY_PARTICIPATION + 1e-12
        ),
    }
    return {
        "format": V7_EVALUATION_FORMAT,
        "candidate_id": fixed_gate.candidate_id,
        "passed": bool(fixed_gate.passed and pre_pnl.complete and realized.passed),
        "fixed_strategy_gate_passed": fixed_gate.passed,
        "stretch_50_reached": fixed_gate.stretch_50_reached,
        "stretch_is_report_only": True,
        "checks": checks,
        "observed": {
            **fixed_gate.observed,
            "pre_pnl_possible_order_key_count": pre_pnl.possible_order_key_count,
            "pre_pnl_unknown_exact_volume_count": pre_pnl.unknown_order_key_count,
            "realized_filled_order_key_count": realized.order_key_count,
            "realized_unknown_exact_volume_count": realized.unknown_volume_count,
            "realized_participation_breach_count": realized.breach_count,
            "realized_maximum_first_candle_participation": (
                realized.maximum_participation
            ),
            "fixed_maximum_first_candle_participation": (
                V7_MAXIMUM_ENTRY_PARTICIPATION
            ),
        },
    }


def _report_markdown(
    inputs: V7EvaluationInputs,
    gate: dict[str, Any],
    scenario_metrics: pd.DataFrame,
    pre_pnl: V7ParticipationCoverageAudit,
    realized: V7RealizedParticipationAudit,
) -> str:
    """Stroit compact audit-report bez marketingovogo obeshchaniya pribyli."""
    primary = scenario_metrics.loc[
        scenario_metrics["scenario_id"].astype(str).eq("asset_s1_f1")
    ]
    primary_cagr = float(primary.iloc[0]["cagr"]) if len(primary) == 1 else float("nan")
    lines = [
        "# Futures-v7 development evaluation",
        "",
        f"- Model: `{inputs.training.model_id}`",
        f"- Score period: `{V7_SCORE_START}` .. `{V7_SCORE_END}`",
        f"- Gate: `{'GO' if gate['passed'] else 'NO_GO'}`",
        f"- Primary CAGR: `{primary_cagr:.6f}`",
        f"- Stretch 50% reached: `{gate['stretch_50_reached']}` (report-only)",
        f"- Fixed scenarios: `{len(scenario_metrics)}`",
        (
            "- Evaluation implementation SHA-256: `"
            f"{inputs.input_seals['evaluation_implementation']['aggregate_sha256']}`"
        ),
        (
            "- Pre-PnL exact volume coverage: "
            f"`{pre_pnl.covered_order_key_count}/{pre_pnl.possible_order_key_count}`"
        ),
        (
            "- Realized exact first-candle participation: "
            f"max `{realized.maximum_participation:.6%}`, "
            f"unknown `{realized.unknown_volume_count}`, "
            f"breaches `{realized.breach_count}`"
        ),
        "- Assembly NPZ read for target-free calendar: `True`",
        (
            "- Assembly NPZ keys read: `sample_trade_dates`, `decision_times`, "
            "`asset_valid`"
        ),
        "- supervised_target/supervised_valid read: `False`/`False`",
        "- Protected 2026 data accessed: `False`",
        "- Status: development research only; no profit guarantee.",
        "",
    ]
    return "\n".join(lines)


def _artifact_record(output: Path, path: Path) -> dict[str, Any]:
    """Stroit byte identity odnogo gotovogo evaluation artifact."""
    return {
        "path": path.relative_to(output).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _persist_evaluation_artifacts(
    inputs: V7EvaluationInputs,
    output: Path,
    targets: pd.DataFrame,
    pre_pnl: V7ParticipationCoverageAudit,
    scenario_metrics: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    results: dict[str, V7ScenarioResult],
    realized: V7RealizedParticipationAudit,
    gate: dict[str, Any],
) -> V7EvaluationArtifacts:
    """Atomarno pishet vse evaluation outputs i ih final manifest."""
    artifact_names = (*V7_EVALUATION_ARTIFACT_NAMES, "evaluation_manifest.json")
    existing = [output / name for name in artifact_names]
    if any(path.exists() for path in existing):
        raise FileExistsError("Evaluation output uzhe soderzhit authoritative artifact")
    output.mkdir(parents=True, exist_ok=True)
    paths = {name: output / name for name in V7_EVALUATION_ARTIFACT_NAMES}
    seals = {
        **inputs.input_seals,
        "fixed_participation_rule": {
            "volume": "exact_first_factual_10m_entry_candle",
            "maximum_participation": V7_MAXIMUM_ENTRY_PARTICIPATION,
            "unknown_volume_allowed": 0,
            "tuned": False,
            "pre_pnl_scope": "possible_target_entry_rebalance_exit_keys",
            "realized_scope": "aggregate_filled_order_keys_all_12_scenarios",
        },
    }
    write_json(paths["input_seals.json"], seals)
    _atomic_write_parquet(paths["targets.parquet"], targets)
    _atomic_write_csv(
        paths["pre_pnl_participation_coverage.csv"], pre_pnl.coverage
    )
    _atomic_write_csv(paths["scenario_metrics.csv"], scenario_metrics)
    write_json(
        paths["metrics.json"],
        {"scenarios": _json_safe(scenario_metrics.to_dict("records"))},
    )
    _atomic_write_csv(paths["fold_metrics.csv"], fold_metrics)
    _atomic_write_csv(paths["execution_failures.csv"], _combined_failures(results))
    _atomic_write_parquet(paths["orders.parquet"], _combined_orders(results))
    _atomic_write_parquet(paths["equity_curve.parquet"], _combined_equity(results))
    _atomic_write_csv(paths["realized_participation.csv"], realized.rows)
    write_json(paths["gate_decision.json"], _json_safe(gate))
    atomic_write_text(
        paths["report.md"],
        _report_markdown(inputs, gate, scenario_metrics, pre_pnl, realized),
    )
    manifest_path = output / "evaluation_manifest.json"
    artifact_records = {
        name: _artifact_record(output, path) for name, path in paths.items()
    }
    manifest = {
        "format": V7_EVALUATION_FORMAT,
        "research_status": "development_evaluation_complete_no_holdout_access",
        "protected_from": V7_PROTECTED_FROM.isoformat(),
        "candidate_id": V7_EVALUATION_CANDIDATE_ID,
        "model_id": inputs.training.model_id,
        "gate_passed": bool(gate["passed"]),
        "stretch_50_reached": bool(gate["stretch_50_reached"]),
        "scenario_count": len(scenario_metrics),
        "fold_row_count": len(fold_metrics),
        "artifacts": artifact_records,
        "input_seals_sha256": artifact_records["input_seals.json"]["sha256"],
        "evaluation_implementation_sha256": inputs.input_seals[
            "evaluation_implementation"
        ]["aggregate_sha256"],
        "assembly_npz_read_for_target_free_calendar": True,
        "assembly_npz_array_keys_read": [
            "sample_trade_dates",
            "decision_times",
            "asset_valid",
        ],
        "supervised_target_read_for_scores": False,
        "supervised_valid_read_for_scores": False,
        "pnl_uses_only_2021_2025_score_period_with_prior_market_warmup": True,
    }
    manifest["manifest_payload_sha256"] = _canonical_json_sha256(manifest)
    write_json(manifest_path, manifest)
    return V7EvaluationArtifacts(
        output_directory=output,
        manifest_path=manifest_path,
        gate_path=paths["gate_decision.json"],
        targets_path=paths["targets.parquet"],
        metrics_path=paths["metrics.json"],
    )


def run_v7_evaluation_from_inputs(
    inputs: V7EvaluationInputs,
    output_directory: Path,
    *,
    scenario_runner: Callable[..., tuple[
        pd.DataFrame,
        pd.DataFrame,
        dict[str, V7ScenarioResult],
    ]] = run_v7_scenarios,
    gate_evaluator: Callable[..., V7GateDecision] = evaluate_v7_gates,
) -> V7EvaluationArtifacts:
    """Stroit targets, auditit volume, zapuskaet 12 scenario i pishet result."""
    output = _bounded_path(inputs.project_root, output_directory, "Evaluation output")
    verify_v7_evaluation_code_identity(
        inputs.project_root,
        inputs.input_seals.get("evaluation_implementation"),
    )
    targets = build_v7_evaluation_targets(
        inputs.panel,
        inputs.active_map,
        inputs.training.predictions,
    )
    market = build_exact_v7_execution_market(
        inputs.contract_observations,
        inputs.spec_proxy,
        inputs.execution_overlay,
    )
    audit_v7_target_execution_timing(
        targets,
        inputs.training.predictions,
        inputs.execution_overlay,
    )
    pre_pnl = audit_v7_pre_pnl_participation_coverage(
        targets,
        inputs.exact_entry_volume,
    )
    if not pre_pnl.complete:
        raise V7ParticipationCoverageError(pre_pnl)
    scenario_metrics, fold_metrics, results = scenario_runner(
        market,
        targets,
        score_start=V7_SCORE_START,
        score_end=V7_SCORE_END,
        candidate_id=V7_EVALUATION_CANDIDATE_ID,
        initial_cash=V7_INITIAL_CASH,
        expected_assets=V7_ASSETS,
    )
    metric_scenarios = set(scenario_metrics["scenario_id"].astype(str))
    if set(results) != metric_scenarios or len(results) != 12:
        raise ValueError("Scenario result keys ne sovpadayut s fixed 12 metrics")
    realized = audit_v7_realized_entry_participation(
        results,
        inputs.exact_entry_volume,
    )
    fixed_gate = gate_evaluator(
        scenario_metrics,
        fold_metrics,
        candidate_id=V7_EVALUATION_CANDIDATE_ID,
    )
    gate = _evaluation_gate_payload(fixed_gate, pre_pnl, realized)
    return _persist_evaluation_artifacts(
        inputs,
        output,
        targets,
        pre_pnl,
        scenario_metrics,
        fold_metrics,
        results,
        realized,
        gate,
    )


def run_v7_evaluation(
    project_root: Path,
    assembly_manifest_path: Path,
    expected_assembly_manifest_sha256: str,
    training_summary_path: Path,
    expected_training_summary_sha256: str,
    predictions_path: Path,
    expected_predictions_sha256: str,
    output_directory: Path,
    *,
    v7_config_path: Path = V7_CONFIG_PATH,
    expected_v7_config_sha256: str = DEFAULT_V7_CONFIG_SHA256,
    v6_protocol_path: Path = Path("configs/futures_v6_experiment.yaml"),
    expected_v6_protocol_sha256: str = FUTURES_V6_PROTOCOL_SHA256,
) -> V7EvaluationArtifacts:
    """Proveryaet authoritative inputs i vypolnyaet local/server evaluation."""
    inputs = load_verified_v7_evaluation_inputs(
        project_root,
        assembly_manifest_path,
        expected_assembly_manifest_sha256,
        training_summary_path,
        expected_training_summary_sha256,
        predictions_path,
        expected_predictions_sha256,
        v7_config_path=v7_config_path,
        expected_v7_config_sha256=expected_v7_config_sha256,
        v6_protocol_path=v6_protocol_path,
        expected_v6_protocol_sha256=expected_v6_protocol_sha256,
    )
    return run_v7_evaluation_from_inputs(inputs, output_directory)


def build_argument_parser() -> argparse.ArgumentParser:
    """Stroit local/server CLI s obyazatel'nymi external byte-seals."""
    parser = argparse.ArgumentParser(
        description="Evaluate sealed futures-v7 OOS predictions without 2026 access.",
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--assembly-manifest", type=Path, required=True)
    parser.add_argument("--assembly-manifest-sha256", required=True)
    parser.add_argument("--training-summary", type=Path, required=True)
    parser.add_argument("--training-summary-sha256", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--predictions-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--v7-config",
        type=Path,
        default=V7_CONFIG_PATH,
    )
    parser.add_argument(
        "--v7-config-sha256",
        default=DEFAULT_V7_CONFIG_SHA256,
    )
    parser.add_argument(
        "--v6-protocol",
        type=Path,
        default=Path("configs/futures_v6_experiment.yaml"),
    )
    parser.add_argument(
        "--v6-protocol-sha256",
        default=FUTURES_V6_PROTOCOL_SHA256,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Vypolnyaet CLI i pechataet tol'ko final artifact paths."""
    arguments = build_argument_parser().parse_args(argv)
    artifacts = run_v7_evaluation(
        arguments.project_root,
        arguments.assembly_manifest,
        arguments.assembly_manifest_sha256,
        arguments.training_summary,
        arguments.training_summary_sha256,
        arguments.predictions,
        arguments.predictions_sha256,
        arguments.output,
        v7_config_path=arguments.v7_config,
        expected_v7_config_sha256=arguments.v7_config_sha256,
        v6_protocol_path=arguments.v6_protocol,
        expected_v6_protocol_sha256=arguments.v6_protocol_sha256,
    )
    print(
        json.dumps(
            {
                "output_directory": str(artifacts.output_directory),
                "manifest": str(artifacts.manifest_path),
                "gate": str(artifacts.gate_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "V7_EVALUATION_ARTIFACT_NAMES",
    "V7_EVALUATION_CANDIDATE_ID",
    "V7_EVALUATION_CODE_RELATIVE_PATHS",
    "V7_EVALUATION_FORMAT",
    "V7_INITIAL_CASH",
    "V7_MAXIMUM_ENTRY_PARTICIPATION",
    "V7ParticipationCoverageAudit",
    "V7ParticipationCoverageError",
    "V7EvaluationArtifacts",
    "V7EvaluationInputs",
    "V7RealizedParticipationAudit",
    "V7TargetFreeOOSCalendar",
    "VerifiedV7TrainingOutputs",
    "audit_v7_prediction_active_key_identity",
    "audit_v7_pre_pnl_participation_coverage",
    "audit_v7_realized_entry_participation",
    "audit_v7_target_execution_timing",
    "build_argument_parser",
    "build_authoritative_unpriced_nontradable_evidence",
    "build_exact_v7_execution_market",
    "build_v7_evaluation_code_identity",
    "build_v7_evaluation_targets",
    "load_verified_v7_evaluation_inputs",
    "load_v7_target_free_oos_calendar",
    "main",
    "run_v7_evaluation",
    "run_v7_evaluation_from_inputs",
    "verify_v7_training_outputs",
    "verify_v7_evaluation_code_identity",
]


if __name__ == "__main__":
    raise SystemExit(main())
