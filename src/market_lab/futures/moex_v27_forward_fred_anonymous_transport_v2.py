"""Capture frozen V27 STLFSI4 with a CDN-compatible anonymous request header."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol

import pandas as pd
import requests
import yaml

from market_lab.futures import moex_v27_forward_component_source as parent_component
from market_lab.futures import moex_v27_forward_validation_source as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v27_forward_fred_anonymous_transport_v2.yaml"
)
CONFIG_SHA256: Final[str] = (
    "8a26480dd25f17e3522b00efdb5f83bb67dee7ff0e95351cf460581fc5c01028"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = parent_component.DEFAULT_OUTPUT_ROOT


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
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("anonymous FRED transport config must be an object")
    component = config["parent_component_source"]
    official = config["official_source"]
    diagnosis = config["transport_diagnosis"]
    retry = config["retry"]
    headers = config["request_headers"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "futures_v27_forward_fred_anonymous_transport_v2"
        or config.get("live_trading_allowed") is not False
        or component["protocol_sha256"] != parent_component.CONFIG_SHA256
        or component["implementation_sha256"] != _sha(Path(parent_component.__file__))
        or component["parser_sha256"] != _sha(Path(parent.__file__))
        or official["series_id"] != "STLFSI4"
        or official["query_and_date_bounds_changed_from_parent"] is not False
        or official["parser_and_output_columns_changed_from_parent"] is not False
        or official["model_and_forward_availability_changed_from_parent"] is not False
        or diagnosis["response_payload_values_read"] is not False
        or diagnosis["market_prices_returns_or_pnl_used"] is not False
        or headers["Accept"] != "text/csv"
        or headers["Accept-Encoding"] != "identity"
        or headers["Connection"] != "close"
        or int(retry["attempts"]) != 3
        or list(retry["backoff_seconds"]) != [1, 2]
        or retry["fallback_to_cache_or_other_series"] != "forbidden"
    ):
        raise ValueError("anonymous FRED transport protocol drifted")
    parent_component.load_config()
    return config


def request_url(retrieval: pd.Timestamp, config: Mapping[str, Any]) -> str:
    expected = str(config["official_source"]["endpoint"])
    url = parent.fred_url(retrieval)
    if not url.startswith(f"{expected}?"):
        raise ValueError("anonymous FRED endpoint or query drifted")
    return url


def _get(
    client: SessionLike,
    url: str,
    config: Mapping[str, Any],
) -> ResponseLike:
    retry = config["retry"]
    headers = {str(key): str(value) for key, value in config["request_headers"].items()}
    attempts = int(retry["attempts"])
    backoff = [float(value) for value in retry["backoff_seconds"]]
    for attempt in range(attempts):
        try:
            response = client.get(
                url,
                headers=headers,
                timeout=float(retry["timeout_seconds"]),
            )
            if int(response.status_code) >= 400:
                raise RuntimeError(f"official FRED fredgraph returned HTTP {response.status_code}")
            return response
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise RuntimeError("official anonymous FRED transport v2 failed") from None
            time.sleep(backoff[attempt])
    raise AssertionError("unreachable anonymous FRED retry state")


def parse_response(raw: bytes, retrieval: pd.Timestamp) -> pd.DataFrame:
    return parent.parse_fred_forward(raw, retrieval)


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    retrieval = parent_component._retrieval(retrieved_at)
    boundary = pd.Timestamp(
        parent_component.load_config()["forward_boundary"][
            "earliest_component_retrieval_at_utc"
        ]
    )
    if retrieval < boundary:
        raise ValueError("anonymous FRED transport V2 retrieval precedes component seal")
    url = request_url(retrieval, config)
    client: SessionLike = session or requests.Session()
    response = _get(client, url, config)
    raw = bytes(response.content)
    macro = parse_response(raw, retrieval)

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"snapshot_macro_fred_transport_v2_{retrieval.strftime('%Y%m%dT%H%M%S%fZ')}"
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        raw_path = temporary / "raw_fred_stlfsi4.csv.gz"
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
            "transport": "anonymous_fredgraph_header_v2",
            "retrieved_at_utc": retrieval.isoformat(),
            "source_dates": [],
            "status": "complete_valid",
            "forward_only": True,
            "contains_return_label_target_prediction_or_pnl": False,
            "raw": {
                "fred_stlfsi4": {
                    "path": raw_path.name,
                    "url": url,
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
        _write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("anonymous FRED transport V2 audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    load_config()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    item = manifest["raw"]["fred_stlfsi4"]
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
        "transport_exact": manifest["transport"] == "anonymous_fredgraph_header_v2",
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
        if not all(checks.values()):
            raise SystemExit(1)
    else:
        print(collect(args.output_root))


if __name__ == "__main__":
    main()
