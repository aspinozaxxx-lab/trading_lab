"""Parse MOEX Type B option quote clears after the sealed V2 fail-closed stop."""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import moex_type_b_derivatives_sample_source_v2 as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_type_b_derivatives_sample_source_v3.yaml"
)
CONFIG_SHA256: Final[str] = (
    "c2c659f39ff6cfea9d8bdffca28ac15e968c14c3204f6173516f7dd949f4662a"
)
DEFAULT_ARCHIVE: Final[Path] = parent.DEFAULT_ARCHIVE
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/options/moex-type-b-derivatives-sample-2024-10-01-v3"
)


def load_config() -> dict[str, Any]:
    actual = parent._sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("Type B V3 config must be an object")
    parent_v2 = config["parent_v2"]
    source = config["source"]
    tick = config["tick_semantics"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_type_b_derivatives_sample_source_v3"
        or config.get("status")
        != "sealed_after_null_clear_discovery_before_full_value_parse"
        or config.get("live_trading_allowed") is not False
        or parent._sha_file(PROJECT_ROOT / parent_v2["config_path"])
        != parent_v2["config_sha256"]
        or parent_v2["output_created"] is not False
        or int(parent_v2["rows_read_before_failure_including_header"]) != 2531
        or source["archive_sha256"]
        != "afccc1602d81c15dd064eadd44dd91a3aff53bcb3213fe96840f0b8188601e30"
        or int(source["expected_content_length_bytes"]) != 101_968_982
        or tick["one_of_PRICE_VOLUME_null"] != "forbidden"
        or tick["trade_with_null_PRICE_or_VOLUME"] != "forbidden"
        or config["limitations"][0]
        != "This is one free sample trade date, not a performance sample."
    ):
        raise ValueError("Type B V3 source protocol drifted")
    return config


def _compat_config() -> dict[str, Any]:
    config = copy.deepcopy(load_config())
    config["discovered_archive_identity"] = config["archive_identity"]
    config["discovered_headers"] = config["headers"]
    config["temporal_correction"] = config["temporal_semantics"]
    return config


def normalize_tick_chunk(
    frame: pd.DataFrame, start_row: int, config: dict[str, Any]
) -> pd.DataFrame:
    if list(frame.columns) != parent.TICK_HEADER:
        raise ValueError("Type B V3 option tick header drift")
    if not frame["SYSTEM"].isin(["C", "P"]).all():
        raise ValueError("Type B V3 option tick admitted non-option system")
    if not frame["TYPE"].isin(["B", "S"]).all():
        raise ValueError("Type B V3 option tick side drift")
    trade_id = parent._trade_id(frame["DEAL_ID"], required=False)
    raw_price = frame["PRICE"].astype("string").str.strip()
    raw_volume = frame["VOLUME"].astype("string").str.strip()
    price_null = raw_price.eq("null")
    volume_null = raw_volume.eq("null")
    if not price_null.equals(volume_null):
        raise ValueError("Type B V3 PRICE/VOLUME null pair drift")
    if (trade_id.notna() & price_null).any():
        raise ValueError("Type B V3 trade cannot clear a quote")
    price = pd.to_numeric(raw_price.mask(price_null), errors="raise").astype("Float64")
    volume_numeric = pd.to_numeric(raw_volume.mask(volume_null), errors="raise").astype(
        "Float64"
    )
    present = ~price_null
    if (
        price.loc[present].le(0.0).any()
        or volume_numeric.loc[present].le(0.0).any()
        or not np.isfinite(price.loc[present].astype(float)).all()
        or not np.isfinite(volume_numeric.loc[present].astype(float)).all()
        or not np.equal(
            volume_numeric.loc[present].astype(float),
            np.floor(volume_numeric.loc[present].astype(float)),
        ).all()
    ):
        raise ValueError("Type B V3 non-clear price/volume must be finite and positive")
    volume = volume_numeric.astype("Int64")
    event_kind = np.select(
        [price_null.to_numpy(), trade_id.notna().to_numpy()],
        ["best_quote_clear", "trade"],
        default="best_quote_update",
    )
    return pd.DataFrame(
        {
            "source_date": pd.Timestamp(config["source"]["source_trade_date"]),
            "event_at_moscow": parent._parse_moment(frame["MOMENT"], config),
            "original_row_number": np.arange(
                start_row, start_row + len(frame), dtype=np.int64
            ),
            "secid": frame["#SYMBOL"].astype("string"),
            "option_system": frame["SYSTEM"].astype("string"),
            "side": frame["TYPE"].astype("string"),
            "event_kind": pd.Series(event_kind, index=frame.index, dtype="string"),
            "trade_id": trade_id,
            "price": price,
            "volume": volume,
        }
    )


@contextmanager
def _parent_v3_semantics() -> Iterator[None]:
    original_sha = parent.CONFIG_SHA256
    original_loader = parent.load_config
    original_normalizer = parent.normalize_tick_chunk
    parent.CONFIG_SHA256 = CONFIG_SHA256
    parent.load_config = _compat_config
    parent.normalize_tick_chunk = normalize_tick_chunk
    try:
        yield
    finally:
        parent.CONFIG_SHA256 = original_sha
        parent.load_config = original_loader
        parent.normalize_tick_chunk = original_normalizer


def collect(archive: Path = DEFAULT_ARCHIVE, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    with _parent_v3_semantics():
        return parent.collect(archive, output_root)


def audit(directory: Path) -> dict[str, Any]:
    with _parent_v3_semantics():
        return parent.audit(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        report = audit(args.audit_directory)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["all_true"] is not True:
            raise SystemExit(1)
        return
    print(collect(args.archive, args.output_root))


if __name__ == "__main__":
    main()
