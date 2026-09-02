"""Correct board-wide OFZ history transport to explicit daily MOEX requests."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import pandas as pd
import yaml

from market_lab.futures import moex_ofz_total_return_source as base

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_ofz_total_return_source_r1.yaml"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
PARENT_CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_ofz_total_return_source_v1.yaml"
CONTAINER_FORMAT: Final[str] = "ofz_daily_history_raw_container_v1"
_BASE_LOAD_CONFIG = base.load_config
_BASE_NORMALIZE_HISTORY = base.normalize_history_page
_BASE_CONFIG_PATH = base.CONFIG_PATH
_BASE_MODULE_PATH = base.MODULE_PATH


def _sha(path: Path) -> str:
    return base._sha_file(path)


def _load_parent() -> dict[str, Any]:
    old_config, old_module = base.CONFIG_PATH, base.MODULE_PATH
    base.CONFIG_PATH, base.MODULE_PATH = _BASE_CONFIG_PATH, _BASE_MODULE_PATH
    try:
        return _BASE_LOAD_CONFIG()
    finally:
        base.CONFIG_PATH, base.MODULE_PATH = old_config, old_module


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(correction, dict):
        raise ValueError("OFZ R1 correction must be an object")
    parent = correction["parent_v1"]
    implementation = correction["implementation"]
    transport = correction["transport_correction"]
    if (
        actual != declared
        or correction.get("protocol_id") != "moex_ofz_total_return_source_r1"
        or correction.get("status")
        != "sealed_after_v1_current_date_preflight_failure_before_historical_rows"
        or correction.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"]) != parent["implementation_sha256"]
        or _sha(PROJECT_ROOT / implementation["path"]) != implementation["sha256"]
        or transport["V1_output_created"] is not False
        or transport["V1_bondization_requested"] is not False
        or transport["market_fields_or_economics_changed"] is not False
        or transport["daily_container_format"] != CONTAINER_FORMAT
        or transport["date_enumeration"] != "every_calendar_day_in_sealed_range"
    ):
        raise ValueError("OFZ R1 correction drifted")
    config = copy.deepcopy(_load_parent())
    config["protocol_id"] = correction["protocol_id"]
    config["status"] = correction["status"]
    config["declared_at_utc"] = correction["declared_at_utc"]
    config["implementation"] = implementation
    config["transport_correction"] = transport
    config["source"]["history"]["transport"] = "explicit_date_parameter_per_calendar_day"
    config["source"]["history"]["daily_container_format"] = CONTAINER_FORMAT
    return config


def daily_history_url(config: dict[str, Any], date: pd.Timestamp, start: int) -> str:
    source = config["source"]["history"]
    query = {
        "iss.meta": "off",
        "iss.only": "history,history.cursor",
        "history.columns": ",".join(config["required_history_columns"]),
        "date": date.date().isoformat(),
        "start": start,
    }
    return f"{source['endpoint']}?{urlencode(query)}"


def _request_with_retry(client: base.SessionLike, url: str) -> bytes:
    delays = (0.0, 0.5, 2.0)
    failure: Exception | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            return base._request(client, url)
        except Exception as error:  # requests and synthetic clients share no base class
            failure = error
    raise RuntimeError("OFZ daily history request failed after fixed retries") from failure


def _daily_pages(
    client: base.SessionLike,
    config: dict[str, Any],
    retrieval: pd.Timestamp,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    source = config["source"]["history"]
    frames: list[pd.DataFrame] = []
    embedded: list[dict[str, Any]] = []
    for date in pd.date_range(source["from"], source["till"], freq="D"):
        start, total = 0, None
        while total is None or start < total:
            url = daily_history_url(config, date, start)
            raw = _request_with_retry(client, url)
            frame, observed_total, page_size = _BASE_NORMALIZE_HISTORY(
                raw,
                expected_start=start,
                retrieved_at=retrieval,
                config=config,
            )
            if total is not None and total != observed_total:
                raise ValueError("OFZ daily history total changed during pagination")
            total = observed_total
            if not frame.empty and not frame["trade_date"].eq(date).all():
                raise ValueError("OFZ explicit-date response returned another trade date")
            frames.append(frame)
            embedded.append(
                {
                    "date": date.date().isoformat(),
                    "cursor_start": start,
                    "url": url,
                    "response_bytes": len(raw),
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "response_base64": base64.b64encode(raw).decode("ascii"),
                }
            )
            if total == 0:
                break
            start += page_size
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        raise ValueError("OFZ explicit daily transport returned no historical rows")
    return pd.concat(nonempty, ignore_index=True), embedded


def _container_bytes(pages: list[dict[str, Any]]) -> bytes:
    payload = {"format": CONTAINER_FORMAT, "pages": pages}
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _fetch_history(
    client: base.SessionLike,
    config: dict[str, Any],
    retrieval: pd.Timestamp,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frame, embedded = _daily_pages(client, config, retrieval)
    raw = _container_bytes(embedded)
    url = (
        f"embedded:{CONTAINER_FORMAT}:"
        f"{config['source']['history']['from']}:{config['source']['history']['till']}"
    )
    return frame, [{"start": 0, "url": url, "raw": raw}]


def normalize_history_page(
    raw: bytes,
    *,
    expected_start: int,
    retrieved_at: pd.Timestamp,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    if payload.get("format") != CONTAINER_FORMAT:
        return _BASE_NORMALIZE_HISTORY(
            raw,
            expected_start=expected_start,
            retrieved_at=retrieved_at,
            config=config,
        )
    if expected_start != 0 or not isinstance(payload.get("pages"), list):
        raise ValueError("OFZ daily history container identity drift")
    frames: list[pd.DataFrame] = []
    source = config["source"]["history"]
    expected_dates = pd.date_range(source["from"], source["till"], freq="D")
    observed_dates: list[pd.Timestamp] = []
    for item in payload["pages"]:
        response = base64.b64decode(item["response_base64"], validate=True)
        if (
            len(response) != int(item["response_bytes"])
            or hashlib.sha256(response).hexdigest() != item["response_sha256"]
        ):
            raise ValueError("OFZ embedded daily response identity drift")
        date = pd.Timestamp(item["date"])
        frame, _, _ = _BASE_NORMALIZE_HISTORY(
            response,
            expected_start=int(item["cursor_start"]),
            retrieved_at=retrieved_at,
            config=config,
        )
        if not frame.empty and not frame["trade_date"].eq(date).all():
            raise ValueError("OFZ embedded response date drift")
        frames.append(frame)
        observed_dates.append(date)
    if set(observed_dates) != set(expected_dates):
        raise ValueError("OFZ daily container does not cover every sealed calendar date")
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        raise ValueError("OFZ daily container has no normalized history")
    combined = pd.concat(nonempty, ignore_index=True)
    return combined, len(combined), max(len(combined), 1)


def _activate() -> None:
    base.CONFIG_PATH = CONFIG_PATH
    base.MODULE_PATH = MODULE_PATH
    base.load_config = load_config
    base._fetch_history = _fetch_history
    base.normalize_history_page = normalize_history_page


def main() -> None:
    _activate()
    base.main()


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "CONTAINER_FORMAT",
    "daily_history_url",
    "load_config",
    "main",
    "normalize_history_page",
]
