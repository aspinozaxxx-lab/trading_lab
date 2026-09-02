"""Collect delayed public-ISS cross-market BBO with depth explicitly unresolved."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_forward_cross_market_bbo_source as v1
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_cross_market_bbo_source_v2.yaml"
)
CONFIG_SHA256: Final[str] = (
    "d4d8910ce884d2831c08387c3927c6f41a16a912a741ce8f8af2d8553731b649"
)
PARENT_CONFIG_SHA256: Final[str] = v1.CONFIG_SHA256
REMOVED_SOURCE_UNAVAILABLE_REASONS: Final[frozenset[str]] = frozenset(
    {"positive_best_depth_missing"}
)


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent_path = PROJECT_ROOT / correction["parent_v1"]["config"]
    parent = v1.load_config()
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or correction.get("protocol_id")
        != "moex_forward_cross_market_bbo_source_v2"
        or correction.get("live_trading_allowed") is not False
        or _sha(parent_path) != PARENT_CONFIG_SHA256
        or correction["parent_v1"]["config_sha256"] != PARENT_CONFIG_SHA256
        or int(
            correction["correction_scope"][
                "parameters_universe_contract_selection_schedule_and_http_requests_changed"
            ]
        )
        != 0
    ):
        raise ValueError("delayed cross-market V2 protocol drifted")
    config = copy.deepcopy(parent)
    config["protocol_id"] = correction["protocol_id"]
    config["protocol_version"] = 2
    config["status"] = correction["status"]
    config["official_sources"]["access_mode"] = correction["access_semantics"]["mode"]
    config["output"] = correction["output"]
    config["readiness"] = {
        "discovery_sessions_source_only": correction["readiness"][
            "discovery_sessions_source_only"
        ],
        "minimum_complete_core_snapshots_per_session": correction["readiness"][
            "minimum_quote_complete_snapshots_per_session"
        ],
        "calibration_sessions_after_separate_economic_seal": correction["readiness"][
            "calibration_sessions_after_separate_economic_seal"
        ],
        "unseen_evaluation_sessions_after_calibration": correction["readiness"][
            "unseen_evaluation_sessions_after_calibration"
        ],
    }
    config["limitations"] = correction["limitations"]
    return config


def _safe_output_root(value: str) -> Path:
    return v1._safe_output_root(value)


def _remove_unavailable_depth_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for index, value in output["invalid_reason"].items():
        reasons = [] if pd.isna(value) else str(value).split("|")
        remaining = [
            reason for reason in reasons if reason not in REMOVED_SOURCE_UNAVAILABLE_REASONS
        ]
        output.at[index, "invalid_reason"] = "|".join(remaining) if remaining else pd.NA
        output.at[index, "valid"] = not remaining
    return output


def normalize_snapshot(
    raw: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    source_date,
    retrieval: pd.Timestamp,
    slot: pd.Timestamp,
) -> pd.DataFrame:
    frame = v1.normalize_snapshot(
        raw,
        config=config,
        source_date=source_date,
        retrieval=retrieval,
        slot=slot,
    )
    return _remove_unavailable_depth_reasons(frame)


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
        raise FileExistsError(f"duplicate delayed cross-market snapshot slot: {final}")
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
            "parent_v1_config_sha256": PARENT_CONFIG_SHA256,
            "parent_v1_implementation_sha256": _sha(Path(v1.__file__)),
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
        raise ValueError("delayed cross-market V2 snapshot audit failed")
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
    boundary = pd.Timestamp(config["forward_boundary"]["earliest_source_date"]).date()
    return {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == _sha(Path(__file__)),
        "parent_hashes_exact": manifest["parent_v1_config_sha256"]
        == PARENT_CONFIG_SHA256
        and manifest["parent_v1_implementation_sha256"] == _sha(Path(v1.__file__)),
        "source_only": manifest["source_only"] is True,
        "depth_and_realtime_unresolved": manifest["depth_and_realtime_unresolved"] is True,
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
        "counts_exact": len(stored) == 39 and len(core) == 35 and len(raw) == 4,
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
