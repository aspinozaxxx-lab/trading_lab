"""Collect and replay-audit dividend-stock MOEX calendar-spread history."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import yaml

from market_lab.futures import moex_calendar_spread_source as base
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_dividend_calendar_spread_source_v1.yaml"
CONFIG_SHA256: Final[str] = "ad9a300811a0ef42abe740fa64c4eb793ae501ab1edff9ae554ce52fdd896936"
SOURCE_START: Final[date] = date(2023, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[date] = date(2026, 1, 1)
ASSETS: Final[tuple[str, ...]] = ("GAZR", "SBRF", "ROSN", "TATN", "NOTK")
ASSET_CODES: Final[dict[str, str]] = {asset: asset for asset in ASSETS}
SECURITY_PREFIXES: Final[dict[str, str]] = {
    "GAZR": "GZ",
    "SBRF": "SR",
    "ROSN": "RN",
    "TATN": "TT",
    "NOTK": "NK",
}
EXPECTED_SPREAD_COUNTS: Final[dict[str, int]] = {
    "GAZR": 10,
    "SBRF": 10,
    "ROSN": 10,
    "TATN": 12,
    "NOTK": 11,
}
EXPECTED_MISSING_DATE_SPREADS: Final[dict[str, tuple[str, ...]]] = {asset: () for asset in ASSETS}
EXPECTED_REGULAR_ADJACENT_COUNTS: Final[dict[str, int]] = dict(EXPECTED_SPREAD_COUNTS)
EXPECTED_NEAR_DATE_MATCH_COUNTS: Final[dict[str, int]] = dict(EXPECTED_SPREAD_COUNTS)
RMS_FILES: Final[dict[str, str]] = {
    "configs/moex_rms_historical_pit_source_v4.yaml": (
        "83bcabed33afccbdb92ca3a1dbdc3f00e6d7ab71134a9d4e1c3ef1d93f51e5ae"
    ),
    "src/market_lab/futures/moex_rms_historical_pit_source.py": (
        "0411f83b21e0b3de63ab90fb3b2780c4fc57fd596a2a64a5f299057a642a1133"
    ),
    "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/manifest.json": (
        "e88360d3f1a3476e3e34a67b947fb7aa1a656a2c290aa46e27add84dd397b2e3"
    ),
    "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/audit.json": (
        "013c6e234521fc5d6eebf143bddb3c35392251c414dc014e749f672b8726824c"
    ),
    "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/cashflow.parquet": (
        "be7f9a32bf2b085edb01df4cee8d3a895be10b182e9708fd5e033616dfefad19"
    ),
}


@dataclass(frozen=True, slots=True)
class DividendAssetSpec:
    """Minimal validated asset declaration accepted by the shared ISS routes."""

    asset_code: str
    logical_symbol: str
    security_prefix: str
    engine: str = "futures"
    market: str = "forts"
    primary_board: str = "RFUD"
    timezone: str = "Europe/Moscow"

    @classmethod
    def from_symbol(cls, logical_symbol: str) -> DividendAssetSpec:
        key = logical_symbol.upper()
        if key not in ASSETS:
            raise ValueError(f"unknown dividend-stock futures asset: {logical_symbol}")
        return cls(ASSET_CODES[key], key, SECURITY_PREFIXES[key])


def _safe_project_path(value: str, required_root: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe dividend-spread path: {value}")
    if relative.parts[0].lower() != required_root.lower():
        raise ValueError(f"dividend-spread path must start with {required_root}")
    return PROJECT_ROOT / relative


def load_protocol(
    config_path: Path = DEFAULT_CONFIG,
) -> base.CalendarSpreadSourceProtocol:
    """Verify the pre-price source seal and all pinned RMS cashflow artifacts."""
    path = config_path.resolve()
    actual_sha = base.sha256_file(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("dividend calendar-spread protocol must be a YAML object")
    period = payload.get("period", {})
    universe = payload.get("universe", {})
    preflight = payload.get("metadata_preflight", {})
    output = payload.get("output", {})
    expected_counts = {
        str(key): int(value)
        for key, value in preflight.get("exact_dated_spread_counts", {}).items()
    }
    if (
        actual_sha != CONFIG_SHA256
        or payload.get("protocol_id") != "moex_dividend_calendar_spread_source_v1"
        or payload.get("scope") != "source_only_no_returns_targets_signals_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or date.fromisoformat(str(period.get("start"))) != SOURCE_START
        or date.fromisoformat(str(period.get("end"))) != SOURCE_END
        or date.fromisoformat(str(period.get("protected_from"))) != PROTECTED_FROM
        or tuple(universe.get("logical_assets", ())) != ASSETS
        or universe.get("official_asset_codes") != ASSET_CODES
        or universe.get("security_prefixes") != SECURITY_PREFIXES
        or expected_counts != EXPECTED_SPREAD_COUNTS
        or int(preflight.get("exact_total_dated_spreads", -1))
        != sum(EXPECTED_SPREAD_COUNTS.values())
        or preflight.get("all_53_selected_archive_codes_present") is not True
        or output.get("immutable") is not True
        or output.get("contents_in_git") is not False
        or SOURCE_END >= PROTECTED_FROM
    ):
        raise ValueError("dividend calendar-spread source protocol drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in RMS_FILES.items():
        artifact = PROJECT_ROOT / relative
        if base.sha256_file(artifact) != expected:
            raise ValueError(f"pinned RMS cashflow artifact drifted: {relative}")
        dependency_hashes[relative] = expected
    shared_relative = "src/market_lab/futures/moex_calendar_spread_source.py"
    adapter_relative = "src/market_lab/futures/moex_dividend_calendar_spread_source.py"
    dependency_hashes[shared_relative] = base.sha256_file(PROJECT_ROOT / shared_relative)
    dependency_hashes[adapter_relative] = base.sha256_file(PROJECT_ROOT / adapter_relative)
    return base.CalendarSpreadSourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        payload=payload,
        output_directory=_safe_project_path(str(output["directory"]), "data"),
        dependency_hashes=dependency_hashes,
    )


@contextmanager
def _dividend_registry() -> Iterator[None]:
    original_discover = base.discover_spreads

    def discover_in_sealed_period(
        payload: dict[str, Any],
        asset: DividendAssetSpec,
        source_start: date = SOURCE_START,
        source_end: date = SOURCE_END,
    ) -> Any:
        return original_discover(payload, asset, source_start, source_end)

    names = {
        "SOURCE_START": SOURCE_START,
        "SOURCE_END": SOURCE_END,
        "PROTECTED_FROM": PROTECTED_FROM,
        "ASSETS": ASSETS,
        "EXPECTED_SPREAD_COUNTS": EXPECTED_SPREAD_COUNTS,
        "EXPECTED_MISSING_DATE_SPREADS": EXPECTED_MISSING_DATE_SPREADS,
        "EXPECTED_REGULAR_ADJACENT_COUNTS": EXPECTED_REGULAR_ADJACENT_COUNTS,
        "EXPECTED_NEAR_DATE_MATCH_COUNTS": EXPECTED_NEAR_DATE_MATCH_COUNTS,
        "FuturesAssetSpec": DividendAssetSpec,
        "discover_spreads": discover_in_sealed_period,
        "FORBIDDEN_OUTPUT_FRAGMENTS": (
            *base.FORBIDDEN_OUTPUT_FRAGMENTS,
            "prediction",
        ),
    }
    previous = {name: getattr(base, name) for name in names}
    try:
        for name, value in names.items():
            setattr(base, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(base, name, value)


def collect_dividend_spreads(
    protocol: base.CalendarSpreadSourceProtocol,
    client: base.OfficialMoexClient | None = None,
) -> Path:
    """Collect through the shared fail-closed implementation, then publish atomically."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"dividend calendar-spread output exists: {final}")
    stage = final.with_name(f".{final.name}.adapter-{os.getpid()}")
    if stage.exists():
        raise FileExistsError(f"dividend calendar-spread stage exists: {stage}")
    staged_protocol = base.CalendarSpreadSourceProtocol(
        config_path=protocol.config_path,
        config_sha256=protocol.config_sha256,
        payload=protocol.payload,
        output_directory=stage,
        dependency_hashes=protocol.dependency_hashes,
    )
    try:
        with _dividend_registry():
            base.collect_calendar_spreads(staged_protocol, client=client)
        manifest_path = stage / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest.update(
            {
                "bundle_id": "moex-dividend-calendar-spreads-2023-2025-v1",
                "source": (
                    "official MOEX ISS and public calendar-spread archive, "
                    "joined only by sealed identities to pinned RMS cashflow"
                ),
                "contains_returns_targets_labels_signals_predictions_equity_or_pnl": False,
                "cashflow_source": {
                    "root": protocol.payload["cashflow_source"]["root"],
                    "cashflow_sha256": protocol.payload["cashflow_source"]["cashflow_sha256"],
                },
            }
        )
        write_json(manifest_path, manifest)
        sidecar = f"{base.sha256_file(manifest_path)}  manifest.json\n"
        atomic_write_bytes(stage / "manifest.sha256", sidecar.encode("utf-8-sig"))
        stage.replace(final)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return final


def audit_bundle(protocol: base.CalendarSpreadSourceProtocol) -> base.SourceAudit:
    """Replay every raw response and add dividend-family identity checks."""
    with _dividend_registry():
        result = base.audit_bundle(protocol)
    manifest = json.loads(
        (protocol.output_directory / "manifest.json").read_text(encoding="utf-8-sig")
    )
    checks = dict(result.checks)
    checks.update(
        {
            "dividend_bundle_identity_exact": manifest.get("bundle_id")
            == "moex-dividend-calendar-spreads-2023-2025-v1",
            "broad_outcome_absence_declared": manifest.get(
                "contains_returns_targets_labels_signals_predictions_equity_or_pnl"
            )
            is False,
            "cashflow_sha_exact": manifest.get("cashflow_source", {}).get("cashflow_sha256")
            == RMS_FILES[
                "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/cashflow.parquet"
            ],
            "all_53_spreads_exact": result.counts["spreads"] == 53,
        }
    )
    if not all(checks.values()):
        raise ValueError(f"dividend calendar-spread audit failed: {checks}")
    return base.SourceAudit(checks=checks, counts=result.counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol(arguments.config)
    if not arguments.audit_only:
        print(collect_dividend_spreads(protocol))
    audit = audit_bundle(protocol)
    print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
