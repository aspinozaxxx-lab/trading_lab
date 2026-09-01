"""Collect immutable current-vintage MOEX USD/RUB TOM daily history."""

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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_fx_spot_source_v1.yaml"
CONFIG_SHA256: Final[str] = "15af78e5e9383a9fd357bd088738009bf0af9213a6975423ffa9942afdf45eb9"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/fx_basis/moex-usdrub-tom-current-vintage-2018-2025-v1"
)
USER_AGENT: Final[str] = "market-lab-fx-spot-source/1.0 (MOEX research)"
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "board_id",
    "trade_date",
    "short_name",
    "security_id",
    "open",
    "low",
    "high",
    "close",
    "number_of_trades",
    "weighted_average_price",
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
        raise ValueError("MOEX FX spot source config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_fx_spot_source_v1"
        or config.get("live_trading_allowed") is not False
        or config["hypothesis_for_later_protocol"]["this_protocol_computes_returns_targets_or_pnl"]
        is not False
        or config["temporal_semantics"]["protected_ceiling_exclusive"] != "2026-01-01"
    ):
        raise ValueError("MOEX FX spot source protocol invariant drift")
    return config


def request_url(config: dict[str, Any], start: int) -> str:
    if start < 0 or start % int(config["source"]["page_size_observed_in_transport_probe"]):
        raise ValueError("invalid MOEX FX spot cursor start")
    query = {
        **config["source"]["query"],
        "from": config["source"]["from"],
        "till": config["source"]["till"],
        "start": start,
    }
    return f"{config['source']['endpoint']}?{urlencode(query)}"


def _json_block(payload: dict[str, Any], name: str) -> tuple[list[str], list[list[Any]]]:
    block = payload.get(name)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        raise ValueError(f"missing MOEX {name} block")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX {name} rows")
    return [str(value) for value in block["columns"]], rows


def normalize_page(
    raw: bytes,
    expected_start: int,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _json_block(payload, "history")
    required = config["required_history_columns"]
    if set(required) - set(columns):
        raise ValueError("MOEX FX spot history schema drift")
    cursor_columns, cursor_rows = _json_block(payload, "history.cursor")
    if cursor_columns != ["INDEX", "TOTAL", "PAGESIZE"] or len(cursor_rows) != 1:
        raise ValueError("MOEX FX spot cursor schema drift")
    cursor = dict(zip(cursor_columns, cursor_rows[0], strict=True))
    total = int(cursor["TOTAL"])
    page_size = int(cursor["PAGESIZE"])
    if (
        int(cursor["INDEX"]) != expected_start
        or total != int(config["source"]["total_rows_observed_in_transport_probe"])
        or page_size != int(config["source"]["page_size_observed_in_transport_probe"])
    ):
        raise ValueError("MOEX FX spot cursor value drift")
    frame = pd.DataFrame(rows, columns=columns).loc[:, required].copy()
    if expected_start < total and frame.empty:
        raise ValueError("unexpected empty MOEX FX spot page")
    trade_dates = pd.to_datetime(frame["TRADEDATE"], errors="raise")
    available = (
        trade_dates.dt.tz_localize("Europe/Moscow")
        + pd.Timedelta(days=1)
    ).dt.tz_convert("UTC")
    output = pd.DataFrame(
        {
            "board_id": frame["BOARDID"].astype("string"),
            "trade_date": trade_dates,
            "short_name": frame["SHORTNAME"].astype("string"),
            "security_id": frame["SECID"].astype("string"),
            "open": pd.to_numeric(frame["OPEN"], errors="coerce"),
            "low": pd.to_numeric(frame["LOW"], errors="coerce"),
            "high": pd.to_numeric(frame["HIGH"], errors="coerce"),
            "close": pd.to_numeric(frame["CLOSE"], errors="coerce"),
            "number_of_trades": pd.to_numeric(frame["NUMTRADES"], errors="coerce"),
            "weighted_average_price": pd.to_numeric(frame["WAPRICE"], errors="coerce"),
            "available_at_utc": available,
            "retrieved_at_utc": retrieved_at.tz_convert("UTC").isoformat(),
            "access_mode": config["source"]["access_mode"],
        },
        columns=OUTPUT_COLUMNS,
    )
    if not output.empty:
        if set(output["board_id"].astype(str)) != {config["source"]["board"]}:
            raise ValueError("unexpected MOEX FX spot board")
        if set(output["security_id"].astype(str)) != {config["source"]["security"]}:
            raise ValueError("unexpected MOEX FX spot security")
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("derived outcome column escaped into MOEX FX spot source")
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
    frames: list[pd.DataFrame] = []
    raw_pages: list[tuple[int, str, bytes]] = []
    start = 0
    total: int | None = None
    while total is None or start < total:
        url = request_url(config, start)
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        raw = bytes(response.content)
        frame, observed_total, page_size = normalize_page(raw, start, retrieval, config)
        if total is not None and observed_total != total:
            raise ValueError("MOEX FX spot cursor total changed during collection")
        total = observed_total
        frames.append(frame)
        raw_pages.append((start, url, raw))
        start += page_size
    history = pd.concat(frames, ignore_index=True).sort_values(
        "trade_date", kind="stable", ignore_index=True
    )
    lower = pd.Timestamp(config["source"]["from"])
    upper = pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"])
    if (
        len(history) != total
        or history["trade_date"].duplicated().any()
        or history["trade_date"].min() < lower
        or history["trade_date"].max() >= upper
    ):
        raise ValueError("MOEX FX spot coverage or identity mismatch")

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable MOEX FX spot output already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        raw_artifacts = []
        for page_start, url, payload in raw_pages:
            path = temporary / f"raw_page_{page_start:06d}.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            raw_artifacts.append(
                {
                    "start": page_start,
                    "url": url,
                    "path": path.name,
                    "response_bytes": len(payload),
                    "response_sha256": _sha_bytes(payload),
                    "stored_bytes": path.stat().st_size,
                    "stored_sha256": _sha_file(path),
                }
            )
        processed = temporary / "spot_history.parquet"
        history.to_parquet(processed, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "current_vintage": True,
            "contains_returns_labels_targets_pnl_or_basis": False,
            "counts": {
                "rows": len(history),
                "pages": len(raw_pages),
                "first_trade_date": history["trade_date"].min().date().isoformat(),
                "last_trade_date": history["trade_date"].max().date().isoformat(),
            },
            "raw": raw_artifacts,
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
        raise ValueError("MOEX FX spot source audit failed")
    return output_root


def audit(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    replay: list[pd.DataFrame] = []
    checks: dict[str, bool] = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "target_and_basis_free": manifest["contains_returns_labels_targets_pnl_or_basis"]
        is False,
    }
    for item in manifest["raw"]:
        path = output_root / item["path"]
        payload = gzip.decompress(path.read_bytes())
        checks[f"raw_{item['start']}_stored_exact"] = (
            path.stat().st_size == item["stored_bytes"]
            and _sha_file(path) == item["stored_sha256"]
        )
        checks[f"raw_{item['start']}_response_exact"] = (
            len(payload) == item["response_bytes"]
            and _sha_bytes(payload) == item["response_sha256"]
        )
        frame, _, _ = normalize_page(payload, int(item["start"]), retrieval, config)
        replay.append(frame)
    rebuilt = pd.concat(replay, ignore_index=True).sort_values(
        "trade_date", kind="stable", ignore_index=True
    )
    processed_item = manifest["processed"]
    processed_path = output_root / processed_item["path"]
    stored = pd.read_parquet(processed_path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    upper = pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"])
    checks.update(
        {
            "processed_exact": processed_path.stat().st_size == processed_item["bytes"]
            and _sha_file(processed_path) == processed_item["sha256"],
            "rows_exact": len(stored) == int(processed_item["rows"]),
            "raw_replay_exact": replay_exact,
            "identity_unique": not stored["trade_date"].duplicated().any(),
            "protected_ceiling_exact": bool((stored["trade_date"] < upper).all()),
            "availability_after_trade_date": bool(
                (
                    pd.to_datetime(stored["available_at_utc"], utc=True)
                    > stored["trade_date"].dt.tz_localize("UTC")
                ).all()
            ),
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
