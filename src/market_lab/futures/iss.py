"""Parser spravochnika futures i chistye generatory URL oficial'nogo MOEX ISS."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

import pandas as pd

from market_lab.futures.specs import (
    FuturesAssetSpec,
    FuturesBoardSegment,
    canonical_board_segment_id,
    canonical_contract_id,
)

MOEX_ISS_BASE_URL = "https://iss.moex.com/iss"  # Bazovyi HTTPS-adres oficial'nogo ISS.
SERIES_BLOCK = "series"  # Imya bloka spravochnika serii futures.
BOARDS_BLOCK = "boards"  # Imya bloka rezhimov torgov instrumenta.
SERIES_REQUIRED_COLUMNS = frozenset(  # Minimal'naya proveriaemaya skhema series.
    {
        "secid",
        "name",
        "start_date",
        "expiration_date",
        "asset_code",
        "is_traded",
    }
)
BOARD_REQUIRED_COLUMNS = frozenset(  # Polya dlya datirovannogo razresheniya doski.
    {"secid", "boardid", "history_from", "history_till"}
)
DEFAULT_CANDLE_INTERVAL = 10  # Kod desyatiminutnoi svechi v ISS.
OUTRIGHT_SECID_PATTERN = re.compile(  # SECID odnoi postavki, ne calendar spread.
    r"^[A-Z]+[FGHJKMNQUVXZ]\d(?:_\d{4})?$",
    re.IGNORECASE,
)
SERIES_OUTPUT_COLUMNS = (  # Normalizovannaya skhema odinochnyh kontraktov.
    "canonical_contract_id",
    "secid",
    "name",
    "start_date",
    "expiration_date",
    "asset_code",
    "underlying_asset",
    "is_traded",
)
SERIES_EXCLUDED_COLUMNS = (  # Audit-skhema otbroshennyh spread i service strok.
    "secid",
    "name",
    "start_date",
    "expiration_date",
    "asset_code",
    "exclusion_reason",
)


@dataclass(frozen=True, slots=True)
class FuturesSeriesCatalog:
    """Hranit odinochnye kontrakty i yavnyi audit otbroshennyh strok ISS."""

    contracts: pd.DataFrame
    excluded: pd.DataFrame


def _parse_iss_block(
    payload: dict[str, Any],
    block_name: str,
    required_columns: frozenset[str],
) -> pd.DataFrame:
    """Prevrashchaet tablichnyi ISS-blok v DataFrame so strogoi skhemoi."""
    block = payload.get(block_name)
    if not isinstance(block, dict):
        raise ValueError(f"Otvet ISS ne soderzhit obekt {block_name}")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"Nekorrektnyi tablichnyi blok ISS: {block_name}")
    normalized_columns = [str(column).lower() for column in columns]
    if len(normalized_columns) != len(set(normalized_columns)):
        raise ValueError(f"Povtory kolonok v ISS-bloke {block_name}")
    missing = required_columns - set(normalized_columns)
    if missing:
        raise ValueError(f"V {block_name} net kolonok: {sorted(missing)}")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"Stroka {block_name} ne sootvetstvuet columns")
    return pd.DataFrame(rows, columns=normalized_columns)


def _normalize_date_column(frame: pd.DataFrame, column: str) -> pd.Series:
    """Normalizuet datu ISS bez podmeny nekorrektnyh znachenii."""
    parsed = pd.to_datetime(frame[column], errors="raise")
    if parsed.isna().any():
        raise ValueError(f"Propusk daty v kolonke {column}")
    return parsed.dt.normalize()


def _is_outright_secid(value: object) -> bool:
    """Otdelyaet odinochnyi futures-kontrakt ot spread i sluzhebnyh instrumentov."""
    return pd.notna(value) and OUTRIGHT_SECID_PATTERN.fullmatch(str(value)) is not None


def _series_exclusion_reason(row: pd.Series, asset: FuturesAssetSpec | None) -> str:
    """Obyasnyaet, pochemu stroka spravochnika ne yavlyaetsya odinochnym kontraktom."""
    if pd.isna(row["start_date"]) or pd.isna(row["expiration_date"]):
        return "missing_contract_dates"
    if not _is_outright_secid(row["secid"]):
        return "calendar_spread_or_service"
    if asset is not None and not str(row["secid"]).upper().startswith(
        str(asset.security_prefix).upper()
    ):
        return "unexpected_security_prefix"
    return "unsupported_series_row"


def parse_futures_series_catalog(
    payload: dict[str, Any],
    asset: FuturesAssetSpec | None = None,
) -> FuturesSeriesCatalog:
    """Normalizuet series JSON i vozvrashchaet contracts vmeste s auditom otseva."""
    frame = _parse_iss_block(payload, SERIES_BLOCK, SERIES_REQUIRED_COLUMNS)
    if frame.empty:
        return FuturesSeriesCatalog(
            pd.DataFrame(columns=SERIES_OUTPUT_COLUMNS),
            pd.DataFrame(columns=SERIES_EXCLUDED_COLUMNS),
        )
    frame["secid"] = frame["secid"].astype("string")
    frame["asset_code"] = frame["asset_code"].astype("string")
    frame["name"] = frame["name"].astype("string")
    if asset is not None:
        frame = frame.loc[frame["asset_code"] == asset.asset_code].copy()
    accepted = frame["secid"].map(_is_outright_secid)
    accepted &= frame["start_date"].notna() & frame["expiration_date"].notna()
    if asset is not None:
        accepted &= frame["secid"].str.upper().str.startswith(
            str(asset.security_prefix).upper()
        )
    excluded = frame.loc[~accepted].copy()
    if excluded.empty:
        excluded = pd.DataFrame(columns=SERIES_EXCLUDED_COLUMNS)
    else:
        excluded["exclusion_reason"] = excluded.apply(
            _series_exclusion_reason,
            axis=1,
            asset=asset,
        )
        excluded = excluded[list(SERIES_EXCLUDED_COLUMNS)].reset_index(drop=True)
    frame = frame.loc[accepted].copy()
    if frame.empty:
        return FuturesSeriesCatalog(
            pd.DataFrame(columns=SERIES_OUTPUT_COLUMNS),
            excluded,
        )
    if frame[["secid", "asset_code", "name"]].isna().any().any():
        raise ValueError("Series soderzhit pustoi SECID, asset_code ili name")
    frame["start_date"] = _normalize_date_column(frame, "start_date")
    frame["expiration_date"] = _normalize_date_column(frame, "expiration_date")
    if (frame["expiration_date"] < frame["start_date"]).any():
        raise ValueError("Series soderzhit expiraciyu ran'she start_date")
    traded = pd.to_numeric(frame["is_traded"], errors="raise")
    if not traded.isin((0, 1)).all():
        raise ValueError("is_traded dolzhen byt' 0 ili 1")
    frame["is_traded"] = traded.astype(bool)
    if "underlying_asset" not in frame:
        frame["underlying_asset"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    else:
        frame["underlying_asset"] = frame["underlying_asset"].astype("string")
    frame["canonical_contract_id"] = [
        canonical_contract_id(asset_code, secid, expiration.date())
        for asset_code, secid, expiration in zip(
            frame["asset_code"],
            frame["secid"],
            frame["expiration_date"],
            strict=True,
        )
    ]
    frame = frame.drop_duplicates()
    duplicate_alias = frame.duplicated(
        ["canonical_contract_id", "secid"], keep=False
    )
    if duplicate_alias.any():
        raise ValueError("Protivorechivye stroki odnogo futures-aliasa")
    contracts = (
        frame[list(SERIES_OUTPUT_COLUMNS)]
        .sort_values(["expiration_date", "start_date", "secid"])
        .reset_index(drop=True)
    )
    return FuturesSeriesCatalog(contracts=contracts, excluded=excluded)


def parse_futures_series_payload(
    payload: dict[str, Any],
    asset: FuturesAssetSpec | None = None,
) -> pd.DataFrame:
    """Vozvrashchaet tol'ko odinochnye kontrakty dlya sovmestimogo API."""
    return parse_futures_series_catalog(payload, asset).contracts


def parse_futures_boards_payload(
    payload: dict[str, Any],
    preferred_board: str | None = None,
) -> pd.DataFrame:
    """Normalizuet datirovannye boards i otbrasyvaet undated service metadata."""
    frame = _parse_iss_block(payload, BOARDS_BLOCK, BOARD_REQUIRED_COLUMNS)
    output_columns = [
        "secid",
        "boardid",
        "history_from",
        "history_till",
        "listed_from",
        "listed_till",
        "is_primary",
        "is_traded",
        "engine",
        "market",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    for column in ("secid", "boardid"):
        frame[column] = frame[column].astype("string")
    if preferred_board is not None:
        frame = frame.loc[frame["boardid"] == preferred_board].copy()
    undated = frame[["history_from", "history_till"]].isna().any(axis=1)
    excluded_undated_count = int(undated.sum())
    frame = frame.loc[~undated].copy()
    if frame.empty:
        output = pd.DataFrame(columns=output_columns)
        output.attrs["excluded_undated_count"] = excluded_undated_count
        return output
    for column in ("history_from", "history_till"):
        frame[column] = _normalize_date_column(frame, column)
    for column, fallback in (
        ("listed_from", "history_from"),
        ("listed_till", "history_till"),
    ):
        if column not in frame:
            frame[column] = frame[fallback]
        else:
            parsed = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
            frame[column] = parsed.fillna(frame[fallback])
    for column in ("is_primary", "is_traded"):
        if column not in frame:
            frame[column] = False
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(bool)
    for column in ("engine", "market"):
        if column not in frame:
            frame[column] = pd.Series(pd.NA, index=frame.index, dtype="string")
        else:
            frame[column] = frame[column].astype("string")
    if (frame["history_till"] < frame["history_from"]).any():
        raise ValueError("Boards soderzhit history_till ran'she history_from")
    output = frame[output_columns].sort_values(
        ["secid", "history_from", "boardid"]
    ).reset_index(
        drop=True,
    )
    output.attrs["excluded_undated_count"] = excluded_undated_count
    return output


def resolve_canonical_board_segments(
    contracts: pd.DataFrame,
    boards: pd.DataFrame,
    preferred_board: str | None = "RFUD",
    require_all: bool = True,
) -> pd.DataFrame:
    """Vyberaet po odnomu peresekayushchemusya board-segmentu na kazhdyi kontrakt."""
    required_contracts = {
        "canonical_contract_id",
        "secid",
        "start_date",
        "expiration_date",
    }
    required_boards = {"secid", "boardid", "history_from", "history_till"}
    if missing := required_contracts - set(contracts.columns):
        raise ValueError(f"V contracts net kolonok: {sorted(missing)}")
    if missing := required_boards - set(boards.columns):
        raise ValueError(f"V boards net kolonok: {sorted(missing)}")
    resolved: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for contract in contracts.to_dict("records"):
        candidates = boards.loc[boards["secid"] == contract["secid"]].copy()
        overlap = (candidates["history_from"] <= contract["expiration_date"]) & (
            candidates["history_till"] >= contract["start_date"]
        )
        candidates = candidates.loc[overlap]
        if candidates.empty:
            unresolved.append(str(contract["canonical_contract_id"]))
            continue
        preferred = (
            candidates["boardid"] == preferred_board
            if preferred_board is not None
            else pd.Series(False, index=candidates.index)
        )
        if preferred.any():
            candidates = candidates.loc[preferred]
        elif "is_primary" in candidates and candidates["is_primary"].any():
            candidates = candidates.loc[candidates["is_primary"]]
        elif "is_traded" in candidates and candidates["is_traded"].any():
            candidates = candidates.loc[candidates["is_traded"]]
        for board in candidates.sort_values(["history_from", "boardid"]).to_dict("records"):
            segment_start = board["history_from"]
            segment_end = board["history_till"]
            segment_id = canonical_board_segment_id(
                str(contract["canonical_contract_id"]),
                str(board["boardid"]),
                segment_start.date(),
                segment_end.date(),
            )
            resolved.append(
                {
                    "canonical_segment_id": segment_id,
                    "canonical_contract_id": contract["canonical_contract_id"],
                    "secid": contract["secid"],
                    "boardid": board["boardid"],
                    "segment_start": segment_start,
                    "segment_end": segment_end,
                }
            )
    if unresolved and require_all:
        raise ValueError(f"Net board-segmentov dlya kontraktov: {unresolved}")
    output = pd.DataFrame(
        resolved,
        columns=[
            "canonical_segment_id",
            "canonical_contract_id",
            "secid",
            "boardid",
            "segment_start",
            "segment_end",
        ],
    ).sort_values(["segment_start", "canonical_contract_id"], ignore_index=True)
    if output["canonical_segment_id"].duplicated().any():
        raise ValueError("Povtor canonical board-segmenta")
    for _, group in output.groupby(["canonical_contract_id", "boardid"], sort=False):
        ordered = group.sort_values("segment_start")
        previous_end = ordered["segment_end"].shift(1)
        if (ordered["segment_start"] <= previous_end).fillna(False).any():
            raise ValueError("Peresekayushchiesya storage-segmenty odnogo kontrakta")
    return output


def resolve_contract_segment(
    segments: pd.DataFrame,
    secid: str,
    trading_date: date,
    board_id: str | None = None,
) -> FuturesBoardSegment:
    """Odnoznachno razreshaet povtornyi arhivnyi SECID cherez datu i board."""
    timestamp = pd.Timestamp(trading_date)
    mask = (segments["secid"] == secid) & (segments["segment_start"] <= timestamp) & (
        segments["segment_end"] >= timestamp
    )
    if board_id is not None:
        mask &= segments["boardid"] == board_id
    matched = segments.loc[mask]
    if len(matched) != 1:
        raise ValueError(
            f"Ozhidalsya odin segment {secid} na {trading_date}, polucheno {len(matched)}"
        )
    row = matched.iloc[0]
    return FuturesBoardSegment(
        canonical_contract_id=str(row["canonical_contract_id"]),
        secid=str(row["secid"]),
        board_id=str(row["boardid"]),
        segment_start=row["segment_start"].date(),
        segment_end=row["segment_end"].date(),
    )


def resolve_canonical_contract_segment(
    segments: pd.DataFrame,
    contract_id: str,
    trading_date: date,
    board_id: str | None = None,
) -> FuturesBoardSegment:
    """Razreshaet fakticheskii SECID kanonicheskoi postavki na ukazannuyu datu."""
    timestamp = pd.Timestamp(trading_date)
    mask = (segments["canonical_contract_id"] == contract_id) & (
        segments["segment_start"] <= timestamp
    ) & (segments["segment_end"] >= timestamp)
    if board_id is not None:
        mask &= segments["boardid"] == board_id
    matched = segments.loc[mask]
    if len(matched) != 1:
        raise ValueError(
            f"Ozhidalsya odin segment {contract_id} na {trading_date}, "
            f"polucheno {len(matched)}"
        )
    row = matched.iloc[0]
    return FuturesBoardSegment(
        canonical_contract_id=str(row["canonical_contract_id"]),
        secid=str(row["secid"]),
        board_id=str(row["boardid"]),
        segment_start=row["segment_start"].date(),
        segment_end=row["segment_end"].date(),
    )


def _dated_query(date_start: date | None, date_end: date | None, **values: Any) -> str:
    """Kodiruet obshchie ISS-parametry v stabil'nom poryadke."""
    parameters: list[tuple[str, Any]] = [("iss.meta", "off")]
    parameters.extend((key, value) for key, value in values.items() if value is not None)
    if date_start is not None:
        parameters.append(("from", date_start.isoformat()))
    if date_end is not None:
        parameters.append(("till", date_end.isoformat()))
    return urlencode(parameters)


def _validate_cursor_start(cursor_start: int) -> None:
    """Proveryaet neotricatel'noe smeshchenie stranicy ISS."""
    if cursor_start < 0:
        raise ValueError("cursor_start dolzhen byt' >= 0")


def futures_series_url(asset: FuturesAssetSpec) -> str:
    """Formiruet official'nyi URL spravochnika serii futures."""
    query = _dated_query(
        None,
        None,
        asset_code=asset.asset_code,
        show_expired=1,
        **{"iss.only": SERIES_BLOCK},
    )
    return (
        f"{MOEX_ISS_BASE_URL}/statistics/engines/{quote(asset.engine, safe='')}/markets/"
        f"{quote(asset.market, safe='')}/series.json?{query}"
    )


def futures_boards_url(secid: str) -> str:
    """Formiruet URL datirovannyh board-segmentov odnogo storage SECID."""
    if not secid:
        raise ValueError("secid obyazatelen")
    query = _dated_query(None, None, **{"iss.only": BOARDS_BLOCK})
    return f"{MOEX_ISS_BASE_URL}/securities/{quote(secid, safe='')}.json?{query}"


def futures_candles_url(
    asset: FuturesAssetSpec,
    secid: str,
    start: date | None = None,
    end: date | None = None,
    interval: int = DEFAULT_CANDLE_INTERVAL,
    board_id: str | None = None,
    cursor_start: int = 0,
) -> str:
    """Formiruet board-aware URL svechei odnogo kanonicheskogo kontrakta."""
    if interval <= 0:
        raise ValueError("interval dolzhen byt' polozhitel'nym")
    _validate_cursor_start(cursor_start)
    board_path = (
        f"/boards/{quote(board_id, safe='')}" if board_id is not None else ""
    )
    query = _dated_query(
        start,
        end,
        interval=interval,
        start=cursor_start,
        **{"iss.only": "candles"},
    )
    return (
        f"{MOEX_ISS_BASE_URL}/engines/{quote(asset.engine, safe='')}/markets/"
        f"{quote(asset.market, safe='')}{board_path}/securities/"
        f"{quote(secid, safe='')}/candles.json?{query}"
    )


def futures_daily_url(
    asset: FuturesAssetSpec,
    secid: str,
    start: date | None = None,
    end: date | None = None,
    board_id: str | None = None,
    cursor_start: int = 0,
) -> str:
    """Formiruet URL dnevnoi istorii s volume, OI i settlement kontrakta."""
    _validate_cursor_start(cursor_start)
    board = board_id or asset.primary_board
    query = _dated_query(start, end, start=cursor_start)
    return (
        f"{MOEX_ISS_BASE_URL}/history/engines/{quote(asset.engine, safe='')}/markets/"
        f"{quote(asset.market, safe='')}/boards/{quote(board, safe='')}/securities/"
        f"{quote(secid, safe='')}.json?{query}"
    )


def futures_open_interest_url(
    asset: FuturesAssetSpec,
    start: date | None = None,
    end: date | None = None,
) -> str:
    """Formiruet datirovannyi OI URL bez ignoriruemogo serverom cursor."""
    query = _dated_query(
        start,
        end,
        **{"iss.only": "open_positions"},
    )
    return (
        f"{MOEX_ISS_BASE_URL}/statistics/engines/{quote(asset.engine, safe='')}/markets/"
        f"{quote(asset.market, safe='')}/openpositions/"
        f"{quote(asset.asset_code, safe='')}.json?{query}"
    )
