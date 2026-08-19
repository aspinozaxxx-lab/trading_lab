"""Kausal'nyi versioned proxy kontraktnyh futures-specs dlya research accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

SPEC_PROXY_VERSION = "futures-conservative-spec-proxy-v1"  # Zamorozhennaya versiya proxy.
PROTECTED_HOLDOUT_START = date(2026, 1, 1)  # Nachalo zapreshchennogo futures holdout.
MODELED_INITIAL_MARGIN_RATE = 0.25  # Research IM kak 25% lagged notional, ne birzhevaya istoriya.
EXPECTED_MARGIN_BUFFER_MULTIPLE = 2.0  # Konservativnyi dvukratnyi buffer modeled IM.
SIZING_LAG_SESSIONS = 1  # Edinstvennyi dopustimyi lag factual session dlya sizing.
REALIZED_POINT_VALUE_FORMULA = (  # Audit-imya primary formuly accounting proxy.
    "VALUE/(VOLUME*WAPRICE)"
)
FALLBACK_REALIZED_POINT_VALUE_FORMULA = (  # Audit-imya factual OI fallback-formuly.
    "OPENPOSITIONVALUE/(OPENPOSITION*SETTLEPRICE)"
)
UNAVAILABLE_REALIZED_POINT_VALUE_FORMULA = (  # Yavnoe imya otsutstvuyushchei formuly.
    "UNAVAILABLE"
)
INPUT_COLUMNS = frozenset(  # Minimal'naya factual daily skhema bez returns i targetov.
    {
        "session_date",
        "contract_id",
        "asset_symbol",
        "value",
        "volume",
        "waprice",
        "settle",
        "open_interest",
        "open_interest_value",
    }
)
INPUT_ALIASES = {  # Sovmestimost' s normalizovannymi imenami dnevnoi istorii ISS.
    "trade_date": "session_date",
    "secid": "contract_id",
    "asset_code": "asset_symbol",
    "weighted_average_price": "waprice",
}
ASSET_ALIASES = {  # Oficial'nye asset code i torgovye prefiksy v logical symbol.
    "SI": "SI",
    "RI": "RI",
    "RTS": "RI",
    "BR": "BR",
    "MIX": "MIX",
    "MX": "MIX",
}
PROXY_OUTPUT_COLUMNS = (  # Stabil'naya skhema causal spec-proxy.
    "session_date",
    "contract_id",
    "asset_symbol",
    "value",
    "volume",
    "waprice",
    "settle",
    "open_interest",
    "open_interest_value",
    "primary_trade_accounting_point_value",
    "fallback_open_interest_accounting_point_value",
    "realized_accounting_point_value",
    "realized_reference_price",
    "realized_point_value_formula",
    "realized_accounting_status",
    "realized_available_after_session",
    "sizing_observed_session_date",
    "sizing_point_value",
    "sizing_reference_price",
    "sizing_notional",
    "sizing_tick_cash_value",
    "modeled_initial_margin",
    "expected_buffered_initial_margin",
    "sizing_status",
    "sizing_usable",
    "tick_size",
    "conservative_fee_per_side",
    "modeled_initial_margin_rate",
    "expected_margin_buffer_multiple",
    "sizing_lag_sessions",
    "spec_proxy_version",
    "approximate",
    "research_only",
    "historical_exchange_exact",
    "broker_exact",
)


@dataclass(frozen=True, slots=True)
class ConservativeFuturesSpec:
    """Fiksiruet versioned tick, fee i modeled margin odnogo logical asset."""

    asset_symbol: str
    tick_size: float
    conservative_fee_per_side: float
    modeled_initial_margin_rate: float = MODELED_INITIAL_MARGIN_RATE
    expected_margin_buffer_multiple: float = EXPECTED_MARGIN_BUFFER_MULTIPLE
    version: str = SPEC_PROXY_VERSION
    approximate: bool = True
    research_only: bool = True
    historical_exchange_exact: bool = False
    broker_exact: bool = False

    def __post_init__(self) -> None:
        """Zapreshchaet oslablenie konservativnyh ili audit-harakteristik proxy."""
        if pd.isna(self.asset_symbol):
            raise ValueError("Pustoi asset v futures spec-proxy")
        alias = str(self.asset_symbol).strip().upper()
        if alias not in ASSET_ALIASES:
            raise ValueError(f"Neizvestnyi asset futures spec-proxy: {self.asset_symbol!r}")
        normalized = ASSET_ALIASES[alias]
        object.__setattr__(self, "asset_symbol", normalized)
        numeric = (
            self.tick_size,
            self.conservative_fee_per_side,
            self.modeled_initial_margin_rate,
            self.expected_margin_buffer_multiple,
        )
        if any(not np.isfinite(value) or value <= 0.0 for value in numeric):
            raise ValueError("Tick, fee i margin assumptions dolzhny byt' polozhitel'nymi")
        if self.modeled_initial_margin_rate != MODELED_INITIAL_MARGIN_RATE:
            raise ValueError("V etoi versii modeled IM dolzhen byt' rovno 25% notional")
        if self.expected_margin_buffer_multiple != EXPECTED_MARGIN_BUFFER_MULTIPLE:
            raise ValueError("V etoi versii expected margin buffer dolzhen byt' rovno 2x")
        if self.version != SPEC_PROXY_VERSION:
            raise ValueError("Neizvestnaya versiya futures spec-proxy")
        if (
            not self.approximate
            or not self.research_only
            or self.historical_exchange_exact
            or self.broker_exact
        ):
            raise ValueError("Spec-proxy dolzhen ostavat'sya approximate research-only")


@dataclass(frozen=True, slots=True)
class RequiredSizingSpec:
    """Hranit tol'ko proverennyi lag-1 spec dlya odnogo session-open resheniya."""

    session_date: pd.Timestamp
    contract_id: str
    asset_symbol: str
    sizing_observed_session_date: pd.Timestamp
    sizing_point_value: float
    sizing_reference_price: float
    sizing_notional: float
    tick_size: float
    sizing_tick_cash_value: float
    conservative_fee_per_side: float
    modeled_initial_margin: float
    expected_buffered_initial_margin: float
    version: str
    approximate: bool
    research_only: bool
    historical_exchange_exact: bool
    broker_exact: bool

    def __post_init__(self) -> None:
        """Proveryaet, chto accessor ne propustil unknown ili necausal value."""
        numeric = (
            self.sizing_point_value,
            self.sizing_reference_price,
            self.sizing_notional,
            self.tick_size,
            self.sizing_tick_cash_value,
            self.conservative_fee_per_side,
            self.modeled_initial_margin,
            self.expected_buffered_initial_margin,
        )
        if any(not np.isfinite(value) or value <= 0.0 for value in numeric):
            raise ValueError("Required sizing spec soderzhit unknown ili nepositive value")
        if self.sizing_observed_session_date >= self.session_date:
            raise ValueError("Sizing spec dolzhen byt' iz proshloi factual session")
        if self.version != SPEC_PROXY_VERSION:
            raise ValueError("Sizing spec imeet neizvestnuyu versiyu")
        if (
            not self.approximate
            or not self.research_only
            or self.historical_exchange_exact
            or self.broker_exact
        ):
            raise ValueError("Sizing spec ne mozhet vydavat'sya za broker/exchange exact")


CONSERVATIVE_SPEC_REGISTRY = {  # Zamorozhennye tick i fee na storonu v RUB.
    "SI": ConservativeFuturesSpec("SI", tick_size=1.0, conservative_fee_per_side=4.0),
    "RI": ConservativeFuturesSpec("RI", tick_size=10.0, conservative_fee_per_side=9.0),
    "BR": ConservativeFuturesSpec("BR", tick_size=0.01, conservative_fee_per_side=10.0),
    "MIX": ConservativeFuturesSpec("MIX", tick_size=25.0, conservative_fee_per_side=15.0),
}


def conservative_futures_spec(asset_symbol: str) -> ConservativeFuturesSpec:
    """Vozvrashchaet zamorozhennyi proxy ili fail-closed dlya neizvestnogo asset."""
    normalized = _normalize_asset_symbol(asset_symbol)
    return CONSERVATIVE_SPEC_REGISTRY[normalized]


def realized_rub_point_multiplier(value: object, volume: object, waprice: object) -> float:
    """Schitaet VALUE/(VOLUME*WAPRICE) tol'ko dlya finite positive factual polei."""
    values = tuple(_finite_positive_or_none(item) for item in (value, volume, waprice))
    if any(item is None for item in values):
        return float("nan")
    factual_value, factual_volume, factual_waprice = values
    assert factual_value is not None
    assert factual_volume is not None
    assert factual_waprice is not None
    multiplier = factual_value / (factual_volume * factual_waprice)
    return float(multiplier) if np.isfinite(multiplier) and multiplier > 0.0 else float("nan")


def realized_rub_open_interest_point_multiplier(
    open_interest_value: object,
    open_interest: object,
    settle: object,
) -> float:
    """Schitaet OI-value/(OI*settle) tol'ko dlya finite positive factual polei."""
    values = tuple(
        _finite_positive_or_none(item)
        for item in (open_interest_value, open_interest, settle)
    )
    if any(item is None for item in values):
        return float("nan")
    factual_value, factual_open_interest, factual_settle = values
    assert factual_value is not None
    assert factual_open_interest is not None
    assert factual_settle is not None
    multiplier = factual_value / (factual_open_interest * factual_settle)
    return float(multiplier) if np.isfinite(multiplier) and multiplier > 0.0 else float("nan")


def build_causal_spec_proxy(
    daily: pd.DataFrame,
    session_calendar: pd.DatetimeIndex | list[object] | tuple[object, ...],
) -> pd.DataFrame:
    """Stroit current accounting proxy i strogo lag-1 sizing specs po kontraktu."""
    market = _normalize_daily(daily)
    calendar = _normalize_session_calendar(session_calendar)
    unknown_dates = set(market["session_date"]) - set(calendar)
    if unknown_dates:
        raise ValueError("Daily spec-proxy soderzhit datu vne factual session calendar")
    ordinal = pd.Series(np.arange(len(calendar), dtype=int), index=calendar)
    market["_session_ordinal"] = market["session_date"].map(ordinal)
    market["primary_trade_accounting_point_value"] = [
        realized_rub_point_multiplier(value, volume, waprice)
        for value, volume, waprice in market[["value", "volume", "waprice"]].itertuples(
            index=False,
            name=None,
        )
    ]
    market["fallback_open_interest_accounting_point_value"] = [
        realized_rub_open_interest_point_multiplier(open_interest_value, open_interest, settle)
        for open_interest_value, open_interest, settle in market[
            ["open_interest_value", "open_interest", "settle"]
        ].itertuples(index=False, name=None)
    ]
    primary_valid = _positive_series(market["primary_trade_accounting_point_value"])
    fallback_valid = _positive_series(
        market["fallback_open_interest_accounting_point_value"]
    )
    fallback_selected = ~primary_valid & fallback_valid
    realized_valid = primary_valid | fallback_selected
    market["realized_accounting_point_value"] = np.select(
        [primary_valid, fallback_selected],
        [
            market["primary_trade_accounting_point_value"],
            market["fallback_open_interest_accounting_point_value"],
        ],
        default=np.nan,
    )
    market["realized_reference_price"] = np.select(
        [primary_valid, fallback_selected],
        [market["waprice"], market["settle"]],
        default=np.nan,
    )
    market["realized_accounting_status"] = np.select(
        [primary_valid, fallback_selected],
        ["available_primary_after_session", "available_fallback_after_session"],
        default="invalid_primary_and_fallback",
    )
    market["realized_point_value_formula"] = np.select(
        [primary_valid, fallback_selected],
        [REALIZED_POINT_VALUE_FORMULA, FALLBACK_REALIZED_POINT_VALUE_FORMULA],
        default=UNAVAILABLE_REALIZED_POINT_VALUE_FORMULA,
    )
    market["realized_available_after_session"] = realized_valid
    groups = market.groupby("contract_id", sort=False, observed=True)
    market["sizing_observed_session_date"] = groups["session_date"].shift(1)
    market["_previous_session_ordinal"] = groups["_session_ordinal"].shift(1)
    market["sizing_point_value"] = groups["realized_accounting_point_value"].shift(1)
    market["sizing_reference_price"] = groups["realized_reference_price"].shift(1)
    market["_session_gap"] = market["_session_ordinal"] - market["_previous_session_ordinal"]
    missing_previous = market["sizing_observed_session_date"].isna()
    stale_previous = ~missing_previous & market["_session_gap"].ne(SIZING_LAG_SESSIONS)
    previous_invalid = ~missing_previous & ~stale_previous & ~(
        _positive_series(market["sizing_point_value"])
        & _positive_series(market["sizing_reference_price"])
    )
    market["sizing_status"] = np.select(
        [missing_previous, stale_previous, previous_invalid],
        [
            "missing_previous_contract_session",
            "stale_previous_contract_session",
            "previous_session_proxy_invalid",
        ],
        default="available_lag_1_session",
    )
    market["sizing_usable"] = market["sizing_status"].eq("available_lag_1_session")
    market.loc[~market["sizing_usable"], "sizing_point_value"] = np.nan
    market.loc[~market["sizing_usable"], "sizing_reference_price"] = np.nan
    market["sizing_notional"] = (
        market["sizing_point_value"] * market["sizing_reference_price"]
    )
    specs = [conservative_futures_spec(symbol) for symbol in market["asset_symbol"]]
    market["tick_size"] = [spec.tick_size for spec in specs]
    market["conservative_fee_per_side"] = [spec.conservative_fee_per_side for spec in specs]
    market["sizing_tick_cash_value"] = market["tick_size"] * market["sizing_point_value"]
    market["modeled_initial_margin"] = market["sizing_notional"] * MODELED_INITIAL_MARGIN_RATE
    market["expected_buffered_initial_margin"] = (
        market["modeled_initial_margin"] * EXPECTED_MARGIN_BUFFER_MULTIPLE
    )
    market["modeled_initial_margin_rate"] = MODELED_INITIAL_MARGIN_RATE
    market["expected_margin_buffer_multiple"] = EXPECTED_MARGIN_BUFFER_MULTIPLE
    market["sizing_lag_sessions"] = SIZING_LAG_SESSIONS
    market["spec_proxy_version"] = SPEC_PROXY_VERSION
    market["approximate"] = True
    market["research_only"] = True
    market["historical_exchange_exact"] = False
    market["broker_exact"] = False
    return market.loc[:, PROXY_OUTPUT_COLUMNS].reset_index(drop=True)


def require_sizing_spec(
    proxy: pd.DataFrame,
    contract_id: str,
    session_date: object,
) -> RequiredSizingSpec:
    """Vozvrashchaet sizing spec ili otkazyvaetsya pri missing/stale/unknown stroki."""
    missing_columns = set(PROXY_OUTPUT_COLUMNS) - set(proxy.columns)
    if missing_columns:
        raise ValueError(f"Spec-proxy ne soderzhit kolonok: {sorted(missing_columns)}")
    normalized_date = _normalize_one_date(session_date)
    selected = proxy.loc[
        proxy["contract_id"].astype("string").eq(str(contract_id))
        & pd.to_datetime(proxy["session_date"], errors="raise").dt.normalize().eq(normalized_date)
    ]
    if len(selected) != 1:
        raise LookupError("Nuzhna rovno odna stroka contract/session spec-proxy")
    row = selected.iloc[0]
    if not bool(row["sizing_usable"]):
        raise LookupError(f"Sizing spec nedostupen: {row['sizing_status']}")
    if row["spec_proxy_version"] != SPEC_PROXY_VERSION:
        raise ValueError("Spec-proxy version ne sootvetstvuet zamorozhennoi")
    if (
        not _exact_bool(row["approximate"], True)
        or not _exact_bool(row["research_only"], True)
        or not _exact_bool(row["historical_exchange_exact"], False)
        or not _exact_bool(row["broker_exact"], False)
        or row["sizing_lag_sessions"] != SIZING_LAG_SESSIONS
        or row["modeled_initial_margin_rate"] != MODELED_INITIAL_MARGIN_RATE
        or row["expected_margin_buffer_multiple"] != EXPECTED_MARGIN_BUFFER_MULTIPLE
    ):
        raise ValueError("Spec-proxy assumptions byli izmeneny ili oslableny")
    return RequiredSizingSpec(
        session_date=pd.Timestamp(row["session_date"]),
        contract_id=str(row["contract_id"]),
        asset_symbol=str(row["asset_symbol"]),
        sizing_observed_session_date=pd.Timestamp(row["sizing_observed_session_date"]),
        sizing_point_value=float(row["sizing_point_value"]),
        sizing_reference_price=float(row["sizing_reference_price"]),
        sizing_notional=float(row["sizing_notional"]),
        tick_size=float(row["tick_size"]),
        sizing_tick_cash_value=float(row["sizing_tick_cash_value"]),
        conservative_fee_per_side=float(row["conservative_fee_per_side"]),
        modeled_initial_margin=float(row["modeled_initial_margin"]),
        expected_buffered_initial_margin=float(row["expected_buffered_initial_margin"]),
        version=str(row["spec_proxy_version"]),
        approximate=bool(row["approximate"]),
        research_only=bool(row["research_only"]),
        historical_exchange_exact=bool(row["historical_exchange_exact"]),
        broker_exact=bool(row["broker_exact"]),
    )


def require_realized_accounting_point_value(
    proxy: pd.DataFrame,
    contract_id: str,
    session_date: object,
) -> float:
    """Vozvrashchaet current-session accounting proxy tol'ko posle proverki ego status."""
    if set(PROXY_OUTPUT_COLUMNS) - set(proxy.columns):
        raise ValueError("Frame ne yavlyaetsya spec-proxy accounting nablyudenii")
    normalized_date = _normalize_one_date(session_date)
    selected = proxy.loc[
        proxy["contract_id"].astype("string").eq(str(contract_id))
        & pd.to_datetime(proxy["session_date"], errors="raise").dt.normalize().eq(normalized_date)
    ]
    if len(selected) != 1:
        raise LookupError("Nuzhna rovno odna accounting stroka contract/session")
    row = selected.iloc[0]
    status = row["realized_accounting_status"]
    formula = row["realized_point_value_formula"]
    expected_formula = {
        "available_primary_after_session": REALIZED_POINT_VALUE_FORMULA,
        "available_fallback_after_session": FALLBACK_REALIZED_POINT_VALUE_FORMULA,
    }.get(status)
    if status == "invalid_primary_and_fallback":
        raise LookupError("Realized accounting point value unknown")
    if expected_formula is None:
        raise ValueError("Accounting proxy imeet neizvestnyi status")
    if (
        row["spec_proxy_version"] != SPEC_PROXY_VERSION
        or formula != expected_formula
        or not _exact_bool(row["realized_available_after_session"], True)
        or not _exact_bool(row["approximate"], True)
        or not _exact_bool(row["research_only"], True)
        or not _exact_bool(row["historical_exchange_exact"], False)
        or not _exact_bool(row["broker_exact"], False)
    ):
        raise ValueError("Accounting proxy assumptions byli izmeneny ili oslableny")
    value = _finite_positive_or_none(row["realized_accounting_point_value"])
    if value is None:
        raise LookupError("Realized accounting point value unknown")
    return value


def assert_append_only_spec_proxy(existing: pd.DataFrame, candidate: pd.DataFrame) -> None:
    """Proveryaet neizmennost' staryh strok i tol'ko budushchie novye session rows."""
    required = set(PROXY_OUTPUT_COLUMNS)
    if required - set(existing.columns) or required - set(candidate.columns):
        raise ValueError("Append-only audit trebuet polnuyu skhemu spec-proxy")
    keys = ["session_date", "contract_id"]
    if existing.duplicated(keys).any() or candidate.duplicated(keys).any():
        raise ValueError("Append-only audit ne prinimaet duplicate contract/session")
    existing_normalized = _normalized_proxy_for_compare(existing)
    candidate_normalized = _normalized_proxy_for_compare(candidate)
    existing_keys = pd.MultiIndex.from_frame(existing_normalized[keys])
    candidate_keys = pd.MultiIndex.from_frame(candidate_normalized[keys])
    if not existing_keys.isin(candidate_keys).all():
        raise ValueError("Candidate udalil istoricheskuyu stroku spec-proxy")
    historical = candidate_normalized.set_index(keys).loc[existing_keys].reset_index()
    historical = historical.loc[:, PROXY_OUTPUT_COLUMNS]
    expected = existing_normalized.loc[:, PROXY_OUTPUT_COLUMNS]
    if not historical.equals(expected):
        raise ValueError("Candidate izmenil istoricheskuyu stroku spec-proxy")
    new_mask = ~candidate_keys.isin(existing_keys)
    if new_mask.any() and not existing_normalized.empty:
        last_existing = existing_normalized["session_date"].max()
        if (candidate_normalized.loc[new_mask, "session_date"] <= last_existing).any():
            raise ValueError("Novaya stroka ne yavlyaetsya append posle istorii")


def _normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet factual daily bez imputacii i zapreshchaet unknown asset/date."""
    rename = {
        source: target
        for source, target in INPUT_ALIASES.items()
        if source in daily and target not in daily
    }
    result = daily.rename(columns=rename).copy()
    if missing := INPUT_COLUMNS - set(result.columns):
        raise ValueError(f"Daily spec-proxy ne soderzhit kolonok: {sorted(missing)}")
    result = result.loc[:, sorted(INPUT_COLUMNS)].copy()
    result["session_date"] = _normalize_dates(result["session_date"])
    if (result["session_date"].dt.date >= PROTECTED_HOLDOUT_START).any():
        raise ValueError("Daily spec-proxy ne mozhet chitat' zashchishchennyi holdout")
    result["contract_id"] = result["contract_id"].astype("string")
    if result["contract_id"].isna().any() or result["contract_id"].eq("").any():
        raise ValueError("contract_id obyazatelen dlya spec-proxy")
    result["asset_symbol"] = [
        _normalize_asset_symbol(value) for value in result["asset_symbol"]
    ]
    for column in (
        "value",
        "volume",
        "waprice",
        "settle",
        "open_interest",
        "open_interest_value",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result.duplicated(["session_date", "contract_id"]).any():
        raise ValueError("Daily spec-proxy soderzhit duplicate contract/session")
    inconsistent = result.groupby("contract_id", observed=True)["asset_symbol"].nunique().gt(1)
    if inconsistent.any():
        raise ValueError("Odin contract_id svyazan s raznymi asset")
    return result.sort_values(
        ["contract_id", "session_date"],
        kind="mergesort",
    ).reset_index(drop=True)


def _normalize_session_calendar(values: Any) -> pd.DatetimeIndex:
    """Proveryaet unikal'nyi rastushchii factual calendar strogo do holdout."""
    calendar = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    if calendar.empty:
        raise ValueError("Factual session calendar pust")
    if calendar.tz is not None:
        calendar = calendar.tz_convert("Europe/Moscow").tz_localize(None)
    calendar = calendar.normalize()
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("Factual session calendar dolzhen byt' unikal'nym i rastushchim")
    if any(timestamp.date() >= PROTECTED_HOLDOUT_START for timestamp in calendar):
        raise ValueError("Factual session calendar zahodit v zashchishchennyi holdout")
    return calendar


def _normalize_dates(values: pd.Series) -> pd.Series:
    """Privodit daily daty k timezone-naive polunochi po Europe/Moscow."""
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    if parsed.isna().any():
        raise ValueError("Propusk session_date v spec-proxy")
    return parsed.dt.normalize()


def _normalize_one_date(value: object) -> pd.Timestamp:
    """Privodit odnu datu accessor-a k torgovoi date Europe/Moscow."""
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("Pustaya session_date")
    if parsed.tz is not None:
        parsed = parsed.tz_convert("Europe/Moscow").tz_localize(None)
    normalized = parsed.normalize()
    if normalized.date() >= PROTECTED_HOLDOUT_START:
        raise ValueError("Accessor ne mozhet chitat' zashchishchennyi holdout")
    return normalized


def _normalize_asset_symbol(value: object) -> str:
    """Privodit logical symbol ili ISS asset_code k SI/RI/BR/MIX."""
    if pd.isna(value):
        raise ValueError("Pustoi asset v futures spec-proxy")
    normalized = str(value).strip().upper()
    if normalized not in ASSET_ALIASES:
        raise ValueError(f"Neizvestnyi asset futures spec-proxy: {value!r}")
    return ASSET_ALIASES[normalized]


def _finite_positive_or_none(value: object) -> float | None:
    """Vozvrashchaet finite positive float ili None bez imputacii."""
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if np.isfinite(converted) and converted > 0.0 else None


def _positive_series(values: pd.Series) -> pd.Series:
    """Stroit mask finite positive dlya numeric pandas series."""
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.notna() & np.isfinite(numeric) & numeric.gt(0.0)


def _exact_bool(value: object, expected: bool) -> bool:
    """Proveryaet nastoyashchii bool i ne prinimaet stroki ili chisla."""
    return isinstance(value, (bool, np.bool_)) and bool(value) is expected


def _normalized_proxy_for_compare(proxy: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet proxy i stabiliziruet daty pered append-only sravneniem."""
    result = proxy.loc[:, PROXY_OUTPUT_COLUMNS].copy()
    result["session_date"] = _normalize_dates(result["session_date"])
    result["sizing_observed_session_date"] = pd.to_datetime(
        result["sizing_observed_session_date"],
        errors="coerce",
    ).dt.normalize()
    return result.sort_values(
        ["session_date", "contract_id"],
        kind="mergesort",
    ).reset_index(drop=True)
