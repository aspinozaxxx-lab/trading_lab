"""Build the sealed source-only same-expiry RUONIA/RUSFAR futures history."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_calendar_spread_source as network
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_ruonia_rusfar_futures_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "0e7db967b67f7285c741670b7f1a611adf41e296ac7fcc5ac849ad07fb7f8a1e"
)
LEGS: Final[dict[str, tuple[str, str]]] = {
    "ruonia": ("RUON", r"^RR[FGHJKMNQUVXZ][0-9]$"),
    "rusfar": ("1MFR", r"^MF[FGHJKMNQUVXZ][0-9]$"),
}
HISTORY_COLUMNS: Final[tuple[str, ...]] = (
    "BOARDID",
    "TRADEDATE",
    "SECID",
    "OPEN",
    "LOW",
    "HIGH",
    "CLOSE",
    "VALUE",
    "VOLUME",
    "OPENPOSITION",
    "SETTLEPRICE",
    "WAPRICE",
    "NUMTRADES",
    "SHORTNAME",
    "ASSETCODE",
)
PAIR_COLUMNS: Final[tuple[str, ...]] = (
    "expiration_date",
    "ruonia_secid",
    "rusfar_secid",
    "ruonia_start_date",
    "rusfar_start_date",
    "ruonia_name",
    "rusfar_name",
)
DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "leg",
    "asset_code",
    "secid",
    "short_name",
    "series_start_date",
    "expiration_date",
    "board_id",
    "trade_date",
    "open",
    "low",
    "high",
    "close",
    "value",
    "volume",
    "open_position",
    "settle_price",
    "waprice",
    "num_trades",
)


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("RUONIA/RUSFAR source config must be an object")
    metadata = payload["metadata_probe_only"]["asset_codes"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "moex_ruonia_rusfar_futures_source_v1"
        or payload.get("live_trading_allowed") is not False
        or int(payload["metadata_probe_only"]["exact_same_expiration_pairs_before_2026"])
        != 79
        or metadata["ruonia"]["asset_code"] != LEGS["ruonia"][0]
        or metadata["rusfar"]["asset_code"] != LEGS["rusfar"][0]
        or payload["collection"]["protected_from"] != "2026-01-01"
    ):
        raise ValueError("RUONIA/RUSFAR source protocol drifted")
    return payload


def _safe_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe RUONIA/RUSFAR output root: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "processed"):
        raise ValueError("RUONIA/RUSFAR output must be under data/processed")
    return PROJECT_ROOT / relative


def _series_url(config: dict[str, Any], asset_code: str) -> str:
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "series",
            "asset_code": asset_code,
            "show_expired": 1,
        }
    )
    return f"{config['official_sources']['series_endpoint']}?{query}"


def _history_url(
    config: dict[str, Any], secid: str, start: int, request_from: str
) -> str:
    base = str(config["official_sources"]["history_template"]).format(secid=secid)
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "history,history.cursor",
            "history.columns": ",".join(HISTORY_COLUMNS),
            "from": request_from,
            "till": config["collection"]["end"],
            "start": start,
        }
    )
    return f"{base}?{query}"


def select_pairs(
    series_payloads: dict[str, dict[str, Any]], config: dict[str, Any]
) -> pd.DataFrame:
    selected: dict[str, pd.DataFrame] = {}
    start = pd.Timestamp(config["collection"]["start"])
    end = pd.Timestamp(config["collection"]["end"])
    for leg, (asset_code, pattern) in LEGS.items():
        frame = iss._parse_iss_block(
            series_payloads[leg],
            "series",
            frozenset(
                {"secid", "name", "start_date", "expiration_date", "asset_code"}
            ),
        )
        frame = frame.loc[
            frame["asset_code"].astype(str).eq(asset_code)
            & frame["secid"].astype(str).map(
                lambda value, exact_pattern=pattern: re.fullmatch(
                    exact_pattern, value
                )
                is not None
            )
        ].copy()
        frame["start_date"] = pd.to_datetime(frame["start_date"], errors="raise")
        frame["expiration_date"] = pd.to_datetime(
            frame["expiration_date"], errors="raise"
        )
        frame = frame.loc[
            frame["expiration_date"].ge(start)
            & frame["expiration_date"].le(end)
        ].copy()
        if frame.duplicated("expiration_date").any():
            raise ValueError(f"duplicate {leg} expiration in series metadata")
        selected[leg] = frame.set_index("expiration_date")
    common = selected["ruonia"].index.intersection(selected["rusfar"].index).sort_values()
    rows = []
    for expiration in common:
        ruonia = selected["ruonia"].loc[expiration]
        rusfar = selected["rusfar"].loc[expiration]
        rows.append(
            {
                "expiration_date": expiration,
                "ruonia_secid": str(ruonia["secid"]),
                "rusfar_secid": str(rusfar["secid"]),
                "ruonia_start_date": pd.Timestamp(ruonia["start_date"]),
                "rusfar_start_date": pd.Timestamp(rusfar["start_date"]),
                "ruonia_name": str(ruonia["name"]),
                "rusfar_name": str(rusfar["name"]),
            }
        )
    pairs = pd.DataFrame(rows, columns=PAIR_COLUMNS)
    if len(pairs) != 79:
        raise ValueError(f"expected 79 RUONIA/RUSFAR pairs, got {len(pairs)}")
    if pairs["expiration_date"].min() != pd.Timestamp("2019-06-28"):
        raise ValueError("first RUONIA/RUSFAR expiration drifted")
    if pairs["expiration_date"].max() != pd.Timestamp("2025-12-30"):
        raise ValueError("last RUONIA/RUSFAR expiration drifted")
    return pairs


def _cursor(payload: dict[str, Any]) -> tuple[int, int, int]:
    cursor = iss._parse_iss_block(
        payload, "history.cursor", frozenset({"index", "total", "pagesize"})
    )
    if len(cursor) != 1:
        raise ValueError("history cursor must contain exactly one row")
    values = tuple(int(cursor.iloc[0][name]) for name in ("index", "total", "pagesize"))
    if values[0] < 0 or values[1] < 0 or values[2] <= 0:
        raise ValueError("invalid history cursor values")
    return values


def _history_frame(
    payload: dict[str, Any],
    *,
    leg: str,
    expected_asset: str,
    secid: str,
    series_start: pd.Timestamp,
    expiration: pd.Timestamp,
) -> pd.DataFrame:
    frame = iss._parse_iss_block(
        payload,
        "history",
        frozenset(column.lower() for column in HISTORY_COLUMNS),
    )
    if frame.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    if set(frame["secid"].astype(str)) != {secid}:
        raise ValueError(f"history SECID drifted for {secid}")
    if set(frame["assetcode"].astype(str)) != {expected_asset}:
        raise ValueError(f"history ASSETCODE drifted for {secid}")
    if set(frame["boardid"].astype(str)) != {"RFUD"}:
        raise ValueError(f"history BOARDID drifted for {secid}")
    output = pd.DataFrame(
        {
            "leg": leg,
            "asset_code": expected_asset,
            "secid": secid,
            "short_name": frame["shortname"].astype("string"),
            "series_start_date": series_start,
            "expiration_date": expiration,
            "board_id": frame["boardid"].astype("string"),
            "trade_date": pd.to_datetime(frame["tradedate"], errors="raise"),
        }
    )
    mapping = {
        "open": "open",
        "low": "low",
        "high": "high",
        "close": "close",
        "value": "value",
        "volume": "volume",
        "openposition": "open_position",
        "settleprice": "settle_price",
        "waprice": "waprice",
        "numtrades": "num_trades",
    }
    for source_column, output_column in mapping.items():
        output[output_column] = pd.to_numeric(frame[source_column], errors="coerce")
    return output.loc[:, DAILY_COLUMNS]


def rebuild(
    raw: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    series_items = {
        item["leg"]: item["payload"] for item in raw if item["kind"] == "series"
    }
    if set(series_items) != set(LEGS):
        raise ValueError("raw series identities drifted")
    pairs = select_pairs(series_items, config)
    pair_lookup: dict[tuple[str, str], tuple[pd.Timestamp, pd.Timestamp]] = {}
    for row in pairs.itertuples(index=False):
        pair_lookup[("ruonia", row.ruonia_secid)] = (
            row.ruonia_start_date,
            row.expiration_date,
        )
        pair_lookup[("rusfar", row.rusfar_secid)] = (
            row.rusfar_start_date,
            row.expiration_date,
        )
    frames = []
    for item in raw:
        if item["kind"] != "history":
            continue
        key = (str(item["leg"]), str(item["secid"]))
        if key not in pair_lookup:
            raise ValueError(f"unexpected raw history identity: {key}")
        series_start, expiration = pair_lookup[key]
        frames.append(
            _history_frame(
                item["payload"],
                leg=key[0],
                expected_asset=LEGS[key[0]][0],
                secid=key[1],
                series_start=series_start,
                expiration=expiration,
            )
        )
    daily = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=DAILY_COLUMNS)
    )
    daily = daily.sort_values(["trade_date", "expiration_date", "leg"], ignore_index=True)
    if daily.duplicated(["leg", "secid", "trade_date"]).any():
        raise ValueError("duplicate RUONIA/RUSFAR contract-date row")
    if not daily.empty and pd.to_datetime(daily["trade_date"]).ge("2026-01-01").any():
        raise ValueError("protected 2026 history leaked into source")
    forbidden = {str(value).casefold() for value in config["forbidden_derived_columns"]}
    if any(str(column).casefold() in forbidden for column in daily.columns):
        raise ValueError("forbidden derived column leaked into source")
    return pairs, daily


def collect(output_root: Path | None = None, *, client=None) -> Path:
    config = load_config()
    root = (output_root or _safe_root(config["output"]["root"])).resolve()
    if root.exists():
        raise FileExistsError(f"RUONIA/RUSFAR source already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    active = client or network.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        series_payloads = {}
        for leg, (asset_code, _) in LEGS.items():
            url = _series_url(config, asset_code)
            payload = active.get_json(url)
            series_payloads[leg] = payload
            raw.append({"kind": "series", "leg": leg, "url": url, "payload": payload})
        pairs = select_pairs(series_payloads, config)
        for row in pairs.itertuples(index=False):
            for leg in LEGS:
                secid = str(getattr(row, f"{leg}_secid"))
                request_from = max(
                    pd.Timestamp(config["collection"]["start"]),
                    pd.Timestamp(getattr(row, f"{leg}_start_date")),
                ).date().isoformat()
                cursor_start = 0
                while True:
                    url = _history_url(config, secid, cursor_start, request_from)
                    payload = active.get_json(url)
                    raw.append(
                        {
                            "kind": "history",
                            "leg": leg,
                            "secid": secid,
                            "cursor_start": cursor_start,
                            "url": url,
                            "payload": payload,
                        }
                    )
                    index, total, page_size = _cursor(payload)
                    rows = len(payload["history"]["data"])
                    if index != cursor_start:
                        raise ValueError(f"history cursor index drifted for {secid}")
                    if cursor_start + rows >= total:
                        break
                    if rows <= 0:
                        raise ValueError(f"history pagination stalled for {secid}")
                    cursor_start += page_size
        pairs, daily = rebuild(raw, config)
        pairs_path = temporary / "series_pairs.parquet"
        daily_path = temporary / "daily_history.parquet"
        raw_path = temporary / "raw_responses.jsonl.gz"
        storage._write_parquet(pairs_path, pairs)
        storage._write_parquet(daily_path, daily)
        atomic_write_bytes(raw_path, storage._raw_bytes(raw))
        counts = {
            "same_expiration_pairs": len(pairs),
            "daily_rows": len(daily),
            "raw_responses": len(raw),
            "rows_by_leg": {
                leg: int(daily["leg"].eq(leg).sum()) for leg in LEGS
            },
            "positive_trade_activity_rows_by_leg": {
                leg: int(
                    (
                        daily["leg"].eq(leg)
                        & daily["num_trades"].gt(0)
                        & daily["volume"].gt(0)
                    ).sum()
                )
                for leg in LEGS
            },
        }
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(Path(__file__)),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_only": True,
            "contains_spread_return_signal_trade_or_pnl": False,
            "live_trading_allowed": False,
            "counts": counts,
            "artifacts": {
                "pairs": storage._artifact(pairs_path, len(pairs)),
                "daily": storage._artifact(daily_path, len(daily)),
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
        temporary.replace(root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()
    checks = audit(root)
    write_json(root / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("RUONIA/RUSFAR source audit failed")
    return root


def audit(root: Path) -> dict[str, bool]:
    config = load_config()
    bundle = root.resolve()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_path = bundle / manifest["artifacts"]["raw"]["file"]
    pairs_path = bundle / manifest["artifacts"]["pairs"]["file"]
    daily_path = bundle / manifest["artifacts"]["daily"]["file"]
    raw = storage._read_raw(raw_path)
    rebuilt_pairs, rebuilt_daily = rebuild(raw, config)
    stored_pairs = pd.read_parquet(pairs_path)
    stored_daily = pd.read_parquet(daily_path)
    try:
        pd.testing.assert_frame_equal(stored_pairs, rebuilt_pairs, check_dtype=False)
        pairs_replay = True
    except AssertionError:
        pairs_replay = False
    try:
        pd.testing.assert_frame_equal(stored_daily, rebuilt_daily, check_dtype=False)
        daily_replay = True
    except AssertionError:
        daily_replay = False
    return {
        "manifest_sha_exact": (bundle / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_spread_return_signal_trade_or_pnl"]
        is False,
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "artifact_hashes_exact": _sha(raw_path)
        == manifest["artifacts"]["raw"]["sha256"]
        and _sha(pairs_path) == manifest["artifacts"]["pairs"]["sha256"]
        and _sha(daily_path) == manifest["artifacts"]["daily"]["sha256"],
        "artifact_rows_exact": len(stored_pairs)
        == manifest["artifacts"]["pairs"]["rows"]
        == 79
        and len(stored_daily) == manifest["artifacts"]["daily"]["rows"],
        "pairs_replay_exact": pairs_replay,
        "daily_replay_exact": daily_replay,
        "dates_before_2026": bool(
            pd.to_datetime(stored_daily["trade_date"]).lt("2026-01-01").all()
        ),
        "identity_unique": not stored_daily.duplicated(
            ["leg", "secid", "trade_date"]
        ).any(),
        "both_legs_present": set(stored_daily["leg"].astype(str)) == set(LEGS),
        "missing_not_zero_imputed": bool(stored_daily.isna().any().any()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit-only", type=Path)
    args = parser.parse_args()
    if args.audit_only:
        checks = audit(args.audit_only)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
