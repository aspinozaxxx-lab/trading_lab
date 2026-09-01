"""V3 collection correction for one exact empty RFUD interval."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_calendar_spread_source as v1
from market_lab.futures import moex_calendar_spread_source_v2 as v2
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_calendar_spread_source_v3.yaml"
)
PARENT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_calendar_spread_source_v2.yaml"
)
PARENT_CONFIG_SHA256: Final[str] = (
    "be770102469677a3d5b88c79e976799298072aa77c45c405b31387a9fb809173"
)
PARENT_IMPLEMENTATION_SHA256: Final[str] = (
    "d0c865a45369e13bf118842d045f32fd58d0188879e987986b1ce9bfbad1e30d"
)
EXPECTED_EMPTY_ISS_SECID: Final[str] = "BRF1BRG1"
EXPECTED_EMPTY_ISS_SPREAD_ID: Final[str] = (
    "BR:BRF1BRG1:2020-12-31:2021-02-01"
)
EXPECTED_EMPTY_ISS_ARCHIVE_CODE: Final[str] = "BR-1.21-2.21"
EXPECTED_EMPTY_ISS_FROM: Final[date] = date(2021, 1, 1)
EXPECTED_EMPTY_ISS_TILL: Final[date] = date(2020, 12, 30)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar-spread V3 {label} must be a mapping")
    return value


def load_protocol(
    config_path: Path = DEFAULT_CONFIG,
) -> v1.CalendarSpreadSourceProtocol:
    """Verify the exact V3 operational delta and both immutable parent seals."""
    path = config_path.resolve()
    actual_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("calendar-spread V3 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar-spread V3 protocol must be a YAML object")
    parent = _mapping(payload.get("parent_protocol"), "parent protocol")
    failure = _mapping(payload.get("observed_v2_failure"), "V2 failure")
    correction = _mapping(payload.get("collection_only_correction"), "correction")
    period = _mapping(payload.get("period"), "period")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(
        payload.get("implementation_dependencies"), "dependencies"
    )
    if (
        payload.get("protocol_id") != "moex_calendar_spread_source_v3"
        or payload.get("scope") != "source_only_no_returns_targets_or_pnl"
        or payload.get("sealed_before_resumed_bulk_history") is not True
        or payload.get("live_trading_allowed") is not False
        or parent.get("config") != "configs/moex_calendar_spread_source_v2.yaml"
        or parent.get("config_sha256") != PARENT_CONFIG_SHA256
        or parent.get("implementation_sha256") != PARENT_IMPLEMENTATION_SHA256
        or failure.get("canonical_output_created") is not False
        or failure.get("exception")
        != f"empty calendar-spread ISS interval: {EXPECTED_EMPTY_ISS_SPREAD_ID}"
        or int(failure.get("exact_empty_interval_count", -1)) != 1
        or tuple(failure.get("exact_empty_interval_secids", ()))
        != (EXPECTED_EMPTY_ISS_SECID,)
        or correction.get("only_change")
        != "skip_ISS_request_for_exact_declared_empty_interval"
        or correction.get("public_archive_collection") != "unchanged_required"
        or correction.get("catalog_board_dates_mutated") is not False
        or correction.get("unexpected_empty_interval_policy") != "reject"
        or correction.get("all_other_parent_rules") != "byte_identical"
        or date.fromisoformat(str(period["start"])) != v1.SOURCE_START
        or date.fromisoformat(str(period["end"])) != v1.SOURCE_END
        or date.fromisoformat(str(period["protected_from"])) != v1.PROTECTED_FROM
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar-spread V3 protocol invariants drifted")
    parent_protocol = v2.load_protocol(PARENT_CONFIG)
    if parent_protocol.config_sha256 != PARENT_CONFIG_SHA256:
        raise ValueError("calendar-spread V3 parent config drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"calendar-spread V3 dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    output_directory = v1._project_path(str(output["directory"]), "data")
    if output_directory in {
        parent_protocol.output_directory,
        v1.load_protocol().output_directory,
    }:
        raise ValueError("calendar-spread V3 must not overwrite a parent output")
    return v1.CalendarSpreadSourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        payload=payload,
        output_directory=output_directory,
        dependency_hashes=dependency_hashes,
    )


def _is_exact_declared_empty_interval(
    row: Mapping[str, Any],
    request_from: date,
    request_till: date,
) -> bool:
    return bool(
        str(row["logical_asset"]) == "BR"
        and str(row["secid"]) == EXPECTED_EMPTY_ISS_SECID
        and str(row["spread_id"]) == EXPECTED_EMPTY_ISS_SPREAD_ID
        and str(row["archive_code"]) == EXPECTED_EMPTY_ISS_ARCHIVE_CODE
        and request_from == EXPECTED_EMPTY_ISS_FROM
        and request_till == EXPECTED_EMPTY_ISS_TILL
        and pd.Timestamp(row["series_start"]).date() == date(2020, 12, 14)
        and pd.Timestamp(row["spread_last_trade"]).date() == date(2021, 1, 4)
        and pd.Timestamp(row["board_history_from"]).date() == date(2020, 12, 14)
        and pd.Timestamp(row["board_history_till"]).date() == date(2020, 12, 30)
    )


def _collect_calendar_spreads(
    protocol: v1.CalendarSpreadSourceProtocol,
    client: v1.OfficialMoexClient | None = None,
) -> Path:
    """Collect V1/V2 bytes while allowing one exact declared empty ISS interval."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"calendar-spread V3 output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    own_client = client is None
    active_client = client or v1.OfficialMoexClient()
    raw_records: list[v1.RawRecord] = []
    catalog_frames: list[pd.DataFrame] = []
    iss_daily_frames: list[pd.DataFrame] = []
    archive_daily_frames: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    empty_iss_spreads: list[str] = []
    try:
        for logical_asset in v1.ASSETS:
            asset = FuturesAssetSpec.from_symbol(logical_asset)
            archive_list_payload = active_client.post_json(
                v1.ARCHIVE_LIST_URL,
                {
                    "knownCategoryValues": f"Basis:{asset.asset_code};",
                    "category": "Spread",
                },
            )
            archive_codes = set(v1.parse_archive_spread_list(archive_list_payload))
            raw_records.append(
                v1._raw_record(
                    kind="archive_spread_list",
                    asset=asset,
                    url=v1.ARCHIVE_LIST_URL,
                    payload=archive_list_payload,
                )
            )
            series_url = iss.futures_series_url(asset)
            series_payload = active_client.get_json(series_url)
            raw_records.append(
                v1._raw_record(
                    kind="series",
                    asset=asset,
                    url=series_url,
                    payload=series_payload,
                )
            )
            discovered = v1.discover_spreads(series_payload, asset)
            if len(discovered) != v1.EXPECTED_SPREAD_COUNTS[logical_asset]:
                raise ValueError(f"calendar-spread V3 count drift for {logical_asset}")
            if (
                int(discovered["regular_adjacent_expiry"].sum())
                != v1.EXPECTED_REGULAR_ADJACENT_COUNTS[logical_asset]
                or int(discovered["near_expiration_matches_spread_last_trade"].sum())
                != v1.EXPECTED_NEAR_DATE_MATCH_COUNTS[logical_asset]
            ):
                raise ValueError(f"calendar-spread V3 metadata drift for {logical_asset}")
            missing_archive_codes = set(discovered["archive_code"]) - archive_codes
            if missing_archive_codes:
                raise ValueError(
                    f"calendar-spread V3 archive mapping missing: "
                    f"{sorted(missing_archive_codes)}"
                )
            enriched_rows: list[dict[str, Any]] = []
            for discovered_row in discovered.to_dict("records"):
                board_url = iss.futures_boards_url(str(discovered_row["secid"]))
                board_payload = active_client.get_json(board_url)
                raw_records.append(
                    v1._raw_record(
                        kind="boards",
                        asset=asset,
                        url=board_url,
                        payload=board_payload,
                        catalog_row=discovered_row,
                    )
                )
                board = v1._select_board(board_payload, discovered_row)
                row = {**discovered_row, **board}
                iss_request_from = max(
                    v1.SOURCE_START,
                    pd.Timestamp(row["series_start"]).date(),
                    pd.Timestamp(row["board_history_from"]).date(),
                )
                iss_request_till = min(
                    v1.SOURCE_END,
                    pd.Timestamp(row["spread_last_trade"]).date(),
                    pd.Timestamp(row["board_history_till"]).date(),
                )
                row["iss_request_from"] = pd.Timestamp(iss_request_from)
                row["iss_request_till"] = pd.Timestamp(iss_request_till)
                row["archive_request_from"] = pd.Timestamp(v1.SOURCE_START)
                row["archive_request_till"] = pd.Timestamp(v1.SOURCE_END)
                if iss_request_till < iss_request_from:
                    if not _is_exact_declared_empty_interval(
                        row, iss_request_from, iss_request_till
                    ):
                        raise ValueError(
                            f"unexpected empty calendar-spread ISS interval: "
                            f"{row['spread_id']}"
                        )
                    history = pd.DataFrame(columns=v1.ISS_DAILY_COLUMNS)
                    history_records: list[v1.RawRecord] = []
                    empty_iss_spreads.append(str(row["spread_id"]))
                else:
                    history, history_records = v1._fetch_history(
                        active_client,
                        asset,
                        row,
                        iss_request_from,
                        iss_request_till,
                    )
                raw_records.extend(history_records)
                archive, archive_records = v1._fetch_public_archive(
                    active_client,
                    asset,
                    row,
                    v1.SOURCE_START,
                    v1.SOURCE_END,
                )
                raw_records.extend(archive_records)
                if not history.empty:
                    iss_daily_frames.append(history)
                if not archive.empty:
                    archive_daily_frames.append(archive)
                history_dates = set(pd.to_datetime(history["trade_date"]))
                archive_dates = set(pd.to_datetime(archive["trade_date"]))
                coverage_rows.append(
                    {
                        "spread_id": row["spread_id"],
                        "logical_asset": logical_asset,
                        "secid": row["secid"],
                        "archive_code": row["archive_code"],
                        "iss_request_from": pd.Timestamp(iss_request_from),
                        "iss_request_till": pd.Timestamp(iss_request_till),
                        "archive_request_from": pd.Timestamp(v1.SOURCE_START),
                        "archive_request_till": pd.Timestamp(v1.SOURCE_END),
                        "iss_rows": int(len(history)),
                        "iss_reported_trade_rows": int(
                            history["reported_trade_activity"].sum()
                        ),
                        "iss_settlement_rows": int(history["has_settlement"].sum()),
                        "archive_rows": int(len(archive)),
                        "archive_reported_trade_rows": int(
                            archive["reported_trade_activity"].sum()
                        ),
                        "overlap_rows": int(len(history_dates & archive_dates)),
                        "iss_only_rows": int(len(history_dates - archive_dates)),
                        "archive_only_rows": int(len(archive_dates - history_dates)),
                        "archive_outside_iss_interval_rows": int(
                            (~archive["inside_iss_request_interval"]).sum()
                        ),
                        "archive_outside_series_interval_rows": int(
                            (~archive["inside_series_interval"]).sum()
                        ),
                        "archive_last_outside_range_rows": int(
                            archive["last_outside_range"].sum()
                        ),
                        "archive_crossed_quote_rows": int(
                            archive["closing_quote_crossed"].sum()
                        ),
                        "first_iss_date": (
                            pd.NaT if history.empty else history["trade_date"].min()
                        ),
                        "last_iss_date": (
                            pd.NaT if history.empty else history["trade_date"].max()
                        ),
                        "first_archive_date": (
                            pd.NaT if archive.empty else archive["trade_date"].min()
                        ),
                        "last_archive_date": (
                            pd.NaT if archive.empty else archive["trade_date"].max()
                        ),
                    }
                )
                enriched_rows.append(row)
            catalog_frames.append(
                pd.DataFrame(enriched_rows, columns=v1.CATALOG_COLUMNS)
            )
        if empty_iss_spreads != [EXPECTED_EMPTY_ISS_SPREAD_ID]:
            raise ValueError(
                f"calendar-spread V3 empty interval set drifted: {empty_iss_spreads}"
            )
        catalog = pd.concat(catalog_frames, ignore_index=True).sort_values(
            ["logical_asset", "near_expiration", "secid"], ignore_index=True
        )
        iss_daily = (
            pd.concat(iss_daily_frames, ignore_index=True).sort_values(
                ["trade_date", "logical_asset", "spread_id"], ignore_index=True
            )
            if iss_daily_frames
            else pd.DataFrame(columns=v1.ISS_DAILY_COLUMNS)
        )
        archive_daily = (
            pd.concat(archive_daily_frames, ignore_index=True).sort_values(
                ["trade_date", "logical_asset", "spread_id"], ignore_index=True
            )
            if archive_daily_frames
            else pd.DataFrame(columns=v1.ARCHIVE_DAILY_COLUMNS)
        )
        coverage = pd.DataFrame(
            coverage_rows, columns=v1.COVERAGE_COLUMNS
        ).sort_values(["logical_asset", "iss_request_till", "secid"], ignore_index=True)
        if len(catalog) != sum(v1.EXPECTED_SPREAD_COUNTS.values()):
            raise ValueError("calendar-spread V3 total catalog count drifted")
        if any(
            v1._forbidden_columns(frame)
            for frame in (catalog, iss_daily, archive_daily, coverage)
        ):
            raise ValueError("calendar-spread V3 output contains outcome columns")
        for frame, identity in (
            (iss_daily, ["trade_date", "spread_id", "board_id"]),
            (archive_daily, ["trade_date", "spread_id"]),
        ):
            if frame.empty:
                continue
            if pd.to_datetime(frame["trade_date"], errors="raise").max().date() >= (
                v1.PROTECTED_FROM
            ):
                raise ValueError("calendar-spread V3 output contains protected prices")
            if frame.duplicated(identity).any():
                raise ValueError("calendar-spread V3 output contains duplicate identities")
        catalog_path = temporary / "catalog.parquet"
        iss_daily_path = temporary / "iss_daily.parquet"
        archive_daily_path = temporary / "public_archive_daily.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_moex_responses.jsonl.gz"
        v1._write_parquet(catalog_path, catalog)
        v1._write_parquet(iss_daily_path, iss_daily)
        v1._write_parquet(archive_daily_path, archive_daily)
        v1._write_parquet(coverage_path, coverage)
        atomic_write_bytes(raw_path, v1._raw_archive_bytes(raw_records))
        artifacts = {
            "catalog": v1._artifact(catalog_path, len(catalog)),
            "iss_daily": v1._artifact(iss_daily_path, len(iss_daily)),
            "public_archive_daily": v1._artifact(
                archive_daily_path, len(archive_daily)
            ),
            "coverage": v1._artifact(coverage_path, len(coverage)),
            "raw": v1._artifact(raw_path, len(raw_records)),
        }
        manifest = {
            "bundle_id": "moex-calendar-spreads-current-vintage-2021-2025-v3",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": protocol.dependency_hashes,
            "source": "official MOEX ISS and public calendar-spread archive",
            "source_only": True,
            "contains_returns_targets_labels_signals_equity_or_pnl": False,
            "live_trading_allowed": False,
            "redistribution_review_required": True,
            "period": {
                "start": v1.SOURCE_START.isoformat(),
                "end": v1.SOURCE_END.isoformat(),
                "protected_from": v1.PROTECTED_FROM.isoformat(),
            },
            "counts": {
                "spreads": int(len(catalog)),
                "iss_daily_rows": int(len(iss_daily)),
                "public_archive_daily_rows": int(len(archive_daily)),
                "coverage_rows": int(len(coverage)),
                "raw_responses": int(len(raw_records)),
                "spreads_with_iss_history": int(coverage["iss_rows"].gt(0).sum()),
                "spreads_with_public_archive": int(
                    coverage["archive_rows"].gt(0).sum()
                ),
                "spreads_with_reported_trades": int(
                    coverage["archive_reported_trade_rows"].gt(0).sum()
                ),
                "iss_reported_trade_rows": int(
                    coverage["iss_reported_trade_rows"].sum()
                ),
                "public_archive_reported_trade_rows": int(
                    coverage["archive_reported_trade_rows"].sum()
                ),
                "iss_settlement_rows": int(
                    coverage["iss_settlement_rows"].sum()
                ),
                "overlap_rows": int(coverage["overlap_rows"].sum()),
                "iss_only_rows": int(coverage["iss_only_rows"].sum()),
                "public_archive_only_rows": int(
                    coverage["archive_only_rows"].sum()
                ),
                "public_archive_outside_iss_interval_rows": int(
                    coverage["archive_outside_iss_interval_rows"].sum()
                ),
                "public_archive_outside_series_interval_rows": int(
                    coverage["archive_outside_series_interval_rows"].sum()
                ),
                "public_archive_last_outside_range_rows": int(
                    coverage["archive_last_outside_range_rows"].sum()
                ),
                "public_archive_crossed_quote_rows": int(
                    coverage["archive_crossed_quote_rows"].sum()
                ),
                "empty_iss_interval_spread_ids": empty_iss_spreads,
                "by_asset": {
                    asset: int(catalog["logical_asset"].eq(asset).sum())
                    for asset in v1.ASSETS
                },
                "regular_adjacent_by_asset": {
                    asset: int(
                        catalog.loc[
                            catalog["logical_asset"].eq(asset),
                            "regular_adjacent_expiry",
                        ].sum()
                    )
                    for asset in v1.ASSETS
                },
                "near_date_match_by_asset": {
                    asset: int(
                        catalog.loc[
                            catalog["logical_asset"].eq(asset),
                            "near_expiration_matches_spread_last_trade",
                        ].sum()
                    )
                    for asset in v1.ASSETS
                },
                "metadata_missing_date_spreads": {
                    asset: list(v1.EXPECTED_MISSING_DATE_SPREADS[asset])
                    for asset in v1.ASSETS
                },
            },
            "availability": {
                "rule": "trade_date_plus_one_calendar_day_00_00_Europe_Moscow",
                "same_day_use_forbidden": True,
            },
            "artifacts": artifacts,
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        sidecar_path = temporary / "manifest.sha256"
        sidecar_text = f"{v1.sha256_file(manifest_path)}  manifest.json\n"
        atomic_write_bytes(sidecar_path, sidecar_text.encode("utf-8-sig"))
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active_client.close()
    return final


def collect_calendar_spreads(
    protocol: v1.CalendarSpreadSourceProtocol,
    client: v1.OfficialMoexClient | None = None,
) -> Path:
    """Run V3 collection under the inherited V2 parser correction."""
    with v2._patched_parent_parser():
        return _collect_calendar_spreads(protocol, client)


def audit_bundle(protocol: v1.CalendarSpreadSourceProtocol) -> v1.SourceAudit:
    """Replay V3 with inherited V2 blank-ASSETCODE parsing."""
    with v2._patched_parent_parser():
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
