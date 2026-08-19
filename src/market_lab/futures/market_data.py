"""Strogie parsery svechei, dnevnoi istorii i participant OI futures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from market_lab.futures.iss import _parse_iss_block
from market_lab.futures.specs import FuturesAssetSpec

CANDLES_REQUIRED_COLUMNS = frozenset(  # Minimal'naya skhema 10m svechei ISS.
    {"open", "close", "high", "low", "value", "volume", "begin", "end"}
)
DAILY_REQUIRED_COLUMNS = frozenset(  # Polya dlya cen, OI, oborota i sdelok za den'.
    {
        "boardid",
        "tradedate",
        "secid",
        "open",
        "low",
        "high",
        "close",
        "value",
        "volume",
        "openposition",
        "openpositionvalue",
        "settleprice",
        "waprice",
        "numtrades",
        "assetcode",
    }
)
PARTICIPANT_OI_REQUIRED_COLUMNS = frozenset(  # Asset-level OI fizicheskih i yuridicheskih lic.
    {
        "tradedate",
        "asset",
        "is_fiz",
        "persons_long",
        "persons_short",
        "open_position_long",
        "open_position_short",
        "oichange_long",
        "oichange_short",
    }
)
DAILY_NONNEGATIVE_COLUMNS = (  # Dnevnye polya, gde otricatel'noe znachenie nedopustimo.
    "value",
    "volume",
    "openposition",
    "openpositionvalue",
    "numtrades",
)
DAILY_OHLC_COLUMNS = (  # Edinyi poryadok cen dlya audita polnoty dnevnoi stroki.
    "open",
    "high",
    "low",
    "close",
)
PARTICIPANT_NONNEGATIVE_COLUMNS = (  # Schetchiki uchastnikov i otkrytyh pozicii.
    "persons_long",
    "persons_short",
    "open_position_long",
    "open_position_short",
)


@dataclass(frozen=True, slots=True)
class IssPageCursor:
    """Opisyvaet tekushchuyu stranicu paginated ISS history."""

    index: int
    total: int
    page_size: int

    @property
    def next_index(self) -> int | None:
        """Vozvrashchaet sleduyushchee smeshchenie ili None posle poslednei stranicy."""
        candidate = self.index + self.page_size
        return candidate if candidate < self.total else None


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    """Preobrazuet ukazannye kolonki v chisla bez tikhogo sokhraneniya strok."""
    for column in columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def _utc_timestamp(series: pd.Series, timezone: str) -> pd.Series:
    """Prevrashchaet naivnoe birzhevoe vremya ISS v vozrastayushchii UTC timestamp."""
    parsed = pd.to_datetime(series, errors="raise")
    if parsed.isna().any():
        raise ValueError("Propusk vremeni v svechah futures")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    return parsed.dt.tz_convert("UTC")


def _validate_ohlc(frame: pd.DataFrame, mask: pd.Series | None = None) -> None:
    """Proveryaet polozhitel'nye OHLC i invariant low <= open/close <= high."""
    selected = frame if mask is None else frame.loc[mask]
    if selected.empty:
        return
    prices = selected[["open", "high", "low", "close"]]
    if prices.isna().any().any() or (~np.isfinite(prices.to_numpy(dtype=float))).any():
        raise ValueError("Torgovaya stroka soderzhit propusk ili beskonechnost' OHLC")
    if (prices <= 0.0).any().any():
        raise ValueError("OHLC futures dolzhny byt' polozhitel'nymi")
    invalid = (selected["high"] < selected[["open", "close"]].max(axis=1)) | (
        selected["low"] > selected[["open", "close"]].min(axis=1)
    ) | (selected["high"] < selected["low"])
    if invalid.any():
        raise ValueError("Narushen OHLC-invariant futures")


def parse_iss_page_cursor(payload: dict[str, Any], block_name: str) -> IssPageCursor:
    """Chitaet INDEX/TOTAL/PAGESIZE i zapreshchaet nepolnyi cursor history."""
    cursor_name = f"{block_name}.cursor"
    cursor = _parse_iss_block(
        payload,
        cursor_name,
        frozenset({"index", "total", "pagesize"}),
    )
    if len(cursor) != 1:
        raise ValueError(f"Ozhidalas' odna stroka cursor {cursor_name}")
    values = cursor.iloc[0]
    index = int(values["index"])
    total = int(values["total"])
    page_size = int(values["pagesize"])
    if index < 0 or total < 0 or page_size <= 0 or index > total:
        raise ValueError(f"Nekorrektnyi cursor {cursor_name}")
    return IssPageCursor(index=index, total=total, page_size=page_size)


def parse_futures_candles_payload(
    payload: dict[str, Any],
    asset: FuturesAssetSpec,
    secid: str,
) -> pd.DataFrame:
    """Normalizuet odnu stranicu 10m OHLCV, ne pridumyvaya number of trades."""
    frame = _parse_iss_block(payload, "candles", CANDLES_REQUIRED_COLUMNS)
    output_columns = [
        "timestamp",
        "end_timestamp",
        "secid",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "value",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    _numeric(frame, ("open", "high", "low", "close", "volume", "value"))
    _validate_ohlc(frame)
    if frame[["volume", "value"]].isna().any().any():
        raise ValueError("Propusk volume/value v futures candles")
    if (frame[["volume", "value"]] < 0.0).any().any():
        raise ValueError("Otricatel'nyi volume/value v futures candles")
    frame["timestamp"] = _utc_timestamp(frame["begin"], asset.timezone)
    frame["end_timestamp"] = _utc_timestamp(frame["end"], asset.timezone)
    if (frame["end_timestamp"] <= frame["timestamp"]).any():
        raise ValueError("Konec futures-svechi ne pozhe nachala")
    if frame["timestamp"].duplicated().any():
        raise ValueError("Povtor timestamp futures-svechi")
    frame["secid"] = secid
    return frame[output_columns].sort_values("timestamp", ignore_index=True)


def parse_futures_daily_payload(
    payload: dict[str, Any],
    asset: FuturesAssetSpec,
    expected_secid: str | None = None,
) -> tuple[pd.DataFrame, IssPageCursor]:
    """Normalizuet daily history i sohranyaet netorgovye settlement-only stroki."""
    frame = _parse_iss_block(payload, "history", DAILY_REQUIRED_COLUMNS)
    cursor = parse_iss_page_cursor(payload, "history")
    output_columns = [
        "trade_date",
        "board_id",
        "secid",
        "asset_code",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "waprice",
        "volume",
        "value",
        "num_trades",
        "open_interest",
        "open_interest_value",
        "reported_trade_activity",
        "ohlc_complete",
        "ohlc_missing_with_activity",
        "has_trade",
        "has_settlement",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns), cursor
    frame["trade_date"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    frame["board_id"] = frame["boardid"].astype("string")
    frame["secid"] = frame["secid"].astype("string")
    frame["asset_code"] = frame["assetcode"].astype("string").fillna(asset.asset_code)
    nonmatching_asset = frame["asset_code"] != asset.asset_code
    if nonmatching_asset.any():
        raise ValueError("Daily history soderzhit drugoi asset_code")
    if expected_secid is not None and (frame["secid"] != expected_secid).any():
        raise ValueError("Daily history soderzhit drugoi SECID")
    _numeric(
        frame,
        (
            "open",
            "high",
            "low",
            "close",
            "settleprice",
            "waprice",
            "volume",
            "value",
            "numtrades",
            "openposition",
            "openpositionvalue",
        ),
    )
    for column in DAILY_NONNEGATIVE_COLUMNS:
        if (frame[column].dropna() < 0.0).any():
            raise ValueError(f"Otricatel'noe dnevnoe pole futures: {column}")
    known_waprice = frame["waprice"].dropna()
    if (~np.isfinite(known_waprice)).any() or (known_waprice < 0.0).any():
        raise ValueError("Factual WAPRICE futures dolzhen byt' finite nonnegative")
    frame["reported_trade_activity"] = (
        (frame["numtrades"].fillna(0.0) > 0.0)
        | (frame["volume"].fillna(0.0) > 0.0)
        | (frame["value"].fillna(0.0) > 0.0)
    )
    ohlc = frame[list(DAILY_OHLC_COLUMNS)]
    frame["ohlc_complete"] = ohlc.notna().all(axis=1) & np.isfinite(
        ohlc.fillna(0.0).to_numpy(dtype=float)
    ).all(axis=1)
    frame["ohlc_missing_with_activity"] = (
        frame["reported_trade_activity"] & ~frame["ohlc_complete"]
    )
    frame["has_trade"] = frame["reported_trade_activity"] & frame["ohlc_complete"]
    frame["has_settlement"] = (
        frame["settleprice"].notna()
        & np.isfinite(frame["settleprice"])
        & (frame["settleprice"] > 0.0)
    )
    _validate_ohlc(frame, frame["ohlc_complete"])
    if (
        ~frame["reported_trade_activity"]
        & ~frame["has_settlement"]
        & ~frame["ohlc_complete"]
    ).any():
        raise ValueError("Daily stroka ne soderzhit ni aktivnosti, ni ceny, ni settlement")
    if frame.duplicated(["trade_date", "secid", "board_id"]).any():
        raise ValueError("Povtor dnevnoi stroki futures")
    frame = frame.rename(
        columns={
            "settleprice": "settle",
            "numtrades": "num_trades",
            "openposition": "open_interest",
            "openpositionvalue": "open_interest_value",
        }
    )
    return frame[output_columns].sort_values("trade_date", ignore_index=True), cursor


def parse_futures_participant_oi_payload(
    payload: dict[str, Any],
    asset: FuturesAssetSpec,
) -> pd.DataFrame:
    """Normalizuet asset-level participant OI, kotoryi nel'zya podmenyat' contract OI."""
    frame = _parse_iss_block(
        payload,
        "open_positions",
        PARTICIPANT_OI_REQUIRED_COLUMNS,
    )
    output_columns = [
        "trade_date",
        "asset_code",
        "is_physical",
        "persons_long",
        "persons_short",
        "open_position_long",
        "open_position_short",
        "oi_change_long",
        "oi_change_short",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    frame["trade_date"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    frame["asset_code"] = frame["asset"].astype("string")
    if (frame["asset_code"] != asset.asset_code).any():
        raise ValueError("Participant OI soderzhit drugoi asset_code")
    is_fiz = pd.to_numeric(frame["is_fiz"], errors="raise")
    if not is_fiz.isin((0, 1)).all():
        raise ValueError("is_fiz dolzhen byt' 0 ili 1")
    frame["is_physical"] = is_fiz.astype(bool)
    numeric_columns = PARTICIPANT_NONNEGATIVE_COLUMNS + (
        "oichange_long",
        "oichange_short",
    )
    _numeric(frame, numeric_columns)
    if frame[list(numeric_columns)].isna().any().any():
        raise ValueError("Propusk v participant OI")
    for column in PARTICIPANT_NONNEGATIVE_COLUMNS:
        if (frame[column] < 0.0).any():
            raise ValueError(f"Otricatel'nyi participant OI: {column}")
    if frame.duplicated(["trade_date", "asset_code", "is_physical"]).any():
        raise ValueError("Povtor kategorii participant OI")
    frame = frame.rename(
        columns={
            "oichange_long": "oi_change_long",
            "oichange_short": "oi_change_short",
        }
    )
    return frame[output_columns].sort_values(
        ["trade_date", "is_physical"], ignore_index=True
    )
