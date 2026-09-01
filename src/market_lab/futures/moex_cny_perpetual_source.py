"""Collect immutable MOEX CNYRUBF perpetual futures and SWAPRATE history."""

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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_cny_perpetual_source_v1.yaml"
CONFIG_SHA256: Final[str] = "45d3c4ead342423fb9be033b97cbcc6d7b57adc1ef37ee68c2d083a91eb7b265"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/fx_basis/moex-cny-perpetual-current-vintage-v1"
)
USER_AGENT: Final[str] = "market-lab-cny-perpetual-source/1.0 (MOEX research)"
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "security_id",
    "board_id",
    "asset_code",
    "trade_date",
    "lot_size_cny",
    "open",
    "low",
    "high",
    "close",
    "settle",
    "swap_rate",
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
        raise ValueError("CNY perpetual source config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_cny_perpetual_source_v1"
        or config.get("live_trading_allowed") is not False
        or config["hypothesis_for_later_protocol"]["this_protocol_computes_signal_return_or_pnl"]
        is not False
        or config["temporal_semantics"]["same_day_swaprate_use"] != "forbidden"
    ):
        raise ValueError("CNY perpetual source invariant drift")
    return config


def history_url(config: dict[str, Any], start: int) -> str:
    source = config["source"]
    query = {
        "iss.meta": "off",
        "from": source["from"],
        "till": source["till"],
        "start": start,
    }
    return f"{source['history_endpoint']}?{urlencode(query)}"


def _block(payload: dict[str, Any], name: str) -> tuple[list[str], list[list[Any]]]:
    item = payload.get(name)
    if not isinstance(item, dict) or not isinstance(item.get("columns"), list):
        raise ValueError(f"missing MOEX {name} block")
    rows = item.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX {name} rows")
    return [str(value) for value in item["columns"]], rows


def verify_description(raw: bytes, config: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _block(payload, "description")
    frame = pd.DataFrame(rows, columns=columns)
    if not {"name", "value"}.issubset(frame.columns):
        raise ValueError("CNY perpetual description schema drift")
    values = dict(zip(frame["name"].astype(str), frame["value"], strict=True))
    boards_columns, boards_rows = _block(payload, "boards")
    boards = pd.DataFrame(boards_rows, columns=boards_columns)
    source = config["source"]
    if (
        str(values.get("SECID")) != source["security"]
        or str(values.get("ASSETCODE")) != source["asset_code"]
        or str(values.get("FRSTTRADE")) != source["first_trade"]
        or str(values.get("LSTTRADE")) != source["declared_last_trade"]
        or int(float(values.get("LOTSIZE"))) != int(source["lot_size_cny"])
        or str(values.get("TYPE")) != "futures"
        or source["board"] not in set(boards["boardid"].astype(str))
    ):
        raise ValueError("CNY perpetual metadata identity mismatch")
    return {
        "security_id": source["security"],
        "asset_code": source["asset_code"],
        "lot_size_cny": int(source["lot_size_cny"]),
    }


def normalize_page(
    raw: bytes,
    expected_start: int,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _block(payload, "history")
    required = config["required_history_columns"]
    if set(required) - set(columns):
        raise ValueError("CNY perpetual history schema drift")
    cursor_columns, cursor_rows = _block(payload, "history.cursor")
    if cursor_columns != ["INDEX", "TOTAL", "PAGESIZE"] or len(cursor_rows) != 1:
        raise ValueError("CNY perpetual cursor schema drift")
    cursor = dict(zip(cursor_columns, cursor_rows[0], strict=True))
    source = config["source"]
    total, page_size = int(cursor["TOTAL"]), int(cursor["PAGESIZE"])
    if (
        int(cursor["INDEX"]) != expected_start
        or total != int(source["total_rows_observed"])
        or page_size != int(source["page_size_observed"])
    ):
        raise ValueError("CNY perpetual cursor value drift")
    frame = pd.DataFrame(rows, columns=columns).loc[:, required].copy()
    if expected_start < total and frame.empty:
        raise ValueError("unexpected empty CNY perpetual page")
    dates = pd.to_datetime(frame["TRADEDATE"], errors="raise")
    available = (dates.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).dt.tz_convert(
        "UTC"
    )
    output = pd.DataFrame(
        {
            "security_id": frame["SECID"].astype("string"),
            "board_id": frame["BOARDID"].astype("string"),
            "asset_code": frame["ASSETCODE"].astype("string"),
            "trade_date": dates,
            "lot_size_cny": int(source["lot_size_cny"]),
            "open": pd.to_numeric(frame["OPEN"], errors="coerce"),
            "low": pd.to_numeric(frame["LOW"], errors="coerce"),
            "high": pd.to_numeric(frame["HIGH"], errors="coerce"),
            "close": pd.to_numeric(frame["CLOSE"], errors="coerce"),
            "settle": pd.to_numeric(frame["SETTLEPRICE"], errors="coerce"),
            "swap_rate": pd.to_numeric(frame["SWAPRATE"], errors="coerce"),
            "weighted_average_price": pd.to_numeric(frame["WAPRICE"], errors="coerce"),
            "volume": pd.to_numeric(frame["VOLUME"], errors="coerce"),
            "number_of_trades": pd.to_numeric(frame["NUMTRADES"], errors="coerce"),
            "open_interest": pd.to_numeric(frame["OPENPOSITION"], errors="coerce"),
            "available_at_utc": available,
            "retrieved_at_utc": retrieved_at.tz_convert("UTC").isoformat(),
            "access_mode": source["access_mode"],
        },
        columns=OUTPUT_COLUMNS,
    )
    if not output.empty and (
        set(output["security_id"].astype(str)) != {source["security"]}
        or set(output["board_id"].astype(str)) != {source["board"]}
        or set(output["asset_code"].astype(str)) != {source["asset_code"]}
    ):
        raise ValueError("CNY perpetual page identity mismatch")
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("derived outcome escaped into CNY perpetual source")
    return output, total, page_size


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
    description_response = client.get(
        config["source"]["description_endpoint"],
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    )
    description_response.raise_for_status()
    description_raw = bytes(description_response.content)
    verify_description(description_raw, config)
    start, total = 0, None
    frames, pages = [], []
    while total is None or start < total:
        url = history_url(config, start)
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        raw = bytes(response.content)
        frame, observed_total, page_size = normalize_page(raw, start, retrieval, config)
        if total is not None and total != observed_total:
            raise ValueError("CNY perpetual total changed during pagination")
        total = observed_total
        frames.append(frame)
        pages.append((start, url, raw))
        start += page_size
    history = pd.concat(frames, ignore_index=True).sort_values("trade_date", ignore_index=True)
    upper = pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"])
    if history["trade_date"].duplicated().any() or history["trade_date"].max() >= upper:
        raise ValueError("CNY perpetual identity or temporal mismatch")

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable CNY perpetual source exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
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

        raw_description = persist(
            temporary / "raw_description.json.gz",
            description_raw,
            config["source"]["description_endpoint"],
            {},
        )
        raw_pages = [
            persist(
                temporary / f"raw_history_{start:06d}.json.gz",
                raw,
                url,
                {"start": start},
            )
            for start, url, raw in pages
        ]
        processed = temporary / "perpetual.parquet"
        history.to_parquet(processed, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "contains_signal_basis_returns_labels_targets_or_pnl": False,
            "counts": {
                "rows": len(history),
                "pages": len(pages),
                "first_trade_date": history["trade_date"].min().date().isoformat(),
                "last_trade_date": history["trade_date"].max().date().isoformat(),
                "positive_trade_rows": int((history["number_of_trades"] > 0).sum()),
                "swap_rate_nonmissing_rows": int(history["swap_rate"].notna().sum()),
            },
            "raw": {"description": raw_description, "history": raw_pages},
            "processed": {
                "path": processed.name,
                "bytes": processed.stat().st_size,
                "sha256": _sha_file(processed),
                "rows": len(history),
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
        raise ValueError("CNY perpetual source audit failed")
    return output_root


def audit(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "outcome_free": manifest["contains_signal_basis_returns_labels_targets_or_pnl"]
        is False,
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

    verify_description(load_raw(manifest["raw"]["description"], "description"), config)
    frames = []
    for item in manifest["raw"]["history"]:
        frame, _, _ = normalize_page(
            load_raw(item, f"history_{item['start']}"),
            int(item["start"]),
            retrieval,
            config,
        )
        frames.append(frame)
    rebuilt = pd.concat(frames, ignore_index=True).sort_values("trade_date", ignore_index=True)
    item = manifest["processed"]
    path = output_root / item["path"]
    stored = pd.read_parquet(path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    checks.update(
        {
            "processed_exact": path.stat().st_size == item["bytes"]
            and _sha_file(path) == item["sha256"],
            "rows_exact": len(stored) == int(item["rows"]),
            "raw_replay_exact": replay_exact,
            "identity_unique": not stored["trade_date"].duplicated().any(),
            "swap_rate_not_imputed": int(stored["swap_rate"].notna().sum())
            == int(manifest["counts"]["swap_rate_nonmissing_rows"]),
        }
    )
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
