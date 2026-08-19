"""Fail-closed sborka market i target dataset pered futures PnL-ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from market_lab.futures.spec_proxy import (
    PROTECTED_HOLDOUT_START,
    SIZING_LAG_SESSIONS,
    SPEC_PROXY_VERSION,
)

# Fiksirovannyi universe polnogo portfolio snapshot.
EXECUTION_ASSETS = ("SI", "RI", "BR", "MIX")
# Chislovoi dopusk tolko dlya gross, ne dlya missing joins.
EXECUTION_TOLERANCE = 1e-12
# Audit-versiya adaptera pered ledger, bez rascheta PnL.
EXECUTION_DATASET_VERSION = "futures-execution-dataset-v1"
# Klyuch exact one-to-one market/spec join.
MARKET_JOIN_COLUMNS = ("session_date", "asset_code", "contract_id")
# Obyazatel'nye raw polya kontraktnyh nablyudenii.
CONTRACT_OBSERVATION_COLUMNS = frozenset(
    {
        "session_date",
        "asset_code",
        "contract_id",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "volume",
    }
)
# Obyazatel'nye factual i audit polya causal spec-proxy.
SPEC_PROXY_COLUMNS = frozenset(
    {
        "session_date",
        "asset_symbol",
        "contract_id",
        "sizing_point_value",
        "sizing_observed_session_date",
        "sizing_lag_sessions",
        "sizing_usable",
        "realized_accounting_point_value",
        "realized_available_after_session",
        "tick_size",
        "conservative_fee_per_side",
        "modeled_initial_margin",
        "spec_proxy_version",
        "approximate",
        "research_only",
        "historical_exchange_exact",
        "broker_exact",
    }
)
# Ledger-compatible market schema plus raw close i audit provenance.
PORTFOLIO_MARKET_OUTPUT_COLUMNS = (
    "session_date",
    "asset_code",
    "contract_id",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "sizing_point_value",
    "accounting_point_value",
    "tick_size",
    "fee_per_contract",
    "initial_margin",
    "sizing_usable",
    "accounting_usable",
    "spec_proxy_version",
    "approximate",
    "research_only",
    "historical_exchange_exact",
    "broker_exact",
    "provenance",
)
# Minimal'naya skhema causal portfolio weights do contract mapping.
WEIGHT_COLUMNS = frozenset({"decision_date", "asset", "target_weight"})
# Minimal'naya skhema factual next-open timing.
TIMING_COLUMNS = frozenset({"decision_date", "effective_date"})
# Minimal'naya skhema polnogo active-contract snapshot.
ACTIVE_MAP_COLUMNS = frozenset(
    {"decision_date", "effective_date", "observed_through", "asset_code", "contract_id"}
)
# Ledger-compatible target schema s audit provenance.
PORTFOLIO_TARGET_OUTPUT_COLUMNS = (
    "effective_date",
    "decision_date",
    "observed_through",
    "asset_code",
    "contract_id",
    "target_weight",
    "provenance",
)
# Polya execution coverage, kotorye obyazatel'ny dlya non-flat target.
EXECUTION_COVERAGE_FIELDS = (
    "sizing_point_value",
    "accounting_point_value",
    "tick_size",
    "fee_per_contract",
    "initial_margin",
)


@dataclass(frozen=True, slots=True)
class ExecutionCoverageAudit:
    """Hranit validnyi exact-join report vseh non-flat execution rows."""

    active_rows: int
    covered_rows: int
    exact_join: bool
    sizing_available_rows: int
    accounting_available_rows: int
    tick_available_rows: int
    fee_available_rows: int
    initial_margin_available_rows: int
    coverage: pd.DataFrame


def _normalize_dates(values: pd.Series, label: str) -> pd.Series:
    """Normalizuet factual daty bez calendar-day ili timezone sdviga."""
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.isna().any():
        raise ValueError(f"{label} soderzhit propusk daty")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    normalized = parsed.dt.normalize()
    if normalized.dt.date.ge(PROTECTED_HOLDOUT_START).any():
        raise ValueError(f"{label} zahodit v protected holdout")
    return normalized


def _normalize_optional_dates(values: pd.Series, label: str) -> pd.Series:
    """Normalizuet optional factual daty i blokiruet protected holdout."""
    parsed = pd.to_datetime(values, errors="coerce")
    invalid = values.notna() & parsed.isna()
    if invalid.any():
        raise ValueError(f"{label} soderzhit invalid datu")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    normalized = parsed.dt.normalize()
    available = normalized.dropna()
    if available.dt.date.ge(PROTECTED_HOLDOUT_START).any():
        raise ValueError(f"{label} zahodit v protected holdout")
    return normalized


def _normalize_assets(values: pd.Series, label: str) -> pd.Series:
    """Privodit logical futures asset k SI/RI/BR/MIX i zapreshchaet unknown."""
    normalized = values.astype("string").str.strip().str.upper().replace({"RTS": "RI"})
    if normalized.isna().any() or normalized.eq("").any():
        raise ValueError(f"{label} soderzhit pustoi asset")
    unknown = sorted(set(normalized) - set(EXECUTION_ASSETS))
    if unknown:
        raise ValueError(f"{label} soderzhit neizvestnye assets: {unknown}")
    return normalized


def _normalize_contract_ids(values: pd.Series, label: str) -> pd.Series:
    """Sohranyaet canonical contract ID i ostavlyaet yavnyi flat kak NA."""
    normalized = values.astype("string").str.strip()
    normalized = normalized.mask(normalized.eq(""), pd.NA)
    if normalized.dropna().str.contains(r"\s", regex=True).any():
        raise ValueError(f"{label} soderzhit nestabilnyi contract_id")
    return normalized


def _exact_boolean(values: pd.Series, expected: bool, label: str) -> None:
    """Zapreshchaet stroki i chisla vmesto nastoyashchih bool audit-flagov."""
    valid = pd.Series(
        [_is_exact_boolean_value(value, expected) for value in values],
        index=values.index,
    )
    if not valid.all():
        raise ValueError(f"{label} dolzhen byt' exact {expected}")


def _require_boolean(values: pd.Series, label: str) -> None:
    """Trebuet exact bool tip, no razreshaet oba factual sostoyaniya."""
    valid = values.map(_is_boolean_value)
    if not valid.all():
        raise ValueError(f"{label} dolzhen byt' exact bool")


def _is_boolean_value(value: object) -> bool:
    """Proveryaet, chto odno znachenie yavlyaetsya nastoyashchim bool."""
    return isinstance(value, (bool, np.bool_))


def _is_exact_boolean_value(value: object, expected: bool) -> bool:
    """Sravnivaet exact bool znachenie s ozhidaemym flagom."""
    return _is_boolean_value(value) and bool(value) is expected


def _finite_positive(values: pd.Series) -> pd.Series:
    """Vozvrashchaet mask konechnyh strogo polozhitel'nyh znachenii."""
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.notna() & np.isfinite(numeric) & numeric.gt(0.0)


def _finite_nonnegative(values: pd.Series) -> pd.Series:
    """Vozvrashchaet mask konechnyh neotricatel'nyh znachenii."""
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.notna() & np.isfinite(numeric) & numeric.ge(0.0)


def _rename_first_available(
    frame: pd.DataFrame,
    target: str,
    candidates: tuple[str, ...],
) -> pd.DataFrame:
    """Pereimenuet pervyi alias tolko esli canonical target otsutstvuet."""
    if target in frame:
        return frame
    for candidate in candidates:
        if candidate in frame:
            return frame.rename(columns={candidate: target})
    return frame


def _normalize_contract_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet raw OHLC/settle/volume bez imputacii ili synthetic cen."""
    result = frame.copy()
    result = _rename_first_available(result, "session_date", ("trade_date",))
    result = _rename_first_available(result, "asset_code", ("asset", "asset_symbol"))
    result = _rename_first_available(
        result,
        "contract_id",
        ("canonical_contract_id",),
    )
    if missing := CONTRACT_OBSERVATION_COLUMNS - set(result.columns):
        raise ValueError(f"Contract observations ne soderzhat: {sorted(missing)}")
    result = result.loc[:, sorted(CONTRACT_OBSERVATION_COLUMNS)].copy()
    result["session_date"] = _normalize_dates(result["session_date"], "contract observations")
    result["asset_code"] = _normalize_assets(result["asset_code"], "contract observations")
    result["contract_id"] = _normalize_contract_ids(
        result["contract_id"], "contract observations"
    )
    if result["contract_id"].isna().any():
        raise ValueError("Contract observations ne mogut byt' flat")
    numeric_columns = CONTRACT_OBSERVATION_COLUMNS - {
        "session_date",
        "asset_code",
        "contract_id",
    }
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ("open", "high", "low", "close", "settle"):
        available = result[column].dropna()
        if (~np.isfinite(available)).any() or available.le(0.0).any():
            raise ValueError(f"Raw {column} dolzhen byt' finite positive ili missing")
    available_volume = result["volume"].dropna()
    if (~np.isfinite(available_volume)).any() or available_volume.lt(0.0).any():
        raise ValueError("Raw volume dolzhen byt' finite nonnegative ili missing")
    complete = result[["open", "high", "low", "close"]].notna().all(axis=1)
    invalid = complete & (
        result["high"].lt(result[["open", "close"]].max(axis=1))
        | result["low"].gt(result[["open", "close"]].min(axis=1))
        | result["high"].lt(result["low"])
    )
    if invalid.any():
        raise ValueError("Contract observations narushayut OHLC invariant")
    if result.duplicated(list(MARKET_JOIN_COLUMNS)).any():
        raise ValueError("Contract observations soderzhat duplicate join-key")
    return result.sort_values(list(MARKET_JOIN_COLUMNS), kind="mergesort").reset_index(
        drop=True
    )


def _normalize_spec_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet causal lag-1 specs i research-only audit-flagi bez imputacii."""
    result = frame.copy()
    result = _rename_first_available(result, "session_date", ("trade_date",))
    result = _rename_first_available(result, "asset_symbol", ("asset", "asset_code"))
    result = _rename_first_available(
        result,
        "contract_id",
        ("canonical_contract_id",),
    )
    if missing := SPEC_PROXY_COLUMNS - set(result.columns):
        raise ValueError(f"Spec proxy ne soderzhit: {sorted(missing)}")
    result = result.loc[:, sorted(SPEC_PROXY_COLUMNS)].copy()
    result["session_date"] = _normalize_dates(result["session_date"], "spec proxy")
    result["asset_code"] = _normalize_assets(result.pop("asset_symbol"), "spec proxy")
    result["contract_id"] = _normalize_contract_ids(result["contract_id"], "spec proxy")
    if result["contract_id"].isna().any():
        raise ValueError("Spec proxy contract_id ne mozhet byt' pustym")
    if result["spec_proxy_version"].ne(SPEC_PROXY_VERSION).any():
        raise ValueError("Spec proxy version ne sootvetstvuet zamorozhennoi")
    _exact_boolean(result["approximate"], True, "approximate")
    _exact_boolean(result["research_only"], True, "research_only")
    _exact_boolean(result["historical_exchange_exact"], False, "historical_exchange_exact")
    _exact_boolean(result["broker_exact"], False, "broker_exact")
    _require_boolean(result["sizing_usable"], "sizing_usable")
    _require_boolean(
        result["realized_available_after_session"], "realized_available_after_session"
    )
    result["sizing_observed_session_date"] = _normalize_optional_dates(
        result["sizing_observed_session_date"], "sizing observed session"
    )
    for column in (
        "sizing_point_value",
        "realized_accounting_point_value",
        "tick_size",
        "conservative_fee_per_side",
        "modeled_initial_margin",
        "sizing_lag_sessions",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    sizing_usable = result["sizing_usable"].astype(bool)
    accounting_usable = result["realized_available_after_session"].astype(bool)
    if result["sizing_lag_sessions"].ne(SIZING_LAG_SESSIONS).any():
        raise ValueError("Spec proxy sizing lag dolzhen byt' rovno odna factual session")
    if (
        result.loc[sizing_usable, "sizing_observed_session_date"].isna().any()
        or (
            result.loc[sizing_usable, "sizing_observed_session_date"]
            >= result.loc[sizing_usable, "session_date"]
        ).any()
    ):
        raise ValueError("Usable sizing spec dolzhen byt' nablyudaem strogo do session")
    positive_requirements = {
        "sizing_point_value": sizing_usable,
        "modeled_initial_margin": sizing_usable,
        "realized_accounting_point_value": accounting_usable,
    }
    for column, mask in positive_requirements.items():
        if not _finite_positive(result.loc[mask, column]).all():
            raise ValueError(f"Usable spec soderzhit invalid {column}")
    if not _finite_positive(result["tick_size"]).all():
        raise ValueError("Spec proxy tick_size dolzhen byt' polozhitel'nym")
    if not _finite_positive(result["conservative_fee_per_side"]).all():
        raise ValueError("Spec proxy conservative fee dolzhen byt' positive")
    if result.duplicated(list(MARKET_JOIN_COLUMNS)).any():
        raise ValueError("Spec proxy soderzhit duplicate join-key")
    return result.sort_values(list(MARKET_JOIN_COLUMNS), kind="mergesort").reset_index(
        drop=True
    )


def _exact_key_match(left: pd.DataFrame, right: pd.DataFrame, label: str) -> None:
    """Trebuet odinakovyi nabor join-key bez left/right-only strok."""
    compared = left.loc[:, list(MARKET_JOIN_COLUMNS)].merge(
        right.loc[:, list(MARKET_JOIN_COLUMNS)],
        on=list(MARKET_JOIN_COLUMNS),
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    if not compared["_merge"].eq("both").all():
        counts = compared["_merge"].value_counts().to_dict()
        raise ValueError(f"{label} key mismatch: {counts}")


def build_portfolio_market(
    contract_observations: pd.DataFrame,
    spec_proxy: pd.DataFrame,
) -> pd.DataFrame:
    """Stroit exact ledger market iz raw contract rows i causal research specs."""
    observations = _normalize_contract_observations(contract_observations)
    specs = _normalize_spec_proxy(spec_proxy)
    _exact_key_match(observations, specs, "contract/spec")
    merged = observations.merge(
        specs,
        on=list(MARKET_JOIN_COLUMNS),
        how="inner",
        validate="one_to_one",
        sort=True,
    )
    merged = merged.rename(
        columns={
            "realized_accounting_point_value": "accounting_point_value",
            "conservative_fee_per_side": "fee_per_contract",
            "modeled_initial_margin": "initial_margin",
            "realized_available_after_session": "accounting_usable",
        }
    )
    merged["provenance"] = json.dumps(
        {
            "version": EXECUTION_DATASET_VERSION,
            "join": "exact_one_to_one_session_asset_canonical_contract",
            "sizing": "lag_1_factual_session",
            "accounting": "current_session_realized",
            "imputation": False,
            "research_only": True,
            "contains_pnl_or_returns": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return merged.loc[:, list(PORTFOLIO_MARKET_OUTPUT_COLUMNS)].sort_values(
        list(MARKET_JOIN_COLUMNS), kind="mergesort", ignore_index=True
    )


def _normalize_weights(frame: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet polnye finite weight snapshots do contract mapping."""
    result = frame.copy()
    result = _rename_first_available(result, "asset", ("asset_code", "asset_symbol"))
    if missing := WEIGHT_COLUMNS - set(result.columns):
        raise ValueError(f"Weights ne soderzhat: {sorted(missing)}")
    keep = sorted(WEIGHT_COLUMNS | ({"provenance"} & set(result.columns)))
    result = result.loc[:, keep].copy()
    result["decision_date"] = _normalize_dates(result["decision_date"], "weights")
    result["asset_code"] = _normalize_assets(result.pop("asset"), "weights")
    result["target_weight"] = pd.to_numeric(result["target_weight"], errors="coerce")
    if not np.isfinite(result["target_weight"]).all():
        raise ValueError("Weights target_weight dolzhen byt' finite")
    if result["target_weight"].abs().gt(1.0 + EXECUTION_TOLERANCE).any():
        raise ValueError("Otdel'nyi target_weight prevyshaet 1")
    if result.duplicated(["decision_date", "asset_code"]).any():
        raise ValueError("Weights soderzhat duplicate decision/asset")
    expected = frozenset(EXECUTION_ASSETS)
    for decision_date, snapshot in result.groupby("decision_date", sort=False):
        if frozenset(snapshot["asset_code"]) != expected:
            raise ValueError(f"Nepolnyi weight snapshot na {decision_date.date()}")
        if snapshot["target_weight"].abs().sum() > 1.0 + EXECUTION_TOLERANCE:
            raise ValueError("Weight snapshot prevyshaet gross 1x")
    if "provenance" not in result:
        result["provenance"] = pd.NA
    return result.sort_values(["decision_date", "asset_code"], kind="mergesort").reset_index(
        drop=True
    )


def _normalize_timing(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet exact decision D -> next factual effective date."""
    result = frame.copy()
    result = _rename_first_available(result, "decision_date", ("trade_date",))
    if missing := TIMING_COLUMNS - set(result.columns):
        raise ValueError(f"Timing map ne soderzhit: {sorted(missing)}")
    keep = sorted(TIMING_COLUMNS | ({"timing_regime"} & set(result.columns)))
    result = result.loc[:, keep].copy()
    result["decision_date"] = _normalize_dates(result["decision_date"], "timing decision")
    result["effective_date"] = _normalize_dates(result["effective_date"], "timing effective")
    if result["decision_date"].ge(result["effective_date"]).any():
        raise ValueError("Timing effective_date dolzhen byt' posle decision_date")
    if result["decision_date"].duplicated().any() or result["effective_date"].duplicated().any():
        raise ValueError("Timing map dolzhen byt' one-to-one")
    if "timing_regime" not in result:
        result["timing_regime"] = "next_factual_trade_date_open"
    return result.sort_values("decision_date", kind="mergesort").reset_index(drop=True)


def _normalize_active_map(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet polnyi causal active-contract snapshot bez podstanovki kontrakta."""
    result = frame.copy()
    result = _rename_first_available(result, "asset_code", ("asset", "asset_symbol"))
    result = _rename_first_available(
        result,
        "contract_id",
        ("active_contract_id", "position_contract_id", "canonical_contract_id"),
    )
    if missing := ACTIVE_MAP_COLUMNS - set(result.columns):
        raise ValueError(f"Active map ne soderzhit: {sorted(missing)}")
    optional = {"tradable"} & set(result.columns)
    result = result.loc[:, sorted(ACTIVE_MAP_COLUMNS | optional)].copy()
    result["decision_date"] = _normalize_dates(result["decision_date"], "active decision")
    result["effective_date"] = _normalize_dates(result["effective_date"], "active effective")
    result["observed_through"] = _normalize_dates(
        result["observed_through"], "active observed_through"
    )
    result["asset_code"] = _normalize_assets(result["asset_code"], "active map")
    result["contract_id"] = _normalize_contract_ids(result["contract_id"], "active map")
    if result["observed_through"].gt(result["decision_date"]).any():
        raise ValueError("Active observed_through ne mozhet byt' pozhe decision_date")
    if result["decision_date"].ge(result["effective_date"]).any():
        raise ValueError("Active effective_date dolzhen byt' posle decision_date")
    if result.duplicated(["decision_date", "asset_code"]).any():
        raise ValueError("Active map soderzhit duplicate decision/asset")
    if "tradable" in result:
        valid_tradable = result["tradable"].map(_is_boolean_value)
        if not valid_tradable.all():
            raise ValueError("Active tradable dolzhen byt' exact bool")
    else:
        result["tradable"] = result["contract_id"].notna()
    return result.sort_values(["decision_date", "asset_code"], kind="mergesort").reset_index(
        drop=True
    )


def _assert_weight_active_keys(weights: pd.DataFrame, active: pd.DataFrame) -> None:
    """Trebuet odinakovye polnye decision/asset keys weights i active map."""
    keys = ["decision_date", "asset_code"]
    compared = weights.loc[:, keys].merge(
        active.loc[:, keys],
        on=keys,
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    if not compared["_merge"].eq("both").all():
        raise ValueError("Weights i active map imeyut raznye decision/asset keys")


def map_decision_weights_to_next_open(
    weights: pd.DataFrame,
    timing_map: pd.DataFrame,
    active_map: pd.DataFrame,
) -> pd.DataFrame:
    """Mapit close-D weights na exact next factual open i active contract."""
    normalized_weights = _normalize_weights(weights)
    timing = _normalize_timing(timing_map)
    active = _normalize_active_map(active_map)
    _assert_weight_active_keys(normalized_weights, active)
    active_with_timing = active.merge(
        timing,
        on="decision_date",
        how="left",
        validate="many_to_one",
        suffixes=("_active", "_timing"),
    )
    if active_with_timing["effective_date_timing"].isna().any():
        raise ValueError("Active map decision_date otsutstvuet v timing map")
    if active_with_timing["effective_date_active"].ne(
        active_with_timing["effective_date_timing"]
    ).any():
        raise ValueError("Active map effective_date ne sootvetstvuet timing")
    mapped = normalized_weights.merge(
        active_with_timing,
        on=["decision_date", "asset_code"],
        how="inner",
        validate="one_to_one",
        suffixes=("_weight", "_active"),
    )
    nonzero = mapped["target_weight"].ne(0.0)
    missing_contract = mapped["contract_id"].isna()
    if (nonzero & missing_contract).any():
        raise ValueError("Nenulevoi target ne imeet active contract")
    if (nonzero & ~mapped["tradable"].astype(bool)).any():
        raise ValueError("Nenulevoi target ukazan dlya netorguemogo active contract")
    mapped.loc[~nonzero, "contract_id"] = pd.NA
    output_rows: list[dict[str, Any]] = []
    for row in mapped.itertuples(index=False):
        provenance = {
            "version": EXECUTION_DATASET_VERSION,
            "mapping": "decision_close_to_next_factual_trade_date_open",
            "timing_regime": row.timing_regime,
            "active_observed_through": row.observed_through.date().isoformat(),
            "weight_provenance": row.provenance,
            "contract_removed_for_zero_target": bool(row.target_weight == 0.0),
            "contains_pnl_or_returns": False,
        }
        output_rows.append(
            {
                "effective_date": row.effective_date_timing,
                "decision_date": row.decision_date,
                "observed_through": row.observed_through,
                "asset_code": row.asset_code,
                "contract_id": row.contract_id,
                "target_weight": float(row.target_weight),
                "provenance": json.dumps(
                    provenance,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            }
        )
    return pd.DataFrame(output_rows, columns=PORTFOLIO_TARGET_OUTPUT_COLUMNS).sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )


def _normalize_market_for_audit(frame: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet ledger market schema, version i research-only flagi pered audit."""
    required = set(PORTFOLIO_MARKET_OUTPUT_COLUMNS) - {"provenance", "close"}
    if missing := required - set(frame.columns):
        raise ValueError(f"Portfolio market audit ne soderzhit: {sorted(missing)}")
    result = frame.copy()
    result["session_date"] = _normalize_dates(result["session_date"], "portfolio market")
    result["asset_code"] = _normalize_assets(result["asset_code"], "portfolio market")
    result["contract_id"] = _normalize_contract_ids(result["contract_id"], "portfolio market")
    if result["contract_id"].isna().any():
        raise ValueError("Portfolio market ne mozhet soderzhat flat contract")
    if result["spec_proxy_version"].ne(SPEC_PROXY_VERSION).any():
        raise ValueError("Portfolio market spec version mismatch")
    _exact_boolean(result["approximate"], True, "market approximate")
    _exact_boolean(result["research_only"], True, "market research_only")
    _exact_boolean(
        result["historical_exchange_exact"], False, "market historical_exchange_exact"
    )
    _exact_boolean(result["broker_exact"], False, "market broker_exact")
    _require_boolean(result["sizing_usable"], "market sizing_usable")
    _require_boolean(result["accounting_usable"], "market accounting_usable")
    if result.duplicated(list(MARKET_JOIN_COLUMNS)).any():
        raise ValueError("Portfolio market audit soderzhit duplicate join-key")
    return result


def _normalize_active_for_audit(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet mapped targets ili active contract rows dlya coverage audit."""
    result = frame.copy()
    result = _rename_first_available(result, "asset_code", ("asset", "asset_symbol"))
    result = _rename_first_available(
        result,
        "contract_id",
        ("active_contract_id", "position_contract_id", "canonical_contract_id"),
    )
    result = _rename_first_available(result, "effective_date", ("session_date",))
    required = {"effective_date", "asset_code", "contract_id"}
    if missing := required - set(result.columns):
        raise ValueError(f"Active execution audit ne soderzhit: {sorted(missing)}")
    keep = sorted(required | ({"target_weight"} & set(result.columns)))
    result = result.loc[:, keep].copy()
    result["effective_date"] = _normalize_dates(result["effective_date"], "active execution")
    result["asset_code"] = _normalize_assets(result["asset_code"], "active execution")
    result["contract_id"] = _normalize_contract_ids(result["contract_id"], "active execution")
    if "target_weight" in result:
        result["target_weight"] = pd.to_numeric(result["target_weight"], errors="coerce")
        if not np.isfinite(result["target_weight"]).all():
            raise ValueError("Active execution target_weight dolzhen byt' finite")
        nonflat = result["target_weight"].ne(0.0)
    else:
        nonflat = result["contract_id"].notna()
    if result.loc[nonflat, "contract_id"].isna().any():
        raise ValueError("Non-flat active execution row ne imeet contract_id")
    result = result.loc[nonflat].copy()
    if result.duplicated(["effective_date", "asset_code"]).any():
        raise ValueError("Active execution audit soderzhit duplicate effective/asset")
    return result


def audit_active_execution_coverage(
    market: pd.DataFrame,
    active_map: pd.DataFrame,
) -> ExecutionCoverageAudit:
    """Validiruet exact market join i vse specs kazhdoi non-flat active stroki."""
    normalized_market = _normalize_market_for_audit(market)
    active = _normalize_active_for_audit(active_map)
    if active.empty:
        empty = pd.DataFrame(
            columns=["effective_date", "asset_code", "contract_id", *EXECUTION_COVERAGE_FIELDS]
        )
        return ExecutionCoverageAudit(0, 0, True, 0, 0, 0, 0, 0, empty)
    joined = active.merge(
        normalized_market,
        left_on=["effective_date", "asset_code", "contract_id"],
        right_on=["session_date", "asset_code", "contract_id"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    missing_market = joined["_merge"].ne("both")
    if missing_market.any():
        raise ValueError(f"Active execution ne imeet exact market row: {int(missing_market.sum())}")
    availability = pd.DataFrame(
        {
            "sizing_point_value": joined["sizing_usable"].astype(bool)
            & _finite_positive(joined["sizing_point_value"]),
            "accounting_point_value": joined["accounting_usable"].astype(bool)
            & _finite_positive(joined["accounting_point_value"]),
            "tick_size": _finite_positive(joined["tick_size"]),
            "fee_per_contract": _finite_positive(joined["fee_per_contract"]),
            "initial_margin": _finite_positive(joined["initial_margin"]),
        }
    )
    incomplete = ~availability.all(axis=1)
    if incomplete.any():
        counts = {column: int((~availability[column]).sum()) for column in availability}
        raise ValueError(f"Active execution specs incomplete: {counts}")
    coverage = joined.loc[:, ["effective_date", "asset_code", "contract_id"]].copy()
    for column in EXECUTION_COVERAGE_FIELDS:
        coverage[column] = availability[column].to_numpy(dtype=bool)
    count = len(coverage)
    return ExecutionCoverageAudit(
        active_rows=count,
        covered_rows=count,
        exact_join=True,
        sizing_available_rows=int(availability["sizing_point_value"].sum()),
        accounting_available_rows=int(availability["accounting_point_value"].sum()),
        tick_available_rows=int(availability["tick_size"].sum()),
        fee_available_rows=int(availability["fee_per_contract"].sum()),
        initial_margin_available_rows=int(availability["initial_margin"].sum()),
        coverage=coverage.reset_index(drop=True),
    )
