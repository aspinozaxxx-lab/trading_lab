"""Collect sealed forward LQDT quotes for the idle cash sleeve hypothesis."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_stock_futures_cash_carry_source as shared
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_forward_lqdt_idle_cash_source_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "15fb471a2a940b1dabeab6d16f82a8c1fd3e8b863b28936202c42eb4f8f4e1fa"
)
DEFAULT_OUTPUT_ROOT: Final[Path] = PROJECT_ROOT / "data/forward/moex-lqdt-idle-cash-v1"
MOSCOW_TZ: Final[str] = "Europe/Moscow"
STAGES: Final[tuple[str, ...]] = ("decision", "fill")
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "stage",
    "secid",
    "board_id",
    "isin",
    "lot_size",
    "minimum_step",
    "settlement_date",
    "bid",
    "offer",
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
    return shared.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("forward LQDT protocol must be an object")
    instrument = payload["instrument"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_forward_lqdt_idle_cash_source_v1"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["stages"]["allowed_stage_arguments"]) != STAGES
        or instrument["secid"] != "LQDT"
        or instrument["isin"] != "RU000A1014L8"
        or instrument["primary_board"] != "TQBR"
        or payload["economic_separation"][
            "LQDT_units_must_be_zero_while_corresponding_cash_carry_sleeve_is_active"
        ]
        is not True
        or payload["collection"]["atomic_immutable_snapshot"] is not True
    ):
        raise ValueError("forward LQDT protocol drifted")
    return payload


def _safe_output_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe forward LQDT output path: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "forward"):
        raise ValueError("forward LQDT output must be under data/forward")
    return PROJECT_ROOT / relative


def request_url(config: dict[str, Any]) -> str:
    query = urlencode({"iss.meta": "off", "iss.only": "securities,marketdata"})
    return f"{config['official_source']['endpoint']}?{query}"


def _source_context(
    config: dict[str, Any],
    stage: str,
    retrieved_at: str | datetime | pd.Timestamp | None,
) -> tuple[date, pd.Timestamp]:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    local = retrieval.tz_convert(MOSCOW_TZ)
    source_date = local.date()
    boundary = date.fromisoformat(config["forward_boundary"]["earliest_source_date"])
    if source_date < boundary:
        raise ValueError("forward LQDT source date precedes sealed boundary")
    scheduled = time.fromisoformat(config["stages"][stage]["scheduled_local_time"])
    if local.time().replace(tzinfo=None) < scheduled:
        raise ValueError(f"{stage} LQDT collection is earlier than sealed local schedule")
    return source_date, retrieval


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def normalize_response(
    payload: dict[str, Any],
    *,
    config: dict[str, Any],
    stage: str,
    source_date: date,
    retrieval: pd.Timestamp,
) -> pd.DataFrame:
    security = iss._parse_iss_block(
        payload,
        "securities",
        frozenset({"secid", "boardid", "isin", "lotsize", "minstep", "settledate"}),
    )
    market = iss._parse_iss_block(
        payload,
        "marketdata",
        frozenset({"secid", "boardid", "bid", "offer"}),
    )
    expected_secid = str(config["instrument"]["secid"])
    expected_board = str(config["instrument"]["primary_board"])
    expected_isin = str(config["instrument"]["isin"])
    security_rows = security.loc[
        security["secid"].astype(str).eq(expected_secid)
        & security["boardid"].astype(str).eq(expected_board)
    ]
    market_rows = market.loc[
        market["secid"].astype(str).eq(expected_secid)
        & market["boardid"].astype(str).eq(expected_board)
    ]
    invalid: list[str] = []
    if len(security_rows) != 1:
        security_values: dict[str, Any] = {}
        invalid.append("security_identity_missing_or_duplicate")
    else:
        security_values = security_rows.iloc[0].to_dict()
    if len(market_rows) != 1:
        market_values: dict[str, Any] = {}
        invalid.append("quote_identity_missing_or_duplicate")
    else:
        market_values = market_rows.iloc[0].to_dict()
    if str(security_values.get("isin")) != expected_isin:
        invalid.append("isin_mismatch")
    lot_size = _number(security_values.get("lotsize"))
    minimum_step = _number(security_values.get("minstep"))
    if lot_size is None or lot_size <= 0 or not float(lot_size).is_integer():
        invalid.append("lot_size_missing_or_invalid")
    if minimum_step is None or minimum_step <= 0:
        invalid.append("minimum_step_missing_or_invalid")
    settlement = pd.to_datetime(security_values.get("settledate"), errors="coerce")
    if pd.isna(settlement) or settlement.date() < source_date:
        invalid.append("settlement_date_missing_or_stale")
    bid = _number(market_values.get("bid"))
    offer = _number(market_values.get("offer"))
    if bid is None or offer is None or bid <= 0 or offer <= 0:
        invalid.append("positive_two_sided_quote_missing")
    elif offer <= bid:
        invalid.append("crossed_or_locked_quote")
    clocks = {
        name: market_values.get(name)
        for name in ("systime", "updatetime", "seqnum")
        if market_values.get(name) not in (None, "")
        and pd.notna(market_values.get(name))
    }
    if not clocks:
        invalid.append("exchange_clock_missing")
    row = {
        "source_date": source_date.isoformat(),
        "stage": stage,
        "secid": expected_secid,
        "board_id": expected_board,
        "isin": expected_isin,
        "lot_size": int(lot_size) if lot_size is not None and lot_size > 0 else pd.NA,
        "minimum_step": minimum_step if minimum_step is not None else pd.NA,
        "settlement_date": settlement.date().isoformat() if pd.notna(settlement) else pd.NA,
        "bid": bid if bid is not None else pd.NA,
        "offer": offer if offer is not None else pd.NA,
        "exchange_systime": market_values.get("systime", pd.NA),
        "exchange_updatetime": market_values.get("updatetime", pd.NA),
        "exchange_seqnum": market_values.get("seqnum", pd.NA),
        "retrieved_at_utc": retrieval.isoformat(),
        "access_mode": config["official_source"]["access_mode"],
        "valid": not invalid,
        "invalid_reason": "|".join(invalid) if invalid else pd.NA,
    }
    output = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
    forbidden = tuple(str(item).lower() for item in config["forbidden_outputs"])
    if any(any(fragment in str(column).lower() for fragment in forbidden) for column in output):
        raise ValueError("forward LQDT source leaked a forbidden output column")
    return output


def _raw_bytes(record: dict[str, Any]) -> bytes:
    return shared._raw_bytes([record])


def collect(
    stage: str,
    output_root: Path | None = None,
    *,
    client: JsonClient | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_date, retrieval = _source_context(config, stage, retrieved_at)
    root = (
        output_root
        or _safe_output_root(str(config["output"]["root"]))
    ).resolve()
    final = root / f"snapshot_{source_date:%Y%m%d}_{stage}"
    if final.exists():
        raise FileExistsError(f"duplicate forward LQDT stage/date: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or shared.shared.OfficialMoexClient()
    own_client = client is None
    try:
        url = request_url(config)
        payload = active.get_json(url)
        frame = normalize_response(
            payload,
            config=config,
            stage=stage,
            source_date=source_date,
            retrieval=retrieval,
        )
        raw_path = temporary / "official_moex_lqdt_response.jsonl.gz"
        quotes_path = temporary / "quotes.parquet"
        atomic_write_bytes(raw_path, _raw_bytes({"url": url, "payload": payload}))
        shared._write_parquet(quotes_path, frame)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_date": source_date.isoformat(),
            "stage": stage,
            "retrieved_at_utc": retrieval.isoformat(),
            "status": "complete_valid" if bool(frame.iloc[0]["valid"]) else "invalid",
            "source_only": True,
            "contains_yield_return_signal_trade_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {"rows": 1, "valid_rows": int(frame["valid"].sum()), "raw": 1},
            "artifacts": {
                "quotes": shared._artifact(quotes_path, 1),
                "raw": shared._artifact(raw_path, 1),
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
        raise ValueError("forward LQDT snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    root = snapshot.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_date = date.fromisoformat(str(manifest["source_date"]))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    raw = shared._read_raw(raw_path)
    raw_exact_count = len(raw) == 1 and isinstance(raw[0].get("payload"), dict)
    rebuilt = normalize_response(
        raw[0]["payload"],
        config=config,
        stage=str(manifest["stage"]),
        source_date=source_date,
        retrieval=retrieval,
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
    boundary = date.fromisoformat(config["forward_boundary"]["earliest_source_date"])
    expected_status = "complete_valid" if bool(rebuilt.iloc[0]["valid"]) else "invalid"
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_yield_return_signal_trade_or_pnl"] is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "source_date_forward_exact": source_date >= boundary
        and source_date == retrieval.tz_convert(MOSCOW_TZ).date(),
        "stage_exact": manifest["stage"] in STAGES,
        "status_exact": manifest["status"] == expected_status,
        "quotes_sha_exact": _sha(quotes_path) == manifest["artifacts"]["quotes"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "row_count_exact": len(stored) == 1 == int(manifest["counts"]["rows"]),
        "raw_count_exact": raw_exact_count,
        "raw_replay_exact": replay_exact,
        "identity_exact": len(stored) == 1
        and stored.iloc[0]["secid"] == "LQDT"
        and stored.iloc[0]["board_id"] == "TQBR",
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
