"""One external variance-premium screen with bounded source and existing ledger."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v78_treasury_channels as engine
from market_lab import futures_v94_skewness_premium as mapping_tools

base = engine.base
CONFIG = base.PROJECT / "configs/v96_variance_premium_v1.json"
SEAL = base.PROJECT / "configs/v96_variance_premium_v1.seal.json"
STORAGE = Path("/srv/trading_lab_data")


def parse_sp500(content, *, metadata_only=False):
    base.require(0 < len(content) <= 2_000_000, "SP500 response size")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    base.require(reader.fieldnames == ["observation_date", "SP500"], "SP500 schema")
    records = list(reader)
    base.require(bool(records), "empty SP500")
    # Validate the entire date universe BEFORE any float conversion.
    for record in records:
        base.require(set(record) == set(reader.fieldnames), "SP500 row width")
        day = record["observation_date"]
        base.require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)), "SP500 date format")
        base.require(
            pd.Timestamp("2018-01-01") <= pd.Timestamp(day) < base.BOUNDARY, "protected SP500 date"
        )
    days = pd.DatetimeIndex([r["observation_date"] for r in records])
    base.require(days.is_monotonic_increasing and days.is_unique, "unordered SP500 dates")
    values, valid = [], []
    for record in records:
        value = record["SP500"]
        present = value not in ("", ".")
        base.require(
            not present or bool(re.fullmatch(r"\d+(?:\.\d{1,4})?", value)), "SP500 value format"
        )
        valid.append(present)
        if not metadata_only:
            number = float(value) if present else np.nan
            base.require(not present or np.isfinite(number) and number > 0, "invalid SP500")
            values.append(number)
    frame = pd.DataFrame({"source_date": days, "sp500_present": valid})
    if not metadata_only:
        frame["sp500"] = values
    return frame


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("source redirect forbidden")


def collect(cfg, expected):
    import importlib.metadata

    spec = cfg["source"]
    root = base.safe(STORAGE, "source_evidence/v96_sp500_" + expected[:12])
    base.require(not root.exists(), "source already exists; no repeat")
    sys.path.insert(0, spec["calendar_dependencies"])
    import exchange_calendars as xcals

    base.require(xcals.__version__ == spec["calendar_version"], "calendar version drift")
    calendar = xcals.get_calendar("XNYS", start=spec["start"], end="2026-01-09")
    for day, expected_session in (
        ("2018-12-05", False),
        ("2018-03-30", False),
        ("2021-12-31", True),
        ("2022-06-20", False),
        ("2025-01-09", False),
    ):
        base.require(calendar.is_session(day) == expected_session, "calendar closure drift")
    sessions = calendar.sessions
    table = pd.DataFrame({"source_date": sessions[:-1], "next_session": sessions[1:]})
    table = table.loc[table.source_date.le(spec["end"])]
    root.mkdir(exist_ok=False)
    base.write_json(
        root / "started.json",
        {"seal_sha256": expected, "started_at_utc": datetime.now(UTC).isoformat()},
    )
    table.to_parquet(root / "xnys_sessions.parquet", index=False)
    req = urllib.request.Request(spec["sp500_url"], headers={"User-Agent": "trading-lab/0.5"})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=90) as response:
        base.require(response.status == 200 and response.url == spec["sp500_url"], "HTTP source")
        raw = response.read(2_000_001)
    # Invalid response is retained as evidence; never printed or interpreted as outcomes.
    (root / "sp500.csv").write_bytes(raw)
    frame = parse_sp500(raw, metadata_only=True)
    dates = table.source_date
    base.require(
        not frame.loc[frame.sp500_present, "source_date"].isin(dates).eq(False).any(),
        "SP500 observation on non-XNYS session",
    )
    manifest = {
        "status": "COMPLETE",
        "seal_sha256": expected,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "url": spec["sp500_url"],
        "rows": len(frame),
        "present": int(frame.sp500_present.sum()),
        "minimum_date": str(frame.source_date.min().date()),
        "maximum_date": str(frame.source_date.max().date()),
        "sessions": len(table),
        "all_dates_before_2026": True,
        "original_vintages_proved": False,
        "numeric_values_evaluated": False,
        "calendar_packages": {
            p: importlib.metadata.version(p)
            for p in (
                "exchange-calendars",
                "pyluach",
                "toolz",
                "korean-lunar-calendar",
                "pandas",
                "numpy",
            )
        },
        "calendar_code_sha256": base.sha(Path(xcals.__file__).parent / "exchange_calendar_xnys.py"),
        "files": {p.name: base.sha(p) for p in sorted(root.iterdir()) if p.is_file()},
    }
    base.write_json(root / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "source_root": str(root),
                "manifest_sha256": base.sha(root / "manifest.json"),
                "rows": manifest["rows"],
                "present": manifest["present"],
            }
        ),
        flush=True,
    )


def read_source(cfg, expected, manifest_sha):
    root = base.safe(STORAGE, "source_evidence/v96_sp500_" + expected[:12])
    base.require(base.sha(root / "manifest.json") == manifest_sha, "source manifest drift")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    base.require(
        manifest["status"] == "COMPLETE"
        and manifest["seal_sha256"] == expected
        and manifest["all_dates_before_2026"],
        "source incomplete/protected",
    )
    for name, digest in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == digest, "source bytes drift")
    vroot = base.safe(STORAGE, cfg["source"]["vix_root"])
    base.require(
        base.sha(vroot / "manifest.json") == cfg["source"]["vix_manifest_sha256"],
        "VIX manifest drift",
    )
    base.require(
        base.sha(vroot / "cboe_vix_term_structure.parquet") == cfg["source"]["vix_parquet_sha256"],
        "VIX source drift",
    )
    calendar = pd.read_parquet(root / "xnys_sessions.parquet")
    dates = pd.read_parquet(vroot / "cboe_vix_term_structure.parquet", columns=["observation_date"])
    base.require(
        dates.observation_date.notna().all() and dates.observation_date.lt(base.BOUNDARY).all(),
        "protected VIX",
    )
    raw = (root / "sp500.csv").read_bytes()
    parse_sp500(raw, metadata_only=True)
    vix = pd.read_parquet(
        vroot / "cboe_vix_term_structure.parquet",
        columns=["observation_date", "vix_close", "available_at"],
    )
    return calendar, parse_sp500(raw), vix, manifest


def features(calendar, sp500, vix, cfg):
    d = calendar.copy()
    for col in ("source_date", "next_session"):
        d[col] = pd.to_datetime(d[col])
    base.require(
        d.source_date.notna().all()
        and d.source_date.lt(base.BOUNDARY).all()
        and d.source_date.is_monotonic_increasing
        and d.source_date.is_unique
        and d.next_session.gt(d.source_date).all(),
        "invalid calendar",
    )
    for frame, column in ((sp500, "source_date"), (vix, "observation_date")):
        base.require(
            frame[column].notna().all()
            and frame[column].lt(base.BOUNDARY).all()
            and not frame[column].duplicated().any(),
            "invalid/protected source",
        )
    d = d.merge(sp500, on="source_date", how="left", validate="one_to_one")
    d = d.merge(
        vix.rename(columns={"observation_date": "source_date"}),
        on="source_date",
        how="left",
        validate="one_to_one",
    )
    valid = np.isfinite(d.sp500) & d.sp500.gt(0) & d.sp500_present.eq(True)
    price = d.sp500.where(valid)
    d["log_return"] = np.log(price / price.shift(1))
    sig = cfg["signal"]
    d["realized_variance"] = (
        d.log_return.pow(2)
        .rolling(sig["realized_sessions"], min_periods=sig["realized_sessions"])
        .mean()
        * sig["annualization"]
    )
    original_clock = pd.to_datetime(d.available_at, utc=True)
    iv = (
        d.vix_close.where(np.isfinite(d.vix_close) & d.vix_close.gt(0) & original_clock.notna())
        .div(100)
        .pow(2)
    )
    d["vrp_proxy"] = iv - d.realized_variance
    d["prior_median"] = (
        d.vrp_proxy.shift(1)
        .rolling(sig["rank_sessions"], min_periods=sig["rank_sessions"])
        .median()
    )
    lag = d.next_session + pd.Timedelta(hours=23, minutes=59, seconds=59)
    lag = lag.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    d["available_at_utc"] = lag.where(
        original_clock.isna() | lag.ge(original_clock), original_clock
    )
    # Missing quoted clock invalidates its value, not the state's clock or calendar row.
    d["ready"] = np.isfinite(d.vrp_proxy) & np.isfinite(d.prior_median) & original_clock.notna()
    d["high"] = d.ready & d.vrp_proxy.gt(d.prior_median)
    base.require(d.available_at_utc.is_monotonic_increasing, "source clocks out of order")
    return d


def targets(active, state, cfg):
    plan = mapping_tools.mapping(active)
    plan = plan.loc[plan.asset_code.isin(cfg["assets"]) & plan.decision_date.notna()]
    result, cohorts = {"primary": [], "control": []}, []
    last_month, selected_at, selected_source, reason = None, pd.NaT, pd.NaT, "warmup"
    weights, cohort_high = {"primary": 0.0, "control": 0.0}, 0
    sig = cfg["signal"]
    for day, part in plan.groupby("decision_date", sort=True):
        month = day.to_period("M")
        rebalance = month != last_month
        if rebalance:
            last_month, selected_at = month, day
            cutoff = (
                (day + pd.Timedelta(hours=18, minutes=45))
                .tz_localize("Europe/Moscow")
                .tz_convert("UTC")
            )
            known = state.loc[state.available_at_utc.le(cutoff)]
            latest = known.iloc[-1] if len(known) else None
            selected_source = latest.source_date if latest is not None else pd.NaT
            fresh = (
                latest is not None
                and 0 <= (day - selected_source).days <= sig["maximum_selection_source_age_days"]
            )
            ready = bool(fresh and latest.ready)
            cohorts.append((month, ready, bool(ready and latest.high)))
            cohorts = cohorts[-sig["holding_months"] :]
            complete = (
                len(cohorts) == sig["holding_months"]
                and all(c[1] for c in cohorts)
                and [c[0] for c in cohorts]
                == list(pd.period_range(end=month, periods=sig["holding_months"], freq="M"))
            )
            reason = "ready" if complete else "incomplete_or_stale_monthly_cohorts"
            cohort_high = sum(c[2] for c in cohorts)
            gross = cfg["execution"]["maximum_signal_gross"]
            weights = {
                "primary": gross * cohort_high / sig["holding_months"] if complete else 0.0,
                "control": gross / 2 if complete else 0.0,
            }
        for record in part.to_dict("records"):
            for arm in result:
                row = dict(record)
                row.update(
                    selection_date=selected_at,
                    source_date=selected_source,
                    source_url="local:v96_us_variance_proxy:" + str(selected_source),
                    monthly_rebalance=rebalance,
                    selection_reason=reason,
                    high_cohorts=cohort_high,
                    feature_unavailable=reason != "ready",
                    requested_weight=weights[arm] / len(cfg["assets"]),
                )
                row["source_unavailable"] = not (
                    row["plan_tradable"] is True and pd.notna(row["contract_id"])
                )
                row["stale_at_fill"] = (row["effective_date"] - day).days > sig[
                    "maximum_fill_gap_calendar_days"
                ]
                row["target_weight"] = (
                    row["requested_weight"]
                    if not (row["source_unavailable"] or row["stale_at_fill"])
                    else 0.0
                )
                result[arm].append(row)
    for arm, records in result.items():
        frame = pd.DataFrame(records)
        frame = frame.loc[
            frame.effective_date.between(cfg["period"]["start"], cfg["period"]["end"])
        ].copy()
        base.require(not frame.empty, "empty evaluation calendar")
        frame["terminal_flat"] = frame.effective_date.eq(frame.effective_date.max())
        frame.loc[frame.terminal_flat, "target_weight"] = 0.0
        frame.loc[frame.target_weight.eq(0), "contract_id"] = None
        frame["provenance"] = "v96_variance_premium_" + arm
        result[arm] = frame.sort_values(["effective_date", "asset_code"], ignore_index=True)
    return result


def load(expected):
    base.require(base.sha(SEAL) == expected, "V96 seal drift")
    for name, digest in json.loads(SEAL.read_text(encoding="utf-8"))["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V96 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    parent = base.load_config(cfg["parent_v64_seal_sha256"])
    base.require(
        cfg["assets"] == ["MIX", "RI"]
        and cfg["protected_from"] == "2026-01-01"
        and not cfg["goal_verified"]
        and not cfg["live_trading_allowed"],
        "scope drift",
    )
    return cfg, {**parent, "eras": [e for e in parent["eras"] if e["id"] == "recent"]}


def run(cfg, parent, expected, manifest_sha):
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing canonical; no repeat")
    verified = base.preflight(parent, STORAGE)
    output.mkdir(exist_ok=False)
    base.write_json(
        output / "started.json",
        {
            "seal_sha256": expected,
            "source_manifest_sha256": manifest_sha,
            "started_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    calendar, sp500, vix, manifest = read_source(cfg, expected, manifest_sha)
    base.write_json(output / "inputs.json", {"futures": verified, "external_source": manifest})
    declared = base.declarations(parent)["recent"]
    active = pd.read_parquet(
        base.safe(STORAGE, declared["active_map"]["path"]), columns=base.ACTIVE_COLS
    )
    state = features(calendar, sp500, vix, cfg)
    state.to_parquet(output / "variance_states.parquet", index=False)
    signals = targets(active, state, cfg)
    p = signals["primary"]
    monthly = p.loc[p.monthly_rebalance].drop_duplicates("decision_date")
    quality = {
        "ready_asset_date_fraction": float((~(p.feature_unavailable | p.stale_at_fill)).mean()),
        "monthly_decisions": len(monthly),
        "ready_monthly_decisions": int((~monthly.feature_unavailable).sum()),
        "monthly_reason_counts": {
            str(k): int(v) for k, v in monthly.selection_reason.value_counts().items()
        },
        "high_cohort_counts": {
            str(k): int(v) for k, v in monthly.high_cohorts.value_counts().items()
        },
        "source_sessions": len(state),
        "ready_source_sessions": int(state.ready.sum()),
        "original_vintages_proved": False,
    }
    market = engine.market_inputs(STORAGE, declared, cfg)
    case = engine.simulate_case(output / "case", signals, market, quality, cfg, "variance_premium")
    payload = {
        "status": "COMPLETE",
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "source_manifest_sha256": manifest_sha,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "case": case,
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "manifest.json",
        {
            "status": "COMPLETE",
            "seal_sha256": expected,
            "source_manifest_sha256": manifest_sha,
            "completed_at_utc": payload["completed_at_utc"],
            "files": {
                str(p.relative_to(output)): base.sha(p)
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(json.dumps({"output": str(output), "assessment": case["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    cli.add_argument("--collect", action="store_true")
    cli.add_argument("--source-manifest-sha")
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    base.require(args.collect != bool(args.source_manifest_sha), "choose source or economic run")
    cfg, parent = load(args.seal_sha)
    if args.collect:
        collect(cfg, args.seal_sha)
    else:
        run(cfg, parent, args.seal_sha, args.source_manifest_sha)


if __name__ == "__main__":
    main()
