"""Retry the sealed pre-2018 macro source with a FRED-compatible transport identity."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import requests
import yaml

from market_lab.futures import pre2018_macro_source as v1
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/pre2018_macro_source_v2.yaml"
CURL_USER_AGENT: Final[str] = "curl/8.10.1"


@dataclass(frozen=True, slots=True)
class MacroSourceV2Protocol:
    """Transport-only S2 correction inheriting every S1 source rule."""

    config_path: Path
    config_sha256: str
    parent: v1.MacroSourceProtocol
    output_directory: Path
    dependency_hashes: dict[str, str]

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


class CurlCompatibleSession:
    """Preserve every request field except the transport identity rejected by FRED."""

    def __init__(self, inner: v1.SessionLike | None = None) -> None:
        self.inner = inner or requests.Session()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        data: bytes | None = None,
    ) -> v1.ResponseLike:
        corrected = dict(headers)
        corrected["User-Agent"] = CURL_USER_AGENT
        return self.inner.request(
            method,
            url,
            headers=corrected,
            timeout=timeout,
            data=data,
        )


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> MacroSourceV2Protocol:
    """Verify S2 and its complete S1 inheritance before any HTTP request."""
    path = config_path.resolve()
    actual_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("macro source V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("macro source V2 protocol must be a YAML object")
    if payload.get("protocol_id") != "pre2018_macro_source_v2":
        raise ValueError("unexpected macro source V2 protocol id")
    if payload.get("scope") != "source_only_no_market_outcomes":
        raise ValueError("macro source V2 protocol is not source-only")
    parent_record = payload.get("parent_S1_protocol")
    failure = payload.get("failed_S1_transport_attempt")
    transport = payload.get("transport_correction")
    output = payload.get("output")
    dependencies = payload.get("implementation_dependencies")
    if not all(
        isinstance(item, Mapping)
        for item in (parent_record, failure, transport, output, dependencies)
    ):
        raise ValueError("macro source V2 protocol has an invalid section")
    assert isinstance(parent_record, Mapping)
    assert isinstance(failure, Mapping)
    assert isinstance(transport, Mapping)
    assert isinstance(output, Mapping)
    assert isinstance(dependencies, Mapping)
    parent = v1.load_protocol(v1._project_path(str(parent_record["path"])))
    if parent.config_sha256 != str(parent_record["sha256"]).lower():
        raise ValueError("macro source V2 parent S1 identity mismatch")
    if (
        failure.get("output_published") is not False
        or failure.get("official_response_bytes_persisted") is not False
        or failure.get("market_outcomes_observed") is not False
        or transport.get("only_changed_field") != "HTTP_User_Agent"
        or transport.get("S1_user_agent")
        != "market-lab-research/pre2018-macro-source-v1"
        or transport.get("S2_user_agent") != CURL_USER_AGENT
    ):
        raise ValueError("macro source V2 transport-only correction changed")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = v1._project_path(str(relative))
        digest = str(expected).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"macro source V2 dependency SHA drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return MacroSourceV2Protocol(
        config_path=path,
        config_sha256=actual_sha,
        parent=parent,
        output_directory=v1._project_path(str(output["directory"])),
        dependency_hashes=dependency_hashes,
    )


def collect(
    protocol: MacroSourceV2Protocol,
    *,
    session: v1.SessionLike | None = None,
    retrieved_at_utc: str | None = None,
) -> v1.MacroSourceTables:
    """Run the unchanged S1 collector with only the sealed transport identity correction."""
    transport = session if session is not None else CurlCompatibleSession()
    return v1.collect(protocol, session=transport, retrieved_at_utc=retrieved_at_utc)


def persist(protocol: MacroSourceV2Protocol, tables: v1.MacroSourceTables) -> Path:
    """Publish immutable S2 artifacts with explicit failed-S1 lineage."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"pre-2018 macro V2 output already exists: {final}")
    expected_kinds = (
        "fred_stlfsi4_csv",
        "cbr_ruonia_html",
        "cbr_key_rate_soap_xml",
    )
    if tuple(response.kind for response in tables.responses) != expected_kinds:
        raise ValueError("macro V2 requires exactly the three sealed official responses")
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
        state_counts = tables.stlfsi["stress_state"].value_counts()
        monetary_counts = tables.monetary["series_id"].value_counts()
        key_rate = tables.monetary.loc[
            tables.monetary["series_id"].eq("key_rate"), "value"
        ]
        manifest_core = {
            "schema_version": 2,
            "source_id": "official-pre2018-stlfsi4-cbr-monetary-current-vintage-v2",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
            },
            "parent_S1": {
                "protocol_sha256": protocol.parent.config_sha256,
                "output_published": False,
                "failure": "FRED_read_timeout_for_research_User_Agent",
                "market_outcomes_observed": False,
            },
            "transport_correction": {
                "only_changed_field": "HTTP_User_Agent",
                "user_agent": CURL_USER_AGENT,
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
                "key_rate_minimum_percent": float(key_rate.min()),
                "key_rate_maximum_percent": float(key_rate.max()),
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
