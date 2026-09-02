"""Collect official MOEX notices for historical stock-unit adjustments."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import shutil
import tempfile
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq
import requests
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_stock_split_adjustment_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "2416baf31b4de412ccddb7e05ecbb028387966374576eba5ff0682842456c548"
)
OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/moex-stock-split-adjustments-2024-2025-v1"
)
EXPECTED_STOCKS: Final[tuple[str, ...]] = ("TRNFP", "GMKN", "PLZL", "VTBR")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def _sha_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _extract_text(raw: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="strict"))
    return " ".join(parser.parts)


def load_protocol() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("stock split source config must be an object")
    events = payload.get("events")
    urls = {
        str(event[key])
        for event in events
        for key in ("equity_notice", "futures_notice")
    }
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_stock_split_adjustment_source_v1"
        or payload.get("status")
        != "sealed_after_official_split_facts_observed_before_corrected_economic_replay"
        or payload.get("live_trading_allowed") is not False
        or not isinstance(events, list)
        or tuple(str(event["stock_secid"]) for event in events) != EXPECTED_STOCKS
        or len(urls) != 8
    ):
        raise ValueError("stock split source protocol drifted")
    dependency = payload["dependency"]
    root = storage._project_path(dependency["root"], "data")
    for key in ("manifest", "specs"):
        declaration = dependency[key]
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"stock split dependency drifted: {key}")
        if key == "specs" and pq.ParquetFile(path).metadata.num_rows != int(
            declaration["rows"]
        ):
            raise ValueError("stock split dependency rows drifted")
    return payload


def _adjusted_contracts(payload: dict[str, Any]) -> pd.DataFrame:
    dependency = payload["dependency"]
    root = storage._project_path(dependency["root"], "data")
    specs = pd.read_parquet(root / dependency["specs"]["file"])
    specs["last_trade"] = pd.to_datetime(specs["last_trade"], errors="raise")
    selected: list[pd.DataFrame] = []
    for event in payload["events"]:
        stock = str(event["stock_secid"])
        cutoff = pd.Timestamp(event["old_contract_last_trade_before"])
        part = specs.loc[
            specs["stock_secid"].eq(stock) & specs["last_trade"].lt(cutoff)
        ].copy()
        part["action"] = str(event["action"])
        part["action_effective_date"] = pd.Timestamp(event["equity_effective_date"])
        original = pd.to_numeric(part["lot_size_shares"], errors="raise").astype(int)
        if event["action"] == "split":
            factor = int(event["factor_new_shares_per_old_share"])
            adjusted = original * factor
        elif event["action"] == "consolidation":
            factor = int(event["factor_old_shares_per_new_share"])
            if original.mod(factor).ne(0).any():
                raise ValueError("stock split adjusted unit is fractional")
            adjusted = original // factor
        else:
            raise ValueError(f"unknown stock action: {event['action']}")
        part["action_factor"] = factor
        part["historical_contract_lot_shares"] = original
        part["back_adjusted_spot_units"] = adjusted
        selected.append(
            part[
                [
                    "contract_id",
                    "stock_secid",
                    "secid",
                    "asset_code",
                    "last_trade",
                    "action",
                    "action_effective_date",
                    "action_factor",
                    "historical_contract_lot_shares",
                    "back_adjusted_spot_units",
                ]
            ]
        )
    output = pd.concat(selected, ignore_index=True).sort_values(
        ["stock_secid", "last_trade", "secid"], ignore_index=True
    )
    if len(output) != 27 or output["back_adjusted_spot_units"].le(0).any():
        raise ValueError("stock split affected-contract identity drifted")
    return output


def _get(session: requests.Session, url: str, timeout: int, retries: int) -> requests.Response:
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt + 1 >= retries:
                raise
            time.sleep(float(2**attempt))
    raise AssertionError("unreachable")


def _raw_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)


def _read_raw(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _audit_directory(directory: Path, payload: dict[str, Any]) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    events_path = directory / "events.json"
    affected_path = directory / "affected_contracts.parquet"
    raw_path = directory / "official_moex_notices.jsonl.gz"
    raw = _read_raw(raw_path)
    expected_urls = {
        str(event[key])
        for event in payload["events"]
        for key in ("equity_notice", "futures_notice")
    }
    raw_hashes_exact = all(
        _sha_bytes(base64.b64decode(item["content_base64"]))
        == item["content_sha256"]
        for item in raw
    )
    fragments_exact = True
    by_url = {str(item["url"]): item for item in raw}
    for event in payload["events"]:
        for role in ("equity", "futures"):
            item = by_url[str(event[f"{role}_notice"])]
            text = _extract_text(base64.b64decode(item["content_base64"]))
            fragments_exact &= all(
                fragment in text for fragment in event[f"{role}_required_fragments"]
            )
    affected = pd.read_parquet(affected_path)
    checks = {
        "manifest_sha_exact": _sha(manifest_path)
        == (directory / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0],
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "source_only": manifest["source_only"] is True,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "events_sha_exact": _sha(events_path) == manifest["artifacts"]["events"]["sha256"],
        "affected_sha_exact": _sha(affected_path)
        == manifest["artifacts"]["affected_contracts"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "events_exact": json.loads(events_path.read_text(encoding="utf-8-sig"))
        == payload["events"],
        "exact_8_urls": len(raw) == 8 and set(by_url) == expected_urls,
        "raw_content_hashes_exact": raw_hashes_exact,
        "required_fragments_exact": fragments_exact,
        "exact_27_affected_contracts": len(affected) == 27,
        "affected_identity_unique": not affected["contract_id"].duplicated().any(),
        "adjusted_units_positive_integer": bool(
            pd.to_numeric(affected["back_adjusted_spot_units"], errors="raise")
            .astype(int)
            .gt(0)
            .all()
        ),
        "outcomes_absent": manifest[
            "contains_basis_returns_targets_signals_predictions_equity_or_pnl"
        ]
        is False,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def collect(payload: dict[str, Any]) -> Path:
    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"stock split source exists: {OUTPUT_ROOT}")
    OUTPUT_ROOT.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{OUTPUT_ROOT.name}.", dir=OUTPUT_ROOT.parent))
    try:
        session = requests.Session()
        session.headers["User-Agent"] = "TradingLabResearch/1.0"
        raw: list[dict[str, Any]] = []
        for event in payload["events"]:
            for role in ("equity", "futures"):
                url = str(event[f"{role}_notice"])
                response = _get(
                    session,
                    url,
                    int(payload["collection"]["timeout_seconds"]),
                    int(payload["collection"]["retries"]),
                )
                content = response.content
                content_type = str(response.headers.get("content-type", ""))
                if "text/html" not in content_type.lower() or len(content) < 50_000:
                    raise ValueError(f"stock split notice response invalid: {url}")
                text = _extract_text(content)
                required = event[f"{role}_required_fragments"]
                if not all(fragment in text for fragment in required):
                    raise ValueError(f"stock split notice facts missing: {url}")
                raw.append(
                    {
                        "stock_secid": event["stock_secid"],
                        "role": role,
                        "url": url,
                        "status_code": response.status_code,
                        "content_type": content_type,
                        "retrieved_at_utc": datetime.now(UTC).isoformat(),
                        "content_sha256": _sha_bytes(content),
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                )
        events_path = temporary / "events.json"
        affected_path = temporary / "affected_contracts.parquet"
        raw_path = temporary / "official_moex_notices.jsonl.gz"
        write_json(events_path, payload["events"])
        affected = _adjusted_contracts(payload)
        storage._write_parquet(affected_path, affected)
        atomic_write_bytes(raw_path, _raw_bytes(raw))
        manifest = {
            "bundle_id": OUTPUT_ROOT.name,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_only": True,
            "contains_basis_returns_targets_signals_predictions_equity_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {"events": 4, "affected_contracts": 27, "raw_responses": 8},
            "artifacts": {
                "events": storage._artifact(events_path, 4),
                "affected_contracts": storage._artifact(affected_path, len(affected)),
                "raw": storage._artifact(raw_path, len(raw)),
            },
            "limitations": payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        audit = _audit_directory(temporary, payload)
        if not audit["all_true"]:
            raise ValueError(f"stock split source audit failed: {audit}")
        write_json(temporary / "audit.json", audit)
        temporary.replace(OUTPUT_ROOT)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return OUTPUT_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args(argv)
    payload = load_protocol()
    if args.audit_only:
        audit = _audit_directory(OUTPUT_ROOT, payload)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0 if audit["all_true"] else 1
    output = collect(payload)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
