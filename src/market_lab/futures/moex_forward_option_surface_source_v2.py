"""Preserve exchange clocks, sequence and margin in forward MOEX option snapshots."""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_forward_option_surface_source as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_forward_option_surface_source_v2.yaml"
CONFIG_SHA256: Final[str] = "f9a0646279913c75bda7ed5f0e50bbe6ae89905a44dbd6a1a1653aedc7f8d3c4"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-options-surface-v2-timestamps-margin"
)
BASE_OUTPUT_COLUMNS: Final[tuple[str, ...]] = parent.OUTPUT_COLUMNS
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    *BASE_OUTPUT_COLUMNS,
    "previous_open_interest",
    "initial_margin_non_covered",
    "initial_margin_sell",
    "initial_margin_buy",
    "initial_margin_exchange_time",
    "last_trade_quantity",
    "market_update_time",
    "last_trade_time",
    "exchange_sequence_number",
    "open_interest_change",
)
PARENT_COLLECT = parent.collect
PARENT_AUDIT = parent.audit
PARENT_NORMALIZE = parent.normalize_response


def _sha_file(path: Path) -> str:
    return parent._sha_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("forward option V2 config must be an object")
    source = config["source"]
    probe = config["schema_probe_only"]
    temporal = config["temporal_semantics"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_forward_option_surface_source_v2"
        or config.get("status") != "sealed_after_schema_and_nonnull_probe_before_first_v2_value"
        or config.get("live_trading_allowed") is not False
        or _sha_file(PROJECT_ROOT / config["parent_v1"]["config_path"])
        != config["parent_v1"]["config_sha256"]
        or _sha_file(PROJECT_ROOT / config["parent_v1"]["implementation_path"])
        != config["parent_v1"]["implementation_sha256"]
        or source["historical_backfill"] != "forbidden"
        or temporal["preboundary_or_v1_snapshot_copy"] != "forbidden"
        or probe["values_read"] is not False
        or int(probe["public_depth_fields_nonnull_rows_all_four_assets"]) != 0
        or probe["public_depth_fields_excluded_from_v2_normalized_output"] is not True
        or config["limitations"][0]
        != "Public delayed ISS does not expose option BBO depth or queue position."
    ):
        raise ValueError("forward option V2 protocol drifted")
    return config


def _compat_config() -> dict[str, Any]:
    config = load_config()
    parent_path = PROJECT_ROOT / config["parent_v1"]["config_path"]
    base = yaml.safe_load(parent_path.read_text(encoding="utf-8-sig"))
    if not isinstance(base, dict):
        raise ValueError("forward option V1 parent config must be an object")
    base = copy.deepcopy(base)
    base["protocol_id"] = config["protocol_id"]
    base["protocol_version"] = config["protocol_version"]
    base["status"] = config["status"]
    base["source"] = copy.deepcopy(config["source"])
    base["required_security_columns"] = [
        *base["required_security_columns"],
        *config["required_added_security_columns"],
    ]
    base["required_marketdata_columns"] = [
        *base["required_marketdata_columns"],
        *config["required_added_marketdata_columns"],
    ]
    base["forbidden_columns"] = config["forbidden_columns"]
    base["temporal_semantics"] = {
        **base["temporal_semantics"],
        "forward_only": True,
    }
    return base


def normalize_response(
    raw: bytes,
    requested_asset: str,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> pd.DataFrame:
    original_columns = parent.OUTPUT_COLUMNS
    parent.OUTPUT_COLUMNS = BASE_OUTPUT_COLUMNS
    try:
        base = PARENT_NORMALIZE(raw, requested_asset, retrieved_at, config)
    finally:
        parent.OUTPUT_COLUMNS = original_columns
    payload = json.loads(raw.decode("utf-8-sig"))
    security = parent._block(payload, "securities", config["required_security_columns"])
    market = parent._block(payload, "marketdata", config["required_marketdata_columns"])
    added = security[
        ["SECID", "BOARDID", "PREVOPENPOSITION", "IMNP", "IMP", "IMBUY", "IMTIME"]
    ].merge(
        market[["SECID", "BOARDID", "QUANTITY", "UPDATETIME", "TIME", "SEQNUM", "OICHANGE"]],
        on=["SECID", "BOARDID"],
        how="inner",
        validate="one_to_one",
    )
    added = added.rename(
        columns={
            "SECID": "secid",
            "BOARDID": "boardid",
            "PREVOPENPOSITION": "previous_open_interest",
            "IMNP": "initial_margin_non_covered",
            "IMP": "initial_margin_sell",
            "IMBUY": "initial_margin_buy",
            "IMTIME": "initial_margin_exchange_time",
            "QUANTITY": "last_trade_quantity",
            "UPDATETIME": "market_update_time",
            "TIME": "last_trade_time",
            "SEQNUM": "exchange_sequence_number",
            "OICHANGE": "open_interest_change",
        }
    )
    numeric = [
        "previous_open_interest",
        "initial_margin_non_covered",
        "initial_margin_sell",
        "initial_margin_buy",
        "last_trade_quantity",
        "exchange_sequence_number",
        "open_interest_change",
    ]
    for column in numeric:
        added[column] = pd.to_numeric(added[column], errors="coerce")
    for column in (
        "initial_margin_exchange_time",
        "market_update_time",
        "last_trade_time",
    ):
        added[column] = added[column].astype("string")
        if added[column].isna().any() or added[column].str.strip().eq("").any():
            raise ValueError(f"forward option V2 missing required exchange clock: {column}")
    if added["exchange_sequence_number"].isna().any():
        raise ValueError("forward option V2 missing exchange sequence number")
    output = base.merge(
        added,
        on=["secid", "boardid"],
        how="inner",
        validate="one_to_one",
    ).loc[:, OUTPUT_COLUMNS]
    if len(output) != len(base):
        raise ValueError("forward option V2 added-field identity mismatch")
    forbidden = {str(value).lower() for value in load_config()["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in output.columns}:
        raise ValueError("forward option V2 contains a forbidden economic column")
    return output.sort_values(
        ["asset_code", "last_trade_date", "strike", "option_type", "secid"],
        kind="stable",
        ignore_index=True,
    )


@contextmanager
def _parent_v2_semantics() -> Iterator[None]:
    original_sha = parent.CONFIG_SHA256
    original_module = parent.MODULE_PATH
    original_columns = parent.OUTPUT_COLUMNS
    original_loader = parent.load_config
    original_normalizer = parent.normalize_response
    parent.CONFIG_SHA256 = CONFIG_SHA256
    parent.MODULE_PATH = MODULE_PATH
    parent.OUTPUT_COLUMNS = OUTPUT_COLUMNS
    parent.load_config = _compat_config
    parent.normalize_response = normalize_response
    try:
        yield
    finally:
        parent.CONFIG_SHA256 = original_sha
        parent.MODULE_PATH = original_module
        parent.OUTPUT_COLUMNS = original_columns
        parent.load_config = original_loader
        parent.normalize_response = original_normalizer


def _retrieval(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    result = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    return result.tz_convert("UTC")


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: parent.SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = _retrieval(retrieved_at)
    boundary = pd.Timestamp(config["temporal_semantics"]["earliest_eligible_retrieved_at_utc"])
    if retrieval < boundary:
        raise ValueError("forward option V2 retrieval precedes sealed boundary")
    with _parent_v2_semantics():
        snapshot = PARENT_COLLECT(
            output_root,
            session=session,
            retrieved_at=retrieval,
        )
    checks = audit(snapshot)
    parent._write_json(
        snapshot / "audit.json", {"checks": checks, "all_true": all(checks.values())}
    )
    if not all(checks.values()):
        raise ValueError("forward option V2 snapshot audit failed")
    return snapshot


def audit(snapshot: Path) -> dict[str, bool]:
    with _parent_v2_semantics():
        checks = PARENT_AUDIT(snapshot)
    stored = pd.read_parquet(snapshot / "option_surface.parquet")
    checks.update(
        {
            "v2_columns_exact": tuple(stored.columns) == OUTPUT_COLUMNS,
            "exchange_clocks_complete": bool(
                stored[
                    [
                        "initial_margin_exchange_time",
                        "market_update_time",
                        "last_trade_time",
                    ]
                ]
                .notna()
                .all(axis=None)
            ),
            "exchange_sequence_complete": bool(stored["exchange_sequence_number"].notna().all()),
            "v2_boundary_respected": bool(
                pd.Timestamp(stored["retrieved_at_utc"].iloc[0])
                >= pd.Timestamp(
                    load_config()["temporal_semantics"]["earliest_eligible_retrieved_at_utc"]
                )
            ),
            "live_trading_disabled": load_config()["live_trading_allowed"] is False,
        }
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        if not all(checks.values()):
            raise SystemExit(1)
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
