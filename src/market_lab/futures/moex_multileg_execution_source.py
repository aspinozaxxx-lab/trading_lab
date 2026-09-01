"""Fail-closed ingestion of licensed MOEX multileg execution reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Final
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_multileg_execution_source_v1.yaml"
)
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
PACKAGE_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(20\d{6})(?!\d)")
MAX_ID_LENGTH: Final[int] = 64

REPORT_KINDS: Final[tuple[str, ...]] = (
    "multileg_dict",
    "multileg_deal",
    "participant_multileg_deal",
    "participant_multileg_order_log",
    "participant_leg_deal",
)
MARKET_CORE_KINDS: Final[tuple[str, str]] = (
    "multileg_dict",
    "multileg_deal",
)
FORBIDDEN_OUTPUT_FRAGMENTS: Final[tuple[str, ...]] = (
    "return",
    "target",
    "label",
    "signal",
    "strategy",
    "equity",
    "pnl",
    "profit",
)
SENSITIVE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "kod",
        "kod_buy",
        "kod_sell",
        "kod_rts_b",
        "kod_rts_s",
        "user",
        "user_buy",
        "user_sell",
        "user_to",
        "comment",
        "comm_buy",
        "comm_sell",
    }
)

REQUIRED_COLUMNS: Final[dict[str, frozenset[str]]] = {
    "multileg_dict": frozenset({"DATE", "ISIN", "NUM_LEGS", "ISIN_LEG", "VOL"}),
    "multileg_deal": frozenset(
        {"DATE", "TIME", "ISIN", "PRICE1", "PRICE", "VOL", "ID_DEAL", "TYPE"}
    ),
    "participant_multileg_deal": frozenset(
        {
            "ID_DEAL",
            "ISIN",
            "PRICE1",
            "PRICE",
            "VOL",
            "DATE",
            "TIME",
            "NO_BUY",
            "NO_SELL",
            "ID_TRADE",
        }
    ),
    "participant_multileg_order_log": frozenset(
        {
            "NUMB_ORDER",
            "ISIN",
            "PRICE",
            "VOL",
            "REST_VOL",
            "TIP",
            "SOST",
            "DATE",
            "TIME",
            "TYPE",
        }
    ),
    "participant_leg_deal": frozenset(
        {"ID_DEAL", "ISIN", "PRICE", "VOL", "DATE", "TIME", "ID_MULT"}
    ),
}

ID_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "ID_DEAL",
        "ID_TRADE",
        "ID_MULT",
        "NUMB_ORDER",
        "NO_BUY",
        "NO_SELL",
        "N_ORDER1",
        "EXT_ID",
        "EXT_ID_B",
        "EXT_ID_S",
    }
)
NUMERIC_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "NUM_LEGS",
        "PRICE1",
        "PRICE",
        "PRICE_RUR",
        "PRICE_RUR1",
        "VOL",
        "REST_VOL",
        "RATE",
        "DAYS",
        "TIP",
        "SOST",
        "TYPE",
        "TYPE_BUY",
        "TYPE_SELL",
        "FEE_BUY",
        "FEE_SELL",
        "FEE_EX_B",
        "FEE_CC_B",
        "FEE_EX_S",
        "FEE_CC_S",
    }
)
OPTIONAL_PUBLISHED_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "multileg_dict": (),
    "multileg_deal": ("RATE",),
    "participant_multileg_deal": (
        "TYPE",
        "TYPE_BUY",
        "TYPE_SELL",
        "FEE_BUY",
        "FEE_SELL",
        "FEE_EX_B",
        "FEE_CC_B",
        "FEE_EX_S",
        "FEE_CC_S",
        "PRICE_RUR",
        "PRICE_RUR1",
    ),
    "participant_multileg_order_log": (
        "DAYS",
        "PRICE_RUR",
        "EXT_ID",
        "DATE_EXP",
        "N_ORDER1",
    ),
    "participant_leg_deal": ("ID_DEAL",),
}


@dataclass(frozen=True, slots=True)
class MultilegSourceProtocol:
    """Verified source-only declaration for local licensed report ingestion."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    input_directory: Path
    output_directory: Path
    period_start: date
    period_end: date
    protected_from: date
    maximum_member_bytes: int
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class InputObject:
    """One dated CSV object discovered without extracting an archive to disk."""

    container_path: Path
    container_name: str
    container_sha256: str
    member_name: str
    report_kind: str
    package_date: date
    raw_size: int


@dataclass(frozen=True, slots=True)
class SourcePreflight:
    """Parsed source tables plus target-free integrity checks."""

    tables: dict[str, pd.DataFrame]
    inventory: pd.DataFrame
    checks: dict[str, bool]
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class SourceAudit:
    """Replay and byte-integrity result for a published source bundle."""

    checks: dict[str, bool]
    counts: dict[str, int]


def sha256_file(path: Path) -> str:
    """Return the streaming SHA-256 of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"multileg source {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"multileg source sidecar missing: {sidecar}")
    tokens = sidecar.read_text(encoding="utf-8-sig").split()
    if not tokens:
        raise ValueError("empty multileg source sidecar")
    return tokens[0].lower()


def _project_path(relative_value: str, required_root: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe multileg source path: {relative_value}")
    if relative.parts[0].lower() != required_root.lower():
        raise ValueError(f"multileg source path must start with {required_root}")
    return PROJECT_ROOT / relative


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> MultilegSourceProtocol:
    """Verify the seal without opening any licensed market-data file."""
    path = config_path.resolve()
    actual_sha = sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("multileg source protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("multileg source protocol must be a YAML object")
    period = _mapping(payload.get("period"), "period")
    source = _mapping(payload.get("source"), "source")
    temporal = _mapping(payload.get("temporal_safety"), "temporal safety")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    start = date.fromisoformat(str(period["start"]))
    end = date.fromisoformat(str(period["end"]))
    protected = date.fromisoformat(str(period["protected_from"]))
    accepted = tuple(source.get("accepted_report_kinds", ()))
    if (
        payload.get("protocol_id") != "moex_multileg_execution_source_v1"
        or payload.get("scope") != "source_only_no_returns_targets_signals_or_pnl"
        or payload.get("sealed_before_first_licensed_archive_read") is not True
        or payload.get("live_trading_allowed") is not False
        or source.get("network_download") is not False
        or source.get("license_or_member_archive_required") is not True
        or accepted != REPORT_KINDS
        or temporal.get("dated_container_required_before_open") is not True
        or temporal.get("same_day_signal_use_forbidden") is not True
        or temporal.get("execution_replay_only") is not True
        or start != date(2021, 1, 1)
        or end != date(2025, 12, 31)
        or protected != date(2026, 1, 1)
        or not start <= end < protected
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("multileg source protocol invariants drifted")
    maximum_member_bytes = int(source.get("maximum_uncompressed_member_bytes", 0))
    if maximum_member_bytes <= 0:
        raise ValueError("multileg source maximum member size must be positive")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if sha256_file(dependency_path) != digest:
            raise ValueError(f"multileg source dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return MultilegSourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        payload=payload,
        input_directory=_project_path(str(source["directory"]), "data"),
        output_directory=_project_path(str(output["directory"]), "data"),
        period_start=start,
        period_end=end,
        protected_from=protected,
        maximum_member_bytes=maximum_member_bytes,
        dependency_hashes=dependency_hashes,
    )


def _canonical_report_basename(name: str) -> str:
    basename = PurePosixPath(name.replace("\\", "/")).name.lower()
    return re.sub(r"^20\d{6}[_-]", "", basename)


def classify_report_name(name: str) -> str | None:
    """Map official historical filenames to non-overlapping report families."""
    basename = _canonical_report_basename(name)
    if basename == "multileg_dict.csv":
        return "multileg_dict"
    if basename == "multileg_deal.csv":
        return "multileg_deal"
    stem = Path(basename).stem
    if stem.startswith("multilegf04"):
        suffix = stem[len("multilegf04") :].lstrip("_")
        if suffix.startswith(("cl", "trade")):
            return None
        return "participant_multileg_deal"
    if stem.startswith("multilegordlog"):
        suffix = stem[len("multilegordlog") :].lstrip("_")
        if suffix.startswith("trade"):
            return None
        return "participant_multileg_order_log"
    if stem.startswith("f04"):
        suffix = stem[len("f04") :].lstrip("_")
        if suffix.startswith(("cl", "trade")):
            return None
        return "participant_leg_deal"
    return None


def _package_date_from_name(name: str) -> date:
    matches = PACKAGE_DATE_PATTERN.findall(name.replace("\\", "/"))
    parsed = sorted({datetime.strptime(item, "%Y%m%d").date() for item in matches})
    if len(parsed) != 1:
        raise ValueError(f"exactly one package YYYYMMDD is required before read: {name}")
    return parsed[0]


def _validate_package_date(package_date: date, protocol: MultilegSourceProtocol) -> None:
    if package_date >= protocol.protected_from:
        raise ValueError(f"protected multileg package date rejected before read: {package_date}")
    if not protocol.period_start <= package_date <= protocol.period_end:
        raise ValueError(f"multileg package date outside sealed period: {package_date}")


def discover_input_objects(protocol: MultilegSourceProtocol) -> list[InputObject]:
    """Inventory dated CSV/ZIP names; reject protected packages before opening them."""
    root = protocol.input_directory
    if not root.is_dir():
        raise FileNotFoundError(f"licensed multileg input directory missing: {root}")
    discovered: list[InputObject] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix not in {".csv", ".zip", ".7z"}:
            continue
        package_date = _package_date_from_name(relative)
        _validate_package_date(package_date, protocol)
        if suffix == ".7z":
            raise ValueError(
                f"7z input must be extracted into a dated directory before audit: {relative}"
            )
        container_sha = sha256_file(path)
        if suffix == ".csv":
            kind = classify_report_name(path.name)
            if kind is None:
                continue
            size = path.stat().st_size
            if size > protocol.maximum_member_bytes:
                raise ValueError(f"multileg CSV exceeds sealed size limit: {relative}")
            discovered.append(
                InputObject(
                    container_path=path,
                    container_name=relative,
                    container_sha256=container_sha,
                    member_name=path.name,
                    report_kind=kind,
                    package_date=package_date,
                    raw_size=size,
                )
            )
            continue
        with zipfile.ZipFile(path) as archive:
            for member in sorted(archive.infolist(), key=lambda item: item.filename):
                if member.is_dir():
                    continue
                member_path = PurePosixPath(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"unsafe multileg ZIP member: {member.filename}")
                kind = classify_report_name(member.filename)
                if kind is None:
                    continue
                member_dates = PACKAGE_DATE_PATTERN.findall(member.filename)
                if member_dates:
                    member_date = _package_date_from_name(member.filename)
                    _validate_package_date(member_date, protocol)
                    if member_date != package_date:
                        raise ValueError(
                            f"multileg ZIP/member date mismatch: {relative}/{member.filename}"
                        )
                if member.file_size > protocol.maximum_member_bytes:
                    raise ValueError(
                        f"multileg ZIP member exceeds sealed size limit: {member.filename}"
                    )
                discovered.append(
                    InputObject(
                        container_path=path,
                        container_name=relative,
                        container_sha256=container_sha,
                        member_name=member.filename,
                        report_kind=kind,
                        package_date=package_date,
                        raw_size=member.file_size,
                    )
                )
    identities = [
        (item.container_name, item.member_name, item.report_kind, item.package_date)
        for item in discovered
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate multileg source object identity")
    return discovered


def _read_object_bytes(item: InputObject) -> bytes:
    if item.container_path.suffix.lower() == ".csv":
        payload = item.container_path.read_bytes()
    else:
        with zipfile.ZipFile(item.container_path) as archive:
            payload = archive.read(item.member_name)
    if len(payload) != item.raw_size:
        raise ValueError(f"multileg object size drift: {item.member_name}")
    return payload


def _decode_csv(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251", "cp866"):
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        first_line = text.splitlines()[0] if text.splitlines() else ""
        if ";" in first_line:
            return text
    raise ValueError("multileg CSV is not strict UTF-8/CP1251/CP866 semicolon text")


def _normalize_header(value: str) -> str:
    normalized = value.strip().lstrip("#").strip().strip("[]").strip()
    normalized = re.sub(r"\s+", "_", normalized).upper()
    if not normalized:
        raise ValueError("blank multileg CSV column")
    return normalized


def _parse_date_value(value: object) -> date:
    text = str(value).strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"invalid multileg event date: {text!r}")


def _parse_time_value(value: object) -> time:
    text = str(value).strip()
    for pattern in ("%H:%M:%S", "%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    raise ValueError(f"invalid multileg event time: {text!r}")


def _normalized_identifier(series: pd.Series, column: str) -> pd.Series:
    normalized = series.astype("string").str.strip().replace("", pd.NA)
    if normalized.dropna().str.len().gt(MAX_ID_LENGTH).any():
        raise ValueError(f"multileg identifier too long: {column}")
    return normalized


def _numeric(series: pd.Series, column: str) -> pd.Series:
    normalized = series.astype("string").str.strip().replace("", pd.NA)
    normalized = normalized.str.replace(",", ".", regex=False)
    try:
        return pd.to_numeric(normalized, errors="raise")
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid multileg numeric column: {column}") from error


def _published_columns(kind: str) -> tuple[str, ...]:
    required = tuple(sorted(REQUIRED_COLUMNS[kind]))
    optional = OPTIONAL_PUBLISHED_COLUMNS[kind]
    return required + tuple(item for item in optional if item not in required)


def parse_report_bytes(
    kind: str,
    payload: bytes,
    package_date: date,
    *,
    source_object: str = "synthetic",
    container_sha256: str = "0" * 64,
) -> pd.DataFrame:
    """Parse one already date-gated report into a privacy-safe closed schema."""
    if kind not in REPORT_KINDS:
        raise ValueError(f"unsupported multileg report kind: {kind}")
    text = _decode_csv(payload)
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if reader.fieldnames is None:
        raise ValueError("multileg CSV header missing")
    normalized_headers = [_normalize_header(item) for item in reader.fieldnames]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise ValueError("duplicate normalized multileg CSV columns")
    missing = REQUIRED_COLUMNS[kind] - set(normalized_headers)
    if missing:
        raise ValueError(f"multileg {kind} required columns missing: {sorted(missing)}")
    records: list[dict[str, object]] = []
    original_headers = list(reader.fieldnames)
    for raw_row in reader:
        if None in raw_row:
            raise ValueError("multileg CSV row has more fields than its header")
        row = {
            normalized: raw_row.get(original)
            for original, normalized in zip(
                original_headers, normalized_headers, strict=True
            )
        }
        if any(str(value or "").strip() for value in row.values()):
            records.append(row)
    selected = list(_published_columns(kind))
    frame = pd.DataFrame(records)
    for column in selected:
        if column not in frame:
            frame[column] = pd.NA
    frame = frame[selected].copy()
    for column in ID_COLUMNS & set(frame.columns):
        frame[column] = _normalized_identifier(frame[column], column)
    for column in NUMERIC_COLUMNS & set(frame.columns):
        frame[column] = _numeric(frame[column], column)
    if not frame.empty:
        event_dates = frame["DATE"].map(_parse_date_value)
        if not event_dates.eq(package_date).all():
            raise ValueError(
                f"multileg row/package date mismatch in {source_object}: "
                f"{sorted(set(event_dates))} != {package_date}"
            )
        if "TIME" in frame:
            event_times = frame["TIME"].map(_parse_time_value)
            frame["event_at_moscow"] = [
                datetime.combine(day, value, tzinfo=MOSCOW)
                for day, value in zip(event_dates, event_times, strict=True)
            ]
        else:
            frame["event_at_moscow"] = pd.NaT
        frame["event_date"] = pd.to_datetime(event_dates)
    else:
        frame["event_at_moscow"] = pd.Series(dtype="datetime64[ns, Europe/Moscow]")
        frame["event_date"] = pd.Series(dtype="datetime64[ns]")
    frame["package_date"] = pd.Timestamp(package_date)
    frame["report_available_at_moscow"] = datetime.combine(
        package_date + timedelta(days=1), time.min, tzinfo=MOSCOW
    )
    frame["source_object"] = source_object
    frame["container_sha256"] = container_sha256
    frame.columns = [column.lower() for column in frame.columns]
    if kind == "participant_leg_deal" and not frame.empty:
        frame = frame.loc[frame["id_mult"].notna()].reset_index(drop=True)
    for column in frame.columns:
        if column in SENSITIVE_COLUMNS:
            raise ValueError(f"sensitive multileg column escaped closed schema: {column}")
        if any(fragment in column for fragment in FORBIDDEN_OUTPUT_FRAGMENTS):
            raise ValueError(f"outcome column escaped into multileg source: {column}")
    return frame.reset_index(drop=True)


def _inventory_frame(objects: Iterable[InputObject], object_hashes: list[str]) -> pd.DataFrame:
    rows = []
    for item, object_hash in zip(objects, object_hashes, strict=True):
        rows.append(
            {
                "package_date": pd.Timestamp(item.package_date),
                "report_kind": item.report_kind,
                "container_name": item.container_name,
                "member_name": item.member_name,
                "container_sha256": item.container_sha256,
                "object_sha256": object_hash,
                "raw_size": item.raw_size,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["package_date", "report_kind", "container_name", "member_name"],
        ignore_index=True,
    )


def _empty_table(kind: str) -> pd.DataFrame:
    return parse_report_bytes(
        kind,
        (";".join(_published_columns(kind)) + "\n").encode("utf-8"),
        date(2021, 1, 1),
    ).iloc[0:0]


def _complete_dictionary_groups(dictionary: pd.DataFrame) -> bool:
    if dictionary.empty:
        return False
    required = dictionary[["event_date", "isin", "num_legs", "isin_leg", "vol"]]
    for _, group in required.groupby(["event_date", "isin"], dropna=False):
        if (
            len(group) != 2
            or group["num_legs"].nunique(dropna=False) != 1
            or int(group["num_legs"].iloc[0]) != 2
            or group["isin_leg"].nunique(dropna=False) != 2
            or set(group["vol"].astype(int)) != {-1, 1}
        ):
            return False
    return True


def _all_deals_have_dictionary(
    deals: pd.DataFrame, dictionary: pd.DataFrame
) -> bool:
    if deals.empty:
        return True
    if dictionary.empty:
        return False
    known = set(zip(dictionary["event_date"], dictionary["isin"], strict=True))
    observed = set(zip(deals["event_date"], deals["isin"], strict=True))
    return observed <= known


def _participant_leg_link_complete(
    participant: pd.DataFrame, legs: pd.DataFrame
) -> bool:
    if participant.empty:
        return True
    if legs.empty:
        return False
    distinct_legs = legs.groupby(["event_date", "id_mult"])["isin"].nunique()
    for row in participant[["event_date", "id_deal"]].itertuples(index=False):
        if distinct_legs.get((row.event_date, row.id_deal), 0) != 2:
            return False
    return True


def _participant_legs_match_dictionary(
    participant: pd.DataFrame,
    legs: pd.DataFrame,
    dictionary: pd.DataFrame,
) -> bool:
    if participant.empty:
        return True
    if legs.empty or dictionary.empty:
        return False
    expected = dictionary.groupby(["event_date", "isin"])["isin_leg"].agg(
        lambda values: frozenset(values.dropna())
    )
    actual = legs.groupby(["event_date", "id_mult"])["isin"].agg(
        lambda values: frozenset(values.dropna())
    )
    for row in participant[["event_date", "isin", "id_deal"]].itertuples(index=False):
        if actual.get((row.event_date, row.id_deal)) != expected.get(
            (row.event_date, row.isin)
        ):
            return False
    return True


def _participant_order_link_complete(
    participant: pd.DataFrame, order_log: pd.DataFrame
) -> bool:
    if participant.empty:
        return True
    if order_log.empty:
        return False
    known = set(order_log["numb_order"].dropna())
    for row in participant[["no_buy", "no_sell"]].itertuples(index=False):
        linked = {value for value in row if not pd.isna(value)}
        if not linked or not linked <= known:
            return False
    return True


def _participant_fee_fields_complete(participant: pd.DataFrame) -> bool:
    if participant.empty:
        return True
    fee_columns = (
        "fee_buy",
        "fee_sell",
        "fee_ex_b",
        "fee_cc_b",
        "fee_ex_s",
        "fee_cc_s",
    )
    return bool(participant[list(fee_columns)].notna().any(axis=1).all())


def _core_date_coverage(
    inventory: pd.DataFrame, protocol: MultilegSourceProtocol
) -> tuple[bool, bool, int]:
    kind_dates = {
        kind: set(
            inventory.loc[inventory["report_kind"].eq(kind), "package_date"].dt.date
        )
        for kind in MARKET_CORE_KINDS
    }
    equal = bool(kind_dates["multileg_dict"]) and kind_dates[
        "multileg_dict"
    ] == kind_dates["multileg_deal"]
    all_dates = sorted(kind_dates["multileg_dict"] & kind_dates["multileg_deal"])
    if not all_dates:
        return equal, False, 0
    maximum_gap = max(
        (right - left).days for left, right in zip(all_dates, all_dates[1:], strict=False)
    ) if len(all_dates) > 1 else 0
    bounded = (
        all_dates[0] <= protocol.period_start + timedelta(days=14)
        and all_dates[-1] >= protocol.period_end - timedelta(days=14)
        and maximum_gap <= 14
    )
    return equal, bounded, maximum_gap


def preflight_source(protocol: MultilegSourceProtocol) -> SourcePreflight:
    """Parse local licensed bytes and evaluate source-only completeness gates."""
    objects = discover_input_objects(protocol)
    frames: dict[str, list[pd.DataFrame]] = defaultdict(list)
    object_hashes: list[str] = []
    for item in objects:
        payload = _read_object_bytes(item)
        object_hash = hashlib.sha256(payload).hexdigest()
        object_hashes.append(object_hash)
        frames[item.report_kind].append(
            parse_report_bytes(
                item.report_kind,
                payload,
                item.package_date,
                source_object=f"{item.container_name}!{item.member_name}",
                container_sha256=item.container_sha256,
            )
        )
    tables = {
        kind: (
            pd.concat(frames[kind], ignore_index=True)
            if frames[kind]
            else _empty_table(kind)
        )
        for kind in REPORT_KINDS
    }
    inventory = _inventory_frame(objects, object_hashes) if objects else pd.DataFrame(
        columns=(
            "package_date",
            "report_kind",
            "container_name",
            "member_name",
            "container_sha256",
            "object_sha256",
            "raw_size",
        )
    )
    dictionary = tables["multileg_dict"]
    deals = tables["multileg_deal"]
    participant = tables["participant_multileg_deal"]
    order_log = tables["participant_multileg_order_log"]
    legs = tables["participant_leg_deal"]
    core_dates_equal, full_period_bounded, maximum_gap = _core_date_coverage(
        inventory, protocol
    )
    protected_absent = all(
        table.empty
        or pd.to_datetime(table["event_date"]).dt.date.lt(protocol.protected_from).all()
        for table in tables.values()
    )
    deals_unique = deals.empty or not deals.duplicated(["event_date", "id_deal"]).any()
    checks = {
        "input_objects_nonempty": bool(objects),
        "protected_market_rows_absent": bool(protected_absent),
        "market_core_report_kinds_present": all(
            inventory["report_kind"].eq(kind).any() for kind in MARKET_CORE_KINDS
        ),
        "market_core_object_date_sets_equal": bool(core_dates_equal),
        "full_period_core_coverage_bounded": bool(full_period_bounded),
        "dictionary_exact_two_signed_legs": _complete_dictionary_groups(dictionary),
        "market_deal_identity_unique": bool(deals_unique),
        "all_market_deals_have_same_day_dictionary": _all_deals_have_dictionary(
            deals, dictionary
        ),
        "participant_leg_link_complete_if_present": _participant_leg_link_complete(
            participant, legs
        ),
        "participant_legs_match_dictionary_if_present": (
            _participant_legs_match_dictionary(participant, legs, dictionary)
        ),
        "participant_order_link_complete_if_present": _participant_order_link_complete(
            participant, order_log
        ),
        "participant_fee_fields_complete_if_present": _participant_fee_fields_complete(
            participant
        ),
        "source_tables_have_no_sensitive_columns": all(
            not (set(table.columns) & SENSITIVE_COLUMNS) for table in tables.values()
        ),
        "source_tables_have_no_outcome_columns": all(
            not any(
                fragment in column
                for column in table.columns
                for fragment in FORBIDDEN_OUTPUT_FRAGMENTS
            )
            for table in tables.values()
        ),
    }
    counts = {
        "input_objects": len(objects),
        "core_package_dates": int(
            inventory.loc[
                inventory["report_kind"].eq("multileg_deal"), "package_date"
            ].nunique()
        ),
        "maximum_core_package_gap_days": int(maximum_gap),
        **{f"{kind}_rows": int(len(table)) for kind, table in tables.items()},
    }
    return SourcePreflight(tables=tables, inventory=inventory, checks=checks, counts=counts)


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    Path(temporary_name).unlink(missing_ok=True)
    try:
        frame.to_parquet(temporary_name, index=False)
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _artifact(path: Path, rows: int) -> dict[str, object]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": rows,
    }


def _normalized_replay_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        if pd.api.types.is_object_dtype(normalized[column].dtype) or isinstance(
            normalized[column].dtype, pd.StringDtype
        ):
            normalized[column] = normalized[column].astype("string")
    return normalized.convert_dtypes()


def build_bundle(protocol: MultilegSourceProtocol) -> Path:
    """Publish an immutable source bundle only after every sealed core gate passes."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"multileg source output already exists: {final}")
    preflight = preflight_source(protocol)
    if not all(preflight.checks.values()):
        failed = sorted(name for name, passed in preflight.checks.items() if not passed)
        raise ValueError(f"multileg source preflight failed: {failed}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        artifact_rows: dict[str, tuple[Path, int]] = {}
        inventory_path = temporary / "inventory.parquet"
        _write_parquet(inventory_path, preflight.inventory)
        artifact_rows["inventory"] = (inventory_path, len(preflight.inventory))
        for kind, table in preflight.tables.items():
            path = temporary / f"{kind}.parquet"
            _write_parquet(path, table)
            artifact_rows[kind] = (path, len(table))
        audit_path = temporary / "audit.json"
        write_json(audit_path, {"checks": preflight.checks, "counts": preflight.counts})
        artifact_rows["audit"] = (audit_path, len(preflight.checks))
        artifacts = {
            name: _artifact(path, rows) for name, (path, rows) in artifact_rows.items()
        }
        manifest = {
            "schema_version": 1,
            "bundle_id": "moex-multileg-execution-2021-2025-v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": protocol.dependency_hashes,
            "source": "licensed_or_member_official_MOEX_multileg_reports",
            "source_only": True,
            "contains_returns_targets_labels_signals_equity_or_pnl": False,
            "live_trading_allowed": False,
            "redistribution_forbidden_until_license_review": True,
            "period": {
                "start": protocol.period_start.isoformat(),
                "end": protocol.period_end.isoformat(),
                "protected_from": protocol.protected_from.isoformat(),
            },
            "temporal_semantics": {
                "event_at_is_execution_replay_only": True,
                "same_day_signal_use_forbidden": True,
                "report_available_at": "next_calendar_day_00_00_Europe_Moscow",
            },
            "checks": preflight.checks,
            "counts": preflight.counts,
            "artifacts": artifacts,
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{sha256_file(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_bundle(protocol: MultilegSourceProtocol) -> SourceAudit:
    """Replay licensed inputs and verify every published artifact byte/hash/row count."""
    root = protocol.output_directory
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError(f"multileg source bundle incomplete: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    sidecar_sha = sidecar_path.read_text(encoding="utf-8-sig").split()[0]
    replay = preflight_source(protocol)
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar_sha == sha256_file(manifest_path),
        "protocol_sha_exact": manifest.get("protocol_sha256") == protocol.config_sha256,
        "implementation_sha_exact": manifest.get("implementation_sha256")
        == protocol.dependency_hashes,
        "source_only": manifest.get("source_only") is True,
        "live_forbidden": manifest.get("live_trading_allowed") is False,
        "protected_absent_declared": manifest.get("period", {}).get("protected_from")
        == protocol.protected_from.isoformat(),
        "replay_checks_exact": manifest.get("checks") == replay.checks,
        "replay_counts_exact": manifest.get("counts") == replay.counts,
    }
    replay_tables = {"inventory": replay.inventory, **replay.tables}
    for name, metadata in manifest.get("artifacts", {}).items():
        path = root / str(metadata["path"])
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == int(
            metadata["bytes"]
        )
        checks[f"{name}_sha256"] = path.is_file() and sha256_file(path) == metadata[
            "sha256"
        ]
        if name in replay_tables and path.is_file():
            stored = pd.read_parquet(path)
            expected = replay_tables[name]
            checks[f"{name}_rows"] = len(stored) == int(metadata["rows"])
            try:
                pd.testing.assert_frame_equal(
                    _normalized_replay_frame(stored),
                    _normalized_replay_frame(expected),
                    check_dtype=False,
                )
            except AssertionError:
                checks[f"{name}_replay_exact"] = False
            else:
                checks[f"{name}_replay_exact"] = True
    return SourceAudit(checks=checks, counts=replay.counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol(arguments.config)
    if arguments.preflight:
        result = preflight_source(protocol)
        print(json.dumps({"checks": result.checks, "counts": result.counts}, indent=2))
        return 0
    if arguments.audit_only:
        result = audit_bundle(protocol)
        print(json.dumps({"checks": result.checks, "counts": result.counts}, indent=2))
        return 0
    output = build_bundle(protocol)
    result = audit_bundle(protocol)
    print(output)
    print(json.dumps({"checks": result.checks, "counts": result.counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
