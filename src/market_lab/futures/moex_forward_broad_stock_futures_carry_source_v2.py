"""Collect delayed broad stock-futures BBO pairs with depth unresolved."""

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
from market_lab.futures import moex_forward_broad_stock_futures_carry_source as v1
from market_lab.futures import moex_forward_cross_market_bbo_source as cross_v1
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_broad_stock_futures_carry_source_v2.yaml"
)
CONFIG_SHA256: Final[str] = (
    "cb753e017dd2decbd6eb85f7100ac65823ae827e733e45c2c7fed14dbf66c2b8"
)
PARENT_CONFIG_SHA256: Final[str] = v1.CONFIG_SHA256
REMOVED_SOURCE_UNAVAILABLE_REASONS: Final[frozenset[str]] = frozenset(
    {"spot_positive_best_depth_missing", "futures_positive_best_depth_missing"}
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
        != "moex_forward_broad_stock_futures_carry_source_v2"
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
        raise ValueError("delayed broad carry V2 protocol drifted")
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
        "minimum_complete_snapshots_per_session": correction["readiness"][
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
    return "complete_30_pair_quotes" if bool(frame["valid"].all()) else "invalid_pair_quotes"


def collect(
    output_root: Path | None = None,
    *,
    client=None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    source_date, retrieval, slot = cross_v1._source_context(config, retrieved_at)
    root = (output_root or _safe_output_root(str(config["output"]["root"]))).resolve()
    final = root / f"snapshot_{slot:%Y%m%dT%H%M}_moscow"
    if final.exists():
        raise FileExistsError(f"duplicate delayed broad carry snapshot slot: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or network.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        series_url = v1._series_url(config)
        series_payload = active.get_json(series_url)
        raw.append({"kind": "series", "url": series_url, "payload": series_payload})
        selected = v1.select_contracts(series_payload, source_date, config)
        futures_secids = [item[1] for item in selected.values() if item is not None]
        spot_url = v1._venue_url(
            str(config["official_sources"]["spots_bulk"]),
            list(config["universe"]["exact_stock_order"]),
            v1.SPOT_SECURITY_COLUMNS,
        )
        futures_url = v1._venue_url(
            str(config["official_sources"]["futures_bulk"]),
            futures_secids,
            v1.FUTURES_SECURITY_COLUMNS,
        )
        raw.append({"kind": "spots", "url": spot_url, "payload": active.get_json(spot_url)})
        raw.append(
            {
                "kind": "futures",
                "url": futures_url,
                "payload": active.get_json(futures_url),
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
        pairs_path = temporary / "stock_futures_pairs.parquet"
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        storage._write_parquet(pairs_path, frame)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "parent_v1_config_sha256": PARENT_CONFIG_SHA256,
            "parent_v1_implementation_sha256": _sha(Path(v1.__file__)),
            "shared_cross_v1_implementation_sha256": _sha(Path(cross_v1.__file__)),
            "source_date": source_date.isoformat(),
            "scheduled_slot_moscow": slot.isoformat(),
            "retrieved_at_utc": retrieval.isoformat(),
            "status": _status(frame),
            "source_only": True,
            "depth_realtime_and_fill_unresolved": True,
            "contains_basis_return_signal_trade_or_pnl": False,
            "live_trading_allowed": False,
            "counts": {
                "rows": len(frame),
                "quote_complete_pairs": int(frame["valid"].sum()),
                "raw_responses": len(raw),
            },
            "artifacts": {
                "pairs": storage._artifact(pairs_path, len(frame)),
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
        raise ValueError("delayed broad carry V2 snapshot audit failed")
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
    pairs_path = root / manifest["artifacts"]["pairs"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt = normalize_snapshot(
        raw,
        config=config,
        source_date=source_date,
        retrieval=retrieval,
        slot=slot,
    )
    stored = pd.read_parquet(pairs_path)
    try:
        pd.testing.assert_frame_equal(
            stored.astype(object).where(stored.notna(), None),
            rebuilt.astype(object).where(rebuilt.notna(), None),
            check_dtype=False,
        )
        replay_exact = True
    except AssertionError:
        replay_exact = False
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
        and manifest["parent_v1_implementation_sha256"] == _sha(Path(v1.__file__))
        and manifest["shared_cross_v1_implementation_sha256"]
        == _sha(Path(cross_v1.__file__)),
        "source_only": manifest["source_only"] is True,
        "depth_realtime_and_fill_unresolved": manifest[
            "depth_realtime_and_fill_unresolved"
        ]
        is True,
        "outcomes_absent": manifest["contains_basis_return_signal_trade_or_pnl"] is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "forward_date_exact": source_date >= boundary
        and source_date == retrieval.tz_convert(cross_v1.MOSCOW_TZ).date(),
        "status_exact": manifest["status"] == _status(rebuilt),
        "pairs_sha_exact": _sha(pairs_path) == manifest["artifacts"]["pairs"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "counts_exact": len(stored) == 30 and len(raw) == 3,
        "identity_exact": set(stored["stock_secid"])
        == set(config["universe"]["exact_stock_order"])
        and not stored["stock_secid"].duplicated().any(),
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
