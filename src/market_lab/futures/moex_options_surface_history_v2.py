"""Collect the sealed public exact-date MOEX core-four option history pilot V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests
import yaml

from market_lab.futures.moex_options_surface_source import parse_option_short_code

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_options_surface_source_v2.yaml"
CONFIG_SHA256: Final[str] = "685fb7e9ee5776cfc21dee3c3946ce3e63050c54ec0de02918d98d953308c14a"
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/options/moex-core4-options-pilot-2021-01-v2"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
MOSCOW_TIMEZONE: Final[str] = "Europe/Moscow"
USER_AGENT: Final[str] = "market-lab-moex-option-history-v2/1.0 (research)"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
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


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("MOEX option history V2 config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_options_surface_source_v2"
        or config.get("live_trading_allowed") is not False
        or config["objective"]["signal_returns_targets_predictions_or_pnl_allowed"] is not False
        or str(config["dates"]["protected_from"]) != "2026-01-01"
        or config["correction"]["parent_output_created"] is not False
    ):
        raise ValueError("MOEX option history V2 invariants drifted")
    return config


def request_url(config: dict[str, Any], query_date: date, server_asset: str, start: int) -> str:
    if (
        server_asset not in config["source"]["assets"]
        or start < 0
        or pd.Timestamp(query_date) >= PROTECTED_FROM
    ):
        raise ValueError("invalid MOEX option history request")
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "history,history.cursor",
            "history.columns": ",".join(config["source"]["required_columns"]),
            "date": query_date.isoformat(),
            "assetcode": server_asset,
            "start": start,
        }
    )
    return f"{config['source']['endpoint']}?{query}"


def _block(payload: dict[str, Any], name: str) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        raise ValueError(f"missing MOEX option history {name} block")
    rows = block.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX option history {name} rows")
    return pd.DataFrame(rows, columns=[str(value) for value in block["columns"]])


def parse_page(
    raw: bytes, query_date: date, config: dict[str, Any]
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    frame = _block(payload, "history")
    if tuple(frame.columns) != tuple(config["source"]["required_columns"]):
        raise ValueError("MOEX option history exact schema drift")
    cursor = _block(payload, "history.cursor")
    if len(cursor) != 1 or {"INDEX", "TOTAL", "PAGESIZE"} - set(cursor.columns):
        raise ValueError("MOEX option history cursor drift")
    index = int(cursor.iloc[0]["INDEX"])
    total = int(cursor.iloc[0]["TOTAL"])
    if index < 0 or total < 0 or index + len(frame) > total:
        raise ValueError("MOEX option history cursor invalid")
    if len(frame):
        dates = pd.to_datetime(frame["TRADEDATE"], errors="raise").dt.date.unique()
        if len(dates) != 1 or dates[0] != query_date:
            raise ValueError("MOEX option history returned wrong date")
    return frame, index, total


def _get_with_retry(url: str, session: SessionLike | None) -> bytes:
    error: BaseException | None = None
    for attempt in range(3):
        try:
            client = session or requests
            response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
            response.raise_for_status()
            return bytes(response.content)
        except (requests.RequestException, TimeoutError) as caught:
            error = caught
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"MOEX option history request failed: {url}") from error


def fetch_job(
    query_date: date,
    server_asset: str,
    config: dict[str, Any],
    session: SessionLike | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    start = 0
    total: int | None = None
    frames: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    while total is None or start < total:
        url = request_url(config, query_date, server_asset, start)
        raw = _get_with_retry(url, session)
        frame, index, page_total = parse_page(raw, query_date, config)
        if index != start or (total is not None and page_total != total):
            raise ValueError("MOEX option history pagination drift")
        total = page_total
        if len(frame):
            frame = frame.copy()
            frame["server_assetcode"] = server_asset
        frames.append(frame)
        pages.append(
            {
                "query_date": query_date.isoformat(),
                "server_assetcode": server_asset,
                "start": start,
                "url": url,
                "rows": len(frame),
                "raw": raw,
            }
        )
        if len(frame) == 0:
            if total != 0:
                raise ValueError("MOEX option history empty page before total")
            break
        start += len(frame)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined) != int(total or 0):
        raise ValueError("MOEX option history incomplete asset-date")
    return combined, pages


def canonical_jobs(config: dict[str, Any]) -> list[tuple[date, str]]:
    dates = pd.date_range(config["dates"]["pilot_start"], config["dates"]["pilot_end"])
    return [(value.date(), asset) for value in dates for asset in config["source"]["assets"]]


def normalize(
    frame: pd.DataFrame, retrieved_at: pd.Timestamp, config: dict[str, Any]
) -> pd.DataFrame:
    required = list(config["source"]["required_columns"])
    if frame.empty:
        return pd.DataFrame(
            columns=[column.lower() for column in required]
            + [
                "server_assetcode",
                "logical_asset",
                "parsed_root",
                "strike",
                "settlement_code",
                "option_type",
                "encoded_expiry_month",
                "encoded_expiry_year_digit",
                "encoded_week_code",
                "available_at_utc",
                "retrieved_at_utc",
            ]
        )
    output = frame.loc[:, required + ["server_assetcode"]].copy()
    output.columns = [column.lower() for column in output.columns]
    output["tradedate"] = pd.to_datetime(output["tradedate"], errors="raise").dt.normalize()
    parsed = []
    unparsed: list[str] = []
    for security_id in output["secid"]:
        item = parse_option_short_code(security_id)
        if item is None:
            unparsed.append(str(security_id))
            parsed.append({})
        else:
            parsed.append(item)
    if unparsed:
        raise ValueError(f"unparsed core MOEX option codes: {sorted(set(unparsed))[:20]}")
    parsed_frame = pd.DataFrame(parsed).rename(columns={"asset": "logical_asset"})
    output = pd.concat([output.reset_index(drop=True), parsed_frame.reset_index(drop=True)], axis=1)
    expected_asset = output["server_assetcode"].map(config["source"]["logical_mapping"])
    if not output["logical_asset"].eq(expected_asset).all():
        raise ValueError("MOEX option server asset and parsed root mismatch")
    identifier_columns = {"tradedate", "boardid", "secid", "server_assetcode"}
    numeric_columns = [
        column.lower() for column in required if column.lower() not in identifier_columns
    ]
    for column in numeric_columns:
        output[column] = pd.to_numeric(output[column], errors="coerce").astype(float)
        if np.isinf(output[column].to_numpy()).any():
            raise ValueError(f"infinite MOEX option history {column}")
    if output["tradedate"].ge(PROTECTED_FROM).any():
        raise ValueError("MOEX option history crossed protected boundary")
    if output.duplicated(["tradedate", "boardid", "secid"]).any():
        raise ValueError("duplicate MOEX option date/board/security")
    output["available_at_utc"] = (
        output["tradedate"].dt.tz_localize(MOSCOW_TIMEZONE) + pd.Timedelta(days=1)
    ).dt.tz_convert("UTC")
    output["retrieved_at_utc"] = retrieved_at.tz_convert("UTC")
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("outcome column escaped into MOEX option source")
    return output.sort_values(
        ["tradedate", "logical_asset", "secid", "boardid"],
        kind="mergesort",
        ignore_index=True,
    )


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    jobs: list[tuple[date, str]] | None = None,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
    max_workers: int = 12,
) -> Path:
    config = load_config()
    canonical = jobs is None
    selected_jobs = canonical_jobs(config) if jobs is None else jobs
    if not selected_jobs or len(set(selected_jobs)) != len(selected_jobs):
        raise ValueError("MOEX option history jobs must be nonempty and unique")
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("MOEX option history retrieval must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    results: dict[tuple[date, str], tuple[pd.DataFrame, list[dict[str, Any]]]] = {}
    workers = 1 if session is not None else max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_job, d, asset, config, session): (d, asset)
            for d, asset in selected_jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            results[futures[future]] = future.result()
            if canonical and completed % 10 == 0:
                print(f"MOEX option history progress {completed}/{len(selected_jobs)}", flush=True)
    frames = [results[job][0] for job in selected_jobs if len(results[job][0])]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    normalized = normalize(combined, retrieval, config)
    if canonical:
        expected = config["preseal_inspection"]["january_2021_metadata"]["expected_rows"]
        counts = normalized["server_assetcode"].value_counts().to_dict()
        if len(normalized) != int(expected["total"]) or any(
            int(counts.get(asset, 0)) != int(expected[asset])
            for asset in config["source"]["assets"]
        ):
            raise ValueError("MOEX option history sealed metadata counts drifted")
    raw_pages = [page for job in selected_jobs for page in results[job][1]]
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable MOEX option history output exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        request_log = []
        raw_zip = temporary / "raw_responses.zip"
        with zipfile.ZipFile(raw_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for page in sorted(
                raw_pages,
                key=lambda x: (x["query_date"], x["server_assetcode"], int(x["start"])),
            ):
                member = (
                    f"raw/{page['query_date']}/{page['server_assetcode']}/"
                    f"{int(page['start']):06d}.json"
                )
                archive.writestr(member, page["raw"])
                request_log.append(
                    {
                        key: page[key]
                        for key in ("query_date", "server_assetcode", "start", "url", "rows")
                    }
                    | {
                        "zip_member": member,
                        "response_bytes": len(page["raw"]),
                        "response_sha256": _sha_bytes(page["raw"]),
                    }
                )
        _write_json(temporary / "requests.json", request_log)
        processed = temporary / "options_daily_core4.parquet"
        normalized.to_parquet(processed, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "canonical_pilot": canonical,
            "job_count": len(selected_jobs),
            "raw_page_count": len(request_log),
            "contains_returns_targets_predictions_or_pnl": False,
            "raw_zip": {
                "path": raw_zip.name,
                "bytes": raw_zip.stat().st_size,
                "sha256": _sha_file(raw_zip),
            },
            "requests": {
                "path": "requests.json",
                "bytes": (temporary / "requests.json").stat().st_size,
                "sha256": _sha_file(temporary / "requests.json"),
                "rows": len(request_log),
            },
            "processed": {
                "path": processed.name,
                "bytes": processed.stat().st_size,
                "sha256": _sha_file(processed),
                "rows": len(normalized),
                "minimum_tradedate": normalized["tradedate"].min().date().isoformat()
                if len(normalized)
                else None,
                "maximum_tradedate": normalized["tradedate"].max().date().isoformat()
                if len(normalized)
                else None,
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
        raise ValueError("MOEX option history audit failed")
    return output_root


def audit(output_root: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    raw_zip = output_root / manifest["raw_zip"]["path"]
    requests_path = output_root / manifest["requests"]["path"]
    checks = {
        "protocol_exact": manifest["protocol_id"] == config["protocol_id"],
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "target_free": manifest["contains_returns_targets_predictions_or_pnl"] is False,
        "raw_zip_exact": raw_zip.stat().st_size == manifest["raw_zip"]["bytes"]
        and _sha_file(raw_zip) == manifest["raw_zip"]["sha256"],
        "requests_exact": requests_path.stat().st_size == manifest["requests"]["bytes"]
        and _sha_file(requests_path) == manifest["requests"]["sha256"],
    }
    request_log = json.loads(requests_path.read_text(encoding="utf-8-sig"))
    rebuilt = []
    raw_exact = True
    with zipfile.ZipFile(raw_zip) as archive:
        for item in request_log:
            raw = archive.read(item["zip_member"])
            raw_exact &= (
                len(raw) == item["response_bytes"] and _sha_bytes(raw) == item["response_sha256"]
            )
            raw_exact &= item["url"] == request_url(
                config,
                date.fromisoformat(item["query_date"]),
                item["server_assetcode"],
                int(item["start"]),
            )
            frame, index, _ = parse_page(raw, date.fromisoformat(item["query_date"]), config)
            raw_exact &= index == int(item["start"])
            if len(frame):
                frame["server_assetcode"] = item["server_assetcode"]
                rebuilt.append(frame)
    checks["all_raw_pages_exact"] = raw_exact
    replay = normalize(
        pd.concat(rebuilt, ignore_index=True) if rebuilt else pd.DataFrame(), retrieval, config
    )
    processed_path = output_root / manifest["processed"]["path"]
    stored = pd.read_parquet(processed_path)
    try:
        pd.testing.assert_frame_equal(stored, replay, check_dtype=False)
        frame_exact = True
    except AssertionError:
        frame_exact = False
    checks["processed_exact"] = (
        processed_path.stat().st_size == manifest["processed"]["bytes"]
        and _sha_file(processed_path) == manifest["processed"]["sha256"]
        and len(stored) == manifest["processed"]["rows"]
        and frame_exact
    )
    if manifest["canonical_pilot"]:
        checks["canonical_counts_exact"] = len(stored) == int(
            config["preseal_inspection"]["january_2021_metadata"]["expected_rows"]["total"]
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=12)
    args = parser.parse_args()
    if args.audit_only:
        checks = audit(args.output_root)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root, max_workers=args.max_workers))


if __name__ == "__main__":
    main()
