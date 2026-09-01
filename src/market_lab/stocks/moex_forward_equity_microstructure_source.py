"""Capture immutable target-free MOEX equity microstructure snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-equity-microstructure-v1"
)
AUTHENTICATED_ISS_ROOT: Final[str] = "https://apim.moex.com/iss"
TOKEN_ENVIRONMENT_VARIABLE: Final[str] = "MOEX_ALGOPACK_TOKEN"
USER_AGENT: Final[str] = "market-lab-forward-equity-microstructure/1.0 (MOEX research)"
DELIVERY_BUFFER: Final[pd.Timedelta] = pd.Timedelta(minutes=1)
TICKERS: Final[tuple[str, ...]] = (
    "AFKS",
    "AFLT",
    "ALRS",
    "BSPB",
    "CBOM",
    "CHMF",
    "ENPG",
    "GAZP",
    "GMKN",
    "IRAO",
    "LKOH",
    "MAGN",
    "MGNT",
    "MOEX",
    "MTSS",
    "NLMK",
    "NVTK",
    "PHOR",
    "PLZL",
    "ROSN",
    "RTKM",
    "RUAL",
    "SBER",
    "SBERP",
    "SNGS",
    "SNGSP",
    "TATN",
    "TATNP",
    "TRNFP",
    "VTBR",
)
TRADESTATS_COLUMNS: Final[tuple[str, ...]] = (
    "tradedate",
    "tradetime",
    "secid",
    "vol",
    "val",
    "trades",
    "trades_b",
    "trades_s",
    "val_b",
    "val_s",
    "vol_b",
    "vol_s",
    "disb",
    "SYSTIME",
)
ORDERSTATS_COLUMNS: Final[tuple[str, ...]] = (
    "tradedate",
    "tradetime",
    "secid",
    "put_orders_b",
    "put_orders_s",
    "put_val_b",
    "put_val_s",
    "put_vol_b",
    "put_vol_s",
    "put_vol",
    "put_val",
    "put_orders",
    "cancel_orders_b",
    "cancel_orders_s",
    "cancel_val_b",
    "cancel_val_s",
    "cancel_vol_b",
    "cancel_vol_s",
    "cancel_vol",
    "cancel_val",
    "cancel_orders",
    "SYSTIME",
)
OBSTATS_COLUMNS: Final[tuple[str, ...]] = (
    "tradedate",
    "tradetime",
    "secid",
    "spread_bbo",
    "spread_lv10",
    "spread_1mio",
    "levels_b",
    "levels_s",
    "vol_b",
    "vol_s",
    "val_b",
    "val_s",
    "imbalance_vol_bbo",
    "imbalance_val_bbo",
    "imbalance_vol",
    "imbalance_val",
    "SYSTIME",
)
DATASET_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "tradestats": TRADESTATS_COLUMNS,
    "orderstats": ORDERSTATS_COLUMNS,
    "obstats": OBSTATS_COLUMNS,
}
FORBIDDEN_PRICE_OUTCOME_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "pr_open",
        "pr_high",
        "pr_low",
        "pr_close",
        "pr_std",
        "pr_vwap",
        "pr_change",
        "pr_vwap_b",
        "pr_vwap_s",
        "put_vwap_b",
        "put_vwap_s",
        "cancel_vwap_b",
        "cancel_vwap_s",
        "vwap_b",
        "vwap_s",
        "vwap_b_1mio",
        "vwap_s_1mio",
        "return",
        "label",
        "target",
        "pnl",
    }
)


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class SessionLike(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> ResponseLike: ...


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def _source_date(value: str | pd.Timestamp) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("Europe/Moscow").tz_localize(None)
    parsed = parsed.normalize()
    if parsed < pd.Timestamp("2026-01-01"):
        raise ValueError("forward equity source_date must be 2026 or later")
    return parsed


def _retrieval_time(value: str | pd.Timestamp | datetime | None) -> pd.Timestamp:
    parsed = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if parsed.tzinfo is None:
        raise ValueError("retrieval time must include an explicit timezone")
    return parsed.tz_convert("UTC")


def dataset_url(dataset: str, source_date: pd.Timestamp) -> str:
    if dataset not in DATASET_COLUMNS:
        raise ValueError(f"unsupported equity dataset: {dataset}")
    columns = DATASET_COLUMNS[dataset]
    if set(columns) & FORBIDDEN_PRICE_OUTCOME_COLUMNS:
        raise ValueError("equity request escaped the target-free schema")
    query = urlencode(
        {
            "date": source_date.date().isoformat(),
            "latest": 1,
            "iss.meta": "off",
            "iss.only": "data",
            "data.columns": ",".join(columns),
        }
    )
    return f"{AUTHENTICATED_ISS_ROOT}/datashop/algopack/eq/{dataset}.json?{query}"


def _request(
    url: str,
    token: str,
    session: SessionLike | None,
) -> tuple[dict[str, Any], bytes]:
    if not token.strip():
        raise ValueError("MOEX ALGOPACK bearer token is required for equity microstructure")
    client = requests.Session() if session is None else session
    response = client.get(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("MOEX equity response is not a JSON object")
    return payload, bytes(response.content)


def _table(payload: dict[str, Any], expected: tuple[str, ...]) -> pd.DataFrame:
    block = payload.get("data")
    if not isinstance(block, dict):
        raise ValueError("MOEX equity response lacks data block")
    columns = block.get("columns")
    rows = block.get("data")
    if columns != list(expected) or not isinstance(rows, list):
        raise ValueError("MOEX equity response escaped the closed schema")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("MOEX equity response contains a malformed row")
    return pd.DataFrame(rows, columns=columns)


def normalize_dataset(
    frame: pd.DataFrame,
    dataset: str,
    retrieved_at: pd.Timestamp,
) -> pd.DataFrame:
    expected = DATASET_COLUMNS[dataset]
    if tuple(frame.columns) != expected:
        raise ValueError("equity normalization input schema mismatch")
    if set(frame.columns) & FORBIDDEN_PRICE_OUTCOME_COLUMNS:
        raise ValueError("forbidden price/outcome field entered equity normalization")
    normalized = frame.loc[frame["secid"].astype(str).isin(TICKERS)].copy()
    normalized["dataset"] = dataset
    normalized["exchange_systime"] = pd.to_datetime(
        normalized.pop("SYSTIME"), errors="coerce"
    ).dt.tz_localize("Europe/Moscow", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    if normalized["exchange_systime"].isna().any():
        raise ValueError("MOEX equity SYSTIME is missing or invalid")
    normalized["retrieved_at"] = retrieved_at
    exchange_available = normalized["exchange_systime"] + DELIVERY_BUFFER
    normalized["available_at"] = exchange_available.where(
        exchange_available >= retrieved_at, retrieved_at
    )
    normalized["access_mode"] = "algopack_subscribed_realtime"
    normalized["contains_absolute_price_return_target_or_pnl"] = False
    return normalized


def collect_snapshot(
    output_root: Path,
    source_date: str | pd.Timestamp,
    *,
    token: str,
    session: SessionLike | None = None,
    retrieved_at_utc: str | pd.Timestamp | datetime | None = None,
) -> Path:
    source_day = _source_date(source_date)
    retrieved = _retrieval_time(retrieved_at_utc)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    snapshot_name = f"snapshot_{retrieved.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / snapshot_name
    if final.exists():
        raise FileExistsError(f"immutable equity snapshot exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{snapshot_name}-", dir=output_root))
    request_records: list[dict[str, Any]] = []
    normalized_frames: list[pd.DataFrame] = []
    try:
        raw_directory = temporary / "raw"
        raw_directory.mkdir()
        for dataset, columns in DATASET_COLUMNS.items():
            url = dataset_url(dataset, source_day)
            payload, raw = _request(url, token, session)
            raw_path = raw_directory / f"{dataset}.json.gz"
            with raw_path.open("wb") as raw_stream, gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw_stream,
                mtime=0,
            ) as stream:
                stream.write(raw)
            frame = _table(payload, columns)
            normalized = normalize_dataset(frame, dataset, retrieved)
            normalized_frames.append(normalized)
            request_records.append(
                {
                    "dataset": dataset,
                    "url": url,
                    "raw_path": str(raw_path.relative_to(temporary)).replace("\\", "/"),
                    "raw_bytes_uncompressed": len(raw),
                    "raw_gzip_bytes": raw_path.stat().st_size,
                    "raw_gzip_sha256": sha256_file(raw_path),
                    "response_rows": len(frame),
                    "universe_rows": len(normalized),
                }
            )
        combined = pd.concat(normalized_frames, ignore_index=True, sort=False)
        combined.sort_values(
            ["dataset", "secid", "exchange_systime"], kind="stable", inplace=True
        )
        combined.reset_index(drop=True, inplace=True)
        normalized_path = temporary / "microstructure.parquet"
        combined.to_parquet(normalized_path, index=False, compression="zstd")
        _write_json(temporary / "requests.json", request_records)
        manifest = {
            "protocol": "moex-forward-equity-microstructure-v1",
            "source_date": source_day.date().isoformat(),
            "retrieved_at_utc": retrieved.isoformat(),
            "access_mode": "algopack_subscribed_realtime",
            "token_environment_variable": TOKEN_ENVIRONMENT_VARIABLE,
            "token_persisted": False,
            "target_free": True,
            "ticker_count": len(TICKERS),
            "tickers": list(TICKERS),
            "datasets": list(DATASET_COLUMNS),
            "request_count": len(request_records),
            "normalized_rows": len(combined),
            "normalized_path": normalized_path.name,
            "normalized_bytes": normalized_path.stat().st_size,
            "normalized_sha256": sha256_file(normalized_path),
            "implementation_sha256": sha256_file(MODULE_PATH),
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_snapshot(snapshot_directory: Path) -> dict[str, bool]:
    snapshot_directory = snapshot_directory.resolve()
    manifest_path = snapshot_directory / "manifest.json"
    requests_path = snapshot_directory / "requests.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    requests_payload = json.loads(requests_path.read_text(encoding="utf-8-sig"))
    normalized_path = snapshot_directory / manifest["normalized_path"]
    normalized = pd.read_parquet(normalized_path)
    raw_exact = True
    for item in requests_payload:
        path = snapshot_directory / item["raw_path"]
        raw_exact &= path.is_file()
        if path.is_file():
            raw_exact &= path.stat().st_size == int(item["raw_gzip_bytes"])
            raw_exact &= sha256_file(path) == item["raw_gzip_sha256"]
    available = pd.to_datetime(normalized.get("available_at"), utc=True, errors="coerce")
    retrieved = pd.to_datetime(normalized.get("retrieved_at"), utc=True, errors="coerce")
    checks = {
        "manifest_exists": manifest_path.is_file(),
        "requests_exist": requests_path.is_file(),
        "protocol_exact": manifest.get("protocol")
        == "moex-forward-equity-microstructure-v1",
        "subscribed_realtime_exact": manifest.get("access_mode")
        == "algopack_subscribed_realtime",
        "token_not_persisted": manifest.get("token_persisted") is False,
        "target_free_manifest": manifest.get("target_free") is True,
        "request_count_exact": len(requests_payload) == len(DATASET_COLUMNS),
        "datasets_exact": set(manifest.get("datasets", [])) == set(DATASET_COLUMNS),
        "raw_identities_exact": bool(raw_exact),
        "normalized_identity_exact": normalized_path.stat().st_size
        == int(manifest["normalized_bytes"])
        and sha256_file(normalized_path) == manifest["normalized_sha256"],
        "normalized_rows_exact": len(normalized) == int(manifest["normalized_rows"]),
        "normalized_tickers_bounded": set(normalized.get("secid", [])) <= set(TICKERS),
        "normalized_datasets_exact": set(normalized.get("dataset", []))
        <= set(DATASET_COLUMNS),
        "forbidden_fields_absent": not set(normalized.columns)
        & FORBIDDEN_PRICE_OUTCOME_COLUMNS,
        "target_free_rows": normalized[
            "contains_absolute_price_return_target_or_pnl"
        ].eq(False).all(),
        "availability_not_backdated": available.notna().all()
        and retrieved.notna().all()
        and available.ge(retrieved).all(),
    }
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-date")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        checks = audit_snapshot(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        if not all(checks.values()):
            raise SystemExit(2)
        return
    if not args.source_date:
        parser.error("--source-date is required when collecting")
    token = os.environ.get(TOKEN_ENVIRONMENT_VARIABLE, "")
    output = collect_snapshot(args.output_root, args.source_date, token=token)
    checks = audit_snapshot(output)
    print(json.dumps({"output": str(output), "checks": checks}, indent=2))
    if not all(checks.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
