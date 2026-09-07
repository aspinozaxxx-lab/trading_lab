"""Manifest-bound <=2025 price inputs for the separately authorized AlgoPack paper arm.

Preflight reads only manifests, byte hashes, Parquet metadata and time/identity columns.
Price materialization is an explicit separate call; no network, training or live orders.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath

import pandas as pd
import pyarrow.parquet as pq

ALIASES = {"Si": "SI", "RTS": "RI", "BR": "BR", "MIX": "MIX"}
PROTECTED = pd.Timestamp("2026-01-01", tz="UTC")
TIME_COLUMNS = ["timestamp", "end_timestamp", "canonical_contract_id"]
PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe(root: Path, relative: str) -> Path:
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root.absolute():
        raise ValueError("input root must be absolute without symlink ancestors")
    parsed = PurePosixPath(relative)
    if (
        not relative
        or parsed.is_absolute()
        or parsed.as_posix() != relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or any(char in relative for char in "\\:\x00")
    ):
        raise ValueError("noncanonical input path")
    path = root
    for number, part in enumerate(("", *parsed.parts)):
        if part:
            path /= part
        info = path.lstat()
        is_directory = number < len(parsed.parts)
        valid = stat.S_ISDIR(info.st_mode) if is_directory else stat.S_ISREG(info.st_mode)
        if not valid or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("nonordinary input path")
    return path


def count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("count must be a nonnegative integer")
    return value


def verified(root: Path, record: dict) -> Path:
    path = safe(root, record["path"])
    if (
        count(record["bytes"]) != path.stat().st_size
        or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
        or digest(path) != record["sha256"]
    ):
        raise ValueError("input byte identity mismatch")
    return path


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def read_manifest(root: Path, record: dict) -> dict:
    path = verified(root, record)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("manifest changed while reading")
    result = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(result, dict):
        raise ValueError("manifest is not a mapping")
    return result


def _time_frame(path: Path, record: dict, contract_id: str) -> pd.DataFrame:
    if pq.ParquetFile(path).metadata.num_rows != count(record["rows"]):
        raise ValueError("Parquet row count mismatch")
    frame = pd.read_parquet(path, columns=TIME_COLUMNS)
    begin = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    end = pd.to_datetime(frame["end_timestamp"], utc=True, errors="raise")
    if (
        begin.isna().any()
        or end.isna().any()
        or begin.ge(PROTECTED).any()
        or end.ge(PROTECTED).any()
        or end.lt(begin).any()
    ):
        raise ValueError("protected or invalid source time")
    if (
        frame["canonical_contract_id"].isna().any()
        or not frame["canonical_contract_id"].eq(contract_id).all()
    ):
        raise ValueError("Parquet contract identity mismatch")
    if begin.duplicated().any() or not begin.is_monotonic_increasing:
        raise ValueError("duplicate or unordered source timestamps")
    if digest(path) != record["sha256"]:
        raise ValueError("Parquet changed during metadata projection")
    return pd.DataFrame({"begin": begin, "end": end})


def inspect_intraday(root: Path, top_identity: dict) -> tuple[dict, list[dict]]:
    """Full transitive BYTE verification, not a claim of raw-to-price semantic replay."""
    top = read_manifest(root, top_identity)
    if top.get("requested_end") != "2025-12-31" or top.get("protected_from") != "2026-01-01":
        raise ValueError("top-level protected boundary mismatch")
    if top.get("namespace") != "futures_v7_10m":
        raise ValueError("unexpected intraday namespace")
    assets = top["assets"]
    if len(assets) != 4 or {item["asset_code"] for item in assets} != set(ALIASES):
        raise ValueError("exact four source assets required")
    artifacts, identities = [], [dict(top_identity)]
    totals = dict(assets=4, segments=0, empty_segments=0, rows=0, pages=0)
    seen_paths, seen_segments = {top_identity["path"]}, set()
    for asset_ref in assets:
        if asset_ref["path"] in seen_paths:
            raise ValueError("duplicate asset path")
        seen_paths.add(asset_ref["path"])
        asset = read_manifest(root, asset_ref)
        identities.append(dict(asset_ref))
        source_asset = asset_ref["asset_code"]
        if (
            asset.get("requested_end") != "2025-12-31"
            or asset.get("protected_from") != "2026-01-01"
            or asset.get("asset", {}).get("asset_code") != source_asset
        ):
            raise ValueError("asset identity or boundary mismatch")
        subtotal = dict(segments=0, empty_segments=0, rows=0, pages=0)
        for segment_ref in asset["segment_manifests"]:
            if segment_ref["path"] in seen_paths:
                raise ValueError("duplicate segment path")
            seen_paths.add(segment_ref["path"])
            segment = read_manifest(root, segment_ref)
            identities.append(dict(segment_ref))
            declaration = segment["segment"]
            segment_id = declaration["canonical_segment_id"]
            if segment_id in seen_segments or segment_id != segment_ref["canonical_segment_id"]:
                raise ValueError("duplicate or mismatched segment identity")
            seen_segments.add(segment_id)
            rows, pages = count(segment_ref["rows"]), count(segment_ref["pages"])
            if pages < 1 or segment["status"] != ("complete" if rows else "complete_empty"):
                raise ValueError("segment not complete")
            if segment_ref["status"] != segment["status"]:
                raise ValueError("segment reference status mismatch")
            if (
                segment["asset"]["asset_code"] != source_asset
                or declaration["board_id"] != "RFUD"
                or declaration["requested_end"] > "2025-12-31"
                or declaration["requested_start"] > declaration["requested_end"]
            ):
                raise ValueError("segment asset/board/request boundary mismatch")
            if segment["counts"]["rows"] != rows or segment["counts"]["pages"] != pages:
                raise ValueError("segment count mismatch")
            for kind in ("raw", "parquet"):
                artifact = segment["artifacts"][kind]
                if artifact["path"] in seen_paths:
                    raise ValueError("reused artifact path")
                seen_paths.add(artifact["path"])
                path = verified(root, artifact)
                identities.append(dict(artifact))
                if count(artifact["rows"]) != rows or count(artifact["pages"]) != pages:
                    raise ValueError("artifact counts mismatch")
                if kind == "parquet":
                    times = _time_frame(path, artifact, declaration["canonical_contract_id"])
                    artifacts.append(
                        dict(
                            **artifact,
                            asset=ALIASES[source_asset],
                            secid=declaration["secid"],
                            contract_id=declaration["canonical_contract_id"],
                            segment_manifest=dict(segment_ref),
                            minimum=None if times.empty else times["begin"].min().isoformat(),
                            maximum=None if times.empty else times["end"].max().isoformat(),
                        )
                    )
            subtotal["segments"] += 1
            subtotal["empty_segments"] += int(rows == 0)
            subtotal["rows"] += rows
            subtotal["pages"] += pages
        if any(
            count(asset["counts"][key]) != value or count(asset_ref[key]) != value
            for key, value in subtotal.items()
        ):
            raise ValueError("asset aggregate mismatch")
        for key, value in subtotal.items():
            totals[key] += value
    if any(count(top["totals"][key]) != value for key, value in totals.items()):
        raise ValueError("global aggregate mismatch")
    report = dict(
        totals=totals,
        identities=identities,
        metadata_only=True,
        prices_read=False,
        semantic_raw_replay=False,
        protected_from="2026-01-01",
    )
    return report, artifacts


def load_price_artifact(root: Path, record: dict) -> pd.DataFrame:
    """Explicit post-seal value load; repeat time-only gate before OHLCV projection."""
    segment = read_manifest(root, record["segment_manifest"])
    source = segment["segment"]
    if (
        source["canonical_contract_id"] != record["contract_id"]
        or source["secid"] != record["secid"]
        or ALIASES[segment["asset"]["asset_code"]] != record["asset"]
        or any(record[key] != value for key, value in segment["artifacts"]["parquet"].items())
    ):
        raise ValueError("derived artifact identity differs from segment manifest")
    path = verified(root, record)
    _time_frame(path, record, record["contract_id"])
    frame = pd.read_parquet(path, columns=TIME_COLUMNS + PRICE_COLUMNS)
    if digest(path) != record["sha256"]:
        raise ValueError("price artifact changed during materialization")
    frame["asset"] = record["asset"]
    frame["secid"] = record["secid"]
    return frame


def load_active_plan(root: Path, record: dict) -> pd.DataFrame:
    """Read only date/contract eligibility metadata; no prices or future targets."""
    path = verified(root, record)
    columns = [
        "effective_date",
        "decision_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "secid",
        "plan_tradable",
    ]
    plan = pd.read_parquet(path, columns=columns)
    if len(plan) != count(record["rows"]) or digest(path) != record["sha256"]:
        raise ValueError("active map count or identity mismatch")
    for column in columns[:3]:
        value = pd.to_datetime(plan[column], errors="raise")
        if (
            value.dt.tz is not None
            or value.isna().any()
            or not value.eq(value.dt.normalize()).all()
        ):
            raise ValueError("active map requires nonmissing naive calendar dates")
        if value.ge(pd.Timestamp("2026-01-01")).any():
            raise ValueError("active map touches protected 2026")
        plan[column] = value
    plan["asset"] = plan["asset_code"].str.upper().replace({"RTS": "RI"})
    if not plan["asset"].isin(ALIASES.values()).all():
        raise ValueError("unknown active-map asset")
    eligible = (
        plan["plan_tradable"].astype("boolean").fillna(False)
        & plan["observed_through"].le(plan["decision_date"])
        & plan["decision_date"].lt(plan["effective_date"])
        & plan["contract_id"].notna()
        & plan["secid"].notna()
        & plan["effective_date"].ge(pd.Timestamp("2020-01-01"))
    )
    plan["plan_eligible"] = eligible
    if plan.duplicated(["effective_date", "asset"]).any():
        raise ValueError("duplicate active-map date/asset")
    # Keep ineligible plan rows visible for the future decision calendar/coverage report.
    return plan.sort_values(["effective_date", "asset"], kind="stable").reset_index(drop=True)
