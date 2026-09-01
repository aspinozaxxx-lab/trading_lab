"""Build a causal variable-availability panel from the sealed 2008-2011 source."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_pre2018_core4_derived as derived_base
from market_lab.futures import panel as panel_core
from market_lab.futures.roll import RollPlannerConfig
from market_lab.futures.spec_proxy import build_causal_spec_proxy
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2012_core_derived_v1.yaml"
PROTECTED_FROM: Final[date] = date(2012, 1, 1)
SOURCE_ID: Final[str] = (
    "official-moex-core3-plus-mix-daily-current-vintage-2008-2011-v2"
)
DERIVED_SOURCE_ID: Final[str] = (
    "moex-pre2012-core3-plus-late-mix-causal-derived-2008-2011-v1"
)
ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
CORE3: Final[tuple[str, ...]] = ("SI", "RI", "BR")
SOURCE_TO_LOGICAL: Final[dict[str, str]] = {
    "Si": "SI",
    "RTS": "RI",
    "BR": "BR",
    "MIX": "MIX",
}
CONTRACT_ROOTS: Final[dict[str, str]] = {
    "SI": "Si",
    "RI": "RI",
    "BR": "BR",
    "MIX": "MX",
}
ADMITTED_MONTH_CODES: Final[dict[str, tuple[str, ...]]] = {
    "SI": ("H", "M", "U", "Z"),
    "RI": ("H", "M", "U", "Z"),
    "BR": ("F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"),
    "MIX": ("H", "M", "U", "Z"),
}
EXPECTED_ADMITTED_CONTRACTS: Final[dict[str, int]] = {
    "SI": 16,
    "RI": 16,
    "BR": 38,
    "MIX": 1,
}
EXPECTED_ADMITTED_DAILY_ROWS: Final[dict[str, int]] = {
    "SI": 3_397,
    "RI": 2_390,
    "BR": 2_170,
    "MIX": 54,
}
EXPECTED_TOTAL_ADMITTED_DAILY_ROWS: Final[int] = 8_011
EXPECTED_EXCLUDED_SI_CONTRACTS: Final[int] = 10
EXPECTED_MASTER_SESSIONS: Final[int] = 781
EXPECTED_MASTER_START: Final[pd.Timestamp] = pd.Timestamp("2008-10-08")
EXPECTED_MASTER_END: Final[pd.Timestamp] = pd.Timestamp("2011-12-15")
EXPECTED_MIX_SESSIONS: Final[int] = 54
EXPECTED_MIX_START: Final[pd.Timestamp] = pd.Timestamp("2011-09-30")
EXPECTED_MIX_END: Final[pd.Timestamp] = pd.Timestamp("2011-12-15")
EXPECTED_MIX_UNAVAILABLE_SESSIONS: Final[int] = 727
EXPECTED_SOURCE_INERT_IDENTITIES: Final[tuple[tuple[str, str], ...]] = (
    ("RIM9_2009", "2008-09-12"),
    ("SiU9_2009", "2008-09-12"),
)
EMPTY_PARTICIPANT_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "asset_code",
    "is_physical",
    "open_position_long",
    "open_position_short",
)
MIX_PANEL_MARKET_COLUMNS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "front_settle",
    "next_settle",
    "roll_yield",
)
MIX_ACTIVE_MARKET_COLUMNS: Final[tuple[str, ...]] = (
    "execution_price",
    "exit_execution_price",
    "entry_execution_price",
    "overlap_old_price",
    "overlap_new_price",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "value",
    "num_trades",
    "open_interest",
)


@dataclass(frozen=True, slots=True)
class DerivedProtocol:
    """Byte-sealed parent source and outcome-free transformation contract."""

    config_path: Path
    config_sha256: str
    source_directory: Path
    source_manifest_sha256: str
    source_daily_sha256: str
    source_raw_sha256: str
    source_daily_rows: int
    source_contracts: int
    output_directory: Path
    roll_config: RollPlannerConfig
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class DerivedAudit:
    """Offline deterministic rebuild result for one immutable derived bundle."""

    checks: dict[str, bool]
    counts: dict[str, int]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"pre-2012 derived {label} must be a mapping")
    return value


def _expected_int_mapping(value: object, label: str) -> dict[str, int]:
    payload = _mapping(value, label)
    return {str(key): int(item) for key, item in payload.items()}


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> DerivedProtocol:
    """Verify config and every transformation dependency before source values load."""
    path = config_path.resolve()
    config_sha = derived_base.sha256_file(path)
    if derived_base._sidecar_sha(path) != config_sha:
        raise ValueError("pre-2012 derived protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("pre-2012 derived protocol must be a YAML object")
    source = _mapping(payload.get("source"), "source")
    admission = _mapping(payload.get("contract_admission"), "contract admission")
    calendar = _mapping(payload.get("variable_availability_calendar"), "calendar")
    roll = _mapping(payload.get("causal_roll"), "causal roll")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    configured_codes = {
        str(asset): tuple(str(code) for code in codes)
        for asset, codes in _mapping(
            admission.get("admitted_month_codes"), "month codes"
        ).items()
    }
    if (
        payload.get("protocol_id") != "moex_pre2012_core_derived_source_v1"
        or payload.get("scope") != "source_derived_no_strategy_no_outcomes"
        or payload.get("sealed_before_first_derived_price_build") is not True
        or payload.get("live_trading_allowed") is not False
        or source.get("source_id") != SOURCE_ID
        or source.get("minimum_price_date") != "2008-01-09"
        or source.get("maximum_price_date") != "2011-12-16"
        or source.get("protected_from") != "2012-01-01"
        or configured_codes != ADMITTED_MONTH_CODES
        or _expected_int_mapping(admission.get("expected_contracts"), "contracts")
        != EXPECTED_ADMITTED_CONTRACTS
        or _expected_int_mapping(admission.get("expected_daily_rows"), "daily rows")
        != EXPECTED_ADMITTED_DAILY_ROWS
        or int(admission.get("expected_total_daily_rows", -1))
        != EXPECTED_TOTAL_ADMITTED_DAILY_ROWS
        or int(admission.get("expected_excluded_SI_contracts", -1))
        != EXPECTED_EXCLUDED_SI_CONTRACTS
        or tuple(calendar.get("master_assets", ())) != CORE3
        or int(calendar.get("expected_master_sessions", -1))
        != EXPECTED_MASTER_SESSIONS
        or calendar.get("expected_master_start") != "2008-10-08"
        or calendar.get("expected_master_end") != "2011-12-15"
        or int(calendar.get("expected_MIX_sessions", -1)) != EXPECTED_MIX_SESSIONS
        or int(calendar.get("expected_MIX_unavailable_sessions", -1))
        != EXPECTED_MIX_UNAVAILABLE_SESSIONS
        or calendar.get("MIX_unavailable_policy")
        != "explicit_flat_mask_never_backfill"
        or calendar.get("missing_return_bridge_allowed") is not False
        or output.get("immutable_no_overwrite") is not True
        or output.get("outside_git_via_data_junction") is not True
    ):
        raise ValueError("pre-2012 derived protocol invariants drifted")
    settings = RollPlannerConfig(
        confirmation_days=int(roll["confirmation_days"]),
        hard_fallback_sessions=int(roll["hard_fallback_sessions"]),
        dominance_ratio=float(roll["dominance_ratio"]),
        overlap_price_column=str(roll["overlap_price_column"]),
        execution_price_column=str(roll["execution_price_column"]),
    )
    if settings != RollPlannerConfig():
        raise ValueError("pre-2012 roll settings differ from frozen defaults")
    expected_dependencies = {
        "src/market_lab/futures/moex_pre2012_core_derived_v1.py",
        "src/market_lab/futures/moex_pre2018_core4_derived.py",
        "src/market_lab/futures/panel.py",
        "src/market_lab/futures/roll.py",
        "src/market_lab/futures/spec_proxy.py",
        "src/market_lab/io_utils.py",
    }
    if set(map(str, dependencies)) != expected_dependencies:
        raise ValueError("pre-2012 derived dependency set drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = derived_base._project_path(str(relative))
        digest = str(expected).lower()
        if derived_base.sha256_file(dependency_path) != digest:
            raise ValueError(f"pre-2012 derived dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return DerivedProtocol(
        config_path=path,
        config_sha256=config_sha,
        source_directory=derived_base._project_path(str(source["directory"])),
        source_manifest_sha256=str(source["manifest_sha256"]).lower(),
        source_daily_sha256=str(source["daily_sha256"]).lower(),
        source_raw_sha256=str(source["raw_sha256"]).lower(),
        source_daily_rows=int(source["daily_rows"]),
        source_contracts=int(source["contracts"]),
        output_directory=derived_base._project_path(str(output["directory"])),
        roll_config=settings,
        dependency_hashes=dependency_hashes,
    )


def _verified_artifact(directory: Path, record: Mapping[str, Any]) -> Path:
    path = (directory / str(record["path"])).resolve()
    try:
        path.relative_to(directory.resolve())
    except ValueError as error:
        raise ValueError("pre-2012 source artifact escapes its bundle") from error
    if (
        not path.is_file()
        or path.stat().st_size != int(record["bytes"])
        or derived_base.sha256_file(path) != str(record["sha256"]).lower()
    ):
        raise ValueError(f"pre-2012 source artifact identity mismatch: {path.name}")
    return path


def verify_and_load_source(
    protocol: DerivedProtocol,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Verify every source byte before loading the two transformation inputs."""
    manifest_path = protocol.source_directory / "manifest.json"
    content = manifest_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != protocol.source_manifest_sha256:
        raise ValueError("pre-2012 source manifest SHA-256 mismatch")
    stated = (
        protocol.source_directory.joinpath("manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        .lower()
    )
    if stated != protocol.source_manifest_sha256:
        raise ValueError("pre-2012 source manifest sidecar mismatch")
    manifest = json.loads(content.decode("utf-8-sig"))
    core = dict(manifest)
    identity = str(core.pop("manifest_payload_sha256", ""))
    if hashlib.sha256(derived_base._canonical_json(core)).hexdigest() != identity:
        raise ValueError("pre-2012 source manifest payload identity mismatch")
    bounds = _mapping(manifest.get("request_bounds"), "source request bounds")
    counts = _mapping(manifest.get("counts"), "source counts")
    artifacts = _mapping(manifest.get("artifacts"), "source artifacts")
    if (
        manifest.get("source_id") != SOURCE_ID
        or bounds.get("from") != "2008-01-01"
        or bounds.get("till") != "2011-12-31"
        or bounds.get("protected_from") != "2012-01-01"
        or int(counts.get("contracts", -1)) != protocol.source_contracts
        or int(counts.get("daily_rows", -1)) != protocol.source_daily_rows
        or int(counts.get("inert_daily_rows", -1)) != 2
        or str(artifacts["daily"]["sha256"]).lower()
        != protocol.source_daily_sha256
        or str(artifacts["raw_archive"]["sha256"]).lower()
        != protocol.source_raw_sha256
    ):
        raise ValueError("pre-2012 source manifest contract drifted")
    verified = {
        name: _verified_artifact(protocol.source_directory, record)
        for name, record in artifacts.items()
    }
    daily = pd.read_parquet(verified["daily"])
    contracts = pd.read_parquet(verified["contracts"])
    if len(daily) != protocol.source_daily_rows or len(contracts) != protocol.source_contracts:
        raise ValueError("pre-2012 source loaded row count mismatch")
    if (
        daily["trade_date"].min() != pd.Timestamp("2008-01-09")
        or daily["trade_date"].max() != pd.Timestamp("2011-12-16")
        or daily["trade_date"].dt.date.ge(PROTECTED_FROM).any()
        or daily.duplicated(["trade_date", "canonical_contract_id", "board_id"]).any()
    ):
        raise ValueError("pre-2012 source temporal or identity gate failed")
    inert = daily.loc[
        ~daily["reported_trade_activity"]
        & ~daily["ohlc_complete"]
        & ~daily["has_settlement"]
    ]
    identities = tuple(
        sorted(
            (str(row.secid), row.trade_date.date().isoformat())
            for row in inert[["secid", "trade_date"]].itertuples(index=False)
        )
    )
    if identities != tuple(sorted(EXPECTED_SOURCE_INERT_IDENTITIES)):
        raise ValueError("pre-2012 source inert identities changed")
    return manifest, daily, contracts


def _contract_month_code(row: Mapping[str, Any]) -> str:
    logical = str(row["logical_symbol"])
    root = CONTRACT_ROOTS.get(logical)
    secid = str(row["secid"])
    if root is None or not secid.startswith(root):
        raise ValueError(f"pre-2012 contract root mismatch: {logical}/{secid}")
    suffix = secid[len(root) :].split("_", maxsplit=1)[0]
    if len(suffix) != 2 or not suffix[1].isdigit():
        raise ValueError(f"unexpected pre-2012 dated SECID: {secid}")
    return suffix[0]


def admit_structural_contract_cycles(
    daily: pd.DataFrame,
    contracts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Keep quarterly SI/RI/MIX and monthly BR before any derived price calculation."""
    selected = contracts.copy()
    selected["contract_month_code"] = [
        _contract_month_code(row) for row in selected.to_dict("records")
    ]
    selected["cycle_admitted"] = [
        month in ADMITTED_MONTH_CODES[str(asset)]
        for asset, month in selected[
            ["logical_symbol", "contract_month_code"]
        ].itertuples(index=False, name=None)
    ]
    admitted = selected.loc[selected["cycle_admitted"]].copy()
    excluded = selected.loc[~selected["cycle_admitted"]].copy()
    counts = admitted.groupby("logical_symbol").size().astype(int).to_dict()
    if counts != EXPECTED_ADMITTED_CONTRACTS:
        raise ValueError(f"pre-2012 admitted contract counts changed: {counts}")
    if (
        len(excluded) != EXPECTED_EXCLUDED_SI_CONTRACTS
        or not excluded["logical_symbol"].eq("SI").all()
    ):
        raise ValueError("pre-2012 admission may exclude only ten SI serial contracts")
    admitted_ids = set(admitted["canonical_contract_id"].astype(str))
    admitted_daily = daily.loc[
        daily["canonical_contract_id"].astype(str).isin(admitted_ids)
    ].copy()
    daily_counts = {
        logical: int(admitted_daily["asset_code"].astype(str).eq(source_code).sum())
        for source_code, logical in SOURCE_TO_LOGICAL.items()
    }
    if (
        daily_counts != EXPECTED_ADMITTED_DAILY_ROWS
        or len(admitted_daily) != EXPECTED_TOTAL_ADMITTED_DAILY_ROWS
    ):
        raise ValueError(f"pre-2012 admitted daily counts changed: {daily_counts}")
    return admitted_daily, admitted, {
        "rule": "official_cycle_before_any_derived_price_or_strategy_outcome",
        "admitted_month_codes": ADMITTED_MONTH_CODES,
        "admitted_contracts": counts,
        "admitted_daily_rows": daily_counts,
        "total_admitted_daily_rows": len(admitted_daily),
        "excluded_contracts": len(excluded),
        "excluded_contract_ids": sorted(excluded["canonical_contract_id"].astype(str)),
        "return_signal_equity_or_pnl_used": False,
    }


@contextmanager
def _panel_universe(assets: tuple[str, ...]) -> Iterator[None]:
    original = panel_core.REQUIRED_LOGICAL_ASSETS
    if original != ASSETS:
        raise RuntimeError("shared panel universe is already patched")
    panel_core.REQUIRED_LOGICAL_ASSETS = assets
    try:
        yield
    finally:
        panel_core.REQUIRED_LOGICAL_ASSETS = original


def _empty_participants(assets: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    return {
        asset: pd.DataFrame(columns=EMPTY_PARTICIPANT_COLUMNS) for asset in assets
    }


def _build_asset_group(
    observations: Mapping[str, pd.DataFrame],
    assets: tuple[str, ...],
    roll_config: RollPlannerConfig,
) -> panel_core.FuturesPanelBuildResult:
    with _panel_universe(assets):
        return panel_core.build_causal_development_panel(
            observations,
            _empty_participants(assets),
            roll_config=roll_config,
            protected_from=PROTECTED_FROM,
        )


def _expand_mix_panel(
    partial: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    observed_dates = pd.DatetimeIndex(partial["trade_date"])
    if (
        len(partial) != EXPECTED_MIX_SESSIONS
        or not observed_dates.isin(calendar).all()
        or observed_dates.min() != EXPECTED_MIX_START
        or observed_dates.max() != EXPECTED_MIX_END
    ):
        raise ValueError("pre-2012 MIX panel availability changed")
    frame = partial.set_index("trade_date").reindex(calendar)
    missing = ~frame.index.isin(observed_dates)
    if int(missing.sum()) != EXPECTED_MIX_UNAVAILABLE_SESSIONS:
        raise ValueError("pre-2012 MIX unavailable-session count changed")
    if not (frame.index[missing] < EXPECTED_MIX_START).all():
        raise ValueError("pre-2012 MIX has a missing session after its first observation")
    frame.index.name = "trade_date"
    frame["asset_code"] = "MIX"
    frame.loc[missing, "active_contract_action"] = "flat"
    frame.loc[missing, "active_contract_reason"] = "asset_not_yet_available"
    for column in (
        "active_contract_valid",
        "active_contract_carry_unfilled",
        "active_expiry_horizon_censored",
        "raw_ohlc_missing_with_activity",
        "raw_ohlc_complete",
        "curve_valid",
        "participant_snapshot_complete",
    ):
        frame.loc[missing, column] = False
    frame.loc[missing, "active_chain_id"] = 0
    result = frame.reset_index()[partial.columns]
    if not result.loc[missing, list(MIX_PANEL_MARKET_COLUMNS)].isna().all(axis=None):
        raise ValueError("pre-2012 MIX unavailable panel contains fabricated market values")
    return result


def _expand_mix_active(
    partial: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    observed_dates = pd.DatetimeIndex(partial["effective_date"])
    frame = partial.set_index("effective_date").reindex(calendar)
    missing = ~frame.index.isin(observed_dates)
    if int(missing.sum()) != EXPECTED_MIX_UNAVAILABLE_SESSIONS:
        raise ValueError("pre-2012 MIX active unavailable-session count changed")
    frame.index.name = "effective_date"
    frame["asset_code"] = "MIX"
    frame.loc[missing, "action"] = "flat"
    frame.loc[missing, "reason"] = "asset_not_yet_available"
    for column in (
        "roll",
        "plan_tradable",
        "expiry_horizon_censored",
        "carry_unfilled",
        "execution_open_available",
        "feature_input_valid",
        "reported_trade_activity",
        "ohlc_complete",
        "ohlc_missing_with_activity",
        "has_trade",
        "has_settlement",
    ):
        frame.loc[missing, column] = False
    frame.loc[missing, "chain_id"] = 0
    frame.loc[missing, "forward_additive_adjustment"] = 0.0
    result = frame.reset_index()[partial.columns]
    if not result.loc[missing, list(MIX_ACTIVE_MARKET_COLUMNS)].isna().all(axis=None):
        raise ValueError("pre-2012 MIX unavailable active rows contain market values")
    return result


def _action_counts(active: pd.DataFrame) -> dict[str, dict[str, int]]:
    return {
        asset: (
            active.loc[active["asset_code"].astype(str).eq(asset), "action"]
            .astype(str)
            .value_counts()
            .astype(int)
            .to_dict()
        )
        for asset in ASSETS
    }


def _maximum_true_streak(values: pd.Series) -> int:
    maximum = current = 0
    for value in values.fillna(False).astype(bool):
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def build_derived_tables(protocol: DerivedProtocol) -> derived_base.DerivedTables:
    """Build causal core-three history plus explicitly unavailable pre-listing MIX rows."""
    manifest, daily, contracts = verify_and_load_source(protocol)
    admitted_daily, admitted_contracts, admission_audit = (
        admit_structural_contract_cycles(daily, contracts)
    )
    observations = derived_base._observations_by_asset(
        admitted_daily,
        admitted_contracts,
    )
    core = _build_asset_group(
        {asset: observations[asset] for asset in CORE3},
        CORE3,
        protocol.roll_config,
    )
    mix = _build_asset_group(
        {"MIX": observations["MIX"]},
        ("MIX",),
        protocol.roll_config,
    )
    calendar = pd.DatetimeIndex(
        core.panel["trade_date"].drop_duplicates().sort_values(ignore_index=True)
    )
    if (
        len(calendar) != EXPECTED_MASTER_SESSIONS
        or calendar.min() != EXPECTED_MASTER_START
        or calendar.max() != EXPECTED_MASTER_END
    ):
        raise ValueError("pre-2012 core-three master calendar changed")
    mix_panel = _expand_mix_panel(mix.panel, calendar)
    mix_active = _expand_mix_active(mix.active_contract_map, calendar)
    panel = pd.concat([core.panel, mix_panel], ignore_index=True).sort_values(
        ["trade_date", "asset_code"], kind="mergesort", ignore_index=True
    )
    active = pd.concat([core.active_contract_map, mix_active], ignore_index=True).sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )
    expected_rows = EXPECTED_MASTER_SESSIONS * len(ASSETS)
    if (
        len(panel) != expected_rows
        or len(active) != expected_rows
        or panel.duplicated(["trade_date", "asset_code"]).any()
        or active.duplicated(["effective_date", "asset_code"]).any()
    ):
        raise ValueError("pre-2012 variable-availability panel is not rectangular")
    contract_observations = pd.concat(
        [core.contract_observations, mix.contract_observations],
        ignore_index=True,
    ).sort_values(
        ["trade_date", "asset_code", "expiration_date", "canonical_contract_id"],
        kind="mergesort",
        ignore_index=True,
    )
    spec_input = contract_observations.rename(
        columns={
            "trade_date": "session_date",
            "canonical_contract_id": "contract_id",
            "logical_asset": "asset_symbol",
        }
    )
    spec_proxy = build_causal_spec_proxy(spec_input, calendar)
    if spec_proxy["session_date"].dt.date.ge(PROTECTED_FROM).any():
        raise ValueError("pre-2012 derived spec proxy reaches protected boundary")
    actions = _action_counts(active)
    roll_counts = {
        asset: int(
            active.loc[
                active["asset_code"].astype(str).eq(asset) & active["roll"].fillna(False)
            ].shape[0]
        )
        for asset in ASSETS
    }
    unresolved_rolls = sum(
        counts.get("carry_unfilled_roll", 0) for counts in actions.values()
    )
    unresolved_exits = sum(
        counts.get("carry_unfilled_exit", 0) for counts in actions.values()
    )
    if unresolved_rolls or unresolved_exits:
        raise ValueError(
            "pre-2012 derived panel contains unresolved roll/exit: "
            f"rolls={unresolved_rolls}, exits={unresolved_exits}"
        )
    source_inert_dates = pd.DatetimeIndex(
        daily.loc[
            ~daily["reported_trade_activity"]
            & ~daily["ohlc_complete"]
            & ~daily["has_settlement"],
            "trade_date",
        ]
    )
    if source_inert_dates.isin(calendar).any():
        raise ValueError("pre-2012 inert source row unexpectedly entered master calendar")
    frames = {
        "panel": panel,
        "active_contract_map": active,
        "contract_observations": contract_observations,
        "spec_proxy": spec_proxy,
    }
    derived_base._assert_source_only_schema(frames)
    unavailable_mix = panel.loc[
        panel["asset_code"].astype(str).eq("MIX")
        & panel["active_contract_reason"].astype(str).eq("asset_not_yet_available")
    ]
    audit = {
        "schema_version": 1,
        "source_manifest_sha256": protocol.source_manifest_sha256,
        "source_daily_sha256": manifest["artifacts"]["daily"]["sha256"],
        "source_daily_rows": len(daily),
        "source_contracts": len(contracts),
        "contract_admission": admission_audit,
        "roll_config": asdict(protocol.roll_config),
        "calendar_source": "intersection_of_factual_SI_RI_BR_sessions",
        "calendar_start": calendar.min().date().isoformat(),
        "calendar_end": calendar.max().date().isoformat(),
        "master_session_count": len(calendar),
        "panel_rows": len(panel),
        "active_contract_rows": len(active),
        "contract_observation_rows": len(contract_observations),
        "spec_proxy_rows": len(spec_proxy),
        "MIX_source_session_count": len(mix.panel),
        "MIX_first_source_session": EXPECTED_MIX_START.date().isoformat(),
        "MIX_last_source_session": EXPECTED_MIX_END.date().isoformat(),
        "MIX_unavailable_session_count": len(unavailable_mix),
        "MIX_unavailable_policy": "explicit_flat_mask_never_backfill",
        "MIX_unavailable_market_values_present": False,
        "source_inert_identities": [
            {"secid": secid, "trade_date": trade_date}
            for secid, trade_date in EXPECTED_SOURCE_INERT_IDENTITIES
        ],
        "source_inert_rows_before_master_calendar": len(source_inert_dates),
        "source_inert_return_bridge_created": False,
        "successful_rolls": roll_counts,
        "action_counts": actions,
        "unresolved_roll_count": unresolved_rolls,
        "unresolved_exit_count": unresolved_exits,
        "maximum_consecutive_feature_invalid": {
            asset: _maximum_true_streak(
                ~active.loc[
                    active["asset_code"].astype(str).eq(asset), "feature_input_valid"
                ]
            )
            for asset in ASSETS
        },
        "spec_sizing_usable_rows": int(spec_proxy["sizing_usable"].sum()),
        "spec_sizing_unusable_rows": int((~spec_proxy["sizing_usable"]).sum()),
        "active_feature_valid_rows": int(active["feature_input_valid"].sum()),
        "active_feature_invalid_rows": int((~active["feature_input_valid"]).sum()),
        "participant_oi_available": False,
        "participant_oi_missing_preserved": True,
        "contains_prices": True,
        "contains_returns_targets_labels_signals_equity_or_pnl": False,
        "historical_exchange_exact": False,
        "broker_exact": False,
    }
    return derived_base.DerivedTables(
        panel=panel,
        active_contract_map=active,
        contract_observations=contract_observations,
        spec_proxy=spec_proxy,
        audit=audit,
    )


def persist_derived(protocol: DerivedProtocol, tables: derived_base.DerivedTables) -> Path:
    """Publish one immutable outcome-free derived bundle outside Git."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"pre-2012 derived output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        frames = {
            "panel": tables.panel,
            "active_contract_map": tables.active_contract_map,
            "contract_observations": tables.contract_observations,
            "spec_proxy": tables.spec_proxy,
        }
        derived_base._assert_source_only_schema(frames)
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            derived_base._atomic_parquet(path, frame)
            artifacts[name] = derived_base._artifact(path, len(frame))
            artifacts[name]["columns"] = frame.columns.tolist()
        audit_path = temporary / "audit.json"
        write_json(audit_path, tables.audit)
        artifacts["audit"] = derived_base._artifact(audit_path)
        manifest_core = {
            "schema_version": 1,
            "source_id": DERIVED_SOURCE_ID,
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "parent_source": {
                "directory": protocol.source_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.source_manifest_sha256,
                "daily_sha256": protocol.source_daily_sha256,
                "raw_sha256": protocol.source_raw_sha256,
            },
            "implementation_dependencies": protocol.dependency_hashes,
            "contract_admission": tables.audit["contract_admission"],
            "variable_availability": {
                "master_assets": list(CORE3),
                "MIX_first_source_session": tables.audit["MIX_first_source_session"],
                "MIX_unavailable_session_count": tables.audit[
                    "MIX_unavailable_session_count"
                ],
                "MIX_unavailable_policy": tables.audit["MIX_unavailable_policy"],
            },
            "temporal_semantics": {
                "minimum_session": tables.audit["calendar_start"],
                "maximum_session": tables.audit["calendar_end"],
                "protected_from": PROTECTED_FROM.isoformat(),
                "contains_prices": True,
                "contains_returns_targets_labels_signals_equity_or_pnl": False,
                "causal_forward_adjustment": True,
                "missing_values_preserved": True,
                "missing_or_listing_gap_return_bridge_created": False,
            },
            "quality_gates": {
                "successful_rolls": tables.audit["successful_rolls"],
                "action_counts": tables.audit["action_counts"],
                "unresolved_roll_count": tables.audit["unresolved_roll_count"],
                "unresolved_exit_count": tables.audit["unresolved_exit_count"],
                "panel_rows": tables.audit["panel_rows"],
                "active_contract_rows": tables.audit["active_contract_rows"],
            },
            "limitations": {
                "participant_oi_available": False,
                "historical_exchange_specs_exact": False,
                "historical_broker_fees_and_margin_exact": False,
                "MIX_available_only_late_2011": True,
                "live_admission_possible": False,
            },
            "artifacts": artifacts,
        }
        identity = hashlib.sha256(derived_base._canonical_json(manifest_core)).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": identity},
        )
        atomic_write_text(
            temporary / "manifest.sha256",
            f"{derived_base.sha256_file(manifest_path)}  manifest.json\n",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def _normalized(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_object_dtype(output[column].dtype) or isinstance(
            output[column].dtype,
            pd.StringDtype,
        ):
            output[column] = output[column].astype("string")
    return output.convert_dtypes()


def audit_bundle(protocol: DerivedProtocol) -> DerivedAudit:
    """Rebuild the derived tables and compare every persisted source-only artifact."""
    root = protocol.output_directory.resolve()
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    identity_payload = dict(manifest)
    identity = identity_payload.pop("manifest_payload_sha256", None)
    rebuilt = build_derived_tables(protocol)
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar_path.read_text(encoding="utf-8-sig").split()[0]
        == derived_base.sha256_file(manifest_path),
        "manifest_payload_sha_exact": hashlib.sha256(
            derived_base._canonical_json(identity_payload)
        ).hexdigest()
        == identity,
        "source_id_exact": manifest.get("source_id") == DERIVED_SOURCE_ID,
        "protocol_sha_exact": manifest.get("protocol", {}).get("sha256")
        == protocol.config_sha256,
        "implementation_dependencies_exact": manifest.get(
            "implementation_dependencies"
        )
        == protocol.dependency_hashes,
        "parent_source_exact": manifest.get("parent_source", {}).get(
            "manifest_sha256"
        )
        == protocol.source_manifest_sha256,
        "audit_exact": json.loads(
            (root / manifest["artifacts"]["audit"]["path"]).read_text(
                encoding="utf-8-sig"
            )
        )
        == rebuilt.audit,
    }
    frames = {
        "panel": rebuilt.panel,
        "active_contract_map": rebuilt.active_contract_map,
        "contract_observations": rebuilt.contract_observations,
        "spec_proxy": rebuilt.spec_proxy,
    }
    for name, expected in frames.items():
        record = manifest["artifacts"][name]
        path = root / str(record["path"])
        checks[f"{name}_bytes"] = path.stat().st_size == int(record["bytes"])
        checks[f"{name}_sha256"] = derived_base.sha256_file(path) == record["sha256"]
        stored = pd.read_parquet(path)
        checks[f"{name}_rows"] = len(stored) == int(record["rows"])
        checks[f"{name}_columns"] = stored.columns.tolist() == record["columns"]
        try:
            pd.testing.assert_frame_equal(
                _normalized(stored),
                _normalized(expected),
                check_dtype=False,
            )
        except AssertionError:
            checks[f"{name}_rebuild_exact"] = False
        else:
            checks[f"{name}_rebuild_exact"] = True
    return DerivedAudit(
        checks=checks,
        counts={
            "master_sessions": int(rebuilt.audit["master_session_count"]),
            "panel_rows": len(rebuilt.panel),
            "active_contract_rows": len(rebuilt.active_contract_map),
            "contract_observation_rows": len(rebuilt.contract_observations),
            "spec_proxy_rows": len(rebuilt.spec_proxy),
        },
    )


def build_and_persist(config_path: Path = DEFAULT_CONFIG) -> Path:
    protocol = load_protocol(config_path)
    output = persist_derived(protocol, build_derived_tables(protocol))
    audit = audit_bundle(protocol)
    if not all(audit.checks.values()):
        failed = sorted(name for name, passed in audit.checks.items() if not passed)
        raise ValueError(f"pre-2012 derived audit failed: {failed}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol(arguments.config)
    if arguments.audit_only:
        audit = audit_bundle(protocol)
        print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
        return 0
    print(build_and_persist(arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
