"""Parser-only V2 correction for the sealed MOEX calendar-spread source."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_calendar_spread_source as v1

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_calendar_spread_source_v2.yaml"
)
PARENT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_calendar_spread_source.yaml"
PARENT_CONFIG_SHA256: Final[str] = (
    "7268753933efb4c9633f3e314ebc1d67cf4a7d63e4290e0f3a0142bacce8048e"
)
PARENT_IMPLEMENTATION_SHA256: Final[str] = (
    "db2174889a4fc3baa08e39bfa4685b7cfdaaf01adf370760b27546b5ef5c261d"
)
_PARENT_PARSE = v1.parse_spread_history_page


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar-spread V2 {label} must be a mapping")
    return value


def load_protocol(
    config_path: Path = DEFAULT_CONFIG,
) -> v1.CalendarSpreadSourceProtocol:
    """Verify the V2 delta, its parent seal and every pinned implementation byte."""
    path = config_path.resolve()
    actual_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("calendar-spread V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar-spread V2 protocol must be a YAML object")
    parent = _mapping(payload.get("parent_protocol"), "parent protocol")
    failure = _mapping(payload.get("observed_v1_failure"), "V1 failure")
    correction = _mapping(payload.get("parser_only_correction"), "correction")
    period = _mapping(payload.get("period"), "period")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(
        payload.get("implementation_dependencies"), "dependencies"
    )
    if (
        payload.get("protocol_id") != "moex_calendar_spread_source_v2"
        or payload.get("scope") != "source_only_no_returns_targets_or_pnl"
        or payload.get("sealed_before_resumed_bulk_history") is not True
        or payload.get("live_trading_allowed") is not False
        or parent.get("config") != "configs/moex_calendar_spread_source.yaml"
        or parent.get("config_sha256") != PARENT_CONFIG_SHA256
        or parent.get("implementation_sha256") != PARENT_IMPLEMENTATION_SHA256
        or failure.get("canonical_output_created") is not False
        or failure.get("exception")
        != "calendar-spread history returned another asset code"
        or failure.get("logical_asset") != "SI"
        or failure.get("secid") != "SiZ5SiH6"
        or tuple(failure.get("returned_assetcode_classes", ()))
        != ("null", "empty_string")
        or correction.get("only_change")
        != "strip_blank_ASSETCODE_to_missing_before_parent_parser"
        or correction.get("raw_payload_mutated") is not False
        or correction.get("nonblank_mismatch_policy") != "reject_unchanged"
        or correction.get("all_other_parent_rules") != "byte_identical"
        or date.fromisoformat(str(period["start"])) != v1.SOURCE_START
        or date.fromisoformat(str(period["end"])) != v1.SOURCE_END
        or date.fromisoformat(str(period["protected_from"])) != v1.PROTECTED_FROM
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar-spread V2 protocol invariants drifted")
    parent_protocol = v1.load_protocol(PARENT_CONFIG)
    if parent_protocol.config_sha256 != PARENT_CONFIG_SHA256:
        raise ValueError("calendar-spread V2 parent config drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"calendar-spread V2 dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    output_directory = v1._project_path(str(output["directory"]), "data")
    if output_directory == parent_protocol.output_directory:
        raise ValueError("calendar-spread V2 must not overwrite V1 output")
    return v1.CalendarSpreadSourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        payload=payload,
        output_directory=output_directory,
        dependency_hashes=dependency_hashes,
    )


def _normalize_blank_assetcode(payload: dict[str, Any]) -> dict[str, Any]:
    history = _mapping(payload.get("history"), "history block")
    columns = history.get("columns")
    rows = history.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("calendar-spread V2 history block drifted")
    matches = [
        index
        for index, column in enumerate(columns)
        if str(column).lower() == "assetcode"
    ]
    if len(matches) != 1:
        raise ValueError("calendar-spread V2 requires one ASSETCODE column")
    asset_index = matches[0]
    normalized_rows: list[list[Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, list) or len(raw_row) != len(columns):
            raise ValueError("calendar-spread V2 history row width drifted")
        row = list(raw_row)
        value = row[asset_index]
        if isinstance(value, str) and not value.strip():
            row[asset_index] = None
        normalized_rows.append(row)
    normalized_history = dict(history)
    normalized_history["data"] = normalized_rows
    normalized_payload = dict(payload)
    normalized_payload["history"] = normalized_history
    return normalized_payload


def parse_spread_history_page(
    payload: dict[str, Any],
    catalog_row: Mapping[str, Any],
) -> tuple[pd.DataFrame, Any]:
    """Normalize only blank ASSETCODE while retaining the exact raw response."""
    normalized = _normalize_blank_assetcode(payload)
    return _PARENT_PARSE(normalized, catalog_row)


@contextmanager
def _patched_parent_parser() -> Iterator[None]:
    original = v1.parse_spread_history_page
    v1.parse_spread_history_page = parse_spread_history_page
    try:
        yield
    finally:
        v1.parse_spread_history_page = original


def collect_calendar_spreads(
    protocol: v1.CalendarSpreadSourceProtocol,
    client: v1.OfficialMoexClient | None = None,
) -> Path:
    """Run the byte-identical V1 collector under the one sealed parser correction."""
    with _patched_parent_parser():
        return v1.collect_calendar_spreads(protocol, client)


def audit_bundle(protocol: v1.CalendarSpreadSourceProtocol) -> v1.SourceAudit:
    """Replay V2 raw responses using the same isolated parser correction."""
    with _patched_parent_parser():
        return v1.audit_bundle(protocol)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol(arguments.config)
    if arguments.audit_only:
        audit = audit_bundle(protocol)
        print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
        return 0
    output = collect_calendar_spreads(protocol)
    audit = audit_bundle(protocol)
    print(output)
    print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
