"""Collect pre-2018 macro data while preserving unknown historical RUONIA timing."""

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import info_radar
from market_lab.futures import pre2018_macro_source as v1
from market_lab.futures import pre2018_macro_source_v2 as v2
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/pre2018_macro_source_v3.yaml"
EXPECTED_RUONIA_ROWS: Final[int] = 1478
EXPECTED_RUONIA_EXPLICIT_PUBLICATION_ROWS: Final[int] = 78
EXPECTED_RUONIA_UNKNOWN_PUBLICATION_ROWS: Final[int] = 1400
UNKNOWN_PUBLICATION_MARKERS: Final[frozenset[str]] = frozenset(
    {"", "-", "–", "—", chr(0xFFFD)}
)
DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d{2}\.\d{2}\.\d{4}")


@dataclass(frozen=True, slots=True)
class MacroSourceV3Protocol:
    """S3 parser-only correction inheriting every S2 request and transport rule."""

    config_path: Path
    config_sha256: str
    parent: v2.MacroSourceV2Protocol
    output_directory: Path
    dependency_hashes: dict[str, str]
    expected_ruonia_rows: int
    expected_explicit_publication_rows: int
    expected_unknown_publication_rows: int

    @property
    def source_start(self) -> Any:
        return self.parent.source_start

    @property
    def source_end(self) -> Any:
        return self.parent.source_end

    @property
    def protected_from(self) -> Any:
        return self.parent.protected_from

    @property
    def minimum_stlfsi_rows(self) -> int:
        return self.parent.minimum_stlfsi_rows

    @property
    def minimum_ruonia_rows(self) -> int:
        return self.parent.minimum_ruonia_rows

    @property
    def minimum_key_rate_rows(self) -> int:
        return self.parent.minimum_key_rate_rows


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> MacroSourceV3Protocol:
    """Verify S3 and complete S2 inheritance before official HTTP requests."""
    path = config_path.resolve()
    actual_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("macro source V3 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("macro source V3 protocol must be a YAML object")
    if payload.get("protocol_id") != "pre2018_macro_source_v3":
        raise ValueError("unexpected macro source V3 protocol id")
    if payload.get("scope") != "source_only_no_market_outcomes":
        raise ValueError("macro source V3 protocol is not source-only")
    parent_record = payload.get("parent_S2_protocol")
    failure = payload.get("failed_S2_parse_attempt")
    correction = payload.get("RUONIA_parser_correction")
    output = payload.get("output")
    dependencies = payload.get("implementation_dependencies")
    if not all(
        isinstance(item, Mapping)
        for item in (parent_record, failure, correction, output, dependencies)
    ):
        raise ValueError("macro source V3 protocol has an invalid section")
    assert isinstance(parent_record, Mapping)
    assert isinstance(failure, Mapping)
    assert isinstance(correction, Mapping)
    assert isinstance(output, Mapping)
    assert isinstance(dependencies, Mapping)
    parent = v2.load_protocol(v1._project_path(str(parent_record["path"])))
    if parent.config_sha256 != str(parent_record["sha256"]).lower():
        raise ValueError("macro source V3 parent S2 identity mismatch")
    counts = correction.get("exact_source_only_counts")
    if not isinstance(counts, Mapping):
        raise ValueError("macro source V3 lacks RUONIA count declaration")
    expected = (
        int(counts["total_rows"]),
        int(counts["explicit_publication_date_rows"]),
        int(counts["unknown_publication_date_rows"]),
    )
    if expected != (
        EXPECTED_RUONIA_ROWS,
        EXPECTED_RUONIA_EXPLICIT_PUBLICATION_ROWS,
        EXPECTED_RUONIA_UNKNOWN_PUBLICATION_ROWS,
    ):
        raise ValueError("macro source V3 RUONIA source-only counts changed")
    if (
        failure.get("output_published") is not False
        or failure.get("market_outcomes_observed") is not False
        or correction.get("only_changed_behavior")
        != "preserve_unknown_RUONIA_publication_date_and_available_at_as_missing"
        or correction.get("infer_missing_publication_date") is not False
        or correction.get("credit_collateral_when_availability_missing") is not False
    ):
        raise ValueError("macro source V3 parser-only correction changed")
    dependency_hashes: dict[str, str] = {}
    for relative, expected_sha in dependencies.items():
        dependency_path = v1._project_path(str(relative))
        digest = str(expected_sha).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"macro source V3 dependency SHA drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return MacroSourceV3Protocol(
        config_path=path,
        config_sha256=actual_sha,
        parent=parent,
        output_directory=v1._project_path(str(output["directory"])),
        dependency_hashes=dependency_hashes,
        expected_ruonia_rows=expected[0],
        expected_explicit_publication_rows=expected[1],
        expected_unknown_publication_rows=expected[2],
    )


def parse_ruonia_preserving_unknown(
    content: bytes,
    protocol: MacroSourceV3Protocol,
) -> pd.DataFrame:
    """Parse all official rows but never infer unavailable historical publication dates."""
    try:
        html = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("historical RUONIA HTML is not UTF-8") from error
    parser = info_radar._CbrTableParser()
    parser.feed(html)
    if len(parser.tables) != 1:
        raise ValueError("historical RUONIA HTML must contain one data table")
    rows = parser.tables[0]
    if len(rows) < 2 or len(rows[0]) != 11:
        raise ValueError("historical RUONIA table schema drifted")
    normalized: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) != 11:
            raise ValueError("historical RUONIA row does not have 11 columns")
        effective = datetime.strptime(row[0], "%d.%m.%Y").date()
        raw_publication = row[10].strip()
        if DATE_PATTERN.fullmatch(raw_publication):
            publication = datetime.strptime(raw_publication, "%d.%m.%Y").date()
            if publication < effective:
                raise ValueError("RUONIA publication date precedes observation")
            available_at: Any = info_radar._calendar_lag_available_at(publication, 1)
            availability_rule = "publication_date_plus_one_calendar_day"
        elif raw_publication in UNKNOWN_PUBLICATION_MARKERS:
            publication = None
            available_at = pd.NaT
            availability_rule = "publication_date_unavailable_no_inference"
        else:
            raise ValueError(f"unknown historical RUONIA publication marker: {raw_publication}")
        # Validate every official numeric field even though only the rate enters the
        # normalized monetary table.
        for index, label in (
            (2, "volume"),
            (3, "transactions"),
            (4, "participants"),
            (5, "min_rate"),
            (6, "p25_rate"),
            (7, "p75_rate"),
            (8, "max_rate"),
        ):
            info_radar._optional_decimal_number(row[index], label)
        normalized.append(
            {
                "source": "cbr",
                "series_id": "ruonia",
                "observation_date": pd.Timestamp(effective),
                "publication_date": (
                    pd.NaT if publication is None else pd.Timestamp(publication)
                ),
                "available_at": available_at,
                "value": info_radar._decimal_number(row[1], "ruonia"),
                "availability_rule": availability_rule,
            }
        )
    frame = pd.DataFrame(normalized).sort_values("observation_date", ignore_index=True)
    if frame["observation_date"].duplicated().any():
        raise ValueError("historical RUONIA has duplicate observation dates")
    explicit = int(frame["publication_date"].notna().sum())
    unknown = int(frame["publication_date"].isna().sum())
    if (len(frame), explicit, unknown) != (
        protocol.expected_ruonia_rows,
        protocol.expected_explicit_publication_rows,
        protocol.expected_unknown_publication_rows,
    ):
        raise ValueError("historical RUONIA exact source-only counts changed")
    return frame


def parse_monetary(
    ruonia_content: bytes,
    key_rate_content: bytes,
    protocol: MacroSourceV3Protocol,
) -> pd.DataFrame:
    ruonia = parse_ruonia_preserving_unknown(ruonia_content, protocol)
    key_rate = info_radar.parse_cbr_key_rate_xml(key_rate_content).loc[
        :, v1.MONETARY_COLUMNS
    ]
    key_rate["observation_date"] = pd.to_datetime(
        key_rate["observation_date"], errors="raise"
    ).dt.normalize()
    key_rate["publication_date"] = pd.to_datetime(
        key_rate["publication_date"], errors="coerce"
    ).dt.normalize()
    key_rate["available_at"] = pd.to_datetime(key_rate["available_at"], errors="raise", utc=True)
    if (
        key_rate["observation_date"].dt.date.lt(protocol.source_start).any()
        or key_rate["observation_date"].dt.date.gt(protocol.source_end).any()
    ):
        raise ValueError("CBR key rate ignored bounded dates")
    protected = pd.Timestamp(protocol.protected_from, tz=v1.MOSCOW).tz_convert("UTC")
    key_rate = key_rate.loc[key_rate["available_at"].lt(protected)]
    ruonia["available_at"] = pd.to_datetime(ruonia["available_at"], errors="coerce", utc=True)
    explicit_future = ruonia["available_at"].notna() & ruonia["available_at"].ge(protected)
    if explicit_future.any():
        raise ValueError("explicit RUONIA availability crosses protected 2018")
    combined = pd.concat([key_rate, ruonia], ignore_index=True)
    combined["value"] = pd.to_numeric(combined["value"], errors="raise").astype(float)
    if (
        combined.duplicated(["series_id", "observation_date"]).any()
        or combined["value"].isna().any()
        or not combined["value"].gt(0.0).all()
    ):
        raise ValueError("historical monetary rows are duplicate, missing, or nonpositive")
    return combined.sort_values(
        ["series_id", "observation_date"], kind="mergesort", ignore_index=True
    )


def collect(
    protocol: MacroSourceV3Protocol,
    *,
    session: v1.SessionLike | None = None,
    retrieved_at_utc: str | None = None,
) -> v1.MacroSourceTables:
    """Fetch the unchanged S2 requests and apply only the sealed RUONIA missing policy."""
    retrieved = retrieved_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    retrieved_timestamp = pd.Timestamp(retrieved)
    if retrieved_timestamp.tzinfo is None:
        raise ValueError("macro source V3 retrieval timestamp must be timezone-aware")
    retrieved_timestamp = retrieved_timestamp.tz_convert("UTC")
    transport = session if session is not None else v2.CurlCompatibleSession()
    fred = v1._fetch(
        transport,
        kind="fred_stlfsi4_csv",
        method="GET",
        url=v1.fred_url(protocol),
        retrieved_at_utc=retrieved,
    )
    ruonia = v1._fetch(
        transport,
        kind="cbr_ruonia_html",
        method="GET",
        url=info_radar.build_cbr_ruonia_url(protocol.source_start, protocol.source_end),
        retrieved_at_utc=retrieved,
    )
    key_body = info_radar.build_cbr_key_rate_soap(protocol.source_start, protocol.source_end)
    key_rate = v1._fetch(
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
    stlfsi = v1.parse_stlfsi(fred.content, protocol)
    stlfsi["retrieved_at_utc"] = pd.Series(
        [retrieved_timestamp] * len(stlfsi), dtype="datetime64[ms, UTC]"
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
        raise ValueError("pre-2018 macro V3 minimum coverage failed")
    coverage_rows: list[dict[str, Any]] = [
        {
            "series_id": v1.FRED_SERIES,
            "rows": len(stlfsi),
            "complete_rows": int(stlfsi["complete"].sum()),
            "available_at_rows": int(stlfsi["available_at"].notna().sum()),
            "unknown_available_at_rows": int(stlfsi["available_at"].isna().sum()),
            "minimum_observation_date": stlfsi["observation_date"].min(),
            "maximum_observation_date": stlfsi["observation_date"].max(),
        }
    ]
    for series_id, group in monetary.groupby("series_id", sort=True):
        coverage_rows.append(
            {
                "series_id": series_id,
                "rows": len(group),
                "complete_rows": len(group),
                "available_at_rows": int(group["available_at"].notna().sum()),
                "unknown_available_at_rows": int(group["available_at"].isna().sum()),
                "minimum_observation_date": group["observation_date"].min(),
                "maximum_observation_date": group["observation_date"].max(),
            }
        )
    coverage = pd.DataFrame(coverage_rows)
    return v1.MacroSourceTables(stlfsi, monetary, coverage, (fred, ruonia, key_rate))


def persist(protocol: MacroSourceV3Protocol, tables: v1.MacroSourceTables) -> Path:
    """Publish immutable S3 source with explicit unknown RUONIA timing coverage."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"pre-2018 macro V3 output already exists: {final}")
    expected_kinds = (
        "fred_stlfsi4_csv",
        "cbr_ruonia_html",
        "cbr_key_rate_soap_xml",
    )
    if tuple(response.kind for response in tables.responses) != expected_kinds:
        raise ValueError("macro V3 requires exactly the three sealed official responses")
    frames = {
        "stlfsi4": tables.stlfsi,
        "cbr_monetary": tables.monetary,
        "coverage": tables.coverage,
    }
    v1._assert_source_only_schema(frames)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            frame.to_parquet(path, index=False, compression="zstd")
            artifacts[name] = v1._artifact(path, frame)
        raw_path = temporary / "official_macro_responses.jsonl.gz"
        atomic_write_bytes(raw_path, v1._raw_archive(tables.responses))
        artifacts["raw_archive"] = {
            **v1._artifact(raw_path),
            "records": len(tables.responses),
        }
        states = tables.stlfsi["stress_state"].value_counts()
        counts = tables.monetary["series_id"].value_counts()
        ruonia = tables.monetary.loc[tables.monetary["series_id"].eq("ruonia")]
        key_rate = tables.monetary.loc[tables.monetary["series_id"].eq("key_rate")]
        manifest_core = {
            "schema_version": 3,
            "source_id": "official-pre2018-stlfsi4-cbr-monetary-current-vintage-v3",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "lineage": {
                "S1_protocol_sha256": protocol.parent.parent.config_sha256,
                "S1_output_published": False,
                "S2_protocol_sha256": protocol.parent.config_sha256,
                "S2_output_published": False,
                "market_outcomes_observed_before_S3": False,
            },
            "transport": {"user_agent": v2.CURL_USER_AGENT},
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
                "stlfsi_above_average_rows": int(states.get("above_average", 0)),
                "stlfsi_normal_or_below_rows": int(states.get("normal_or_below", 0)),
                "ruonia_rows": int(counts.get("ruonia", 0)),
                "ruonia_explicit_publication_rows": int(ruonia["publication_date"].notna().sum()),
                "ruonia_unknown_publication_rows": int(ruonia["publication_date"].isna().sum()),
                "key_rate_rows": int(counts.get("key_rate", 0)),
                "key_rate_minimum_percent": float(key_rate["value"].min()),
                "key_rate_maximum_percent": float(key_rate["value"].max()),
            },
            "temporal_semantics": {
                "STLFSI4_available_at": (
                    "Thursday 23:59:59 America/Chicago six calendar days after Friday"
                ),
                "RUONIA_explicit_available_at": (
                    "publication_date_plus_one_calendar_day_Moscow"
                ),
                "RUONIA_unknown_publication": "available_at_missing_no_inference_no_credit",
                "key_rate_available_at": "effective_date_plus_one_calendar_day_Moscow",
                "every_nonmissing_processed_available_at_before_2018": True,
                "admissible_join": "latest available_at less than or equal to decision_at",
                "missing_values_preserved": True,
                "contains_MOEX_prices_returns_targets_labels_or_pnl": False,
            },
            "limitations": {
                "STLFSI4_current_vintage": True,
                "STLFSI4_original_historical_vintages_proved": False,
                "RUONIA_historical_publication_date_missing_for_most_rows": True,
                "RUONIA_missing_timing_collateral_credit_allowed": False,
                "CBR_exact_intraday_publication_timestamp": False,
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
        identity = v1.sha256_bytes(v1._canonical_json(manifest_core))
        write_json(manifest_path, {**manifest_core, "manifest_payload_sha256": identity})
        manifest_sha = v1.sha256_file(manifest_path)
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
