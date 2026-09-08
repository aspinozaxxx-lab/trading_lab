"""Small fixed auction-specific clean-price premium screen, not a portfolio NAV."""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v64_si_tax_calendar as base

PROJECT = base.PROJECT
CONFIG = PROJECT / "configs/v67_ofz_auction_concession_v1.json"
SEAL = PROJECT / "configs/v67_ofz_auction_concession_v1.seal.json"
HISTORY = [
    "trade_date",
    "security_id",
    "value_rub",
    "open_clean_pct",
    "duration_days",
    "currency_id",
    "face_unit",
    "available_at_utc",
]
AUCTIONS = [
    "document_id",
    "event_kind",
    "publication_date",
    "available_at",
    "issue_code",
    "ofz_type",
]


def load(expected):
    base.require(base.sha(SEAL) == expected, "V67 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(PROJECT, name)) == digest, "V67 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    base.load_config(cfg["parent_helper_seal_sha256"])
    base.require(cfg["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg


def preflight(cfg, storage):
    checks = {}
    for role, item in cfg["inputs"].items():
        p = base.safe(storage, item["path"])
        checks[role + "_sha"] = p.is_file() and base.sha(p) == item["sha256"]
        if "bytes" in item:
            checks[role + "_bytes"] = p.is_file() and p.stat().st_size == item["bytes"]
        if "rows" in item:
            checks[role + "_rows"] = pq.ParquetFile(p).metadata.num_rows == item["rows"]
        if role in ("history", "auctions"):
            col = "trade_date" if role == "history" else "publication_date"
            dates = pd.to_datetime(pd.read_parquet(p, columns=[col])[col])
            checks[role + "_dates"] = bool(
                dates.notna().all()
                and dates.ge("2021-01-01").all()
                and dates.lt(base.BOUNDARY).all()
            )
    base.require(all(checks.values()), "input identity or boundary failed")
    return checks


def prepare(history, auctions, cfg):
    h, a = history[HISTORY].copy(), auctions[AUCTIONS].copy()
    h["trade_date"] = pd.to_datetime(h.trade_date)
    a["publication_date"] = pd.to_datetime(a.publication_date)
    for f, key in ((h, "trade_date"), (a, "publication_date")):
        base.require(
            f[key].notna().all() and f[key].lt(base.BOUNDARY).all(), "protected or missing date"
        )
    h["available_at_utc"] = pd.to_datetime(h.available_at_utc, utc=True)
    a["available_at"] = pd.to_datetime(a.available_at, utc=True)
    base.require(
        h.available_at_utc.notna().all() and a.available_at.notna().all(), "missing availability"
    )
    base.require(not h.duplicated(["trade_date", "security_id"]).any(), "duplicate history")
    for key in ("value_rub", "open_clean_pct", "duration_days"):
        h[key] = pd.to_numeric(h[key], errors="coerce")
    h = h.sort_values(["security_id", "trade_date"])
    n = cfg["selection"]["liquidity_sessions"]
    h["median_value"] = (
        h.value_rub.where(h.value_rub.ge(0))
        .groupby(h.security_id)
        .transform(lambda x: x.rolling(n, min_periods=n).median())
    )
    a = a.loc[a.event_kind.eq("primary_result") & a.ofz_type.eq("ПД")].copy()
    base.require(
        not a.duplicated(["publication_date", "issue_code"]).any(), "duplicate primary issue"
    )
    return h, a.sort_values(["publication_date", "issue_code"])


def choose(history, auctions, cfg):
    rows = []
    dates = sorted(history.trade_date.unique())
    p = cfg["selection"]
    for event in auctions.itertuples(index=False):
        day = event.publication_date
        midnight = (day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)).tz_convert("UTC")
        decision_at = max(midnight, event.available_at)
        previous_dates = [pd.Timestamp(d) for d in dates if d <= day]
        row = {
            "document_id": event.document_id,
            "publication_date": day,
            "decision_at": decision_at,
            "issue_code": event.issue_code,
            "primary_id": None,
            "control_1": None,
            "control_2": None,
            "status": "snapshot_missing",
            "snapshot_date": pd.NaT,
        }
        if not previous_dates or (day - previous_dates[-1]).days > p["maximum_snapshot_age_days"]:
            rows.append(row)
            continue
        snapshot = history.loc[history.trade_date.eq(previous_dates[-1])].copy()
        row["snapshot_date"] = previous_dates[-1]
        eligible = snapshot.loc[
            snapshot.security_id.str.match(p["security_regex"])
            & snapshot.currency_id.eq("SUR")
            & snapshot.face_unit.eq("RUB")
            & snapshot.median_value.ge(p["minimum_median_value_rub"])
            & snapshot.duration_days.ge(p["minimum_duration_days"])
            & snapshot.available_at_utc.le(decision_at)
        ].copy()
        matched = eligible.loc[eligible.security_id.str.slice(2, -1).eq(event.issue_code)]
        base.require(len(matched) <= 1, "ambiguous issue identity")
        row["status"] = "primary_not_eligible"
        if matched.empty:
            rows.append(row)
            continue
        primary = matched.iloc[0]
        row["primary_id"] = str(primary.security_id)
        auctioned = set(auctions.loc[auctions.publication_date.eq(day), "issue_code"])
        controls = eligible.loc[~eligible.security_id.str.slice(2, -1).isin(auctioned)].copy()
        controls["distance"] = (controls.duration_days - primary.duration_days).abs()
        controls = controls.loc[controls.distance.le(p["maximum_control_duration_distance_days"])]
        controls = controls.sort_values(["distance", "security_id"]).head(p["control_count"])
        row["status"] = "controls_missing"
        if len(controls) == p["control_count"]:
            row.update(
                status="selected",
                control_1=str(controls.iloc[0].security_id),
                control_2=str(controls.iloc[1].security_id),
                primary_duration_days=float(primary.duration_days),
                control_max_distance_days=float(controls.distance.max()),
            )
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate(selection, history, cfg):
    dates = pd.DatetimeIndex(sorted(history.trade_date.unique()))
    lookup = history.set_index(["trade_date", "security_id"]).open_clean_pct
    rows = []
    p = cfg["evaluation"]
    for item in selection.to_dict("records"):
        row = {
            **item,
            "evaluation_status": "not_selected",
            "entry_date": pd.NaT,
            "exit_date": pd.NaT,
            "primary_gross_bps": np.nan,
            "control_gross_bps": np.nan,
            "excess_bps": np.nan,
        }
        if item["status"] != "selected":
            rows.append(row)
            continue
        entry_i = dates.searchsorted(item["publication_date"], side="right")
        exit_i = entry_i + p["hold_sessions"]
        row["evaluation_status"] = "outside_source_window"
        if exit_i >= len(dates):
            rows.append(row)
            continue
        entry, finish = dates[entry_i], dates[exit_i]
        row.update(entry_date=entry, exit_date=finish, evaluation_status="calendar_gap")
        if (entry - item["publication_date"]).days > p["maximum_entry_delay_days"] or (
            finish - entry
        ).days > p["maximum_holding_calendar_days"]:
            rows.append(row)
            continue
        entry_clock_lower = entry.tz_localize("Europe/Moscow").tz_convert("UTC")
        base.require(item["decision_at"] <= entry_clock_lower, "decision not before entry day")
        ids = [item["primary_id"], item["control_1"], item["control_2"]]
        prices = np.array(
            [[lookup.get((date, sec), np.nan) for sec in ids] for date in (entry, finish)],
            dtype=float,
        )
        row["evaluation_status"] = "missing_entry_or_exit_price"
        if not (np.isfinite(prices).all() and (prices > 0).all()):
            rows.append(row)
            continue
        returns = (prices[1] / prices[0] - 1) * 10000
        row.update(
            evaluation_status="complete",
            primary_gross_bps=float(returns[0]),
            control_gross_bps=float(returns[1:].mean()),
            excess_bps=float(returns[0] - returns[1:].mean()),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(evaluation, cfg):
    complete = evaluation.loc[evaluation.evaluation_status.eq("complete")]
    daily = complete.groupby("publication_date")[
        ["primary_gross_bps", "control_gross_bps", "excess_bps"]
    ].mean()
    doubled = 2 * cfg["evaluation"]["one_way_cost_bps"]["doubled"]
    net = daily.primary_gross_bps - doubled
    t = (
        float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net))))
        if len(net) > 1 and net.std(ddof=1) > 0
        else None
    )
    selected = int(evaluation.status.eq("selected").sum())
    fraction = len(complete) / selected if selected else 0.0
    yearly = {}
    for year in cfg["evaluation"]["calendar_years"]:
        d = daily.loc[daily.index.year == year]
        yearly[str(year)] = {
            "days": len(d),
            "gross_mean_bps": float(d.primary_gross_bps.mean()) if len(d) else None,
            "net_doubled_mean_bps": float((d.primary_gross_bps - doubled).mean())
            if len(d)
            else None,
            "excess_mean_bps": float(d.excess_bps.mean()) if len(d) else None,
        }
    g = cfg["screen_gates"]
    checks = {
        "enough_days": len(daily) >= g["minimum_complete_publication_days"],
        "coverage": fraction >= g["minimum_complete_fraction_selected"],
        "positive_net": bool(len(daily) and net.mean() > g["minimum_primary_doubled_mean_bps"]),
        "positive_excess": bool(
            len(daily) and daily.excess_bps.mean() > g["minimum_excess_mean_bps"]
        ),
        "positive_net_years": sum(
            x["net_doubled_mean_bps"] is not None and x["net_doubled_mean_bps"] > 0
            for x in yearly.values()
        )
        >= g["minimum_positive_net_years"],
        "positive_excess_years": sum(
            x["excess_mean_bps"] is not None and x["excess_mean_bps"] > 0 for x in yearly.values()
        )
        >= g["minimum_positive_excess_years"],
        "net_t": t is not None and t >= g["minimum_day_clustered_t_net"],
    }
    return {
        "source_events": len(evaluation),
        "selected_events": selected,
        "complete_events": len(complete),
        "complete_days": len(daily),
        "coverage": fraction,
        "selection_statuses": evaluation.status.value_counts().to_dict(),
        "evaluation_statuses": evaluation.evaluation_status.value_counts().to_dict(),
        "complete_case_gross_mean_bps": float(daily.primary_gross_bps.mean())
        if len(daily)
        else None,
        "complete_case_control_gross_mean_bps": float(daily.control_gross_bps.mean())
        if len(daily)
        else None,
        "complete_case_excess_mean_bps": float(daily.excess_bps.mean()) if len(daily) else None,
        "complete_case_net_mean_bps": {
            name: float((daily.primary_gross_bps - 2 * cost).mean()) if len(daily) else None
            for name, cost in cfg["evaluation"]["one_way_cost_bps"].items()
        },
        "day_clustered_t_net": t,
        "yearly": yearly,
        "checks": checks,
        "failed_gates": [k for k, v in checks.items() if not v],
        "verdict": "STAGE2_CANDIDATE" if all(checks.values()) else "REJECT_STAGE1",
        "cagr": None,
        "sharpe": None,
        "maximum_drawdown": None,
        "portfolio_trades": 0,
        "goal_verified": False,
    }, daily.reset_index()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    args = parser.parse_args()
    cfg = load(args.seal_sha)
    base.require(os.name == "posix", "research on server only")
    root = base.safe(args.storage_root, "runs/v67_ofz_auction_concession_v1_" + args.seal_sha[:12])
    base.require(not root.exists(), "existing run; do not repeat")
    checks = preflight(cfg, args.storage_root)
    root.mkdir(parents=True, exist_ok=False)
    base.write_json(root / "inputs.json", checks)
    raw_h = pd.read_parquet(
        base.safe(args.storage_root, cfg["inputs"]["history"]["path"]), columns=HISTORY
    )
    raw_a = pd.read_parquet(
        base.safe(args.storage_root, cfg["inputs"]["auctions"]["path"]), columns=AUCTIONS
    )
    h, a = prepare(raw_h, raw_a, cfg)
    selected = choose(h, a, cfg)
    evaluated = evaluate(selected, h, cfg)
    metrics, daily = summarize(evaluated, cfg)
    for name, frame in (
        ("selection", selected),
        ("evaluation", evaluated),
        ("daily_events", daily),
    ):
        frame.to_parquet(root / f"{name}.parquet", index=False)
    base.write_json(
        root / "metrics.json",
        {"protocol_id": cfg["protocol_id"], "seal_sha256": args.seal_sha, **metrics},
    )
    base.write_json(
        root / "identity.json",
        {
            "seal_sha256": args.seal_sha,
            "files": {p.name: base.sha(p) for p in sorted(root.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(root), **metrics}), flush=True)


if __name__ == "__main__":
    main()
