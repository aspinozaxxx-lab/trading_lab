"""End-to-end development-only futures-v6 eksperiment bez dostupa k holdout."""

from __future__ import annotations

import hashlib
import io
import tempfile
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import matplotlib
import pandas as pd

from market_lab.futures.cftc_radar import official_development_release_overrides
from market_lab.futures.execution_dataset import (
    audit_active_execution_coverage,
    build_portfolio_market,
    map_decision_weights_to_next_open,
)
from market_lab.futures.session_timing import legacy_forts_decision_calendar
from market_lab.futures.v6_candidates import (
    V6_CANDIDATE_IDS,
    build_causal_v6_candidates,
    build_v6_candidate_portfolio_targets,
)
from market_lab.futures.v6_evaluation import (
    V6_CANDIDATES,
    V6_PRIMARY_SCENARIO,
    V6_SELECTION_SCENARIO,
    evaluate_v6_gates,
    run_v6_scenarios,
    select_v6_candidate,
)
from market_lab.futures.v6_protocol import (
    load_futures_v6_protocol,
    resolve_protocol_root,
    resolve_protocol_runs,
    verify_futures_v6_references,
)
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

V6_DEVELOPMENT_SCORE_START: Final[date] = date(2021, 1, 1)  # Pervyi outer OOS god.
V6_DEVELOPMENT_SCORE_END: Final[date] = date(2025, 12, 31)  # Poslednii razreshennyi god.
V6_INITIAL_CASH: Final[float] = 1_000_000.0  # Obshchii RUB cash pool.
V6_RUN_PREFIX: Final[str] = "futures-v6-development"  # Stabil'nyi prefiks run_id.
V6_EXPERIMENT_VERSION: Final[str] = "futures-v6-development-v1"  # Audit-versiya.
V6_ARTIFACT_IDS: Final[tuple[str, ...]] = (  # Obyazatel'nye input references.
    "panel",
    "active_map",
    "contract_observations",
    "panel_audit",
    "spec_proxy",
    "spec_manifest",
    "cbr_data",
    "cbr_manifest",
    "cftc_data",
    "cftc_manifest",
)


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 artefakta potokovo bez ego interpretacii."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet Parquet Zstandard vnutri run-kataloga."""
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    atomic_write_bytes(path, buffer.getvalue())


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno zapisivaet CSV kak UTF-8 s BOM i stabil'nym newline."""
    atomic_write_text(path, frame.to_csv(index=False, lineterminator="\n"))


def _json_safe(value: Any) -> Any:
    """Prevrashchaet pandas/numpy znacheniya v determinirovannyi JSON payload."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _load_inputs(references: dict[str, Path]) -> dict[str, pd.DataFrame]:
    """Chitaet tolko uzhe proverennye development Parquet posle protocol seal."""
    missing = set(V6_ARTIFACT_IDS) - set(references)
    if missing:
        raise ValueError(f"Protocol references ne soderzhat: {sorted(missing)}")
    return {
        "panel": pd.read_parquet(references["panel"]),
        "active_map": pd.read_parquet(references["active_map"]),
        "contract_observations": pd.read_parquet(references["contract_observations"]),
        "spec_proxy": pd.read_parquet(references["spec_proxy"]),
        "cbr_data": pd.read_parquet(references["cbr_data"]),
        "cftc_data": pd.read_parquet(references["cftc_data"]),
    }


def _portfolio_market_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Pereimenuet causal forward close dlya edinogo risk-constructor API."""
    required = {"trade_date", "asset_code", "close"}
    if missing := required - set(panel.columns):
        raise ValueError(f"Panel ne soderzhit portfolio market kolonok: {sorted(missing)}")
    return panel.loc[:, ["trade_date", "asset_code", "close"]].rename(
        columns={
            "trade_date": "session_date",
            "asset_code": "asset",
            "close": "adjusted_close",
        }
    )


def _active_rows_for_weights(active_map: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Ostavlyaet exact decision keys kandidata i isklyuchaet initial NaT row."""
    if "decision_date" not in active_map:
        raise ValueError("Active map ne soderzhit decision_date")
    decisions = pd.DatetimeIndex(pd.to_datetime(weights["decision_date"], errors="raise"))
    active_dates = pd.to_datetime(active_map["decision_date"], errors="coerce")
    selected = active_map.loc[active_dates.isin(decisions)].copy()
    expected_rows = len(decisions.unique()) * 4
    if len(selected) != expected_rows:
        raise ValueError("Active map ne pokryvaet vse candidate decision snapshots")
    return selected


def _map_all_candidate_targets(
    portfolio_targets: pd.DataFrame,
    decision_calendar: pd.DataFrame,
    active_map: pd.DataFrame,
    portfolio_market: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Mapit vse candidate weights na next-open contract i auditit spec coverage."""
    mapped: dict[str, pd.DataFrame] = {}
    audit_rows: list[dict[str, object]] = []
    for candidate in V6_CANDIDATES:
        weights = portfolio_targets.loc[
            portfolio_targets["candidate_id"].eq(candidate)
        ].drop(columns="candidate_id")
        active = _active_rows_for_weights(active_map, weights)
        targets = map_decision_weights_to_next_open(
            weights,
            decision_calendar,
            active,
        )
        score_mask = targets["effective_date"].dt.date >= V6_DEVELOPMENT_SCORE_START
        targets = targets.loc[score_mask].reset_index(drop=True)
        coverage = audit_active_execution_coverage(portfolio_market, targets)
        audit_rows.append(
            {
                "candidate_id": candidate,
                "active_rows": coverage.active_rows,
                "covered_rows": coverage.covered_rows,
                "exact_join": coverage.exact_join,
                "sizing_available_rows": coverage.sizing_available_rows,
                "accounting_available_rows": coverage.accounting_available_rows,
                "tick_available_rows": coverage.tick_available_rows,
                "fee_available_rows": coverage.fee_available_rows,
                "initial_margin_available_rows": coverage.initial_margin_available_rows,
            }
        )
        mapped[candidate] = targets
    if tuple(mapped) != V6_CANDIDATES:
        raise AssertionError("Mapped target order otlichaetsya ot sealed candidates")
    return mapped, pd.DataFrame(audit_rows)


def _evaluation_market(portfolio_market: pd.DataFrame) -> pd.DataFrame:
    """Fizicheski ogranichivaet ledger tolko outer OOS 2021-2025."""
    dates = pd.to_datetime(portfolio_market["session_date"], errors="raise").dt.date
    mask = dates.ge(V6_DEVELOPMENT_SCORE_START) & dates.le(V6_DEVELOPMENT_SCORE_END)
    selected = portfolio_market.loc[mask].copy()
    if selected.empty or dates.loc[mask].min() < V6_DEVELOPMENT_SCORE_START:
        raise ValueError("Pustoi ili nekorrektnyi evaluation market")
    return selected.reset_index(drop=True)


def _scenario_row(
    scenario_metrics: pd.DataFrame,
    candidate: str,
    scenario_id: str,
) -> dict[str, Any]:
    """Izvlekaet edinstvennyi aggregate result dlya JSON/reporta."""
    rows = scenario_metrics.loc[
        scenario_metrics["candidate_id"].eq(candidate)
        & scenario_metrics["scenario_id"].eq(scenario_id)
    ]
    if len(rows) != 1:
        raise ValueError("Aggregate scenario row dolzhen byt' edinstvennym")
    return _json_safe(rows.iloc[0].to_dict())


def _plot_equity(path: Path, ledger: pd.DataFrame, selected_candidate: str) -> None:
    """Sohranyaet selected primary cash i adverse equity bez interaktivnogo backend."""
    figure, axis = plt.subplots(figsize=(10, 5))
    axis.plot(ledger["session_date"], ledger["ending_cash"], label="ending cash")
    axis.plot(
        ledger["session_date"],
        ledger["intraday_adverse_equity"],
        label="intraday adverse equity",
        alpha=0.55,
    )
    axis.set_title(f"Futures v6 development: {selected_candidate}")
    axis.set_xlabel("session")
    axis.set_ylabel("RUB")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150)
    plt.close(figure)
    atomic_write_bytes(path, buffer.getvalue())


def _report_text(
    run_id: str,
    selected_candidate: str,
    primary: dict[str, Any],
    stress: dict[str, Any],
    gate_payload: dict[str, Any],
) -> str:
    """Formiruet korotkii research-report bez garantiya ili broker-claim."""
    status = "GO_FOR_SEPARATE_HOLDOUT_PROTOCOL" if gate_payload["passed"] else "NO_GO"
    stretch = "yes" if gate_payload["stretch_50_reached"] else "no"
    return (
        "# Futures v6 development report\n\n"
        f"- Run: `{run_id}`\n"
        f"- Status: **{status}**\n"
        f"- Selected candidate: `{selected_candidate}`\n"
        f"- Primary net CAGR: {float(primary['cagr']):.2%}\n"
        f"- Primary Sharpe: {float(primary['sharpe']):.3f}\n"
        f"- Primary risk drawdown: {float(primary['risk_drawdown']):.2%}\n"
        f"- Double-cost CAGR: {float(stress['cagr']):.2%}\n"
        f"- 50% CAGR stretch reached: {stretch}\n\n"
        "This is a research-only approximate futures backtest. It is not a profit "
        "guarantee and is not broker-executable PnL. The 2026 holdout was not read; "
        "even a GO only permits creation of a separate exact-10m/ETS holdout protocol.\n"
    )


def _persist_run(
    temporary_run: Path,
    config_path: Path,
    references: dict[str, Path],
    bundle: Any,
    portfolio_targets: pd.DataFrame,
    mapped_targets: dict[str, pd.DataFrame],
    coverage: pd.DataFrame,
    scenario_metrics: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    ranking: pd.DataFrame,
    selected_candidate: str,
    gate_payload: dict[str, Any],
    results: dict[tuple[str, str], Any],
    run_id: str,
) -> None:
    """Atomarno sohranyaet polnyi development audit v staging run-katalog."""
    atomic_write_bytes(temporary_run / "resolved_config.yaml", config_path.read_bytes())
    reference_payload = {
        record_id: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for record_id, path in sorted(references.items())
    }
    write_json(temporary_run / "verified_references.json", reference_payload)
    _atomic_write_parquet(temporary_run / "candidate_scores.parquet", bundle.candidate_scores)
    _atomic_write_parquet(temporary_run / "cbr_features.parquet", bundle.cbr_features)
    _atomic_write_parquet(temporary_run / "cftc_asset_scores.parquet", bundle.cftc_asset_scores)
    _atomic_write_parquet(temporary_run / "router_targets.parquet", bundle.router_targets)
    _atomic_write_parquet(temporary_run / "portfolio_targets.parquet", portfolio_targets)
    _atomic_write_parquet(
        temporary_run / "mapped_execution_targets.parquet",
        pd.concat(
            [frame.assign(candidate_id=candidate) for candidate, frame in mapped_targets.items()],
            ignore_index=True,
        ),
    )
    _atomic_write_csv(temporary_run / "execution_coverage.csv", coverage)
    _atomic_write_csv(temporary_run / "scenario_metrics.csv", scenario_metrics)
    _atomic_write_csv(temporary_run / "fold_metrics.csv", fold_metrics)
    _atomic_write_csv(temporary_run / "selection_ranking.csv", ranking)
    primary = _scenario_row(
        scenario_metrics,
        selected_candidate,
        V6_PRIMARY_SCENARIO,
    )
    stress = _scenario_row(
        scenario_metrics,
        selected_candidate,
        V6_SELECTION_SCENARIO,
    )
    write_json(
        temporary_run / "selection.json",
        {
            "selected_candidate": selected_candidate,
            "selection_scenario": V6_SELECTION_SCENARIO,
            "selection_rule": (
                "highest_median_fold_sharpe_then_worst_fold_cagr_then_candidate_id"
            ),
        },
    )
    write_json(temporary_run / "gates.json", gate_payload)
    write_json(
        temporary_run / "metrics.json",
        {
            "selected_candidate": selected_candidate,
            "primary": primary,
            "double_cost": stress,
            "gates": gate_payload,
        },
    )
    for suffix, scenario_id in (
        ("primary", V6_PRIMARY_SCENARIO),
        ("double_cost", V6_SELECTION_SCENARIO),
    ):
        result = results[(selected_candidate, scenario_id)]
        _atomic_write_csv(temporary_run / f"selected_{suffix}_ledger.csv", result.ledger)
        _atomic_write_csv(temporary_run / f"selected_{suffix}_positions.csv", result.positions)
        _atomic_write_csv(temporary_run / f"selected_{suffix}_orders.csv", result.orders)
    _plot_equity(
        temporary_run / "equity_curve.png",
        results[(selected_candidate, V6_PRIMARY_SCENARIO)].ledger,
        selected_candidate,
    )
    atomic_write_text(
        temporary_run / "report.md",
        _report_text(run_id, selected_candidate, primary, stress, gate_payload),
    )
    atomic_write_text(
        temporary_run / "run.log",
        (
            f"version={V6_EXPERIMENT_VERSION}\n"
            f"run_id={run_id}\n"
            f"selected_candidate={selected_candidate}\n"
            f"development_gate_passed={gate_payload['passed']}\n"
            "holdout_read=false\n"
        ),
    )


def execute_futures_v6_development(config_path: Path) -> Path:
    """Proveryaet seal, schitaet development OOS i nikogda ne otkryvaet holdout."""
    if V6_CANDIDATE_IDS != V6_CANDIDATES:
        raise RuntimeError("Candidate assembly i evaluation imeyut raznyi seal")
    resolved_config = config_path.resolve()
    protocol = load_futures_v6_protocol(resolved_config, verify_references=False)
    project_root = resolve_protocol_root(resolved_config, protocol)
    runs_root = resolve_protocol_runs(resolved_config, protocol)
    references = verify_futures_v6_references(protocol, project_root)
    inputs = _load_inputs(references)
    dates = pd.DatetimeIndex(
        pd.to_datetime(inputs["panel"]["trade_date"], errors="raise")
        .drop_duplicates()
        .sort_values()
    )
    decision_calendar = legacy_forts_decision_calendar(dates)
    bundle = build_causal_v6_candidates(
        inputs["panel"],
        inputs["cbr_data"],
        decision_calendar,
        cftc_history=inputs["cftc_data"],
        cftc_release_overrides=official_development_release_overrides(),
    )
    portfolio_targets = build_v6_candidate_portfolio_targets(
        _portfolio_market_panel(inputs["panel"]),
        bundle,
    )
    portfolio_market = build_portfolio_market(
        inputs["contract_observations"],
        inputs["spec_proxy"],
    )
    mapped_targets, coverage = _map_all_candidate_targets(
        portfolio_targets,
        bundle.decision_calendar,
        inputs["active_map"],
        portfolio_market,
    )
    scenario_metrics, fold_metrics, results = run_v6_scenarios(
        _evaluation_market(portfolio_market),
        mapped_targets,
        initial_cash=V6_INITIAL_CASH,
    )
    selected_candidate, ranking = select_v6_candidate(fold_metrics)
    decision = evaluate_v6_gates(selected_candidate, scenario_metrics, fold_metrics)
    gate_payload = _json_safe(asdict(decision))
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{V6_RUN_PREFIX}-{timestamp}-{uuid.uuid4().hex[:8]}"
    runs_root.mkdir(parents=True, exist_ok=True)
    final_run = (runs_root / run_id).resolve()
    try:
        final_run.relative_to(runs_root.resolve())
    except ValueError as error:
        raise ValueError("Run path vyshel iz sealed runs root") from error
    if final_run.exists():
        raise FileExistsError(f"Run uzhe sushchestvuet: {final_run}")
    with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=runs_root) as temporary:
        temporary_run = Path(temporary)
        _persist_run(
            temporary_run,
            resolved_config,
            references,
            bundle,
            portfolio_targets,
            mapped_targets,
            coverage,
            scenario_metrics,
            fold_metrics,
            ranking,
            selected_candidate,
            gate_payload,
            results,
            run_id,
        )
        temporary_run.replace(final_run)
    return final_run


__all__ = ["execute_futures_v6_development"]
