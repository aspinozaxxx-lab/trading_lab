"""Collect immutable MOEX CNY/RUB spot and quarterly futures history."""

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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_cny_cash_carry_source_v1.yaml"
CONFIG_SHA256: Final[str] = "511f17e3fe74d0ef16d09eb957d470d6b69816c028a559e06a9ec2ab3dc1ecc6"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/fx_basis/moex-cny-cash-carry-current-vintage-v1"
)
USER_AGENT: Final[str] = "market-lab-cny-carry-source/1.0 (MOEX research)"
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "instrument_kind",
    "security_id",
    "board_id",
    "asset_code",
    "trade_date",
    "expiration_date",
    "lot_size_cny",
    "open",
    "low",
    "high",
    "close",
    "settle",
    "weighted_average_price",
    "volume",
    "number_of_trades",
    "open_interest",
    "available_at_utc",
    "retrieved_at_utc",
    "access_mode",
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
        raise ValueError("MOEX CNY carry source config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_cny_cash_carry_source_v1"
        or config.get("live_trading_allowed") is not False
        or config["hypothesis_for_later_protocol"]
        ["this_protocol_computes_basis_returns_targets_or_pnl"]
        is not False
        or config["temporal_semantics"]["protected_ceiling_exclusive"] != "2026-01-01"
    ):
        raise ValueError("MOEX CNY carry source invariant drift")
    return config


def spot_url(config: dict[str, Any], start: int) -> str:
    source = config["source"]["spot"]
    query = {
        "iss.meta": "off",
        "from": source["from"],
        "till": source["till"],
        "start": start,
    }
    return f"{source['endpoint']}?{urlencode(query)}"


def futures_url(config: dict[str, Any], secid: str, start: int) -> str:
    source = config["source"]["futures"]
    if secid not in source["exact_contracts"]:
        raise ValueError("undeclared CNY futures contract")
    endpoint = source["history_endpoint_template"].format(secid=secid)
    query = {
        "iss.meta": "off",
        "from": source["from"],
        "till": source["till"],
        "start": start,
    }
    return f"{endpoint}?{urlencode(query)}"


def description_url(config: dict[str, Any], secid: str) -> str:
    if secid not in config["source"]["futures"]["exact_contracts"]:
        raise ValueError("undeclared CNY futures contract")
    return config["source"]["futures"]["description_endpoint_template"].format(secid=secid)


def _block(payload: dict[str, Any], name: str) -> tuple[list[str], list[list[Any]]]:
    item = payload.get(name)
    if not isinstance(item, dict) or not isinstance(item.get("columns"), list):
        raise ValueError(f"missing MOEX {name} block")
    rows = item.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX {name} rows")
    return [str(value) for value in item["columns"]], rows


def verify_description(raw: bytes, secid: str, config: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _block(payload, "description")
    frame = pd.DataFrame(rows, columns=columns)
    if not {"name", "value"}.issubset(frame.columns):
        raise ValueError("CNY futures description schema drift")
    values = dict(zip(frame["name"].astype(str), frame["value"], strict=True))
    boards_columns, boards_rows = _block(payload, "boards")
    boards = pd.DataFrame(boards_rows, columns=boards_columns)
    source = config["source"]["futures"]
    expected_expiry = source["exact_contracts"][secid]
    if (
        str(values.get("SECID")) != secid
        or str(values.get("ASSETCODE")) != source["asset_code"]
        or str(values.get("LSTTRADE")) != expected_expiry
        or int(float(values.get("LOTSIZE"))) != int(source["lot_size_cny"])
        or str(values.get("TYPE")) != source["contract_type"]
        or source["board"] not in set(boards["boardid"].astype(str))
    ):
        raise ValueError(f"CNY futures metadata identity mismatch: {secid}")
    return {
        "security_id": secid,
        "asset_code": str(values["ASSETCODE"]),
        "expiration_date": expected_expiry,
        "lot_size_cny": int(float(values["LOTSIZE"])),
    }


def normalize_page(
    raw: bytes,
    *,
    kind: str,
    secid: str,
    expected_start: int,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _block(payload, "history")
    cursor_columns, cursor_rows = _block(payload, "history.cursor")
    if cursor_columns != ["INDEX", "TOTAL", "PAGESIZE"] or len(cursor_rows) != 1:
        raise ValueError("CNY source cursor schema drift")
    cursor = dict(zip(cursor_columns, cursor_rows[0], strict=True))
    total, page_size = int(cursor["TOTAL"]), int(cursor["PAGESIZE"])
    if int(cursor["INDEX"]) != expected_start:
        raise ValueError("CNY source cursor index drift")
    if kind == "spot":
        source = config["source"]["spot"]
        required = config["required_spot_columns"]
        if total != int(source["total_rows_observed"]):
            raise ValueError("CNY spot cursor total drift")
        expiration = pd.NaT
        lot_size = int(config["source"]["futures"]["lot_size_cny"])
        expected_board = source["board"]
        expected_asset = "CNY"
    elif kind == "futures":
        source = config["source"]["futures"]
        required = config["required_futures_columns"]
        expiration = pd.Timestamp(source["exact_contracts"][secid])
        lot_size = int(source["lot_size_cny"])
        expected_board = source["board"]
        expected_asset = source["asset_code"]
    else:
        raise ValueError("unknown CNY source instrument kind")
    if page_size != int(source["page_size_observed"]):
        raise ValueError("CNY source cursor page-size drift")
    if set(required) - set(columns):
        raise ValueError("CNY source history schema drift")
    frame = pd.DataFrame(rows, columns=columns).loc[:, required].copy()
    if expected_start < total and frame.empty:
        raise ValueError("unexpected empty CNY source page")
    dates = pd.to_datetime(frame["TRADEDATE"], errors="raise")
    available = (dates.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).dt.tz_convert(
        "UTC"
    )

    def numeric(column: str) -> pd.Series:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce")
        return pd.Series(float("nan"), index=frame.index, dtype=float)

    output = pd.DataFrame(
        {
            "instrument_kind": kind,
            "security_id": frame["SECID"].astype("string"),
            "board_id": frame["BOARDID"].astype("string"),
            "asset_code": expected_asset,
            "trade_date": dates,
            "expiration_date": expiration,
            "lot_size_cny": lot_size,
            "open": pd.to_numeric(frame["OPEN"], errors="coerce"),
            "low": pd.to_numeric(frame["LOW"], errors="coerce"),
            "high": pd.to_numeric(frame["HIGH"], errors="coerce"),
            "close": pd.to_numeric(frame["CLOSE"], errors="coerce"),
            "settle": numeric("SETTLEPRICE"),
            "weighted_average_price": pd.to_numeric(frame["WAPRICE"], errors="coerce"),
            "volume": numeric("VOLUME"),
            "number_of_trades": pd.to_numeric(frame["NUMTRADES"], errors="coerce"),
            "open_interest": numeric("OPENPOSITION"),
            "available_at_utc": available,
            "retrieved_at_utc": retrieved_at.tz_convert("UTC").isoformat(),
            "access_mode": config["source"]["access_mode"],
        },
        columns=OUTPUT_COLUMNS,
    )
    if not output.empty and (
        set(output["security_id"].astype(str)) != {secid}
        or set(output["board_id"].astype(str)) != {expected_board}
    ):
        raise ValueError("CNY source page identity mismatch")
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("derived outcome escaped into CNY source")
    return output, total, page_size


def _fetch_pages(
    client: SessionLike,
    config: dict[str, Any],
    kind: str,
    secid: str,
    retrieval: pd.Timestamp,
) -> tuple[pd.DataFrame, list[tuple[int, str, bytes]]]:
    start, total = 0, None
    frames, raw_pages = [], []
    while total is None or start < total:
        url = spot_url(config, start) if kind == "spot" else futures_url(config, secid, start)
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        raw = bytes(response.content)
        frame, observed_total, page_size = normalize_page(
            raw,
            kind=kind,
            secid=secid,
            expected_start=start,
            retrieved_at=retrieval,
            config=config,
        )
        if total is not None and total != observed_total:
            raise ValueError("CNY source total changed during pagination")
        total = observed_total
        frames.append(frame)
        raw_pages.append((start, url, raw))
        start += page_size
    return pd.concat(frames, ignore_index=True), raw_pages


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
    spot_secid = config["source"]["spot"]["security"]
    spot, spot_raw = _fetch_pages(client, config, "spot", spot_secid, retrieval)
    futures_frames, descriptions, futures_raw = [], {}, {}
    for secid in config["source"]["futures"]["exact_contracts"]:
        url = description_url(config, secid)
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        raw_description = bytes(response.content)
        verify_description(raw_description, secid, config)
        descriptions[secid] = (url, raw_description)
        frame, pages = _fetch_pages(client, config, "futures", secid, retrieval)
        futures_frames.append(frame)
        futures_raw[secid] = pages
    futures = pd.concat(futures_frames, ignore_index=True)
    upper = pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"])
    if (
        spot.duplicated(["security_id", "trade_date"]).any()
        or futures.duplicated(["security_id", "trade_date"]).any()
        or spot["trade_date"].max() >= upper
        or futures["trade_date"].max() >= upper
    ):
        raise ValueError("CNY source identity or temporal mismatch")

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable CNY source exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        raw_manifest = {"spot": [], "descriptions": {}, "futures": {}}

        def persist(path: Path, payload: bytes, url: str, extra: dict[str, Any]) -> dict[str, Any]:
            path.write_bytes(gzip.compress(payload, mtime=0))
            return {
                **extra,
                "path": path.name,
                "url": url,
                "response_bytes": len(payload),
                "response_sha256": _sha_bytes(payload),
                "stored_bytes": path.stat().st_size,
                "stored_sha256": _sha_file(path),
            }

        for start, url, raw in spot_raw:
            raw_manifest["spot"].append(
                persist(temporary / f"raw_spot_{start:06d}.json.gz", raw, url, {"start": start})
            )
        for secid, (url, raw) in descriptions.items():
            raw_manifest["descriptions"][secid] = persist(
                temporary / f"raw_description_{secid}.json.gz", raw, url, {"secid": secid}
            )
        for secid, pages in futures_raw.items():
            raw_manifest["futures"][secid] = []
            for start, url, raw in pages:
                raw_manifest["futures"][secid].append(
                    persist(
                        temporary / f"raw_futures_{secid}_{start:06d}.json.gz",
                        raw,
                        url,
                        {"secid": secid, "start": start},
                    )
                )
        spot_path, futures_path = temporary / "spot.parquet", temporary / "futures.parquet"
        spot.sort_values("trade_date", ignore_index=True).to_parquet(spot_path, index=False)
        futures.sort_values(["security_id", "trade_date"], ignore_index=True).to_parquet(
            futures_path, index=False
        )
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "contains_basis_returns_labels_targets_or_pnl": False,
            "counts": {
                "spot_rows": len(spot),
                "futures_rows": len(futures),
                "futures_contracts": futures["security_id"].nunique(),
                "spot_nonpositive_rows": int((spot[["open", "close"]].min(axis=1) <= 0).sum()),
                "futures_nonpositive_rows": int(
                    (futures[["open", "close"]].min(axis=1) <= 0).sum()
                ),
            },
            "raw": raw_manifest,
            "processed": {
                "spot": {
                    "path": spot_path.name,
                    "bytes": spot_path.stat().st_size,
                    "sha256": _sha_file(spot_path),
                    "rows": len(spot),
                },
                "futures": {
                    "path": futures_path.name,
                    "bytes": futures_path.stat().st_size,
                    "sha256": _sha_file(futures_path),
                    "rows": len(futures),
                },
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(output_root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(output_root)
    _write_json(output_root / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("MOEX CNY source audit failed")
    return output_root


def audit(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "outcome_free": manifest["contains_basis_returns_labels_targets_or_pnl"] is False,
    }

    def load_raw(item: dict[str, Any], label: str) -> bytes:
        path = output_root / item["path"]
        payload = gzip.decompress(path.read_bytes())
        checks[f"{label}_stored_exact"] = (
            path.stat().st_size == item["stored_bytes"]
            and _sha_file(path) == item["stored_sha256"]
        )
        checks[f"{label}_response_exact"] = (
            len(payload) == item["response_bytes"]
            and _sha_bytes(payload) == item["response_sha256"]
        )
        return payload

    spot_frames = []
    spot_secid = config["source"]["spot"]["security"]
    for item in manifest["raw"]["spot"]:
        payload = load_raw(item, f"spot_{item['start']}")
        frame, _, _ = normalize_page(
            payload,
            kind="spot",
            secid=spot_secid,
            expected_start=int(item["start"]),
            retrieved_at=retrieval,
            config=config,
        )
        spot_frames.append(frame)
    futures_frames = []
    for secid, item in manifest["raw"]["descriptions"].items():
        verify_description(load_raw(item, f"description_{secid}"), secid, config)
    for secid, pages in manifest["raw"]["futures"].items():
        for item in pages:
            payload = load_raw(item, f"futures_{secid}_{item['start']}")
            frame, _, _ = normalize_page(
                payload,
                kind="futures",
                secid=secid,
                expected_start=int(item["start"]),
                retrieved_at=retrieval,
                config=config,
            )
            futures_frames.append(frame)
    rebuilt = {
        "spot": pd.concat(spot_frames, ignore_index=True).sort_values(
            "trade_date", ignore_index=True
        ),
        "futures": pd.concat(futures_frames, ignore_index=True).sort_values(
            ["security_id", "trade_date"], ignore_index=True
        ),
    }
    for name, frame in rebuilt.items():
        item = manifest["processed"][name]
        path = output_root / item["path"]
        stored = pd.read_parquet(path)
        stored_compare = stored.copy()
        frame_compare = frame.copy()
        for column in frame.columns:
            if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(
                frame[column]
            ):
                stored_compare[column] = stored_compare[column].astype("string")
                frame_compare[column] = frame_compare[column].astype("string")
        try:
            pd.testing.assert_frame_equal(stored_compare, frame_compare, check_dtype=False)
            replay_exact = True
        except AssertionError:
            replay_exact = False
        checks[f"{name}_processed_exact"] = (
            path.stat().st_size == item["bytes"] and _sha_file(path) == item["sha256"]
        )
        checks[f"{name}_rows_exact"] = len(stored) == int(item["rows"])
        checks[f"{name}_raw_replay_exact"] = replay_exact
        checks[f"{name}_identity_unique"] = not stored.duplicated(
            ["security_id", "trade_date"]
        ).any()
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.audit:
        checks = audit(args.output_root)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
