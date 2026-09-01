"""Capture immutable public-delayed MOEX option-surface snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_forward_option_surface_source_v1.yaml"
CONFIG_SHA256: Final[str] = "a33c86b4440a0c14fceac4c5a2e3bdd580e3ff9964bfcb375a4ba09f83529eaa"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = PROJECT_ROOT / "data/forward/moex-options-surface-v1"
USER_AGENT: Final[str] = "market-lab-forward-option-surface/1.0 (MOEX research)"
JOIN_KEYS: Final[tuple[str, str]] = ("SECID", "BOARDID")
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "retrieved_at_utc",
    "available_at_utc",
    "access_mode",
    "requested_asset",
    "asset_code",
    "secid",
    "boardid",
    "underlying_asset",
    "option_type",
    "strike",
    "last_trade_date",
    "last_delivery_date",
    "minimum_step",
    "step_price",
    "buy_sell_fee",
    "scalper_fee",
    "exercise_fee",
    "previous_settle",
    "underlying_settle",
    "bid",
    "offer",
    "spread",
    "open",
    "high",
    "low",
    "last",
    "settle",
    "volume",
    "number_of_trades",
    "open_interest",
    "exchange_systime",
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
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("forward option-surface config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_forward_option_surface_source_v1"
        or config.get("live_trading_allowed") is not False
        or config["temporal_semantics"]["forward_only"] is not True
        or config["hypothesis_for_later_protocol"]["this_protocol_computes_returns_targets_or_pnl"]
        is not False
    ):
        raise ValueError("forward option-surface protocol invariant drift")
    return config


def request_url(config: dict[str, Any], requested_asset: str) -> str:
    if requested_asset not in config["source"]["requested_assets"]:
        raise ValueError("undeclared option asset")
    query = {**config["source"]["query"], "assets": requested_asset}
    return f"{config['source']['endpoint']}?{urlencode(query)}"


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


def normalize_response(
    raw: bytes,
    requested_asset: str,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> pd.DataFrame:
    payload = json.loads(raw.decode("utf-8-sig"))
    security = _block(payload, "securities", config["required_security_columns"])
    market = _block(payload, "marketdata", config["required_marketdata_columns"])
    if security.empty or market.empty:
        raise ValueError("empty MOEX option response")
    if security.duplicated(list(JOIN_KEYS)).any() or market.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("duplicate MOEX option identity")
    if set(map(tuple, security[list(JOIN_KEYS)].to_numpy())) != set(
        map(tuple, market[list(JOIN_KEYS)].to_numpy())
    ):
        raise ValueError("security/marketdata option identity mismatch")
    expected_source_asset = requested_asset
    if set(security["ASSETCODE"].astype(str)) != {expected_source_asset}:
        raise ValueError("requested option asset does not match response")
    joined = security.merge(market, on=list(JOIN_KEYS), how="inner", validate="one_to_one")
    source_dates = pd.to_datetime(joined["TRADE_SESSION_DATE"], errors="raise")
    retrieval_utc = retrieved_at.tz_convert("UTC")
    retrieval_moscow_date = retrieval_utc.tz_convert("Europe/Moscow").tz_localize(None).normalize()
    if source_dates.max() > retrieval_moscow_date:
        raise ValueError("option source date is after retrieval Moscow date")
    mapping = config["source"]["asset_mapping"]
    output = pd.DataFrame(
        {
            "source_date": source_dates,
            "retrieved_at_utc": retrieval_utc.isoformat(),
            "available_at_utc": retrieval_utc.isoformat(),
            "access_mode": config["source"]["access_mode"],
            "requested_asset": requested_asset,
            "asset_code": mapping[requested_asset],
            "secid": joined["SECID"].astype("string"),
            "boardid": joined["BOARDID"].astype("string"),
            "underlying_asset": joined["UNDERLYINGASSET"].astype("string"),
            "option_type": joined["OPTIONTYPE"].astype("string"),
            "strike": pd.to_numeric(joined["STRIKE"], errors="coerce"),
            "last_trade_date": pd.to_datetime(joined["LASTTRADEDATE"], errors="coerce"),
            "last_delivery_date": pd.to_datetime(joined["LASTDELDATE"], errors="coerce"),
            "minimum_step": pd.to_numeric(joined["MINSTEP"], errors="coerce"),
            "step_price": pd.to_numeric(joined["STEPPRICE"], errors="coerce"),
            "buy_sell_fee": pd.to_numeric(joined["BUYSELLFEE"], errors="coerce"),
            "scalper_fee": pd.to_numeric(joined["SCALPERFEE"], errors="coerce"),
            "exercise_fee": pd.to_numeric(joined["EXERCISEFEE"], errors="coerce"),
            "previous_settle": pd.to_numeric(joined["PREVSETTLEPRICE"], errors="coerce"),
            "underlying_settle": pd.to_numeric(
                joined["UNDERLYINGSETTLEPRICE"], errors="coerce"
            ),
            "bid": pd.to_numeric(joined["BID"], errors="coerce"),
            "offer": pd.to_numeric(joined["OFFER"], errors="coerce"),
            "spread": pd.to_numeric(joined["SPREAD"], errors="coerce"),
            "open": pd.to_numeric(joined["OPEN"], errors="coerce"),
            "high": pd.to_numeric(joined["HIGH"], errors="coerce"),
            "low": pd.to_numeric(joined["LOW"], errors="coerce"),
            "last": pd.to_numeric(joined["LAST"], errors="coerce"),
            "settle": pd.to_numeric(joined["SETTLEPRICE"], errors="coerce"),
            "volume": pd.to_numeric(joined["VOLTODAY"], errors="coerce"),
            "number_of_trades": pd.to_numeric(joined["NUMTRADES"], errors="coerce"),
            "open_interest": pd.to_numeric(joined["OPENPOSITION"], errors="coerce"),
            "exchange_systime": joined["SYSTIME"].astype("string"),
        },
        columns=OUTPUT_COLUMNS,
    )
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("derived outcome column escaped into option snapshot")
    return output.sort_values(
        ["asset_code", "last_trade_date", "strike", "option_type", "secid"],
        kind="stable",
        ignore_index=True,
    )


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
    raw: dict[str, bytes] = {}
    frames = []
    for asset in config["source"]["requested_assets"]:
        response = client.get(
            request_url(config, asset), headers={"User-Agent": USER_AGENT}, timeout=30.0
        )
        response.raise_for_status()
        raw[asset] = bytes(response.content)
        frames.append(normalize_response(raw[asset], asset, retrieval, config))
    surface = pd.concat(frames, ignore_index=True).sort_values(
        ["asset_code", "last_trade_date", "strike", "option_type", "secid"],
        kind="stable",
        ignore_index=True,
    )
    if surface.duplicated(["asset_code", "boardid", "secid"]).any():
        raise ValueError("duplicate option identity across asset responses")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_artifacts = {}
        for asset, payload in raw.items():
            path = temporary / f"raw_{asset}.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            raw_artifacts[asset] = {
                "path": path.name,
                "url": request_url(config, asset),
                "response_bytes": len(payload),
                "response_sha256": _sha_bytes(payload),
                "stored_bytes": path.stat().st_size,
                "stored_sha256": _sha_file(path),
            }
        processed = temporary / "option_surface.parquet"
        surface.to_parquet(processed, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "access_mode": config["source"]["access_mode"],
            "forward_only": True,
            "contains_returns_labels_targets_or_pnl": False,
            "counts": {
                "rows": len(surface),
                "by_asset": surface.groupby("asset_code").size().astype(int).to_dict(),
                "source_dates": sorted(surface["source_date"].dt.date.astype(str).unique()),
            },
            "raw": raw_artifacts,
            "processed": {
                "path": processed.name,
                "bytes": processed.stat().st_size,
                "sha256": _sha_file(processed),
                "rows": len(surface),
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
        raise ValueError("forward option snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    replay = []
    checks: dict[str, bool] = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest["contains_returns_labels_targets_or_pnl"] is False,
    }
    for asset, item in manifest["raw"].items():
        path = snapshot / item["path"]
        payload = gzip.decompress(path.read_bytes())
        checks[f"raw_{asset}_stored_exact"] = (
            path.stat().st_size == item["stored_bytes"]
            and _sha_file(path) == item["stored_sha256"]
        )
        checks[f"raw_{asset}_response_exact"] = (
            len(payload) == item["response_bytes"]
            and _sha_bytes(payload) == item["response_sha256"]
        )
        replay.append(normalize_response(payload, asset, retrieval, config))
    rebuilt = pd.concat(replay, ignore_index=True).sort_values(
        ["asset_code", "last_trade_date", "strike", "option_type", "secid"],
        kind="stable",
        ignore_index=True,
    )
    processed_item = manifest["processed"]
    processed_path = snapshot / processed_item["path"]
    stored = pd.read_parquet(processed_path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_like=False, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    checks.update(
        {
            "processed_exact": processed_path.stat().st_size == processed_item["bytes"]
            and _sha_file(processed_path) == processed_item["sha256"],
            "rows_exact": len(stored) == int(processed_item["rows"]),
            "raw_replay_exact": replay_exact,
            "all_assets_present": set(stored["asset_code"])
            == set(config["source"]["asset_mapping"].values()),
            "identity_unique": not stored.duplicated(["asset_code", "boardid", "secid"]).any(),
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
