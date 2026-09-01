"""Capture immutable target-free MOEX forward microstructure snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet
import requests

from market_lab.futures import futoi_source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-microstructure-v1"
)
PUBLIC_ISS_ROOT: Final[str] = "https://iss.moex.com/iss"
AUTHENTICATED_ISS_ROOT: Final[str] = "https://apim.moex.com/iss"
TOKEN_ENVIRONMENT_VARIABLE: Final[str] = "MOEX_ALGOPACK_TOKEN"
USER_AGENT: Final[str] = "market-lab-forward-microstructure/1.0 (MOEX research)"
MOSCOW_TIMEZONE: Final[str] = "Europe/Moscow"
DELIVERY_BUFFER: Final[pd.Timedelta] = pd.Timedelta(minutes=1)
FUTOI_TICKERS: Final[tuple[str, ...]] = tuple(futoi_source.TICKERS)
FUTOI_COLUMNS: Final[tuple[str, ...]] = tuple(futoi_source.ISS_COLUMNS)
TRADESTATS_FLOW_COLUMNS: Final[tuple[str, ...]] = (
    "tradedate",
    "tradetime",
    "secid",
    "asset_code",
    "vol",
    "trades",
    "trades_b",
    "trades_s",
    "val_b",
    "val_s",
    "vol_b",
    "vol_s",
    "disb",
    "im",
    "oi_open",
    "oi_high",
    "oi_low",
    "oi_close",
    "SYSTIME",
)
OBSTATS_FLOW_COLUMNS: Final[tuple[str, ...]] = (
    "tradedate",
    "tradetime",
    "secid",
    "asset_code",
    "spread_l1",
    "spread_l2",
    "spread_l3",
    "spread_l5",
    "spread_l10",
    "spread_l20",
    "levels_b",
    "levels_s",
    "vol_b_l1",
    "vol_b_l2",
    "vol_b_l3",
    "vol_b_l5",
    "vol_b_l10",
    "vol_b_l20",
    "vol_s_l1",
    "vol_s_l2",
    "vol_s_l3",
    "vol_s_l5",
    "vol_s_l10",
    "vol_s_l20",
    "SYSTIME",
)
FORBIDDEN_OUTCOME_COLUMNS: Final[frozenset[str]] = frozenset(
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
        "mid_price",
        "micro_price",
        "vwap_b_l3",
        "vwap_b_l5",
        "vwap_b_l10",
        "vwap_b_l20",
        "vwap_s_l3",
        "vwap_s_l5",
        "vwap_s_l10",
        "vwap_s_l20",
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


def _as_aware_utc(value: str | pd.Timestamp | datetime, label: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include an explicit timezone")
    return parsed.tz_convert("UTC")


def _validate_source_date(value: str | pd.Timestamp) -> pd.Timestamp:
    parsed = pd.Timestamp(value).normalize()
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    if parsed < pd.Timestamp("2026-01-01"):
        raise ValueError("forward snapshot source_date must be 2026 or later")
    return parsed


def _futoi_url(ticker: str, source_date: pd.Timestamp, authenticated: bool) -> str:
    if ticker not in FUTOI_TICKERS:
        raise ValueError(f"unsupported forward FUTOI ticker: {ticker}")
    root = AUTHENTICATED_ISS_ROOT if authenticated else PUBLIC_ISS_ROOT
    date = source_date.date().isoformat()
    query = urlencode(
        {
            "from": date,
            "till": date,
            "latest": 1,
            "iss.meta": "off",
            "iss.only": "futoi",
            "futoi.columns": ",".join(FUTOI_COLUMNS),
        }
    )
    return f"{root}/analyticalproducts/futoi/securities/{ticker.lower()}.json?{query}"


def _algopack_url(dataset: str, contract_id: str, source_date: pd.Timestamp) -> str:
    if dataset not in {"tradestats", "obstats"}:
        raise ValueError(f"unsupported forward ALGOPACK dataset: {dataset}")
    if not contract_id or any(character in contract_id for character in "/\\?&#"):
        raise ValueError("invalid forward contract identifier")
    columns = TRADESTATS_FLOW_COLUMNS if dataset == "tradestats" else OBSTATS_FLOW_COLUMNS
    if set(columns) & FORBIDDEN_OUTCOME_COLUMNS:
        raise ValueError("forward request schema contains a forbidden outcome column")
    query = urlencode(
        {
            "date": source_date.date().isoformat(),
            "latest": 1,
            "iss.meta": "off",
            "iss.only": "data",
            "data.columns": ",".join(columns),
        }
    )
    return (
        f"{AUTHENTICATED_ISS_ROOT}/datashop/algopack/fo/{dataset}/"
        f"{contract_id}.json?{query}"
    )


def _table(payload: dict[str, Any], block: str, expected: tuple[str, ...]) -> pd.DataFrame:
    table = payload.get(block)
    if not isinstance(table, dict):
        raise ValueError(f"MOEX response lacks the {block!r} block")
    columns = table.get("columns")
    rows = table.get("data")
    if columns != list(expected) or not isinstance(rows, list):
        raise ValueError(f"MOEX {block} response escaped the target-free closed schema")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"MOEX {block} response contains a malformed row")
    return pd.DataFrame(rows, columns=columns)


def _request(
    url: str,
    *,
    token: str | None,
    session: SessionLike | None,
) -> tuple[dict[str, Any], bytes]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    network = session or requests.Session()
    response = network.get(url, headers=headers, timeout=60.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("MOEX forward response root is not an object")
    raw = bytes(response.content)
    if not raw:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload, raw


def _observation_times(
    frame: pd.DataFrame,
    retrieved_at: pd.Timestamp,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    observed_naive = pd.to_datetime(
        frame["tradedate"].astype("string") + " " + frame["tradetime"].astype("string"),
        errors="raise",
    )
    published_naive = pd.to_datetime(frame["SYSTIME"], errors="raise")
    if observed_naive.dt.tz is not None or published_naive.dt.tz is not None:
        raise ValueError("MOEX forward source unexpectedly returned timezone-aware local clocks")
    observed = observed_naive.dt.tz_localize(MOSCOW_TIMEZONE).dt.tz_convert("UTC")
    published = published_naive.dt.tz_localize(MOSCOW_TIMEZONE).dt.tz_convert("UTC")
    if published.lt(observed).any():
        raise ValueError("MOEX forward publication precedes its observation")
    retrieval = pd.Series(retrieved_at, index=frame.index, dtype="datetime64[ns, UTC]")
    available = pd.concat((published + DELIVERY_BUFFER, retrieval), axis=1).max(axis=1)
    return observed, published, available


def normalize_futoi_snapshot(
    frame: pd.DataFrame,
    ticker: str,
    retrieved_at: pd.Timestamp,
    authenticated: bool,
) -> pd.DataFrame:
    """Normalize a paired FUTOI point while preserving actual forward availability."""

    if frame.empty:
        return pd.DataFrame()
    output = frame.copy().rename(
        columns={
            "tradedate": "source_date",
            "tradetime": "source_time",
            "clgroup": "client_group",
            "pos": "net_position",
            "pos_long": "long_position",
            "pos_short": "short_position",
            "pos_long_num": "long_accounts",
            "pos_short_num": "short_accounts",
            "systime": "published_at_moscow",
        }
    )
    clock_frame = frame.rename(columns={"systime": "SYSTIME"})
    observed, published, available = _observation_times(clock_frame, retrieved_at)
    output["observed_at"] = observed
    output["published_at"] = published
    output["retrieved_at"] = retrieved_at
    output["available_at"] = available
    output["source_date"] = pd.to_datetime(output["source_date"], errors="raise").dt.normalize()
    output["source_time"] = output["source_time"].astype("string")
    if not output["ticker"].astype("string").str.casefold().eq(ticker.casefold()).all():
        raise ValueError("forward FUTOI response returned another ticker")
    output["client_group"] = output["client_group"].astype("string").str.upper()
    if not set(output["client_group"].dropna().unique()) <= {"FIZ", "YUR"}:
        raise ValueError("forward FUTOI returned an unknown client group")
    integer_columns = (
        "sess_id",
        "seqnum",
        "net_position",
        "long_position",
        "short_position",
        "long_accounts",
        "short_accounts",
    )
    for column in integer_columns:
        numeric = pd.to_numeric(output[column], errors="raise")
        if not np.isfinite(numeric).all() or not np.equal(numeric, np.trunc(numeric)).all():
            raise ValueError(f"forward FUTOI {column} is not finite integer data")
        output[column] = numeric.astype("int64")
    if not output["net_position"].eq(
        output["long_position"] + output["short_position"]
    ).all():
        raise ValueError("forward FUTOI net-position identity failed")
    keys = ["source_date", "source_time", "ticker", "sess_id", "seqnum"]
    if output.groupby(keys, observed=True)["client_group"].nunique().ne(2).any():
        raise ValueError("forward FUTOI point lacks an exact FIZ/YUR pair")
    output["dataset"] = "futoi"
    output["asset_code"] = output["ticker"].map(futoi_source.TICKER_TO_ASSET)
    output["contract_id"] = pd.NA
    output["access_mode"] = (
        "authenticated_realtime_candidate" if authenticated else "public_15_day_delayed"
    )
    output["contains_prices_returns_targets_or_pnl"] = False
    return output


def normalize_algopack_snapshot(
    frame: pd.DataFrame,
    dataset: str,
    contract_id: str,
    retrieved_at: pd.Timestamp,
) -> pd.DataFrame:
    """Normalize subscribed flow/depth fields without reading absolute prices."""

    if frame.empty:
        return pd.DataFrame()
    expected = TRADESTATS_FLOW_COLUMNS if dataset == "tradestats" else OBSTATS_FLOW_COLUMNS
    if tuple(frame.columns) != expected or set(frame.columns) & FORBIDDEN_OUTCOME_COLUMNS:
        raise ValueError("forward ALGOPACK frame escaped its target-free schema")
    output = frame.copy()
    if not output["secid"].astype("string").eq(contract_id).all():
        raise ValueError("forward ALGOPACK response returned another contract")
    observed, published, available = _observation_times(output, retrieved_at)
    output["observed_at"] = observed
    output["published_at"] = published
    output["retrieved_at"] = retrieved_at
    output["available_at"] = available
    output["dataset"] = dataset
    output["contract_id"] = output["secid"].astype("string")
    output["source_date"] = pd.to_datetime(output["tradedate"], errors="raise").dt.normalize()
    output["source_time"] = output["tradetime"].astype("string")
    output["access_mode"] = "authenticated_subscription"
    output["contains_prices_returns_targets_or_pnl"] = False
    return output


def _artifact(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix == ".parquet":
        record["rows"] = parquet.ParquetFile(path).metadata.num_rows
    return record


def _parse_contracts(values: list[str]) -> dict[str, str]:
    contracts: dict[str, str] = {}
    for value in values:
        asset, separator, contract = value.partition("=")
        asset = asset.strip().upper()
        contract = contract.strip()
        if separator != "=" or asset not in {"SI", "RI", "BR", "MIX"} or not contract:
            raise ValueError(f"invalid --contract mapping: {value}")
        if asset in contracts:
            raise ValueError(f"duplicate --contract asset: {asset}")
        contracts[asset] = contract
    return contracts


def collect_forward_snapshot(
    output_root: Path,
    source_date: str | pd.Timestamp,
    *,
    contracts: dict[str, str] | None = None,
    token: str | None = None,
    session: SessionLike | None = None,
    retrieved_at_utc: str | pd.Timestamp | datetime | None = None,
) -> Path:
    """Write one immutable retrieval-vintage snapshot without any price or target fields."""

    date = _validate_source_date(source_date)
    contracts = contracts or {}
    retrieved_at = _as_aware_utc(
        retrieved_at_utc or datetime.now(UTC),
        "retrieved_at_utc",
    )
    authenticated = bool(token)
    if contracts and not authenticated:
        raise ValueError("ALGOPACK contract snapshots require a bearer token")
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_{retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=output_root))
    records: list[pd.DataFrame] = []
    requests_log: list[dict[str, object]] = []
    try:
        raw_directory = temporary / "raw"
        raw_directory.mkdir()
        for ticker in FUTOI_TICKERS:
            url = _futoi_url(ticker, date, authenticated)
            payload, raw = _request(url, token=token, session=session)
            frame = _table(payload, "futoi", FUTOI_COLUMNS)
            normalized = normalize_futoi_snapshot(
                frame,
                ticker,
                retrieved_at,
                authenticated,
            )
            if not normalized.empty:
                records.append(normalized)
            raw_path = raw_directory / f"futoi_{ticker.lower()}.json.gz"
            raw_path.write_bytes(gzip.compress(raw, mtime=0))
            requests_log.append(
                {
                    "dataset": "futoi",
                    "identifier": ticker,
                    "request_url": url,
                    "authenticated": authenticated,
                    "rows": int(len(frame)),
                    "raw_path": str(raw_path.relative_to(temporary)).replace("\\", "/"),
                    "raw_gzip_sha256": sha256_file(raw_path),
                    "raw_gzip_bytes": raw_path.stat().st_size,
                }
            )
        for asset, contract_id in sorted(contracts.items()):
            for dataset in ("tradestats", "obstats"):
                url = _algopack_url(dataset, contract_id, date)
                payload, raw = _request(url, token=token, session=session)
                expected = (
                    TRADESTATS_FLOW_COLUMNS if dataset == "tradestats" else OBSTATS_FLOW_COLUMNS
                )
                frame = _table(payload, "data", expected)
                normalized = normalize_algopack_snapshot(
                    frame,
                    dataset,
                    contract_id,
                    retrieved_at,
                )
                if not normalized.empty:
                    normalized["requested_asset_code"] = asset
                    records.append(normalized)
                raw_path = raw_directory / f"{dataset}_{asset.lower()}_{contract_id}.json.gz"
                raw_path.write_bytes(gzip.compress(raw, mtime=0))
                requests_log.append(
                    {
                        "dataset": dataset,
                        "identifier": contract_id,
                        "request_url": url,
                        "authenticated": True,
                        "rows": int(len(frame)),
                        "raw_path": str(raw_path.relative_to(temporary)).replace("\\", "/"),
                        "raw_gzip_sha256": sha256_file(raw_path),
                        "raw_gzip_bytes": raw_path.stat().st_size,
                    }
                )
        prepared = [frame.dropna(axis=1, how="all") for frame in records]
        combined = (
            pd.concat(prepared, ignore_index=True, sort=False)
            if prepared
            else pd.DataFrame()
        )
        if len(combined) and not combined["contains_prices_returns_targets_or_pnl"].eq(False).all():
            raise ValueError("forward normalized source contains an outcome-bearing row")
        normalized_path = temporary / "microstructure.parquet"
        combined.to_parquet(normalized_path, index=False)
        requests_path = temporary / "requests.json"
        _write_json(requests_path, requests_log)
        manifest: dict[str, object] = {
            "dataset_id": "moex_forward_microstructure_v1",
            "implementation_sha256": sha256_file(MODULE_PATH),
            "created_at_utc": retrieved_at.isoformat(),
            "source_date": date.date().isoformat(),
            "authenticated": authenticated,
            "token_persisted": False,
            "contracts": contracts,
            "request_count": len(requests_log),
            "normalized_rows": int(len(combined)),
            "datasets_requested": sorted({str(item["dataset"]) for item in requests_log}),
            "temporal_semantics": {
                "available_at": "max(exchange_SYSTIME_plus_one_minute, actual_retrieval_at)",
                "public_futoi_delay": "officially_documented_15_days",
                "contains_prices_returns_targets_or_pnl": False,
                "historical_backtest_admissible_before_retrieval": False,
            },
            "artifacts": {
                "microstructure": _artifact(normalized_path),
                "requests": _artifact(requests_path),
            },
            "raw_artifacts": [
                {
                    key: value
                    for key, value in item.items()
                    if key in {"raw_path", "raw_gzip_sha256", "raw_gzip_bytes"}
                }
                for item in requests_log
            ],
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    audit_forward_snapshot(final)
    return final


def audit_forward_snapshot(snapshot: Path) -> dict[str, bool]:
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "dataset_identity": manifest["dataset_id"] == "moex_forward_microstructure_v1",
        "implementation_identity": manifest["implementation_sha256"]
        == sha256_file(MODULE_PATH),
        "target_free": manifest["temporal_semantics"][
            "contains_prices_returns_targets_or_pnl"
        ]
        is False,
        "token_not_persisted": manifest["token_persisted"] is False,
    }
    for name, record in manifest["artifacts"].items():
        path = snapshot / record["path"]
        checks[f"artifact:{name}"] = bool(
            path.is_file()
            and path.stat().st_size == int(record["bytes"])
            and sha256_file(path) == record["sha256"]
        )
        if checks[f"artifact:{name}"] and path.suffix == ".parquet":
            checks[f"rows:{name}"] = parquet.ParquetFile(path).metadata.num_rows == int(
                record["rows"]
            )
    for index, record in enumerate(manifest["raw_artifacts"]):
        path = snapshot / record["raw_path"]
        checks[f"raw:{index}"] = bool(
            path.is_file()
            and path.stat().st_size == int(record["raw_gzip_bytes"])
            and sha256_file(path) == record["raw_gzip_sha256"]
        )
    if not all(checks.values()):
        raise ValueError(f"MOEX forward snapshot audit failed: {checks}")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--source-date", required=True)
    parser.add_argument("--contract", action="append", default=[])
    parser.add_argument("--audit-directory", type=Path)
    arguments = parser.parse_args()
    if arguments.audit_directory is not None:
        print(json.dumps(audit_forward_snapshot(arguments.audit_directory), indent=2))
        return
    token = os.environ.get(TOKEN_ENVIRONMENT_VARIABLE)
    output = collect_forward_snapshot(
        arguments.output_root,
        arguments.source_date,
        contracts=_parse_contracts(arguments.contract),
        token=token,
    )
    print(output)


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "FUTOI_COLUMNS",
    "FUTOI_TICKERS",
    "OBSTATS_FLOW_COLUMNS",
    "TOKEN_ENVIRONMENT_VARIABLE",
    "TRADESTATS_FLOW_COLUMNS",
    "audit_forward_snapshot",
    "collect_forward_snapshot",
    "main",
    "normalize_algopack_snapshot",
    "normalize_futoi_snapshot",
]
