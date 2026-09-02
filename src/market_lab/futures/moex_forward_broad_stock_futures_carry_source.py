"""Collect sealed broad stock-futures carry quote pairs without computing basis."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_forward_cross_market_bbo_source as cross
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_broad_stock_futures_carry_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "5cd396e0033f26d161227dfbbdaef8812769d852dd3940d9e8f5bf8c8faabf70"
)
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-broad-stock-futures-carry-v1"
)
SPOT_SECURITY_COLUMNS: Final[tuple[str, ...]] = (
    "SECID",
    "BOARDID",
    "LOTSIZE",
    "MINSTEP",
)
FUTURES_SECURITY_COLUMNS: Final[tuple[str, ...]] = (
    "SECID",
    "BOARDID",
    "SECTYPE",
    "ASSETCODE",
    "LOTVOLUME",
    "MINSTEP",
    "LASTTRADEDATE",
    "LASTDELDATE",
    "INITIALMARGIN",
    "STEPPRICE",
)
MARKET_COLUMNS: Final[tuple[str, ...]] = (
    "SECID",
    "BOARDID",
    "BID",
    "OFFER",
    "BIDDEPTH",
    "OFFERDEPTH",
    "BIDDEPTHT",
    "OFFERDEPTHT",
    "NUMBIDS",
    "NUMOFFERS",
    "VOLTODAY",
    "VALTODAY",
    "OPENPOSITION",
    "UPDATETIME",
    "SEQNUM",
    "SYSTIME",
)
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "scheduled_slot_moscow",
    "stock_secid",
    "futures_asset_code",
    "futures_secid",
    "futures_expiration",
    "days_to_expiration",
    "spot_lot_size_shares",
    "futures_lot_volume_shares",
    "spot_lots_per_futures_contract",
    "spot_minimum_step",
    "futures_minimum_step",
    "futures_security_type_code",
    "futures_last_trade_date",
    "futures_last_delivery_date",
    "futures_initial_margin",
    "futures_step_price",
    "spot_bid",
    "spot_offer",
    "spot_bid_depth_lots",
    "spot_offer_depth_lots",
    "spot_total_bid_depth_lots",
    "spot_total_offer_depth_lots",
    "spot_number_of_bids",
    "spot_number_of_offers",
    "spot_volume_today",
    "spot_value_today",
    "futures_bid",
    "futures_offer",
    "futures_bid_depth_contracts",
    "futures_offer_depth_contracts",
    "futures_total_bid_depth_contracts",
    "futures_total_offer_depth_contracts",
    "futures_number_of_bids",
    "futures_number_of_offers",
    "futures_volume_today",
    "futures_value_today",
    "futures_open_position",
    "spot_exchange_systime",
    "spot_exchange_updatetime",
    "spot_exchange_seqnum",
    "futures_exchange_systime",
    "futures_exchange_updatetime",
    "futures_exchange_seqnum",
    "retrieved_at_utc",
    "access_mode",
    "valid",
    "invalid_reason",
)


class JsonClient(Protocol):
    def get_json(self, url: str) -> dict[str, Any]: ...


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("broad carry source protocol must be an object")
    universe = payload["universe"]
    stocks = tuple(universe["exact_stock_order"])
    mapping = universe["quarterly_futures_asset_code_by_stock"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "moex_forward_broad_stock_futures_carry_source_v1"
        or payload.get("live_trading_allowed") is not False
        or len(stocks) != 30
        or set(stocks) != set(mapping)
        or payload["universe"]["spot_board"] != cross.EQUITY_BOARD
        or payload["universe"]["futures_board"] != cross.FUTURES_BOARD
        or int(payload["collection"]["HTTP_requests_per_snapshot"]) != 3
        or payload["collection"]["atomic_immutable_snapshot_directory"] is not True
    ):
        raise ValueError("broad carry source protocol drifted")
    return payload


def _safe_output_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe broad carry output root: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "forward"):
        raise ValueError("broad carry output must be under data/forward")
    return PROJECT_ROOT / relative


def _series_url(config: dict[str, Any]) -> str:
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "series",
            "series.columns": (
                "secid,name,start_date,expiration_date,asset_code,"
                "underlying_asset,is_traded"
            ),
        }
    )
    return f"{config['official_sources']['futures_series']}?{query}"


def _venue_url(
    endpoint: str,
    secids: list[str],
    security_columns: tuple[str, ...],
) -> str:
    if not secids or len(secids) != len(set(secids)):
        raise ValueError("broad carry filtered request has empty or duplicate SECIDs")
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities": ",".join(secids),
            "securities.columns": ",".join(security_columns),
            "marketdata.columns": ",".join(MARKET_COLUMNS),
        }
    )
    return f"{endpoint}?{query}"


def select_contracts(
    payload: dict[str, Any], source_date: date, config: dict[str, Any]
) -> dict[str, tuple[str, str, date] | None]:
    series = iss._parse_iss_block(
        payload,
        "series",
        frozenset(
            {
                "secid",
                "start_date",
                "expiration_date",
                "asset_code",
                "underlying_asset",
                "is_traded",
            }
        ),
    )
    series["start_date"] = pd.to_datetime(series["start_date"], errors="raise")
    series["expiration_date"] = pd.to_datetime(
        series["expiration_date"], errors="raise"
    )
    traded = pd.to_numeric(series["is_traded"], errors="coerce").eq(1)
    minimum = int(config["contract_selection"]["minimum_calendar_days_to_expiry"])
    maximum = int(config["contract_selection"]["maximum_calendar_days_to_expiry"])
    mapping = config["universe"]["quarterly_futures_asset_code_by_stock"]
    selected: dict[str, tuple[str, str, date] | None] = {}
    for stock in config["universe"]["exact_stock_order"]:
        asset_code = str(mapping[stock])
        days = (series["expiration_date"] - pd.Timestamp(source_date)).dt.days
        rows = series.loc[
            traded
            & series["underlying_asset"].astype(str).eq(str(stock))
            & series["asset_code"].astype(str).eq(asset_code)
            & series["start_date"].le(pd.Timestamp(source_date))
            & days.between(minimum, maximum)
        ].sort_values(["expiration_date", "secid"])
        if rows.empty:
            selected[str(stock)] = None
        else:
            row = rows.iloc[0]
            selected[str(stock)] = (
                asset_code,
                str(row["secid"]),
                pd.Timestamp(row["expiration_date"]).date(),
            )
    return selected


def _blocks(
    payload: dict[str, Any], required_security_columns: frozenset[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    securities = iss._parse_iss_block(
        payload, "securities", required_security_columns
    )
    market = iss._parse_iss_block(
        payload,
        "marketdata",
        frozenset({"secid", "boardid", "bid", "offer", "biddepth", "offerdepth"}),
    )
    return securities, market


def _only_row(
    frame: pd.DataFrame, secid: str, board: str
) -> tuple[dict[str, Any], str | None]:
    rows = frame.loc[
        frame["secid"].astype(str).eq(secid)
        & frame["boardid"].astype(str).eq(board)
    ]
    if len(rows) != 1:
        return {}, "identity_missing_or_duplicate"
    return rows.iloc[0].to_dict(), None


def _positive_integer(value: Any) -> int | None:
    number = cross._number(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _clock_exists(values: dict[str, Any]) -> bool:
    return any(
        values.get(name) not in (None, "") and pd.notna(values.get(name))
        for name in ("systime", "updatetime", "seqnum")
    )


def _quote_values(
    values: dict[str, Any], prefix: str, invalid: list[str]
) -> dict[str, Any]:
    bid = cross._number(values.get("bid"))
    offer = cross._number(values.get("offer"))
    bid_depth = cross._number(values.get("biddepth"))
    offer_depth = cross._number(values.get("offerdepth"))
    if bid is None or offer is None or bid <= 0 or offer <= 0:
        invalid.append(f"{prefix}_positive_two_sided_quote_missing")
    elif offer <= bid:
        invalid.append(f"{prefix}_crossed_or_locked_quote")
    if bid_depth is None or offer_depth is None or bid_depth <= 0 or offer_depth <= 0:
        invalid.append(f"{prefix}_positive_best_depth_missing")
    if not _clock_exists(values):
        invalid.append(f"{prefix}_exchange_clock_missing")
    return {
        "bid": bid if bid is not None else pd.NA,
        "offer": offer if offer is not None else pd.NA,
        "bid_depth": bid_depth if bid_depth is not None else pd.NA,
        "offer_depth": offer_depth if offer_depth is not None else pd.NA,
        "total_bid_depth": cross._optional(values.get("biddeptht")),
        "total_offer_depth": cross._optional(values.get("offerdeptht")),
        "number_of_bids": cross._optional(values.get("numbids")),
        "number_of_offers": cross._optional(values.get("numoffers")),
        "volume": cross._optional(values.get("voltaday")),
        "value": cross._optional(values.get("valtoday")),
    }


def _sleep_row(
    stock: str,
    *,
    source_date: date,
    slot: pd.Timestamp,
    retrieval: pd.Timestamp,
    access_mode: str,
) -> dict[str, Any]:
    row = {column: pd.NA for column in OUTPUT_COLUMNS}
    row.update(
        {
            "source_date": source_date.isoformat(),
            "scheduled_slot_moscow": slot.isoformat(),
            "stock_secid": stock,
            "retrieved_at_utc": retrieval.isoformat(),
            "access_mode": access_mode,
            "valid": False,
            "invalid_reason": "no_eligible_metadata_contract",
        }
    )
    return row


def _pair_row(
    stock: str,
    contract: tuple[str, str, date],
    *,
    spot_securities: pd.DataFrame,
    spot_market: pd.DataFrame,
    futures_securities: pd.DataFrame,
    futures_market: pd.DataFrame,
    source_date: date,
    slot: pd.Timestamp,
    retrieval: pd.Timestamp,
    access_mode: str,
) -> dict[str, Any]:
    asset_code, futures_secid, expiration = contract
    invalid: list[str] = []
    spot_security, reason = _only_row(spot_securities, stock, cross.EQUITY_BOARD)
    if reason:
        invalid.append(f"spot_security_{reason}")
    spot_values, reason = _only_row(spot_market, stock, cross.EQUITY_BOARD)
    if reason:
        invalid.append(f"spot_market_{reason}")
    futures_security, reason = _only_row(
        futures_securities, futures_secid, cross.FUTURES_BOARD
    )
    if reason:
        invalid.append(f"futures_security_{reason}")
    futures_values, reason = _only_row(
        futures_market, futures_secid, cross.FUTURES_BOARD
    )
    if reason:
        invalid.append(f"futures_market_{reason}")
    if str(futures_security.get("assetcode")) != asset_code:
        invalid.append("futures_asset_code_mismatch")
    spot_lot = _positive_integer(spot_security.get("lotsize"))
    futures_lot = _positive_integer(futures_security.get("lotvolume"))
    if spot_lot is None:
        invalid.append("spot_lot_size_missing_or_invalid")
    if futures_lot is None:
        invalid.append("futures_lot_volume_missing_or_invalid")
    spot_lots: int | Any = pd.NA
    if spot_lot is not None and futures_lot is not None:
        ratio = futures_lot / spot_lot
        if ratio <= 0 or not math.isfinite(ratio) or not ratio.is_integer():
            invalid.append("spot_lots_per_contract_not_positive_integer")
        else:
            spot_lots = int(ratio)
    spot_quote = _quote_values(spot_values, "spot", invalid)
    futures_quote = _quote_values(futures_values, "futures", invalid)
    days = (expiration - source_date).days
    return {
        "source_date": source_date.isoformat(),
        "scheduled_slot_moscow": slot.isoformat(),
        "stock_secid": stock,
        "futures_asset_code": asset_code,
        "futures_secid": futures_secid,
        "futures_expiration": expiration.isoformat(),
        "days_to_expiration": days,
        "spot_lot_size_shares": spot_lot if spot_lot is not None else pd.NA,
        "futures_lot_volume_shares": futures_lot if futures_lot is not None else pd.NA,
        "spot_lots_per_futures_contract": spot_lots,
        "spot_minimum_step": cross._optional(spot_security.get("minstep")),
        "futures_minimum_step": cross._optional(futures_security.get("minstep")),
        "futures_security_type_code": futures_security.get("sectype", pd.NA),
        "futures_last_trade_date": futures_security.get("lasttradedate", pd.NA),
        "futures_last_delivery_date": futures_security.get("lastdeldate", pd.NA),
        "futures_initial_margin": cross._optional(futures_security.get("initialmargin")),
        "futures_step_price": cross._optional(futures_security.get("stepprice")),
        "spot_bid": spot_quote["bid"],
        "spot_offer": spot_quote["offer"],
        "spot_bid_depth_lots": spot_quote["bid_depth"],
        "spot_offer_depth_lots": spot_quote["offer_depth"],
        "spot_total_bid_depth_lots": spot_quote["total_bid_depth"],
        "spot_total_offer_depth_lots": spot_quote["total_offer_depth"],
        "spot_number_of_bids": spot_quote["number_of_bids"],
        "spot_number_of_offers": spot_quote["number_of_offers"],
        "spot_volume_today": spot_quote["volume"],
        "spot_value_today": spot_quote["value"],
        "futures_bid": futures_quote["bid"],
        "futures_offer": futures_quote["offer"],
        "futures_bid_depth_contracts": futures_quote["bid_depth"],
        "futures_offer_depth_contracts": futures_quote["offer_depth"],
        "futures_total_bid_depth_contracts": futures_quote["total_bid_depth"],
        "futures_total_offer_depth_contracts": futures_quote["total_offer_depth"],
        "futures_number_of_bids": futures_quote["number_of_bids"],
        "futures_number_of_offers": futures_quote["number_of_offers"],
        "futures_volume_today": futures_quote["volume"],
        "futures_value_today": futures_quote["value"],
        "futures_open_position": cross._optional(futures_values.get("openposition")),
        "spot_exchange_systime": spot_values.get("systime", pd.NA),
        "spot_exchange_updatetime": spot_values.get("updatetime", pd.NA),
        "spot_exchange_seqnum": spot_values.get("seqnum", pd.NA),
        "futures_exchange_systime": futures_values.get("systime", pd.NA),
        "futures_exchange_updatetime": futures_values.get("updatetime", pd.NA),
        "futures_exchange_seqnum": futures_values.get("seqnum", pd.NA),
        "retrieved_at_utc": retrieval.isoformat(),
        "access_mode": access_mode,
        "valid": not invalid,
        "invalid_reason": "|".join(invalid) if invalid else pd.NA,
    }


def _forbidden_columns(frame: pd.DataFrame, config: dict[str, Any]) -> bool:
    forbidden = {str(item).casefold() for item in config["forbidden_outputs"]}
    return any(str(column).casefold() in forbidden for column in frame.columns)


def normalize_snapshot(
    raw: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    source_date: date,
    retrieval: pd.Timestamp,
    slot: pd.Timestamp,
) -> pd.DataFrame:
    payloads = {str(item["kind"]): item["payload"] for item in raw}
    if set(payloads) != {"series", "spots", "futures"}:
        raise ValueError("broad carry raw response identity drifted")
    selected = select_contracts(payloads["series"], source_date, config)
    spot_securities, spot_market = _blocks(
        payloads["spots"], frozenset({"secid", "boardid", "lotsize", "minstep"})
    )
    futures_securities, futures_market = _blocks(
        payloads["futures"],
        frozenset(
            {"secid", "boardid", "sectype", "assetcode", "lotvolume", "minstep"}
        ),
    )
    access_mode = str(config["official_sources"]["access_mode"])
    rows = []
    for stock in config["universe"]["exact_stock_order"]:
        contract = selected[str(stock)]
        if contract is None:
            rows.append(
                _sleep_row(
                    str(stock),
                    source_date=source_date,
                    slot=slot,
                    retrieval=retrieval,
                    access_mode=access_mode,
                )
            )
        else:
            rows.append(
                _pair_row(
                    str(stock),
                    contract,
                    spot_securities=spot_securities,
                    spot_market=spot_market,
                    futures_securities=futures_securities,
                    futures_market=futures_market,
                    source_date=source_date,
                    slot=slot,
                    retrieval=retrieval,
                    access_mode=access_mode,
                )
            )
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if len(frame) != 30 or frame["stock_secid"].duplicated().any():
        raise ValueError("broad carry normalized pair identity drifted")
    if _forbidden_columns(frame, config):
        raise ValueError("broad carry source leaked a forbidden output column")
    return frame


def _status(frame: pd.DataFrame) -> str:
    return "complete_30_pairs_valid" if bool(frame["valid"].all()) else "invalid_pairs"


def collect(
    output_root: Path | None = None,
    *,
    client: JsonClient | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_date, retrieval, slot = cross._source_context(config, retrieved_at)
    root = (output_root or _safe_output_root(str(config["output"]["root"]))).resolve()
    final = root / f"snapshot_{slot:%Y%m%dT%H%M}_moscow"
    if final.exists():
        raise FileExistsError(f"duplicate broad carry snapshot slot: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or network.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        series_url = _series_url(config)
        series_payload = active.get_json(series_url)
        raw.append({"kind": "series", "url": series_url, "payload": series_payload})
        selected = select_contracts(series_payload, source_date, config)
        futures_secids = [
            contract[1] for contract in selected.values() if contract is not None
        ]
        spot_url = _venue_url(
            str(config["official_sources"]["spots_bulk"]),
            list(config["universe"]["exact_stock_order"]),
            SPOT_SECURITY_COLUMNS,
        )
        futures_url = _venue_url(
            str(config["official_sources"]["futures_bulk"]),
            futures_secids,
            FUTURES_SECURITY_COLUMNS,
        )
        raw.append({"kind": "spots", "url": spot_url, "payload": active.get_json(spot_url)})
        raw.append(
            {"kind": "futures", "url": futures_url, "payload": active.get_json(futures_url)}
        )
        frame = normalize_snapshot(
            raw,
            config=config,
            source_date=source_date,
            retrieval=retrieval,
            slot=slot,
        )
        raw_path = temporary / "official_moex_responses.jsonl.gz"
        pairs_path = temporary / "stock_futures_pairs.parquet"
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        storage._write_parquet(pairs_path, frame)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "shared_cross_market_source_sha256": _sha(Path(cross.__file__)),
            "source_date": source_date.isoformat(),
            "scheduled_slot_moscow": slot.isoformat(),
            "retrieved_at_utc": retrieval.isoformat(),
            "status": _status(frame),
            "source_only": True,
            "contains_basis_return_signal_trade_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "rows": len(frame),
                "valid_pairs": int(frame["valid"].sum()),
                "raw_responses": len(raw),
            },
            "artifacts": {
                "pairs": storage._artifact(pairs_path, len(frame)),
                "raw": storage._artifact(raw_path, len(raw)),
            },
            "limitations": config["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()  # type: ignore[attr-defined]
    checks = audit(final)
    write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("broad carry snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    root = snapshot.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_date = pd.Timestamp(manifest["source_date"]).date()
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    slot = pd.Timestamp(manifest["scheduled_slot_moscow"])
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    pairs_path = root / manifest["artifacts"]["pairs"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt = normalize_snapshot(
        raw,
        config=config,
        source_date=source_date,
        retrieval=retrieval,
        slot=slot,
    )
    stored = pd.read_parquet(pairs_path)
    try:
        left = stored.astype(object).where(stored.notna(), None)
        right = rebuilt.astype(object).where(rebuilt.notna(), None)
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    boundary = pd.Timestamp(config["forward_boundary"]["earliest_source_date"]).date()
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == _sha(Path(__file__)),
        "shared_source_sha_exact": manifest["shared_cross_market_source_sha256"]
        == _sha(Path(cross.__file__)),
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_basis_return_signal_trade_or_pnl"] is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "forward_date_exact": source_date >= boundary
        and source_date == retrieval.tz_convert(cross.MOSCOW_TZ).date(),
        "status_exact": manifest["status"] == _status(rebuilt),
        "pairs_sha_exact": _sha(pairs_path) == manifest["artifacts"]["pairs"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "counts_exact": len(stored) == 30
        and len(raw) == 3
        and int(manifest["counts"]["rows"]) == 30,
        "identity_exact": set(stored["stock_secid"])
        == set(config["universe"]["exact_stock_order"])
        and not stored["stock_secid"].duplicated().any(),
        "forbidden_columns_absent": not _forbidden_columns(stored, config),
        "raw_replay_exact": replay_exact,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
