"""Collect immutable official MOEX OFZ history and bond cash-flow schedules."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_ofz_total_return_source_v1.yaml"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/ofz/moex-ofz-history-bondization-2021-2025-v1"
)
USER_AGENT: Final[str] = "market-lab-ofz-source/1.0 (MOEX research)"
SCHEDULE_KINDS: Final[tuple[str, ...]] = ("coupons", "amortizations", "offers")
HISTORY_OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "board_id",
    "trade_date",
    "short_name",
    "security_id",
    "number_of_trades",
    "value_rub",
    "volume",
    "open_clean_pct",
    "close_clean_pct",
    "wap_clean_pct",
    "legal_close_clean_pct",
    "accrued_interest_rub",
    "yield_close_pct",
    "yield_at_wap_pct",
    "maturity_date",
    "duration_days",
    "coupon_percent",
    "coupon_value_rub",
    "face_value",
    "currency_id",
    "face_unit",
    "bond_type",
    "bond_subtype",
    "available_at_utc",
    "retrieved_at_utc",
    "access_mode",
)
SCHEDULE_OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "event_kind",
    "security_id",
    "isin",
    "name",
    "primary_board_id",
    "event_date",
    "record_date",
    "start_date",
    "initial_face_value",
    "face_value",
    "face_unit",
    "value_percent",
    "value",
    "value_rub",
    "offer_price",
    "offer_type",
    "data_source",
    "current_vintage",
    "available_at_utc",
    "retrieved_at_utc",
    "access_mode",
)


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("OFZ source config must be an object")
    implementation = config["implementation"]
    if (
        actual != declared
        or config.get("protocol_id") != "moex_ofz_total_return_source_v1"
        or config.get("status") != "sealed_after_schema_probe_before_any_history_row"
        or config.get("live_trading_allowed") is not False
        or _sha_file(PROJECT_ROOT / implementation["path"]) != implementation["sha256"]
        or config["scope"]["computes_return_target_prediction_or_pnl"] is not False
        or config["temporal_semantics"]["protected_ceiling_exclusive"] != "2026-01-01"
    ):
        raise ValueError("OFZ source seal drifted")
    return config


def history_url(config: dict[str, Any], start: int) -> str:
    source = config["source"]["history"]
    query = {
        "iss.meta": "off",
        "iss.only": "history,history.cursor",
        "history.columns": ",".join(config["required_history_columns"]),
        "from": source["from"],
        "till": source["till"],
        "start": start,
    }
    return f"{source['endpoint']}?{urlencode(query)}"


def schedule_url(config: dict[str, Any], secid: str, kind: str, start: int) -> str:
    if kind not in SCHEDULE_KINDS or not secid.startswith("SU"):
        raise ValueError("undeclared OFZ schedule request")
    source = config["source"]["bondization"]
    endpoint = source["endpoint_template"].format(secid=secid)
    query = {
        "iss.meta": "off",
        "iss.only": f"{kind},{kind}.cursor",
        f"{kind}.start": start,
    }
    return f"{endpoint}?{urlencode(query)}"


def _block(payload: dict[str, Any], name: str) -> tuple[list[str], list[list[Any]]]:
    item = payload.get(name)
    if not isinstance(item, dict) or not isinstance(item.get("columns"), list):
        raise ValueError(f"missing MOEX {name} block")
    rows = item.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"invalid MOEX {name} rows")
    return [str(value) for value in item["columns"]], rows


def _cursor(
    payload: dict[str, Any], name: str, expected_start: int, rows: list[list[Any]]
) -> tuple[int, int]:
    item = payload.get(name)
    if item is None and expected_start == 0 and not rows:
        return 0, 20
    columns, values = _block(payload, name)
    if columns != ["INDEX", "TOTAL", "PAGESIZE"] or len(values) != 1:
        raise ValueError(f"invalid MOEX {name}")
    cursor = dict(zip(columns, values[0], strict=True))
    if int(cursor["INDEX"]) != expected_start:
        raise ValueError(f"MOEX {name} index drift")
    total, page_size = int(cursor["TOTAL"]), int(cursor["PAGESIZE"])
    if total < 0 or page_size < 1:
        raise ValueError(f"MOEX {name} values invalid")
    return total, page_size


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def normalize_history_page(
    raw: bytes,
    *,
    expected_start: int,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _block(payload, "history")
    total, page_size = _cursor(payload, "history.cursor", expected_start, rows)
    required = tuple(config["required_history_columns"])
    if set(required) - set(columns):
        raise ValueError("OFZ history schema drift")
    frame = pd.DataFrame(rows, columns=columns).loc[:, required].copy()
    if expected_start < total and frame.empty:
        raise ValueError("unexpected empty OFZ history page")
    frame = frame.loc[
        frame["SECID"].astype(str).str.startswith("SU")
        & frame["BOARDID"].astype(str).eq(config["source"]["history"]["board"])
    ].copy()
    dates = pd.to_datetime(frame["TRADEDATE"], errors="raise")
    available = (dates.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).dt.tz_convert("UTC")
    output = pd.DataFrame(
        {
            "board_id": frame["BOARDID"].astype("string"),
            "trade_date": dates,
            "short_name": frame["SHORTNAME"].astype("string"),
            "security_id": frame["SECID"].astype("string"),
            "number_of_trades": _numeric(frame, "NUMTRADES"),
            "value_rub": _numeric(frame, "VALUE"),
            "volume": _numeric(frame, "VOLUME"),
            "open_clean_pct": _numeric(frame, "OPEN"),
            "close_clean_pct": _numeric(frame, "CLOSE"),
            "wap_clean_pct": _numeric(frame, "WAPRICE"),
            "legal_close_clean_pct": _numeric(frame, "LEGALCLOSEPRICE"),
            "accrued_interest_rub": _numeric(frame, "ACCINT"),
            "yield_close_pct": _numeric(frame, "YIELDCLOSE"),
            "yield_at_wap_pct": _numeric(frame, "YIELDATWAP"),
            "maturity_date": pd.to_datetime(frame["MATDATE"], errors="coerce"),
            "duration_days": _numeric(frame, "DURATION"),
            "coupon_percent": _numeric(frame, "COUPONPERCENT"),
            "coupon_value_rub": _numeric(frame, "COUPONVALUE"),
            "face_value": _numeric(frame, "FACEVALUE"),
            "currency_id": frame["CURRENCYID"].astype("string"),
            "face_unit": frame["FACEUNIT"].astype("string"),
            "bond_type": frame["BONDTYPE"].astype("string"),
            "bond_subtype": frame["BONDSUBTYPE"].astype("string"),
            "available_at_utc": available,
            "retrieved_at_utc": retrieved_at.tz_convert("UTC").isoformat(),
            "access_mode": config["source"]["access_mode"],
        },
        columns=HISTORY_OUTPUT_COLUMNS,
    )
    if not output.empty and (
        not output["security_id"].astype(str).str.startswith("SU").all()
        or set(output["board_id"].astype(str)) != {config["source"]["history"]["board"]}
    ):
        raise ValueError("OFZ normalized history identity drift")
    return output, total, page_size


def normalize_schedule_page(
    raw: bytes,
    *,
    secid: str,
    kind: str,
    expected_start: int,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    columns, rows = _block(payload, kind)
    total, page_size = _cursor(payload, f"{kind}.cursor", expected_start, rows)
    required = set(config["required_schedule_columns"][kind])
    if required - set(columns):
        raise ValueError(f"OFZ {kind} schema drift")
    frame = pd.DataFrame(rows, columns=columns)
    if expected_start < total and frame.empty:
        raise ValueError(f"unexpected empty OFZ {kind} page")
    if not frame.empty and set(frame["secid"].astype(str)) != {secid}:
        raise ValueError(f"OFZ {kind} security identity drift")
    date_column = {
        "coupons": "coupondate",
        "amortizations": "amortdate",
        "offers": "offerdate",
    }[kind]
    event_date = pd.to_datetime(frame.get(date_column), errors="coerce")
    lower = pd.Timestamp(config["source"]["bondization"]["event_from"])
    upper = pd.Timestamp(config["source"]["bondization"]["event_till"])
    keep = event_date.between(lower, upper, inclusive="both")
    frame = frame.loc[keep].copy()
    event_date = event_date.loc[keep]

    def optional_numeric(column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(float("nan"), index=frame.index, dtype=float)
        return pd.to_numeric(frame[column], errors="coerce")

    def optional_string(column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(pd.NA, index=frame.index, dtype="string")
        return frame[column].astype("string")

    output = pd.DataFrame(
        {
            "event_kind": kind.removesuffix("s"),
            "security_id": optional_string("secid"),
            "isin": optional_string("isin"),
            "name": optional_string("name"),
            "primary_board_id": optional_string("primary_boardid"),
            "event_date": event_date,
            "record_date": pd.to_datetime(frame.get("recorddate"), errors="coerce"),
            "start_date": pd.to_datetime(frame.get("startdate"), errors="coerce"),
            "initial_face_value": optional_numeric("initialfacevalue"),
            "face_value": optional_numeric("facevalue"),
            "face_unit": optional_string("faceunit"),
            "value_percent": optional_numeric("valueprc"),
            "value": optional_numeric("value"),
            "value_rub": optional_numeric("value_rub"),
            "offer_price": optional_numeric("price"),
            "offer_type": optional_string("offertype"),
            "data_source": optional_string("data_source"),
            "current_vintage": True,
            "available_at_utc": retrieved_at.tz_convert("UTC").isoformat(),
            "retrieved_at_utc": retrieved_at.tz_convert("UTC").isoformat(),
            "access_mode": config["source"]["access_mode"],
        },
        columns=SCHEDULE_OUTPUT_COLUMNS,
    )
    return output, total, page_size


def _request(client: SessionLike, url: str) -> bytes:
    response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
    response.raise_for_status()
    return bytes(response.content)


def _fetch_history(
    client: SessionLike, config: dict[str, Any], retrieval: pd.Timestamp
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    start, total = 0, None
    frames: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    while total is None or start < total:
        url = history_url(config, start)
        raw = _request(client, url)
        frame, observed_total, page_size = normalize_history_page(
            raw,
            expected_start=start,
            retrieved_at=retrieval,
            config=config,
        )
        if total is not None and total != observed_total:
            raise ValueError("OFZ history total changed during pagination")
        total = observed_total
        frames.append(frame)
        pages.append({"start": start, "url": url, "raw": raw})
        start += page_size
    if not frames:
        raise ValueError("OFZ history returned no pages")
    return pd.concat(frames, ignore_index=True), pages


def _fetch_schedule(
    client: SessionLike,
    config: dict[str, Any],
    retrieval: pd.Timestamp,
    secid: str,
    kind: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    start, total = 0, None
    frames: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    while total is None or start < total:
        url = schedule_url(config, secid, kind, start)
        raw = _request(client, url)
        frame, observed_total, page_size = normalize_schedule_page(
            raw,
            secid=secid,
            kind=kind,
            expected_start=start,
            retrieved_at=retrieval,
            config=config,
        )
        if total is not None and total != observed_total:
            raise ValueError(f"OFZ {kind} total changed during pagination")
        total = observed_total
        frames.append(frame)
        pages.append({"start": start, "url": url, "raw": raw})
        if total == 0:
            break
        start += page_size
    return pd.concat(frames, ignore_index=True), pages


def _persist_raw(path: Path, item: dict[str, Any], **identity: Any) -> dict[str, Any]:
    raw = item["raw"]
    path.write_bytes(gzip.compress(raw, mtime=0))
    return {
        **identity,
        "start": int(item["start"]),
        "url": item["url"],
        "path": path.name,
        "response_bytes": len(raw),
        "response_sha256": _sha_bytes(raw),
        "stored_bytes": path.stat().st_size,
        "stored_sha256": _sha_file(path),
    }


def _validate_outcome_free(frame: pd.DataFrame, config: dict[str, Any]) -> None:
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in frame.columns}:
        raise ValueError("derived outcome escaped into OFZ source")


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    client: SessionLike = session or requests.Session()
    history, history_pages = _fetch_history(client, config, retrieval)
    if history.empty:
        raise ValueError("OFZ history has zero SU rows")
    protected = pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"])
    if (
        history["trade_date"].ge(protected).any()
        or history.duplicated(["security_id", "trade_date"]).any()
        or not history["trade_date"]
        .between(
            pd.Timestamp(config["source"]["history"]["from"]),
            pd.Timestamp(config["source"]["history"]["till"]),
        )
        .all()
    ):
        raise ValueError("OFZ history temporal or identity mismatch")
    schedule_frames: list[pd.DataFrame] = []
    schedule_pages: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for secid in sorted(history["security_id"].astype(str).unique()):
        schedule_pages[secid] = {}
        for kind in SCHEDULE_KINDS:
            frame, pages = _fetch_schedule(client, config, retrieval, secid, kind)
            schedule_frames.append(frame)
            schedule_pages[secid][kind] = pages
    nonempty_schedules = [frame for frame in schedule_frames if not frame.empty]
    schedule = (
        pd.concat(nonempty_schedules, ignore_index=True)
        if nonempty_schedules
        else pd.DataFrame(columns=SCHEDULE_OUTPUT_COLUMNS)
    )
    if schedule.duplicated(["event_kind", "security_id", "event_date"]).any():
        raise ValueError("OFZ schedule identity is not unique")
    _validate_outcome_free(history, config)
    _validate_outcome_free(schedule, config)
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable OFZ source exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        raw_manifest: dict[str, Any] = {"history": [], "bondization": {}}
        for item in history_pages:
            raw_manifest["history"].append(
                _persist_raw(temporary / f"raw_history_{item['start']:07d}.json.gz", item)
            )
        for secid, by_kind in schedule_pages.items():
            raw_manifest["bondization"][secid] = {}
            for kind, pages in by_kind.items():
                raw_manifest["bondization"][secid][kind] = []
                for item in pages:
                    raw_manifest["bondization"][secid][kind].append(
                        _persist_raw(
                            temporary / f"raw_{kind}_{secid}_{item['start']:05d}.json.gz",
                            item,
                            security_id=secid,
                            event_kind=kind,
                        )
                    )
        history = history.sort_values(["trade_date", "security_id"], ignore_index=True)
        schedule = schedule.sort_values(
            ["event_date", "security_id", "event_kind"], ignore_index=True
        )
        history_path = temporary / "ofz_history.parquet"
        schedule_path = temporary / "ofz_bondization.parquet"
        history.to_parquet(history_path, index=False)
        schedule.to_parquet(schedule_path, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": _sha_file(CONFIG_PATH),
            "implementation_sha256": _sha_file(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "contains_return_label_target_prediction_or_pnl": False,
            "bondization_current_vintage_not_historical_predictor": True,
            "counts": {
                "history_rows": len(history),
                "unique_trade_dates": history["trade_date"].nunique(),
                "securities": history["security_id"].nunique(),
                "coupon_events": int(schedule["event_kind"].eq("coupon").sum()),
                "amortization_events": int(schedule["event_kind"].eq("amortization").sum()),
                "offer_events": int(schedule["event_kind"].eq("offer").sum()),
                "positive_value_rows": int(history["value_rub"].gt(0).sum()),
                "positive_trade_rows": int(history["number_of_trades"].gt(0).sum()),
                "positive_close_rows": int(history["close_clean_pct"].gt(0).sum()),
            },
            "raw": raw_manifest,
            "processed": {
                "history": {
                    "path": history_path.name,
                    "bytes": history_path.stat().st_size,
                    "sha256": _sha_file(history_path),
                    "rows": len(history),
                },
                "bondization": {
                    "path": schedule_path.name,
                    "bytes": schedule_path.stat().st_size,
                    "sha256": _sha_file(schedule_path),
                    "rows": len(schedule),
                },
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(output_root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    result = audit(output_root)
    _write_json(output_root / "audit.json", result)
    if not result["all_true"]:
        raise ValueError("MOEX OFZ source audit failed")
    return output_root


def _load_raw(root: Path, item: dict[str, Any], checks: dict[str, bool], label: str) -> bytes:
    path = root / item["path"]
    payload = gzip.decompress(path.read_bytes())
    checks[f"{label}_stored_exact"] = (
        path.stat().st_size == int(item["stored_bytes"])
        and _sha_file(path) == item["stored_sha256"]
    )
    checks[f"{label}_response_exact"] = (
        len(payload) == int(item["response_bytes"])
        and _sha_bytes(payload) == item["response_sha256"]
    )
    return payload


def _frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    left = left.copy()
    right = right.copy()
    for column in right.columns:
        if (
            pd.api.types.is_object_dtype(left[column])
            or pd.api.types.is_string_dtype(left[column])
            or pd.api.types.is_object_dtype(right[column])
            or pd.api.types.is_string_dtype(right[column])
        ):
            left[column] = left[column].astype("string")
            right[column] = right[column].astype("string")
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
        return True
    except AssertionError:
        return False


def audit(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    checks: dict[str, bool] = {
        "config_exact": manifest["config_sha256"] == _sha_file(CONFIG_PATH),
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "outcome_free": manifest["contains_return_label_target_prediction_or_pnl"] is False,
        "bondization_current_vintage_disclosed": manifest[
            "bondization_current_vintage_not_historical_predictor"
        ]
        is True,
    }
    history_frames: list[pd.DataFrame] = []
    for item in manifest["raw"]["history"]:
        raw = _load_raw(output_root, item, checks, f"history_{item['start']}")
        frame, _, _ = normalize_history_page(
            raw,
            expected_start=int(item["start"]),
            retrieved_at=retrieval,
            config=config,
        )
        history_frames.append(frame)
    schedule_frames: list[pd.DataFrame] = []
    for secid, by_kind in manifest["raw"]["bondization"].items():
        for kind, pages in by_kind.items():
            for item in pages:
                raw = _load_raw(output_root, item, checks, f"{kind}_{secid}_{item['start']}")
                frame, _, _ = normalize_schedule_page(
                    raw,
                    secid=secid,
                    kind=kind,
                    expected_start=int(item["start"]),
                    retrieved_at=retrieval,
                    config=config,
                )
                schedule_frames.append(frame)
    nonempty_schedules = [frame for frame in schedule_frames if not frame.empty]
    rebuilt = {
        "history": pd.concat(history_frames, ignore_index=True).sort_values(
            ["trade_date", "security_id"], ignore_index=True
        ),
        "bondization": (
            pd.concat(nonempty_schedules, ignore_index=True)
            if nonempty_schedules
            else pd.DataFrame(columns=SCHEDULE_OUTPUT_COLUMNS)
        ).sort_values(["event_date", "security_id", "event_kind"], ignore_index=True),
    }
    for name, frame in rebuilt.items():
        item = manifest["processed"][name]
        path = output_root / item["path"]
        stored = pd.read_parquet(path)
        checks[f"{name}_processed_exact"] = (
            path.stat().st_size == int(item["bytes"]) and _sha_file(path) == item["sha256"]
        )
        checks[f"{name}_rows_exact"] = len(stored) == int(item["rows"])
        checks[f"{name}_raw_replay_exact"] = _frames_equal(stored, frame)
    checks["history_identity_unique"] = (
        not rebuilt["history"].duplicated(["security_id", "trade_date"]).any()
    )
    checks["schedule_identity_unique"] = (
        not rebuilt["bondization"].duplicated(["event_kind", "security_id", "event_date"]).any()
    )
    checks["protected_history_rows_zero"] = (
        not rebuilt["history"]["trade_date"]
        .ge(pd.Timestamp(config["temporal_semantics"]["protected_ceiling_exclusive"]))
        .any()
    )
    return {"checks": checks, "all_true": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.audit:
        print(json.dumps(audit(args.output_root), ensure_ascii=False, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "DEFAULT_OUTPUT_ROOT",
    "HISTORY_OUTPUT_COLUMNS",
    "SCHEDULE_OUTPUT_COLUMNS",
    "audit",
    "collect",
    "history_url",
    "load_config",
    "normalize_history_page",
    "normalize_schedule_page",
    "schedule_url",
]
