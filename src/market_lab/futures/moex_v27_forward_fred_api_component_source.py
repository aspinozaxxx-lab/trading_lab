"""Capture the V27 STLFSI4 component through the authenticated official FRED API."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

from market_lab.futures import moex_v27_forward_component_source as parent_component
from market_lab.futures import moex_v27_forward_validation_source as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v27_forward_fred_api_component_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "2954c5a41a2687b0f017f14ab53af023a9b60dc4a9576c3fdede455d71fdd568"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = parent_component.DEFAULT_OUTPUT_ROOT
API_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{32}$")


class ResponseLike(Protocol):
    content: bytes
    status_code: int


class SessionLike(Protocol):
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return parent_component._sha(path)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent_config = config["parent_component_source"]
    auth = config["authentication"]
    route = config["route_selection"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "futures_v27_forward_fred_api_component_v1"
        or config.get("live_trading_allowed") is not False
        or parent_config["protocol_sha256"] != parent_component.CONFIG_SHA256
        or parent_config["implementation_sha256"] != _sha(Path(parent_component.__file__))
        or auth["environment_variable"] != "FRED_API_KEY"
        or auth["command_line_argument"] != "forbidden"
        or auth["manifest_query_or_URL"] != "redacted"
        or route["if_FRED_API_KEY_configured"] != "authenticated_API_only"
        or route["fallback_after_authenticated_HTTP_or_parse_failure"] != "forbidden"
        or route["selection_by_market_outcome"] != "forbidden"
    ):
        raise ValueError("authenticated FRED component protocol drifted")
    parent_component.load_config()
    return config


def load_api_key() -> str:
    value = os.environ.get("FRED_API_KEY", "")
    if not API_KEY_PATTERN.fullmatch(value):
        raise ValueError("FRED_API_KEY is not configured as 32 lowercase alphanumeric chars")
    return value


def request_urls(
    retrieval: pd.Timestamp, api_key: str, config: dict[str, Any]
) -> tuple[str, str, dict[str, str | int]]:
    settings = config["official_api"]
    end = retrieval.date()
    start = end - timedelta(days=int(settings["observation_lookback_days"]))
    public: dict[str, str | int] = {
        "series_id": str(settings["series_id"]),
        "file_type": str(settings["file_type"]),
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
        "realtime_start": end.isoformat(),
        "realtime_end": end.isoformat(),
        "output_type": int(settings["output_type"]),
        "sort_order": str(settings["sort_order"]),
        "limit": int(settings["limit"]),
    }
    redacted = f"{settings['endpoint']}?{urlencode(public)}"
    secret = f"{redacted}&api_key={api_key}"
    return secret, redacted, public


def _get_sanitized(
    client: SessionLike, secret_url: str, *, attempts: int = 3
) -> ResponseLike:
    if attempts <= 0:
        raise ValueError("FRED API attempts must be positive")
    for attempt in range(attempts):
        try:
            response = client.get(
                secret_url,
                headers={"User-Agent": "market-lab-v27-fred-api/1.0 (research)"},
                timeout=30.0,
            )
            if int(response.status_code) >= 400:
                raise RuntimeError(f"official FRED API returned HTTP {response.status_code}")
            return response
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise RuntimeError("official FRED API transport failed") from None
            time.sleep(2**attempt)
    raise AssertionError("unreachable FRED API retry state")


def parse_response(raw: bytes, retrieval: pd.Timestamp) -> pd.DataFrame:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("official FRED API response is not valid UTF-8 JSON") from error
    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("official FRED API observations are empty")
    rows: list[dict[str, Any]] = []
    for item in observations:
        observation = date.fromisoformat(str(item["date"]))
        value_text = str(item.get("value", "")).strip()
        rows.append(
            {
                "series_id": "stlfsi4",
                "observation_date": pd.Timestamp(observation),
                "effective_date": pd.Timestamp(observation),
                "value": float(value_text)
                if value_text not in {"", "."}
                else float("nan"),
                "model_available_at_utc": parent.stlfsi_source.conservative_available_at(
                    observation
                ),
            }
        )
    frame = pd.DataFrame(rows).sort_values("observation_date", ignore_index=True)
    if frame["observation_date"].duplicated().any():
        raise ValueError("duplicate official FRED API observation date")
    frame["forward_available_at_utc"] = parent._forward_availability(
        frame["model_available_at_utc"], retrieval
    )
    frame["retrieved_at_utc"] = retrieval.tz_convert("UTC")
    frame["source_current_vintage"] = True
    return frame.loc[:, parent.MACRO_COLUMNS]


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    api_key = load_api_key()
    retrieval = parent_component._retrieval(retrieved_at)
    boundary = pd.Timestamp(
        parent_component.load_config()["forward_boundary"][
            "earliest_component_retrieval_at_utc"
        ]
    )
    if retrieval < boundary:
        raise ValueError("authenticated FRED retrieval precedes component seal")
    secret_url, redacted_url, public_query = request_urls(retrieval, api_key, config)
    client: SessionLike = session or requests.Session()
    response = _get_sanitized(client, secret_url)
    raw = bytes(response.content)
    if api_key.encode() in raw:
        raise ValueError("official FRED response unexpectedly contains the API key")
    macro = parse_response(raw, retrieval)

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_macro_fred_api_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_path = temporary / "raw_fred_api_stlfsi4.json.gz"
        raw_path.write_bytes(gzip.compress(raw, mtime=0))
        macro_path = temporary / "macro.parquet"
        macro.to_parquet(macro_path, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha(MODULE_PATH),
            "parent_component_protocol_sha256": parent_component.CONFIG_SHA256,
            "parent_component_implementation_sha256": _sha(
                Path(parent_component.__file__)
            ),
            "component": "macro_fred",
            "transport": "authenticated_official_FRED_API",
            "retrieved_at_utc": retrieval.isoformat(),
            "source_dates": [],
            "status": "complete_valid",
            "forward_only": True,
            "contains_return_label_target_prediction_or_pnl": False,
            "credential_persisted": False,
            "raw": {
                "fred_api_stlfsi4": {
                    "path": raw_path.name,
                    "url_without_credential": redacted_url,
                    "public_query": public_query,
                    "response_bytes": len(raw),
                    "response_sha256": _sha_bytes(raw),
                    "stored_bytes": raw_path.stat().st_size,
                    "stored_sha256": _sha(raw_path),
                }
            },
            "processed": {
                "name": "macro",
                "path": macro_path.name,
                "bytes": macro_path.stat().st_size,
                "sha256": _sha(macro_path),
                "rows": len(macro),
            },
        }
        serialized = json.dumps(manifest, ensure_ascii=False)
        if api_key in serialized or "api_key" in serialized.lower():
            raise ValueError("FRED credential leaked into manifest")
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("authenticated FRED component audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    load_config()
    manifest_bytes = (snapshot / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    item = manifest["raw"]["fred_api_stlfsi4"]
    raw_path = snapshot / item["path"]
    raw = gzip.decompress(raw_path.read_bytes())
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    rebuilt = parse_response(raw, retrieval)
    processed = manifest["processed"]
    macro_path = snapshot / processed["path"]
    stored = pd.read_parquet(macro_path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
        replay_exact = True
    except AssertionError:
        replay_exact = False
    manifest_text = manifest_bytes.decode("utf-8-sig").lower()
    return {
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha(MODULE_PATH),
        "parent_protocol_exact": manifest["parent_component_protocol_sha256"]
        == parent_component.CONFIG_SHA256,
        "parent_implementation_exact": manifest[
            "parent_component_implementation_sha256"
        ]
        == _sha(Path(parent_component.__file__)),
        "component_exact": manifest["component"] == "macro_fred",
        "authenticated_transport_exact": manifest["transport"]
        == "authenticated_official_FRED_API",
        "credential_not_persisted": manifest["credential_persisted"] is False
        and "api_key" not in manifest_text,
        "forward_only": manifest["forward_only"] is True,
        "target_free": manifest["contains_return_label_target_prediction_or_pnl"] is False,
        "raw_stored_exact": raw_path.stat().st_size == int(item["stored_bytes"])
        and _sha(raw_path) == item["stored_sha256"],
        "raw_response_exact": len(raw) == int(item["response_bytes"])
        and _sha_bytes(raw) == item["response_sha256"],
        "processed_exact": macro_path.stat().st_size == int(processed["bytes"])
        and _sha(macro_path) == processed["sha256"],
        "processed_rows_exact": len(stored) == int(processed["rows"]),
        "raw_replay_exact": replay_exact,
        "macro_series_exact": set(stored["series_id"]) == {"stlfsi4"},
        "availability_after_retrieval": bool(
            pd.to_datetime(stored["forward_available_at_utc"], utc=True)
            .ge(retrieval)
            .all()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
