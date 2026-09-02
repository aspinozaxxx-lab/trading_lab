"""Collect the sealed forward TQBR money-market fund quote/depth pool."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import quote, urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_forward_lqdt_idle_cash_source as lqdt_shared
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_money_market_fund_pool_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "37a3baeb7d0b0062139cb6afe7db7d5cba4e7f02e547a32c90b5f1cabf52e884"
)
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-money-market-fund-pool-v1"
)
STAGES: Final[tuple[str, ...]] = ("decision", "fill")
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "stage",
    "secid",
    "board_id",
    "isin",
    "registration_number",
    "lot_size",
    "minimum_step",
    "settlement_date",
    "bid",
    "offer",
    "bid_depth_units",
    "offer_depth_units",
    "total_bid_depth_units",
    "total_offer_depth_units",
    "number_of_bids",
    "number_of_offers",
    "exchange_systime",
    "exchange_updatetime",
    "exchange_seqnum",
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
        raise ValueError("money-market fund pool protocol must be an object")
    universe = payload["fixed_universe"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "moex_forward_money_market_fund_pool_source_v1"
        or payload.get("live_trading_allowed") is not False
        or tuple(universe["funds"]) != ("LQDT", "SBMM", "AKMM", "TMON")
        or universe["board"] != "TQBR"
        or tuple(payload["stages"]["allowed_stage_arguments"]) != STAGES
        or payload["role_constraints"]["selection_or_ranking_during_source_collection"]
        != "forbidden"
        or payload["collection"]["atomic_immutable_snapshot"] is not True
    ):
        raise ValueError("money-market fund pool protocol drifted")
    return payload


def request_url(config: dict[str, Any], secid: str) -> str:
    endpoint = str(config["official_source"]["endpoint_template"]).replace(
        "{secid}", quote(secid, safe="")
    )
    query = urlencode({"iss.meta": "off", "iss.only": "securities,marketdata"})
    return f"{endpoint}?{query}"


def _number(value: Any) -> float | None:
    return lqdt_shared._number(value)


def _optional_number(value: Any) -> float | Any:
    parsed = _number(value)
    return parsed if parsed is not None else pd.NA


def normalize_response(
    payload: dict[str, Any],
    secid: str,
    *,
    config: dict[str, Any],
    stage: str,
    source_date: date,
    retrieval: pd.Timestamp,
) -> pd.DataFrame:
    security = iss._parse_iss_block(
        payload,
        "securities",
        frozenset(
            {"secid", "boardid", "isin", "regnumber", "lotsize", "minstep", "settledate"}
        ),
    )
    market = iss._parse_iss_block(
        payload,
        "marketdata",
        frozenset({"secid", "boardid", "bid", "offer", "biddepth", "offerdepth"}),
    )
    board = str(config["fixed_universe"]["board"])
    declaration = config["fixed_universe"]["funds"][secid]
    security_rows = security.loc[
        security["secid"].astype(str).eq(secid)
        & security["boardid"].astype(str).eq(board)
    ]
    market_rows = market.loc[
        market["secid"].astype(str).eq(secid)
        & market["boardid"].astype(str).eq(board)
    ]
    invalid: list[str] = []
    if len(security_rows) != 1:
        securities: dict[str, Any] = {}
        invalid.append("security_identity_missing_or_duplicate")
    else:
        securities = security_rows.iloc[0].to_dict()
    if len(market_rows) != 1:
        values: dict[str, Any] = {}
        invalid.append("quote_identity_missing_or_duplicate")
    else:
        values = market_rows.iloc[0].to_dict()
    if str(securities.get("isin")) != str(declaration["isin"]):
        invalid.append("isin_mismatch")
    if str(securities.get("regnumber")) != str(declaration["registration_number"]):
        invalid.append("registration_number_mismatch")
    lot_size = _number(securities.get("lotsize"))
    minimum_step = _number(securities.get("minstep"))
    if lot_size is None or lot_size <= 0 or not lot_size.is_integer():
        invalid.append("lot_size_missing_or_invalid")
    if minimum_step is None or minimum_step <= 0:
        invalid.append("minimum_step_missing_or_invalid")
    settlement = pd.to_datetime(securities.get("settledate"), errors="coerce")
    if pd.isna(settlement) or settlement.date() < source_date:
        invalid.append("settlement_date_missing_or_stale")
    bid = _number(values.get("bid"))
    offer = _number(values.get("offer"))
    bid_depth = _number(values.get("biddepth"))
    offer_depth = _number(values.get("offerdepth"))
    if bid is None or offer is None or bid <= 0 or offer <= 0:
        invalid.append("positive_two_sided_quote_missing")
    elif offer <= bid:
        invalid.append("crossed_or_locked_quote")
    if bid_depth is None or offer_depth is None or bid_depth <= 0 or offer_depth <= 0:
        invalid.append("positive_two_sided_depth_missing")
    clocks = {
        name: values.get(name)
        for name in ("systime", "updatetime", "seqnum")
        if values.get(name) not in (None, "") and pd.notna(values.get(name))
    }
    if not clocks:
        invalid.append("exchange_clock_missing")
    row = {
        "source_date": source_date.isoformat(),
        "stage": stage,
        "secid": secid,
        "board_id": board,
        "isin": declaration["isin"],
        "registration_number": declaration["registration_number"],
        "lot_size": int(lot_size) if lot_size is not None and lot_size > 0 else pd.NA,
        "minimum_step": minimum_step if minimum_step is not None else pd.NA,
        "settlement_date": settlement.date().isoformat() if pd.notna(settlement) else pd.NA,
        "bid": bid if bid is not None else pd.NA,
        "offer": offer if offer is not None else pd.NA,
        "bid_depth_units": bid_depth if bid_depth is not None else pd.NA,
        "offer_depth_units": offer_depth if offer_depth is not None else pd.NA,
        "total_bid_depth_units": _optional_number(values.get("biddeptht")),
        "total_offer_depth_units": _optional_number(values.get("offerdeptht")),
        "number_of_bids": _optional_number(values.get("numbids")),
        "number_of_offers": _optional_number(values.get("numoffers")),
        "exchange_systime": values.get("systime", pd.NA),
        "exchange_updatetime": values.get("updatetime", pd.NA),
        "exchange_seqnum": values.get("seqnum", pd.NA),
        "retrieved_at_utc": retrieval.isoformat(),
        "access_mode": config["official_source"]["access_mode"],
        "valid": not invalid,
        "invalid_reason": "|".join(invalid) if invalid else pd.NA,
    }
    return pd.DataFrame([row], columns=OUTPUT_COLUMNS)


def _forbidden(frame: pd.DataFrame, config: dict[str, Any]) -> bool:
    fragments = tuple(str(item).lower() for item in config["forbidden_outputs"])
    return any(any(fragment in str(column).lower() for fragment in fragments) for column in frame)


def collect(
    stage: str,
    output_root: Path | None = None,
    *,
    client: JsonClient | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_date, retrieval = lqdt_shared._source_context(config, stage, retrieved_at)
    root = (
        output_root
        or lqdt_shared._safe_output_root(str(config["output"]["root"]))
    ).resolve()
    final = root / f"snapshot_{source_date:%Y%m%d}_{stage}"
    if final.exists():
        raise FileExistsError(f"duplicate money-market pool stage/date: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or storage.shared.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        frames: list[pd.DataFrame] = []
        for secid in config["fixed_universe"]["funds"]:
            url = request_url(config, secid)
            payload = active.get_json(url)
            raw.append({"secid": secid, "url": url, "payload": payload})
            frames.append(
                normalize_response(
                    payload,
                    secid,
                    config=config,
                    stage=stage,
                    source_date=source_date,
                    retrieval=retrieval,
                )
            )
        frame = pd.concat(frames, ignore_index=True)
        if len(frame) != 4 or frame["secid"].duplicated().any() or _forbidden(frame, config):
            raise ValueError("money-market pool output identity or source-only schema failed")
        raw_path = temporary / "official_moex_fund_pool_responses.jsonl.gz"
        quotes_path = temporary / "fund_quotes.parquet"
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        storage._write_parquet(quotes_path, frame)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_date": source_date.isoformat(),
            "stage": stage,
            "retrieved_at_utc": retrieval.isoformat(),
            "status": "complete_valid" if bool(frame["valid"].all()) else "invalid",
            "source_only": True,
            "contains_ranking_yield_return_signal_trade_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "rows": len(frame),
                "valid_rows": int(frame["valid"].sum()),
                "raw": len(raw),
            },
            "artifacts": {
                "quotes": storage._artifact(quotes_path, len(frame)),
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
        raise ValueError("money-market fund pool snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    root = snapshot.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_date = pd.Timestamp(manifest["source_date"]).date()
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt = pd.concat(
        [
            normalize_response(
                item["payload"],
                str(item["secid"]),
                config=config,
                stage=str(manifest["stage"]),
                source_date=source_date,
                retrieval=retrieval,
            )
            for item in raw
        ],
        ignore_index=True,
    )
    quotes_path = root / manifest["artifacts"]["quotes"]["file"]
    stored = pd.read_parquet(quotes_path)
    try:
        left = stored.astype(object).where(stored.notna(), None)
        right = rebuilt.astype(object).where(rebuilt.notna(), None)
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    expected_status = "complete_valid" if bool(rebuilt["valid"].all()) else "invalid"
    boundary = pd.Timestamp(config["forward_boundary"]["earliest_source_date"]).date()
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "outcomes_and_ranking_absent": manifest[
            "contains_ranking_yield_return_signal_trade_or_pnl"
        ]
        is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "source_date_forward_exact": source_date >= boundary
        and source_date == retrieval.tz_convert(lqdt_shared.MOSCOW_TZ).date(),
        "status_exact": manifest["status"] == expected_status,
        "quotes_sha_exact": _sha(quotes_path) == manifest["artifacts"]["quotes"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "row_count_exact": len(stored) == 4 == int(manifest["counts"]["rows"]),
        "raw_count_exact": len(raw) == 4 == int(manifest["counts"]["raw"]),
        "raw_replay_exact": replay_exact,
        "identity_exact": set(stored["secid"]) == set(config["fixed_universe"]["funds"])
        and not stored["secid"].duplicated().any(),
        "forbidden_columns_absent": not _forbidden(stored, config),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        if args.stage is None:
            parser.error("--stage is required when collecting")
        print(collect(args.stage, args.output_root))


if __name__ == "__main__":
    main()
