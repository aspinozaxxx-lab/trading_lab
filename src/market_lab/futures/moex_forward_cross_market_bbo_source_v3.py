"""Collect delayed cross-market BBO with exact CNY perpetual futures context."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_forward_cross_market_bbo_source as v1
from market_lab.futures import moex_forward_cross_market_bbo_source_v2 as v2
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_cross_market_bbo_source_v3.yaml"
)
CONFIG_SHA256: Final[str] = (
    "f680f8bbe0196d9ce862413be6bc33432edf89df7267abcde792d74c3274d016"
)
PARENT_CONFIG_SHA256: Final[str] = v2.CONFIG_SHA256
CNY_PERPETUAL_SECID: Final[str] = "CNYRUBF"
CNY_PERPETUAL_LOGICAL_ASSET: Final[str] = "CNYRUB_PERPETUAL"
CNY_SPOT_SECID: Final[str] = "CNYRUB_TOM"


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent_path = PROJECT_ROOT / correction["parent_v2"]["config"]
    parent_implementation = PROJECT_ROOT / correction["parent_v2"]["implementation"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or correction.get("protocol_id")
        != "moex_forward_cross_market_bbo_source_v3"
        or correction.get("live_trading_allowed") is not False
        or _sha(parent_path) != PARENT_CONFIG_SHA256
        or correction["parent_v2"]["config_sha256"] != PARENT_CONFIG_SHA256
        or _sha(parent_implementation)
        != correction["parent_v2"]["implementation_sha256"]
        or correction["additional_source"]["exact_secid"] != CNY_PERPETUAL_SECID
        or correction["correction_scope"]["expected_rows"] != 40
        or correction["correction_scope"]["expected_core_rows"] != 35
    ):
        raise ValueError("CNY-perpetual cross-market V3 protocol drifted")
    config = copy.deepcopy(v2.load_config())
    config["protocol_id"] = correction["protocol_id"]
    config["protocol_version"] = 3
    config["status"] = correction["status"]
    config["output"] = correction["output"]
    config["readiness"] = correction["readiness"]
    config["limitations"] = correction["limitations"]
    config["v3_correction"] = correction["correction_scope"]
    config["cny_perpetual"] = correction["additional_source"]
    return config


def _safe_output_root(value: str) -> Path:
    return v1._safe_output_root(value)


def cny_perpetual_url(config: dict[str, Any]) -> str:
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": ",".join(v1.SECURITY_COLUMNS),
            "marketdata.columns": ",".join(v1.MARKET_COLUMNS),
            "securities": CNY_PERPETUAL_SECID,
        }
    )
    return f"{config['cny_perpetual']['endpoint']}?{query}"


def normalize_snapshot(
    raw: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    source_date,
    retrieval: pd.Timestamp,
    slot: pd.Timestamp,
) -> pd.DataFrame:
    payloads = {str(item["kind"]): item["payload"] for item in raw}
    expected = {"series", "equities", "futures", "fx", "cny_perpetual"}
    if set(payloads) != expected:
        raise ValueError("CNY-perpetual V3 raw request identity drifted")
    parent_raw = [item for item in raw if item["kind"] != "cny_perpetual"]
    frame = v2.normalize_snapshot(
        parent_raw,
        config=config,
        source_date=source_date,
        retrieval=retrieval,
        slot=slot,
    )
    spot_mask = frame["logical_asset"].astype(str).eq(CNY_SPOT_SECID)
    if int(spot_mask.sum()) != 1 or not bool(frame.loc[spot_mask, "core_required"].iloc[0]):
        raise ValueError("CNY spot parent identity drifted")
    frame.loc[spot_mask, "core_required"] = False
    securities, market = v1._blocks(payloads["cny_perpetual"])
    row = v1._row(
        securities,
        market,
        source_date=source_date,
        slot=slot,
        retrieval=retrieval,
        venue_kind="currency_futures_context",
        logical_asset=CNY_PERPETUAL_LOGICAL_ASSET,
        secid=CNY_PERPETUAL_SECID,
        board=v1.FUTURES_BOARD,
        expiration=None,
        core_required=True,
        access_mode=str(config["official_sources"]["access_mode"]),
    )
    perpetual = v2._remove_unavailable_depth_reasons(
        pd.DataFrame([row], columns=v1.OUTPUT_COLUMNS)
    )
    frame = pd.concat([frame, perpetual], ignore_index=True).sort_values(
        ["venue_kind", "logical_asset"], ignore_index=True
    )
    if len(frame) != 40 or int(frame["core_required"].sum()) != 35:
        raise ValueError("CNY-perpetual V3 normalized universe count drifted")
    if frame.duplicated(["venue_kind", "logical_asset"]).any():
        raise ValueError("CNY-perpetual V3 identity is not unique")
    if v1._forbidden_columns(frame, config):
        raise ValueError("CNY-perpetual V3 leaked a forbidden column")
    return frame


def _status(frame: pd.DataFrame) -> str:
    core = frame.loc[frame["core_required"]]
    return "complete_core_quotes" if bool(core["valid"].all()) else "invalid_core_quotes"


def collect(
    output_root: Path | None = None,
    *,
    client=None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_date, retrieval, slot = v1._source_context(config, retrieved_at)
    root = (output_root or _safe_output_root(str(config["output"]["root"]))).resolve()
    final = root / f"snapshot_{slot:%Y%m%dT%H%M}_moscow"
    if final.exists():
        raise FileExistsError(f"duplicate CNY-perpetual V3 snapshot slot: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or network.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        series_url = v1.request_urls(config, ["metadata_selection_pending"])["series"]
        series_payload = active.get_json(series_url)
        raw.append({"kind": "series", "url": series_url, "payload": series_payload})
        selected = v1.select_futures_contracts(series_payload, source_date, config)
        futures_secids = [item[0] for item in selected.values() if item is not None]
        urls = v1.request_urls(config, futures_secids)
        for kind in ("equities", "futures", "fx"):
            url = urls[kind]
            raw.append({"kind": kind, "url": url, "payload": active.get_json(url)})
        perpetual_url = cny_perpetual_url(config)
        raw.append(
            {
                "kind": "cny_perpetual",
                "url": perpetual_url,
                "payload": active.get_json(perpetual_url),
            }
        )
        frame = normalize_snapshot(
            raw,
            config=config,
            source_date=source_date,
            retrieval=retrieval,
            slot=slot,
        )
        raw_path = temporary / "official_moex_responses.jsonl.gz"
        snapshot_path = temporary / "cross_market_snapshot.parquet"
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        storage._write_parquet(snapshot_path, frame)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "parent_v2_config_sha256": PARENT_CONFIG_SHA256,
            "parent_v2_implementation_sha256": _sha(Path(v2.__file__)),
            "source_date": source_date.isoformat(),
            "scheduled_slot_moscow": slot.isoformat(),
            "retrieved_at_utc": retrieval.isoformat(),
            "status": _status(frame),
            "source_only": True,
            "depth_and_realtime_unresolved": True,
            "contains_returns_labels_signals_predictions_trades_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "rows": len(frame),
                "core_rows": int(frame["core_required"].sum()),
                "quote_complete_core_rows": int(
                    frame.loc[frame["core_required"], "valid"].sum()
                ),
                "context_rows": int((~frame["core_required"]).sum()),
                "raw_responses": len(raw),
            },
            "artifacts": {
                "snapshot": storage._artifact(snapshot_path, len(frame)),
                "raw": storage._artifact(raw_path, len(raw)),
            },
            "limitations": config["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()
    checks = audit(final)
    write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("CNY-perpetual V3 snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    config = load_config()
    root = snapshot.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_date = pd.Timestamp(manifest["source_date"]).date()
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    slot = pd.Timestamp(manifest["scheduled_slot_moscow"])
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    snapshot_path = root / manifest["artifacts"]["snapshot"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt = normalize_snapshot(
        raw,
        config=config,
        source_date=source_date,
        retrieval=retrieval,
        slot=slot,
    )
    stored = pd.read_parquet(snapshot_path)
    try:
        pd.testing.assert_frame_equal(
            stored.astype(object).where(stored.notna(), None),
            rebuilt.astype(object).where(rebuilt.notna(), None),
            check_dtype=False,
        )
        replay_exact = True
    except AssertionError:
        replay_exact = False
    core = stored.loc[stored["core_required"]]
    cny = stored.loc[stored["logical_asset"].eq(CNY_PERPETUAL_LOGICAL_ASSET)]
    spot = stored.loc[stored["logical_asset"].eq(CNY_SPOT_SECID)]
    boundary = pd.Timestamp(config["forward_boundary"]["earliest_source_date"]).date()
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == _sha(Path(__file__)),
        "parent_hashes_exact": manifest["parent_v2_config_sha256"]
        == PARENT_CONFIG_SHA256
        and manifest["parent_v2_implementation_sha256"] == _sha(Path(v2.__file__)),
        "source_only": manifest["source_only"] is True,
        "depth_and_realtime_unresolved": manifest["depth_and_realtime_unresolved"]
        is True,
        "outcomes_absent": manifest[
            "contains_returns_labels_signals_predictions_trades_or_pnl"
        ]
        is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "forward_date_exact": source_date >= boundary
        and source_date == retrieval.tz_convert(v1.MOSCOW_TZ).date(),
        "status_exact": manifest["status"] == _status(rebuilt),
        "snapshot_sha_exact": _sha(snapshot_path)
        == manifest["artifacts"]["snapshot"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "counts_exact": len(stored) == 40 and len(core) == 35 and len(raw) == 5,
        "cny_perpetual_exact_core": len(cny) == 1
        and bool(cny["core_required"].iloc[0]),
        "cny_spot_preserved_optional": len(spot) == 1
        and not bool(spot["core_required"].iloc[0]),
        "identity_unique": not stored.duplicated(["venue_kind", "logical_asset"]).any(),
        "forbidden_columns_absent": not v1._forbidden_columns(stored, config),
        "raw_replay_exact": replay_exact,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
