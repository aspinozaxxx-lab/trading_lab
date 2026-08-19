"""Strogii byte-seal i semantic contract dlya futures-v6 experimenta."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_lab.io_utils import TEXT_ENCODING

FUTURES_V6_PROTOCOL_FILENAME = (  # Kanonicheskoe imya zapechatannogo YAML.
    "futures_v6_experiment.yaml"
)
FUTURES_V6_PROTOCOL_SHA256 = (  # SHA-256 final'nogo YAML s BOM do development PnL.
    "73bc4cba13c65530ae446b0174f14987d0f55d74fdc45e10a8f93b6c6bdcdee9"
)
BASE_V5_PROTOCOL_SHA256 = (  # Neizmenyaemyi byte-seal bazovogo v5 protocola.
    "d73d17ffd9caeac46cbd3a353526c178df792070a4ea17744ab32abdfc32da38"
)
INFORMATION_CHANNELS_SHA256 = (  # Byte-seal opisaniya vneshnih kanalov.
    "1d38314608832f8680a0b6b483b67464c0e5beac2226f76f5d5943b986d37493"
)
HEX_SYMBOLS = frozenset("0123456789abcdef")  # Dopustimyi alfavit SHA-256.


class StrictV6Model(BaseModel):
    """Zapreshchaet lishnie polya i mutaciyu razdelov protocola."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactFileRecord(StrictV6Model):
    """Fiksiruet identifikator, project-relative path, hash i razmer faila."""

    id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)


class ArtifactRecord(ExactFileRecord):
    """Dobavlyaet neobyazatel'noe chislo strok dlya Parquet-artefakta."""

    rows: int | None = Field(default=None, ge=0)


class ProtocolPaths(StrictV6Model):
    """Fiksiruet koren proekta otnositel'no YAML i katalog rezultatov."""

    project_root: str = Field(min_length=1)
    runs: str = Field(min_length=1)


class SealedConfigs(StrictV6Model):
    """Hranit byte-seal bazovogo v5 i protocola information channels."""

    base_v5: ExactFileRecord
    information_channels: ExactFileRecord


class SourceStatuses(StrictV6Model):
    """Yavno otlichaet vklyuchennye, otklyuchennye i extractor-only istochniki."""

    moex: str = Field(min_length=1)
    cbr: str = Field(min_length=1)
    cftc: str = Field(min_length=1)
    gdelt: str = Field(min_length=1)
    filings: str = Field(min_length=1)
    qwen: str = Field(min_length=1)


class MoEParameters(StrictV6Model):
    """Fiksiruet vse default-parametry causal mixture-of-experts."""

    trend_horizons: tuple[int, int, int]
    volatility_lookback: int = Field(ge=2)
    long_volatility_lookback: int = Field(ge=2)
    breakout_lookback: int = Field(ge=2)
    participation_lookback: int = Field(ge=2)
    learning_rate: float = Field(gt=0)
    regime_shrinkage: float = Field(gt=0)
    exploration: float = Field(ge=0, lt=1)
    risk_threshold: float = Field(gt=0)
    crisis_threshold: float = Field(gt=0)


class MacroParameters(StrictV6Model):
    """Fiksiruet CBR overlay i confirmation bez OOS-podbora."""

    information_budget: float = Field(gt=0, lt=0.5)
    strong_event_threshold: float = Field(gt=0, le=1)
    conflict_gross_scale: float = Field(ge=0, le=1)
    confirmation_boost: float = Field(ge=1, le=1.5)
    cbr_scale_lookback: int = Field(ge=20)
    cbr_minimum_history: int = Field(ge=10)
    shock_clip: float = Field(gt=0)


class RouterParameters(StrictV6Model):
    """Fiksiruet exponential router i zavedomo spyashchie specialisty."""

    learning_rate: float = Field(gt=0)
    exploration: float = Field(ge=0, lt=1)
    maximum_gross: float = Field(gt=0, le=1)
    mandatory_specialists: list[str] = Field(min_length=2, max_length=2)
    sleeping_specialists: list[str] = Field(min_length=2, max_length=2)


class PortfolioParameters(StrictV6Model):
    """Fiksiruet causal risk-scaling, covariance i turnover sleeves."""

    ewma_volatility_span: int = Field(ge=2)
    covariance_sessions: int = Field(ge=2)
    annual_target_volatility: float = Field(gt=0, le=1)
    gross_cap: float = Field(gt=0, le=1)
    turnover_sleeves: int = Field(ge=1)
    trading_sessions_per_year: int = Field(ge=1)


class CausalModelParameters(StrictV6Model):
    """Obedinyaet fiksirovannye parametry vseh signal'nyh sloev."""

    moe: MoEParameters
    macro: MacroParameters
    router: RouterParameters
    portfolio: PortfolioParameters


class TimingProtocol(StrictV6Model):
    """Fiksiruet legacy RFUD close-to-open mapping i granicy ego primeneniya."""

    timezone: str = Field(min_length=1)
    decision_local_time: str = Field(min_length=1)
    execution_local_time: str = Field(min_length=1)
    execution_rule: str = Field(min_length=1)
    timing_regime: str = Field(min_length=1)
    development_end: date
    protected_holdout_start: date
    unified_session_start: date
    holdout_timing_protocol_required: str = Field(min_length=1)


class ExecutionProtocol(StrictV6Model):
    """Fiksiruet capital, contract sizing i polnyi nabor cost-stressov."""

    initial_capital_rub: float = Field(gt=0)
    integer_contracts: bool
    atomicity_scenarios: list[str] = Field(min_length=2, max_length=2)
    primary_atomicity: str = Field(min_length=1)
    stress_atomicity: str = Field(min_length=1)
    slippage_ticks: list[int] = Field(min_length=3, max_length=3)
    fee_multipliers: list[float] = Field(min_length=2, max_length=2)
    maximum_participation: float = Field(gt=0, le=1)
    initial_margin_buffer_multiplier: float = Field(gt=0)


class ValidationFold(StrictV6Model):
    """Zadaet expanding train i odin kalendarnyi OOS god."""

    name: str = Field(min_length=1)
    train_start: date
    train_end: date
    score_start: date
    score_end: date


class ValidationProtocol(StrictV6Model):
    """Fiksiruet odin nepreryvnyi ledger i pyat' godovyh fold."""

    scheme: str = Field(min_length=1)
    continuous_ledger_start: date
    continuous_ledger_end: date
    positions_reset_between_folds: bool
    purge_sessions: int = Field(ge=0)
    folds: list[ValidationFold] = Field(min_length=5, max_length=5)


class SelectionProtocol(StrictV6Model):
    """Fiksiruet edinstvennyi selection-scenario i deterministichnye tie rules."""

    scenario: str = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    tie_breakers: list[str] = Field(min_length=2, max_length=2)
    selected_before_holdout_access: bool
    all_candidates_same_scenarios: bool


class GateProtocol(StrictV6Model):
    """Fiksiruet pre-holdout porogi i polnotu ispolneniya."""

    primary_scenario: str = Field(min_length=1)
    double_cost_scenario: str = Field(min_length=1)
    minimum_positive_folds: int = Field(ge=1)
    minimum_worst_fold_net_cagr: float
    minimum_aggregate_net_cagr: float
    minimum_aggregate_net_sharpe: float
    maximum_aggregate_drawdown: float = Field(gt=0, lt=1)
    minimum_double_cost_net_cagr: float
    execution_complete_required: bool
    maximum_critical_execution_events: int = Field(ge=0)
    maximum_unresolved_halt_events: int = Field(ge=0)
    all_candidate_scenarios_reported: bool


class StretchProtocol(StrictV6Model):
    """Pomeshchaet 50 procentov godovyh tolko v report, ne v objective."""

    minimum_net_cagr: float = Field(gt=0)
    role: str = Field(min_length=1)
    used_for_selection: bool
    used_for_holdout_access: bool
    guarantee: bool


class HoldoutProtocol(StrictV6Model):
    """Blokiruet H1-2026 i trebuet otdel'nyi exact-10m ETS protocol."""

    start: date
    end: date
    status: str = Field(min_length=1)
    evaluation_budget: int = Field(ge=1)
    network_download_allowed: bool
    local_read_allowed: bool
    unlock_condition: str = Field(min_length=1)
    required_timing_protocol: str = Field(min_length=1)
    legacy_daily_mapping_allowed: bool


class FuturesV6Protocol(StrictV6Model):
    """Predstavlyaet polnyi futures-v6 contract i otklonyaet semantic drift."""

    protocol_name: str = Field(min_length=1)
    protocol_version: int = Field(ge=1)
    research_status: str = Field(min_length=1)
    paths: ProtocolPaths
    sealed_configs: SealedConfigs
    artifacts: list[ArtifactRecord] = Field(min_length=10, max_length=10)
    code_files: list[ExactFileRecord] = Field(min_length=15, max_length=15)
    sources: SourceStatuses
    candidates: list[str] = Field(min_length=4, max_length=4)
    models: CausalModelParameters
    timing: TimingProtocol
    execution: ExecutionProtocol
    validation: ValidationProtocol
    selection: SelectionProtocol
    gates: GateProtocol
    stretch: StretchProtocol
    holdout: HoldoutProtocol

    @model_validator(mode="after")
    def reject_semantic_drift(self) -> FuturesV6Protocol:
        """Sravnivaet static semantiku i exact record identities s etalonom."""
        actual = _semantic_projection(self)
        drift = _first_semantic_drift(actual, EXPECTED_FUTURES_V6_SEMANTICS)
        if drift is not None:
            raise ValueError(f"Semantic drift futures-v6: {drift}")
        return self

    def artifact(self, record_id: str) -> ArtifactRecord:
        """Vozvrashchaet artefakt po zapechatannomu stabil'nomu identifikatoru."""
        matches = [record for record in self.artifacts if record.id == record_id]
        if len(matches) != 1:
            raise KeyError(f"Ne naiden edinstvennyi futures-v6 artifact: {record_id}")
        return matches[0]

    def code_file(self, record_id: str) -> ExactFileRecord:
        """Vozvrashchaet code-file po zapechatannomu identifikatoru."""
        matches = [record for record in self.code_files if record.id == record_id]
        if len(matches) != 1:
            raise KeyError(f"Ne naiden edinstvennyi futures-v6 code-file: {record_id}")
        return matches[0]


EXPECTED_ARTIFACT_IDENTITIES = [  # Exact poryadok i puti development-artefaktov.
    {
        "id": "panel",
        "path": "data/processed/futures_v5/development_panel_2018_2025.parquet",
        "rows_required": True,
    },
    {
        "id": "active_map",
        "path": (
            "data/processed/futures_v5/"
            "development_panel_2018_2025_active_contract_map.parquet"
        ),
        "rows_required": True,
    },
    {
        "id": "contract_observations",
        "path": (
            "data/processed/futures_v5/"
            "development_panel_2018_2025_contract_observations.parquet"
        ),
        "rows_required": True,
    },
    {
        "id": "panel_audit",
        "path": "data/processed/futures_v5/development_panel_2018_2025_audit.json",
        "rows_required": False,
    },
    {
        "id": "spec_proxy",
        "path": (
            "data/processed/futures_v5_specs_v1/"
            "spec_proxy_2018-01-01_2025-12-31_87372f337a75eeb4/spec_proxy.parquet"
        ),
        "rows_required": True,
    },
    {
        "id": "spec_manifest",
        "path": (
            "data/processed/futures_v5_specs_v1/"
            "spec_proxy_2018-01-01_2025-12-31_87372f337a75eeb4/manifest.json"
        ),
        "rows_required": False,
    },
    {
        "id": "cbr_data",
        "path": "data/processed/info_radar/cbr-dev-2018-2025-v1/cbr_daily.parquet",
        "rows_required": True,
    },
    {
        "id": "cbr_manifest",
        "path": "data/processed/info_radar/cbr-dev-2018-2025-v1/manifest.json",
        "rows_required": False,
    },
    {
        "id": "cftc_data",
        "path": (
            "data/processed/info_radar/cftc-dev-2018-2025-v1/"
            "processed/cftc_positions.parquet"
        ),
        "rows_required": True,
    },
    {
        "id": "cftc_manifest",
        "path": "data/processed/info_radar/cftc-dev-2018-2025-v1/manifest.json",
        "rows_required": False,
    },
]
EXPECTED_CODE_IDENTITIES = [  # Exact evaluator dependency surface bez circular seal.
    {"id": "panel_engine", "path": "src/market_lab/futures/panel.py"},
    {"id": "roll_engine", "path": "src/market_lab/futures/roll.py"},
    {"id": "moe_model", "path": "src/market_lab/futures/moe.py"},
    {"id": "cbr_adapter", "path": "src/market_lab/futures/info_radar.py"},
    {
        "id": "macro_fusion",
        "path": "src/market_lab/futures/information_fusion.py",
    },
    {"id": "cftc_adapter", "path": "src/market_lab/futures/cftc_radar.py"},
    {
        "id": "specialist_router",
        "path": "src/market_lab/futures/specialist_router.py",
    },
    {
        "id": "portfolio_construction",
        "path": "src/market_lab/futures/portfolio_construction.py",
    },
    {
        "id": "execution_dataset",
        "path": "src/market_lab/futures/execution_dataset.py",
    },
    {
        "id": "portfolio_ledger",
        "path": "src/market_lab/futures/portfolio_ledger.py",
    },
    {"id": "session_timing", "path": "src/market_lab/futures/session_timing.py"},
    {"id": "spec_proxy_code", "path": "src/market_lab/futures/spec_proxy.py"},
    {"id": "v6_evaluation", "path": "src/market_lab/futures/v6_evaluation.py"},
    {"id": "v6_candidates", "path": "src/market_lab/futures/v6_candidates.py"},
    {"id": "v6_experiment", "path": "src/market_lab/futures/v6_experiment.py"},
]
EXPECTED_FUTURES_V6_SEMANTICS = {  # Static contract; hashes dannyh zakrepleny YAML seal.
    "protocol_name": "futures-v6-information-specialist-continuous",
    "protocol_version": 6,
    "research_status": "development_only_holdout_untouched",
    "paths": {"project_root": "..", "runs": "runs"},
    "sealed_configs": {
        "base_v5": {
            "id": "base_v5_protocol",
            "path": "configs/futures_v5_protocol.yaml",
            "sha256": BASE_V5_PROTOCOL_SHA256,
            "bytes": 3644,
        },
        "information_channels": {
            "id": "information_channels_protocol",
            "path": "configs/futures_v6_information_channels.yaml",
            "sha256": INFORMATION_CHANNELS_SHA256,
            "bytes": 2907,
        },
    },
    "artifacts": EXPECTED_ARTIFACT_IDENTITIES,
    "code_files": EXPECTED_CODE_IDENTITIES,
    "sources": {
        "moex": "enabled",
        "cbr": "enabled",
        "cftc": "enabled",
        "gdelt": "disabled_429",
        "filings": "disabled_no_authorized_historical_pit",
        "qwen": "extractor_only",
    },
    "candidates": [
        "base_moe",
        "macro_overlay",
        "macro_confirmation",
        "specialist_router",
    ],
    "models": {
        "moe": {
            "trend_horizons": [5, 20, 60],
            "volatility_lookback": 20,
            "long_volatility_lookback": 60,
            "breakout_lookback": 20,
            "participation_lookback": 20,
            "learning_rate": 2.0,
            "regime_shrinkage": 24.0,
            "exploration": 0.04,
            "risk_threshold": 0.25,
            "crisis_threshold": 0.75,
        },
        "macro": {
            "information_budget": 0.35,
            "strong_event_threshold": 0.65,
            "conflict_gross_scale": 0.25,
            "confirmation_boost": 1.15,
            "cbr_scale_lookback": 60,
            "cbr_minimum_history": 20,
            "shock_clip": 3.0,
        },
        "router": {
            "learning_rate": 2.0,
            "exploration": 0.04,
            "maximum_gross": 1.0,
            "mandatory_specialists": ["base", "cbr_macro"],
            "sleeping_specialists": ["filings", "news"],
        },
        "portfolio": {
            "ewma_volatility_span": 20,
            "covariance_sessions": 60,
            "annual_target_volatility": 0.20,
            "gross_cap": 1.0,
            "turnover_sleeves": 5,
            "trading_sessions_per_year": 252,
        },
    },
    "timing": {
        "timezone": "Europe/Moscow",
        "decision_local_time": "18:50:00",
        "execution_local_time": "19:00:00",
        "execution_rule": "next_factual_trade_date_daily_open",
        "timing_regime": "legacy_evening_belongs_to_next_trade_date",
        "development_end": "2025-12-31",
        "protected_holdout_start": "2026-01-01",
        "unified_session_start": "2026-03-23",
        "holdout_timing_protocol_required": "exact_10m_ets_session_protocol",
    },
    "execution": {
        "initial_capital_rub": 1_000_000.0,
        "integer_contracts": True,
        "atomicity_scenarios": ["asset", "portfolio"],
        "primary_atomicity": "asset",
        "stress_atomicity": "portfolio",
        "slippage_ticks": [1, 2, 4],
        "fee_multipliers": [1.0, 2.0],
        "maximum_participation": 0.01,
        "initial_margin_buffer_multiplier": 2.0,
    },
    "validation": {
        "scheme": "continuous_deployment_expanding_calendar_years",
        "continuous_ledger_start": "2021-01-01",
        "continuous_ledger_end": "2025-12-31",
        "positions_reset_between_folds": False,
        "purge_sessions": 5,
        "folds": [
            {
                "name": f"outer_{year}",
                "train_start": "2018-01-01",
                "train_end": f"{year - 1}-12-31",
                "score_start": f"{year}-01-01",
                "score_end": f"{year}-12-31",
            }
            for year in range(2021, 2026)
        ],
    },
    "selection": {
        "scenario": "asset_s2_f2",
        "primary_metric": "median_outer_fold_net_sharpe",
        "tie_breakers": ["worst_outer_fold_net_cagr_desc", "candidate_id_asc"],
        "selected_before_holdout_access": True,
        "all_candidates_same_scenarios": True,
    },
    "gates": {
        "primary_scenario": "asset_s1_f1",
        "double_cost_scenario": "asset_s2_f2",
        "minimum_positive_folds": 4,
        "minimum_worst_fold_net_cagr": -0.10,
        "minimum_aggregate_net_cagr": 0.12,
        "minimum_aggregate_net_sharpe": 0.80,
        "maximum_aggregate_drawdown": 0.25,
        "minimum_double_cost_net_cagr": 0.00,
        "execution_complete_required": True,
        "maximum_critical_execution_events": 0,
        "maximum_unresolved_halt_events": 0,
        "all_candidate_scenarios_reported": True,
    },
    "stretch": {
        "minimum_net_cagr": 0.50,
        "role": "report_only",
        "used_for_selection": False,
        "used_for_holdout_access": False,
        "guarantee": False,
    },
    "holdout": {
        "start": "2026-01-01",
        "end": "2026-07-31",
        "status": "locked_untouched",
        "evaluation_budget": 1,
        "network_download_allowed": False,
        "local_read_allowed": False,
        "unlock_condition": "sealed_development_passes_all_pre_holdout_gates",
        "required_timing_protocol": "exact_10m_ets_session_protocol",
        "legacy_daily_mapping_allowed": False,
    },
}


def _semantic_projection(protocol: FuturesV6Protocol) -> dict[str, Any]:
    """Udalyaet factual hashes artefaktov/koda, ostavlyaya exact identity i staticu."""
    snapshot = protocol.model_dump(mode="json")
    snapshot["artifacts"] = [
        {
            "id": record.id,
            "path": record.path,
            "rows_required": record.rows is not None,
        }
        for record in protocol.artifacts
    ]
    snapshot["code_files"] = [
        {"id": record.id, "path": record.path} for record in protocol.code_files
    ]
    return snapshot


def _first_semantic_drift(actual: Any, expected: Any, path: str = "$") -> str | None:
    """Nahodit pervoe otlichie tipa, klucha, poryadka ili znacheniya."""
    if type(actual) is not type(expected):
        return f"{path}: type {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(expected, dict):
        if list(actual) != list(expected):
            return f"{path}: keys/order {list(actual)!r} != {list(expected)!r}"
        for key in expected:
            drift = _first_semantic_drift(actual[key], expected[key], f"{path}.{key}")
            if drift is not None:
                return drift
        return None
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} != {len(expected)}"
        for index, expected_item in enumerate(expected):
            drift = _first_semantic_drift(actual[index], expected_item, f"{path}[{index}]")
            if drift is not None:
                return drift
        return None
    if actual != expected:
        return f"{path}: {actual!r} != {expected!r}"
    return None


def byte_sha256(path: Path) -> str:
    """Vozvrashchaet SHA-256 tochnyh baitov faila, vklyuchaya vozmozhnyi BOM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_sha256(value: str, *, label: str) -> str:
    """Proveryaet 64-znachnyi lower-case hex bez neodnoznachnoi normalizacii."""
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(symbol not in HEX_SYMBOLS for symbol in normalized):
        raise ValueError(f"{label} dolzhen byt' 64-znachnym SHA-256 hex")
    return normalized


def verify_futures_v6_config_seal(
    path: Path,
    expected_sha256: str = FUTURES_V6_PROTOCOL_SHA256,
) -> str:
    """Fail-closed sravnivaet tochnye baity YAML s ozhidaemym seal."""
    if expected_sha256 == FUTURES_V6_PROTOCOL_SHA256 and expected_sha256.startswith(
        "PLACEHOLDER"
    ):
        raise RuntimeError("Futures-v6 protocol poka ne zapechatan: SHA-256 PLACEHOLDER")
    expected = _normalized_sha256(expected_sha256, label="Ozhidaemyi config SHA-256")
    actual = byte_sha256(path)
    if actual != expected:
        raise ValueError(
            "Futures-v6 config seal mismatch: "
            f"expected {expected}, actual {actual}"
        )
    return actual


def resolve_bounded_path(project_root: Path, configured_path: str | Path) -> Path:
    """Razreshaet tolko otnositel'nyi path, ostayushchiisya vnutri project root."""
    root = project_root.resolve()
    relative = Path(configured_path)
    if relative.is_absolute():
        raise ValueError(f"Absolute path zapreshchen v futures-v6: {configured_path}")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path vyhodit za project root: {configured_path}")
    return resolved


def resolve_protocol_root(config_path: Path, protocol: FuturesV6Protocol) -> Path:
    """Razreshaet sealed project root otnositel'no kataloga YAML."""
    config_directory = config_path.resolve().parent
    root = (config_directory / protocol.paths.project_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Futures-v6 project root ne naiden: {root}")
    return root


def resolve_protocol_runs(config_path: Path, protocol: FuturesV6Protocol) -> Path:
    """Vozvrashchaet bounded runs path bez ego sozdaniya ili zapisi."""
    root = resolve_protocol_root(config_path, protocol)
    return resolve_bounded_path(root, protocol.paths.runs)


def resolve_record_path(project_root: Path, record: ExactFileRecord) -> Path:
    """Razreshaet path odnoi sealed zapisi strogo vnutri project root."""
    return resolve_bounded_path(project_root, record.path)


def _all_records(protocol: FuturesV6Protocol) -> list[ExactFileRecord]:
    """Sobiraet configs, artifacts i code v edinom zapechatannom poryadke."""
    return [
        protocol.sealed_configs.base_v5,
        protocol.sealed_configs.information_channels,
        *protocol.artifacts,
        *protocol.code_files,
    ]


def _verify_exact_records(
    records: list[ExactFileRecord],
    project_root: Path,
) -> dict[str, Path]:
    """Proveryaet unique ID/path, tip faila, bytes i hash bez logical load."""
    resolved: dict[str, Path] = {}
    used_paths: set[Path] = set()
    for record in records:
        if record.id in resolved:
            raise ValueError(f"Povtornyi sealed record id: {record.id}")
        path = resolve_record_path(project_root, record)
        if path in used_paths:
            raise ValueError(f"Povtornyi sealed record path: {record.path}")
        if not path.is_file():
            raise FileNotFoundError(f"Sealed file ne naiden: {record.id} -> {path}")
        actual_bytes = path.stat().st_size
        if actual_bytes != record.bytes:
            raise ValueError(
                f"Byte-size mismatch dlya {record.id}: "
                f"expected {record.bytes}, actual {actual_bytes}"
            )
        actual_sha256 = byte_sha256(path)
        if actual_sha256 != record.sha256:
            raise ValueError(
                f"SHA-256 mismatch dlya {record.id}: "
                f"expected {record.sha256}, actual {actual_sha256}"
            )
        resolved[record.id] = path
        used_paths.add(path)
    return resolved


def verify_base_and_information_seals(
    protocol: FuturesV6Protocol,
    project_root: Path,
) -> dict[str, Path]:
    """Otdel'no proveryaet oba roditel'skih config-seal bez market I/O."""
    return _verify_exact_records(
        [
            protocol.sealed_configs.base_v5,
            protocol.sealed_configs.information_channels,
        ],
        project_root,
    )


def verify_futures_v6_references(
    protocol: FuturesV6Protocol,
    project_root: Path,
) -> dict[str, Path]:
    """Proveryaet vse baity, zatem Parquet metadata rows do zagruzki dannyh."""
    resolved = _verify_exact_records(_all_records(protocol), project_root)
    for record in protocol.artifacts:
        if record.rows is None:
            continue
        path = resolved[record.id]
        if path.suffix.lower() != ".parquet":
            raise ValueError(f"Rows razresheny tolko dlya Parquet: {record.id}")
        actual_rows = pq.ParquetFile(path).metadata.num_rows
        if actual_rows != record.rows:
            raise ValueError(
                f"Parquet row mismatch dlya {record.id}: "
                f"expected {record.rows}, actual {actual_rows}"
            )
    return resolved


def validate_futures_v6_protocol(payload: Any) -> FuturesV6Protocol:
    """Validiruet payload bez chteniya config, koda ili rynochnyh dannyh."""
    return FuturesV6Protocol.model_validate(payload)


def load_futures_v6_protocol(
    path: Path,
    *,
    expected_sha256: str = FUTURES_V6_PROTOCOL_SHA256,
    verify_references: bool = True,
    project_root: Path | None = None,
) -> FuturesV6Protocol:
    """Chitaet sealed YAML i do vozvrata proveryaet vse ssylki fail-closed."""
    config_path = path.resolve()
    verify_futures_v6_config_seal(config_path, expected_sha256)
    with config_path.open("r", encoding=TEXT_ENCODING) as stream:
        payload = yaml.safe_load(stream)
    protocol = validate_futures_v6_protocol(payload)
    sealed_root = resolve_protocol_root(config_path, protocol)
    if project_root is not None and project_root.resolve() != sealed_root:
        raise ValueError(
            "Peredannyi project_root ne sovpadaet s sealed root: "
            f"{project_root.resolve()} != {sealed_root}"
        )
    if verify_references:
        verify_futures_v6_references(protocol, sealed_root)
    return protocol


__all__ = [
    "ArtifactRecord",
    "BASE_V5_PROTOCOL_SHA256",
    "EXPECTED_ARTIFACT_IDENTITIES",
    "EXPECTED_CODE_IDENTITIES",
    "EXPECTED_FUTURES_V6_SEMANTICS",
    "ExactFileRecord",
    "FUTURES_V6_PROTOCOL_FILENAME",
    "FUTURES_V6_PROTOCOL_SHA256",
    "FuturesV6Protocol",
    "INFORMATION_CHANNELS_SHA256",
    "byte_sha256",
    "load_futures_v6_protocol",
    "resolve_bounded_path",
    "resolve_protocol_root",
    "resolve_protocol_runs",
    "resolve_record_path",
    "validate_futures_v6_protocol",
    "verify_base_and_information_seals",
    "verify_futures_v6_config_seal",
    "verify_futures_v6_references",
]
