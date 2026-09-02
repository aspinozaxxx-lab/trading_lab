"""Capture the official MOEX futures calendar from public-page ``__NEXT_DATA__``."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v27_forward_calendar_html_transport_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "8380d1a0f090a93bcf91e9a97fb8f461cfe9887cd0ccb7ef20e1a8f280b029a9"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-futures-calendar-html-v1"
)
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
NEXT_DATA_PATTERN: Final[re.Pattern[bytes]] = re.compile(
    rb"<script\b(?=[^>]*\bid=[\"']__NEXT_DATA__[\"'])"
    rb"(?=[^>]*\btype=[\"']application/json[\"'])[^>]*>(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "calendar_year",
    "tradedate",
    "is_traded",
    "reason",
    "retrieved_at_utc",
    "available_at_utc",
    "source_transport",
)
FORBIDDEN_OUTPUT_TERMS: Final[tuple[str, ...]] = (
    "price",
    "return",
    "label",
    "signal",
    "target",
    "prediction",
    "equity",
    "pnl",
)


class ResponseLike(Protocol):
    content: bytes
    status_code: int
    headers: Mapping[str, str]


class SessionLike(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def _retrieval(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    timestamp = pd.Timestamp(value if value is not None else datetime.now(UTC))
    if timestamp.tzinfo is None:
        raise ValueError("calendar retrieval timestamp must include a timezone")
    return timestamp.tz_convert("UTC")


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".yaml.sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("MOEX futures calendar transport config must be an object")
    source = config["official_source"]
    request = config["request"]
    causality = config["causality"]
    consumer = config["consumer_contract"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id")
        != "futures_v27_forward_calendar_html_transport_v1"
        or config.get("live_trading_allowed") is not False
        or source["public_page_endpoint"]
        != "https://www.moex.com/ru/tradingcalendar"
        or source["query"] != {"market": "derivatives-market", "type": "trading"}
        or source["record_fields"] != ["tradedate", "is_traded", "reason"]
        or source["direct_ISS_or_calendar_value_fallback"] != "forbidden"
        or request["method"] != "GET"
        or request["cookies_or_authentication"] != "forbidden"
        or request["alternate_route_after_failure"] != "forbidden"
        or causality["calendar_available_at"]
        != "actual_response_retrieved_at_utc"
        or causality["null_is_traded_policy"] != "unavailable_never_infer"
        or causality["generic_weekday_substitution"] != "forbidden"
        or consumer["hard_fallback_or_promotion_when_calendar_incomplete"]
        != "blocked"
        or consumer["signal_direction_scale_cap_margin_cost_or_gate_changed"] is not False
        or int(config["parent_paper_protocol"]["hard_fallback_sessions_unchanged"])
        != 5
    ):
        raise ValueError("MOEX futures calendar transport protocol drifted")
    for key in ("path", "preflight_path", "roll_planner_path"):
        digest_key = key.replace("path", "sha256")
        if config["parent_paper_protocol"][digest_key] != _sha(
            PROJECT_ROOT / config["parent_paper_protocol"][key]
        ):
            raise ValueError(f"calendar parent dependency drifted: {key}")
    return config


def request_parts(config: Mapping[str, Any]) -> tuple[str, dict[str, str], dict[str, str]]:
    source = config["official_source"]
    request = config["request"]
    return (
        str(source["public_page_endpoint"]),
        {str(key): str(value) for key, value in source["query"].items()},
        {str(key): str(value) for key, value in request["headers"].items()},
    )


def _get(client: SessionLike, config: Mapping[str, Any]) -> ResponseLike:
    url, params, headers = request_parts(config)
    request = config["request"]
    attempts = int(request["attempts"])
    backoff = [float(value) for value in request["backoff_seconds"]]
    for attempt in range(attempts):
        try:
            response = client.get(
                url,
                params=params,
                headers=headers,
                timeout=float(request["timeout_seconds"]),
            )
            if int(response.status_code) >= 400:
                raise RuntimeError(
                    f"official MOEX trading-calendar page returned HTTP {response.status_code}"
                )
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "text/html" not in content_type:
                raise RuntimeError("official MOEX trading-calendar response is not HTML")
            return response
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise RuntimeError("official MOEX calendar transport failed") from None
            time.sleep(backoff[attempt])
    raise AssertionError("unreachable MOEX calendar retry state")


def _calendar_components(root: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            init_data = value.get("initData")
            if isinstance(init_data, dict):
                off_days = init_data.get("offDays")
                if isinstance(off_days, dict) and isinstance(off_days.get("futures"), dict):
                    found.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(root)
    return found


def parse_response(raw: bytes, retrieved_at: pd.Timestamp) -> pd.DataFrame:
    matches = NEXT_DATA_PATTERN.findall(raw)
    if len(matches) != 1:
        raise ValueError(f"expected one MOEX __NEXT_DATA__ payload, found {len(matches)}")
    try:
        payload = json.loads(matches[0])
        root = payload["props"]["pageProps"]["recursiveComponentContentProps"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid MOEX trading-calendar __NEXT_DATA__ schema") from error
    components = _calendar_components(root)
    if len(components) != 1:
        raise ValueError(f"expected one futures calendar component, found {len(components)}")
    years = components[0]["initData"]["offDays"]["futures"]
    retrieval = _retrieval(retrieved_at)
    start_date = retrieval.tz_convert(MOSCOW).normalize().tz_localize(None)
    required_years = (start_date.year, start_date.year + 1)
    if any(str(year) not in years for year in required_years):
        raise ValueError("MOEX page lacks current or following futures calendar year")
    allowed_states = {0, 1, None}
    allowed_reasons = {"H", "W", "N", "T", None}
    rows: list[dict[str, object]] = []
    for year in required_years:
        records = years[str(year)]
        if not isinstance(records, dict):
            raise ValueError(f"MOEX futures calendar year {year} is not an object")
        expected_dates = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        expected_keys = {value.strftime("%Y-%m-%d") for value in expected_dates}
        if set(records) != expected_keys:
            raise ValueError(f"MOEX futures calendar year {year} does not cover every date")
        for date_key, record in records.items():
            if not isinstance(record, dict) or set(record) != {
                "tradedate",
                "is_traded",
                "reason",
            }:
                raise ValueError("MOEX futures calendar record schema drifted")
            if record["tradedate"] != date_key:
                raise ValueError("MOEX futures calendar key/tradedate mismatch")
            state = record["is_traded"]
            reason = record["reason"]
            if isinstance(state, bool) or state not in allowed_states:
                raise ValueError("MOEX futures calendar is_traded escaped declared domain")
            if reason not in allowed_reasons:
                raise ValueError("MOEX futures calendar reason escaped declared domain")
            tradedate = pd.Timestamp(date_key)
            if tradedate < start_date:
                continue
            rows.append(
                {
                    "calendar_year": year,
                    "tradedate": tradedate,
                    "is_traded": state,
                    "reason": reason,
                    "retrieved_at_utc": retrieval,
                    "available_at_utc": retrieval,
                    "source_transport": "official_moex_public_page_next_data_v1",
                }
            )
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if frame.empty or frame["tradedate"].duplicated().any():
        raise ValueError("MOEX futures calendar normalized output is empty or duplicated")
    frame["calendar_year"] = frame["calendar_year"].astype("int16")
    frame["is_traded"] = pd.array(frame["is_traded"], dtype="Int8")
    frame["reason"] = frame["reason"].astype("string")
    if any(term in column.lower() for column in frame for term in FORBIDDEN_OUTPUT_TERMS):
        raise ValueError("economic field escaped into calendar source")
    return frame.sort_values("tradedate", kind="stable", ignore_index=True)


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = _retrieval(retrieved_at)
    boundary = pd.Timestamp(config["causality"]["earliest_eligible_retrieval_at_utc"])
    if retrieval < boundary:
        raise ValueError("MOEX calendar retrieval precedes source seal")
    client: SessionLike = session or requests.Session()
    response = _get(client, config)
    raw = bytes(response.content)
    calendar = parse_response(raw, retrieval)

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_calendar_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_path = temporary / "raw_moex_trading_calendar.html.gz"
        raw_path.write_bytes(gzip.compress(raw, mtime=0))
        calendar_path = temporary / "calendar.parquet"
        calendar.to_parquet(calendar_path, index=False)
        url, params, _ = request_parts(config)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(MODULE_PATH),
            "retrieved_at_utc": retrieval.isoformat(),
            "available_at_utc": retrieval.isoformat(),
            "status": "complete_valid",
            "forward_only": True,
            "contains_return_label_signal_target_prediction_equity_or_pnl": False,
            "raw": {
                "path": raw_path.name,
                "url": url,
                "query": params,
                "response_bytes": len(raw),
                "response_sha256": _sha_bytes(raw),
                "stored_bytes": raw_path.stat().st_size,
                "stored_sha256": _sha(raw_path),
            },
            "processed": {
                "path": calendar_path.name,
                "bytes": calendar_path.stat().st_size,
                "sha256": _sha(calendar_path),
                "rows": len(calendar),
                "known_trading_dates": int(calendar["is_traded"].eq(1).sum()),
                "known_nontrading_dates": int(calendar["is_traded"].eq(0).sum()),
                "unknown_dates": int(calendar["is_traded"].isna().sum()),
                "first_date": calendar["tradedate"].min().date().isoformat(),
                "last_date": calendar["tradedate"].max().date().isoformat(),
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("MOEX futures calendar source audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    raw_item = manifest["raw"]
    raw_path = snapshot / raw_item["path"]
    raw = gzip.decompress(raw_path.read_bytes())
    retrieval = _retrieval(manifest["retrieved_at_utc"])
    rebuilt = parse_response(raw, retrieval)
    processed = manifest["processed"]
    calendar_path = snapshot / processed["path"]
    stored = pd.read_parquet(calendar_path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    return {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha(MODULE_PATH),
        "protocol_exact": manifest["protocol_id"]
        == "futures_v27_forward_calendar_html_transport_v1",
        "complete_valid": manifest["status"] == "complete_valid",
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest[
            "contains_return_label_signal_target_prediction_equity_or_pnl"
        ]
        is False,
        "availability_equals_retrieval": manifest["available_at_utc"]
        == manifest["retrieved_at_utc"],
        "raw_stored_exact": raw_path.stat().st_size == int(raw_item["stored_bytes"])
        and _sha(raw_path) == raw_item["stored_sha256"],
        "raw_response_exact": len(raw) == int(raw_item["response_bytes"])
        and _sha_bytes(raw) == raw_item["response_sha256"],
        "processed_exact": calendar_path.stat().st_size == int(processed["bytes"])
        and _sha(calendar_path) == processed["sha256"],
        "processed_rows_exact": len(stored) == int(processed["rows"]),
        "known_trading_dates_exact": int(stored["is_traded"].eq(1).sum())
        == int(processed["known_trading_dates"]),
        "known_nontrading_dates_exact": int(stored["is_traded"].eq(0).sum())
        == int(processed["known_nontrading_dates"]),
        "unknown_dates_exact": int(stored["is_traded"].isna().sum())
        == int(processed["unknown_dates"]),
        "raw_replay_exact": replay_exact,
        "schema_exact": tuple(stored.columns) == OUTPUT_COLUMNS,
        "no_economic_columns": not any(
            term in column.lower()
            for column in stored.columns
            for term in FORBIDDEN_OUTPUT_TERMS
        ),
        "all_dates_available_after_retrieval": bool(
            pd.to_datetime(stored["available_at_utc"], utc=True).eq(retrieval).all()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        return
    print(collect(args.output_root))


if __name__ == "__main__":
    main()
