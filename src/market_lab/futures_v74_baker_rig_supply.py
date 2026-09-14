"""Fixed Baker Hughes US oil-rig supply screen; cached source cells, no model fit."""

from __future__ import annotations

import argparse
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v64_si_tax_calendar as base
from market_lab import futures_v68_reported_option_flow as shared
from market_lab import futures_v72_policy_guidance as adapter

CONFIG = base.PROJECT / "configs/v74_baker_rig_supply_v1.json"
SEAL = base.PROJECT / "configs/v74_baker_rig_supply_v1.seal.json"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADERS = [
    "Country",
    "County",
    "Basin",
    "GOM",
    "DrillFor",
    "Location",
    "State/Province",
    "Trajectory",
    "Year",
    "Month",
    "US_PublishDate",
    "Rig Count Value",
]


def cells(archive, part, strings):
    """Stream saved values only. Never execute formulas, links, refreshes or macros."""
    with archive.open(part) as stream:
        for _, row in ET.iterparse(stream, events=("end",)):
            if row.tag != NS + "row":
                continue
            result = {}
            for cell in row.findall(NS + "c"):
                column = "".join(c for c in cell.attrib["r"] if c.isalpha())
                value = cell.find(NS + "v")
                kind = cell.attrib.get("t")
                if kind == "inlineStr":
                    value = "".join(n.text or "" for n in cell.iter(NS + "t"))
                elif value is None or value.text is None:
                    value = None
                elif kind == "s":
                    value = strings[int(value.text)]
                elif kind in ("str", "e"):
                    value = value.text
                else:
                    value = float(value.text)
                result[column] = value
            yield int(row.attrib["r"]), result
            row.clear()


def excel_day(value):
    base.require(
        isinstance(value, (int, float)) and np.isfinite(value) and value == int(value),
        "invalid Excel publication date",
    )
    return pd.Timestamp(datetime(1899, 12, 30) + timedelta(days=int(value)))


def read_rigs(path):
    """All raw subgroups validated before selection; oil totals reconciled to summary."""
    totals, oil, rows_by_date = defaultdict(int), defaultdict(int), defaultdict(list)
    dates, countries, unique = set(), set(), set()
    ambiguous, duplicate_rows, missing_county = set(), 0, 0
    count, header = 0, False
    with zipfile.ZipFile(path) as archive:
        base.require(not any("vbaProject" in n for n in archive.namelist()), "unexpected macro")
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        props = wb.find(NS + "workbookPr")
        base.require(
            props is None or props.attrib.get("date1904", "0") in ("0", "false"),
            "unsupported Excel epoch",
        )
        sheets = {
            n.attrib["name"]: n.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            for n in wb.find(NS + "sheets")
        }
        relationships = {
            n.attrib["Id"]: n.attrib["Target"]
            for n in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }

        def part(name):
            target = relationships[sheets[name]]
            base.require(".." not in target.split("/"), "unsafe worksheet part")
            return target.lstrip("/") if target.startswith("/") else "xl/" + target

        strings = [
            "".join(n.text or "" for n in entry.iter(NS + "t"))
            for entry in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        ]
        for number, row in cells(archive, part("NAM Weekly"), strings):
            if number < 11:
                continue
            if number == 11:
                base.require(
                    [row.get(chr(65 + i)) for i in range(12)] == HEADERS, "weekly schema drift"
                )
                header = True
                continue
            if not any(v is not None for v in row.values()):
                continue
            values = [row.get(chr(65 + i)) for i in range(12)]
            base.require(
                all(v is not None for i, v in enumerate(values) if i != 1),
                "missing required subgroup cell",
            )
            missing_county += int(values[1] is None)
            country, drill, value = values[0], values[4], values[11]
            base.require(country in ("UNITED STATES", "CANADA"), "unknown country/total row")
            base.require(drill in ("Oil", "Gas", "Miscellaneous"), "unknown drill type")
            base.require(
                isinstance(value, (int, float))
                and np.isfinite(value)
                and value >= 0
                and value == int(value),
                "invalid rig count",
            )
            day = excel_day(values[10])
            base.require(pd.Timestamp("2013-01-01") <= day < base.BOUNDARY, "protected source date")
            base.require((day.year, day.month) == (values[8], values[9]), "period mismatch")
            key = tuple(values[:11])
            if key in unique:
                ambiguous.add(day)
                duplicate_rows += 1
            unique.add(key)
            dates.add(day)
            countries.add(country)
            count += 1
            if country == "UNITED STATES":
                totals[day] += int(value)
                if drill == "Oil":
                    oil[day] += int(value)
                    rows_by_date[day].append(number)
        base.require(header and countries == {"UNITED STATES", "CANADA"}, "missing source")
        base.require(dates == set(totals) == set(oil), "missing weekly US oil coverage")
        summary = {number: row for number, row in cells(archive, part("NAM Summary"), strings)}
        latest = excel_day(summary[4]["D"])
        base.require(latest == max(dates), "summary date drift")
        base.require(latest not in ambiguous, "ambiguous summary cannot validate totals")
        base.require(
            summary[11]["B"] == "United States Total" and summary[22]["B"] == "Oil",
            "summary labels drift",
        )
        base.require(
            totals[latest] == summary[11]["D"] and oil[latest] == summary[22]["D"],
            "aggregate does not reconcile to publisher summary",
        )
    result = pd.DataFrame(
        [
            {
                "source_date": day,
                "oil_rigs": float(oil[day]) if day not in ambiguous else np.nan,
                "total_us_rigs": float(totals[day]) if day not in ambiguous else np.nan,
                "ambiguous_week": day in ambiguous,
                "oil_source_rows": len(rows_by_date[day]),
                "first_oil_excel_row": min(rows_by_date[day]),
                "last_oil_excel_row": max(rows_by_date[day]),
            }
            for day in sorted(dates)
        ]
    )
    return result, {
        "all_true": True,
        "raw_subgroup_rows": count,
        "weekly_dates": len(result),
        "duplicate_subgroup_records": duplicate_rows,
        "missing_county_rows": missing_county,
        "ambiguous_weekly_dates": len(ambiguous),
        "ambiguous_dates": [str(d.date()) for d in sorted(ambiguous)],
        "minimum_date": str(min(dates).date()),
        "maximum_date": str(max(dates).date()),
        "summary_reconciled": True,
        "original_vintages_proved": False,
    }


def states(rigs, cfg):
    frame = rigs.sort_values("source_date", ignore_index=True).copy()
    frame["source_date"] = pd.to_datetime(frame.source_date)
    base.require(
        frame.source_date.notna().all() and frame.source_date.lt(base.BOUNDARY).all(),
        "protected/null source",
    )
    base.require(not frame.source_date.duplicated().any(), "duplicate weekly source")
    frame["ambiguous_week"] = frame.get("ambiguous_week", False)
    known = ~frame.ambiguous_week
    base.require(frame.oil_rigs.isna().eq(frame.ambiguous_week).all(), "unknown oil count")
    base.require(
        np.isfinite(frame.loc[known, "oil_rigs"]).all()
        and frame.loc[known, "oil_rigs"].ge(0).all(),
        "invalid oil count",
    )
    lookback = cfg["signal"]["lookback_releases"]
    gaps = frame.source_date.diff().dt.days
    # Holiday publication shifts are allowed; missing weeks cannot become shorter history.
    regular = gaps.between(5, 9).rolling(lookback, min_periods=lookback).sum().eq(lookback)
    frame["prior_source_date"] = frame.source_date.shift(lookback)
    frame["oil_rig_change"] = frame.oil_rigs - frame.oil_rigs.shift(lookback)
    complete_history = known.rolling(lookback + 1, min_periods=lookback + 1).sum().eq(lookback + 1)
    frame["ready"] = regular & complete_history & frame.oil_rig_change.notna()
    frame["primary_direction"] = (-np.sign(frame.oil_rig_change)).where(frame.ready, 0.0)
    frame["control_direction"] = frame.ready.astype(float)
    frame["reason"] = np.where(frame.ready, "ready", "ambiguous_incomplete_or_irregular_history")
    frame["available_at_utc"] = (
        frame.source_date.dt.tz_localize("America/Chicago")
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")
    frame["asset_code"] = "BR"
    frame["source_url"] = (
        cfg["source"]["url"] + "#US_PublishDate=" + frame.source_date.dt.strftime("%Y-%m-%d")
    )
    return frame


def load(expected):
    base.require(base.sha(SEAL) == expected, "V74 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8-sig"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V74 frozen file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    _, parent = adapter.load(cfg["parent_v72_seal_sha256"])
    base.require(cfg["assets"] == ["BR"] and cfg["protected_from"] == "2026-01-01", "scope drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg, parent


def preflight(cfg, parent, storage):
    declaration = cfg["source"]
    path = base.safe(storage, declaration["path"])
    base.require(
        path.stat().st_size == declaration["bytes"] and base.sha(path) == declaration["sha256"],
        "source workbook drift",
    )
    rigs, quality = read_rigs(path)
    for key in (
        "raw_subgroup_rows",
        "weekly_dates",
        "minimum_date",
        "maximum_date",
        "duplicate_subgroup_records",
        "missing_county_rows",
        "ambiguous_weekly_dates",
    ):
        base.require(quality[key] == declaration[key], "source metadata drift: " + key)
    return (
        rigs,
        quality,
        {
            "source": declaration,
            "source_checks": quality,
            "futures": base.preflight(parent, storage),
            "all_true": True,
        },
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--storage-root", required=True, type=Path)
    cli.add_argument("--audit", action="store_true")
    args = cli.parse_args()
    base.require(
        os.name == "posix" and str(args.storage_root.resolve()) == "/srv/trading_lab_data",
        "server only",
    )
    cfg, parent = load(args.seal_sha)
    rigs, quality, verified = preflight(cfg, parent, args.storage_root)
    output = base.safe(args.storage_root, "runs/" + cfg["protocol_id"] + "_" + args.seal_sha[:12])
    if args.audit:
        identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
        base.require(identity["seal_sha256"] == args.seal_sha, "run seal drift")
        for name, digest in identity["files"].items():
            base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    else:
        output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    state = states(rigs, cfg)
    declarations = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(args.storage_root, declarations["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    signals = {arm: adapter.targets(active, state, arm, cfg) for arm in ("primary", "control")}
    signal = signals["primary"]
    quality.update(
        ready_asset_date_fraction=float(
            (~(signal.feature_unavailable | signal.stale_at_fill)).mean()
        ),
        source_state_rows=len(state),
        ready_states=int(state.ready.sum()),
    )
    counts = {
        arm: {
            "decisions": len(s),
            "nonzero_targets": int(s.target_weight.ne(0).sum()),
            "used_releases": int(s.loc[s.target_weight.ne(0), "source_url"].nunique()),
            "feature_unavailable": int(s.feature_unavailable.sum()),
            "stale_at_fill": int(s.stale_at_fill.sum()),
            "source_unavailable": int(s.source_unavailable.sum()),
        }
        for arm, s in signals.items()
    }
    if args.audit:
        pd.testing.assert_frame_equal(rigs, pd.read_parquet(output / "rig_counts.parquet"))
        pd.testing.assert_frame_equal(state, pd.read_parquet(output / "rig_states.parquet"))
        payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        base.require(
            payload["source_quality"] == quality and payload["counts"] == counts, "coverage drift"
        )
        replays = 0
        for arm, costs in payload["metrics"].items():
            pd.testing.assert_frame_equal(
                signals[arm], pd.read_parquet(output / f"targets_{arm}.parquet")
            )
            used = signals[arm].loc[signals[arm].target_weight.ne(0)]
            base.require(
                used.available_at_utc.le(used.decision_at_utc).all()
                and used.decision_date.lt(used.effective_date).all(),
                "future signal/fill",
            )
            for cost, value in costs.items():
                ledger = pd.read_parquet(output / f"ledger_{arm}_{cost}.parquet")
                replay = base._performance_metrics(
                    ledger.ending_cash, ledger.session_date, base.CAPITAL
                )
                base.require(
                    all(np.isclose(value[k], v) for k, v in replay.items()), "metric drift"
                )
                days = pd.to_datetime(ledger.session_date)
                daily = ledger.ending_cash / ledger.starting_cash - 1
                annual = {
                    str(y): float(np.prod(1 + daily.loc[days.dt.year.eq(y)]) - 1)
                    for y in sorted(days.dt.year.unique())
                }
                base.require(
                    set(annual) == set(value["annual_returns"])
                    and all(np.isclose(value["annual_returns"][k], v) for k, v in annual.items()),
                    "annual drift",
                )
                pos = pd.read_parquet(output / f"positions_{arm}_{cost}.parquet")
                base.require(
                    all(value[k] == v for k, v in shared.position_counts(pos).items()),
                    "trade count drift",
                )
                orders = pd.read_parquet(output / f"orders_{arm}_{cost}.parquet")
                filled = orders.loc[orders.filled]
                paid = filled.commission_cost.sum() + filled.slippage_cost.sum()
                base.require(
                    np.isclose(paid, value["total_cost"])
                    and np.isclose(ledger.variation_margin.sum() - paid, value["net_pnl"]),
                    "cash drift",
                )
                replays += 1
        base.require(
            replays == 4
            and payload["assessment"] == adapter.assess(payload["metrics"], quality, cfg),
            "assessment drift",
        )
        print(
            json.dumps(
                {
                    "artifact_hashes": len(identity["files"]),
                    "metric_count_cash_replays": replays,
                    "raw_workbook_state_target_replay": True,
                    "all_true": True,
                }
            )
        )
        return
    base.write_json(output / "inputs.json", verified)
    rigs.to_parquet(output / "rig_counts.parquet", index=False)
    state.to_parquet(output / "rig_states.parquet", index=False)
    obs = pd.read_parquet(
        base.safe(args.storage_root, declarations["observations"]["path"]), columns=base.OBS_COLS
    )
    specs = pd.read_parquet(
        base.safe(args.storage_root, declarations["specs"]["path"]),
        columns=sorted(base.SPEC_PROXY_COLUMNS),
    )
    market = base.build_portfolio_market(
        obs.rename(
            columns={
                "trade_date": "session_date",
                "logical_asset": "asset_code",
                "canonical_contract_id": "contract_id",
            }
        ),
        specs,
    )
    market = market.loc[
        market.asset_code.isin(cfg["assets"])
        & pd.to_datetime(market.session_date).between(cfg["period"]["start"], cfg["period"]["end"])
    ]
    metrics = {}
    for arm, signal in signals.items():
        signal.to_parquet(output / f"targets_{arm}.parquet", index=False)
        metrics[arm] = {}
        for cost, (ticks, fee) in cfg["execution"]["costs"].items():
            result = base.run_futures_portfolio_ledger(
                market.loc[pd.to_datetime(market.session_date).le(signal.effective_date.max())],
                signal,
                base.FuturesPortfolioLedgerConfig(
                    initial_cash=base.CAPITAL,
                    expected_assets=tuple(cfg["assets"]),
                    maximum_gross_notional_multiple=cfg["execution"]["maximum_gross_multiple"],
                    initial_margin_buffer_multiplier=cfg["execution"]["margin_buffer"],
                    maximum_participation=cfg["execution"]["maximum_participation"],
                    slippage_ticks=ticks,
                    fee_multiplier=fee,
                    execution_atomicity="asset",
                    unexecutable_target_policy="cancel_and_clip",
                ),
            )
            metrics[arm][cost] = shared.summarize(result)
            for kind in ("ledger", "orders", "positions"):
                getattr(result, kind).to_parquet(
                    output / f"{kind}_{arm}_{cost}.parquet", index=False
                )
            print(json.dumps({"completed": arm, "cost": cost}), flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": args.seal_sha,
        "stage": 1,
        "metrics": metrics,
        "counts": counts,
        "source_quality": quality,
        "assessment": adapter.assess(metrics, quality, cfg),
        "economic_runtime_seconds": time.monotonic() - started,
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": args.seal_sha,
            "files": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)


if __name__ == "__main__":
    main()
