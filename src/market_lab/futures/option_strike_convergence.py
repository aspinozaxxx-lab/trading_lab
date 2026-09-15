"""Pure pre-expiry strike target adapter; no I/O, HTTP, model or economic runner."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype

from market_lab import futures_v64_si_tax_calendar as base

OPTION_COLUMNS = {
    "tradedate",
    "logical_asset",
    "secid",
    "boardid",
    "available_at_utc",
    "openposition",
    "metadata_ready",
    "option_class",
    "first_trade_date",
    "last_trade_date",
    "expiry_date",
    "underlying_contract_id",
    "option_type",
    "strike",
    "unit",
    "lot_size",
    "exercise_style",
    "series_name",
    "quote_units_compatible",
}
CLOSE_COLUMNS = {"trade_date", "logical_asset", "canonical_contract_id", "close"}
ASSETS = ("BR", "MIX", "RI", "SI")
CLASSES = {"margined_future_option", "premium_currency_option", "other_nonfuture_option"}
ARMS = ("primary", "control")


def days(series, *, protected=True):
    result = pd.to_datetime(series)
    base.require(
        result.dt.tz is None and result.notna().all() and result.eq(result.dt.normalize()).all(),
        "invalid date-only column",
    )
    if protected:
        base.require(result.lt(base.BOUNDARY).all(), "protected 2026 date")
    return result


def flag(series):
    base.require(is_bool_dtype(series.dtype), "boolean flags required")
    return series.fillna(False).astype(bool)


def canonical_matches(asset, contract):
    """Structural check only; upstream sealed metadata must prove the actual identity."""
    if not isinstance(contract, str):
        return False
    parts = contract.split(":")
    if len(parts) != 3 or not parts[1]:
        return False
    aliases = {"BR": "BR", "MIX": "MIX", "RTS": "RI", "RI": "RI", "Si": "SI", "SI": "SI"}
    try:
        expiry = pd.Timestamp(parts[2])
    except (ValueError, TypeError):
        return False
    return (
        aliases.get(parts[0]) == asset
        and pd.notna(expiry)
        and expiry.tz is None
        and expiry == expiry.normalize()
        and parts[2] == expiry.strftime("%Y-%m-%d")
    )


def prepare_options(raw):
    base.require(set(raw.columns) == OPTION_COLUMNS, "option feature schema; no labels or prices")
    d = raw.copy()
    d["tradedate"] = days(d.tradedate)
    base.require(
        d.logical_asset.isin(ASSETS).all() and d.secid.notna().all() and d.boardid.notna().all(),
        "source identities",
    )
    base.require(
        not d.duplicated(["tradedate", "logical_asset", "boardid", "secid"]).any(),
        "duplicate option observation",
    )
    d["available_at_utc"] = pd.to_datetime(d.available_at_utc, utc=True)
    floor = (d.tradedate.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).dt.tz_convert(
        "UTC"
    )
    base.require(
        d.available_at_utc.notna().all() and d.available_at_utc.ge(floor).all(),
        "premature source availability",
    )
    keys = ["logical_asset", "tradedate"]
    base.require(d.groupby(keys).available_at_utc.nunique().eq(1).all(), "mixed release clocks")
    d["metadata_ready"] = flag(d.metadata_ready)
    d["quote_units_compatible"] = flag(d.quote_units_compatible)
    base.require(
        d.loc[d.metadata_ready, "option_class"].isin(CLASSES).all(),
        "unknown supposedly ready option class",
    )
    for column in ("first_trade_date", "last_trade_date", "expiry_date"):
        d[column] = pd.to_datetime(d[column], errors="coerce")
        base.require(d[column].dt.tz is None, "metadata date timezone")
        base.require(
            d[column].dropna().eq(d[column].dropna().dt.normalize()).all(),
            "metadata must have exact dates, not guessed times",
        )
    d["openposition"] = pd.to_numeric(d.openposition, errors="coerce").astype(float)
    d["strike"] = pd.to_numeric(d.strike, errors="coerce").astype(float)
    d["lot_size"] = pd.to_numeric(d.lot_size, errors="coerce").astype(float)
    d["oi_usable"] = np.isfinite(d.openposition) & d.openposition.ge(0)
    d["oi_unusable"] = ~d.oi_usable
    d["explicit_nonfuture"] = d.metadata_ready & d.option_class.isin(
        CLASSES - {"margined_future_option"}
    )
    named = d[["unit", "exercise_style", "series_name"]].notna().all(axis=1)
    named &= d[["unit", "exercise_style", "series_name"]].astype(str).ne("").all(axis=1)
    lifecycle = (
        d.first_trade_date.le(d.tradedate)
        & d.last_trade_date.ge(d.tradedate)
        & d.expiry_date.ge(d.last_trade_date)
    )
    mapping = pd.Series(
        [
            canonical_matches(a, c)
            for a, c in zip(d.logical_asset, d.underlying_contract_id, strict=True)
        ],
        index=d.index,
        dtype=bool,
    )
    underlying_expiry = pd.to_datetime(
        d.underlying_contract_id.astype("string").str.rsplit(":", n=1).str[-1],
        format="%Y-%m-%d",
        errors="coerce",
    )
    d["mapping_ok"] = (
        d.metadata_ready
        & d.option_class.eq("margined_future_option")
        & d.quote_units_compatible
        & mapping
        & d.expiry_date.le(underlying_expiry)
        & lifecycle
        & named
        & np.isfinite(d.strike)
        & d.strike.gt(0)
        & np.isfinite(d.lot_size)
        & d.lot_size.gt(0)
        & d.option_type.isin(["call", "put"])
    )
    releases = d.groupby(keys, as_index=False).agg(
        available_at_utc=("available_at_utc", "first"),
        source_rows=("secid", "size"),
        usable_oi_rows=("oi_usable", "sum"),
        unusable_oi_rows=("oi_unusable", "sum"),
        explicit_nonfuture_rows=("explicit_nonfuture", "sum"),
    )
    releases = releases.rename(columns={"logical_asset": "asset_code", "tradedate": "source_date"})
    return d, releases


def empty_choice():
    return {
        "ready": False,
        "reason": "NO_MAPPED_EXPIRY",
        "in_expiry_window": False,
        "primary_direction": np.nan,
        "control_direction": np.nan,
        "selected_expiry": pd.NaT,
        "lower_strike": np.nan,
        "upper_strike": np.nan,
        "lower_oi": np.nan,
        "upper_oi": np.nan,
        "pool_rows": 0,
        "reported_strikes": 0,
    }


def strike_choice(pool, price, decision_date, effective_date, settings):
    """Choose expiry before checking OI; no escape to a later, more convenient maturity."""
    result = empty_choice()
    relevant = pool.loc[pool.expiry_date.gt(decision_date)]
    if relevant.empty:
        return result
    expiry = relevant.expiry_date.min()
    result["selected_expiry"] = expiry
    if (expiry - decision_date).days > settings[
        "maximum_expiry_distance_from_decision_calendar_days"
    ]:
        result["reason"] = "OUTSIDE_EXPIRY_WINDOW"
        return result
    result["in_expiry_window"] = True
    if effective_date >= expiry:
        result["reason"] = "FILL_REACHES_EXPIRY"
        return result
    p = relevant.loc[relevant.expiry_date.eq(expiry)]
    result["pool_rows"] = len(p)
    if p.last_trade_date.lt(effective_date).any():
        result["reason"] = "OPTION_NO_LONGER_TRADABLE_AT_FILL"
        return result
    if len(p[["series_name", "unit", "lot_size", "exercise_style"]].drop_duplicates()) != 1:
        result["reason"] = "INCOMPATIBLE_SERIES"
        return result
    if p.duplicated(["strike", "option_type"]).any():
        result["reason"] = "DUPLICATE_STRIKE_SIDE"
        return result
    observed = p.loc[p.oi_usable]
    # No transform of unknown OI into zero. Totals refer only to this reported pool.
    totals = observed.groupby("strike").openposition.sum(min_count=1).sort_index()
    result["reported_strikes"] = len(totals)
    if not len(totals) or not np.isfinite(totals.to_numpy()).all() or not totals.gt(0).any():
        result["reason"] = "NO_POSITIVE_REPORTED_OI"
        return result
    if price in totals.index:
        result.update(
            ready=True, reason="EXACT_STRIKE_FLAT", primary_direction=0.0, control_direction=0.0
        )
        return result
    lower, upper = totals.loc[totals.index < price], totals.loc[totals.index > price]
    if lower.empty or upper.empty:
        result["reason"] = "UNBRACKETED_PRICE"
        return result
    low, high = float(lower.index[-1]), float(upper.index[0])
    lo, hi = float(lower.iloc[-1]), float(upper.iloc[0])
    if lo + hi <= 0:
        result["reason"] = "ZERO_BRACKET_OI"
        return result
    result.update(
        ready=True,
        reason="READY",
        lower_strike=low,
        upper_strike=high,
        lower_oi=lo,
        upper_oi=hi,
        primary_direction=float((hi > lo) - (hi < lo)),
        control_direction=float(np.sign((price - low) - (high - price))),
    )
    return result


def build_targets(active, options, closes, cfg):
    """Exact decision-close join; emits both arms for the unchanged daily portfolio ledger."""
    base.require(tuple(cfg["assets"]) == ASSETS, "fixed four-asset universe")
    base.require(set(active.columns) == set(base.ACTIVE_COLS), "active feature schema")
    base.require(set(closes.columns) == CLOSE_COLUMNS, "close feature schema; no future labels")
    d, releases = prepare_options(options)
    a = active.copy()
    a["effective_date"] = days(a.effective_date)
    a = a.loc[a.effective_date.between(cfg["period"]["start"], cfg["period"]["end"])].copy()
    for column in ("decision_date", "observed_through"):
        a[column] = days(a[column])
    base.require(
        a.decision_date.lt(a.effective_date).all() and a.observed_through.le(a.decision_date).all(),
        "future map or same-day fill",
    )
    base.require(
        a.asset_code.isin(ASSETS).all()
        and not a.duplicated(["effective_date", "asset_code"]).any(),
        "map identity",
    )
    base.require(
        not a.empty
        and a.groupby("effective_date").asset_code.nunique().eq(4).all()
        and a.groupby("effective_date").decision_date.nunique().eq(1).all(),
        "incomplete joint decision calendar",
    )
    a["plan_tradable"] = flag(a.plan_tradable)
    q = closes.copy()
    q["trade_date"] = days(q.trade_date)
    q["close"] = pd.to_numeric(q.close, errors="coerce").astype(float)
    base.require(
        q.logical_asset.isin(ASSETS).all()
        and not q.duplicated(["trade_date", "logical_asset", "canonical_contract_id"]).any(),
        "duplicate close identity",
    )
    a = a.merge(
        q.rename(
            columns={
                "trade_date": "decision_date",
                "logical_asset": "asset_code",
                "canonical_contract_id": "contract_id",
                "close": "decision_close",
            }
        ),
        on=["decision_date", "asset_code", "contract_id"],
        how="left",
        validate="many_to_one",
    )
    a["decision_at_utc"] = (
        a.decision_date.dt.tz_localize("Europe/Moscow")
        + pd.Timedelta(days=1)
        - pd.Timedelta(nanoseconds=1)
    ).dt.tz_convert("UTC")
    # An old delayed release must not replace a newer source date already available.
    releases = releases.sort_values(["asset_code", "available_at_utc", "source_date"])
    newest = releases.groupby("asset_code").source_date.cummax()
    releases = releases.loc[releases.source_date.eq(newest)]
    a = pd.merge_asof(
        a.sort_values(["decision_at_utc", "asset_code"]),
        releases.sort_values(["available_at_utc", "asset_code"]),
        by="asset_code",
        left_on="decision_at_utc",
        right_on="available_at_utc",
        direction="backward",
    )
    groups = {key: part for key, part in d.groupby(["logical_asset", "tradedate"])}
    states = []
    for row in a.itertuples(index=False):
        result = row._asdict()
        result.update(empty_choice())
        result.update(
            ready=False,
            in_expiry_window=False,
            reason="NO_SOURCE",
            primary_direction=np.nan,
            control_direction=np.nan,
            unresolved_reported_rows=0,
            feature_unavailable=True,
            source_unavailable=False,
            stale_at_fill=False,
        )
        if (
            not row.plan_tradable
            or not canonical_matches(row.asset_code, row.contract_id)
            or pd.Timestamp(row.contract_id.split(":")[-1]) < row.effective_date
        ):
            result.update(reason="INVALID_PLAN", source_unavailable=True)
        elif pd.isna(row.source_date):
            pass
        elif not row.source_date < row.decision_date:
            result["reason"] = "SOURCE_NOT_STRICTLY_PRIOR"
        elif (row.effective_date - row.source_date).days > cfg["signal"][
            "maximum_source_age_at_fill_calendar_days"
        ] or (row.effective_date - row.decision_date).days > cfg["signal"][
            "maximum_decision_to_fill_calendar_days"
        ]:
            result.update(reason="STALE_SOURCE_OR_FILL", stale_at_fill=True)
        elif not np.isfinite(row.decision_close) or row.decision_close <= 0:
            result["reason"] = "MISSING_DECISION_CLOSE"
        else:
            release = groups[(row.asset_code, row.source_date)]
            unresolved = release.oi_usable & ~(release.mapping_ok | release.explicit_nonfuture)
            result["unresolved_reported_rows"] = int(unresolved.sum())
            if unresolved.any():
                result["reason"] = "UNRESOLVED_REPORTED_METADATA"
            else:
                pool = release.loc[
                    release.mapping_ok & release.underlying_contract_id.eq(row.contract_id)
                ]
                result.update(
                    strike_choice(
                        pool,
                        row.decision_close,
                        row.decision_date,
                        row.effective_date,
                        cfg["signal"],
                    )
                )
        result["feature_unavailable"] = not result["ready"]
        states.append(result)
    state = pd.DataFrame(states).sort_values(["effective_date", "asset_code"], ignore_index=True)
    state["terminal_flat"] = (
        state.groupby("asset_code").effective_date.transform("max").eq(state.effective_date)
    )
    targets = {}
    for arm in ARMS:
        target = state.copy()
        target["requested_weight"] = (
            target[arm + "_direction"] * cfg["execution"]["weight_per_asset"]
        )
        target["target_weight"] = target.requested_weight.where(
            target.ready & ~target.terminal_flat, 0.0
        )
        target.loc[target.target_weight.eq(0), "contract_id"] = None
        target["provenance"] = cfg["protocol_id"] + "_" + arm
        base.require(
            np.isfinite(target.target_weight).all()
            and target.groupby("effective_date")
            .target_weight.apply(lambda x: x.abs().sum())
            .le(cfg["execution"]["maximum_signal_gross"] + 1e-12)
            .all(),
            "target/gross invalid",
        )
        targets[arm] = target
    return state, targets
