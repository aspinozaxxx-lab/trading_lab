"""Collect immutable bounded STLFSI4, RUONIA, and CBR key-rate source data."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import math
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml

from market_lab.futures import info_radar
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/pre2018_macro_source.yaml"
FRED_HOST: Final[str] = "fred.stlouisfed.org"
FRED_SERIES: Final[str] = "STLFSI4"
CHICAGO: Final[ZoneInfo] = ZoneInfo("America/Chicago")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
MAX_RESPONSE_BYTES: Final[int] = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0
REQUEST_ATTEMPTS: Final[int] = 3
STLFSI_PUBLICATION_LAG_DAYS: Final[int] = 6
MONETARY_COLUMNS: Final[tuple[str, ...]] = (
    "source",
    "series_id",
    "observation_date",
    "publication_date",
    "available_at",
    "value",
    "availability_rule",
)
FORBIDDEN_OUTCOME_TOKENS: Final[tuple[str, ...]] = (
    "return",
    "target",
    "label",
    "prediction",
    "signal",
    "strategy",
    "pnl",
    "equity",
)


class ResponseLike(Protocol):
    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        data: bytes | None = None,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class MacroSourceProtocol:
    """Byte-sealed bounded source protocol with no strategy fields."""

    config_path: Path
    config_sha256: str
    source_start: date
    source_end: date
    protected_from: date
    output_directory: Path
    minimum_stlfsi_rows: int
    minimum_ruonia_rows: int
    minimum_key_rate_rows: int
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class RawResponse:
    """One exact official response plus request identity."""

    kind: str
    method: str
    url: str
    request_body: bytes | None
    content: bytes
    headers: Mapping[str, str]
    retrieved_at_utc: str


@dataclass(frozen=True, slots=True)
class MacroSourceTables:
    """Target-free processed source tables and raw provenance."""

    stlfsi: pd.DataFrame
    monetary: pd.DataFrame
    coverage: pd.DataFrame
    responses: tuple[RawResponse, ...]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _project_path(relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("macro source path must be project-relative")
    root = PROJECT_ROOT.resolve()
    candidate = Path.absolute(root / relative)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("macro source path escapes project root") from error
    first = candidate.relative_to(root).parts[0]
    if first not in {"data", "runs", "models"}:
        try:
            candidate.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError("macro source path resolves outside project root") from error
    return candidate


def _sidecar_sha(path: Path) -> str:
    parts = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").strip().split()
    if len(parts) != 2 or parts[1] != path.name:
        raise ValueError("invalid macro source SHA sidecar")
    return parts[0].lower()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> MacroSourceProtocol:
    """Verify source protocol and implementation bytes before any HTTP request."""
    path = config_path.resolve()
    actual_sha = sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("macro source protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("macro source protocol must be a YAML object")
    if payload.get("protocol_id") != "pre2018_macro_source_v1":
        raise ValueError("unexpected macro source protocol id")
    if payload.get("scope") != "source_only_no_market_outcomes":
        raise ValueError("macro protocol is not source-only")
    bounds = payload.get("request_bounds")
    output = payload.get("output")
    coverage = payload.get("minimum_coverage")
    dependencies = payload.get("implementation_dependencies")
    if not all(isinstance(item, Mapping) for item in (bounds, output, coverage, dependencies)):
        raise ValueError("macro source protocol has an invalid section")
    assert isinstance(bounds, Mapping)
    assert isinstance(output, Mapping)
    assert isinstance(coverage, Mapping)
    assert isinstance(dependencies, Mapping)
    source_start = date.fromisoformat(str(bounds["from"]))
    source_end = date.fromisoformat(str(bounds["through"]))
    protected_from = date.fromisoformat(str(bounds["protected_from"]))
    if (source_start, source_end, protected_from) != (
        date(2012, 1, 1),
        date(2017, 12, 31),
        date(2018, 1, 1),
    ):
        raise ValueError("macro source date bounds changed")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = _project_path(str(relative))
        digest = str(expected).lower()
        if sha256_file(dependency_path) != digest:
            raise ValueError(f"macro source dependency SHA drift: {relative}")
        dependency_hashes[str(relative)] = digest
    protocol = MacroSourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        source_start=source_start,
        source_end=source_end,
        protected_from=protected_from,
        output_directory=_project_path(str(output["directory"])),
        minimum_stlfsi_rows=int(coverage["stlfsi_complete_rows"]),
        minimum_ruonia_rows=int(coverage["ruonia_rows"]),
        minimum_key_rate_rows=int(coverage["key_rate_rows"]),
        dependency_hashes=dependency_hashes,
    )
    if min(
        protocol.minimum_stlfsi_rows,
        protocol.minimum_ruonia_rows,
        protocol.minimum_key_rate_rows,
    ) <= 0:
        raise ValueError("macro source minimum coverage must be positive")
    return protocol


def fred_url(protocol: MacroSourceProtocol) -> str:
    query = urlencode(
        {
            "id": FRED_SERIES,
            "cosd": protocol.source_start.isoformat(),
            "coed": protocol.source_end.isoformat(),
        }
    )
    value = f"https://{FRED_HOST}/graph/fredgraph.csv?{query}"
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != FRED_HOST
        or parsed.path != "/graph/fredgraph.csv"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise ValueError("bounded FRED URL escaped the official endpoint")
    return value


def stlfsi_available_at(observation: date) -> pd.Timestamp:
    local = datetime.combine(
        observation + timedelta(days=STLFSI_PUBLICATION_LAG_DAYS),
        time(23, 59, 59),
        tzinfo=CHICAGO,
    )
    return pd.Timestamp(local).tz_convert("UTC")


def parse_stlfsi(content: bytes, protocol: MacroSourceProtocol) -> pd.DataFrame:
    """Parse exact bounded weekly rows, preserve missing, and add conservative timing."""
    if not content or len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("bounded STLFSI4 response size is invalid")
    try:
        text_value = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("bounded STLFSI4 response is not UTF-8") from error
    reader = csv.DictReader(StringIO(text_value))
    if reader.fieldnames != ["observation_date", FRED_SERIES]:
        raise ValueError(f"bounded STLFSI4 header drift: {reader.fieldnames}")
    rows: list[dict[str, Any]] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            observation = date.fromisoformat(str(row["observation_date"]))
        except ValueError as error:
            raise ValueError(f"invalid STLFSI4 date at line {line_number}") from error
        if not protocol.source_start <= observation <= protocol.source_end:
            raise ValueError("FRED ignored bounded STLFSI4 dates")
        raw_value = str(row[FRED_SERIES] or "").strip()
        if raw_value in {"", "."}:
            value = float("nan")
        else:
            try:
                value = float(raw_value)
            except ValueError as error:
                raise ValueError(f"invalid STLFSI4 value at line {line_number}") from error
            if not math.isfinite(value) or abs(value) > 25.0:
                raise ValueError("implausible STLFSI4 value")
        rows.append(
            {
                "observation_date": pd.Timestamp(observation),
                "stress_index": value,
                "available_at": stlfsi_available_at(observation),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("bounded STLFSI4 response has no observations")
    if (
        frame["observation_date"].duplicated().any()
        or not frame["observation_date"].is_monotonic_increasing
        or not frame["observation_date"].dt.dayofweek.eq(4).all()
    ):
        raise ValueError("STLFSI4 dates are duplicate, unordered, or non-Friday")
    frame["complete"] = frame["stress_index"].notna()
    frame["stress_state"] = "missing"
    frame.loc[frame["complete"] & frame["stress_index"].gt(0.0), "stress_state"] = (
        "above_average"
    )
    frame.loc[frame["complete"] & frame["stress_index"].le(0.0), "stress_state"] = (
        "normal_or_below"
    )
    frame["source_current_vintage"] = True
    frame["methodology_version"] = FRED_SERIES
    protected = pd.Timestamp(protocol.protected_from, tz=MOSCOW).tz_convert("UTC")
    return frame.loc[frame["available_at"].lt(protected)].reset_index(drop=True)


def parse_monetary(
    ruonia_content: bytes,
    key_rate_content: bytes,
    protocol: MacroSourceProtocol,
) -> pd.DataFrame:
    """Replay official CBR parsers and retain only causally pre-2018 rows."""
    ruonia = info_radar.parse_cbr_ruonia_html(ruonia_content)
    key_rate = info_radar.parse_cbr_key_rate_xml(key_rate_content)
    frames: list[pd.DataFrame] = []
    for name, frame in (("ruonia", ruonia), ("key_rate", key_rate)):
        local = frame.loc[:, MONETARY_COLUMNS].copy()
        local["observation_date"] = pd.to_datetime(
            local["observation_date"], errors="raise"
        ).dt.normalize()
        local["publication_date"] = pd.to_datetime(
            local["publication_date"], errors="coerce"
        ).dt.normalize()
        local["available_at"] = pd.to_datetime(local["available_at"], errors="raise", utc=True)
        if (
            local["observation_date"].dt.date.lt(protocol.source_start).any()
            or local["observation_date"].dt.date.gt(protocol.source_end).any()
            or not local["series_id"].astype(str).eq(name).all()
        ):
            raise ValueError(f"CBR {name} ignored bounded request dates")
        frames.append(local)
    combined = pd.concat(frames, ignore_index=True)
    protected = pd.Timestamp(protocol.protected_from, tz=MOSCOW).tz_convert("UTC")
    combined = combined.loc[combined["available_at"].lt(protected)].copy()
    combined["value"] = pd.to_numeric(combined["value"], errors="raise").astype(float)
    if (
        combined.duplicated(["series_id", "observation_date"]).any()
        or combined["value"].isna().any()
        or not combined["value"].gt(0.0).all()
    ):
        raise ValueError("CBR monetary rows are duplicate, missing, or nonpositive")
    return combined.sort_values(
        ["series_id", "available_at", "observation_date"],
        kind="mergesort",
        ignore_index=True,
    )


def _fetch(
    session: SessionLike,
    *,
    kind: str,
    method: str,
    url: str,
    retrieved_at_utc: str,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> RawResponse:
    response: ResponseLike | None = None
    last_error: BaseException | None = None
    succeeded = False
    request_headers = {
        "User-Agent": "market-lab-research/pre2018-macro-source-v1",
        "Accept": "*/*",
        "Connection": "close",
        **({} if headers is None else dict(headers)),
    }
    for _attempt in range(REQUEST_ATTEMPTS):
        try:
            response = session.request(
                method,
                url,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
                data=data,
            )
            response.raise_for_status()
            succeeded = True
            break
        except (OSError, TimeoutError, requests.RequestException) as error:
            last_error = error
            response = None
    if not succeeded or response is None:
        raise RuntimeError(f"official {kind} request failed") from last_error
    if not response.content or len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError(f"official {kind} response size is invalid")
    return RawResponse(
        kind=kind,
        method=method,
        url=url,
        request_body=data,
        content=response.content,
        headers=dict(response.headers),
        retrieved_at_utc=retrieved_at_utc,
    )


def collect(
    protocol: MacroSourceProtocol,
    *,
    session: SessionLike | None = None,
    retrieved_at_utc: str | None = None,
) -> MacroSourceTables:
    """Fetch exactly three bounded official responses and build target-free tables."""
    retrieved = retrieved_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    retrieved_timestamp = pd.Timestamp(retrieved)
    if retrieved_timestamp.tzinfo is None:
        raise ValueError("macro source retrieval timestamp must be timezone-aware")
    retrieved_timestamp = retrieved_timestamp.tz_convert("UTC")
    transport = session or requests.Session()
    fred = _fetch(
        transport,
        kind="fred_stlfsi4_csv",
        method="GET",
        url=fred_url(protocol),
        retrieved_at_utc=retrieved,
    )
    ruonia = _fetch(
        transport,
        kind="cbr_ruonia_html",
        method="GET",
        url=info_radar.build_cbr_ruonia_url(protocol.source_start, protocol.source_end),
        retrieved_at_utc=retrieved,
    )
    key_body = info_radar.build_cbr_key_rate_soap(protocol.source_start, protocol.source_end)
    key_rate = _fetch(
        transport,
        kind="cbr_key_rate_soap_xml",
        method="POST",
        url=info_radar.CBR_DAILY_INFO_ENDPOINT,
        data=key_body,
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://web.cbr.ru/KeyRateXML",
        },
        retrieved_at_utc=retrieved,
    )
    stlfsi = parse_stlfsi(fred.content, protocol)
    stlfsi["retrieved_at_utc"] = pd.Series(
        [retrieved_timestamp] * len(stlfsi),
        dtype="datetime64[ms, UTC]",
    )
    stlfsi = stlfsi.loc[
        :,
        [
            "observation_date",
            "stress_index",
            "available_at",
            "complete",
            "stress_state",
            "retrieved_at_utc",
            "source_current_vintage",
            "methodology_version",
        ],
    ]
    monetary = parse_monetary(ruonia.content, key_rate.content, protocol)
    counts = monetary["series_id"].value_counts()
    if (
        int(stlfsi["complete"].sum()) < protocol.minimum_stlfsi_rows
        or int(counts.get("ruonia", 0)) < protocol.minimum_ruonia_rows
        or int(counts.get("key_rate", 0)) < protocol.minimum_key_rate_rows
    ):
        raise ValueError("pre-2018 macro source minimum coverage failed")
    coverage = pd.DataFrame(
        [
            {
                "series_id": FRED_SERIES,
                "rows": len(stlfsi),
                "complete_rows": int(stlfsi["complete"].sum()),
                "minimum_observation_date": stlfsi["observation_date"].min(),
                "maximum_observation_date": stlfsi["observation_date"].max(),
                "minimum_available_at": stlfsi["available_at"].min(),
                "maximum_available_at": stlfsi["available_at"].max(),
            },
            *[
                {
                    "series_id": series_id,
                    "rows": len(group),
                    "complete_rows": len(group),
                    "minimum_observation_date": group["observation_date"].min(),
                    "maximum_observation_date": group["observation_date"].max(),
                    "minimum_available_at": group["available_at"].min(),
                    "maximum_available_at": group["available_at"].max(),
                }
                for series_id, group in monetary.groupby("series_id", sort=True)
            ],
        ]
    )
    return MacroSourceTables(stlfsi, monetary, coverage, (fred, ruonia, key_rate))


def _assert_source_only_schema(frames: Mapping[str, pd.DataFrame]) -> None:
    offenders = {
        name: [
            str(column)
            for column in frame.columns
            if any(token in str(column).lower() for token in FORBIDDEN_OUTCOME_TOKENS)
        ]
        for name, frame in frames.items()
    }
    offenders = {name: columns for name, columns in offenders.items() if columns}
    if offenders:
        raise ValueError(f"macro source contains outcome columns: {offenders}")


def _raw_archive(responses: tuple[RawResponse, ...]) -> bytes:
    lines: list[bytes] = []
    for index, response in enumerate(responses):
        headers = {
            key: response.headers[key]
            for key in ("Content-Type", "Last-Modified", "ETag")
            if key in response.headers
        }
        line = {
            "request_index": index,
            "kind": response.kind,
            "method": response.method,
            "url": response.url,
            "request_body_bytes": (
                0 if response.request_body is None else len(response.request_body)
            ),
            "request_body_sha256": (
                None if response.request_body is None else sha256_bytes(response.request_body)
            ),
            "response_headers": headers,
            "response_bytes": len(response.content),
            "response_sha256": sha256_bytes(response.content),
            "retrieved_at_utc": response.retrieved_at_utc,
            "content_encoding": "base64",
            "content": base64.b64encode(response.content).decode("ascii"),
        }
        lines.append(_canonical_json(line))
    return gzip.compress(b"\n".join(lines) + b"\n", compresslevel=6, mtime=0)


def _artifact(path: Path, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if frame is not None:
        record["rows"] = len(frame)
        record["columns"] = frame.columns.tolist()
    return record


def persist(protocol: MacroSourceProtocol, tables: MacroSourceTables) -> Path:
    """Atomically publish one immutable macro source bundle outside Git."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"pre-2018 macro output already exists: {final}")
    frames = {
        "stlfsi4": tables.stlfsi,
        "cbr_monetary": tables.monetary,
        "coverage": tables.coverage,
    }
    _assert_source_only_schema(frames)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            frame.to_parquet(path, index=False, compression="zstd")
            artifacts[name] = _artifact(path, frame)
        raw_path = temporary / "official_macro_responses.jsonl.gz"
        atomic_write_bytes(raw_path, _raw_archive(tables.responses))
        artifacts["raw_archive"] = {
            **_artifact(raw_path),
            "records": len(tables.responses),
        }
        state_counts = tables.stlfsi["stress_state"].value_counts()
        monetary_counts = tables.monetary["series_id"].value_counts()
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-pre2018-stlfsi4-cbr-monetary-current-vintage-v1",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "implementation_dependencies": protocol.dependency_hashes,
            "providers": ["Federal Reserve Bank of St. Louis via FRED", "Bank of Russia"],
            "request_count": len(tables.responses),
            "request_bounds": {
                "from": protocol.source_start.isoformat(),
                "through": protocol.source_end.isoformat(),
                "protected_from": protocol.protected_from.isoformat(),
                "server_side_bounded": True,
            },
            "coverage": {
                "stlfsi_rows": len(tables.stlfsi),
                "stlfsi_complete_rows": int(tables.stlfsi["complete"].sum()),
                "stlfsi_above_average_rows": int(state_counts.get("above_average", 0)),
                "stlfsi_normal_or_below_rows": int(state_counts.get("normal_or_below", 0)),
                "ruonia_rows": int(monetary_counts.get("ruonia", 0)),
                "key_rate_rows": int(monetary_counts.get("key_rate", 0)),
                "key_rate_minimum_percent": float(
                    tables.monetary.loc[
                        tables.monetary["series_id"].eq("key_rate"), "value"
                    ].min()
                ),
                "key_rate_maximum_percent": float(
                    tables.monetary.loc[
                        tables.monetary["series_id"].eq("key_rate"), "value"
                    ].max()
                ),
            },
            "temporal_semantics": {
                "STLFSI4_available_at": (
                    "Thursday 23:59:59 America/Chicago six calendar days after Friday"
                ),
                "RUONIA_available_at": "publication_date_plus_one_calendar_day_Moscow",
                "key_rate_available_at": "effective_date_plus_one_calendar_day_Moscow",
                "every_processed_available_at_before_2018": True,
                "admissible_join": "latest available_at less than or equal to decision_at",
                "missing_values_preserved": True,
                "contains_MOEX_prices_returns_targets_labels_or_pnl": False,
            },
            "limitations": {
                "STLFSI4_current_vintage": True,
                "STLFSI4_original_historical_vintages_proved": False,
                "CBR_exact_intraday_publication_timestamp": False,
                "CBR_conservative_calendar_lag_used": True,
                "strategy_outcomes_observed": False,
                "live_admission_possible": False,
            },
            "rights": {
                "FRED_values_copyrighted_and_citation_required": True,
                "raw_archive_stored_outside_git": True,
                "redistribution_not_authorized_by_this_manifest": True,
            },
            "artifacts": artifacts,
        }
        manifest_path = temporary / "manifest.json"
        identity = sha256_bytes(_canonical_json(manifest_core))
        write_json(manifest_path, {**manifest_core, "manifest_payload_sha256": identity})
        manifest_sha = sha256_file(manifest_path)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{manifest_sha}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def collect_and_persist(config_path: Path = DEFAULT_CONFIG) -> Path:
    protocol = load_protocol(config_path)
    return persist(protocol, collect(protocol))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    arguments = parser.parse_args(argv)
    print(collect_and_persist(arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
