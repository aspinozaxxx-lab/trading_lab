"""V93: independent one-contract interval diagnostics, deliberately not a ledger."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from market_lab.futures.opening_regime_v2 import Market, local_time
from market_lab.futures_v62_opening_regime_v2 import (
    ROOT,
    load_market,
    read_json,
    sha,
    sources,
    write_json,
)

CONFIG = ROOT / "configs/v93_session_components_v1.json"
SEAL = ROOT / "configs/v93_session_components_v1.seal.json"
SPEC_COLUMNS = [
    "session_date",
    "contract_id",
    "sizing_usable",
    "sizing_observed_session_date",
    "sizing_point_value",
    "sizing_tick_cash_value",
    "conservative_fee_per_side",
]


def spec_index(specs: pd.DataFrame) -> dict:
    data = specs.copy()
    for field in ("session_date", "sizing_observed_session_date"):
        data[field] = pd.to_datetime(data[field])
        if data[field].ge(pd.Timestamp("2026-01-01")).any():
            raise ValueError("protected spec date")
    if data.duplicated(["session_date", "contract_id"]).any():
        raise ValueError("duplicate spec")
    return {(r.session_date, r.contract_id): r for r in data.itertuples(index=False)}


def usable_spec(row, day: pd.Timestamp) -> bool:
    if row is None or pd.isna(row.sizing_usable) or not row.sizing_usable:
        return False
    numbers = [row.sizing_point_value, row.sizing_tick_cash_value, row.conservative_fee_per_side]
    return bool(
        pd.notna(row.sizing_observed_session_date)
        and row.sizing_observed_session_date < day
        and np.isfinite(numbers).all()
        and min(numbers) > 0
    )


def requests(market: Market, specs: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """All calendar candidates; no future market row is inspected here."""
    if market.sessions.isna().any() or (
        len(market.sessions) and market.sessions.max() >= pd.Timestamp("2026-01-01")
    ):
        raise ValueError("protected or missing calendar date")
    index = spec_index(specs)
    days = market.sessions[
        (market.sessions >= cfg["period"]["start"]) & (market.sessions <= cfg["period"]["end"])
    ]
    if len(days) and days.max() >= pd.Timestamp("2026-01-01"):
        raise ValueError("protected calendar")
    rows = []
    for i, day in enumerate(days):
        for arm, rule in cfg["arms"].items():
            minute = rule["entry_minute_moscow"]
            contract = market.contracts.get((day, cfg["asset"]))
            spec = index.get((day, contract))
            decision_bar = market.bar(contract, local_time(day, minute - 20))
            exit_day = days[i + 1] if rule["next_session"] and i + 1 < len(days) else day
            reason = "REQUESTED"
            if rule["next_session"] and i + 1 == len(days):
                reason = "TERMINAL_NO_NEW_OVERNIGHT"
            elif contract is None or decision_bar is None:
                reason = "MISSING_PLAN_OR_COMPLETED_DECISION_BAR"
            elif not usable_spec(spec, day):
                reason = "UNUSABLE_PRIOR_SPEC"
            elif decision_bar["volume"] < cfg["minimum_signal_volume"]:
                reason = "INSUFFICIENT_COMPLETED_VOLUME"
            rows.append(
                dict(
                    arm=arm,
                    local_date=day,
                    contract_id=contract,
                    decision_at=local_time(day, minute - 10),
                    entry_at=local_time(day, minute),
                    exit_at=local_time(exit_day, rule["exit_minute_moscow"]),
                    exit_local_date=exit_day,
                    request_state=reason,
                    requested_quantity=int(reason == "REQUESTED"),
                    decision_volume=decision_bar["volume"] if decision_bar is not None else np.nan,
                )
            )
    return pd.DataFrame(rows)


def evaluate(
    request_frame: pd.DataFrame, market: Market, specs: pd.DataFrame, cfg: dict, scenario: str
) -> pd.DataFrame:
    """Observe fixed endpoints, keeping unavailable exits explicitly unresolved.

    Each row is an independent probe: it is NOT a succession of portfolio fills.
    No later probe erases a prior unclosed position or assumes that capital was freed.
    """
    index = spec_index(specs)
    ticks, fee_multiple = cfg["costs"][scenario]
    records = []
    for item in request_frame.to_dict("records"):
        row = dict(
            item,
            scenario=scenario,
            state=item["request_state"],
            entered_quantity=0,
            closed_quantity=0,
            gross_cash=np.nan,
            costs_cash=np.nan,
            net_cash=np.nan,
            entry_notional=np.nan,
            gross_basis_points=np.nan,
            net_basis_points=np.nan,
            entry_participation=np.nan,
            exit_participation=np.nan,
        )
        if item["requested_quantity"]:
            contract = item["contract_id"]
            entry = market.bar(contract, item["entry_at"])
            if entry is None or entry["volume"] < cfg["minimum_factual_volume"]:
                row["state"] = "NO_ENTRY_BAR_OR_CAPACITY"
            else:
                row.update(entered_quantity=1, entry_participation=1 / entry["volume"])
                first = index[(item["local_date"], contract)]
                last = index.get((item["exit_local_date"], contract))
                exit_bar = market.bar(contract, item["exit_at"])
                if exit_bar is None or exit_bar["volume"] < cfg["minimum_factual_volume"]:
                    row["state"] = "UNRESOLVED_EXIT_BAR_OR_CAPACITY"
                elif not usable_spec(last, item["exit_local_date"]):
                    row["state"] = "UNRESOLVED_EXIT_SPEC"
                elif not np.isclose(
                    first.sizing_point_value, last.sizing_point_value, rtol=0, atol=1e-12
                ):
                    row["state"] = "UNRESOLVED_POINT_VALUE_CHANGE"
                else:
                    notional = entry["open"] * first.sizing_point_value
                    gross = (exit_bar["open"] - entry["open"]) * first.sizing_point_value
                    cost = ticks * (
                        first.sizing_tick_cash_value + last.sizing_tick_cash_value
                    ) + fee_multiple * (
                        first.conservative_fee_per_side + last.conservative_fee_per_side
                    )
                    row.update(
                        state="OBSERVED_PAIR",
                        closed_quantity=1,
                        exit_participation=1 / exit_bar["volume"],
                        entry_notional=notional,
                        gross_cash=gross,
                        costs_cash=cost,
                        net_cash=gross - cost,
                        gross_basis_points=10_000 * gross / notional,
                        net_basis_points=10_000 * (gross - cost) / notional,
                    )
        records.append(row)
    return pd.DataFrame(records)


def summarize(frame: pd.DataFrame) -> dict:
    good = frame.loc[frame.state.eq("OBSERVED_PAIR")]
    yearly = {}
    for year, part in frame.groupby(frame.local_date.dt.year):
        observed = part.loc[part.state.eq("OBSERVED_PAIR")]
        yearly[str(year)] = dict(
            calendar_candidates=len(part),
            completed=len(observed),
            unresolved=int((part.entered_quantity - part.closed_quantity).sum()),
            mean_gross_bp=float(observed.gross_basis_points.mean()),
            mean_net_bp=float(observed.net_basis_points.mean()),
            median_net_bp=float(observed.net_basis_points.median()),
        )
    return dict(
        calendar_candidates=len(frame),
        requested=int(frame.requested_quantity.sum()),
        entered=int(frame.entered_quantity.sum()),
        completed=len(good),
        unresolved=int((frame.entered_quantity - frame.closed_quantity).sum()),
        completed_calendar_coverage=len(good) / len(frame) if len(frame) else 0,
        states=frame.state.value_counts().to_dict(),
        yearly=yearly,
        mean_gross_bp=float(good.gross_basis_points.mean()),
        mean_net_bp=float(good.net_basis_points.mean()),
        median_net_bp=float(good.net_basis_points.median()),
        costs_cash_observed_pairs=float(good.costs_cash.sum()),
        maximum_participation=float(
            frame[["entry_participation", "exit_participation"]].max().max()
        ),
        cagr=None,
        sharpe=None,
        maximum_drawdown=None,
        portfolio_pnl=None,
        interpretation=(
            "conditional independent-pair diagnostics, not a wealth path or executable strategy"
        ),
    )


def report(pairs: pd.DataFrame, cfg: dict) -> dict:
    results, comparisons, checks = {}, {}, {}
    gates = cfg["lead_gates"]
    for scenario in cfg["costs"]:
        current = pairs.loc[pairs.scenario.eq(scenario)]
        for arm in cfg["arms"]:
            results[f"{arm}_{scenario}"] = summarize(current.loc[current.arm.eq(arm)])
        matched = (
            current.loc[current.state.eq("OBSERVED_PAIR")]
            .pivot(index="local_date", columns="arm", values="net_basis_points")
            .dropna()
        )
        difference = (
            matched.off_session - matched.main_session_control
            if set(cfg["arms"]).issubset(matched.columns)
            else pd.Series(dtype=float)
        )
        advantage = float(difference.mean())
        comparisons[scenario] = dict(matched_dates=len(difference), mean_net_advantage_bp=advantage)
        primary = results[f"off_session_{scenario}"]
        checks[scenario] = dict(
            enough_pairs=primary["completed"] >= gates["minimum_completed_intervals"],
            coverage=primary["completed_calendar_coverage"]
            >= gates["minimum_completed_calendar_coverage"],
            net_effect=primary["mean_net_bp"] >= gates["minimum_mean_net_basis_points"],
            calendar=set(primary["yearly"]) == {"2021", "2022", "2023", "2024", "2025"},
            positive_years=sum(v["mean_net_bp"] > 0 for v in primary["yearly"].values())
            >= gates["minimum_positive_years"],
            primary_beats_control=advantage > 0,
            all_arms_no_unresolved=all(
                results[f"{a}_{scenario}"]["unresolved"] == 0 for a in cfg["arms"]
            ),
        )
    passed = all(all(x.values()) for x in checks.values())
    incomplete = any(r["unresolved"] for r in results.values())
    verdict = (
        "INCOMPLETE_SOURCE_NO_PROMOTION"
        if incomplete
        else "POSITIVE_COMPONENT_REQUIRES_EXECUTION"
        if passed
        else "NO_GO_COMPONENT"
    )
    return dict(
        results=results,
        matched_date_comparisons=comparisons,
        checks=checks,
        verdict=verdict,
        stage2_candidate=False,
        goal_verified=False,
        live_trading_allowed=False,
    )


def run(expected_seal: str) -> dict:
    if os.name == "nt" or os.geteuid() != 999:
        raise RuntimeError("real source/economics require server UID999")
    if sha(SEAL) != expected_seal:
        raise ValueError("seal drift")
    for path, expected in read_json(SEAL)["files"].items():
        if sha(ROOT / path) != expected:
            raise ValueError(f"code drift: {path}")
    cfg = read_json(CONFIG)
    parent_path = ROOT / cfg["source_config"]
    if sha(parent_path) != cfg["source_config_sha256"]:
        raise ValueError("source config drift")
    parent = yaml.safe_load(parent_path.read_text(encoding="utf-8-sig"))
    artifacts, plan, sessions, evidence = sources(Path(cfg["source_root"]), parent)
    # Inspect physical spec dates before any numeric reader, not only its filename.
    spec_path = Path(evidence["spec_proxy"]["path"])
    dates = pd.read_parquet(spec_path, columns=["session_date", "sizing_observed_session_date"])
    for col in dates:
        if pd.to_datetime(dates[col]).ge(pd.Timestamp("2026-01-01")).any():
            raise ValueError("protected physical spec date")
    output = Path("/srv/trading_lab_data/runs") / f"v93_session_components_v1_{expected_seal[:12]}"
    output.mkdir(exist_ok=False)
    write_json(output / "started.json", dict(at=datetime.now(UTC), seal_sha256=expected_seal))
    market = load_market(
        [a for a in artifacts if a["asset"] == cfg["asset"]],
        plan.loc[plan.asset.eq(cfg["asset"])],
        sessions,
    )
    specs = pd.read_parquet(spec_path, columns=SPEC_COLUMNS)
    candidates = requests(market, specs, cfg)
    candidates.to_parquet(output / "requests.parquet", index=False)
    pairs = pd.concat(
        [evaluate(candidates, market, specs, cfg, c) for c in cfg["costs"]], ignore_index=True
    )
    pairs.to_parquet(output / "pairs.parquet", index=False)
    result = report(pairs, cfg)
    result.update(
        protocol_id=cfg["protocol_id"],
        output=str(output),
        completed_at=datetime.now(UTC),
        seal_sha256=expected_seal,
        config_sha256=sha(CONFIG),
    )
    write_json(output / "metrics.json", result)
    write_json(
        output / "manifest.json",
        dict(
            source=evidence,
            seal_sha256=expected_seal,
            completed_at=datetime.now(UTC),
            artifacts={
                p.name: dict(sha256=sha(p), bytes=p.stat().st_size)
                for p in sorted(output.iterdir())
                if p.is_file()
            },
        ),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-sha", required=True)
    args = parser.parse_args()
    result = run(args.seal_sha)
    print(json.dumps({"output": result["output"], "verdict": result["verdict"]}), flush=True)


if __name__ == "__main__":
    main()
