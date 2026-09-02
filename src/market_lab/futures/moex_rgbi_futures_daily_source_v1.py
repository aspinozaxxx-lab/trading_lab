"""Build the sealed source-only quarterly RGBI futures daily history."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_rvi_futures_daily_source_v1 as base

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_rgbi_futures_daily_source_v1.yaml"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
CONFIG_SHA256: Final[str] = "fe49459e3ece14c954d60e397b71a834b712a254792d62b17476eb473c36430a"
ASSET_CODE: Final[str] = "RGBI"
SECID_PATTERN: Final[str] = r"^RB[HMUZ][2-5]$"
EXPECTED_SECIDS: Final[tuple[str, ...]] = (
    "RBM2", "RBU2", "RBZ2", "RBH3", "RBM3", "RBU3", "RBZ3", "RBH4",
    "RBM4", "RBU4", "RBZ4", "RBH5", "RBM5", "RBU5", "RBZ5",
)


def _sha(path: Path) -> str:
    return base.storage.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("RGBI source config must be an object")
    probe = payload["availability_probe_only"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_rgbi_futures_daily_source_v1"
        or payload.get("status")
        != "sealed_after_identity_date_and_schema_probe_before_market_values_or_outcomes"
        or payload.get("live_trading_allowed") is not False
        or probe["asset_code"] != ASSET_CODE
        or probe["secid_regex"] != SECID_PATTERN
        or tuple(probe["exact_secids"]) != EXPECTED_SECIDS
        or int(probe["exact_quarterly_series_2022_2025"]) != 15
        or payload["collection"]["protected_from"] != "2026-01-01"
    ):
        raise ValueError("RGBI source protocol drifted")
    return payload


def select_series(payload: dict[str, Any], config: dict[str, Any]) -> pd.DataFrame:
    frame = iss._parse_iss_block(
        payload,
        "series",
        frozenset({"secid", "name", "start_date", "expiration_date", "asset_code"}),
    )
    frame = frame.loc[
        frame["asset_code"].astype(str).eq(ASSET_CODE)
        & frame["secid"].astype(str).map(
            lambda value: re.fullmatch(SECID_PATTERN, value) is not None
        )
    ].copy()
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="raise")
    frame["expiration_date"] = pd.to_datetime(frame["expiration_date"], errors="raise")
    frame = frame.loc[
        frame["expiration_date"].ge("2022-01-01")
        & frame["expiration_date"].le(config["collection"]["end"])
    ].copy()
    output = pd.DataFrame(
        {
            "secid": frame["secid"].astype("string"),
            "short_name": frame["name"].astype("string"),
            "start_date": frame["start_date"],
            "expiration_date": frame["expiration_date"],
            "asset_code": frame["asset_code"].astype("string"),
        }
    ).sort_values("expiration_date", ignore_index=True)
    if tuple(output["secid"].astype(str)) != EXPECTED_SECIDS:
        raise ValueError("RGBI exact series identity or order drifted")
    if output["secid"].duplicated().any() or output["expiration_date"].duplicated().any():
        raise ValueError("duplicate RGBI series identity")
    if output["expiration_date"].min() != pd.Timestamp("2022-06-01"):
        raise ValueError("first RGBI expiration drifted")
    if output["expiration_date"].max() != pd.Timestamp("2025-12-01"):
        raise ValueError("last RGBI expiration drifted")
    return output.loc[:, base.SERIES_COLUMNS]


def audit(root: Path) -> dict[str, bool]:
    config = load_config()
    bundle = root.resolve()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_path = bundle / manifest["artifacts"]["raw"]["file"]
    series_path = bundle / manifest["artifacts"]["series"]["file"]
    daily_path = bundle / manifest["artifacts"]["daily"]["file"]
    raw = base.storage._read_raw(raw_path)
    rebuilt_series, rebuilt_daily = base.rebuild(raw, config)
    stored_series = pd.read_parquet(series_path)
    stored_daily = pd.read_parquet(daily_path)
    try:
        pd.testing.assert_frame_equal(stored_series, rebuilt_series, check_dtype=False)
        series_replay = True
    except AssertionError:
        series_replay = False
    try:
        pd.testing.assert_frame_equal(stored_daily, rebuilt_daily, check_dtype=False)
        daily_replay = True
    except AssertionError:
        daily_replay = False
    return {
        "manifest_sha_exact": (bundle / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(MODULE_PATH),
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_curve_return_label_signal_trade_or_pnl"]
        is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "artifact_hashes_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"]
        and _sha(series_path) == manifest["artifacts"]["series"]["sha256"]
        and _sha(daily_path) == manifest["artifacts"]["daily"]["sha256"],
        "artifact_rows_exact": len(stored_series)
        == manifest["artifacts"]["series"]["rows"]
        == 15
        and len(stored_daily) == manifest["artifacts"]["daily"]["rows"],
        "series_replay_exact": series_replay,
        "daily_replay_exact": daily_replay,
        "dates_before_2026": bool(
            pd.to_datetime(stored_daily["trade_date"]).lt("2026-01-01").all()
        ),
        "identity_unique": not stored_daily.duplicated(["secid", "trade_date"]).any(),
        "asset_exact": set(stored_daily["asset_code"].astype(str)) == {ASSET_CODE},
        "missing_not_zero_imputed": bool(stored_daily.isna().any().any()),
    }


def _activate() -> None:
    base.CONFIG_PATH = CONFIG_PATH
    base.CONFIG_SHA256 = CONFIG_SHA256
    base.ASSET_CODE = ASSET_CODE
    base.SECID_PATTERN = SECID_PATTERN
    base.__file__ = str(MODULE_PATH)
    base.load_config = load_config
    base.select_series = select_series
    base.audit = audit


def main() -> None:
    _activate()
    base.main()


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "CONFIG_SHA256",
    "EXPECTED_SECIDS",
    "audit",
    "load_config",
    "main",
    "select_series",
]
