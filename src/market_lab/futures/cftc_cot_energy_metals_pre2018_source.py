"""Collect the sealed target-free 2012-2017 CFTC COT source for V59."""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import cftc_cot_energy_metals_source as base
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/cftc_cot_energy_metals_pre2018_source_v1.yaml"
CONFIG_SHA256: Final[str] = "1d8fb69b0860440c186adb80ee7d138ce1bdcdf8589f465dd6e6ed32f723c42f"
YEARS: Final[tuple[int, ...]] = tuple(range(2012, 2018))


def sha256_file(path: Path) -> str:
    return base._sha_file(path)


def load_config() -> dict[str, Any]:
    actual = sha256_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    hypothesis = config["frozen_later_v59_hypothesis"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "cftc_cot_energy_metals_pre2018_source_v1"
        or config.get("status") != "sealed_before_any_2012_2017_position_value"
        or config.get("live_trading_allowed") is not False
        or tuple(int(year) for year in config["official_sources"]["annual_archives"]) != YEARS
        or tuple(config["universe"]["exact_order"]) != ("WTI", "GOLD")
        or str(config["dates"]["protected_from"]) != "2018-01-01"
        or int(hypothesis["lookback_admitted_reports"]) != 13
        or hypothesis["direction_rule"] != "positive_short_BR_negative_long_BR_exact_zero_cash"
        or float(hypothesis["annual_volatility_target"]) != 0.30
        or float(hypothesis["maximum_absolute_target"]) != 2.0
    ):
        raise ValueError("pre-2018 CFTC source protocol drifted")
    config["_config_sha256"] = actual
    return config


def _parse_archive(
    payload: bytes, year: int, config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize the header-only 2012 date alias without altering stored raw bytes."""
    parse_payload = payload
    if year == 2012:
        member_name, csv_bytes = base._annual_member(payload, year)
        text = base._decode_csv(csv_bytes)
        old = "Report_Date_as_MM_DD_YYYY"
        new = "Report_Date_as_YYYY-MM-DD"
        if old not in text.splitlines()[0]:
            raise ValueError("CFTC 2012 sealed date alias is absent")
        normalized_csv = text.replace(old, new, 1).encode("utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member_name, normalized_csv)
        parse_payload = buffer.getvalue()
    frame, record = base.parse_annual_archive(parse_payload, year, config)
    member_name, csv_bytes = base._annual_member(payload, year)
    record.update(
        {
            "member": member_name,
            "archive_sha256": base._sha_bytes(payload),
            "archive_bytes": len(payload),
            "csv_sha256": base._sha_bytes(csv_bytes),
            "csv_bytes": len(csv_bytes),
        }
    )
    return frame, record


def collect(
    output_root: Path | None = None,
    *,
    session: base.SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    output = (
        output_root.resolve() if output_root is not None else base._root(config["outputs"]["root"])
    )
    if output.exists():
        raise FileExistsError(f"immutable pre-2018 CFTC output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    retrieved = pd.Timestamp(retrieved_at or datetime.now(UTC))
    retrieved = (
        retrieved.tz_localize("UTC") if retrieved.tzinfo is None else retrieved.tz_convert("UTC")
    )
    frames: list[pd.DataFrame] = []
    records: list[dict[str, Any]] = []
    annual_bytes: dict[int, bytes] = {}
    for raw_year, url in config["official_sources"]["annual_archives"].items():
        year = int(raw_year)
        payload = base._download(str(url), session)
        frame, record = _parse_archive(payload, year, config)
        record["url"] = str(url)
        frames.append(frame)
        records.append(record)
        annual_bytes[year] = payload
    panel = pd.concat(frames, ignore_index=True).sort_values(
        ["report_date", "logical_market"], kind="mergesort", ignore_index=True
    )
    if panel.duplicated(["logical_market", "report_date"]).any():
        raise ValueError("pre-2018 CFTC cross-year duplicate")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    raw_buffer = io.BytesIO()
    with zipfile.ZipFile(raw_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for year in sorted(annual_bytes):
            archive.writestr(f"annual/fut_disagg_txt_{year}.zip", annual_bytes[year])
        archive.writestr(
            "retrieval.json",
            json.dumps(
                {"retrieved_at_utc": retrieved.isoformat(), "records": records},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8-sig"),
        )
    raw_path = staging / "raw_archives.zip"
    processed_path = staging / "cot_positions.parquet"
    atomic_write_bytes(raw_path, raw_buffer.getvalue())
    atomic_write_bytes(processed_path, base._parquet_bytes(panel))
    manifest = {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": config["_config_sha256"],
        "implementation_sha256": sha256_file(Path(__file__)),
        "parser_implementation_sha256": sha256_file(Path(base.__file__)),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "retrieved_at_utc": retrieved.isoformat(),
        "source_only": True,
        "contains_moex_price_return_target_signal_trade_or_pnl": False,
        "records": records,
        "processed": {
            "file": processed_path.name,
            "rows": len(panel),
            "sha256": sha256_file(processed_path),
            "bytes": processed_path.stat().st_size,
            "minimum_report_date": panel["report_date"].min().date().isoformat(),
            "maximum_report_date": panel["report_date"].max().date().isoformat(),
            "market_rows": {
                key: int(value)
                for key, value in panel["logical_market"].value_counts().sort_index().items()
            },
        },
        "raw": {
            "file": raw_path.name,
            "sha256": sha256_file(raw_path),
            "bytes": raw_path.stat().st_size,
            "annual_archives": len(annual_bytes),
        },
    }
    write_json(staging / "manifest.json", manifest)
    atomic_write_text(
        staging / "manifest.sha256",
        f"{sha256_file(staging / 'manifest.json')}  manifest.json\n",
    )
    staging.rename(output)
    audit = audit_bundle(output)
    write_json(output / "audit.json", audit)
    if not audit["all_true"]:
        raise ValueError("pre-2018 CFTC source audit failed")
    return output


def _raw_records(raw_path: Path) -> tuple[dict[str, Any], dict[int, bytes]]:
    with zipfile.ZipFile(raw_path) as archive:
        metadata = json.loads(archive.read("retrieval.json").decode("utf-8-sig"))
        annual = {
            int(item["year"]): archive.read(f"annual/fut_disagg_txt_{int(item['year'])}.zip")
            for item in metadata["records"]
        }
    return metadata, annual


def audit_bundle(output: Path) -> dict[str, Any]:
    config = load_config()
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    processed_path = output / manifest["processed"]["file"]
    raw_path = output / manifest["raw"]["file"]
    checks = {
        "protocol_exact": manifest["protocol_sha256"] == config["_config_sha256"],
        "implementation_exact": manifest["implementation_sha256"] == sha256_file(Path(__file__)),
        "parser_exact": manifest["parser_implementation_sha256"]
        == sha256_file(Path(base.__file__)),
        "manifest_sidecar_exact": (output / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == sha256_file(manifest_path),
        "processed_exact": sha256_file(processed_path) == manifest["processed"]["sha256"],
        "raw_exact": sha256_file(raw_path) == manifest["raw"]["sha256"],
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_moex_price_return_target_signal_trade_or_pnl"]
        is False,
    }
    metadata, annual = _raw_records(raw_path)
    checks["six_raw_archives"] = set(annual) == set(YEARS)
    frames = [_parse_archive(annual[year], year, config)[0] for year in YEARS]
    rebuilt = pd.concat(frames, ignore_index=True).sort_values(
        ["report_date", "logical_market"], kind="mergesort", ignore_index=True
    )
    stored = pd.read_parquet(processed_path)
    try:
        pd.testing.assert_frame_equal(stored, rebuilt, check_dtype=False)
        checks["raw_replay_exact"] = True
    except AssertionError:
        checks["raw_replay_exact"] = False
    checks.update(
        {
            "rows_exact": len(stored) == int(manifest["processed"]["rows"]),
            "unique_market_report_date": not stored.duplicated(
                ["logical_market", "report_date"]
            ).any(),
            "protected_rows_zero": bool(stored["report_date"].lt("2018-01-01").all()),
            "markets_exact": set(stored["logical_market"]) == {"WTI", "GOLD"},
            "record_hashes_replay": all(
                base._sha_bytes(annual[int(item["year"])]) == item["archive_sha256"]
                for item in metadata["records"]
            ),
        }
    )
    return {"checks": checks, "all_true": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.audit:
        audit = audit_bundle(args.audit)
        print(json.dumps(audit, indent=2, sort_keys=True))
        raise SystemExit(0 if audit["all_true"] else 1)
    print(collect(args.output))


if __name__ == "__main__":
    main()
