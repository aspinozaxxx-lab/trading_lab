"""Capture immutable forward-only MOEX CNY futures relative-value snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_cny_relative_value_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = "1305af9d3d0d06957b5f7e2bb5fb566dc7986cd8be8fc008ed1c50907b9f13ef"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = PROJECT_ROOT / "data/forward/moex-cny-relative-value-v1"
USER_AGENT: Final[str] = "market-lab-forward-cny-relative-value/1.0 (MOEX research)"
JOIN_KEYS: Final[tuple[str, str]] = ("SECID", "BOARDID")
QUOTE_COLUMNS: Final[tuple[str, ...]] = (
    "quote_date",
    "retrieved_at_utc",
    "available_at_utc",
    "access_mode",
    "instrument_kind",
    "secid",
    "boardid",
    "asset_code",
    "last_trade_date",
    "last_delivery_date",
    "lot_volume_cny",
    "minimum_step",
    "step_price",
    "initial_margin_rub",
    "buy_sell_fee_rub",
    "scalper_fee_rub",
    "previous_settle",
    "bid",
    "offer",
    "spread",
    "last",
    "settle",
    "volume",
    "number_of_trades",
    "open_interest",
    "exchange_systime",
)
FUNDING_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "retrieved_at_utc",
    "available_at_utc",
    "access_mode",
    "secid",
    "boardid",
    "settle",
    "swap_rate",
    "number_of_trades",
    "volume",
)


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".yaml.sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("forward CNY relative-value config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_forward_cny_relative_value_source_v1"
        or config.get("live_trading_allowed") is not False
        or config["temporal_semantics"]["forward_only"] is not True
        or config["hypothesis_for_later_protocol"]["historical_2026_backfill"]
        != "forbidden"
        or config["hypothesis_for_later_protocol"]["this_protocol_computes_signal_return_or_pnl"]
        is not False
    ):
        raise ValueError("forward CNY relative-value protocol invariant drift")
    return config


def current_url(config: dict[str, Any], request_name: str) -> str:
    request = config["source"]["requests"].get(request_name)
    if request_name not in {"perpetual", "quarterly"} or request is None:
        raise ValueError("undeclared forward CNY request")
    query = {**config["source"]["query"], "assets": request["assets"]}
    return f"{config['source']['current_endpoint']}?{urlencode(query)}"


def history_url(
    config: dict[str, Any], retrieval: pd.Timestamp, start: int = 0
) -> str:
    moscow_date = retrieval.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    till = moscow_date - pd.Timedelta(days=1)
    earliest = pd.Timestamp(config["temporal_semantics"]["earliest_allowed_source_date"])
    query = {
        "iss.meta": "off",
        "from": earliest.date().isoformat(),
        "till": till.date().isoformat(),
        "start": int(start),
        "history.columns": ",".join(config["source"]["perpetual_history_columns"]),
    }
    return f"{config['source']['history_endpoint']}?{urlencode(query)}"


def _block(payload: dict[str, Any], name: str, required: list[str]) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        raise ValueError(f"missing MOEX {name} block")
    columns = [str(value) for value in block["columns"]]
    if set(required) - set(columns):
        raise ValueError(f"MOEX {name} schema drift")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX {name} rows")
    return pd.DataFrame(rows, columns=columns)


def normalize_current(
    raw: bytes,
    request_name: str,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> pd.DataFrame:
    payload = json.loads(raw.decode("utf-8-sig"))
    security = _block(payload, "securities", config["required_security_columns"])
    market = _block(payload, "marketdata", config["required_marketdata_columns"])
    if security.duplicated(list(JOIN_KEYS)).any() or market.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("duplicate MOEX CNY current identity")
    retrieval_utc = retrieved_at.tz_convert("UTC")
    moscow_date = retrieval_utc.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    request = config["source"]["requests"][request_name]
    if request_name == "perpetual":
        selected = security.loc[security["SECID"].astype(str).eq(request["exact_secid"])]
        kind = "perpetual"
        expected_rows = 1
    elif request_name == "quarterly":
        pattern = re.compile(request["secid_regex"])
        expiration = pd.to_datetime(security["LASTTRADEDATE"], errors="coerce")
        mask = security["SECID"].astype(str).map(lambda value: bool(pattern.fullmatch(value)))
        selected = security.loc[mask & expiration.ge(moscow_date)].copy()
        selected["_expiration"] = pd.to_datetime(selected["LASTTRADEDATE"])
        selected = selected.sort_values(["_expiration", "SECID"], kind="stable").head(
            int(request["nearest_future_contracts"])
        )
        selected = selected.drop(columns="_expiration")
        kind = "quarterly"
        expected_rows = int(request["nearest_future_contracts"])
    else:
        raise ValueError("unknown forward CNY request")
    if len(selected) != expected_rows:
        raise ValueError(f"forward CNY {request_name} deterministic selection incomplete")
    selected_keys = set(map(tuple, selected[list(JOIN_KEYS)].to_numpy()))
    market_keys = set(map(tuple, market[list(JOIN_KEYS)].to_numpy()))
    if not selected_keys <= market_keys:
        raise ValueError("selected CNY security lacks matching marketdata")
    joined = selected.merge(market, on=list(JOIN_KEYS), how="inner", validate="one_to_one")
    quote_dates = pd.to_datetime(joined["TRADEDATE"], errors="raise")
    earliest = pd.Timestamp(config["temporal_semantics"]["earliest_allowed_source_date"])
    if quote_dates.isna().any() or quote_dates.min() < earliest or quote_dates.max() > moscow_date:
        raise ValueError("forward CNY quote date escaped sealed interval")
    output = pd.DataFrame(
        {
            "quote_date": quote_dates,
            "retrieved_at_utc": retrieval_utc.isoformat(),
            "available_at_utc": retrieval_utc.isoformat(),
            "access_mode": config["source"]["access_mode"],
            "instrument_kind": kind,
            "secid": joined["SECID"].astype("string"),
            "boardid": joined["BOARDID"].astype("string"),
            "asset_code": joined["ASSETCODE"].astype("string"),
            "last_trade_date": pd.to_datetime(joined["LASTTRADEDATE"], errors="raise"),
            "last_delivery_date": pd.to_datetime(joined["LASTDELDATE"], errors="coerce"),
            "lot_volume_cny": pd.to_numeric(joined["LOTVOLUME"], errors="coerce"),
            "minimum_step": pd.to_numeric(joined["MINSTEP"], errors="coerce"),
            "step_price": pd.to_numeric(joined["STEPPRICE"], errors="coerce"),
            "initial_margin_rub": pd.to_numeric(joined["INITIALMARGIN"], errors="coerce"),
            "buy_sell_fee_rub": pd.to_numeric(joined["BUYSELLFEE"], errors="coerce"),
            "scalper_fee_rub": pd.to_numeric(joined["SCALPERFEE"], errors="coerce"),
            "previous_settle": pd.to_numeric(joined["PREVSETTLEPRICE"], errors="coerce"),
            "bid": pd.to_numeric(joined["BID"], errors="coerce"),
            "offer": pd.to_numeric(joined["OFFER"], errors="coerce"),
            "spread": pd.to_numeric(joined["SPREAD"], errors="coerce"),
            "last": pd.to_numeric(joined["LAST"], errors="coerce"),
            "settle": pd.to_numeric(joined["SETTLEPRICE"], errors="coerce"),
            "volume": pd.to_numeric(joined["VOLTODAY"], errors="coerce"),
            "number_of_trades": pd.to_numeric(joined["NUMTRADES"], errors="coerce"),
            "open_interest": pd.to_numeric(joined["OPENPOSITION"], errors="coerce"),
            "exchange_systime": joined["SYSTIME"].astype("string"),
        },
        columns=QUOTE_COLUMNS,
    )
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("derived outcome escaped into forward CNY quotes")
    return output.sort_values(
        ["instrument_kind", "last_trade_date", "secid"], kind="stable", ignore_index=True
    )


def normalize_history(
    raw: bytes,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int | None, int | None]:
    payload = json.loads(raw.decode("utf-8-sig"))
    history = _block(payload, "history", config["source"]["perpetual_history_columns"])
    cursor_block = payload.get("history.cursor")
    total = page_size = None
    if isinstance(cursor_block, dict) and cursor_block.get("data"):
        cursor = dict(zip(cursor_block["columns"], cursor_block["data"][0], strict=True))
        total, page_size = int(cursor["TOTAL"]), int(cursor["PAGESIZE"])
    retrieval_utc = retrieved_at.tz_convert("UTC")
    moscow_date = retrieval_utc.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    earliest = pd.Timestamp(config["temporal_semantics"]["earliest_allowed_source_date"])
    if history.empty:
        return pd.DataFrame(columns=FUNDING_COLUMNS), total, page_size
    dates = pd.to_datetime(history["TRADEDATE"], errors="raise")
    if (
        set(history["SECID"].astype(str)) != {"CNYRUBF"}
        or dates.min() < earliest
        or dates.max() >= moscow_date
    ):
        raise ValueError("forward CNY funding history escaped sealed interval")
    output = pd.DataFrame(
        {
            "trade_date": dates,
            "retrieved_at_utc": retrieval_utc.isoformat(),
            "available_at_utc": retrieval_utc.isoformat(),
            "access_mode": config["source"]["access_mode"],
            "secid": history["SECID"].astype("string"),
            "boardid": history["BOARDID"].astype("string"),
            "settle": pd.to_numeric(history["SETTLEPRICE"], errors="coerce"),
            "swap_rate": pd.to_numeric(history["SWAPRATE"], errors="coerce"),
            "number_of_trades": pd.to_numeric(history["NUMTRADES"], errors="coerce"),
            "volume": pd.to_numeric(history["VOLUME"], errors="coerce"),
        },
        columns=FUNDING_COLUMNS,
    )
    return output.sort_values("trade_date", ignore_index=True), total, page_size


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    client: SessionLike = session or requests.Session()
    current_raw: dict[str, bytes] = {}
    quote_frames = []
    for name in ("perpetual", "quarterly"):
        response = client.get(
            current_url(config, name), headers={"User-Agent": USER_AGENT}, timeout=30.0
        )
        response.raise_for_status()
        current_raw[name] = bytes(response.content)
        quote_frames.append(normalize_current(current_raw[name], name, retrieval, config))
    quotes = pd.concat(quote_frames, ignore_index=True)
    if quotes.duplicated(["boardid", "secid"]).any():
        raise ValueError("duplicate selected CNY quote identity")

    history_raw: list[tuple[int, bytes]] = []
    funding_frames = []
    start, total = 0, None
    moscow_date = retrieval.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    earliest = pd.Timestamp(config["temporal_semantics"]["earliest_allowed_source_date"])
    history_available = moscow_date - pd.Timedelta(days=1) >= earliest
    while history_available and (total is None or start < total):
        response = client.get(
            history_url(config, retrieval, start),
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        response.raise_for_status()
        raw = bytes(response.content)
        frame, observed_total, page_size = normalize_history(raw, retrieval, config)
        history_raw.append((start, raw))
        funding_frames.append(frame)
        if observed_total is None or page_size is None:
            total = len(frame)
            break
        if total is not None and total != observed_total:
            raise ValueError("forward CNY history total changed during pagination")
        total = observed_total
        if page_size <= 0:
            break
        start += page_size
    funding = pd.concat(funding_frames, ignore_index=True) if funding_frames else pd.DataFrame(
        columns=FUNDING_COLUMNS
    )
    if not funding.empty and funding["trade_date"].duplicated().any():
        raise ValueError("duplicate forward CNY funding date")

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_artifacts: dict[str, Any] = {}
        for label, payload in current_raw.items():
            path = temporary / f"raw_current_{label}.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            raw_artifacts[f"current_{label}"] = {
                "path": path.name,
                "url": current_url(config, label),
                "response_bytes": len(payload),
                "response_sha256": _sha_bytes(payload),
                "stored_bytes": path.stat().st_size,
                "stored_sha256": _sha_file(path),
            }
        for page_start, payload in history_raw:
            path = temporary / f"raw_history_{page_start:06d}.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            raw_artifacts[f"history_{page_start}"] = {
                "path": path.name,
                "url": history_url(config, retrieval, page_start),
                "start": page_start,
                "response_bytes": len(payload),
                "response_sha256": _sha_bytes(payload),
                "stored_bytes": path.stat().st_size,
                "stored_sha256": _sha_file(path),
            }
        quote_path = temporary / "quotes.parquet"
        funding_path = temporary / "funding_history.parquet"
        quotes.to_parquet(quote_path, index=False)
        funding.to_parquet(funding_path, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "access_mode": config["source"]["access_mode"],
            "forward_only": True,
            "contains_signal_return_label_target_or_pnl": False,
            "counts": {
                "quote_rows": len(quotes),
                "quote_dates": sorted(quotes["quote_date"].dt.date.astype(str).unique()),
                "funding_rows": len(funding),
                "funding_dates": (
                    sorted(funding["trade_date"].dt.date.astype(str).unique())
                    if not funding.empty
                    else []
                ),
            },
            "raw": raw_artifacts,
            "processed": {
                "quotes": {
                    "path": quote_path.name,
                    "bytes": quote_path.stat().st_size,
                    "sha256": _sha_file(quote_path),
                    "rows": len(quotes),
                },
                "funding": {
                    "path": funding_path.name,
                    "bytes": funding_path.stat().st_size,
                    "sha256": _sha_file(funding_path),
                    "rows": len(funding),
                },
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("forward CNY relative-value snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks: dict[str, bool] = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest["contains_signal_return_label_target_or_pnl"] is False,
    }
    quote_frames = []
    funding_frames = []
    for label, item in manifest["raw"].items():
        path = snapshot / item["path"]
        payload = gzip.decompress(path.read_bytes())
        checks[f"raw_{label}_stored_exact"] = (
            path.stat().st_size == item["stored_bytes"]
            and _sha_file(path) == item["stored_sha256"]
        )
        checks[f"raw_{label}_response_exact"] = (
            len(payload) == item["response_bytes"]
            and _sha_bytes(payload) == item["response_sha256"]
        )
        if label.startswith("current_"):
            quote_frames.append(
                normalize_current(payload, label.removeprefix("current_"), retrieval, config)
            )
        else:
            funding_frames.append(normalize_history(payload, retrieval, config)[0])
    rebuilt_quotes = pd.concat(quote_frames, ignore_index=True)
    rebuilt_funding = (
        pd.concat(funding_frames, ignore_index=True)
        if funding_frames
        else pd.DataFrame(columns=FUNDING_COLUMNS)
    )
    stored_frames = {}
    for name, rebuilt in (("quotes", rebuilt_quotes), ("funding", rebuilt_funding)):
        item = manifest["processed"][name]
        path = snapshot / item["path"]
        stored = pd.read_parquet(path)
        stored_frames[name] = stored
        try:
            pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
            replay_exact = True
        except AssertionError:
            replay_exact = False
        checks[f"{name}_processed_exact"] = (
            path.stat().st_size == item["bytes"] and _sha_file(path) == item["sha256"]
        )
        checks[f"{name}_rows_exact"] = len(stored) == int(item["rows"])
        checks[f"{name}_raw_replay_exact"] = replay_exact
    checks.update(
        {
            "three_quote_rows": len(stored_frames["quotes"]) == 3,
            "one_perpetual_two_quarterlies": stored_frames["quotes"]["instrument_kind"]
            .value_counts()
            .to_dict()
            == {"quarterly": 2, "perpetual": 1},
            "quote_identity_unique": not stored_frames["quotes"].duplicated(
                ["boardid", "secid"]
            ).any(),
            "funding_date_unique": not stored_frames["funding"]["trade_date"].duplicated().any(),
        }
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
