"""Joint source-quality admission for V41 stock/futures/LQDT forward snapshots."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_forward_lqdt_idle_cash_source as lqdt_source
from market_lab.futures import moex_forward_stock_futures_cash_carry_source as stock_source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v41_forward_execution_admission_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "8183eb50f3aabcdc50b9399eb4bd512c7713425a0c16343cf2299ad1de7e5a50"
)


def _sha(path: Path) -> str:
    return stock_source.daily_source.sha256_file(path)


def _safe_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V41 forward root: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "forward"):
        raise ValueError("V41 forward root must be under data/forward")
    return PROJECT_ROOT / relative


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V41 forward execution admission config must be an object")
    parents = payload["parents"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "v41_forward_execution_admission_v1"
        or payload.get("live_trading_allowed") is not False
        or parents["stock_futures"]["config_sha256"] != stock_source.CONFIG_SHA256
        or parents["idle_cash"]["config_sha256"] != lqdt_source.CONFIG_SHA256
        or int(payload["joint_timing"]["maximum_same_stage_retrieval_skew_seconds"])
        != 30
        or int(payload["depth_admission"]["spot"]["shares_per_covered_unit"]) != 100
        or int(payload["depth_admission"]["futures"]["contracts_per_covered_unit"]) != 1
    ):
        raise ValueError("V41 forward execution admission config drifted")
    return payload


def phase_progress(count: int, readiness: dict[str, Any]) -> dict[str, Any]:
    discovery_required = int(readiness["discovery_complete_joint_dates"])
    calibration_required = int(readiness["calibration_joint_dates_after_discovery"])
    evaluation_required = int(readiness["unseen_evaluation_joint_dates_after_calibration"])
    discovery = min(count, discovery_required)
    calibration = min(max(count - discovery_required, 0), calibration_required)
    evaluation = min(
        max(count - discovery_required - calibration_required, 0), evaluation_required
    )
    if discovery < discovery_required:
        phase = "discovery"
    elif calibration < calibration_required:
        phase = "calibration"
    elif evaluation < evaluation_required:
        phase = "unseen_evaluation"
    else:
        phase = "independent_review"
    return {
        "current_phase": phase,
        "discovery": {"complete": discovery, "required": discovery_required},
        "calibration": {"complete": calibration, "required": calibration_required},
        "unseen_evaluation": {"complete": evaluation, "required": evaluation_required},
        "remaining_to_economic_protocol_seal": max(discovery_required - count, 0),
        "remaining_to_unseen_evaluation_complete": max(
            discovery_required + calibration_required + evaluation_required - count,
            0,
        ),
        "economic_protocol_may_be_sealed": discovery == discovery_required,
        "annualization_allowed": evaluation == evaluation_required,
        "live_trading_allowed": False,
    }


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _exact_row(
    payload: dict[str, Any],
    block: str,
    secid: str,
    board: str,
    required: frozenset[str],
) -> dict[str, Any]:
    frame = iss._parse_iss_block(payload, block, required | {"secid", "boardid"})
    rows = frame.loc[
        frame["secid"].astype(str).eq(secid)
        & frame["boardid"].astype(str).eq(board)
    ]
    if len(rows) != 1:
        raise ValueError(f"{block} identity missing or duplicate for {secid}/{board}")
    return rows.iloc[0].to_dict()


def _depth_values(payload: dict[str, Any], secid: str, board: str) -> tuple[float, float]:
    row = _exact_row(
        payload,
        "marketdata",
        secid,
        board,
        frozenset({"biddepth", "offerdepth"}),
    )
    bid = _number(row.get("biddepth"))
    offer = _number(row.get("offerdepth"))
    if bid is None or offer is None or bid <= 0 or offer <= 0:
        raise ValueError(f"nonpositive best depth for {secid}/{board}")
    return bid, offer


def _stock_depth(snapshot: Path, config: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    raw_path = snapshot / manifest["artifacts"]["raw"]["file"]
    records = stock_source.daily_source._read_raw(raw_path)
    spot_required_shares = int(
        config["depth_admission"]["spot"]["shares_per_covered_unit"]
    )
    expected_assets = set(stock_source.load_protocol().payload["universe"]["logical_assets"])
    seen: set[tuple[str, str]] = set()
    coverage: list[float] = []
    details: list[dict[str, Any]] = []
    for item in records:
        kind = str(item.get("kind"))
        if kind not in {"marketdata_spot", "marketdata_futures"}:
            continue
        asset = str(item["logical_asset"])
        secid = str(item["secid"])
        payload = item["payload"]
        if asset not in expected_assets:
            raise ValueError(f"unexpected stock-depth asset: {asset}")
        venue = "spot" if kind == "marketdata_spot" else "futures"
        board = "TQBR" if venue == "spot" else "RFUD"
        identity = (asset, venue)
        if identity in seen:
            raise ValueError(f"duplicate stock-depth identity: {identity}")
        seen.add(identity)
        bid, offer = _depth_values(payload, secid, board)
        if venue == "spot":
            security = _exact_row(
                payload,
                "securities",
                secid,
                board,
                frozenset({"lotsize"}),
            )
            lot_size = _number(security.get("lotsize"))
            if (
                lot_size is None
                or lot_size <= 0
                or not float(lot_size).is_integer()
                or spot_required_shares % int(lot_size) != 0
            ):
                raise ValueError(f"spot lot size cannot form 100 shares: {asset}/{secid}")
            required_units = spot_required_shares // int(lot_size)
        else:
            required_units = int(
                config["depth_admission"]["futures"]["contracts_per_covered_unit"]
            )
        minimum_multiple = min(bid, offer) / required_units
        if minimum_multiple < 1.0:
            raise ValueError(
                f"best depth below one covered unit: {asset}/{venue}={minimum_multiple}"
            )
        coverage.append(minimum_multiple)
        details.append(
            {
                "logical_asset": asset,
                "venue_kind": venue,
                "secid": secid,
                "required_order_units": required_units,
                "bid_depth_units": bid,
                "offer_depth_units": offer,
                "minimum_coverage_multiple": minimum_multiple,
            }
        )
    expected = {(asset, venue) for asset in expected_assets for venue in ("spot", "futures")}
    if seen != expected:
        raise ValueError(f"stock-depth pair set mismatch: missing={sorted(expected - seen)}")
    return {
        "minimum_coverage_multiple": min(coverage),
        "pairs": details,
    }


def _lqdt_depth(snapshot: Path) -> dict[str, float]:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    raw_path = snapshot / manifest["artifacts"]["raw"]["file"]
    records = stock_source.daily_source._read_raw(raw_path)
    if len(records) != 1 or not isinstance(records[0].get("payload"), dict):
        raise ValueError("LQDT raw response count drifted")
    bid, offer = _depth_values(records[0]["payload"], "LQDT", "TQBR")
    return {"bid_depth_units": bid, "offer_depth_units": offer}


def _parent_entries(
    root: Path,
    audit_function: Any,
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, str]], dict[str, list[str]]]:
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    invalid: list[dict[str, str]] = []
    duplicates: dict[str, list[str]] = defaultdict(list)
    for snapshot in sorted(path for path in root.glob("snapshot_*") if path.is_dir()):
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            checks = audit_function(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"parent audit failed: {', '.join(failed)}")
            if manifest["status"] != "complete_valid":
                raise ValueError(f"parent status is {manifest['status']}")
            key = (str(manifest["source_date"]), str(manifest["stage"]))
            if key in entries:
                label = f"{key[0]}:{key[1]}"
                duplicates[label].extend([entries[key]["snapshot"].name, snapshot.name])
                del entries[key]
                continue
            if f"{key[0]}:{key[1]}" in duplicates:
                duplicates[f"{key[0]}:{key[1]}"].append(snapshot.name)
                continue
            entries[key] = {"snapshot": snapshot, "manifest": manifest}
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})
    return entries, invalid, {key: sorted(set(value)) for key, value in duplicates.items()}


def _forbidden_keys(value: Any, fragments: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(
            any(fragment in str(key).lower() for fragment in fragments)
            or _forbidden_keys(item, fragments)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_forbidden_keys(item, fragments) for item in value)
    return False


def assess(
    stock_root: Path | None = None,
    lqdt_root: Path | None = None,
) -> dict[str, Any]:
    config = load_config()
    stock_path = (
        stock_root or _safe_root(config["parents"]["stock_futures"]["root"])
    ).resolve()
    lqdt_path = (lqdt_root or _safe_root(config["parents"]["idle_cash"]["root"])).resolve()
    stock_entries, stock_invalid, stock_duplicates = _parent_entries(
        stock_path, stock_source.audit
    )
    lqdt_entries, lqdt_invalid, lqdt_duplicates = _parent_entries(
        lqdt_path, lqdt_source.audit
    )
    boundary = date.fromisoformat(config["forward_boundary"]["earliest_source_date"])
    stages = tuple(config["joint_timing"]["required_stages"])
    maximum_skew = float(
        config["joint_timing"]["maximum_same_stage_retrieval_skew_seconds"]
    )
    dates = sorted(
        {key[0] for key in stock_entries} | {key[0] for key in lqdt_entries}
    )
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for source_date in dates:
        try:
            if date.fromisoformat(source_date) < boundary:
                raise ValueError("joint source date precedes boundary")
            required_keys = [(source_date, stage) for stage in stages]
            if any(key not in stock_entries for key in required_keys):
                raise ValueError("stock parent lacks both complete stages")
            if any(key not in lqdt_entries for key in required_keys):
                raise ValueError("LQDT parent lacks both complete stages")
            stage_records: list[dict[str, Any]] = []
            stock_times: list[pd.Timestamp] = []
            lqdt_times: list[pd.Timestamp] = []
            for stage in stages:
                key = (source_date, stage)
                stock_item = stock_entries[key]
                lqdt_item = lqdt_entries[key]
                stock_at = pd.Timestamp(stock_item["manifest"]["retrieved_at_utc"])
                lqdt_at = pd.Timestamp(lqdt_item["manifest"]["retrieved_at_utc"])
                skew = abs((stock_at - lqdt_at).total_seconds())
                if skew > maximum_skew:
                    raise ValueError(f"same-stage retrieval skew exceeds {maximum_skew}s")
                stock_depth = _stock_depth(stock_item["snapshot"], config)
                lqdt_depth = _lqdt_depth(lqdt_item["snapshot"])
                stock_times.append(stock_at)
                lqdt_times.append(lqdt_at)
                stage_records.append(
                    {
                        "stage": stage,
                        "retrieval_skew_seconds": skew,
                        "stock_minimum_depth_coverage_multiple": stock_depth[
                            "minimum_coverage_multiple"
                        ],
                        "LQDT_bid_depth_units": lqdt_depth["bid_depth_units"],
                        "LQDT_offer_depth_units": lqdt_depth["offer_depth_units"],
                    }
                )
            if stock_times[1] <= stock_times[0] or lqdt_times[1] <= lqdt_times[0]:
                raise ValueError("fill retrieval is not after decision retrieval")
            admitted.append({"source_date": source_date, "stages": stage_records})
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            rejected.append({"source_date": source_date, "reason": str(error)})
    report = {
        "protocol_id": config["protocol_id"],
        "config_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "stock_root": str(stock_path),
        "LQDT_root": str(lqdt_path),
        "joint_date_count": len(admitted),
        "rejected_joint_date_count": len(rejected),
        "admitted_joint_dates": admitted,
        "rejected_joint_dates": rejected,
        "stock_invalid_snapshots": stock_invalid,
        "LQDT_invalid_snapshots": lqdt_invalid,
        "stock_duplicate_stage_dates": stock_duplicates,
        "LQDT_duplicate_stage_dates": lqdt_duplicates,
        "paper_economics_allowed": False,
        "progress": phase_progress(len(admitted), config["readiness"]),
    }
    forbidden = tuple(str(item).lower() for item in config["forbidden_outputs"])
    if _forbidden_keys(report, forbidden):
        raise ValueError("V41 forward admission report leaked forbidden output keys")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-root", type=Path)
    parser.add_argument("--lqdt-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(assess(args.stock_root, args.lqdt_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
