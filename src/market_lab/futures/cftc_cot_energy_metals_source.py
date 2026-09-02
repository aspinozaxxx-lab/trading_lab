"""Collect the sealed target-free CFTC COT energy/metals source V1."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from datetime import time as wall_time
from pathlib import Path
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/cftc_cot_energy_metals_source_v1.yaml"
CONFIG_SHA256: Final[str] = "91616481d10da89324ddade784cd10ae1b023215fcdde1b3354fccb7f544464f"
USER_AGENT: Final[str] = "trading-lab-research/1.0 (CFTC public COT archive)"
NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")

INPUT_TO_OUTPUT: Final[dict[str, str]] = {
    "Open_Interest_All": "open_interest",
    "Prod_Merc_Positions_Long_All": "producer_long",
    "Prod_Merc_Positions_Short_All": "producer_short",
    "Swap_Positions_Long_All": "swap_long",
    "Swap__Positions_Short_All": "swap_short",
    "Swap__Positions_Spread_All": "swap_spreading",
    "M_Money_Positions_Long_All": "managed_money_long",
    "M_Money_Positions_Short_All": "managed_money_short",
    "M_Money_Positions_Spread_All": "managed_money_spreading",
    "Other_Rept_Positions_Long_All": "other_reportable_long",
    "Other_Rept_Positions_Short_All": "other_reportable_short",
    "Other_Rept_Positions_Spread_All": "other_reportable_spreading",
    "NonRept_Positions_Long_All": "nonreportable_long",
    "NonRept_Positions_Short_All": "nonreportable_short",
    "Traders_Tot_All": "total_traders",
}


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> ResponseLike: ...


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return storage.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("unsafe CFTC output path")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "processed"):
        raise ValueError("CFTC output must be under data/processed")
    return PROJECT_ROOT / relative


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("CFTC config must be an object")
    archives = config["official_sources"]["annual_archives"]
    hypothesis = config["frozen_later_v58_hypothesis"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "cftc_cot_energy_metals_source_v1"
        or config.get("status") != "sealed_before_any_2018_2025_position_value"
        or config.get("live_trading_allowed") is not False
        or tuple(int(year) for year in archives) != tuple(range(2018, 2026))
        or tuple(config["universe"]["exact_order"]) != ("WTI", "GOLD")
        or config["schema"].get("moex_prices_returns_labels_targets_signals_trades_or_pnl_allowed")
        is not False
        or int(hypothesis["lookback_admitted_reports"]) != 13
        or float(hypothesis["annual_volatility_target"]) != 0.30
        or float(hypothesis["maximum_absolute_target"]) != 2.0
    ):
        raise ValueError("CFTC source protocol drifted")
    config["_config_sha256"] = actual
    return config


def _decode_csv(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CFTC annual CSV is not UTF-8 or CP1252")


def _annual_member(archive_bytes: bytes, year: int) -> tuple[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as error:
        raise ValueError(f"CFTC {year} archive is not a ZIP") from error
    members = [
        item
        for item in archive.infolist()
        if not item.is_dir()
        and not item.filename.startswith("__MACOSX/")
        and Path(item.filename).suffix.lower() in {".txt", ".csv"}
    ]
    if len(members) != 1:
        raise ValueError(f"CFTC {year} archive must contain one CSV/TXT member")
    member = members[0]
    if Path(member.filename).is_absolute() or ".." in Path(member.filename).parts:
        raise ValueError("unsafe CFTC ZIP member")
    return member.filename, archive.read(member)


def _conservative_available_at(report_dates: pd.Series) -> pd.Series:
    values = []
    for value in pd.to_datetime(report_dates, errors="raise"):
        local_date = (pd.Timestamp(value) + pd.Timedelta(days=7)).date()
        localized = datetime.combine(local_date, wall_time(23, 59, 59), tzinfo=NEW_YORK)
        values.append(pd.Timestamp(localized).tz_convert("UTC"))
    return pd.Series(values, dtype="datetime64[ns, UTC]")


def parse_annual_archive(
    archive_bytes: bytes, year: int, config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    member_name, csv_bytes = _annual_member(archive_bytes, year)
    frame = pd.read_csv(io.StringIO(_decode_csv(csv_bytes)), dtype=str)
    frame.columns = [str(column).strip() for column in frame.columns]
    required = set(config["schema"]["required_input_columns"])
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CFTC {year} required columns missing: {sorted(missing)}")
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].str.strip()
    configured = config["universe"]["markets"]
    code_to_market = {
        str(item["cftc_contract_market_code"]): logical for logical, item in configured.items()
    }
    selected = frame.loc[frame["CFTC_Contract_Market_Code"].isin(code_to_market)].copy()
    if selected.empty:
        raise ValueError(f"CFTC {year} selected markets are absent")
    selected["logical_market"] = selected["CFTC_Contract_Market_Code"].map(code_to_market)
    for logical, item in configured.items():
        rows = selected.loc[selected["logical_market"].eq(logical)]
        if rows.empty:
            raise ValueError(f"CFTC {year} market missing: {logical}")
        if (
            not rows["Market_and_Exchange_Names"]
            .eq(str(item["exact_market_and_exchange_name"]))
            .all()
        ):
            actual_names = sorted(rows["Market_and_Exchange_Names"].unique())
            raise ValueError(f"CFTC {year} market name drift for {logical}: {actual_names}")
    selected["report_date"] = pd.to_datetime(
        selected["Report_Date_as_YYYY-MM-DD"], errors="raise"
    ).dt.normalize()
    if not selected["report_date"].dt.year.eq(year).all():
        raise ValueError(f"CFTC {year} contains cross-year selected rows")
    protected = pd.Timestamp(config["dates"]["protected_from"])
    if selected["report_date"].ge(protected).any():
        raise ValueError("CFTC protected report date detected")
    if selected.duplicated(["logical_market", "report_date"]).any():
        raise ValueError(f"CFTC {year} duplicate selected market/report date")
    if not selected["FutOnly_or_Combined"].str.contains("FutOnly", case=False, na=False).all():
        raise ValueError(f"CFTC {year} selected rows are not futures-only")
    selected = selected.reset_index(drop=True)
    output = pd.DataFrame(
        {
            "report_date": selected["report_date"],
            "available_at_utc": _conservative_available_at(selected["report_date"]),
            "logical_market": selected["logical_market"],
            "market_and_exchange_name": selected["Market_and_Exchange_Names"],
            "cftc_contract_market_code": selected["CFTC_Contract_Market_Code"],
        }
    )
    for input_column, output_column in INPUT_TO_OUTPUT.items():
        output[output_column] = pd.to_numeric(
            selected[input_column].str.replace(",", "", regex=False), errors="coerce"
        ).astype(float)
    output["contract_units"] = selected["Contract_Units"].astype("string")
    output["source_archive_year"] = year
    numeric = list(INPUT_TO_OUTPUT.values())
    if output[numeric].isna().any(axis=None):
        raise ValueError(f"CFTC {year} selected numeric position is missing")
    if output[numeric].lt(0.0).any(axis=None):
        raise ValueError(f"CFTC {year} selected position is negative")
    if not output["open_interest"].gt(0.0).all():
        raise ValueError(f"CFTC {year} selected open interest is not positive")
    output = output.sort_values(["report_date", "logical_market"], kind="mergesort").reset_index(
        drop=True
    )
    expected_columns = list(config["schema"]["normalized_columns"])
    if list(output.columns) != expected_columns:
        raise ValueError("CFTC normalized schema drifted")
    return output, {
        "year": year,
        "member": member_name,
        "archive_sha256": _sha_bytes(archive_bytes),
        "archive_bytes": len(archive_bytes),
        "csv_sha256": _sha_bytes(csv_bytes),
        "csv_bytes": len(csv_bytes),
        "source_rows": len(frame),
        "selected_rows": len(output),
    }


def _download(url: str, session: SessionLike | None = None) -> bytes:
    client = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=60.0)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty CFTC archive response")
            return response.content
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"CFTC archive download failed: {url}") from last_error


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as stream:
        path = Path(stream.name)
    try:
        frame.to_parquet(path, index=False)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def collect(
    output_root: Path | None = None,
    *,
    session: SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    config = load_config()
    output = output_root.resolve() if output_root is not None else _root(config["outputs"]["root"])
    if output.exists():
        raise FileExistsError(f"immutable CFTC output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    retrieved = pd.Timestamp(retrieved_at or datetime.now(UTC))
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")
    frames: list[pd.DataFrame] = []
    records: list[dict[str, Any]] = []
    annual_bytes: dict[int, bytes] = {}
    for raw_year, url in config["official_sources"]["annual_archives"].items():
        year = int(raw_year)
        payload = _download(str(url), session)
        frame, record = parse_annual_archive(payload, year, config)
        record["url"] = str(url)
        frames.append(frame)
        records.append(record)
        annual_bytes[year] = payload
    panel = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["report_date", "logical_market"], kind="mergesort")
        .reset_index(drop=True)
    )
    if panel.duplicated(["logical_market", "report_date"]).any():
        raise ValueError("CFTC cross-year duplicate selected market/report date")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        raw_buffer = io.BytesIO()
        with zipfile.ZipFile(raw_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for year in sorted(annual_bytes):
                archive.writestr(f"annual/fut_disagg_txt_{year}.zip", annual_bytes[year])
            archive.writestr(
                "retrieval.json",
                json.dumps(
                    {
                        "retrieved_at_utc": retrieved.isoformat(),
                        "records": records,
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8-sig"),
            )
        raw_path = staging / "raw_archives.zip"
        processed_path = staging / "cot_positions.parquet"
        atomic_write_bytes(raw_path, raw_buffer.getvalue())
        atomic_write_bytes(processed_path, _parquet_bytes(panel))
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": config["_config_sha256"],
            "implementation_sha256": _sha_file(Path(__file__)),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "retrieved_at_utc": retrieved.isoformat(),
            "source_only": True,
            "contains_moex_price_return_target_signal_trade_or_pnl": False,
            "records": records,
            "processed": {
                "file": processed_path.name,
                "rows": len(panel),
                "sha256": _sha_file(processed_path),
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
                "sha256": _sha_file(raw_path),
                "bytes": raw_path.stat().st_size,
                "annual_archives": len(annual_bytes),
            },
        }
        write_json(staging / "manifest.json", manifest)
        atomic_write_text(
            staging / "manifest.sha256",
            f"{_sha_file(staging / 'manifest.json')}  manifest.json\n",
        )
        staging.rename(output)
    except Exception:
        raise
    audit = audit_bundle(output)
    write_json(output / "audit.json", audit)
    if not audit["all_true"]:
        raise ValueError("CFTC source audit failed")
    return output


def _raw_records(raw_path: Path) -> tuple[dict[str, Any], dict[int, bytes]]:
    with zipfile.ZipFile(raw_path) as archive:
        names = set(archive.namelist())
        metadata = json.loads(archive.read("retrieval.json").decode("utf-8-sig"))
        annual: dict[int, bytes] = {}
        for item in metadata["records"]:
            year = int(item["year"])
            name = f"annual/fut_disagg_txt_{year}.zip"
            if name not in names:
                raise ValueError(f"CFTC raw bundle missing {name}")
            annual[year] = archive.read(name)
    return metadata, annual


def audit_bundle(output: Path) -> dict[str, Any]:
    config = load_config()
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    processed_path = output / manifest["processed"]["file"]
    raw_path = output / manifest["raw"]["file"]
    checks: dict[str, bool] = {
        "protocol_exact": manifest["protocol_sha256"] == config["_config_sha256"],
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(Path(__file__)),
        "manifest_sidecar_exact": (output / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == _sha_file(manifest_path),
        "processed_exact": _sha_file(processed_path) == manifest["processed"]["sha256"],
        "raw_exact": _sha_file(raw_path) == manifest["raw"]["sha256"],
        "source_only": manifest["source_only"] is True,
        "outcomes_absent": manifest["contains_moex_price_return_target_signal_trade_or_pnl"]
        is False,
    }
    metadata, annual = _raw_records(raw_path)
    checks["eight_raw_archives"] = set(annual) == set(range(2018, 2026))
    rebuilt_frames: list[pd.DataFrame] = []
    replay_records: list[dict[str, Any]] = []
    for year in sorted(annual):
        frame, record = parse_annual_archive(annual[year], year, config)
        rebuilt_frames.append(frame)
        replay_records.append(record)
    rebuilt = (
        pd.concat(rebuilt_frames, ignore_index=True)
        .sort_values(["report_date", "logical_market"], kind="mergesort")
        .reset_index(drop=True)
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
            "protected_rows_zero": bool(stored["report_date"].lt("2026-01-01").all()),
            "availability_after_report": bool(
                (
                    pd.to_datetime(stored["available_at_utc"], utc=True)
                    > pd.to_datetime(stored["report_date"], utc=True)
                ).all()
            ),
            "markets_exact": set(stored["logical_market"]) == {"WTI", "GOLD"},
            "record_hashes_replay": all(
                record["archive_sha256"]
                == next(
                    item["archive_sha256"]
                    for item in metadata["records"]
                    if int(item["year"]) == record["year"]
                )
                for record in replay_records
            ),
        }
    )
    return {
        "checks": checks,
        "all_true": all(checks.values()),
        "limitations": config["limitations"],
    }


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


__all__ = [
    "CONFIG_PATH",
    "CONFIG_SHA256",
    "audit_bundle",
    "collect",
    "load_config",
    "parse_annual_archive",
]
