"""Collect immutable public-MOEX cross-market BBO snapshots every ten minutes."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_cross_market_bbo_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "80d5202db7c0d85542f79f775a29a30ebe16ec94f8d745abd9ec9d7ab4f27d3d"
)
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-cross-market-bbo-v1"
)
MOSCOW_TZ: Final[str] = "Europe/Moscow"
EQUITY_BOARD: Final[str] = "TQBR"
FUTURES_BOARD: Final[str] = "RFUD"
FX_BOARD: Final[str] = "CETS"
FUTURES_ASSET_CODES: Final[dict[str, str]] = {
    "SI": "Si",
    "RI": "RTS",
    "BR": "BR",
    "MIX": "MIX",
}
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "scheduled_slot_moscow",
    "venue_kind",
    "logical_asset",
    "secid",
    "board_id",
    "contract_expiration",
    "lot_size",
    "minimum_step",
    "bid",
    "offer",
    "bid_depth_lots",
    "offer_depth_lots",
    "total_bid_depth_lots",
    "total_offer_depth_lots",
    "number_of_bids",
    "number_of_offers",
    "trading_status",
    "open",
    "high",
    "low",
    "last",
    "waprice",
    "volume",
    "value_today",
    "last_trade_value",
    "number_of_trades",
    "open_position",
    "exchange_systime",
    "exchange_updatetime",
    "exchange_seqnum",
    "retrieved_at_utc",
    "access_mode",
    "core_required",
    "valid",
    "invalid_reason",
)
SECURITY_COLUMNS: Final[tuple[str, ...]] = (
    "SECID",
    "BOARDID",
    "LOTSIZE",
    "MINSTEP",
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
    "TRADINGSTATUS",
    "OPEN",
    "HIGH",
    "LOW",
    "LAST",
    "WAPRICE",
    "VOLUME",
    "VALTODAY",
    "VALUE",
    "NUMTRADES",
    "OPENPOSITION",
    "SYSTIME",
    "UPDATETIME",
    "SEQNUM",
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
        raise ValueError("cross-market BBO protocol must be an object")
    universe = payload["universe"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_forward_cross_market_bbo_source_v1"
        or payload.get("live_trading_allowed") is not False
        or len(universe["equities"]["secids"]) != 30
        or tuple(universe["futures"]["logical_assets"]) != ("SI", "RI", "BR", "MIX")
        or tuple(universe["fx"]["secids"]) != ("CNYRUB_TOM",)
        or tuple(universe["idle_cash_context"]["secids"])
        != ("LQDT", "SBMM", "AKMM", "TMON")
        or int(payload["schedule"]["interval_minutes"]) != 10
        or payload["collection"]["atomic_immutable_snapshot_directory"] is not True
    ):
        raise ValueError("cross-market BBO protocol drifted")
    return payload


def _safe_output_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe cross-market output root: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "forward"):
        raise ValueError("cross-market output must be under data/forward")
    return PROJECT_ROOT / relative


def request_urls(config: dict[str, Any]) -> dict[str, str]:
    common = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "securities.columns": ",".join(SECURITY_COLUMNS),
        "marketdata.columns": ",".join(MARKET_COLUMNS),
    }
    sources = config["official_sources"]
    series_query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "series",
            "series.columns": (
                "secid,name,start_date,expiration_date,asset_code,is_traded"
            ),
        }
    )
    return {
        "series": f"{sources['futures_series']}?{series_query}",
        "equities": f"{sources['equities_bulk']}?{urlencode(common)}",
        "futures": f"{sources['futures_bulk']}?{urlencode(common)}",
        "fx": f"{sources['fx_bulk']}?{urlencode(common)}",
    }


def _source_context(
    config: dict[str, Any], retrieved_at: str | datetime | pd.Timestamp | None
) -> tuple[date, pd.Timestamp, pd.Timestamp]:
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("cross-market retrieval timestamp must include a timezone")
    retrieval = retrieval.tz_convert("UTC")
    local = retrieval.tz_convert(MOSCOW_TZ)
    boundary = date.fromisoformat(config["forward_boundary"]["earliest_source_date"])
    if local.date() < boundary:
        raise ValueError("cross-market source date precedes sealed boundary")
    if local.weekday() >= 5:
        raise ValueError("cross-market collection is restricted to weekdays")
    first = time.fromisoformat(config["schedule"]["first_snapshot_local_time"])
    last = time.fromisoformat(config["schedule"]["last_snapshot_local_time"])
    first_local = pd.Timestamp.combine(local.date(), first).tz_localize(MOSCOW_TZ)
    last_local = pd.Timestamp.combine(local.date(), last).tz_localize(MOSCOW_TZ)
    interval = pd.Timedelta(minutes=int(config["schedule"]["interval_minutes"]))
    elapsed = local - first_local
    if elapsed < pd.Timedelta(0) or local > last_local + pd.Timedelta(minutes=2):
        raise ValueError("cross-market retrieval is outside the sealed collection window")
    slot_number = int(elapsed // interval)
    slot = first_local + slot_number * interval
    if local < slot or local - slot > pd.Timedelta(minutes=2):
        raise ValueError("cross-market retrieval missed the sealed ten-minute slot")
    if slot > last_local:
        raise ValueError("cross-market retrieval slot is after the sealed last slot")
    return local.date(), retrieval, slot


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    number = float(parsed)
    return number if math.isfinite(number) else None


def _optional(value: Any) -> float | Any:
    number = _number(value)
    return number if number is not None else pd.NA


def select_futures_contracts(
    payload: dict[str, Any], source_date: date, config: dict[str, Any]
) -> dict[str, tuple[str, date] | None]:
    series = iss.parse_futures_series_payload(payload)
    minimum_days = int(
        config["universe"]["futures"][
            "nearest_contract_minimum_calendar_days_to_expiry"
        ]
    )
    selected: dict[str, tuple[str, date] | None] = {}
    for logical_asset, asset_code in FUTURES_ASSET_CODES.items():
        rows = series.loc[
            series["asset_code"].astype(str).eq(asset_code)
            & series["is_traded"].astype(bool)
            & series["start_date"].le(pd.Timestamp(source_date))
            & series["expiration_date"].ge(
                pd.Timestamp(source_date) + pd.Timedelta(days=minimum_days)
            )
        ].sort_values(["expiration_date", "secid"])
        if rows.empty:
            selected[logical_asset] = None
        else:
            row = rows.iloc[0]
            selected[logical_asset] = (
                str(row["secid"]),
                pd.Timestamp(row["expiration_date"]).date(),
            )
    return selected


def _blocks(payload: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    securities = iss._parse_iss_block(
        payload, "securities", frozenset({"secid", "boardid", "lotsize", "minstep"})
    )
    market = iss._parse_iss_block(
        payload,
        "marketdata",
        frozenset({"secid", "boardid", "bid", "offer", "biddepth", "offerdepth"}),
    )
    return securities, market


def _row(
    securities: pd.DataFrame,
    market: pd.DataFrame,
    *,
    source_date: date,
    slot: pd.Timestamp,
    retrieval: pd.Timestamp,
    venue_kind: str,
    logical_asset: str,
    secid: str,
    board: str,
    expiration: date | None,
    core_required: bool,
    access_mode: str,
) -> dict[str, Any]:
    security_rows = securities.loc[
        securities["secid"].astype(str).eq(secid)
        & securities["boardid"].astype(str).eq(board)
    ]
    market_rows = market.loc[
        market["secid"].astype(str).eq(secid)
        & market["boardid"].astype(str).eq(board)
    ]
    invalid: list[str] = []
    if len(security_rows) != 1:
        security: dict[str, Any] = {}
        invalid.append("security_identity_missing_or_duplicate")
    else:
        security = security_rows.iloc[0].to_dict()
    if len(market_rows) != 1:
        values: dict[str, Any] = {}
        invalid.append("market_identity_missing_or_duplicate")
    else:
        values = market_rows.iloc[0].to_dict()
    bid = _number(values.get("bid"))
    offer = _number(values.get("offer"))
    bid_depth = _number(values.get("biddepth"))
    offer_depth = _number(values.get("offerdepth"))
    if bid is None or offer is None or bid <= 0 or offer <= 0:
        invalid.append("positive_two_sided_quote_missing")
    elif offer <= bid:
        invalid.append("crossed_or_locked_quote")
    if bid_depth is None or offer_depth is None or bid_depth <= 0 or offer_depth <= 0:
        invalid.append("positive_best_depth_missing")
    clocks = [values.get(name) for name in ("systime", "updatetime", "seqnum")]
    if not any(value not in (None, "") and pd.notna(value) for value in clocks):
        invalid.append("exchange_clock_missing")
    lot_size = _number(security.get("lotsize"))
    minimum_step = _number(security.get("minstep"))
    if lot_size is None or lot_size <= 0 or minimum_step is None or minimum_step <= 0:
        invalid.append("lot_or_minimum_step_missing")
    row = {
        "source_date": source_date.isoformat(),
        "scheduled_slot_moscow": slot.isoformat(),
        "venue_kind": venue_kind,
        "logical_asset": logical_asset,
        "secid": secid,
        "board_id": board,
        "contract_expiration": expiration.isoformat() if expiration else pd.NA,
        "lot_size": lot_size if lot_size is not None else pd.NA,
        "minimum_step": minimum_step if minimum_step is not None else pd.NA,
        "bid": bid if bid is not None else pd.NA,
        "offer": offer if offer is not None else pd.NA,
        "bid_depth_lots": bid_depth if bid_depth is not None else pd.NA,
        "offer_depth_lots": offer_depth if offer_depth is not None else pd.NA,
        "total_bid_depth_lots": _optional(values.get("biddeptht")),
        "total_offer_depth_lots": _optional(values.get("offerdeptht")),
        "number_of_bids": _optional(values.get("numbids")),
        "number_of_offers": _optional(values.get("numoffers")),
        "trading_status": values.get("tradingstatus", pd.NA),
        "open": _optional(values.get("open")),
        "high": _optional(values.get("high")),
        "low": _optional(values.get("low")),
        "last": _optional(values.get("last")),
        "waprice": _optional(values.get("waprice")),
        "volume": _optional(values.get("volume")),
        "value_today": _optional(values.get("valtoday")),
        "last_trade_value": _optional(values.get("value")),
        "number_of_trades": _optional(values.get("numtrades")),
        "open_position": _optional(values.get("openposition")),
        "exchange_systime": values.get("systime", pd.NA),
        "exchange_updatetime": values.get("updatetime", pd.NA),
        "exchange_seqnum": values.get("seqnum", pd.NA),
        "retrieved_at_utc": retrieval.isoformat(),
        "access_mode": access_mode,
        "core_required": core_required,
        "valid": not invalid,
        "invalid_reason": "|".join(invalid) if invalid else pd.NA,
    }
    return row


def _sleep_future_row(
    logical_asset: str,
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
            "venue_kind": "futures",
            "logical_asset": logical_asset,
            "board_id": FUTURES_BOARD,
            "retrieved_at_utc": retrieval.isoformat(),
            "access_mode": access_mode,
            "core_required": True,
            "valid": False,
            "invalid_reason": "no_eligible_metadata_contract",
        }
    )
    return row


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
    if set(payloads) != {"series", "equities", "futures", "fx"}:
        raise ValueError("cross-market raw request identity drifted")
    equity_securities, equity_market = _blocks(payloads["equities"])
    futures_securities, futures_market = _blocks(payloads["futures"])
    fx_securities, fx_market = _blocks(payloads["fx"])
    selected = select_futures_contracts(payloads["series"], source_date, config)
    access_mode = str(config["official_sources"]["access_mode"])
    rows: list[dict[str, Any]] = []
    for secid in config["universe"]["equities"]["secids"]:
        rows.append(
            _row(
                equity_securities,
                equity_market,
                source_date=source_date,
                slot=slot,
                retrieval=retrieval,
                venue_kind="equity",
                logical_asset=str(secid),
                secid=str(secid),
                board=EQUITY_BOARD,
                expiration=None,
                core_required=True,
                access_mode=access_mode,
            )
        )
    for logical_asset in config["universe"]["futures"]["logical_assets"]:
        contract = selected[str(logical_asset)]
        if contract is None:
            rows.append(
                _sleep_future_row(
                    str(logical_asset),
                    source_date=source_date,
                    slot=slot,
                    retrieval=retrieval,
                    access_mode=access_mode,
                )
            )
        else:
            secid, expiration = contract
            rows.append(
                _row(
                    futures_securities,
                    futures_market,
                    source_date=source_date,
                    slot=slot,
                    retrieval=retrieval,
                    venue_kind="futures",
                    logical_asset=str(logical_asset),
                    secid=secid,
                    board=FUTURES_BOARD,
                    expiration=expiration,
                    core_required=True,
                    access_mode=access_mode,
                )
            )
    for secid in config["universe"]["fx"]["secids"]:
        rows.append(
            _row(
                fx_securities,
                fx_market,
                source_date=source_date,
                slot=slot,
                retrieval=retrieval,
                venue_kind="fx",
                logical_asset=str(secid),
                secid=str(secid),
                board=FX_BOARD,
                expiration=None,
                core_required=True,
                access_mode=access_mode,
            )
        )
    for secid in config["universe"]["idle_cash_context"]["secids"]:
        rows.append(
            _row(
                equity_securities,
                equity_market,
                source_date=source_date,
                slot=slot,
                retrieval=retrieval,
                venue_kind="idle_cash_context",
                logical_asset=str(secid),
                secid=str(secid),
                board=EQUITY_BOARD,
                expiration=None,
                core_required=False,
                access_mode=access_mode,
            )
        )
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values(
        ["venue_kind", "logical_asset"], ignore_index=True
    )
    if len(frame) != 39 or int(frame["core_required"].sum()) != 35:
        raise ValueError("cross-market normalized universe count drifted")
    if frame.duplicated(["venue_kind", "logical_asset"]).any():
        raise ValueError("cross-market normalized identity is not unique")
    if _forbidden_columns(frame, config):
        raise ValueError("cross-market output leaked a forbidden column")
    return frame


def _status(frame: pd.DataFrame) -> str:
    core = frame.loc[frame["core_required"]]
    return "complete_core_valid" if bool(core["valid"].all()) else "invalid_core"


def collect(
    output_root: Path | None = None,
    *,
    client: JsonClient | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_date, retrieval, slot = _source_context(config, retrieved_at)
    root = (output_root or _safe_output_root(str(config["output"]["root"]))).resolve()
    final = root / f"snapshot_{slot:%Y%m%dT%H%M}_moscow"
    if final.exists():
        raise FileExistsError(f"duplicate cross-market snapshot slot: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or network.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        for kind, url in request_urls(config).items():
            raw.append({"kind": kind, "url": url, "payload": active.get_json(url)})
        frame = normalize_snapshot(
            raw,
            config=config,
            source_date=source_date,
            retrieval=retrieval,
            slot=slot,
        )
        raw_path = temporary / "official_moex_responses.jsonl.gz"
        snapshot_path = temporary / "cross_market_snapshot.parquet"
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        storage._write_parquet(snapshot_path, frame)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_date": source_date.isoformat(),
            "scheduled_slot_moscow": slot.isoformat(),
            "retrieved_at_utc": retrieval.isoformat(),
            "status": _status(frame),
            "source_only": True,
            "contains_returns_labels_signals_predictions_trades_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "rows": len(frame),
                "core_rows": int(frame["core_required"].sum()),
                "valid_core_rows": int(frame.loc[frame["core_required"], "valid"].sum()),
                "context_rows": int((~frame["core_required"]).sum()),
                "valid_context_rows": int(frame.loc[~frame["core_required"], "valid"].sum()),
                "raw_responses": len(raw),
            },
            "artifacts": {
                "snapshot": storage._artifact(snapshot_path, len(frame)),
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
        raise ValueError("cross-market snapshot audit failed")
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
    snapshot_path = root / manifest["artifacts"]["snapshot"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt = normalize_snapshot(
        raw,
        config=config,
        source_date=source_date,
        retrieval=retrieval,
        slot=slot,
    )
    stored = pd.read_parquet(snapshot_path)
    try:
        left = stored.astype(object).where(stored.notna(), None)
        right = rebuilt.astype(object).where(rebuilt.notna(), None)
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    boundary = pd.Timestamp(config["forward_boundary"]["earliest_source_date"]).date()
    core = stored.loc[stored["core_required"]]
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest[
            "contains_returns_labels_signals_predictions_trades_or_pnl"
        ]
        is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "forward_date_exact": source_date >= boundary
        and source_date == retrieval.tz_convert(MOSCOW_TZ).date(),
        "slot_exact": slot.tz_convert(MOSCOW_TZ).date() == source_date,
        "status_exact": manifest["status"] == _status(rebuilt),
        "snapshot_sha_exact": _sha(snapshot_path)
        == manifest["artifacts"]["snapshot"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "counts_exact": len(stored) == 39
        and len(core) == 35
        and len(raw) == 4
        and int(manifest["counts"]["rows"]) == 39,
        "identity_unique": not stored.duplicated(["venue_kind", "logical_asset"]).any(),
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
