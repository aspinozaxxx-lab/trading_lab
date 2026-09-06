"""Fixed calendar-mechanism screen; no model fit, paid data or parent rerun."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures.execution_dataset import SPEC_PROXY_COLUMNS, build_portfolio_market
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    _performance_metrics,
    run_futures_portfolio_ledger,
)

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT / "configs/v64_si_tax_calendar_v1.yaml"
SEAL = PROJECT / "configs/v64_si_tax_calendar_v1.seal.json"
BOUNDARY = pd.Timestamp("2026-01-01")
CAPITAL = 1_000_000.0
ACTIVE_COLS = [
    "decision_date",
    "effective_date",
    "observed_through",
    "asset_code",
    "contract_id",
    "plan_tradable",
    "roll",
]
OBS_COLS = [
    "trade_date",
    "logical_asset",
    "canonical_contract_id",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
]
ARMS = {"tax": 0, "control": -14}
SCENARIOS = {"primary": (1, 1.0), "doubled": (2, 2.0), "stress": (4, 2.0)}


def require(value: Any, message: str) -> None:
    if not bool(value):
        raise ValueError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe(root: Path, relative: str) -> Path:
    part = Path(relative)
    require(not part.is_absolute() and ".." not in part.parts, "unsafe path")
    result = (root / part).resolve()
    require(result.is_relative_to(root.resolve()), "path escaped storage")
    return result


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8-sig",
    )


def load_config(expected_seal: str) -> dict[str, Any]:
    require(sha(SEAL) == expected_seal, "seal identity mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        require(sha(safe(PROJECT, name)) == digest, f"sealed file drift: {name}")
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8-sig"))
    require(cfg["protocol_id"] == "v64_si_tax_calendar_v1", "wrong protocol")
    require(cfg["research_only"] and not cfg["live_trading_allowed"], "research only")
    require(str(cfg["protected_from"]) == "2026-01-01", "protected boundary drift")
    return cfg


def declarations(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalogs = {}
    for name, spec in cfg["input_catalogs"].items():
        path = safe(PROJECT, spec["path"])
        require(sha(path) == spec["sha256"], "catalog identity mismatch")
        catalogs[name] = yaml.safe_load(path.read_text(encoding="utf-8-sig"))["inputs"]
    result = {}
    for era in cfg["eras"]:
        catalog = catalogs[era["catalog"]]
        if era["selection"] == "pre2012":
            result[era["id"]] = {
                "active_map": catalog["active_contract_map"],
                "observations": catalog["contract_observations"],
                "specs": catalog["spec_proxy"],
            }
        else:
            result[era["id"]] = catalog["execution_eras"][int(era["selection"])]
    return result


def preflight(cfg: dict[str, Any], storage: Path) -> dict[str, Any]:
    """Read bytes, schemas, counts and date columns only, never market values."""
    checks, metadata = {}, {}
    specs = declarations(cfg)
    for era in cfg["eras"]:
        for role, declaration in specs[era["id"]].items():
            key = f"{era['id']}_{role}"
            path = safe(storage, declaration["path"])
            checks[key + "_bytes"] = path.is_file() and path.stat().st_size == declaration["bytes"]
            checks[key + "_sha"] = path.is_file() and sha(path) == declaration["sha256"]
            require(checks[key + "_sha"] and checks[key + "_bytes"], f"input drift {key}")
            pf = pq.ParquetFile(path)
            required = (
                ACTIVE_COLS
                if role == "active_map"
                else (OBS_COLS if role == "observations" else list(SPEC_PROXY_COLUMNS))
            )
            checks[key + "_rows"] = pf.metadata.num_rows == declaration["rows"]
            checks[key + "_schema"] = set(required) <= set(pf.schema_arrow.names)
            require(checks[key + "_rows"] and checks[key + "_schema"], f"schema drift {key}")
            column = {
                "active_map": "effective_date",
                "observations": "trade_date",
                "specs": "session_date",
            }[role]
            dates = pd.to_datetime(pd.read_parquet(path, columns=[column])[column])
            checks[key + "_boundary"] = bool(
                dates.notna().all()
                and dates.lt(BOUNDARY).all()
                and dates.between(era["start"], era["end"]).all()
            )
            metadata[key] = {
                "path": declaration["path"],
                "sha256": declaration["sha256"],
                "rows": pf.metadata.num_rows,
                "minimum_date": str(dates.min().date()),
                "maximum_date": str(dates.max().date()),
            }
    require(all(checks.values()), "source preflight failed")
    return {"checks": checks, "inputs": metadata}


def calendar_signal(dates: pd.Series, shift: int) -> pd.DataFrame:
    require(shift in ARMS.values(), "undeclared control shift")
    dates = pd.to_datetime(dates, errors="raise")
    require(dates.notna().all() and dates.lt(BOUNDARY).all(), "invalid/protected signal date")
    anchors = (
        pd.Series(np.where(dates.lt(pd.Timestamp("2023-01-01")), 25, 28), index=dates.index) + shift
    )
    active = dates.dt.day.ge(anchors - 7) & dates.dt.day.lt(anchors)
    return pd.DataFrame(
        {
            "decision_date": dates,
            "anchor_day": anchors,
            "calendar_weight": np.where(active, -1.0, 0.0),
        }
    )


def build_targets(active: pd.DataFrame, shift: int) -> pd.DataFrame:
    """Price-free targets; admission uses only mapping, calendar and actual execution clock."""
    frame = active.loc[active["asset_code"].eq("SI"), ACTIVE_COLS].copy()
    for name in ("decision_date", "effective_date", "observed_through"):
        frame[name] = pd.to_datetime(frame[name], errors="raise")
    # A first source row has no predecessor; it is never a decision/entry.
    frame = (
        frame.loc[frame["decision_date"].notna()]
        .sort_values("effective_date")
        .reset_index(drop=True)
    )
    require(not frame.empty, "no SI map")
    require(frame["effective_date"].lt(BOUNDARY).all(), "protected effective date")
    require((frame["decision_date"] < frame["effective_date"]).all(), "noncausal fill")
    require((frame["observed_through"] <= frame["decision_date"]).all(), "future map")
    require(
        not frame.duplicated("decision_date").any()
        and not frame.duplicated("effective_date").any(),
        "duplicate SI map",
    )
    signal = calendar_signal(frame["decision_date"], shift)
    frame["anchor_day"] = signal["anchor_day"]
    frame["requested_weight"] = signal["calendar_weight"]
    tradable = frame["plan_tradable"].fillna(False).astype(bool) & frame["contract_id"].notna()
    stale = frame["effective_date"].dt.to_period("M") != frame["decision_date"].dt.to_period("M")
    stale |= frame["effective_date"].dt.day.gt(frame["anchor_day"])
    frame["source_unavailable"] = ~tradable & frame["requested_weight"].ne(0)
    frame["calendar_expired_at_fill"] = stale & frame["requested_weight"].ne(0)
    frame["target_weight"] = frame["requested_weight"].where(tradable & ~stale, 0.0)
    frame["terminal_flat"] = False
    frame.loc[frame.index[-1], ["target_weight", "terminal_flat"]] = [0.0, True]
    frame.loc[frame["target_weight"].eq(0), "contract_id"] = None
    frame["provenance"] = f"v64_fixed_calendar_shift_{shift}_price_free"
    return frame


def summarize(result: Any) -> dict[str, Any]:
    ledger, positions, orders = result.ledger, result.positions, result.orders
    dates = pd.to_datetime(ledger["session_date"])
    daily = ledger["ending_cash"].to_numpy() / ledger["starting_cash"].to_numpy() - 1
    annual = {
        str(year): float(np.prod(1 + daily[dates.dt.year.eq(year)]) - 1)
        for year in sorted(dates.dt.year.unique())
    }
    exposure = positions["contracts"].ne(0).reset_index(drop=True)
    entries = int((exposure & ~exposure.shift(1, fill_value=False)).sum())
    exits = int((~exposure & exposure.shift(1, fill_value=False)).sum())
    filled = orders.loc[orders["filled"]]
    paired_cost = filled["commission_cost"].sum() + filled["slippage_cost"].sum()
    require(np.isclose(paired_cost, result.metrics["total_cost"]), "order costs mismatch")
    require(
        np.isclose(
            ledger["variation_margin"].sum() - paired_cost, result.metrics["ending_cash"] - CAPITAL
        ),
        "cash accounting mismatch",
    )
    return {
        **result.metrics,
        "annual_returns": annual,
        "positive_years": sum(x > 0 for x in annual.values()),
        "year_segments": len(annual),
        "worst_year": min(annual.values()),
        "position_entries": entries,
        "round_trips": exits,
        "exposed_sessions": int(exposure.sum()),
        "sessions": len(ledger),
        "maximum_close_gross_leverage": float(ledger["gross_leverage"].max()),
        "gross_vm_pnl": float(ledger["variation_margin"].sum()),
        "net_pnl": float(result.metrics["ending_cash"] - CAPITAL),
        "turnover_multiple": float(result.metrics["order_notional"] / CAPITAL),
    }


def assess(metrics: dict[str, Any]) -> dict[str, Any]:
    require(set(metrics) == {"early", "middle", "recent"}, "missing declared era")
    for arms in metrics.values():
        require(set(arms) == set(ARMS), "missing declared arm")
        for scenarios in arms.values():
            require(set(scenarios) == set(SCENARIOS), "missing declared costs")
    checks = {}
    for era, arms in metrics.items():
        for arm, scenarios in arms.items():
            for name, value in scenarios.items():
                prefix = f"{era}_{arm}_{name}"
                checks[prefix + "_complete"] = bool(value["execution_complete"])
                checks[prefix + "_terminal_flat"] = not value["terminal_carried"]
        checks[era + "_trades"] = arms["tax"]["primary"]["round_trips"] >= 12
        tax = arms["tax"]["primary"]
        checks[era + "_positive_years"] = tax["positive_years"] / tax["year_segments"] >= 0.60
        for name in ("primary", "stress"):
            checks[f"{era}_{name}_positive"] = arms["tax"][name]["total_return"] > 0
            checks[f"{era}_{name}_beats_control"] = (
                arms["tax"][name]["cagr"] > arms["control"][name]["cagr"]
            )
    valid = all(v for k, v in checks.items() if k.endswith(("_complete", "_terminal_flat")))
    passed = all(checks.values())
    return {
        "checks": checks,
        "verdict": "GO_TO_NEW_FORWARD_VALIDATION"
        if passed
        else ("NO_GO" if valid else "INVALID_EXECUTION_NO_PROMOTION"),
        "goal_20_supported_all_eras": valid
        and all(v["tax"]["stress"]["cagr"] >= 0.20 for v in metrics.values()),
        "goal_50_supported_all_eras": valid
        and all(v["tax"]["stress"]["cagr"] >= 0.50 for v in metrics.values()),
        "independent_holdout": False,
        "live_trading_allowed": False,
    }


def run(cfg: dict[str, Any], storage: Path, expected_seal: str) -> Path:
    require(os.name == "posix", "historical economics must run on gpu-mlserver")
    output = safe(storage, f"runs/v64_si_tax_calendar_v1_{expected_seal[:12]}")
    require(not output.exists(), "canonical output already exists; never rerun/overwrite")
    verified = preflight(cfg, storage)
    specs = declarations(cfg)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "started.json", {"seal_sha256": expected_seal, "host": platform.node()})
    write_json(output / "source_preflight.json", verified)
    metrics, counts = {}, {}
    for era in cfg["eras"]:
        source = specs[era["id"]]
        active = pd.read_parquet(safe(storage, source["active_map"]["path"]), columns=ACTIVE_COLS)
        obs = pd.read_parquet(safe(storage, source["observations"]["path"]), columns=OBS_COLS)
        sp = pd.read_parquet(
            safe(storage, source["specs"]["path"]), columns=sorted(SPEC_PROXY_COLUMNS)
        )
        obs = obs.loc[obs["logical_asset"].eq("SI")].rename(
            columns={
                "trade_date": "session_date",
                "logical_asset": "asset_code",
                "canonical_contract_id": "contract_id",
            }
        )
        sp = sp.loc[sp["asset_symbol"].eq("SI")]
        market = build_portfolio_market(obs, sp)
        require(pd.to_datetime(market["session_date"]).lt(BOUNDARY).all(), "protected market")
        metrics[era["id"]], counts[era["id"]] = {}, {}
        for arm, shift in ARMS.items():
            targets = build_targets(active, shift)
            end = targets["effective_date"].max()
            execution_market = market.loc[pd.to_datetime(market["session_date"]).le(end)].copy()
            prefix = f"{era['id']}_{arm}"
            targets.to_parquet(output / f"targets_{prefix}.parquet", index=False)
            counts[era["id"]][arm] = {
                "decisions": len(targets),
                "nonzero_targets": int(targets["target_weight"].ne(0).sum()),
                "source_unavailable": int(targets["source_unavailable"].sum()),
                "calendar_expired": int(targets["calendar_expired_at_fill"].sum()),
            }
            metrics[era["id"]][arm] = {}
            for name, (ticks, fee) in SCENARIOS.items():
                result = run_futures_portfolio_ledger(
                    execution_market,
                    targets,
                    FuturesPortfolioLedgerConfig(
                        initial_cash=CAPITAL,
                        expected_assets=("SI",),
                        slippage_ticks=ticks,
                        fee_multiplier=fee,
                        execution_atomicity="asset",
                        unexecutable_target_policy="cancel_and_clip",
                    ),
                )
                metrics[era["id"]][arm][name] = summarize(result)
                for kind in ("ledger", "orders", "positions"):
                    getattr(result, kind).to_parquet(
                        output / f"{kind}_{prefix}_{name}.parquet", index=False
                    )
                print(f"completed {prefix}_{name}", flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected_seal,
        "config_sha256": sha(CONFIG),
        "metrics": metrics,
        "counts": counts,
        "assessment": assess(metrics),
        "limitations": cfg["limitations"],
    }
    write_json(output / "metrics.json", payload)
    lines = [
        "# V64 SI tax-calendar screen",
        "",
        payload["assessment"]["verdict"],
        "",
        "Already-open development; separate capital per era, not one bridged NAV.",
        "",
        "| Era | Arm | Costs | CAGR | Sharpe | MDD | Round trips | Complete |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for era, arms in metrics.items():
        for arm, scenarios in arms.items():
            for name, m in scenarios.items():
                lines.append(
                    f"| {era} | {arm} | {name} | {m['cagr']:.4%} | {m['sharpe']:.3f} | "
                    f"{m['maximum_drawdown']:.4%} | {m['round_trips']} | "
                    f"{m['execution_complete']} |"
                )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    files = {
        p.name: {"sha256": sha(p), "bytes": p.stat().st_size}
        for p in sorted(output.iterdir())
        if p.is_file()
    }
    write_json(
        output / "identity.json",
        {
            "seal_sha256": expected_seal,
            "files": files,
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    )
    return output


def audit(output: Path) -> dict[str, bool]:
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    checks = {"run_seal_identity": identity["seal_sha256"] == sha(SEAL)}
    for name, declaration in identity["files"].items():
        path = safe(output, name)
        checks[name + "_identity"] = (
            path.stat().st_size == declaration["bytes"] and sha(path) == declaration["sha256"]
        )
    require(all(checks.values()), "artifact identity mismatch")
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    for era, arms in payload["metrics"].items():
        for arm, scenarios in arms.items():
            for name, m in scenarios.items():
                prefix = f"{era}_{arm}_{name}"
                ledger = pd.read_parquet(output / f"ledger_{prefix}.parquet")
                values = _performance_metrics(
                    ledger["ending_cash"], ledger["session_date"], CAPITAL
                )
                checks[prefix + "_dates"] = bool(
                    pd.to_datetime(ledger["session_date"]).lt(BOUNDARY).all()
                )
                for metric, value in values.items():
                    checks[prefix + "_" + metric] = bool(
                        np.isclose(value, m[metric], rtol=1e-10, atol=1e-10)
                    )
    checks["assessment_replay"] = assess(payload["metrics"]) == payload["assessment"]
    require(all(checks.values()), "metric replay failed")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg = load_config(args.seal_sha)
    if args.audit:
        checks = audit(args.audit)
        print(json.dumps({"checks": len(checks), "all_true": all(checks.values())}))
    elif args.preflight_only:
        print(json.dumps(preflight(cfg, args.storage_root), indent=2))
    else:
        print(run(cfg, args.storage_root, args.seal_sha))


if __name__ == "__main__":
    main()
