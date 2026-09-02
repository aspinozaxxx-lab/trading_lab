"""Capture independently available V27 forward market and macro components."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import requests
import yaml

from market_lab.futures import info_radar
from market_lab.futures import moex_v27_forward_validation_source as parent
from market_lab.futures import v27_forward_transport_compatibility as transport

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v27_forward_components_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "242d2684a76699c97fa7bc521ffd44045ee111b4f976f6e37fcfa4613da58110"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = PROJECT_ROOT / "data/forward/v27-validation-v3-components"
COMPONENTS: Final[tuple[str, ...]] = (
    "market_execution",
    "market_decision",
    "macro_fred",
    "macro_cbr",
)


def _sha_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return transport.sha256_file(path)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent_config = config["parent_source"]
    scope = config["correction_scope"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "futures_v27_forward_components_v1"
        or config.get("live_trading_allowed") is not False
        or parent_config["protocol_sha256"] != parent.CONFIG_SHA256
        or parent_config["implementation_sha256"] != _sha(Path(parent.__file__))
        or scope["economic_hypothesis_changed"] is not False
        or scope["signal_position_or_target_changed"] is not False
        or scope["endpoint_query_or_normalization_changed"] is not False
        or scope["market_output_columns_changed"] is not False
        or scope["macro_output_columns_changed"] is not False
        or scope["availability_rule_changed"] is not False
        or scope["source_storage_atomicity_only"] is not True
        or scope["failed_component_substitution"] != "forbidden"
        or scope["cache_backfill_or_forward_fill"] != "forbidden"
    ):
        raise ValueError("V27 component source protocol drifted")
    transport.load_config()
    parent.load_config()
    return config


def _retrieval(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    result = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("V27 component retrieval timestamp must be timezone-aware")
    return result.tz_convert("UTC")


def _fetch_market(
    component_config: dict[str, Any],
    source_config: dict[str, Any],
    component: str,
    retrieval: pd.Timestamp,
    client: parent.SessionLike,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], list[str]]:
    snapshot_kind = (
        "execution_observation" if component == "market_execution" else "decision_eod"
    )
    raw: dict[str, dict[str, Any]] = {}
    frames: list[pd.DataFrame] = []
    for logical_asset in component_config["components"][component]["required_sources"][:4]:
        asset = str(logical_asset).removeprefix("MOEX_current_")
        response = parent._get_with_retries(client, parent.market_url(source_config, asset))
        response.raise_for_status()
        payload = bytes(response.content)
        raw[f"market_{asset}"] = {
            "payload": payload,
            "url": parent.market_url(source_config, asset),
            "logical_asset": asset,
        }
        frames.append(
            parent.normalize_market(payload, asset, snapshot_kind, retrieval, source_config)
        )
    current = pd.concat(frames, ignore_index=True).sort_values(
        ["logical_asset", "last_trade_date", "secid"], kind="stable", ignore_index=True
    )
    source_dates = current["source_date"].dt.date.astype(str).unique().tolist()
    if len(source_dates) != 1 or current.duplicated(
        ["logical_asset", "boardid", "secid"]
    ).any():
        raise ValueError("V27 component market date or identity mismatch")
    if source_dates[0] < str(
        component_config["forward_boundary"]["earliest_market_source_date"]
    ):
        raise ValueError("V27 component market source date precedes seal")
    history_frames: list[pd.DataFrame] = []
    if snapshot_kind == "decision_eod":
        for row in current.itertuples(index=False):
            source_date = pd.Timestamp(row.source_date)
            url = parent.history_url(source_config, str(row.secid), source_date)
            response = parent._get_with_retries(client, url)
            response.raise_for_status()
            payload = bytes(response.content)
            safe = "".join(character for character in str(row.secid) if character.isalnum())
            label = f"history_{row.logical_asset}_{safe}"
            raw[label] = {
                "payload": payload,
                "url": url,
                "logical_asset": str(row.logical_asset),
                "boardid": str(row.boardid),
                "secid": str(row.secid),
                "source_date": source_dates[0],
            }
            history_frames.append(
                parent.normalize_official_history(
                    payload,
                    logical_asset=str(row.logical_asset),
                    boardid=str(row.boardid),
                    secid=str(row.secid),
                    source_date=source_date,
                    config=source_config,
                )
            )
    return (
        parent.attach_official_history(current, history_frames, snapshot_kind),
        raw,
        source_dates,
    )


def _fetch_macro(
    component: str,
    retrieval: pd.Timestamp,
    client: parent.SessionLike,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    if component == "macro_fred":
        url = parent.fred_url(retrieval)
        response = parent._get_with_retries(client, url)
        response.raise_for_status()
        payload = bytes(response.content)
        return parent.parse_fred_forward(payload, retrieval), {
            "fred_stlfsi4": {"payload": payload, "url": url}
        }
    start, end = parent.macro_bounds(retrieval)
    ruonia_url = info_radar.build_cbr_ruonia_url(start, end)
    ruonia_response = parent._get_with_retries(client, ruonia_url)
    ruonia_response.raise_for_status()
    key_body = info_radar.build_cbr_key_rate_soap(start, end)
    key_response = parent._post_with_retries(
        client,
        info_radar.CBR_DAILY_INFO_ENDPOINT,
        data=key_body,
        headers={
            "User-Agent": parent.USER_AGENT,
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://web.cbr.ru/KeyRateXML",
        },
    )
    key_response.raise_for_status()
    ruonia = bytes(ruonia_response.content)
    key_rate = bytes(key_response.content)
    return parent.normalize_cbr_forward(ruonia, key_rate, retrieval), {
        "cbr_ruonia": {"payload": ruonia, "url": ruonia_url},
        "cbr_key_rate": {
            "payload": key_rate,
            "url": info_radar.CBR_DAILY_INFO_ENDPOINT,
            "request_body_bytes": len(key_body),
            "request_body_sha256": _sha_bytes(key_body),
        },
    }


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    component: str,
    session: parent.SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_config = parent.load_config()
    if component not in COMPONENTS:
        raise ValueError("unknown V27 forward component")
    retrieval = _retrieval(retrieved_at)
    boundary = pd.Timestamp(config["forward_boundary"]["earliest_component_retrieval_at_utc"])
    if retrieval < boundary:
        raise ValueError("V27 component retrieval precedes component seal")
    client: parent.SessionLike = session or requests.Session()
    source_dates: list[str] = []
    if component.startswith("market_"):
        processed, raw, source_dates = _fetch_market(
            config, source_config, component, retrieval, client
        )
        processed_name = "market"
    else:
        processed, raw = _fetch_macro(component, retrieval, client)
        processed_name = "macro"

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_{component}_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_manifest: dict[str, dict[str, Any]] = {}
        for label, item in raw.items():
            payload = bytes(item["payload"])
            path = temporary / f"raw_{label}.bin.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            declaration = {
                key: value for key, value in item.items() if key != "payload"
            }
            declaration.update(
                {
                    "path": path.name,
                    "response_bytes": len(payload),
                    "response_sha256": _sha_bytes(payload),
                    "stored_bytes": path.stat().st_size,
                    "stored_sha256": _sha(path),
                }
            )
            raw_manifest[label] = declaration
        processed_path = temporary / f"{processed_name}.parquet"
        processed.to_parquet(processed_path, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(MODULE_PATH),
            "parent_protocol_sha256": parent.CONFIG_SHA256,
            "parent_implementation_sha256": _sha(Path(parent.__file__)),
            "component": component,
            "retrieved_at_utc": retrieval.isoformat(),
            "source_dates": source_dates,
            "status": "complete_valid",
            "forward_only": True,
            "contains_return_label_target_prediction_or_pnl": False,
            "raw": raw_manifest,
            "processed": {
                "name": processed_name,
                "path": processed_path.name,
                "bytes": processed_path.stat().st_size,
                "sha256": _sha(processed_path),
                "rows": len(processed),
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
        raise ValueError("V27 forward component audit failed")
    return final


def _replay(
    manifest: dict[str, Any], raw: dict[str, bytes], source_config: dict[str, Any]
) -> pd.DataFrame:
    component = str(manifest["component"])
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    if component.startswith("market_"):
        snapshot_kind = (
            "execution_observation" if component == "market_execution" else "decision_eod"
        )
        market_frames = [
            parent.normalize_market(
                raw[label],
                label.removeprefix("market_"),
                snapshot_kind,
                retrieval,
                source_config,
            )
            for label in sorted(raw)
            if label.startswith("market_")
        ]
        current = pd.concat(market_frames, ignore_index=True).sort_values(
            ["logical_asset", "last_trade_date", "secid"],
            kind="stable",
            ignore_index=True,
        )
        history_frames = [
            parent.normalize_official_history(
                raw[label],
                logical_asset=str(manifest["raw"][label]["logical_asset"]),
                boardid=str(manifest["raw"][label]["boardid"]),
                secid=str(manifest["raw"][label]["secid"]),
                source_date=pd.Timestamp(manifest["raw"][label]["source_date"]),
                config=source_config,
            )
            for label in sorted(raw)
            if label.startswith("history_")
        ]
        return parent.attach_official_history(current, history_frames, snapshot_kind)
    if component == "macro_fred":
        return parent.parse_fred_forward(raw["fred_stlfsi4"], retrieval)
    return parent.normalize_cbr_forward(
        raw["cbr_ruonia"], raw["cbr_key_rate"], retrieval
    )


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    source_config = parent.load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha(MODULE_PATH),
        "parent_protocol_exact": manifest["parent_protocol_sha256"] == parent.CONFIG_SHA256,
        "parent_implementation_exact": manifest["parent_implementation_sha256"]
        == _sha(Path(parent.__file__)),
        "known_component": manifest["component"] in COMPONENTS,
        "complete_valid": manifest["status"] == "complete_valid",
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest["contains_return_label_target_prediction_or_pnl"] is False,
    }
    raw: dict[str, bytes] = {}
    for label, item in manifest["raw"].items():
        path = snapshot / item["path"]
        payload = gzip.decompress(path.read_bytes())
        raw[label] = payload
        checks[f"raw_{label}_stored_exact"] = (
            path.stat().st_size == int(item["stored_bytes"])
            and _sha(path) == item["stored_sha256"]
        )
        checks[f"raw_{label}_response_exact"] = (
            len(payload) == int(item["response_bytes"])
            and _sha_bytes(payload) == item["response_sha256"]
        )
    rebuilt = _replay(manifest, raw, source_config)
    declaration = manifest["processed"]
    path = snapshot / declaration["path"]
    stored = pd.read_parquet(path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    checks.update(
        {
            "processed_exact": path.stat().st_size == int(declaration["bytes"])
            and _sha(path) == declaration["sha256"],
            "processed_rows_exact": len(stored) == int(declaration["rows"]),
            "raw_replay_exact": replay_exact,
            "retrieval_after_seal": pd.Timestamp(manifest["retrieved_at_utc"])
            >= pd.Timestamp(config["forward_boundary"]["earliest_component_retrieval_at_utc"]),
        }
    )
    if manifest["component"].startswith("market_"):
        checks["market_source_date_after_seal"] = bool(manifest["source_dates"]) and all(
            value >= config["forward_boundary"]["earliest_market_source_date"]
            for value in manifest["source_dates"]
        )
        checks["market_columns_exact"] = tuple(stored.columns) == (
            parent.CURRENT_MARKET_COLUMNS + parent.OFFICIAL_HISTORY_COLUMNS
        )
    else:
        required = set(config["components"][manifest["component"]]["required_series"])
        checks["macro_series_exact"] = set(stored["series_id"]) == required
        checks["macro_forward_available_after_retrieval"] = bool(
            pd.to_datetime(stored["forward_available_at_utc"], utc=True)
            .ge(pd.Timestamp(manifest["retrieved_at_utc"]))
            .all()
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    elif args.component:
        print(collect(args.output_root, component=args.component))
    else:
        parser.error("--component is required unless --audit-directory is used")


if __name__ == "__main__":
    main()
