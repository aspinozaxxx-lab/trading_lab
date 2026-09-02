"""Capture immutable forward-only market and macro snapshots for V27 validation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

from market_lab.futures import info_radar, stlfsi_source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v27_forward_validation_v1.yaml"
CONFIG_SHA256: Final[str] = "c1acf97bbeb950452346b6961010ea3df1aeeb05ce24f95130579b69e5b5724e"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = PROJECT_ROOT / "data/forward/v27-validation-v1"
USER_AGENT: Final[str] = "market-lab-v27-forward-validation/1.0 (research)"
SNAPSHOT_KINDS: Final[tuple[str, str]] = ("decision_eod", "execution_observation")
MACRO_LOOKBACK_DAYS: Final[int] = 400
JOIN_KEYS: Final[tuple[str, str]] = ("SECID", "BOARDID")
MARKET_COLUMNS: Final[tuple[str, ...]] = (
    "snapshot_kind",
    "source_date",
    "retrieved_at_utc",
    "available_at_utc",
    "access_mode",
    "logical_asset",
    "source_asset",
    "secid",
    "boardid",
    "last_trade_date",
    "last_delivery_date",
    "minimum_step",
    "step_price",
    "initial_margin_rub",
    "buy_sell_fee_rub",
    "scalper_fee_rub",
    "previous_settle",
    "bid",
    "offer",
    "open",
    "high",
    "low",
    "last",
    "settle",
    "number_of_trades",
    "volume",
    "open_interest",
    "exchange_systime",
)
MACRO_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "observation_date",
    "effective_date",
    "value",
    "model_available_at_utc",
    "forward_available_at_utc",
    "retrieved_at_utc",
    "source_current_vintage",
)


class ResponseLike(Protocol):
    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> ResponseLike: ...

    def post(
        self,
        url: str,
        *,
        data: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


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
        raise ValueError("V27 forward validation config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent = PROJECT_ROOT / config["parent_v27"]["protocol"]
    if (
        config.get("protocol_id") != "futures_v27_forward_validation_v1"
        or config.get("live_trading_allowed") is not False
        or config["forward_boundary"]["historical_2026_market_backfill"] != "forbidden"
        or config["parent_v27"]["protocol_sha256"] != _sha_file(parent)
        or config["frozen_economics"]["log_momentum_horizons_sessions"]
        != [21, 63, 126, 252]
        or int(config["sequential_validation"]["warmup_common_sessions"]) != 252
        or int(config["sequential_validation"]["evaluation_common_sessions_minimum"])
        != 504
    ):
        raise ValueError("V27 forward validation invariant drift")
    return config


def market_url(config: dict[str, Any], logical_asset: str) -> str:
    source_asset = config["market_source"]["assets_query"].get(logical_asset)
    if source_asset is None:
        raise ValueError("undeclared V27 logical asset")
    query = {"iss.meta": "off", "iss.only": "securities,marketdata", "assets": source_asset}
    return f"{config['market_source']['endpoint']}?{urlencode(query)}"


def macro_bounds(retrieval: pd.Timestamp) -> tuple[date, date]:
    end = retrieval.tz_convert("Europe/Moscow").date()
    return end - timedelta(days=MACRO_LOOKBACK_DAYS), end


def fred_url(retrieval: pd.Timestamp) -> str:
    start, end = macro_bounds(retrieval)
    query = urlencode({"id": "STLFSI4", "cosd": start.isoformat(), "coed": end.isoformat()})
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?{query}"


def _block(payload: dict[str, Any], name: str, required: list[str]) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        raise ValueError(f"missing MOEX {name} block")
    columns = [str(value) for value in block["columns"]]
    if set(required) - set(columns):
        raise ValueError(f"MOEX V27 {name} schema drift")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX V27 {name} rows")
    return pd.DataFrame(rows, columns=columns)


def normalize_market(
    raw: bytes,
    logical_asset: str,
    snapshot_kind: str,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> pd.DataFrame:
    if snapshot_kind not in SNAPSHOT_KINDS:
        raise ValueError("unknown V27 snapshot kind")
    payload = json.loads(raw.decode("utf-8-sig"))
    required = config["market_source"]["current_snapshot_fields"]
    security = _block(payload, "securities", required["security"])
    market = _block(payload, "marketdata", required["marketdata"])
    if security.duplicated(list(JOIN_KEYS)).any() or market.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("duplicate MOEX V27 contract identity")
    source_asset = config["market_source"]["assets_query"][logical_asset]
    selected = security.loc[security["ASSETCODE"].astype(str).eq(source_asset)].copy()
    if selected.empty:
        raise ValueError(f"empty MOEX V27 listed chain: {logical_asset}")
    selected_keys = set(map(tuple, selected[list(JOIN_KEYS)].to_numpy()))
    market_selected = market.loc[
        market[list(JOIN_KEYS)].apply(tuple, axis=1).isin(selected_keys)
    ].copy()
    if selected_keys != set(map(tuple, market_selected[list(JOIN_KEYS)].to_numpy())):
        raise ValueError("MOEX V27 security/marketdata identity mismatch")
    joined = selected.merge(
        market_selected, on=list(JOIN_KEYS), how="inner", validate="one_to_one"
    )
    nonmissing_dates = pd.to_datetime(joined["TRADEDATE"], errors="coerce").dropna().unique()
    if len(nonmissing_dates) != 1:
        raise ValueError("MOEX V27 response must expose one exact source date")
    source_date = pd.Timestamp(nonmissing_dates[0])
    retrieval_utc = retrieved_at.tz_convert("UTC")
    retrieval_moscow_date = retrieval_utc.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    earliest = pd.Timestamp(config["forward_boundary"]["earliest_allowed_market_source_date"])
    if source_date < earliest or source_date > retrieval_moscow_date:
        raise ValueError("MOEX V27 source date escaped forward seal")
    expirations = pd.to_datetime(joined["LASTTRADEDATE"], errors="raise")
    joined = joined.loc[expirations.ge(source_date)].copy()
    expirations = pd.to_datetime(joined["LASTTRADEDATE"], errors="raise")
    if joined.empty:
        raise ValueError("MOEX V27 chain has no unexpired contracts")
    output = pd.DataFrame(
        {
            "snapshot_kind": snapshot_kind,
            "source_date": source_date,
            "retrieved_at_utc": retrieval_utc.isoformat(),
            "available_at_utc": retrieval_utc.isoformat(),
            "access_mode": config["market_source"]["access_mode"],
            "logical_asset": logical_asset,
            "source_asset": source_asset,
            "secid": joined["SECID"].astype("string"),
            "boardid": joined["BOARDID"].astype("string"),
            "last_trade_date": expirations,
            "last_delivery_date": pd.to_datetime(joined["LASTDELDATE"], errors="coerce"),
            "minimum_step": pd.to_numeric(joined["MINSTEP"], errors="coerce"),
            "step_price": pd.to_numeric(joined["STEPPRICE"], errors="coerce"),
            "initial_margin_rub": pd.to_numeric(joined["INITIALMARGIN"], errors="coerce"),
            "buy_sell_fee_rub": pd.to_numeric(joined["BUYSELLFEE"], errors="coerce"),
            "scalper_fee_rub": pd.to_numeric(joined["SCALPERFEE"], errors="coerce"),
            "previous_settle": pd.to_numeric(joined["PREVSETTLEPRICE"], errors="coerce"),
            "bid": pd.to_numeric(joined["BID"], errors="coerce"),
            "offer": pd.to_numeric(joined["OFFER"], errors="coerce"),
            "open": pd.to_numeric(joined["OPEN"], errors="coerce"),
            "high": pd.to_numeric(joined["HIGH"], errors="coerce"),
            "low": pd.to_numeric(joined["LOW"], errors="coerce"),
            "last": pd.to_numeric(joined["LAST"], errors="coerce"),
            "settle": pd.to_numeric(joined["SETTLEPRICE"], errors="coerce"),
            "number_of_trades": pd.to_numeric(joined["NUMTRADES"], errors="coerce"),
            "volume": pd.to_numeric(joined["VOLTODAY"], errors="coerce"),
            "open_interest": pd.to_numeric(joined["OPENPOSITION"], errors="coerce"),
            "exchange_systime": joined["SYSTIME"].astype("string"),
        },
        columns=MARKET_COLUMNS,
    )
    forbidden = {str(value).lower() for value in config["forbidden_source_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("derived outcome escaped into V27 market snapshot")
    return output.sort_values(
        ["logical_asset", "last_trade_date", "secid"], kind="stable", ignore_index=True
    )


def _forward_availability(
    model_available: pd.Series, retrieval: pd.Timestamp
) -> pd.Series:
    modeled = pd.to_datetime(model_available, utc=True)
    retrieval_utc = retrieval.tz_convert("UTC")
    return modeled.where(modeled.ge(retrieval_utc), retrieval_utc)


def parse_fred_forward(raw: bytes, retrieval: pd.Timestamp) -> pd.DataFrame:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("forward STLFSI4 CSV is not UTF-8") from error
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames != ["observation_date", "STLFSI4"]:
        raise ValueError("forward STLFSI4 header drift")
    rows = []
    for row in reader:
        observation = date.fromisoformat(str(row["observation_date"]))
        value_text = str(row["STLFSI4"] or "").strip()
        rows.append(
            {
                "series_id": "stlfsi4",
                "observation_date": pd.Timestamp(observation),
                "effective_date": pd.Timestamp(observation),
                "value": float(value_text) if value_text not in {"", "."} else float("nan"),
                "model_available_at_utc": stlfsi_source.conservative_available_at(observation),
            }
        )
    if not rows:
        raise ValueError("forward STLFSI4 response is empty")
    frame = pd.DataFrame(rows).sort_values("observation_date", ignore_index=True)
    if frame["observation_date"].duplicated().any():
        raise ValueError("duplicate forward STLFSI4 observation")
    frame["forward_available_at_utc"] = _forward_availability(
        frame["model_available_at_utc"], retrieval
    )
    frame["retrieved_at_utc"] = retrieval.tz_convert("UTC")
    frame["source_current_vintage"] = True
    return frame.loc[:, MACRO_COLUMNS]


def normalize_cbr_forward(
    ruonia_raw: bytes,
    key_rate_raw: bytes,
    retrieval: pd.Timestamp,
) -> pd.DataFrame:
    ruonia = info_radar.parse_cbr_ruonia_html(ruonia_raw)
    key_rate = info_radar.parse_cbr_key_rate_xml(key_rate_raw)
    frames = []
    for source in (ruonia, key_rate):
        frame = pd.DataFrame(
            {
                "series_id": source["series_id"].astype("string"),
                "observation_date": pd.to_datetime(source["observation_date"]),
                "effective_date": pd.to_datetime(source["effective_date"]),
                "value": pd.to_numeric(source["value"], errors="raise"),
                "model_available_at_utc": pd.to_datetime(source["available_at"], utc=True),
            }
        )
        frame["forward_available_at_utc"] = _forward_availability(
            frame["model_available_at_utc"], retrieval
        )
        frame["retrieved_at_utc"] = retrieval.tz_convert("UTC")
        frame["source_current_vintage"] = True
        frames.append(frame.loc[:, MACRO_COLUMNS])
    output = pd.concat(frames, ignore_index=True).sort_values(
        ["series_id", "observation_date"], ignore_index=True
    )
    if output.duplicated(["series_id", "observation_date"]).any():
        raise ValueError("duplicate forward CBR macro observation")
    return output


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    snapshot_kind: str,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    if snapshot_kind not in SNAPSHOT_KINDS:
        raise ValueError("unknown V27 snapshot kind")
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("V27 retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    client: SessionLike = session or requests.Session()
    market_raw: dict[str, bytes] = {}
    market_frames = []
    for logical_asset in config["frozen_economics"]["universe"]:
        response = client.get(
            market_url(config, logical_asset),
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        response.raise_for_status()
        market_raw[logical_asset] = bytes(response.content)
        market_frames.append(
            normalize_market(
                market_raw[logical_asset], logical_asset, snapshot_kind, retrieval, config
            )
        )
    market = pd.concat(market_frames, ignore_index=True).sort_values(
        ["logical_asset", "last_trade_date", "secid"], kind="stable", ignore_index=True
    )
    source_dates = market["source_date"].dt.date.astype(str).unique()
    if len(source_dates) != 1 or market.duplicated(["logical_asset", "boardid", "secid"]).any():
        raise ValueError("V27 market snapshot date or identity mismatch")

    start, end = macro_bounds(retrieval)
    fred_response = client.get(
        fred_url(retrieval), headers={"User-Agent": USER_AGENT}, timeout=30.0
    )
    fred_response.raise_for_status()
    ruonia_url = info_radar.build_cbr_ruonia_url(start, end)
    ruonia_response = client.get(
        ruonia_url, headers={"User-Agent": USER_AGENT}, timeout=30.0
    )
    ruonia_response.raise_for_status()
    key_body = info_radar.build_cbr_key_rate_soap(start, end)
    key_response = client.post(
        info_radar.CBR_DAILY_INFO_ENDPOINT,
        data=key_body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://web.cbr.ru/KeyRateXML",
        },
        timeout=30.0,
    )
    key_response.raise_for_status()
    raw_macro = {
        "fred_stlfsi4": bytes(fred_response.content),
        "cbr_ruonia": bytes(ruonia_response.content),
        "cbr_key_rate": bytes(key_response.content),
    }
    macro = pd.concat(
        [
            parse_fred_forward(raw_macro["fred_stlfsi4"], retrieval),
            normalize_cbr_forward(
                raw_macro["cbr_ruonia"], raw_macro["cbr_key_rate"], retrieval
            ),
        ],
        ignore_index=True,
    ).sort_values(["series_id", "observation_date"], ignore_index=True)

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_{snapshot_kind}_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_artifacts: dict[str, Any] = {}
        for logical_asset, payload in market_raw.items():
            path = temporary / f"raw_market_{logical_asset}.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            raw_artifacts[f"market_{logical_asset}"] = {
                "path": path.name,
                "url": market_url(config, logical_asset),
                "response_bytes": len(payload),
                "response_sha256": _sha_bytes(payload),
                "stored_bytes": path.stat().st_size,
                "stored_sha256": _sha_file(path),
            }
        macro_urls = {
            "fred_stlfsi4": fred_url(retrieval),
            "cbr_ruonia": ruonia_url,
            "cbr_key_rate": info_radar.CBR_DAILY_INFO_ENDPOINT,
        }
        for label, payload in raw_macro.items():
            path = temporary / f"raw_{label}.bin.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            raw_artifacts[label] = {
                "path": path.name,
                "url": macro_urls[label],
                "response_bytes": len(payload),
                "response_sha256": _sha_bytes(payload),
                "stored_bytes": path.stat().st_size,
                "stored_sha256": _sha_file(path),
            }
            if label == "cbr_key_rate":
                raw_artifacts[label]["request_body_bytes"] = len(key_body)
                raw_artifacts[label]["request_body_sha256"] = _sha_bytes(key_body)
        market_path = temporary / "market.parquet"
        macro_path = temporary / "macro.parquet"
        market.to_parquet(market_path, index=False)
        macro.to_parquet(macro_path, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "snapshot_kind": snapshot_kind,
            "retrieved_at_utc": retrieval.isoformat(),
            "forward_only": True,
            "contains_return_label_target_prediction_or_pnl": False,
            "counts": {
                "market_rows": len(market),
                "market_rows_by_asset": market.groupby("logical_asset").size().to_dict(),
                "source_dates": sorted(source_dates),
                "macro_rows": len(macro),
                "macro_rows_by_series": macro.groupby("series_id").size().to_dict(),
            },
            "raw": raw_artifacts,
            "processed": {
                "market": {
                    "path": market_path.name,
                    "bytes": market_path.stat().st_size,
                    "sha256": _sha_file(market_path),
                    "rows": len(market),
                },
                "macro": {
                    "path": macro_path.name,
                    "bytes": macro_path.stat().st_size,
                    "sha256": _sha_file(macro_path),
                    "rows": len(macro),
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
        raise ValueError("V27 forward snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    snapshot_kind = str(manifest["snapshot_kind"])
    checks: dict[str, bool] = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest["contains_return_label_target_prediction_or_pnl"] is False,
    }
    market_frames = []
    macro_raw: dict[str, bytes] = {}
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
        if label.startswith("market_"):
            logical_asset = label.removeprefix("market_")
            market_frames.append(
                normalize_market(payload, logical_asset, snapshot_kind, retrieval, config)
            )
        else:
            macro_raw[label] = payload
    rebuilt_market = pd.concat(market_frames, ignore_index=True).sort_values(
        ["logical_asset", "last_trade_date", "secid"], kind="stable", ignore_index=True
    )
    rebuilt_macro = pd.concat(
        [
            parse_fred_forward(macro_raw["fred_stlfsi4"], retrieval),
            normalize_cbr_forward(
                macro_raw["cbr_ruonia"], macro_raw["cbr_key_rate"], retrieval
            ),
        ],
        ignore_index=True,
    ).sort_values(["series_id", "observation_date"], ignore_index=True)
    stored_frames = {}
    for name, rebuilt in (("market", rebuilt_market), ("macro", rebuilt_macro)):
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
            "exact_assets": set(stored_frames["market"]["logical_asset"])
            == set(config["frozen_economics"]["universe"]),
            "market_identity_unique": not stored_frames["market"].duplicated(
                ["logical_asset", "boardid", "secid"]
            ).any(),
            "macro_series_exact": set(stored_frames["macro"]["series_id"])
            == {"stlfsi4", "ruonia", "key_rate"},
            "macro_forward_availability_not_before_retrieval": bool(
                pd.to_datetime(stored_frames["macro"]["forward_available_at_utc"], utc=True)
                .ge(retrieval)
                .all()
            ),
        }
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--snapshot-kind", choices=SNAPSHOT_KINDS)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    elif args.snapshot_kind:
        print(collect(args.output_root, snapshot_kind=args.snapshot_kind))
    else:
        parser.error("--snapshot-kind is required unless --audit-directory is used")


if __name__ == "__main__":
    main()
