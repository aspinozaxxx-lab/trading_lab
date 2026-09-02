"""Fail-closed operational preflight for the sealed V27 forward paper program."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import moex_v27_forward_validation_source as source
from market_lab.futures import v27_forward_transport_compatibility as transport

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v27_forward_paper_v1.yaml"
CONFIG_SHA256: Final[str] = "d68f0595ab383e618f4daf1c810190fbb0479d2c6e667655bc597294d5839a76"
ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
OBSERVATION_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "asset_code",
    "secid",
    "expiration_date",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
)


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".yaml.sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("V27 forward paper config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    source_contract = config["source_contract"]
    transport.assert_compatible(source_contract["implementation_sha256"])
    if (
        config.get("protocol_id") != "futures_v27_forward_paper_v1"
        or config.get("live_trading_allowed") is not False
        or source_contract["protocol_sha256"]
        != _sha_file(PROJECT_ROOT / source_contract["protocol"])
        or int(
            config["signal_and_decision_timing"][
                "required_common_price_sessions_before_first_finite_252_return_signal"
            ]
        )
        != 253
        or config["roll"]["unavailable_calendar_policy"].startswith("block") is False
        or config["decision_panel_mapping"]["current_LAST_accepted_as_close"] is not False
        or config["evaluation"]["no_interim_cagr_or_promotion"] is not True
    ):
        raise ValueError("V27 forward paper invariants drifted")
    for item in config["frozen_parent_implementations"].values():
        if item["sha256"] != _sha_file(PROJECT_ROOT / item["path"]):
            raise ValueError(f"V27 forward parent implementation drift: {item['path']}")
    return config


def build_decision_observations(
    snapshots: list[Path], config: dict[str, Any]
) -> pd.DataFrame:
    """Map audited official history fields without computing a return or PnL."""
    mapping = config["decision_panel_mapping"]
    source_columns = [mapping[column] for column in OBSERVATION_COLUMNS]
    frames: list[pd.DataFrame] = []
    for snapshot in snapshots:
        manifest = json.loads(
            (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
        )
        if manifest["snapshot_kind"] != "decision_eod":
            raise ValueError("paper observation input must be decision_eod")
        market = pd.read_parquet(snapshot / "market.parquet")
        if missing := set(source_columns) - set(market.columns):
            raise ValueError(f"V27 V2 market lacks paper fields: {sorted(missing)}")
        frame = market.loc[:, source_columns].rename(
            columns={value: key for key, value in mapping.items() if key in OBSERVATION_COLUMNS}
        )
        frames.append(frame.loc[:, OBSERVATION_COLUMNS])
    if not frames:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    observations = pd.concat(frames, ignore_index=True)
    observations["trade_date"] = pd.to_datetime(
        observations["trade_date"], errors="raise"
    ).dt.normalize()
    observations["expiration_date"] = pd.to_datetime(
        observations["expiration_date"], errors="raise"
    ).dt.normalize()
    observations["asset_code"] = observations["asset_code"].astype("string")
    observations["secid"] = observations["secid"].astype("string")
    for column in (
        "open",
        "high",
        "low",
        "close",
        "settle",
        "volume",
        "open_interest",
    ):
        observations[column] = pd.to_numeric(observations[column], errors="coerce")
    if observations.duplicated(["trade_date", "asset_code", "secid"]).any():
        raise ValueError("duplicate V27 paper contract observation")
    if set(observations["asset_code"].dropna().astype(str)) - set(ASSETS):
        raise ValueError("undeclared asset escaped into V27 paper observations")
    return observations.sort_values(
        ["trade_date", "asset_code", "expiration_date", "secid"],
        kind="stable",
        ignore_index=True,
    )


def common_price_dates(observations: pd.DataFrame) -> list[str]:
    """Count dates with at least one factual positive official CLOSE for every asset."""
    if observations.empty:
        return []
    close = pd.to_numeric(observations["close"], errors="coerce")
    usable = observations.loc[close.notna() & np.isfinite(close) & close.gt(0.0)]
    assets_by_date = usable.groupby("trade_date")["asset_code"].agg(
        lambda values: set(values.dropna().astype(str))
    )
    return [
        date.date().isoformat()
        for date, assets in assets_by_date.items()
        if assets == set(ASSETS)
    ]


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = load_config()
    root = output_root.resolve()
    valid: dict[tuple[str, str], Path] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)
    invalid: list[dict[str, str]] = []
    for snapshot in sorted(path for path in root.glob("snapshot_*") if path.is_dir()):
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            dates = manifest["counts"]["source_dates"]
            kind = str(manifest["snapshot_kind"])
            if kind not in source.SNAPSHOT_KINDS or not isinstance(dates, list) or len(dates) != 1:
                raise ValueError("invalid snapshot kind or source date cardinality")
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"raw replay failed: {', '.join(failed)}")
            key = (kind, str(dates[0]))
            if key in valid:
                duplicate_key = f"{kind}:{dates[0]}"
                duplicates[duplicate_key].extend([valid[key].name, snapshot.name])
            else:
                valid[key] = snapshot
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})
    decision_paths = [
        path for (kind, _), path in sorted(valid.items()) if kind == "decision_eod"
    ]
    observations = build_decision_observations(decision_paths, config)
    common_dates = common_price_dates(observations)
    required = int(
        config["signal_and_decision_timing"][
            "required_common_price_sessions_before_first_finite_252_return_signal"
        ]
    )
    token_name = str(config["roll"]["calendar_auth_environment_variable"])
    calendar_auth_present = bool(os.environ.get(token_name))
    blockers = []
    if invalid:
        blockers.append("invalid_snapshot_present")
    if duplicates:
        blockers.append("duplicate_kind_source_date")
    if len(common_dates) < required:
        blockers.append("signal_warmup_incomplete")
    if not calendar_auth_present:
        blockers.append("official_future_session_calendar_authorization_missing")
    return {
        "protocol_id": config["protocol_id"],
        "config_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_root": str(root),
        "valid_unique_snapshot_count": len(valid),
        "valid_unique_decision_date_count": len(decision_paths),
        "mapped_contract_observation_rows": len(observations),
        "common_official_close_date_count": len(common_dates),
        "first_common_official_close_date": common_dates[0] if common_dates else None,
        "last_common_official_close_date": common_dates[-1] if common_dates else None,
        "required_common_price_sessions": required,
        "remaining_common_price_sessions": max(required - len(common_dates), 0),
        "calendar_auth_environment_variable": token_name,
        "calendar_authorization_present": calendar_auth_present,
        "invalid_snapshots": invalid,
        "duplicate_kind_source_dates": {
            key: sorted(set(value)) for key, value in sorted(duplicates.items())
        },
        "paper_economics_may_start": not blockers,
        "contains_return_target_prediction_or_pnl": False,
        "blockers": blockers,
        "live_trading_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
