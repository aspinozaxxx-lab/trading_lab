"""Closed description inventory and complete release-calendar join for V90/V91."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from market_lab import futures_v68_reported_option_flow as reporting
from market_lab.futures import option_contract_mapping as mapper
from market_lab.futures import option_strike_convergence as rule

base = reporting.base
SOURCE_METADATA = {
    "tradedate",
    "logical_asset",
    "secid",
    "boardid",
    "available_at_utc",
    "option_type",
}
SOURCE_COLUMNS = SOURCE_METADATA | {"openposition"}
FEATURE_METADATA = rule.OPTION_COLUMNS - {
    "tradedate",
    "boardid",
    "available_at_utc",
    "openposition",
}
MAPPING_COLUMNS = FEATURE_METADATA | {
    "mapping_reason",
    "description_sha256",
    "catalog_evidence_sha256",
    "source_record_sha256",
    "needs_description",
}
CALENDAR_COLUMNS = {"tradedate", "logical_asset", "available_at_utc", "source_rows"}
MARKER = "__V92_EMPTY_RELEASE__"


def checked_json(path, expected):
    raw = path.read_bytes()
    base.require(mapper.digest(raw) == expected, "JSON input hash mismatch")
    return json.loads(raw)


def source_calendar(requests, metadata, config):
    """Calendar is the sealed request grid, not only rows surviving a data join."""
    base.require(set(metadata.columns) == SOURCE_METADATA, "source metadata columns only")
    d = metadata.copy()
    d["tradedate"] = rule.days(d.tradedate)
    d["available_at_utc"] = pd.to_datetime(d.available_at_utc, utc=True)
    floor = (d.tradedate.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).dt.tz_convert(
        "UTC"
    )
    base.require(
        d.available_at_utc.notna().all() and d.available_at_utc.ge(floor).all(),
        "source availability before next-day floor",
    )
    base.require(
        d.logical_asset.isin(rule.ASSETS).all()
        and d.option_type.isin(["call", "put"]).all()
        and d[["secid", "boardid"]].notna().all().all()
        and not d.duplicated(["tradedate", "logical_asset", "boardid", "secid"]).any(),
        "source metadata identities",
    )
    reverse = {v[0]: k for k, v in mapper.FUTURES_ASSET_REGISTRY.items()}
    jobs = set()
    for record in requests:
        day = mapper.exact_day(record["query_date"])
        base.require(
            pd.Timestamp(day) < base.BOUNDARY and record["server_assetcode"] in reverse,
            "protected/unknown source job",
        )
        jobs.add((pd.Timestamp(day), reverse[record["server_assetcode"]]))
    calendar = pd.DataFrame(sorted(jobs), columns=["tradedate", "logical_asset"])
    spec = config["source"]
    base.require(
        len(calendar) == spec["expected_asset_dates"]
        and calendar.tradedate.nunique() == spec["expected_source_dates"]
        and calendar.groupby("tradedate").logical_asset.nunique().eq(4).all()
        and str(calendar.tradedate.min().date()) == spec["processed"]["minimum_tradedate"]
        and str(calendar.tradedate.max().date()) == spec["processed"]["maximum_tradedate"],
        "incomplete source request calendar",
    )
    counts = d.groupby(["tradedate", "logical_asset"], as_index=False).agg(
        source_rows=("secid", "size"),
        available_at_utc=("available_at_utc", "first"),
        clocks=("available_at_utc", "nunique"),
    )
    base.require(
        counts.clocks.eq(1).all()
        and set(map(tuple, counts[["tradedate", "logical_asset"]].to_numpy())) <= jobs,
        "mixed source clocks or unplanned observations",
    )
    calendar = calendar.merge(
        counts.drop(columns="clocks"),
        how="left",
        on=["tradedate", "logical_asset"],
        validate="one_to_one",
    )
    calendar["source_rows"] = calendar.source_rows.fillna(0).astype(int)
    empty_clock = (
        calendar.tradedate.dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
    ).dt.tz_convert("UTC")
    calendar["available_at_utc"] = calendar.available_at_utc.fillna(empty_clock)
    return calendar


def weekly_metadata(config, storage):
    reporting.source_preflight(config, storage)
    spec = config["source"]
    root = base.safe(storage, spec["root"])
    manifest = checked_json(root / "manifest.json", spec["manifest_sha256"])
    base.require(
        manifest["canonical_source"] is True
        and manifest["config_sha256"] == spec["source_config_sha256"]
        and manifest["decision_calendar_sha256"] == spec["decision_calendar_sha256"]
        and manifest["job_count"] == spec["expected_asset_dates"],
        "source calendar provenance",
    )
    request_spec = manifest["requests"]
    path = base.safe(root, request_spec["path"])
    base.require(path.stat().st_size == request_spec["bytes"], "request inventory bytes")
    requests = checked_json(path, request_spec["sha256"])
    base.require(len(requests) == request_spec["rows"], "request inventory rows")
    metadata = pd.read_parquet(
        base.safe(root, spec["processed"]["path"]), columns=sorted(SOURCE_METADATA)
    )
    return source_calendar(requests, metadata, config)


def closed_index(manifest, plan, config):
    """Reject partial acquisition before opening any description records."""
    spec = config["descriptions"]
    base.require(
        manifest["status"] in ("SOURCE_COMPLETE", "COMPLETE_WITH_SOURCE_GAPS")
        and manifest["processed"] == manifest["planned"] == spec["expected_descriptions"]
        and manifest["seal_sha256"] == spec["source_seal_sha256"]
        and manifest["census_manifest_sha256"] == config["census"]["manifest_sha256"]
        and manifest["economic_admission"] is False
        and bool(manifest.get("completed_at_utc")),
        "closed full description source required",
    )
    need = rule.flag(plan.needs_description)
    base.require(
        len(plan) == config["census"]["expected_contracts"]
        and not plan.secid.duplicated().any()
        and int(need.sum()) == spec["expected_descriptions"]
        and plan.logical_asset.isin(rule.ASSETS).all(),
        "census identity/size",
    )
    records = manifest["records"]
    keys = [(r["logical_asset"], r["secid"]) for r in records]
    selected = set(map(tuple, plan.loc[need, ["logical_asset", "secid"]].to_numpy()))
    base.require(
        len(keys) == len(set(keys)) == spec["expected_descriptions"] and set(keys) == selected,
        "description index differs from full census",
    )
    return {key: record for key, record in zip(keys, records, strict=True)}


def empty_mapping(secid, asset, catalog_sha, needed=False, reason="ALL_NULL_NOT_REQUESTED"):
    out = dict.fromkeys(MAPPING_COLUMNS)
    out.update(
        secid=secid,
        logical_asset=asset,
        metadata_ready=False,
        option_class="unknown",
        quote_units_compatible=False,
        needs_description=needed,
        mapping_reason=reason,
        catalog_evidence_sha256=catalog_sha,
    )
    return out


def map_closed_descriptions(config, storage, source_sha, catalog):
    root = base.safe(storage, config["descriptions"]["root"])
    manifest = checked_json(root / "manifest.json", source_sha)
    census_root = base.safe(storage, config["census"]["root"])
    census = checked_json(census_root / "manifest.json", config["census"]["manifest_sha256"])
    base.require(
        census["seal_sha256"] == config["descriptions"]["source_seal_sha256"], "census source seal"
    )
    plan_path = census_root / "contracts.parquet"
    base.require(
        base.sha(plan_path)
        == census["artifacts"]["contracts.parquet"]
        == config["census"]["contracts_sha256"],
        "census contracts hash",
    )
    plan = pd.read_parquet(plan_path)
    index = closed_index(manifest, plan, config)
    for column in ("first_seen", "last_seen"):
        values = rule.days(plan[column])
        base.require(values.between("2021-01-01", "2025-12-31").all(), "census source period")
    reuse = base.safe(storage, config["descriptions"]["reuse_root"])
    checked_json(reuse / "manifest.json", config["descriptions"]["reuse_manifest_sha256"])
    result = []
    for row in plan.itertuples(index=False):
        out = empty_mapping(
            row.secid, row.logical_asset, catalog.evidence_sha256, bool(row.needs_description)
        )
        if row.needs_description:
            entry = index[(row.logical_asset, row.secid)]
            record = checked_json(base.safe(root, entry["record"]), entry["sha256"])
            base.require(
                record["kind"] == "description"
                and record["identity"] == {"secid": row.secid, "asset": row.logical_asset}
                and record["url"]
                == config["descriptions"]["url"].format(secid=quote(row.secid, safe="")),
                "description record identity",
            )
            out.update(
                source_record_sha256=entry["sha256"],
                mapping_reason="DESCRIPTION_SOURCE_UNAVAILABLE",
            )
            if record.get("raw"):
                spec = record["raw"]
                path = Path(spec["path"])
                allowed = reuse if record["reference_reused"] else root
                base.require(
                    path.is_absolute() and path.resolve().is_relative_to(allowed),
                    "description raw path escape",
                )
                if record["reference_reused"]:
                    base.require(
                        spec["source_manifest_sha256"]
                        == config["descriptions"]["reuse_manifest_sha256"],
                        "reused source provenance",
                    )
                raw = path.read_bytes()
                base.require(
                    len(raw) == spec["bytes"] and mapper.digest(raw) == spec["sha256"],
                    "description raw drift",
                )
                out["description_sha256"] = spec["sha256"]
                if record["attempts"] and record["attempts"][-1].get("http_status") == 200:
                    bound = mapper.map_description(
                        raw,
                        spec["sha256"],
                        secid=row.secid,
                        logical_asset=row.logical_asset,
                        catalog=catalog,
                    )
                    out.update({k: bound[k] for k in FEATURE_METADATA})
                    out["mapping_reason"] = bound["reason"]
        result.append(out)
    frame = pd.DataFrame(result, columns=sorted(MAPPING_COLUMNS))
    base.require(len(frame) == len(plan), "no census rows may disappear")
    return frame


def assemble_options(raw, mapping, calendar):
    """Many-to-one exact metadata join; explicit empty releases carry NULL, never zero OI."""
    base.require(
        set(raw.columns) == SOURCE_COLUMNS
        and set(mapping.columns) == MAPPING_COLUMNS
        and set(calendar.columns) == CALENDAR_COLUMNS,
        "assembly schema; no extra values",
    )
    base.require(not mapping.duplicated(["logical_asset", "secid"]).any(), "duplicate mapping")
    d = raw.copy()
    d["tradedate"] = rule.days(d.tradedate)
    d["available_at_utc"] = pd.to_datetime(d.available_at_utc, utc=True)
    base.require(
        d.option_type.isin(["call", "put"]).all()
        and not d.secid.astype(str).str.startswith(MARKER).any(),
        "source side/marker collision",
    )
    d = d.rename(columns={"option_type": "source_option_type"}).merge(
        mapping[sorted(FEATURE_METADATA)],
        how="left",
        on=["logical_asset", "secid"],
        validate="many_to_one",
        indicator=True,
    )
    base.require(d._merge.eq("both").all(), "unrepresented source identity")
    d["metadata_ready"], d["quote_units_compatible"] = (
        rule.flag(d.metadata_ready),
        rule.flag(d.quote_units_compatible),
    )
    conflict = (
        d.metadata_ready
        & d.option_class.eq("margined_future_option")
        & d.option_type.ne(d.source_option_type)
    )
    d.loc[conflict, ["metadata_ready", "quote_units_compatible"]] = False
    d = d[sorted(rule.OPTION_COLUMNS)]
    c = calendar.copy()
    c["tradedate"] = rule.days(c.tradedate)
    c["available_at_utc"] = pd.to_datetime(c.available_at_utc, utc=True)
    base.require(
        not c.duplicated(["tradedate", "logical_asset"]).any()
        and c.logical_asset.isin(rule.ASSETS).all()
        and c.groupby("tradedate").logical_asset.nunique().eq(4).all(),
        "joint release calendar",
    )
    counts = d.groupby(["tradedate", "logical_asset"], as_index=False).agg(
        actual_rows=("secid", "size"),
        actual_clock=("available_at_utc", "first"),
        clock_count=("available_at_utc", "nunique"),
    )
    c = c.merge(
        counts,
        how="outer",
        on=["tradedate", "logical_asset"],
        validate="one_to_one",
        indicator=True,
    )
    base.require(
        c._merge.ne("right_only").all() and c.actual_rows.fillna(0).eq(c.source_rows).all(),
        "source calendar count mismatch",
    )
    nonempty = c.source_rows.gt(0)
    base.require(
        c.loc[nonempty, "clock_count"].eq(1).all()
        and c.loc[nonempty, "actual_clock"].eq(c.loc[nonempty, "available_at_utc"]).all(),
        "source calendar clock mismatch",
    )
    empty = c.loc[~nonempty]
    markers = []
    for row in empty.itertuples(index=False):
        marker = dict.fromkeys(rule.OPTION_COLUMNS)
        marker.update(
            tradedate=row.tradedate,
            logical_asset=row.logical_asset,
            secid=f"{MARKER}{row.logical_asset}_{row.tradedate:%Y%m%d}",
            boardid=MARKER,
            available_at_utc=row.available_at_utc,
            openposition=np.nan,
            metadata_ready=False,
            quote_units_compatible=False,
            option_class="unknown",
        )
        markers.append(marker)
    if markers:
        # A missing observation must remain representable even if every original OI was integer.
        d["openposition"] = pd.to_numeric(d.openposition, errors="coerce").astype(float)
        marker_frame = pd.DataFrame(markers, columns=d.columns).astype(d.dtypes.to_dict())
        d = pd.concat([d, marker_frame], ignore_index=True)
        d["metadata_ready"], d["quote_units_compatible"] = (
            rule.flag(d.metadata_ready),
            rule.flag(d.quote_units_compatible),
        )
    return d, {
        "original_source_rows": len(raw),
        "empty_release_markers": len(markers),
        "source_side_conflict_rows": int(conflict.sum()),
    }


def release_quality(options, calendar):
    prepared, _ = rule.prepare_options(options)
    prepared["unresolved_mapping"] = prepared.oi_usable & ~(
        prepared.mapping_ok | prepared.explicit_nonfuture
    )
    prepared["mapped_reported_future"] = prepared.oi_usable & prepared.mapping_ok
    counts = prepared.groupby(["tradedate", "logical_asset"], as_index=False).agg(
        usable_oi_rows=("oi_usable", "sum"),
        unusable_oi_rows=("oi_unusable", "sum"),
        explicit_nonfuture_rows=("explicit_nonfuture", "sum"),
        unresolved_reported_rows=("unresolved_mapping", "sum"),
        mapped_reported_future_rows=("mapped_reported_future", "sum"),
    )
    out = calendar.merge(
        counts, how="left", on=["tradedate", "logical_asset"], validate="one_to_one"
    )
    base.require(out.usable_oi_rows.notna().all(), "missing release markers")
    out["mapping_ready"] = out.mapped_reported_future_rows.gt(0) & out.unresolved_reported_rows.eq(
        0
    )
    return out
