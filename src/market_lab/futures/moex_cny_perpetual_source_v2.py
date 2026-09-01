"""Corrected V2 collector for the full 2022-04-26..2025 CNYRUBF range."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import requests
import yaml

from market_lab.futures import moex_cny_perpetual_source as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_cny_perpetual_source_v2.yaml"
CONFIG_SHA256: Final[str] = "9dbf7e77508759f8cc256ff4ada7ef5269be1fdf542c036f64772d972cfefdc7"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/fx_basis/moex-cny-perpetual-current-vintage-v2"
)
USER_AGENT: Final[str] = "market-lab-cny-perpetual-source/2.0 (MOEX research)"


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
        raise ValueError("CNY perpetual V2 config seal mismatch")
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    base = parent.load_config()
    if (
        correction.get("protocol_id") != "moex_cny_perpetual_source_v2"
        or correction.get("live_trading_allowed") is not False
        or correction["parent"]["config_sha256"] != parent.CONFIG_SHA256
        or correction["parent"]["failed_attempt_output_created"] is not False
        or correction["exact_override"]
        != {"path": "source.total_rows_observed", "old": 764, "new": 937}
        or correction["diagnosis"]["price_swaprate_return_or_pnl_read_for_diagnosis"]
        is not False
    ):
        raise ValueError("CNY perpetual V2 correction invariant drift")
    effective = json.loads(json.dumps(base))
    effective["protocol_id"] = correction["protocol_id"]
    effective["protocol_version"] = 2
    effective["source"]["total_rows_observed"] = int(correction["exact_override"]["new"])
    effective["output"]["root"] = correction["output"]["root"]
    effective["v2_correction"] = correction
    return effective


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: parent.SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    client: parent.SessionLike = session or requests.Session()
    description_response = client.get(
        config["source"]["description_endpoint"],
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    )
    description_response.raise_for_status()
    description_raw = bytes(description_response.content)
    parent.verify_description(description_raw, config)
    start, total = 0, None
    frames: list[pd.DataFrame] = []
    pages: list[tuple[int, str, bytes]] = []
    while total is None or start < total:
        url = parent.history_url(config, start)
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        raw = bytes(response.content)
        frame, observed_total, page_size = parent.normalize_page(
            raw, start, retrieval, config
        )
        if total is not None and total != observed_total:
            raise ValueError("CNY perpetual V2 total changed during pagination")
        total = observed_total
        frames.append(frame)
        pages.append((start, url, raw))
        start += page_size
    history = pd.concat(frames, ignore_index=True).sort_values("trade_date", ignore_index=True)
    upper = pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"])
    if (
        len(history) != int(config["source"]["total_rows_observed"])
        or history["trade_date"].duplicated().any()
        or history["trade_date"].max() >= upper
    ):
        raise ValueError("CNY perpetual V2 identity or temporal mismatch")

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable CNY perpetual V2 source exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        def persist(
            path: Path, payload: bytes, url: str, extra: dict[str, Any]
        ) -> dict[str, Any]:
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
                temporary / f"raw_history_{page_start:06d}.json.gz",
                raw,
                url,
                {"start": page_start},
            )
            for page_start, url, raw in pages
        ]
        processed = temporary / "perpetual.parquet"
        history.to_parquet(processed, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "parent_config_sha256": parent.CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "parent_implementation_sha256": _sha_file(parent.MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "contains_signal_basis_returns_labels_targets_or_pnl": False,
            "counts": {
                "rows": len(history),
                "pages": len(pages),
                "first_trade_date": history["trade_date"].min().date().isoformat(),
                "last_trade_date": history["trade_date"].max().date().isoformat(),
                "positive_trade_rows": int((history["number_of_trades"] > 0).sum()),
                "positive_volume_rows": int((history["volume"] > 0).sum()),
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
        raise ValueError("CNY perpetual V2 source audit failed")
    return output_root


def audit(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "parent_config_exact": manifest["parent_config_sha256"] == parent.CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "parent_implementation_exact": manifest["parent_implementation_sha256"]
        == _sha_file(parent.MODULE_PATH),
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

    parent.verify_description(
        load_raw(manifest["raw"]["description"], "description"), config
    )
    frames = []
    for item in manifest["raw"]["history"]:
        frame, _, _ = parent.normalize_page(
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
